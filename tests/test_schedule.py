"""Repeating reminders, snooze, and the trail (docs/SCHEDULE_DESIGN.md, D1, D3, D4, D5 and unit R2): migration 7 and
diya_schedule.Schedule.

What this proves: a series is made only from words diya_repeat reads, and the same words and rule cannot be active twice nor
more than MAX_ACTIVE at once (the database refuses the duplicate itself); materialize makes an ordinary reminder, once, when
the time comes, takes no write lock when nothing is due, and cannot be fooled into making it twice by two callers; a series
that fell behind makes one reminder and records the rest as missed; a pending reminder of the same series is closed as lapsed
when a newer one arrives and nothing else is touched; pause, resume, skip and stop each do exactly one thing and refuse what
makes no sense; snooze moves one reminder and leaves its series alone; every change writes the trail with who did it; and a
write that fails part way leaves nothing behind.
"""
import sqlite3
import threading
from datetime import datetime, timedelta

import pytest

import diya
import diya_db
import diya_schedule
import diya_time
from diya_schedule import (DuplicateSeries, IllegalState, InvalidSeries, Schedule, TooManySeries, UnknownReminder,
                           UnknownSeries)
from diya_time import NotUnderstood

NOW = datetime(2026, 10, 10, 10, 15)  # a Saturday, 10:15 local


def ts(local):
    return diya_time.iso_of_local(local)


@pytest.fixture
def store(tmp_path):
    return diya_db.Store(str(tmp_path / "schedule.db"))


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def schedule(store, clock):
    return Schedule(store, clock=lambda: clock["now"])


# ---- migration 7 ------------------------------------------------------------------------------------

