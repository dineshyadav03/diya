"""Time words, read against the day they were SAID (docs/TIME_DESIGN.md), added 2026-10-21 from Mem0's article on time in memory.

A fact has two clocks: when the thing happened (event time) and when Diya was told (write time). "I ran my first 10K last weekend" said in June means the weekend of the 14th; read in October against today it
means a different weekend and is wrong for ever. Diya stores the person's own words and the day they were written. This module reads the relative time words in a text against a given day, in code and
without a model, and says what they meant, so that a fact told months later still carries the right dates.

* `find(text, anchor)`: the relative phrases in `text` ("yesterday", "last weekend", "3 weeks ago", "next month", "last Friday") with the days they meant on `anchor`.
* `describe(span)`: those days in words that keep the precision honest ("the weekend of 17-18 Oct 2026", "September 2026", "about Wed 7 Oct 2026"); a month stays a month, a week stays a week.
* `annotate(text, anchor, today)`: the text with each resolved phrase followed by what it meant, when it was said on another day than `today`.
* `window(text, anchor)`: the days a question asks about ("what did I say last week?"), for ranking old messages.
* `ends_on(text, anchor)`: the last day a fact says it lasts to ("until 31 Jan", "through the end of March", "ends on 15 Nov").

What it will NOT resolve, on purpose (a phrase it cannot be sure of is left as written, because a wrong date is worse than a vague one): "next Friday" and "next weekend" (the coming one or the one after?), a bare
"on Friday" (past or future?), "this Friday" when Friday has already passed this week, and a month with no year when it is not obvious ("in March"). Weeks run Monday to Sunday; a weekend is Saturday and Sunday.
Times of day inside a day ("yesterday evening") are kept in the phrase but the span is the day. All dates are the person's own calendar days; turning a stored moment into that day is `local_date`.

Importing this module has no side effects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_COUNT = r"(?P<n>\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_PART = r"(?:\s+(?:morning|afternoon|evening|night))?"
MAX_ANNOTATIONS = 3
RECENT_DAYS = 45  # a date with no year that passed less than this long ago is about the past, not about next year


@dataclass(frozen=True)
class Span:
    phrase: str  # as written
    start: date  # first day it meant
    end: date  # last day it meant
    kind: str  # day, night, weekend, week, month, year, about
    at: int  # where the phrase starts in the text
    to: int  # and ends


def local_date(moment, tz=None):
    """The calendar day, for the person, of a stored moment (an ISO text or a datetime; a moment with no zone is taken as UTC, which is how Diya stores them). `tz` is a tzinfo for the person's zone;
    None is this computer's zone. A late-night message sent from far from UTC is the day it was for the person, not the day it was in UTC."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(tz) if tz is not None else moment.astimezone()).date()


def _monday(day):
    return day - timedelta(days=day.weekday())


def _month_range(year, month):
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return first, last


def _add_months(day, months):
    index = day.year * 12 + (day.month - 1) + months
    return index // 12, index % 12 + 1


def _number(text):
    return int(text) if text.isdigit() else _NUMBERS[text.lower()]


