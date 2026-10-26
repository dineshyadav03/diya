"""Google writes (diya_google_write.py, docs/GOOGLE_WRITE_DESIGN.md), added 2026-10-18: an event on the calendar, a task in Google Tasks, a folder in Drive, a new Google Doc.

No test reaches the real Google: `httpx.request` is replaced by a stand-in Google that records every request and answers as scripted, and the sign-in is a stand-in token. What this proves: each is its own
connector with its own narrow scope and shares Google's client with Calendar and Gmail; each is proposed only when the message asks for exactly that thing, and only by the approval system (nothing is
sent while proposing or approving; only running sends, once); the time of an event is read by code from the person's own words and frozen when it is proposed, and a time the model made up is never taken;
a refusal Google gives is a failure with nothing done, a request that may have got through is "unknown" and is never sent again, and an event asked for twice is one event.
It does not prove that the real Google answers like the stand-in: nobody has connected these through it yet.
"""
import dataclasses
import json
import re
import types

import httpx
import pytest

import diya
import diya_actions
import diya_config
import diya_connector_tools
import diya_connectors
import diya_google_calendar as gcal
import diya_google_write as gw
import diya_intent
import diya_time
from diya_actions import ActionFailed, ActionUncertain, Actions, InvalidArgs
from diya_db import Store
from fakes import FakeClient, text_reply, tool_reply

CAL, TASKS, DRIVE = "google_calendar_edit", "google_tasks", "google_drive_files"
RLO = chr(0x202E)  # a right-to-left override: written as a number, so that this file holds no invisible character itself


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "connectors.log"), google_client_id="a-client-id", google_client_secret="a-client-secret",
    )


@pytest.fixture
def signed_in(config, monkeypatch):
    """All three connected, and Google's token refresh answered with a stand-in token."""
    for name in (CAL, TASKS, DRIVE):
        diya_connectors.store_token(config, name, f"refresh-{name}")
    monkeypatch.setattr(gcal, "access_token", lambda cfg, name: f"access-{name}")
    return config


def reply(status=200, body=None):
    return types.SimpleNamespace(status_code=status, json=lambda: body if body is not None else {})


class Google:
    """The stand-in: `answers` is a list of responses (or exceptions to raise), used in order; every request is recorded."""

    def __init__(self, monkeypatch, *answers):
        self.answers = list(answers)
        self.calls = []
        monkeypatch.setattr(gw.httpx, "request", self)

    def __call__(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json, "headers": headers, "timeout": timeout})
        answer = self.answers.pop(0) if self.answers else reply(200, {})
        if isinstance(answer, Exception):
            raise answer
        return answer


START = "2026-10-23T11:30:00Z"
EVENT = {"title": "AI study session", "when": "friday at 5pm", "start": START, "duration_minutes": 90}


def made_event(args=EVENT, **changes):
    body = {"id": gw.event_id(args), "status": "confirmed", "summary": args["title"], "htmlLink": "https://www.google.com/calendar/event?eid=abc"}
    body.update(changes)
    return reply(200, body)


def event_read_back(args=EVENT, **changes):
    """What Google says when the event is asked for again by its id."""
    body = {"id": gw.event_id(args), "status": "confirmed", "summary": args["title"], "start": {"dateTime": args["start"]}, "end": {"dateTime": "2026-10-23T13:00:00Z"},
            "htmlLink": "https://www.google.com/calendar/event?eid=abc"}
    body.update(changes)
    return reply(200, body)


def task_made(title="Renew pass", **changes):
    return reply(200, dict({"id": "task_ID_1234", "title": title, "webViewLink": "https://tasks.google.com/task/abc"}, **changes))


def task_read_back(title="Renew pass", **changes):
    return reply(200, dict({"id": "task_ID_1234", "title": title, "status": "needsAction", "webViewLink": "https://tasks.google.com/task/abc"}, **changes))


def folder_made(name="Exams", **changes):
    return reply(200, dict({"id": "folder_ID_1234", "name": name, "mimeType": gw.FOLDER_TYPE, "webViewLink": "https://drive.google.com/drive/folders/1"}, **changes))


def doc_made(title="Plan", **changes):
    return reply(200, dict({"documentId": "doc_ID-1234567890", "title": title}, **changes))


def doc_read_back(title="Plan", text=None, **changes):
    content = [{"paragraph": {"elements": [{"textRun": {"content": text + "\n"}}]}}] if text else []
    return reply(200, dict({"documentId": "doc_ID-1234567890", "title": title, "body": {"content": content}}, **changes))


# ---- the registry -------------------------------------------------------------------------------------------------------------------------

def test_there_are_three_connectors_each_with_its_own_narrow_scope_and_googles_one_client(config):
    found = {c.name: c for c in gw.connectors()}
    assert set(found) == {CAL, TASKS, DRIVE} and all(c.implemented and c.auth_kind == "oauth" and c.oauth_connect for c in found.values())
    assert {n: gw.GOOGLE_WRITE[n][2] for n in found} == {
        CAL: "https://www.googleapis.com/auth/calendar.events", TASKS: "https://www.googleapis.com/auth/tasks", DRIVE: "https://www.googleapis.com/auth/drive.file",
    }
    assert all(c.setup.state is gcal.client_state and c.setup.save is gcal.save_client and c.setup.fields == gcal.SETUP.fields for c in found.values())
    assert all(any(gw.GOOGLE_WRITE[n][3].split(" and ")[0] in step for step in found[n].setup.steps) for n in found)  # the steps name the API to switch on


@pytest.mark.parametrize("name", [CAL, TASKS, DRIVE])
def test_connecting_asks_google_for_that_one_scope_and_stores_the_token_under_its_own_name(config, name):
    asked = []

    def browser(url):
        asked.append(url)
        raise diya_connectors.ConnectorError("stop here")

    with pytest.raises(diya_connectors.ConnectorError, match="stop here"):
        gw.connector_for(name).oauth_connect(config, browser)
    assert gw.GOOGLE_WRITE[name][2].replace(":", "%3A").replace("/", "%2F") in asked[0]


