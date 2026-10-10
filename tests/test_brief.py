"""The day's brief (docs/SCHEDULE_DESIGN.md, D8 and unit R5): diya_brief.py.

What this proves: the brief puts each reminder where it belongs by the clock (due now, later today, or neither: a reminder due
at the very moment is due now, and one due at midnight tonight is tomorrow's), sorts them, counts the ones with no time; sorts
tasks into overdue and due today by the same rule the task list uses (a task due on a day is not late until the day is over), leaves the
rest out and counts the undated; lists the repeating reminders that are running, soonest first and no more than five, leaving a paused
or a stopped one out, and says which of them make one today; marks a reminder that came from a repeating one; makes one plain sentence
from the counts; and changes nothing it is given.
"""
import copy
import dataclasses
from datetime import datetime

import pytest

import diya
import diya_brief
import diya_config
import diya_time
from fakes import FakeClient, text_reply

NOW = datetime(2026, 10, 10, 10, 15)  # a Saturday, 10:15 local


def ts(local):
    return diya_time.iso_of_local(local)


def on(day, hour=0, minute=0):
    return ts(datetime(2026, 10, day, hour, minute))


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def agent(tmp_path, clock):
    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(
        diya_config.load_config(), db_path=str(data / "b.db"), profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"), dream_log_path=str(data / "dream.log"), dream_pending_path=str(data / "pending.jsonl"),
    )
    return diya.Agent(config, client=FakeClient([text_reply("ok")] * 5), clock=lambda: clock["now"])


def brief_of(agent, now=NOW):
    rows = agent.store.reminders("pending")
    return diya_brief.build(now, rows, agent.tasks.tasks("open"), agent.schedule.series("active"), agent.schedule.series_of([r["id"] for r in rows]))


# --- reminders ------------------------------------------------------------------------------------------------

def test_a_reminder_is_due_now_from_the_moment_it_falls_and_later_today_until_midnight(agent):
    for content, when in (("two days ago", on(8, 9)), ("this morning", on(10, 9)), ("this very minute", on(10, 10, 15)),
                          ("a minute from now", on(10, 10, 16)), ("tonight", on(10, 23, 59)), ("midnight", on(11, 0, 0)), ("tomorrow", on(11, 9))):
        agent.store.add_reminder(content, content, when)
    brief = brief_of(agent)
    assert [r["content"] for r in brief["due_now"]] == ["two days ago", "this morning", "this very minute"]  # oldest first; the moment itself is due
    assert [r["content"] for r in brief["later_today"]] == ["a minute from now", "tonight"]  # midnight tonight is already tomorrow
    assert brief["counts"]["due_now"] == 3 and brief["counts"]["later_today"] == 2


def test_each_reminder_carries_what_the_page_needs_and_nothing_made_up(agent):
    rid = agent.store.add_reminder("call mum", "at 5pm", on(10, 17))
    (item,) = brief_of(agent)["later_today"]
    assert item["id"] == rid and item["content"] == "call mum" and item["due"] == on(10, 17)
    assert item["due_text"] == "Saturday 10 Oct 2026, 17:00" and item["repeats"] is False and item["told"] is False
    assert set(item) == {"id", "content", "due", "due_text", "told", "repeats"}
    agent.store.mark_notified(rid)
    assert brief_of(agent)["later_today"][0]["told"] is True


def test_a_reminder_with_no_time_is_counted_and_not_listed(agent):
    agent.store.add_reminder("someday")
    agent.store.add_reminder("also someday", "when I'm back")
    brief = brief_of(agent)
    assert brief["counts"]["no_time"] == 2 and brief["due_now"] == [] and brief["later_today"] == []


def test_reminders_that_fall_at_the_same_moment_keep_the_order_they_were_made(agent):
    for name in ("first", "second", "third"):
        agent.store.add_reminder(name, name, on(10, 18))
    assert [r["content"] for r in brief_of(agent)["later_today"]] == ["first", "second", "third"]


def test_a_reminder_a_repeating_one_made_says_so(agent, clock):
    agent.schedule.create("take pills", "every day at 8am")
    clock["now"] = datetime(2026, 10, 11, 9, 0)
    agent.schedule.materialize()
    agent.store.add_reminder("a plain one", "x", on(11, 20))
    brief = brief_of(agent, now=clock["now"])
    assert [(r["content"], r["repeats"]) for r in brief["due_now"] + brief["later_today"]] == [("take pills", True), ("a plain one", False)]


# --- tasks ----------------------------------------------------------------------------------------------------

