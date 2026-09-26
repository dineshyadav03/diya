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
from unittest import mock

import pytest

import diya_db
from diya_db import Store, apply_migrations

# Every migration the real code ships, and just the first. The tests below that are about ONE
# migration (the original schema) or about racing for a migration (section 4) do not care how many
# there are, so adding a migration never breaks them.
REAL_VERSIONS = [v for v, _ in diya_db.MIGRATIONS]
MIGRATION_1 = diya_db.MIGRATIONS[:1]

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

def test_a_fresh_database_gets_every_table_and_records_every_migration(tmp_path):
    conn = sqlite3.connect(tmp_path / "fresh.db")
    applied = apply_migrations(conn)
    assert applied == REAL_VERSIONS
    assert {"threads", "messages", "reminders", "facts", "fact_events", "migrations"} <= tables(conn)
    rows = migrations_rows(conn)
    assert [v for v, _ in rows] == REAL_VERSIONS
    from datetime import datetime
    for _, applied_at in rows:
        datetime.fromisoformat(applied_at)  # a real timestamp, not a placeholder


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
        ("due_ts", "TEXT", False, None, False),  # migration 3: a real due time beside the words
        ("notified_at", "TEXT", False, None, False),
    ]


def test_a_fresh_store_used_through_its_normal_methods_also_gets_the_migrations_table(tmp_path):
    """The integration point that matters: Store.connect() is what every real caller uses."""
    store = Store(str(tmp_path / "used.db"))
    store.create_thread()
    conn = sqlite3.connect(tmp_path / "used.db")
    assert [v for v, _ in migrations_rows(conn)] == REAL_VERSIONS


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
    assert applied == REAL_VERSIONS  # migration 1 is newly recorded, even though its tables already existed
    assert [v for v, _ in migrations_rows(conn)] == REAL_VERSIONS


