"""What Diya wrote first, over HTTP (docs/PROACTIVE_DESIGN.md): the routes behind the cards at the top of the chat.

    GET  /api/proactive         what she has said that the person has not looked at yet, newest first, at most five: [{id, kind, text, thread_id, created_at}]
    POST /api/proactive/seen    {"ids": [...]}  these were looked at (opened, or dismissed): they are not shown again

Like every other route, behind the access token; the words were built in code from the person's own reminders and tasks and still go through diya_memory.printable on the way out.
Reading is always possible, whatever DIYA_PROACTIVE says: switching her off only stops new messages.
"""
from __future__ import annotations

from pydantic import BaseModel

import diya_events
import diya_proactive
from diya_memory import printable

MAX_IDS = 20
MAX_ID = 2**63 - 1


def lines_of(text):
    """The message with its line breaks kept (it is a short list) and every line made safe to show, one at a time: printable() alone would make it one run-on line."""
    return "\n".join(printable(line, 400) for line in text.split("\n"))


class SeenBody(BaseModel):
    ids: list[int]


def register(app, config, agent):
    """Add the routes to `app`, directly, like every other route. The store is looked up per request."""

    def proactive():
        return diya_proactive.Proactive(agent.store)

    @app.get("/api/proactive")
    def unseen():
        return {"messages": [{"id": m["id"], "kind": m["kind"], "text": lines_of(m["text"]), "thread_id": m["thread_id"], "created_at": m["created_at"]} for m in proactive().unseen()]}

    @app.post("/api/proactive/seen")
    def seen(body: SeenBody):
        ids = [i for i in body.ids[:MAX_IDS] if 0 < i <= MAX_ID]
        proactive().mark_seen(ids, diya_events.utc_of_local(agent.now()))
        return {"seen": len(ids)}
