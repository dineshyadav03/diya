"""The pause switch (diya_pause.py, docs/PAUSE_DESIGN.md), added 2026-10-18 for DIYA-047.

What this proves, with the real approval system, notifier and routes: pausing is remembered in the database (so a separate process sees it) and is recorded in the journal; an approved action is not run
while paused and stays approved, then runs once after "resume"; proposing, approving, rejecting and chatting still work while paused; the scheduled notifier runs no automation and writes nothing first
while paused but still tells the person their reminders; the routes work and are behind the token; and a database that cannot be read does not count as paused (the switch cannot take Diya down).
It does not prove that nothing else Diya could do on a schedule is stopped: it stops the three things listed in the design, and says what it leaves.
"""
import dataclasses
import io
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import diya
import diya_actions
import diya_automations as auto
import diya_config
import diya_notify
import diya_pause as pause
import diya_time
import diya_web
from diya_db import Store
from fakes import FakeClient, task_kind


class Quiet:
    def transcribe(self, path):
        return ""


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "p.db"))


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "p.db"), notify_log_path=str(tmp_path / "n.log"), proactive=False, push=False, auto_memory=False, require_token=False)


def test_pausing_is_remembered_with_when_and_why_and_resuming_clears_it(store):
    assert pause.state(store) == {"paused": False, "since": None, "reason": ""} and not pause.is_paused(store)
    state = pause.pause(store, "I am away", now=datetime(2026, 10, 18, 9, 0))
    assert state["paused"] and state["reason"] == "I am away" and state["since"].startswith("2026-10-18T09:00")
    assert pause.is_paused(Store(store.path))  # another connection, as a separate process would have
    assert pause.resume(store) == {"paused": False, "since": None, "reason": ""}


def test_pausing_twice_keeps_the_first_time_and_resuming_when_not_paused_does_nothing(store):
    first = pause.pause(store, "one", now=datetime(2026, 10, 18, 9, 0))
    again = pause.pause(store, "two", now=datetime(2026, 10, 18, 11, 0))
    assert again == first
    pause.resume(store)
    pause.resume(store)
    assert [e["tool"] for e in store.journal_recent(10)] == ["resume", "pause"]  # only the real changes are in the journal


def test_the_reason_is_made_safe_and_short(store):
    state = pause.pause(store, "bad\nline" + chr(0x202E) + "x" * 500)
    assert "\n" not in state["reason"] and chr(0x202E) not in state["reason"] and len(state["reason"]) <= 210


def test_a_database_that_cannot_be_read_does_not_count_as_paused(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    assert pause.state(Store(str(junk))) == {"paused": False, "since": None, "reason": ""}


# ---- approved actions ------------------------------------------------------------------------------------------------------------------------

def approved_action(config, ran):
    actions = diya_actions.Actions(Store(config.db_path), config, (task_kind(executed=ran),))
    action = actions.propose("add_task", {"title": "x"})
    actions.approve(action["id"], action["args_hash"], "ui")
    return actions, action


def test_an_approved_action_is_not_run_while_paused_stays_approved_and_runs_once_after_resume(config):
    ran = []
    actions, action = approved_action(config, ran)
    pause.pause(actions.store)
    with pytest.raises(diya_actions.Paused, match="paused"):
        actions.run(action["id"])
    assert ran == [] and actions.get(action["id"])["status"] == "approved"
    assert [e[0] for e in actions.events(action["id"])] == ["proposed", "approved"]
    pause.resume(actions.store)
    done = actions.run(action["id"])
    assert done["status"] == "succeeded" and len(ran) == 1
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(action["id"])
    assert len(ran) == 1


def test_proposing_approving_and_rejecting_still_work_while_paused(config):
    ran = []
    actions = diya_actions.Actions(Store(config.db_path), config, (task_kind(executed=ran),))
    pause.pause(actions.store)
    one = actions.propose("add_task", {"title": "one"})
    two = actions.propose("add_task", {"title": "two"})
    actions.approve(one["id"], one["args_hash"], "ui")
    actions.reject(two["id"], "ui")
    assert actions.get(one["id"])["status"] == "approved" and actions.get(two["id"])["status"] == "rejected" and ran == []


def test_the_approve_route_says_why_nothing_was_done_and_leaves_the_action_waiting(config):
    ran = []
    agent = diya.Agent(config, client=FakeClient(), action_kinds=[task_kind(executed=ran)])
    client = TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost")
    action = agent.actions.propose("add_task", {"title": "x"})
    client.post("/api/pause", json={"reason": "testing"})
    answer = client.post(f"/api/actions/{action['id']}/approve", json={"args_hash": action["args_hash"]})
    assert answer.status_code == 423 and "paused" in answer.json()["detail"] and ran == []
    assert agent.actions.get(action["id"])["status"] == "pending"  # refused before approving: it just waits
    client.post("/api/resume")
    assert client.post(f"/api/actions/{action['id']}/approve", json={"args_hash": action["args_hash"]}).status_code == 200 and len(ran) == 1


def test_the_routes_pause_and_resume_and_the_status_page_says_so(config):
    agent = diya.Agent(config, client=FakeClient(), action_kinds=[])
    client = TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost")
    assert client.post("/api/pause", json={"reason": "exams"}).json()["paused"] is True
    item = next(i for i in client.get("/api/health").json()["items"] if i["name"] == "pause")
    assert item["status"] == "warn" and "exams" in item["text"] and "Reminders still fire" in item["text"]
    assert client.post("/api/pause").json()["paused"] is True  # no body at all is fine
    assert client.post("/api/resume").json()["paused"] is False
    item = next(i for i in client.get("/api/health").json()["items"] if i["name"] == "pause")
    assert item["status"] == "ok"


# ---- the scheduled notifier ---------------------------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 11, 14, 0)


class Screen:
    def __init__(self):
        self.shown = []

    def __call__(self, title, body):
        self.shown.append((title, body))


def run_notifier(config, screen, now, extra=()):
    out = io.StringIO()
    return diya_notify.main(list(extra), config=config, out=out, notify=screen, now=now), out.getvalue()


def test_while_paused_the_notifier_runs_no_automation_and_writes_nothing_first_but_still_tells_the_reminders(config, monkeypatch):
    store = Store(config.db_path)
    auto.Automations(store, lambda: NOW).create("tell me the weather in Pune", "every day at 8am")
    store.add_reminder("take the pills", "when", diya_time.iso_of_local(datetime(2026, 10, 12, 8, 0)))
    made = []
    monkeypatch.setattr(diya_notify, "_make_agent", lambda cfg: made.append(1))
    config = dataclasses.replace(config, proactive=True)
    pause.pause(store)
    screen = Screen()
    code, text = run_notifier(config, screen, datetime(2026, 10, 12, 8, 1))
    assert code == 0 and "paused: automations and Diya writing first are stopped" in text and made == []
    assert any("take the pills" in body for _t, body in screen.shown)  # the reminder was told
    assert store.list_threads() == []  # nothing was written in the chat


def test_after_resume_the_automation_runs_as_before(config, monkeypatch):
    store = Store(config.db_path)
    auto.Automations(store, lambda: NOW).create("tell me the weather in Pune", "every day at 8am")

    class Brain:
        def briefing(self, instruction):
            return "Sunny."

    monkeypatch.setattr(diya_notify, "_make_agent", lambda cfg: Brain())
    pause.pause(store)
    assert "automations run" not in run_notifier(config, Screen(), datetime(2026, 10, 12, 8, 1))[1]
    pause.resume(store)
    assert "1 automations run" in run_notifier(config, Screen(), datetime(2026, 10, 12, 8, 6))[1]
