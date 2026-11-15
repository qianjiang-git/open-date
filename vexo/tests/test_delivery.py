"""Notification inbox, duplicate ticks, stale acknowledgments."""
from conftest import Demo


def to_suggested(d):
    d.step(1)
    d.approach("alice", "bob", -70, 6)


def test_inbox_cursor_and_durability(demo):
    to_suggested(demo)
    first = demo.client.get("/api/me/notifications", headers=demo.u("alice")).json()
    assert len(first["items"]) == 1
    again = demo.client.get(f"/api/me/notifications?after={first['cursor']}", headers=demo.u("alice")).json()
    assert again["items"] == []
    refreshed = demo.client.get("/api/me/notifications", headers=demo.u("alice")).json()
    assert refreshed["items"][0]["id"] == first["items"][0]["id"]          # survives a page refresh
    nid = first["items"][0]["id"]
    assert demo.client.post(f"/api/notifications/{nid}/read", headers=demo.u("alice")).status_code == 200
    assert demo.client.post(f"/api/notifications/{nid}/read", headers=demo.u("bob")).status_code == 404


def test_suggestion_payload_reveals_nothing(demo):
    to_suggested(demo)
    n = demo.inbox("alice")[0]
    text = (n["title"] + n["body"]).lower()
    for secret in ("bob", "climbing", "guitar", "honesty"):
        assert secret not in text


def test_duplicate_tick_has_no_side_effects(demo):
    d = demo
    d.step(1)
    hub = d.hubs["alice"]
    body = {"session_id": hub["session"], "seq": hub["seq"], "band": {"state": "advertising"},
            "observations": [{"target_band_number": 22, "sequence": 999, "rssi_dbm": -50, "samples": 5,
                              "window_seconds": 5, "sample_age_ms": 0}]}
    r = d.client.post("/api/hub/tick", json=body, headers=d.h("alice")).json()
    assert r["duplicate"] is True
    assert d.state()["sightings"] == []                                      # replayed seq ignored


def test_stale_ack_cannot_restore_a_match(demo):
    d = demo
    to_suggested(d)
    d.respond("alice"), d.respond("bob")
    d.approach("alice", "bob", -50, 8)
    assert d.match("alice")["state"] == "LIT"
    old_cmd = dict(d.hubs["alice"]["desired"])
    me = d.client.get("/api/me", headers=d.u("alice")).json()
    d.client.put("/api/me/dating-status", headers=d.u("alice"),
                 json={"status": "paused", "expected_version": me["status_version"]})
    # an old LIT acknowledgment arrives after the pause
    d.hubs["alice"]["acks"].append({"command_id": old_cmd["command_id"], "version": old_cmd["desired_version"],
                                    "status": "APPLIED"})
    d.step(1)
    assert d.match("alice") is None
    assert d.state()["matches"][0]["end_reason"] == "paused"
    assert d.hubs["alice"]["desired"]["mode"] == "IDLE"


def test_command_carries_a_lease(demo):
    demo.step(1)
    assert demo.hubs["alice"]["desired"]["valid_for_ms"] == 5000


def test_profile_revealed_only_after_both_accept(demo):
    to_suggested(demo)
    assert "counterpart" not in demo.match("bob")
    demo.respond("bob")
    assert "counterpart" not in demo.match("bob")
    demo.respond("alice")
    assert demo.match("bob")["counterpart"]["display_name"] == "Alice"
    assert "date_of_birth" not in demo.match("bob")["counterpart"]
