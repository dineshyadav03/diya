"""Finding an event by name, and finding free time, answered by code from Google Calendar (DIYA-080; docs/GOOGLE_CHANGES.md), added 2026-10-26.

The same idea as diya_calendar_talk: dates, times and who is busy when are facts, so code reads the calendar and writes the answer itself, with no model call and no changed digits. Two kinds of short, plain question:

* **Finding**: "when is my dentist appointment?", "find my physics session", "do I have a lab on friday?" -> the events in the next 90 days (or the day named) whose name has those words. When nothing matches and the question
  did not say "calendar", the question is left to the chat (it may be about something the person told Diya or wrote in their notes, not about the calendar).
* **Free time**: "when am I free on friday?", "find an hour tomorrow", "am I free at 3pm on monday?" -> the gaps between events within working hours (9:00 to 18:00, said in the answer), day by day, and for a time asked about
  whether anything is on then. An event marked as free (Google's "transparent") and an all-day event that is not marked busy do not block.

Read only: one request to Google, through the one careful client (diya_google_client), on the read-only Calendar card. Event names are other people's words and are cleaned and cut. Importing this module has no side effects.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

import diya_connectors
import diya_google_calchange as cc
import diya_google_client as client
import diya_when
from diya_memory import printable

MAX_CHARS = 110
WORK_START, WORK_END = 9, 18
MAX_DAYS = 7
SHOWN = 10
SEARCH_DAYS = cc.WINDOW_DAYS
_LEAD = r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*"
_TOPIC = r"(?P<topic>[a-z0-9][a-z0-9 '&.-]{1,60}?)"
_WHEN = re.compile(_LEAD + r"(?:when(?:'s|\s+is|\s+are|\s+was)?|what\s+time\s+(?:is|are|was))\s+(?:my\s+|the\s+|our\s+)?" + _TOPIC + r"\s*\??$", re.IGNORECASE)
_FIND = re.compile(_LEAD + r"(?:find|search(?:\s+for)?|look\s+(?:for|up))\s+(?:in\s+my\s+calendar\s+for\s+|my\s+calendar\s+for\s+)?(?:my\s+|the\s+|our\s+)?" + _TOPIC + r"(?:\s+(?:in|on)\s+(?:my\s+)?calendar)?\s*\??$", re.IGNORECASE)
_HAVE_A = re.compile(_LEAD + r"do\s+i\s+have\s+(?:an?\s+|any\s+|the\s+)" + _TOPIC + r"(?:\s+(?:on|this|next|tomorrow|today|coming)\b.*)?\s*\??$", re.IGNORECASE)
_CALENDAR_WORD = re.compile(r"\bcalendar\b", re.IGNORECASE)  # only when the person says calendar is "nothing found" an answer: "when is my exam?" may be about something they told Diya
_NOT_A_SEARCH = re.compile(r"\b(?:add|create|make|book|set\s+up|put|remind|move|cancel|delete|remove|reschedule|invite|send|plan|free|busy|available|birthday|weather|time\s+is\s+it)\b", re.IGNORECASE)
_FREE = re.compile(
    _LEAD + r"(?:when\s+am\s+i\s+(?:free|available)|am\s+i\s+(?:free|available|busy)|are\s+you\s+able\s+to\s+find|find\s+(?:me\s+)?(?:an?\s+)?(?:free\s+)?(?:\d+\s*(?:hours?|hrs?|h|minutes?|mins?|m)|hour|half\s+an?\s+hour|time|slot|gap)|do\s+i\s+have\s+(?:any\s+)?(?:free\s+)?time)", re.IGNORECASE)
_LENGTH = re.compile(r"\b(?:(?P<n>\d{1,3})\s*(?P<u>hours?|hrs?|h|minutes?|mins?|m)\b|(?P<half>half\s+an?\s+hour)|(?P<hour>an?\s+hour))", re.IGNORECASE)
_CLOCK = re.compile(r"\bat\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?\b", re.IGNORECASE)


def _clean_topic(topic):
    return " ".join(re.sub(r"[^\w' &.-]", " ", topic).split()).strip(" .'-")


def search_topic(text):
    """The words of an event being looked for ("when is my dentist appointment?" -> "dentist appointment"), or None if the message is not such a question."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS or "\n" in text or _NOT_A_SEARCH.search(text):
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    found = _WHEN.search(flat) or _FIND.search(flat) or _HAVE_A.search(flat)
    topic = _clean_topic(found.group("topic")) if found else ""
    return topic if len(topic) >= 3 and topic.lower() not in {"it", "that", "this", "time", "date", "today", "tomorrow"} else None


