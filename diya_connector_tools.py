"""The three no-OAuth connectors (docs/CONNECTORS_DESIGN.md, unit C2): Home Assistant, Notion and
Todoist. Each is read-only (D2) -- one search/list tool, one validator that checks a pasted token
against the real service before it is stored. Network calls go through httpx with a short timeout,
the same pattern get_weather already uses; a request that fails is a friendly string back to the
model, never an exception it has to make sense of.

Each tool function takes `config` bound at Agent-construction time (functools.partial, the same way
get_weather binds its allowed hosts) but reads the CURRENT token from storage on every call, not once
-- so a disconnect takes effect on the next call without restarting anything.

`real_connectors()`/`tool_specs()` are the registry Agent and diya_web actually use, so they also
include Google Calendar (unit C3, diya_google_calendar.py) -- the shared plumbing for "every real
connector" lives here, even though its own OAuth mechanics are a separate module.
"""
from __future__ import annotations

import re

import httpx

import diya_connectors
import diya_google_calendar
import diya_intent
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs
from diya_connectors import Connector, ConnectorError

NETWORK_TIMEOUT = 5.0
NOTION_VERSION = "2022-06-28"


def _friendly(exc):
    """httpx raises different exceptions for a timeout, a DNS failure, a refused connection, etc.;
    the model (and the Connect form) only need one readable sentence, not a stack trace."""
    if isinstance(exc, httpx.TimeoutException):
        return "the request timed out"
    return str(exc) or type(exc).__name__


# ---- Home Assistant ---------------------------------------------------------------------------

def _home_assistant_base(config):
    return (config.home_assistant_url or "").strip().rstrip("/")


def home_assistant_validate(config):
    def validate(token):
        base = _home_assistant_base(config)
        if not base:
            raise ConnectorError("set DIYA_HOME_ASSISTANT_URL to your instance's address first")
        try:
            response = httpx.get(f"{base}/api/", headers={"Authorization": f"Bearer {token}"}, timeout=NETWORK_TIMEOUT)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"couldn't reach Home Assistant at {base}: {_friendly(exc)}")
        if response.status_code == 401:
            raise ConnectorError("Home Assistant rejected that token")
        if response.status_code != 200:
            raise ConnectorError(f"Home Assistant answered with HTTP {response.status_code}")

    return validate


def home_assistant_search(config):
    def search(query):
        token = diya_connectors.read_token(config, "home_assistant")
        if token is None:
            return "Home Assistant is not connected."
        base = _home_assistant_base(config)
        if not base:
            return "Home Assistant has no address configured (DIYA_HOME_ASSISTANT_URL)."
        try:
            response = httpx.get(f"{base}/api/states", headers={"Authorization": f"Bearer {token}"}, timeout=NETWORK_TIMEOUT)
        except httpx.HTTPError as exc:
            return f"Couldn't reach Home Assistant: {_friendly(exc)}"
        if response.status_code != 200:
            return f"Home Assistant answered with HTTP {response.status_code}."
        needle = query.strip().lower()
        matches = [
            entity for entity in response.json()
            if needle in entity.get("entity_id", "").lower()
            or needle in entity.get("attributes", {}).get("friendly_name", "").lower()
        ]
        if not matches:
            return f"No entity matching '{query}' was found."
        return "\n".join(
            f"{entity.get('attributes', {}).get('friendly_name', entity['entity_id'])} "
            f"({entity['entity_id']}): {entity['state']}"
            for entity in matches[:5]
        )

    return search


# ---- Notion -------------------------------------------------------------------------------------

def _notion_headers(token):
    return {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}


def notion_validate(token):
    try:
        response = httpx.get("https://api.notion.com/v1/users/me", headers=_notion_headers(token), timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"couldn't reach Notion: {_friendly(exc)}")
    if response.status_code == 401:
        raise ConnectorError("Notion rejected that token")
    if response.status_code != 200:
        raise ConnectorError(f"Notion answered with HTTP {response.status_code}")


def _notion_title(item):
    """A page or database's own title property, wherever Notion's response nests it; falls back to
    the item's id rather than crashing on an unusual or empty result."""
    for prop in item.get("properties", {}).values():
        if prop.get("type") == "title":
            text = "".join(part.get("plain_text", "") for part in prop.get("title", []))
            if text:
                return text
    return item.get("id", "(untitled)")