def test_an_old_databases_existing_data_survives_the_upgrade_byte_for_byte(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_database(path)
    before = {
        "threads": sqlite3.connect(path).execute("SELECT * FROM threads").fetchall(),
        "messages": sqlite3.connect(path).execute("SELECT * FROM messages").fetchall(),
        "reminders": sqlite3.connect(path).execute("SELECT id, content, due_at, created_at, done FROM reminders").fetchall(),
    }

    apply_migrations(sqlite3.connect(path))

    after_conn = sqlite3.connect(path)
    assert before["threads"] == after_conn.execute("SELECT * FROM threads").fetchall()
    assert before["messages"] == after_conn.execute("SELECT * FROM messages").fetchall()
    assert before["reminders"] == after_conn.execute("SELECT id, content, due_at, created_at, done FROM reminders").fetchall()
    # migration 3 added two columns; a reminder from before it has no real due time and was never told
    assert after_conn.execute("SELECT due_ts, notified_at FROM reminders").fetchall() == [(None, None)] * len(before["reminders"])


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
    assert apply_migrations(conn) == REAL_VERSIONS
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
    assert results == [REAL_VERSIONS] + [[]] * (times - 1)
    assert len(migrations_rows(conn)) == len(REAL_VERSIONS)


# --- 4. two connections migrating the same database at the same moment ---------------------------
# The API and the scheduled Dreaming process both call apply_migrations on every connection, so the
# first migration after a code change is applied by whichever connects first -- and sometimes both
# do. Measured before this was fixed: two simultaneous migrators on a fresh file, 5 of 150 rounds one
# of them raised "UNIQUE constraint failed: migrations.version" (the database itself came out right).
# These tests interleave the two connections deterministically instead of hoping to hit the window.

SECOND_MIGRATION = (2, ("CREATE TABLE IF NOT EXISTS extra (id INTEGER PRIMARY KEY)",))


@pytest.fixture
def two_migrations(monkeypatch):
    """Migration 1 plus a stand-in second one, so there is something for a second connection to race
    for. Deliberately not "the real list plus one": the real list grows."""
    monkeypatch.setattr(diya_db, "MIGRATIONS", MIGRATION_1 + (SECOND_MIGRATION,))


def _database_at_migration_1(path):
    """A database that has only ever seen migration 1, whatever else the real code has since added."""
    conn = sqlite3.connect(path)
    with mock.patch.object(diya_db, "MIGRATIONS", MIGRATION_1):
        assert apply_migrations(conn) == [1]
    conn.close()


def _versions(path):
    conn = sqlite3.connect(path)
    try:
        return [v for v, _ in migrations_rows(conn)]
    finally:
        conn.close()


def test_a_second_connection_arriving_mid_migration_never_makes_either_of_them_fail(tmp_path, monkeypatch):
    """A rival connection is let in at the worst moment: after the first connection has decided
    migration 2 is pending, and before it has recorded it. Before the fix the rival applied and
    recorded migration 2 in that gap and the first connection's own INSERT then raised
    IntegrityError. The interleave is forced with an SQL function that a migration statement calls."""
    path = str(tmp_path / "race.db")
    _database_at_migration_1(path)
    rival_result = {}

    def rival():
        other = sqlite3.connect(path, timeout=0)  # give up at once if the file is locked
        other.create_function("rival", 0, lambda: 0)  # migration 2 calls it on this connection too; here it does nothing
        try:
            rival_result["applied"] = apply_migrations(other)
        except sqlite3.OperationalError as exc:  # "database is locked": the first connection holds it
            rival_result["blocked"] = str(exc)
        finally:
            other.close()
        return 0

    first = sqlite3.connect(path)
    first.create_function("rival", 0, rival)
    monkeypatch.setattr(
        diya_db, "MIGRATIONS",
        MIGRATION_1 + ((2, ("SELECT rival()",) + SECOND_MIGRATION[1]),),
    )

    mine = apply_migrations(first)  # must not raise

    assert rival_result, "the rival never ran, so nothing was interleaved"
    assert sorted(mine + rival_result.get("applied", [])) == [2]  # exactly one of them applied it
    assert _versions(path) == [1, 2]
    assert "extra" in tables(sqlite3.connect(path))


def test_a_migration_another_connection_finished_after_the_first_look_is_not_applied_again(tmp_path, two_migrations):
    """The other gap: the rival finishes between "migration 2 is pending" and taking the lock. The
    first connection has to look again once it holds the lock, or it applies migration 2 a second
    time. The rival is let in by a trace hook on the statement that takes the lock."""
    path = str(tmp_path / "race.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("INSERT INTO migrations (version, applied_at) VALUES (1, '2026-01-01T00:00:00+00:00')")
    for ddl in LEGACY_SCHEMA:
        conn.execute(ddl)
    conn.commit()
    rival_applied = []
    hook_fired = []

    def on_statement(sql):
        if sql.lstrip().upper().startswith("BEGIN") and not hook_fired:
            hook_fired.append(sql)
            other = sqlite3.connect(path, timeout=0)
            try:
                rival_applied.extend(apply_migrations(other))
            finally:
                other.close()

    conn.set_trace_callback(on_statement)

    mine = apply_migrations(conn)  # must not raise

    conn.set_trace_callback(None)
    assert hook_fired, "no BEGIN was issued, so the rival was never let in between the look and the lock"
    assert rival_applied == [2] and mine == []  # the rival got there first, and this one found nothing left
    assert _versions(path) == [1, 2]


def test_the_write_lock_is_held_from_the_first_statement_until_the_version_is_recorded(tmp_path, monkeypatch):
    """The property the two tests above rely on, checked directly: at each point where a rival could
    slip in, ask a second connection whether it can take the write lock. It must not be able to --
    while a migration's statements run, and at the moment the version is about to be recorded. (A
    deferred BEGIN holds no write lock yet at the first point; a commit before the INSERT has
    released it at the second.)"""
    path = str(tmp_path / "lock.db")
    _database_at_migration_1(path)
    probes = []

    def lock_is_free():
        other = sqlite3.connect(path, timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
            return True
        except sqlite3.OperationalError:  # "database is locked": the connection under test holds it
            return False
        finally:
            other.close()

    def probe():
        probes.append(("while a statement runs", lock_is_free()))
        return 0

    first = sqlite3.connect(path)
    first.create_function("probe", 0, probe)

    def on_statement(sql):
        if sql.lstrip().startswith("INSERT INTO migrations"):
            probes.append(("as the version is recorded", lock_is_free()))

    first.set_trace_callback(on_statement)
    monkeypatch.setattr(
        diya_db, "MIGRATIONS",
        MIGRATION_1 + ((2, ("SELECT probe()",) + SECOND_MIGRATION[1]),),
    )

    assert apply_migrations(first) == [2]

    first.set_trace_callback(None)
    assert probes == [("while a statement runs", False), ("as the version is recorded", False)]


def test_an_up_to_date_database_is_never_held_up_by_someone_elses_write(tmp_path):
    """The fast path must not need the write lock: every Store call connects, and most of them find
    nothing to do. Someone else holding a write transaction must not stall them."""
    path = str(tmp_path / "busy.db")
    current = sqlite3.connect(path)
    assert apply_migrations(current) == REAL_VERSIONS  # every real migration: nothing left pending
    current.close()
    writer = sqlite3.connect(path)
    writer.execute("BEGIN IMMEDIATE")
    try:
        reader = sqlite3.connect(path, timeout=0)
        assert apply_migrations(reader) == []  # returns at once instead of "database is locked"
        reader.close()
    finally:
        writer.rollback()
        writer.close()


def test_a_migration_that_fails_part_way_is_not_half_applied(tmp_path, monkeypatch):
    path = str(tmp_path / "broken.db")
    _database_at_migration_1(path)
    monkeypatch.setattr(
        diya_db, "MIGRATIONS",
        MIGRATION_1 + ((2, ("CREATE TABLE IF NOT EXISTS half (id INTEGER)", "THIS IS NOT SQL")),),
    )
    conn = sqlite3.connect(path)

    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn)

    assert not conn.in_transaction  # nothing left open to hold the lock
    assert "half" not in tables(conn)  # the statement that did run was undone with the rest
    assert _versions(path) == [1]  # and migration 2 was not recorded as applied
    other = sqlite3.connect(path, timeout=0)
    other.execute("CREATE TABLE probe (id INTEGER)")  # the file is writable again
    other.close()


def test_many_pairs_of_simultaneous_migrators_never_raise(tmp_path, two_migrations):
    """The measurement that found the problem, kept as a backstop. Each round is a brand new file
    and two threads that start together; on the unfixed code about 1 round in 30 raised."""
    import threading

    errors = []
    for round_no in range(60):
        path = str(tmp_path / f"round{round_no}.db")
        barrier = threading.Barrier(2)

        def worker():
            try:
                conn = sqlite3.connect(path)
                barrier.wait()
                apply_migrations(conn)
                conn.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert _versions(path) == [1, 2]
    assert errors == []


# --- 5. migration 2: the tables reviewed memory lives in (docs/STAGE2_DESIGN.md, D3) ----------------

def test_migration_2_creates_the_fact_tables_with_exactly_the_expected_columns():
    """A behaviour-level pin of the shipped schema, like the one for migration 1. Once migration 2 has
    run on a real database it is never edited: a change is migration 3."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    assert columns(conn, "facts") == [
        ("id", "INTEGER", False, None, True),
        ("text", "TEXT", True, None, False),
        ("text_key", "TEXT", True, None, False),
        ("status", "TEXT", True, None, False),
        ("source", "TEXT", True, None, False),
        ("batch_first", "INTEGER", False, None, False),
        ("batch_last", "INTEGER", False, None, False),
        ("position", "INTEGER", False, None, False),
        ("model", "TEXT", False, None, False),
        ("extracted_at", "TEXT", False, None, False),
        ("raw", "TEXT", False, None, False),
        ("flags", "TEXT", True, "'[]'", False),
        ("created_at", "TEXT", True, None, False),
    ]
    assert columns(conn, "fact_events") == [
        ("id", "INTEGER", False, None, True),
        ("fact_id", "INTEGER", True, None, False),
        ("event", "TEXT", True, None, False),
        ("actor", "TEXT", True, None, False),
        ("at", "TEXT", True, None, False),
        ("detail", "TEXT", False, None, False),
    ]


def _insert_fact(conn, text, status="candidate", source="dreaming", batch_first=None, position=None):
    conn.execute(
        "INSERT INTO facts (text, text_key, status, source, batch_first, position, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'now')",
        (text, text.casefold(), status, source, batch_first, position),
    )


def test_the_status_column_refuses_anything_but_the_four_statuses():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    for status in ("candidate", "accepted", "rejected", "retired"):
        _insert_fact(conn, f"fact {status}", status=status, source="manual")
    for bad in ("pending", "ACCEPTED", "", "accepted "):
        with pytest.raises(sqlite3.IntegrityError):
            _insert_fact(conn, f"fact {bad!r}", status=bad, source="manual")


def test_a_queue_slot_can_be_recorded_only_once_but_other_sources_are_not_held_to_it():
    """(batch_first, position) identifies a staged fact, which is what makes ingesting twice harmless.
    It constrains only rows that came from the queue: the old profile's lines and typed facts have no
    slot, and must not collide with each other."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    _insert_fact(conn, "first", batch_first=7, position=0)
    _insert_fact(conn, "second", batch_first=7, position=1)  # same record, next position
    _insert_fact(conn, "third", batch_first=9, position=0)  # next record, same position
    with pytest.raises(sqlite3.IntegrityError):
        _insert_fact(conn, "again", batch_first=7, position=0)
    for n in range(3):  # no slot: any number of these
        _insert_fact(conn, f"typed {n}", source="manual")
        _insert_fact(conn, f"imported {n}", source="legacy_profile")


def test_only_one_accepted_fact_can_have_a_given_identity_but_other_statuses_can_repeat():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    _insert_fact(conn, "Likes tea", status="accepted", source="manual")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_fact(conn, "likes tea", status="accepted", source="manual")  # same fact, other capitals
    for status in ("candidate", "rejected", "retired"):
        _insert_fact(conn, "likes tea", status=status, source="manual")  # a repeat is not accepted yet
    _insert_fact(conn, "likes coffee", status="accepted", source="manual")


def test_the_fact_tables_start_empty_and_an_old_databases_own_rows_are_untouched(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_database(path)
    apply_migrations(sqlite3.connect(path))
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM fact_events").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone() == (1,)  # and the old data is still there


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