def test_a_task_is_overdue_by_the_lists_own_rule_and_due_today_otherwise(agent, clock):
    clock["now"] = datetime(2026, 10, 8, 12, 0)
    for content, due in (("late by a day", "Oct 9"), ("late by hours", "Oct 10 at 9am"), ("today, no time", "Oct 10"),
                         ("today, evening", "Oct 10 at 5pm"), ("tomorrow", "Oct 11"), ("no date", None), ("words only", "when I'm back")):
        agent.tasks.add(content, due)
    clock["now"] = NOW
    brief = brief_of(agent)
    assert [t["content"] for t in brief["tasks_overdue"]] == ["late by a day", "late by hours"]
    assert [t["content"] for t in brief["tasks_today"]] == ["today, no time", "today, evening"]  # a day-only task is not late until the day is over
    assert brief["counts"]["tasks_overdue"] == 2 and brief["counts"]["tasks_today"] == 2 and brief["counts"]["tasks_undated"] == 2
    assert set(brief["tasks_overdue"][0]) == {"id", "content", "due", "due_text", "overdue"} and brief["tasks_overdue"][0]["overdue"] is True
    assert brief["tasks_today"][0]["overdue"] is False and brief["tasks_today"][0]["due_text"] == "Saturday 10 Oct 2026"


def test_a_done_task_is_not_in_the_brief_because_only_open_ones_are_given(agent):
    task = agent.tasks.add("pay the bill", "today")
    agent.tasks.complete(task["id"])
    brief = brief_of(agent)
    assert brief["tasks_today"] == [] and brief["tasks_overdue"] == [] and brief["counts"]["tasks_undated"] == 0


# --- repeating reminders --------------------------------------------------------------------------------------

def test_running_repeating_reminders_are_listed_soonest_first_and_say_whether_one_falls_today(agent):
    agent.schedule.create("bins", "every Monday at 9am")
    agent.schedule.create("take pills", "every day at 8am")
    agent.schedule.create("evening walk", "every day at 6pm")
    brief = brief_of(agent)
    assert [(s["content"], s["next"], s["today"]) for s in brief["repeating"]] == [
        ("evening walk", "Saturday 10 Oct 2026, 18:00", True), ("take pills", "Sunday 11 Oct 2026, 08:00", False),
        ("bins", "Monday 12 Oct 2026, 09:00", False)]
    assert set(brief["repeating"][0]) == {"id", "content", "rule", "next", "today"} and brief["repeating"][0]["rule"] == "Every day at 18:00"
    assert brief["counts"]["repeating"] == 3 and brief["counts"]["repeating_today"] == 1


def test_a_paused_or_a_stopped_repeating_reminder_makes_nothing_so_it_is_not_in_the_brief(agent):
    for name in ("a", "b", "c"):
        agent.schedule.create(name, "every day at 6pm")
    agent.schedule.pause(2)
    agent.schedule.stop(3)
    brief = brief_of(agent)
    assert [s["content"] for s in brief["repeating"]] == ["a"] and brief["counts"]["repeating"] == 1 and brief["counts"]["repeating_today"] == 1


def test_no_more_than_five_repeating_reminders_are_listed_but_all_of_them_are_counted(agent):
    for n in range(7):
        agent.schedule.create(f"thing {n}", f"every day at {n + 11}:00")
    brief = brief_of(agent)
    assert len(brief["repeating"]) == diya_brief.SERIES_SHOWN == 5 and brief["counts"]["repeating"] == 7 and brief["counts"]["repeating_today"] == 7
    assert [s["content"] for s in brief["repeating"]] == [f"thing {n}" for n in range(5)]  # the soonest five


def test_a_series_with_no_next_time_is_left_out_rather_than_guessed_at():
    series = [{"id": 1, "content": "x", "rule": "daily@09:00", "next_ts": None, "paused": False, "ended": False}]
    brief = diya_brief.build(NOW, [], [], series)
    assert brief["repeating"] == [] and brief["counts"]["repeating"] == 0


# --- the sentence and the shape ---------------------------------------------------------------------------------

def test_an_empty_day_says_so_and_has_the_whole_shape(agent):
    brief = brief_of(agent)
    assert brief["headline"] == "Nothing is due today." and brief["date"] == "Saturday 10 Oct 2026"
    assert set(brief) == {"date", "headline", "due_now", "later_today", "tasks_overdue", "tasks_today", "repeating", "counts"}
    assert brief["counts"] == {"due_now": 0, "later_today": 0, "no_time": 0, "tasks_overdue": 0, "tasks_today": 0, "tasks_undated": 0,
                               "repeating": 0, "repeating_today": 0}


def counts_of(**given):
    base = {"due_now": 0, "later_today": 0, "no_time": 0, "tasks_overdue": 0, "tasks_today": 0, "tasks_undated": 0, "repeating": 0, "repeating_today": 0}
    return dict(base, **given)


