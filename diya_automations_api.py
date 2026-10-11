"""Automations over HTTP (docs/AUTOMATIONS_DESIGN.md): the routes behind the UI's Automations page.

    GET  /api/automations                 {"enabled": bool, "max": n, "automations": [{id, instruction, rule, state, next, last_run, last_status, runs}]}
    POST /api/automations                 {"text": "every morning at 8am tell me the weather in Pune"}  make one, read from the person's own words exactly as the chat reads them; 201
    POST /api/automations/{id}/pause      stop it running until it is resumed
    POST /api/automations/{id}/resume     let it run again, from the next time it falls (not the ones missed)
    POST /api/automations/{id}/run        run it now, by hand, and wait for the answer (it is written in the chat like any other); the schedule is not changed
    POST /api/automations/{id}/delete     remove it (POST, because the API's CORS allows only GET and POST)

Every route is behind the access token like the rest of the API. A refusal is an HTTP error with the reason in `detail`: 404 for one that is not there, 409 for one that is not allowed now (too many,
or switched off), 422 for words that cannot be read. Reading is always possible, whatever DIYA_AUTOMATIONS says: switching it off only stops new ones and the scheduled runs.
The instruction is the person's own words (or what the chat made of them), and everything sent back goes through diya_memory.printable().
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya_automations
import diya_proactive
import diya_repeat
import diya_time
from diya_memory import printable

MAX_ID = 2**63 - 1
EXAMPLE = "every morning at 8am tell me the weather in Pune"


class MakeBody(BaseModel):
    text: str


def _check_id(value):
    if not 0 < value <= MAX_ID:
        raise HTTPException(status_code=404, detail=f"there is no automation {printable(value)}")


def register(app, config, agent):
    """Add the routes to `app`, directly, like every other route. The store is looked up per request."""

    def automations():
        return diya_automations.Automations(agent.store, agent.now)

    def when(iso):
        return printable(diya_time.describe_local(diya_time.local_from_iso(iso))) if iso else None

    def public(row):
        return {
            "id": row["id"],
            "instruction": printable(row["instruction"], diya_automations.MAX_INSTRUCTION_CHARS),
            "rule": printable(diya_repeat.Repeat.from_canonical(row["rule"]).describe()),
            "state": row["state"],
            "next": when(row["next_ts"]) if row["state"] == "active" else None,
            "last_run": when(row["last_run_at"]),
            "last_status": printable(row["last_status"]) if row["last_status"] else None,
            "runs": row["runs"],
        }

    def listing():
        return {"enabled": config.automations, "max": diya_automations.MAX_AUTOMATIONS, "automations": [public(row) for row in automations().list()]}

    def refuse(exc):
        text = printable(str(exc))
        raise HTTPException(status_code=404 if text.startswith("there is no automation") else 409, detail=text)

    @app.get("/api/automations")
    def list_automations():
        return listing()

    @app.post("/api/automations", status_code=201)
    def make(body: MakeBody):
        if not config.automations:
            raise HTTPException(status_code=409, detail="automations are switched off (DIYA_AUTOMATIONS=0)")
        request = diya_automations.parse_request(body.text, agent.now())
        if isinstance(request, str):
            raise HTTPException(status_code=422, detail=printable(request))
        if request is None:
            raise HTTPException(status_code=422, detail=f"say when and what, in one sentence, for example: {EXAMPLE}")
        try:
            row = automations().create(request.instruction, request.words)
        except diya_automations.AutomationError as exc:
            raise HTTPException(status_code=409 if "already" in str(exc) else 422, detail=printable(str(exc)))
        return {"created": public(row), **listing()}

    def change(automation_id, action):
        _check_id(automation_id)
        try:
            getattr(automations(), action)(automation_id)
        except diya_automations.AutomationError as exc:
            refuse(exc)
        return {"id": automation_id, **listing()}

    @app.post("/api/automations/{automation_id}/pause")
    def pause(automation_id: int):
        return change(automation_id, "pause")

    @app.post("/api/automations/{automation_id}/resume")
    def resume(automation_id: int):
        return change(automation_id, "resume")

    @app.post("/api/automations/{automation_id}/delete")
    def delete(automation_id: int):
        return change(automation_id, "delete")

    @app.post("/api/automations/{automation_id}/run")
    def run_now(automation_id: int):
        _check_id(automation_id)
        if not config.automations:
            raise HTTPException(status_code=409, detail="automations are switched off (DIYA_AUTOMATIONS=0)")
        try:
            row = automations().get(automation_id)
        except diya_automations.AutomationError as exc:
            refuse(exc)
        message = diya_automations.run_by_hand(row, automations(), agent, diya_proactive.Proactive(agent.store), agent.now())
        return {"id": automation_id, "wrote": message is not None, "thread_id": message["thread_id"] if message else None, **listing()}