def test_migration_seven_adds_two_tables_a_column_and_the_indexes_and_changes_nothing_else(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, due_at TEXT,"
                 " created_at TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    conn.execute("INSERT INTO reminders (content, created_at) VALUES ('keep me', 't')")
    conn.commit()
    applied = diya_db.apply_migrations(conn)
    assert applied == [v for v, _ in diya_db.MIGRATIONS] and 7 in applied
    series = {row[1]: (row[2], bool(row[3])) for row in conn.execute("PRAGMA table_info(reminder_series)")}
    assert series == {
        "id": ("INTEGER", False), "content": ("TEXT", True), "content_key": ("TEXT", True), "rule": ("TEXT", True), "said": ("TEXT", False),
        "next_ts": ("TEXT", False), "paused": ("INTEGER", True), "ended": ("INTEGER", True), "source": ("TEXT", True),
        "thread_id": ("INTEGER", False), "message_id": ("INTEGER", False), "created_at": ("TEXT", True), "ended_at": ("TEXT", False),
    }
    assert "series_id" in {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
    events = {row[1] for row in conn.execute("PRAGMA table_info(schedule_events)")}
    assert events == {"id", "series_id", "reminder_id", "event", "actor", "at", "detail"}
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"series_one_active_per_key", "reminders_by_series", "schedule_events_by_series"} <= indexes
    assert conn.execute("SELECT content, series_id FROM reminders").fetchall() == [("keep me", None)]  # an old reminder belongs to no series
    assert diya_db.apply_migrations(conn) == []
    conn.close()


def test_the_database_itself_refuses_an_active_duplicate_a_bad_source_and_a_bad_flag(store):
    conn = store.connect()

    def insert(key="a", rule="daily@09:00", paused=0, ended=0, source="chat"):
        conn.execute("INSERT INTO reminder_series (content, content_key, rule, paused, ended, source, created_at) VALUES (?, ?, ?, ?, ?, ?, 't')",
                     (key, key, rule, paused, ended, source))

    insert()
    with pytest.raises(sqlite3.IntegrityError):
        insert()
    insert(rule="weekdays@09:00")  # the same words with another rule are another series
    insert(ended=1)
    insert(ended=1)  # a stopped one does not count
    for bad in ({"source": "model"}, {"paused": 2}, {"ended": 2}):
        with pytest.raises(sqlite3.IntegrityError):
            insert(key="z", **bad)
    conn.close()


# ---- making one -------------------------------------------------------------------------------------

def test_a_series_is_saved_with_its_rule_its_words_and_the_first_time_it_falls(schedule):
    series = schedule.create("  take  out the\tbins ", "every Monday at 9am", thread_id=4, message_id=9)
    assert series == {
        "id": 1, "content": "take out the bins", "rule": "weekly:0@09:00", "said": "every Monday at 9am", "next_ts": ts(datetime(2026, 10, 12, 9, 0)),
        "paused": False, "ended": False, "source": "chat", "thread_id": 4, "message_id": 9, "created_at": ts(NOW), "ended_at": None, "assumed": [],
    }
    assert {k: v for k, v in schedule.get(1).items()} == {k: v for k, v in series.items() if k != "assumed"}


def test_what_the_rule_filled_in_is_handed_back_once_and_not_stored(schedule):
    series = schedule.create("water the plants", "every Friday")
    assert series["assumed"] == ["no time was given, so 09:00"] and "assumed" not in schedule.get(1)


def test_creating_one_writes_the_trail_with_who_made_it(schedule):
    schedule.create("a", "every day at 8am")
    schedule.create("b", "every day at 8am", source="page")
    first, second = schedule.events()
    assert (first["event"], first["actor"], first["series_id"], first["reminder_id"]) == ("created", "model", 1, None)
    assert first["detail"] == {"rule": "daily@08:00", "said": "every day at 8am"} and first["at"] == ts(NOW)
    assert (second["event"], second["actor"], second["series_id"]) == ("created", "owner", 2)


@pytest.mark.parametrize("content, why", [("", "needs something"), ("   ", "needs something"), (None, "must be words"), (5, "must be words"),
                                          ("x" * 301, "at most 300"), ("pay" + chr(7) + "bill", "cannot contain the character")])
def test_words_that_are_not_a_reminder_are_refused_and_save_nothing(schedule, content, why):
    with pytest.raises(InvalidSeries, match=why):
        schedule.create(content, "every day")
    assert schedule.series("all") == [] and schedule.events() == []


def test_the_most_a_repeating_reminder_may_say_is_what_a_one_off_may_say(schedule):
    assert diya_schedule.MAX_CONTENT_CHARS == diya.MAX_REMINDER_CHARS == 300
    assert schedule.create("x" * 300, "every day")["content"] == "x" * 300


@pytest.mark.parametrize("words", ["every hour", "soon", "every Monday until June", "every week", "", None, 5])
def test_a_repeat_that_cannot_be_read_saves_nothing_and_says_why(schedule, words):
    with pytest.raises(NotUnderstood):
        schedule.create("x", words)
    assert schedule.series("all") == [] and schedule.events() == []


def test_the_same_words_with_the_same_rule_cannot_be_active_twice_whatever_the_capitals(schedule):
    first = schedule.create("Take out the bins", "every Monday at 9am")
    for again in ("take OUT the   bins", "TAKE OUT THE BINS"):
        with pytest.raises(DuplicateSeries) as raised:
            schedule.create(again, "every monday at 9:00")
        assert raised.value.series_id == first["id"]
    schedule.create("Take out the bins", "every Tuesday at 9am")  # another rule: another series
    assert len(schedule.series("all")) == 2


def test_a_stopped_series_frees_its_words(schedule):
    first = schedule.create("bins", "every Monday")
    schedule.stop(first["id"])
    assert schedule.create("bins", "every Monday")["id"] == 2


def test_no_more_than_twenty_are_active_and_a_stopped_one_does_not_count(schedule, monkeypatch):
    assert diya_schedule.MAX_ACTIVE == 20
    monkeypatch.setattr(diya_schedule, "MAX_ACTIVE", 2)
    schedule.create("a", "every day")
    schedule.create("b", "every day")
    with pytest.raises(TooManySeries, match="2 repeating reminders"):
        schedule.create("c", "every day")
    schedule.stop(1)
    assert schedule.create("c", "every day")["id"] == 3


def test_the_source_and_the_ids_are_checked(schedule):
    with pytest.raises(ValueError, match="source must be one of chat, page"):
        schedule.create("x", "every day", source="model")
    for name in ("thread_id", "message_id"):
        for value in ("3", 1.5, True):
            with pytest.raises(ValueError, match=f"{name} must be a whole number or None"):
                schedule.create("x", "every day", **{name: value})
    assert schedule.series("all") == []


# ---- reading ----------------------------------------------------------------------------------------

def test_series_come_oldest_first_and_can_be_asked_for_by_state(schedule):
    for name in "abc":
        schedule.create(name, "every day")
    schedule.stop(2)
    assert [s["content"] for s in schedule.series()] == ["a", "c"]
    assert [s["content"] for s in schedule.series("ended")] == ["b"]
    assert [s["content"] for s in schedule.series("all")] == ["a", "b", "c"]


@pytest.mark.parametrize("state", ["paused", "", None, "ACTIVE", 1])
def test_an_unknown_state_is_refused(schedule, state):
    with pytest.raises(ValueError, match="state must be one of active, ended, all"):
        schedule.series(state)


def test_a_series_that_is_not_there_is_unknown(schedule):
    for call in (schedule.get, schedule.pause, schedule.resume, schedule.skip, schedule.stop):
        with pytest.raises(UnknownSeries, match="there is no repeating reminder 9"):
            call(9)


def test_a_series_is_described_in_words_and_an_ended_one_has_no_next_time(schedule):
    schedule.create("bins", "every Monday and Thursday at 6pm")
    assert diya_schedule.describe(schedule.get(1)) == {"rule": "Every Monday and Thursday at 18:00", "next": "Monday 12 Oct 2026, 18:00"}
    schedule.stop(1)
    assert diya_schedule.describe(schedule.get(1)) == {"rule": "Every Monday and Thursday at 18:00", "next": None}


def test_the_trail_can_be_read_for_one_series_and_cut_short_and_a_bad_limit_is_refused(schedule):
    schedule.create("a", "every day")
    schedule.create("b", "every day")
    schedule.pause(2)
    assert [(e["series_id"], e["event"]) for e in schedule.events(series_id=2)] == [(2, "created"), (2, "paused")]
    assert len(schedule.events()) == 3 and len(schedule.events(limit=2)) == 2 and schedule.events(limit=2)[0]["series_id"] == 1
    for bad in (0, -1, True, "3", 1.5):
        with pytest.raises(ValueError, match="limit must be a whole number above 0"):
            schedule.events(limit=bad)


def test_an_event_that_is_not_one_of_the_known_events_or_actors_is_a_bug(schedule):
    conn = schedule.store.connect()
    for event, actor in (("exploded", "owner"), ("created", "stranger")):
        with pytest.raises(ValueError, match="unknown event or actor"):
            schedule._event(conn, event, actor, "t")
    conn.close()


# ---- pause, resume, skip, stop -----------------------------------------------------------------------

def test_pausing_stops_it_making_reminders_and_resuming_works_the_next_one_out_from_now(schedule, clock, store):
    schedule.create("bins", "every Monday at 9am")
    assert schedule.pause(1)["paused"] is True
    clock["now"] = datetime(2026, 10, 20, 8, 0)  # more than a week later: two Mondays have passed
    assert schedule.materialize() == [] and store.reminders("all") == []
    resumed = schedule.resume(1)
    assert resumed["paused"] is False and resumed["next_ts"] == ts(datetime(2026, 10, 26, 9, 0))  # from now, not from the old time
    assert schedule.materialize() == [] and store.reminders("all") == []  # nothing for the time it was paused
    events = schedule.events(series_id=1)
    assert [e["event"] for e in events] == ["created", "paused", "resumed"] and events[2]["detail"] == {"was_next": ts(datetime(2026, 10, 12, 9, 0))}
    assert {e["actor"] for e in events[1:]} == {"owner"}


def test_skipping_lets_the_next_time_pass_without_a_reminder_and_moves_on_exactly_one_step(schedule, store):
    schedule.create("bins", "every Monday at 9am")
    skipped = schedule.skip(1)
    assert skipped["next_ts"] == ts(datetime(2026, 10, 19, 9, 0)) and store.reminders("all") == []
    assert schedule.skip(1)["next_ts"] == ts(datetime(2026, 10, 26, 9, 0))
    assert schedule.events(series_id=1)[1]["detail"] == {"skipped": ts(datetime(2026, 10, 12, 9, 0))}


def test_stopping_ends_it_for_good_and_leaves_a_reminder_it_already_made(schedule, clock, store):
    schedule.create("bins", "every Monday at 9am")
    clock["now"] = datetime(2026, 10, 12, 9, 5)
    (made,) = schedule.materialize()
    stopped = schedule.stop(1)
    assert stopped["ended"] is True and stopped["next_ts"] is None and stopped["ended_at"] == ts(clock["now"])
    assert [r["id"] for r in store.reminders("pending")] == [made]
    clock["now"] = datetime(2026, 10, 30, 9, 5)
    assert schedule.materialize() == []


@pytest.mark.parametrize("setup, call, why", [
    (["pause"], "pause", "already paused"), ([], "resume", "not paused"), (["stop"], "pause", "has been stopped"), (["stop"], "resume", "has been stopped"),
    (["stop"], "skip", "has been stopped"), (["pause"], "skip", "paused; resume it first"), (["stop"], "stop", "already been stopped"),
])
def test_what_makes_no_sense_is_refused_and_changes_nothing(schedule, setup, call, why):
    schedule.create("bins", "every Monday at 9am")
    for step in setup:
        getattr(schedule, step)(1)
    before, trail = schedule.get(1), schedule.events()
    with pytest.raises(IllegalState, match=why):
        getattr(schedule, call)(1)
    assert schedule.get(1) == before and schedule.events() == trail


def test_a_change_that_fails_part_way_is_rolled_back(schedule, monkeypatch):
    schedule.create("bins", "every Monday at 9am")

    def broken(*args, **kwargs):
        raise RuntimeError("part way")

    monkeypatch.setattr(Schedule, "_event", staticmethod(broken))
    with pytest.raises(RuntimeError):
        schedule.pause(1)
    monkeypatch.undo()
    assert schedule.get(1)["paused"] is False and len(schedule.events()) == 1


# ---- making what has come due -------------------------------------------------------------------------

def test_when_the_time_comes_an_ordinary_reminder_is_made_once_and_the_series_moves_on(schedule, clock, store):
    schedule.create("take out the bins", "every Monday at 9am")
    assert schedule.materialize() == []  # not yet
    clock["now"] = datetime(2026, 10, 12, 9, 0)  # exactly the time: it has come
    assert schedule.materialize() == [1]
    assert schedule.materialize() == []  # and not again
    (reminder,) = store.reminders("all")
    assert (reminder["content"], reminder["due_at"], reminder["due_ts"], reminder["done"], reminder["notified_at"]) == (
        "take out the bins", "every Monday at 9am", ts(datetime(2026, 10, 12, 9, 0)), 0, None)
    assert schedule.get(1)["next_ts"] == ts(datetime(2026, 10, 19, 9, 0))
    assert schedule.series_of([1]) == {1: 1}
    occurred = [e for e in schedule.events() if e["event"] == "occurred"]
    assert len(occurred) == 1 and (occurred[0]["actor"], occurred[0]["series_id"], occurred[0]["reminder_id"]) == ("system", 1, 1)
    assert occurred[0]["detail"] == {"due": ts(datetime(2026, 10, 12, 9, 0))}


def test_a_made_reminder_is_told_and_done_like_any_other_and_the_series_carries_on(schedule, clock, store):
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 8, 30)
    (first,) = schedule.materialize()
    assert [r["id"] for r in store.due_reminders(ts(clock["now"]), unnotified_only=True)] == [first]
    assert store.mark_notified(first) is True and store.complete_reminder(first) is True
    clock["now"] = datetime(2026, 10, 12, 8, 30)
    (second,) = schedule.materialize()
    assert second != first and store.get_reminder(first)["done"] == 1 and store.get_reminder(second)["done"] == 0
    assert [e["event"] for e in schedule.events() if e["event"] in ("lapsed", "missed")] == []  # first was done: nothing lapsed


