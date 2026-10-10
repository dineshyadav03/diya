"""Reminders that repeat, and a way to push one back (docs/SCHEDULE_DESIGN.md, D1, D3, D4, D5 and unit R2).

A repeating reminder is a **series**: its words, its rule (diya_repeat, stored as canonical text) and when it next falls.
When that time comes the series makes an ordinary reminder (a row in `reminders` carrying `series_id`), so due, told and done
work exactly as they do for any reminder and no reminder code knows about recurrence. Everything that happens to a series or
one of its reminders is written to an append-only trail, `schedule_events`, with who did it.

    schedule = Schedule(store)
    schedule.create("take out the bins", "every Monday at 9am")     a series; nothing is due yet
    schedule.materialize()                                            make what has come due; call it before looking
    schedule.pause(1); schedule.resume(1); schedule.skip(1); schedule.stop(1)
    schedule.snooze(reminder_id, "in 10 minutes")                     any reminder, repeating or not

The rules that hold whoever asks: a series is made only from words diya_repeat can read; the same words with the same rule
cannot be active twice; no more than MAX_ACTIVE are active; a series that has fallen behind (the machine was off) makes ONE
reminder for the latest time that has passed and records the rest as missed; a reminder of the same series that is still
pending when a newer one arrives is closed as lapsed, not left to pile up. Each call uses its own short-lived connection, as
Store does, and what must be true when it writes is checked inside the write (BEGIN IMMEDIATE).
"""
from __future__ import annotations

import contextlib
import json
from datetime import datetime

import diya_memory
import diya_repeat
import diya_time

MAX_ACTIVE = 20  # series that have not been stopped
MAX_CONTENT_CHARS = 300  # the same limit a one-off reminder has (diya.MAX_REMINDER_CHARS)
MAX_CATCH_UP = 5000  # falls worked through in one look; a series further behind than this is moved on to the next future fall
SOURCES = ("chat", "page")
EVENTS = ("created", "occurred", "lapsed", "missed", "paused", "resumed", "skipped", "stopped", "snoozed")
ACTORS = ("owner", "model", "system")
STATES = ("active", "ended", "all")
FIELDS = ("id", "content", "rule", "said", "next_ts", "paused", "ended", "source", "thread_id", "message_id", "created_at", "ended_at")
_SELECT = "SELECT " + ", ".join(FIELDS) + " FROM reminder_series"


class ScheduleError(Exception):
    """A request about a repeating reminder that cannot be done as asked. The text can be shown to the person."""


class InvalidSeries(ScheduleError):
    pass


class UnknownSeries(ScheduleError):
    pass


class UnknownReminder(ScheduleError):
    pass


class DuplicateSeries(ScheduleError):
    """The same words with the same rule are already active; `series_id` is that series."""

    def __init__(self, message, series_id):
        super().__init__(message)
        self.series_id = series_id


class TooManySeries(ScheduleError):
    pass


class IllegalState(ScheduleError):
    """The series (or reminder) is not in a state this can be done to: pausing what is paused, snoozing what is done."""


def _series(row):
    item = dict(zip(FIELDS, row))
    item["paused"] = bool(item["paused"])
    item["ended"] = bool(item["ended"])
    return item


def describe(series):
    """A series in words for the person: {"rule": "Every Monday at 09:00", "next": "Monday 12 Oct 2026, 09:00" or None}."""
    rule = diya_repeat.Repeat.from_canonical(series["rule"]).describe()
    nxt = diya_time.describe_local(diya_time.local_from_iso(series["next_ts"])) if series["next_ts"] else None
    return {"rule": rule, "next": nxt}