@pytest.mark.parametrize("counts, sentence", [
    ({"due_now": 1}, "1 reminder due now."),
    ({"due_now": 2}, "2 reminders due now."),
    ({"later_today": 1}, "1 reminder later today."),
    ({"later_today": 3}, "3 reminders later today."),
    ({"tasks_overdue": 1}, "1 task overdue."),
    ({"tasks_overdue": 4}, "4 tasks overdue."),
    ({"tasks_today": 1}, "1 task due today."),
    ({"tasks_today": 2}, "2 tasks due today."),
    ({"repeating_today": 1}, "1 repeating reminder making one today."),
    ({"repeating_today": 2}, "2 repeating reminders making one today."),
    ({"due_now": 2, "later_today": 1, "tasks_overdue": 1, "tasks_today": 3, "repeating_today": 1},
     "2 reminders due now, 1 reminder later today, 1 task overdue, 3 tasks due today, 1 repeating reminder making one today."),
    ({"no_time": 5, "tasks_undated": 5, "repeating": 5}, "Nothing is due today."),  # things with no date are not "due today"
])
def test_the_sentence_is_made_from_the_counts_and_only_the_counts(counts, sentence):
    assert diya_brief.headline(counts_of(**counts)) == sentence


def test_the_date_is_the_local_day_in_words():
    assert diya_brief.build(datetime(2026, 1, 1, 0, 0), [], [], [])["date"] == "Thursday 1 Jan 2026"
    assert diya_brief.build(datetime(2026, 12, 31, 23, 59), [], [], [])["date"] == "Thursday 31 Dec 2026"


def test_the_day_ends_at_local_midnight_whatever_the_time_now(agent):
    agent.store.add_reminder("just before midnight", "x", on(10, 23, 59))
    agent.store.add_reminder("just after", "x", on(11, 0, 1))
    late = datetime(2026, 10, 10, 23, 58)
    brief = brief_of(agent, now=late)
    assert [r["content"] for r in brief["later_today"]] == ["just before midnight"]
    early = datetime(2026, 10, 11, 0, 0)
    brief = brief_of(agent, now=early)
    assert [r["content"] for r in brief["later_today"]] == ["just after"] and brief["date"] == "Sunday 11 Oct 2026"


def test_building_the_brief_changes_nothing_it_is_given(agent):
    agent.store.add_reminder("a", "x", on(10, 9))
    agent.store.add_reminder("b", "x", on(10, 18))
    agent.tasks.add("t", "today")
    agent.schedule.create("s", "every day at 6pm")
    rows = agent.store.reminders("pending")
    tasks = agent.tasks.tasks("open")
    series = agent.schedule.series("active")
    before = copy.deepcopy((rows, tasks, series))
    diya_brief.build(NOW, rows, tasks, series, {})
    assert (rows, tasks, series) == before


# ---- what the mutation run found nothing checking ----------------------------------------------------------------------

def test_reminders_are_in_time_order_whatever_order_they_were_made_in_and_ties_keep_the_order_made(agent):
    agent.store.add_reminder("evening", "x", on(10, 18))
    agent.store.add_reminder("late morning", "x", on(10, 11))
    agent.store.add_reminder("afternoon", "x", on(10, 17))
    agent.store.add_reminder("tie, made first", "x", on(10, 20))
    agent.store.add_reminder("tie, made second", "x", on(10, 20))
    assert [r["content"] for r in brief_of(agent)["later_today"]] == ["late morning", "afternoon", "evening", "tie, made first", "tie, made second"]


def test_tasks_are_in_due_order_whatever_order_they_were_made_in_and_ties_keep_the_order_made(agent, clock):
    clock["now"] = datetime(2026, 10, 8, 12, 0)
    agent.tasks.add("five o'clock", "Oct 10 at 5pm")
    agent.tasks.add("three o'clock", "Oct 10 at 3pm")
    agent.tasks.add("tie, made first", "Oct 10 at 8pm")
    agent.tasks.add("tie, made second", "Oct 10 at 8pm")
    clock["now"] = NOW
    assert [t["content"] for t in brief_of(agent)["tasks_today"]] == ["three o'clock", "five o'clock", "tie, made first", "tie, made second"]


def series_row(series_id, content, next_ts, **more):
    return dict({"id": series_id, "content": content, "rule": "daily@09:00", "next_ts": next_ts, "paused": False, "ended": False}, **more)


def test_repeating_reminders_that_fall_together_keep_the_order_they_were_made_in():
    rows = [series_row(1, "first", on(11, 9)), series_row(2, "second", on(11, 9)), series_row(3, "third", on(11, 9))]
    assert [s["content"] for s in diya_brief.build(NOW, [], [], rows)["repeating"]] == ["first", "second", "third"]


def test_a_stopped_series_is_left_out_even_if_it_is_handed_over_with_a_time():
    rows = [series_row(1, "running", on(11, 9)), series_row(2, "stopped", on(11, 9), ended=True)]
    brief = diya_brief.build(NOW, [], [], rows)
    assert [s["content"] for s in brief["repeating"]] == ["running"] and brief["counts"]["repeating"] == 1


def test_a_series_that_falls_at_midnight_tonight_falls_tomorrow_not_today():
    brief = diya_brief.build(NOW, [], [], [series_row(1, "at midnight", on(11, 0, 0)), series_row(2, "a minute before", on(10, 23, 59))])
    assert [(s["content"], s["today"]) for s in brief["repeating"]] == [("a minute before", True), ("at midnight", False)]
    assert brief["counts"]["repeating_today"] == 1
