"""Google writes: Diya can ADD things to your Google account when you approve each one (docs/GOOGLE_WRITE_DESIGN.md).

Four things in this first round, all of them new, private and easy to take back by hand: an event on your calendar, a task in Google Tasks, a folder in your Drive, a new Google Doc. Not here yet, on purpose:
changing or deleting what is already there, sending mail, sharing anything with anybody.

Every one is an action in Diya's approval system (diya_actions, docs/ACTIONS_DESIGN.md), the same as the Todoist task, and so:

* the model can only PROPOSE it; nothing is done until the owner approves exactly what was shown, on the Actions page, and approval is bound to a hash of the exact request and lapses after a day;
* what the owner reads is built in code from the arguments, never from what the model said, and a time is read from the PERSON's own words by code (diya_time), fixed when it is proposed (so "tomorrow
  at 5pm" cannot mean a different day if it is approved the next day), and one the person did not say is not guessed;
* a refusal Google gives before anything happened is a failure; a request that may have reached Google, with no answer, is "unknown" and is never retried by itself (the calendar event carries an id made
  from the request, so asking again cannot make a second one);
* each service is its own connector with its own sign-in and its own narrow scope, added only when wanted: calendar.events, tasks and drive.file (only files Diya herself made: folders and documents).
  They share the Google client id and secret with Calendar and Gmail (diya_google_calendar).

None of it has been tried against a real Google account: the tests stand in for Google (tests/test_google_write.py). Importing this module has no side effects.
"""
from __future__ import annotations

import hashlib
import re
import webbrowser
from datetime import datetime, timedelta, timezone

import httpx

import diya_connectors
import diya_google_calendar
import diya_intent
import diya_memory
import diya_time
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

NETWORK_TIMEOUT = 15.0
TITLE_MAX = 120
NOTES_MAX = 500
BODY_MAX = 3000  # the approval system keeps the arguments to 4000 characters in all
SHOWN_BODY = 100  # how much of a document's text the owner is shown in the one sentence they approve (the description is at most 300 characters)
MINUTES = (5, 1440)

CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TASKS_PAGE = 25  # how many open tasks one look at the list asks for (one request; a longer list says it is longer)
TASKS_API ="https://tasks.googleapis.com/tasks/v1/lists/@default/tasks"
DRIVE_API = "https://www.googleapis.com/drive/v3/files"
DOCS_API = "https://docs.googleapis.com/v1/documents"
FOLDER_TYPE = "application/vnd.google-apps.folder"

# connector name -> (label, what it does, scope, the API(s) to switch on)
GOOGLE_WRITE = {
    "google_calendar_edit": ("Google Calendar (add events)", "Add events to your calendar, each one when you approve it.", "https://www.googleapis.com/auth/calendar.events", "Google Calendar API"),
    "google_tasks": ("Google Tasks", "List your Google Tasks and add one when you approve it.", "https://www.googleapis.com/auth/tasks", "Google Tasks API"),
    "google_drive_files": (
        "Google Drive and Docs (new things)", "Make a folder or a Google Doc when you approve it. Diya can only see what she made herself (the narrow drive.file scope).",
        "https://www.googleapis.com/auth/drive.file", "Google Drive API and Google Docs API",
    ),
}

# What cannot have reached Google: the request was never sent. Anything else that goes wrong on the way may have been.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)
_ISO_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DOC_ID = re.compile(r"[A-Za-z0-9_-]{10,100}")


# ---- the sign-in and the request ---------------------------------------------------------------------------------------------------------

def _steps(api, scope):
    return (
        "Use the same Google Cloud project as for Calendar (console.cloud.google.com).",
        f"APIs & Services, Library: search for {api} and press Enable (each one).",
        f"OAuth consent screen (Google Auth platform), Data access: add the scope {scope}. Your own address is already a test user; keep Publishing status on In production.",
        "The Client ID and secret are shared with Calendar and Gmail: if you pasted them for those, just press Connect.",
    )