# (pattern, builder(match, anchor) -> (start, end, kind) or None)
def _build():
    p = []

    def add(pattern, builder):
        p.append((re.compile(pattern, re.IGNORECASE), builder))

    add(r"\bday before yesterday\b", lambda m, a: (a - timedelta(days=2), a - timedelta(days=2), "day"))
    add(rf"\byesterday{_PART}\b", lambda m, a: (a - timedelta(days=1), a - timedelta(days=1), "day"))
    add(r"\blast night\b", lambda m, a: (a - timedelta(days=1), a - timedelta(days=1), "night"))
    add(r"\btonight\b", lambda m, a: (a, a, "night"))
    add(r"\btoday\b|\bthis (?:morning|afternoon|evening)\b", lambda m, a: (a, a, "day"))
    add(r"\bday after tomorrow\b", lambda m, a: (a + timedelta(days=2), a + timedelta(days=2), "day"))
    add(rf"\btomorrow{_PART}\b", lambda m, a: (a + timedelta(days=1), a + timedelta(days=1), "day"))

    def weekend(m, a):
        word = m.group(1).lower()
        saturday = a + timedelta(days=(5 - a.weekday()) % 7)  # this coming Saturday (today, on a Saturday)
        if a.weekday() == 6:  # on a Sunday the weekend "this weekend" is the one that began yesterday
            saturday = a - timedelta(days=1)
        if word == "this":
            return saturday, saturday + timedelta(days=1), "weekend"
        if word == "last":
            return saturday - timedelta(days=7), saturday - timedelta(days=6), "weekend"
        return None  # "next weekend": the coming one or the one after? left as written

    add(r"\b(last|this|next) weekend\b", weekend)

    def week(m, a):
        word = m.group(1).lower()
        start = _monday(a) + timedelta(weeks={"last": -1, "this": 0, "next": 1}[word])
        return start, start + timedelta(days=6), "week"

    add(r"\b(last|this|next) week\b", week)

    def month(m, a):
        year, number = _add_months(a, {"last": -1, "this": 0, "next": 1}[m.group(1).lower()])
        return (*_month_range(year, number), "month")

    add(r"\b(last|this|next) month\b", month)
    add(r"\b(last|this|next) year\b", lambda m, a: (date(a.year + {"last": -1, "this": 0, "next": 1}[m.group(1).lower()], 1, 1), date(a.year + {"last": -1, "this": 0, "next": 1}[m.group(1).lower()], 12, 31), "year"))

    def ago(m, a, sign=-1):
        n, unit = _number(m.group("n")), m.group("unit").lower().rstrip("s")
        if unit == "day":
            d = a + timedelta(days=sign * n)
            return d, d, "day"
        if unit == "week":
            d = a + timedelta(weeks=sign * n)
            return d, d, "about"
        if unit == "month":
            year, number = _add_months(a, sign * n)
            return (*_month_range(year, number), "month")
        year = a.year + sign * n
        return date(year, 1, 1), date(year, 12, 31), "year"

    add(rf"\b{_COUNT} (?P<unit>days?|weeks?|months?|years?) ago\b", ago)
    add(rf"\bin {_COUNT} (?P<unit>days?|weeks?|months?|years?)\b", lambda m, a: ago(m, a, +1))

    def weekday(m, a):
        word, name = m.group(1).lower(), m.group(2).lower()
        target = _WEEKDAYS.index(name)
        if word == "last":
            delta = (a.weekday() - target) % 7 or 7  # the most recent one before today
            d = a - timedelta(days=delta)
            return d, d, "day"
        if target >= a.weekday():  # "this Friday": today or the one coming in this week
            d = a + timedelta(days=target - a.weekday())
            return d, d, "day"
        return None  # "this Monday" on a Wednesday: this week's or next week's? left as written

    add(rf"\b(last|this) ({'|'.join(_WEEKDAYS)})\b", weekday)
    return p


_PATTERNS = _build()
_HINT = re.compile(
    r"\b(?:yesterday|tomorrow|today|tonight|last night|day before yesterday|day after tomorrow|(?:last|this|next) (?:weekend|week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"this (?:morning|afternoon|evening)|ago|in (?:\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve) (?:days?|weeks?|months?|years?))\b", re.IGNORECASE)


def has_relative(text):
    """A cheap look: could this text hold a relative time word at all?"""
    return isinstance(text, str) and _HINT.search(text) is not None


def find(text, anchor):
    """The relative time phrases in `text` that can be resolved against the day `anchor`, left to right, none overlapping."""
    if not isinstance(text, str) or not isinstance(anchor, date):
        return []
    anchor = anchor.date() if isinstance(anchor, datetime) else anchor
    found = []
    for pattern, build in _PATTERNS:
        for match in pattern.finditer(text):
            try:
                built = build(match, anchor)
            except (ValueError, KeyError, OverflowError):
                built = None
            if built is None:
                continue
            start, end, kind = built
            found.append(Span(match.group(0), start, end, kind, match.start(), match.end()))
    found.sort(key=lambda s: (s.at, -(s.to - s.at)))
    chosen, edge = [], -1
    for span in found:
        if span.at >= edge:
            chosen.append(span)
            edge = span.to
    return chosen


def _day(d, year=True):
    return f"{DAYS[d.weekday()]} {d.day} {MON[d.month - 1]}" + (f" {d.year}" if year else "")


def describe(span):
    """The days a phrase meant, in words that keep its precision: a day is a day, a weekend or a week says so, a month is only a month."""
    start, end = span.start, span.end
    if span.kind == "day":
        return _day(start)
    if span.kind == "night":
        return f"the night of {_day(start)}"
    if span.kind == "about":
        return f"about {_day(start)}"
    if span.kind in ("weekend", "week"):
        label = "the weekend of" if span.kind == "weekend" else "the week of"
        if start.month == end.month:
            return f"{label} {start.day}-{end.day} {MON[end.month - 1]} {end.year}"
        across = f" {start.year}" if start.year != end.year else ""
        return f"{label} {start.day} {MON[start.month - 1]}{across}-{end.day} {MON[end.month - 1]} {end.year}"
    if span.kind == "month":
        return f"{MONTHS[start.month - 1]} {start.year}"
    return str(start.year)


