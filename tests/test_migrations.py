"""The migrations system in diya_db.py: a `migrations` table records which numbered, ordered
migrations have run. The three things this must prove:

1. a fresh database ends up correct (every table, every migration recorded);
2. a database from before this system existed (the three tables already there, no `migrations`
   table) upgrades cleanly, with its existing data untouched;
3. a database already at the latest migration is untouched by connecting again.

LEGACY_SCHEMA is a deliberate, frozen copy of the schema exactly as it shipped before migrations
existed (diya_db.py's own history, commit b3f6d92 onward). It must never be updated to track future
changes to diya_db.MIGRATIONS -- the whole point is to keep proving that a real pre-existing
diya.db, in the exact shape it was actually created in, still upgrades cleanly today.
"""
import sqlite3

import pytest

import diya_db
from diya_db import Store, apply_migrations

LEGACY_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (thread_id) REFERENCES threads(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        due_at TEXT,
        created_at TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0
    )
    """,
)


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(conn, table):
    return [(r[1], r[2], bool(r[3]), r[4], bool(r[5])) for r in conn.execute(f"PRAGMA table_info({table})")]


def migrations_rows(conn):
    return conn.execute("SELECT version, applied_at FROM migrations ORDER BY version").fetchall()


# --- 1. a fresh database ends up correct ------------------------------------------------------

def test_a_fresh_database_gets_every_table_and_records_migration_1(tmp_path):
    conn = sqlite3.connect(tmp_path / "fresh.db")
    applied = apply_migrations(conn)
    assert applied == [1]
    assert {"threads", "messages", "reminders", "migrations"} <= tables(conn)
    rows = migrations_rows(conn)
    assert [v for v, _ in rows] == [1]
    from datetime import datetime
    datetime.fromisoformat(rows[0][1])  # a real timestamp, not a placeholder


def test_a_fresh_database_has_exactly_the_expected_columns():
    """A behaviour-level pin, not a text diff: proves the actual schema migration 1 creates is
    unchanged, independent of how the CREATE TABLE strings happen to be formatted."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    assert columns(conn, "threads") == [
        ("id", "INTEGER", False, None, True),
        ("title", "TEXT", False, None, False),
        ("created_at", "TEXT", True, None, False),
    ]
    assert columns(conn, "messages") == [
        ("id", "INTEGER", False, None, True),
        ("thread_id", "INTEGER", True, None, False),
        ("role", "TEXT", True, None, False),
        ("content", "TEXT", True, None, False),
        ("created_at", "TEXT", True, None, False),
    ]
    assert columns(conn, "reminders") == [
        ("id", "INTEGER", False, None, True),
        ("content", "TEXT", True, None, False),
        ("due_at", "TEXT", False, None, False),
        ("created_at", "TEXT", True, None, False),
        ("done", "INTEGER", True, "0", False),
    ]


def test_a_fresh_store_used_through_its_normal_methods_also_gets_the_migrations_table(tmp_path):
    """The integration point that matters: Store.connect() is what every real caller uses."""
    store = Store(str(tmp_path / "used.db"))
    store.create_thread()
    conn = sqlite3.connect(tmp_path / "used.db")
    assert migrations_rows(conn) == [(1, migrations_rows(conn)[0][1])]


# --- 2. a database at the old, no-migrations-table state upgrades cleanly, data untouched --------

def _make_legacy_database(path):
    conn = sqlite3.connect(path)
    for ddl in LEGACY_SCHEMA:
        conn.execute(ddl)
    conn.execute("INSERT INTO threads (title, created_at) VALUES ('t1', '2026-01-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO messages (thread_id, role, content, created_at) VALUES (1, 'user', 'hi', '2026-01-01T00:00:01+00:00')"
    )
    conn.execute(
        "INSERT INTO reminders (content, due_at, created_at, done) VALUES ('call mom', NULL, '2026-01-01T00:00:02+00:00', 0)"
    )
    conn.commit()
    conn.close()