def test_the_real_registry_has_every_kind_and_each_tool_only_proposes():
    kinds = {k.name: k for k in diya_connector_tools.real_action_kinds()}
    assert {n: (k.connector, k.tool_name) for n, k in kinds.items() if n in ("google_calendar_add_event", "google_tasks_add", "google_drive_make_folder", "google_docs_create")} == {
        "google_calendar_add_event": (CAL, "propose_calendar_event"), "google_tasks_add": (TASKS, "propose_google_task"),
        "google_drive_make_folder": (DRIVE, "propose_drive_folder"), "google_docs_create": (DRIVE, "propose_google_doc"),
    }  # the first four Google kinds, unchanged (the kinds that change what is already there: docs/GOOGLE_CHANGES.md, tests/test_google_tasks_changes.py)
    for kind in gw.action_kinds():
        function = kind.tool["function"]
        assert "only PROPOSES" in function["description"] and "approves it on the Actions page" in function["description"]
        assert kind.asked is not None
    assert len({k.tool_name for k in diya_connector_tools.real_action_kinds()}) == len(diya_connector_tools.real_action_kinds())


def test_the_read_tool_is_offered_only_for_google_tasks_and_has_its_own_name():
    ((connector, spec, func),) = gw.read_tool_specs(None)
    assert connector == TASKS and spec["function"]["name"] == "list_google_tasks" and callable(func)


def test_forgetting_googles_client_signs_out_every_google_connector_that_used_it(config):
    for name in gcal.SHARING_CLIENT:
        diya_connectors.store_token(config, name, "t")
    gcal.save_client(config, {"client_id": "x" * 10 + ".apps.googleusercontent.com", "client_secret": "s" * 12})
    assert gcal.clear_client(config) is True
    assert not any(diya_connectors.is_connected(config, name) for name in gcal.SHARING_CLIENT)


# ---- which messages ask for which --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "put the dentist on my calendar for friday at 5pm", "add a study session to my calendar tomorrow at 6pm", "schedule a meeting with Sam tomorrow at 10am", "Please book an appointment for monday at 9am",
    "can you add an exam to my google calendar on friday at 10am",
])
def test_these_ask_for_a_calendar_event(text):
    assert diya_intent.asks_to_add_calendar_event(text)


@pytest.mark.parametrize("text", [
    "I wonder what is on my calendar tomorrow?", "show me my calendar", "remind me to call mum tomorrow at 5pm", "how do I add an event to my calendar", "don't add it to my calendar", "I have a meeting tomorrow",
    "my calendar is full", "", None, 5,
])
def test_these_do_not(text):
    assert not diya_intent.asks_to_add_calendar_event(text)


@pytest.mark.parametrize("text", ["add buy milk to my Google Tasks", "Create a task in Google Tasks to renew the bus pass", "put call the bank on google tasks"])
def test_these_ask_for_a_google_task(text):
    assert diya_intent.asks_for_google_task(text) and diya_intent.names_google_tasks(text)


@pytest.mark.parametrize("text", ["add buy milk to my tasks", "what is in my Google Tasks?", "how do I add a task in Google Tasks", "never add that to Google Tasks", "add task call mum"])
def test_these_do_not_ask_for_a_google_task(text):
    assert not diya_intent.asks_for_google_task(text)


@pytest.mark.parametrize("text", ["make a folder called Exams in my Google Drive", "create a new folder named Notes on my drive", "Add a folder for semester 3 to Drive"])
def test_these_ask_for_a_drive_folder(text):
    assert diya_intent.asks_for_drive_folder(text)


@pytest.mark.parametrize("text", ["make a folder called Exams", "what folders are in my drive", "how do I make a folder in Drive", "I have a folder in my drive"])
def test_these_do_not_ask_for_a_drive_folder(text):
    assert not diya_intent.asks_for_drive_folder(text)


@pytest.mark.parametrize("text", ["create a Google Doc called Study plan", "make a new google doc for my notes", "Please add a Google Document titled Plan"])
def test_these_ask_for_a_google_doc(text):
    assert diya_intent.asks_for_google_doc(text)


@pytest.mark.parametrize("text", ["write me a document about owls", "open my google doc", "what is a google doc", "create a note"])
def test_these_do_not_ask_for_a_google_doc(text):
    assert not diya_intent.asks_for_google_doc(text)


# ---- the arguments and the sentence the owner approves ---------------------------------------------------------------------------------------

def test_an_event_needs_a_title_and_a_start_and_its_sentence_says_when_and_that_nobody_is_invited():
    gw.event_validate(EVENT)
    line = gw.event_render(EVENT)
    assert line == f"Add to your Google Calendar: AI study session, {diya_time.describe_local(diya_time.local_from_iso(START))}, for 90 minutes (just you: nobody is invited)"


@pytest.mark.parametrize("args, why", [
    ({"title": "x"}, "needs the time it starts"), ({"title": "x", "start": "tomorrow"}, "needs the time it starts"), ({"title": "", "start": START}, "needs a name"),
    ({"title": "x", "start": "2026-13-45T99:00:00Z"}, "not a time"), ({"title": "x", "start": START, "duration_minutes": 1}, "between 5 and 1440"),
    ({"title": "x", "start": START, "duration_minutes": True}, "between 5 and 1440"), ({"title": "x", "start": START, "duration_minutes": 1441}, "between 5 and 1440"),
    ({"title": "x", "start": START, "attendees": ["a@b.c"]}, "has no attendees"), ({"title": "x" * 121, "start": START}, "at most 120"),
    ({"title": "a" + RLO + "b", "start": START}, "one plain line"),
])
def test_an_event_that_is_not_valid_says_why(args, why):
    with pytest.raises(InvalidArgs, match=why):
        gw.event_validate(args)


