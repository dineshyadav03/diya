"""Home over HTTP (docs/HOME_DESIGN.md): the route behind the UI's Home page.

    GET /api/home     the cards for today, found by code (diya_home.py): reminders and tasks that need the person, a question about memory, an action waiting for a yes, mail waiting for a reply, the next
                      event on the calendar

GET only. Acting on a card is done by the routes that already exist (the card says which), so nothing new can change anything. Each source is read on its own and a source that cannot be read is named in
`problems` instead of failing the page. Google Calendar and Gmail are slow (Gmail took about nine seconds on the real account), so the page never waits for them: they are read in a thread of their own at most
once every CALENDAR_CACHE_SECONDS and MAIL_CACHE_SECONDS, the page is given what was read last time, and a source that has never been read yet is named in `looking` so the page asks again in a few seconds.
Every word sent back goes through diya_memory.printable.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import diya_brief
import diya_connectors
import diya_google_calendar
import diya_home
import diya_mail_waiting
import diya_memory
import diya_time
from diya_brief_api import _safe
from diya_google_mail import MailError
from diya_memory import FactError
from diya_questions import Questions

CALENDAR_CACHE_SECONDS = 120
MAIL_CACHE_SECONDS = 300  # Gmail is asked at most this often, however often the page looks
BACKGROUND = True  # read an account in a thread of its own, never while the page waits; the tests turn this off to read it at once


class _Source:
    """One account, read at most once every `ttl` seconds. `get(key, read)` gives (the last value read for this `key`, or None; whether the first reading is still going)."""

    def __init__(self, name, ttl):
        self.name, self.ttl, self.lock = name, ttl, threading.Lock()
        self.key, self.at, self.value, self.running = None, None, None, False

    def get(self, key, read):
        with self.lock:
            fresh = self.at is not None and self.key == key and time.monotonic() - self.at < self.ttl
            start = not fresh and not self.running
            if start:
                self.running = True
        if start:
            if BACKGROUND:
                threading.Thread(target=self._refresh, args=(key, read), daemon=True, name=f"home-{self.name}").start()
            else:
                self._refresh(key, read)
        with self.lock:
            value = self.value if self.key == key else None
            return value, value is None and self.running

    def _refresh(self, key, read):
        try:
            value = read()
        except Exception as exc:  # noqa: BLE001 -- one source that fails must not take the page down
            value = ([], f"{self.name} could not be read ({type(exc).__name__}).")
        with self.lock:
            self.key, self.at, self.value, self.running = key, time.monotonic(), value, False


def register(app, config, agent):
    """Add the route to `app`, directly, like every other route. Nothing is read here: the rows are read per request."""
    calendar, mail = _Source("Google Calendar", CALENDAR_CACHE_SECONDS), _Source("Gmail", MAIL_CACHE_SECONDS)

    def read_calendar(now):
        start = datetime.combine(now.date(), now.time()).astimezone()
        end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).astimezone()
        return diya_google_calendar.events_between(config, start, end, 10)  # (events, why they could not be read or None)

    def read_mail():
        try:
            return diya_mail_waiting.read(config), None
        except MailError as exc:
            return [], str(exc)

    def waiting_questions(now):
        if not config.auto_memory or not config.ask_memory:
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
        now, problems, looking = agent.now(), [], []
        reminders = agent.store.reminders("pending")
        series_ids = agent.schedule.series_of([row["id"] for row in reminders])
        brief = diya_brief.build(now, reminders, agent.tasks.tasks("open"), agent.schedule.series("active"), series_ids)
        questions, pending, events, letters = [], [], [], []
        try:
            questions = waiting_questions(now)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Memory questions could not be read ({type(exc).__name__}).")
        try:
            agent.actions.reconcile()
            pending = agent.actions.pending()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Waiting actions could not be read ({type(exc).__name__}).")
        connected = diya_connectors.is_connected(config, "google_calendar")
        if connected:
            value, waiting = calendar.get(now.date(), lambda: read_calendar(now))
            events, why = value if value else ([], None)
            if why:
                problems.append(why)
            if waiting:
                looking.append("Google Calendar")
        gmail = diya_connectors.is_connected(config, "google_mail")
        if gmail:
            value, waiting = mail.get(now.date(), read_mail)
            letters, why = value if value else ([], None)
            if why:
                problems.append(why)
            if waiting:
                looking.append("Gmail")
        return _safe(diya_home.build(now, brief, questions, pending, events, calendar=connected, problems=problems, mail=letters, gmail=gmail, looking=looking))
