"""Where repeating reminders meet the rest (docs/SCHEDULE_DESIGN.md, D3 and unit R2): the notifier, the Reminders listing and the
agent's list_reminders.

What this proves: the notifier makes the reminder for a series whose time has come and tells it once, with no one having
opened the app; a dry run makes and records nothing; a database error while making them is reported and does not stop the
reminders that are already due from being told; the Reminders listing and the agent's tool make what has come due before they
show anything and say which reminders came from a series; and the model is told what repeats, when it next falls and whether
it is paused.
"""
import dataclasses
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_notify
import diya_schedule
import diya_time
import diya_web
from diya_db import Store
from diya_notify import NotifyError, run_once
from fakes import FakeClient, text_reply

NOW = datetime(2026, 10, 10, 10, 15)  # a Saturday, 10:15 local
LOCAL = "https://localhost"


def ts(local):
    return diya_time.iso_of_local(local)


class Screen:
    def __init__(self):
        self.shown = []

    def __call__(self, title, body):
        self.shown.append((title, body))


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "i.db"))


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def schedule(store, clock):
    return diya_schedule.Schedule(store, clock=lambda: clock["now"])


# ---- the notifier -----------------------------------------------------------------------------------------

def test_the_notifier_makes_and_tells_a_repeating_reminder_whose_time_has_come(store, schedule):
    schedule.create("take out the bins", "every Monday at 9am")
    screen = Screen()
    report = run_once(store, screen, now=datetime(2026, 10, 12, 9, 5))
    assert (report.due, report.told, report.failed) == (1, 1, 0)
    assert [body for _, body in screen.shown] == ["take out the bins"]
    again = Screen()
    assert run_once(store, again, now=datetime(2026, 10, 12, 9, 6)) == diya_notify.Report(0, 0, 0) and again.shown == []  # told once
    assert [e["event"] for e in schedule.events()] == ["created", "occurred"]


def test_before_its_time_the_notifier_makes_and_tells_nothing(store, schedule):
    schedule.create("take out the bins", "every Monday at 9am")
    screen = Screen()
    assert run_once(store, screen, now=datetime(2026, 10, 12, 8, 59)) == diya_notify.Report(0, 0, 0)
    assert screen.shown == [] and store.reminders("all") == []


def test_a_dry_run_says_what_it_would_tell_but_makes_nothing_so_records_nothing(store, schedule):
    schedule.create("take out the bins", "every Monday at 9am")
    lines = []
    report = run_once(store, Screen(), now=datetime(2026, 10, 12, 9, 5), dry_run=True, say=lines.append)
    assert report.due == 0 and lines == [] and store.reminders("all") == [] and len(schedule.events()) == 1


def test_a_database_error_while_making_them_is_said_and_the_reminders_already_due_are_still_told(store, schedule, monkeypatch):
    schedule.create("repeating", "every Monday at 9am")
    store.add_reminder("one-off", "x", ts(datetime(2026, 10, 12, 8, 0)))

    def broken(self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(diya_schedule.Schedule, "materialize", broken)
    screen, lines = Screen(), []
    report = run_once(store, screen, now=datetime(2026, 10, 12, 9, 5), say=lines.append)
    assert (report.due, report.told) == (1, 1) and [body for _, body in screen.shown] == ["one-off"]
    assert lines == ["could not make the repeating reminders that are due: database is locked"]


def test_a_schedule_error_while_making_them_is_said_too(store, schedule, monkeypatch):
    def broken(self):
        raise diya_schedule.IllegalState("nope")

    monkeypatch.setattr(diya_schedule.Schedule, "materialize", broken)
    lines = []
    run_once(store, Screen(), now=NOW, say=lines.append)
    assert lines == ["could not make the repeating reminders that are due: nope"]


def test_what_is_said_about_a_failure_has_no_reminders_words_and_hidden_characters_are_escaped(store, monkeypatch):
    def broken(self):
        raise sqlite3.OperationalError("bad" + chr(27) + "[2J")

    monkeypatch.setattr(diya_schedule.Schedule, "materialize", broken)
    lines = []
    run_once(store, Screen(), now=NOW, say=lines.append)
    assert chr(27) not in lines[0] and "u001b" in lines[0]


def test_a_failed_notification_for_a_made_reminder_is_tried_again_next_pass(store, schedule):
    schedule.create("take pills", "every day at 8am")
    flaky = {"fail": True}

    def screen(title, body):
        if flaky["fail"]:
            raise NotifyError("not now")

    first = run_once(store, screen, now=datetime(2026, 10, 11, 8, 5), say=lambda line: None)
    assert (first.due, first.told, first.failed) == (1, 0, 1)
    flaky["fail"] = False
    second = run_once(store, Screen(), now=datetime(2026, 10, 11, 8, 6))
    assert (second.due, second.told) == (1, 1)  # made once, told on the second try


# ---- the agent and the Reminders listing ---------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(
        diya_config.load_config(), db_path=str(data / "i.db"), profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"), dream_log_path=str(data / "dream.log"), dream_pending_path=str(data / "pending.jsonl"),
        connector_tokens_dir=str(data / "tokens"), connectors_log_path=str(data / "c.log"), require_token=False,
    )


