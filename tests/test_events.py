"""The one list of what is worth interrupting for (docs/PUSH_DESIGN.md, sections 2 and 3, unit P3): diya_events.py.

What this proves: every kind of message has exactly the words the design gives it, with the text hidden or shown; a flood of due reminders is told as four and one that stands
for the rest; what a channel was told is recorded once per key, per channel, and counted in messages and not in events; what is pending is decided in one place: reminders that are due,
not done, not too old and not yet told; questions only when memory raises them; actions that are waiting and not out of time; "your day" once per date, from its time for a
few hours, and only when something is due; the quiet hours hold back everything but a reminder; and the toast (diya_notify.py) and this list say the same words.
"""
from datetime import datetime, timedelta, timezone

import pytest

import diya_events as ev
import diya_notify
import diya_time
from diya_db import Store
from diya_memory import Memory

NOW = datetime(2026, 10, 12, 10, 0)  # a Monday, 10:00 local
CREATED = "2026-10-11T03:30:00+00:00"


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "e.db"))


def ts(local):
    return diya_time.iso_of_local(local)


def remind(store, text, local, done=False):
    reminder_id = store.add_reminder(text, "when", ts(local))
    if done:
        store.complete_reminder(reminder_id)
    return reminder_id


def action(store, status, expires):
    conn = store.connect()
    number = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
    conn.execute("INSERT INTO actions (kind, args, args_hash, summary, status, created_at, expires_at) VALUES ('k', '{}', ?, 's', ?, '2026-10-12T00:00:00Z', ?)", (f"h{number}", status, ts(expires)))
    conn.commit()
    conn.close()


def question(store):
    memory = Memory(store)
    fact_id = memory.add_candidate("private thing", batch_first=1, batch_last=1, position=0, model="m", extracted_at=CREATED, raw="- private thing")
    memory.set_flags(fact_id, ["ask:sensitive:model_private"], "system")
    import diya_questions

    queue = diya_questions.Questions(store, None)
    queue.refill(memory, NOW)
    return queue


# --- the words ---------------------------------------------------------------------------------------------------------------

def test_a_reminder_hidden_says_only_that_one_is_due():
    assert ev.reminder_words({"due_ts": "2026-10-12T03:30:00Z", "content": "call the bank"}, False) == ("Diya", "A reminder is due")


def test_a_reminder_shown_has_its_time_and_its_own_words(store):
    title, body = ev.reminder_words({"due_ts": ts(datetime(2026, 10, 12, 9, 0)), "content": "call the bank"}, True)
    assert (title, body) == ("Diya: Monday 12 Oct 2026, 09:00", "call the bank")


def test_a_reminder_with_no_time_is_titled_plainly():
    assert ev.reminder_words({"due_ts": None, "content": "x"}, True) == ("Diya reminder", "x")


def test_a_reminders_words_are_made_safe_and_cut():
    assert ev.reminder_words({"due_ts": None, "content": "a" + chr(27) + "b"}, True)[1] == "a\\u001bb"  # the control character is shown as an escape, not itself
    title, body = ev.reminder_words({"due_ts": None, "content": "c" * 300}, True)
    assert len(body) <= ev.BODY_CHARS + 3 and body.endswith("...")


def test_the_other_kinds_say_a_count_and_never_what_it_is_about():
    assert ev.question_words(1) == ("Diya", "Diya has a question for you.")
    assert ev.question_words(3) == ("Diya", "Diya has 3 questions for you.")
    assert ev.action_words(1) == ("Diya", "An action is waiting for your approval.")
    assert ev.action_words(2) == ("Diya", "2 actions are waiting for your approval.")
    assert ev.more_words(4) == ("Diya", "4 more reminders are due. Open the Reminders page to see them.")


def test_the_day_says_its_headline_only_when_text_is_shown():
    assert ev.day_words("2 reminders later today.", False) == ("Diya", "Your day is ready.")
    assert ev.day_words("2 reminders later today.", True) == ("Diya", "Your day is ready. 2 reminders later today.")
    assert ev.day_words(None, True) == ("Diya", "Your day is ready.")


@pytest.mark.parametrize("count, singles, rest", [(0, 0, 0), (1, 1, 0), (4, 4, 0), (5, 5, 0), (6, 4, 2), (10, 4, 6)])
def test_a_flood_is_four_one_by_one_and_one_for_the_rest(count, singles, rest):
    one_by_one, the_rest = ev.split_flood(list(range(count)))
    assert (len(one_by_one), len(the_rest)) == (singles, rest) and one_by_one + the_rest == list(range(count))


def test_the_toast_and_this_list_use_the_same_words_and_the_same_flood_rule():
    assert diya_notify.MAX_NOTIFICATIONS == ev.MAX_NOTIFICATIONS and (diya_notify.TITLE_CHARS, diya_notify.BODY_CHARS) == (ev.TITLE_CHARS, ev.BODY_CHARS)
    assert diya_notify._words is ev.reminder_words


