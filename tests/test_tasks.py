"""The to-do list inside Diya (docs/TASKS_DESIGN.md, D1, D5 and unit T1): migration 6 and diya_tasks.Tasks.

What this proves: a task is one trimmed line (nothing invisible or controlling) with the person's words for when beside
the moment they were read as; the same words cannot be open twice and no more than MAX_OPEN can be open, both enforced
inside the write (so two callers cannot both pass) and, for the duplicate, by the database itself; a day with no time is
shown as a day, never as nine o'clock; ticking a task off and putting it back are idempotent and say whether they did
anything; and an old database gains the table without losing a row.
"""
import sqlite3
import threading
from datetime import datetime

import pytest

import diya_db
import diya_tasks
import diya_time
from diya_tasks import DuplicateTask, InvalidTask, Tasks, TooManyTasks, UnknownTask

NOW = datetime(2026, 9, 23, 10, 15)  # a Wednesday, 10:15 local


@pytest.fixture
def store(tmp_path):
    return diya_db.Store(str(tmp_path / "tasks.db"))


@pytest.fixture
def tasks(store):
    return Tasks(store, clock=lambda: NOW)


def stamp(local):
    return diya_time.iso_of_local(local)


# ---- migration 6 ------------------------------------------------------------------------------------

def test_migration_six_adds_the_table_and_two_indexes_and_changes_nothing_else(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, due_at TEXT,"
                 " created_at TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    conn.execute("INSERT INTO reminders (content, created_at) VALUES ('keep me', 't')")
    conn.commit()
    applied = diya_db.apply_migrations(conn)
    assert applied == [v for v, _ in diya_db.MIGRATIONS] and 6 in applied
    columns = {row[1]: (row[2], bool(row[3])) for row in conn.execute("PRAGMA table_info(tasks)")}
    assert columns == {
        "id": ("INTEGER", False), "content": ("TEXT", True), "content_key": ("TEXT", True), "due_at": ("TEXT", False),
        "due_ts": ("TEXT", False), "done": ("INTEGER", True), "source": ("TEXT", True), "thread_id": ("INTEGER", False),
        "message_id": ("INTEGER", False), "created_at": ("TEXT", True), "completed_at": ("TEXT", False),
    }
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tasks'")}
    assert {"tasks_one_open_per_key", "tasks_by_done"} <= indexes
    assert conn.execute("SELECT content FROM reminders").fetchall() == [("keep me",)]
    assert diya_db.apply_migrations(conn) == []
    conn.close()


def test_a_database_at_version_five_gains_the_table_and_keeps_its_actions(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "five.db"))
    real = diya_db.MIGRATIONS
    diya_db.MIGRATIONS = real[:5]
    try:
        diya_db.apply_migrations(conn)
    finally:
        diya_db.MIGRATIONS = real
    conn.execute("INSERT INTO actions (kind, args, args_hash, summary, status, created_at, expires_at)"
                 " VALUES ('k', '{}', 'h', 's', 'pending', 't', 't')")
    conn.commit()
    assert diya_db.apply_migrations(conn) == [v for v, _ in diya_db.MIGRATIONS if v > 5]  # 6 and whatever comes after
    assert conn.execute("SELECT kind FROM actions").fetchall() == [("k",)]
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone() == (0,)
    conn.close()


def insert(conn, key="a", done=0, source="chat"):
    conn.execute("INSERT INTO tasks (content, content_key, done, source, created_at) VALUES (?, ?, ?, ?, 't')",
                 (key, key, done, source))


def test_the_database_itself_refuses_a_second_open_copy_a_bad_source_and_a_bad_done_flag(store):
    conn = store.connect()
    insert(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn)
    insert(conn, done=1)  # a done copy does not count
    insert(conn, done=1)
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, key="b", source="model")
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, key="c", done=2)
    conn.close()


# ---- adding ----------------------------------------------------------------------------------------

def test_a_task_is_saved_and_returned_with_every_field(tasks):
    task = tasks.add("Buy oat milk", thread_id=3, message_id=7)
    assert task == {
        "id": 1, "content": "Buy oat milk", "due_at": None, "due_ts": None, "done": False, "source": "chat",
        "thread_id": 3, "message_id": 7, "created_at": stamp(NOW), "completed_at": None,
    }
    assert tasks.get(1) == task


