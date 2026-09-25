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
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple

# Proposals from the design doc (D7), starting points to tune, not findings. The model is sent the
# profile on every turn, so it is bounded: per fact, and in total as it is rendered for the model.
VERIFIER_PREFIX = "verifier:"  # the flag the optional model check leaves: verifier:yes, verifier:no or verifier:unclear (diya_verifier.py)
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
    "flagged": None,  # the advisory checks changed what they say about a fact; never its status
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


class SourceUnreadable(FactError):
    """The staged queue or the old profile could not be read, so nothing was taken from it."""


# Characters that are invisible or steer how text is displayed. A fact is model output, and a person
# reads it in a terminal or a page: an escape sequence or a bidirectional override could make the
# screen say something the stored text does not (design doc, T3). U+200C/U+200D (joiners) are NOT
# listed: real scripts and emoji sequences need them.
_INVISIBLE = frozenset(
    "\u061c\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2060\u2066\u2067\u2068\u2069\ufeff"
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


# ---- cleaning up a staged line (design doc D4) -----------------------------------------------------

FLAG_PREAMBLE = "preamble"  # looks like the model introducing its list, not a fact
FLAG_TOO_LONG = "too_long"  # over MAX_FACT_CHARS: it cannot be accepted until it is edited shorter

# One list marker at the start of a line: a bullet character, or a number and a . or ). It must be
# followed by whitespace or the end of the line, so "-5 degrees is cold" keeps its minus sign.
_LIST_MARKER = re.compile(r"(?:[-*\u2022\u2023\u25e6\u2043\u2219]|\d{1,3}[.)])(?:\s+|$)")
_PREAMBLE = re.compile(r"(?:here (?:are|is)|new facts?|the following|facts?:)\b", re.IGNORECASE)
_NONE = re.compile(r"none\.?", re.IGNORECASE)


class Normalised(NamedTuple):
    text: str
    flags: tuple


def _unwanted(char):
    return unicodedata.category(char) in ("Cc", "Cs", "Co") or char in _INVISIBLE


def normalise_fact(line):
    """Turn one line of Dreaming's reply into the fact it holds, or None if it holds none.

    Every kind of whitespace (line breaks, tabs, U+2028, a non-breaking space) becomes one space; one
    leading list marker is dropped; control characters and invisible or bidirectional ones are
    deleted (so nothing stored can carry a terminal escape). What is left always passes check_text.
    A blank line, a lone marker and the model's own `NONE` are None. Nothing else is dropped: a line
    that looks like the model introducing its list, or that is over the length limit, is kept and
    FLAGGED, because hiding a line is a decision and this stage records its decisions."""
    if not isinstance(line, str):
        return None
    text = " ".join(line.split())  # whitespace first: a tab or line break is a gap, not something to delete
    # Delete the rest BEFORE looking for the marker: a byte order mark or a zero-width character in
    # front of the "-" would otherwise hide it, and the bullet would stay in the fact.
    text = " ".join("".join(char for char in text if not _unwanted(char)).split())
    text = _LIST_MARKER.sub("", text, count=1) if _LIST_MARKER.match(text) else text
    if not text or _NONE.fullmatch(text):
        return None
    flags = []
    if text.endswith(":") or _PREAMBLE.match(text):
        flags.append(FLAG_PREAMBLE)
    if len(text) > MAX_FACT_CHARS:
        flags.append(FLAG_TOO_LONG)
    return Normalised(text, tuple(flags))


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


@dataclass(frozen=True)
class ImportResult:
    imported: int  # lines taken in as accepted facts
    already: int  # lines that were imported by an earlier run (whatever became of them since)
    duplicates: int  # lines that repeat another line or an accepted fact
    chars_used: int  # the accepted facts as rendered for the model, after this import
    over_budget: bool  # chars_used is over MAX_PROFILE_CHARS: no NEW fact can be accepted until it is not


@dataclass(frozen=True)
class IngestReport:
    records: int = 0  # well-formed records found in the staged queue
    bad_records: int = 0  # of those, records whose `facts` is not a list
    new: int = 0  # candidates created by this run
    already: int = 0  # facts whose queue slot an earlier run had already recorded
    skipped: int = 0  # lines with nothing to keep (blank, a lone marker, NONE, not text)


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

    def has_legacy_import(self):
        """Has the old profile ever been taken in? True whatever became of those facts since, so a fact
        someone retired never causes the file to be imported again."""
        with self._read() as conn:
            return conn.execute("SELECT 1 FROM facts WHERE source = 'legacy_profile' LIMIT 1").fetchone() is not None

    def known_keys(self):
        """The identity (text_key) of every fact of any status: everything the store has seen."""
        with self._read() as conn:
            return {row[0] for row in conn.execute("SELECT text_key FROM facts")}

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

    def import_legacy(self, items, actor="import"):
        """Take the lines of the old `user_profile.txt` in as accepted facts, all or none.

        `items` is (text, raw, flags) for each line, the text already cleaned by normalise_fact. These
        facts are what the model has been told until now, so they go in as they are: exempt from the
        per-fact and total limits (an existing profile is not thrown away because a limit is new; going
        over only stops NEW facts being accepted, see ImportResult.over_budget). A line is skipped, not
        an error, if it says the same as a fact that is already accepted, or if it was imported before
        -- even if that one has since been retired, so running the import again never brings back a
        fact someone has removed."""
        _check_actor(actor)
        imported = already = duplicates = 0
        taken = set()
        with self._write() as conn:
            for text, raw, flags in items:
                check_text(text)
                key = text_key(text)
                if key in taken:
                    duplicates += 1
                elif conn.execute(
                    "SELECT 1 FROM facts WHERE source = 'legacy_profile' AND text_key = ?", (key,)
                ).fetchone():
                    already += 1
                elif conn.execute("SELECT 1 FROM facts WHERE status = 'accepted' AND text_key = ?", (key,)).fetchone():
                    duplicates += 1
                else:
                    now = _now()
                    cur = conn.execute(
                        "INSERT INTO facts (text, text_key, status, source, raw, flags, created_at)"
                        " VALUES (?, ?, 'accepted', 'legacy_profile', ?, ?, ?)",
                        (text, key, raw, json.dumps(list(flags)), now),
                    )
                    self._event(conn, cur.lastrowid, "imported", actor, now)
                    taken.add(key)
                    imported += 1
            used = len(render_profile([row[0] for row in conn.execute(
                "SELECT text FROM facts WHERE status = 'accepted' ORDER BY id")]))
        return ImportResult(imported, already, duplicates, used, used > MAX_PROFILE_CHARS)

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
                article = "an" if needs[0] in "aeiou" else "a"
                raise IllegalTransition(f"fact {fact_id} is {status}; only {article} {needs} fact can be {ACTION_EVENT[action]}")
            if becomes == "accepted":
                # Restoring is not held to the per-fact length: a fact that was accepted once
                # (or imported from the old profile) stays restorable. Everything else is.
                self._check_room(conn, fact_id, text, enforce_fact_length=(action == "accept"))
            now = _now()
            conn.execute("UPDATE facts SET status = ? WHERE id = ?", (becomes, fact_id))
            self._event(conn, fact_id, ACTION_EVENT[action], actor, now)

    def edit(self, fact_id, text, actor):
        """Reword a candidate before deciding on it. The previous wording stays in the event. A model's second
        opinion (a `verifier:` flag) was about the old wording, so it is dropped, and the event says which."""
        _check_actor(actor)
        check_text(text)
        with self._write() as conn:
            row = conn.execute("SELECT status, text, flags FROM facts WHERE id = ?", (fact_id,)).fetchone()
            if row is None:
                raise UnknownFact(f"there is no fact {fact_id}")
            status, old, flags = row
            if status != "candidate":
                raise IllegalTransition(f"fact {fact_id} is {status}; only a candidate can be edited")
            flags = json.loads(flags)
            stale = [flag for flag in flags if flag.startswith(VERIFIER_PREFIX)]
            detail = {"from": old}
            if stale:
                detail["cleared"] = stale
            now = _now()
            conn.execute("UPDATE facts SET text = ?, text_key = ?, flags = ? WHERE id = ?",
                         (text, text_key(text), json.dumps([flag for flag in flags if flag not in stale]), fact_id))
            self._event(conn, fact_id, "edited", actor, now, json.dumps(detail))

    # ---- the advisory checks (docs/STAGE2_DESIGN.md, D5; the methods are in diya_checks.py) ----
    def set_flags(self, fact_id, flags, actor):
        """Replace a fact's flags. Never touches its status. Records a `flagged` event, with the old and new
        flags, only if they actually changed; returns whether they did."""
        _check_actor(actor)
        if not isinstance(flags, (list, tuple)) or not all(isinstance(flag, str) for flag in flags):
            raise InvalidFact("flags are a list of text")
        new = list(flags)
        with self._write() as conn:
            row = conn.execute("SELECT flags FROM facts WHERE id = ?", (fact_id,)).fetchone()
            if row is None:
                raise UnknownFact(f"there is no fact {fact_id}")
            old = json.loads(row[0])
            if old == new:
                return False
            conn.execute("UPDATE facts SET flags = ? WHERE id = ?", (json.dumps(new), fact_id))
            self._event(conn, fact_id, "flagged", actor, _now(), json.dumps({"from": old, "to": new}))
            return True

    def run_checks(self, actor="system"):
        """Run the deterministic checks on every candidate and record what they say. Advisory only: no
        fact's status changes, whatever a check finds. The checks look at the user messages a fact was
        extracted from and at every other fact, so they are recomputed each time -- a fact that was a
        `duplicate` stops being one when the accepted copy is retired. What cleaning says about the text
        (preamble, too_long) is recomputed too, so editing a fact shorter drops its `too_long` flag; those
        flags stay in front. A model's second opinion (`verifier:`), which is asked for on request and cannot be
        recomputed here, is kept, at the end. Returns (candidates checked, how many changed)."""
        import diya_checks

        every = self.facts()
        checked = changed = 0
        for fact in every:
            if fact["status"] != "candidate":
                continue
            checked += 1
            if fact["batch_first"] is None:
                messages = []
            else:
                messages = [
                    (m["id"], m["content"])
                    for m in self.store.get_messages_between(fact["batch_first"], fact["batch_last"])
                    if m["role"] == "user"  # the extractor only ever saw the user's own words
                ]
            others = [{"id": o["id"], "text": o["text"], "status": o["status"]} for o in every if o["id"] != fact["id"]]
            cleaned = normalise_fact(fact["text"])  # what cleaning says about the text as it is NOW (it may have been edited)
            kept = list(cleaned.flags) if cleaned is not None else []
            opinion = [flag for flag in fact["flags"] if flag.startswith(VERIFIER_PREFIX)]
            flags = kept + diya_checks.check_flags({"id": fact["id"], "text": fact["text"]}, messages, others) + opinion
            if self.set_flags(fact["id"], flags, actor):
                changed += 1
        return checked, changed

    # ---- checking the store itself ----
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


# ---- getting facts in: the staged queue and the old profile -------------------------------------


def ingest_queue(memory, config, actor="cli"):
    """Copy what Dreaming has staged into the store as candidates. Safe to run as often as you like:
    each fact is keyed by (the queue record's first message id, its position in that record's list),
    so a fact already recorded is never recorded twice, whatever has happened to it since.

    The queue itself is only ever READ. It stays exactly as Dreaming wrote it -- Dreaming finds a
    record it has already staged by scanning this file, so removing or editing one would make it
    extract the same messages again (design doc P1) -- and neither the checkpoint nor the log is
    touched. Reading goes through Dreamer.staged_batches(), so there is one tolerant reader of that
    file, not two. Raises SourceUnreadable, having ingested nothing, if the file cannot be read."""
    from dreaming import Dreamer  # here, not at the top: it brings in the OpenAI client

    try:
        batches = Dreamer(config).staged_batches()
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceUnreadable(f"could not read the staged queue {config.dream_pending_path}: {exc}") from exc

    records = bad_records = new = already = skipped = 0
    for record in batches:
        records += 1
        lines = record.get("facts")
        if not isinstance(lines, list):
            bad_records += 1
            continue
        model = record.get("model") if isinstance(record.get("model"), str) else ""
        staged_at = record.get("timestamp") if isinstance(record.get("timestamp"), str) else ""
        for position, line in enumerate(lines):  # a skipped line still takes its position: slots never shift
            fact = normalise_fact(line)
            if fact is None:
                skipped += 1
                continue
            created = memory.add_candidate(
                fact.text, batch_first=record["first_message_id"], batch_last=record["last_message_id"],
                position=position, model=model, extracted_at=staged_at, raw=line, flags=fact.flags, actor=actor,
            )
            if created is None:
                already += 1
            else:
                new += 1
    return IngestReport(records, bad_records, new, already, skipped)


def import_legacy_profile(memory, config, actor="import"):
    """Take the old `user_profile.txt` into the store as accepted facts (Memory.import_legacy says
    how). The file is read the way Agent.with_profile reads it -- UTF-8, a bad byte replaced rather than
    fatal, any line ending -- and is never modified. No file, or an empty one, imports nothing. Raises
    SourceUnreadable, having imported nothing, if it exists and cannot be read."""
    try:
        with open(config.profile_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except FileNotFoundError:
        lines = []
    except OSError as exc:
        raise SourceUnreadable(f"could not read the profile {config.profile_path}: {exc}") from exc
    items = []
    for line in lines:
        fact = normalise_fact(line)
        if fact is not None:
            items.append((fact.text, line, fact.flags))
    return memory.import_legacy(items, actor=actor)


def profile_lines_not_in_memory(memory, config):
    """How many lines of the old profile file are in no fact at all. A fact of any status counts as "in
    memory" (it has been seen, and a rejected or retired one was decided about), so this only counts lines
    that were never brought in: once the model reads memory and not the file, those lines are invisible to
    it. 0 if there is no readable file."""
    try:
        with open(config.profile_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return 0
    known = memory.known_keys()
    missing = 0
    for line in lines:
        fact = normalise_fact(line)
        if fact is not None and text_key(fact.text) not in known:
            missing += 1
    return missing


# ---- showing facts to a person (the command line and the web UI share these) ---------------------


def printable(text, limit=None):
    """`text` as one line that is safe to show: whitespace of every kind becomes a single space, and
    every control, invisible or direction-changing character is shown as a visible escape (a backslash,
    u and four hex digits) instead of being passed on. Cut to `limit` characters, with an ellipsis, if
    given. Everything read back from the database that a person is shown goes through this: it is model
    output, or something someone typed or pasted, and it must not be able to rewrite what a screen says."""
    text = " ".join(str(text).split())
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip() + "..."
    out = []
    for char in text:
        if _unwanted(char):
            code = ord(char)
            out.append(chr(92) + ("u" + format(code, "04x") if code <= 0xFFFF else "U" + format(code, "08x")))
        else:
            out.append(char)
    return "".join(out)


_VERIFIER_SHORT = {
    "yes": "model's second look: supported (unreliable)",
    "no": "model's second look: not supported (unreliable)",
    "unclear": "model's second look: no clear answer (unreliable)",
}
_FLAG_SHORT = {
    "ungrounded": "ungrounded",
    "instruction_shaped": "looks like an instruction",
    "no_source": "its source messages are gone",
    "preamble": "looks like an introduction, not a fact",
    "too_long": "too long to accept as it is",
}


def flag_short(flag):
    """A flag in a few words, for a list."""
    name, _, arg = flag.partition(":")
    if name == "source_message":
        return f"source message {printable(arg)}"
    if name == "duplicate":
        return f"same as fact {printable(arg)}"
    if name == "similar":
        return f"similar to fact {printable(arg)}"
    if name == "previously_rejected":
        return f"rejected before as fact {printable(arg)}"
    if name == "verifier" and arg in _VERIFIER_SHORT:
        return _VERIFIER_SHORT[arg]
    return _FLAG_SHORT.get(name) or printable(flag)


def flag_long(memory, flag):
    """A flag in a sentence, for one fact's detail; names the other fact when the flag points at one."""
    name, _, arg = flag.partition(":")
    detail = {
        "ungrounded": "few of its words appear in the messages it was extracted from",
        "instruction_shaped": "it talks to the assistant or gives an order, rather than stating something about you",
        "no_source": "none of the messages it was extracted from are in the database any more",
        "preamble": "it reads like the model introducing its list",
        "too_long": f"it is over {MAX_FACT_CHARS} characters; edit it shorter before accepting",
    }
    if name in detail:
        return f"{name}: {detail[name]}"
    if name == "source_message":
        return f"source_message: the message it best matches is {printable(arg)}"
    if name == "verifier" and arg in _VERIFIER_SHORT:
        return (f"verifier: the same small model was asked whether the messages this came from support it, and said {arg}. "
                "It shares the blind spots of the model that proposed the fact, so this is a hint, never evidence.")
    if name in ("duplicate", "similar", "previously_rejected"):
        verb = {"duplicate": "says the same as", "similar": "shares most of its words with",
                "previously_rejected": "is the same as one you rejected,"}[name]
        try:
            other = memory.get(int(arg))
            return f"{name}: {verb} fact {arg} ({other['status']}): {printable(other['text'], 120)}"
        except (ValueError, FactError):
            return f"{name}: {verb} fact {printable(arg)}"
    return printable(flag)