ACCESS = {
    "google_calendar_edit": ("Adds an event, just for you, to your calendar, but only when you approve that one event.", "Cannot invite anyone, and cannot change or delete events."),
    "google_tasks": ("Lists your open Google Tasks.", "Adds a task, but only when you approve that one task.", "Cannot complete, change or delete tasks."),
    "google_drive_files": ("Makes a folder or a new Google Doc, but only when you approve that one.", "Can see only the files and folders Diya made herself, never the rest of your Drive.", "Cannot share, move or delete anything."),
}


def connector_for(name):
    """The Connector for one of them (the Connections page offers it; docs/CONNECTORS_DESIGN.md)."""
    label, description, scope, api = GOOGLE_WRITE[name]

    def connect(config, open_browser=None):
        return diya_google_calendar.connect_to(config, scope, name, open_browser or webbrowser.open)

    setup = diya_connectors.Setup(
        fields=diya_google_calendar.SETUP.fields, steps=_steps(api, scope), state=diya_google_calendar.client_state, save=diya_google_calendar.save_client, clear=diya_google_calendar.clear_client
    )
    return diya_connectors.Connector(name=name, label=label, description=description, auth_kind="oauth", implemented=True, oauth_connect=connect, setup=setup, revoke=diya_google_calendar.revoke_for(name), scope=scope, access=ACCESS[name])


def connectors():
    return tuple(connector_for(name) for name in GOOGLE_WRITE)


def _reason(response):
    """What Google said was wrong, in one short plain line (its own `message`), or ''."""
    try:
        message = (response.json().get("error") or {}).get("message")
    except (ValueError, AttributeError):
        return ""
    return diya_memory.printable(message, 160) if isinstance(message, str) else ""


# What an approved action may ask Google for, as code and not as a habit (DIYA-040). The account is the one connected under that connector's own name; the resource is only ever the primary calendar, the default
# task list, Drive's top level and Docs as listed here (a calendar id, a task list, a share or a person's address cannot appear in a request); the operation is one of these methods. Anything else is refused
# before a token is fetched or a byte is sent. There is no recipient list because nothing Diya does reaches another person (no invitation, no share, no mail).
_ID = "[A-Za-z0-9_-]{5,128}"
_PERMITTED = tuple((connector, method, re.compile(pattern)) for connector, method, pattern in (
    ("google_calendar_edit", "POST", re.escape(CALENDAR_API)),
    ("google_calendar_edit", "GET", re.escape(CALENDAR_API) + "/" + _ID),
    ("google_tasks", "POST", re.escape(TASKS_API)),
    ("google_tasks", "GET", re.escape(TASKS_API) + "/" + _ID),
    ("google_drive_files", "POST", re.escape(DRIVE_API)),
    ("google_drive_files", "GET", re.escape(DRIVE_API) + "/" + _ID),
    ("google_drive_files", "POST", re.escape(DOCS_API)),
    ("google_drive_files", "POST", re.escape(DOCS_API) + "/" + _ID + ":batchUpdate"),
    ("google_drive_files", "GET", re.escape(DOCS_API) + "/" + _ID),
))


def permitted(connector, method, url):
    """Is this exact request one an approved action may make for that connector?"""
    return any(c == connector and m == method and pattern.fullmatch(url) for c, m, pattern in _PERMITTED)