def test_nothing_due_asks_for_no_write_lock(schedule, clock, monkeypatch):
    schedule.create("bins", "every Monday at 9am")

    def not_allowed(self):
        raise AssertionError("materialize asked for the write lock with nothing due")

    monkeypatch.setattr(Schedule, "_write", not_allowed)
    assert schedule.materialize() == []
    clock["now"] = datetime(2026, 10, 11, 23, 59)
    assert schedule.materialize() == []


def test_two_series_that_are_both_due_each_make_one_in_order(schedule, clock, store):
    schedule.create("a", "every day at 8am")
    schedule.create("b", "every day at 9am")
    clock["now"] = datetime(2026, 10, 11, 9, 30)
    assert schedule.materialize() == [1, 2]
    assert [r["content"] for r in store.reminders("all")] == ["a", "b"]


def test_a_series_that_fell_behind_makes_one_reminder_for_the_latest_time_and_records_the_rest_as_missed(schedule, clock, store):
    schedule.create("take pills", "every day at 8am")  # next: Sun 11 Oct 08:00
    clock["now"] = datetime(2026, 10, 20, 8, 30)  # asleep for nine days: falls on 11..20 Oct are due: ten of them
    assert schedule.materialize() == [1]
    (reminder,) = store.reminders("all")
    assert reminder["due_ts"] == ts(datetime(2026, 10, 20, 8, 0))  # the latest
    assert schedule.get(1)["next_ts"] == ts(datetime(2026, 10, 21, 8, 0))
    (missed,) = [e for e in schedule.events() if e["event"] == "missed"]
    assert missed["detail"] == {"missed": 9, "made_for": ts(datetime(2026, 10, 20, 8, 0))} and missed["actor"] == "system"


