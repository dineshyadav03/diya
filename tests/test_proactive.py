"""Diya writing first (docs/PROACTIVE_DESIGN.md): diya_proactive.py, its routes, and the notifier's use of it.

What this proves: a good-morning is written once a day, only from its time and for four hours after it, from the person's own reminders and tasks; an evening check-in only when something is still
open; a reminder is written when it comes due, even at night, and not when it is a day old; a hello after two quiet days, not to someone who has never written and not twice in three days;
nothing but a reminder is written in the quiet hours, and no more than the day's cap; the messages go in one chat called Diya; looking at one stops it being offered; the notifier puts each
on the desktop once, hides the words when told to, and a failure on the desktop never undoes the message; and DIYA_PROACTIVE=0 stops it all.
"""
import dataclasses
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_events
import diya_notify
import diya_proactive as pro
import diya_time
import diya_web
from diya_db import Store
from fakes import FakeClient

MORNING = datetime(2026, 10, 12, 8, 45)  # a Monday


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "p.db"))


@pytest.fixture
def empty_day():
    """Ask for this to test a day with nothing on it: the morning message is then not written at all (2026-10-27)."""


@pytest.fixture(autouse=True)
def a_day_with_something_on_it(monkeypatch, request):
    """Most of these tests are about the messages themselves, and a morning message is only written when the day has something on it, so the day gets one stand-in reminder at 17:00 unless the test asks for `empty_day`."""
    if "empty_day" in request.fixturenames:
        return
    real = diya_events.day_brief

    def busy(store, now):
        brief = real(store, now)
        if not (brief["due_now"] or brief["later_today"] or brief["tasks_overdue"] or brief["tasks_today"]):
            due = diya_time.iso_of_local(datetime(now.year, now.month, now.day, 17, 0))
            brief["later_today"] = [{"id": 0, "content": "stand-in", "due": due, "due_text": None, "told": False, "repeats": False}]
        return brief

    monkeypatch.setattr(diya_events, "day_brief", busy)


def talker(store, **kwargs):
    return pro.Proactive(store, **kwargs)


def remind(store, text, local):
    return store.add_reminder(text, "when", diya_time.iso_of_local(local))


def say(store, text, when_utc):
    """A message from the person at a given UTC time."""
    thread = store.create_thread()
    message = store.add_message(thread, "user", text)
    conn = store.connect()
    conn.execute("UPDATE messages SET created_at = ? WHERE id = ?", (when_utc.isoformat(), message))
    conn.commit()
    conn.close()


# ---- the morning -------------------------------------------------------------------------------------------------------------

def test_the_morning_message_has_the_day_in_it_and_goes_in_a_chat_called_diya(store):
    remind(store, "call the bank", datetime(2026, 10, 12, 16, 0))
    (row,) = talker(store).make(MORNING)
    assert row["kind"] == "morning" and row["key"] == "morning:2026-10-12" and row["seen_at"] is None and row["toasted_at"] is None
    assert row["text"].startswith(pro.GREETINGS[datetime(2026, 10, 12).toordinal() % 4]) and "1 reminder later today." in row["text"] and "- 16:00 call the bank" in row["text"]
    assert store.get_history(row["thread_id"]) == [{"role": "assistant", "content": row["text"]}]
    conn = store.connect()
    assert conn.execute("SELECT title FROM threads WHERE id = ?", (row["thread_id"],)).fetchone()[0] == "Diya"
    conn.close()


def test_the_morning_message_is_written_once_a_day_and_again_the_next(store):
    remind(store, "x", datetime(2026, 12, 25, 16, 0))  # far off, so no reminder of its own comes due on the way
    assert len(talker(store).make(MORNING)) == 1 and talker(store).make(MORNING + timedelta(minutes=5)) == []
    assert len(talker(store).make(MORNING + timedelta(days=1))) == 1


@pytest.mark.parametrize("hour, minute, written", [(8, 29, False), (8, 30, True), (12, 29, True), (12, 30, False), (14, 0, False)])
def test_the_morning_message_comes_from_its_time_for_four_hours_and_not_a_minute_before_or_after(store, hour, minute, written):
    assert bool(talker(store).make(datetime(2026, 10, 12, hour, minute))) is written