def test_nobody_can_be_invited_through_the_arguments():
    assert "attendees" not in json.dumps(gw.event_kind().tool) and "guests" not in json.dumps(gw.event_kind().tool)


@pytest.mark.parametrize("check, args, why", [
    (gw.task_validate, {"title": "x", "due": "friday"}, "must be a date"), (gw.task_validate, {"title": "x", "notes": "n" * 501}, "at most 500"), (gw.task_validate, {"title": "x", "list": "other"}, "has no list"),
    (gw.folder_validate, {"name": "a/b"}, "cannot have"), (gw.folder_validate, {"name": ""}, "needs a name"), (gw.folder_validate, {"name": "x", "parent": "root"}, "has no parent"),
    (gw.doc_validate, {"title": "x", "body": "b" * (gw.BODY_MAX + 1)}, "at most 3000"), (gw.doc_validate, {"title": "x", "share": "all"}, "has no share"),
])
def test_the_other_kinds_refuse_what_they_do_not_have(check, args, why):
    with pytest.raises(InvalidArgs, match=why):
        check(args)


def test_the_longest_of_each_still_fits_in_the_sentence_the_store_allows(signed_in):
    actions = Actions(Store(signed_in.db_path), signed_in, gw.action_kinds())
    longest = [
        ("google_calendar_add_event", {"title": "t" * 120, "start": START, "duration_minutes": 1440, "when": "w" * 100}),
        ("google_tasks_add", {"title": "t" * 120, "notes": "n" * 500, "due": "2026-10-23"}),
        ("google_drive_make_folder", {"name": "f" * 120}),
        ("google_docs_create", {"title": "t" * 120, "body": "b" * 3000}),
    ]
    for kind, args in longest:
        assert len(actions.propose(kind, args)["summary"]) <= diya_actions.MAX_SUMMARY_CHARS


def test_a_documents_sentence_shows_the_start_of_its_text_and_says_when_there_is_none():
    assert gw.doc_render({"title": "Plan"}) == "Make a new Google Doc called Plan, empty"
    shown = gw.doc_render({"title": "Plan", "body": "b" * 500})
    assert shown.endswith("..." ) and shown.count("b") == gw.SHOWN_BODY


# ---- the time of an event is the person's -------------------------------------------------------------------------------------------------

def test_a_time_the_person_said_is_read_by_code_and_frozen_with_a_note_to_check_it():
    args, notes = gw.event_prepare({"title": "Dentist", "when": "friday at 5pm"}, "put the dentist on my calendar for friday at 5pm")
    assert args["start"] == diya_time.parse_when("friday at 5pm").iso() and args["when"] == "friday at 5pm" and args["title"] == "Dentist"
    assert len(notes) == 1 and notes[0].startswith("Read as ") and "tell the user" in notes[0]


def test_a_time_the_model_made_up_is_not_taken_and_the_model_is_told_it_has_none():
    args, notes = gw.event_prepare({"title": "Dentist", "when": "tomorrow at 5pm"}, "put the dentist on my calendar")
    assert args == {"title": "Dentist"} and notes and notes[0].startswith("It has no time")
    with pytest.raises(InvalidArgs):
        gw.event_validate(args)


def test_a_start_the_model_worked_out_itself_is_never_taken():
    args, notes = gw.event_prepare({"title": "Dentist", "start": START}, "put the dentist on my calendar for friday at 5pm")
    assert "start" not in args and notes[0].startswith("It has no time")


def test_a_time_that_leaves_out_the_day_the_person_said_is_not_taken():
    args, notes = gw.event_prepare({"title": "Dentist", "when": "5pm"}, "put the dentist on my calendar for friday at 5pm")
    assert "start" not in args and "leaves out" in notes[0]


def test_words_that_are_not_a_time_are_not_one():
    args, notes = gw.event_prepare({"title": "Dentist", "when": "soon"}, "put the dentist on my calendar soon")
    assert "start" not in args and notes[0].startswith("It has no time")


def test_a_task_due_day_is_the_persons_or_left_out():
    args, notes = gw.task_prepare({"title": "x", "due": "friday"}, "add x to my Google Tasks for friday")
    assert args["due"] == diya_time.parse_when("friday").local.strftime("%Y-%m-%d") and notes == []
    args, notes = gw.task_prepare({"title": "x", "due": "tomorrow"}, "add x to my Google Tasks")
    assert args == {"title": "x"} and "left out" in notes[0]
    assert gw.task_prepare({"title": "x"}, "anything") == ({"title": "x"}, [])


def test_the_event_id_is_made_from_the_request_and_is_one_google_accepts():
    one, same, other = gw.event_id(EVENT), gw.event_id(dict(EVENT)), gw.event_id(dict(EVENT, duration_minutes=60))
    assert one == same != other and re.fullmatch(r"[0-9a-v]{5,1024}", one)


# ---- running them: what is sent ----------------------------------------------------------------------------------------------------------

def test_an_event_is_sent_to_the_primary_calendar_with_nobody_invited_and_no_mail_sent(signed_in, monkeypatch):
    google = Google(monkeypatch, made_event(), event_read_back())
    said = gw.event_execute(signed_in, EVENT)
    call, check = google.calls
    assert (check["method"], check["url"]) == ("GET", f"{gw.CALENDAR_API}/{gw.event_id(EVENT)}")  # asked for again by its id: the answer to the write is not taken as proof
    assert call["method"] == "POST" and call["url"] == gw.CALENDAR_API and call["params"] == {"sendUpdates": "none"}
    assert call["headers"] == {"Authorization": f"Bearer access-{CAL}"} and call["timeout"] == gw.NETWORK_TIMEOUT
    assert call["json"] == {
        "id": gw.event_id(EVENT), "summary": "AI study session", "start": {"dateTime": START, "timeZone": "UTC"}, "end": {"dateTime": "2026-10-23T13:00:00Z", "timeZone": "UTC"},
    }
    assert "attendees" not in call["json"]
    assert said.startswith("Added to your Google Calendar and read back to check: AI study session") and "for 90 minutes" in said and "https://www.google.com/calendar/event?eid=abc" in said