def test_a_series_that_is_one_behind_records_nothing_missed(schedule, clock):
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 20, 0)
    schedule.materialize()
    assert [e for e in schedule.events() if e["event"] == "missed"] == []


def test_a_series_further_behind_than_the_catch_up_limit_is_moved_on_to_the_most_recent_time(schedule, clock, store, monkeypatch):
    monkeypatch.setattr(diya_schedule, "MAX_CATCH_UP", 3)
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 20, 8, 30)
    assert schedule.materialize() == [1]
    assert store.get_reminder(1)["due_ts"] == ts(datetime(2026, 10, 20, 8, 0))
    assert schedule.get(1)["next_ts"] == ts(datetime(2026, 10, 21, 8, 0))


def test_a_pending_reminder_of_the_same_series_lapses_when_a_newer_one_arrives_and_nothing_else_does(schedule, clock, store):
    schedule.create("take pills", "every day at 8am")
    schedule.create("water plants", "every day at 8am")
    other = store.add_reminder("a one-off")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    first, plants = schedule.materialize()
    done = store.add_reminder("already done")
    store.complete_reminder(done)
    clock["now"] = datetime(2026, 10, 12, 9, 0)
    schedule.materialize()
    assert store.get_reminder(first)["done"] == 1 and store.get_reminder(plants)["done"] == 1  # both stale ones closed
    assert store.get_reminder(other)["done"] == 0  # a one-off is never touched
    assert [r["id"] for r in store.reminders("pending") if r["id"] not in (first, plants)] == [other, 5, 6]
    lapsed = [e for e in schedule.events() if e["event"] == "lapsed"]
    assert sorted((e["series_id"], e["reminder_id"]) for e in lapsed) == [(1, first), (2, plants)] and {e["actor"] for e in lapsed} == {"system"}


