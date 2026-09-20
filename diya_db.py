import sqlite3
from datetime import datetime, timezone

import diya_config

_SCHEMA = (
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
        for ddl in _SCHEMA:
            conn.execute(ddl)
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
