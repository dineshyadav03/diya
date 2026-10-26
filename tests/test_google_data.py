"""What Diya keeps because of Google: shown, exported, purged (diya_google_data.py; DIYA-146; docs/GOOGLE_CHANGES.md), added 2026-10-27.

What this proves: the counts and the export hold the finished actions on Google (with their words), the words in the activity record for Google tools, and Diya's replies that carry a Google report, and never a sign-in, token or
secret; an export never overwrites a file; a purge says how much would go and removes nothing without --yes; each kind is purged on its own (finished actions only, with their events: a waiting action is left; activity: the
words are blanked, the row stays and a receipt is written; replies: only assistant messages that hold a report mark, with their search-index entries: a message the person wrote is never touched; connections: every connected Google
card is disconnected); and nothing else in the database is changed.
"""
import dataclasses
import json
import os

import pytest

import diya_actions
import diya_config
import diya_connectors
import diya_db
import diya_google_data as data
import diya_journal


@pytest.fixture
def world(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"), profile_path=str(tmp_path / "p.txt"),
                                 protect_secrets=False, require_token=False)
    store = diya_db.Store(config.db_path)
    for name in ("google_calendar", "google_tasks", "google_mail_send"):
        diya_connectors.store_token(config, name, "SECRET-REFRESH-TOKEN")
    thread = store.create_thread("t")
    store.add_message(thread, "user", "any email from the college?")
    store.add_message(thread, "assistant", "Dr Rao wrote.\n\nYour mail, searched for from college:\n- Tue · from Dr Rao · Exam moved")
    store.add_message(thread, "assistant", "Hello, how can I help?")
    store.add_message(thread, "user", "what is on my calendar?")
    store.add_message(thread, "assistant", "Your calendar for the next two weeks:\nTue 27 Oct\n  10:00  Dentist")
    diya_journal.record(store, "read_mail", {"question": "any email from the college?"}, "ok", kind="flow", note="the secret subject")
    diya_journal.record(store, "add_reminder", {"content": "call mum"}, "ok")
    actions = diya_actions.Actions(store, config, [])
    conn = store.connect()
    for kind, status in (("gmail_send", "succeeded"), ("google_tasks_add", "failed"), ("gmail_send", "pending"), ("todoist_add_task", "succeeded")):
        conn.execute("INSERT INTO actions (kind, args, args_hash, summary, status, tainted, taint_sources, created_at, expires_at) VALUES (?, ?, ?, ?, ?, 0, '[]', '2026-10-26T10:00:00Z', '2026-10-27T10:00:00Z')",
                     (kind, json.dumps({"to": "dad@example.com", "body": "I will be late"}), f"hash-{kind}-{status}", f"{kind} summary", status))
        conn.execute("INSERT INTO action_events (action_id, event, actor, at, detail) VALUES ((SELECT MAX(id) FROM actions), 'proposed', 'model', '2026-10-26T10:00:00Z', NULL)")
    conn.commit()
    conn.close()
    return config, store


def test_the_names_of_what_is_google_come_from_the_catalog_and_the_kinds():
    assert "read_mail" in data.google_tool_names() and "propose_send_gmail" in data.google_tool_names() and "add_reminder" not in data.google_tool_names()
    assert "gmail_send" in data.google_kinds() and "google_tasks_add" in data.google_kinds() and "todoist_add_task" not in data.google_kinds()


def test_the_counts_say_what_is_kept(world):
    config, store = world
    found = data.counts(config, store)
    assert found["actions_finished"] == 2 and found["actions_waiting"] == 1 and found["activity_rows"] == 1 and found["activity_rows_with_words"] == 1 and found["replies_with_google_reports"] == 2
    assert sorted(found["cards_connected"]) == ["google_calendar", "google_mail_send", "google_tasks"]


def test_the_export_holds_the_words_and_never_a_secret(world):
    config, store = world
    exported = data.export(config, store)
    text = json.dumps(exported)
    assert [a["kind"] for a in exported["actions"]] == ["gmail_send", "google_tasks_add", "gmail_send"] and exported["actions"][0]["args"]["to"] == "dad@example.com"
    assert exported["activity"][0]["tool"] == "read_mail" and exported["activity"][0]["note"] == "the secret subject" and len(exported["replies"]) == 2
    assert "SECRET-REFRESH-TOKEN" not in text and "todoist" not in text and "Hello, how can I help?" not in text


