"""The day over HTTP (docs/SCHEDULE_DESIGN.md, D8 and unit R5): diya_brief_api.py.

What this proves: the route gives the brief for the agent's own clock, built from what is stored; it makes the repeating reminders
that have come due before it looks, so the brief is current whoever looked first; what a model or a person wrote reaches the browser
with control, invisible and direction-changing characters escaped, however deep; only GET exists; and building the app touches no store.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import diya
import diya_brief_api
import diya_config
import diya_memory
import diya_time
import diya_web
from fakes import FakeClient, text_reply

LOCAL = "https://localhost"
NOW = datetime(2026, 10, 10, 10, 15)  # a Saturday, 10:15 local
ESC, BIDI, ZWSP = chr(27), chr(0x202E), chr(0x200B)


def ts(local):
    return diya_time.iso_of_local(local)


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def parts(tmp_path, clock):
    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(
        diya_config.load_config(), db_path=str(data / "b.db"), profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"), dream_log_path=str(data / "dream.log"), dream_pending_path=str(data / "pending.jsonl"),
        connector_tokens_dir=str(data / "tokens"), connectors_log_path=str(data / "c.log"), require_token=False,
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 5), clock=lambda: clock["now"])
    return TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL), agent


@pytest.fixture
def client(parts):
    return parts[0]


@pytest.fixture
def agent(parts):
    return parts[1]


def no_hidden(value):
    if isinstance(value, str):
        return all(not diya_memory._unwanted(ch) for ch in value)
    if isinstance(value, dict):
        return all(no_hidden(k) and no_hidden(v) for k, v in value.items())
    if isinstance(value, list):
        return all(no_hidden(v) for v in value)
    return True


def test_an_empty_day_is_an_answer_not_an_error(client):
    response = client.get("/api/today")
    assert response.status_code == 200
    body = response.json()
    assert body["headline"] == "Nothing is due today." and body["date"] == "Saturday 10 Oct 2026"
    assert body["due_now"] == [] and body["later_today"] == [] and body["tasks_overdue"] == [] and body["tasks_today"] == [] and body["repeating"] == []


def test_the_brief_is_built_from_what_is_stored_for_the_agents_own_day(client, agent):
    agent.store.add_reminder("call mum", "at 9am", ts(datetime(2026, 10, 10, 9, 0)))
    agent.store.add_reminder("dentist", "at 5pm", ts(datetime(2026, 10, 10, 17, 0)))
    agent.tasks.add("pay rent", "Oct 10 at 5pm")
    agent.schedule.create("take pills", "every day at 6pm")
    body = client.get("/api/today").json()
    assert body["headline"] == "1 reminder due now, 1 reminder later today, 1 task due today, 1 repeating reminder making one today."
    assert [r["content"] for r in body["due_now"]] == ["call mum"] and [r["content"] for r in body["later_today"]] == ["dentist"]
    assert [t["content"] for t in body["tasks_today"]] == ["pay rent"] and [s["content"] for s in body["repeating"]] == ["take pills"]
    assert body["counts"]["repeating_today"] == 1


def test_looking_makes_the_repeating_reminders_that_have_come_due_so_the_brief_is_current(client, agent, clock):
    agent.schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    body = client.get("/api/today").json()
    assert [(r["content"], r["repeats"]) for r in body["due_now"]] == [("take pills", True)]
    assert body["repeating"][0]["next"] == "Monday 12 Oct 2026, 08:00"
    assert [r["content"] for r in agent.store.reminders("pending")] == ["take pills"]


def test_the_brief_changes_nothing_but_the_repeating_reminders_it_had_to_catch_up(client, agent):
    agent.store.add_reminder("call mum", "x", ts(datetime(2026, 10, 10, 9, 0)))
    agent.tasks.add("pay rent", "Oct 10 at 5pm")
    before = (agent.store.reminders("all"), agent.tasks.tasks("all"), agent.schedule.series("all"), agent.schedule.events())
    for _ in range(3):
        client.get("/api/today")
    assert (agent.store.reminders("all"), agent.tasks.tasks("all"), agent.schedule.series("all"), agent.schedule.events()) == before


def test_nothing_from_the_database_reaches_the_browser_with_a_hidden_character(client, agent):
    agent.store.add_reminder("call" + ESC + "[2J mum" + BIDI + "evil", "x", ts(datetime(2026, 10, 10, 9, 0)))
    agent.store.add_reminder("zero" + ZWSP + "width", "x", ts(datetime(2026, 10, 10, 17, 0)))
    conn = agent.store.connect()
    conn.execute("INSERT INTO tasks (content, content_key, due_at, due_ts, done, source, created_at) VALUES (?, 'k', ?, ?, 0, 'chat', 't')",
                 ("task" + ESC + "[2J", "Oct 10 at 9am", ts(datetime(2026, 10, 10, 9, 0))))
    conn.execute("INSERT INTO reminder_series (content, content_key, rule, said, next_ts, source, created_at) VALUES (?, 'k2', 'daily@18:00', 'x', ?, 'chat', 't')",
                 ("series" + BIDI + "evil", ts(datetime(2026, 10, 10, 18, 0))))
    conn.commit()
    conn.close()
    body = client.get("/api/today").json()
    assert no_hidden(body)
    assert chr(92) + "u001b" in body["due_now"][0]["content"] and chr(92) + "u202e" in body["due_now"][0]["content"]
    assert chr(92) + "u200b" in body["later_today"][0]["content"]
    assert chr(92) + "u001b" in body["tasks_overdue"][0]["content"] and chr(92) + "u202e" in body["repeating"][0]["content"]


def test_safe_reaches_into_lists_and_dicts_and_leaves_numbers_and_nothing_alone():
    value = {"a": ["x" + ESC, {"b": "y" + BIDI}], "n": 3, "none": None, "flag": True}
    assert diya_brief_api._safe(value) == {"a": ["x" + chr(92) + "u001b", {"b": "y" + chr(92) + "u202e"}], "n": 3, "none": None, "flag": True}


def test_only_get_exists_on_this_route(client):
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert client.request(method, "/api/today").status_code == 405


def test_building_the_app_touches_no_store():
    import types

    agent = types.SimpleNamespace()  # no .schedule, .store, .tasks or .make_due_repeats at all
    config = dataclasses.replace(diya_config.load_config(), require_token=False)
    app = diya_web.create_app(config, agent, object())
    assert "/api/today" in {route.path for route in app.routes}


# ---- what the mutation run found nothing checking ----------------------------------------------------------------------

def test_what_is_done_is_not_in_the_day(client, agent):
    done_reminder = agent.store.add_reminder("already done", "x", ts(datetime(2026, 10, 10, 9, 0)))
    agent.store.complete_reminder(done_reminder)
    agent.store.add_reminder("still to do", "x", ts(datetime(2026, 10, 10, 9, 30)))
    done_task = agent.tasks.add("paid already", "Oct 10 at 5pm")
    agent.tasks.complete(done_task["id"])
    agent.tasks.add("still to pay", "Oct 10 at 6pm")
    body = client.get("/api/today").json()
    assert [r["content"] for r in body["due_now"]] == ["still to do"]
    assert [t["content"] for t in body["tasks_today"]] == ["still to pay"]
