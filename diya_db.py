import sqlite3
from datetime import datetime, timezone

import diya_config

# Migration 1 is the schema that has always existed here, unchanged: CREATE TABLE IF NOT EXISTS,
# so it is just as safe to run against a brand-new file as against a database that already has
# these tables from before this migrations system existed (see apply_migrations()). A shipped
# migration's SQL is never edited or removed -- a schema change is always a new, higher-numbered
# entry appended to this tuple, so what apply_migrations() already recorded as "applied" for an
# existing database stays a true description of what it actually ran.
MIGRATIONS = (
    (1, (
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
    )),
    # Migration 2: reviewed memory (docs/STAGE2_DESIGN.md, D3). `facts` is one row per fact with a
    # status; `fact_events` is the append-only trail of every change to it. Nothing reads either
    # table until diya_memory.py does, and nothing here touches an existing table.
    #
    # SQLite does not enforce FOREIGN KEY unless a connection asks (nothing here does), so the
    # reference below documents intent; diya_memory.Memory.verify_integrity() is what checks it.
    # `text_key` is the case-folded text: the identity used to refuse a second accepted copy of the
    # same fact. `source` and `event` are checked in code, not here, so a later stage can add a
    # value without rebuilding the table.
    (2, (
        """
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            text_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('candidate', 'accepted', 'rejected', 'retired')),
            source TEXT NOT NULL,
            batch_first INTEGER,
            batch_last INTEGER,
            position INTEGER,
            model TEXT,
            extracted_at TEXT,
            raw TEXT,
            flags TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        )
        """,
        # one row per (queue record, position in its facts list): what makes ingesting idempotent
        """
        CREATE UNIQUE INDEX IF NOT EXISTS facts_one_per_queue_slot
            ON facts (batch_first, position) WHERE source = 'dreaming'
        """,
        # at most one accepted fact per identity, whatever the code above it does
        """
        CREATE UNIQUE INDEX IF NOT EXISTS facts_one_accepted_per_key
            ON facts (text_key) WHERE status = 'accepted'
        """,
        """
        CREATE TABLE IF NOT EXISTS fact_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            actor TEXT NOT NULL,
            at TEXT NOT NULL,
            detail TEXT,
            FOREIGN KEY (fact_id) REFERENCES facts(id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS fact_events_by_fact ON fact_events (fact_id)",
    )),
)


def apply_migrations(conn):
    """Bring `conn`'s database up to the latest schema, recording which migrations have run in a
    `migrations` table (version, applied_at). Safe to call on every connection, not just the
    first:

    - A fresh database has no tables at all -- every migration runs, in order, from nothing.
    - A database from before this system existed has the three tables already, but no `migrations`
      table -- it gets created empty, migration 1 runs (a no-op for those three tables, since they
      already exist; CREATE TABLE IF NOT EXISTS never touches existing rows), and is then recorded
      as applied. No data is read, changed, or lost in the process.
    - A database already at the latest migration has every version recorded -- nothing in
      MIGRATIONS runs again, and nothing is written; migrating an up-to-date database is a no-op,
      not just a harmless repeat. That path never asks for the write lock, so it is never held up
      by someone else's write.

    Two processes can arrive at a database with a migration pending at the same moment -- the API
    and the scheduled Dreaming run both connect through here. So when something is pending the
    write lock is taken first (BEGIN IMMEDIATE), the applied versions are read again under it, and
    the pending migrations are applied in that one transaction: whoever gets the lock applies, the
    other waits (for the connection's busy timeout), then finds nothing left to do. A migration that
    fails part way is rolled back whole, not left half applied.

    Returns the version numbers newly applied, oldest first (empty if the database was already
    current) -- used by tests to tell these cases apart; nothing else needs it, since migrating is
    meant to be invisible in normal use.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = _applied_versions(conn)
    if all(version in applied for version, _ in MIGRATIONS):
        return []
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Look again: another connection may have applied some of these since the look above.
        applied = _applied_versions(conn)
        newly_applied = []
        for version, statements in MIGRATIONS:
            if version in applied:
                continue
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
            newly_applied.append(version)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return newly_applied


def _applied_versions(conn):
    return {row[0] for row in conn.execute("SELECT version FROM migrations")}


class Store:
    """Diya's SQLite storage, bound to one database file.

    Nothing is opened or created until the first call, and each call uses its
    own short-lived connection, as before. Passing the path explicitly (rather
    than reading a global) is what lets tests, evals and the web app each use
    their own database.
    """

    def __init__(self, path):
        self.path = path

    def connect(self):
        conn = sqlite3.connect(self.path)
        apply_migrations(conn)
        return conn

    def add_reminder(self, content, due_at=None):
        conn = self.connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO reminders (content, due_at, created_at, done) VALUES (?, ?, ?, 0)",
            (content, due_at, now),
        )
        conn.commit()
        conn.close()

    def list_reminders(self, include_done=False):
        conn = self.connect()
        query = "SELECT id, content, due_at, done FROM reminders"
        if not include_done:
            query += " WHERE done = 0"
        query += " ORDER BY id"
        rows = conn.execute(query).fetchall()
        conn.close()
        return rows

    def complete_reminder(self, reminder_id):
        conn = self.connect()
        conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
        conn.commit()
        conn.close()

    def create_thread(self, title=None):
        conn = self.connect()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute("INSERT INTO threads (title, created_at) VALUES (?, ?)", (title, now))
        conn.commit()
        thread_id = cur.lastrowid
        conn.close()
        return thread_id

    def add_message(self, thread_id, role, content):
        conn = self.connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO messages (thread_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, role, content, now),
        )
        conn.commit()
        conn.close()

    def get_history(self, thread_id):
        conn = self.connect()
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY id", (thread_id,)
        ).fetchall()
        conn.close()
        return [{"role": role, "content": content} for role, content in rows]

    def list_threads(self):
        conn = self.connect()
        rows = conn.execute("SELECT id, title, created_at FROM threads ORDER BY id").fetchall()
        conn.close()
        return rows

    def list_threads_with_preview(self):
        """Newest first, with a snippet of the first real message so threads are recognizable
        (titles are always blank right now -- nothing ever sets one)."""
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT t.id, t.created_at,
                   (SELECT content FROM messages m
                    WHERE m.thread_id = t.id AND m.role = 'user'
                    ORDER BY m.id LIMIT 1) AS preview
            FROM threads t
            ORDER BY t.id DESC
            """
        ).fetchall()
        conn.close()
        return [{"id": r[0], "created_at": r[1], "preview": r[2] or "(empty thread)"} for r in rows]

    def get_messages_since(self, message_id):
        """All messages across every thread with id > message_id, oldest first."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT id, thread_id, role, content FROM messages WHERE id > ? ORDER BY id",
            (message_id,),
        ).fetchall()
        conn.close()
        return [{"id": r[0], "thread_id": r[1], "role": r[2], "content": r[3]} for r in rows]


# --- Module-level functions ---------------------------------------------------
# Kept so scripts that just `import diya_db` (dreaming.py, diya_chat.py) work
# unchanged. Each call resolves the database from DIYA_DB_PATH (default
# "diya.db" in the working directory, exactly as before).

def _default_store():
    return Store(diya_config.load_config().db_path)


def get_connection():
    return _default_store().connect()


def add_reminder(content, due_at=None):
    return _default_store().add_reminder(content, due_at)


def list_reminders(include_done=False):
    return _default_store().list_reminders(include_done)


def complete_reminder(reminder_id):
    return _default_store().complete_reminder(reminder_id)


def create_thread(title=None):
    return _default_store().create_thread(title)


def add_message(thread_id, role, content):
    return _default_store().add_message(thread_id, role, content)


def get_history(thread_id):
    return _default_store().get_history(thread_id)


def list_threads():
    return _default_store().list_threads()


def list_threads_with_preview():
    return _default_store().list_threads_with_preview()


def get_messages_since(message_id):
    return _default_store().get_messages_since(message_id)