def test_the_stored_time_is_utc_text_and_the_source_defaults_to_chat(tasks):
    assert diya_db.MOMENT.fullmatch(tasks.add("x")["created_at"])
    assert tasks.add("y", source="page")["source"] == "page"


def test_whitespace_of_every_kind_becomes_single_spaces(tasks):
    assert tasks.add("  Buy\t oat\n milk  ")["content"] == "Buy oat milk"
    assert tasks.add("Call" + chr(0x2028) + "mum" + chr(0xA0) + "now")["content"] == "Call mum now"


@pytest.mark.parametrize("content", ["", "   ", "\n\t", None, 5, ["x"], b"x"])
def test_something_that_is_not_words_is_not_a_task(tasks, content):
    with pytest.raises(InvalidTask):
        tasks.add(content)
    assert tasks.tasks("all") == []


def test_a_task_is_at_most_two_hundred_characters(tasks):
    assert diya_tasks.MAX_TASK_CHARS == 200
    assert tasks.add("x" * 200)["content"] == "x" * 200
    with pytest.raises(InvalidTask, match="at most 200 characters"):
        tasks.add("y" * 201)
    assert len(tasks.tasks("all")) == 1


@pytest.mark.parametrize("char", [chr(7), chr(0x1b), chr(0), chr(0x202E), chr(0x200B), chr(0xFEFF), chr(0x2066), chr(0xE000), chr(0xD800)])
def test_a_control_or_invisible_character_is_refused_not_repaired(tasks, char):
    with pytest.raises(InvalidTask, match="a task cannot contain the character"):
        tasks.add(f"pay{char}bill")
    assert tasks.tasks("all") == []


def test_a_joiner_that_real_scripts_need_is_allowed(tasks):
    assert tasks.add("family" + chr(0x200D) + "trip")["content"] == "family" + chr(0x200D) + "trip"


def test_when_it_is_due_is_read_as_a_moment_and_the_words_are_kept(tasks):
    task = tasks.add("Send the invoice", "Friday")
    assert task["due_at"] == "Friday" and task["due_ts"] == stamp(datetime(2026, 9, 25, 9, 0))
    task = tasks.add("Prepare slides", "  tomorrow   at 5pm ")
    assert task["due_at"] == "tomorrow at 5pm" and task["due_ts"] == stamp(datetime(2026, 9, 24, 17, 0))


@pytest.mark.parametrize("words", ["when I'm back", "next Friday", "yesterday", "sometime", "the 3rd"])
def test_a_due_phrase_that_cannot_be_read_is_kept_as_words_and_is_not_an_error(tasks, words):
    task = tasks.add("Call mum", words)
    assert task["due_at"] == words and task["due_ts"] is None


@pytest.mark.parametrize("due", [None, "", "   ", "\n"])
def test_no_due_phrase_is_no_due_date(tasks, due):
    task = tasks.add("Call mum", due)
    assert task["due_at"] is None and task["due_ts"] is None


@pytest.mark.parametrize("due", [5, ["Friday"], b"Friday", True])
def test_a_due_phrase_that_is_not_words_is_refused(tasks, due):
    with pytest.raises(InvalidTask, match="must be words"):
        tasks.add("Call mum", due)
    assert tasks.tasks("all") == []


def test_a_due_phrase_is_at_most_sixty_characters_and_has_no_control_characters(tasks):
    assert tasks.add("a", "x" * 60)["due_at"] == "x" * 60
    with pytest.raises(InvalidTask, match="when it is due is at most 60 characters"):
        tasks.add("b", "y" * 61)
    with pytest.raises(InvalidTask, match="when it is due cannot contain the character"):
        tasks.add("c", "Fri" + chr(0x202E) + "day")
    assert len(tasks.tasks("all")) == 1


def test_the_due_phrase_is_read_against_the_clock_it_was_given(store):
    later = Tasks(store, clock=lambda: datetime(2026, 12, 30, 8, 0))
    assert later.add("Plan", "tomorrow at 5pm")["due_ts"] == stamp(datetime(2026, 12, 31, 17, 0))


