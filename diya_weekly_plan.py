"""A weekly plan checked against the calendar before anything is proposed (DIYA-141; docs/GOOGLE_CHANGES.md), added 2026-10-27.

"Plan my week: study physics 3 times for 1 hour, gym 2 times for 45 minutes". Code reads the calendar for the days, finds the gaps between the events there (the same gaps as "when am I free", between 9:00 and 18:00, never in
the past), and puts each session in the earliest gap that is free, spreading the sessions of one thing over different days first and never on top of an event or another session. So a conflict is found BEFORE anything is
made: a session that fits no gap is said not to fit, and nothing is proposed for it. What fits is shown as a plan, and the first few sessions (one message may lead to at most 3 actions) are PROPOSED as events for the owner
to approve one by one; the rest are asked for again. The event kind is the existing "add an event to my calendar": each card carries the title, the day and the time, and nobody is invited. Nothing is made without the approval.

Not built: tasks in the same plan, moving an existing event, and a plan longer than a week. Importing this module has no side effects.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

import diya_calendar_find as cf
import diya_when

MAX_SESSIONS = 14
MAX_LENGTH = 4 * 60
_LEAD = r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*"
_PLAN = re.compile(_LEAD + r"plan\s+(?:out\s+)?(?:my\s+|the\s+)?(?P<when>this\s+week|next\s+week|week)?\s*(?:for\s+me\s*)?[:,-]?\s*(?P<items>.+)$", re.IGNORECASE)
_ITEM = re.compile(
    r"(?P<what>[A-Za-z][A-Za-z ']{1,40}?)\s+(?P<n>\d{1,2})\s*(?:times|x|sessions)(?:\s+(?:a|per|this|next))?(?:\s+week)?\s*(?:,\s*)?(?:for|of|at)?\s*(?P<len>\d+(?:\.\d+)?)\s*(?P<unit>hours?|hrs?|h|minutes?|mins?|m)\b", re.IGNORECASE)


def request(text, today):
    """{"items": [(what, times, minutes)], "first": day, "last": day, "label": words} for a plain request to plan the week, else None."""
    if not isinstance(text, str) or not text.strip() or len(text) > 300 or "\n" in text.strip():
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    found = _PLAN.search(flat)
    if not found or not re.search(r"\bweek\b", flat, re.IGNORECASE):
        return None
    items = []
    for item in _ITEM.finditer(found.group("items")):
        what = " ".join(re.sub(r"^(?:and|then|also)\s+", "", item.group("what").strip(), flags=re.IGNORECASE).split())
        minutes = float(item.group("len")) * (60 if item.group("unit").lower().startswith("h") else 1)
        times = int(item.group("n"))
        if what and 1 <= times <= 7 and 15 <= minutes <= MAX_LENGTH:
            items.append((what[0].upper() + what[1:], times, int(minutes)))
    if not items or sum(t for _, t, _ in items) > MAX_SESSIONS:
        return None
    if re.search(r"\bnext\s+week\b", flat, re.IGNORECASE):
        first = today + timedelta(days=7 - today.weekday())
        return {"items": items, "first": first, "last": first + timedelta(days=6), "label": "next week"}
    return {"items": items, "first": today, "last": today + timedelta(days=6 - today.weekday()), "label": "the rest of this week"}


def _pseudo(start, minutes):
    """A busy stretch in the shape Google gives, for a session already placed (or for the time already gone today)."""
    return {"start": {"dateTime": start.astimezone().isoformat()}, "end": {"dateTime": (start + timedelta(minutes=minutes)).astimezone().isoformat()}}


def schedule(events, plan, now):
    """([(title, start, minutes)], [what did not fit]) for `plan` given the calendar's `events`: each session in the earliest gap that is free, different days first. `now` is a naive local time; nothing is placed before it."""
    busy = list(events)
    today = now.date()
    if plan["first"] <= today <= plan["last"]:
        busy.append(_pseudo(datetime.combine(today, time.min), int((now - datetime.combine(today, time.min)).total_seconds() // 60) + 1))
    days, placed, missed = [plan["first"] + timedelta(days=n) for n in range((plan["last"] - plan["first"]).days + 1)], [], []
    for title, times, minutes in plan["items"]:
        used = set()
        for number in range(1, times + 1):
            choice = None
            for allow_repeat in (False, True):
                for day in days:
                    if day in used and not allow_repeat:
                        continue
                    gaps = cf.free_slots(busy, day, minutes)
                    if gaps:
                        choice = (day, gaps[0][0])
                        break
                if choice:
                    break
            if choice is None:
                missed.append(f"{title.lower()}, session {number} of {times} ({minutes} minutes): no free gap of that length is left between {cf.WORK_START}:00 and {cf.WORK_END}:00")
                continue
            used.add(choice[0])
            placed.append((title, choice[1], minutes))
            busy.append(_pseudo(choice[1], minutes))
    return sorted(placed, key=lambda s: s[1]), missed


def _length(minutes):
    return f"{minutes // 60} hour{'s' if minutes > 60 else ''}" if minutes % 60 == 0 else f"{minutes} minutes"


def render(plan, placed, missed, today, proposed):
    """The plan as text: what goes where (checked against the calendar), what did not fit, and how many are proposed."""
    lines = [f"Plan for {plan['label']}, placed in the gaps of your calendar between {cf.WORK_START}:00 and {cf.WORK_END}:00:"]
    for title, times, minutes in plan["items"]:
        mine = [s for s in placed if s[0] == title and s[2] == minutes]
        lines.append(f"- {title} ({_length(minutes)}): " + (", ".join(f"{diya_when.DAYS[s[1].weekday()]} {s[1].day} {diya_when.MON[s[1].month - 1]} {s[1]:%H:%M}" for s in mine) if mine else "nothing fits"))
    if missed:
        lines += ["Did not fit:"] + [f"- {m}" for m in missed]
    if placed:
        lines.append(f"{proposed} of the {len(placed)} session(s) are proposed on your calendar for you to approve{'; ask again for the rest' if proposed < len(placed) else ''}. Nobody is invited.")
    return "\n".join(lines)
