"""Full flow and every lifecycle exit, with simulated sightings and simulated hubs."""
from conftest import Demo


def to_suggested(d: Demo):
    d.step(1)
    d.approach("alice", "bob", -70, 6)
    assert d.match("alice")["state"] == "SUGGESTED"


def to_accepted(d: Demo):
    to_suggested(d)
    d.respond("alice")
    d.respond("bob")
    assert d.match("alice")["state"] == "ACCEPTED"


def to_lit(d: Demo):
    to_accepted(d)
    d.approach("alice", "bob", -50, 8)
    assert d.match("alice")["state"] == "LIT", d.state()["matches"][0]


def test_happy_path_end_to_end(demo):
    d = demo
    to_suggested(d)
    m = d.match("alice")
    assert "counterpart" not in m and "color" not in m          # anonymous until both accept
    assert [n["kind"] for n in d.inbox("alice")] == ["suggestion"]
    assert [n["kind"] for n in d.inbox("bob")] == ["suggestion"]

    d.respond("alice")
    m = d.match("alice")
    assert m["state"] == "SUGGESTED" and m["you_accepted"] and "counterpart" not in m
    assert "counterpart" not in d.match("bob")

    d.respond("bob")
    a, b = d.match("alice"), d.match("bob")
    assert a["state"] == "ACCEPTED" and a["counterpart"]["display_name"] == "Bob"
    assert b["counterpart"]["display_name"] == "Alice"
    assert a["color"] == b["color"] == "#00c7be"
    assert a["id"] == b["id"]

    d.approach("alice", "bob", -50, 8)
    a = d.match("alice")
    assert a["state"] == "LIT"
    assert a["proximity_note"] == "Proximity last confirmed before lighting"
    da, db_ = d.hubs["alice"]["desired"], d.hubs["bob"]["desired"]
    assert da["mode"] == db_["mode"] == "LIT" and da["color"] == db_["color"] == "#00c7be"
    assert da["lighting_session_id"] == db_["lighting_session_id"]

    d.tap("alice")
    d.step(1)
    assert d.match("alice")["state"] == "LIT"                  # one tap is not enough
    d.tap("bob")
    d.step(1)
    assert d.match("alice")["state"] == "MET"
    d.step(0.5)                                                  # both hubs poll the new command
    assert d.hubs["alice"]["desired"]["mode"] == d.hubs["bob"]["desired"]["mode"] == "MET_FLASH"

    d.step(4)
    assert d.match("alice") is None
    s = d.state()
    assert s["matches"][0]["state"] == "ENDED" and s["matches"][0]["end_reason"] == "met"
    assert s["matches"][0]["met_via"] == "band_taps"
    assert s["color_leases"][0]["release_after"] is not None     # quarantined until cleanup acks
    d.step(0.5)                                                  # hubs receive and ack the cleanup
    s = d.state()
    assert {x["mode"] for x in s["devices"]} == {"BEACON"}
    assert s["color_leases"] == []                               # released after both cleanup acks
    kinds = [n["kind"] for n in d.inbox("bob")]
    assert kinds == ["suggestion", "accepted", "close", "met", "ended"]


def test_cooldown_after_met_prevents_immediate_rematch(demo):
    d = demo
    to_lit(d)
    d.tap("alice"), d.tap("bob")
    d.step(1)
    d.step(4)
    d.approach("alice", "bob", -50, 10)
    assert d.match("alice") is None


def test_decline_ends_and_cools_down(demo):
    d = demo
    to_suggested(d)
    d.respond("alice", accept=False)
    assert d.match("alice") is None and d.match("bob") is None
    d.approach("alice", "bob", -70, 6)
    assert d.match("alice") is None


def test_suggestion_expires(demo):
    d = demo
    to_suggested(d)
    d.step(121)
    assert d.match("alice") is None
    assert d.state()["matches"][0]["end_reason"] == "suggestion_expired"


def test_one_acceptance_never_lights(demo):
    d = demo
    to_suggested(d)
    d.respond("alice")
    d.approach("alice", "bob", -50, 8)
    assert d.match("alice")["state"] == "SUGGESTED"
    assert {x["mode"] for x in d.state()["devices"]} == {"BEACON"}


def test_approach_deadline(demo):
    d = demo
    to_accepted(d)
    d.step(181)
    assert d.state()["matches"][0]["end_reason"] == "approach_expired"


def test_lit_timeout_and_cleanup(demo):
    d = demo
    to_lit(d)
    d.step(61)
    s = d.state()
    assert s["matches"][0]["end_reason"] == "lit_timeout"
    assert {x["mode"] for x in s["devices"]} == {"BEACON"}


def test_partial_lighting_failure_retries_then_gives_up(demo):
    d = demo
    to_accepted(d)
    # Bob's band fails to light: the attempt is cleaned up and the match goes back to ACCEPTED
    d.clock.advance(1)
    for _ in range(8):
        d.clock.advance(1)
        d.sight("alice", "bob", -50), d.sight("bob", "alice", -50)
        d.tick("alice"), d.tick("alice")
        d.tick("bob", fail=True), d.tick("bob", fail=True)
        d.app.state.engine.run_once()
        if d.state()["matches"][0]["attempts"] == 1 and d.match("alice")["state"] == "ACCEPTED":
            break
    s = d.state()
    assert s["matches"][0]["state"] == "ACCEPTED" and s["matches"][0]["attempts"] == 1
    assert {x["mode"] for x in s["devices"]} == {"BEACON"}       # both cleaned up
    assert s["color_leases"][0]["color_hex"] == "#00c7be"        # colour stays with the pair

    # second attempt also fails -> device_failure
    for _ in range(10):
        d.clock.advance(1)
        d.sight("alice", "bob", -50), d.sight("bob", "alice", -50)
        d.tick("alice"), d.tick("alice")
        d.tick("bob", fail=True), d.tick("bob", fail=True)
        d.app.state.engine.run_once()
    s = d.state()
    assert s["matches"][0]["end_reason"] == "device_failure"


