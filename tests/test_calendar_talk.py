"""What is on the calendar, written by code (diya_calendar_talk, diya_google_calendar.events_between, diya_when.upcoming_day; found on 2026-10-21), added 2026-10-21.

The first real calendar answer was written by the model, which turned 2020 into "2.020", added emoji and made a block that began in 2020 sound new. What this proves, with a fixed clock and a stand-in for Google: a plain
question about the calendar is taken and a request, a long message, "next Friday" and a question about something else are not; the days are the ones asked about (today, tomorrow, this week, this weekend, a weekday
name, a date, the next N days, else two weeks) and the Google request is for exactly those local days; events are written day by day with their time, an all-day event as "all day" with the correct last day (Google's end is
the day after), a timed event in the person's own zone, a multi-day one with when it ends, and one that began before the window as "Still on" with when it started and ends; the year is never rewritten; an event title
that carries control or invisible characters is cleaned and one that is huge is cut; nothing on the days gives "Nothing on your calendar"; more than the limit says so; a Google refusal is said in words with its reason;
not connected is said in words only when the person said calendar; and through the real chat the model is not asked and the exchange is journalled as a flow. It does not read your real calendar: that was done once by hand.
"""
import dataclasses
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import diya
import diya_calendar_talk as ct
import diya_config
import diya_connectors
import diya_google_calendar as gc
import diya_web
import diya_when
from fakes import ByQuestionClient
from test_categories import FakeTranscriber, LOCAL

TODAY = date(2026, 10, 21)  # a Wednesday


@pytest.mark.parametrize("question, first, last", [
    ("what's on my calendar?", TODAY, TODAY + timedelta(days=13)),
    ("what's on my calendar today", TODAY, TODAY), ("any meetings tomorrow?", date(2026, 10, 22), date(2026, 10, 22)),
    ("what's on my calendar this week?", date(2026, 10, 19), date(2026, 10, 25)), ("events this weekend", date(2026, 10, 24), date(2026, 10, 25)),
    ("what have I got next week", date(2026, 10, 26), date(2026, 11, 1)), ("what do I have on Saturday", date(2026, 10, 24), date(2026, 10, 24)),
    ("calendar for wednesday", TODAY, TODAY), ("events on 28 Oct", date(2026, 10, 28), date(2026, 10, 28)), ("what do I have on 3 January", date(2027, 1, 3), date(2027, 1, 3)),
    ("meetings on 2026-11-02", date(2026, 11, 2), date(2026, 11, 2)), ("show my calendar for the next 3 days", TODAY, date(2026, 10, 23)),
    ("tell me what's on my calendar", TODAY, TODAY + timedelta(days=13)), ("what's my schedule today", TODAY, TODAY), ("can you show my calendar for friday", date(2026, 10, 23), date(2026, 10, 23)),
])
def test_a_plain_question_is_taken_for_the_days_it_asks_about(question, first, last):
    found = ct.asks(question, TODAY)
    assert found is not None and (found[0], found[1]) == (first, last)


@pytest.mark.parametrize("text", [
    "add dentist to my calendar", "schedule a meeting tomorrow", "cancel my meeting on friday", "move the event to saturday", "remind me about the meeting",
    "what am I doing wrong", "what's on my mind", "what's on tv tonight", "what am I doing with my life", "what's on my list today", "what do I have to do today", "what do I have on my list", "what's the weather", "what do you know about my calendar habits", "how are you", "what is the capital of France",
    "x" * 200, "what's on my\ncalendar", "", None, 5,
])
def test_a_request_or_anything_else_goes_on_to_the_model(text):
    assert ct.asks(text, TODAY) is None


def test_a_weekday_name_is_its_next_day_and_next_friday_is_not_guessed():
    assert diya_when.upcoming_day("on saturday", TODAY) == date(2026, 10, 24) and diya_when.upcoming_day("this friday", TODAY) == date(2026, 10, 23)
    assert diya_when.upcoming_day("on wednesday", TODAY) == TODAY and diya_when.upcoming_day("next friday", TODAY) is None
    assert diya_when.upcoming_day("on 3 jan", TODAY) == date(2027, 1, 3) and diya_when.upcoming_day("on 20 oct", TODAY) == date(2027, 10, 20)  # a day already gone is next year's
    assert diya_when.upcoming_day("nothing", TODAY) is None and diya_when.upcoming_day(None, TODAY) is None and diya_when.upcoming_day("on 31 feb", TODAY) is None


