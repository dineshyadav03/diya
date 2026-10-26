"""Google Calendar beyond adding: change an event, cancel it, invite guests, answer an invitation, an event that repeats, and finding an event or free time (diya_google_calchange.py, diya_calendar_find.py; DIYA-080,
-082, -083, -084; docs/GOOGLE_CHANGES.md), added 2026-10-26.

No test here reaches the real Google: a stateful stand-in Calendar answers, keeps every request, applies what it is sent and refuses a stale If-Match. What this proves: each card's list of allowed requests; each kind is
proposed only when the message asks for that thing in those words; the event is found NOW from the person's own words (none, several, someone else's, with guests, or one of a series refuses it, "the next one" picks); a
new name, time or length the model made up is dropped; a change is sent with the version it was proposed against and nothing is done to an event that moved on; every change is read back; guests are only typed addresses;
an answer to an invitation needs the person's own yes, no or maybe; an event that repeats needs the person's own words for how often and how many times; an outcome that is not known is said to be not known; and the
calendar questions (an event by name, free time) are answered by code from the read-only card.
"""
import dataclasses
import json
import types
from datetime import datetime, time, timedelta, timezone

import pytest

import diya
import diya_actions
import diya_autoapprove
import diya_calendar_find as cf
import diya_catalog
import diya_config
import diya_connectors
import diya_google_calchange as cc
import diya_google_calendar as gcal
import diya_google_cards
import diya_google_client as client
import diya_intent_google as asks
import diya_time
from fakes import FakeClient, text_reply, tool_reply

EVENTS = cc.EVENTS
CARDS = (cc.READER, cc.CHANGE, cc.GUESTS, cc.ADDER)


def resp(status=200, body=None):
    return types.SimpleNamespace(status_code=status, headers={}, json=lambda: body if body is not None else {})


def stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tomorrow_at(hour, days=1):
    local = datetime.combine(datetime.now().astimezone().date() + timedelta(days=days), time(hour))
    return stamp(local.astimezone())


def event(eid, title, start, minutes=60, **extra):
    end = stamp(datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(minutes=minutes))
    return {"id": eid, "etag": f'"v1-{eid}"', "status": "confirmed", "summary": title, "start": {"dateTime": start}, "end": {"dateTime": end}, "organizer": {"self": True, "email": "me@example.com"}, **extra}


class Calendar:
    """A stand-in Google Calendar: events with versions, the five requests Diya makes, and the answer to a stale If-Match."""

    def __init__(self):
        self.events, self.requests, self.zone, self.delete_leaves_cancelled, self.fail_status = {}, [], "Asia/Kolkata", False, {}
        self.add(event("evdentist1", "Dentist appointment", tomorrow_at(10, 2)))
        self.add(event("evphysics1", "Physics session", tomorrow_at(15, 3)))

    def add(self, ev):
        self.events[ev["id"]] = ev

    @staticmethod
    def stored(body):
        """What Google keeps of what it is sent: a wall-clock time in a zone becomes a time with its offset, and the entry for the account's own address is marked as the account's."""
        import zoneinfo

        kept = json.loads(json.dumps(body))
        for key in ("start", "end"):
            part = kept.get(key)
            if isinstance(part, dict) and part.get("timeZone") not in (None, "UTC") and not part["dateTime"].endswith("Z") and "+" not in part["dateTime"][10:]:
                part["dateTime"] = datetime.fromisoformat(part["dateTime"]).replace(tzinfo=zoneinfo.ZoneInfo(part["timeZone"])).isoformat()
        for attendee in kept.get("attendees") or []:
            if attendee.get("email") == "me@example.com":
                attendee["self"] = True
        return kept

    def bump(self, ev):
        n = int(ev["etag"].split("-")[0].strip('"v')) + 1
        ev["etag"] = f'"v{n}-{ev["id"]}"'

    def __call__(self, *args, **kwargs):
        method, url = (args[0], args[1]) if len(args) == 2 else ("GET", args[0])
        params, body, headers = kwargs.get("params") or {}, kwargs.get("json"), kwargs.get("headers") or {}
        self.requests.append((method, url, dict(params), body, dict(headers)))
        if method in self.fail_status:
            return resp(self.fail_status[method], {"error": {"message": "backend error"}})
        tail = url[len(EVENTS):].strip("/")
        if not tail:
            if method == "GET":
                low, high = params.get("timeMin"), params.get("timeMax")
                rows = [e for e in self.events.values() if e["status"] != "cancelled" and (not low or e["start"].get("dateTime", e["start"].get("date", ""))[:10] >= low[:10])]
                rows = sorted(rows, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
                return resp(200, {"items": rows, "timeZone": self.zone})
            if method == "POST":
                if body["id"] in self.events:
                    return resp(409, {"error": {"message": "duplicate"}})
                new = dict(self.stored(body), etag=f'"v1-{body["id"]}"', status="confirmed", organizer={"self": True, "email": "me@example.com"}, htmlLink="https://calendar.example/e")
                self.events[body["id"]] = new
                return resp(200, new)
        ev = self.events.get(tail)
        if ev is None:
            return resp(404, {"error": {"message": "not found"}})
        if method == "GET":
            return resp(200, ev)
        if "If-Match" in headers and headers["If-Match"] != ev["etag"]:
            return resp(412, {"error": {"message": "precondition failed"}})
        if method == "PATCH":
            ev.update(self.stored(body))
            self.bump(ev)
            return resp(200, ev)
        if method == "DELETE":
            if self.delete_leaves_cancelled:
                ev["status"] = "cancelled"
            else:
                del self.events[tail]
            return resp(204)
        return resp(400)

    def mutations(self):
        return [r for r in self.requests if r[0] in ("POST", "PUT", "DELETE", "PATCH")]


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False, lookup=False)
    for name in CARDS:
        diya_connectors.store_token(config, name, "refresh")
    return config