def test_the_command_line_shows_exports_to_a_new_file_and_refuses_to_overwrite(world, tmp_path):
    import io

    config, _ = world
    out, err = io.StringIO(), io.StringIO()
    assert data.main(["show"], config=config, out=out, err=err) == 0 and json.loads(out.getvalue())["actions_finished"] == 2
    target = str(tmp_path / "google_export.json")
    out = io.StringIO()
    assert data.main(["export", "--out", target], config=config, out=out, err=err) == 0 and "Wrote" in out.getvalue() and json.load(open(target, encoding="utf-8"))["counts"]["actions_finished"] == 2
    err = io.StringIO()
    assert data.main(["export", "--out", target], config=config, out=io.StringIO(), err=err) == data.EXIT_REFUSED and "already exists" in err.getvalue()


def test_a_purge_without_yes_removes_nothing_and_says_how_much(world):
    config, store = world
    before = data.counts(config, store)
    for what in ("actions", "activity", "replies", "connections"):
        report = data.purge(config, store, what)
        assert report["done"] is False and "left" in report
    assert data.counts(config, store) == before


def test_purging_actions_removes_the_finished_ones_with_their_events_and_leaves_the_waiting_and_the_others(world):
    config, store = world
    report = data.purge(config, store, "actions", confirm=True)
    conn = store.connect()
    left = [(r[0], r[1]) for r in conn.execute("SELECT kind, status FROM actions ORDER BY id")]
    events = conn.execute("SELECT COUNT(*) FROM action_events").fetchone()[0]
    conn.close()
    assert report["removed"] == 2 and left == [("gmail_send", "pending"), ("todoist_add_task", "succeeded")] and events == 2


def test_purging_activity_blanks_the_words_keeps_the_rows_and_writes_a_receipt(world):
    config, store = world
    report = data.purge(config, store, "activity", confirm=True)
    conn = store.connect()
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT tool, args_preview, note FROM tool_journal")}
    conn.close()
    assert report["blanked"] == 1 and rows["read_mail"] == (None, None) and rows["add_reminder"][0] is not None  # (an unrelated tool keeps its words)
    assert any(r["what"] == "blanked" and r["rows_changed"] == 1 for r in store.journal_receipts())


def test_purging_replies_removes_only_assistant_messages_with_a_google_report_and_never_the_persons_own(world):
    config, store = world
    report = data.purge(config, store, "replies", confirm=True)
    conn = store.connect()
    left = [(r[0], r[1]) for r in conn.execute("SELECT role, content FROM messages ORDER BY id")]
    conn.close()
    assert report["removed"] == 2 and left == [("user", "any email from the college?"), ("assistant", "Hello, how can I help?"), ("user", "what is on my calendar?")]


def test_purging_connections_disconnects_every_connected_google_card_and_tells_google_once(world, monkeypatch):
    import types

    import diya_google_calendar

    told = []
    monkeypatch.setattr(diya_google_calendar.httpx, "post", lambda url, **kw: told.append((url, kw)) or types.SimpleNamespace(status_code=200))
    config, store = world
    report = data.purge(config, store, "connections", confirm=True)
    assert sorted(report["disconnected"]) == ["google_calendar", "google_mail_send", "google_tasks"] and data.counts(config, store)["cards_connected"] == []
    assert len(told) == 1 and told[0][0] == diya_google_calendar.REVOKE_URL and report["revoked_at_google"] is True  # one telling, by the last card


def test_an_unknown_kind_is_refused(world):
    config, store = world
    with pytest.raises(ValueError):
        data.purge(config, store, "everything", confirm=True)


def test_the_purge_command_needs_a_known_kind_and_says_nothing_was_removed_without_yes(world):
    import io

    config, store = world
    out = io.StringIO()
    assert data.main(["purge", "--what", "actions"], config=config, out=out, err=io.StringIO()) == 0 and "Nothing was removed. Say --yes to do it." in out.getvalue() and data.counts(config, store)["actions_finished"] == 2
    assert data.main(["purge", "--what", "bogus"], config=config, out=io.StringIO(), err=io.StringIO()) != 0