def test_an_event_that_is_already_there_from_an_earlier_try_is_not_made_twice(signed_in, monkeypatch):
    google = Google(monkeypatch, reply(409, {"error": {"message": "The requested identifier already exists."}}), reply(200, {"id": gw.event_id(EVENT), "status": "confirmed", "summary": "AI study session"}))
    said = gw.event_execute(signed_in, EVENT)
    assert said.startswith("That event was already on your calendar") and [c["method"] for c in google.calls] == ["POST", "GET"]
    assert google.calls[1]["url"] == f"{gw.CALENDAR_API}/{gw.event_id(EVENT)}"


def test_an_event_that_was_added_and_then_deleted_is_a_failure_that_says_what_to_change(signed_in, monkeypatch):
    Google(monkeypatch, reply(409), reply(200, {"status": "cancelled", "summary": "AI study session"}))
    with pytest.raises(ActionFailed, match="added before and then deleted.*Change the title"):
        gw.event_execute(signed_in, EVENT)


def test_an_id_that_belongs_to_a_different_event_is_a_failure(signed_in, monkeypatch):
    Google(monkeypatch, reply(409), reply(200, {"status": "confirmed", "summary": "Something else"}))
    with pytest.raises(ActionFailed, match="not this one"):
        gw.event_execute(signed_in, EVENT)


@pytest.mark.parametrize("body", [{}, {"id": "other", "status": "confirmed"}, {"status": "cancelled"}, ["not", "a", "dict"]])
def test_an_answer_that_is_not_the_event_leaves_it_unknown(signed_in, monkeypatch, body):
    Google(monkeypatch, reply(200, body))
    with pytest.raises(ActionUncertain, match="may or may not be on your calendar"):
        gw.event_execute(signed_in, EVENT)


def test_a_task_is_sent_with_its_notes_and_due_day_only_when_there_are_some(signed_in, monkeypatch):
    google = Google(monkeypatch, task_made(), task_read_back(due="2026-10-23T00:00:00.000Z"), task_made("Plain"), task_read_back("Plain"))
    said = gw.task_execute(signed_in, {"title": "Renew pass", "notes": "bring the id", "due": "2026-10-23"})
    gw.task_execute(signed_in, {"title": "Plain"})
    assert google.calls[0]["url"] == gw.TASKS_API and google.calls[0]["json"] == {"title": "Renew pass", "notes": "bring the id", "due": "2026-10-23T00:00:00.000Z"}
    assert (google.calls[1]["method"], google.calls[1]["url"]) == ("GET", f"{gw.TASKS_API}/task_ID_1234")
    assert google.calls[2]["json"] == {"title": "Plain"} and google.calls[0]["headers"] == {"Authorization": f"Bearer access-{TASKS}"}
    assert said == "Added to your Google Tasks and read back to check: Renew pass. https://tasks.google.com/task/abc"


def test_a_task_answer_that_is_not_the_task_leaves_it_unknown(signed_in, monkeypatch):
    Google(monkeypatch, reply(200, {"title": "another"}))
    with pytest.raises(ActionUncertain, match="may or may not be in your list"):
        gw.task_execute(signed_in, {"title": "Renew pass"})


def test_a_folder_is_made_at_the_top_of_drive_and_nothing_is_shared(signed_in, monkeypatch):
    google = Google(monkeypatch, folder_made(), folder_made(trashed=False))
    said = gw.folder_execute(signed_in, {"name": "Exams"})
    call, check = google.calls
    assert (check["method"], check["url"]) == ("GET", f"{gw.DRIVE_API}/folder_ID_1234")
    assert call["url"] == gw.DRIVE_API and call["json"] == {"name": "Exams", "mimeType": gw.FOLDER_TYPE} and "parents" not in call["json"] and "permissions" not in call["json"]
    assert said == "Made the folder Exams in your Google Drive and read it back to check. https://drive.google.com/drive/folders/1"


def test_a_folder_answer_that_is_not_the_folder_leaves_it_unknown(signed_in, monkeypatch):
    Google(monkeypatch, reply(200, {"name": "Exams", "mimeType": "text/plain"}))
    with pytest.raises(ActionUncertain, match="may or may not be in your Drive"):
        gw.folder_execute(signed_in, {"name": "Exams"})


def test_a_document_is_made_then_given_its_text_and_its_address_is_built_by_code(signed_in, monkeypatch):
    google = Google(monkeypatch, doc_made(), reply(200, {}), doc_read_back(text="Week one: revise maths"))
    said = gw.doc_execute(signed_in, {"title": "Plan", "body": "Week one: revise maths"})
    assert [c["url"] for c in google.calls] == [gw.DOCS_API, f"{gw.DOCS_API}/doc_ID-1234567890:batchUpdate", f"{gw.DOCS_API}/doc_ID-1234567890"]
    assert google.calls[0]["json"] == {"title": "Plan"}
    assert google.calls[1]["json"] == {"requests": [{"insertText": {"location": {"index": 1}, "text": "Week one: revise maths"}}]}
    assert said == "Made the Google Doc Plan and read it back to check. https://docs.google.com/document/d/doc_ID-1234567890/edit"


def test_a_document_with_no_text_is_one_write_and_a_read_back(signed_in, monkeypatch):
    google = Google(monkeypatch, doc_made(), doc_read_back())
    gw.doc_execute(signed_in, {"title": "Plan"})
    assert [c["method"] for c in google.calls] == ["POST", "GET"]