def test_a_done_reminder_of_a_series_is_not_reported_lapsed(schedule, clock, store):
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    (first,) = schedule.materialize()
    store.complete_reminder(first)
    clock["now"] = datetime(2026, 10, 12, 9, 0)
    schedule.materialize()
    assert [e for e in schedule.events() if e["event"] == "lapsed"] == []


def test_a_paused_or_stopped_series_makes_nothing_however_late(schedule, clock, store):
    schedule.create("a", "every day at 8am")
    schedule.create("b", "every day at 8am", source="page")
    schedule.create("c", "every day at 8am", source="page")
    schedule.pause(2)
    schedule.stop(3)
    clock["now"] = datetime(2026, 11, 1, 9, 0)
    assert schedule.materialize() == [1]
    assert [r["content"] for r in store.reminders("all")] == ["a"]


def test_a_rule_that_cannot_be_read_back_is_left_alone_and_the_others_are_still_made(schedule, clock, store):
    schedule.create("good", "every day at 8am")
    schedule.create("bad", "every day at 9am", source="page")
    conn = schedule.store.connect()
    conn.execute("UPDATE reminder_series SET rule = 'nonsense' WHERE id = 2")
    conn.commit()
    conn.close()
    clock["now"] = datetime(2026, 10, 11, 10, 0)
    assert schedule.materialize() == [1]
    assert schedule.get(2)["next_ts"] == ts(datetime(2026, 10, 11, 9, 0))  # untouched: still due, never guessed at


