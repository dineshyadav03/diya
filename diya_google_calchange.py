"""Google Calendar beyond adding: change an event, cancel it, invite guests, answer an invitation, and add an event that repeats (DIYA-082, -083, -084; docs/GOOGLE_CHANGES.md), added 2026-10-26.

Two new cards, each with the one Google permission Calendar events already use (`calendar.events`), off until pressed Connect, and each held to its own list of allowed requests in Diya's code:

* **Google Calendar (change events)** (`google_calendar_change`): reschedule, rename or change the length of ONE event of yours, and cancel one. Only an event that is yours (you made it), has no guests, does not repeat and is on your main
  calendar: anything that would tell other people (a guest, an organiser) is not done here.
* **Google Calendar (guests)** (`google_calendar_guests`): invite typed addresses to one event of yours, and accept, decline or say maybe to an invitation. Both TELL other people (Google emails them), so both are risk level 3.

An event that repeats is added with the existing "add events" card (a new kind of the same card): daily, weekly, monthly or yearly, a number of times the person said (2 to 52), in their calendar's own time zone.

The rules that hold for all of them (docs/GOOGLE_CHANGES.md): a proposal the owner approves exactly as shown, never straight away; the event is found NOW by the words the person used (none, or several, refuses it; "the next one" is the one
thing that picks and the card says which); its version (etag) is checked again when it is run and sent as If-Match, so nothing is done to an event that changed in the meantime; the change is read back; an outcome that is not
known is `unknown` and never retried; nothing the model invented (a new name, a time, an address) is used unless it is in the person's own words.

Importing this module has no side effects except naming what each card may ask Google for (diya_google_client.allow).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone

import diya_connectors
import diya_google_cards
import diya_google_client as client
import diya_google_mailwrite as mw
import diya_google_write as gw
import diya_intent
import diya_intent_google as asks
import diya_memory
import diya_time
import diya_when
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

EVENTS = gw.CALENDAR_API
READER, CHANGE, GUESTS, ADDER = "google_calendar", "google_calendar_change", "google_calendar_guests", "google_calendar_edit"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
LABELS = {READER: "Google Calendar", CHANGE: "Google Calendar (change events)", GUESTS: "Google Calendar (guests)", ADDER: "Google Calendar (add events)"}
EID = r"[A-Za-z0-9_-]{5,1024}"
WINDOW_DAYS = 90  # how far ahead an event is looked for
MAX_GUESTS = 5
MAX_ALL_GUESTS = 10
REPEATS = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}
TIMES = (2, 52)
_E = re.escape(EVENTS)

client.allow(READER, "GET", _E)
client.allow(READER, "GET", rf"{_E}/{EID}")
client.allow(ADDER, "GET", _E)  # the calendar's own time zone is read from the list (the list answer names it)
for _card in (CHANGE, GUESTS):
    client.allow(_card, "GET", _E)
    client.allow(_card, "GET", rf"{_E}/{EID}")
    client.allow(_card, "PATCH", rf"{_E}/{EID}")
client.allow(CHANGE, "DELETE", rf"{_E}/{EID}")


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").casefold()).split())


# ---- times as Google gives them ---------------------------------------------------------------------------------------------------------------------

def _utc_iso(google_text):
    """A time with a zone (Google's text) as UTC text like 2026-10-30T11:30:00Z; None for a day with no time or anything unreadable."""
    try:
        moment = datetime.fromisoformat(str(google_text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when_of(event):
    start = (event.get("start") or {})
    iso = _utc_iso(start.get("dateTime"))
    if iso:
        return diya_time.describe_local(diya_time.local_from_iso(iso))
    return str(start.get("date") or "?")[:10] + " (all day)"


def _day_of(event):
    start = event.get("start") or {}
    iso = _utc_iso(start.get("dateTime"))
    if iso:
        return diya_time.local_from_iso(iso).date()
    try:
        return date.fromisoformat(str(start.get("date")))
    except ValueError:
        return None


def _shown(event):
    return f"{diya_memory.printable(event.get('summary') or '(no title)', 60)} ({_when_of(event)})"


def _same_moment(google_text, iso):
    return _utc_iso(google_text) == iso


# ---- finding the one event ---------------------------------------------------------------------------------------------------------------------------

_NEXT = re.compile(r"\b(?:next|upcoming|soonest|first)\b", re.IGNORECASE)


def _words(value, said):
    """`value` (the event's name as the model gave it) if the person said it themselves; else ''."""
    if not isinstance(value, str) or not value.strip() or not diya_intent.said_in(value, said):
        return ""
    return " ".join(re.sub(r"[^\w' &-]", " ", value).split())[:80]


def find_event(config, card, title, said, *, day_from=None):
    """The one event on the main calendar, in the next 90 days, whose name has the words the person used (a read); InvalidArgs, with words, for none or several. A day they named narrows it (read from `day_from`, which
    is the message unless the caller says otherwise: a message that moves an event names the NEW day too, and that is not the day it is on); "the next one" picks the soonest."""
    wanted = _words(title, said)
    if not wanted:
        raise InvalidArgs("say which event, by its name, in the user's own words; I do not choose one")
    now = datetime.now(timezone.utc)
    params = {"timeMin": _stamp(now - timedelta(hours=2)), "timeMax": _stamp(now + timedelta(days=WINDOW_DAYS)), "singleEvents": "true", "orderBy": "startTime", "maxResults": 100}
    try:
        events, _more = client.pages(config, card, LABELS[card], EVENTS, params, "items", max_pages=2)
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    live = [e for e in events if e.get("status") != "cancelled"]
    matches = [e for e in live if _norm(wanted) in _norm(e.get("summary"))]
    matches = [e for e in matches if _norm(e.get("summary")) == _norm(wanted)] or matches
    day = diya_when.upcoming_day(said if day_from is None else day_from, datetime.now().astimezone().date())
    if day is not None:
        matches = [e for e in matches if _day_of(e) == day]
    if not matches:
        raise InvalidArgs(f"there is no event called {diya_memory.printable(wanted, 60)!r} on your calendar in the next {WINDOW_DAYS} days{' on that day' if day else ''}; ask the user which event")
    if len(matches) > 1 and not _NEXT.search(said):
        shown = "; ".join(_shown(e) for e in matches[:5])
        raise InvalidArgs(f"{len(matches)} events match {diya_memory.printable(wanted, 60)!r}: {shown}. Ask the user which one, by its day, and do not choose")
    event = matches[0]
    if not isinstance(event.get("id"), str) or not re.fullmatch(EID, event["id"]):
        raise InvalidArgs("Google gave that event no usable id, so it cannot be changed safely")
    return event


def _guests(event):
    """The addresses invited to an event other than the person themselves."""
    return [a for a in (event.get("attendees") or []) if isinstance(a, dict) and not a.get("self") and isinstance(a.get("email"), str)]


def _repeats(event):
    return bool(event.get("recurringEventId") or event.get("recurrence"))


def _plain_own(event, *, timed=False, guests_ok=False):
    """InvalidArgs, saying why, unless the event is the person's own, on their calendar, is not one of a series, has no guests (unless `guests_ok`) and (if `timed`) has a start time."""
    organizer = event.get("organizer") or {}
    if not organizer.get("self"):
        raise InvalidArgs(f"{_shown(event)} is someone else's event, so it is not changed; you can accept or decline it instead")
    if _repeats(event):
        raise InvalidArgs(f"{_shown(event)} is one of a series that repeats, and changing a series is not something Diya does")
    if _guests(event) and not guests_ok:
        raise InvalidArgs(f"{_shown(event)} has guests, and changing it would tell them; do that in Google Calendar")
    if timed and not _utc_iso((event.get("start") or {}).get("dateTime")):
        raise InvalidArgs(f"{_shown(event)} is an all-day event, and Diya moves only events that have a time")


def _ref(event):
    return {"title": diya_memory.printable(event.get("summary") or "(no title)", 100), "event_id": event["id"], "etag": str(event.get("etag") or "")[:200], "shown": _shown(event)}


def _validate_ref(args):
    if not isinstance(args.get("event_id"), str) or not re.fullmatch(EID, args["event_id"]):
        raise InvalidArgs("a change needs the event found by its name (Diya finds it; it cannot be given an id)")
    gw._clean_title(args.get("title"), "an event")
    if not isinstance(args.get("etag", ""), str) or len(args.get("etag", "")) > 200:
        raise InvalidArgs("the event's version is not usable")
    mw._line(args.get("shown"), "the event's description", 300)


def _read_event(config, card, args):
    return client.read(config, card, LABELS[card], f"{EVENTS}/{args['event_id']}")


def _still_the_same(config, card, args, *, guests_ok=False):
    """The event as it is now; ActionFailed (nothing done) if it is gone, cancelled, changed since it was proposed, or has guests/repeats when it must not."""
    try:
        current = _read_event(config, card, args)
    except client.GoogleError as exc:
        if exc.kind == "not_found" or exc.status == 410:
            raise ActionFailed("That event is not on your calendar any more, so nothing was done.")
        raise ActionFailed(f"{exc} Nothing was done.")
    if not current or current.get("status") == "cancelled":
        raise ActionFailed("That event is not on your calendar any more, so nothing was done.")
    if args.get("etag") and current.get("etag") and current["etag"] != args["etag"]:
        raise ActionFailed(f"{args['shown']} was changed in Google Calendar after it was proposed, so nothing was done. Look at it in Google and ask again if you still want this.")
    if not guests_ok and (_guests(current) or _repeats(current)):
        raise ActionFailed("That event now has guests or repeats, so nothing was done.")
    return current


def _verify(config, card, args, check, what):
    try:
        found = _read_event(config, card, args)
    except client.GoogleError:
        raise ActionUncertain(f"Google said {what} was done, but reading it back to check did not work, so it is not confirmed. Look in Google Calendar, then record what you found.")
    problem = check(found)
    if problem:
        raise ActionUncertain(f"Google said {what} was done, but reading it back showed {problem}, so it is not confirmed. Look in Google Calendar, then record what you found.")
    return found


# ---- change an event ---------------------------------------------------------------------------------------------------------------------------------

UPDATE_KEYS = {"title", "event_id", "etag", "shown", "new_title", "when", "start", "end"}


def update_prepare(args, text):
    """What the person said, only: a new name that is not in their words is left out; the new time is read by code from their words; a length is kept only if they said the number."""
    kept = {k: v for k, v in args.items() if k in ("title", "new_title", "when", "duration_minutes")}
    notes = []
    if "new_title" in kept and not gw._own_words(kept["new_title"], text):
        kept.pop("new_title")
        notes.append("The new name was left out because it was not in the user's words.")
    when = kept.pop("when", None)
    if when is not None:
        try:
            if not isinstance(when, str) or diya_time.disagreement(when, text):
                raise diya_time.NotUnderstood("the time is not the user's")
            moment = diya_time.parse_when(when)
            kept["when"], kept["start"] = " ".join(when.split()), moment.iso()
        except diya_time.NotUnderstood:
            notes.append(f"The new time {when!r} was left out because the user did not say it.")
    minutes = kept.get("duration_minutes")
    if minutes is not None and not (isinstance(minutes, int) and not isinstance(minutes, bool) and gw.MINUTES[0] <= minutes <= gw.MINUTES[1]
                                    and (re.search(rf"(?<!\d){minutes}(?!\d)", text) or (minutes == 60 and re.search(r"\bhour\b", text, re.IGNORECASE)) or (minutes == 30 and re.search(r"\bhalf\b", text, re.IGNORECASE)))):
        kept.pop("duration_minutes")
        notes.append("The length was left out because the user did not say it.")
    return kept, notes


def update_resolve(config, args, said):
    when = args.get("when")
    rest = said  # the day the event is ON is read from what is left once the NEW time is taken out of the message; if that cannot be told, no day is used
    if isinstance(when, str) and when:
        rest = re.sub(re.escape(when), " ", said, flags=re.IGNORECASE) if re.search(re.escape(when), said, re.IGNORECASE) else ""
    event = find_event(config, CHANGE, args.get("title"), said, day_from=rest)
    _plain_own(event, timed=True)
    old_start, old_end = _utc_iso(event["start"]["dateTime"]), _utc_iso((event.get("end") or {}).get("dateTime"))
    if not old_end:
        raise InvalidArgs(f"{_shown(event)} has no end time, so it is not changed")
    resolved = _ref(event)
    if args.get("new_title") and args["new_title"] != event.get("summary"):
        resolved["new_title"] = args["new_title"]
    minutes = args.get("duration_minutes") or int((_utc(old_end) - _utc(old_start)).total_seconds() // 60)
    start = args.get("start") or old_start
    if args.get("start") or args.get("duration_minutes"):
        end = _stamp(_utc(start) + timedelta(minutes=minutes))
        if (start, end) != (old_start, old_end):
            resolved["start"], resolved["end"] = start, end
            if args.get("when"):
                resolved["when"] = args["when"]
    if not (resolved.get("new_title") or resolved.get("start")):
        raise InvalidArgs("that would change nothing: say what to change about it, its name, when it starts or how long it lasts")
    return resolved


def update_validate(args):
    gw._only(args, UPDATE_KEYS, "changing an event")
    _validate_ref(args)
    if "new_title" in args:
        gw._clean_title(args["new_title"], "an event")
    if ("start" in args) != ("end" in args):
        raise InvalidArgs("a new time needs both its start and its end")
    for key in ("start", "end"):
        if key in args:
            if not isinstance(args[key], str) or not gw._ISO_UTC.fullmatch(args[key]):
                raise InvalidArgs("that is not a time")
            try:
                diya_time.local_from_iso(args[key])
            except ValueError:
                raise InvalidArgs("that is not a time")
    if "end" in args:
        minutes = (_utc(args["end"]) - _utc(args["start"])).total_seconds() / 60
        if not gw.MINUTES[0] <= minutes <= gw.MINUTES[1]:
            raise InvalidArgs(f"an event lasts between {gw.MINUTES[0]} and {gw.MINUTES[1]} minutes")
    if "when" in args and (not isinstance(args["when"], str) or len(args["when"]) > diya_time.MAX_CHARS):
        raise InvalidArgs("when must be the user's own words, a few of them")
    if not (args.get("new_title") or args.get("start")):
        raise InvalidArgs("say what to change: its name, when it starts or how long it lasts")


def _changes(args):
    parts = []
    if args.get("new_title"):
        parts.append(f"renamed '{diya_memory.printable(args['new_title'], 60)}'")
    if args.get("start"):
        minutes = int((_utc(args["end"]) - _utc(args["start"])).total_seconds() // 60)
        parts.append(f"now {diya_time.describe_local(diya_time.local_from_iso(args['start']))}, {minutes} minutes")
    return ", ".join(parts)


def update_render(args):
    return f"Change the calendar event {args['shown']}: {_changes(args)} (just you: nobody is told)"


def update_execute(config, args):
    _still_the_same(config, CHANGE, args)
    body = {}
    if args.get("new_title"):
        body["summary"] = args["new_title"]
    if args.get("start"):
        body["start"], body["end"] = {"dateTime": args["start"], "timeZone": "UTC"}, {"dateTime": args["end"], "timeZone": "UTC"}
    client.send(config, CHANGE, LABELS[CHANGE], "PATCH", f"{EVENTS}/{args['event_id']}", params={"sendUpdates": "none"}, body=body, headers={"If-Match": args["etag"]} if args.get("etag") else None,
                doing=f"changing '{args['title']}'")

    def check(found):
        if body.get("summary") and found.get("summary") != body["summary"]:
            return "a different name"
        if args.get("start") and (not _same_moment((found.get("start") or {}).get("dateTime"), args["start"]) or not _same_moment((found.get("end") or {}).get("dateTime"), args["end"])):
            return "a different time"
        if found.get("status") == "cancelled":
            return "an event that is not on the calendar"
        return ""

    _verify(config, CHANGE, args, check, f"changing '{args['title']}'")
    return f"Changed in your Google Calendar and read back to check: {args['title']} is now {_changes(args)}."


# ---- cancel an event ---------------------------------------------------------------------------------------------------------------------------------

def cancel_resolve(config, args, said):
    event = find_event(config, CHANGE, args.get("title"), said)
    _plain_own(event)
    return _ref(event)


def cancel_validate(args):
    gw._only(args, {"title", "event_id", "etag", "shown"}, "cancelling an event")
    _validate_ref(args)


def cancel_render(args):
    return f"Cancel the calendar event {args['shown']} (nobody is told; Diya cannot bring it back)"


def cancel_execute(config, args):
    _still_the_same(config, CHANGE, args)
    client.send(config, CHANGE, LABELS[CHANGE], "DELETE", f"{EVENTS}/{args['event_id']}", params={"sendUpdates": "none"}, headers={"If-Match": args["etag"]} if args.get("etag") else None, ok=(200, 204),
                doing=f"cancelling '{args['title']}'")
    try:
        found = _read_event(config, CHANGE, args)
    except client.GoogleError as exc:
        if exc.kind == "not_found" or exc.status == 410:
            return f"Cancelled on your Google Calendar: {args['shown']}. Google no longer has it."
        raise ActionUncertain("Google said the event was cancelled, but reading to check did not work, so it is not confirmed. Look in Google Calendar, then record what you found.")
    if found.get("status") == "cancelled":
        return f"Cancelled on your Google Calendar: {args['shown']}."
    raise ActionUncertain("Google said the event was cancelled, but it is still there, so it is not confirmed. Look in Google Calendar, then record what you found.")


# ---- guests --------------------------------------------------------------------------------------------------------------------------------------------

def invite_prepare(args, text):
    """Guests are only addresses the person typed in their own message."""
    kept = {k: v for k, v in args.items() if k in ("title", "guests")}
    kept["guests"] = mw.own_recipients(kept.get("guests"), text, "a guest")
    if len(mw._split(kept["guests"])) > MAX_GUESTS:
        raise InvalidArgs(f"at most {MAX_GUESTS} guests are invited at a time")
    return kept, []


def invite_resolve(config, args, said):
    event = find_event(config, GUESTS, args.get("title"), said)
    _plain_own(event, guests_ok=True)
    have = {a["email"].lower() for a in _guests(event)}
    new = [g for g in mw._split(args.get("guests")) if g.lower() not in have]
    if not new:
        raise InvalidArgs(f"{_shown(event)}: they are already invited")
    if len(have) + len(new) > MAX_ALL_GUESTS:
        raise InvalidArgs(f"an event invited by Diya has at most {MAX_ALL_GUESTS} guests")
    return dict(_ref(event), guests=", ".join(new))


def invite_validate(args):
    gw._only(args, {"title", "event_id", "etag", "shown", "guests"}, "inviting guests")
    _validate_ref(args)
    if not 1 <= len(mw._addresses(args.get("guests"), "a guest")) <= MAX_GUESTS:
        raise InvalidArgs(f"an invitation goes to one to {MAX_GUESTS} email addresses")


def invite_render(args):
    return f"Invite {diya_memory.printable(args['guests'], 120)} to {args['shown']} (Google Calendar emails them)"


def _attendee_entry(attendee):
    return {key: attendee[key] for key in ("email", "displayName", "optional", "responseStatus") if key in attendee}


def invite_execute(config, args):
    current = _still_the_same(config, GUESTS, args, guests_ok=True)
    if not (current.get("organizer") or {}).get("self") or _repeats(current):
        raise ActionFailed("That event is not a plain event of yours any more, so nobody was invited.")
    existing = [_attendee_entry(a) for a in (current.get("attendees") or []) if isinstance(a, dict) and isinstance(a.get("email"), str)]
    known = {a["email"].lower() for a in existing}
    attendees = existing + [{"email": g} for g in mw._split(args["guests"]) if g.lower() not in known]
    if len(attendees) > MAX_ALL_GUESTS:
        raise ActionFailed("That would be more guests than Diya invites, so nobody was invited.")
    client.send(config, GUESTS, LABELS[GUESTS], "PATCH", f"{EVENTS}/{args['event_id']}", params={"sendUpdates": "all"}, body={"attendees": attendees}, headers={"If-Match": args["etag"]} if args.get("etag") else None,
                doing=f"inviting {args['guests']}")
    wanted = {g.lower() for g in mw._split(args["guests"])}

    def check(found):
        have = {a.get("email", "").lower() for a in (found.get("attendees") or []) if isinstance(a, dict)}
        return "" if wanted <= have else "guests that are missing"

    _verify(config, GUESTS, args, check, f"inviting {args['guests']}")
    return f"Invited {args['guests']} to {args['shown']} and read back to check; Google Calendar emailed them."


RESPONSES = {"accepted": r"\b(?:accept|yes|going|attend|confirm)\b", "declined": r"\b(?:decline|reject|no|can'?t\s+(?:go|make|come|attend)|not\s+(?:going|coming))\b", "tentative": r"\b(?:maybe|tentative(?:ly)?|might|perhaps)\b"}
RESPONSE_WORDS = {"accepted": "Accept", "declined": "Decline", "tentative": "Say maybe to"}


def rsvp_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("title", "response")}
    pattern = RESPONSES.get(kept.get("response"))
    if not pattern or not re.search(pattern, text, re.IGNORECASE):
        raise InvalidArgs("say whether to accept, decline or say maybe, in the user's own words; I do not choose")
    return kept, []


def rsvp_resolve(config, args, said):
    event = find_event(config, GUESTS, args.get("title"), said)
    me = [a for a in (event.get("attendees") or []) if isinstance(a, dict) and a.get("self")]
    if not me or (event.get("organizer") or {}).get("self"):
        raise InvalidArgs(f"{_shown(event)} is not an invitation you were sent, so there is nothing to answer")
    return dict(_ref(event), response=args["response"])


def rsvp_validate(args):
    gw._only(args, {"title", "event_id", "etag", "shown", "response"}, "answering an invitation")
    _validate_ref(args)
    if args.get("response") not in RESPONSES:
        raise InvalidArgs("an invitation is accepted, declined or answered with maybe")


def rsvp_render(args):
    return f"{RESPONSE_WORDS[args['response']]} the invitation {args['shown']} (the organiser is told)"


def rsvp_execute(config, args):
    current = _still_the_same(config, GUESTS, args, guests_ok=True)
    attendees = [dict(_attendee_entry(a), **({"self": True} if a.get("self") else {})) for a in (current.get("attendees") or []) if isinstance(a, dict) and isinstance(a.get("email"), str)]
    mine = [a for a in attendees if a.get("self")]
    if not mine:
        raise ActionFailed("You are not a guest of that event any more, so nothing was answered.")
    for entry in attendees:
        if entry.get("self"):
            entry["responseStatus"] = args["response"]
            entry.pop("self")
    client.send(config, GUESTS, LABELS[GUESTS], "PATCH", f"{EVENTS}/{args['event_id']}", params={"sendUpdates": "all"}, body={"attendees": attendees}, headers={"If-Match": args["etag"]} if args.get("etag") else None,
                doing="answering the invitation")

    def check(found):
        status = [a.get("responseStatus") for a in (found.get("attendees") or []) if isinstance(a, dict) and a.get("self")]
        return "" if status == [args["response"]] else "a different answer"

    _verify(config, GUESTS, args, check, "answering the invitation")
    return f"Answered the invitation {args['shown']} and read back to check: {args['response']}. Google Calendar told the organiser."


# ---- an event that repeats (the existing "add events" card) ----------------------------------------------------------------------------------

_EVERY = {
    "daily": r"\b(?:daily|every\s+day|each\s+day)\b", "weekly": r"\b(?:weekly|every\s+week|each\s+week|every\s+(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)\w*)\b",
    "monthly": r"\b(?:monthly|every\s+month|each\s+month)\b", "yearly": r"\b(?:yearly|annually|every\s+year|each\s+year)\b",
}


def repeating_prepare(args, text):
    """The start is the person's (read by code, as for any new event); how it repeats must be in their words, and so must how many times: a repeat nobody said is not added."""
    kept, notes = gw.event_prepare({k: v for k, v in args.items() if k in ("title", "when", "duration_minutes")}, text)
    repeat = args.get("repeat")
    if repeat not in REPEATS or not re.search(_EVERY[repeat], text, re.IGNORECASE):
        raise InvalidArgs("say how often it repeats (every day, week, month or year), in the user's own words; I do not choose")
    times = args.get("times")
    if not (isinstance(times, int) and not isinstance(times, bool) and TIMES[0] <= times <= TIMES[1] and re.search(rf"(?<!\d){times}(?!\d)", text)):
        raise InvalidArgs(f"say how many times it repeats, {TIMES[0]} to {TIMES[1]}, in the user's own words (for example 'for 8 weeks'); I do not choose")
    return dict(kept, repeat=repeat, times=times), notes


def repeating_validate(args):
    gw._only(args, {"title", "when", "start", "duration_minutes", "repeat", "times"}, "a repeating event")
    gw.event_validate({k: v for k, v in args.items() if k not in ("repeat", "times")})
    if args.get("repeat") not in REPEATS:
        raise InvalidArgs("an event repeats daily, weekly, monthly or yearly")
    if not isinstance(args.get("times"), int) or isinstance(args.get("times"), bool) or not TIMES[0] <= args["times"] <= TIMES[1]:
        raise InvalidArgs(f"an event repeats {TIMES[0]} to {TIMES[1]} times")


def repeating_render(args):
    return (f"Add to your Google Calendar: {args['title']}, from {gw._local(args['start'])}, for {args.get('duration_minutes', 60)} minutes, repeating {args['repeat']}, {args['times']} times "
            "(just you: nobody is invited)")


def _rule(args):
    return f"RRULE:FREQ={REPEATS[args['repeat']]};COUNT={args['times']}"


def repeating_id(args):
    return hashlib.sha256(f"{args['title']}|{args['start']}|{args.get('duration_minutes', 60)}|{args['repeat']}|{args['times']}".encode("utf-8")).hexdigest()[:32]


def _calendar_zone(config):
    """The calendar's own time zone (an IANA name), read from the calendar, or None."""
    try:
        zone = client.read(config, ADDER, LABELS[ADDER], EVENTS, {"maxResults": 1}).get("timeZone")
    except client.GoogleError:
        return None
    return zone if isinstance(zone, str) and re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z0-9_+-]+){0,2}", zone) else None


def _zoned(start_iso, end_iso, zone):
    """(start, end) as Google wants them for an event that repeats: the wall-clock time in the calendar's own zone when that zone is the one this computer is in, so that a daylight-saving change does not shift later
    events; else UTC, which does not shift but is not the wall clock after such a change."""
    if zone:
        try:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(zone)
            local = _utc(start_iso).astimezone(tz)
            machine = diya_time.local_from_iso(start_iso)
            if local.replace(tzinfo=None) == machine:
                end = _utc(end_iso).astimezone(tz)
                return {"dateTime": local.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": zone}, {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": zone}
        except Exception:  # noqa: BLE001 -- no time zone database: UTC it is
            pass
    return {"dateTime": start_iso, "timeZone": "UTC"}, {"dateTime": end_iso, "timeZone": "UTC"}


def repeating_execute(config, args):
    start = _utc(args["start"])
    end_iso = _stamp(start + timedelta(minutes=args.get("duration_minutes", 60)))
    first, last = _zoned(args["start"], end_iso, _calendar_zone(config))
    body = {"id": repeating_id(args), "summary": args["title"], "start": first, "end": last, "recurrence": [_rule(args)]}
    response = gw._send(config, ADDER, "POST", EVENTS, params={"sendUpdates": "none"}, body=body, what="the repeating event", ok=(200,), accept=(409,))
    if response.status_code == 409:
        found = gw._json(gw._send(config, ADDER, "GET", f"{EVENTS}/{body['id']}", what="the repeating event", ok=(200,)))
        if found.get("status") == "cancelled":
            raise ActionFailed("This same repeating event was added before and then deleted, and Google does not let an event come back under the same id, so nothing was added. Change the title a little and ask again.")
        if found.get("summary") != args["title"]:
            raise ActionFailed("Google already has an event with this request's id that is not this one, so nothing was added.")
        return f"That repeating event was already on your calendar (added earlier): {args['title']}.{gw._link(found, 'htmlLink')}"
    data = gw._json(response)
    if data.get("id") != body["id"] or data.get("status") not in ("confirmed", "tentative"):
        raise ActionUncertain("Google answered, but not with the event that was asked for, so it may or may not be on your calendar. Look in Google Calendar, then record what you found.")

    def check(found):
        if found.get("summary") != args["title"]:
            return "a different title"
        if not _same_moment((found.get("start") or {}).get("dateTime"), args["start"]):
            return "a different time"
        if found.get("recurrence") != body["recurrence"]:
            return "a different repeat"
        if found.get("attendees"):
            return "guests, and nobody was to be invited"
        return ""

    verified = gw._read_back(config, ADDER, f"{EVENTS}/{body['id']}", "the repeating event", check)
    return f"Added to your Google Calendar and read back to check: {args['title']}, from {gw._local(args['start'])}, repeating {args['repeat']}, {args['times']} times.{gw._link(verified, 'htmlLink')}"


# ---- the kinds, their tools and the cards ---------------------------------------------------------------------------------------------------------

def _kind(name, label, connector, tool_name, description, properties, required, **functions):
    return ActionKind(
        name=name, label=label, connector=connector, **functions,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is changed until the user approves it on the Actions page.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


TITLE = {"type": "string", "description": "The name of the event, exactly as the user said it."}


def update_kind():
    return _kind("google_calendar_update_event", "Change a Google Calendar event", CHANGE, "propose_update_calendar_event",
                 "Propose renaming one of the user's own calendar events, moving it to another time, or changing how long it lasts. It is only for events with no guests. Use it only when the user asks for that, naming the event.",
                 {"title": TITLE, "new_title": {"type": "string", "description": "Optional. The new name, in the user's words."}, "when": {"type": "string", "description": "Optional. The new start time in the user's own words, e.g. 'friday at 3pm'."},
                  "duration_minutes": {"type": "integer", "description": "Optional. The new length in minutes, only if the user said it."}}, ["title"],
                 validate=update_validate, render=update_render, execute=update_execute, asked=asks.changes_calendar_event, prepare=update_prepare, resolve=update_resolve)


def cancel_kind():
    return _kind("google_calendar_cancel_event", "Cancel a Google Calendar event", CHANGE, "propose_cancel_calendar_event",
                 "Propose cancelling (deleting) one of the user's own calendar events that has no guests. Diya cannot bring it back. Use it only when the user asks for that, naming the event.",
                 {"title": TITLE}, ["title"], validate=cancel_validate, render=cancel_render, execute=cancel_execute, asked=asks.cancels_calendar_event, resolve=cancel_resolve)


def invite_kind():
    return _kind("google_calendar_invite", "Invite guests to a Google Calendar event", GUESTS, "propose_invite_calendar_event",
                 "Propose inviting people to one of the user's own calendar events, by the email addresses the user typed in their message. Google Calendar emails them. Use it only when the user asks for that.",
                 {"title": TITLE, "guests": {"type": "string", "description": "The email addresses, exactly as the user typed them (several: separated by commas). Never guess or look one up."}}, ["title", "guests"],
                 validate=invite_validate, render=invite_render, execute=invite_execute, asked=asks.invites_to_event, prepare=invite_prepare, resolve=invite_resolve)


def rsvp_kind():
    return _kind("google_calendar_rsvp", "Answer a Google Calendar invitation", GUESTS, "propose_rsvp_calendar_event",
                 "Propose accepting, declining or saying maybe to an invitation the user was sent, naming the event. The organiser is told. Use it only when the user asks for that.",
                 {"title": TITLE, "response": {"type": "string", "enum": list(RESPONSES), "description": "accepted, declined or tentative (maybe), as the user said."}}, ["title", "response"],
                 validate=rsvp_validate, render=rsvp_render, execute=rsvp_execute, asked=asks.answers_invitation, prepare=rsvp_prepare, resolve=rsvp_resolve)


def repeating_kind():
    return _kind("google_calendar_add_repeating_event", "Add a repeating Google Calendar event", ADDER, "propose_repeating_calendar_event",
                 "Propose adding an event that repeats (daily, weekly, monthly or yearly, a number of times the user said) to the user's Google Calendar. Nobody is invited. Use it only when the user asks for an event that repeats.",
                 {"title": TITLE, "when": {"type": "string", "description": "When the first one starts, in the user's own words. Required."}, "duration_minutes": {"type": "integer", "description": "Optional. How long each lasts in minutes; 60 if not said."},
                  "repeat": {"type": "string", "enum": list(REPEATS), "description": "How often, as the user said."}, "times": {"type": "integer", "description": "How many times in all, as the user said."}}, ["title", "when", "repeat", "times"],
                 validate=repeating_validate, render=repeating_render, execute=repeating_execute, asked=asks.adds_repeating_event, prepare=repeating_prepare)


def action_kinds():
    return (update_kind(), cancel_kind(), invite_kind(), rsvp_kind(), repeating_kind())


def connectors():
    return (
        diya_google_cards.card(CHANGE, LABELS[CHANGE], "Change the time or name of one of your own events, or cancel one, when you approve it. Only events with no guests.", SCOPE, "Google Calendar API",
                               ("Moves, renames or cancels one event of yours, only when you approve that one change, and only an event that is yours, has no guests and does not repeat.", "Reads which event you mean, and what it looks like afterwards.",
                                "Cannot invite anyone, tell anyone, or change an event that has guests, repeats or is someone else's.")),
        diya_google_cards.card(GUESTS, LABELS[GUESTS], "Invite people to one of your events, or answer an invitation, when you approve it. Google emails them.", SCOPE, "Google Calendar API",
                               ("Invites the addresses you typed to one event of yours, or accepts, declines or says maybe to an invitation, only when you approve that one thing; Google Calendar emails the people involved.",
                                "Invites at most 5 at a time, and at most 10 guests to an event.", "Cannot invite an address you did not type, change or cancel an event, or do anything without your approval.")),
    )
