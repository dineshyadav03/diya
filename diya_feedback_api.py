"""What the person thinks of Diya's replies, over HTTP (docs/FEEDBACK_DESIGN.md; diya_feedback.py), added 2026-10-21.

    POST /api/feedback    one of
        {"action": "list", "message_ids": [12, 14]}                                         {"items": {"12": {message_id, rating, category, note, version, at}}, "reasons": {id: words}}
        {"action": "put", "message_id": 12, "rating": "negative", "category": "wrong", "note": "...", "version": null}      {"item": {...}}   (version: null to create, the version seen to change)
        {"action": "delete", "message_id": 12, "version": 3}                                {"deleted": true}

Like every route these are behind the access token. A refusal is a 400 whose words are safe to show; a change made from another page since the person looked is a 409 that carries the item as it now stands.
Everything sent back goes through diya_memory.printable() (a note is the person's own text, but it is shown in a page).
"""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import diya_feedback
from diya_memory import printable

MAX_IDS = 200


class Action(BaseModel):
    action: str
    message_ids: list[int] | None = None
    message_id: int | None = None
    rating: str | None = None
    category: str | None = None
    note: str | None = None
    version: int | None = None


def shown(item):
    if item is None:
        return None
    return dict(item, note=None if item["note"] is None else printable(item["note"], diya_feedback.MAX_NOTE_CHARS))


def register(app, config, agent):
    def feedback():
        return diya_feedback.Feedback(agent.store)  # looked up per request: the store is what the agent has now

    @app.post("/api/feedback")
    def change(body: Action):
        try:
            if body.action == "list" and body.message_ids is not None:
                found = feedback().items(body.message_ids[:MAX_IDS])
                return {"items": {str(i): shown(item) for i, item in found.items()}, "reasons": dict(diya_feedback.CATEGORIES)}
            if body.action == "put" and body.message_id is not None and body.rating is not None:
                return {"item": shown(feedback().put(body.message_id, body.rating, body.category, body.note, body.version))}
            if body.action == "delete" and body.message_id is not None and body.version is not None:
                feedback().delete(body.message_id, body.version)
                return {"deleted": True}
            raise diya_feedback.FeedbackError("That is not something feedback can do.")
        except diya_feedback.Conflict as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc), "current": shown(exc.current)})
        except diya_feedback.FeedbackError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
