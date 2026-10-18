"""Dreaming's receipts (dreaming.run_cycle, the dream_runs table, GET /api/dreaming, the Activity page's section; docs/DREAMING_RECEIPTS_DESIGN.md), added 2026-10-18.

What this proves, with the real Dreamer and memory and a scripted model: every scheduled pass leaves one row saying which messages it read, how many it staged, what the memory policy did with them and
whether anything went wrong; a pass that finds nothing is a row too (and is only counted on the page); a model that cannot be reached, a staging failure and a crash are each in the receipt, with the
checkpoint left where it was; a receipt cannot be changed or removed; a receipt that cannot be written never fails the pass; the route returns the busy passes newest first with text made safe to show;
and the Status page's Dreaming line is taken from the receipts and says when the last pass went wrong.
"""
import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_health as health
import diya_web
import dreaming
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient, FakeClient


class Quiet:
    def transcribe(self, path):
        return ""


@pytest.fixture
def world(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "d.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), auto_memory=True, categories=False, require_token=False,
    )
    return config, Store(config.db_path)


def say(store, text):
    return store.add_message(store.create_thread("t"), "user", text)


def run(config, store, client):
    dreamer = dreaming.Dreamer(config, client=client, store=store)
    dreaming.run_cycle(dreamer)
    return dreamer


def last(store):
    return store.dream_last_run()


def test_a_pass_with_nothing_new_leaves_a_receipt_that_says_so(world):
    config, store = world
    run(config, store, FakeClient())
    receipt = last(store)
    assert receipt["outcome"] == "nothing new" and receipt["messages_read"] == 0 and receipt["errors"] is None and receipt["duration_ms"] >= 0
    assert store.dream_runs_recent() == []  # not a busy pass: it is only counted
    assert store.dream_idle_count("2000-01-01T00:00:00+00:00") == 1


def test_a_pass_that_reads_messages_says_which_how_many_and_what_the_policy_did(world):
    config, store = world
    first = say(store, "I have a dog named Hog")
    last_id = say(store, "I play badminton on Sundays")
    run(config, store, ByQuestionClient(extraction=["- has a dog named Hog\n- plays badminton on Sundays"], privacy="OK"))
    receipt = last(store)
    assert (receipt["first_message_id"], receipt["last_message_id"], receipt["messages_read"], receipt["staged"]) == (first, last_id, 2, 2)
    assert receipt["remembered"] + receipt["asked"] + receipt["not_kept"] + receipt["held"] == 2 and receipt["outcome"] == "staged facts for the memory policy"
    assert [r["id"] for r in store.dream_runs_recent()] == [receipt["id"]]
    assert Memory(store).verify_integrity() == []


def test_a_pass_that_finds_no_facts_says_it_read_and_found_none(world):
    config, store = world
    say(store, "I like it when the weather is nice")
    run(config, store, ByQuestionClient(extraction=["NONE"]))
    receipt = last(store)
    assert receipt["messages_read"] == 1 and receipt["staged"] == 0 and receipt["outcome"] == "read the messages, found no new facts"


def test_messages_already_read_live_are_a_receipt_that_says_so(world):
    config, store = world
    message = say(store, "I have a dog named Hog")
    store.mark_captured(message, 1)
    run(config, store, FakeClient())
    assert last(store)["outcome"] == "everything new was already read live, or only asks something" and last(store)["messages_read"] == 0 and last(store)["first_message_id"] == message


def test_a_model_that_cannot_be_reached_is_in_the_receipt_and_the_checkpoint_did_not_move(world):
    config, store = world
    say(store, "I have a dog named Hog")
    run(config, store, FakeClient(chat_error=ConnectionError("ollama is not running")))
    receipt = last(store)
    assert receipt["outcome"] == "the model could not be reached: the checkpoint did not move" and receipt["staged"] == 0
    assert "ollama is not running" in json.loads(receipt["errors"])[0]
    assert not (config.dream_state_path and __import__("os").path.exists(config.dream_state_path))  # no checkpoint was written


def test_a_staging_failure_is_in_the_receipt(world, monkeypatch):
    config, store = world
    say(store, "I have a dog named Hog")
    monkeypatch.setattr(dreaming.Dreamer, "_append_pending", lambda self, record: (_ for _ in ()).throw(OSError("disk full")))
    run(config, store, ByQuestionClient(extraction=["- has a dog named Hog"]))
    receipt = last(store)
    assert receipt["outcome"] == "could not stage the facts: the checkpoint did not move" and "disk full" in receipt["errors"]


def test_a_crash_is_recorded_and_still_raised(world, monkeypatch):
    config, store = world
    monkeypatch.setattr(dreaming.Dreamer, "remember_on_its_own", lambda self: (_ for _ in ()).throw(RuntimeError("something odd")))
    with pytest.raises(RuntimeError, match="something odd"):
        run(config, store, FakeClient())
    receipt = last(store)
    assert receipt["outcome"] == "the pass stopped with an error" and "something odd" in receipt["errors"]
    assert [r["id"] for r in store.dream_runs_recent()] == [receipt["id"]]  # an error makes it a busy pass


