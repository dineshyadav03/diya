"""Approving what Diya proposed, over HTTP (docs/ACTIONS_DESIGN.md, D8 and unit A3): the routes behind the UI's
Actions page. The rules are diya_actions', the same ones the command line applies -- this only carries them.

    GET  /api/actions                 what is waiting for the owner, the most recent decided or finished actions, the
                                       counts, and which kinds of action Diya can propose at all
    GET  /api/actions/{id}            one action: its fields, the message it came from, and its events
    POST /api/actions/{id}/approve    {"args_hash": ...}  approve exactly what the page showed, then run it
    POST /api/actions/{id}/reject     turn a pending action down; it is never performed
    POST /api/actions/{id}/resolve    {"happened": true|false, "note": ...|null}  record what happened to an action
                                       whose outcome is unknown (it was cut off mid-run and is never run again)

GET and POST only: the API's CORS allows nothing else, and the browser only ever talks to the UI's own routes
anyway. Every route is behind the access token like the rest of the API (the middleware wraps the whole app); an
approval here is the same authenticated, Host- and Origin-checked request as any other, and reaches no model at
all (D1). A refusal is an HTTP error with the reason in `detail`: 404 for an action that is not there, 409 for one
in the wrong state or that is not what the page showed, 422 for a note that may not be stored.

Everything a person is shown goes through diya_memory.printable(): the arguments are the model's, shaped by
whatever it read, and a control or direction-changing character in them is sent as a visible escape, never as
itself. The arguments are sent as named fields for the page to show as plain text beside the one sentence
(`summary`) the code built from them -- the sentence the owner approves.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, StrictBool

import diya_actions
import diya_connectors
from diya_actions import ActionError, HashMismatch, IllegalTransition, InvalidArgs, UnknownAction
from diya_memory import printable

HISTORY_LIMIT = 50  # how many decided or finished actions the page lists
SOURCE_CHARS = 300  # how much of the message an action came from is sent
DETAIL_CHARS = 200
MAX_ID = 2**63 - 1  # SQLite's largest integer: anything above it cannot be an action's id

_STATUS = ((UnknownAction, 404), (IllegalTransition, 409), (HashMismatch, 409), (InvalidArgs, 422))


class ApproveBody(BaseModel):
    args_hash: str


class ResolveBody(BaseModel):
    happened: StrictBool
    note: str | None = None


def _refusal(exc):
    status = next((code for cls, code in _STATUS if isinstance(exc, cls)), 400)
    return HTTPException(status_code=status, detail=printable(exc))


def _check_id(action_id):
    if not 0 < action_id <= MAX_ID:
        raise HTTPException(status_code=404, detail=f"there is no action {printable(action_id)}")


def _shown(value):
    """One argument's value as the plain text the page shows."""
    if value is None:
        return None
    if value is True or value is False:
        return "yes" if value else "no"
    return printable(value)


def register(app, config, agent):
    """Add the actions routes to `app`. Registered directly on the app, like every other route, so that app.routes
    lists them by path (the tests that check every route for the token and the Host rule rely on it). The action
    store is looked up per request, not here: registering routes touches nothing."""

    def label_of(kind_name):
        kind = diya_actions.by_name(agent.actions.kinds, kind_name)
        return kind.label if kind is not None else kind_name

    def public(action):
        return {
            "id": action["id"],
            "kind": printable(action["kind"]),
            "label": printable(label_of(action["kind"])),
            "summary": printable(action["summary"]),
            "status": action["status"],
            # already in name order: the arguments are stored in canonical form (diya_actions.canonical)
            "fields": [{"name": printable(name), "value": _shown(value)} for name, value in action["args"].items()],
            "args_hash": action["args_hash"],
            "tainted": action["tainted"],
            "taint_sources": [printable(source) for source in action["taint_sources"]],
            "thread_id": action["thread_id"],
            "message_id": action["message_id"],
            "created_at": printable(action["created_at"]),
            "expires_at": printable(action["expires_at"]),
            "decided_at": printable(action["decided_at"]) if action["decided_at"] is not None else None,
            "executed_at": printable(action["executed_at"]) if action["executed_at"] is not None else None,
            "result": printable(action["result"]) if action["result"] is not None else None,
        }

    def kinds():
        return [
            {
                "name": printable(kind.name),
                "label": printable(kind.label),
                "connector": printable(kind.connector) if kind.connector is not None else None,
                "offered": kind.tool is not None,
                "available": kind.connector is None or diya_connectors.is_connected(config, kind.connector),
            }
            for kind in agent.actions.kinds
        ]

    def listing():
        agent.actions.reconcile()  # a run cut off a while ago becomes `unknown`, so the page never shows it as running
        pending = agent.actions.pending()  # closes what has expired first
        finished = [a for a in reversed(agent.actions.actions()) if a["status"] != "pending"][:HISTORY_LIMIT]
        return {
            "pending": [public(a) for a in pending],
            "history": [public(a) for a in finished],
            "counts": agent.actions.counts(),
            "kinds": kinds(),
        }

    @app.get("/api/actions")
    def list_actions():
        return listing()

    @app.get("/api/actions/{action_id}")
    def show(action_id: int):
        _check_id(action_id)
        try:
            action = agent.actions.get(action_id)
        except ActionError as exc:
            raise _refusal(exc)
        source = None
        if action["message_id"] is not None:
            messages = agent.store.get_messages_between(action["message_id"], action["message_id"])
            source = printable(messages[0]["content"], SOURCE_CHARS) if messages else None
        return {
            "action": public(action),
            "source": source,
            "events": [
                {
                    "event": printable(event),
                    "actor": printable(actor),
                    "at": printable(at),
                    "detail": printable(detail, DETAIL_CHARS) if detail else None,
                }
                for event, actor, at, detail in agent.actions.events(action_id)
            ],
        }

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: int, body: ApproveBody):
        _check_id(action_id)
        try:
            agent.actions.approve(action_id, body.args_hash, "ui")
            done = agent.actions.run(action_id)
        except ActionError as exc:
            raise _refusal(exc)
        return {"action": public(done)}

    @app.post("/api/actions/{action_id}/reject")
    def reject(action_id: int):
        _check_id(action_id)
        try:
            done = agent.actions.reject(action_id, "ui")
        except ActionError as exc:
            raise _refusal(exc)
        return {"action": public(done)}

    @app.post("/api/actions/{action_id}/resolve")
    def resolve(action_id: int, body: ResolveBody):
        _check_id(action_id)
        note = " ".join((body.note or "").split()) or None  # a blank note is no note
        try:
            done = agent.actions.resolve(action_id, body.happened, "ui", note=note)
        except ActionError as exc:
            raise _refusal(exc)
        return {"action": public(done)}
