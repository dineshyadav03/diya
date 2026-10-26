"""What was done after you approved it shows in the activity record (diya_actions.Actions.run, the Activity page; DIYA-056), added 2026-10-26.

Before, the Activity page listed what Diya did with a tool or an account, and the Actions page held the outcome of an approved action: two places. What this proves, with the real approval system and the real
journal: running an approved action writes one line of the record (named after its kind, which chat and message it came from, how long it took, how it came out: ok, error for a failure or an unknown outcome, refused
for one that could not start); the line holds the length of the result and a short outcome, never the result's words, and arguments named like a secret are hidden as for every tool; a run is never broken by a
record that cannot be written; each run writes exactly one line, and a refused second run writes none; and the Activity page words it as what you approved.
"""
import dataclasses
from pathlib import Path

import pytest

import diya_actions
import diya_config
import diya_journal
from diya_actions import ActionFailed, ActionUncertain, Actions
from diya_db import Store

ROOT = Path(__file__).resolve().parent.parent


def kind(execute):
    return diya_actions.ActionKind("add_task", "Add a task", None, lambda args: None, lambda args: f"Add the task {args['title']!r}", execute)


def world(tmp_path, execute):
    store = Store(str(tmp_path / "j.db"))
    config = dataclasses.replace(diya_config.load_config(), db_path=store.path)
    actions = Actions(store, config, (kind(execute),))
    thread = store.create_thread()
    message = store.add_message(thread, "user", "add a task")
    action = actions.propose("add_task", {"title": "buy milk", "api_token": "SECRET-VALUE"}, thread_id=thread, message_id=message)
    actions.approve(action["id"], action["args_hash"], "ui")
    return store, actions, action, thread, message


def lines(store):
    return [e for e in store.journal_recent(50) if e["tool"].startswith("approved:")]


def test_a_run_that_worked_is_one_line_with_its_kind_chat_message_and_time_and_not_the_resultss_words(tmp_path):
    store, actions, action, thread, message = world(tmp_path, lambda config, args: "the secret words of the result")
    actions.run(action["id"])
    (line,) = lines(store)
    assert (line["tool"], line["kind"], line["status"], line["thread_id"], line["message_id"]) == ("approved:add_task", "flow", "ok", thread, message)
    assert line["result_chars"] == len("the secret words of the result") and line["duration_ms"] is not None and line["note"] == "approved action done"
    assert "secret words" not in str(line) and "SECRET-VALUE" not in str(line) and "api_token=[hidden]" in line["args_preview"] and "buy milk" in line["args_preview"]


def test_a_failure_and_an_unknown_outcome_are_errors_and_an_action_that_could_not_start_is_refused(tmp_path):
    def fails(config, args):
        raise ActionFailed("the service said no")

    def unsure(config, args):
        raise ActionUncertain("no answer came")

    for number, (execute, note) in enumerate(((fails, "approved action failed"), (unsure, "outcome not known"))):
        folder = tmp_path / f"case{number}"
        folder.mkdir()
        store, actions, action, *_ = world(folder, execute)
        actions.run(action["id"])
        assert lines(store)[0]["status"] == "error" and note in lines(store)[0]["note"]
    folder = tmp_path / "cannot-start"
    folder.mkdir()
    store, actions, action, *_ = world(folder, lambda config, args: "done")
    actions.kinds = ()  # its kind is gone from this install, so it cannot start
    actions.run(action["id"])
    assert lines(store)[0]["status"] == "refused" and lines(store)[0]["note"] == "approved action not started"


def test_each_run_writes_exactly_one_line_and_a_refused_second_run_writes_none(tmp_path):
    store, actions, action, *_ = world(tmp_path, lambda config, args: "done")
    actions.run(action["id"])
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(action["id"])
    assert len(lines(store)) == 1


def test_a_record_that_cannot_be_written_never_breaks_a_run(tmp_path, monkeypatch):
    store, actions, action, *_ = world(tmp_path, lambda config, args: "done")

    def broken(*_args, **_kwargs):
        raise RuntimeError("the journal is not there")

    monkeypatch.setattr(store, "journal_add", broken)
    done = actions.run(action["id"])
    assert done["status"] == "succeeded" and lines(store) == []


def test_the_activity_page_words_it_as_what_you_approved():
    page = (ROOT / "frontend" / "app" / "activity" / "page.js").read_text(encoding="utf-8")
    assert "entry.tool.startsWith('approved:')" in page and "carried out what you approved" in page and "after you approved it" in page