def test_an_old_database_with_no_migrations_table_gains_one_and_is_marked_current(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_database(path)
    assert "migrations" not in tables(sqlite3.connect(path))  # the premise: no tracking table yet

    conn = sqlite3.connect(path)
    applied = apply_migrations(conn)
    assert applied == [1]  # migration 1 is newly recorded, even though its tables already existed
    assert migrations_rows(conn) == [(1, migrations_rows(conn)[0][1])]


def test_an_old_databases_existing_data_survives_the_upgrade_byte_for_byte(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_database(path)
    before = {
        "threads": sqlite3.connect(path).execute("SELECT * FROM threads").fetchall(),
        "messages": sqlite3.connect(path).execute("SELECT * FROM messages").fetchall(),
        "reminders": sqlite3.connect(path).execute("SELECT * FROM reminders").fetchall(),
    }

    apply_migrations(sqlite3.connect(path))

    after_conn = sqlite3.connect(path)
    assert before["threads"] == after_conn.execute("SELECT * FROM threads").fetchall()
    assert before["messages"] == after_conn.execute("SELECT * FROM messages").fetchall()
    assert before["reminders"] == after_conn.execute("SELECT * FROM reminders").fetchall()


def test_an_old_database_upgraded_through_the_real_store_still_answers_normally(tmp_path):
    """Not just the raw tables -- the actual Store methods still work on an upgraded database."""
    path = tmp_path / "legacy.db"
    _make_legacy_database(path)
    store = Store(str(path))
    assert store.get_history(1) == [{"role": "user", "content": "hi"}]
    assert [r[1] for r in store.list_reminders()] == ["call mom"]
    new_id = store.create_thread()
    assert new_id == 2  # AUTOINCREMENT continues from the legacy data, not reset


# --- 3. a database already at the latest migration is untouched --------------------------------

def test_a_current_database_gets_nothing_newly_applied_the_second_time(tmp_path):
    conn = sqlite3.connect(tmp_path / "current.db")
    assert apply_migrations(conn) == [1]
    assert apply_migrations(conn) == []  # nothing left to do


def test_a_current_databases_migration_record_is_not_rewritten(tmp_path):
    conn = sqlite3.connect(tmp_path / "current.db")
    apply_migrations(conn)
    first = migrations_rows(conn)

    apply_migrations(conn)
    second = migrations_rows(conn)

    assert first == second  # same version, same applied_at -- never re-inserted or re-timestamped


def test_a_current_databases_data_is_unchanged_by_connecting_again(tmp_path):
    store = Store(str(tmp_path / "current.db"))
    t = store.create_thread("keep me")
    store.add_message(t, "user", "hello")
    before = (store.list_threads(), store.get_history(t))

    store.connect().close()  # another connection, migrations already applied
    store.connect().close()

    assert (store.list_threads(), store.get_history(t)) == before


class ExecuteSpy:
    """Wraps a real connection, recording every statement passed to execute() while still running
    it for real. sqlite3.Connection doesn't allow patching .execute directly on an instance (it is
    read-only), so apply_migrations is handed this instead -- it only ever calls .execute()."""

    def __init__(self, conn):
        self._conn = conn
        self.executed = []

    def execute(self, sql, *args):
        self.executed.append(" ".join(sql.split()))  # whitespace-normalized, so formatting can't matter
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_calling_apply_migrations_does_not_write_at_all_when_nothing_is_pending(tmp_path):
    """Stronger than "the result looks the same": no INSERT, and no CREATE TABLE for the app's
    own tables, is even attempted a second time -- verified by watching every SQL statement the
    connection actually runs, not just the end state."""
    conn = sqlite3.connect(tmp_path / "current.db")
    apply_migrations(conn)

    spy = ExecuteSpy(conn)
    applied = apply_migrations(spy)

    assert applied == []
    assert not any(sql.startswith("INSERT") for sql in spy.executed)
    for name in ("threads", "messages", "reminders"):
        assert not any(f"CREATE TABLE IF NOT EXISTS {name}" in sql for sql in spy.executed)
    assert len(spy.executed) == 2  # only the migrations-table bootstrap and the applied-versions read


# --- idempotency in general: running the whole thing twice changes nothing, on disk ------------

def test_running_migrations_twice_leaves_the_database_file_byte_identical(tmp_path):
    path = tmp_path / "idempotent.db"
    apply_migrations(sqlite3.connect(path))
    once = path.read_bytes()

    apply_migrations(sqlite3.connect(path))
    twice = path.read_bytes()

    assert once == twice


@pytest.mark.parametrize("times", [2, 3, 5])
def test_apply_migrations_is_idempotent_across_any_number_of_calls(tmp_path, times):
    conn = sqlite3.connect(tmp_path / "repeat.db")
    results = [apply_migrations(conn) for _ in range(times)]
    assert results == [[1]] + [[]] * (times - 1)
    assert len(migrations_rows(conn)) == 1


# --- the migrations table itself --------------------------------------------------------------

def test_migrations_are_declared_in_order_starting_at_1():
    versions = [v for v, _ in diya_db.MIGRATIONS]
    assert versions == sorted(versions) == list(range(1, len(versions) + 1))


def test_the_migrations_table_has_the_expected_shape():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    assert columns(conn, "migrations") == [
        ("version", "INTEGER", False, None, True),
        ("applied_at", "TEXT", True, None, False),
    ]
