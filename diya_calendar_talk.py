"""What is on the calendar, answered by code from Google Calendar for the days the person asked about (found on 2026-10-21 by the first real calendar answer).

The first real answer came from the model, which was given the next five events and wrote them out: it turned the year 2020 into "2.020", put emoji on them and said a block that began in 2020 "starts Dec 20" as if
it were new. Dates, times and a list of events are facts, not wording, and a model of four billion parameters is the wrong thing to copy them. So code reads the calendar for the days asked about and writes the list
itself: no model call, so no changed digits and no waiting for it to load.

Taken: a short, plain QUESTION about the calendar ("what's on my calendar?", "any meetings tomorrow?", "what do I have on Saturday?", "what's on my calendar this week?", "events on 28 Oct", "next 3 days"). The days come
from diya_when (today, tomorrow, this or next week, this weekend, a weekday name, a date); a question that names no day gets the next two weeks. Not taken, so the model and its tools answer as before: a request
to add, move, cancel or book anything, "next Friday" (which people mean two ways), a long message, and a question that is not about the calendar. Read only; one request to Google; the event titles are other
people's words and are cleaned (control and invisible characters removed) and cut. Importing this module has no side effects.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

import diya_connectors
import diya_google_calendar
import diya_when
from diya_memory import printable

MAX_CHARS = 110
LIMIT = 25  # events shown; one more is asked for, to know there are more
DEFAULT_DAYS = 14
TITLE_CHARS = 100

_SUBJECT = re.compile(r"\b(?:calendar|events?|meetings?|appointments?|agenda|schedule)\b", re.IGNORECASE)
_FRAME = re.compile(
    r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*"
    r"(?:what(?:'s|\s+is|\s+are|\s+do\s+i\s+have|\s+have\s+i|\s+events?|\s+meetings?|\s+appointments?)|which|any|anything|do\s+i\s+have|have\s+i\s+got|show|list|check|read|see|look"
    r"|tell\s+me\s+(?:what|my)|how\s+many|(?:my\s+)?(?:calendar|events|meetings|appointments|agenda|schedule))\b", re.IGNORECASE)
# "what do I have on Saturday?" names no calendar word but asks one; not when it is plainly about the to-do list or bills
_HAVE_ON = re.compile(r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and)\b[\s,]*)*what\s+(?:do\s+i|have\s+i\s+got)\s+(?:have\s+|got\s+)?(?:on|for|today|tomorrow|this|next|coming)\b", re.IGNORECASE)
_NOT_CALENDAR = re.compile(r"\b(?:list|tasks?|to-?do|reminders?|bills?|pay|buy|left\s+to|homework|exams?|know|think|remember)\b", re.IGNORECASE)
_REQUEST = re.compile(r"\b(?:add|create|make|book|set\s+up|put|remind|move|cancel|delete|remove|reschedule|schedule\s+(?:a|an|the|me|my)|invite|send|plan|organi[sz]e)\b", re.IGNORECASE)
_NEXT_DAYS = re.compile(r"\bnext\s+(\d{1,2})\s+days?\b", re.IGNORECASE)


def _day_name(day, today):
    text = f"{diya_when.DAYS[day.weekday()]} {day.day} {diya_when.MON[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def _label(start, end, today):
    if start == end:
        return "today" if start == today else "tomorrow" if start == today + timedelta(days=1) else _day_name(start, today)
    return f"{_day_name(start, today)} to {_day_name(end, today)}"


def asks(text, today=None):
    """(first day, last day, how to say it) if `text` is a plain question about the calendar, else None."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS or "\n" in text:
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    asked = (_SUBJECT.search(flat) and _FRAME.search(flat)) or _HAVE_ON.search(flat)
    if not asked or _REQUEST.search(flat) or _NOT_CALENDAR.search(flat) and not _SUBJECT.search(flat):
        return None
    today = today.date() if isinstance(today, datetime) else (today or datetime.now().astimezone().date())
    found = _NEXT_DAYS.search(flat)
    if found:
        days = max(1, min(int(found.group(1)), 31))
        return today, today + timedelta(days=days - 1), f"the next {days} days"
    if re.search(r"\bnext\s+(?:mon|tue|wed|thu|fri|sat|sun)", flat, re.IGNORECASE):
        return None  # "next Friday" is not guessed (diya_when.find leaves it too)
    span = diya_when.window(flat, today)
    if span is not None:
        return span[0], span[1], _label(span[0], span[1], today)
    day = diya_when.upcoming_day(flat, today)
    if day is not None:
        return day, day, _label(day, day, today)
    return today, today + timedelta(days=DEFAULT_DAYS - 1), "the next two weeks"