def test_a_document_whose_text_could_not_be_put_in_is_unknown_and_says_where_it_is(signed_in, monkeypatch):
    Google(monkeypatch, reply(200, {"documentId": "doc_ID-1234567890", "title": "Plan"}), reply(403, {"error": {"message": "Docs API has not been used"}}))
    with pytest.raises(ActionUncertain, match="was made but its text could not be put in it.*Docs API has not been used.*docs.google.com/document/d/doc_ID-1234567890/edit"):
        gw.doc_execute(signed_in, {"title": "Plan", "body": "text"})


@pytest.mark.parametrize("answer", [{"documentId": "../../x", "title": "Plan"}, {"documentId": "short", "title": "Plan"}, {"documentId": "doc_ID-1234567890", "title": "Other"}, {}])
def test_a_document_answer_that_is_not_a_document_leaves_it_unknown_and_builds_no_address(signed_in, monkeypatch, answer):
    Google(monkeypatch, reply(200, answer))
    with pytest.raises(ActionUncertain, match="may or may not be in your Drive"):
        gw.doc_execute(signed_in, {"title": "Plan"})


# ---- running them: what goes wrong -----------------------------------------------------------------------------------------------------

def test_with_nothing_connected_nothing_is_sent(config, monkeypatch):
    google = Google(monkeypatch)
    with pytest.raises(ActionFailed, match="Google Calendar \\(add events\\) is not connected, so nothing was done"):
        gw.event_execute(config, EVENT)
    assert google.calls == []


def test_a_sign_in_google_no_longer_accepts_is_a_failure_that_says_to_connect_again(config, monkeypatch):
    diya_connectors.store_token(config, TASKS, "refresh")
    monkeypatch.setattr(gcal, "access_token", lambda cfg, name: None)
    google = Google(monkeypatch)
    with pytest.raises(ActionFailed, match="did not accept the sign-in.*Connect it again"):
        gw.task_execute(config, {"title": "x"})
    assert google.calls == []


@pytest.mark.parametrize("status", [401, 403])
def test_a_refusal_is_a_failure_that_gives_googles_reason_and_says_nothing_was_done(signed_in, monkeypatch, status):
    Google(monkeypatch, reply(status, {"error": {"message": "Google Tasks API has not been used in project 1 before or it is disabled."}}))
    with pytest.raises(ActionFailed, match="Google refused \\(Google Tasks API has not been used.*\\), so nothing was done.*API is switched on"):
        gw.task_execute(signed_in, {"title": "x"})


def test_a_reason_google_gives_cannot_carry_control_characters_into_what_the_owner_reads(signed_in, monkeypatch):
    Google(monkeypatch, reply(403, {"error": {"message": "bad\nline" + RLO}}))
    with pytest.raises(ActionFailed) as caught:
        gw.task_execute(signed_in, {"title": "x"})
    assert "\n" not in str(caught.value) and RLO not in str(caught.value) and "bad line" in str(caught.value)


def test_being_rate_limited_is_a_failure_that_says_to_ask_again(signed_in, monkeypatch):
    Google(monkeypatch, reply(429))
    with pytest.raises(ActionFailed, match="limiting requests right now, so nothing was done"):
        gw.folder_execute(signed_in, {"name": "x"})


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_failure_on_googles_side_leaves_it_unknown(signed_in, monkeypatch, status):
    Google(monkeypatch, reply(status))
    with pytest.raises(ActionUncertain, match=f"HTTP {status}.*may or may not have been done"):
        gw.folder_execute(signed_in, {"name": "x"})


@pytest.mark.parametrize("status", [400, 404, 418])
def test_any_other_refusal_is_a_failure_that_names_the_status(signed_in, monkeypatch, status):
    Google(monkeypatch, reply(status))
    with pytest.raises(ActionFailed, match=f"HTTP {status}, so nothing was done"):
        gw.folder_execute(signed_in, {"name": "x"})


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow"), httpx.PoolTimeout("busy"), httpx.UnsupportedProtocol("odd")])
def test_a_request_that_was_never_sent_is_a_failure(signed_in, monkeypatch, error):
    Google(monkeypatch, error)
    with pytest.raises(ActionFailed, match="Couldn't reach Google.*so nothing was done"):
        gw.task_execute(signed_in, {"title": "x"})


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.WriteError("cut"), httpx.RemoteProtocolError("hung up"), httpx.DecodingError("garbled")])
def test_a_request_that_may_have_reached_google_leaves_it_unknown(signed_in, monkeypatch, error):
    Google(monkeypatch, error)
    with pytest.raises(ActionUncertain, match="sent to Google but no answer came back.*may or may not have been done"):
        gw.task_execute(signed_in, {"title": "x"})


# ---- the whole flow, through the approval system --------------------------------------------------------------------------------------

def test_proposing_and_approving_send_nothing_and_running_sends_exactly_once(signed_in, monkeypatch):
    google = Google(monkeypatch, made_event(), event_read_back())
    actions = Actions(Store(signed_in.db_path), signed_in, gw.action_kinds())
    action = actions.propose("google_calendar_add_event", EVENT)
    assert google.calls == [] and action["summary"] == gw.event_render(EVENT)
    actions.approve(action["id"], action["args_hash"], "ui")
    assert google.calls == []
    done = actions.run(action["id"])
    assert done["status"] == "succeeded" and done["result"].startswith("Added to your Google Calendar") and [c["method"] for c in google.calls] == ["POST", "GET"]  # one write, one read back
    assert actions.verify_integrity() == []
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(action["id"])
    assert len(google.calls) == 2


def test_an_event_whose_request_may_have_got_through_is_unknown_and_is_never_sent_again(signed_in, monkeypatch):
    google = Google(monkeypatch, httpx.ReadTimeout(""))
    actions = Actions(Store(signed_in.db_path), signed_in, gw.action_kinds())
    action = actions.propose("google_calendar_add_event", EVENT)
    actions.approve(action["id"], action["args_hash"], "cli")
    done = actions.run(action["id"])
    assert done["status"] == "unknown" and "may or may not have been done" in done["result"]
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(action["id"])
    assert len(google.calls) == 1
    assert actions.resolve(action["id"], True, "cli", note="it is on my calendar")["status"] == "succeeded" and len(google.calls) == 1