@pytest.fixture
def agent(config, clock):
    return diya.Agent(config, client=FakeClient([text_reply("ok")] * 5), clock=lambda: clock["now"])


@pytest.fixture
def client(config, agent):
    return TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL)


def test_the_agent_has_a_schedule_on_the_same_clock_and_store(agent, clock):
    assert agent.schedule.store is agent.store
    agent.schedule.create("bins", "every Monday at 9am")
    assert agent.schedule.get(1)["next_ts"] == ts(datetime(2026, 10, 12, 9, 0))


def test_the_tool_that_lists_reminders_makes_what_has_come_due_first_and_names_what_repeats(agent, clock):
    agent.schedule.create("take pills", "every day at 8am")
    agent.store.add_reminder("one-off")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    said = agent.list_reminders()
    assert said.split("\n") == [
        "#1: one-off", "#2: take pills (due Sunday 11 Oct 2026, 08:00)", "Repeating reminders:",
        "repeat #1: take pills (every day at 08:00; next Monday 12 Oct 2026, 08:00)",
    ]


def test_a_paused_series_is_listed_as_paused_with_no_next_time_and_a_stopped_one_is_not_listed(agent):
    agent.schedule.create("a", "every day at 8am")
    agent.schedule.create("b", "every day at 9am")
    agent.schedule.create("c", "every day at 10am")
    agent.schedule.pause(1)
    agent.schedule.stop(3)
    assert agent.list_reminders().split("\n") == [
        "No pending reminders.", "Repeating reminders:", "repeat #1: a (every day at 08:00 (paused))",
        "repeat #2: b (every day at 09:00; next Sunday 11 Oct 2026, 09:00)",
    ]


def test_with_nothing_pending_and_nothing_repeating_the_tool_still_says_so(agent):
    assert agent.list_reminders() == "No pending reminders."


def test_a_series_that_is_stopped_and_has_nothing_pending_leaves_the_plain_answer(agent):
    agent.schedule.create("a", "every day")
    agent.schedule.stop(1)
    assert agent.list_reminders() == "No pending reminders."


def test_a_busy_database_does_not_stop_the_tool_listing_what_is_there(agent, monkeypatch):
    agent.store.add_reminder("one-off")

    def broken(self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(diya_schedule.Schedule, "materialize", broken)
    assert agent.make_due_repeats() == [] and agent.list_reminders() == "#1: one-off"


def test_a_schedule_error_does_not_stop_it_either(agent, monkeypatch):
    def broken(self):
        raise diya_schedule.TooManySeries("no")

    monkeypatch.setattr(diya_schedule.Schedule, "materialize", broken)
    assert agent.make_due_repeats() == []


def test_the_reminders_listing_makes_what_has_come_due_and_says_which_came_from_a_series(client, agent, clock):
    agent.schedule.create("take pills", "every day at 8am")
    plain = agent.store.add_reminder("one-off", "x", ts(datetime(2026, 10, 11, 7, 0)))
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    items = {r["content"]: r for r in client.get("/api/reminders").json()["reminders"]}
    assert items["take pills"]["series"] == 1 and items["take pills"]["state"] == "due"
    assert items["one-off"]["series"] is None and items["one-off"]["id"] == plain
    assert len(client.get("/api/reminders").json()["reminders"]) == 2  # looking again makes no second one


def test_a_reminder_typed_on_the_page_is_not_from_a_series(client):
    body = client.post("/api/reminders", json={"text": "call mum", "when": "tomorrow"}).json()
    assert body["reminder"]["series"] is None and body["reminders"][0]["series"] is None
