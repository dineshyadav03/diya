"""Forgetting for good over HTTP (docs/FORGET_DESIGN.md): the routes behind "Forget for good" on the Memory page and on a message in the chat.

    POST /api/memory/{fact_id}/forget-for-good     take the words of a fact out for good (any status). {"fact": id, "staged_lines_cleaned": n}
    POST /api/messages/{message_id}/forget         {"also_learned": true, "dry_run": false}: delete one of the person's messages and Diya's reply, and (also_learned) the facts read from it.
                                                   With dry_run it changes nothing and says what would happen. Answers the report (diya_forget.forget_message).

Registered BEFORE the memory page's generic `/api/memory/{fact_id}/{action}` route, which would otherwise answer "no such action". There is no way to undo either one; the pages ask first. Behind the
access token like every route; everything sent back is numbers and fixed sentences.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya_forget
import diya_memory
from diya_memory import FactError, IllegalTransition, UnknownFact, printable

MAX_ID = 2**63 - 1


class ForgetBody(BaseModel):
    also_learned: bool = True
    dry_run: bool = False


def _check(identifier, what):
    if not 0 < identifier <= MAX_ID:
        raise HTTPException(status_code=404, detail=f"there is no {what} {printable(identifier)}")


def register(app, config, agent):
    @app.post("/api/memory/{fact_id}/forget-for-good")
    def forget_fact(fact_id: int):
        _check(fact_id, "fact")
        memory = diya_memory.open_memory(agent.store, agent.config)
        try:
            done = diya_forget.forget_fact(memory, agent.config, fact_id, "api")
        except UnknownFact as exc:
            raise HTTPException(status_code=404, detail=printable(exc))
        except (IllegalTransition, FactError) as exc:
            raise HTTPException(status_code=409, detail=printable(exc))
        return {"fact": done["fact_id"], "staged_lines_cleaned": done["staged_lines_cleaned"], "summary": memory.counts()}

    @app.post("/api/messages/{message_id}/forget")
    def forget_message(message_id: int, body: ForgetBody | None = None):
        _check(message_id, "message")
        body = body or ForgetBody()
        memory = diya_memory.open_memory(agent.store, agent.config)
        try:
            return diya_forget.forget_message(agent.store, memory, agent.config, message_id, also_learned=body.also_learned, dry_run=body.dry_run)
        except diya_forget.ForgetError as exc:
            raise HTTPException(status_code=404, detail=printable(exc))
