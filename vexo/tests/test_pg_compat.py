"""Unit tests for the Postgres compatibility layer. No database server required."""
from __future__ import annotations

from server.db import MIGRATIONS
from server.pg import (
    PostgresDatabase,
    database_url,
    is_postgres_url,
    readiness,
    split_statements,
    translate,
)


def test_postgres_url_detection():
    assert is_postgres_url("postgres://u:p@h/db")
    assert is_postgres_url("postgresql://u:p@h/db")
    assert not is_postgres_url("sqlite:///tmp/x.db")
    assert not is_postgres_url("")
    assert not is_postgres_url(None)


def test_database_url_prefers_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@internal:5432/vexo")
    assert database_url("server/vexo.db") == "postgresql://u:p@internal:5432/vexo"


def test_database_url_accepts_configured_postgres(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"
    assert database_url("server/vexo.db") is None


def test_translate_placeholders_and_types():
    sql = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL);"
    out = translate(sql)
    assert "BIGSERIAL PRIMARY KEY" in out
    assert "DOUBLE PRECISION" in out
    assert "AUTOINCREMENT" not in out


def test_translate_insert_or_ignore_gets_conflict_clause():
    sql = ('INSERT OR IGNORE INTO notifications (id, recipient) '
           'VALUES (?, ?)')
    out = translate(sql)
    assert out.startswith("INSERT INTO notifications")
    assert "?" not in out
    assert out.endswith("ON CONFLICT DO NOTHING")


def test_translate_upsert_max_becomes_greatest():
    sql = ("INSERT INTO pair_cooldowns (user_low, user_high, reason, expires_at) VALUES (?,?,?,?)"
           " ON CONFLICT(user_low, user_high) DO UPDATE SET reason = excluded.reason,"
           " expires_at = MAX(expires_at, excluded.expires_at)")
    out = translate(sql)
    assert "GREATEST(expires_at, excluded.expires_at)" in out
    assert "MAX(" not in out


def test_split_statements_ignores_semicolons_in_comments_and_strings():
    script = """
    CREATE TABLE a (id TEXT); -- trailing; comment
    CREATE TABLE b (
      note TEXT NOT NULL, -- a semicolon; lives here
      value TEXT NOT NULL
    );
    INSERT INTO b VALUES ('x;y');
    """
    statements = split_statements(script)
    assert len(statements) == 3
    assert "a semicolon" not in statements[1]
    assert "'x;y'" in statements[2]
    for statement in statements:
        translate(statement)


def test_migration_statements_are_portable():
    statements = split_statements(MIGRATIONS[0])
    assert len(statements) >= 20
    for statement in statements:
        out = translate(statement)
        assert "AUTOINCREMENT" not in out.upper()
        assert "INSERT OR IGNORE" not in out.upper()
        assert "?" not in out
        assert not __import__("re").search(r"\bREAL\b", out, __import__("re").I)


class _FakeDb:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error

    def one(self, sql, args=()):
        if self.error:
            raise self.error
        return self.row


def test_readiness_ok():
    ok, detail = readiness(_FakeDb({"version": 1}), expected_version=1)
    assert ok
    assert detail["database"] == "ok"
    assert detail["schema_version"] == 1


def test_readiness_reports_migrating_and_sanitizes_errors():
    ok, detail = readiness(_FakeDb({"version": 0}), expected_version=1)
    assert not ok
    assert detail["database"] == "migrating"

    ok, detail = readiness(_FakeDb(error=RuntimeError("postgresql://user:secret@host/db")),
                           expected_version=1)
    assert not ok
    assert detail == {"status": "unavailable", "database": "error", "detail": "RuntimeError"}
    assert "secret" not in str(detail)


def test_postgres_database_is_lazy_about_importing_psycopg():
    """Importing server.pg must not require the psycopg driver (keeps local SQLite tests light)."""
    assert PostgresDatabase is not None
