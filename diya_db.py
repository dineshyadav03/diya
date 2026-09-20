import sqlite3
from datetime import datetime, timezone

DB_PATH = "diya.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (thread_id) REFERENCES threads(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            due_at TEXT,
            created_at TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


def add_reminder(content, due_at=None):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO reminders (content, due_at, created_at, done) VALUES (?, ?, ?, 0)",
        (content, due_at, now),
    )
    conn.commit()
    conn.close()


def list_reminders(include_done=False):
    conn = get_connection()
    query = "SELECT id, content, due_at, done FROM reminders"
    if not include_done:
        query += " WHERE done = 0"
    query += " ORDER BY id"
    rows = conn.execute(query).fetchall()
    conn.close()
    return rows


def complete_reminder(reminder_id):
    conn = get_connection()
    conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()


def create_thread(title=None):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute("INSERT INTO threads (title, created_at) VALUES (?, ?)", (title, now))
    conn.commit()
    thread_id = cur.lastrowid
    conn.close()
    return thread_id


def add_message(thread_id, role, content):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO messages (thread_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (thread_id, role, content, now),
    )
    conn.commit()
    conn.close()


def get_history(thread_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY id", (thread_id,)
    ).fetchall()
    conn.close()
    return [{"role": role, "content": content} for role, content in rows]


def list_threads():
    conn = get_connection()
    rows = conn.execute("SELECT id, title, created_at FROM threads ORDER BY id").fetchall()
    conn.close()
    return rows


def list_threads_with_preview():
    """Newest first, with a snippet of the first real message so threads are recognizable
    (titles are always blank right now -- nothing ever sets one)."""
    conn = get_connection()
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


def get_messages_since(message_id):
    """All messages across every thread with id > message_id, oldest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, thread_id, role, content FROM messages WHERE id > ? ORDER BY id",
        (message_id,),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "thread_id": r[1], "role": r[2], "content": r[3]} for r in rows]
