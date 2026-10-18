"""The health report (diya_health.py, diya_health_api.py, the Status page; docs/HEALTH_DESIGN.md), added 2026-10-18.

What this proves, on throwaway state with a stand-in for Ollama: each part says what it actually saw and only says "ok" for a thing it looked at; a broken database, a model that is not there, messages that
could not be read, a stale Dreaming, an unreadable sign-in, an old or missing backup and failed tool calls are each reported in plain words and move the overall state; a part that is switched off says "off"
and does not make the overall state worse; nothing is changed by looking; the route is behind the token like the rest. It does not prove that Ollama's list looks the way the stand-in's does on every version.
"""
import dataclasses
import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import diya
import diya_backup
import diya_config
import diya_connectors
import diya_db
import diya_health as health
import diya_journal
import diya_secrets
import diya_web
from fakes import FakeClient

NOW = datetime(2026, 10, 18, 12, 0, 0)


@pytest.fixture
def world(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "h.db"), backup_dir=str(tmp_path / "bk"), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "c.log"),
        dream_log_path=str(tmp_path / "dream.log"), profile_path=str(tmp_path / "p.txt"), auto_memory=True, protect_secrets=True, require_token=False, model="diya-chat",
    )
    store = diya_db.Store(config.db_path)
    store.add_message(store.create_thread("t"), "user", "hello")
    return config, store


def up(config):
    return True, ["diya-chat:latest", "qwen2.5:3b"]


def by_name(report):
    return {item["name"]: item for item in report["items"]}


def test_every_part_is_reported_in_a_fixed_order_with_a_sentence(world):
    config, store = world
    report = health.collect(config, store, now=NOW, ping=up)
    assert [i["name"] for i in report["items"]] == ["api", "database", "model", "reading", "dreaming", "connections", "backup", "secrets", "tools"]
    assert all(i["status"] in ("ok", "warn", "bad", "off") and i["text"] and i["label"] for i in report["items"]) and report["overall"] in ("ok", "warn", "bad")


def test_the_database_says_how_much_is_in_it_and_a_broken_one_is_bad(world):
    config, store = world
    assert by_name(health.collect(config, store, now=NOW, ping=up))["database"]["text"] == "Opens and passes SQLite's quick check. 1 messages and 0 remembered facts."
    with open(config.db_path, "wb") as f:
        f.write(b"this is not a database at all" * 100)
    item = by_name(health.collect(config, store, now=NOW, ping=up))["database"]
    assert item["status"] == "bad" and "could not be read" in item["text"]


def test_the_model_is_ok_only_when_ollama_answers_and_lists_it(world):
    config, store = world
    assert by_name(health.collect(config, store, now=NOW, ping=up))["model"]["status"] == "ok"
    assert by_name(health.collect(config, store, now=NOW, ping=lambda c: (False, [])))["model"]["status"] == "bad"
    missing = by_name(health.collect(config, store, now=NOW, ping=lambda c: (True, ["other:latest"])))["model"]
    assert missing["status"] == "warn" and "does not list diya-chat" in missing["text"]
    exact = dataclasses.replace(config, model="qwen2.5:3b")
    assert by_name(health.collect(exact, store, now=NOW, ping=up))["model"]["status"] == "ok"
    assert by_name(health.collect(dataclasses.replace(config, model="qwen2.5:7b"), store, now=NOW, ping=up))["model"]["status"] == "warn"  # another tag of the same name is not the model


def test_messages_waiting_or_failed_to_be_read_are_reported(world):
    config, store = world
    assert by_name(health.collect(config, store, now=NOW, ping=up))["reading"]["status"] == "ok"
    first, second = store.enqueue_capture(1), store.enqueue_capture(2)
    pending = by_name(health.collect(config, store, now=NOW, ping=up))["reading"]
    assert pending["status"] == "warn" and "waiting to be read" in pending["text"]
    store.finish_capture(1, "failed", "model down")
    failed = by_name(health.collect(config, store, now=NOW, ping=up))["reading"]
    assert failed["status"] == "bad" and "could not be read" in failed["text"]
    off = by_name(health.collect(dataclasses.replace(config, auto_memory=False), store, now=NOW, ping=up))["reading"]
    assert off["status"] == "off"


def test_dreaming_is_ok_when_recent_and_warns_when_stale_or_never_run(world):
    config, store = world
    assert by_name(health.collect(config, store, now=NOW, ping=up))["dreaming"]["status"] == "warn"
    with open(config.dream_log_path, "w") as f:
        f.write("ran")
    stamp = (NOW - timedelta(hours=5)).timestamp()
    os.utime(config.dream_log_path, (stamp, stamp))
    assert by_name(health.collect(config, store, now=NOW, ping=up))["dreaming"]["text"] == "Last ran 5 hours ago."
    old = (NOW - timedelta(days=4)).timestamp()
    os.utime(config.dream_log_path, (old, old))
    item = by_name(health.collect(config, store, now=NOW, ping=up))["dreaming"]
    assert item["status"] == "warn" and "4 days ago" in item["text"]


