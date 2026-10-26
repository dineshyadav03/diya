"""A weekly plan checked against the calendar before anything is proposed (diya_weekly_plan.py, Agent._plan_week; DIYA-141; docs/GOOGLE_CHANGES.md), added 2026-10-27.

What this proves: a plain request to plan the week is read into things, how many times and how long; each session goes in the earliest free gap of the calendar (never on an event, never on another session, never in the
past, spreading one thing over different days first); a session that fits no gap is said not to fit and nothing is proposed for it; the first few sessions (one message may lead to at most three actions) are proposed as
events for the owner to approve, with the plan shown first; with the calendar or the add-events card not connected the plan is still shown and says so; and nothing is made without an approval.
"""
import dataclasses
import random
from datetime import date, datetime, time, timedelta

import pytest

import diya
import diya_actions
import diya_calendar_find as cf
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_client as client
import diya_google_write as gw
import diya_time
import diya_weekly_plan as wp
from fakes import FakeClient
from test_google_calchange import Calendar, event, stamp

MONDAY = date(2026, 11, 2)
NOW = datetime(2026, 10, 30, 12, 0)  # (a Friday before that Monday)


def busy(day, start, end):
    begins, ends = datetime.combine(day, time(*start)), datetime.combine(day, time(*end))
    return {"start": {"dateTime": begins.astimezone().isoformat()}, "end": {"dateTime": ends.astimezone().isoformat()}}


def plan_for(**kwargs):
    base = {"items": [("Study physics", 3, 60)], "first": MONDAY, "last": MONDAY + timedelta(days=6), "label": "next week"}
    return dict(base, **kwargs)


@pytest.mark.parametrize("text, items", [
    ("plan my week: study physics 3 times for 1 hour, gym 2 times for 45 minutes", [("Study physics", 3, 60), ("Gym", 2, 45)]),
    ("plan next week: reading 2 times for 90 minutes", [("Reading", 2, 90)]),
    ("please plan my week study maths 2x 2 hours and gym 1 time for 30 min", [("Study maths", 2, 120)]),
])
def test_a_request_to_plan_the_week_is_read_into_things_times_and_lengths(text, items):
    found = wp.request(text, date(2026, 10, 27))
    assert found is not None and found["items"][:len(items)] == items


@pytest.mark.parametrize("text", ["plan my holiday", "plan my week", "plan my week: relax", "plan my week: study 30 times for 1 hour", "plan the week: gym 2 times for 5 hours", "what is on my calendar", "x" * 400])
def test_other_messages_are_not_a_request_to_plan_the_week(text):
    assert wp.request(text, date(2026, 10, 27)) is None


def test_next_week_starts_on_the_coming_monday_and_this_week_runs_to_sunday():
    assert wp.request("plan next week: gym 1 times for 1 hour", date(2026, 10, 27))["first"] == date(2026, 11, 2)
    this = wp.request("plan my week: gym 1 times for 1 hour", date(2026, 10, 27))
    assert this["first"] == date(2026, 10, 27) and this["last"] == date(2026, 11, 1)


def test_sessions_of_one_thing_go_on_different_days_in_the_earliest_free_gap():
    placed, missed = wp.schedule([], plan_for(), NOW)
    assert missed == [] and [(s[1].date(), s[1].time()) for s in placed] == [(MONDAY, time(9)), (MONDAY + timedelta(days=1), time(9)), (MONDAY + timedelta(days=2), time(9))]


def test_a_second_thing_goes_after_the_first_on_a_day_and_not_on_top_of_it():
    placed, _ = wp.schedule([], plan_for(items=[("Study physics", 2, 60), ("Gym", 2, 45)]), NOW)
    assert [(s[0], s[1].date().day, s[1].time()) for s in placed] == [("Study physics", 2, time(9)), ("Gym", 2, time(10)), ("Study physics", 3, time(9)), ("Gym", 3, time(10))]


def test_an_event_on_the_calendar_is_never_overlapped():
    events = [busy(MONDAY, (9, 0), (12, 0))]
    placed, _ = wp.schedule(events, plan_for(items=[("Study physics", 1, 60)]), NOW)
    assert placed[0][1] == datetime.combine(MONDAY, time(12))  # the gap after the meeting
    full = [busy(MONDAY + timedelta(days=n), (9, 0), (18, 0)) for n in range(7)]
    placed, missed = wp.schedule(full, plan_for(), NOW)
    assert placed == [] and len(missed) == 3 and "no free gap of that length is left between 9:00 and 18:00" in missed[0]


def test_a_session_that_fits_nowhere_is_said_not_to_fit_and_the_others_are_still_placed():
    events = [busy(MONDAY + timedelta(days=n), (9, 0), (16, 30)) for n in range(7)]  # 1.5 hours left each day
    placed, missed = wp.schedule(events, plan_for(items=[("Study physics", 2, 60), ("Workshop", 1, 120)]), NOW)
    assert [s[0] for s in placed] == ["Study physics", "Study physics"] and len(missed) == 1 and missed[0].startswith("workshop, session 1 of 1 (120 minutes)")


def test_nothing_is_placed_in_the_past():
    today = datetime(2026, 11, 4, 14, 0)  # a Wednesday afternoon
    placed, _ = wp.schedule([], plan_for(first=today.date(), last=today.date() + timedelta(days=2), items=[("Study physics", 1, 60)]), today)
    assert placed[0][1] >= today and placed[0][1].date() == today.date()