def free_question(text, today):
    """(first day, last day, minutes wanted, the clock time asked about or None) for a question about free time, else None."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS or "\n" in text:
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    if not _FREE.search(flat) or re.search(r"\b(?:add|create|make|book|set\s+up|put|remind|move|cancel|delete|remove|reschedule|invite|send|schedule)\b", flat, re.IGNORECASE):
        return None
    if re.search(r"\bnext\s+(?:mon|tue|wed|thu|fri|sat|sun)", flat, re.IGNORECASE):
        return None  # "next Friday" is not guessed
    span = diya_when.window(flat, today)
    if span is not None:
        first, last = span
    else:
        day = diya_when.upcoming_day(flat, today)
        first = last = day if day is not None else today
        if day is None and not re.search(r"\btoday\b", flat, re.IGNORECASE):
            last = today + timedelta(days=2)  # "when am i free?" with no day: today and the two days after
    last = min(last, first + timedelta(days=MAX_DAYS - 1))
    minutes = 30
    length = _LENGTH.search(flat)
    if length:
        if length.group("half"):
            minutes = 30
        elif length.group("hour"):
            minutes = 60
        else:
            n, unit = int(length.group("n")), length.group("u").lower()
            minutes = n * 60 if unit.startswith("h") else n
    minutes = max(5, min(minutes, (WORK_END - WORK_START) * 60))
    at = None
    clock = _CLOCK.search(flat)
    if clock:
        hour, minute, ap = int(clock.group("h")), int(clock.group("m") or 0), (clock.group("ap") or "").lower()
        if ap == "pm" and hour < 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
        elif not ap and 1 <= hour <= 7:
            hour += 12  # "at 3" means the afternoon in a working day
        if 0 <= hour <= 23 and minute <= 59:
            at = time(hour, minute)
    return first, last, minutes, at


def _local(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def _busy(events, day):
    """The busy stretches of one local day, as sorted (from, to) pairs of local times, and the titles that make them."""
    start, end = datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min)
    stretches = []
    for event in events:
        if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
            continue
        first, last = event.get("start") or {}, event.get("end") or {}
        try:
            if first.get("dateTime") and last.get("dateTime"):
                begins, ends = _local(first["dateTime"]), _local(last["dateTime"])
            elif first.get("date"):
                begins = datetime.combine(date.fromisoformat(first["date"]), time.min)
                ends = datetime.combine(date.fromisoformat(last["date"]), time.min) if last.get("date") else begins + timedelta(days=1)
            else:
                continue
        except (ValueError, TypeError):
            continue
        if ends > start and begins < end:
            stretches.append((max(begins, start), min(ends, end), printable(event.get("summary") or "(no title)", 40)))
    return sorted(stretches)


def free_slots(events, day, minutes):
    """The free gaps of at least `minutes` inside working hours on `day`, as [(from, to)] local times."""
    open_, close = datetime.combine(day, time(WORK_START)), datetime.combine(day, time(WORK_END))
    cursor, gaps = open_, []
    for begins, ends, _title in _busy(events, day):
        if begins > cursor and (min(begins, close) - cursor) >= timedelta(minutes=minutes):
            gaps.append((cursor, min(begins, close)))
        cursor = max(cursor, ends)
        if cursor >= close:
            break
    if close - cursor >= timedelta(minutes=minutes):
        gaps.append((cursor, close))
    return gaps


def _day_name(day, today):
    text = f"{diya_when.DAYS[day.weekday()]} {day.day} {diya_when.MON[day.month - 1]}"
    return "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else text if day.year == today.year else f"{text} {day.year}"


def format_free(events, first, last, minutes, at, today):
    """The reply for a question about free time."""
    length = f"{minutes // 60} h {minutes % 60} min" if minutes % 60 and minutes >= 60 else f"{minutes // 60} hour{'s' if minutes > 60 else ''}" if minutes % 60 == 0 and minutes >= 60 else f"{minutes} minutes"
    lines = []
    day = first
    while day <= last:
        if at is not None:
            asked = datetime.combine(day, at)
            clash = [title for begins, ends, title in _busy(events, day) if begins < asked + timedelta(minutes=minutes) and ends > asked]
            word = f"At {at:%H:%M} on {_day_name(day, today)} you are " + ("busy: " + ", ".join(clash) + "." if clash else f"free for {length}.")
            lines.append(word)
        else:
            gaps = free_slots(events, day, minutes)
            busy = _busy(events, day)
            head = f"{_day_name(day, today).capitalize()}"
            if gaps:
                lines.append(f"{head}: free " + ", ".join(f"{a:%H:%M}-{b:%H:%M}" for a, b in gaps[:6]) + (f" (and {len(gaps) - 6} more)" if len(gaps) > 6 else ""))
            else:
                lines.append(f"{head}: no gap of {length} between {WORK_START}:00 and {WORK_END}:00" + (f" (busy: {', '.join(title for _a, _b, title in busy[:4])})" if busy else ""))
        day += timedelta(days=1)
    tail = f"(Gaps of {length} or more between {WORK_START}:00 and {WORK_END}:00, from Google Calendar, which I can only read.)" if at is None else "(From Google Calendar, which I can only read.)"
    return "\n".join(lines + [tail])


def format_found(events, topic, today, days):
    shown = []
    for event in events[:SHOWN]:
        first = event.get("start") or {}
        title = printable(event.get("summary") or "(no title)", 100)
        if first.get("dateTime"):
            begins = _local(first["dateTime"])
            shown.append(f"  {_day_name(begins.date(), today)}, {begins:%H:%M}  {title}")
        elif first.get("date"):
            shown.append(f"  {_day_name(date.fromisoformat(first['date']), today)}, all day  {title}")
    more = f"\n... and {len(events) - SHOWN} more." if len(events) > SHOWN else ""
    return f"On your calendar in the next {days} days, matching '{printable(topic, 60)}':\n" + "\n".join(shown) + more + "\n(From Google Calendar, which I can only read.)"


def _events(config, first, last):
    start = datetime.combine(first, time.min).astimezone()
    end = datetime.combine(last + timedelta(days=1), time.min).astimezone()
    items, _more = client.pages(config, cc.READER, cc.LABELS[cc.READER], cc.EVENTS, {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}, "items", max_pages=2)
    return items


def answer(config, question, now=None):
    """(the reply, whether it was read fine) when `question` asks for an event by name or for free time, else None (then the chat goes on as before). Never raises."""
    now = now or datetime.now().astimezone()
    today = now.date()
    try:
        free = free_question(question, today)
        topic = None if free else search_topic(question)
        if free is None and topic is None:
            return None
        if not diya_connectors.is_connected(config, cc.READER):
            return ("Google Calendar is not connected, so I can't look. The Connections page connects it.", True) if (free or _CALENDAR_WORD.search(question)) else None
        if free:
            first, last, minutes, at = free
            return format_free(_events(config, first, last), first, last, minutes, at, today), True
        day = diya_when.upcoming_day(question, today)
        first, last = (day, day) if day else (today, today + timedelta(days=SEARCH_DAYS))
        wanted = " ".join(topic.lower().split())
        events = [e for e in _events(config, first, last) if wanted in " ".join(str(e.get("summary") or "").lower().split()) and e.get("status") != "cancelled"]
        if not events:
            return (f"I found nothing on your calendar matching '{printable(topic, 60)}' in the next {SEARCH_DAYS if not day else 1} days.", True) if _CALENDAR_WORD.search(question) else None
        return format_found(events, topic, today, SEARCH_DAYS if not day else 1), True
    except client.GoogleError as exc:
        return str(exc), False
    except Exception as exc:  # noqa: BLE001 -- a calendar that cannot be read is said, not a failed chat
        return f"I could not read the calendar ({type(exc).__name__}).", False