def test_six_due_reminders_are_four_messages_and_a_fifth_that_stands_for_two():
    due = [{"id": n, "content": f"r{n}", "due_ts": None} for n in range(1, 7)]
    events = ev.reminder_events(due, True)
    assert [e.keys for e in events] == [("reminder:1",), ("reminder:2",), ("reminder:3",), ("reminder:4",), ("reminder:5", "reminder:6")]
    assert events[-1].body == ev.more_words(2)[1] and all(e.kind == "reminder" for e in events)


# --- who has been told what --------------------------------------------------------------------------------------------------

def test_a_key_is_recorded_once_per_channel_and_the_first_time_is_kept(store):
    push, other = ev.Deliveries(store, "push"), ev.Deliveries(store, "other")
    first = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    push.record(("reminder:1", "reminder:2"), first)
    push.record(("reminder:1",), first + timedelta(hours=1))
    assert push.told() == {"reminder:1", "reminder:2"} and other.told() == set()
    conn = store.connect()
    assert conn.execute("SELECT sent_at FROM event_deliveries WHERE key = 'reminder:1'").fetchone()[0] == "2026-10-12T04:00:00Z"
    conn.close()


def test_recording_nothing_records_nothing(store):
    ev.Deliveries(store, "push").record((), datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert ev.Deliveries(store, "push").told() == set()


def test_messages_are_counted_not_events_and_the_hour_is_closed_at_its_start(store):
    push = ev.Deliveries(store, "push")
    start = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    push.record(("reminder:1",), start)
    push.record(("reminder:2", "reminder:3", "reminder:4"), start + timedelta(minutes=10))  # one message that stands for three
    assert push.messages_since(start) == 2
    assert push.messages_since(start + timedelta(minutes=10)) == 1
    assert push.messages_since(start + timedelta(minutes=10, seconds=1)) == 0
    assert ev.Deliveries(store, "other").messages_since(start) == 0


def test_a_time_with_another_offset_is_stored_in_utc(store):
    ev.Deliveries(store, "push").record(("reminder:1",), datetime(2026, 10, 12, 9, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))))
    assert ev.Deliveries(store, "push").messages_since(datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)) == 1
    assert ev.Deliveries(store, "push").messages_since(datetime(2026, 10, 12, 4, 0, 1, tzinfo=timezone.utc)) == 0


# --- what is pending ---------------------------------------------------------------------------------------------------------

def test_a_due_reminder_is_pending_until_it_is_told_and_a_done_or_future_one_never_is(store):
    due = remind(store, "call the bank", NOW - timedelta(minutes=5))
    remind(store, "later", NOW + timedelta(hours=1))
    remind(store, "finished", NOW - timedelta(minutes=5), done=True)
    events = ev.pending(store, NOW, set())
    assert [e.keys for e in events] == [(f"reminder:{due}",)] and events[0].body == "A reminder is due"
    assert ev.pending(store, NOW, {f"reminder:{due}"}) == []


def test_the_words_can_be_shown(store):
    remind(store, "call the bank", NOW - timedelta(minutes=5))
    assert ev.pending(store, NOW, set(), show_text=True)[0].body == "call the bank"


def test_a_reminder_that_came_due_more_than_a_day_ago_is_not_pushed(store):
    old = remind(store, "old", NOW - timedelta(hours=24, minutes=1))
    edge = remind(store, "edge", NOW - timedelta(hours=24))
    assert [e.keys for e in ev.pending(store, NOW, set())] == [(f"reminder:{edge}",)] and old != edge


def test_the_toast_is_not_limited_by_age_because_it_never_asks_this_list(store):
    remind(store, "old", NOW - timedelta(days=3))
    assert ev.pending(store, NOW, set()) == []
    assert len(store.due_reminders(ts(NOW), unnotified_only=True)) == 1


def test_a_waiting_question_is_pending_only_when_memory_raises_questions(store):
    question(store)
    assert ev.pending(store, NOW, set()) == []
    events = ev.pending(store, NOW, set(), questions_on=True)
    assert [(e.kind, e.body) for e in events] == [("question", "Diya has a question for you.")] and events[0].keys == ("question:1",)
    assert ev.pending(store, NOW, {"question:1"}, questions_on=True) == []


def test_waiting_actions_are_counted_and_an_expired_or_decided_one_is_not(store):
    action(store, "pending", NOW + timedelta(hours=1))
    action(store, "pending", NOW + timedelta(minutes=1))
    action(store, "pending", NOW)  # its time is up this minute
    action(store, "pending", NOW - timedelta(hours=1))
    action(store, "approved", NOW + timedelta(hours=1))
    action(store, "rejected", NOW + timedelta(hours=1))
    events = ev.pending(store, NOW, set())
    assert [(e.kind, e.keys, e.body) for e in events] == [("action", ("action:1", "action:2"), "2 actions are waiting for your approval.")]
    assert ev.pending(store, NOW, {"action:1"})[0].keys == ("action:2",)


def test_one_waiting_action_says_so_in_the_singular(store):
    action(store, "pending", NOW + timedelta(hours=1))
    assert ev.pending(store, NOW, set())[0].body == "An action is waiting for your approval."


