"""SQLite storage: schema migrations and one serialized write path.

Every read-modify-write goes through `Database.tx()`, which takes a process-wide lock and
opens `BEGIN IMMEDIATE`. No network call ever happens inside it (scoring runs outside).
Timestamps are UTC epoch seconds (REAL) from the injectable clock.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager


class Clock:
    """Wall clock in UTC epoch seconds. Tests swap in FakeClock."""

    def now(self) -> float:
        return time.time()


class FakeClock(Clock):
    def __init__(self, start: float = 1_800_000_000.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def new_id() -> str:
    return str(uuid.uuid4())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def dumps(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def loads(text):
    return None if text is None else json.loads(text)


MIGRATIONS = [
    # 1: the whole demo schema
    """
    CREATE TABLE users (
      id TEXT PRIMARY KEY,
      display_name TEXT NOT NULL,
      date_of_birth TEXT NOT NULL,                 -- YYYY-MM-DD
      gender TEXT NOT NULL,
      dating_status TEXT NOT NULL DEFAULT 'paused' CHECK (dating_status IN ('open','paused')),
      status_version INTEGER NOT NULL DEFAULT 1,
      created_at REAL NOT NULL
    );
    CREATE TABLE preferences (
      user_id TEXT PRIMARY KEY REFERENCES users(id),
      genders TEXT NOT NULL,                       -- JSON list the user wants to meet
      age_min INTEGER NOT NULL CHECK (age_min >= 18),
      age_max INTEGER NOT NULL,
      accepted_goals TEXT NOT NULL,                -- JSON list; a goal outside it is a dealbreaker
      version INTEGER NOT NULL DEFAULT 1,
      CHECK (age_max >= age_min)
    );
    CREATE TABLE bands (
      id TEXT PRIMARY KEY,
      number INTEGER NOT NULL UNIQUE CHECK (number BETWEEN 1 AND 999),
      user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
      hub_id TEXT NOT NULL UNIQUE
    );
    CREATE TABLE tokens (
      token_hash TEXT PRIMARY KEY,
      kind TEXT NOT NULL CHECK (kind IN ('user','hub','operator')),
      user_id TEXT REFERENCES users(id),
      hub_id TEXT
    );
    CREATE TABLE profiles (
      user_id TEXT PRIMARY KEY REFERENCES users(id),
      version INTEGER NOT NULL DEFAULT 1,
      approved INTEGER NOT NULL DEFAULT 0,
      summary TEXT NOT NULL,
      interests TEXT NOT NULL,                     -- JSON list of normalised tags
      personal_values TEXT NOT NULL,               -- JSON list of normalised tags
      goal TEXT NOT NULL,                          -- relationship goal tag, '' if unknown
      updated_at REAL NOT NULL
    );
    CREATE TABLE voice_notes (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id),
      transcript TEXT NOT NULL,
      source TEXT NOT NULL CHECK (source IN ('mic','typed','seed')),
      created_at REAL NOT NULL,
      deleted_at REAL
    );
    CREATE TABLE profile_proposals (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id),
      base_version INTEGER NOT NULL,
      changes TEXT NOT NULL,
      state TEXT NOT NULL CHECK (state IN ('pending','accepted','rejected','stale')),
      provider TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    CREATE TABLE hub_sessions (
      hub_id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id),
      band_id TEXT NOT NULL REFERENCES bands(id),
      session_id TEXT NOT NULL,
      last_seq INTEGER NOT NULL DEFAULT 0,
      last_tick REAL NOT NULL,
      band_state TEXT NOT NULL,
      mic_active INTEGER NOT NULL DEFAULT 0,
      battery INTEGER
    );
    CREATE TABLE sightings (
      observer_id TEXT NOT NULL REFERENCES users(id),
      target_band_id TEXT NOT NULL REFERENCES bands(id),
      source TEXT NOT NULL,
      source_session TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      rssi REAL NOT NULL,
      samples INTEGER NOT NULL,
      first_sample_at REAL NOT NULL,
      last_sample_at REAL NOT NULL,
      zone TEXT NOT NULL,
      zone_since REAL NOT NULL,
      candidate TEXT,
      candidate_since REAL,
      PRIMARY KEY (observer_id, target_band_id)
    );
    CREATE TABLE score_jobs (
      id TEXT PRIMARY KEY,
      user_low TEXT NOT NULL,
      user_high TEXT NOT NULL,
      cache_key TEXT NOT NULL UNIQUE,
      state TEXT NOT NULL CHECK (state IN ('pending','running','done','failed')),
      result TEXT,
      lease_until REAL,
      retries INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      finished_at REAL
    );
    CREATE TABLE matches (
      id TEXT PRIMARY KEY,
      user_low TEXT NOT NULL REFERENCES users(id),
      user_high TEXT NOT NULL REFERENCES users(id),
      state TEXT NOT NULL CHECK (state IN ('SCORING','SUGGESTED','ACCEPTED','LIGHTING','LIT','MET','ENDED')),
      job_id TEXT REFERENCES score_jobs(id),
      score INTEGER,
      scorer TEXT,
      reasons TEXT,                                -- private, never sent to clients
      shared TEXT,
      icebreaker TEXT,
      low_profile_version INTEGER NOT NULL,
      high_profile_version INTEGER NOT NULL,
      low_pref_version INTEGER NOT NULL,
      high_pref_version INTEGER NOT NULL,
      low_accepted INTEGER,
      high_accepted INTEGER,
      color TEXT,
      evidence TEXT,                               -- which source opened lighting
      lighting_session_id TEXT,
      lighting_attempts INTEGER NOT NULL DEFAULT 0,
      close_required_after REAL NOT NULL DEFAULT 0,
      close_confirmed_at REAL,
      low_tapped INTEGER NOT NULL DEFAULT 0,
      high_tapped INTEGER NOT NULL DEFAULT 0,
      met_via TEXT,
      version INTEGER NOT NULL DEFAULT 1,
      deadline REAL,
      end_reason TEXT,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL,
      CHECK (user_low < user_high)
    );
    CREATE TABLE active_members (
      user_id TEXT PRIMARY KEY REFERENCES users(id),
      match_id TEXT NOT NULL REFERENCES matches(id)
    );
    CREATE TABLE color_leases (
      color_hex TEXT PRIMARY KEY,
      match_id TEXT NOT NULL UNIQUE REFERENCES matches(id),
      release_after REAL                           -- NULL while the match is active
    );
    CREATE TABLE pair_cooldowns (
      user_low TEXT NOT NULL,
      user_high TEXT NOT NULL,
      reason TEXT NOT NULL,
      expires_at REAL NOT NULL,
      PRIMARY KEY (user_low, user_high)
    );
    CREATE TABLE blocks (
      blocker_id TEXT NOT NULL REFERENCES users(id),
      blocked_id TEXT NOT NULL REFERENCES users(id),
      created_at REAL NOT NULL,
      PRIMARY KEY (blocker_id, blocked_id)
    );
    CREATE TABLE notifications (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      id TEXT NOT NULL UNIQUE,
      recipient TEXT NOT NULL REFERENCES users(id),
      match_id TEXT NOT NULL REFERENCES matches(id),
      kind TEXT NOT NULL,
      payload TEXT NOT NULL,
      read INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      UNIQUE (recipient, match_id, kind)
    );
    CREATE TABLE device_desired (
      band_id TEXT PRIMARY KEY REFERENCES bands(id),
      version INTEGER NOT NULL,
      command_id TEXT NOT NULL,
      match_id TEXT,
      lighting_session_id TEXT,
      mode TEXT NOT NULL CHECK (mode IN ('BEACON','IDLE','LIT','MET_FLASH')),
      color TEXT,
      pattern TEXT,
      brightness REAL,
      cleanup_for TEXT,                            -- match whose light this command clears
      updated_at REAL NOT NULL
    );
    CREATE TABLE device_acks (
      command_id TEXT NOT NULL,
      band_id TEXT NOT NULL REFERENCES bands(id),
      version INTEGER NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('APPLIED','FAILED','EXPIRED','SUPERSEDED')),
      applied_at REAL NOT NULL,
      error TEXT,
      PRIMARY KEY (command_id, band_id)
    );
    CREATE TABLE tap_events (
      event_id TEXT PRIMARY KEY,
      match_id TEXT NOT NULL,
      lighting_session_id TEXT NOT NULL,
      user_id TEXT NOT NULL,
      accepted INTEGER NOT NULL,
      received_at REAL NOT NULL
    );
    CREATE TABLE transitions (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      match_id TEXT NOT NULL,
      from_state TEXT,
      to_state TEXT NOT NULL,
      reason TEXT NOT NULL,
      at REAL NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: str, clock: Clock | None = None):
        self.path = path
        self.clock = clock or Clock()
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self.lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self.conn.execute("SELECT version FROM schema_version").fetchone()
            current = row["version"] if row else 0
            for number, script in enumerate(MIGRATIONS, start=1):
                if number <= current:
                    continue
                self.conn.executescript("BEGIN;" + script + "COMMIT;")
                self.conn.execute("DELETE FROM schema_version")
                self.conn.execute("INSERT INTO schema_version VALUES (?)", (number,))

    @contextmanager
    def tx(self):
        """One serialized write transaction. Yields the connection."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def read(self, sql: str, args=()) -> list:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def now(self) -> float:
        return self.clock.now()