@pytest.fixture
def calendar(monkeypatch):
    service = Calendar()
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "tok" if name in CARDS else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return service


def propose(config, message_text, tool, args):
    agent = diya.Agent(config, client=FakeClient([tool_reply(tool, json.dumps(args)), text_reply("ok")]), action_kinds=list(cc.action_kinds()))
    agent.ask([{"role": "user", "content": message_text}])
    return agent


def run_approved(agent):
    (action,) = agent.actions.pending()
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    return agent.actions.run(action["id"])


# ---- what each card may ask for ------------------------------------------------------------------------------------------------------------------

def test_the_change_card_can_change_and_cancel_one_event_and_the_guests_card_can_only_change_one():
    one, many = f"{EVENTS}/evdentist1", EVENTS
    assert client.permitted(cc.CHANGE, "PATCH", one) and client.permitted(cc.CHANGE, "DELETE", one) and client.permitted(cc.CHANGE, "GET", one) and client.permitted(cc.CHANGE, "GET", many)
    assert not client.permitted(cc.CHANGE, "POST", many) and not client.permitted(cc.CHANGE, "POST", f"{EVENTS}/evdentist1/move") and not client.permitted(cc.CHANGE, "DELETE", many)
    assert client.permitted(cc.GUESTS, "PATCH", one) and not client.permitted(cc.GUESTS, "DELETE", one) and not client.permitted(cc.GUESTS, "POST", many)
    assert client.permitted(cc.READER, "GET", many) and not any(client.permitted(cc.READER, m, one) for m in ("PATCH", "DELETE", "POST", "PUT"))
    other = "https://www.googleapis.com/calendar/v3/calendars/someone%40example.com/events/evdentist1"
    assert not any(client.permitted(card, m, other) for card in CARDS for m in ("GET", "PATCH", "DELETE"))  # only the main calendar


def test_both_new_cards_use_the_one_calendar_events_permission_and_are_known_to_disconnect(config):
    from diya_connector_tools import real_connectors

    made = {c.name: c for c in real_connectors(config)}
    for name in (cc.CHANGE, cc.GUESTS):
        assert made[name].scope == cc.SCOPE and made[name].implemented and name in gcal.every_card() and name in diya_google_cards.names()


