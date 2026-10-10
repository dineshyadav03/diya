"""Reads the words for a repeating time ("every Monday at 9am") as a rule, and works out when it next falls.

docs/SCHEDULE_DESIGN.md, D2 and unit R1. Like `diya_time`, this is plain code: the model passes the person's words on and
this module reads them or refuses, because a rule the model made up would fire for ever at a time nobody chose. A refusal
carries a reason that can be relayed to the person.

    parse_repeat("every Monday at 9am", now)  ->  Repeat(kind="weekly", days=(0,), at=09:00)
    parse_repeat("every weekday", now)         ->  ... at 09:00, assumed=("no time was given, so 09:00",)
    parse_repeat("every hour", now)            ->  raises NotUnderstood

What it reads: every day / daily / every morning (09:00) / every evening (18:00); every weekday; every <weekday> (and
<weekday> ...) / weekly on <weekday>; every month on the 15th / monthly on the 15th / every 15th; every N days or weeks,
every other day or week. Always at a time of day: none given is 09:00, and it says so in `assumed`. What it will not guess:
anything more often than once a day, an end or a count ("until June", "for 5 weeks", "10 times"), "every second Tuesday" and
"the last Friday", "every week" with no day, "every month" with no date, "every weekend", and yearly (a date with no year
needs its own reading). A day-of-month of 29-31 means the last day of a shorter month.

All arithmetic is in the machine's local wall-clock time, as in diya_time; converting to UTC is the caller's job
(diya_time.iso_of_local), so daylight saving is the operating system's. Importing this module has no side effects and
reads no clock: `now` is a parameter.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import diya_time
from diya_time import DAY_NAMES, DEFAULT_HOUR, MONTH_NAMES, WEEKDAYS, NotUnderstood

MAX_CHARS = 100
MAX_EVERY_DAYS = 365  # "every N days": a longer gap is a one-off reminder
KINDS = ("daily", "weekdays", "weekly", "monthly", "interval")

_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_COUNT_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_COUNT = "|".join(["[0-9]{1,3}", "other", *_COUNT_WORDS])

# Said before anything is read, on the person's own words, so that a refusal can name what was wrong.
_AN_END = re.compile(
    r"\b(?:until|till)\b|\bfor\s+(?:the\s+next\s+)?(?:[0-9]+|an?|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:times?|days?|weeks?|months?|years?)\b|\b[0-9]+\s+times\b"
)
_TOO_OFTEN = re.compile(r"\bhourly\b|\bevery\s+(?:[0-9]+\s+|other\s+)?(?:minutes?|mins?|hours?|hrs?)\b|\bevery\s+hour\b")
_YEARLY = re.compile(r"\b(?:yearly|annually|annual)\b|\b(?:every|each)\s+year\b")
_NTH_WEEKDAY = re.compile(rf"\b(?:first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)\s+(?:{_WD})\b")
_LAST_DAY = re.compile(r"\blast\s+day\b")
_WEEKEND = re.compile(r"\bweekends?\b")

# Read after the filler words are gone ("on", "at", "the", "of" ...), at the start of what is left.
_DAILY = re.compile(r"(?:(?:every|each)\s+(?:single\s+)?day|daily)\b")
_PART_OF_DAY = re.compile(r"(?:every|each)\s+(?=(?:morning|afternoon|evening)\b)")
_WEEKDAYS = re.compile(r"(?:(?:every|each)\s+(?:weekday|workday)s?|weekdays)\b")
_WEEKLY = re.compile(rf"(?:(?:every|each)(?:\s+week)?|weekly)\s+(?P<days>(?:{_WD})(?:\s+(?:and\s+)?(?:{_WD}))*)\b")
_MONTHLY = re.compile(
    r"(?:(?:every|each)\s+month|monthly)\s+(?P<dom>[0-9]{1,2})(?:st|nd|rd|th)\b"
    r"|(?:every|each)\s+(?P<dom2>[0-9]{1,2})(?:st|nd|rd|th)(?:\s+day)?(?:\s+month)?\b"
    r"|(?P<dom3>[0-9]{1,2})(?:st|nd|rd|th)\s+(?:every|each)\s+month\b"  # "on the 1st of every month"
)
_NIGHT = re.compile(r"(?:every|each)\s+night\b")
_INTERVAL = re.compile(rf"(?:every|each)\s+(?P<n>{_COUNT})\s+(?P<unit>days?|weeks?)\b")
_BARE_WEEK = re.compile(r"(?:(?:every|each)\s+week|weekly)\b")
_BARE_MONTH = re.compile(r"(?:(?:every|each)\s+month|monthly)\b")


@dataclass(frozen=True)
class Repeat:
    """A rule for when something falls. `at` is the time of day. `days` (weekly) are weekday numbers, Monday = 0;
    `day_of_month` (monthly); `every` and `anchor` (interval): every `every` days counting from the date `anchor`.
    `assumed` is what was filled in that the person did not say, in words; it is not part of the rule."""

    kind: str
    at: time
    days: tuple = ()
    day_of_month: int = 0
    every: int = 0
    anchor: date | None = None
    assumed: tuple = field(default=(), compare=False)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}, got {self.kind!r}")
        if not isinstance(self.at, time) or self.at.second or self.at.microsecond or self.at.tzinfo is not None:
            raise ValueError("at must be a time of day with no seconds and no time zone")
        if self.kind == "weekly" and not (self.days and list(self.days) == sorted(set(self.days)) and all(isinstance(d, int) and 0 <= d <= 6 for d in self.days)):
            raise ValueError("a weekly rule needs its weekdays, each 0-6, in order, once")
        if self.kind == "monthly" and not (isinstance(self.day_of_month, int) and 1 <= self.day_of_month <= 31):
            raise ValueError("a monthly rule needs a day of the month, 1-31")
        if self.kind == "interval" and not (isinstance(self.every, int) and 2 <= self.every <= MAX_EVERY_DAYS and isinstance(self.anchor, date)):
            raise ValueError(f"an interval rule needs 2-{MAX_EVERY_DAYS} days and the date it counts from")

    # ---- the rule as text: what is stored ----
    def canonical(self):
        """The rule as one line of text, from_canonical's input: daily@09:00, weekdays@09:00, weekly:0,3@09:00, monthly:15@09:00,
        every:3@09:00#2026-10-12."""
        clock = f"{self.at:%H:%M}"
        if self.kind == "weekly":
            return f"weekly:{','.join(str(d) for d in self.days)}@{clock}"
        if self.kind == "monthly":
            return f"monthly:{self.day_of_month}@{clock}"
        if self.kind == "interval":
            return f"every:{self.every}@{clock}#{self.anchor.isoformat()}"
        return f"{self.kind}@{clock}"

    @classmethod
    def from_canonical(cls, text):
        """The rule `canonical` wrote, or ValueError: whatever is read back from the database is checked, not trusted."""
        m = _CANON.fullmatch(text) if isinstance(text, str) else None
        if m is None:
            raise ValueError(f"not a repeat rule: {text!r}")
        at = time(int(m["h"]), int(m["mi"]))
        kind, arg = m["kind"], m["arg"]
        try:
            if kind in ("daily", "weekdays"):
                if arg is not None or m["anchor"] is not None:
                    raise ValueError("this rule takes no argument")
                return cls(kind, at)
            if kind == "weekly":
                days = tuple(int(d) for d in arg.split(",")) if arg else ()
                return cls("weekly", at, days=days)
            if kind == "monthly":
                return cls("monthly", at, day_of_month=int(arg or 0))
            return cls("interval", at, every=int(arg or 0), anchor=date.fromisoformat(m["anchor"] or ""))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"not a repeat rule: {text!r} ({exc})") from None

    # ---- the rule in words, for the person ----
    def describe(self):
        clock = f"{self.at:%H:%M}"
        if self.kind == "daily":
            return f"Every day at {clock}"
        if self.kind == "weekdays":
            return f"Every weekday at {clock}"
        if self.kind == "weekly":
            names = [DAY_NAMES[d] for d in self.days]
            return f"Every {', '.join(names[:-1]) + ' and ' + names[-1] if len(names) > 1 else names[0]} at {clock}"
        if self.kind == "monthly":
            shorter = " (the last day of a shorter month)" if self.day_of_month > 28 else ""
            return f"Every month on the {_ordinal(self.day_of_month)}{shorter} at {clock}"
        if self.every % 7 == 0:
            span = f"{self.every // 7} weeks" if self.every > 7 else "week"
        else:
            span = f"{self.every} days"
        a = self.anchor
        return f"Every {span} at {clock}, counting from {a.day} {MONTH_NAMES[a.month - 1]} {a.year}"

    # ---- the arithmetic ----
    def next_after(self, local):
        """The first moment this rule falls strictly after `local` (a naive local datetime)."""
        if not isinstance(local, datetime) or local.tzinfo is not None:
            raise TypeError("local must be a naive local datetime")
        local = local.replace(second=0, microsecond=0)
        today = local.date()

        def at_on(day):
            return datetime.combine(day, self.at)

        if self.kind == "interval":
            first = at_on(self.anchor)
            if first > local:
                return first
            gap = (local - first) // timedelta(days=self.every)
            candidate = first + timedelta(days=self.every * gap)
            while candidate <= local:
                candidate += timedelta(days=self.every)
            return candidate
        if self.kind == "monthly":
            year, month = today.year, today.month
            for _ in range(14):
                day = min(self.day_of_month, calendar.monthrange(year, month)[1])
                candidate = at_on(date(year, month, day))
                if candidate > local:
                    return candidate
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            raise AssertionError("a monthly rule always falls within 14 months")  # pragma: no cover
        for ahead in range(8):
            day = today + timedelta(days=ahead)
            weekday = day.weekday()
            if self.kind == "weekdays" and weekday > 4:
                continue
            if self.kind == "weekly" and weekday not in self.days:
                continue
            if at_on(day) > local:
                return at_on(day)
        raise AssertionError("a daily, weekday or weekly rule always falls within 8 days")  # pragma: no cover

    def before(self, local):
        """The last moment this rule fell at or before `local`, or None if it has not fallen yet (an interval before its
        first date). Used to find the most recent occurrence that is due."""
        if not isinstance(local, datetime) or local.tzinfo is not None:
            raise TypeError("local must be a naive local datetime")
        local = local.replace(second=0, microsecond=0)
        if self.kind == "interval" and datetime.combine(self.anchor, self.at) > local:
            return None
        # start one gap back (the longest gap a rule has is `every` days, or a month) and walk forward to the last fall
        probe = local - timedelta(days=self.every + 1 if self.kind == "interval" else 62)
        previous = None
        while True:
            fall = self.next_after(probe)
            if fall > local:
                return previous
            previous, probe = fall, fall


