"""Directed sightings: "observer's hub heard target's band", never "band A heard band B".

The hub sends smoothed RSSI with a sample age; the server decides zones itself from
timestamps (dwell + hysteresis), so a client cannot just claim CLOSE. Sample time is
bounded by the server's receipt time. Replayed or unchanged observations never refresh
presence.
"""
from __future__ import annotations

from .config import Rssi

ZONES = ("UNKNOWN", "FAR", "NEAR", "CLOSE")
_RANK = {"UNKNOWN": 0, "FAR": 1, "NEAR": 2, "CLOSE": 3}


def candidate_zone(zone: str, rssi: float, cfg: Rssi) -> str:
    """The zone this reading points to, given the current zone (hysteresis lives here)."""
    if zone in ("UNKNOWN", "FAR"):
        return "NEAR" if rssi >= cfg.near_enter else "FAR"
    if zone == "NEAR":
        if rssi >= cfg.close_enter:
            return "CLOSE"
        if rssi < cfg.near_exit:
            return "FAR"
        return "NEAR"
    # CLOSE
    return "NEAR" if rssi < cfg.close_exit else "CLOSE"


def dwell_for(old: str, new: str, cfg: Rssi) -> float:
    if old == "UNKNOWN" and new == "FAR":
        return 0.0
    return cfg.enter_dwell_s if _RANK[new] > _RANK[old] else cfg.exit_dwell_s


def effective_zone(row, now: float, cfg: Rssi) -> str:
    if row is None or now - row["last_sample_at"] > cfg.stale_s:
        return "UNKNOWN"
    return row["zone"]


def record(conn, cfg: Rssi, *, observer_id: str, target_band_id: str, source: str,
           source_session: str, sequence: int, rssi: float, samples: int,
           sample_age_ms: int, receipt: float) -> str:
    """Apply one observation. Returns accepted | replay | unchanged | too_few_samples | bad_age."""
    if sample_age_ms < 0 or sample_age_ms > cfg.max_sample_age_ms:
        return "bad_age"
    if samples < cfg.min_samples:
        return "too_few_samples"
    sample_at = receipt - sample_age_ms / 1000.0
    row = conn.execute(
        "SELECT * FROM sightings WHERE observer_id = ? AND target_band_id = ?",
        (observer_id, target_band_id)).fetchone()

    if row is None:
        cand = candidate_zone("UNKNOWN", rssi, cfg)
        zone, zone_since, candidate, candidate_since = "UNKNOWN", sample_at, cand, sample_at
        if dwell_for("UNKNOWN", cand, cfg) == 0:
            zone, candidate, candidate_since = cand, None, None
        conn.execute(
            "INSERT INTO sightings (observer_id, target_band_id, source, source_session, sequence, rssi,"
            " samples, first_sample_at, last_sample_at, zone, zone_since, candidate, candidate_since)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (observer_id, target_band_id, source, source_session, sequence, rssi, samples,
             sample_at, sample_at, zone, zone_since, candidate, candidate_since))
        return "accepted"

    if row["source_session"] == source_session and sequence <= row["sequence"]:
        return "replay"
    if sample_at <= row["last_sample_at"]:
        return "unchanged"

    zone, zone_since = row["zone"], row["zone_since"]
    candidate, candidate_since = row["candidate"], row["candidate_since"]
    first_sample_at = row["first_sample_at"]
    if sample_at - row["last_sample_at"] > cfg.stale_s or row["source"] != source:
        # stale gap or a different evidence source: clear the filter and start again
        zone, zone_since, candidate, candidate_since = "UNKNOWN", sample_at, None, None
        first_sample_at = sample_at

    cand = candidate_zone(zone, rssi, cfg)
    if cand == zone:
        candidate, candidate_since = None, None
    else:
        if candidate != cand:
            candidate, candidate_since = cand, sample_at
        if sample_at - candidate_since >= dwell_for(zone, cand, cfg):
            zone, zone_since, candidate, candidate_since = cand, sample_at, None, None

    conn.execute(
        "UPDATE sightings SET source = ?, source_session = ?, sequence = ?, rssi = ?, samples = ?,"
        " first_sample_at = ?, last_sample_at = ?, zone = ?, zone_since = ?, candidate = ?,"
        " candidate_since = ? WHERE observer_id = ? AND target_band_id = ?",
        (source, source_session, sequence, rssi, samples, first_sample_at, sample_at, zone,
         zone_since, candidate, candidate_since, observer_id, target_band_id))
    return "accepted"


def direction(conn, observer_id: str, target_user_id: str):
    """The sighting row for observer -> target's band, or None."""
    return conn.execute(
        "SELECT s.* FROM sightings s JOIN bands b ON b.id = s.target_band_id"
        " WHERE s.observer_id = ? AND b.user_id = ?", (observer_id, target_user_id)).fetchone()


def counts_as_evidence(row, now: float, cfg: Rssi, allowed_sources: set, at_least: str,
                       not_before: float = 0.0, within_s: float | None = None) -> bool:
    if row is None or row["source"] not in allowed_sources:
        return False
    if not_before and row["last_sample_at"] <= not_before:
        return False                             # evidence must be strictly newer
    if within_s is not None and now - row["last_sample_at"] > within_s:
        return False
    return _RANK[effective_zone(row, now, cfg)] >= _RANK[at_least]
