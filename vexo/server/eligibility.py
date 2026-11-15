"""Hard filters that run before any scorer. A pair failing one is never scored or shown."""
from __future__ import annotations

from datetime import date, datetime, timezone

from .db import loads

BAND_UNAVAILABLE = {"needs_double_tap", "error", "voice", "offline"}
MIN_INTERESTS, MIN_VALUES = 3, 2


def pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def age_on(dob: str, now: float) -> int:
    born = date.fromisoformat(dob)
    today = datetime.fromtimestamp(now, tz=timezone.utc).date()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def profile_complete(p) -> bool:
    return (p is not None and p["approved"] == 1
            and len(loads(p["interests"])) >= MIN_INTERESTS
            and len(loads(p["personal_values"])) >= MIN_VALUES
            and bool(p["goal"]))


def hub_ready(conn, user_id: str, now: float, hub_lost_s: float) -> bool:
    h = conn.execute("SELECT * FROM hub_sessions WHERE user_id = ?", (user_id,)).fetchone()
    return (h is not None and now - h["last_tick"] <= hub_lost_s
            and h["band_state"] not in BAND_UNAVAILABLE and not h["mic_active"])


def _wants(prefs, other_user, other_profile, now: float) -> str | None:
    if other_user["gender"] not in loads(prefs["genders"]):
        return "gender_preference"
    if not prefs["age_min"] <= age_on(other_user["date_of_birth"], now) <= prefs["age_max"]:
        return "age_preference"
    if other_profile["goal"] not in loads(prefs["accepted_goals"]):
        return "goal_dealbreaker"
    return None


def check(conn, a: str, b: str, now: float, hub_lost_s: float, require_hubs: bool = True) -> str | None:
    """None if the pair may be scored, else the first failing reason."""
    if a == b:
        return "same_user"
    users = {u["id"]: u for u in conn.execute("SELECT * FROM users WHERE id IN (?, ?)", (a, b))}
    if len(users) != 2:
        return "unknown_user"
    for uid in (a, b):
        if age_on(users[uid]["date_of_birth"], now) < 18:
            return "not_adult"
        if users[uid]["dating_status"] != "open":
            return "not_open"
    profiles = {p["user_id"]: p for p in conn.execute(
        "SELECT * FROM profiles WHERE user_id IN (?, ?)", (a, b))}
    if not all(profile_complete(profiles.get(uid)) for uid in (a, b)):
        return "profile_incomplete"
    prefs = {p["user_id"]: p for p in conn.execute(
        "SELECT * FROM preferences WHERE user_id IN (?, ?)", (a, b))}
    if len(prefs) != 2:
        return "no_preferences"
    for me, other in ((a, b), (b, a)):
        reason = _wants(prefs[me], users[other], profiles[other], now)
        if reason:
            return reason
    if conn.execute("SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?)"
                    " OR (blocker_id = ? AND blocked_id = ?)", (a, b, b, a)).fetchone():
        return "blocked"
    low, high = pair(a, b)
    if conn.execute("SELECT 1 FROM pair_cooldowns WHERE user_low = ? AND user_high = ? AND expires_at > ?",
                    (low, high, now)).fetchone():
        return "cooldown"
    if require_hubs and not (hub_ready(conn, a, now, hub_lost_s) and hub_ready(conn, b, now, hub_lost_s)):
        return "hub_unavailable"
    return None
