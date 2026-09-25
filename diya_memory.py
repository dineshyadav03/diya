"""Diya's reviewed memory: the facts Dreaming stages, and what a person decides about each one.

The design and the reasons for every choice here are in docs/STAGE2_DESIGN.md (section 3). In short:
a fact is a row in `facts` with one of four statuses, and only `accepted` facts are ever meant to
reach the model (see render_profile).

    candidate --accept--> accepted --retire--> retired --restore--> accepted
    candidate --reject--> rejected --reopen--> candidate

Nothing else is legal. Every change is ONE transaction that updates the status and appends a row
to `fact_events`, so the two cannot disagree (verify_integrity() checks that they don't), and every
decision starts with BEGIN IMMEDIATE so that "is there room?" and "accept it" cannot be separated
by another process doing the same thing.

Importing this module has no side effects; a Memory touches the database only when it is used.
"""
from __future__ import annotations

import contextlib
import json
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

# Proposals from the design doc (D7), starting points to tune, not findings. The model is sent the
# profile on every turn, so it is bounded: per fact, and in total as it is rendered for the model.
MAX_FACT_CHARS = 200
MAX_PROFILE_CHARS = 2000

STATUSES = ("candidate", "accepted", "rejected", "retired")
SOURCES = ("dreaming", "legacy_profile", "manual")
ACTORS = ("cli", "api", "import", "system")

# action -> (the status a fact must be in, the status it ends up in)
ACTIONS = {
    "accept": ("candidate", "accepted"),
    "reject": ("candidate", "rejected"),
    "reopen": ("rejected", "candidate"),
    "retire": ("accepted", "retired"),
    "restore": ("retired", "accepted"),
}
# the event each action records
ACTION_EVENT = {
    "accept": "accepted",
    "reject": "rejected",
    "reopen": "reopened",
    "retire": "retired",
    "restore": "restored",
}
# the status an event leaves a fact in; None means the event does not change the status. Replaying
# a fact's events in order must land on its current status -- that is the integrity check.
EVENT_STATUS = {
    "ingested": "candidate",
    "imported": "accepted",
    "added": "accepted",
    "accepted": "accepted",
    "rejected": "rejected",
    "reopened": "candidate",
    "retired": "retired",
    "restored": "accepted",
    "edited": None,
}


class FactError(Exception):
    """A change to the fact store that was refused. Nothing was written."""


class InvalidFact(FactError):
    """The text (or a field next to it) is not something that may be stored."""


class UnknownFact(FactError):
    """There is no fact with that id."""


class IllegalTransition(FactError):
    """The fact is not in a status that action applies to."""


class DuplicateFact(FactError):
    """An accepted fact already says the same thing."""


class BudgetExceeded(FactError):
    """Accepting this fact would take the profile over its size limit."""


# Characters that are invisible or steer how text is displayed. A fact is model output, and a person
# reads it in a terminal or a page: an escape sequence or a bidirectional override could make the
# screen say something the stored text does not (design doc, T3). U+200C/U+200D (joiners) are NOT
# listed: real scripts and emoji sequences need them.
_INVISIBLE = frozenset(
    "؜​‎‏‪‫‬‭‮⁠⁦⁧⁨⁩﻿"
)


def check_text(text):
    """Raise InvalidFact unless `text` is a fact in canonical form: text, non-empty, trimmed, single
    spaces only, no line breaks or tabs, no control characters, nothing invisible. Refuses rather
    than repairs: cleaning a line up is normalise_fact's job, and the store is the last line of
    defence for whatever called it."""
    if not isinstance(text, str):
        raise InvalidFact("a fact is text")
    if not text:
        raise InvalidFact("a fact cannot be empty")
    if text != " ".join(text.split()):
        raise InvalidFact(f"a fact is one trimmed line with single spaces, got {ascii(text)[:60]}")
    for char in text:
        if unicodedata.category(char) in ("Cc", "Cs", "Co", "Zl", "Zp") or char in _INVISIBLE:
            raise InvalidFact(f"a fact cannot contain the character {ascii(char)}")


def text_key(text):
    """A fact's identity: the same words in any capitalisation are the same fact."""
    return text.casefold()


def render_profile(texts):
    """The facts as the model is given them (after the header diya.Agent.with_profile adds). The
    total budget is measured on this string, so what is counted is what is sent."""
    return "\n".join("- " + text for text in texts)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _check_actor(actor):
    if actor not in ACTORS:
        raise ValueError(f"actor must be one of {', '.join(ACTORS)}, got {actor!r}")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)  # True == 1 in Python, but is no id


_FACT_COLUMNS = "id, text, status, source, batch_first, batch_last, position, model, extracted_at, raw, flags, created_at"


def _fact(row):
    keys = ("id", "text", "status", "source", "batch_first", "batch_last", "position", "model",
            "extracted_at", "raw", "flags", "created_at")
    fact = dict(zip(keys, row))
    fact["flags"] = json.loads(fact["flags"])
    return fact