def annotate(text, anchor, today, limit=MAX_ANNOTATIONS):
    """`text` with what each relative phrase meant added right after it, when the text was written on another day than `today` (a phrase that is still about now needs no help). The text is otherwise
    unchanged. At most `limit` phrases are annotated."""
    if not has_relative(text) or not isinstance(anchor, date):
        return text
    if (anchor.date() if isinstance(anchor, datetime) else anchor) == (today.date() if isinstance(today, datetime) else today):
        return text
    spans = find(text, anchor)[:limit]
    if not spans:
        return text
    out, last = [], 0
    for span in spans:
        out.append(text[last:span.to])
        out.append(f" (that was {describe(span)})")
        last = span.to
    out.append(text[last:])
    return "".join(out)


_GENERIC = frozenset("say said tell told mention mentioned talk talked happen happened write wrote chat chatted discuss discussed message messages conversation anything something everything thing things stuff".split())


def window(question, anchor):
    """(first day, last day) a question asks about ("what did I say last week?"), the union of the time phrases it holds, or None. Used to rank old messages higher, never to drop any."""
    spans = find(question, anchor)
    if not spans:
        return None
    return min(s.start for s in spans), max(s.end for s in spans)


def time_only(question, anchor):
    """Is the question only about WHEN ("what did I say last week?", "anything from yesterday?")? Then the messages from that window answer it, whatever they are about."""
    spans = find(question, anchor)
    if not spans:
        return False
    import diya_checks

    rest = question
    for span in reversed(spans):
        rest = rest[:span.at] + " " + rest[span.to:]
    return not (diya_checks.content_words(rest) - diya_checks.content_words(" ".join(_GENERIC)))  # (compared as stems, the way content_words gives them)


# ---- how long a fact says it lasts -----------------------------------------------------------------------------------------------

_MONTH_ALT = "|".join(sorted([m.lower() for m in MONTHS] + [m.lower() for m in MON] + ["sept"], key=len, reverse=True))
_MONTH_INDEX = {**{m.lower(): i + 1 for i, m in enumerate(MONTHS)}, **{m.lower(): i + 1 for i, m in enumerate(MON)}, "sept": 9}
_END_WORD = r"(?:until|till|through|thru|up to|ends? on|ending on|ends?|expires? on|expires?|due)"
_DM = re.compile(rf"\b{_END_WORD}\s+(?:the\s+)?(?:end of\s+)?(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m1>{_MONTH_ALT})|(?P<m2>{_MONTH_ALT})\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?)(?:,?\s+(?P<y>20\d\d))?\b", re.IGNORECASE)
_END_OF_MONTH = re.compile(rf"\b{_END_WORD}\s+(?:the\s+)?end of\s+(?P<m>{_MONTH_ALT})(?:,?\s+(?P<y>20\d\d))?\b", re.IGNORECASE)
_MONTH_ONLY = re.compile(rf"\b{_END_WORD}\s+(?P<m>{_MONTH_ALT})(?:,?\s+(?P<y>20\d\d))?\b(?!\s+\d)", re.IGNORECASE)
_ISO = re.compile(rf"\b{_END_WORD}\s+(?P<y>20\d\d)-(?P<m>\d\d)-(?P<d>\d\d)\b", re.IGNORECASE)


def ends_on(text, anchor):
    """The last day a fact says it lasts to, if it says so with a date: "until 31 Jan", "through March 15", "ends on 15 Nov", "until the end of March", "until 2026-12-01", "expires 2027". A day with no
    year is its next occurrence on or after `anchor`; a month alone is the last day of that month. None when there is no such date, or when it is already behind `anchor` (a fact that says "until
    2019" is about the past and does not fade)."""
    if not isinstance(text, str) or not isinstance(anchor, date):
        return None
    anchor = anchor.date() if isinstance(anchor, datetime) else anchor

    def month_of(word):
        return _MONTH_INDEX.get(word.lower().rstrip("."))

    candidates = []
    for m in _ISO.finditer(text):
        try:
            candidates.append(date(int(m.group("y")), int(m.group("m")), int(m.group("d"))))
        except ValueError:
            pass
    for m in _DM.finditer(text):
        month, day = month_of(m.group("m1") or m.group("m2")), int(m.group("d1") or m.group("d2"))
        year = int(m.group("y")) if m.group("y") else None
        try:
            if year is None:
                d = date(anchor.year, month, day)
                if d < anchor:
                    d = d if (anchor - d).days <= RECENT_DAYS else date(anchor.year + 1, month, day)  # just passed: about the past; long passed: the next one
            else:
                d = date(year, month, day)
            candidates.append(d)
        except ValueError:
            pass
    for pattern in (_END_OF_MONTH, _MONTH_ONLY):
        for m in pattern.finditer(text):
            month = month_of(m.group("m"))
            if month is None:
                continue
            if m.group("y"):
                year = int(m.group("y"))
            else:
                year = anchor.year
                if (anchor - _month_range(year, month)[1]).days > RECENT_DAYS:
                    year += 1
            candidates.append(_month_range(year, month)[1])
    candidates = [d for d in candidates if d >= anchor]
    return max(candidates) if candidates else None