# ---- the words that ask ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, fn, expected", [
    ("move my dentist appointment to friday at 3pm", asks.changes_calendar_event, True),
    ("rename the physics session to physics lab", asks.changes_calendar_event, True),
    ("move buy milk to the top of my google tasks", asks.changes_calendar_event, False),
    ("how do i move an event", asks.changes_calendar_event, False),
    ("move the dentist", asks.changes_calendar_event, False),  # no calendar word
    ("cancel my dentist appointment", asks.cancels_calendar_event, True),
    ("don't cancel my dentist appointment", asks.cancels_calendar_event, False),
    ("delete buy milk from my google tasks", asks.cancels_calendar_event, False),
    ("invite maya@example.com to the physics session", asks.invites_to_event, True),
    ("invite maya to the physics session", asks.invites_to_event, False),  # no address typed
    ("accept the invitation to the physics session", asks.answers_invitation, True),
    ("decline the meeting with sam", asks.answers_invitation, True),
    ("say maybe to the study session", asks.answers_invitation, True),
    ("add a weekly study session on mondays at 6pm for 8 weeks", asks.adds_repeating_event, True),
    ("add a study session on monday at 6pm", asks.adds_repeating_event, False),
])
def test_each_kind_is_asked_for_only_in_its_own_words(text, fn, expected):
    assert fn(text) is expected


# ---- change an event ---------------------------------------------------------------------------------------------------------------------------------

def test_an_event_is_renamed_after_approval_with_its_version_and_read_back(config, calendar):
    agent = propose(config, "rename the physics session to Physics lab", "propose_update_calendar_event", {"title": "physics session", "new_title": "Physics lab"})
    (action,) = agent.actions.actions()
    assert action["status"] == "pending" and action["args"]["event_id"] == "evphysics1" and action["args"]["new_title"] == "Physics lab" and action["summary"].startswith("Change the calendar event Physics session (")
    assert calendar.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "read back to check" in done["result"] and calendar.events["evphysics1"]["summary"] == "Physics lab"
    (patch,) = calendar.mutations()
    assert patch[0] == "PATCH" and patch[2] == {"sendUpdates": "none"} and patch[4]["If-Match"] == '"v1-evphysics1"' and patch[3] == {"summary": "Physics lab"}


