"""PostgreSQL backend for the hosted deployment, plus a backend selector.

The application was written against SQLite. This module keeps the same small surface
(`tx()`, `read()`, `one()`, `now()`, `.conn.execute(...)`) and translates the handful of
SQLite-only spellings used by the schema and queries. It is intentionally isolated from
`server/db.py` so local SQLite development and tests keep working unchanged.

Select the backend with `DATABASE_URL` (Render sets this automatically):

    postgresql://user:password@host/database   -> PostgresDatabase
    anything else / unset                      -> SQLite Database(path)

Correctness notes:

* All writes take a transaction-scoped PostgreSQL advisory lock. That reproduces the
  old "one serialized writer" guarantee across processes and overlapping deploys, while
  still being a database-level lock rather than a process-local mutex.
* Migrations take a separate session-level advisory lock, so two instances starting at
  the same moment cannot migrate concurrently.
* Timestamps are `DOUBLE PRECISION`; SQLite `REAL` is only 4-byte and loses precision at
  epoch-second magnitudes.
* `INSERT OR IGNORE` becomes `INSERT ... ON CONFLICT DO NOTHING`, and `MAX(a, b)` in the
  one upsert becomes `GREATEST(a, b)`.
* Epoch-millisecond sequences use `BIGINT`; SQLite's `INTEGER` is already 64-bit, but
  PostgreSQL's is 32-bit.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager

from .db import MIGRATIONS, Clock

log = logging.getLogger("vexo.db.pg")

POSTGRES_PREFIXES = ("postgres://", "postgresql://")
MIGRATION_LOCK_KEY = 0x76657830  # "vex0"
WRITE_LOCK_KEY = 0x76657831

PG_MIGRATIONS = MIGRATIONS + [
    "ALTER TABLE sightings ALTER COLUMN sequence TYPE BIGINT;",
]


def is_postgres_url(value: str | None) -> bool:
    return bool(value) and value.strip().lower().startswith(POSTGRES_PREFIXES)


def database_url(configured: str | None = None) -> str | None:
    """DATABASE_URL always wins; a configured Postgres URL is the fallback."""
    url = os.environ.get("DATABASE_URL") or (configured if is_postgres_url(configured) else None)
    if not url:
        return None
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def translate(sql: str) -> str:
    """Rewrite SQLite-only SQL into PostgreSQL. Idempotent and safe for repeated calls."""
    out = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", sql, flags=re.I)
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", out, flags=re.I)

    insert_or_ignore = re.search(r"\bINSERT\s+OR\s+IGNORE\b", out, flags=re.I) is not None
    if insert_or_ignore:
        out = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", out, flags=re.I)

    # The only MAX(a, b) in the codebase is an upsert expression. PostgreSQL spells the
    # scalar two-argument form GREATEST; MAX is its aggregate.
    out = re.sub(
        r"\bMAX\s*\(\s*([A-Za-z_][\w.]*)\s*,\s*([A-Za-z_][\w.]*)\s*\)",
        r"GREATEST(\1, \2)",
        out,
        flags=re.I,
    )

    # The SQL in this project has no literal question marks; all are placeholders.
    out = out.replace("?", "%s")

    if insert_or_ignore:
        out = out.rstrip()
        if out.endswith(";"):
            out = out[:-1].rstrip()
        if "ON CONFLICT" not in out.upper():
            out += " ON CONFLICT DO NOTHING"
    return out


def _strip_comments(script: str) -> str:
    """Remove `--` comments while respecting single-quoted strings."""
    out: list[str] = []
    i, in_string = 0, False
    while i < len(script):
        char = script[i]
        if in_string:
            out.append(char)
            if char == "'":
                if i + 1 < len(script) and script[i + 1] == "'":
                    out.append(script[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if char == "'":
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "-" and i + 1 < len(script) and script[i + 1] == "-":
            newline = script.find("\n", i)
            if newline == -1:
                break
            out.append("\n")
            i = newline + 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def split_statements(script: str) -> list[str]:
    """Split a migration script on semicolons outside comments and quoted strings."""
    cleaned = _strip_comments(script)
    statements: list[str] = []
    buffer: list[str] = []
    i, in_string = 0, False
    while i < len(cleaned):
        char = cleaned[i]
        if in_string:
            buffer.append(char)
            if char == "'":
                if i + 1 < len(cleaned) and cleaned[i + 1] == "'":
                    buffer.append(cleaned[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if char == "'":
            in_string = True
            buffer.append(char)
            i += 1
            continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            i += 1
            continue
        buffer.append(char)
        i += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


class _Cursor:
    """Minimal cursor wrapper so callers can keep using `.fetchone()` and `.fetchall()`."""

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)

    @property
    def rowcount(self):
        return self._cursor.rowcount


class _Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, args=()):
        return _Cursor(self.raw.execute(translate(sql), tuple(args)))

    def close(self) -> None:
        self.raw.close()


class PostgresDatabase:
    """Same interface as `server.db.Database`, backed by one serialized PG connection."""

    backend = "postgresql"
    expected_version = len(PG_MIGRATIONS)

    def __init__(self, dsn: str, clock: Clock | None = None):
        import psycopg
        from psycopg.rows import dict_row

        self.dsn = dsn
        self.clock = clock or Clock()
        self.lock = threading.RLock()
        self.conn = _Connection(psycopg.connect(dsn, autocommit=True, row_factory=dict_row))
        self._migrate()

    def _migrate(self) -> None:
        raw = self.conn.raw
        with self.lock:
            raw.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
            try:
                raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
                row = raw.execute("SELECT version FROM schema_version").fetchone()
                current = int(row["version"]) if row else 0
                for number, script in enumerate(PG_MIGRATIONS, start=1):
                    if number <= current:
                        continue
                    raw.execute("BEGIN")
                    try:
                        for statement in split_statements(script):
                            raw.execute(translate(statement))
                        raw.execute("DELETE FROM schema_version")
                        raw.execute("INSERT INTO schema_version VALUES (%s)", (number,))
                        raw.execute("COMMIT")
                    except BaseException:
                        raw.execute("ROLLBACK")
                        raise
                    log.info("applied database migration %s", number)
            finally:
                raw.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))

    @contextmanager
    def tx(self):
        """One serialized write transaction. Yields the wrapped connection."""
        raw = self.conn.raw
        with self.lock:
            raw.execute("BEGIN")
            try:
                raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK_KEY,))
                yield self.conn
            except BaseException:
                raw.execute("ROLLBACK")
                raise
            else:
                raw.execute("COMMIT")

    def read(self, sql: str, args=()) -> list:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def now(self) -> float:
        return self.clock.now()

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def open_database(configured_path: str | None = None, clock: Clock | None = None):
    """Pick Postgres when DATABASE_URL is a Postgres DSN, otherwise keep SQLite."""
    dsn = database_url(configured_path)
    if dsn:
        return PostgresDatabase(dsn, clock)

    from .config import ROOT
    from .db import Database

    return Database(configured_path or str(ROOT / "server" / "vexo.db"), clock)


def readiness(db, expected_version: int | None = None) -> tuple[bool, dict]:
    """Sanitized readiness detail: no DSN, credentials or stack traces."""
    expected = expected_version if expected_version is not None else getattr(db, "expected_version", len(MIGRATIONS))
    try:
        row = db.one("SELECT version FROM schema_version")
        version = int(row["version"]) if row else 0
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        return False, {"status": "unavailable", "database": "error", "detail": type(exc).__name__}
    if version < expected:
        return False, {"status": "unavailable", "database": "migrating", "schema_version": version,
                       "expected_version": expected}
    return True, {"status": "ok", "database": "ok", "schema_version": version}