def test_a_series_due_by_its_text_but_not_by_the_local_clock_is_left_for_the_next_look(schedule, clock, store, monkeypatch):
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 8, 0)
    real = diya_time.local_from_iso
    monkeypatch.setattr(diya_time, "local_from_iso", lambda text, *a, **k: real(text, *a, **k) + timedelta(minutes=1))  # the clocks disagree
    assert schedule.materialize() == [] and store.reminders("all") == []
    monkeypatch.undo()
    assert schedule.materialize() == [1]


def test_two_callers_looking_at_once_make_one_reminder_between_them(store, clock):
    Schedule(store, clock=lambda: clock["now"]).create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    barrier = threading.Barrier(6)
    made = []

    def look():
        barrier.wait()
        made.extend(Schedule(store, clock=lambda: clock["now"]).materialize())

    threads = [threading.Thread(target=look) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert made == [1] and len(store.reminders("all")) == 1


def test_a_write_that_fails_while_making_a_reminder_leaves_nothing_behind(schedule, clock, store, monkeypatch):
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    original = Schedule._event

    def fails_on_occurred(conn, event, *args, **kwargs):
        if event == "occurred":
            raise RuntimeError("part way")
        return original(conn, event, *args, **kwargs)

    monkeypatch.setattr(Schedule, "_event", staticmethod(fails_on_occurred))
    with pytest.raises(RuntimeError):
        schedule.materialize()
    monkeypatch.undo()
    assert store.reminders("all") == [] and schedule.get(1)["next_ts"] == ts(datetime(2026, 10, 11, 8, 0))
    assert schedule.materialize() == [1]  # and the next look still makes it


# ---- snooze --------------------------------------------------------------------------------------------

def test_snoozing_moves_a_reminder_and_has_it_told_again_then(schedule, clock, store):
    rid = store.add_reminder("call mum", "Friday 5pm", ts(datetime(2026, 10, 9, 17, 0)))
    store.mark_notified(rid)
    result = schedule.snooze(rid, "in 10 minutes")
    assert result == {"id": rid, "due_ts": ts(datetime(2026, 10, 10, 10, 25)), "due_text": "Saturday 10 Oct 2026, 10:25", "assumed": []}
    row = store.get_reminder(rid)
    assert (row["due_ts"], row["notified_at"], row["done"], row["due_at"]) == (ts(datetime(2026, 10, 10, 10, 25)), None, 0, "Friday 5pm")
    assert store.due_reminders(ts(datetime(2026, 10, 10, 10, 26)), unnotified_only=True)[0]["id"] == rid
    (event,) = schedule.events()
    assert (event["event"], event["actor"], event["reminder_id"], event["series_id"]) == ("snoozed", "owner", rid, None)
    assert event["detail"] == {"from": ts(datetime(2026, 10, 9, 17, 0)), "to": ts(datetime(2026, 10, 10, 10, 25)), "said": "in 10 minutes"}


def test_a_reminder_with_no_time_can_be_given_one_and_what_was_assumed_is_said(schedule, store):
    rid = store.add_reminder("no time")
    result = schedule.snooze(rid, "tomorrow")
    assert result["due_ts"] == ts(datetime(2026, 10, 11, 9, 0)) and result["assumed"] == ["no time was given, so 09:00"]
    assert schedule.events()[0]["detail"]["from"] is None


def test_snoozing_a_reminder_of_a_series_moves_that_reminder_and_leaves_the_series_alone(schedule, clock, store):
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 8, 30)
    (rid,) = schedule.materialize()
    series_before = schedule.get(1)
    schedule.snooze(rid, "in an hour")
    assert schedule.get(1) == series_before and store.get_reminder(rid)["due_ts"] == ts(datetime(2026, 10, 11, 9, 30))
    assert schedule.events()[-1]["series_id"] == 1


