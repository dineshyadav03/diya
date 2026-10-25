"""Getting all your data out as plain files (diya_export.py; docs/EXPORT.md; DIYA-214), added 2026-10-25.

What this proves, with the real store and real data made through the real code: the export holds your chats (as lines and as something to read), what Diya remembers with its history and who it is about, your
tasks, reminders, repeating reminders, automations, categories, the ratings and notes, the actions with their results, the activity record and what Diya wrote first, with a README that counts them; none of
the secrets (the token's hash, the sign-in tokens, the Google client secret, notification keys, Telegram state) is in any file; the database is opened read-only (its bytes do not change) and a database from an
older version simply gives empty files; a failed run leaves no half-made folder and a second export never replaces the first; hidden and control characters are written as visible escapes while line breaks stay;
a message forgotten for good is not in the export; the folder is ignored by git; and the command line says what it did or why it could not.
"""
import dataclasses
import hashlib
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import diya_actions
import diya_automations
import diya_config
import diya_connectors
import diya_export
import diya_feedback
import diya_forget
import diya_memory
import diya_tasks
from diya_db import Store

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 25, 9, 30, 0)
SECRETS = ("tok-hash-0123456789abcdef", "refresh-token-SECRET-1", "client-secret-SECRET-2", "push-auth-SECRET-3", "push-p256dh-SECRET-4", "telegram-SECRET-5")
RLO, TAG = chr(0x202E), chr(0xE0041)


@pytest.fixture
def world(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config(), db_path=str(tmp_path / "diya.db"), data_dir="", connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "clog"), google_client_id="client-id",
        google_client_secret="client-secret-SECRET-2", profile_path=str(tmp_path / "p.txt"), dream_pending_path=str(tmp_path / "pending.jsonl"),
    )
    store = Store(config.db_path)
    thread = store.create_thread()
    store.set_thread_title(thread, "Exam plans")
    first = store.add_message(thread, "user", "my board exam is on 14 March")
    store.add_message(thread, "assistant", "Noted: 14 March.\nGood luck!")
    second = store.add_message(thread, "user", "नमस्ते and what about tomorrow")
    store.add_message(thread, "assistant", "It looks clear.")
    memory = diya_memory.open_memory(store, config)
    fact = memory.add_manual("is preparing for the board exam", "api")
    other = memory.add_manual("has a sister who studies law", "api")
    memory.set_person(other, "Asha", "api")
    diya_tasks.Tasks(store).add("buy a geometry box")
    store.add_reminder("call the school", due_at="tomorrow 9am")
    diya_automations.Automations(store).create("tell me the weather", "every morning at 8am")
    diya_feedback.Feedback(store).put(first, "negative", "wrong", "it should have said the 15th")
    conn = store.connect()
    try:
        conn.execute("INSERT INTO categories (name, meaning, origin, position, created_at) VALUES ('Exams', 'study', 'person', 0, '2026-10-01')")
        conn.execute("INSERT INTO message_categories (message_id, category_id, source, created_at) VALUES (?, 1, 'person', '2026-10-01')", (first,))
        conn.execute("INSERT INTO app_state (key, value) VALUES ('token_hash', ?)", (SECRETS[0],))
        conn.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at, failures) VALUES ('https://push.example/abc', ?, ?, '2026-10-01', 0)", (SECRETS[4], SECRETS[3]))
        conn.execute("INSERT INTO telegram_state (key, value) VALUES ('offset', ?)", (SECRETS[5],))
        conn.execute("INSERT INTO proactive_messages (kind, key, thread_id, message_id, text, created_at) VALUES ('brief', 'k', ?, ?, 'Good morning', '2026-10-02')", (thread, first))
        conn.commit()
    finally:
        conn.close()
    store.journal_add(tool="web_search", kind="tool", origin="chat", thread_id=thread, message_id=first, args_digest="d", args_preview="q=weather", status="ok", result_chars=10, duration_ms=300, note=None)
    diya_connectors.store_token(config, "google_calendar", SECRETS[1])
    return config, store, thread, first, second, fact


def read(folder, name):
    return (folder / name).read_text(encoding="utf-8")


def test_the_export_holds_each_kind_of_your_data_and_a_readme_that_counts_them(world, tmp_path):
    config, _store, _thread, first, _second, _fact = world
    folder, counts = diya_export.export(config, tmp_path / "out", NOW)
    assert folder.name == "diya-export-2026-10-25-093000" and folder.parent == tmp_path / "out"
    assert [json.loads(line)["id"] for line in read(folder, "messages.jsonl").splitlines()][0] == first and counts["messages.jsonl"] == 4
    chat = read(folder, "conversations.md")
    assert "## Chat 1: Exam plans" in chat and "**You**" in chat and "Noted: 14 March.\nGood luck!" in chat and "नमस्ते" in chat
    memory = json.loads(read(folder, "memory.json"))
    assert [f["text"] for f in memory] == ["is preparing for the board exam", "has a sister who studies law"] and memory[1]["person"] == "Asha" and memory[0]["history"][0]["event"] == "added"
    profile = read(folder, "memory_profile.txt")
    assert profile == "- is preparing for the board exam\n\nAbout Asha:\n- has a sister who studies law\n"
    assert json.loads(read(folder, "tasks.json"))[0]["content"] == "buy a geometry box"
    assert json.loads(read(folder, "reminders.json"))[0]["content"] == "call the school"
    assert json.loads(read(folder, "automations.json"))[0]["instruction"] == "tell me the weather"
    assert json.loads(read(folder, "categories.json")) == [{"message_id": first, "category": "Exams", "source": "person", "created_at": "2026-10-01"}]
    assert json.loads(read(folder, "feedback.json"))[0]["note"] == "it should have said the 15th"
    assert json.loads(read(folder, "activity.json"))[0]["tool"] == "web_search"
    assert json.loads(read(folder, "proactive.json"))[0]["text"] == "Good morning"
    readme = read(folder, "README.txt")
    assert "messages.jsonl" in readme and "Left out on purpose" in readme and "delete this folder" in readme and "2026-10-25 09:30:00" in readme