@pytest.mark.parametrize("source", ["model", "", None, "Chat"])
def test_an_unknown_source_is_a_bug_not_a_refusal(tasks, source):
    with pytest.raises(ValueError, match="source must be one of chat, page"):
        tasks.add("x", source=source)


@pytest.mark.parametrize("name", ["thread_id", "message_id"])
@pytest.mark.parametrize("value", ["3", 1.5, True, [1]])
def test_a_thread_or_message_id_must_be_a_whole_number_or_none(tasks, name, value):
    with pytest.raises(ValueError, match=f"{name} must be a whole number or None"):
        tasks.add("x", **{name: value})


# ---- duplicates and the cap --------------------------------------------------------------------------

def test_a_write_holds_the_database_write_lock_from_its_first_statement(store):
    """What keeps "is it already open?" and "is the list full?" true at the moment the task is written: while a write is in
    progress no other connection can start one, even before the first statement has run. (Eight threads adding the same words
    at once, below, usually pass without it too, because the unique index and a small window hide the race; this does not.)"""
    tasks = Tasks(store, clock=lambda: NOW)
    with tasks._write():
        other = sqlite3.connect(store.path, timeout=0.05)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()


def test_a_write_that_fails_part_way_is_rolled_back_not_half_done(store):
    tasks = Tasks(store, clock=lambda: NOW)
    with pytest.raises(RuntimeError):
        with tasks._write() as conn:
            conn.execute("INSERT INTO tasks (content, content_key, done, source, created_at) VALUES ('x', 'x', 0, 'chat', 't')")
            raise RuntimeError("part way")
    assert tasks.tasks("all") == []


def test_the_same_words_in_any_capitals_cannot_be_open_twice(tasks):
    first = tasks.add("Buy oat milk")
    for again in ("Buy oat milk", "buy OAT milk", "  BUY  oat   MILK "):
        with pytest.raises(DuplicateTask) as raised:
            tasks.add(again)
        assert raised.value.task_id == first["id"] and f"#{first['id']}" in str(raised.value)
    assert len(tasks.tasks("all")) == 1


def test_a_done_task_frees_its_words_and_a_different_due_phrase_does_not_make_a_new_task(tasks):
    first = tasks.add("Buy oat milk")
    with pytest.raises(DuplicateTask):
        tasks.add("Buy oat milk", "Friday")
    tasks.complete(first["id"])
    assert tasks.add("Buy oat milk")["id"] == 2


def test_the_list_holds_at_most_five_hundred_open_tasks(tasks, monkeypatch):
    assert diya_tasks.MAX_OPEN == 500
    monkeypatch.setattr(diya_tasks, "MAX_OPEN", 3)
    for n in range(3):
        tasks.add(f"task {n}")
    with pytest.raises(TooManyTasks, match="3 open tasks"):
        tasks.add("one more")
    assert [t["content"] for t in tasks.tasks("all")] == ["task 0", "task 1", "task 2"]
    tasks.complete(1)  # done ones do not count
    assert tasks.add("one more")["id"] == 4


def test_the_duplicate_check_comes_before_the_cap(tasks, monkeypatch):
    monkeypatch.setattr(diya_tasks, "MAX_OPEN", 1)
    tasks.add("x")
    with pytest.raises(DuplicateTask):
        tasks.add("x")
    with pytest.raises(TooManyTasks):
        tasks.add("y")


