"""Every match transition, reservation, colour lease and device command lives here.

All functions take an open transaction (`conn` from Database.tx()) and never touch the
network. States: SCORING -> SUGGESTED -> ACCEPTED -> LIGHTING -> LIT -> MET -> ENDED.
See IMPLEMENTATION_PLAN.md sections 8-10.
"""
from __future__ import annotations

import logging

from . import eligibility, matcher, presence
from .config import MET_COLOR, PALETTE, PALETTE_NAMES, Config
from .db import dumps, loads, new_id

log = logging.getLogger("vexo.lifecycle")

ACTIVE = ("SCORING", "SUGGESTED", "ACCEPTED", "LIGHTING", "LIT", "MET")
DEVICE_STATES = ("LIGHTING", "LIT", "MET")         # states that may have lit a band


# ---------------------------------------------------------------- small helpers

def get_match(conn, match_id: str):
    return conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()


def band_of(conn, user_id: str):
    return conn.execute("SELECT * FROM bands WHERE user_id = ?", (user_id,)).fetchone()


def side(m, user_id: str) -> str:
    if user_id == m["user_low"]:
        return "low"
    if user_id == m["user_high"]:
        return "high"
    raise PermissionError("not a member of this match")


def other(m, user_id: str) -> str:
    return m["user_high"] if side(m, user_id) == "low" else m["user_low"]


def _transition(conn, m, to_state: str, reason: str, now: float, **fields) -> None:
    fields.update(state=to_state, updated_at=now)
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE matches SET {sets}, version = version + 1 WHERE id = ?",
                 (*fields.values(), m["id"]))
    conn.execute("INSERT INTO transitions (match_id, from_state, to_state, reason, at) VALUES (?,?,?,?,?)",
                 (m["id"], m["state"], to_state, reason, now))
    log.info("match %s %s -> %s (%s)", m["id"][:8], m["state"], to_state, reason)