def test_an_event_is_moved_to_the_time_the_person_said_and_keeps_its_length(config, calendar):
    agent = propose(config, "move the dentist appointment to friday at 3pm", "propose_update_calendar_event", {"title": "dentist appointment", "when": "friday at 3pm"})
    (action,) = agent.actions.actions()
    wanted = diya_time.parse_when("friday at 3pm").iso()
    assert action["args"]["start"] == wanted and action["args"]["end"] == stamp(datetime.strptime(wanted, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(minutes=60))
    done = run_approved(agent)
    assert done["status"] == "succeeded" and calendar.events["evdentist1"]["start"]["dateTime"] == wanted


def test_a_new_name_time_or_length_the_model_made_up_is_dropped_and_nothing_to_change_is_refused(config, calendar):
    agent = propose(config, "change the physics session", "propose_update_calendar_event", {"title": "physics session", "new_title": "Something else", "when": "next century", "duration_minutes": 999})
    assert agent.actions.actions() == [] and calendar.mutations() == []
    agent = propose(config, "change the physics session to 90 minutes", "propose_update_calendar_event", {"title": "physics session", "duration_minutes": 90})
    (action,) = agent.actions.actions()
    assert "start" in action["args"] and "new_title" not in action["args"]
    assert (datetime.strptime(action["args"]["end"], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(action["args"]["start"], "%Y-%m-%dT%H:%M:%SZ")) == timedelta(minutes=90)


def test_an_event_with_guests_that_repeats_that_is_someone_elses_or_all_day_is_not_changed(config, calendar):
    calendar.add(event("evguests01", "Team sync", tomorrow_at(11), attendees=[{"email": "me@example.com", "self": True}, {"email": "sam@example.com"}]))
    calendar.add(event("evseries01", "Standup", tomorrow_at(9), recurringEventId="series1"))
    calendar.add(event("evtheirs01", "Their review", tomorrow_at(12), organizer={"self": False, "email": "boss@example.com"}))
    calendar.add({"id": "evallday01", "etag": '"v1-evallday01"', "status": "confirmed", "summary": "Holiday", "start": {"date": "2026-12-25"}, "end": {"date": "2026-12-26"}, "organizer": {"self": True}})
    for name, words in (("Team sync", "has guests"), ("Standup", "series"), ("Their review", "someone else's"), ("Holiday", "all-day")):
        agent = propose(config, f"rename {name} to Renamed", "propose_update_calendar_event", {"title": name, "new_title": "Renamed"})
        assert agent.actions.actions() == [], name
        with pytest.raises(diya_actions.InvalidArgs, match=words):
            cc.update_resolve(config, {"title": name, "new_title": "Renamed"}, f"rename {name} to Renamed")
    assert calendar.mutations() == []


def test_several_matches_refuse_the_change_and_next_picks_the_soonest(config, calendar):
    calendar.add(event("evphysics2", "Physics session", tomorrow_at(15, 5)))
    agent = propose(config, "rename the physics session to Lab", "propose_update_calendar_event", {"title": "physics session", "new_title": "Lab"})
    assert agent.actions.actions() == []
    agent = propose(config, "rename my next physics session to Lab", "propose_update_calendar_event", {"title": "physics session", "new_title": "Lab"})
    (action,) = agent.actions.actions()
    assert action["args"]["event_id"] == "evphysics1"


def test_a_title_the_person_did_not_say_is_not_searched_for(config, calendar):
    with pytest.raises(diya_actions.InvalidArgs, match="say which event"):
        cc.find_event(config, cc.CHANGE, "Dentist appointment", "rename it to lab")
    with pytest.raises(diya_actions.InvalidArgs, match="there is no event called"):
        cc.find_event(config, cc.CHANGE, "gym", "rename gym to lab")


def test_an_event_that_changed_after_it_was_proposed_is_not_touched(config, calendar):
    agent = propose(config, "rename the physics session to Physics lab", "propose_update_calendar_event", {"title": "physics session", "new_title": "Physics lab"})
    calendar.events["evphysics1"]["summary"] = "Edited elsewhere"
    calendar.bump(calendar.events["evphysics1"])
    done = run_approved(agent)
    assert done["status"] == "failed" and "was changed in Google Calendar after it was proposed" in done["result"] and calendar.mutations() == []


def test_a_version_that_moves_between_the_check_and_the_change_is_refused_by_google_and_nothing_is_done(config, calendar, monkeypatch):
    agent = propose(config, "rename the physics session to Physics lab", "propose_update_calendar_event", {"title": "physics session", "new_title": "Physics lab"})
    monkeypatch.setattr(cc, "_still_the_same", lambda *a, **k: None)  # the check passed, and then someone else edited it
    calendar.bump(calendar.events["evphysics1"])
    done = run_approved(agent)
    assert done["status"] == "failed" and "changed in the meantime" in done["result"] and calendar.events["evphysics1"]["summary"] == "Physics session"


def test_a_change_the_server_did_not_apply_is_not_confirmed(config, calendar, monkeypatch):
    agent = propose(config, "rename the physics session to Physics lab", "propose_update_calendar_event", {"title": "physics session", "new_title": "Physics lab"})
    original = calendar.__call__

    def ignoring(*args, **kwargs):
        if len(args) == 2 and args[0] == "PATCH":
            calendar.requests.append(("PATCH", args[1], {}, kwargs.get("json"), {}))
            return resp(200, calendar.events["evphysics1"])
        return original(*args, **kwargs)

    monkeypatch.setattr(client.httpx, "request", ignoring)
    done = run_approved(agent)
    assert done["status"] == "unknown" and "a different name" in done["result"]


def test_a_change_with_a_server_error_part_way_is_unknown_and_never_tried_again(config, calendar):
    agent = propose(config, "rename the physics session to Physics lab", "propose_update_calendar_event", {"title": "physics session", "new_title": "Physics lab"})
    calendar.fail_status["PATCH"] = 500
    done = run_approved(agent)
    assert done["status"] == "unknown" and len([r for r in calendar.requests if r[0] == "PATCH"]) == 1
    with pytest.raises(diya_actions.ActionError):
        agent.actions.run(done["id"])


# ---- cancel an event --------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("leaves_cancelled", [False, True])
def test_an_event_is_cancelled_after_approval_and_read_back_whichever_way_google_shows_it_gone(config, calendar, leaves_cancelled):
    calendar.delete_leaves_cancelled = leaves_cancelled
    agent = propose(config, "cancel my dentist appointment", "propose_cancel_calendar_event", {"title": "dentist appointment"})
    (action,) = agent.actions.actions()
    assert "Diya cannot bring it back" in action["summary"] and calendar.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and done["result"].startswith("Cancelled on your Google Calendar:")
    (delete,) = calendar.mutations()
    assert delete[0] == "DELETE" and delete[2] == {"sendUpdates": "none"} and delete[4]["If-Match"] == '"v1-evdentist1"'


def test_an_event_with_guests_is_not_cancelled_and_nobody_is_told(config, calendar):
    calendar.add(event("evguests01", "Team sync", tomorrow_at(11), attendees=[{"email": "sam@example.com"}]))
    agent = propose(config, "cancel the team sync meeting", "propose_cancel_calendar_event", {"title": "team sync"})
    assert agent.actions.actions() == [] and calendar.mutations() == []


def test_a_cancel_that_may_have_gone_is_unknown(config, calendar):
    agent = propose(config, "cancel my dentist appointment", "propose_cancel_calendar_event", {"title": "dentist appointment"})
    calendar.fail_status["DELETE"] = 500
    done = run_approved(agent)
    assert done["status"] == "unknown" and "may or may not have been done" in done["result"]


# ---- guests ---------------------------------------------------------------------------------------------------------------------------------------------

def test_guests_are_invited_by_typed_address_with_google_telling_them_and_read_back(config, calendar):
    agent = propose(config, "invite maya@example.com to the physics session", "propose_invite_calendar_event", {"title": "physics session", "guests": "maya@example.com"})
    (action,) = agent.actions.actions()
    assert action["args"]["guests"] == "maya@example.com" and "Google Calendar emails them" in action["summary"] and calendar.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "emailed them" in done["result"]
    (patch,) = calendar.mutations()
    assert patch[2] == {"sendUpdates": "all"} and patch[3] == {"attendees": [{"email": "maya@example.com"}]} and patch[4]["If-Match"] == '"v1-evphysics1"'


def test_an_address_the_person_did_not_type_is_never_invited(config, calendar):
    for wrong in ("sam@example.com", "maya", "maya@example.com, sam@example.com"):
        agent = propose(config, "invite maya@example.com to the physics session", "propose_invite_calendar_event", {"title": "physics session", "guests": wrong})
        assert agent.actions.actions() == [], wrong
    assert calendar.mutations() == []


def test_someone_already_invited_is_not_invited_again_and_the_existing_guests_are_kept(config, calendar):
    calendar.add(event("evguests01", "Team sync", tomorrow_at(11), attendees=[{"email": "me@example.com", "self": True, "responseStatus": "accepted"}, {"email": "sam@example.com", "responseStatus": "accepted"}]))
    agent = propose(config, "invite sam@example.com to the team sync meeting", "propose_invite_calendar_event", {"title": "team sync", "guests": "sam@example.com"})
    assert agent.actions.actions() == []
    agent = propose(config, "invite maya@example.com to the team sync meeting", "propose_invite_calendar_event", {"title": "team sync", "guests": "maya@example.com"})
    done = run_approved(agent)
    assert done["status"] == "succeeded"
    assert [a["email"] for a in calendar.events["evguests01"]["attendees"]] == ["me@example.com", "sam@example.com", "maya@example.com"] and calendar.events["evguests01"]["attendees"][1]["responseStatus"] == "accepted"


def test_guests_cannot_be_added_to_someone_elses_event_or_a_series(config, calendar):
    calendar.add(event("evtheirs01", "Their review", tomorrow_at(12), organizer={"self": False, "email": "boss@example.com"}))
    agent = propose(config, "invite maya@example.com to the their review meeting", "propose_invite_calendar_event", {"title": "their review", "guests": "maya@example.com"})
    assert agent.actions.actions() == []


def test_an_invitation_is_answered_only_with_the_persons_own_yes_no_or_maybe(config, calendar):
    calendar.add(event("evinvite01", "Study group", tomorrow_at(17), organizer={"self": False, "email": "sam@example.com"},
                       attendees=[{"email": "sam@example.com", "organizer": True, "responseStatus": "accepted"}, {"email": "me@example.com", "self": True, "responseStatus": "needsAction"}]))
    agent = propose(config, "decline the study group invitation", "propose_rsvp_calendar_event", {"title": "study group", "response": "accepted"})
    assert agent.actions.actions() == [] and calendar.mutations() == []  # the model said accept, the person said decline
    agent = propose(config, "accept the study group invitation", "propose_rsvp_calendar_event", {"title": "study group", "response": "accepted"})
    (action,) = agent.actions.actions()
    assert action["summary"].startswith("Accept the invitation Study group (") and "the organiser is told" in action["summary"]
    done = run_approved(agent)
    assert done["status"] == "succeeded", done["result"]
    statuses = {a["email"]: a["responseStatus"] for a in calendar.events["evinvite01"]["attendees"]}
    assert statuses == {"sam@example.com": "accepted", "me@example.com": "accepted"}
    (patch,) = calendar.mutations()
    assert patch[2] == {"sendUpdates": "all"} and all("self" not in a for a in patch[3]["attendees"])


def test_an_event_of_your_own_is_not_an_invitation_to_answer(config, calendar):
    agent = propose(config, "accept the physics session invitation", "propose_rsvp_calendar_event", {"title": "physics session", "response": "accepted"})
    assert agent.actions.actions() == []


# ---- an event that repeats ---------------------------------------------------------------------------------------------------------------------

def test_a_repeating_event_is_added_with_the_persons_words_for_how_often_and_how_many_times(config, calendar):
    said = "add a weekly study session on monday at 6pm for 8 weeks"
    agent = propose(config, said, "propose_repeating_calendar_event", {"title": "study session", "when": "monday at 6pm", "repeat": "weekly", "times": 8})
    (action,) = agent.actions.actions()
    assert action["args"]["repeat"] == "weekly" and action["args"]["times"] == 8 and "repeating weekly, 8 times" in action["summary"] and calendar.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "read back to check" in done["result"], done["result"]
    (post,) = calendar.mutations()
    assert post[0] == "POST" and post[3]["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=8"] and post[3]["start"]["timeZone"] in ("Asia/Kolkata", "UTC") and "attendees" not in post[3] and post[2] == {"sendUpdates": "none"}


def test_a_repeat_or_a_count_the_person_did_not_say_is_not_added(config, calendar):
    for said, args in (
        ("add a study session on monday at 6pm for 8 weeks", {"title": "study session", "when": "monday at 6pm", "repeat": "daily", "times": 8}),  # no "daily" in the words
        ("add a weekly study session on monday at 6pm", {"title": "study session", "when": "monday at 6pm", "repeat": "weekly", "times": 20}),  # no 20 in the words
        ("add a weekly study session on monday at 6pm for 100 weeks", {"title": "study session", "when": "monday at 6pm", "repeat": "weekly", "times": 100}),  # more than 52
    ):
        agent = propose(config, said, "propose_repeating_calendar_event", args)
        assert agent.actions.actions() == [], said
    assert calendar.mutations() == []


# ---- finding an event and free time --------------------------------------------------------------------------------------------------------------

def test_an_event_is_found_by_name_and_listed_by_code(config, calendar):
    answer, fine = cf.answer(config, "when is my dentist appointment?")
    assert fine and answer.startswith("On your calendar in the next 90 days, matching 'dentist appointment':") and "Dentist appointment" in answer and "I can only read" in answer
    assert cf.answer(config, "find my gym session in my calendar") == ("I found nothing on your calendar matching 'gym session' in the next 90 days.", True)
    assert cf.answer(config, "when is my gym session?") is None and cf.answer(config, "when is my exam?") is None  # nothing, and "calendar" not said: it may be about something they told Diya
    assert cf.answer(config, "cancel my dentist appointment") is None and cf.answer(config, "when is my birthday") is None


def test_free_time_is_the_gaps_between_events_in_working_hours(config, calendar):
    calendar.events.clear()
    day = datetime.now().astimezone().date() + timedelta(days=1)
    calendar.add(event("evmorning01", "Lab", stamp(datetime.combine(day, time(10)).astimezone()), 60))
    calendar.add(event("evnoon00001", "Lunch with Sam", stamp(datetime.combine(day, time(13)).astimezone()), 60))
    answer, fine = cf.answer(config, "when am i free tomorrow?")
    assert fine and answer.startswith("Tomorrow: free 09:00-10:00, 11:00-13:00, 14:00-18:00") and "between 9:00 and 18:00" in answer
    answer, _ = cf.answer(config, "find an hour tomorrow")
    assert "09:00-10:00" in answer and "Gaps of 1 hour or more" in answer
    answer, _ = cf.answer(config, "find 5 hours tomorrow")
    assert "no gap of 5 hours" in answer and "Lab" in answer
    answer, _ = cf.answer(config, "am i free at 10am tomorrow?")
    assert answer.startswith("At 10:00 on tomorrow you are busy: Lab.")
    answer, _ = cf.answer(config, "am i free at 3pm tomorrow?")
    assert "you are free for 30 minutes" in answer


def test_an_event_marked_free_and_a_cancelled_one_do_not_block_and_an_all_day_busy_one_does(config, calendar):
    calendar.events.clear()
    day = datetime.now().astimezone().date() + timedelta(days=1)
    calendar.add(event("evfree00001", "Birthday", stamp(datetime.combine(day, time(10)).astimezone()), 60, transparency="transparent"))
    answer, _ = cf.answer(config, "when am i free tomorrow?")
    assert "free 09:00-18:00" in answer
    calendar.add({"id": "evallday002", "etag": '"v1-evallday002"', "status": "confirmed", "summary": "Conference", "start": {"date": day.isoformat()}, "end": {"date": (day + timedelta(days=1)).isoformat()}, "organizer": {"self": True}})
    answer, _ = cf.answer(config, "when am i free tomorrow?")
    assert "no gap of 30 minutes" in answer and "Conference" in answer


def test_calendar_questions_say_when_the_calendar_is_not_connected_and_do_not_reach_google(config, calendar):
    diya_connectors.disconnect(config, cc.READER)
    answer, fine = cf.answer(config, "when am i free tomorrow?")
    assert "not connected" in answer and calendar.requests == []
    assert cf.answer(config, "when is my gym?") is None


def test_the_chat_answers_these_questions_from_the_calendar_with_no_model(config, calendar):
    agent = diya.Agent(config, client=FakeClient([]), action_kinds=[])
    answer, tools = agent.ask([{"role": "user", "content": "when is my dentist appointment?"}])
    assert "Dentist appointment" in answer and agent.client.chat_calls == []


# ---- the catalog and the switches ------------------------------------------------------------------------------------------------------------------

def test_every_kind_is_in_the_catalog_with_its_tier_and_none_can_be_done_straight_away():
    expected = {"propose_update_calendar_event": 2, "propose_cancel_calendar_event": 3, "propose_invite_calendar_event": 3, "propose_rsvp_calendar_event": 3, "propose_repeating_calendar_event": 2}
    assert {name: diya_catalog.CATALOG[name].tier for name in expected} == expected and {k.tool_name for k in cc.action_kinds()} == set(expected)
    assert not {k.name for k in cc.action_kinds()} & set(diya_autoapprove.AUTO_KINDS) and all(k.auto_ok is None for k in cc.action_kinds())
    assert all(diya_catalog.CATALOG[name].approval == "owner approves each action" for name in expected)


def test_the_models_tools_cannot_name_an_event_id_a_version_or_a_calendar():
    for kind in cc.action_kinds():
        assert not set(kind.tool["function"]["parameters"]["properties"]) & {"event_id", "etag", "calendar_id", "attendees", "send_updates"}, kind.name
