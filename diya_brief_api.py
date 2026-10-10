"""The day over HTTP (docs/SCHEDULE_DESIGN.md, D8 and unit R5): the route behind the UI's Today page.

    GET /api/today     what is due now and later today, the tasks overdue or due today, and the repeating reminders that
                       will make one next -- built in code from the owner's own rows (diya_brief.py), never written by a model

GET only, and there is nothing to change here: acting on a reminder, a task or a repeating reminder is done on its own page.
The route is behind the access token like the rest of the API. Reminders, tasks and repeating reminders come from the model as
well as from the person, so every word sent back goes through diya_memory.printable(): a control or direction-changing character
is sent as a visible escape.
"""
from __future__ import annotations

import diya_brief
from diya_memory import printable


def _safe(value):
    """`value` with every string in it made safe to show, however deep."""
    if isinstance(value, str):
        return printable(value)
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def register(app, config, agent):
    """Add the route to `app`, directly, like every other route. The rows are read per request: registering touches nothing."""

    @app.get("/api/today")
    def today():
        agent.make_due_repeats()  # so a repeating reminder whose time has come is in the brief, whoever looks first
        now = agent.now()
        reminders = agent.store.reminders("pending")
        series_ids = agent.schedule.series_of([row["id"] for row in reminders])
        return _safe(diya_brief.build(now, reminders, agent.tasks.tasks("open"), agent.schedule.series("active"), series_ids))