def test_snooze_refuses_a_time_it_cannot_read_a_time_that_has_passed_a_done_reminder_and_one_that_is_not_there(schedule, store):
    rid = store.add_reminder("x", None, ts(datetime(2026, 10, 12, 9, 0)))
    for words in ("soonish", "yesterday", "", None, 5):
        with pytest.raises(NotUnderstood):
            schedule.snooze(rid, words)
    assert store.get_reminder(rid)["due_ts"] == ts(datetime(2026, 10, 12, 9, 0)) and schedule.events() == []
    done = store.add_reminder("done")
    store.complete_reminder(done)
    with pytest.raises(IllegalState, match="already done"):
        schedule.snooze(done, "tomorrow")
    with pytest.raises(UnknownReminder, match="there is no reminder 99"):
        schedule.snooze(99, "tomorrow")
    assert schedule.events() == []


# ---- which series a reminder came from -----------------------------------------------------------------

def test_which_reminders_came_from_a_series_is_asked_in_one_go_and_junk_is_ignored(schedule, clock, store):
    schedule.create("a", "every day at 8am")
    plain = store.add_reminder("plain")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    (made,) = schedule.materialize()
    assert schedule.series_of([plain, made, 99]) == {made: 1}
    assert schedule.series_of([]) == {} and schedule.series_of(["1; DROP TABLE reminders", None, True, 1.5]) == {}


# ---- what the mutation run found nothing checking ----------------------------------------------------------------------

def test_a_write_holds_the_database_write_lock_from_its_first_statement(store):
    """What keeps "is it already active?" and "is it full?" true at the moment the series is written (as for the task list)."""
    schedule = Schedule(store, clock=lambda: NOW)
    with schedule._write():
        other = sqlite3.connect(store.path, timeout=0.05)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()


def test_the_limits_are_the_documented_ones():
    assert (diya_schedule.MAX_ACTIVE, diya_schedule.MAX_CONTENT_CHARS, diya_schedule.MAX_CATCH_UP) == (20, 300, 5000)


def test_exactly_the_catch_up_limit_behind_is_worked_through_and_further_behind_records_what_it_worked_through(schedule, clock, store, monkeypatch):
    monkeypatch.setattr(diya_schedule, "MAX_CATCH_UP", 3)
    schedule.create("take pills", "every day at 8am")  # first falls 11 Oct
    clock["now"] = datetime(2026, 10, 13, 8, 30)  # the 11th, 12th and 13th: exactly three
    schedule.materialize()
    schedule.create("water plants", "every day at 8am")  # first falls 14 Oct
    clock["now"] = datetime(2026, 10, 17, 8, 30)  # the 14th to the 17th: four, one more than it will work through
    schedule.materialize()
    missed = [(e["series_id"], e["detail"]) for e in schedule.events() if e["event"] == "missed"]
    assert missed[0] == (1, {"missed": 2, "made_for": ts(datetime(2026, 10, 13, 8, 0))})  # three falls: all worked through, one made, two missed
    assert (2, {"missed": 2, "made_for": ts(datetime(2026, 10, 17, 8, 0))}) in missed  # four: it stops at the limit, then moves on to the latest
    assert schedule.get(2)["next_ts"] == ts(datetime(2026, 10, 18, 8, 0))


