"""A to-do list inside Diya (docs/TASKS_DESIGN.md).

A task is a row in Diya's own database. Nothing here touches the network or an account, which is why adding one needs
no approval (docs/ACTIONS_DESIGN.md, D2): it is local, the Tasks page shows it, and the owner can tick it off. What the
model may do with the list is decided in diya.py (it can add and read, never close or change); what is true of the list
whoever asks is decided here, and the database is the last line of defence for it:

- a task is one trimmed line of at most MAX_TASK_CHARS characters, with nothing invisible or controlling in it;
- the same words (in any capitals) cannot be open twice, and no more than MAX_OPEN tasks are open at once;
- `due_at` is the person's own words for when and `due_ts` is that read as a moment (UTC text, null if it could not be
  read), as for a reminder: the words stay what was said, and anything that acts on a time acts on a real one.

Each call uses its own short-lived connection, as Store does; what must be true when it writes is checked inside the
write (BEGIN IMMEDIATE), so two callers cannot both pass the same check.
"""
import contextlib
import re
from datetime import datetime, time

import diya_db
import diya_memory
import diya_time

MAX_TASK_CHARS = 200
MAX_DUE_CHARS = 60
MAX_OPEN = 500
SOURCES = ("chat", "page")
STATES = ("open", "done", "all")
FIELDS = ("id", "content", "due_at", "due_ts", "done", "source", "thread_id", "message_id", "created_at", "completed_at")
_SELECT = "SELECT " + ", ".join(FIELDS) + " FROM tasks"


class TaskError(Exception):
    """A request about the list that cannot be done as asked. The text can be shown to the person."""


class InvalidTask(TaskError):
    pass


class UnknownTask(TaskError):
    pass


class DuplicateTask(TaskError):
    """The same words are already an open task; `task_id` is that task."""

    def __init__(self, message, task_id):
        super().__init__(message)
        self.task_id = task_id


class TooManyTasks(TaskError):
    pass


def _task(row):
    task = dict(zip(FIELDS, row))
    task["done"] = bool(task["done"])
    return task


def _stamp(local):
    """A local wall-clock time as stored text (UTC): 2026-10-05T10:15:00Z."""
    return diya_time.iso_of_local(local)


def _tidy(text, what, limit):
    """`text` with its whitespace made single spaces, or InvalidTask if it is not a line of text that may be stored."""
    if not isinstance(text, str):
        raise InvalidTask(f"{what} must be words")
    text = " ".join(text.split())
    if len(text) > limit:
        raise InvalidTask(f"{what} is at most {limit} characters")
    if text:
        try:
            diya_memory.check_text(text)  # whitespace is single spaces by now, so only a control or invisible character fails
        except diya_memory.InvalidFact as exc:
            raise InvalidTask(str(exc).replace("a fact", what, 1))
    return text


_TODAY = re.compile(r"(?:by |due |on |for )?today")


def _today_stamp(words, now):
    """A task due "today", as a day: that day at nine, which only carries the date (a task due on a day is not late until the day
    is over). diya_time reads a bare day as that day at 09:00, so "today" after nine o'clock reads as "already passed": right for a
    reminder, which is for a moment, wrong for a task, which is for a day. None for any other words."""
    if _TODAY.fullmatch(words.lower()):
        return _stamp(datetime.combine(now.date(), time(9, 0)))
    return None


def says_a_time(words):
    """Do the person's words for when name a time of day ("5pm", "noon", "in 2 hours"), not just a day? Reading "Friday"
    gives 09:00 (diya_time's own default), and a task due "Friday" must not be shown as due at nine."""
    return any(
        facet.kind in ("clock", "part") or (facet.kind == "relative" and facet.value[1] in ("minutes", "hours"))
        for facet in diya_time.facets(words)
    )


def describe_due(task):
    """When a task is due, in words for the person: the day, and the time only if they said one, when it was read as a
    moment; their own words if it could not be read; nothing if there is none."""
    if task["due_ts"]:
        local = diya_time.local_from_iso(task["due_ts"])
        if says_a_time(task["due_at"]):
            return diya_time.describe_local(local)
        return f"{diya_time.DAY_NAMES[local.weekday()]} {local.day} {diya_time.MONTH_NAMES[local.month - 1]} {local.year}"
    if task["due_at"]:
        return f"asked as {task['due_at']!r}"
    return ""


def is_overdue(task, now):
    """Is an open task past its due date? `now` is the current local time (a naive datetime). A task due at a named time
    is overdue after that moment; one due on a day (no time named) is overdue only once that day is over, so a task due
    "Friday" is not late on Friday morning. A done task, a task with no date and one whose date could not be read are not."""
    if task["done"] or not task["due_ts"]:
        return False
    due = diya_time.local_from_iso(task["due_ts"])
    return due < now if says_a_time(task["due_at"]) else due.date() < now.date()


