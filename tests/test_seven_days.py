"""A simulated week of scheduled work that is interrupted again and again (diya_notify.run_once, diya_schedule, diya_automations.run_due, diya_proactive; task DIYA-057), added 2026-10-21.

What this proves, with the real code on a real database and a clock that is moved by hand through seven days in ten-minute steps: while the computer is shut every night and once for a whole day, a notification
fails one time in ten, the program is stopped and started again one time in twenty (every object is made again from the database), and one time in thirty-three it is stopped just after a notification was
shown and before it was written down:
* every daily and weekly repeating reminder is made exactly once for its day, none twice and none missing (the day the computer was shut over its time, it is made when the computer wakes);
* every reminder, repeating or single, is shown to the person and written down as shown, and none is lost; a reminder is shown a second time only when the program was stopped in the one moment between showing and writing down (the test counts those, so they cannot grow): a notification is shown at least once, not exactly once;
* every automation runs once per day and its answer is in the chat once (a key made of the automation and the time makes a second post a no-op);
* the repeating-reminder and automation tables have no two rows for the same day, and the database passes its own checks at the end.
It is a simulation of 7 days, not 7 days: the real weekly trial (DIYA-220) is a task on the owner's computer. It does not simulate the real operating system's notifications.
"""
import random
from collections import Counter
from datetime import datetime, timedelta

import pytest

import diya_automations
import diya_notify
import diya_proactive
import diya_schedule
import diya_time
from diya_db import Store

START = datetime(2026, 10, 5, 0, 0)  # a Monday
STEP = timedelta(minutes=10)
DAYS = 7


class Crash(BaseException):
    """The program is stopped dead (not an Exception: nothing in the code under test may catch it)."""


class Briefer:
    def briefing(self, instruction):
        return "Pune is 28 degrees."


def asleep(moment):
    """The computer is shut every night from 23:00 to 07:30, and on the fourth day from 02:00 to 16:00 (a long meeting, a flat battery)."""
    if moment.date() == (START + timedelta(days=3)).date() and 2 <= moment.hour < 16:
        return True
    return moment.hour >= 23 or (moment.hour, moment.minute) < (7, 30)


@pytest.fixture
def trial(tmp_path):
    path = str(tmp_path / "week.db")
    now = {"at": START}
    store = Store(path)
    clock = lambda: now["at"]  # noqa: E731
    schedule = diya_schedule.Schedule(store, clock=clock)
    schedule.create("water the plants", "every day at 9am")
    schedule.create("clean the filter", "every sunday at 9am")
    automations = diya_automations.Automations(store, clock)
    automations.create("tell me the weather in Pune", "every day at 8am")
    for offset_hours in (11, 30, 56, 80, 101, 125, 149):  # seven single reminders through the week
        due = START + timedelta(hours=offset_hours, minutes=5)
        store.add_reminder(f"single reminder {offset_hours}", None, diya_time.iso_of_local(due))
    return path, now


def run_the_week(path, now, seed):
    rng = random.Random(seed)
    shown = Counter()  # reminder content -> how many times it was shown
    stats = {"restarts": 0, "failures": 0, "crashes_after_showing": 0}
    store = Store(path)
    end = START + timedelta(days=DAYS)
    while now["at"] < end:
        moment = now["at"]
        if asleep(moment):
            now["at"] += STEP
            continue
        if rng.random() < 0.05:  # the program was stopped and started: everything is made again from the database
            store = Store(path)
            stats["restarts"] += 1

        def notify(title, body):
            if rng.random() < 0.35:
                stats["failures"] += 1
                raise diya_notify.NotifyError("the notification could not be shown")
            shown[body] += 1

        real_mark = store.mark_notified

        def mark(reminder_id, at=None):
            if rng.random() < 0.20:  # stopped dead after the notification was shown and before it was recorded
                raise Crash()
            return real_mark(reminder_id, at)

        store.mark_notified = mark
        try:
            diya_notify.run_once(store, notify, now=moment, show_text=True, say=lambda line: None)
        except Crash:
            stats["crashes_after_showing"] += 1
        finally:
            store.mark_notified = real_mark
        diya_automations.run_due(store, Briefer, diya_proactive.Proactive(store), moment, say=lambda line: None, clock=lambda: moment)
        now["at"] += STEP
    return store, shown, stats


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_week_of_stops_and_failures_makes_and_shows_everything_once(trial, seed):
    path, now = trial
    store, shown, stats = run_the_week(path, now, seed)
    assert stats["restarts"] > 20 and stats["failures"] >= 3 and stats["crashes_after_showing"] >= 1  # the week really was interrupted

    conn = store.connect()
    try:
        made = conn.execute("SELECT series_id, due_ts, content FROM reminders WHERE series_id IS NOT NULL ORDER BY id").fetchall()
        messages = conn.execute("SELECT key FROM proactive_messages WHERE kind = 'automation' ORDER BY id").fetchall()
        singles = conn.execute("SELECT content, notified_at FROM reminders WHERE series_id IS NULL").fetchall()
        all_reminders = conn.execute("SELECT content, notified_at, done FROM reminders").fetchall()
    finally:
        conn.close()

    daily = [due for _series, due, content in made if content == "water the plants"]
    weekly = [due for _series, due, content in made if content == "clean the filter"]
    expected_days = [diya_time.iso_of_local(datetime.combine((START + timedelta(days=d)).date(), datetime.min.time()) + timedelta(hours=9)) for d in range(DAYS)]
    assert sorted(daily) == sorted(expected_days)  # one for each of the seven days, none twice, the shut day's made at waking
    assert weekly == [diya_time.iso_of_local(datetime(2026, 10, 11, 9, 0))]  # the one Sunday in the week

    keys = [key for (key,) in messages]
    assert len(keys) == DAYS and len(set(keys)) == DAYS  # one answer in the chat per day, no key twice

    assert all(notified_at is not None for _content, notified_at, _done in all_reminders)  # every reminder that was made was shown and written down: a failed one was tried again until it got through
    made_of = Counter(content for content, _notified, _done in all_reminders)
    extra = sum(max(0, shown[content] - made_of[content]) for content in made_of)
    assert extra <= stats["crashes_after_showing"]  # a reminder is shown a second time only when the program was stopped between showing it and writing that down
    assert store.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