_CANON = re.compile(
    r"(?P<kind>daily|weekdays|weekly|monthly|every)(?::(?P<arg>[0-9]+(?:,[0-9]+)*))?@(?P<h>[0-9]{2}):(?P<mi>[0-9]{2})(?:#(?P<anchor>[0-9]{4}-[0-9]{2}-[0-9]{2}))?"
)


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _refuse(text):
    """Named refusals for what the person is likely to say that this will not read, checked before anything is read."""
    s = " ".join(text.lower().replace("’", "'").split())
    if _AN_END.search(s):
        raise NotUnderstood("an end or a count ('until', 'for 5 weeks', '10 times') cannot be set: it repeats until you stop it")
    if _TOO_OFTEN.search(s):
        raise NotUnderstood("more often than once a day is not supported; give a time of day and 'every day'")
    if _YEARLY.search(s):
        raise NotUnderstood("'every year' is not supported yet; set a one-off reminder for the date")
    if _NTH_WEEKDAY.search(s):
        raise NotUnderstood("'every second Tuesday' and 'the last Friday' are not supported; name the weekday or give 'every 2 weeks'")
    if _LAST_DAY.search(s):
        raise NotUnderstood("'the last day of the month' is not supported; give a day, and 29-31 means the last day of a shorter month")
    if _WEEKEND.search(s):
        raise NotUnderstood("'weekend' could mean Saturday, Sunday or both; name the day")


