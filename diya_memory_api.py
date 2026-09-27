"""Reviewing staged facts over HTTP (docs/STAGE2_DESIGN.md, D6 and unit 6): the routes behind the UI's
memory page. The rules are diya_memory's, the same ones the command line applies -- this only carries them.

    GET  /api/memory                  every fact, with its status, flags, who it is about and the memory's size
    GET  /api/memory/{id}             one fact: its flags in words, the messages it came from, its history
    POST /api/memory/ingest           copy newly staged facts in as candidates and check them
    POST /api/memory/add              {"text": ...}  a fact typed by the person; it goes in already accepted
    POST /api/memory/{id}/{action}    accept | reject | reopen | retire | restore, or edit with {"text": ...}
    POST /api/memory/merge            {"from_name": ..., "into_name": ...|null}  move a person's facts onto
                                       another name, or back to no one in particular (null); never automatic,
                                       never deletes from_name's own row (docs/PERSON_MEMORY_DESIGN.md, D3)

GET and POST only: the API's CORS allows nothing else, and the browser only ever talks to the UI's own
routes anyway. Every route is behind the access token like the rest of the API (the middleware wraps the
whole app). A refusal is an HTTP error with the reason in `detail`: 404 for a fact or person that isn't
there, 409 for a change that doesn't apply (wrong status, a repeat, no room), 422 for text that may not be
stored or a name that may not be used.

Everything read back from the database that a person is shown goes through diya_memory.printable(): it is
model output or something someone pasted, and a control or direction-changing character in it is sent as
a visible escape, never as itself.
"""
from __future__ import annotations

import dataclasses

from fastapi import HTTPException
from pydantic import BaseModel

import diya_memory
from diya_memory import (
    BudgetExceeded,
    DuplicateFact,
    FactError,
    IllegalTransition,
    InvalidFact,
    Memory,
    SourceUnreadable,
    UnknownFact,
    UnknownPerson,
    normalise_fact,
    printable,
)

SOURCE_CHARS = 300  # how much of a source message is sent
STAGED_CHARS = 300
DETAIL_CHARS = 200
MAX_ID = 2**63 - 1  # SQLite's largest integer: anything above it cannot be a fact's id

_STATUS = ((UnknownFact, 404), (UnknownPerson, 404), (IllegalTransition, 409), (DuplicateFact, 409),
          (BudgetExceeded, 409), (InvalidFact, 422))


class TextBody(BaseModel):
    text: str


class MergeBody(BaseModel):
    from_name: str
    into_name: str | None = None


def _refusal(exc):
    status = next((code for cls, code in _STATUS if isinstance(exc, cls)), 400)
    return HTTPException(status_code=status, detail=printable(exc))


def _check_id(fact_id):
    if not 0 < fact_id <= MAX_ID:
        raise HTTPException(status_code=404, detail=f"there is no fact {printable(fact_id)}")


def register(app, config, agent):
    """Add the memory routes to `app`. Registered directly on the app, like every other route, so that
    app.routes lists them by path (the tests that check every route for the token and the Host rule rely on it)."""
    # The store is looked up per request, not here: registering routes touches nothing (create_app is free).

    def summary(memory):
        return {
            "counts": memory.counts(),
            "used": len(memory.render()),
            "limit": diya_memory.MAX_PROFILE_CHARS,
            "max_fact_chars": diya_memory.MAX_FACT_CHARS,
        }

    def public(fact):
        return {
            "id": fact["id"],
            "text": printable(fact["text"]),
            "status": fact["status"],
            "source": fact["source"],
            "person": printable(fact["person"]) if fact["person"] is not None else None,
            "flags": [{"code": printable(flag), "label": diya_memory.flag_short(flag)} for flag in fact["flags"]],
            "created_at": printable(fact["created_at"]),
        }

    @app.get("/api/memory")
    def list_facts():
        memory = Memory(agent.store)
        return {"summary": summary(memory), "facts": [public(fact) for fact in memory.facts()]}

    @app.get("/api/memory/{fact_id}")
    def show(fact_id: int):
        _check_id(fact_id)
        memory = Memory(agent.store)
        try:
            fact = memory.get(fact_id)
        except FactError as exc:
            raise _refusal(exc)
        sources = []
        if fact["batch_first"] is not None:
            sources = [
                {"id": m["id"], "thread_id": m["thread_id"], "text": printable(m["content"], SOURCE_CHARS)}
                for m in agent.store.get_messages_between(fact["batch_first"], fact["batch_last"])
                if m["role"] == "user"  # the only messages the model that proposed it was shown
            ]
        return {
            "fact": public(fact),
            "staged": printable(fact["raw"], STAGED_CHARS) if fact["raw"] is not None else None,
            "model": printable(fact["model"]) if fact["model"] is not None else None,
            "extracted_at": printable(fact["extracted_at"]) if fact["extracted_at"] is not None else None,
            "range": None if fact["batch_first"] is None else [fact["batch_first"], fact["batch_last"]],
            "flag_details": [diya_memory.flag_long(memory, flag) for flag in fact["flags"]],
            "sources": sources,
            "events": [
                {
                    "event": printable(event),
                    "actor": printable(actor),
                    "at": printable(at),
                    "detail": printable(detail, DETAIL_CHARS) if detail else None,
                }
                for event, actor, at, detail in memory.events(fact_id)
            ],
        }

    @app.post("/api/memory/ingest")
    def ingest():
        memory = Memory(agent.store)
        try:
            report = diya_memory.ingest_queue(memory, config, actor="api")
        except SourceUnreadable as exc:
            raise HTTPException(status_code=500, detail=printable(exc))
        checked, changed = memory.run_checks("api")
        return {"report": dataclasses.asdict(report), "checked": checked, "changed": changed, "summary": summary(memory)}

    @app.post("/api/memory/add", status_code=201)
    def add(body: TextBody):
        memory = Memory(agent.store)
        fact = normalise_fact(body.text)
        if fact is None:
            raise HTTPException(status_code=422, detail="there is nothing left of that text once it is cleaned up")
        try:
            fact_id = memory.add_manual(fact.text, "api")
        except FactError as exc:
            raise _refusal(exc)
        memory.run_checks("api")
        return {"fact": public(memory.get(fact_id)), "summary": summary(memory)}

    @app.post("/api/memory/merge")
    def merge(body: MergeBody):
        memory = Memory(agent.store)
        try:
            moved = memory.merge_people(body.from_name, body.into_name, "api")
        except FactError as exc:
            raise _refusal(exc)
        return {"moved": moved, "people": memory.people()}

    @app.post("/api/memory/{fact_id}/{action}")
    def decide(fact_id: int, action: str, body: TextBody | None = None):
        _check_id(fact_id)
        if action != "edit" and action not in diya_memory.ACTIONS:
            raise HTTPException(status_code=404, detail=f"there is no action {printable(action)}")
        memory = Memory(agent.store)
        try:
            if action == "edit":
                if body is None:
                    raise InvalidFact("editing needs the new text")
                cleaned = normalise_fact(body.text)
                if cleaned is None:
                    raise InvalidFact("there is nothing left of that text once it is cleaned up")
                memory.edit(fact_id, cleaned.text, "api")
            else:
                memory.decide(fact_id, action, "api")
        except FactError as exc:
            raise _refusal(exc)
        memory.run_checks("api")
        return {"fact": public(memory.get(fact_id)), "summary": summary(memory)}
