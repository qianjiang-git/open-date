"""Enrollment: users, preferences, approved profiles, band ownership and demo tokens.

Demo tokens are random, shown once, and stored only as SHA-256 hashes.
"""
from __future__ import annotations

import secrets

from . import lifecycle
from .db import Database, dumps, hash_token, new_id


def issue_token(conn, kind: str, user_id: str | None = None, hub_id: str | None = None) -> str:
    token = f"{kind}_{secrets.token_urlsafe(24)}"
    conn.execute("INSERT INTO tokens (token_hash, kind, user_id, hub_id) VALUES (?,?,?,?)",
                 (hash_token(token), kind, user_id, hub_id))
    return token


def enroll(db: Database, *, name: str, dob: str, gender: str, band_number: int, seeking: list,
           age_min: int, age_max: int, goal: str, accepted_goals: list, summary: str,
           interests: list, values: list, open_now: bool = False, notes: list | None = None) -> dict:
    """Create one participant with an approved profile. Returns ids and fresh tokens."""
    now = db.now()
    uid, band_id, hub_id = new_id(), new_id(), f"hub-{band_number}"
    with db.tx() as conn:
        conn.execute("INSERT INTO users (id, display_name, date_of_birth, gender, dating_status, created_at)"
                     " VALUES (?,?,?,?,?,?)", (uid, name, dob, gender, "open" if open_now else "paused", now))
        conn.execute("INSERT INTO preferences (user_id, genders, age_min, age_max, accepted_goals)"
                     " VALUES (?,?,?,?,?)", (uid, dumps(seeking), age_min, age_max, dumps(accepted_goals)))
        conn.execute("INSERT INTO profiles (user_id, approved, summary, interests, personal_values, goal, updated_at)"
                     " VALUES (?, 1, ?, ?, ?, ?, ?)", (uid, summary, dumps(interests), dumps(values), goal, now))
        conn.execute("INSERT INTO bands (id, number, user_id, hub_id) VALUES (?,?,?,?)",
                     (band_id, band_number, uid, hub_id))
        for text in notes or []:
            conn.execute("INSERT INTO voice_notes (id, user_id, transcript, source, created_at)"
                         " VALUES (?,?,?, 'seed', ?)", (new_id(), uid, text, now))
        lifecycle.set_desired(conn, band_id, "BEACON" if open_now else "IDLE", now)
        user_token = issue_token(conn, "user", user_id=uid)
        hub_token = issue_token(conn, "hub", user_id=uid, hub_id=hub_id)
    return {"user_id": uid, "band_id": band_id, "hub_id": hub_id, "band_number": band_number,
            "user_token": user_token, "hub_token": hub_token}


def operator_token(db: Database) -> str:
    with db.tx() as conn:
        return issue_token(conn, "operator")


# Demo people. Alice and Bob are a strong match; Cara also fits Bob (allocation test),
# Dan is a poor match for everyone.
PEOPLE = {
    "alice": dict(name="Alice", dob="1997-03-14", gender="woman", seeking=["man"], age_min=24, age_max=40,
                  goal="long-term", accepted_goals=["long-term", "friendship-first"],
                  summary="Spends weekends outdoors and evenings at small gigs. Builds things at hackathons.",
                  interests=["climbing", "hiking", "guitar", "live-music", "coding"],
                  values=["curiosity", "honesty", "adventure"],
                  notes=["I went bouldering again this morning, then played guitar at an open mic.",
                         "Honestly I want something long-term with someone curious."]),
    "bob": dict(name="Bob", dob="1995-08-02", gender="man", seeking=["woman"], age_min=24, age_max=38,
                goal="long-term", accepted_goals=["long-term"],
                summary="Climber and amateur guitarist who loves trying new trails.",
                interests=["climbing", "guitar", "hiking", "coffee", "live-music"],
                values=["honesty", "curiosity", "kindness"],
                notes=["Climbing gym three times a week, guitar most nights."]),
    "cara": dict(name="Cara", dob="1996-11-20", gender="woman", seeking=["man"], age_min=24, age_max=40,
                 goal="long-term", accepted_goals=["long-term"],
                 summary="Trail runner and coffee nerd who reads on long train rides.",
                 interests=["hiking", "coffee", "climbing", "reading"],
                 values=["honesty", "kindness", "curiosity"], notes=[]),
    "dan": dict(name="Dan", dob="1990-01-05", gender="man", seeking=["woman"], age_min=24, age_max=45,
                goal="casual", accepted_goals=["casual", "long-term"],
                summary="Gamer and film buff who prefers quiet nights in.",
                interests=["video-games", "film", "board-games"],
                values=["humor", "independence"], notes=[]),
}