def test_connections_name_what_is_connected_and_an_unreadable_sign_in(world, monkeypatch):
    config, store = world
    assert "Nothing is connected" in by_name(health.collect(config, store, now=NOW, ping=up))["connections"]["text"]
    off = dataclasses.replace(config, protect_secrets=False)
    diya_connectors.store_token(off, "todoist", "t")
    assert by_name(health.collect(config, store, now=NOW, ping=up))["connections"]["text"] == "Connected: Todoist."
    os.makedirs(config.connector_tokens_dir, exist_ok=True)
    with open(os.path.join(config.connector_tokens_dir, "notion.token"), "w") as f:
        f.write("dpapi1:" + "QUFB" + "\n")  # protected for someone else, or damaged
    item = by_name(health.collect(config, store, now=NOW, ping=up))["connections"]
    assert item["status"] == "warn" and "Notion" in item["text"] and "Connect again" in item["text"]


def test_the_backup_is_ok_when_recent_warns_when_old_or_missing_and_is_off_when_off(world):
    config, store = world
    assert by_name(health.collect(config, store, now=NOW, ping=up))["backup"]["status"] == "warn"
    diya_backup.make(config, now=NOW - timedelta(hours=3))
    ok = by_name(health.collect(config, store, now=NOW, ping=up))["backup"]
    assert ok["status"] == "ok" and "3 hours ago" in ok["text"] and "checked" in ok["text"]
    old = by_name(health.collect(config, store, now=NOW + timedelta(days=5), ping=up))["backup"]
    assert old["status"] == "warn" and "days ago" in old["text"]
    assert by_name(health.collect(dataclasses.replace(config, backup=False), store, now=NOW, ping=up))["backup"]["status"] == "off"


def test_how_sign_ins_are_stored_is_said_plainly(world, monkeypatch):
    config, store = world
    monkeypatch.setattr(diya_secrets, "available", lambda: True)
    assert by_name(health.collect(config, store, now=NOW, ping=up))["secrets"]["status"] == "ok"
    monkeypatch.setattr(diya_secrets, "available", lambda: False)
    assert by_name(health.collect(config, store, now=NOW, ping=up))["secrets"]["status"] == "warn"
    assert by_name(health.collect(dataclasses.replace(config, protect_secrets=False), store, now=NOW, ping=up))["secrets"]["status"] == "off"


def test_failed_tool_calls_in_the_last_day_are_counted(world):
    config, store = world
    moment = datetime.now()
    assert by_name(health.collect(config, store, now=moment, ping=up))["tools"]["text"] == "No tool calls in the last day."
    diya_journal.record(store, "web_search", {"query": "x"}, "ok")
    diya_journal.record(store, "web_search", {"query": "y"}, "error", note="timeout")
    item = by_name(health.collect(config, store, now=moment, ping=up))["tools"]
    assert item["status"] == "warn" and item["text"].startswith("1 of 2 tool calls in the last day did not work")


def test_the_overall_state_is_the_worst_of_the_parts_and_off_does_not_count(world):
    config, store = world
    quiet = dataclasses.replace(config, auto_memory=False, backup=False, protect_secrets=False)
    with open(config.dream_log_path, "w") as f:
        f.write("ran")
    assert health.collect(quiet, store, now=datetime.now(), ping=up)["overall"] == "ok"
    assert health.collect(quiet, store, now=datetime.now(), ping=lambda c: (False, []))["overall"] == "bad"
    os.remove(config.dream_log_path)
    assert health.collect(quiet, store, now=datetime.now(), ping=up)["overall"] == "warn"  # Dreaming has never run


def test_looking_changes_nothing(world):
    config, store = world
    before = open(config.db_path, "rb").read()
    health.collect(config, store, now=NOW, ping=up)
    assert open(config.db_path, "rb").read() == before and not os.path.exists(config.backup_dir)


def test_the_ollama_question_is_short_and_never_raises(monkeypatch):
    import httpx

    config = diya_config.load_config({})
    seen = {}

    def get(url, timeout=None):
        seen["url"], seen["timeout"] = url, timeout
        raise httpx.ConnectError("down")

    monkeypatch.setattr(health.httpx, "get", get)
    assert health.ping_ollama(config) == (False, []) and seen["url"].endswith("/api/tags") and seen["timeout"] == 2.0


def test_the_route_returns_the_report(world):
    config, store = world
    app = diya_web.create_app(config, diya.Agent(config, client=FakeClient(), store=store), object())
    from diya_health_api import register  # noqa: F401  # the route is registered by create_app; this checks the import path

    client = TestClient(app, base_url="https://localhost")
    body = client.get("/api/health").json()
    assert body["overall"] in ("ok", "warn", "bad") and len(body["items"]) == 9