TUE = date(2026, 10, 27)  # a Tuesday: the day the model answered "next Tuesday" with Sunday 22 Nov


@pytest.mark.parametrize("today, question, day", [
    (TUE, '"what am I doing next Tuesday?', date(2026, 11, 3)),  # the exact message, quote mark and all
    (TUE, "what's on next tuesday", date(2026, 11, 3)), (TUE, "what do I have next tuesday", date(2026, 11, 3)),
    (date(2026, 10, 26), "what am I doing next Tuesday?", date(2026, 11, 3)),  # a Monday: this Tuesday is tomorrow, next Tuesday is the one after
    (date(2026, 10, 25), "what am I doing next Tuesday?", date(2026, 10, 27)),  # a Sunday: next week starts tomorrow
    (TUE, "any meetings next friday?", date(2026, 11, 6)), (TODAY, "what's on my calendar next friday", date(2026, 10, 30)),
    (TUE, "am I free next monday?", date(2026, 11, 2)), (TUE, "what's on tuesday?", TUE), (TUE, "what am I doing tomorrow", date(2026, 10, 28)),
])
def test_next_weekday_is_picked_by_code_not_by_the_model(today, question, day):
    found = ct.asks(question, today)
    assert found is not None and found[0] == found[1] == day


def test_the_answer_says_the_date_it_picked():
    first, last, label = ct.asks('"what am I doing next Tuesday?', TUE)
    assert label == "Tuesday 3 Nov (next Tuesday)"
    assert ct.format_events([], first, last, label, TUE) == "Nothing on your calendar for Tuesday 3 Nov (next Tuesday)."


def test_next_weekday_is_the_same_weekday_of_the_following_week():
    for offset in range(14):  # whatever day it is asked on, a Tuesday of next week, 1 to 13 days ahead, never in the past
        today = TUE + timedelta(days=offset)
        day = diya_when.next_weekday("next tuesday", today)
        assert day.weekday() == 1 and 1 <= (day - today).days <= 13 and day > diya_when._monday(today) + timedelta(days=6)
    assert diya_when.next_weekday("on tuesday", TUE) is None and diya_when.next_weekday(None, TUE) is None and diya_when.next_weekday("next tuesday", None) is None


def event(title, start, end, all_day=False):
    return {"title": title, "start": start, "end": end, "all_day": all_day}


LOCAL_ZONE = datetime.now().astimezone().tzinfo