def test_no_session_ever_overlaps_an_event_or_another_session_over_many_random_weeks():
    rng = random.Random(11)
    for _ in range(200):
        events = []
        for day in range(7):
            for _n in range(rng.randint(0, 3)):
                hour = rng.randint(8, 17)
                events.append(busy(MONDAY + timedelta(days=day), (hour, rng.choice([0, 30])), (min(hour + rng.randint(1, 3), 20), 0)))
        items = [(f"Thing {n}", rng.randint(1, 3), rng.choice([30, 45, 60, 90])) for n in range(rng.randint(1, 3))]
        placed, _ = wp.schedule(events, plan_for(items=items), NOW)
        spans = [(s[1], s[1] + timedelta(minutes=s[2])) for s in placed]
        for begins, ends in spans:
            assert time(9) <= begins.time() and (ends.time() <= time(18) or ends.time() == time(0)) and begins.date() == ends.date()
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                assert a[1] <= b[0] or b[1] <= a[0]
        for e in events:
            e_begins, e_ends = cf._local(e["start"]["dateTime"]), cf._local(e["end"]["dateTime"])
            assert all(ends <= e_begins or begins >= e_ends for begins, ends in spans)


# ---- in the chat ----------------------------------------------------------------------------------------------------------------------------------------

CARDS = ("google_calendar", "google_calendar_edit")


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False, lookup=False)
    for name in CARDS:
        diya_connectors.store_token(config, name, "refresh")
    return config


@pytest.fixture
def calendar(monkeypatch):
    service = Calendar()
    service.events.clear()
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "tok" if name in CARDS else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return service


def chat(config):
    return diya.Agent(config, client=FakeClient([]), action_kinds=list(gw.action_kinds()))


def test_the_plan_is_shown_then_the_first_sessions_are_proposed_for_approval_and_nothing_is_made_yet(config, calendar):
    agent = chat(config)
    answer, tools = agent.ask([{"role": "user", "content": "plan next week: study physics 2 times for 1 hour, gym 2 times for 45 minutes"}])
    actions = agent.actions.actions()
    assert tools == ["read_calendar", "propose_calendar_event"] and agent.client.chat_calls == []
    assert answer.startswith("Plan for next week, placed in the gaps of your calendar between 9:00 and 18:00:") and "- Study physics (1 hour): " in answer and "- Gym (45 minutes): " in answer
    assert len(actions) == diya_actions.MAX_PER_TURN == 3 and "3 of the 4 session(s) are proposed on your calendar for you to approve; ask again for the rest. Nobody is invited." in answer
    assert "Ready for your OK:" in answer and all(a["status"] == "pending" and a["tainted"] and a["kind"] == "google_calendar_add_event" for a in actions) and calendar.mutations() == []
    assert actions[0]["args"]["title"] == "Study physics" and actions[0]["args"]["duration_minutes"] == 60


def test_an_approved_session_is_made_on_the_calendar_at_the_planned_time(config, calendar):
    agent = chat(config)
    agent.ask([{"role": "user", "content": "plan next week: study physics 1 times for 1 hour"}])
    (action,) = agent.actions.pending()
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    done = agent.actions.run(action["id"])
    assert done["status"] == "succeeded" and any(e["summary"] == "Study physics" and e["start"]["dateTime"] == action["args"]["start"] for e in calendar.events.values())


def test_the_plan_avoids_what_is_already_on_the_calendar(config, calendar):
    monday = date.today() + timedelta(days=7 - date.today().weekday())
    calendar.add(event("evmeeting001", "Lectures", stamp(datetime.combine(monday, time(9)).astimezone()), 180))
    agent = chat(config)
    agent.ask([{"role": "user", "content": "plan next week: study physics 1 times for 1 hour"}])
    (action,) = agent.actions.pending()
    planned = diya_time.local_from_iso(action["args"]["start"])
    assert not (datetime.combine(monday, time(9)) <= planned < datetime.combine(monday, time(12)))


def test_without_the_add_events_card_the_plan_is_still_shown_and_says_how_to_connect_it(config, calendar):
    diya_connectors.disconnect(config, "google_calendar_edit")
    agent = chat(config)
    answer, tools = agent.ask([{"role": "user", "content": "plan next week: study physics 2 times for 1 hour"}])
    assert answer.startswith("Plan for next week") and "connect Google Calendar (add events)" in answer and agent.actions.actions() == [] and tools == ["read_calendar"]


def test_without_the_calendar_it_says_so_and_asks_nothing_of_google(config, calendar):
    diya_connectors.disconnect(config, "google_calendar")
    agent = chat(config)
    answer, _ = agent.ask([{"role": "user", "content": "plan next week: study physics 2 times for 1 hour"}])
    assert "Google Calendar is not connected" in answer and calendar.requests == [] and agent.actions.actions() == []


def test_a_session_that_cannot_fit_is_reported_in_the_reply_and_not_proposed(config, calendar):
    monday = date.today() + timedelta(days=7 - date.today().weekday())
    for n in range(7):
        calendar.add(event(f"evfull00000{n}", f"Busy {n}", stamp(datetime.combine(monday + timedelta(days=n), time(9)).astimezone()), 540))
    agent = chat(config)
    answer, _ = agent.ask([{"role": "user", "content": "plan next week: study physics 2 times for 1 hour"}])
    assert "nothing fits" in answer and "Did not fit:" in answer and agent.actions.actions() == [] and calendar.mutations() == []
