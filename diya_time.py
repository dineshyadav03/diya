"""Reads the words a person uses for a moment ("Friday 5pm", "in 2 hours") as a real time, in plain code.

docs/PROACTIVITY_DESIGN.md, D2 and unit P1. A reminder can only fire if something can say when it is due, and
the model cannot: it is never told the date, and a 3B model is unreliable at date arithmetic. So the model
passes the person's words on and this module reads them, or refuses. A refusal is the safe answer: it is relayed
to the person ("I could not tell when that is"), where a wrong guess would fire at the wrong time.

    parse_when("Friday 5pm", now)  ->  When(local=2026-09-25 17:00, utc=..., assumed=())
    parse_when("tomorrow", now)    ->  ... at 09:00, assumed=("no time was given, so 09:00",)
    parse_when("soonish", now)     ->  raises NotUnderstood

What it reads: today, tonight, tomorrow, the day after tomorrow, weekday names, "in N minutes / hours / days /
weeks", dates written with a month name ("26 Sep", "September 26th 2026") or as 2026-09-26, and a time as 5pm,
5:30pm, 17:30, noon, or morning / afternoon / evening. What it will not guess: a bare "at 5" (morning or
evening?), "3/4" (March 4th or April 3rd?), "next Friday" (which one?), midnight (which side of the date?),
"next week", "later", anything it cannot account for word by word. A day with no time is 09:00, and it says so
in `assumed`; the caller shows that to the person.

All arithmetic is in the machine's own local wall-clock time; only at the end is it converted to UTC, with the
operating system's rules for that date (so daylight saving is the OS's, and a time that does not exist on the day
the clocks jump is whatever the OS makes of it). Importing this module has no side effects and reads no clock:
`now` is a parameter, so every result here is reproducible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

MAX_CHARS = 100  # a time is a few words; anything longer is not one
DEFAULT_HOUR = 9  # a day with no time
PART_OF_DAY = {"morning": 9, "afternoon": 15, "evening": 18}
TONIGHT_HOUR = 20
MAX_YEARS = 5  # further than this is a typo, not a plan

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_FILLER = {"on", "at", "by", "for", "the", "this", "of", "around", "about"}
_WEEKDAY = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))

_RELATIVE = re.compile(
    r"in (?:(?P<n>[0-9]{1,4})|(?P<word>half an|an|a)) ?(?P<unit>minutes?|mins?|hours?|hrs?|h|days?|weeks?)(?: (?P<rest>.+))?"
)
_ISO = re.compile(r"\b(?P<y>[0-9]{4})-(?P<mo>[0-9]{2})-(?P<d>[0-9]{2})(?:t(?P<h>[0-9]{2}):(?P<mi>[0-9]{2}))?\b")
_DAY_MONTH = re.compile(rf"\b(?P<d>[0-9]{{1,2}})(?:st|nd|rd|th)? (?P<m>{_MONTH})(?: (?P<y>20[0-9]{{2}}))?\b")
_MONTH_DAY = re.compile(rf"\b(?P<m>{_MONTH}) (?P<d>[0-9]{{1,2}})(?:st|nd|rd|th)?(?: (?P<y>20[0-9]{{2}}))?\b")
_SLASH = re.compile(r"\b[0-9]{1,2}/[0-9]{1,2}(?:/[0-9]{2,4})?\b")
_NEXT_WEEKDAY = re.compile(rf"\bnext (?:{_WEEKDAY})\b")
_DAY_WORD = re.compile(rf"\b(?P<w>day after tomorrow|tomorrow|today|tonight|yesterday|{_WEEKDAY})\b")
_CLOCK = re.compile(r"\b(?P<h>[0-9]{1,2}):(?P<mi>[0-9]{2}) ?(?P<ap>am|pm)?\b")
_HOUR_AP = re.compile(r"\b(?P<h>[0-9]{1,2}) ?(?P<ap>am|pm)\b")
_NOON = re.compile(r"\bnoon\b")
_MIDNIGHT = re.compile(r"\bmidnight\b")
_PART = re.compile(r"\b(?P<p>morning|afternoon|evening)\b")
_IN_PART = re.compile(r"\bin (?=(?:morning|afternoon|evening)\b)")


class NotUnderstood(ValueError):
    """The words could not be read as a time. `reason` says why, in words that can be relayed to the person."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class When:
    local: datetime  # the wall-clock time it was read as (no time zone)
    utc: datetime  # the same moment in UTC (aware)
    words: str  # what was asked, as given
    assumed: tuple  # what was filled in that the person did not say, in words

    def iso(self):
        """The moment as text, in UTC: what is stored."""
        return self.utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    def describe(self):
        """The moment in words, for the person: 'Friday 25 Sep 2026, 17:00'."""
        l = self.local
        return f"{DAY_NAMES[l.weekday()]} {l.day} {MONTH_NAMES[l.month - 1]} {l.year}, {l:%H:%M}"


