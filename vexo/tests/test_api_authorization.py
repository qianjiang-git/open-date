"""Identity comes from the token; every role is confined to its own routes and data."""
from conftest import Demo


def test_missing_and_unknown_tokens(demo):
    assert demo.client.get("/api/me").status_code == 401
    assert demo.client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_roles_are_separated(demo):
    tick = {"session_id": "session-x", "seq": 1, "band": {"state": "advertising"}}
    assert demo.client.post("/api/hub/tick", json=tick, headers=demo.u("alice")).status_code == 403
    assert demo.client.get("/api/me", headers=demo.h("alice")).status_code == 403
    assert demo.client.get("/api/demo/state", headers=demo.u("alice")).status_code == 403
    assert demo.client.post("/api/demo/reset", headers=demo.h("alice")).status_code == 403


def test_two_sessions_stay_isolated(demo):
    a = demo.client.get("/api/me", headers=demo.u("alice")).json()
    b = demo.client.get("/api/me", headers=demo.u("bob")).json()
    assert a["display_name"] == "Alice" and b["display_name"] == "Bob"


def test_outsider_cannot_act_on_a_match():
    d = Demo(people=("alice", "bob", "dan"))
    d.step(1)
    d.approach("alice", "bob", -70, 6)
    mid = d.match("alice")["id"]
    for path in ("respond", "cancel", "block", "confirm-met"):
        body = {"accept": True} if path == "respond" else None
        r = d.client.post(f"/api/matches/{mid}/{path}", json=body, headers=d.u("dan"))
        assert r.status_code in (403, 409), (path, r.status_code)
    assert d.match("alice")["state"] == "SUGGESTED"


def test_hub_identity_comes_from_token_not_body(demo):
    """Bob's hub reports a sighting: it is recorded as Bob observing, whatever it claims."""
    demo.step(1)
    body = {"session_id": "bob-session-1", "seq": 99, "band": {"state": "advertising"},
            "observations": [{"target_band_number": 11, "sequence": 1, "rssi_dbm": -60, "samples": 5,
                              "window_seconds": 5, "sample_age_ms": 0}]}
    demo.client.post("/api/hub/tick", json=body, headers=demo.h("bob"))
    sightings = demo.state()["sightings"]
    assert sightings == [{**sightings[0], "observer": "Bob", "target": "Alice"}]


def test_hub_ignores_its_own_band_and_unknown_bands(demo):
    body = {"session_id": "alice-session-1", "seq": 1, "band": {"state": "advertising"},
            "observations": [
                {"target_band_number": 11, "sequence": 1, "rssi_dbm": -40, "samples": 5,
                 "window_seconds": 5, "sample_age_ms": 0},
                {"target_band_number": 777, "sequence": 2, "rssi_dbm": -40, "samples": 5,
                 "window_seconds": 5, "sample_age_ms": 0}]}
    demo.client.post("/api/hub/tick", json=body, headers=demo.h("alice"))
    assert demo.state()["sightings"] == []


def test_roster_limits_accepted_bands():
    d = Demo(roster=[11])                     # Bob's band 22 is not on this demo's roster
    body = {"session_id": "alice-session-1", "seq": 1, "band": {"state": "advertising"},
            "observations": [{"target_band_number": 22, "sequence": 1, "rssi_dbm": -60, "samples": 5,
                              "window_seconds": 5, "sample_age_ms": 0}]}
    d.client.post("/api/hub/tick", json=body, headers=d.h("alice"))
    assert d.state()["sightings"] == []


def test_version_guards(demo):
    r = demo.client.put("/api/me/dating-status", headers=demo.u("alice"),
                        json={"status": "paused", "expected_version": 999})
    assert r.status_code == 409
    r = demo.client.patch("/api/me/profile", headers=demo.u("alice"), json={"expected_version": 999})
    assert r.status_code == 409