def at(day, hour, minute=0):
    """An event time as Google gives it: with the person's own zone."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL_ZONE).isoformat()


def test_events_are_written_day_by_day_with_the_time_the_all_day_ones_and_the_ones_that_cross_days():
    d1, d2 = date(2026, 10, 24), date(2026, 10, 28)
    events = [
        event("Orchestrate", at(d1, 18), at(d1 + timedelta(days=1), 18)),
        event("Standup", at(d2, 9, 30), at(d2, 10)),
        event("Registration", d2.isoformat(), (d2 + timedelta(days=1)).isoformat(), all_day=True),
        event("Winter break", "2020-12-20", "2027-01-03", all_day=True),
        event("Quick call", at(d2, 14), at(d2, 14)),
    ]
    text = ct.format_events(events, TODAY, date(2026, 11, 3), "the next two weeks", TODAY)
    assert text.splitlines() == [
        "Your calendar for the next two weeks:",
        "Still on:",
        "  Winter break (started Sun 20 Dec 2020, until Sat 2 Jan 2027)",
        "Sat 24 Oct",
        "  18:00  Orchestrate (until Sun 25 Oct 18:00)",
        "Wed 28 Oct",
        "  09:30-10:00  Standup",
        "  all day  Registration",
        "  14:00  Quick call",
        "(From Google Calendar, which I can only read.)",
    ]
    assert "2020" in text and "2.020" not in text  # the year is never rewritten


def test_a_multi_day_all_day_event_says_its_real_last_day():
    text = ct.format_events([event("Trip", "2026-10-26", "2026-10-29", all_day=True)], TODAY, date(2026, 11, 3), "x", TODAY)
    assert "  all day  Trip (until Wed 28 Oct)" in text  # Google's end, the 29th, is the day after the last


def test_an_event_in_another_zone_is_shown_in_the_persons_own_time():
    utc = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    shown = ct.format_events([event("Call", utc.isoformat(), (utc + timedelta(hours=1)).isoformat())], TODAY, date(2026, 11, 3), "x", TODAY)
    local = utc.astimezone()
    assert f"{local:%H:%M}-{(local + timedelta(hours=1)):%H:%M}  Call" in shown


def test_a_title_with_control_or_invisible_characters_is_cleaned_and_a_huge_one_cut():
    nasty = "Dentist" + chr(0x1b) + "[31m" + chr(0x202e) + "txet" + chr(0x200b)
    text = ct.format_events([event(nasty, "2026-10-28", "2026-10-29", True), event("T" * 500, "2026-10-29", "2026-10-30", True)], TODAY, date(2026, 11, 3), "x", TODAY)
    assert chr(0x1b) not in text and chr(0x202e) not in text and chr(0x200b) not in text
    assert max(len(line) for line in text.splitlines()) < 140


def test_nothing_on_the_days_and_more_than_the_limit_are_said():
    assert ct.format_events([], TODAY, TODAY, "today", TODAY) == "Nothing on your calendar for today."
    many = [event(f"E{n}", "2026-10-28", "2026-10-29", True) for n in range(ct.LIMIT + 1)]
    text = ct.format_events(many, TODAY, date(2026, 11, 3), "x", TODAY)
    assert f"more than {ct.LIMIT}" in text and text.count("all day") == ct.LIMIT


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "c.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False,
    )


def test_the_google_request_is_for_exactly_the_local_days_asked(config, monkeypatch):
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    seen = {}
    monkeypatch.setattr(gc, "_access_token", lambda config: "fresh")

    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {"items": [{"summary": "Dentist", "start": {"dateTime": at(date(2026, 10, 22), 17)}, "end": {"dateTime": at(date(2026, 10, 22), 18)}}]}

    def fake_get(url, headers=None, params=None, timeout=None):
        seen.update(params)
        return Reply()

    monkeypatch.setattr(gc.httpx, "get", fake_get)
    now = datetime(2026, 10, 21, 12, 0, tzinfo=LOCAL_ZONE)
    text, fine = ct.answer(config, "any meetings tomorrow?", now)
    assert fine and "17:00-18:00  Dentist" in text and text.startswith("Your calendar for tomorrow:")
    assert datetime.fromisoformat(seen["timeMin"]) == datetime(2026, 10, 22, 0, 0, tzinfo=LOCAL_ZONE) and datetime.fromisoformat(seen["timeMax"]) == datetime(2026, 10, 23, 0, 0, tzinfo=LOCAL_ZONE)
    assert seen["singleEvents"] == "true" and seen["orderBy"] == "startTime" and seen["maxResults"] == ct.LIMIT + 1


def test_a_refusal_from_google_and_a_connection_that_is_not_there_are_said_in_words(config, monkeypatch):
    now = datetime(2026, 10, 21, 12, 0, tzinfo=LOCAL_ZONE)
    assert ct.answer(config, "what's on my calendar?", now) == ("Google Calendar is not connected, so I can't look. The Connections page connects it.", True)
    assert ct.answer(config, "what do I have on saturday", now) is None  # it did not say calendar, so reminders and tasks may be meant: left to the model
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    monkeypatch.setattr(gc, "_access_token", lambda config: "fresh")

    class Refused:
        status_code = 403

        @staticmethod
        def json():
            return {"error": "accessNotConfigured", "error_description": "API disabled"}

    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: Refused())
    text, fine = ct.answer(config, "what's on my calendar?", now)
    assert not fine and "HTTP 403 (accessNotConfigured: API disabled)" in text
    assert ct.answer(config, "what's the weather", now) is None


def test_through_the_chat_the_model_is_not_asked_and_the_exchange_is_a_journalled_flow(config, monkeypatch):
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    monkeypatch.setattr(gc, "_access_token", lambda config: "fresh")
    soon = (datetime.now().astimezone() + timedelta(days=1)).date()

    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {"items": [{"summary": "Dentist", "start": {"dateTime": at(soon, 17)}, "end": {"dateTime": at(soon, 18)}}]}

    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: Reply())
    model = ByQuestionClient(chat=["I cannot see your calendar."])
    agent = diya.Agent(config, client=model)
    web = TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL)
    said = str(web.post("/api/chat", json={"message": "what's on my calendar tomorrow?"}).json())
    assert "17:00-18:00  Dentist" in said and "cannot see" not in said
    assert len(model.asked("chat")) == 0
    row = agent.store.connect().execute("SELECT tool, kind, status FROM tool_journal ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("read_calendar", "flow", "ok")