def _local(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()


def _span(event):
    """(first day, last day, start time text, end time text or None, whether it is an all-day event) of one event as Google gave it; None if it cannot be read."""
    try:
        if event["all_day"]:
            first = date.fromisoformat(event["start"])
            last = date.fromisoformat(event["end"]) - timedelta(days=1) if event.get("end") else first  # an all-day event's end is the day AFTER its last day
            return first, max(first, last), "all day", None, True
        begins, ends = _local(event["start"]), _local(event["end"]) if event.get("end") else None
        return begins.date(), (ends or begins).date(), begins.strftime("%H:%M"), ends, False
    except (KeyError, ValueError, TypeError):
        return None


def format_events(events, start_day, end_day, label, today):
    """The reply: the events for `label`, day by day, then the ones that began earlier and are still on; or "Nothing on your calendar for ...". Plain text, from the record, nothing added."""
    shown, more = events[:LIMIT], len(events) > LIMIT
    still_on, by_day = [], {}
    for event in shown:
        span = _span(event)
        if span is None:
            continue
        first, last, begins, ends, all_day = span
        title = printable(event.get("title") or "(no title)", TITLE_CHARS)
        if first < start_day:
            still_on.append(f"  {title} (started {_day_name(first, today)}, until {_day_name(last, today)})")
            continue
        if all_day:
            line = f"  all day  {title}" + (f" (until {_day_name(last, today)})" if last > first else "")
        elif ends is not None and ends.date() == first and ends.strftime("%H:%M") != begins:
            line = f"  {begins}-{ends.strftime('%H:%M')}  {title}"
        elif ends is not None and ends.date() > first:
            line = f"  {begins}  {title} (until {_day_name(ends.date(), today)} {ends.strftime('%H:%M')})"
        else:
            line = f"  {begins}  {title}"
        by_day.setdefault(first, []).append(line)
    if not still_on and not by_day:
        return f"Nothing on your calendar for {label}."
    lines = [f"Your calendar for {label}:"]
    if still_on:
        lines += ["Still on:"] + still_on
    for day in sorted(by_day):
        lines += [_day_name(day, today)] + by_day[day]
    if more:
        lines.append(f"... and more than {LIMIT}: ask about a shorter time to see the rest.")
    lines.append("(From Google Calendar, which I can only read.)")
    return "\n".join(lines)


def answer(config, question, now=None):
    """(the reply, whether it was read fine) when `question` is a plain calendar question, else None (then the model answers as before). Never raises."""
    now = now or datetime.now().astimezone()
    today = now.date()
    found = asks(question, today)
    if found is None:
        return None
    start_day, end_day, label = found
    named = bool(_SUBJECT.search(question))  # "what do I have on Saturday?" does not say calendar: it may mean reminders and tasks too
    try:
        if not diya_connectors.is_connected(config, "google_calendar"):
            return ("Google Calendar is not connected, so I can't look. The Connections page connects it.", True) if named else None
        start = datetime.combine(start_day, time.min).astimezone()
        end = datetime.combine(end_day + timedelta(days=1), time.min).astimezone()
        events, problem = diya_google_calendar.events_between(config, start, end, LIMIT + 1)
        if problem:
            return problem, False
        text = format_events(events, start_day, end_day, label, today)
        return (text if named else text + "\nYour reminders and tasks for the day are on the Today page."), True
    except Exception as exc:  # noqa: BLE001 -- a calendar that cannot be read is said, not a failed chat
        return f"I could not read the calendar ({type(exc).__name__}).", False
