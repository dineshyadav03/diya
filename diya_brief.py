"""The day, from what the owner already has (docs/SCHEDULE_DESIGN.md, D8 and unit R5).

Nothing here is written by a model: the brief is a view of rows the owner, or the owner's own words, already made --
reminders, tasks and repeating reminders -- sorted and counted, with one plain sentence on top made from the counts. So there is
nothing in it to review before trusting it, and nothing that can be talked into saying something (docs/PROACTIVITY_DESIGN.md D8
wanted review because it assumed a model would write it; a list of the owner's own rows needs none).

`build` is pure: it is given the rows and the current local time and returns a plain dict, reading no store and no clock.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import diya_schedule
import diya_tasks
import diya_time

SERIES_SHOWN = 5  # how many of the repeating reminders the brief lists, soonest first


def _day_bounds(now):
    """(the stored text of the start of today, of the start of tomorrow), in the local day that `now` is in."""
    start = datetime.combine(now.date(), time.min)
    return diya_time.iso_of_local(start), diya_time.iso_of_local(start + timedelta(days=1))


def _plural(count, thing):
    return f"{count} {thing}" if count == 1 else f"{count} {thing}s"


def _reminder(row, series_ids):
    return {
        "id": row["id"],
        "content": row["content"],
        "due": row["due_ts"],
        "due_text": diya_time.describe_local(diya_time.local_from_iso(row["due_ts"])) if row["due_ts"] else None,
        "told": row["notified_at"] is not None,
        "repeats": row["id"] in series_ids,
    }


def _task(task, now):
    return {
        "id": task["id"],
        "content": task["content"],
        "due": task["due_ts"],
        "due_text": diya_tasks.describe_due(task) if task["due_ts"] else None,
        "overdue": diya_tasks.is_overdue(task, now),
    }


def headline(counts):
    """One sentence from the counts, or "Nothing is due today." when there is nothing to say."""
    parts = []
    if counts["due_now"]:
        parts.append(f"{_plural(counts['due_now'], 'reminder')} due now")
    if counts["later_today"]:
        parts.append(f"{_plural(counts['later_today'], 'reminder')} later today")
    if counts["tasks_overdue"]:
        parts.append(f"{_plural(counts['tasks_overdue'], 'task')} overdue")
    if counts["tasks_today"]:
        parts.append(f"{_plural(counts['tasks_today'], 'task')} due today")
    if counts["repeating_today"]:
        parts.append(f"{_plural(counts['repeating_today'], 'repeating reminder')} making one today")
    if not parts:
        return "Nothing is due today."
    return ", ".join(parts) + "."  # every part starts with a count, so there is no first letter to capitalise


def build(now, reminders, tasks, series, series_ids=()):
    """The brief for the local day of `now` (a naive datetime).

    `reminders`: the pending reminders as `Store.reminders("pending")` gives them; `tasks`: the open tasks as `Tasks.tasks("open")`
    gives them; `series`: the repeating reminders as `Schedule.series("active")` gives them (a paused one makes nothing, so it is
    left out); `series_ids`: the ids of the reminders that came from a series.
    """
    series_ids = set(series_ids)
    now_ts = diya_time.iso_of_local(now)
    _, tomorrow_ts = _day_bounds(now)

    timed = sorted((r for r in reminders if r["due_ts"]), key=lambda r: (r["due_ts"], r["id"]))
    due_now = [_reminder(r, series_ids) for r in timed if r["due_ts"] <= now_ts]
    later_today = [_reminder(r, series_ids) for r in timed if now_ts < r["due_ts"] < tomorrow_ts]
    no_time = sum(1 for r in reminders if not r["due_ts"])

    shown = [_task(t, now) for t in sorted(tasks, key=lambda t: (t["due_ts"] or "", t["id"]))]
    overdue = [t for t in shown if t["overdue"]]
    today = [t for t in shown if not t["overdue"] and t["due"] and _is_today(t, now)]
    undated = sum(1 for t in tasks if not t["due_ts"])

    running = sorted((s for s in series if not s["paused"] and not s["ended"] and s["next_ts"]), key=lambda s: (s["next_ts"], s["id"]))
    repeating = []
    for s in running[:SERIES_SHOWN]:
        words = diya_schedule.describe(s)
        repeating.append({"id": s["id"], "content": s["content"], "rule": words["rule"], "next": words["next"], "today": s["next_ts"] < tomorrow_ts})
    repeating_today = sum(1 for s in running if s["next_ts"] < tomorrow_ts)

    counts = {
        "due_now": len(due_now), "later_today": len(later_today), "no_time": no_time,
        "tasks_overdue": len(overdue), "tasks_today": len(today), "tasks_undated": undated,
        "repeating": len(running), "repeating_today": repeating_today,
    }
    return {
        "date": f"{diya_time.DAY_NAMES[now.weekday()]} {now.day} {diya_time.MONTH_NAMES[now.month - 1]} {now.year}",
        "headline": headline(counts),
        "due_now": due_now,
        "later_today": later_today,
        "tasks_overdue": overdue,
        "tasks_today": today,
        "repeating": repeating,
        "counts": counts,
    }


def _is_today(task, now):
    """Is the task's due day today? (A task due on a day with no time named is due today all day, even before its stored 09:00.)"""
    return diya_time.local_from_iso(task["due"]).date() == now.date()
