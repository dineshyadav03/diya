import os
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
    # 8: the messages memory took in the moment they were said (docs/AUTO_MEMORY_DESIGN.md, D7 and unit A4): one row for each message that
    # was read for facts live, so the scheduled Dreaming pass does not read it a second time. `facts` is how many candidates it made.
    (8, (
        """
        CREATE TABLE IF NOT EXISTS memory_captures (
            message_id INTEGER PRIMARY KEY,
            at TEXT NOT NULL,
            facts INTEGER NOT NULL
        )
        """,
    )),
    # 9: the questions Diya raises herself (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5). One row for each fact and kind of question, ever (UNIQUE), so a fact is never
    # asked about twice in the same way. `shown_at` starts the day after which an unanswered question counts as ignored, `wait_until` is the three days it then waits,
    # `notified_at` is when the desktop notifier told the person there is a question (once). `detail` is JSON made by code: the fact a waiting fact may replace, the time
    # an offer is for. Times are UTC text.
    (9, (
        """
        CREATE TABLE IF NOT EXISTS memory_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('doubt', 'conflict', 'sensitive', 'stale', 'offer')),
            state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'answered', 'dropped')),
            created_at TEXT NOT NULL,
            shown_at TEXT,
            ignores INTEGER NOT NULL DEFAULT 0,
            wait_until TEXT,
            notified_at TEXT,
            answered_at TEXT,
            answer TEXT,
            detail TEXT,
            UNIQUE (fact_id, kind)
        )
        """,
        "CREATE INDEX IF NOT EXISTS memory_questions_by_state ON memory_questions (state)",
    )),
    # 10: who has been told what, on a channel other than the desktop toast (docs/PUSH_DESIGN.md, section 3). One row for each channel and event key, ever (UNIQUE), recorded only
    # after the channel ACCEPTED the message. `batch` is the first key of the message the row was part of ("3 more reminders" is one message and three rows), so a rate limit
    # counts messages and not events. Times are UTC text.
    (10, (
        """
        CREATE TABLE IF NOT EXISTS event_deliveries (
            channel TEXT NOT NULL,
            key TEXT NOT NULL,
            batch TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (channel, key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS event_deliveries_by_time ON event_deliveries (channel, sent_at)",
    )),
    # 11: the devices that asked to be told by Web Push (docs/PUSH_DESIGN.md, section 4). `endpoint` is a bearer URL for pushing to that device: it is never returned by any route
    # and never logged. `failures` counts consecutive refusals of Diya's request; at five the subscription is removed.
    (11, (
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_ok_at TEXT,
            failures INTEGER NOT NULL DEFAULT 0
        )
        """,
    )),
    # 12: the Telegram bridge's own small notes (docs/TELEGRAM_DESIGN.md, section 3): the paired owner's id, the last update handled, the thread its messages go in, and, while pairing,
    # the hash of the one-time code, when it expires and how many wrong guesses it has had. The bot token is NOT here: it is in its own file.
    (12, (
        "CREATE TABLE IF NOT EXISTS telegram_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    )),
    # 13: what Diya said first (docs/PROACTIVE_DESIGN.md): one row for each message she wrote on her own, in the chat's own messages table (`message_id`) and here, with a `key` that is
    # unique so the same good-morning is never said twice in a day. `seen_at` is when the person looked at it (it is then no longer waiting on the chat page) and `toasted_at` when the
    # desktop notifier put it on the screen.
    (13, (
        """
        CREATE TABLE IF NOT EXISTS proactive_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            thread_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            seen_at TEXT,
            toasted_at TEXT
        )
        """,
    )),
    # 14: things Diya does on a schedule, for the person (docs/AUTOMATIONS_DESIGN.md): what to do in the person's own words (`instruction`), when in their words (`words`) and as a rule
    # (`rule`, diya_repeat's text form), whether it is `active` or `paused`, the next time it falls (`next_ts`, stored like every moment here, UTC), and how the last run went.
    (14, (
        """
        CREATE TABLE IF NOT EXISTS automations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instruction TEXT NOT NULL,
            words TEXT NOT NULL,
            rule TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'paused')),
            next_ts TEXT NOT NULL,
            last_run_at TEXT,
            last_status TEXT,
            runs INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
    )),
    # 15: when a reminder was ticked off (docs/PROACTIVITY_DESIGN.md, "Reminders that were done"). Until now `done` was all that was kept, so "when did I buy the guitar strings?" could not be answered by
    # anything: the reminder was marked done and then forgotten. Stored like every other moment here (UTC, ...Z). A reminder done before this has none, and says so; so does one that a repeating
    # series closed when the next came, which was never ticked off.
    (15, (
        "ALTER TABLE reminders ADD COLUMN done_at TEXT",
    )),
    # 16: the embedding of each accepted fact, for relevance recall (docs/RECALL_DESIGN.md): one row per fact and embedding model, with the fact's text_key so a fact whose words changed is embedded again.
    # The vector is JSON text. Nothing here is ever sent anywhere, and a row can always be made again from the fact.
    (16, (
        """
        CREATE TABLE IF NOT EXISTS fact_embeddings (
            fact_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            text_key TEXT NOT NULL,
            vector TEXT NOT NULL,
            PRIMARY KEY (fact_id, model)
        )
        """,
    )),
    # 17: small settings of the app itself (docs/ONE_CHAT_DESIGN.md): for now which chat is THE chat (key 'main_thread'). One row per key; nothing secret is kept here.
    (17, (
        """
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    )),
    # 18: what is said, in categories (docs/ONE_CHAT_DESIGN.md, step 2). `categories` is the list the person sees (the starter ones are made on first use; `origin` keeps a starter category's original
    # name when it is renamed, so code that knows it as "Weather" still finds it); `message_categories` puts each of the person's messages in exactly one (`source`: code, model, continued or person).
    (18, (
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            meaning TEXT,
            origin TEXT,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS message_categories (
            message_id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (message_id) REFERENCES messages(id),
            FOREIGN KEY (category_id) REFERENCES categories(id)
        )
        """,
    )),
    # 19: merging categories, and new categories Diya suggests (docs/ONE_CHAT_DESIGN.md, step 4). A merged category stays as a hidden row (`merged_into`) so that code which knows it by its starter name
    # still finds where its messages went. A suggestion is a name and the messages it is about, until the person says yes or no.
    (19, (
        "ALTER TABLE categories ADD COLUMN merged_into INTEGER",
        """
        CREATE TABLE IF NOT EXISTS category_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE,
            message_ids TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            decided_at TEXT
        )
        """,
    )),
    # 20: the capture queue (docs/MEMORY_DURABILITY_DESIGN.md). Every message the person sends is written here the moment it is saved, and read for facts by whoever is reading, one at a time, until
    # nothing is waiting. Until now a message that arrived while another was being read was skipped and left to the scheduled pass, up to half an hour later. `state`: pending, done, skipped (nothing
    # worth keeping in it), failed (tried three times; the scheduled pass still reads it).
    (20, (
        """
        CREATE TABLE IF NOT EXISTS capture_queue (
            message_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            done_at TEXT,
            last_error TEXT,
            FOREIGN KEY (message_id) REFERENCES messages(id)
        )
        """,
    )),
    # 21: the activity journal (docs/ACTIVITY_JOURNAL_DESIGN.md): one row for everything Diya did with a tool or a connector, never changed and never deleted (two triggers make the database itself
    # refuse an UPDATE or a DELETE). The arguments are kept as a digest and a short preview with secrets hidden; the result is not kept, only how long it was.
    (21, (
        """
        CREATE TABLE IF NOT EXISTS tool_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            tool TEXT NOT NULL,
            kind TEXT NOT NULL,
            origin TEXT NOT NULL,
            thread_id INTEGER,
            message_id INTEGER,
            args_digest TEXT,
            args_preview TEXT,
            status TEXT NOT NULL,
            result_chars INTEGER,
            duration_ms INTEGER,
            note TEXT
        )
        """,
        "CREATE TRIGGER IF NOT EXISTS tool_journal_no_update BEFORE UPDATE ON tool_journal BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS tool_journal_no_delete BEFORE DELETE ON tool_journal BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END",
    )),
    # Dreaming's receipts (DIYA-030, docs/DREAMING_RECEIPTS_DESIGN.md): one row per scheduled pass saying what it read, staged, did and whether anything went wrong. Append-only like the journal.
    (22, (
        """
        CREATE TABLE IF NOT EXISTS dream_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            first_message_id INTEGER,
            last_message_id INTEGER,
            messages_read INTEGER NOT NULL DEFAULT 0,
            staged INTEGER NOT NULL DEFAULT 0,
            remembered INTEGER NOT NULL DEFAULT 0,
            asked INTEGER NOT NULL DEFAULT 0,
            not_kept INTEGER NOT NULL DEFAULT 0,
            held INTEGER NOT NULL DEFAULT 0,
            replaced INTEGER NOT NULL DEFAULT 0,
            questions INTEGER NOT NULL DEFAULT 0,
            categories_sorted INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL,
            errors TEXT
        )
        """,
        "CREATE TRIGGER IF NOT EXISTS dream_runs_no_update BEFORE UPDATE ON dream_runs BEGIN SELECT RAISE(ABORT, 'the receipts are append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS dream_runs_no_delete BEFORE DELETE ON dream_runs BEGIN SELECT RAISE(ABORT, 'the receipts are append-only'); END",
    )),
    # Said again (docs/FADING_DESIGN.md): each time the person says something Diya already knows, the message is recorded as a mention of that fact, so the fact can say how often and when it was said (the
    # evidence behind it, as Hindsight keeps a proof count) and what a passing state last heard from the person; and Dreaming's receipt counts the facts that faded.
    (23, (
        """
        CREATE TABLE IF NOT EXISTS fact_mentions (
            fact_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            at TEXT NOT NULL,
            PRIMARY KEY (fact_id, message_id),
            FOREIGN KEY (fact_id) REFERENCES facts(id)
        )
        """,
        "ALTER TABLE dream_runs ADD COLUMN faded INTEGER NOT NULL DEFAULT 0",
    )),
)

MAX_THREAD_TITLE = 80  # the longest name a chat can be given
MAX_SEARCH_CHARS = 100  # the longest search that is looked for
SNIPPET_BEFORE, SNIPPET_AFTER = 40, 90  # how much of a message is shown around what was found


def _around(text, query):
    """A short piece of `text` around the first place `query` is in it (ignoring case), with … where it was cut: what a search result shows."""
    flat = " ".join(str(text).split())
    at = flat.lower().find(query.lower())
    if at < 0:
        return flat[:SNIPPET_BEFORE + SNIPPET_AFTER] + ("…" if len(flat) > SNIPPET_BEFORE + SNIPPET_AFTER else "")
    start, end = max(0, at - SNIPPET_BEFORE), min(len(flat), at + len(query) + SNIPPET_AFTER)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


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
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)  # a database in a folder that does not exist yet (DIYA_DATA_DIR) is made there
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

    def complete_reminder(self, reminder_id, at=None):
        """Mark a reminder done, and when (`at` is UTC text like 2026-09-25T11:30:00Z; now if not given). Returns True if this call did it, False if it was already done or is not there."""
        if at is not None and not (isinstance(at, str) and MOMENT.fullmatch(at)):
            raise ValueError(f"at must look like 2026-09-25T11:30:00Z, got {at!r}")
        conn = self.connect()
        cur = conn.execute("UPDATE reminders SET done = 1, done_at = ? WHERE id = ? AND done = 0",
                           (at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), reminder_id))
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def done_reminders(self, limit=20):
        """The reminders already done, newest first (the ones with no recorded time last), as dicts: id, content, due_at, due_ts, done_at, series_id. `done_at` is None for one done before the
        time was kept, and for one a repeating series closed when the next came (it has a `series_id`)."""
        conn = self.connect()
        rows = conn.execute("SELECT id, content, due_at, due_ts, done_at, series_id FROM reminders WHERE done = 1 ORDER BY done_at IS NULL, done_at DESC, id DESC LIMIT ?", (int(limit),)).fetchall()
        conn.close()
        return [dict(zip(("id", "content", "due_at", "due_ts", "done_at", "series_id"), row)) for row in rows]

    def create_thread(self, title=None):
        conn = self.connect()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute("INSERT INTO threads (title, created_at) VALUES (?, ?)", (title, now))
        conn.commit()
        thread_id = cur.lastrowid
        conn.close()
        return thread_id

    @staticmethod
    def _chosen_main(conn):
        """(the id of the one chat, whether it was already kept). The kept one if that chat is still there; else the chat that has the newest message; else (None, False): there is no chat at all."""
        row = conn.execute("SELECT value FROM app_state WHERE key = 'main_thread'").fetchone()
        if row is not None and re.fullmatch(r"[0-9]{1,18}", str(row[0])):
            found = conn.execute("SELECT id FROM threads WHERE id = ?", (int(row[0]),)).fetchone()
            if found is not None:
                return found[0], True
        newest = conn.execute("SELECT t.id FROM messages m JOIN threads t ON t.id = m.thread_id ORDER BY m.id DESC LIMIT 1").fetchone()
        return (newest[0] if newest is not None else None), False

    def current_main_thread(self):
        """Which chat is the one chat, without making anything (for a list or a read): None when there is no chat yet."""
        conn = self.connect()
        try:
            return self._chosen_main(conn)[0]
        finally:
            conn.close()

    def main_thread(self):
        """The one chat Diya has (docs/ONE_CHAT_DESIGN.md): its id, made and kept (in app_state) if need be. The first time (or if that chat has gone) it is the chat that has the newest message, so a
        person who has been talking carries on where they were, or a new chat called Diya when there are none. Chosen under one write lock, so two callers asking at the same moment get the same chat."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            chosen, kept = self._chosen_main(conn)
            if not kept:
                if chosen is None:
                    chosen = conn.execute("INSERT INTO threads (title, created_at) VALUES (?, ?)", ("Diya", datetime.now(timezone.utc).isoformat())).lastrowid
                conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('main_thread', ?)", (str(chosen),))
            conn.commit()
            return chosen
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_messages_tail(self, thread_id, limit):
        """The newest `limit` messages of a chat, oldest first, and whether older ones were left out: ([{id, role, content}], more_before). The one chat grows without end, so a page asks for a tail."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT id, role, content FROM (SELECT id, role, content FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id", (thread_id, int(limit) + 1)
        ).fetchall()
        conn.close()
        more = len(rows) > int(limit)
        rows = rows[1:] if more else rows
        return [{"id": row_id, "role": role, "content": content} for row_id, role, content in rows], more

    def previous_user_message(self, message_id):
        """The text of the person's message just before this one in the same chat, or None."""
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT p.content FROM messages m JOIN messages p ON p.thread_id = m.thread_id AND p.id < m.id AND p.role = 'user' WHERE m.id = ? ORDER BY p.id DESC LIMIT 1", (int(message_id),)
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    # --- the activity journal (append-only) ---

    def journal_add(self, *, tool, kind, origin, thread_id, message_id, args_digest, args_preview, status, result_chars, duration_ms, note):
        conn = self.connect()
        try:
            cur = conn.execute(
                "INSERT INTO tool_journal (at, tool, kind, origin, thread_id, message_id, args_digest, args_preview, status, result_chars, duration_ms, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), tool, kind, origin, thread_id, message_id, args_digest, args_preview, status, result_chars, duration_ms, note),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def journal_recent(self, limit=50, tool=None):
        """The newest entries first, as dicts."""
        conn = self.connect()
        try:
            sql = "SELECT id, at, tool, kind, origin, thread_id, message_id, args_digest, args_preview, status, result_chars, duration_ms, note FROM tool_journal"
            args = []
            if tool is not None:
                sql += " WHERE tool = ?"
                args.append(str(tool))
            rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", args + [int(limit)]).fetchall()
            names = ("id", "at", "tool", "kind", "origin", "thread_id", "message_id", "args_digest", "args_preview", "status", "result_chars", "duration_ms", "note")
            return [dict(zip(names, row)) for row in rows]
        finally:
            conn.close()

    def journal_last(self, tools):
        """The newest journal row whose tool is one of `tools`, as a dict, or None."""
        tools = list(tools)
        if not tools:
            return None
        conn = self.connect()
        try:
            conn.row_factory = sqlite3.Row
            marks = ",".join("?" for _ in tools)
            row = conn.execute(f"SELECT * FROM tool_journal WHERE tool IN ({marks}) ORDER BY id DESC LIMIT 1", tools).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def journal_counts(self, since):
        """{status: how many} of the entries written at or after `since` (an ISO time)."""
        conn = self.connect()
        try:
            return dict(conn.execute("SELECT status, COUNT(*) FROM tool_journal WHERE at >= ? GROUP BY status", (since,)).fetchall())
        finally:
            conn.close()

    # --- the capture queue ---

    def enqueue_capture(self, message_id):
        """Put a message of the person's in the queue to be read for facts. Once only: a message already there (read or not) is left as it is."""
        conn = self.connect()
        try:
            conn.execute("INSERT OR IGNORE INTO capture_queue (message_id, created_at) VALUES (?, ?)", (int(message_id), datetime.now(timezone.utc).isoformat()))
            conn.commit()
        finally:
            conn.close()

    def pending_captures(self, limit=50):
        """The ids of the messages still waiting to be read, oldest first."""
        conn = self.connect()
        try:
            return [row[0] for row in conn.execute("SELECT message_id FROM capture_queue WHERE state = 'pending' ORDER BY message_id LIMIT ?", (int(limit),))]
        finally:
            conn.close()

    def finish_capture(self, message_id, state, error=None):
        """A message has been dealt with: done, skipped or failed."""
        conn = self.connect()
        try:
            conn.execute(
                "UPDATE capture_queue SET state = ?, done_at = ?, last_error = ? WHERE message_id = ?",
                (state, datetime.now(timezone.utc).isoformat(), None if error is None else str(error)[:300], int(message_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def retry_capture(self, message_id, error=None):
        """A try that did not work: count it. Returns how many tries the message has had."""
        conn = self.connect()
        try:
            conn.execute("UPDATE capture_queue SET attempts = attempts + 1, last_error = ? WHERE message_id = ?", (None if error is None else str(error)[:300], int(message_id)))
            conn.commit()
            row = conn.execute("SELECT attempts FROM capture_queue WHERE message_id = ?", (int(message_id),)).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def capture_backlog(self):
        """{state: how many} of everything in the queue."""
        conn = self.connect()
        try:
            return dict(conn.execute("SELECT state, COUNT(*) FROM capture_queue GROUP BY state").fetchall())
        finally:
            conn.close()

    def add_message(self, thread_id, role, content, capture=False):
        """Save a message and return its id. With `capture`, the person's message is also put in the queue to be read for facts IN THE SAME TRANSACTION (DIYA-019): there is no moment at which the
        message is saved and the job to read it is not, so a crash between the two cannot lose the reading."""
        conn = self.connect()
        now = datetime.now(timezone.utc).isoformat()
        try:
            cur = conn.execute(
                "INSERT INTO messages (thread_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, role, content, now),
            )
            message_id = cur.lastrowid
            if capture and role == "user":
                conn.execute("INSERT OR IGNORE INTO capture_queue (message_id, created_at) VALUES (?, ?)", (message_id, now))
            conn.commit()
        finally:
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
        """Newest first, each with what to call it in a list: the name the person gave it (set_thread_title), or else a snippet of the first
        real message so threads are recognizable (a thread has no name until one is given)."""
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT t.id, t.created_at,
                   COALESCE(NULLIF(t.title, ''), (SELECT content FROM messages m
                    WHERE m.thread_id = t.id AND m.role = 'user'
                    ORDER BY m.id LIMIT 1)) AS preview
            FROM threads t
            ORDER BY t.id DESC
            """
        ).fetchall()
        conn.close()
        return [{"id": r[0], "created_at": r[1], "preview": r[2] or "(empty thread)"} for r in rows]

    def set_thread_title(self, thread_id, title):
        """Give a chat a name, or take it back with an empty one (the list then shows the first message again). Returns True if the chat exists."""
        title = " ".join(str(title or "").split())[:MAX_THREAD_TITLE] or None
        conn = self.connect()
        cur = conn.execute("UPDATE threads SET title = ? WHERE id = ?", (title, thread_id))
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def search_threads(self, query, limit=30):
        """The chats with a message (or a name) that contains `query`, newest first, as dicts: id, created_at, preview (as in list_threads_with_preview) and `match`, a short piece of the
        newest message that contains it. Case is ignored for plain English letters; `%` and `_` are only themselves. Nothing is changed."""
        query = " ".join(str(query or "").split())[:MAX_SEARCH_CHARS]
        if len(query) < 2:
            return []
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT t.id, t.created_at,
                   COALESCE(NULLIF(t.title, ''), (SELECT content FROM messages m WHERE m.thread_id = t.id AND m.role = 'user' ORDER BY m.id LIMIT 1)) AS preview,
                   (SELECT content FROM messages m WHERE m.thread_id = t.id AND m.role IN ('user', 'assistant') AND m.content LIKE ? ESCAPE '\\' ORDER BY m.id DESC LIMIT 1) AS found
            FROM threads t
            WHERE t.title LIKE ? ESCAPE '\\'
               OR EXISTS (SELECT 1 FROM messages m WHERE m.thread_id = t.id AND m.role IN ('user', 'assistant') AND m.content LIKE ? ESCAPE '\\')
            ORDER BY t.id DESC LIMIT ?
            """,
            (like, like, like, int(limit)),
        ).fetchall()
        conn.close()
        return [{"id": r[0], "created_at": r[1], "preview": r[2] or "(empty thread)", "match": _around(r[3] or r[2] or "", query)} for r in rows]

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

    DREAM_RUN_FIELDS = ("started_at", "duration_ms", "first_message_id", "last_message_id", "messages_read", "staged", "remembered", "asked", "not_kept", "held", "replaced", "questions", "categories_sorted", "outcome", "errors", "faded")

    def dream_run_add(self, **fields):
        """Record one Dreaming pass (a receipt). Append-only: the table refuses any change afterwards. Returns the receipt's number."""
        unknown = set(fields) - set(self.DREAM_RUN_FIELDS)
        if unknown:
            raise ValueError(f"a Dreaming receipt has no {', '.join(sorted(unknown))}")
        conn = self.connect()
        try:
            names = [n for n in self.DREAM_RUN_FIELDS if n in fields]
            cur = conn.execute(f"INSERT INTO dream_runs ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", [fields[n] for n in names])
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def dream_runs_recent(self, limit=30, busy_only=True):
        """The newest receipts first. With `busy_only` the passes that read nothing and found nothing wrong are left out (they are counted by dream_idle_count)."""
        where = "WHERE messages_read > 0 OR staged > 0 OR remembered > 0 OR asked > 0 OR not_kept > 0 OR replaced > 0 OR questions > 0 OR categories_sorted > 0 OR faded > 0 OR errors IS NOT NULL" if busy_only else ""
        conn = self.connect()
        try:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(f"SELECT * FROM dream_runs {where} ORDER BY id DESC LIMIT ?", (int(limit),))]
        finally:
            conn.close()

    def dream_last_run(self):
        """The newest receipt of any kind, or None."""
        found = self.dream_runs_recent(1, busy_only=False)
        return found[0] if found else None

    def dream_idle_count(self, since):
        """How many passes since `since` (ISO text) found nothing to do."""
        conn = self.connect()
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM dream_runs WHERE started_at >= ? AND messages_read = 0 AND staged = 0 AND remembered = 0 AND asked = 0 AND not_kept = 0 AND replaced = 0 AND questions = 0"
                " AND categories_sorted = 0 AND faded = 0 AND errors IS NULL", (since,),
            ).fetchone()[0]
        finally:
            conn.close()

    def message_times(self, ids):
        """{message id: when it was saved (ISO text)} for those messages. Read-only."""
        ids = [int(i) for i in ids]
        if not ids:
            return {}
        conn = self.connect()
        try:
            marks = ",".join("?" for _ in ids)
            return dict(conn.execute(f"SELECT id, created_at FROM messages WHERE id IN ({marks})", ids).fetchall())
        finally:
            conn.close()

    def captured_message_ids(self, ids):
        """Which of the message `ids` memory has already taken in live (a set). Read-only."""
        ids = list(ids)
        found = set()
        conn = self.connect()
        for start in range(0, len(ids), 500):  # in pieces, so a long list never meets SQLite's limit on the number of values
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))  # only question marks, built here: nothing from outside is put in the text of the query
            found.update(row[0] for row in conn.execute(f"SELECT message_id FROM memory_captures WHERE message_id IN ({marks})", chunk))
        conn.close()
        return found

    def mark_captured(self, message_id, facts):
        """Record that memory took message `message_id` in live and made `facts` candidates from it. Marking it twice changes nothing."""
        conn = self.connect()
        conn.execute("INSERT OR IGNORE INTO memory_captures (message_id, at, facts) VALUES (?, ?, ?)",
                     (message_id, datetime.now(timezone.utc).isoformat(), facts))
        conn.commit()
        conn.close()

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


def main_thread():
    return _default_store().main_thread()


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