class Memory:
    """The fact store, bound to one `diya_db.Store`. Each call uses its own short-lived connection,
    as Store does."""

    def __init__(self, store):
        self.store = store

    # ---- connections ----
    @contextlib.contextmanager
    def _read(self):
        conn = self.store.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def _write(self):
        """One transaction holding the write lock from the first statement: what it checks is still
        true when it writes. Committed if the block finishes, rolled back if it raises."""
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

    # ---- reading ----
    def get(self, fact_id):
        with self._read() as conn:
            row = conn.execute(f"SELECT {_FACT_COLUMNS} FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            raise UnknownFact(f"there is no fact {fact_id}")
        return _fact(row)

    def facts(self, status=None):
        """Every fact (or every fact with `status`), oldest first."""
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}, got {status!r}")
        query = f"SELECT {_FACT_COLUMNS} FROM facts"
        args = ()
        if status is not None:
            query += " WHERE status = ?"
            args = (status,)
        with self._read() as conn:
            rows = conn.execute(query + " ORDER BY id", args).fetchall()
        return [_fact(row) for row in rows]

    def events(self, fact_id):
        """A fact's history, oldest first, as (event, actor, at, detail)."""
        with self._read() as conn:
            return conn.execute(
                "SELECT event, actor, at, detail FROM fact_events WHERE fact_id = ? ORDER BY id", (fact_id,)
            ).fetchall()

    def counts(self):
        with self._read() as conn:
            found = dict(conn.execute("SELECT status, COUNT(*) FROM facts GROUP BY status"))
        return {status: found.get(status, 0) for status in STATUSES}

    def accepted_texts(self):
        """What the model may be told, oldest first. Nothing that is not accepted is ever returned."""
        with self._read() as conn:
            rows = conn.execute("SELECT text FROM facts WHERE status = 'accepted' ORDER BY id").fetchall()
        return [row[0] for row in rows]

    def render(self):
        """The accepted facts as the model is given them; '' when there are none."""
        return render_profile(self.accepted_texts())

    # ---- adding ----
    def add_candidate(self, text, *, batch_first, batch_last, position, model, extracted_at, raw,
                      flags=(), actor="system"):
        """Record one staged fact as a candidate. Returns its id, or None if this slot -- this
        position in the queue record that starts at `batch_first` -- was already recorded, which is
        what makes ingesting the same queue twice harmless."""
        _check_actor(actor)
        check_text(text)
        if not (_is_int(batch_first) and _is_int(batch_last) and _is_int(position)):
            raise InvalidFact("a candidate needs integer batch_first, batch_last and position")
        if batch_last < batch_first or position < 0:
            raise InvalidFact("batch_last cannot be before batch_first, and position cannot be negative")
        if not isinstance(raw, str) or not isinstance(model, str) or not isinstance(extracted_at, str):
            raise InvalidFact("a candidate needs the raw line, the model and the time it was extracted")
        if not all(isinstance(flag, str) for flag in flags):
            raise InvalidFact("flags are text")
        with self._write() as conn:
            if conn.execute(
                "SELECT 1 FROM facts WHERE source = 'dreaming' AND batch_first = ? AND position = ?",
                (batch_first, position),
            ).fetchone():
                return None
            now = _now()
            cur = conn.execute(
                "INSERT INTO facts (text, text_key, status, source, batch_first, batch_last, position, model,"
                " extracted_at, raw, flags, created_at) VALUES (?, ?, 'candidate', 'dreaming', ?, ?, ?, ?, ?, ?, ?, ?)",
                (text, text_key(text), batch_first, batch_last, position, model, extracted_at, raw,
                 json.dumps(list(flags)), now),
            )
            self._event(conn, cur.lastrowid, "ingested", actor, now)
            return cur.lastrowid

    def add_manual(self, text, actor):
        """A fact the person typed themselves: they are the reviewer, so it goes in already accepted.
        Held to the same duplicate and size limits as any other accept."""
        _check_actor(actor)
        check_text(text)
        with self._write() as conn:
            self._check_room(conn, None, text, enforce_fact_length=True)
            now = _now()
            cur = conn.execute(
                "INSERT INTO facts (text, text_key, status, source, flags, created_at)"
                " VALUES (?, ?, 'accepted', 'manual', '[]', ?)",
                (text, text_key(text), now),
            )
            self._event(conn, cur.lastrowid, "added", actor, now)
            return cur.lastrowid

    # ---- deciding ----
    def decide(self, fact_id, action, actor):
        """Apply `action` (accept, reject, reopen, retire or restore) to a fact. Raises FactError, and
        writes nothing, if the fact is not in a status that action applies to, or (accept, restore)
        if an accepted fact already says the same thing or the profile has no room."""
        _check_actor(actor)
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {', '.join(ACTIONS)}, got {action!r}")
        needs, becomes = ACTIONS[action]
        with self._write() as conn:
            row = conn.execute("SELECT status, text FROM facts WHERE id = ?", (fact_id,)).fetchone()
            if row is None:
                raise UnknownFact(f"there is no fact {fact_id}")
            status, text = row
            if status != needs:
                raise IllegalTransition(f"fact {fact_id} is {status}; only a {needs} fact can be {ACTION_EVENT[action]}")
            if becomes == "accepted":
                # Restoring is not held to the per-fact length: a fact that was accepted once
                # (or imported from the old profile) stays restorable. Everything else is.
                self._check_room(conn, fact_id, text, enforce_fact_length=(action == "accept"))
            now = _now()
            conn.execute("UPDATE facts SET status = ? WHERE id = ?", (becomes, fact_id))
            self._event(conn, fact_id, ACTION_EVENT[action], actor, now)

    def edit(self, fact_id, text, actor):
        """Reword a candidate before deciding on it. The previous wording stays in the event."""
        _check_actor(actor)
        check_text(text)
        with self._write() as conn:
            row = conn.execute("SELECT status, text FROM facts WHERE id = ?", (fact_id,)).fetchone()
            if row is None:
                raise UnknownFact(f"there is no fact {fact_id}")
            status, old = row
            if status != "candidate":
                raise IllegalTransition(f"fact {fact_id} is {status}; only a candidate can be edited")
            now = _now()
            conn.execute("UPDATE facts SET text = ?, text_key = ? WHERE id = ?", (text, text_key(text), fact_id))
            self._event(conn, fact_id, "edited", actor, now, json.dumps({"from": old}))

    # ---- checking ----
    def verify_integrity(self):
        """Everything that should always be true of the store, checked; returns a list of problems
        (empty when it is sound). SQLite does not enforce the foreign key here, so this is where an
        orphaned event, or a status that disagrees with the fact's own history, is found."""
        problems = []
        with self._read() as conn:
            facts = conn.execute("SELECT id, text, text_key, status FROM facts ORDER BY id").fetchall()
            events = conn.execute("SELECT id, fact_id, event, actor FROM fact_events ORDER BY id").fetchall()
        known = {row[0] for row in facts}
        history = defaultdict(list)
        for event_id, fact_id, event, actor in events:
            if fact_id not in known:
                problems.append(f"event {event_id} belongs to fact {fact_id}, which does not exist")
            if event not in EVENT_STATUS:
                problems.append(f"event {event_id} is of an unknown kind {event!r}")
            if actor not in ACTORS:
                problems.append(f"event {event_id} has an unknown actor {actor!r}")
            history[fact_id].append(event)
        accepted_keys = defaultdict(list)
        for fact_id, text, key, status in facts:
            if status not in STATUSES:
                problems.append(f"fact {fact_id} has an unknown status {status!r}")
            if not history[fact_id]:
                problems.append(f"fact {fact_id} has no events")
            else:
                replayed = None
                for event in history[fact_id]:
                    replayed = EVENT_STATUS.get(event) or replayed
                if replayed != status:
                    problems.append(f"fact {fact_id} is {status} but its events say {replayed}")
            try:
                check_text(text)
            except InvalidFact as exc:
                problems.append(f"fact {fact_id}: {exc}")
            if key != text_key(text):
                problems.append(f"fact {fact_id}: its identity does not match its text")
            if status == "accepted":
                accepted_keys[key].append(fact_id)
        for ids in accepted_keys.values():
            if len(ids) > 1:
                problems.append(f"facts {ids} are all accepted and say the same thing")
        return problems

    # ---- internals ----
    @staticmethod
    def _event(conn, fact_id, event, actor, at, detail=None):
        conn.execute(
            "INSERT INTO fact_events (fact_id, event, actor, at, detail) VALUES (?, ?, ?, ?, ?)",
            (fact_id, event, actor, at, detail),
        )

    @staticmethod
    def _check_room(conn, fact_id, text, enforce_fact_length):
        """Inside the write transaction: would accepting `text` (as fact `fact_id`, or a new one when
        None) repeat an accepted fact or take the profile over its limit?"""
        if enforce_fact_length and len(text) > MAX_FACT_CHARS:
            raise InvalidFact(
                f"this fact is {len(text)} characters and the limit is {MAX_FACT_CHARS}; edit it shorter first"
            )
        own = -1 if fact_id is None else fact_id
        twin = conn.execute(
            "SELECT id FROM facts WHERE status = 'accepted' AND text_key = ? AND id != ?", (text_key(text), own)
        ).fetchone()
        if twin:
            raise DuplicateFact(f"fact {twin[0]} says the same thing and is already accepted")
        others = [
            row[0]
            for row in conn.execute("SELECT text FROM facts WHERE status = 'accepted' AND id != ? ORDER BY id", (own,))
        ]
        used = len(render_profile(others))
        total = len(render_profile(others + [text]))
        if total > MAX_PROFILE_CHARS:
            raise BudgetExceeded(
                f"memory is full: {used} of {MAX_PROFILE_CHARS} characters are used and this fact needs "
                f"{total - used} more. Retire a fact first."
            )
