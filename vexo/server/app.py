"""FastAPI routes, token auth, public projections and the static phone/operator pages.

Run: .venv/bin/python -m uvicorn --factory server.app:serve --host 127.0.0.1 --port 8080
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as config_mod
from . import eligibility, lifecycle, presence, profiler
from .config import PALETTE_NAMES, Config
from .db import Database, dumps, hash_token, loads, new_id
from . import signal_api
from .linkedin_import import router as linkedin_import_router
from .schemas import (DatingStatus, DemoSighting, PreferencesEdit, ProfileEdit, Respond, Tick,
                      VoiceNote)
from .worker import Engine

UI = Path(__file__).resolve().parent.parent / "ui"
log = logging.getLogger("vexo.api")


def create_app(cfg: Config | None = None, db: Database | None = None, start_worker: bool = True) -> FastAPI:
    cfg = cfg or config_mod.load()
    db = db or Database(cfg.db_path)
    engine = Engine(db, cfg)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(engine.run_forever()) if start_worker else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Vexo Match", lifespan=lifespan)
    app.include_router(linkedin_import_router)
    app.state.db, app.state.cfg, app.state.engine = db, cfg, engine

    # ------------------------------------------------------------ auth

    def principal(request: Request) -> dict:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        row = db.one("SELECT * FROM tokens WHERE token_hash = ?", (hash_token(header[7:].strip()),))
        if row is None:
            raise HTTPException(401, "unknown token")
        return dict(row)

    def user(p: dict = Depends(principal)) -> str:
        if p["kind"] != "user":
            raise HTTPException(403, "user token required")
        return p["user_id"]

    def hub(p: dict = Depends(principal)) -> dict:
        if p["kind"] != "hub":
            raise HTTPException(403, "hub token required")
        return p

    def operator(p: dict = Depends(principal)) -> dict:
        if p["kind"] != "operator":
            raise HTTPException(403, "operator token required")
        return p

    def guard(fn):
        """Map domain errors to HTTP codes."""
        try:
            return fn()
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    # ------------------------------------------------------------ projections

    def public_profile(conn, uid: str) -> dict:
        u = conn.execute("SELECT display_name FROM users WHERE id = ?", (uid,)).fetchone()
        p = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()
        return {"display_name": u["display_name"], "summary": p["summary"], "interests": loads(p["interests"]),
                "values": loads(p["personal_values"]), "goal": p["goal"]}

    def project_match(conn, m, uid: str, now: float) -> dict:
        s = lifecycle.side(m, uid)
        out = {"id": m["id"], "state": m["state"], "version": m["version"],
               "seconds_left": None if m["deadline"] is None else max(0, round(m["deadline"] - now)),
               "you_accepted": bool(m[f"{s}_accepted"]), "you_tapped": bool(m[f"{s}_tapped"])}
        if m["state"] == "SUGGESTED":
            out["headline"] = "Someone compatible is nearby"
            out["detail"] = "Accept to see who it is. They only see you if you both accept."
        if m["state"] in ("ACCEPTED", "LIGHTING", "LIT", "MET"):
            out["counterpart"] = public_profile(conn, lifecycle.other(m, uid))
            out["shared"] = loads(m["shared"]) or []
            out["icebreaker"] = m["icebreaker"]
            out["color"] = m["color"]
            out["color_name"] = PALETTE_NAMES.get(m["color"]) if m["color"] else None
            out["scorer"] = m["scorer"]
            out["evidence"] = m["evidence"]
            if m["state"] in ("LIGHTING", "LIT", "MET"):
                out["proximity_note"] = "Proximity last confirmed before lighting"
                out["lighting_session_id"] = m["lighting_session_id"]
            if m["met_via"] == "app_fallback":
                out["met_note"] = "Confirmed in the app (band tap fallback)"
        return out

    # ------------------------------------------------------------ me

    @app.get("/api/me")
    def me(uid: str = Depends(user)):
        now = db.now()
        with db.lock:
            conn = db.conn
            u = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
            p = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()
            pref = conn.execute("SELECT * FROM preferences WHERE user_id = ?", (uid,)).fetchone()
            band = lifecycle.band_of(conn, uid)
            h = conn.execute("SELECT * FROM hub_sessions WHERE user_id = ?", (uid,)).fetchone()
            return {
                "id": uid, "display_name": u["display_name"], "dating_status": u["dating_status"],
                "status_version": u["status_version"], "age": eligibility.age_on(u["date_of_birth"], now),
                "gender": u["gender"],
                "profile": {"version": p["version"], "approved": bool(p["approved"]), "summary": p["summary"],
                            "interests": loads(p["interests"]), "values": loads(p["personal_values"]),
                            "goal": p["goal"], "complete": eligibility.profile_complete(p)} if p else None,
                "preferences": {"version": pref["version"], "genders": loads(pref["genders"]),
                                "age_min": pref["age_min"], "age_max": pref["age_max"],
                                "accepted_goals": loads(pref["accepted_goals"])} if pref else None,
                "band_number": band["number"] if band else None,
                "hub": None if h is None else {
                    "online": now - h["last_tick"] <= cfg.deadlines.hub_lost_s, "band_state": h["band_state"],
                    "seconds_since_tick": round(now - h["last_tick"], 1), "battery": h["battery"]},
                "demo_mode": cfg.demo_mode,
            }

    @app.patch("/api/me/profile")
    def edit_profile(body: ProfileEdit, uid: str = Depends(user)):
        now = db.now()
        with db.tx() as conn:
            p = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()
            if p is None or p["version"] != body.expected_version:
                raise HTTPException(409, "profile changed since you loaded it")
            _write_profile(conn, uid, p, {k: v for k, v in body.model_dump().items()
                                          if k != "expected_version" and v is not None}, now)
        return {"ok": True}

    def _write_profile(conn, uid: str, p, changes: dict, now: float) -> None:
        conn.execute(
            "UPDATE profiles SET summary = ?, interests = ?, personal_values = ?, goal = ?, approved = 1,"
            " version = version + 1, updated_at = ? WHERE user_id = ?",
            (changes.get("summary", p["summary"]), dumps(changes.get("interests", loads(p["interests"]))),
             dumps(changes.get("values", loads(p["personal_values"]))), changes.get("goal", p["goal"]), now, uid))
        conn.execute("UPDATE profile_proposals SET state = 'stale' WHERE user_id = ? AND state = 'pending'"
                     " AND base_version < ?", (uid, p["version"] + 1))
        lifecycle.end_for_user(conn, uid, "profile_changed", now, cfg)

    @app.patch("/api/me/preferences")
    def edit_preferences(body: PreferencesEdit, uid: str = Depends(user)):
        now = db.now()
        with db.tx() as conn:
            pref = conn.execute("SELECT * FROM preferences WHERE user_id = ?", (uid,)).fetchone()
            if pref is None or pref["version"] != body.expected_version:
                raise HTTPException(409, "preferences changed since you loaded them")
            new = {"genders": body.genders if body.genders is not None else loads(pref["genders"]),
                   "age_min": body.age_min or pref["age_min"], "age_max": body.age_max or pref["age_max"],
                   "accepted_goals": body.accepted_goals if body.accepted_goals is not None
                   else loads(pref["accepted_goals"])}
            if new["age_max"] < new["age_min"]:
                raise HTTPException(422, "age_max must be at least age_min")
            conn.execute("UPDATE preferences SET genders = ?, age_min = ?, age_max = ?, accepted_goals = ?,"
                         " version = version + 1 WHERE user_id = ?",
                         (dumps(new["genders"]), new["age_min"], new["age_max"], dumps(new["accepted_goals"]), uid))
            lifecycle.end_for_user(conn, uid, "preferences_changed", now, cfg)
        return {"ok": True}

    @app.put("/api/me/dating-status")
    def dating_status(body: DatingStatus, uid: str = Depends(user)):
        now = db.now()
        with db.tx() as conn:
            u = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
            if u["status_version"] != body.expected_version:
                raise HTTPException(409, "status changed since you loaded it")
            conn.execute("UPDATE users SET dating_status = ?, status_version = status_version + 1 WHERE id = ?",
                         (body.status, uid))
            if body.status == "paused":
                lifecycle.end_for_user(conn, uid, "paused", now, cfg)
            lifecycle.reset_owner_device(conn, uid, now)
        return {"ok": True, "dating_status": body.status}

    # ------------------------------------------------------------ matches

    @app.get("/api/me/match")
    def my_match(uid: str = Depends(user)):
        now = db.now()
        with db.lock:
            conn = db.conn
            row = conn.execute("SELECT match_id FROM active_members WHERE user_id = ?", (uid,)).fetchone()
            if row is None:
                return {"match": None}
            return {"match": project_match(conn, lifecycle.get_match(conn, row["match_id"]), uid, now)}

    @app.post("/api/matches/{match_id}/respond")
    def respond(match_id: str, body: Respond, uid: str = Depends(user)):
        now = db.now()
        with db.tx() as conn:
            m = guard(lambda: lifecycle.respond(conn, match_id, uid, body.accept, now, cfg))
            return {"match": project_match(conn, m, uid, now) if m["state"] != "ENDED" else None}

    @app.post("/api/matches/{match_id}/cancel")
    def cancel(match_id: str, uid: str = Depends(user)):
        with db.tx() as conn:
            guard(lambda: lifecycle.cancel(conn, match_id, uid, db.now(), cfg))
        return {"ok": True}

    @app.post("/api/matches/{match_id}/block")
    def block(match_id: str, uid: str = Depends(user)):
        """Block the other person in this match. Their id is never exposed to the client."""
        now = db.now()
        with db.tx() as conn:
            m = lifecycle.get_match(conn, match_id)
            if m is None:
                raise HTTPException(404, "no such match")
            target = guard(lambda: lifecycle.other(m, uid))
            conn.execute("INSERT OR IGNORE INTO blocks (blocker_id, blocked_id, created_at) VALUES (?,?,?)",
                         (uid, target, now))
            if m["state"] != "ENDED":
                lifecycle.end(conn, m, "blocked", now, cfg)
        return {"ok": True}

    @app.post("/api/matches/{match_id}/confirm-met")
    def confirm_met(match_id: str, uid: str = Depends(user)):
        """Labelled fallback when the band's tap event does not arrive."""
        now = db.now()
        with db.tx() as conn:
            m = lifecycle.get_match(conn, match_id)
            if m is None or m["state"] != "LIT":
                raise HTTPException(409, "lights are not on for this match")
            band = lifecycle.band_of(conn, uid)
            ok = guard(lambda: lifecycle.record_tap(
                conn, uid, band["id"], {"event_id": new_id(), "match_id": match_id,
                                        "lighting_session_id": m["lighting_session_id"]}, now, cfg, via="app"))
        return {"ok": ok}

    # ------------------------------------------------------------ notifications

    @app.get("/api/me/notifications")
    def notifications(after: int = 0, uid: str = Depends(user)):
        rows = db.read("SELECT * FROM notifications WHERE recipient = ? AND seq > ? ORDER BY seq LIMIT 50",
                       (uid, after))
        return {"items": [{"id": r["id"], "seq": r["seq"], "kind": r["kind"], "match_id": r["match_id"],
                           "read": bool(r["read"]), "created_at": r["created_at"], **loads(r["payload"])}
                          for r in rows],
                "cursor": rows[-1]["seq"] if rows else after}

    @app.post("/api/notifications/{notification_id}/read")
    def mark_read(notification_id: str, uid: str = Depends(user)):
        with db.tx() as conn:
            cur = conn.execute("UPDATE notifications SET read = 1 WHERE id = ? AND recipient = ?",
                               (notification_id, uid))
            if cur.rowcount == 0:
                raise HTTPException(404, "no such notification")
        return {"ok": True}

    # ------------------------------------------------------------ voice notes and proposals

    @app.post("/api/me/voice-notes")
    def add_note(body: VoiceNote, uid: str = Depends(user)):
        now = db.now()
        with db.tx() as conn:
            conn.execute("INSERT INTO voice_notes (id, user_id, transcript, source, created_at) VALUES (?,?,?,?,?)",
                         (new_id(), uid, body.transcript, body.source, now))
            notes = [r["transcript"] for r in conn.execute(
                "SELECT transcript FROM voice_notes WHERE user_id = ? AND deleted_at IS NULL"
                " ORDER BY created_at DESC LIMIT 20", (uid,))][::-1]
            p = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()
            current = {"summary": p["summary"], "interests": loads(p["interests"]),
                       "values": loads(p["personal_values"]), "goal": p["goal"]}
            base = p["version"]
        changes, provider = profiler.propose(notes, current, cfg.scorer)   # outside the transaction
        proposal_id = new_id()
        with db.tx() as conn:
            conn.execute("INSERT INTO profile_proposals (id, user_id, base_version, changes, state, provider,"
                         " created_at) VALUES (?,?,?,?, 'pending', ?, ?)",
                         (proposal_id, uid, base, dumps(changes), provider, db.now()))
        return {"proposal_id": proposal_id, "changes": changes, "provider": provider}

    @app.get("/api/me/profile-proposals")
    def proposals(uid: str = Depends(user)):
        rows = db.read("SELECT * FROM profile_proposals WHERE user_id = ? AND state = 'pending'"
                       " ORDER BY created_at DESC", (uid,))
        return {"items": [{"id": r["id"], "base_version": r["base_version"], "changes": loads(r["changes"]),
                           "provider": r["provider"]} for r in rows]}

    @app.post("/api/me/profile-proposals/{proposal_id}/{decision}")
    def decide_proposal(proposal_id: str, decision: str, uid: str = Depends(user)):
        if decision not in ("accept", "reject"):
            raise HTTPException(404, "unknown decision")
        now = db.now()
        with db.tx() as conn:
            pr = conn.execute("SELECT * FROM profile_proposals WHERE id = ? AND user_id = ?",
                              (proposal_id, uid)).fetchone()
            if pr is None or pr["state"] != "pending":
                raise HTTPException(404, "no pending proposal")
            if decision == "reject":
                conn.execute("UPDATE profile_proposals SET state = 'rejected' WHERE id = ?", (proposal_id,))
                return {"ok": True}
            p = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()
            if p["version"] != pr["base_version"]:
                conn.execute("UPDATE profile_proposals SET state = 'stale' WHERE id = ?", (proposal_id,))
                raise HTTPException(409, "profile changed after this proposal; it is now stale")
            conn.execute("UPDATE profile_proposals SET state = 'accepted' WHERE id = ?", (proposal_id,))
            _write_profile(conn, uid, p, loads(pr["changes"]), now)
        return {"ok": True}

    # ------------------------------------------------------------ hub tick

    @app.post("/api/hub/tick")
    def tick(body: Tick, h: dict = Depends(hub)):
        now = db.now()
        with db.tx() as conn:
            band = conn.execute("SELECT * FROM bands WHERE hub_id = ?", (h["hub_id"],)).fetchone()
            if band is None:
                raise HTTPException(403, "hub is not enrolled to a band")
            uid = band["user_id"]
            sess = conn.execute("SELECT * FROM hub_sessions WHERE hub_id = ?", (h["hub_id"],)).fetchone()
            fresh = sess is None or sess["session_id"] != body.session_id or body.seq > sess["last_seq"]
            if fresh:
                conn.execute(
                    "INSERT INTO hub_sessions (hub_id, user_id, band_id, session_id, last_seq, last_tick, band_state,"
                    " mic_active, battery) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(hub_id) DO UPDATE SET"
                    " session_id = excluded.session_id, last_seq = excluded.last_seq, last_tick = excluded.last_tick,"
                    " band_state = excluded.band_state, mic_active = excluded.mic_active, battery = excluded.battery",
                    (h["hub_id"], uid, band["id"], body.session_id, body.seq, now, body.band.state,
                     int(body.band.mic_active), body.band.battery))
                roster = set(cfg.roster) if cfg.roster else None
                for o in body.observations:
                    if o.target_band_number == band["number"]:
                        continue                                 # never our own band
                    if roster is not None and o.target_band_number not in roster:
                        continue
                    target = conn.execute("SELECT id FROM bands WHERE number = ?",
                                          (o.target_band_number,)).fetchone()
                    if target is None:
                        continue                                 # not an enrolled participant
                    presence.record(conn, cfg.rssi, observer_id=uid, target_band_id=target["id"],
                                    source=o.source, source_session=body.session_id, sequence=o.sequence,
                                    rssi=o.rssi_dbm, samples=o.samples, sample_age_ms=o.sample_age_ms, receipt=now)
            for a in body.acks:
                lifecycle.record_ack(conn, band["id"], a.model_dump(), now, cfg)
            tap_acks = []
            for t in body.taps:
                lifecycle.record_tap(conn, uid, band["id"], t.model_dump(), now, cfg)
                tap_acks.append(t.event_id)
            d = conn.execute("SELECT * FROM device_desired WHERE band_id = ?", (band["id"],)).fetchone()
            if d is None:
                d = lifecycle.set_desired(conn, band["id"], lifecycle.owner_mode(conn, uid), now)
            desired = {"command_id": d["command_id"], "desired_version": d["version"], "match_id": d["match_id"],
                       "lighting_session_id": d["lighting_session_id"], "mode": d["mode"], "color": d["color"],
                       "pattern": d["pattern"], "brightness": d["brightness"],
                       "valid_for_ms": cfg.deadlines.command_lease_ms}
            return {"server_time": now, "accepted_seq": body.seq, "duplicate": not fresh, "desired": desired,
                    "tap_acks": tap_acks, "ack_ids": [a.command_id for a in body.acks],
                    "roster": sorted(cfg.roster), "next_poll_ms": 1000}

    # ------------------------------------------------------------ operator (demo only)

    @app.post("/api/demo/sightings")
    def demo_sighting(body: DemoSighting, _op: dict = Depends(operator)):
        if body.source not in cfg.allowed_sources:
            raise HTTPException(409, f"{body.source} sightings are not accepted in {cfg.demo_mode} mode")
        now = db.now()
        with db.tx() as conn:
            obs = conn.execute("SELECT * FROM bands WHERE number = ?", (body.observer_band,)).fetchone()
            tgt = conn.execute("SELECT * FROM bands WHERE number = ?", (body.target_band,)).fetchone()
            if obs is None or tgt is None or obs["id"] == tgt["id"]:
                raise HTTPException(404, "both bands must be enrolled and different")
            result = presence.record(conn, cfg.rssi, observer_id=obs["user_id"], target_band_id=tgt["id"],
                                     source=body.source, source_session="operator", sequence=int(now * 1000),
                                     rssi=body.rssi_dbm, samples=body.samples, sample_age_ms=0, receipt=now)
            row = conn.execute("SELECT zone FROM sightings WHERE observer_id = ? AND target_band_id = ?",
                               (obs["user_id"], tgt["id"])).fetchone()
        return {"result": result, "zone": row["zone"] if row else None}

    @app.post("/api/demo/confirm-close/{match_id}")
    def demo_confirm_close(match_id: str, _op: dict = Depends(operator)):
        with db.tx() as conn:
            guard(lambda: lifecycle.operator_confirm_close(conn, match_id, db.now()))
        return {"ok": True, "evidence": "operator"}

    @app.post("/api/demo/reset")
    def demo_reset(_op: dict = Depends(operator)):
        now = db.now()
        with db.tx() as conn:
            for m in conn.execute(f"SELECT * FROM matches WHERE state IN {lifecycle.ACTIVE}").fetchall():
                lifecycle.end(conn, m, "reset", now, cfg)
            conn.execute("UPDATE matches SET job_id = NULL")       # detach before deleting jobs (FK)
            for table in ("sightings", "pair_cooldowns", "notifications", "score_jobs", "tap_events"):
                conn.execute(f"DELETE FROM {table}")
        return {"ok": True}

    @app.get("/api/demo/state")
    def demo_state(_op: dict = Depends(operator)):
        now = db.now()
        with db.lock:
            conn = db.conn
            users = {u["id"]: dict(u) for u in conn.execute("SELECT * FROM users")}
            bands = {b["id"]: dict(b) for b in conn.execute("SELECT * FROM bands")}
            name = {uid: u["display_name"] for uid, u in users.items()}
            num = {b["user_id"]: b["number"] for b in bands.values()}
            return {
                "now": now, "demo_mode": cfg.demo_mode, "scorer": cfg.scorer.provider,
                "users": [{"name": u["display_name"], "band": num.get(uid), "status": u["dating_status"],
                           "active_match": (conn.execute("SELECT match_id FROM active_members WHERE user_id = ?",
                                                         (uid,)).fetchone() or {"match_id": None})["match_id"]}
                          for uid, u in users.items()],
                "hubs": [{"user": name[h["user_id"]], "band_state": h["band_state"],
                          "online": now - h["last_tick"] <= cfg.deadlines.hub_lost_s,
                          "seconds_since_tick": round(now - h["last_tick"], 1), "battery": h["battery"]}
                         for h in conn.execute("SELECT * FROM hub_sessions")],
                "sightings": [{"observer": name[s["observer_id"]], "target": name[bands[s["target_band_id"]]["user_id"]],
                               "source": s["source"], "rssi": round(s["rssi"], 1),
                               "zone": presence.effective_zone(s, now, cfg.rssi), "candidate": s["candidate"],
                               "age_s": round(now - s["last_sample_at"], 1)}
                              for s in conn.execute("SELECT * FROM sightings")],
                "matches": [{"id": m["id"], "pair": [name[m["user_low"]], name[m["user_high"]]], "state": m["state"],
                             "score": m["score"], "scorer": m["scorer"], "private_reasons": loads(m["reasons"]),
                             "color": m["color"], "evidence": m["evidence"], "attempts": m["lighting_attempts"],
                             "end_reason": m["end_reason"], "met_via": m["met_via"],
                             "seconds_left": None if m["deadline"] is None else round(m["deadline"] - now, 1)}
                            for m in conn.execute("SELECT * FROM matches ORDER BY created_at DESC LIMIT 10")],
                "devices": [{"band": bands[d["band_id"]]["number"], "mode": d["mode"], "version": d["version"],
                             "color": d["color"], "cleanup_for": (d["cleanup_for"] or "")[:8],
                             "ack": (conn.execute("SELECT status FROM device_acks WHERE command_id = ? AND band_id = ?",
                                                  (d["command_id"], d["band_id"])).fetchone() or {"status": None})["status"]}
                            for d in conn.execute("SELECT * FROM device_desired")],
                "color_leases": [dict(c) for c in conn.execute("SELECT * FROM color_leases")],
            }

    # ------------------------------------------------------------ static pages

    signal_api.register(app)

    @app.get("/respond")
    def respond_page():
        return FileResponse(UI / "respond.html")

    @app.get("/connect")
    def connect_page():
        return FileResponse(UI / "respond.html")

    @app.get("/")
    def phone_page():
        return FileResponse(UI / "phone.html")

    @app.get("/operator")
    def operator_page():
        return FileResponse(UI / "operator.html")

    app.mount("/ui", StaticFiles(directory=UI), name="ui")
    return app


def serve() -> FastAPI:
    """Entry point for `uvicorn --factory server.app:serve`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return create_app()