def parse_repeat(text, now=None):
    """Read `text` as a repeat rule, or raise NotUnderstood. `now` (a naive local datetime; the real clock if omitted) is
    used only to pick the date an "every N days" rule counts from: the first time it falls."""
    if not isinstance(text, str):
        raise NotUnderstood("no repeat was given")
    if len(" ".join(text.split())) > MAX_CHARS:
        raise NotUnderstood("that is too long to be a repeat")
    now = (datetime.now() if now is None else now).replace(second=0, microsecond=0)
    if now.tzinfo is not None:
        raise TypeError("now must be a naive local datetime")
    _refuse(text)
    s = diya_time._normalise(text)
    if not s:
        raise NotUnderstood("no repeat was given")
    if not re.match(r"(?:every|each|daily|weekly|monthly|weekdays)\b|[0-9]{1,2}(?:st|nd|rd|th)\s+(?:every|each)\s+month\b", s):
        raise NotUnderstood(f"could not read {' '.join(text.split())[:60]!r} as a repeat; say 'every ...' (for example 'every Monday at 9am')")
    assumed = []

    def clock(rest, part=None):
        """The time of day in `rest` (what is left of the words), with 09:00 if there is none."""
        if part is not None:
            rest = f"{part} {rest}".strip()
        if not rest.strip():
            assumed.append(f"no time was given, so {DEFAULT_HOUR:02d}:00")
            return time(DEFAULT_HOUR)
        found = diya_time._time_of_day(rest, assumed)
        if found is None:
            raise NotUnderstood(f"could not read {rest.strip()!r} as a time of day")
        return found

    m = _PART_OF_DAY.match(s)
    if m:  # "every morning": a daily rule whose time is the part of the day
        part = re.match(r"morning|afternoon|evening", s[m.end():]).group(0)
        rest = s[m.end() + len(part):]
        return Repeat("daily", clock(rest, part), assumed=tuple(assumed))
    m = _NIGHT.match(s)
    if m:  # "every night at 10pm": night has no hour of its own, so a time is required
        if not s[m.end():].strip():
            raise NotUnderstood("'every night' needs a time: say 'every night at 10pm', for example")
        return Repeat("daily", clock(s[m.end():]), assumed=tuple(assumed))
    m = _DAILY.match(s)
    if m:
        return Repeat("daily", clock(s[m.end():]), assumed=tuple(assumed))
    m = _WEEKDAYS.match(s)
    if m:
        return Repeat("weekdays", clock(s[m.end():]), assumed=tuple(assumed))
    m = _WEEKLY.match(s)
    if m:
        days = tuple(sorted({WEEKDAYS[w] for w in re.findall(_WD, m.group("days"))}))
        return Repeat("weekly", clock(s[m.end():]), days=days, assumed=tuple(assumed))
    m = _MONTHLY.match(s)
    if m:
        dom = int(m.group("dom") or m.group("dom2") or m.group("dom3"))
        if not 1 <= dom <= 31:
            raise NotUnderstood(f"the {_ordinal(dom)} is not a day of the month")
        at = clock(s[m.end():])
        if dom > 28:
            assumed.append(f"the {_ordinal(dom)} means the last day of a month that is shorter")
        return Repeat("monthly", at, day_of_month=dom, assumed=tuple(assumed))
    m = _INTERVAL.match(s)
    if m:
        word = m.group("n")
        n = 2 if word == "other" else _COUNT_WORDS.get(word) or int(word)
        every = n * (7 if m.group("unit").startswith("week") else 1)
        at = clock(s[m.end():])
        if every == 1:
            return Repeat("daily", at, assumed=tuple(assumed))
        if not 2 <= every <= MAX_EVERY_DAYS:
            raise NotUnderstood(f"every {n} {m.group('unit')} is not between 2 and {MAX_EVERY_DAYS} days; set a one-off reminder")
        first = datetime.combine(now.date(), at)
        anchor = now.date() if first > now else now.date() + timedelta(days=1)
        return Repeat("interval", at, every=every, anchor=anchor, assumed=tuple(assumed))
    if _BARE_WEEK.match(s):
        raise NotUnderstood("'every week' needs a day: say 'every Monday', for example")
    if _BARE_MONTH.match(s):
        raise NotUnderstood("'every month' needs a date: say 'every month on the 15th', for example")
    raise NotUnderstood(f"could not read {' '.join(text.split())[:60]!r} as a repeat; try 'every day', 'every Monday', 'every month on the 15th' or 'every 2 weeks'")


