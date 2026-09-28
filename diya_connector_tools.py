"""The three no-OAuth connectors (docs/CONNECTORS_DESIGN.md, unit C2): Home Assistant, Notion and
Todoist. Each is read-only (D2) -- one search/list tool, one validator that checks a pasted token
against the real service before it is stored. Network calls go through httpx with a short timeout,
the same pattern get_weather already uses; a request that fails is a friendly string back to the
model, never an exception it has to make sense of.

Each tool function takes `config` bound at Agent-construction time (functools.partial, the same way
get_weather binds its allowed hosts) but reads the CURRENT token from storage on every call, not once
-- so a disconnect takes effect on the next call without restarting anything.
"""
from __future__ import annotations

import httpx

import diya_connectors
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

def todoist_validate(token):
    try:
        response = httpx.get("https://api.todoist.com/rest/v2/projects", headers={"Authorization": f"Bearer {token}"}, timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"couldn't reach Todoist: {_friendly(exc)}")
    if response.status_code == 401:
        raise ConnectorError("Todoist rejected that token")
    if response.status_code != 200:
        raise ConnectorError(f"Todoist answered with HTTP {response.status_code}")


def todoist_tasks(config):
    def list_tasks(filter=None):
        token = diya_connectors.read_token(config, "todoist")
        if token is None:
            return "Todoist is not connected."
        params = {"filter": filter} if filter else {}
        try:
            response = httpx.get(
                "https://api.todoist.com/rest/v2/tasks", headers={"Authorization": f"Bearer {token}"},
                params=params, timeout=NETWORK_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return f"Couldn't reach Todoist: {_friendly(exc)}"
        if response.status_code != 200:
            return f"Todoist answered with HTTP {response.status_code}."
        tasks = response.json()
        if not tasks:
            return "No matching tasks."
        lines = []
        for task in tasks[:10]:
            due = task.get("due")
            when = f" (due {due['string']})" if due and due.get("string") else ""
            lines.append(f"{task['content']}{when}")
        return "\n".join(lines)

    return list_tasks


# ---- wiring: the registry and the tool specs -----------------------------------------------------

def real_connectors(config):
    """The three connectors this unit builds, ready to hand to diya_web.create_app()."""
    return (
        Connector(name="home_assistant", label="Home Assistant", description="Search entity states from a local instance.",
                 auth_kind="token", implemented=True, validate=home_assistant_validate(config)),
        Connector(name="notion", label="Notion", description="Search pages and databases you connect.",
                 auth_kind="token", implemented=True, validate=notion_validate),
        Connector(name="todoist", label="Todoist", description="List your open tasks.",
                 auth_kind="token", implemented=True, validate=todoist_validate),
    )


def tool_specs(config):
    """(connector name, tool spec, bound function) for the three connectors -- Agent filters this by
    which are actually connected (D4: invisible to the model otherwise) and registers the functions."""
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
    )