def _send(config, connector, method, url, *, params=None, body=None, what="that", ok=(200,), accept=()):
    """One request to Google as the owner, for an approved action. Returns the response when its status is in `ok` or `accept`. ActionFailed, with nothing done, for a refusal Google gave (and for a sign-in
    that is gone); ActionUncertain for a request that may have reached Google with no answer, or a failure on its side part way."""
    label = GOOGLE_WRITE[connector][0]
    if not permitted(connector, method, url):
        raise ActionFailed(f"{label} is not allowed to make that request, so nothing was done.")
    if diya_connectors.read_token(config, connector) is None:
        raise ActionFailed(f"{label} is not connected, so nothing was done.")
    token = diya_google_calendar.access_token(config, connector)
    if token is None:
        raise ActionFailed(f"Google did not accept the sign-in for {label}, so nothing was done. Connect it again on the Connections page.")
    try:
        response = httpx.request(method, url, params=params, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        if isinstance(exc, _NEVER_SENT):
            raise ActionFailed(f"Couldn't reach Google ({type(exc).__name__}), so nothing was done.")
        raise ActionUncertain(f"The request was sent to Google but no answer came back ({type(exc).__name__}), so {what} may or may not have been done. Look in Google, then record what you found.")
    status = response.status_code
    if status in ok or status in accept:
        return response
    reason = _reason(response)
    suffix = f" ({reason})" if reason else ""
    if status in (401, 403):
        raise ActionFailed(f"Google refused{suffix}, so nothing was done. Check that the API is switched on and that you allowed Diya to do this, then connect {label} again.")
    if status == 429:
        raise ActionFailed(f"Google is limiting requests right now, so nothing was done.{diya_google_calendar.wait_hint(response).replace('Try again', 'Propose it again')}")
    if 500 <= status <= 599:
        raise ActionUncertain(f"Google answered with an error (HTTP {status}) part way through, so {what} may or may not have been done. Look in Google, then record what you found.")
    raise ActionFailed(f"Google answered with HTTP {status}{suffix}, so nothing was done.")


def _json(response):
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _link(data, key):
    link = data.get(key)
    return f" {link}" if isinstance(link, str) and link.startswith("https://") and len(link) <= 300 else ""


_REMOTE_ID = re.compile(r"[A-Za-z0-9_-]{5,128}")


def _read_back(config, connector, url, what, check, params=None):
    """The independent check that a write really happened (DIYA-052): Google's answer to the write is not taken as proof; the thing is asked for again by its id, and what comes back must be what was
    asked for. `check(data)` returns "" when it is, else a few words saying what is different. Anything else (the read failing, a different thing) is ActionUncertain: it may well be there, it is not
    confirmed, and the person is told to look. Returns what came back."""
    try:
        data = _json(_send(config, connector, "GET", url, params=params, what=what, ok=(200,)))
    except (ActionFailed, ActionUncertain):
        raise ActionUncertain(f"Google said {what} was made, but reading it back to check did not work, so it is not confirmed. Look in Google, then record what you found.")
    problem = check(data) if data else "an empty answer"
    if problem:
        raise ActionUncertain(f"Google said {what} was made, but reading it back showed {problem}, so it is not confirmed. Look in Google, then record what you found.")
    return data


def _same_moment(google_text, our_iso):
    """Is Google's RFC 3339 time (any offset) the same moment as our UTC text?"""
    try:
        return datetime.fromisoformat(str(google_text).replace("Z", "+00:00")) == datetime.fromisoformat(our_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False


def _clean_title(value, what):
    if not isinstance(value, str) or not value.strip():
        raise InvalidArgs(f"{what} needs a name, in words")
    if len(value) > TITLE_MAX:
        raise InvalidArgs(f"a name is at most {TITLE_MAX} characters")
    if diya_memory.printable(value) != value:
        raise InvalidArgs("a name is one plain line")


def _only(args, allowed, what):
    extra = sorted(set(args) - set(allowed))
    if extra:
        raise InvalidArgs(f"{what} has no {', '.join(extra)}")


def _local(start):
    return diya_time.describe_local(diya_time.local_from_iso(start))


# ---- a calendar event ---------------------------------------------------------------------------------------------------------------------

def event_validate(args):
    _only(args, {"title", "when", "start", "duration_minutes"}, "a calendar event")
    _clean_title(args.get("title"), "an event")
    start = args.get("start")
    if not isinstance(start, str) or not _ISO_UTC.fullmatch(start):
        raise InvalidArgs("an event needs the time it starts and the user has not said one: ask them when, and do not guess")
    try:
        diya_time.local_from_iso(start)
    except ValueError:
        raise InvalidArgs("that is not a time")
    duration = args.get("duration_minutes", 60)
    if not isinstance(duration, int) or isinstance(duration, bool) or not MINUTES[0] <= duration <= MINUTES[1]:
        raise InvalidArgs(f"an event lasts between {MINUTES[0]} and {MINUTES[1]} minutes")
    if "when" in args and (not isinstance(args["when"], str) or len(args["when"]) > diya_time.MAX_CHARS):
        raise InvalidArgs("when must be the user's own words, a few of them")


def event_render(args):
    return f"Add to your Google Calendar: {args['title']}, {_local(args['start'])}, for {args.get('duration_minutes', 60)} minutes (just you: nobody is invited)"


def event_prepare(args, text):
    """The time is the PERSON's: read by code from their own words and fixed now. A time they did not say is not guessed (the model made one up in most of the cases where it gave one: docs/ACTIONS_DESIGN.md,
    section 6), and one the model computed itself ("start") is never taken; the model is told it has none."""
    bare = {key: value for key, value in args.items() if key not in ("when", "start")}
    when = args.get("when")
    if not isinstance(when, str) or not when.strip():
        return bare, ["It has no time: the user did not say when it starts, so ask them."]
    problem = diya_time.disagreement(when, text)
    if problem:
        return bare, [f"It has no time: {problem}. Ask the user when it starts."]
    try:
        moment = diya_time.parse_when(when)
    except diya_time.NotUnderstood as exc:
        return bare, [f"It has no time: {exc.reason} Ask the user when it starts."]
    notes = [f"Read as {moment.describe()}" + (f" ({'; '.join(moment.assumed)})" if moment.assumed else "") + ": tell the user, so they can check it before they approve."]
    return dict(bare, when=" ".join(when.split()), start=moment.iso()), notes


def event_id(args):
    """Google lets the caller choose an event's id (the letters a to v and digits, 5 to 1024 long): one made from the request, so that asking again cannot make a second event."""
    return hashlib.sha256(f"{args['title']}|{args['start']}|{args.get('duration_minutes', 60)}".encode("utf-8")).hexdigest()[:32]


def event_execute(config, args):
    start = datetime.strptime(args["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=args.get("duration_minutes", 60))
    body = {"id": event_id(args), "summary": args["title"], "start": {"dateTime": args["start"], "timeZone": "UTC"}, "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "timeZone": "UTC"}}
    response = _send(config, "google_calendar_edit", "POST", CALENDAR_API, params={"sendUpdates": "none"}, body=body, what="the event", ok=(200,), accept=(409,))
    if response.status_code == 409:  # an event with this id is there: an earlier attempt got through, or it was added and later deleted. It is checked, not assumed.
        found = _json(_send(config, "google_calendar_edit", "GET", f"{CALENDAR_API}/{body['id']}", what="the event", ok=(200,)))
        if found.get("status") == "cancelled":
            raise ActionFailed("This same event was added before and then deleted, and Google does not let an event come back under the same id, so nothing was added. Change the title or the length a little and ask again.")
        if found.get("summary") != args["title"]:
            raise ActionFailed("Google already has an event with this request's id that is not this one, so nothing was added.")
        return f"That event was already on your calendar (added earlier): {args['title']}, {_local(args['start'])}.{_link(found, 'htmlLink')}"
    data = _json(response)
    if data.get("id") != body["id"] or data.get("status") not in ("confirmed", "tentative"):
        raise ActionUncertain("Google answered, but not with the event that was asked for, so it may or may not be on your calendar. Look in Google Calendar, then record what you found.")

    def check(found):
        if found.get("summary") != args["title"]:
            return "a different title"
        if not _same_moment((found.get("start") or {}).get("dateTime"), args["start"]) or not _same_moment((found.get("end") or {}).get("dateTime"), body["end"]["dateTime"]):
            return "a different time"
        if found.get("status") not in ("confirmed", "tentative"):
            return "an event that is not on the calendar"
        if found.get("attendees"):
            return "guests, and nobody was to be invited"
        return ""

    verified = _read_back(config, "google_calendar_edit", f"{CALENDAR_API}/{body['id']}", "the event", check)
    return f"Added to your Google Calendar and read back to check: {args['title']}, {_local(args['start'])}, for {args.get('duration_minutes', 60)} minutes.{_link(verified, 'htmlLink') or _link(data, 'htmlLink')}"


def event_kind():
    return ActionKind(
        name="google_calendar_add_event", label="Add a Google Calendar event", connector="google_calendar_edit", validate=event_validate, render=event_render, execute=event_execute,
        asked=diya_intent.asks_to_add_calendar_event, prepare=event_prepare,
        tool={"type": "function", "function": {
            "name": "propose_calendar_event",
            "description": (
                "Propose adding an event to the user's Google Calendar. This only PROPOSES it: nothing is added until the user approves it on the Actions page. Use it only when the user asks you to add, "
                "schedule or book an event, meeting or appointment on their calendar. Nobody is invited; it is only for the user."
            ),
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string", "description": "What it is, in a few words, e.g. 'AI study session'."},
                "when": {"type": "string", "description": "When it starts, in the user's own words, e.g. 'tomorrow at 5pm'. Required, and only what the user said."},
                "duration_minutes": {"type": "integer", "description": "Optional. How long it lasts in minutes; 60 if the user did not say."},
            }, "required": ["title", "when"]},
        }},
    )


# ---- a Google task ------------------------------------------------------------------------------------------------------------------------

def task_validate(args):
    _only(args, {"title", "notes", "due"}, "a Google task")
    _clean_title(args.get("title"), "a task")
    if "notes" in args and (not isinstance(args["notes"], str) or len(args["notes"]) > NOTES_MAX or diya_memory.printable(args["notes"]) != args["notes"]):
        raise InvalidArgs(f"a task's notes are one plain line of at most {NOTES_MAX} characters")
    if "due" in args and (not isinstance(args["due"], str) or not _DATE.fullmatch(args["due"])):
        raise InvalidArgs("when it is due must be a date, said by the user")


def task_render(args):
    due = f" (due {args['due']})" if args.get("due") else ""
    return f"Add to your Google Tasks: {args['title']}{due}"


def task_prepare(args, text):
    """A due date is the person's: read by code from their words (a day, not a time of day), or left out and the model told."""
    due = args.get("due")
    if due is None:
        return args, []
    rest = {key: value for key, value in args.items() if key != "due"}
    left_out = [f"It has no due date: {due!r} was left out, because the user did not say when."]
    if not isinstance(due, str) or diya_time.disagreement(due, text):
        return rest, left_out
    try:
        moment = diya_time.parse_when(due)
    except diya_time.NotUnderstood:
        return rest, left_out
    return dict(rest, due=moment.local.strftime("%Y-%m-%d")), []


def task_execute(config, args):
    body = {"title": args["title"]}
    if args.get("notes"):
        body["notes"] = args["notes"]
    if args.get("due"):
        body["due"] = f"{args['due']}T00:00:00.000Z"
    data = _json(_send(config, "google_tasks", "POST", TASKS_API, body=body, what="the task", ok=(200, 201)))
    if data.get("title") != args["title"]:
        raise ActionUncertain("Google answered, but not with the task that was asked for, so it may or may not be in your list. Look in Google Tasks, then record what you found.")
    task_id = data.get("id")
    if not isinstance(task_id, str) or not _REMOTE_ID.fullmatch(task_id):
        raise ActionUncertain("Google said the task was made but gave no usable id to check it by, so it is not confirmed. Look in Google Tasks, then record what you found.")

    def check(found):
        if found.get("title") != args["title"] or found.get("deleted"):
            return "a different task"
        if found.get("status") != "needsAction":
            return "a task that is not open"
        if args.get("due") and not str(found.get("due", "")).startswith(args["due"]):
            return "a different due day"
        return ""

    verified = _read_back(config, "google_tasks", f"{TASKS_API}/{task_id}", "the task", check)
    return f"Added to your Google Tasks and read back to check: {args['title']}.{_link(verified, 'webViewLink') or _link(data, 'webViewLink')}"


def task_kind():
    return ActionKind(
        name="google_tasks_add", label="Add a Google Task", connector="google_tasks", validate=task_validate, render=task_render, execute=task_execute, asked=diya_intent.asks_for_google_task, prepare=task_prepare,
        tool={"type": "function", "function": {
            "name": "propose_google_task",
            "description": "Propose adding a task to the user's Google Tasks. This only PROPOSES it: nothing is added until the user approves it on the Actions page. Use it only when the user asks for it in Google Tasks by name.",
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string", "description": "What the task is, in a few words."},
                "notes": {"type": "string", "description": "Optional. A line of detail."},
                "due": {"type": "string", "description": "Optional. The day it is due, in the user's own words, e.g. 'friday'. Leave it out unless they said when."},
            }, "required": ["title"]},
        }},
    )


def google_tasks_list(config):
    """The read side of Google Tasks, as a tool: the open tasks in the default list."""
    def tool():
        if diya_connectors.read_token(config, "google_tasks") is None:
            return "Google Tasks is not connected."
        token = diya_google_calendar.access_token(config, "google_tasks")
        if token is None:
            return diya_google_calendar.not_connected_words(config, "google_tasks", "Google Tasks")
        try:
            response = httpx.get(TASKS_API, params={"showCompleted": "false", "maxResults": TASKS_PAGE}, headers={"Authorization": f"Bearer {token}"}, timeout=NETWORK_TIMEOUT)
        except httpx.HTTPError as exc:
            return f"Couldn't reach Google Tasks: {type(exc).__name__}"
        if response.status_code == 429:
            return f"Google Tasks is limiting requests right now.{diya_google_calendar.wait_hint(response)}"
        if response.status_code != 200:
            return f"Google Tasks answered with HTTP {response.status_code}."
        items = [i for i in (_json(response).get("items") or []) if isinstance(i, dict)]
        if not items:
            return "No open tasks in Google Tasks."
        lines = [diya_memory.printable(i.get("title") or "(no title)", 120) + (f" (due {str(i['due'])[:10]})" if i.get("due") else "") for i in items]
        if _json(response).get("nextPageToken"):  # Google has more: say so, so a long list is never taken for the whole list
            lines.append(f"(There are more open tasks than these {len(items)}; only the first {TASKS_PAGE} are shown.)")
        return "\n".join(lines)

    return tool


# ---- a Drive folder -----------------------------------------------------------------------------------------------------------------------

def folder_validate(args):
    _only(args, {"name"}, "a Drive folder")
    _clean_title(args.get("name"), "a folder")
    if any(ch in args["name"] for ch in "/\\<>:\"|?*"):
        raise InvalidArgs("a folder's name cannot have / \\ < > : \" | ? or * in it")


def folder_render(args):
    return f"Make a folder in your Google Drive: {args['name']} (at the top of My Drive)"


def folder_execute(config, args):
    response = _send(config, "google_drive_files", "POST", DRIVE_API, body={"name": args["name"], "mimeType": FOLDER_TYPE}, params={"fields": "id,name,mimeType,webViewLink"}, what="the folder", ok=(200, 201))
    data = _json(response)
    if data.get("mimeType") != FOLDER_TYPE or data.get("name") != args["name"]:
        raise ActionUncertain("Google answered, but not with the folder that was asked for, so it may or may not be in your Drive. Look in Google Drive, then record what you found.")
    folder_id = data.get("id")
    if not isinstance(folder_id, str) or not _REMOTE_ID.fullmatch(folder_id):
        raise ActionUncertain("Google said the folder was made but gave no usable id to check it by, so it is not confirmed. Look in Google Drive, then record what you found.")

    def check(found):
        if found.get("name") != args["name"] or found.get("mimeType") != FOLDER_TYPE:
            return "a different folder"
        return "a folder in the bin" if found.get("trashed") else ""

    verified = _read_back(config, "google_drive_files", f"{DRIVE_API}/{folder_id}", "the folder", check, params={"fields": "id,name,mimeType,trashed,webViewLink"})
    return f"Made the folder {args['name']} in your Google Drive and read it back to check.{_link(verified, 'webViewLink') or _link(data, 'webViewLink')}"


def folder_kind():
    return ActionKind(
        name="google_drive_make_folder", label="Make a Google Drive folder", connector="google_drive_files", validate=folder_validate, render=folder_render, execute=folder_execute,
        asked=diya_intent.asks_for_drive_folder,
        tool={"type": "function", "function": {
            "name": "propose_drive_folder",
            "description": "Propose making a new folder in the user's Google Drive. This only PROPOSES it: nothing is made until the user approves it on the Actions page. Use it only when the user asks for a folder in their Drive.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "The folder's name."}}, "required": ["name"]},
        }},
    )


# ---- a Google Doc ---------------------------------------------------------------------------------------------------------------------------

def doc_validate(args):
    _only(args, {"title", "body"}, "a Google Doc")
    _clean_title(args.get("title"), "a document")
    body = args.get("body", "")
    if not isinstance(body, str) or len(body) > BODY_MAX:
        raise InvalidArgs(f"a document's text is at most {BODY_MAX} characters")


def doc_render(args):
    body = " ".join(str(args.get("body", "")).split())
    shown = diya_memory.printable(body, SHOWN_BODY)
    return f"Make a new Google Doc called {args['title']}" + (f", starting with: {shown}" if shown else ", empty")


def _document_text(document):
    """All the text in a Google Doc as the Docs API returns it (paragraphs of text runs)."""
    parts = []
    for element in ((document.get("body") or {}).get("content") or []):
        for run in (((element or {}).get("paragraph") or {}).get("elements") or []):
            text = ((run or {}).get("textRun") or {}).get("content")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def doc_execute(config, args):
    made = _json(_send(config, "google_drive_files", "POST", DOCS_API, body={"title": args["title"]}, what="the document", ok=(200,)))
    document_id = made.get("documentId")
    if not isinstance(document_id, str) or not _DOC_ID.fullmatch(document_id) or made.get("title") != args["title"]:
        raise ActionUncertain("Google answered, but not with the document that was asked for, so it may or may not be in your Drive. Look in Google Drive, then record what you found.")
    link = f" https://docs.google.com/document/d/{document_id}/edit"
    if args.get("body"):
        try:
            _send(config, "google_drive_files", "POST", f"{DOCS_API}/{document_id}:batchUpdate", body={"requests": [{"insertText": {"location": {"index": 1}, "text": args["body"]}}]}, what="the text", ok=(200,))
        except (ActionFailed, ActionUncertain) as exc:
            # The document exists: this is neither a clean failure nor a clean success. It is said so, with where it is.
            raise ActionUncertain(f"The document was made but its text could not be put in it ({exc}). It is here:{link}")

    def check(found):
        if found.get("title") != args["title"]:
            return "a different title"
        if args.get("body") and args["body"] not in _document_text(found):
            return "the text missing"
        return ""

    _read_back(config, "google_drive_files", f"{DOCS_API}/{document_id}", "the document", check)
    return f"Made the Google Doc {args['title']} and read it back to check.{link}"


def doc_kind():
    return ActionKind(
        name="google_docs_create", label="Make a Google Doc", connector="google_drive_files", validate=doc_validate, render=doc_render, execute=doc_execute, asked=diya_intent.asks_for_google_doc,
        tool={"type": "function", "function": {
            "name": "propose_google_doc",
            "description": "Propose making a new Google Doc, with a line of text in it if the user asked for it. This only PROPOSES it: nothing is made until the user approves it on the Actions page. Use it only when the user asks for a Google Doc.",
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string", "description": "The document's title."},
                "body": {"type": "string", "description": "Optional. The text to start it with: plain text on one line."},
            }, "required": ["title"]},
        }},
    )


def action_kinds():
    return (event_kind(), task_kind(), folder_kind(), doc_kind())


def read_tool_specs(config):
    """(connector name, tool spec, function) for the read side that goes with these connectors: the open Google Tasks."""
    return (("google_tasks", {"type": "function", "function": {
        "name": "list_google_tasks", "description": "List the user's open Google Tasks.", "parameters": {"type": "object", "properties": {}, "required": []},
    }}, google_tasks_list(config)),)