def test_retry_needs_fresh_close_evidence(demo):
    d = demo
    to_accepted(d)
    for _ in range(8):
        d.clock.advance(1)
        d.sight("alice", "bob", -50), d.sight("bob", "alice", -50)
        d.tick("alice"), d.tick("alice")
        d.tick("bob", fail=True), d.tick("bob", fail=True)
        d.app.state.engine.run_once()
        if d.state()["matches"][0]["attempts"] == 1 and d.match("alice")["state"] == "ACCEPTED":
            break
    # no new sightings: the old CLOSE evidence predates the failure and must not relight
    d.step(2)
    assert d.match("alice")["state"] == "ACCEPTED"


def test_lighting_timeout_when_no_ack(demo):
    d = demo
    to_accepted(d)
    for _ in range(8):
        d.clock.advance(1)
        d.sight("alice", "bob", -50), d.sight("bob", "alice", -50)
        d.tick("alice"), d.tick("alice")
        d.tick("bob", auto_apply=False), d.tick("bob", auto_apply=False)
        d.app.state.engine.run_once()
    assert d.state()["matches"][0]["state"] == "LIGHTING"
    d.step(11, ticks=False)
    # hubs silent for 11 s -> hub_lost ends it before any relight
    assert d.match("alice") is None


def test_hub_loss_ends_lit_match(demo):
    d = demo
    to_lit(d)
    d.hubs["bob"]["online"] = False
    d.step(6)
    s = d.state()
    assert s["matches"][0]["end_reason"] == "hub_lost"
    d.step(0.5)
    assert d.hubs["alice"]["desired"]["mode"] == "BEACON"        # surviving side is cleaned up


def test_device_loss_while_lit(demo):
    d = demo
    to_lit(d)
    d.hubs["bob"]["state"] = "advertising"          # band dropped its connection
    d.step(1)
    assert d.state()["matches"][0]["end_reason"] == "device_loss"


def test_pause_cancels_and_idles_band(demo):
    d = demo
    to_lit(d)
    me = d.client.get("/api/me", headers=d.u("alice")).json()
    r = d.client.put("/api/me/dating-status", headers=d.u("alice"),
                     json={"status": "paused", "expected_version": me["status_version"]})
    assert r.status_code == 200
    d.step(1)
    s = d.state()
    assert s["matches"][0]["end_reason"] == "paused"
    modes = {x["band"]: x["mode"] for x in s["devices"]}
    assert modes == {11: "IDLE", 22: "BEACON"}


def test_late_tap_from_old_session_cannot_mark_new_match_met(demo):
    d = demo
    to_lit(d)
    old = dict(d.hubs["alice"]["desired"])
    d.step(61)                                       # lit timeout
    # a tap carrying the old session arrives late
    d.hubs["alice"]["taps"].append({"event_id": "late-tap-0001", "match_id": old["match_id"],
                                    "lighting_session_id": old["lighting_session_id"]})
    d.step(1)
    assert d.state()["matches"][0]["end_reason"] == "lit_timeout"


def test_repeated_tap_is_idempotent(demo):
    d = demo
    to_lit(d)
    d.tap("alice")
    tap = d.hubs["alice"]["taps"][0]
    d.step(1)
    d.hubs["alice"]["taps"].append(dict(tap))       # redelivered
    d.step(1)
    assert d.match("alice")["state"] == "LIT"


def test_app_confirmation_fallback_is_labelled(demo):
    d = demo
    to_lit(d)
    mid = d.match("alice")["id"]
    for who in ("alice", "bob"):
        assert d.client.post(f"/api/matches/{mid}/confirm-met", headers=d.u(who)).json()["ok"]
    m = d.match("alice")
    assert m["state"] == "MET" and m["met_note"].startswith("Confirmed in the app")


def test_operator_confirm_close_is_labelled(demo):
    d = demo
    to_accepted(d)
    mid = d.match("alice")["id"]
    assert d.client.post(f"/api/demo/confirm-close/{mid}", headers=d.op).status_code == 200
    d.step(1)
    d.step(1)
    m = d.match("alice")
    assert m["state"] == "LIT" and m["evidence"] == "operator"


def test_demo_reset_after_a_scored_match(demo):
    d = demo
    to_lit(d)
    r = d.client.post("/api/demo/reset", headers=d.op)
    assert r.status_code == 200, r.text
    s = d.state()
    assert s["matches"][0]["end_reason"] == "reset" and s["sightings"] == []
    d.step(0.5)
    assert {x["mode"] for x in d.state()["devices"]} == {"BEACON"}
    d.approach("alice", "bob", -70, 6)                      # cooldowns cleared: can match again
    assert d.match("alice")["state"] == "SUGGESTED"


def test_worker_expires_without_any_polling(demo):
    d = demo
    to_suggested(d)
    d.clock.advance(200)
    d.app.state.engine.run_once()
    assert d.state()["matches"][0]["state"] == "ENDED"