MAX_SCAN_CHARS = 600  # how much of a message is searched for a repeat
MAX_RUN_WORDS = 12  # the longest run of words tried as one repeat
_KEY_WORD = re.compile(r"\b(?:every|each|daily|weekly|monthly|weekdays)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Found:
    """A repeat found in a person's message: their words for it as they wrote them, the rule those read as, and where the words
    sit in the message (`text[start:end] == words`)."""

    words: str
    rule: Repeat
    start: int
    end: int


def _longest_run(text, spans, first, now):
    """(Found, index of its last word) for the longest run of words starting at word `first` that reads as a repeat, or None."""
    for last in range(min(first + MAX_RUN_WORDS, len(spans)) - 1, first - 1, -1):
        start = spans[first][0]
        words = text[start:spans[last][1]].rstrip(".,;:!?")
        if not _KEY_WORD.search(words):
            continue
        try:
            rule = parse_repeat(words, now)
        except NotUnderstood:
            continue
        # the reader skips filler words ("about", "of", "at"), so a run can end in some that belong to what follows, not to the repeat
        while last > first and text[spans[last][0]:spans[last][1]].lower().strip(".,;:!?'\"") in diya_time._FILLER:
            last -= 1
        words = text[start:spans[last][1]].rstrip(".,;:!?")
        return Found(words, rule, start, start + len(words)), last
    return None


def find_repeat(text, now=None):
    """The repeat a person said somewhere in `text`: where the first run of their words that reads as a repeat starts, taking the
    longest run from there ("every day at 8am" out of "remind me every day at 8am to take my pills"), or None.

    None as well when the message says more than this will read, because the part that reads would silently drop the rest: "until
    June", "every hour", "every second Tuesday", "every weekend" (the refusals of `parse_repeat`, checked on the whole message), and
    a second repeat after the first (it will not guess between them)."""
    if not isinstance(text, str):
        return None
    text = text[:MAX_SCAN_CHARS]
    try:
        _refuse(text)
    except NotUnderstood:
        return None
    spans = [m.span() for m in re.finditer(r"\S+", text)]
    for first in range(len(spans)):
        found = _longest_run(text, spans, first, now)
        if found is None:
            continue
        result, last = found
        if any(_longest_run(text, spans, later, now) for later in range(last + 1, len(spans))):
            return None
        return result
    return None