def notion_search(config):
    def search(query):
        token = diya_connectors.read_token(config, "notion")
        if token is None:
            return "Notion is not connected."
        try:
            response = httpx.post(
                "https://api.notion.com/v1/search",
                headers={**_notion_headers(token), "Content-Type": "application/json"},
                json={"query": query, "page_size": 5},
                timeout=NETWORK_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return f"Couldn't reach Notion: {_friendly(exc)}"
        if response.status_code != 200:
            return f"Notion answered with HTTP {response.status_code}."
        results = response.json().get("results", [])
        if not results:
            return f"No pages or databases matching '{query}' were found."
        return "\n".join(_notion_title(item) for item in results)

    return search


# ---- Todoist --------------------------------------------------------------------------------------

# Todoist's current API (v1). The older REST v2 this connector was first built on now answers "410 Gone", so a token
# could not even be connected (docs/ACTIONS_DESIGN.md, D11). v1 lists are paginated: {"results": [...], "next_cursor"}.
TODOIST_API = "https://api.todoist.com/api/v1"
TODOIST_LIST_LIMIT = 10  # how many tasks one answer shows


def _todoist_headers(token):
    return {"Authorization": f"Bearer {token}"}


def todoist_validate(token):
    try:
        response = httpx.get(f"{TODOIST_API}/projects", headers=_todoist_headers(token), params={"limit": 1}, timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"couldn't reach Todoist: {_friendly(exc)}")
    if response.status_code in (401, 403):
        raise ConnectorError("Todoist rejected that token")
    if response.status_code != 200:
        raise ConnectorError(f"Todoist answered with HTTP {response.status_code}")


def todoist_tasks(config):
    def list_tasks(filter=None):
        token = diya_connectors.read_token(config, "todoist")
        if token is None:
            return "Todoist is not connected."
        if filter:
            url, params = f"{TODOIST_API}/tasks/filter", {"query": filter, "limit": TODOIST_LIST_LIMIT}
        else:
            url, params = f"{TODOIST_API}/tasks", {"limit": TODOIST_LIST_LIMIT}
        try:
            response = httpx.get(url, headers=_todoist_headers(token), params=params, timeout=NETWORK_TIMEOUT)
        except httpx.HTTPError as exc:
            return f"Couldn't reach Todoist: {_friendly(exc)}"
        if response.status_code != 200:
            return f"Todoist answered with HTTP {response.status_code}."
        try:
            body = response.json()
        except ValueError:
            body = None
        tasks = body.get("results") if isinstance(body, dict) else None
        if not isinstance(tasks, list):
            return "Todoist sent back something this couldn't read."
        if not tasks:
            return "No matching tasks."
        lines = []
        for task in tasks[:TODOIST_LIST_LIMIT]:
            due = task.get("due")
            when = f" (due {due['string']})" if due and due.get("string") else ""
            lines.append(f"{task['content']}{when}")
        return "\n".join(lines)

    return list_tasks


# ---- Todoist: the first write (docs/ACTIONS_DESIGN.md, D11 and unit A4) ---------------------------------------

TODOIST_CONTENT_MAX = 200
TODOIST_DUE_MAX = 60
# What cannot have reached Todoist: the request was never sent. Anything else that goes wrong on the way is treated as
# "may have been sent" -- so the task may exist -- because calling that a failure would invite a second attempt.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)


def todoist_add_task_validate(args):
    extra = sorted(set(args) - {"content", "due_string"})
    if extra:
        raise InvalidArgs(f"a Todoist task has no {', '.join(extra)}")
    content = args.get("content")
    if not isinstance(content, str) or not content:
        raise InvalidArgs("a Todoist task needs its content, in words")
    if len(content) > TODOIST_CONTENT_MAX:
        raise InvalidArgs(f"a task's content is at most {TODOIST_CONTENT_MAX} characters")
    if "due_string" in args:
        due = args["due_string"]
        if not isinstance(due, str) or not due:
            raise InvalidArgs("when it is due must be words, like 'tomorrow at 5pm' (or left out)")
        if len(due) > TODOIST_DUE_MAX:
            raise InvalidArgs(f"when it is due is at most {TODOIST_DUE_MAX} characters")


def todoist_add_task_render(args):
    due = f" (due {args['due_string']})" if args.get("due_string") else ""
    return f"Add to your Todoist Inbox: {args['content']}{due}"


def _said(phrase, text):
    """Is `phrase` (a due date, say) among the person's own words? Whole words, any capitals, spaces and the full stop or
    comma after it ignored -- "tomorrow" in "add it for Tomorrow." yes, "day" in "Monday" no."""
    phrase = " ".join(str(phrase).lower().split()).strip(" .,;:!?")
    words = " ".join(str(text).lower().split())
    return bool(phrase) and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", words) is not None


def todoist_add_task_prepare(args, text):
    """A due date the person did not say is left out (docs/ACTIONS_DESIGN.md, section 6: measured, the model made one up in
    over half the cases where it gave one, e.g. "tomorrow at 5pm" for "add task call mum"), and the model is told."""
    due = args.get("due_string")
    if due is None or _said(due, text):
        return args, []
    return ({key: value for key, value in args.items() if key != "due_string"},
            [f"It has no due date: {due!r} was left out, because the user did not say when."])


def todoist_add_task_execute(config, args):
    """Create the task through Todoist's API, in the Inbox (no project is chosen). Called only by Actions.run, after the
    owner approved exactly these arguments. Never retried: a failure it knows happened before anything took effect is
    ActionFailed; a request that may have reached Todoist (no answer, or a failure on its side) is ActionUncertain."""
    token = diya_connectors.read_token(config, "todoist")
    if token is None:  # disconnected between the check that precedes this and now
        raise ActionFailed("Todoist is not connected, so nothing was added.")
    body = {"content": args["content"]}
    if args.get("due_string"):
        body["due_string"] = args["due_string"]
    try:
        response = httpx.post(f"{TODOIST_API}/tasks", headers=_todoist_headers(token), json=body, timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        if isinstance(exc, _NEVER_SENT):
            raise ActionFailed(f"Couldn't reach Todoist ({_friendly(exc)}), so nothing was added.")
        raise ActionUncertain(
            f"The request was sent to Todoist but no answer came back ({_friendly(exc)}), so the task may or may not have "
            "been added. Look in Todoist, then record what you found."
        )
    status = response.status_code
    if status in (200, 201):
        try:
            task_id = response.json().get("id")
        except (ValueError, AttributeError):
            task_id = None
        return f"Added to your Todoist Inbox (task {task_id})." if task_id else "Added to your Todoist Inbox."
    if status in (401, 403):
        raise ActionFailed("Todoist refused the token, so nothing was added. Reconnect Todoist on the Connections page.")
    if status == 429:
        raise ActionFailed("Todoist is limiting requests right now, so nothing was added. Propose it again in a minute.")
    if 500 <= status <= 599:
        raise ActionUncertain(
            f"Todoist answered with an error (HTTP {status}) part way through, so the task may or may not have been added. "
            "Look in Todoist, then record what you found."
        )
    raise ActionFailed(f"Todoist answered with HTTP {status}, so nothing was added.")


def todoist_add_task_kind():
    return ActionKind(
        name="todoist_add_task",
        label="Add a Todoist task",
        connector="todoist",
        validate=todoist_add_task_validate,
        render=todoist_add_task_render,
        execute=todoist_add_task_execute,
        asked=diya_intent.is_task_request,
        prepare=todoist_add_task_prepare,
        tool={
            "type": "function",
            "function": {
                "name": "propose_todoist_task",
                "description": (
                    "Propose adding a task to the user's Todoist Inbox. This only PROPOSES it: nothing is added until the "
                    "user approves it on the Actions page. Use it only when the user asks you to add, create or put "
                    "something on their Todoist or to-do list."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "What the task is, in a few words, e.g. 'Buy oat milk'."},
                        "due_string": {
                            "type": "string",
                            "description": "Optional. When it is due, in the user's own words, e.g. 'tomorrow at 5pm'. Leave it out unless they said when.",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
    )


def real_action_kinds():
    """Every kind of action Diya actually has, ready to hand to Agent (action_kinds=): each a write the owner approves
    one at a time on the Actions page. Lives here, beside the connectors, because a kind needs its connector."""
    return (todoist_add_task_kind(),)


# ---- wiring: the registry and the tool specs -----------------------------------------------------

def real_connectors(config):
    """Every connector Diya actually has, ready to hand to diya_web.create_app()."""
    return (
        Connector(name="home_assistant", label="Home Assistant", description="Search entity states from a local instance.",
                 auth_kind="token", implemented=True, validate=home_assistant_validate(config)),
        Connector(name="notion", label="Notion", description="Search pages and databases you connect.",
                 auth_kind="token", implemented=True, validate=notion_validate),
        Connector(name="todoist", label="Todoist", description="List your open tasks, and add one when you approve it.",
                 auth_kind="token", implemented=True, validate=todoist_validate),
        Connector(name="google_calendar", label="Google Calendar", description="Read your upcoming events.",
                 auth_kind="oauth", implemented=True, oauth_connect=diya_google_calendar.connect),
    )


def tool_specs(config):
    """(connector name, tool spec, bound function) for every connector -- Agent filters this by which
    are actually connected (D4: invisible to the model otherwise) and registers the functions."""
    return (
        ("home_assistant", {
            "type": "function",
            "function": {
                "name": "search_home_assistant",
                "description": "Search the user's Home Assistant entities (lights, locks, sensors, switches) by name and see their current state.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "A name or part of one, e.g. 'living room light' or 'front door'."}},
                    "required": ["query"],
                },
            },
        }, home_assistant_search(config)),
        ("notion", {
            "type": "function",
            "function": {
                "name": "search_notion",
                "description": "Search the user's connected Notion pages and databases.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "What to search Notion for."}},
                    "required": ["query"],
                },
            },
        }, notion_search(config)),
        ("todoist", {
            "type": "function",
            "function": {
                "name": "list_todoist_tasks",
                "description": "List the user's open Todoist tasks, optionally filtered (Todoist's own filter language, e.g. 'today' or 'overdue').",
                "parameters": {
                    "type": "object",
                    "properties": {"filter": {"type": "string", "description": "Optional Todoist filter, e.g. 'today'. Omit to list everything open."}},
                    "required": [],
                },
            },
        }, todoist_tasks(config)),
        ("google_calendar", {
            "type": "function",
            "function": {
                "name": "list_calendar_events",
                "description": "List the user's next upcoming Google Calendar events.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }, diya_google_calendar.list_events(config)),
    )