def test_no_secret_is_in_any_file_of_the_export(world, tmp_path):
    config, *_ = world
    folder, _ = diya_export.export(config, tmp_path / "out", NOW)
    for path in folder.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for secret in SECRETS:
                assert secret not in text, (path.name, secret)
            assert "push.example" not in text and "p256dh" not in text and "token_hash" not in text, path.name


def test_the_database_is_only_read_and_never_migrated(world, tmp_path):
    config, *_ = world
    before = hashlib.sha256(Path(config.db_path).read_bytes()).hexdigest()
    diya_export.export(config, tmp_path / "out", NOW)
    assert hashlib.sha256(Path(config.db_path).read_bytes()).hexdigest() == before
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE threads (id INTEGER PRIMARY KEY, title TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, thread_id INTEGER, role TEXT, content TEXT, created_at TEXT)")
    conn.execute("INSERT INTO threads VALUES (1, 'old chat', 'x')")
    conn.execute("INSERT INTO messages VALUES (1, 1, 'user', 'hello from long ago', 'x')")
    conn.commit()
    conn.close()
    folder, counts = diya_export.export(dataclasses.replace(config, db_path=str(old)), tmp_path / "out2", NOW)
    assert counts["messages.jsonl"] == 1 and json.loads(read(folder, "tasks.json")) == [] and "Not in this database" in read(folder, "README.txt")
    assert [r[0] for r in sqlite3.connect(old).execute("SELECT name FROM sqlite_master WHERE type='table'")] == ["threads", "messages"]  # nothing was added to it


def test_a_failed_run_leaves_nothing_half_made_and_a_second_export_never_replaces_the_first(world, tmp_path, monkeypatch):
    config, *_ = world
    out = tmp_path / "out"
    first, _ = diya_export.export(config, out, NOW)
    second, _ = diya_export.export(config, out, NOW)  # the same second
    assert first != second and first.is_dir() and second.is_dir() and second.name == "diya-export-2026-10-25-093000-2"

    def boom(*_args, **_kwargs):
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(diya_export, "_write_json", boom)
    with pytest.raises(RuntimeError):
        diya_export.export(config, out, datetime(2026, 10, 26, 8, 0, 0))
    assert sorted(p.name for p in out.iterdir()) == [first.name, second.name]  # no folder for the failed run, and no scratch folder left


def test_hidden_and_control_characters_are_written_as_visible_escapes_and_line_breaks_stay(world, tmp_path):
    config, store, thread, *_ = world
    store.add_message(thread, "user", f"line one\nline two {RLO}evil {TAG} end\x1b[31m")
    folder, _ = diya_export.export(config, tmp_path / "out", NOW)
    for name in ("conversations.md", "messages.jsonl"):
        text = read(folder, name)
        assert RLO not in text and TAG not in text and "\x1b" not in text, name
    chat = read(folder, "conversations.md")
    assert "line one\nline two" in chat and "\\u202e" in chat and "\\U000e0041" in chat and "\\u001b" in chat


def test_a_message_forgotten_for_good_is_not_in_the_export(world, tmp_path):
    config, store, _thread, _first, second, _fact = world
    diya_forget.forget_message(store, diya_memory.open_memory(store, config), config, second)
    folder, counts = diya_export.export(config, tmp_path / "out", NOW)
    assert "what about tomorrow" not in read(folder, "messages.jsonl") + read(folder, "conversations.md") and counts["messages.jsonl"] == 2


def test_an_action_is_exported_with_its_arguments_and_result_but_never_a_token(world, tmp_path):
    config, store, *_ = world
    kind = diya_actions.ActionKind("add_task", "Add a task", None, lambda args: None, lambda args: f"Add the task {args['title']!r}", lambda cfg, args: "done")
    actions = diya_actions.Actions(store, config, (kind,))
    action = actions.propose("add_task", {"title": "buy milk"})
    actions.approve(action["id"], action["args_hash"], "ui")
    actions.run(action["id"])
    folder, _ = diya_export.export(config, tmp_path / "out", NOW)
    found = json.loads(read(folder, "actions.json"))
    assert found[0]["args"] == {"title": "buy milk"} and found[0]["status"] == "succeeded" and found[0]["result"] == "done"


def test_the_folder_is_ignored_by_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/exports/" in ignore and "diya-export-*/" in ignore


def test_the_command_says_what_it_did_and_why_it_could_not(world, tmp_path):
    config, *_ = world
    out, err = io.StringIO(), io.StringIO()
    assert diya_export.main(["--out", str(tmp_path / "out")], config=config, out=out, err=err) == 0
    said = out.getvalue()
    assert "Wrote " in said and "messages.jsonl" in said and "private data" in said and err.getvalue() == ""
    missing = dataclasses.replace(config, db_path=str(tmp_path / "nope.db"))
    out, err = io.StringIO(), io.StringIO()
    assert diya_export.main(["--out", str(tmp_path / "out3")], config=missing, out=out, err=err) == 2
    assert "there is no database" in err.getvalue() and not (tmp_path / "nope.db").exists() and not (tmp_path / "out3").exists()