def test_a_paused_series_that_is_past_due_asks_for_no_write_lock(schedule, clock, monkeypatch):
    schedule.create("bins", "every Monday at 9am")
    schedule.pause(1)
    clock["now"] = datetime(2026, 10, 13, 9, 0)

    def not_allowed(self):
        raise AssertionError("materialize asked for the write lock for a series that makes nothing")

    monkeypatch.setattr(Schedule, "_write", not_allowed)
    assert schedule.materialize() == []


def test_a_stopped_series_row_that_somehow_still_has_a_time_asks_for_no_write_lock_and_makes_nothing(schedule, clock, store, monkeypatch):
    schedule.create("bins", "every Monday at 9am")
    conn = store.connect()
    conn.execute("UPDATE reminder_series SET ended = 1 WHERE id = 1")  # stop() clears the time; a row that says otherwise is still stopped
    conn.commit()
    conn.close()
    clock["now"] = datetime(2026, 10, 13, 9, 0)

    def not_allowed(self):
        raise AssertionError("materialize asked for the write lock for a stopped series")

    monkeypatch.setattr(Schedule, "_write", not_allowed)
    assert schedule.materialize() == []


def test_series_of_answers_only_for_real_reminder_ids(schedule, clock):
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    (rid,) = schedule.materialize()
    assert schedule.series_of([rid]) == {rid: 1} and schedule.series_of([rid, True, rid]) == {rid: 1}
    assert schedule.series_of([True]) == {}  # True is not reminder 1
    assert schedule.series_of([str(rid)]) == {} and schedule.series_of([float(rid)]) == {} and schedule.series_of([None, "x", [1]]) == {}
    assert schedule.series_of([]) == {}


def test_the_words_are_kept_with_single_spaces_in_the_series_and_in_a_snooze(schedule, store):
    series = schedule.create("bins", "  every   Monday  at 9am ")
    assert series["said"] == "every Monday at 9am"
    rid = store.add_reminder("call mum", "x", ts(datetime(2026, 10, 11, 9, 0)))
    schedule.snooze(rid, "  in   10  minutes ")
    assert [e for e in schedule.events() if e["event"] == "snoozed"][0]["detail"]["said"] == "in 10 minutes"


def test_the_trail_stores_detail_as_sorted_json_and_as_null_when_there_is_none(schedule, store):
    schedule.create("bins", "every Monday at 9am")
    schedule.pause(1)
    conn = store.connect()
    try:
        rows = conn.execute("SELECT event, detail FROM schedule_events ORDER BY id").fetchall()
    finally:
        conn.close()
    assert rows == [("created", '{"rule": "weekly:0@09:00", "said": "every Monday at 9am"}'), ("paused", None)]


def test_the_trail_sorts_the_keys_of_its_detail_so_the_same_event_is_always_the_same_text(schedule, clock, store):
    """"created" happens to put its keys in order already; "snoozed" and "missed" do not, so they show whether the dump sorts them."""
    schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 13, 9, 0)
    schedule.materialize()  # three falls behind: one made, two missed
    rid = store.add_reminder("call mum", "x", ts(datetime(2026, 10, 14, 9, 0)))
    schedule.snooze(rid, "in 10 minutes")
    conn = store.connect()
    try:
        rows = dict(conn.execute("SELECT event, detail FROM schedule_events WHERE event IN ('missed', 'snoozed')").fetchall())
    finally:
        conn.close()
    assert rows["missed"] == '{"made_for": "%s", "missed": 2}' % ts(datetime(2026, 10, 13, 8, 0))
    assert rows["snoozed"] == '{"from": "%s", "said": "in 10 minutes", "to": "%s"}' % (ts(datetime(2026, 10, 14, 9, 0)), ts(datetime(2026, 10, 13, 9, 10)))