def test_the_memory_pass_failing_is_in_the_receipt_and_does_not_stop_the_rest(world, monkeypatch):
    import diya_autonomy

    config, store = world
    say(store, "I have a dog named Hog")
    monkeypatch.setattr(diya_autonomy, "apply", lambda memory, **kw: (_ for _ in ()).throw(RuntimeError("the store is on fire")))
    run(config, store, ByQuestionClient(extraction=["- has a dog named Hog"]))
    receipt = last(store)
    assert receipt["staged"] == 1 and "the store is on fire" in receipt["errors"]


def test_a_receipt_cannot_be_changed_or_removed(world):
    config, store = world
    run(config, store, FakeClient())
    conn = sqlite3.connect(config.db_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE dream_runs SET outcome = 'nothing happened'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM dream_runs")
    finally:
        conn.close()
    with pytest.raises(ValueError, match="no secret"):
        store.dream_run_add(started_at="x", duration_ms=1, outcome="x", secret="x")


def test_a_receipt_that_cannot_be_written_never_fails_the_pass(world, monkeypatch, capsys):
    config, store = world
    monkeypatch.setattr(Store, "dream_run_add", lambda self, **f: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    run(config, store, FakeClient())  # does not raise
    assert "[error] The receipt for this pass could not be written" in capsys.readouterr().out


def test_the_scheduled_entry_point_writes_a_receipt(world, monkeypatch):
    config, store = world
    for name, value in (("DIYA_DB_PATH", config.db_path), ("DIYA_DREAM_LOG_PATH", config.dream_log_path), ("DIYA_DREAM_STATE_PATH", config.dream_state_path),
                        ("DIYA_DREAM_PENDING_PATH", config.dream_pending_path), ("DIYA_PROFILE_PATH", config.profile_path)):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(dreaming, "OpenAI", lambda **kw: FakeClient())
    assert dreaming.main() == 0
    assert last(store)["outcome"] == "nothing new"


# ---- the route and the health line ----------------------------------------------------------------------------------------------------------

def client_for(config, store):
    agent = diya.Agent(config, client=FakeClient(), store=store)
    return TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost")


def test_the_route_lists_busy_passes_newest_first_and_counts_the_idle_ones(world):
    config, store = world
    run(config, store, FakeClient())
    run(config, store, FakeClient())
    say(store, "I have a dog named Hog")
    run(config, store, ByQuestionClient(extraction=["- has a dog named Hog"], privacy="OK"))
    body = client_for(config, store).get("/api/dreaming").json()
    assert len(body["runs"]) == 1 and body["runs"][0]["staged"] == 1 and body["idle_last_day"] == 2 and body["last_run"]["id"] == body["runs"][0]["id"]
    assert body["runs"][0]["errors"] == [] and isinstance(body["runs"][0]["duration_ms"], int)


def test_the_route_makes_errors_safe_to_show_and_works_with_no_receipts(world):
    config, store = world
    assert client_for(config, store).get("/api/dreaming").json() == {"runs": [], "last_run": None, "idle_last_day": 0}
    store.dream_run_add(started_at=datetime.now(timezone.utc).isoformat(), duration_ms=5, outcome="bad\nline" + chr(0x202E), errors=json.dumps(["boom\nline" + chr(0x202E)]))
    run_shown = client_for(config, store).get("/api/dreaming").json()["runs"][0]
    assert "\n" not in run_shown["outcome"] and chr(0x202E) not in run_shown["outcome"] and all("\n" not in e and chr(0x202E) not in e for e in run_shown["errors"])


def test_the_status_line_comes_from_the_receipts_and_says_when_the_last_pass_went_wrong(world):
    config, store = world
    now = datetime.now()
    assert health.collect(config, store, now=now, ping=lambda c: (True, []))["items"][5]["status"] == "warn"  # never ran
    store.dream_run_add(started_at=(datetime.now(timezone.utc) - timedelta(minutes=150)).isoformat(), duration_ms=5, outcome="nothing new")
    item = health.collect(config, store, now=now, ping=lambda c: (True, []))["items"][5]
    assert item["status"] == "ok" and "Last ran 2 hours ago" in item["text"]
    store.dream_run_add(started_at=datetime.now(timezone.utc).isoformat(), duration_ms=5, outcome="the model could not be reached", errors=json.dumps(["no model"]))
    item = health.collect(config, store, now=now, ping=lambda c: (True, []))["items"][5]
    assert item["status"] == "warn" and "something went wrong in that pass" in item["text"]
    store.dream_run_add(started_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat(), duration_ms=5, outcome="nothing new")  # an older row does not hide the newest
    assert health.collect(config, store, now=now, ping=lambda c: (True, []))["items"][5]["status"] == "warn"