class Tasks:
    """The task list, bound to one `diya_db.Store`. `clock` returns the current local time as a naive datetime (the
    Agent's own clock); a parameter so tests do not depend on today."""

    def __init__(self, store, clock=None):
        self.store = store
        self._clock = clock or datetime.now

    @contextlib.contextmanager
    def _read(self):
        conn = self.store.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def _write(self):
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    # ---- reading ----
    def get(self, task_id):
        with self._read() as conn:
            row = conn.execute(_SELECT + " WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise UnknownTask(f"there is no task {task_id}")
        return _task(row)

    def tasks(self, state="open", limit=None):
        """Tasks as dicts (FIELDS; `done` is a bool). Open ones oldest first, done ones most recently finished first,
        `all` open then done. `limit` keeps the first that many."""
        if state not in STATES:
            raise ValueError(f"state must be one of {', '.join(STATES)}, got {state!r}")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise ValueError(f"limit must be a whole number above 0 or None, got {limit!r}")
        order = {
            "open": " WHERE done = 0 ORDER BY id",
            "done": " WHERE done = 1 ORDER BY completed_at DESC, id DESC",
            "all": " ORDER BY done, CASE WHEN done = 0 THEN id END, completed_at DESC, id DESC",
        }[state]
        query = _SELECT + order + (f" LIMIT {limit}" if limit else "")
        with self._read() as conn:
            rows = conn.execute(query).fetchall()
        return [_task(row) for row in rows]

    def counts(self):
        with self._read() as conn:
            found = dict(conn.execute("SELECT done, COUNT(*) FROM tasks GROUP BY done"))
        return {"open": found.get(0, 0), "done": found.get(1, 0)}

    # ---- writing ----
    def add(self, content, due=None, *, source="chat", thread_id=None, message_id=None):
        """Save a task and return it. `due` is the person's own words for when, or None: read as a moment if it can be,
        kept as words if not (that is not an error: "when I'm back" is a real thing to say). Raises TaskError, and
        writes nothing, for words that are not a task, a task that is already open, or a full list."""
        if source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}, got {source!r}")
        for name, value in (("thread_id", thread_id), ("message_id", message_id)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"{name} must be a whole number or None, got {value!r}")
        content = _tidy(content, "a task", MAX_TASK_CHARS)
        if not content:
            raise InvalidTask("a task needs words")
        due = _tidy(due, "when it is due", MAX_DUE_CHARS) if due is not None else ""  # which also refuses what is not words
        now = self._clock()
        due_ts = None
        if due:
            try:
                due_ts = diya_time.parse_when(due, now).iso()
            except diya_time.NotUnderstood:
                due_ts = _today_stamp(due, now)
        key = diya_memory.text_key(content)
        with self._write() as conn:
            existing = conn.execute("SELECT id FROM tasks WHERE content_key = ? AND done = 0", (key,)).fetchone()
            if existing:
                raise DuplicateTask(f"that task is already on the list (#{existing[0]})", existing[0])
            open_now = conn.execute("SELECT COUNT(*) FROM tasks WHERE done = 0").fetchone()[0]
            if open_now >= MAX_OPEN:
                raise TooManyTasks(f"the list already has {open_now} open tasks; none more until some are done")
            cur = conn.execute(
                "INSERT INTO tasks (content, content_key, due_at, due_ts, done, source, thread_id, message_id, created_at)"
                " VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
                (content, key, due or None, due_ts, source, thread_id, message_id, _stamp(now)),
            )
            task_id = cur.lastrowid
        return self.get(task_id)

    def complete(self, task_id):
        """Tick a task off. True if this call did it, False if it was already done; UnknownTask if there is no such task."""
        now = self._clock()
        with self._write() as conn:
            cur = conn.execute("UPDATE tasks SET done = 1, completed_at = ? WHERE id = ? AND done = 0", (_stamp(now), task_id))
            if cur.rowcount == 0 and conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
                raise UnknownTask(f"there is no task {task_id}")
            return cur.rowcount > 0

    def reopen(self, task_id):
        """Put a done task back on the list. True if this call did it, False if it was already open. DuplicateTask if the
        same words are open again by now; UnknownTask if there is no such task."""
        with self._write() as conn:
            row = conn.execute("SELECT content_key, done FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise UnknownTask(f"there is no task {task_id}")
            if not row[1]:
                return False
            existing = conn.execute("SELECT id FROM tasks WHERE content_key = ? AND done = 0", (row[0],)).fetchone()
            if existing:
                raise DuplicateTask(f"the same task is already open (#{existing[0]})", existing[0])
            open_now = conn.execute("SELECT COUNT(*) FROM tasks WHERE done = 0").fetchone()[0]
            if open_now >= MAX_OPEN:
                raise TooManyTasks(f"the list already has {open_now} open tasks; none more until some are done")
            conn.execute("UPDATE tasks SET done = 0, completed_at = NULL WHERE id = ?", (task_id,))
            return True