_ON_DM = re.compile(rf"\b(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m1>{_MONTH_ALT})|(?P<m2>{_MONTH_ALT})\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?)\b(?:,?\s+(?P<y>20\d\d)\b)?", re.IGNORECASE)
_ON_ISO = re.compile(r"\b(?P<y>20\d\d)-(?P<m>\d\d)-(?P<d>\d\d)\b")


def past_day(question, today):
    """The day a question about the PAST points at, for "what did you know on 12 Oct?" and "what did you remember last week?": an ISO date, "12 Oct", "Oct 12th", "12 October 2026", or a relative phrase
    that is wholly behind `today` (yesterday, 3 days ago, last Friday, last week = its last day, last month = its last day). A day with no year is its most recent occurrence on or before `today`. None
    when the question names no such day, or names one that has not come yet."""
    if not isinstance(question, str) or not isinstance(today, date):
        return None
    today = today.date() if isinstance(today, datetime) else today
    found = []
    for m in _ON_ISO.finditer(question):
        try:
            found.append(date(int(m.group("y")), int(m.group("m")), int(m.group("d"))))
        except ValueError:
            pass
    for m in _ON_DM.finditer(question):
        month, day = _MONTH_INDEX.get((m.group("m1") or m.group("m2")).lower().rstrip(".")), int(m.group("d1") or m.group("d2"))
        try:
            if m.group("y"):
                found.append(date(int(m.group("y")), month, day))
                continue
            d = date(today.year, month, day)
            found.append(d if d <= today else date(today.year - 1, month, day))
        except ValueError:
            pass
    for span in find(question, today):
        if span.end < today:
            found.append(span.end)
    found = [d for d in found if d <= today]
    return found[0] if found else None


_WEEKDAY_WORD = re.compile(r"\b(?:on\s+|this\s+|coming\s+)?(?P<w>monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues|tue|wed|thurs|thur|thu|fri|sat|sun)\b", re.IGNORECASE)
_WEEKDAY_INDEX = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}


def upcoming_day(question, today):
    """The day a question about the FUTURE points at, when a calendar is being asked: an ISO date, "28 Oct" or "Oct 28th 2026" (a day with no year is its next occurrence on or after `today`), or a weekday name
    ("on Saturday", "this friday": the first such day on or after `today`). None when there is none, and None for "next Friday", which people mean two ways (the same rule as `find`)."""
    if not isinstance(question, str) or not isinstance(today, date):
        return None
    today = today.date() if isinstance(today, datetime) else today
    if re.search(r"\bnext\s+(?:mon|tue|wed|thu|fri|sat|sun)", question, re.IGNORECASE):
        return None
    match = _ON_ISO.search(question)
    if match:
        try:
            return date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
        except ValueError:
            return None
    match = _ON_DM.search(question)
    if match:
        month, day = _MONTH_INDEX.get((match.group("m1") or match.group("m2")).lower().rstrip(".")), int(match.group("d1") or match.group("d2"))
        try:
            if match.group("y"):
                return date(int(match.group("y")), month, day)
            found = date(today.year, month, day)
            return found if found >= today else date(today.year + 1, month, day)
        except ValueError:
            return None
    match = _WEEKDAY_WORD.search(question)
    if match:
        wanted = _WEEKDAY_INDEX[match.group("w").lower()[:3]]
        return today + timedelta(days=(wanted - today.weekday()) % 7)
    return None


def strip_days(text, today=None):
    """`text` with the days it names (an ISO date, "12 Oct", a relative phrase) taken out, so what is left is the topic."""
    if not isinstance(text, str):
        return ""
    today = today or datetime.now().astimezone().date()
    text = _ON_ISO.sub(" ", text)
    text = _ON_DM.sub(" ", text)
    for span in sorted(find(text, today), key=lambda s: -len(s.phrase)):
        text = re.sub(re.escape(span.phrase), " ", text, count=1, flags=re.IGNORECASE)
    return " ".join(text.split())
