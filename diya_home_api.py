"""Home over HTTP (docs/HOME_DESIGN.md): the route behind the UI's Home page.

    GET /api/home     the cards for today, found by code (diya_home.py): reminders and tasks that need the person, a question about memory, an action waiting for a yes, the next event on the calendar

GET only. Acting on a card is done by the routes that already exist (the card says which), so nothing new can change anything. Each source is read on its own and a source that cannot be read is named in
`problems` instead of failing the page. Google Calendar is asked at most once every CALENDAR_CACHE_SECONDS, however often the page looks. Every word sent back goes through diya_memory.printable.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import diya_brief
import diya_connectors
import diya_google_calendar
import diya_home
import diya_memory
import diya_time
from diya_brief_api import _safe
from diya_memory import FactError
from diya_questions import Questions

CALENDAR_CACHE_SECONDS = 120


def register(app, config, agent):
    """Add the route to `app`, directly, like every other route. Nothing is read here: the rows are read per request."""
    cache = {"at": None, "day": None, "events": [], "problem": None}

    def calendar(now):
        """(whether the calendar is connected, today's events from now on, why they could not be read or None)."""
        if not diya_connectors.is_connected(config, "google_calendar"):
            return False, [], None
        fresh = cache["at"] is not None and cache["day"] == now.date() and time.monotonic() - cache["at"] < CALENDAR_CACHE_SECONDS
        if not fresh:
            start = datetime.combine(now.date(), now.time()).astimezone()
            end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).astimezone()
            events, problem = diya_google_calendar.events_between(config, start, end, 10)
            cache.update(at=time.monotonic(), day=now.date(), events=events, problem=problem)
        return True, cache["events"], cache["problem"]

    def waiting_questions(now):
        if not config.auto_memory:
            return []
        memory, queue = diya_memory.open_memory(agent.store, agent.config), Questions(agent.store, quiet=diya_time.parse_quiet(config.questions_quiet))
        queue.refill(memory, now)
        shown = []
        for item in queue.visible(now):
            try:
                shown.append(queue.describe(memory, item))
            except FactError:
                continue  # its fact is gone: the next refill closes it
        return shown

    @app.get("/api/home")
    def home():
        agent.make_due_repeats()  # so a repeating reminder whose time has come is here, whoever looks first
        now, problems = agent.now(), []
        reminders = agent.store.reminders("pending")
        series_ids = agent.schedule.series_of([row["id"] for row in reminders])
        brief = diya_brief.build(now, reminders, agent.tasks.tasks("open"), agent.schedule.series("active"), series_ids)
        questions, pending, events, connected = [], [], [], False
        try:
            questions = waiting_questions(now)
        except Exception as exc:  # noqa: BLE001 -- one source that fails must not take the page down
            problems.append(f"Memory questions could not be read ({type(exc).__name__}).")
        try:
            agent.actions.reconcile()
            pending = agent.actions.pending()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Waiting actions could not be read ({type(exc).__name__}).")
        try:
            connected, events, problem = calendar(now)
            if problem:
                problems.append(problem)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Google Calendar could not be read ({type(exc).__name__}).")
        return _safe(diya_home.build(now, brief, questions, pending, events, calendar=connected, problems=problems))