def notify(conn, recipient: str, match_id: str, kind: str, title: str, body: str, now: float, **extra) -> None:
    """Durable inbox item; (recipient, match, kind) is unique so retries never duplicate."""
    conn.execute(
        "INSERT OR IGNORE INTO notifications (id, recipient, match_id, kind, payload, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (new_id(), recipient, match_id, kind, dumps({"title": title, "body": body, **extra}), now))


def owner_mode(conn, user_id: str) -> str:
    u = conn.execute("SELECT dating_status FROM users WHERE id = ?", (user_id,)).fetchone()
    return "BEACON" if u and u["dating_status"] == "open" else "IDLE"


def set_desired(conn, band_id: str, mode: str, now: float, *, match_id=None, session=None,
                color=None, pattern=None, brightness=None, cleanup_for=None) -> dict:
    """Write the band's desired state. A real change gets a new version and command id."""
    cur = conn.execute("SELECT * FROM device_desired WHERE band_id = ?", (band_id,)).fetchone()
    same = cur is not None and (cur["mode"], cur["match_id"], cur["lighting_session_id"], cur["color"],
                                cur["cleanup_for"]) == (mode, match_id, session, color, cleanup_for)
    if same:
        return dict(cur)
    version = (cur["version"] + 1) if cur else 1
    conn.execute(
        "INSERT INTO device_desired (band_id, version, command_id, match_id, lighting_session_id, mode,"
        " color, pattern, brightness, cleanup_for, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(band_id) DO UPDATE SET version = excluded.version, command_id = excluded.command_id,"
        " match_id = excluded.match_id, lighting_session_id = excluded.lighting_session_id,"
        " mode = excluded.mode, color = excluded.color, pattern = excluded.pattern,"
        " brightness = excluded.brightness, cleanup_for = excluded.cleanup_for,"
        " updated_at = excluded.updated_at",
        (band_id, version, new_id(), match_id, session, mode, color, pattern, brightness, cleanup_for, now))
    return dict(conn.execute("SELECT * FROM device_desired WHERE band_id = ?", (band_id,)).fetchone())


def reset_owner_device(conn, user_id: str, now: float) -> None:
    """Point the user's band at BEACON/IDLE unless a live match is driving it."""
    band = band_of(conn, user_id)
    if band is None:
        return
    active = conn.execute(
        "SELECT m.state FROM active_members a JOIN matches m ON m.id = a.match_id WHERE a.user_id = ?",
        (user_id,)).fetchone()
    if active and active["state"] in DEVICE_STATES:
        return
    cur = conn.execute("SELECT cleanup_for FROM device_desired WHERE band_id = ?", (band["id"],)).fetchone()
    set_desired(conn, band["id"], owner_mode(conn, user_id), now,
                cleanup_for=cur["cleanup_for"] if cur else None)


def _cooldown(conn, low: str, high: str, reason: str, until: float) -> None:
    conn.execute("INSERT INTO pair_cooldowns (user_low, user_high, reason, expires_at) VALUES (?,?,?,?)"
                 " ON CONFLICT(user_low, user_high) DO UPDATE SET reason = excluded.reason,"
                 " expires_at = MAX(expires_at, excluded.expires_at)", (low, high, reason, until))


LONG_COOLDOWN = {"declined", "cancelled", "met", "blocked"}
SHORT_COOLDOWN = {"suggestion_expired", "approach_expired", "lit_timeout", "device_failure",
                  "device_loss", "hub_lost", "scoring_unavailable", "scoring_timeout"}
ENDED_MESSAGES = {
    "declined": "This suggestion was closed.",
    "cancelled": "This match was cancelled.",
    "met": "You met. Discovery resumes if you stay open.",
    "suggestion_expired": "The suggestion expired.",
    "approach_expired": "Time ran out before you found each other.",
    "lit_timeout": "The lights timed out.",
}


def end(conn, m, reason: str, now: float, cfg: Config) -> None:
    """Terminate a match: release members, clean devices, quarantine its colour, set cooldown."""
    if m["state"] == "ENDED":
        return
    d = cfg.deadlines
    _transition(conn, m, "ENDED", reason, now, end_reason=reason, deadline=None)
    conn.execute("DELETE FROM active_members WHERE match_id = ?", (m["id"],))
    touched_devices = m["state"] in DEVICE_STATES or m["lighting_attempts"] > 0
    if touched_devices:
        for uid in (m["user_low"], m["user_high"]):
            band = band_of(conn, uid)
            set_desired(conn, band["id"], owner_mode(conn, uid), now, cleanup_for=m["id"])
        # quarantine: free once both cleanup acks arrive, or after every lease has expired
        conn.execute("UPDATE color_leases SET release_after = ? WHERE match_id = ?",
                     (now + d.command_lease_ms / 1000 + 1, m["id"]))
    else:
        conn.execute("DELETE FROM color_leases WHERE match_id = ?", (m["id"],))
    if reason in LONG_COOLDOWN:
        _cooldown(conn, m["user_low"], m["user_high"], reason, now + d.cooldown_long_s)
    elif reason in SHORT_COOLDOWN:
        _cooldown(conn, m["user_low"], m["user_high"], reason, now + d.cooldown_short_s)
    if m["state"] != "SCORING":
        body = ENDED_MESSAGES.get(reason, "This match ended.")
        for uid in (m["user_low"], m["user_high"]):
            notify(conn, uid, m["id"], "ended", "Match ended", body, now, reason_code=reason)


def end_for_user(conn, user_id: str, reason: str, now: float, cfg: Config) -> None:
    row = conn.execute("SELECT match_id FROM active_members WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        end(conn, get_match(conn, row["match_id"]), reason, now, cfg)


# ---------------------------------------------------------------- candidates and scoring

def _scoring_input(conn, user_id: str) -> dict:
    p = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    pref = conn.execute("SELECT * FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
    return {"summary": p["summary"], "interests": loads(p["interests"]), "values": loads(p["personal_values"]),
            "goal": p["goal"], "accepted_goals": loads(pref["accepted_goals"])}


def _versions(conn, low: str, high: str) -> tuple:
    def v(table, uid):
        return conn.execute(f"SELECT version FROM {table} WHERE user_id = ?", (uid,)).fetchone()["version"]
    return (v("profiles", low), v("profiles", high), v("preferences", low), v("preferences", high))


def nearby_pairs(conn, cfg: Config, now: float) -> list:
    """Pairs with fresh, stable NEAR-or-closer evidence from an allowed source, ranked."""
    rows = conn.execute(
        "SELECT s.observer_id, b.user_id AS target_id, s.last_sample_at, s.zone, s.source"
        " FROM sightings s JOIN bands b ON b.id = s.target_band_id").fetchall()
    best: dict = {}
    for r in rows:
        if r["observer_id"] == r["target_id"]:
            continue
        if not presence.counts_as_evidence(r, now, cfg.rssi, cfg.allowed_sources, "NEAR"):
            continue
        key = eligibility.pair(r["observer_id"], r["target_id"])
        best[key] = max(best.get(key, 0), r["last_sample_at"])
    return sorted(best, key=lambda k: (-best[k], k))


def evaluate_candidates(conn, cfg: Config, now: float) -> list:
    """Reserve and start scoring for eligible nearby pairs. Returns job ids needing a scorer."""
    to_score = []
    for low, high in nearby_pairs(conn, cfg, now):
        if conn.execute("SELECT 1 FROM active_members WHERE user_id IN (?, ?)", (low, high)).fetchone():
            continue
        if eligibility.check(conn, low, high, now, cfg.deadlines.hub_lost_s) is not None:
            continue
        versions = _versions(conn, low, high)
        key = matcher.cache_key(low, high, versions, cfg.scorer)
        job = conn.execute("SELECT * FROM score_jobs WHERE cache_key = ?", (key,)).fetchone()
        cached = None
        if job and job["state"] == "done" and now - job["finished_at"] <= cfg.deadlines.score_cache_s:
            cached = loads(job["result"])
            if cached["score"] < cached["threshold"]:
                continue                      # cached negative result: do not reserve again
        match_id = new_id()
        if job is None:
            job_id = new_id()
            conn.execute("INSERT INTO score_jobs (id, user_low, user_high, cache_key, state, created_at)"
                         " VALUES (?,?,?,?, 'pending', ?)", (job_id, low, high, key, now))
        else:
            job_id = job["id"]
            if cached is None and job["state"] in ("failed", "done"):
                conn.execute("UPDATE score_jobs SET state = 'pending', result = NULL, lease_until = NULL"
                             " WHERE id = ?", (job_id,))
        conn.execute(
            "INSERT INTO matches (id, user_low, user_high, state, job_id, low_profile_version,"
            " high_profile_version, low_pref_version, high_pref_version, deadline, created_at, updated_at)"
            " VALUES (?,?,?, 'SCORING', ?,?,?,?,?,?,?,?)",
            (match_id, low, high, job_id, *versions, now + cfg.deadlines.scoring_s, now, now))
        conn.execute("INSERT INTO active_members (user_id, match_id) VALUES (?, ?), (?, ?)",
                     (low, match_id, high, match_id))
        conn.execute("INSERT INTO transitions (match_id, from_state, to_state, reason, at)"
                     " VALUES (?, NULL, 'SCORING', 'eligible nearby pair reserved', ?)", (match_id, now))
        log.info("match %s reserved %s + %s", match_id[:8], low[:8], high[:8])
        if cached is not None:
            _apply_score(conn, get_match(conn, match_id), cached, now, cfg)
        else:
            to_score.append(job_id)
    return to_score


def claim_job(conn, job_id: str, now: float, cfg: Config):
    """Lease a pending job to one scorer. Returns (job, inputs) or None."""
    job = conn.execute("SELECT * FROM score_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None or job["state"] not in ("pending",):
        return None
    conn.execute("UPDATE score_jobs SET state = 'running', lease_until = ? WHERE id = ?",
                 (now + cfg.deadlines.scoring_s, job_id))
    return job, (_scoring_input(conn, job["user_low"]), _scoring_input(conn, job["user_high"]))


def finish_job(conn, job_id: str, result: dict | None, error: str | None, now: float, cfg: Config) -> None:
    """Store a scorer outcome and apply it to every SCORING match waiting on this job."""
    job = conn.execute("SELECT * FROM score_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None or job["state"] != "running":
        return                                   # lease lost: someone else owns it now
    if error is None:
        conn.execute("UPDATE score_jobs SET state = 'done', result = ?, finished_at = ? WHERE id = ?",
                     (dumps(result), now, job_id))
    else:
        conn.execute("UPDATE score_jobs SET state = 'failed', retries = retries + 1, finished_at = ?"
                     " WHERE id = ?", (now, job_id))
    for m in conn.execute("SELECT * FROM matches WHERE job_id = ? AND state = 'SCORING'", (job_id,)).fetchall():
        if error is not None:
            log.warning("scoring unavailable for %s: %s", m["id"][:8], error)
            end(conn, m, "scoring_unavailable", now, cfg)
        else:
            _apply_score(conn, m, result, now, cfg)


def _apply_score(conn, m, result: dict, now: float, cfg: Config) -> None:
    # revalidate: the world may have changed while the scorer ran
    if eligibility.check(conn, m["user_low"], m["user_high"], now, cfg.deadlines.hub_lost_s) is not None:
        end(conn, m, "stale_result", now, cfg)
        return
    if _versions(conn, m["user_low"], m["user_high"]) != (
            m["low_profile_version"], m["high_profile_version"], m["low_pref_version"], m["high_pref_version"]):
        end(conn, m, "stale_result", now, cfg)
        return
    if result["score"] < result["threshold"]:
        end(conn, m, "below_threshold", now, cfg)
        return
    _transition(conn, m, "SUGGESTED", "passing score", now, score=result["score"], scorer=result["scorer"],
                reasons=dumps(result["explanation"]), shared=dumps(result["shared"]),
                icebreaker=result["icebreaker"], deadline=now + cfg.deadlines.suggestion_s)
    for uid in (m["user_low"], m["user_high"]):
        notify(conn, uid, m["id"], "suggestion", "Someone compatible is nearby",
               "You may have a lot in common. Accept to see who it is.", now)


# ---------------------------------------------------------------- app actions

def respond(conn, match_id: str, user_id: str, accept: bool, now: float, cfg: Config):
    m = get_match(conn, match_id)
    if m is None:
        raise LookupError("no such match")
    s = side(m, user_id)
    if m["state"] != "SUGGESTED":
        if m["state"] in ("ACCEPTED", "LIGHTING", "LIT", "MET") and accept:
            return m                             # idempotent repeat of an accept
        raise ValueError(f"match is {m['state']}, not waiting for an answer")
    if not accept:
        end(conn, m, "declined", now, cfg)
        return get_match(conn, match_id)
    conn.execute(f"UPDATE matches SET {s}_accepted = 1, updated_at = ? WHERE id = ?", (now, match_id))
    m = get_match(conn, match_id)
    if m["low_accepted"] and m["high_accepted"]:
        _transition(conn, m, "ACCEPTED", "both accepted", now, deadline=now + cfg.deadlines.approach_s)
        m = get_match(conn, match_id)
        color = assign_color(conn, m)
        for uid in (m["user_low"], m["user_high"]):
            body = (f"Your colour is {PALETTE_NAMES[color]}. Walk toward each other." if color
                    else "Waiting for a free colour.")
            notify(conn, uid, m["id"], "accepted", "It's mutual", body, now)
    return get_match(conn, match_id)


def assign_color(conn, m) -> str | None:
    if m["color"]:
        return m["color"]
    taken = {r["color_hex"] for r in conn.execute("SELECT color_hex FROM color_leases")}
    for color in PALETTE:
        if color not in taken:
            conn.execute("INSERT INTO color_leases (color_hex, match_id, release_after) VALUES (?, ?, NULL)",
                         (color, m["id"]))
            conn.execute("UPDATE matches SET color = ? WHERE id = ?", (color, m["id"]))
            return color
    return None                                  # palette exhausted: stay ACCEPTED and wait


def cancel(conn, match_id: str, user_id: str, now: float, cfg: Config) -> None:
    m = get_match(conn, match_id)
    if m is None:
        raise LookupError("no such match")
    side(m, user_id)
    if m["state"] != "ENDED":
        end(conn, m, "cancelled", now, cfg)


def operator_confirm_close(conn, match_id: str, now: float) -> None:
    """Labelled fallback when reciprocal radio evidence is unreliable."""
    m = get_match(conn, match_id)
    if m is None or m["state"] != "ACCEPTED":
        raise ValueError("match is not waiting to light")
    conn.execute("UPDATE matches SET evidence = 'operator', updated_at = ? WHERE id = ?", (now, match_id))


# ---------------------------------------------------------------- devices

def _start_lighting(conn, m, evidence: str, now: float, cfg: Config) -> None:
    session = new_id()
    _transition(conn, m, "LIGHTING", f"close confirmed ({evidence})", now, lighting_session_id=session,
                lighting_attempts=m["lighting_attempts"] + 1, close_confirmed_at=now, evidence=evidence,
                low_tapped=0, high_tapped=0, deadline=now + cfg.deadlines.lighting_s)
    for uid in (m["user_low"], m["user_high"]):
        set_desired(conn, band_of(conn, uid)["id"], "LIT", now, match_id=m["id"], session=session,
                    color=m["color"], pattern="solid", brightness=0.6)
        notify(conn, uid, m["id"], "close", "They're right here",
               f"Look for {PALETTE_NAMES[m['color']]} on a wrist. Tap your band when you meet.", now)


def _lighting_failed(conn, m, reason: str, now: float, cfg: Config) -> None:
    for uid in (m["user_low"], m["user_high"]):
        set_desired(conn, band_of(conn, uid)["id"], owner_mode(conn, uid), now, cleanup_for=m["id"])
    if m["lighting_attempts"] >= cfg.deadlines.lighting_attempts:
        end(conn, m, "device_failure", now, cfg)
        return
    # back to ACCEPTED; fresh close evidence (newer than now) is required before a retry
    _transition(conn, m, "ACCEPTED", reason, now, lighting_session_id=None, close_required_after=now,
                evidence=None, deadline=now + cfg.deadlines.approach_s)


def _current_applied(conn, band_id: str):
    d = conn.execute("SELECT * FROM device_desired WHERE band_id = ?", (band_id,)).fetchone()
    if d is None:
        return None, False
    ack = conn.execute("SELECT status FROM device_acks WHERE command_id = ? AND band_id = ?",
                       (d["command_id"], band_id)).fetchone()
    return d, bool(ack and ack["status"] == "APPLIED")


def record_ack(conn, band_id: str, ack: dict, now: float, cfg: Config) -> None:
    """Hub reports what happened to a command. Stale acks are stored but change nothing."""
    conn.execute("INSERT OR IGNORE INTO device_acks (command_id, band_id, version, status, applied_at, error)"
                 " VALUES (?,?,?,?,?,?)", (ack["command_id"], band_id, ack["version"], ack["status"], now,
                                           ack.get("error")))
    d = conn.execute("SELECT * FROM device_desired WHERE band_id = ?", (band_id,)).fetchone()
    if d is None or d["command_id"] != ack["command_id"]:
        return                                   # superseded command: no effect
    if d["mode"] == "LIT" and d["match_id"]:
        m = get_match(conn, d["match_id"])
        if m is None or m["state"] != "LIGHTING" or m["lighting_session_id"] != d["lighting_session_id"]:
            return
        if ack["status"] != "APPLIED":
            _lighting_failed(conn, m, f"lighting {ack['status'].lower()}", now, cfg)
            return
        bands = [band_of(conn, uid)["id"] for uid in (m["user_low"], m["user_high"])]
        if all(_current_applied(conn, b)[1] and _current_applied(conn, b)[0]["lighting_session_id"]
               == m["lighting_session_id"] for b in bands):
            _transition(conn, m, "LIT", "both LED acknowledgments", now, deadline=now + cfg.deadlines.lit_s)
    elif d["cleanup_for"] and ack["status"] == "APPLIED":
        _maybe_release_color(conn, d["cleanup_for"])


def _maybe_release_color(conn, match_id: str) -> None:
    m = get_match(conn, match_id)
    if m is None or m["state"] != "ENDED":
        return
    for uid in (m["user_low"], m["user_high"]):
        d, applied = _current_applied(conn, band_of(conn, uid)["id"])
        if not (d and d["cleanup_for"] == match_id and applied):
            return
    conn.execute("DELETE FROM color_leases WHERE match_id = ?", (match_id,))


def record_tap(conn, user_id: str, band_id: str, event: dict, now: float, cfg: Config, via: str = "band") -> bool:
    """A tap counts only for the live lighting session on a band that applied that command."""
    if conn.execute("SELECT 1 FROM tap_events WHERE event_id = ?", (event["event_id"],)).fetchone():
        return False                             # duplicate delivery
    m = get_match(conn, event["match_id"])
    ok = (m is not None and m["state"] == "LIT" and m["lighting_session_id"] == event["lighting_session_id"]
          and user_id in (m["user_low"], m["user_high"]))
    if ok and via == "band":
        d, applied = _current_applied(conn, band_id)
        ok = bool(d and applied and d["mode"] == "LIT" and d["lighting_session_id"] == m["lighting_session_id"])
    conn.execute("INSERT INTO tap_events (event_id, match_id, lighting_session_id, user_id, accepted, received_at)"
                 " VALUES (?,?,?,?,?,?)", (event["event_id"], event["match_id"], event["lighting_session_id"],
                                           user_id, int(ok), now))
    if not ok:
        return False
    s = side(m, user_id)
    conn.execute(f"UPDATE matches SET {s}_tapped = 1, met_via = CASE WHEN ? = 'app' THEN 'app_fallback'"
                 " ELSE COALESCE(met_via, 'band_taps') END WHERE id = ?", (via, m["id"]))
    m = get_match(conn, m["id"])
    if m["low_tapped"] and m["high_tapped"]:
        _transition(conn, m, "MET", f"both taps ({m['met_via']})", now, deadline=now + cfg.deadlines.met_flash_s)
        for uid in (m["user_low"], m["user_high"]):
            set_desired(conn, band_of(conn, uid)["id"], "MET_FLASH", now, match_id=m["id"],
                        session=m["lighting_session_id"], color=MET_COLOR, pattern="blink", brightness=0.8)
            notify(conn, uid, m["id"], "met", "You met",
                   f"Icebreaker: {m['icebreaker'] or 'say hi'}", now)
    return True


# ---------------------------------------------------------------- periodic sweep

def _lighting_gate(conn, m, cfg: Config, now: float) -> str | None:
    """Evidence label if this ACCEPTED match may light now, else None."""
    for uid in (m["user_low"], m["user_high"]):
        if not eligibility.hub_ready(conn, uid, now, cfg.deadlines.hub_lost_s):
            return None
        if m["lighting_attempts"] > 0:
            # a retry waits until the failed attempt's cleanup is acknowledged on both bands
            d, applied = _current_applied(conn, band_of(conn, uid)["id"])
            if not (d and applied and d["mode"] in ("BEACON", "IDLE")):
                return None
    if m["evidence"] == "operator":
        return "operator"
    rows = [presence.direction(conn, m["user_low"], m["user_high"]),
            presence.direction(conn, m["user_high"], m["user_low"])]
    if not all(presence.counts_as_evidence(r, now, cfg.rssi, cfg.allowed_sources, "CLOSE",
                                           not_before=m["close_required_after"], within_s=cfg.rssi.fresh_close_s)
               for r in rows):
        return None
    sources = sorted({r["source"] for r in rows})
    if cfg.demo_mode == "single_laptop" and "real_beacon" not in sources:
        return None                              # a mirrored reading needs a real one behind it
    return "+".join(sources)


def sweep(conn, cfg: Config, now: float) -> list:
    """Deadlines, hub loss, colour retries, lighting gate, lease release, new candidates.
    Runs every 0.5 s from the worker even when nobody polls. Returns job ids to score."""
    d = cfg.deadlines
    for m in conn.execute(f"SELECT * FROM matches WHERE state IN {ACTIVE}").fetchall():
        m = get_match(conn, m["id"])
        if m["state"] == "ENDED":
            continue
        hubs_ok = all(eligibility.hub_ready(conn, uid, now, d.hub_lost_s) for uid in (m["user_low"], m["user_high"]))
        if m["state"] in ("ACCEPTED", "LIGHTING", "LIT", "MET") and not hubs_ok:
            if m["state"] == "MET":
                end(conn, m, "met", now, cfg)
            else:
                end(conn, m, "hub_lost", now, cfg)
            continue
        if m["state"] == "LIT" and not _devices_connected(conn, m):
            end(conn, m, "device_loss", now, cfg)
            continue
        if m["deadline"] is not None and now >= m["deadline"]:
            if m["state"] == "SCORING":
                end(conn, m, "scoring_timeout", now, cfg)
            elif m["state"] == "SUGGESTED":
                end(conn, m, "suggestion_expired", now, cfg)
            elif m["state"] == "ACCEPTED":
                end(conn, m, "approach_expired", now, cfg)
            elif m["state"] == "LIGHTING":
                _lighting_failed(conn, m, "lighting timeout", now, cfg)
            elif m["state"] == "LIT":
                end(conn, m, "lit_timeout", now, cfg)
            elif m["state"] == "MET":
                end(conn, m, "met", now, cfg)
            continue
        if m["state"] == "ACCEPTED":
            if not m["color"]:
                if assign_color(conn, m):
                    m = get_match(conn, m["id"])
                else:
                    continue
            evidence = _lighting_gate(conn, m, cfg, now)
            if evidence:
                _start_lighting(conn, m, evidence, now, cfg)

    conn.execute("DELETE FROM color_leases WHERE release_after IS NOT NULL AND release_after < ?", (now,))
    conn.execute("UPDATE score_jobs SET state = 'failed', finished_at = ? WHERE state = 'running'"
                 " AND lease_until < ?", (now, now))
    pending = evaluate_candidates(conn, cfg, now)
    # recover pending jobs whose matches still wait (e.g. after a restart)
    for r in conn.execute("SELECT DISTINCT j.id FROM score_jobs j JOIN matches m ON m.job_id = j.id"
                          " WHERE j.state = 'pending' AND m.state = 'SCORING'"):
        if r["id"] not in pending:
            pending.append(r["id"])
    return pending


def _devices_connected(conn, m) -> bool:
    for uid in (m["user_low"], m["user_high"]):
        h = conn.execute("SELECT band_state FROM hub_sessions WHERE user_id = ?", (uid,)).fetchone()
        if h is None or h["band_state"] != "connected":
            return False
    return True
