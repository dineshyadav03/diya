"""Repeating reminders and snooze over HTTP (docs/SCHEDULE_DESIGN.md, D4 and unit R4): the routes behind the UI's Scheduled page
and the Reminders page's snooze buttons.

    GET  /api/scheduled                      the repeating reminders (active and paused, then stopped), what has happened lately,
                                             and the counts
    POST /api/scheduled                      {"text": ..., "repeat": ...}  make one; the repeat is read by diya_repeat, exactly as the
                                             model's is, and one it cannot read is a 422 with the reason
    POST /api/scheduled/{id}/pause           stop it making reminders until it is resumed
    POST /api/scheduled/{id}/resume          let it make them again, from now
    POST /api/scheduled/{id}/skip            let the next time pass without a reminder
    POST /api/scheduled/{id}/stop            end it for good (one it already made stays until it is done)
    POST /api/reminders/{id}/snooze          {"when": ...}  push a pending reminder to a later time, told again then

GET and POST only: the API's CORS allows nothing else, and the browser only ever talks to the UI's own routes. Every route is behind
the access token like the rest of the API. A refusal is an HTTP error with the reason in `detail`: 404 for something that is not
there, 409 for what makes no sense in its state or would clash (pausing what is paused, the same repeating reminder twice, too many),
422 for words that cannot be used. There is no delete: Stop ends a series and leaves it in the list, greyed.

Series come from the model as well as from the person, so everything sent back goes through diya_memory.printable().
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from pydantic import BaseModel

import diya_schedule
import diya_time
from diya_memory import printable

MAX_ID = 2**63 - 1  # SQLite's largest integer: anything above it cannot be an id
EVENTS_SHOWN = 15  # how many recent things the page is told about
SERIES_STATES = ("active", "paused", "ended")


class SeriesBody(BaseModel):
    text: str
    repeat: str


class SnoozeBody(BaseModel):
    when: str


def _check_id(value, what):
    if not 0 < value <= MAX_ID:
        raise HTTPException(status_code=404, detail=f"there is no {what} {printable(value)}")


def _refusal(exc):
    """The HTTP answer for a refusal from the schedule itself."""
    detail = printable(re.sub(r" \(#\d+\)", "", str(exc)))
    if isinstance(exc, (diya_schedule.UnknownSeries, diya_schedule.UnknownReminder)):
        return HTTPException(status_code=404, detail=detail)
    if isinstance(exc, (diya_schedule.DuplicateSeries, diya_schedule.TooManySeries, diya_schedule.IllegalState)):
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=422, detail=detail)


def register(app, config, agent):
    """Add the scheduling routes to `app`, directly, like every other route. The schedule is looked up per request: registering
    touches nothing."""

    def state_of(series):
        return "ended" if series["ended"] else "paused" if series["paused"] else "active"

    def public(series):
        words = diya_schedule.describe(series)
        return {
            "id": series["id"],
            "content": printable(series["content"]),
            "said": printable(series["said"]) if series["said"] else None,
            "rule": printable(words["rule"]),
            "next": printable(words["next"]) if words["next"] and state_of(series) == "active" else None,
            "state": state_of(series),
            "from_chat": series["source"] == "chat",
            "ended_at": series["ended_at"],
        }

    def sentence(event, names):
        """One recent event as a plain sentence, with the words of the series it is about."""
        what = f"“{names[event['series_id']]}”" if event["series_id"] in names else "a repeating reminder"
        detail = event["detail"] or {}
        if event["event"] == "created":
            return f"Set up {what}" + (" from the chat" if event["actor"] == "model" else "")
        if event["event"] == "occurred":
            return f"Made the reminder for {what}"
        if event["event"] == "missed":
            return f"Missed {detail.get('missed', 0)} earlier time{'s' if detail.get('missed', 0) != 1 else ''} of {what} (Diya was not looking); made one reminder"
        if event["event"] == "lapsed":
            return f"Closed an older reminder of {what} that was never done, because a newer one arrived"
        if event["event"] == "snoozed":
            return "Pushed a reminder back" + (f" (it is one of {what})" if event["series_id"] else "")
        return {"paused": "Paused", "resumed": "Resumed", "skipped": "Skipped the next time of", "stopped": "Stopped"}[event["event"]] + f" {what}"

    def listing():
        agent.make_due_repeats()
        series = agent.schedule.series("all")
        names = {s["id"]: s["content"] for s in series}
        order = {"active": 0, "paused": 1, "ended": 2}
        items = sorted((public(s) for s in series), key=lambda s: (order[s["state"]], s["id"]))
        recent = agent.schedule.events()[-EVENTS_SHOWN:][::-1]
        events = [
            {"id": e["id"], "event": e["event"], "at": e["at"], "who": e["actor"], "text": printable(sentence(e, {k: printable(v) for k, v in names.items()}))}
            for e in recent
        ]
        return {"series": items, "events": events, "counts": {state: sum(1 for s in items if s["state"] == state) for state in SERIES_STATES}}

    @app.get("/api/scheduled")
    def list_scheduled():
        return listing()

    @app.post("/api/scheduled", status_code=201)
    def make_scheduled(body: SeriesBody):
        try:
            series = agent.schedule.create(body.text, body.repeat, source="page")
        except diya_time.NotUnderstood as exc:
            raise HTTPException(status_code=422, detail=printable(f"I could not read {' '.join(body.repeat.split())[:60]!r} as a repeat: {exc.reason}"))
        except diya_schedule.ScheduleError as exc:
            raise _refusal(exc)
        return {"created": public(series), "assumed": [printable(item) for item in series["assumed"]], **listing()}

    def change(series_id, action):
        _check_id(series_id, "repeating reminder")
        try:
            getattr(agent.schedule, action)(series_id)
        except diya_schedule.ScheduleError as exc:
            raise _refusal(exc)
        return {"id": series_id, **listing()}

    @app.post("/api/scheduled/{series_id}/pause")
    def pause(series_id: int):
        return change(series_id, "pause")

    @app.post("/api/scheduled/{series_id}/resume")
    def resume(series_id: int):
        return change(series_id, "resume")

    @app.post("/api/scheduled/{series_id}/skip")
    def skip(series_id: int):
        return change(series_id, "skip")

    @app.post("/api/scheduled/{series_id}/stop")
    def stop(series_id: int):
        return change(series_id, "stop")

    @app.post("/api/reminders/{reminder_id}/snooze")
    def snooze(reminder_id: int, body: SnoozeBody):
        _check_id(reminder_id, "reminder")
        try:
            moved = agent.schedule.snooze(reminder_id, body.when)
        except diya_time.NotUnderstood as exc:
            raise HTTPException(status_code=422, detail=printable(f"I could not tell when {' '.join(body.when.split())[:60]!r} is: {exc.reason}"))
        except diya_schedule.ScheduleError as exc:
            raise _refusal(exc)
        return {"id": reminder_id, "due": moved["due_ts"], "due_text": printable(moved["due_text"]), "assumed": [printable(a) for a in moved["assumed"]]}
