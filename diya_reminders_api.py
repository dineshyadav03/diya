"""Reminders over HTTP (docs/PROACTIVITY_DESIGN.md, D4 and unit P3): the routes behind the UI's Reminders page.

    GET  /api/reminders            the pending reminders, each `due` (its time has come), `upcoming` or `no_time`,
                                   with the person's own words for when, and the time in words
    POST /api/reminders            {"text": ..., "when": ...}  a reminder the person types; the time is read by
                                   diya_time, exactly as the model's is, and a time it cannot read is a 422
    POST /api/reminders/{id}/done  mark a reminder done

GET and POST only: the API's CORS allows nothing else, and the browser only ever talks to the UI's own routes.
Every route is behind the access token like the rest of the API. A refusal is an HTTP error with the reason in
`detail`: 404 for a reminder that is not there, 409 for one that is already done, 422 for text or a time that
cannot be used.

Reminders come from the model as well as from the person, so everything sent back goes through
diya_memory.printable(): a control or direction-changing character in one is sent as a visible escape.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya
import diya_time
from diya_memory import printable

MAX_ID = 2**63 - 1  # SQLite's largest integer: anything above it cannot be a reminder's id
STATES = ("due", "upcoming", "no_time")


class ReminderBody(BaseModel):
    text: str
    when: str | None = None


def _check_id(reminder_id):
    if not 0 < reminder_id <= MAX_ID:
        raise HTTPException(status_code=404, detail=f"there is no reminder {printable(reminder_id)}")


def register(app, config, agent):
    """Add the reminder routes to `app`, directly, like every other route (the tests that check every route for the
    token and the Host rule read app.routes). The store is looked up per request: registering touches nothing."""

    def now_ts():
        return diya_time.iso_of_local(agent.now())

    def classify(row, now):
        if row["due_ts"] is None:
            return "no_time"
        return "due" if row["due_ts"] <= now else "upcoming"

    def public(row, now, series=None):
        return {
            "id": row["id"],
            "series": (series or {}).get(row["id"]),  # the repeating reminder it came from, if it came from one
            "content": printable(row["content"]),
            "said": printable(row["due_at"]) if row["due_at"] else None,
            "due": row["due_ts"],
            "due_text": diya_time.describe_local(diya_time.local_from_iso(row["due_ts"])) if row["due_ts"] else None,
            "state": classify(row, now),
            "told": row["notified_at"] is not None,
        }

    def listing():
        agent.make_due_repeats()  # so a repeating reminder whose time has come is here, whoever looks first
        now = now_ts()
        rows = agent.store.reminders("pending")
        order = {state: n for n, state in enumerate(STATES)}
        rows.sort(key=lambda r: (order[classify(r, now)], r["due_ts"] or "", r["id"]))
        series = agent.schedule.series_of([row["id"] for row in rows])
        items = [public(row, now, series) for row in rows]
        return {"reminders": items, "counts": {state: sum(1 for i in items if i["state"] == state) for state in STATES}}

    @app.get("/api/reminders")
    def list_reminders():
        return listing()

    @app.post("/api/reminders", status_code=201)
    def add_reminder(body: ReminderBody):
        text = " ".join(body.text.split())
        if not text:
            raise HTTPException(status_code=422, detail="a reminder needs something to remind you about")
        if len(text) > diya.MAX_REMINDER_CHARS:
            raise HTTPException(status_code=422, detail=f"that is over {diya.MAX_REMINDER_CHARS} characters; shorten it")
        if printable(text) != text:
            raise HTTPException(status_code=422, detail="that contains control or invisible characters, which cannot be shown safely")
        words = " ".join((body.when or "").split())
        assumed, due_ts = [], None
        if words:
            try:
                when = diya_time.parse_when(words, agent.now())
            except diya_time.NotUnderstood as exc:
                raise HTTPException(status_code=422, detail=printable(f"I could not tell when {words[:60]!r} is: {exc.reason}"))
            due_ts, assumed = when.iso(), list(when.assumed)
        reminder_id = agent.store.add_reminder(text, words or None, due_ts)
        return {
            "reminder": public(agent.store.get_reminder(reminder_id), now_ts()),
            "assumed": [printable(item) for item in assumed],
            **listing(),
        }

    @app.post("/api/reminders/{reminder_id}/done")
    def done(reminder_id: int):
        _check_id(reminder_id)
        row = agent.store.get_reminder(reminder_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"there is no reminder {reminder_id}")
        if row["done"] or not agent.store.complete_reminder(reminder_id):
            raise HTTPException(status_code=409, detail=f"reminder {reminder_id} is already done")
        return {"id": reminder_id, **listing()}