def test_a_changed_event_is_not_what_was_approved(signed_in, monkeypatch):
    Google(monkeypatch, made_event())
    actions = Actions(Store(signed_in.db_path), signed_in, gw.action_kinds())
    action = actions.propose("google_calendar_add_event", EVENT)
    other = actions.propose("google_calendar_add_event", dict(EVENT, start="2026-10-24T11:30:00Z"))
    assert other["args_hash"] != action["args_hash"]
    with pytest.raises(diya_actions.HashMismatch):
        actions.approve(action["id"], other["args_hash"], "ui")


def test_disconnecting_between_proposing_and_approving_stops_it_before_anything_is_sent(signed_in, monkeypatch):
    google = Google(monkeypatch, reply(200, {"title": "x"}))
    actions = Actions(Store(signed_in.db_path), signed_in, gw.action_kinds())
    action = actions.propose("google_tasks_add", {"title": "x"})
    actions.approve(action["id"], action["args_hash"], "ui")
    diya_connectors.disconnect(signed_in, TASKS)
    done = actions.run(action["id"])
    assert done["status"] == "failed" and "no longer connected" in done["result"] and google.calls == []


def test_none_can_be_proposed_while_its_connector_is_not_connected(config):
    actions = Actions(Store(config.db_path), config, gw.action_kinds())
    for kind, args in (("google_calendar_add_event", EVENT), ("google_tasks_add", {"title": "x"}), ("google_drive_make_folder", {"name": "x"}), ("google_docs_create", {"title": "x"})):
        with pytest.raises(diya_actions.NotConnected):
            actions.propose(kind, args)


# ---- through the agent: the model can only propose, and only what was asked --------------------------------------------------------------

