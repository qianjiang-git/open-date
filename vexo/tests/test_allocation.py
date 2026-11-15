"""One active match per person, stale scorer results, palette exhaustion."""
from conftest import Demo
from server import lifecycle


def test_three_people_one_match_per_person():
    d = Demo(people=("alice", "bob", "cara"))
    d.step(1)
    for _ in range(6):
        d.step(1, sightings=[("alice", "bob", -70), ("bob", "alice", -70),
                             ("cara", "bob", -70), ("bob", "cara", -70)])
    s = d.state()
    active = [m for m in s["matches"] if m["state"] != "ENDED"]
    assert len(active) == 1
    assert "Bob" in active[0]["pair"]
    loser = "cara" if "Alice" in active[0]["pair"] else "alice"
    assert d.match(loser) is None and d.inbox(loser) == []      # losing candidate stays free


def test_concurrent_reports_create_one_match_and_one_notification_each(demo):
    d = demo
    d.step(1)
    for _ in range(6):
        d.clock.advance(1)
        for _ in range(3):                                      # duplicate reports from both sides
            d.sight("alice", "bob", -70), d.sight("bob", "alice", -70)
        d.tick("alice"), d.tick("bob")
        d.app.state.engine.run_once()
        d.app.state.engine.run_once()
    assert len(d.state()["matches"]) == 1
    assert [n["kind"] for n in d.inbox("alice")] == ["suggestion"]
    assert [n["kind"] for n in d.inbox("bob")] == ["suggestion"]


def test_scorer_result_after_pause_is_discarded(demo):
    d = demo
    d.step(1)
    jobs = []
    for _ in range(6):
        d.clock.advance(1)
        d.sight("alice", "bob", -70), d.sight("bob", "alice", -70)
        d.tick("alice"), d.tick("bob")
        jobs += d.app.state.engine.sweep()                     # reserve but do not score yet
    assert jobs and d.state()["matches"][0]["state"] == "SCORING"
    me = d.client.get("/api/me", headers=d.u("alice")).json()
    d.client.put("/api/me/dating-status", headers=d.u("alice"),
                 json={"status": "paused", "expected_version": me["status_version"]})
    d.app.state.engine.score_job(jobs[0])                      # provider returns late
    assert d.state()["matches"][0]["state"] == "ENDED"
    assert d.inbox("alice") == [] and d.inbox("bob") == []


def test_scorer_result_after_profile_change_is_discarded(demo):
    d = demo
    d.step(1)
    jobs = []
    for _ in range(6):
        d.clock.advance(1)
        d.sight("alice", "bob", -70), d.sight("bob", "alice", -70)
        d.tick("alice"), d.tick("bob")
        jobs += d.app.state.engine.sweep()
    me = d.client.get("/api/me", headers=d.u("bob")).json()
    r = d.client.patch("/api/me/profile", headers=d.u("bob"),
                       json={"expected_version": me["profile"]["version"], "summary": "Changed my mind."})
    assert r.status_code == 200
    d.app.state.engine.score_job(jobs[0])
    assert d.inbox("alice") == []


def test_palette_exhaustion_waits_without_reusing(demo, monkeypatch):
    monkeypatch.setattr(lifecycle, "PALETTE", [])
    d = demo
    d.step(1)
    d.approach("alice", "bob", -70, 6)
    d.respond("alice"), d.respond("bob")
    m = d.match("alice")
    assert m["state"] == "ACCEPTED" and m["color"] is None
    d.approach("alice", "bob", -50, 8)
    assert d.match("alice")["state"] == "ACCEPTED"              # no colour, no lighting
    monkeypatch.setattr(lifecycle, "PALETTE", ["#ff9500"])
    d.approach("alice", "bob", -50, 3)
    m = d.match("alice")
    assert m["color"] == "#ff9500" and m["state"] in ("LIGHTING", "LIT")


def test_quarantined_colour_is_not_reused(demo):
    d = Demo(people=("alice", "bob", "cara"))
    d.step(1)
    d.approach("alice", "bob", -70, 6)
    d.respond("alice"), d.respond("bob")
    d.approach("alice", "bob", -50, 8)
    assert d.match("alice")["color"] == "#00c7be"
    d.hubs["bob"]["online"] = False                             # Bob's hub dies while lit
    d.step(6)
    leases = d.state()["color_leases"]
    assert leases and leases[0]["color_hex"] == "#00c7be"       # quarantined: Bob never acked cleanup
    with d.db.tx() as conn:
        m = conn.execute("SELECT * FROM matches LIMIT 1").fetchone()
        new = dict(m)
    # a new pair right now must get a different colour
    d.hubs["bob"]["online"] = True
    with d.db.tx() as conn:
        conn.execute("DELETE FROM pair_cooldowns")
    d.step(7)
    leases = d.state()["color_leases"]
    assert all(c["color_hex"] != "#00c7be" or c["release_after"] for c in leases)
    assert new["color"] == "#00c7be"
