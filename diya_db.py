import re
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
    # Migration 3 (docs/PROACTIVITY_DESIGN.md, D1): a real due time beside the words. `due_at` stays what the
    # person said ("Friday 5pm"), which nothing can act on; `due_ts` is that read as a UTC instant
    # (2026-09-25T11:30:00Z), null for a reminder with no time and for every reminder saved before this, which
    # therefore never become "due". `notified_at` is when the person was told, so a reminder is told once.
    (3, (
        "ALTER TABLE reminders ADD COLUMN due_ts TEXT",
        "ALTER TABLE reminders ADD COLUMN notified_at TEXT",
        "CREATE INDEX IF NOT EXISTS reminders_pending_due ON reminders (due_ts) WHERE done = 0 AND due_ts IS NOT NULL",
    )),
    # Migration 4 (docs/PERSON_MEMORY_DESIGN.md, D1): who a fact is about. `people.name_key` is the case-folded
    # identity (like `facts.text_key`); a fact's `person_id` is null for "self" (the user), which is not a row
    # here at all -- most facts are about the user, so the common case needs no join target. A merge
    # (docs/PERSON_MEMORY_DESIGN.md, D3) re-tags facts; it never deletes a `people` row, so a person with no
    # facts left after one is a record that a merge happened, not an error.
    (4, (
        """
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS people_one_per_key ON people (name_key)",
        "ALTER TABLE facts ADD COLUMN person_id INTEGER REFERENCES people(id)",
        "CREATE INDEX IF NOT EXISTS facts_by_person ON facts (person_id)",
    )),
    # Migration 5 (docs/ACTIONS_DESIGN.md, D3): the approval gate and its trail. `actions` is one row per thing
    # the model proposed to do outside this database; `action_events` is the append-only record of everything
    # that happened to it and who did it (the model proposed, the owner decided, the system ran it) -- the same
    # row-plus-events shape as `facts`/`fact_events`. `args` is canonical JSON and `args_hash` its digest, so an
    # approval can be bound to exactly what was shown. Times are UTC text like 2026-10-04T10:15:00Z, so comparing
    # them as text compares them in time. Nothing reads these tables until diya_actions.py does.
    (5, (
        """
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            args TEXT NOT NULL,
            args_hash TEXT NOT NULL,
            summary TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN
                ('pending', 'approved', 'executing', 'succeeded', 'failed', 'rejected', 'expired', 'unknown')),
            thread_id INTEGER,
            message_id INTEGER,
            tainted INTEGER NOT NULL DEFAULT 0 CHECK (tainted IN (0, 1)),
            taint_sources TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            decided_at TEXT,
            executed_at TEXT,
            result TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS actions_by_status ON actions (status)",
        "CREATE INDEX IF NOT EXISTS actions_by_message ON actions (message_id)",
        # the same thing cannot be waiting twice, whatever the code above it does
        """
        CREATE UNIQUE INDEX IF NOT EXISTS actions_one_pending_per_hash
            ON actions (kind, args_hash) WHERE status = 'pending'
        """,
        """
        CREATE TABLE IF NOT EXISTS action_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            actor TEXT NOT NULL,
            at TEXT NOT NULL,
            detail TEXT,
            FOREIGN KEY (action_id) REFERENCES actions(id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS action_events_by_action ON action_events (action_id)",
    )),
    # Migration 6 (docs/TASKS_DESIGN.md, D1): a to-do list in Diya's own database. The same shape as `reminders` --
    # `due_at` is the person's words for when, `due_ts` that read as a UTC instant (null when it could not be read) --
    # but a task has no notification: nothing tells you, it waits to be looked at. `content_key` is the case-folded
    # text, the identity used to refuse a second OPEN copy of the same task; a done task frees its words again.
    # `source` is where it came from; `thread_id`/`message_id` are the chat and message a task from chat answered.
    # Times are UTC text like 2026-10-05T10:15:00Z. Nothing reads this table until diya_tasks.py does.
    (6, (
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            content_key TEXT NOT NULL,
            due_at TEXT,
            due_ts TEXT,
            done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1)),
            source TEXT NOT NULL CHECK (source IN ('chat', 'page')),
            thread_id INTEGER,
            message_id INTEGER,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS tasks_one_open_per_key ON tasks (content_key) WHERE done = 0",
        "CREATE INDEX IF NOT EXISTS tasks_by_done ON tasks (done)",
    )),
    # Migration 7 (docs/SCHEDULE_DESIGN.md, D1 and D5): reminders that repeat. A `reminder_series` row is the definition of a
    # repeating reminder (its words, its rule as canonical text -- see diya_repeat -- and when it next falls); when that time
    # comes it makes an ordinary row in `reminders` (carrying `series_id`), so nothing about due, told or done changes.
    # `content_key` is the case-folded words, the identity used to refuse the same series twice. `schedule_events` is the
    # append-only trail of everything that happens to a series or one of its reminders and who did it. Times are UTC text.
    (7, (
        """
        CREATE TABLE IF NOT EXISTS reminder_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            content_key TEXT NOT NULL,
            rule TEXT NOT NULL,
            said TEXT,
            next_ts TEXT,
            paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
            ended INTEGER NOT NULL DEFAULT 0 CHECK (ended IN (0, 1)),
            source TEXT NOT NULL CHECK (source IN ('chat', 'page')),
            thread_id INTEGER,
            message_id INTEGER,
            created_at TEXT NOT NULL,
            ended_at TEXT
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS series_one_active_per_key ON reminder_series (content_key, rule) WHERE ended = 0",
        "ALTER TABLE reminders ADD COLUMN series_id INTEGER REFERENCES reminder_series(id)",
        "CREATE INDEX IF NOT EXISTS reminders_by_series ON reminders (series_id) WHERE series_id IS NOT NULL",
        """
        CREATE TABLE IF NOT EXISTS schedule_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER,
            reminder_id INTEGER,
            event TEXT NOT NULL,
            actor TEXT NOT NULL,
            at TEXT NOT NULL,
            detail TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS schedule_events_by_series ON schedule_events (series_id)",
    )),
)

MOMENT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")  # how a due time is stored
REMINDER_FIELDS = ("id", "content", "due_at", "due_ts", "done", "created_at", "notified_at")


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

    def add_reminder(self, content, due_at=None, due_ts=None):
        """Save a reminder and return its id. `due_at` is the person's own words for when; `due_ts` is the
        moment they were read as, in UTC as text like 2026-09-25T11:30:00Z (diya_time's When.iso()), or None
        for a reminder with no time."""
        if due_ts is not None and not (isinstance(due_ts, str) and MOMENT.fullmatch(due_ts)):
            raise ValueError(f"due_ts must look like 2026-09-25T11:30:00Z, got {due_ts!r}")
        conn = self.connect()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO reminders (content, due_at, due_ts, created_at, done) VALUES (?, ?, ?, ?, 0)",
            (content, due_at, due_ts, now),
        )
        conn.commit()
        reminder_id = cur.lastrowid
        conn.close()
        return reminder_id

    def reminders(self, state="pending"):
        """Reminders as dicts (id, content, due_at, due_ts, done, created_at, notified_at), oldest first.
        `state` is 'pending' (not done), 'done' or 'all'."""
        if state not in ("pending", "done", "all"):
            raise ValueError(f"state must be pending, done or all, got {state!r}")
        query = "SELECT id, content, due_at, due_ts, done, created_at, notified_at FROM reminders"
        if state != "all":
            query += f" WHERE done = {1 if state == 'done' else 0}"
        conn = self.connect()
        rows = conn.execute(query + " ORDER BY id").fetchall()
        conn.close()
        return [dict(zip(REMINDER_FIELDS, row)) for row in rows]

    def get_reminder(self, reminder_id):
        """One reminder as a dict (see `reminders`), or None."""
        conn = self.connect()
        row = conn.execute(
            "SELECT id, content, due_at, due_ts, done, created_at, notified_at FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        conn.close()
        return dict(zip(REMINDER_FIELDS, row)) if row else None

    def due_reminders(self, now_ts, unnotified_only=False):
        """Pending reminders whose time has come, soonest first. `now_ts` is UTC text as in `add_reminder`.
        A reminder with no real time (`due_ts` null) is never due: nothing can say when."""
        if not (isinstance(now_ts, str) and MOMENT.fullmatch(now_ts)):
            raise ValueError(f"now_ts must look like 2026-09-25T11:30:00Z, got {now_ts!r}")
        query = (
            "SELECT id, content, due_at, due_ts, done, created_at, notified_at FROM reminders "
            "WHERE done = 0 AND due_ts IS NOT NULL AND due_ts <= ?"
        )
        if unnotified_only:
            query += " AND notified_at IS NULL"
        conn = self.connect()
        rows = conn.execute(query + " ORDER BY due_ts, id", (now_ts,)).fetchall()
        conn.close()
        return [dict(zip(REMINDER_FIELDS, row)) for row in rows]

    def mark_notified(self, reminder_id, at=None):
        """Record that the person has been told about a reminder, once: returns True if this call did it,
        False if it was already recorded, done, or does not exist."""
        conn = self.connect()
        cur = conn.execute(
            "UPDATE reminders SET notified_at = ? WHERE id = ? AND done = 0 AND notified_at IS NULL",
            (at or datetime.now(timezone.utc).isoformat(), reminder_id),
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

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
        """Mark a reminder done. Returns True if this call did it, False if it was already done or is not there."""
        conn = self.connect()
        cur = conn.execute("UPDATE reminders SET done = 1 WHERE id = ? AND done = 0", (reminder_id,))
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

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
        cur = conn.execute(
            "INSERT INTO messages (thread_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, role, content, now),
        )
        conn.commit()
        message_id = cur.lastrowid
        conn.close()
        return message_id

    def get_history(self, thread_id):
        conn = self.connect()
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY id", (thread_id,)
        ).fetchall()
        conn.close()
        return [{"role": role, "content": content} for role, content in rows]

    def get_messages(self, thread_id):
        """One thread's messages, oldest first, each with its id: what get_history returns, plus the ids that say which
        message is which (the chat route needs them to tell a retry of an unanswered message from a new one)."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT id, role, content FROM messages WHERE thread_id = ? ORDER BY id", (thread_id,)
        ).fetchall()
        conn.close()
        return [{"id": row_id, "role": role, "content": content} for row_id, role, content in rows]

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

    def get_messages_between(self, first_id, last_id):
        """All messages across every thread with first_id <= id <= last_id (both ends included), oldest
        first: the messages a batch of staged facts was extracted from. Read-only."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT id, thread_id, role, content FROM messages WHERE id BETWEEN ? AND ? ORDER BY id",
            (first_id, last_id),
        ).fetchall()
        conn.close()
        return [{"id": r[0], "thread_id": r[1], "role": r[2], "content": r[3]} for r in rows]

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


def add_reminder(content, due_at=None, due_ts=None):
    return _default_store().add_reminder(content, due_at, due_ts)


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