def test_the_quiet_hours_hold_back_everything_but_a_reminder(store):
    remind(store, "alarm", NOW - timedelta(minutes=5))
    action(store, "pending", NOW + timedelta(days=1))
    question(store)
    night = datetime(2026, 10, 12, 23, 0)
    action(store, "pending", night + timedelta(days=1))
    conn = store.connect()
    conn.execute("UPDATE reminders SET due_ts = ?", (ts(night - timedelta(minutes=5)),))
    conn.commit()
    conn.close()
    held = ev.pending(store, night, set(), questions_on=True, quiet=(22, 7), day_at=(8, 0))
    assert [e.kind for e in held] == ["reminder"]
    open_hours = ev.pending(store, night, set(), questions_on=True, quiet=None)
    assert [e.kind for e in open_hours] == ["reminder", "question", "action"]


def test_the_order_is_reminders_then_questions_then_actions_then_the_day(store):
    remind(store, "alarm", datetime(2026, 10, 12, 8, 0))
    question(store)
    action(store, "pending", NOW + timedelta(hours=5))
    events = ev.pending(store, datetime(2026, 10, 12, 9, 30), set(), questions_on=True, day_at=(9, 0))
    assert [e.kind for e in events] == ["reminder", "question", "action", "day"]


# --- the day ------------------------------------------------------------------------------------------------------------------

def test_the_day_is_sent_from_its_time_for_three_hours_and_not_a_minute_before_or_after(store):
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    times = {(7, 59): False, (8, 0): True, (9, 30): True, (10, 59): True, (11, 0): False, (14, 0): False}
    for (hour, minute), expected in times.items():
        events = ev.pending(store, datetime(2026, 10, 12, hour, minute), set(), day_at=(8, 0))
        assert any(e.kind == "day" for e in events) is expected, (hour, minute)


def test_the_day_is_sent_once_for_each_date(store):
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    assert [e.keys for e in ev.pending(store, datetime(2026, 10, 12, 8, 30), set(), day_at=(8, 0))] == [("day:2026-10-12",)]
    assert ev.pending(store, datetime(2026, 10, 12, 8, 30), {"day:2026-10-12"}, day_at=(8, 0)) == []
    remind(store, "tomorrow", datetime(2026, 10, 13, 16, 0))
    assert [e.keys for e in ev.pending(store, datetime(2026, 10, 13, 8, 30), {"day:2026-10-12"}, day_at=(8, 0)) if e.kind == "day"] == [("day:2026-10-13",)]


def test_the_day_says_nothing_when_nothing_is_due(store):
    assert ev.pending(store, datetime(2026, 10, 12, 8, 30), set(), day_at=(8, 0)) == []


def test_the_day_has_the_headline_when_text_is_shown_and_not_when_hidden(store):
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    hidden = ev.pending(store, datetime(2026, 10, 12, 8, 30), set(), day_at=(8, 0))[0]
    shown = ev.pending(store, datetime(2026, 10, 12, 8, 30), set(), day_at=(8, 0), show_text=True)[0]
    assert hidden.body == "Your day is ready." and shown.body == "Your day is ready. 1 reminder later today."


def test_with_no_time_there_is_no_day_message(store):
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    assert ev.pending(store, datetime(2026, 10, 12, 8, 30), set(), day_at=None) == []


def test_the_day_headline_is_none_when_nothing_is_due(store):
    assert ev.day_headline(store, NOW) is None
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    assert ev.day_headline(store, NOW) == "1 reminder later today."


def test_a_local_time_is_made_aware_in_utc():
    stamp = ev.utc_of_local(datetime(2026, 10, 12, 10, 0))
    assert stamp.tzinfo == timezone.utc and diya_time.iso_of_local(datetime(2026, 10, 12, 10, 0)) == stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_importing_the_module_reads_nothing(run_python):
    done = run_python("import diya_events, os; print(sorted(n for n in os.listdir('.') if n != '__pycache__'))")
    assert done.returncode == 0 and done.stdout.strip() == "[]"


# --- the edges that mutation found -------------------------------------------------------------------------------------------------

def test_a_time_with_an_offset_is_compared_in_utc_on_both_sides(store):
    push = ev.Deliveries(store, "push")
    ist = timezone(timedelta(hours=5, minutes=30))
    push.record(("reminder:1",), datetime(2026, 10, 12, 9, 30, tzinfo=ist))  # 04:00 UTC
    assert push.messages_since(datetime(2026, 10, 12, 9, 30, tzinfo=ist)) == 1
    assert push.messages_since(datetime(2026, 10, 12, 9, 30, 1, tzinfo=ist)) == 0
    assert push.messages_since(datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)) == 1


def test_the_day_waits_for_its_minute_not_only_its_hour(store):
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    assert [e.kind for e in ev.pending(store, datetime(2026, 10, 12, 9, 15), set(), day_at=(9, 30))] == []
    assert [e.kind for e in ev.pending(store, datetime(2026, 10, 12, 9, 30), set(), day_at=(9, 30))] == ["day"]
    assert [e.kind for e in ev.pending(store, datetime(2026, 10, 12, 12, 29), set(), day_at=(9, 30))] == ["day"]
    assert [e.kind for e in ev.pending(store, datetime(2026, 10, 12, 12, 30), set(), day_at=(9, 30))] == []