def _tidy(text):
    if not isinstance(text, str):
        raise InvalidSeries("a repeating reminder must be words")
    text = " ".join(text.split())
    if not text:
        raise InvalidSeries("a repeating reminder needs something to remind you about")
    if len(text) > MAX_CONTENT_CHARS:
        raise InvalidSeries(f"a repeating reminder is at most {MAX_CONTENT_CHARS} characters")
    try:
        diya_memory.check_text(text)
    except diya_memory.InvalidFact as exc:
        raise InvalidSeries(str(exc).replace("a fact", "a repeating reminder", 1))
    return text


class Schedule:
    """Repeating reminders, bound to one `diya_db.Store`. `clock` returns the current local time as a naive datetime (the
    Agent's own clock); a parameter so tests do not depend on today."""

    def __init__(self, store, clock=None):
        self.store = store
        self._clock = clock or datetime.now

    @contextlib.contextmanager
    def _read(self):
        conn = self.store.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def _write(self):
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    @staticmethod
    def _event(conn, event, actor, at, series_id=None, reminder_id=None, detail=None):
        if event not in EVENTS or actor not in ACTORS:
            raise ValueError(f"unknown event or actor: {event!r}, {actor!r}")
        conn.execute(
            "INSERT INTO schedule_events (series_id, reminder_id, event, actor, at, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (series_id, reminder_id, event, actor, at, json.dumps(detail, sort_keys=True) if detail is not None else None),
        )

    # ---- reading ----
    def get(self, series_id):
        with self._read() as conn:
            row = conn.execute(_SELECT + " WHERE id = ?", (series_id,)).fetchone()
        if row is None:
            raise UnknownSeries(f"there is no repeating reminder {series_id}")
        return _series(row)

    def series(self, state="active"):
        """Series as dicts (FIELDS; `paused` and `ended` are bools), oldest first. `state`: 'active' (not stopped), 'ended' or 'all'."""
        if state not in STATES:
            raise ValueError(f"state must be one of {', '.join(STATES)}, got {state!r}")
        where = {"active": " WHERE ended = 0", "ended": " WHERE ended = 1", "all": ""}[state]
        with self._read() as conn:
            rows = conn.execute(_SELECT + where + " ORDER BY id").fetchall()
        return [_series(row) for row in rows]

    def events(self, series_id=None, limit=None):
        """The trail, oldest first, as dicts (id, series_id, reminder_id, event, actor, at, detail). `detail` is decoded."""
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise ValueError(f"limit must be a whole number above 0 or None, got {limit!r}")
        query = "SELECT id, series_id, reminder_id, event, actor, at, detail FROM schedule_events"
        args = ()
        if series_id is not None:
            query += " WHERE series_id = ?"
            args = (series_id,)
        query += " ORDER BY id" + (f" LIMIT {limit}" if limit else "")
        with self._read() as conn:
            rows = conn.execute(query, args).fetchall()
        keys = ("id", "series_id", "reminder_id", "event", "actor", "at", "detail")
        return [dict(zip(keys, row), detail=json.loads(row[6]) if row[6] is not None else None) for row in rows]

    def series_of(self, reminder_ids):
        """{reminder id: series id} for those of `reminder_ids` that came from a series."""
        ids = [i for i in reminder_ids if isinstance(i, int) and not isinstance(i, bool)]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with self._read() as conn:
            rows = conn.execute(f"SELECT id, series_id FROM reminders WHERE series_id IS NOT NULL AND id IN ({marks})", ids).fetchall()
        return dict(rows)

    # ---- making one, and changing it ----
    def create(self, content, words, *, source="chat", thread_id=None, message_id=None):
        """Make a repeating reminder and return it (the series as `get` gives it, plus `assumed`: what the rule filled in that
        the person did not say). Nothing is due yet: the first reminder is made when the rule first falls. Raises
        diya_time.NotUnderstood (with a reason) if `words` is not a repeat, and ScheduleError, writing nothing, for words that are
        not a reminder, the same series already active, or too many."""
        if source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}, got {source!r}")
        for name, value in (("thread_id", thread_id), ("message_id", message_id)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"{name} must be a whole number or None, got {value!r}")
        content = _tidy(content)
        now = self._clock()
        rule = diya_repeat.parse_repeat(words, now)
        said = " ".join(words.split())
        rule_text, key = rule.canonical(), diya_memory.text_key(content)
        stamp = diya_time.iso_of_local(now)
        actor = "model" if source == "chat" else "owner"
        with self._write() as conn:
            existing = conn.execute("SELECT id FROM reminder_series WHERE content_key = ? AND rule = ? AND ended = 0", (key, rule_text)).fetchone()
            if existing:
                raise DuplicateSeries("that repeating reminder is already set", existing[0])
            active = conn.execute("SELECT COUNT(*) FROM reminder_series WHERE ended = 0").fetchone()[0]
            if active >= MAX_ACTIVE:
                raise TooManySeries(f"{active} repeating reminders are already set; stop one before making another")
            cur = conn.execute(
                "INSERT INTO reminder_series (content, content_key, rule, said, next_ts, source, thread_id, message_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (content, key, rule_text, said, diya_time.iso_of_local(rule.next_after(now)), source, thread_id, message_id, stamp),
            )
            series_id = cur.lastrowid
            self._event(conn, "created", actor, stamp, series_id=series_id, detail={"rule": rule_text, "said": said})
        return dict(self.get(series_id), assumed=list(rule.assumed))

    def _change(self, series_id, event, allowed, apply):
        """One change to a series, in one write: `allowed(series)` says why it cannot be done (a string) or None; `apply(series,
        now) -> (updates, detail)` says what to set."""
        now = self._clock()
        stamp = diya_time.iso_of_local(now)
        with self._write() as conn:
            row = conn.execute(_SELECT + " WHERE id = ?", (series_id,)).fetchone()
            if row is None:
                raise UnknownSeries(f"there is no repeating reminder {series_id}")
            series = _series(row)
            problem = allowed(series)
            if problem:
                raise IllegalState(problem)
            updates, detail = apply(series, now)
            sets = ", ".join(f"{column} = ?" for column in updates)
            conn.execute(f"UPDATE reminder_series SET {sets} WHERE id = ?", (*updates.values(), series_id))
            self._event(conn, event, "owner", stamp, series_id=series_id, detail=detail)
        return self.get(series_id)

    def pause(self, series_id):
        """Stop a series making reminders until it is resumed."""
        return self._change(
            series_id, "paused",
            lambda s: "that repeating reminder has been stopped" if s["ended"] else "that repeating reminder is already paused" if s["paused"] else None,
            lambda s, now: ({"paused": 1}, None),
        )

    def resume(self, series_id):
        """Let a paused series make reminders again; its next one is worked out from now, so nothing is made for the time it was paused."""
        def apply(series, now):
            rule = diya_repeat.Repeat.from_canonical(series["rule"])
            return {"paused": 0, "next_ts": diya_time.iso_of_local(rule.next_after(now))}, {"was_next": series["next_ts"]}

        return self._change(
            series_id, "resumed",
            lambda s: "that repeating reminder has been stopped" if s["ended"] else None if s["paused"] else "that repeating reminder is not paused",
            apply,
        )

    def skip(self, series_id):
        """Let the next time pass without making a reminder for it."""
        def apply(series, now):
            rule = diya_repeat.Repeat.from_canonical(series["rule"])
            following = rule.next_after(diya_time.local_from_iso(series["next_ts"]))
            return {"next_ts": diya_time.iso_of_local(following)}, {"skipped": series["next_ts"]}

        return self._change(
            series_id, "skipped",
            lambda s: "that repeating reminder has been stopped" if s["ended"] else "that repeating reminder is paused; resume it first" if s["paused"] else None,
            apply,
        )

    def stop(self, series_id):
        """End a series for good. A reminder it already made stays until it is done."""
        return self._change(
            series_id, "stopped",
            lambda s: "that repeating reminder has already been stopped" if s["ended"] else None,
            lambda s, now: ({"ended": 1, "next_ts": None, "ended_at": diya_time.iso_of_local(now)}, None),
        )

    # ---- making what has come due ----
    def materialize(self):
        """Make the reminder for every active series whose time has come, and return the new reminders' ids. Safe to call as
        often as anything looks: with nothing due it asks for no write lock, and two callers cannot both make the same one."""
        now = self._clock()
        stamp = diya_time.iso_of_local(now)
        with self._read() as conn:
            if conn.execute("SELECT 1 FROM reminder_series WHERE ended = 0 AND paused = 0 AND next_ts <= ? LIMIT 1", (stamp,)).fetchone() is None:
                return []
        made = []
        with self._write() as conn:
            due = conn.execute(_SELECT + " WHERE ended = 0 AND paused = 0 AND next_ts <= ? ORDER BY id", (stamp,)).fetchall()
            for row in due:
                series = _series(row)
                try:
                    rule = diya_repeat.Repeat.from_canonical(series["rule"])
                except ValueError:
                    continue  # a rule that cannot be read back is left alone, not guessed at: it stays due and the page shows it
                fall = diya_time.local_from_iso(series["next_ts"])
                latest, count = None, 0
                while fall <= now and count < MAX_CATCH_UP:
                    latest, count = fall, count + 1
                    fall = rule.next_after(fall)
                if latest is None:
                    continue  # due by the UTC text but not yet by the local clock (the hour the clocks change): the next look will do it
                if fall <= now:  # more falls behind than MAX_CATCH_UP: take the most recent one and move on from there
                    latest = rule.before(now)
                    fall = rule.next_after(now)
                if count > 1:
                    self._event(conn, "missed", "system", stamp, series_id=series["id"], detail={"missed": count - 1, "made_for": diya_time.iso_of_local(latest)})
                for old in conn.execute("SELECT id FROM reminders WHERE series_id = ? AND done = 0", (series["id"],)).fetchall():
                    conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (old[0],))
                    self._event(conn, "lapsed", "system", stamp, series_id=series["id"], reminder_id=old[0])
                cur = conn.execute(
                    "INSERT INTO reminders (content, due_at, due_ts, created_at, done, series_id) VALUES (?, ?, ?, ?, 0, ?)",
                    (series["content"], series["said"], diya_time.iso_of_local(latest), stamp, series["id"]),
                )
                made.append(cur.lastrowid)
                self._event(conn, "occurred", "system", stamp, series_id=series["id"], reminder_id=cur.lastrowid, detail={"due": diya_time.iso_of_local(latest)})
                conn.execute("UPDATE reminder_series SET next_ts = ? WHERE id = ?", (diya_time.iso_of_local(fall), series["id"]))
        return made

    # ---- pushing a reminder back ----
    def snooze(self, reminder_id, words):
        """Move a pending reminder (repeating or not) to the time `words` say, to be told again then. Raises diya_time.NotUnderstood
        (with a reason) if `words` is not a time that is still ahead, UnknownReminder, and IllegalState for one that is done."""
        now = self._clock()
        when = diya_time.parse_when(words, now)
        stamp = diya_time.iso_of_local(now)
        with self._write() as conn:
            row = conn.execute("SELECT done, due_ts, series_id FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            if row is None:
                raise UnknownReminder(f"there is no reminder {reminder_id}")
            if row[0]:
                raise IllegalState("that reminder is already done")
            conn.execute("UPDATE reminders SET due_ts = ?, notified_at = NULL WHERE id = ?", (when.iso(), reminder_id))
            self._event(conn, "snoozed", "owner", stamp, series_id=row[2], reminder_id=reminder_id, detail={"from": row[1], "to": when.iso(), "said": " ".join(words.split())})
        return {"id": reminder_id, "due_ts": when.iso(), "due_text": when.describe(), "assumed": list(when.assumed)}