def _local_to_utc(naive):
    return naive.astimezone(timezone.utc)  # a naive datetime is taken as the machine's local time, by the OS's rules


def _take(pattern, s, what):
    """Find `pattern` in `s` at most once; return (match or None, `s` with it cut out)."""
    found = list(pattern.finditer(s))
    if len(found) > 1:
        raise NotUnderstood(f"more than one {what} was given")
    if not found:
        return None, s
    m = found[0]
    return m, f"{s[:m.start()]} {s[m.end():]}"


def _normalise(text):
    s = text.lower().replace("’", "'")
    s = re.sub(r"\ba\.m\.?", "am", s)
    s = re.sub(r"\bp\.m\.?", "pm", s)
    s = s.replace("o'clock", " ")
    s = re.sub(r"[,;.!?()\"']+", " ", s)
    return " ".join(word for word in s.split() if word not in _FILLER)


def _hour(h, ap, minute=0):
    """The 24-hour hour for `h` with an optional am/pm, or NotUnderstood."""
    if ap:
        if not 1 <= h <= 12:
            raise NotUnderstood(f"{h}{ap} is not a time")
        h = h % 12 + (12 if ap == "pm" else 0)
    elif h > 23:
        raise NotUnderstood(f"{h}:{minute:02d} is not a time")
    if minute > 59:
        raise NotUnderstood(f"{h}:{minute:02d} is not a time")
    return h


def parse_when(text, now=None, to_utc=None):
    """Read `text` as a moment after `now` (a naive local datetime; the real clock if omitted).

    Returns a When, or raises NotUnderstood. `to_utc` converts a naive local datetime to an aware UTC one
    (the operating system's rules if omitted); tests pass their own."""
    if not isinstance(text, str):
        raise NotUnderstood("no time was given")
    if len(" ".join(text.split())) > MAX_CHARS:
        raise NotUnderstood("that is too long to be a time")
    now = (datetime.now() if now is None else now).replace(second=0, microsecond=0)
    if now.tzinfo is not None:
        raise TypeError("now must be a naive local datetime")
    words = " ".join(text.split())
    s = _normalise(text)
    if not s:
        raise NotUnderstood("no time was given")
    assumed = []
    limit = now + timedelta(days=366 * MAX_YEARS)

    relative = _RELATIVE.fullmatch(s)
    if relative:
        local = _relative(relative, now, assumed)
    else:
        local = _absolute(s, now, assumed)

    if local <= now:
        raise NotUnderstood("that time has already passed")
    if local > limit:
        raise NotUnderstood(f"that is more than {MAX_YEARS} years away, which is probably a typo")
    try:
        utc = (to_utc or _local_to_utc)(local)
    except (OverflowError, OSError, ValueError):
        raise NotUnderstood("that time cannot be worked out on this machine")
    return When(local=local, utc=utc, words=words, assumed=tuple(assumed))


def _relative(m, now, assumed):
    unit = m.group("unit")
    kind = "minutes" if unit.startswith("min") else "hours" if unit in ("h", "hr", "hrs") or unit.startswith("hour") else "days" if unit.startswith("day") else "weeks"
    if m.group("word") == "half an":
        if kind != "hours":
            raise NotUnderstood("'half an' only works with hours")
        n, kind = 30, "minutes"
    else:
        n = 1 if m.group("word") else int(m.group("n"))
    if n == 0:
        raise NotUnderstood("that is now, not a time to be reminded")
    rest = m.group("rest")
    if kind == "minutes":
        return _with_rest(now + timedelta(minutes=n), rest, "minutes")
    if kind == "hours":
        return _with_rest(now + timedelta(hours=n), rest, "hours")
    days = n * (7 if kind == "weeks" else 1)
    day = now.date() + timedelta(days=days)
    if rest is None:
        assumed.append(f"no time was given, so {DEFAULT_HOUR:02d}:00")
        return datetime.combine(day, time(DEFAULT_HOUR))
    clock = _time_of_day(rest, assumed)
    if clock is None:
        raise NotUnderstood(f"could not read {rest!r} as a time of day")
    return datetime.combine(day, clock)


def _with_rest(local, rest, unit):
    if rest is not None:
        raise NotUnderstood(f"a time of day cannot be added to 'in N {unit}'; give one or the other")
    return local