def test_two_callers_adding_the_same_words_at_once_get_one_task_and_one_refusal(store):
    outcomes = []
    barrier = threading.Barrier(8)

    def add():
        barrier.wait()
        try:
            Tasks(store, clock=lambda: NOW).add("Buy oat milk")
            outcomes.append("added")
        except DuplicateTask:
            outcomes.append("duplicate")

    threads = [threading.Thread(target=add) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["added"] + ["duplicate"] * 7


# ---- reading ----------------------------------------------------------------------------------------

def test_open_tasks_come_oldest_first_and_done_ones_most_recently_finished_first(store):
    clock = {"now": NOW}
    tasks = Tasks(store, clock=lambda: clock["now"])
    for name in ("a", "b", "c", "d"):
        tasks.add(name)
    clock["now"] = datetime(2026, 9, 23, 11, 0)
    tasks.complete(3)
    clock["now"] = datetime(2026, 9, 23, 12, 0)
    tasks.complete(1)
    assert [t["content"] for t in tasks.tasks("open")] == ["b", "d"]
    assert [t["content"] for t in tasks.tasks("done")] == ["a", "c"]
    assert [t["content"] for t in tasks.tasks("all")] == ["b", "d", "a", "c"]
    assert [t["content"] for t in tasks.tasks()] == ["b", "d"]  # open is the default


def test_two_done_in_the_same_moment_are_newest_first(tasks):
    for name in ("a", "b", "c"):
        tasks.add(name)
    for n in (1, 2, 3):
        tasks.complete(n)
    assert [t["content"] for t in tasks.tasks("done")] == ["c", "b", "a"]


def test_a_limit_keeps_the_first_that_many_of_the_ordering(tasks):
    for name in ("a", "b", "c"):
        tasks.add(name)
    tasks.complete(1)
    assert [t["content"] for t in tasks.tasks("open", limit=1)] == ["b"]
    assert [t["content"] for t in tasks.tasks("all", limit=2)] == ["b", "c"]
    assert [t["content"] for t in tasks.tasks("done", limit=5)] == ["a"]


@pytest.mark.parametrize("state", ["pending", "", None, "OPEN", 1])
def test_an_unknown_state_is_refused(tasks, state):
    with pytest.raises(ValueError, match="state must be one of open, done, all"):
        tasks.tasks(state)


@pytest.mark.parametrize("limit", [0, -1, True, "3", 1.5])
def test_a_limit_must_be_a_whole_number_above_zero(tasks, limit):
    with pytest.raises(ValueError, match="limit must be a whole number above 0"):
        tasks.tasks("open", limit=limit)


def test_counts_say_how_many_are_open_and_done(tasks):
    assert tasks.counts() == {"open": 0, "done": 0}
    for name in ("a", "b", "c"):
        tasks.add(name)
    tasks.complete(2)
    assert tasks.counts() == {"open": 2, "done": 1}


def test_a_task_that_is_not_there_is_unknown(tasks):
    for call in (tasks.get, tasks.complete, tasks.reopen):
        with pytest.raises(UnknownTask, match="there is no task 99"):
            call(99)


# ---- done and back ----------------------------------------------------------------------------------

def test_ticking_a_task_off_says_whether_it_did_anything_and_records_when(tasks):
    task = tasks.add("a")
    assert tasks.complete(task["id"]) is True
    assert tasks.complete(task["id"]) is False  # a double click is harmless
    done = tasks.get(task["id"])
    assert done["done"] is True and done["completed_at"] == stamp(NOW)


def test_the_first_completion_time_is_kept_when_it_is_ticked_again(store):
    clock = {"now": NOW}
    tasks = Tasks(store, clock=lambda: clock["now"])
    task = tasks.add("a")
    tasks.complete(task["id"])
    clock["now"] = datetime(2026, 9, 24, 9, 0)
    tasks.complete(task["id"])
    assert tasks.get(task["id"])["completed_at"] == stamp(NOW)


def test_putting_a_task_back_clears_when_it_was_done(tasks):
    task = tasks.add("a")
    assert tasks.reopen(task["id"]) is False  # it was never done
    tasks.complete(task["id"])
    assert tasks.reopen(task["id"]) is True
    back = tasks.get(task["id"])
    assert back["done"] is False and back["completed_at"] is None
    assert tasks.reopen(task["id"]) is False


def test_a_task_cannot_be_put_back_while_the_same_words_are_open(tasks):
    old = tasks.add("Buy milk")
    tasks.complete(old["id"])
    new = tasks.add("buy MILK")
    with pytest.raises(DuplicateTask) as raised:
        tasks.reopen(old["id"])
    assert raised.value.task_id == new["id"]
    assert tasks.get(old["id"])["done"] is True


def test_a_task_cannot_be_put_back_into_a_full_list(tasks, monkeypatch):
    monkeypatch.setattr(diya_tasks, "MAX_OPEN", 1)
    first = tasks.add("a")
    tasks.complete(first["id"])
    tasks.add("b")
    with pytest.raises(TooManyTasks):
        tasks.reopen(first["id"])
    assert tasks.get(first["id"])["done"] is True


# ---- saying when ------------------------------------------------------------------------------------

def task_due(words, store):
    return Tasks(store, clock=lambda: NOW).add(f"t {words}", words)


@pytest.mark.parametrize("words, shown", [
    ("Friday", "Friday 25 Sep 2026"),  # a day alone is not nine o'clock
    ("tomorrow", "Thursday 24 Sep 2026"),
    ("in 2 days", "Friday 25 Sep 2026"),
    ("in 1 week", "Wednesday 30 Sep 2026"),
    ("Friday 5pm", "Friday 25 Sep 2026, 17:00"),
    ("tomorrow at 5:30pm", "Thursday 24 Sep 2026, 17:30"),
    ("Friday morning", "Friday 25 Sep 2026, 09:00"),
    ("Friday noon", "Friday 25 Sep 2026, 12:00"),
])
def test_a_due_date_is_shown_as_a_day_unless_the_person_named_a_time(store, words, shown):
    assert diya_tasks.describe_due(task_due(words, store)) == shown


def test_in_a_few_hours_is_shown_with_its_time(store):
    assert diya_tasks.describe_due(task_due("in 2 hours", store)) == "Wednesday 23 Sep 2026, 12:15"


def test_words_that_could_not_be_read_are_shown_as_they_were_said_and_no_due_is_shown_as_nothing(store, tasks):
    assert diya_tasks.describe_due(task_due("when I'm back", store)) == "asked as \"when I'm back\""
    assert diya_tasks.describe_due(tasks.add("plain")) == ""


@pytest.mark.parametrize("words, said", [
    ("5pm", True), ("17:30", True), ("noon", True), ("in 30 minutes", True), ("in an hour", True), ("morning", True),
    ("Friday", False), ("in 3 days", False), ("next week", False), ("", False), ("when I'm back", False), (None, False),
])
def test_what_counts_as_naming_a_time(words, said):
    assert diya_tasks.says_a_time(words) is said


def test_the_error_classes_are_all_task_errors():
    for error in (InvalidTask, UnknownTask, DuplicateTask, TooManyTasks):
        assert issubclass(error, diya_tasks.TaskError)


# ---- overdue ----------------------------------------------------------------------------------------

def due_task(words, store, done=False):
    tasks = Tasks(store, clock=lambda: NOW)
    task = tasks.add(f"t {words}", words)
    if done:
        tasks.complete(task["id"])
        task = tasks.get(task["id"])
    return task


@pytest.mark.parametrize("words, now, late", [
    ("today at 5pm", datetime(2026, 9, 23, 16, 59), False),
    ("today at 5pm", datetime(2026, 9, 23, 17, 0), False),  # exactly then is not yet late
    ("today at 5pm", datetime(2026, 9, 23, 17, 1), True),
    ("Friday", datetime(2026, 9, 25, 0, 0), False),  # a day is not late during that day
    ("Friday", datetime(2026, 9, 25, 9, 1), False),
    ("Friday", datetime(2026, 9, 25, 23, 59, 59), False),
    ("Friday", datetime(2026, 9, 26, 0, 0), True),
    ("Friday", datetime(2026, 10, 30, 12, 0), True),
    ("in 2 hours", datetime(2026, 9, 23, 12, 15), False),
    ("in 2 hours", datetime(2026, 9, 23, 12, 16), True),
    ("in 3 days", datetime(2026, 9, 26, 23, 0), False),
    ("in 3 days", datetime(2026, 9, 27, 0, 1), True),
])
def test_a_task_is_overdue_after_its_moment_or_after_its_day_when_no_time_was_named(store, words, now, late):
    assert diya_tasks.is_overdue(due_task(words, store), now) is late


def test_a_done_task_and_one_with_no_date_or_an_unreadable_one_are_never_overdue(store, tasks):
    later = datetime(2030, 1, 1)
    assert diya_tasks.is_overdue(due_task("today at 5pm", store, done=True), later) is False
    assert diya_tasks.is_overdue(tasks.add("plain"), later) is False
    assert diya_tasks.is_overdue(tasks.add("words", "when I'm back"), later) is False
