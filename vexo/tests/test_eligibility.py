"""Hard filters: no match and no counterpart exposure when any of them fails."""
import pytest

from conftest import BANDS, Demo
from server.db import dumps
from server.enroll import PEOPLE, enroll


def near(d, a="alice", b="bob", seconds=6):
    d.step(1)
    d.approach(a, b, -70, seconds)


def assert_no_match(d, *who):
    for w in who:
        assert d.match(w) is None
        assert d.inbox(w) == []


def test_compatible_pair_matches(demo):
    near(demo)
    assert demo.match("alice")["state"] == "SUGGESTED"


def test_paused_person_is_never_matched():
    d = Demo(open_now=False)
    me = d.client.get("/api/me", headers=d.u("alice")).json()
    d.client.put("/api/me/dating-status", headers=d.u("alice"),
                 json={"status": "open", "expected_version": me["status_version"]})
    near(d)
    assert_no_match(d, "alice", "bob")


def test_underage_is_never_matched():
    d = Demo(people=("alice",))
    spec = dict(PEOPLE["bob"], dob="2010-01-01")
    d.p["bob"] = enroll(d.db, band_number=BANDS["bob"], open_now=True, **spec)
    d.hubs["bob"] = {"session": "s-bob-0001", "seq": 0, "state": "advertising", "acks": [], "taps": [],
                     "applied": None, "online": True}
    near(d)
    assert_no_match(d, "alice", "bob")


def test_gender_preference_must_be_mutual(demo):
    with demo.db.tx() as conn:
        conn.execute("UPDATE preferences SET genders = ? WHERE user_id = ?",
                     (dumps(["nonbinary"]), demo.p["bob"]["user_id"]))
    near(demo)
    assert_no_match(demo, "alice", "bob")


def test_age_range_must_be_mutual(demo):
    with demo.db.tx() as conn:
        conn.execute("UPDATE preferences SET age_min = 40, age_max = 50 WHERE user_id = ?",
                     (demo.p["alice"]["user_id"],))
    near(demo)
    assert_no_match(demo, "alice", "bob")


def test_goal_dealbreaker():
    d = Demo(people=("alice", "dan"))
    near(d, "alice", "dan")
    assert_no_match(d, "alice", "dan")


def test_block_in_either_direction(demo):
    with demo.db.tx() as conn:
        conn.execute("INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (?,?,0)",
                     (demo.p["bob"]["user_id"], demo.p["alice"]["user_id"]))
    near(demo)
    assert_no_match(demo, "alice", "bob")


def test_incomplete_profile(demo):
    with demo.db.tx() as conn:
        conn.execute("UPDATE profiles SET interests = ? WHERE user_id = ?",
                     (dumps(["climbing"]), demo.p["alice"]["user_id"]))
    near(demo)
    assert_no_match(demo, "alice", "bob")


def test_far_sightings_do_not_trigger(demo):
    demo.step(1)
    demo.approach("alice", "bob", -90, 8)
    assert_no_match(demo, "alice", "bob")


def test_offline_hub_blocks_matching(demo):
    demo.hubs["bob"]["online"] = False
    near(demo)
    assert_no_match(demo, "alice", "bob")


def test_hub_needing_double_tap_blocks_matching(demo):
    demo.hubs["bob"]["state"] = "needs_double_tap"
    demo.hubs["bob"]["applied"] = "skip"   # keep the harness from resetting the state
    for _ in range(7):
        demo.clock.advance(1)
        demo.sight("alice", "bob", -70), demo.sight("bob", "alice", -70)
        demo.tick("alice"), demo.tick("bob", auto_apply=False)
        demo.app.state.engine.run_once()
    assert_no_match(demo, "alice", "bob")


@pytest.mark.parametrize("field", ["interests", "personal_values"])
def test_low_score_pair_is_not_suggested_and_is_cached(field):
    d = Demo()
    with d.db.tx() as conn:
        conn.execute(f"UPDATE profiles SET {field} = ? WHERE user_id = ?",
                     (dumps(["tennis", "yoga", "dancing"]), d.p["bob"]["user_id"]))
        conn.execute("UPDATE profiles SET interests = ?, personal_values = ? WHERE user_id = ?",
                     (dumps(["tennis", "yoga", "dancing"]), dumps(["family", "ambition"]), d.p["bob"]["user_id"]))
    near(d)
    assert_no_match(d, "alice", "bob")
    ended = d.state()["matches"]
    assert len(ended) == 1 and ended[0]["end_reason"] == "below_threshold"
    near(d, seconds=5)
    assert len(d.state()["matches"]) == 1                       # cached negative: no re-reservation
