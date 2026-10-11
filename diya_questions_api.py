"""The questions Diya raises herself, over HTTP (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5): the routes behind the chat's cards.

    GET  /api/questions               the questions that may be put in front of the person now (at most three; none in the quiet hours), in words made by code
    POST /api/questions/seen          {"ids": [...]}  these were put in front of the person: a question left for a day counts as ignored
    POST /api/questions/{id}/answer   {"answer": "yes" | "no" | "keep" | "edit", "text": ...}  act on the answer and close the question

Everything is off unless automatic memory is on: with it off the list is empty and nothing is made. Like every other route these are behind the access token,
and what is shown goes through diya_memory.printable. A refusal is an HTTP error with the reason in `detail`: 404 for a question or fact that is not there, 409
for an answer that no longer applies, 422 for an answer the question does not offer or an edit with nothing in it.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya_memory
import diya_time
from diya_memory import FactError, Memory, printable
from diya_questions import Questions

MAX_ID = 2**63 - 1
MAX_SEEN = 20


class AnswerBody(BaseModel):
    answer: str
    text: str | None = None


class SeenBody(BaseModel):
    ids: list[int]


def _refusal(exc):
    status = next((code for cls, code in diya_memory_status() if isinstance(exc, cls)), 400)
    return HTTPException(status_code=status, detail=printable(exc))


def diya_memory_status():
    import diya_memory_api

    return diya_memory_api._STATUS


def register(app, config, agent):
    """Add the question routes to `app`, directly, like every other route. Nothing is touched here: the store is looked up per request."""

    def questions():
        return Questions(agent.store, quiet=diya_time.parse_quiet(config.questions_quiet))

    @app.get("/api/questions")
    def list_questions():
        if not config.auto_memory:
            return {"questions": []}
        memory, queue, now = Memory(agent.store), questions(), agent.now()
        queue.refill(memory, now)
        shown = []
        for item in queue.visible(now):
            try:
                shown.append(queue.describe(memory, item))
            except FactError:
                continue  # its fact is gone: the next refill closes it
        return {"questions": shown}

    @app.post("/api/questions/seen")
    def seen(body: SeenBody):
        if not config.auto_memory:
            return {"seen": 0}
        ids = [i for i in body.ids[:MAX_SEEN] if 0 < i <= MAX_ID]
        questions().seen(ids, agent.now())
        return {"seen": len(ids)}

    @app.post("/api/questions/{question_id}/answer")
    def answer(question_id: int, body: AnswerBody):
        if not 0 < question_id <= MAX_ID:
            raise HTTPException(status_code=404, detail=f"there is no question {printable(question_id)}")
        if not config.auto_memory:
            raise HTTPException(status_code=409, detail="automatic memory is off, so there are no questions")
        memory, queue = Memory(agent.store), questions()
        try:
            closed = queue.answer(memory, question_id, body.answer, agent.now(), text=body.text, add_reminder=agent.store.add_reminder)
        except FactError as exc:
            raise _refusal(exc)
        memory.run_checks("api")
        return {"question": {"id": closed["id"], "state": closed["state"], "answer": closed["answer"]}}