def _time_of_day(s, assumed):
    """A time of day from what is left of the words (which must be only a time), or None if there is none."""
    clock, s = _take(_CLOCK, s, "time")
    hour_ap = None
    if clock is None:
        hour_ap, s = _take(_HOUR_AP, s, "time")
    noon, s = _take(_NOON, s, "time")
    if _MIDNIGHT.search(s):
        raise NotUnderstood("'midnight' could mean either side of the date; say 12am on a date, or 11:59pm")
    part, s = _take(_PART, s, "time")
    given = [x for x in (clock, hour_ap, noon) if x is not None]
    if len(given) > 1:
        raise NotUnderstood("more than one time was given")
    if s.strip():
        if re.fullmatch(r"[0-9]{1,2}", s.strip()):
            raise NotUnderstood(f"'{s.strip()}' could be morning or evening; add am or pm, or use 24-hour time like 17:00")
        raise NotUnderstood(f"could not read {s.strip()!r} as a time")
    if clock is not None:
        return time(_hour(int(clock["h"]), clock["ap"], int(clock["mi"])), int(clock["mi"]))
    if hour_ap is not None:
        return time(_hour(int(hour_ap["h"]), hour_ap["ap"]))
    if noon is not None:
        return time(12)
    if part is not None:
        hour = PART_OF_DAY[part["p"]]
        assumed.append(f"{part['p']} is {hour:02d}:00")
        return time(hour)
    return None


def _absolute(s, now, assumed):
    s = _IN_PART.sub("", s)  # "in the morning" (the filler word "the" is already gone)
    if _NEXT_WEEKDAY.search(s):
        raise NotUnderstood("'next Friday' can mean two different days; say 'Friday' or give a date")
    if _SLASH.search(s):
        raise NotUnderstood("a date like 3/4 can be March 4th or April 3rd; write the month as a word, or use 2026-04-03")

    day, on_date = None, None  # `day` a resolved date; `on_date` says how it was given
    iso, s = _take(_ISO, s, "date")
    dm, s = _take(_DAY_MONTH, s, "date")
    md, s = _take(_MONTH_DAY, s, "date")
    dated = [x for x in (iso, dm, md) if x is not None]
    if len(dated) > 1:
        raise NotUnderstood("more than one date was given")
    word, s = _take(_DAY_WORD, s, "day")
    if dated and word is not None:
        raise NotUnderstood("both a date and a day of the week were given")

    clock = None
    if iso is not None and iso["h"] is not None:
        hour, minute = int(iso["h"]), int(iso["mi"])
        if hour > 23 or minute > 59:
            raise NotUnderstood(f"{iso['h']}:{iso['mi']} is not a time")
        clock = time(hour, minute)
        if s.strip():
            raise NotUnderstood(f"could not read {s.strip()!r} as a time")
    else:
        clock = _time_of_day(s, assumed)
    tonight = word is not None and word["w"] == "tonight"

    if not dated and word is None and clock is None:
        raise NotUnderstood("could not read that as a time; give a day and a time, like 'Friday 5pm' or 'in 2 hours'")

    if dated:
        day = _calendar_day(iso, dm, md, clock or time(DEFAULT_HOUR), now, assumed)
    elif word is not None:
        w = word["w"]
        if w == "yesterday":
            raise NotUnderstood("that time has already passed")
        if w in ("today", "tonight"):
            day = now.date()
        elif w == "tomorrow":
            day = now.date() + timedelta(days=1)
        elif w == "day after tomorrow":
            day = now.date() + timedelta(days=2)
    if tonight and clock is None:
        clock = time(TONIGHT_HOUR)
        assumed.append(f"tonight is {TONIGHT_HOUR:02d}:00")

    if clock is None:
        clock = time(DEFAULT_HOUR)
        assumed.append(f"no time was given, so {DEFAULT_HOUR:02d}:00")

    if word is not None and word["w"] in WEEKDAYS:
        target = WEEKDAYS[word["w"]]
        ahead = (target - now.date().weekday()) % 7
        day = now.date() + timedelta(days=ahead)
        if datetime.combine(day, clock) <= now:
            day += timedelta(days=7)
            assumed.append("that time has passed this week, so it is next week")
    if day is None:  # a time and no day
        day = now.date()
        if datetime.combine(day, clock) <= now:
            day += timedelta(days=1)
            assumed.append("that time has passed today, so it is tomorrow")
        else:
            assumed.append("no day was given, so today")
    return datetime.combine(day, clock)


def _calendar_day(iso, dm, md, clock, now, assumed):
    """The date named by an ISO date or a month-name date. With no year, this year if that is still ahead, else next."""
    try:
        if iso is not None:
            return date(int(iso["y"]), int(iso["mo"]), int(iso["d"]))
        m = dm or md
        month, dom = MONTHS[m["m"]], int(m["d"])
        if m["y"] is not None:
            return date(int(m["y"]), month, dom)
        this_year = date(now.year, month, dom)
        if datetime.combine(this_year, clock) > now:
            return this_year
        assumed.append(f"no year was given, so {now.year + 1}")
        return date(now.year + 1, month, dom)
    except ValueError:
        raise NotUnderstood("that is not a real date")