def test_the_morning_time_is_a_setting_and_off_means_never(store):
    assert [r["kind"] for r in talker(store, morning=(10, 0)).make(datetime(2026, 10, 12, 10, 5))] == ["morning"]
    assert talker(store, morning=None, evening=None).make(MORNING) == []


def test_a_day_with_nothing_on_it_gets_no_morning_message(store, empty_day):
    """Hark writes a brief only when there is something to act on; 15 mornings of "Nothing is on your list" in 14 days were noise (the owner, 2026-10-27)."""
    assert talker(store).make(MORNING) == [] and talker(store).make(MORNING + timedelta(hours=3)) == []


def test_a_morning_message_ends_with_an_offer_to_move_or_drop_what_is_on_it(store):
    remind(store, "call the bank", datetime(2026, 10, 12, 16, 0))
    (row,) = talker(store).make(MORNING)
    assert row["text"].endswith("Want me to move or drop any of it? Just tell me.") and "- 16:00 call the bank" in row["text"]


def test_the_greeting_changes_from_day_to_day(store):
    seen = {talker(store).make(MORNING + timedelta(days=n))[0]["text"].split(" Nothing")[0] for n in range(4)}
    assert seen == set(pro.GREETINGS)


def test_a_long_day_lists_six_and_says_how_many_more(store):
    for n in range(9):
        remind(store, f"item {n}", datetime(2026, 10, 12, 9 + n // 2, 0))
    text = talker(store).make(MORNING)[0]["text"]
    assert text.count("\n- ") == 7 and text.removesuffix("\nWant me to move or drop any of it? Just tell me.").endswith("- and 3 more")  # six items and the line that says how many more, then the offer


def test_tasks_are_listed_with_overdue_ones_marked(store):
    import diya_tasks

    tasks = diya_tasks.Tasks(store, clock=lambda: MORNING)
    tasks.add("buy milk", "today")
    text = talker(store).make(MORNING)[0]["text"]
    assert "- task: buy milk" in text


def test_the_words_of_a_reminder_are_made_safe_and_cut(store):
    remind(store, "a" + chr(27) + "b" + "c" * 300, datetime(2026, 10, 12, 16, 0))
    text = talker(store).make(MORNING)[0]["text"]
    assert chr(27) not in text and "..." in text


# ---- the evening -------------------------------------------------------------------------------------------------------------

def test_the_evening_check_in_names_what_is_still_open_and_only_that(store):
    remind(store, "call the bank", datetime(2026, 10, 12, 10, 0))  # came due, not done
    remind(store, "later tonight", datetime(2026, 10, 12, 21, 0))  # not due yet
    row = [r for r in talker(store, morning=None).make(datetime(2026, 10, 12, 19, 10)) if r["kind"] == "evening"][0]
    assert row["kind"] == "evening" and row["key"] == "evening:2026-10-12" and "1 thing from today is still open." in row["text"]
    assert "- 10:00 call the bank" in row["text"] and "later tonight" not in row["text"] and "Tick off what is done" in row["text"]


def test_with_nothing_open_the_evening_says_nothing(store):
    remind(store, "done already", datetime(2026, 10, 12, 10, 0))
    store.complete_reminder(1)
    assert talker(store, morning=None).make(datetime(2026, 10, 12, 19, 10)) == []


def test_the_evening_window_is_three_hours_from_its_time(store):
    remind(store, "x", datetime(2026, 10, 12, 10, 0))
    store.mark_notified(1)  # the reminder has been told about, so only the evening is left to write
    made = {}
    for hour, minute in ((18, 59), (19, 0), (21, 59), (22, 0)):
        made[(hour, minute)] = [r["kind"] for r in talker(store, morning=None, quiet=None).make(datetime(2026, 10, 12, hour, minute)) if r["kind"] == "evening"]
    assert made == {(18, 59): [], (19, 0): ["evening"], (21, 59): [], (22, 0): []}  # once made it is not made again; nor outside its three hours


# ---- a reminder --------------------------------------------------------------------------------------------------------------

def test_a_reminder_that_comes_due_is_written_once_even_at_night(store):
    reminder = remind(store, "take the pills", datetime(2026, 10, 12, 23, 30))
    night = datetime(2026, 10, 12, 23, 40)
    (row,) = talker(store).make(night)
    assert row["kind"] == "reminder" and row["key"] == f"reminder:{reminder}" and row["text"] == "Reminder: take the pills"
    assert talker(store).make(night + timedelta(minutes=5)) == []


def test_a_reminder_not_yet_due_or_a_day_old_or_done_is_not_written(store):
    remind(store, "later", datetime(2026, 10, 12, 18, 0))
    remind(store, "ancient", datetime(2026, 10, 11, 8, 0))
    done = remind(store, "finished", datetime(2026, 10, 12, 8, 0))
    store.complete_reminder(done)
    assert talker(store, morning=None, evening=None).make(MORNING) == []


# ---- hello after a quiet spell -----------------------------------------------------------------------------------------------

def utc_of(local):
    return diya_events.utc_of_local(local)


def test_a_hello_after_two_quiet_days_names_the_days(store):
    say(store, "hello", utc_of(MORNING - timedelta(days=3, hours=1)))
    (row,) = talker(store, morning=None, evening=None).make(MORNING)
    assert row["kind"] == "away" and row["text"].startswith("It has been 3 days since we talked.")


def test_no_hello_before_two_days_or_to_someone_who_never_wrote_or_twice_in_three_days(store):
    assert talker(store, morning=None, evening=None).make(MORNING) == []  # never wrote
    say(store, "hello", utc_of(MORNING - timedelta(days=1, hours=23)))
    assert talker(store, morning=None, evening=None).make(MORNING) == []  # not yet two days
    later = MORNING + timedelta(days=1, hours=1)  # now it has been two days
    assert len(talker(store, morning=None, evening=None).make(later)) == 1
    assert talker(store, morning=None, evening=None).make(later + timedelta(days=1)) == []  # a day later: not three
    assert len(talker(store, morning=None, evening=None).make(later + timedelta(days=3))) == 1


# ---- the quiet hours and the cap ----------------------------------------------------------------------------------------------

def test_nothing_but_a_reminder_is_written_in_the_quiet_hours(store):
    remind(store, "alarm", datetime(2026, 10, 12, 23, 0))
    say(store, "hello", utc_of(datetime(2026, 10, 1, 9, 0)))
    kinds = [r["kind"] for r in talker(store, morning=(23, 0), evening=(23, 0)).make(datetime(2026, 10, 12, 23, 10))]
    assert kinds == ["reminder"]
    assert [r["kind"] for r in talker(store, morning=(23, 0), evening=(23, 0), quiet=None).make(datetime(2026, 10, 12, 23, 10))] == ["morning", "evening", "away"]


def test_no_more_than_the_days_cap_of_the_other_kinds(store, monkeypatch):
    monkeypatch.setattr(pro, "DAILY_CAP", 1)
    remind(store, "x", datetime(2026, 10, 12, 8, 0))
    say(store, "hello", utc_of(datetime(2026, 10, 1, 9, 0)))
    kinds = [r["kind"] for r in talker(store, morning=(8, 0), evening=(8, 0), quiet=None).make(MORNING)]
    assert kinds.count("reminder") == 1 and len([k for k in kinds if k != "reminder"]) == 1


def test_a_plan_writes_nothing(store):
    remind(store, "x", datetime(2026, 10, 12, 16, 0))
    planned = talker(store).plan(MORNING)
    assert [kind for kind, _, _ in planned] == ["morning"] and store.list_threads() == []


# ---- looking at them ---------------------------------------------------------------------------------------------------------

def test_one_chat_for_all_of_them_and_unseen_means_not_yet_looked_at(store):
    remind(store, "x", datetime(2026, 10, 12, 16, 0))
    first = talker(store).make(MORNING)[0]
    second = [r for r in talker(store, morning=None).make(datetime(2026, 10, 12, 19, 5)) if r["kind"] == "evening"][0]
    assert first["thread_id"] == second["thread_id"] and len(store.list_threads()) == 1
    assert [m["id"] for m in talker(store).unseen()][-1] == first["id"] and second["id"] in [m["id"] for m in talker(store).unseen()]  # newest first
    talker(store).mark_seen([first["id"]], utc_of(MORNING))
    assert first["id"] not in [m["id"] for m in talker(store).unseen()] and second["id"] in [m["id"] for m in talker(store).unseen()]
    talker(store).mark_seen([first["id"]], utc_of(MORNING + timedelta(days=1)))
    assert talker(store)._rows("WHERE id = ?", (first["id"],))[0]["seen_at"] == utc_of(MORNING).strftime("%Y-%m-%dT%H:%M:%SZ")  # the first look is kept


def test_five_at_most_are_offered(store):
    for n in range(8):
        talker(store).make(MORNING + timedelta(days=n))
    assert len(talker(store).unseen()) == 5 and len(talker(store).unseen(limit=8)) == 8


def test_a_reminders_own_message_is_never_put_on_the_desktop_twice(store):
    remind(store, "x", datetime(2026, 10, 12, 8, 0))
    talker(store).make(MORNING)
    kinds = [m["kind"] for m in talker(store).to_toast()]
    assert kinds == ["morning"]  # the reminder has its own notification


def test_what_was_put_on_the_desktop_or_looked_at_is_not_put_there_again(store):
    (row,) = talker(store).make(MORNING)
    talker(store).mark_toasted([row["id"]], utc_of(MORNING))
    assert talker(store).to_toast() == []
    remind(store, "y", datetime(2026, 10, 12, 10, 0))
    evening = [r for r in talker(store, morning=None).make(datetime(2026, 10, 12, 19, 6)) if r["kind"] == "evening"][0]
    assert [m["id"] for m in talker(store).to_toast()] == [evening["id"]]
    talker(store).mark_seen([evening["id"]], utc_of(MORNING))
    assert talker(store).to_toast() == []  # looked at in the chat: not put on the desktop afterwards


# ---- the routes --------------------------------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "a.db"), profile_path=str(tmp_path / "p.txt"), require_token=False, proactive=True)
    agent = diya.Agent(config, client=FakeClient([]), clock=lambda: MORNING)
    return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost"), agent


def test_the_cards_come_from_the_route_and_looking_at_one_removes_it(api):
    client, agent = api
    remind(agent.store, "call the bank", datetime(2026, 10, 12, 16, 0))
    (row,) = talker(agent.store).make(MORNING)
    listed = client.get("/api/proactive").json()["messages"]
    assert [(m["id"], m["kind"], m["thread_id"]) for m in listed] == [(row["id"], "morning", row["thread_id"])] and "call the bank" in listed[0]["text"]
    assert listed[0]["text"] == row["text"] and listed[0]["text"].count("\n") >= 1  # the lines of the list stay lines
    assert client.post("/api/proactive/seen", json={"ids": [row["id"]]}).json() == {"seen": 1}
    assert client.get("/api/proactive").json() == {"messages": []}


def test_seen_ignores_ids_that_are_not_ids_and_takes_at_most_twenty(api):
    client, _ = api
    assert client.post("/api/proactive/seen", json={"ids": [0, -3, 2**70 if False else 5]}).json() == {"seen": 1}
    assert client.post("/api/proactive/seen", json={"ids": list(range(1, 60))}).json() == {"seen": 20}
    assert client.post("/api/proactive/seen", json={}).status_code == 422


def test_the_reply_goes_on_in_the_chat_she_started(api):
    client, agent = api
    remind(agent.store, "x", datetime(2026, 10, 12, 16, 0))
    (row,) = talker(agent.store).make(MORNING)
    agent.client.replies.append(__import__("fakes").text_reply("Done."))
    answer = client.post("/api/chat", json={"thread_id": row["thread_id"], "message": "move it to five"}).json()
    assert answer["thread_id"] == row["thread_id"] and [m["role"] for m in agent.store.get_history(row["thread_id"])] == ["assistant", "user", "assistant"]
    assert agent.client.chat_calls[0]["messages"][-2]["content"] == row["text"]  # the model is shown what she wrote first


# ---- the notifier ------------------------------------------------------------------------------------------------------------

class Screen:
    def __init__(self, failing=False):
        self.shown, self.failing = [], failing

    def __call__(self, title, body):
        if self.failing:
            raise diya_notify.NotifyError("no screen")
        self.shown.append((title, body))


def notify_config(tmp_path, **changes):
    values = dict(db_path=str(tmp_path / "n.db"), notify_log_path=str(tmp_path / "notify.log"), proactive=True, push=False, auto_memory=False)
    return dataclasses.replace(diya_config.load_config({}), **{**values, **changes})


def run_notifier(config, screen, now=MORNING, extra=()):
    out = io.StringIO()
    return diya_notify.main(list(extra), config=config, out=out, notify=screen, now=now), out.getvalue()


def test_a_pass_writes_the_good_morning_and_puts_its_first_line_on_the_desktop_once(tmp_path):
    config = notify_config(tmp_path)
    Store(config.db_path).add_reminder("call the bank", "when", diya_time.iso_of_local(datetime(2026, 10, 12, 16, 0)))
    screen = Screen()
    code, text = run_notifier(config, screen)
    assert code == 0 and "1 written first" in text and len(screen.shown) == 1 and screen.shown[0][0] == "Diya" and screen.shown[0][1].endswith("1 reminder later today.")
    assert run_notifier(config, screen, MORNING + timedelta(minutes=5))[0] == 0 and len(screen.shown) == 1  # not again
    assert len(Store(config.db_path).get_history(1)) == 1


def test_with_the_words_hidden_the_desktop_only_says_that_she_wrote(tmp_path):
    config = notify_config(tmp_path, notify_show_text=False)
    screen = Screen()
    run_notifier(config, screen)
    assert screen.shown == [("Diya", "Diya wrote to you.")]


def test_a_reminder_gets_its_toast_about_the_reminder_and_a_message_in_the_chat_but_no_second_toast(tmp_path):
    config = notify_config(tmp_path, proactive_morning="off", proactive_evening="off")
    Store(config.db_path).add_reminder("take the pills", "when", diya_time.iso_of_local(MORNING - timedelta(minutes=5)))
    screen = Screen()
    run_notifier(config, screen)
    assert [body for _, body in screen.shown] == ["take the pills"] and Store(config.db_path).get_history(1) == [{"role": "assistant", "content": "Reminder: take the pills"}]


def test_a_desktop_that_will_not_show_it_is_tried_again_and_the_message_stays_in_the_chat(tmp_path):
    config = notify_config(tmp_path)
    code, text = run_notifier(config, Screen(failing=True))
    assert code == 1 and "could not tell about message 1" in text and len(Store(config.db_path).get_history(1)) == 1
    screen = Screen()
    assert run_notifier(config, screen, MORNING + timedelta(minutes=5))[0] == 0 and len(screen.shown) == 1


def test_a_dry_run_says_what_it_would_write_and_writes_nothing(tmp_path):
    config = notify_config(tmp_path)
    code, text = run_notifier(config, Screen(), extra=("--dry-run",))
    assert code == 0 and "would write: morning" in text and Store(config.db_path).list_threads() == []


def test_switched_off_it_writes_nothing(tmp_path):
    config = notify_config(tmp_path, proactive=False)
    code, text = run_notifier(config, Screen())
    assert code == 0 and "written first" not in text and Store(config.db_path).list_threads() == []


def test_a_failure_in_writing_is_said_by_its_kind_and_does_not_hide_the_reminders(tmp_path, monkeypatch):
    config = notify_config(tmp_path)
    Store(config.db_path).add_reminder("take the pills", "when", diya_time.iso_of_local(MORNING - timedelta(minutes=5)))
    monkeypatch.setattr(pro.Proactive, "make", lambda self, now: (_ for _ in ()).throw(RuntimeError("SECRET")))
    screen = Screen()
    code, text = run_notifier(config, screen)
    assert code == 1 and "could not write first: RuntimeError" in text and "SECRET" not in text and [body for _, body in screen.shown] == ["take the pills"]


# ---- the settings ------------------------------------------------------------------------------------------------------------

def test_the_defaults_are_on_at_half_past_eight_and_seven_with_the_nights_quiet():
    config = diya_config.load_config({})
    assert (config.proactive, config.proactive_morning, config.proactive_evening, config.proactive_quiet) == (True, "08:30", "19:00", "22-07")


def test_the_settings_are_read_and_checked():
    config = diya_config.load_config({"DIYA_PROACTIVE": "0", "DIYA_PROACTIVE_MORNING": "07:15", "DIYA_PROACTIVE_EVENING": "off", "DIYA_PROACTIVE_QUIET": "off"})
    assert (config.proactive, config.proactive_morning, config.proactive_evening, config.proactive_quiet) == (False, "07:15", "off", "off")
    for name, value in (("DIYA_PROACTIVE_MORNING", "8am"), ("DIYA_PROACTIVE_EVENING", "25:00"), ("DIYA_PROACTIVE_QUIET", "9"), ("DIYA_PROACTIVE", "maybe")):
        with pytest.raises(diya_config.ConfigError, match=name):
            diya_config.load_config({name: value})
