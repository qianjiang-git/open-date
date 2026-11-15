"""Zone classification: dwell, hysteresis, replay, staleness, sample validation."""
import pytest

from conftest import Demo
from server import presence


@pytest.fixture
def d():
    return Demo()


def rec(d, rssi, seq, age_ms=0, samples=5, session="s1"):
    with d.db.tx() as conn:
        return presence.record(conn, d.cfg.rssi, observer_id=d.p["alice"]["user_id"],
                               target_band_id=d.p["bob"]["band_id"], source="real_beacon",
                               source_session=session, sequence=seq, rssi=rssi, samples=samples,
                               sample_age_ms=age_ms, receipt=d.clock.now())


def zone(d):
    with d.db.lock:
        row = presence.direction(d.db.conn, d.p["alice"]["user_id"], d.p["bob"]["user_id"])
        return presence.effective_zone(row, d.clock.now(), d.cfg.rssi)


def run(d, rssi, seconds, start_seq):
    for i in range(seconds):
        d.clock.advance(1)
        rec(d, rssi, start_seq + i)
    return start_seq + seconds


def test_near_needs_three_seconds_of_dwell(d):
    rec(d, -70, 1)
    d.clock.advance(1); rec(d, -70, 2)
    d.clock.advance(1); rec(d, -70, 3)
    assert zone(d) == "UNKNOWN"
    d.clock.advance(1); rec(d, -70, 4)
    assert zone(d) == "NEAR"


def test_single_spike_does_not_change_zone(d):
    seq = run(d, -70, 5, 1)
    assert zone(d) == "NEAR"
    d.clock.advance(1); rec(d, -40, seq)               # one spike
    d.clock.advance(1); rec(d, -70, seq + 1)
    seq = run(d, -70, 5, seq + 2)
    assert zone(d) == "NEAR"


def test_hysteresis_between_close_and_near(d):
    seq = run(d, -70, 5, 1)
    seq = run(d, -50, 5, seq)
    assert zone(d) == "CLOSE"
    seq = run(d, -62, 10, seq)                          # between -66 and -58: stays CLOSE
    assert zone(d) == "CLOSE"
    seq = run(d, -70, 4, seq)                           # below -66 for 4 s: not yet
    assert zone(d) == "CLOSE"
    run(d, -70, 2, seq)
    assert zone(d) == "NEAR"


def test_near_to_far_needs_below_minus_84(d):
    seq = run(d, -70, 5, 1)
    seq = run(d, -80, 10, seq)                          # between -84 and -78: stays NEAR
    assert zone(d) == "NEAR"
    run(d, -90, 6, seq)
    assert zone(d) == "FAR"


def test_replayed_sequence_is_rejected(d):
    run(d, -70, 5, 1)
    d.clock.advance(1)
    assert rec(d, -40, 3) == "replay"


def test_unchanged_sample_time_does_not_refresh(d):
    run(d, -70, 5, 1)
    d.clock.advance(1)
    assert rec(d, -70, 10, age_ms=0) == "accepted"
    assert rec(d, -70, 11, age_ms=0) == "unchanged"     # same sample time, newer sequence


def test_stale_gap_goes_unknown(d):
    run(d, -70, 5, 1)
    d.clock.advance(9)
    assert zone(d) == "UNKNOWN"


def test_too_few_samples_and_bad_ages(d):
    assert rec(d, -70, 1, samples=2) == "too_few_samples"
    assert rec(d, -70, 1, age_ms=-5) == "bad_age"
    assert rec(d, -70, 1, age_ms=60_000) == "bad_age"


def test_sample_age_counts_back_from_receipt(d):
    rec(d, -70, 1)
    d.clock.advance(4)
    rec(d, -70, 2, age_ms=3500)                         # sampled 0.5 s after the first
    assert zone(d) == "UNKNOWN"


def test_hub_cannot_report_simulated_source(d):
    body = {"session_id": "session-1", "seq": 1, "band": {"state": "advertising"},
            "observations": [{"target_band_number": 22, "source": "simulated", "sequence": 1,
                              "rssi_dbm": -50, "samples": 5, "window_seconds": 5, "sample_age_ms": 0}]}
    r = d.client.post("/api/hub/tick", json=body, headers=d.h("alice"))
    assert r.status_code == 422


def test_simulated_sightings_refused_in_real_mode():
    d = Demo(demo_mode="real")
    r = d.client.post("/api/demo/sightings", headers=d.op,
                      json={"observer_band": 11, "target_band": 22, "rssi_dbm": -50, "source": "simulated"})
    assert r.status_code == 409


def test_real_mode_matches_from_hub_reported_beacons():
    d = Demo(demo_mode="real")
    seq = {"alice": 0, "bob": 0}

    def obs(who, target_band, rssi):
        seq[who] += 1
        return [{"target_band_number": target_band, "sequence": seq[who], "rssi_dbm": rssi,
                 "samples": 5, "window_seconds": 5, "sample_age_ms": 100}]

    for _ in range(6):
        d.clock.advance(1)
        d.tick("alice", observations=obs("alice", 22, -70))
        d.tick("bob", observations=obs("bob", 11, -70))
        d.app.state.engine.run_once()
    assert d.match("alice")["state"] == "SUGGESTED"
