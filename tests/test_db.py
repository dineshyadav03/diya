import sqlite3
from datetime import datetime

import pytest

import diya_db
from diya_db import Store


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "store.db"))


# --- laziness and isolation ---------------------------------------------------

def test_constructing_a_store_creates_nothing(tmp_path):
    path = tmp_path / "lazy.db"
    Store(str(path))
    assert not path.exists()


def test_first_use_creates_the_file_and_schema(tmp_path):
    path = tmp_path / "used.db"
    Store(str(path)).list_threads()
    tables = {r[0] for r in sqlite3.connect(path).execute("select name from sqlite_master where type='table'")}
    assert {"threads", "messages", "reminders"} <= tables


def test_stores_on_different_files_are_independent(tmp_path):
    a, b = Store(str(tmp_path / "a.db")), Store(str(tmp_path / "b.db"))
    a.create_thread()
    a.add_reminder("only in a")
    assert b.list_threads() == [] and b.list_reminders() == []


def test_importing_diya_db_has_no_side_effects(run_python, tmp_path):
    result = run_python("import diya_db")
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


# --- threads and messages (behaviour carried over unchanged) -------------------

def test_thread_ids_increase_and_titles_are_kept(store):
    first, second = store.create_thread("t1"), store.create_thread()
    assert second == first + 1
    assert [(r[0], r[1]) for r in store.list_threads()] == [(first, "t1"), (second, None)]
    datetime.fromisoformat(store.list_threads()[0][2])  # timezone-aware ISO timestamp


def test_history_is_returned_in_insertion_order_as_role_content_dicts(store):
    t = store.create_thread()
    store.add_message(t, "user", "hi")
    store.add_message(t, "assistant", "hello")
    store.add_message(t, "user", "again")
    assert store.get_history(t) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "again"},
    ]
    assert store.get_history(t + 99) == []


def test_history_is_per_thread(store):
    a, b = store.create_thread(), store.create_thread()
    store.add_message(a, "user", "in a")
    assert store.get_history(b) == []


def test_previews_are_newest_first_use_the_first_user_message_and_flag_empty_threads(store):
    empty = store.create_thread()
    t = store.create_thread()
    store.add_message(t, "assistant", "not this one")
    store.add_message(t, "user", "first user message")
    store.add_message(t, "user", "second user message")
    previews = store.list_threads_with_preview()
    assert [p["id"] for p in previews] == [t, empty]
    assert previews[0]["preview"] == "first user message"
    assert previews[1]["preview"] == "(empty thread)"
    assert set(previews[0]) == {"id", "created_at", "preview"}


def test_messages_since_spans_threads_oldest_first(store):
    a, b = store.create_thread(), store.create_thread()
    store.add_message(a, "user", "m1")
    store.add_message(b, "assistant", "m2")
    store.add_message(a, "user", "m3")
    everything = store.get_messages_since(0)
    assert [m["content"] for m in everything] == ["m1", "m2", "m3"]
    assert set(everything[0]) == {"id", "thread_id", "role", "content"}
    assert [m["content"] for m in store.get_messages_since(everything[0]["id"])] == ["m2", "m3"]


# --- reminders ----------------------------------------------------------------

def test_reminders_lifecycle(store):
    store.add_reminder("call mom")
    store.add_reminder("buy strings", "Friday")
    rows = store.list_reminders()
    assert [(r[1], r[2], r[3]) for r in rows] == [("call mom", None, 0), ("buy strings", "Friday", 0)]
    store.complete_reminder(rows[0][0])
    assert [r[1] for r in store.list_reminders()] == ["buy strings"]
    assert [(r[1], r[3]) for r in store.list_reminders(include_done=True)] == [("call mom", 1), ("buy strings", 0)]


# --- the module-level functions follow DIYA_DB_PATH, per call --------------------

def test_module_functions_use_the_configured_database(monkeypatch, tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    monkeypatch.setenv("DIYA_DB_PATH", str(a))
    diya_db.create_thread("in a")
    monkeypatch.setenv("DIYA_DB_PATH", str(b))
    assert diya_db.list_threads() == []
    diya_db.add_reminder("in b")
    assert Store(str(a)).list_reminders() == []
    assert [r[1] for r in Store(str(b)).list_reminders()] == ["in b"]


def test_default_database_is_diya_db_in_the_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("DIYA_DB_PATH")
    diya_db.create_thread()
    assert (tmp_path / "diya.db").exists()


def test_every_public_module_function_still_exists():
    for name in ("get_connection", "add_reminder", "list_reminders", "complete_reminder", "create_thread",
                 "add_message", "get_history", "list_threads", "list_threads_with_preview", "get_messages_since"):
        assert callable(getattr(diya_db, name))
