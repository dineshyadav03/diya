"""Repeating reminders and snooze over HTTP (docs/SCHEDULE_DESIGN.md, D4 and unit R4): diya_schedule_api.py.

What this proves: the list says which repeating reminders are active, paused or stopped, in words, with when each next falls
(and nothing next for one that is paused or stopped), and what happened lately in plain sentences; one the person types has its
repeat read by the same reader as the model's and a refusal says why and saves nothing; pause, resume, skip and stop each do one
thing, refuse what makes no sense with a 409 and an unknown id with a 404; snooze moves a pending reminder and refuses a time it
cannot read, a done reminder and one that is not there; everything a person is shown reaches the browser with control, invisible
and direction-changing characters escaped; only GET and POST exist; and building the app touches no store.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_memory
import diya_schedule
import diya_schedule_api
import diya_time
import diya_web
from fakes import FakeClient, text_reply

LOCAL = "https://localhost"
NOW = datetime(2026, 10, 10, 10, 15)  # a Saturday, 10:15 local
ESC, BIDI, ZWSP = chr(27), chr(0x202E), chr(0x200B)


def ts(local):
    return diya_time.iso_of_local(local)


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(
        diya_config.load_config(), db_path=str(data / "s.db"), profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"), dream_log_path=str(data / "dream.log"), dream_pending_path=str(data / "pending.jsonl"),
        connector_tokens_dir=str(data / "tokens"), connectors_log_path=str(data / "c.log"), require_token=False,
    )


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def parts(config, clock):
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 10), clock=lambda: clock["now"])
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


# --- listing ----------------------------------------------------------------------------------------------

def test_an_empty_list_says_so_with_zero_counts(client):
    assert client.get("/api/scheduled").json() == {"series": [], "events": [], "counts": {"active": 0, "paused": 0, "ended": 0}}


def test_each_series_is_shown_in_words_with_when_it_next_falls_active_first_then_paused_then_stopped(client, agent):
    agent.schedule.create("take out the bins", "every Monday at 9am")
    agent.schedule.create("take pills", "every day at 8am", source="page")
    agent.schedule.create("water plants", "every Friday", source="page")
    agent.schedule.create("old one", "every month on the 15th", source="page")
    agent.schedule.pause(2)
    agent.schedule.stop(4)
    body = client.get("/api/scheduled").json()
    assert [(s["id"], s["state"]) for s in body["series"]] == [(1, "active"), (3, "active"), (2, "paused"), (4, "ended")]
    assert body["counts"] == {"active": 2, "paused": 1, "ended": 1}
    bins = body["series"][0]
    assert bins == {"id": 1, "content": "take out the bins", "said": "every Monday at 9am", "rule": "Every Monday at 09:00", "next": "Monday 12 Oct 2026, 09:00",
                    "state": "active", "from_chat": True, "ended_at": None}
    by_id = {s["id"]: s for s in body["series"]}
    assert by_id[2]["next"] is None and by_id[2]["state"] == "paused" and by_id[2]["from_chat"] is False  # a paused one has no next time to promise
    assert by_id[4]["next"] is None and by_id[4]["ended_at"] == ts(NOW)


def test_looking_makes_what_has_come_due_so_the_listing_is_current(client, agent, clock):
    agent.schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    body = client.get("/api/scheduled").json()
    assert body["series"][0]["next"] == "Monday 12 Oct 2026, 08:00"
    assert [r["content"] for r in agent.store.reminders("all")] == ["take pills"]


def test_what_happened_lately_is_told_in_sentences_newest_first_and_cut_to_the_last_few(client, agent, clock, monkeypatch):
    agent.schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 20, 9, 0)  # nine days later: ten times, one reminder made
    client.get("/api/scheduled")
    agent.schedule.pause(1)
    agent.schedule.resume(1)
    agent.schedule.skip(1)
    agent.schedule.stop(1)
    texts = [e["text"] for e in client.get("/api/scheduled").json()["events"]]
    assert texts == [
        "Stopped “take pills”", "Skipped the next time of “take pills”", "Resumed “take pills”", "Paused “take pills”",
        "Made the reminder for “take pills”", "Missed 9 earlier times of “take pills” (Diya was not looking); made one reminder",
        "Set up “take pills” from the chat",
    ]
    monkeypatch.setattr(diya_schedule_api, "EVENTS_SHOWN", 2)
    assert [e["text"] for e in client.get("/api/scheduled").json()["events"]] == ["Stopped “take pills”", "Skipped the next time of “take pills”"]


def test_a_single_missed_time_is_not_pluralised_and_a_lapsed_and_a_snoozed_reminder_are_told(client, agent, clock):
    agent.schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    client.get("/api/scheduled")  # makes the first
    clock["now"] = datetime(2026, 10, 13, 9, 0)  # two more times: the first one lapses, one is missed
    client.get("/api/scheduled")
    agent.schedule.snooze(2, "in an hour")
    texts = [e["text"] for e in client.get("/api/scheduled").json()["events"]]
    assert "Missed 1 earlier time of “take pills” (Diya was not looking); made one reminder" in texts
    assert "Closed an older reminder of “take pills” that was never done, because a newer one arrived" in texts
    assert "Pushed a reminder back (it is one of “take pills”)" in texts


def test_a_one_off_reminder_that_is_pushed_back_is_told_without_a_series(client, agent):
    rid = agent.store.add_reminder("x", "x", ts(datetime(2026, 10, 11, 9, 0)))
    agent.schedule.snooze(rid, "tomorrow")
    assert client.get("/api/scheduled").json()["events"][0]["text"] == "Pushed a reminder back"


def test_an_event_about_a_series_the_list_does_not_name_is_still_told(client, agent):
    conn = agent.store.connect()
    conn.execute("INSERT INTO schedule_events (series_id, event, actor, at) VALUES (99, 'paused', 'owner', 't')")
    conn.commit()
    conn.close()
    assert client.get("/api/scheduled").json()["events"][0]["text"] == "Paused a repeating reminder"


# --- making one --------------------------------------------------------------------------------------------

def test_a_series_typed_on_the_page_is_made_with_its_repeat_read_and_the_list_comes_back(client, agent):
    response = client.post("/api/scheduled", json={"text": "  take   out the bins ", "repeat": "every Monday"})
    assert response.status_code == 201
    body = response.json()
    assert body["created"]["content"] == "take out the bins" and body["created"]["rule"] == "Every Monday at 09:00"
    assert body["created"]["from_chat"] is False and body["assumed"] == ["no time was given, so 09:00"]
    assert body["counts"] == {"active": 1, "paused": 0, "ended": 0}
    assert [s["id"] for s in body["series"]] == [body["created"]["id"]]  # the list comes back too, and holds the new one
    assert body["events"][0]["text"] == "Set up “take out the bins”"  # made by the owner, not the model
    (row,) = agent.schedule.series()
    assert (row["content"], row["rule"], row["source"], row["said"]) == ("take out the bins", "weekly:0@09:00", "page", "every Monday")
    assert agent.schedule.events()[0]["actor"] == "owner"


@pytest.mark.parametrize("repeat, part", [
    ("every hour", "more often than once a day"), ("soon", "say 'every"), ("every week", "needs a day"), ("every Monday until June", "an end or a count"),
    ("", "no repeat was given"),
])
def test_a_repeat_that_cannot_be_read_is_refused_with_the_reason_and_saves_nothing(client, agent, repeat, part):
    response = client.post("/api/scheduled", json={"text": "x", "repeat": repeat})
    assert response.status_code == 422 and part in response.json()["detail"] and response.json()["detail"].startswith("I could not read")
    assert agent.schedule.series("all") == []


@pytest.mark.parametrize("text, part", [("", "needs something"), ("  \n ", "needs something"), ("x" * 301, "at most 300"),
                                        ("call" + ESC + "[2J mum", "cannot contain the character"), ("mum" + BIDI + "evil", "cannot contain")])
def test_text_that_cannot_be_used_is_refused_and_saves_nothing(client, agent, text, part):
    response = client.post("/api/scheduled", json={"text": text, "repeat": "every day"})
    assert response.status_code == 422 and part in response.json()["detail"] and no_hidden(response.json())
    assert agent.schedule.series("all") == []


def test_the_same_repeating_reminder_twice_and_too_many_are_conflicts(client, agent, monkeypatch):
    assert client.post("/api/scheduled", json={"text": "bins", "repeat": "every Monday"}).status_code == 201
    again = client.post("/api/scheduled", json={"text": "BINS", "repeat": "every monday at 9am"})
    assert again.status_code == 409 and again.json()["detail"] == "that repeating reminder is already set"
    monkeypatch.setattr(diya_schedule, "MAX_ACTIVE", 1)
    full = client.post("/api/scheduled", json={"text": "other", "repeat": "every Tuesday"})
    assert full.status_code == 409 and "1 repeating reminders are already set" in full.json()["detail"]
    assert len(agent.schedule.series("all")) == 1


@pytest.mark.parametrize("body", [{}, {"text": "x"}, {"repeat": "every day"}, {"text": 5, "repeat": "every day"}, {"text": "x", "repeat": 5},
                                  {"text": None, "repeat": "every day"}, {"text": "x", "repeat": ["every day"]}])
def test_a_body_of_the_wrong_shape_is_refused_and_saves_nothing(client, agent, body):
    assert client.post("/api/scheduled", json=body).status_code == 422
    assert agent.schedule.series("all") == []


# --- pause, resume, skip, stop -------------------------------------------------------------------------------

def test_each_change_does_one_thing_and_hands_back_the_list(client, agent):
    agent.schedule.create("bins", "every Monday at 9am")
    paused = client.post("/api/scheduled/1/pause").json()
    assert paused["id"] == 1 and paused["series"][0]["state"] == "paused" and paused["counts"] == {"active": 0, "paused": 1, "ended": 0}
    resumed = client.post("/api/scheduled/1/resume").json()
    assert resumed["series"][0]["state"] == "active" and resumed["series"][0]["next"] == "Monday 12 Oct 2026, 09:00"
    skipped = client.post("/api/scheduled/1/skip").json()
    assert skipped["series"][0]["next"] == "Monday 19 Oct 2026, 09:00"
    stopped = client.post("/api/scheduled/1/stop").json()
    assert stopped["series"][0]["state"] == "ended" and stopped["counts"] == {"active": 0, "paused": 0, "ended": 1}
    assert [e["event"] for e in agent.schedule.events()] == ["created", "paused", "resumed", "skipped", "stopped"]


@pytest.mark.parametrize("setup, action, detail", [
    ([], "resume", "is not paused"), (["pause"], "pause", "already paused"), (["pause"], "skip", "paused; resume it first"),
    (["stop"], "pause", "has been stopped"), (["stop"], "resume", "has been stopped"), (["stop"], "skip", "has been stopped"),
    (["stop"], "stop", "already been stopped"),
])
def test_what_makes_no_sense_is_a_conflict_that_changes_nothing(client, agent, setup, action, detail):
    agent.schedule.create("bins", "every Monday at 9am")
    for step in setup:
        getattr(agent.schedule, step)(1)
    before, trail = agent.schedule.get(1), agent.schedule.events()
    response = client.post(f"/api/scheduled/1/{action}")
    assert response.status_code == 409 and detail in response.json()["detail"]
    assert agent.schedule.get(1) == before and agent.schedule.events() == trail


@pytest.mark.parametrize("action", ["pause", "resume", "skip", "stop"])
@pytest.mark.parametrize("path_id, status", [
    ("99", 404), ("0", 404), ("-5", 404), ("9223372036854775808", 404), ("-9223372036854775809", 404), ("abc", 422), ("1.5", 422),
])
def test_an_unknown_series_or_id_is_refused_and_never_an_error(client, action, path_id, status):
    assert client.post(f"/api/scheduled/{path_id}/{action}").status_code == status


def test_an_action_the_schedule_does_not_have_is_not_found_and_touches_nothing(client, agent):
    agent.schedule.create("bins", "every Monday at 9am")
    for action in ("delete", "edit", "undo", "run"):
        assert client.post(f"/api/scheduled/1/{action}").status_code == 404
    assert agent.schedule.get(1)["paused"] is False and len(agent.schedule.events()) == 1


def test_changing_one_series_touches_no_other(client, agent):
    for name in "abc":
        agent.schedule.create(name, "every day")
    client.post("/api/scheduled/2/pause")
    assert [s["state"] for s in client.get("/api/scheduled").json()["series"]] == ["active", "active", "paused"]


# --- snooze -------------------------------------------------------------------------------------------------

def test_snoozing_moves_a_pending_reminder_and_says_when_it_will_be_told_again(client, agent):
    rid = agent.store.add_reminder("call mum", "x", ts(datetime(2026, 10, 10, 9, 0)))
    response = client.post(f"/api/reminders/{rid}/snooze", json={"when": "in 10 minutes"})
    assert response.status_code == 200
    assert response.json() == {"id": rid, "due": ts(datetime(2026, 10, 10, 10, 25)), "due_text": "Saturday 10 Oct 2026, 10:25", "assumed": []}
    assert agent.store.get_reminder(rid)["due_ts"] == ts(datetime(2026, 10, 10, 10, 25))


def test_a_snooze_that_assumes_something_says_what(client, agent):
    rid = agent.store.add_reminder("call mum")
    assert client.post(f"/api/reminders/{rid}/snooze", json={"when": "tomorrow"}).json()["assumed"] == ["no time was given, so 09:00"]


@pytest.mark.parametrize("when", ["soonish", "yesterday", "", "next Friday", "at 5"])
def test_a_time_that_cannot_be_read_or_has_passed_is_refused_with_the_reason_and_moves_nothing(client, agent, when):
    rid = agent.store.add_reminder("x", "x", ts(datetime(2026, 10, 12, 9, 0)))
    response = client.post(f"/api/reminders/{rid}/snooze", json={"when": when})
    assert response.status_code == 422 and response.json()["detail"].startswith("I could not tell when")
    assert agent.store.get_reminder(rid)["due_ts"] == ts(datetime(2026, 10, 12, 9, 0))


def test_a_done_reminder_is_a_conflict_and_an_unknown_one_is_not_found(client, agent):
    rid = agent.store.add_reminder("x")
    agent.store.complete_reminder(rid)
    done = client.post(f"/api/reminders/{rid}/snooze", json={"when": "tomorrow"})
    assert done.status_code == 409 and "already done" in done.json()["detail"]
    assert client.post("/api/reminders/99/snooze", json={"when": "tomorrow"}).status_code == 404


@pytest.mark.parametrize("path_id, status", [("0", 404), ("-1", 404), ("9223372036854775808", 404), ("abc", 422)])
def test_a_snooze_id_that_cannot_be_a_reminder_is_refused(client, path_id, status):
    assert client.post(f"/api/reminders/{path_id}/snooze", json={"when": "tomorrow"}).status_code == status


@pytest.mark.parametrize("body", [{}, {"when": 5}, {"when": None}, {"when": ["tomorrow"]}])
def test_a_snooze_body_of_the_wrong_shape_is_refused(client, agent, body):
    rid = agent.store.add_reminder("x")
    assert client.post(f"/api/reminders/{rid}/snooze", json=body).status_code == 422


def test_snoozing_a_reminder_that_a_series_made_leaves_the_series_alone(client, agent, clock):
    agent.schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 8, 30)
    rid = agent.schedule.materialize()[0]
    before = agent.schedule.get(1)
    assert client.post(f"/api/reminders/{rid}/snooze", json={"when": "in an hour"}).status_code == 200
    assert agent.schedule.get(1) == before


# --- what reaches the browser -----------------------------------------------------------------------------------

def test_nothing_from_the_database_reaches_the_browser_with_a_hidden_character(client, agent):
    conn = agent.store.connect()
    conn.execute(
        "INSERT INTO reminder_series (content, content_key, rule, said, next_ts, source, created_at) VALUES (?, 'k', 'daily@09:00', ?, ?, 'chat', 't')",
        ("call" + ESC + "[2J mum" + BIDI + "evil", "every" + ZWSP + " day", ts(datetime(2026, 10, 11, 9, 0))),
    )
    conn.execute("INSERT INTO schedule_events (series_id, event, actor, at) VALUES (1, 'created', 'model', 't')")
    conn.commit()
    conn.close()
    body = client.get("/api/scheduled").json()
    assert no_hidden(body)
    assert chr(92) + "u001b" in body["series"][0]["content"] and chr(92) + "u200b" in body["series"][0]["said"]
    assert chr(92) + "u202e" in body["events"][0]["text"]


def test_a_refusal_reason_is_made_safe_whatever_it_says(client, agent, monkeypatch):
    def refuse(*args, **kwargs):
        raise diya_schedule.IllegalState("bad" + ESC + "[2J" + BIDI + "evil (#12)")

    monkeypatch.setattr(agent.schedule, "pause", refuse)
    response = client.post("/api/scheduled/1/pause")
    detail = response.json()["detail"]
    assert response.status_code == 409 and no_hidden(response.json()) and "(#12)" not in detail and chr(92) + "u001b" in detail


def test_only_get_and_post_exist_on_these_routes(client):
    for path in ("/api/scheduled", "/api/scheduled/1/pause", "/api/scheduled/1/resume", "/api/scheduled/1/skip", "/api/scheduled/1/stop",
                 "/api/reminders/1/snooze"):
        for method in ("PUT", "DELETE", "PATCH"):
            assert client.request(method, path).status_code == 405
    assert client.get("/api/scheduled/1/pause").status_code == 405 and client.get("/api/reminders/1/snooze").status_code == 405


def test_building_the_app_touches_no_store():
    import types

    agent = types.SimpleNamespace()  # no .schedule and no .make_due_repeats at all
    config = dataclasses.replace(diya_config.load_config(), require_token=False)
    app = diya_web.create_app(config, agent, object())
    assert {"/api/scheduled", "/api/scheduled/{series_id}/pause", "/api/scheduled/{series_id}/resume", "/api/scheduled/{series_id}/skip",
            "/api/scheduled/{series_id}/stop", "/api/reminders/{reminder_id}/snooze"} <= {route.path for route in app.routes}


# ---- what the mutation run found nothing checking ----------------------------------------------------------------------

def test_the_listing_carries_the_fifteen_latest_things_that_happened_newest_first(client, agent):
    agent.schedule.create("bins", "every Monday at 9am")
    for _ in range(9):
        agent.schedule.pause(1)
        agent.schedule.resume(1)  # nineteen events in all
    events = client.get("/api/scheduled").json()["events"]
    assert diya_schedule_api.EVENTS_SHOWN == 15 and len(events) == 15
    assert [e["id"] for e in events] == list(range(19, 4, -1))  # the fifteen newest, the newest first
    assert events[0]["text"] == "Resumed “bins”" and events[-1]["text"] == "Resumed “bins”"


def test_a_series_that_was_paused_and_then_stopped_is_stopped(client, agent):
    agent.schedule.create("bins", "every Monday at 9am")
    agent.schedule.pause(1)
    agent.schedule.stop(1)
    body = client.get("/api/scheduled").json()
    assert (body["series"][0]["state"], body["series"][0]["next"]) == ("ended", None)
    assert body["counts"] == {"active": 0, "paused": 0, "ended": 1}


def test_each_thing_that_happened_says_who_did_it(client, agent, clock):
    agent.schedule.create("by the model", "every day at 8am")
    agent.schedule.create("by the owner", "every day at 9am", source="page")
    clock["now"] = datetime(2026, 10, 11, 8, 30)
    client.get("/api/scheduled")  # makes the first one's reminder
    agent.schedule.pause(2)
    who = [(e["event"], e["who"]) for e in reversed(client.get("/api/scheduled").json()["events"])]
    assert who == [("created", "model"), ("created", "owner"), ("occurred", "system"), ("paused", "owner")]


def test_the_reason_for_an_unreadable_repeat_quotes_it_with_single_spaces(client):
    response = client.post("/api/scheduled", json={"text": "x", "repeat": "  every    hour  "})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("I could not read 'every hour' as a repeat: more often than once a day")


def test_a_snooze_the_reader_refuses_says_which_words_and_why(client, agent):
    rid = agent.store.add_reminder("x")
    response = client.post(f"/api/reminders/{rid}/snooze", json={"when": "  soonish  "})
    assert response.json()["detail"] == "I could not tell when 'soonish' is: could not read 'soonish' as a time"
    past = client.post(f"/api/reminders/{rid}/snooze", json={"when": "yesterday"})
    assert past.json()["detail"] == "I could not tell when 'yesterday' is: that time has already passed"
