"""The to-do list over HTTP (docs/TASKS_DESIGN.md, D7 and unit T2): the routes behind the UI's Tasks page.

    GET  /api/tasks               the open tasks (oldest first, each saying whether it is overdue), the most recently
                                  finished ones, and the counts
    POST /api/tasks               {"text": ..., "when": ...}  a task the person types; "when" is read by diya_time, exactly
                                  as the model's is, and words it cannot read are kept as words, not refused
    POST /api/tasks/{id}/done     tick a task off
    POST /api/tasks/{id}/reopen   put a done task back on the list

GET and POST only: the API's CORS allows nothing else, and the browser only ever talks to the UI's own routes. Every route
is behind the access token like the rest of the API. A refusal is an HTTP error with the reason in `detail`: 404 for a task
that is not there, 409 for one that is already in the state asked for or that would clash (the same words already open, or a
full list), 422 for text that cannot be used.

There is no delete here, on purpose (docs/TASKS_DESIGN.md, D7): Done takes a task off the list without losing it.

Tasks come from the model as well as from the person, so everything sent back goes through diya_memory.printable(): a
control or direction-changing character in one is sent as a visible escape.
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from pydantic import BaseModel

import diya_tasks
from diya_memory import printable

MAX_ID = 2**63 - 1  # SQLite's largest integer: anything above it cannot be a task's id
DONE_SHOWN = 50  # how many finished tasks one answer carries


class TaskBody(BaseModel):
    text: str
    when: str | None = None


def _check_id(task_id):
    if not 0 < task_id <= MAX_ID:
        raise HTTPException(status_code=404, detail=f"there is no task {printable(task_id)}")


def register(app, config, agent):
    """Add the task routes to `app`, directly, like every other route (the tests that check every route for the token and
    the Host rule read app.routes). The list is looked up per request: registering touches nothing."""

    def public(task, now):
        return {
            "id": task["id"],
            "content": printable(task["content"]),
            "said": printable(task["due_at"]) if task["due_at"] else None,
            "due": task["due_ts"],
            "due_text": printable(diya_tasks.describe_due(task)) if task["due_ts"] else None,
            "overdue": diya_tasks.is_overdue(task, now),
            "done": task["done"],
            "completed": task["completed_at"],
            "from_chat": task["source"] == "chat",
        }

    def listing():
        now = agent.now()
        open_tasks = [public(task, now) for task in agent.tasks.tasks("open")]
        done_tasks = [public(task, now) for task in agent.tasks.tasks("done", limit=DONE_SHOWN)]
        counts = agent.tasks.counts()
        counts["overdue"] = sum(1 for task in open_tasks if task["overdue"])
        return {"tasks": open_tasks, "done": done_tasks, "counts": counts}

    def refuse(exc):
        """The HTTP answer for a refusal from the list itself. A task's number means nothing to the person, who is never
        shown one, so "(#3)" is left out of what they are told (the model is shown it: its list has numbers)."""
        detail = printable(re.sub(r" \(#\d+\)", "", str(exc)))
        if isinstance(exc, diya_tasks.UnknownTask):
            return HTTPException(status_code=404, detail=detail)
        if isinstance(exc, (diya_tasks.DuplicateTask, diya_tasks.TooManyTasks)):
            return HTTPException(status_code=409, detail=detail)
        return HTTPException(status_code=422, detail=detail)

    @app.get("/api/tasks")
    def list_tasks():
        return listing()

    @app.post("/api/tasks", status_code=201)
    def add_task(body: TaskBody):
        try:
            task = agent.tasks.add(body.text, body.when, source="page")
        except diya_tasks.TaskError as exc:
            raise refuse(exc)
        return {"task": public(task, agent.now()), **listing()}

    @app.post("/api/tasks/{task_id}/done")
    def done(task_id: int):
        _check_id(task_id)
        try:
            changed = agent.tasks.complete(task_id)
        except diya_tasks.TaskError as exc:
            raise refuse(exc)
        if not changed:
            raise HTTPException(status_code=409, detail=f"task {task_id} is already done")
        return {"id": task_id, **listing()}

    @app.post("/api/tasks/{task_id}/reopen")
    def reopen(task_id: int):
        _check_id(task_id)
        try:
            changed = agent.tasks.reopen(task_id)
        except diya_tasks.TaskError as exc:
            raise refuse(exc)
        if not changed:
            raise HTTPException(status_code=409, detail=f"task {task_id} is already open")
        return {"id": task_id, **listing()}