def ask(config, message, name, arguments):
    """The real Agent and the real kinds, a scripted model that proposes `arguments` whatever it is asked. Returns (the agent, what the model was told back by the tool)."""
    agent = diya.Agent(config, client=FakeClient([tool_reply(name, json.dumps(arguments)), text_reply("ok")]))
    agent.ask([{"role": "user", "content": message}])
    told = [m["content"] for m in agent.client.chat_calls[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"][-1]
    return agent, told


def test_an_event_the_person_asked_for_is_proposed_with_the_time_read_from_their_words_and_nothing_is_sent(signed_in, monkeypatch):
    google = Google(monkeypatch)
    agent, told = ask(signed_in, "put the dentist on my calendar for friday at 5pm", "propose_calendar_event", {"title": "Dentist", "when": "friday at 5pm"})
    (action,) = agent.actions.actions()
    assert action["args"]["start"] == diya_time.parse_when("friday at 5pm").iso() and action["summary"] == gw.event_render(action["args"])
    assert told.startswith("Proposed as action #1:") and "Read as " in told and "Nothing has happened yet" in told
    assert google.calls == []


def test_a_time_the_model_made_up_means_no_card_and_the_model_is_told_to_ask(signed_in, monkeypatch):
    google = Google(monkeypatch)
    agent, told = ask(signed_in, "put the dentist on my calendar", "propose_calendar_event", {"title": "Dentist", "when": "tomorrow at 5pm"})
    assert agent.actions.actions() == [] and told.startswith("Not proposed: an event needs the time it starts") and "ask them when" in told and google.calls == []


@pytest.mark.parametrize("message", ["I wonder what is on my calendar tomorrow?", "remind me to see the dentist tomorrow at 5pm", "I have a dentist appointment on friday", "how do I add an event to my calendar"])
def test_a_message_that_does_not_ask_for_an_event_gets_none_proposed(signed_in, message):
    agent, told = ask(signed_in, message, "propose_calendar_event", {"title": "Dentist", "when": "friday at 5pm"})
    assert agent.actions.actions() == [] and told == diya_actions.NOT_ASKED_TEXT


def test_a_task_that_names_google_tasks_is_proposed_there_and_not_added_to_dias_own_list(signed_in):
    agent, told = ask(signed_in, "add renew the bus pass to my Google Tasks", "propose_google_task", {"title": "Renew the bus pass"})
    assert [a["summary"] for a in agent.actions.actions()] == ["Add to your Google Tasks: Renew the bus pass"] and agent.tasks.tasks("open") == []
    own, said = ask(signed_in, "add renew the bus pass to my Google Tasks", "add_task", {"content": "Renew the bus pass"})
    assert said == diya.TASK_IS_GOOGLES and own.tasks.tasks("open") == [] and len(own.actions.actions()) == 1  # the one proposed above, nothing new
    again, said = ask(signed_in, "add a task to Google Tasks to renew the bus pass", "add_task", {"content": "Renew the bus pass"})
    assert said == diya.TASK_IS_GOOGLES and again.tasks.tasks("open") == []


def test_a_due_day_the_model_made_up_is_left_off_a_google_task(signed_in):
    agent, told = ask(signed_in, "add renew the bus pass to my Google Tasks", "propose_google_task", {"title": "Renew the bus pass", "due": "tomorrow"})
    (action,) = agent.actions.actions()
    assert "due" not in action["args"] and "left out" in told


def test_a_folder_and_a_document_are_proposed_only_when_asked_for(signed_in):
    folder, told = ask(signed_in, "make a folder called Exams in my Google Drive", "propose_drive_folder", {"name": "Exams"})
    assert [a["summary"] for a in folder.actions.actions()] == ["Make a folder in your Google Drive: Exams (at the top of My Drive)"]
    nothing, told = ask(signed_in, "what is in my drive", "propose_drive_folder", {"name": "Exams"})
    assert len(nothing.actions.actions()) == 1 and told == diya_actions.NOT_ASKED_TEXT  # still only the folder above
    doc, told = ask(signed_in, "create a Google Doc called Study plan", "propose_google_doc", {"title": "Study plan"})
    assert [a["summary"] for a in doc.actions.actions()][-1] == "Make a new Google Doc called Study plan, empty" and len(doc.actions.actions()) == 2


def test_the_model_is_shown_only_the_tools_of_what_is_connected(config):
    agent = diya.Agent(config, client=FakeClient())
    names = lambda: {t["function"]["name"] for t in agent.tools}  # noqa: E731
    assert not names() & {"propose_calendar_event", "propose_google_task", "propose_drive_folder", "propose_google_doc", "list_google_tasks"}
    diya_connectors.store_token(config, CAL, "t")
    assert "propose_calendar_event" in names() and "propose_google_task" not in names()
    diya_connectors.store_token(config, TASKS, "t")
    assert {"propose_google_task", "list_google_tasks"} <= names()
    diya_connectors.store_token(config, DRIVE, "t")
    assert {"propose_drive_folder", "propose_google_doc"} <= names()
    diya_connectors.disconnect(config, CAL)
    assert "propose_calendar_event" not in names()


# ---- the read side ----------------------------------------------------------------------------------------------------------------------

def test_the_open_google_tasks_are_listed_with_their_due_days(signed_in, monkeypatch):
    seen = []

    def get(url, params=None, headers=None, timeout=None):
        seen.append((url, params, headers))
        return reply(200, {"items": [{"title": "Renew pass", "due": "2026-10-23T00:00:00.000Z"}, {"title": "Plain"}]})

    monkeypatch.setattr(gw.httpx, "get", get)
    assert gw.google_tasks_list(signed_in)() == "Renew pass (due 2026-10-23)\nPlain"
    assert seen[0][0] == gw.TASKS_API and seen[0][2] == {"Authorization": f"Bearer access-{TASKS}"} and seen[0][1]["showCompleted"] == "false"


def test_the_list_says_so_when_nothing_is_connected_or_google_cannot_be_reached(config, signed_in, monkeypatch):
    monkeypatch.setattr(gw.httpx, "get", lambda *a, **k: reply(200, {}))
    assert gw.google_tasks_list(signed_in)() == "No open tasks in Google Tasks."
    monkeypatch.setattr(gw.httpx, "get", lambda *a, **k: reply(500))
    assert gw.google_tasks_list(signed_in)() == "Google Tasks answered with HTTP 500."
    monkeypatch.setattr(gw.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("x")))
    assert gw.google_tasks_list(signed_in)().startswith("Couldn't reach Google Tasks")
    diya_connectors.disconnect(signed_in, TASKS)
    assert gw.google_tasks_list(signed_in)() == "Google Tasks is not connected."


# ---- where a request can go (DIYA-068) -------------------------------------------------------------------------------------------------------

def test_no_tool_lets_the_model_choose_a_host_a_url_or_a_token(config):
    """The model's only inputs are words: titles, times, names. Nothing it can say names an address, a header or a credential."""
    forbidden = {"url", "uri", "host", "endpoint", "token", "access_token", "refresh_token", "authorization", "headers", "api_key", "key", "secret", "base_url", "domain"}
    specs = [kind.tool for kind in gw.action_kinds()] + [spec for _name, spec, _func in gw.read_tool_specs(None)]
    assert len(specs) == 5
    for spec in specs:
        assert not forbidden & set(spec["function"]["parameters"]["properties"]), spec["function"]["name"]


def test_every_google_address_this_module_can_call_is_a_fixed_google_host():
    addresses = [gw.CALENDAR_API, gw.TASKS_API, gw.DRIVE_API, gw.DOCS_API]
    hosts = {a.split("/")[2] for a in addresses}
    assert hosts == {"www.googleapis.com", "tasks.googleapis.com", "docs.googleapis.com"} and all(a.startswith("https://") for a in addresses)


def test_an_address_built_from_what_google_answered_is_never_followed(signed_in, monkeypatch):
    """A link in Google's answer is shown to the person as text; the next request is always to the module's own address (a document's address is built from a checked id)."""
    google = Google(monkeypatch, doc_made(next="https://evil.example/steal"), reply(200, {}), doc_read_back(text="text"))
    gw.doc_execute(signed_in, {"title": "Plan", "body": "text"})
    assert all(call["url"].startswith(gw.DOCS_API) for call in google.calls)


# ---- the independent read-back (DIYA-052) -------------------------------------------------------------------------------------------------------

def test_a_write_counts_only_after_the_thing_is_asked_for_again_and_is_what_was_asked_for(signed_in, monkeypatch):
    """Google's answer to the write is not proof. Each kind asks for the new thing by its id, in a second request, and compares it with what the owner approved."""
    cases = [
        (gw.event_execute, EVENT, [made_event(), event_read_back()], 2), (gw.task_execute, {"title": "Renew pass"}, [task_made(), task_read_back()], 2),
        (gw.folder_execute, {"name": "Exams"}, [folder_made(), folder_made(trashed=False)], 2), (gw.doc_execute, {"title": "Plan"}, [doc_made(), doc_read_back()], 2),
    ]
    for function, args, answers, expected in cases:
        google = Google(monkeypatch, *answers)
        function(signed_in, args)
        assert [c["method"] for c in google.calls] == ["POST", "GET"] and len(google.calls) == expected


@pytest.mark.parametrize("changes, why", [
    ({"summary": "Something else"}, "a different title"), ({"start": {"dateTime": "2026-10-24T11:30:00Z"}}, "a different time"), ({"end": {"dateTime": "2026-10-23T12:00:00Z"}}, "a different time"),
    ({"status": "cancelled"}, "an event that is not on the calendar"), ({"attendees": [{"email": "someone@example.com"}]}, "guests, and nobody was to be invited"), ({"start": {}}, "a different time"),
])
def test_an_event_that_reads_back_differently_is_not_confirmed(signed_in, monkeypatch, changes, why):
    Google(monkeypatch, made_event(), event_read_back(**changes))
    with pytest.raises(ActionUncertain, match=f"reading it back showed {why}.*not confirmed.*Look in Google"):
        gw.event_execute(signed_in, EVENT)


def test_the_same_moment_in_another_offset_is_the_same_event(signed_in, monkeypatch):
    Google(monkeypatch, made_event(), event_read_back(start={"dateTime": "2026-10-23T17:00:00+05:30"}, end={"dateTime": "2026-10-23T18:30:00+05:30"}))
    assert gw.event_execute(signed_in, EVENT).startswith("Added to your Google Calendar and read back")


@pytest.mark.parametrize("answer", [reply(404, {"error": {"message": "Not Found"}}), reply(500), reply(200, {}), reply(403), httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
def test_a_read_back_that_fails_leaves_it_unknown_not_failed_and_not_succeeded(signed_in, monkeypatch, answer):
    """It may well be there: it is not confirmed. 'Unknown' means it is never sent again, and the person is told to look."""
    Google(monkeypatch, made_event(), answer)
    with pytest.raises(ActionUncertain, match="not confirmed|did not work|empty answer"):
        gw.event_execute(signed_in, EVENT)


@pytest.mark.parametrize("read_back, why", [
    (task_read_back("Another"), "a different task"), (task_read_back(status="completed"), "a task that is not open"), (task_read_back(deleted=True), "a different task"),
])
def test_a_task_that_reads_back_differently_is_not_confirmed(signed_in, monkeypatch, read_back, why):
    Google(monkeypatch, task_made(), read_back)
    with pytest.raises(ActionUncertain, match=f"reading it back showed {why}"):
        gw.task_execute(signed_in, {"title": "Renew pass"})


def test_a_task_due_day_that_does_not_read_back_is_not_confirmed(signed_in, monkeypatch):
    Google(monkeypatch, task_made(), task_read_back(due="2026-10-24T00:00:00.000Z"))
    with pytest.raises(ActionUncertain, match="a different due day"):
        gw.task_execute(signed_in, {"title": "Renew pass", "due": "2026-10-23"})


@pytest.mark.parametrize("made", [reply(200, {"title": "Renew pass"}), reply(200, {"id": "../../x", "title": "Renew pass"}), reply(200, {"id": "ab", "title": "Renew pass"})])
def test_a_write_that_gives_no_usable_id_cannot_be_checked_and_makes_no_second_request(signed_in, monkeypatch, made):
    google = Google(monkeypatch, made)
    with pytest.raises(ActionUncertain, match="no usable id to check it by"):
        gw.task_execute(signed_in, {"title": "Renew pass"})
    assert len(google.calls) == 1


@pytest.mark.parametrize("read_back, why", [
    (folder_made("Other"), "a different folder"), (folder_made(mimeType="text/plain"), "a different folder"), (folder_made(trashed=True), "a folder in the bin"),
])
def test_a_folder_that_reads_back_differently_is_not_confirmed(signed_in, monkeypatch, read_back, why):
    Google(monkeypatch, folder_made(), read_back)
    with pytest.raises(ActionUncertain, match=f"reading it back showed {why}"):
        gw.folder_execute(signed_in, {"name": "Exams"})


@pytest.mark.parametrize("read_back, why", [(doc_read_back("Other", text="Week one"), "a different title"), (doc_read_back(text="Something else entirely"), "the text missing"), (doc_read_back(), "the text missing")])
def test_a_document_that_reads_back_differently_is_not_confirmed(signed_in, monkeypatch, read_back, why):
    Google(monkeypatch, doc_made(), reply(200, {}), read_back)
    with pytest.raises(ActionUncertain, match=f"reading it back showed {why}"):
        gw.doc_execute(signed_in, {"title": "Plan", "body": "Week one"})


def test_a_read_back_failure_is_unknown_in_the_approval_system_and_is_never_run_again(signed_in, monkeypatch):
    google = Google(monkeypatch, made_event(), reply(500))
    actions = Actions(Store(signed_in.db_path), signed_in, gw.action_kinds())
    action = actions.propose("google_calendar_add_event", EVENT)
    actions.approve(action["id"], action["args_hash"], "ui")
    done = actions.run(action["id"])
    assert done["status"] == "unknown" and "not confirmed" in done["result"]
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(action["id"])
    assert len(google.calls) == 2  # the write and the one read back; nothing again


# ---- what the owner is told about the risk before approving (DIYA-048) -------------------------------------------------------------------------

def test_a_waiting_google_action_carries_its_risk_its_reach_and_how_far_it_can_be_undone(signed_in):
    from fastapi.testclient import TestClient

    import diya_web

    class Quiet:
        def transcribe(self, path):
            return ""

    config = dataclasses.replace(signed_in, require_token=False, profile_path=signed_in.db_path + ".p")
    agent = diya.Agent(config, client=FakeClient())
    agent.actions.propose("google_tasks_add", {"title": "Renew the bus pass"})
    agent.actions.propose("google_drive_make_folder", {"name": "Exams"})
    client = TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost")
    shown = {a["kind"]: a for a in client.get("/api/actions").json()["pending"]}
    tasks = shown["google_tasks_add"]["preview"]
    assert tasks["tier"] == 2 and "adds something private to the person's own account" in tasks["tier_words"]
    assert tasks["reaches"] == "tasks.googleapis.com (only when approved)" and tasks["undo"].startswith("by hand in Google Tasks") and tasks["uses"] == "Google Tasks connected"
    assert shown["google_drive_make_folder"]["preview"]["uses"] == "Google Drive and Docs connected"
