"""Actions and approvals (docs/ACTIONS_DESIGN.md): the gate every write must go through.

The model PROPOSES an action; this module records it; only the owner APPROVES it; and the code that
actually performs it (`ActionKind.execute`) is reachable from exactly one place, `Actions.run`, which
refuses anything not approved. There is no model in here and no tool that calls `run`.

    pending --approve--> approved --run--> executing --> succeeded | failed | unknown (an effect that cannot tell)
    pending --reject--> rejected          executing --reconcile--> unknown --resolve--> succeeded | failed
    pending | approved --expire--> expired

Nothing else is legal. Like facts (diya_memory.py) every change is ONE transaction that updates the
status and appends a row to `action_events`, so the two cannot disagree (verify_integrity() checks
that they don't), and every decision begins with BEGIN IMMEDIATE so that "is it still pending?" and
"approve it" cannot be separated by another process doing the same.

`approved -> executing` is committed BEFORE the effect is attempted (D4): a crash mid-effect leaves
`executing`, which reconcile() turns into `unknown` -- never into a second attempt. An action is run
at most once, ever.

This module has no kinds of its own: a kind needs the connector it writes to, so the real ones are
declared beside the connectors (diya_connector_tools.real_action_kinds()) and handed in. Every
kind there is a write the owner approves one at a time (docs/ACTIONS_DESIGN.md).

Importing this module has no side effects; an Actions touches the database only when it is used.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import diya_connectors
import diya_journal
import diya_memory
import diya_pause

# Starting points from the design doc (D6), to tune, not findings.
MAX_PENDING = 10  # actions waiting at once
MAX_PER_TURN = 3  # actions one message of the owner's may lead to
EXPIRY = timedelta(hours=24)  # how long a proposal stays open, and how long an approval stays usable
MIN_RECONCILE_AGE = timedelta(seconds=120)  # an `executing` row younger than this is a run still in flight
MAX_ARGS_CHARS = 4000  # the canonical arguments, whole
MAX_SUMMARY_CHARS = 300
MAX_RESULT_CHARS = 2000
MAX_NOTE_CHARS = 300
MAX_TAINT_SOURCES = 20

STATUSES = ("pending", "approved", "executing", "succeeded", "failed", "rejected", "expired", "unknown")
ACTORS = ("model", "owner", "system")
VIA = ("ui", "cli", "auto")  # how the owner decided: the page, `python diya_actions.py`, or "auto": the owner's standing switch for this kind (diya_autoapprove), applied to a proposal made from the owner's own message

# the status each event leaves an action in; replaying an action's events in order must land on its
# current status -- that is the integrity check
EVENT_STATUS = {
    "proposed": "pending",
    "approved": "approved",
    "rejected": "rejected",
    "expired": "expired",
    "executing": "executing",
    "succeeded": "succeeded",
    "failed": "failed",
    "unknown": "unknown",
    "resolved_succeeded": "succeeded",
    "resolved_failed": "failed",
}
# who may record each event. Only the owner can approve, reject or resolve; only the model proposes;
# everything else is the system. Checked on every write path and again by verify_integrity().
EVENT_ACTOR = {
    "proposed": "model",
    "approved": "owner",
    "rejected": "owner",
    "resolved_succeeded": "owner",
    "resolved_failed": "owner",
    "expired": "system",
    "executing": "system",
    "succeeded": "system",
    "failed": "system",
    "unknown": "system",
}

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


class ActionError(Exception):
    """A change to the action store that was refused. Nothing was written."""


class UnknownKind(ActionError):
    """No such kind of action is registered."""


class UnknownAction(ActionError):
    """There is no action with that id."""


class InvalidArgs(ActionError):
    """The arguments (or the note beside a decision) are not something that may be stored."""


class NotConnected(ActionError):
    """The connector this kind of action needs is not connected."""


class TooManyPending(ActionError):
    """Too many actions are already waiting for the owner."""


class TurnLimit(ActionError):
    """This message of the owner's has already led to as many actions as one message may."""


class DuplicatePending(ActionError):
    """The same action is already waiting."""


class Paused(ActionError):
    """Diya is paused (diya_pause.py): an approved action is not run until the owner resumes. The action stays as it was."""


class IllegalTransition(ActionError):
    """The action is not in a status that change applies to."""


class HashMismatch(ActionError):
    """What is being approved is not what the action now says."""


class ActionFailed(Exception):
    """Raised by an ActionKind.execute for a refusal or failure it can describe in one plain sentence;
    the sentence becomes the action's `result`. Only for a failure it KNOWS happened before anything took effect."""


class ActionUncertain(Exception):
    """Raised by an ActionKind.execute when the effect may or may not have happened: the request was sent and no answer
    came back, or the service failed part way. The action becomes `unknown` -- not `failed`, which would invite a second
    attempt that does it twice -- with the sentence as its `result`, for the owner to check and record (D4)."""


@dataclass(frozen=True)
class ActionKind:
    """One TYPE of action (docs/ACTIONS_DESIGN.md, D2): a declaration, like a Connector -- not an action.

    `connector` is the connector that must be connected for this kind to be proposed or run (None for
    a kind that needs none). `validate(args)` raises InvalidArgs; `render(args)` is the one sentence the
    owner approves, built here in code from the arguments and never from anything the model said;
    `execute(config, args)` performs the effect and returns the service's own reply, or raises
    ActionFailed. `tool` is the function spec (OpenAI's tool format, like diya.TOOLS' entries) the model is
    shown so it can PROPOSE this kind of action (docs/ACTIONS_DESIGN.md, D1); None means the model cannot
    propose it at all. Calling that tool only ever records a pending action -- nothing is performed.

    Two optional checks against what the OWNER wrote, applied by Agent only while a message is being answered (the
    model's arguments are untrusted, and a small model proposes things nobody asked for -- measured, section 6):
    `asked(text)` says whether the message asks for this kind of action at all, and a proposal is refused if not;
    `prepare(args, text)` returns the arguments with whatever the message does not support taken out, and notes (plain
    sentences) saying what was, which the model is told. Either is None for a kind that needs neither.

    `auto_ok(args, text)` is only for a kind that may be switched to "do it straight away" (diya_autoapprove): it says whether EVERYTHING in the proposal is made of what the owner wrote in `text` (a title,
    a name, a line of text that they said, a time that they gave and that was not filled in). If it says no, or the kind has none, the proposal waits for an Approve whatever the switch says.

    `resolve(config, args, said)` is for a kind that changes something that already exists at a service (a task, a file, an event, a message). Called by Agent while the proposal is made, AFTER `prepare`, it looks the one
    thing up by the words the person used (a read) and returns the arguments with its exact reference in them (its id, its version), or raises InvalidArgs saying that there is none or that there are several, so that
    a change is never made to something that was only guessed at."""

    name: str
    label: str
    connector: str | None
    validate: object
    render: object
    execute: object
    tool: dict | None = None
    asked: object = None
    prepare: object = None
    auto_ok: object = None
    resolve: object = None

    @property
    def tool_name(self):
        return self.tool["function"]["name"] if self.tool is not None else None

    def __post_init__(self):
        if self.tool is not None:
            function = self.tool.get("function") if isinstance(self.tool, dict) else None
            if not (
                isinstance(function, dict)
                and self.tool.get("type") == "function"
                and isinstance(function.get("name"), str)
                and _TOOL_NAME.fullmatch(function["name"])
                and isinstance(function.get("description"), str)
                and function["description"].strip()
                and isinstance(function.get("parameters"), dict)
            ):
                raise ValueError(f"{self.name}: tool must be a function spec with a lowercase name, a description and parameters")
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"an action kind's name must be lowercase letters, digits and underscores: {self.name!r}")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError(f"{self.name}: an action kind needs a label")
        if self.connector is not None and not _NAME.fullmatch(self.connector):
            raise ValueError(f"{self.name}: connector must be a connector's name or None, got {self.connector!r}")
        for field in ("validate", "render", "execute"):
            if not callable(getattr(self, field)):
                raise ValueError(f"{self.name}: {field} must be a function")
        for field in ("asked", "prepare"):
            if getattr(self, field) is not None and not callable(getattr(self, field)):
                raise ValueError(f"{self.name}: {field} must be a function or None")


def by_name(kinds, name):
    """The kind called `name`, or None. `kinds` is passed explicitly (not a hidden global) so a test can
    supply fakes without touching the real registry."""
    for kind in kinds:
        if kind.name == name:
            return kind
    return None


# ---- the pure parts: arguments, hashing, text ---------------------------------------------------

def _stamp(moment):
    """A moment as UTC text like 2026-10-04T10:15:00Z, which compares in time when compared as text."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)  # True == 1 in Python, but is no id


def clean_args(args):
    """The arguments as they will be stored: a flat dict of names to text, numbers, true/false or None.
    Raises InvalidArgs for anything else. Text must be plain single-line text (diya_memory.check_text:
    no control or invisible characters, which could make the page say something the stored text does
    not) -- the model's arguments are untrusted, and the owner approves what is displayed."""
    if not isinstance(args, dict):
        raise InvalidArgs("the arguments must be a set of named values")
    for key, value in args.items():
        if not isinstance(key, str) or not _TOOL_NAME.fullmatch(key):
            raise InvalidArgs(f"an argument's name must be lowercase letters, digits and underscores: {key!r}")
        if isinstance(value, str):
            try:
                diya_memory.check_text(value)
            except diya_memory.InvalidFact as exc:
                raise InvalidArgs(f"argument {key!r} is not plain single-line text ({exc})") from exc
        elif not (value is None or isinstance(value, (bool, int, float))):
            raise InvalidArgs(f"argument {key!r} must be text, a number, true/false or empty, not {type(value).__name__}")
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise InvalidArgs(f"argument {key!r} is not a usable number")
    if len(canonical(args)) > MAX_ARGS_CHARS:
        raise InvalidArgs(f"the arguments are over {MAX_ARGS_CHARS} characters")
    return dict(args)


def canonical(args):
    """The one JSON text a given set of arguments always becomes: sorted names, no spare spaces."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def args_hash(kind_name, args):
    """What an approval is bound to (D5): the kind and the arguments, exactly. A hash of the kind too, so
    the same arguments proposed under another kind are not the same action."""
    return hashlib.sha256(f"{kind_name}\n{canonical(args)}".encode("utf-8")).hexdigest()


def normalise_args(args):
    """The model's arguments with two repairs, and nothing else touched. Whitespace in text is tidied (runs of spaces,
    tabs, line breaks and non-breaking spaces become one space, the ends are trimmed), so "buy  milk" is proposed as
    "buy milk" instead of bouncing. And an argument that is empty or null is dropped: a small model fills an optional
    argument it has nothing for with "" (measured: 6 of 75 asked proposals, which then bounced and left the owner told
    the model "could not" do something it could), and an empty optional argument is no argument. The owner sees, and the
    hash binds, the repaired arguments. Anything else wrong -- a control or invisible character, the wrong type -- is
    still refused by `clean_args`. Not a dict: returned unchanged, for `clean_args` to refuse."""
    if not isinstance(args, dict):
        return args
    tidied = {key: " ".join(value.split()) if isinstance(value, str) else value for key, value in args.items()}
    return {key: value for key, value in tidied.items() if value is not None and value != ""}


def proposed_text(action, notes=()):
    """What the model is told after it proposed an action (D1): that it is only a proposal, what was proposed, anything
    that was left out of it and why (`notes`, from ActionKind.prepare), and what to say."""
    said = "".join(f" {note}" for note in notes)
    return (
        f"Proposed as action #{action['id']}: {action['summary'].rstrip('.')}.{said} Nothing has happened yet: the owner has "
        "to approve it on the Actions page. Tell the owner it is waiting for them, and do not say it is done."
    )


def proposal_reply(made, ran=()):
    """What to tell the person after the turn made proposals, built by code from what was recorded and never from what the model wrote (2026-10-26: the model wrote "Why? To help test my own system", offered
    to send reminders and added a private fact about a pet, and, in the same chat, two replies saying a folder and a document were "waiting for your approval" when no action had been recorded at all).
    `made` is [(action, notes)] still waiting: each action's own sentence (the one the owner approves). The notes of `prepare` are addressed to the model ("ask the user when it starts"), so they are not shown: what
    was left out of a proposal is plain from its sentence. `ran` is [action] done straight away (diya_autoapprove), each as it ended: what happened is told in its own words, and an outcome that is not known is said to be not known."""
    parts = []
    for action in ran:
        said = action["summary"].rstrip(".") + "."
        result = f" {action['result']}" if action.get("result") else ""
        if action["status"] == "succeeded":
            parts.append(f"Done: {said}{result}")
        elif action["status"] == "unknown":
            parts.append(f"Not sure it was done: {said}{result or ' What happened is not known.'} Look in Google, then record what you found on the Actions page. It will not be tried again.")
        else:
            parts.append(f"Not done: {said}{result or ' It did not run.'}")
    if made:
        lines = [action["summary"].rstrip(".") + "." for action, _notes in made]
        head = f"Ready for your OK: {lines[0]}" if len(lines) == 1 else "Ready for your OK:\n" + "\n".join(f"- {line}" for line in lines)
        parts.append(head + "\n\nNothing is added to your account until you press Approve (under this message, or on the Actions page).")
    return "\n\n".join(parts)


# Words in a reply that say something is waiting for the owner's approval. Used only when the turn recorded no proposal at all: then the claim is false, whoever wrote it.
_CLAIMS_A_PROPOSAL = re.compile(
    r"waiting\s+for\s+(?:your|you|the\s+owner)\b|(?:on|in)\s+(?:the|your)\s+actions\s+page|\b(?:i(?:'ve|\s+have)\s+)?proposed\b|\bapprove\s+(?:it|this)\b|\bawaiting\s+(?:your\s+)?approval",
    re.IGNORECASE,
)


def claims_a_proposal(answer):
    """Does this reply say that something has been proposed or is waiting for approval?"""
    return isinstance(answer, str) and _CLAIMS_A_PROPOSAL.search(answer) is not None


def nothing_was_proposed_reply(example, why=None):
    """What to say when the person asked for an addition, the model's reply said it was waiting for approval, and no action was recorded: that nothing was set up, why if it is known, and how to ask again."""
    reason = f" ({why.rstrip('.')})" if why else ""
    return f"I did not set that up{reason}: nothing is waiting for your approval. Say it again in one line and I will try again, for example '{example}'."


NOT_ASKED_TEXT = (
    "Not proposed: the user did not ask for that. Answer what they said instead, and do not propose it unless they ask."
)


def refused_text(exc):
    """What the model is told when a proposal was refused (an unknown kind, arguments that were not allowed, a
    connector not connected, too many waiting): one plain sentence, and that nothing was recorded."""
    return f"Not proposed: {str(exc).rstrip('.')}. Nothing was recorded; tell the owner so, plainly."


def _clean_summary(summary):
    if not isinstance(summary, str):
        raise InvalidArgs("the action's description must be text")
    try:
        diya_memory.check_text(summary)
    except diya_memory.InvalidFact as exc:
        raise InvalidArgs(f"the action's description is not plain single-line text ({exc})") from exc
    if len(summary) > MAX_SUMMARY_CHARS:
        raise InvalidArgs(f"the action's description is over {MAX_SUMMARY_CHARS} characters")
    return summary


def _clean_sources(sources):
    """Tool names, once each in the order first seen: which tools ran earlier in the turn (D6)."""
    if isinstance(sources, str) or not hasattr(sources, "__iter__"):
        raise InvalidArgs("taint sources must be a list of tool names")
    cleaned = []
    for source in sources:
        if not isinstance(source, str) or not _TOOL_NAME.fullmatch(source):
            raise InvalidArgs(f"a taint source is a tool's name, got {source!r}")
        if source not in cleaned:
            cleaned.append(source)
    if len(cleaned) > MAX_TAINT_SOURCES:
        raise InvalidArgs(f"at most {MAX_TAINT_SOURCES} taint sources")
    return cleaned


def _clip(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _check_via(via):
    if via not in VIA:
        raise ValueError(f"via must be one of {', '.join(VIA)}, got {via!r}")


_ACTION_SELECT = (
    "SELECT id, kind, args, args_hash, summary, status, thread_id, message_id, tainted, taint_sources,"
    " created_at, expires_at, decided_at, executed_at, result FROM actions"
)
_ACTION_KEYS = ("id", "kind", "args", "args_hash", "summary", "status", "thread_id", "message_id", "tainted",
                "taint_sources", "created_at", "expires_at", "decided_at", "executed_at", "result")


def _action(row):
    action = dict(zip(_ACTION_KEYS, row))
    action["args"] = json.loads(action["args"])
    action["taint_sources"] = json.loads(action["taint_sources"])
    action["tainted"] = bool(action["tainted"])
    return action


# ---- the store ------------------------------------------------------------------------------------

class Actions:
    """The action store, bound to one `diya_db.Store`, the config (for connectors and for `execute`) and the
    kinds this install has. Each call uses its own short-lived connection, as Store does. `clock` returns
    an aware datetime; a parameter so tests do not depend on the real time."""

    def __init__(self, store, config, kinds, clock=None):
        self.store = store
        self.config = config
        self.kinds = tuple(kinds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

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
    def get(self, action_id):
        with self._read() as conn:
            row = conn.execute(_ACTION_SELECT + " WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise UnknownAction(f"there is no action {action_id}")
        return _action(row)

    def actions(self, status=None):
        """Every action (or every action with `status`), oldest first."""
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}, got {status!r}")
        query = _ACTION_SELECT
        args = ()
        if status is not None:
            query += " WHERE status = ?"
            args = (status,)
        with self._read() as conn:
            rows = conn.execute(query + " ORDER BY id", args).fetchall()
        return [_action(row) for row in rows]

    def pending(self):
        """What is waiting for the owner now. Closes anything that has expired first, so it is never shown."""
        self.expire()
        return self.actions("pending")

    def events(self, action_id):
        """An action's history, oldest first, as (event, actor, at, detail)."""
        with self._read() as conn:
            return conn.execute(
                "SELECT event, actor, at, detail FROM action_events WHERE action_id = ? ORDER BY id", (action_id,)
            ).fetchall()

    def counts(self):
        with self._read() as conn:
            found = dict(conn.execute("SELECT status, COUNT(*) FROM actions GROUP BY status"))
        return {status: found.get(status, 0) for status in STATUSES}

    # ---- the model's side: propose ----
    def propose(self, kind_name, args, *, thread_id=None, message_id=None, taint_sources=()):
        """Record an action as `pending` and return it. This is the only thing a tool the model can call may
        do (D1): nothing is performed. Raises ActionError, and writes nothing, for an unknown kind, arguments
        that are not plain data or that the kind refuses, a connector that is not connected, the same action
        already waiting, too many waiting, or too many from one message of the owner's (D6)."""
        kind = by_name(self.kinds, kind_name)
        if kind is None:
            raise UnknownKind(f"there is no kind of action called {kind_name!r}")
        args = clean_args(args)
        kind.validate(args)
        self._require_connected(kind)
        summary = _clean_summary(kind.render(args))
        sources = _clean_sources(taint_sources)
        for name, value in (("thread_id", thread_id), ("message_id", message_id)):
            if value is not None and not _is_int(value):
                raise ValueError(f"{name} must be a whole number or None, got {value!r}")
        digest = args_hash(kind.name, args)
        now = self._clock()
        self.expire(now)
        with self._write() as conn:
            if conn.execute(
                "SELECT 1 FROM actions WHERE kind = ? AND args_hash = ? AND status = 'pending'", (kind.name, digest)
            ).fetchone():
                raise DuplicatePending("that exact action is already waiting for the owner")
            waiting = conn.execute("SELECT COUNT(*) FROM actions WHERE status = 'pending'").fetchone()[0]
            if waiting >= MAX_PENDING:
                raise TooManyPending(f"{waiting} actions are already waiting for the owner; none more until some are decided")
            if message_id is not None:
                from_message = conn.execute("SELECT COUNT(*) FROM actions WHERE message_id = ?", (message_id,)).fetchone()[0]
                if from_message >= MAX_PER_TURN:
                    raise TurnLimit(f"one message can lead to at most {MAX_PER_TURN} actions")
            cur = conn.execute(
                "INSERT INTO actions (kind, args, args_hash, summary, status, thread_id, message_id, tainted,"
                " taint_sources, created_at, expires_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
                (kind.name, canonical(args), digest, summary, thread_id, message_id, 1 if sources else 0,
                 json.dumps(sources), _stamp(now), _stamp(now + EXPIRY)),
            )
            action_id = cur.lastrowid
            self._event(conn, action_id, "proposed", _stamp(now))
        return self.get(action_id)

    # ---- the owner's side: approve, reject, resolve ----
    def approve(self, action_id, shown_hash, via):
        """The owner approves what they were SHOWN (D5): `shown_hash` is the hash the page displayed, and a
        different one refuses the approval. This records the decision and does nothing else; `run` performs
        it. Raises ActionError, and writes nothing, unless the action is pending and not expired."""
        _check_via(via)
        now = self._clock()
        self.expire(now)  # an action whose time is up is `expired` from here on, and so is refused below
        with self._write() as conn:
            row = self._locked(conn, action_id)
            if row["status"] != "pending":
                raise IllegalTransition(f"action {action_id} is {row['status']}; only a pending action can be approved")
            if shown_hash != row["args_hash"]:
                raise HashMismatch(f"action {action_id} is not what was shown: it was changed, so it was not approved")
            conn.execute("UPDATE actions SET status = 'approved', decided_at = ? WHERE id = ?", (_stamp(now), action_id))
            self._event(conn, action_id, "approved", _stamp(now), json.dumps({"via": via}))
        return self.get(action_id)

    def reject(self, action_id, via):
        """The owner refuses a pending action. It is never performed."""
        _check_via(via)
        now = self._clock()
        with self._write() as conn:
            row = self._locked(conn, action_id)
            if row["status"] != "pending":
                raise IllegalTransition(f"action {action_id} is {row['status']}; only a pending action can be rejected")
            conn.execute("UPDATE actions SET status = 'rejected', decided_at = ? WHERE id = ?", (_stamp(now), action_id))
            self._event(conn, action_id, "rejected", _stamp(now), json.dumps({"via": via}))
        return self.get(action_id)

    def resolve(self, action_id, happened, via, note=None):
        """The owner records what they found for an `unknown` action (D4): it did happen (`succeeded`) or it did
        not (`failed`). The only way out of `unknown`; an action is never run again to find out."""
        _check_via(via)
        if not isinstance(happened, bool):
            raise ValueError(f"happened must be True or False, got {happened!r}")
        detail = {"via": via}
        if note is not None:
            try:
                diya_memory.check_text(note)
            except diya_memory.InvalidFact as exc:
                raise InvalidArgs(f"the note is not plain single-line text ({exc})") from exc
            if len(note) > MAX_NOTE_CHARS:
                raise InvalidArgs(f"the note is over {MAX_NOTE_CHARS} characters")
            detail["note"] = note
        now = self._clock()
        with self._write() as conn:
            row = self._locked(conn, action_id)
            if row["status"] != "unknown":
                raise IllegalTransition(f"action {action_id} is {row['status']}; only an unknown action can be resolved")
            becomes = "succeeded" if happened else "failed"
            said = "Recorded by the owner: it happened." if happened else "Recorded by the owner: it did not happen."
            conn.execute("UPDATE actions SET status = ?, result = ? WHERE id = ?",
                         (becomes, _clip(said + (f" {note}" if note else ""), MAX_RESULT_CHARS), action_id))
            self._event(conn, action_id, f"resolved_{becomes}", _stamp(now), json.dumps(detail))
        return self.get(action_id)

    # ---- the system's side: run, expire, reconcile ----
    def run(self, action_id):
        """Perform an approved action, at most once ever (D4). `approved -> executing` is committed BEFORE
        the effect is attempted; the outcome is written after. If the process stops in between the action
        stays `executing` and reconcile() will call it `unknown` -- it is not run again. An action that
        cannot start (its connector was disconnected since, its arguments no longer validate or no longer
        match what was approved, its kind is gone) is `failed` without `execute` being called. Returns the
        action as it ends; raises IllegalTransition for one that is not approved or has expired."""
        if diya_pause.is_paused(self.store):  # the kill switch: checked before anything is touched, so the action stays approved and can be run after "resume"
            raise Paused("Diya is paused, so nothing is run. Resume Diya on the Status page; this action stays approved until its day has passed.")
        now = self._clock()
        self.expire(now)  # an approval that outlived its proposal is `expired`, and so is refused below
        problem = None
        with self._write() as conn:
            row = self._locked(conn, action_id)
            if row["status"] != "approved":
                raise IllegalTransition(f"action {action_id} is {row['status']}; only an approved action can be run")
            kind = by_name(self.kinds, row["kind"])
            args = json.loads(row["args"])
            problem = self._cannot_run(kind, row, args)
            if problem:
                conn.execute("UPDATE actions SET status = 'failed', result = ? WHERE id = ?",
                             (_clip(f"Not run: {problem}", MAX_RESULT_CHARS), action_id))
                self._event(conn, action_id, "failed", _stamp(now), json.dumps({"reason": problem}))
            else:
                conn.execute("UPDATE actions SET status = 'executing', executed_at = ? WHERE id = ?", (_stamp(now), action_id))
                self._event(conn, action_id, "executing", _stamp(now))
        if problem:
            return self._journaled(self.get(action_id), 0.0, started=False)
        # The effect is attempted outside any transaction, after "executing" is on disk.
        started = time.monotonic()
        try:
            outcome, event, result = "succeeded", "succeeded", kind.execute(self.config, args)
        except ActionFailed as exc:
            outcome, event, result = "failed", "failed", str(exc) or "the action failed"
        except ActionUncertain as exc:
            outcome, event, result = "unknown", "unknown", str(exc) or "the outcome is not known"
        except Exception as exc:  # anything else the effect raised: it failed, and the owner is told what
            outcome, event, result = "failed", "failed", f"the action stopped with an error: {type(exc).__name__}: {exc}"
        result = _clip("" if result is None else result, MAX_RESULT_CHARS)
        with self._write() as conn:
            changed = conn.execute(
                "UPDATE actions SET status = ?, result = ? WHERE id = ? AND status = 'executing'",
                (outcome, result, action_id),
            ).rowcount
            if not changed:
                raise IllegalTransition(f"action {action_id} was no longer executing when it finished")
            self._event(conn, action_id, event, _stamp(self._clock()),
                        json.dumps({"reason": result}) if outcome == "unknown" else None)
        return self._journaled(self.get(action_id), time.monotonic() - started)

    def _journaled(self, action, seconds, started=True):
        """Put the outcome of a run in the activity record, so the Activity page shows what was done after you approved it next to everything else (DIYA-056): which kind, how it came out, from which chat and message,
        and how long it took. Never the result's words (only their length, as for every tool), and never able to break a run: recording does not raise."""
        status = {"succeeded": "ok", "failed": "error", "unknown": "error"}.get(action["status"], "refused") if started else "refused"  # one that could not even start (its connector was disconnected, its kind is gone) was refused
        note = {"succeeded": "approved action done", "failed": "approved action failed", "unknown": "approved action: outcome not known, look and record what you found"}.get(action["status"], "approved action not started") if started else "approved action not started"
        diya_journal.record(
            self.store, f"approved:{action['kind']}", action["args"], status, kind="flow", thread_id=action["thread_id"], message_id=action["message_id"], result=action["result"], seconds=seconds, note=note,
        )
        return action

    def expire(self, moment=None):
        """Close every pending or approved-but-not-yet-run action whose time is up as of `moment` (default: now)
        (D6): an approval does not outlive its proposal. Returns how many."""
        now = _stamp(moment or self._clock())
        with self._write() as conn:
            rows = conn.execute(
                "SELECT id FROM actions WHERE status IN ('pending', 'approved') AND expires_at <= ? ORDER BY id", (now,)
            ).fetchall()
            for (action_id,) in rows:
                conn.execute("UPDATE actions SET status = 'expired' WHERE id = ?", (action_id,))
                self._event(conn, action_id, "expired", now)
        return len(rows)

    def reconcile(self, older_than=MIN_RECONCILE_AGE):
        """Turn every `executing` action that has been executing longer than `older_than` into `unknown` (D4):
        the process that was running it stopped, so what happened is not known, and it will not be run again.
        A younger one is a run still in flight, in this process or another, and is left alone. Returns how many."""
        now = self._clock()
        cutoff = _stamp(now - older_than)
        with self._write() as conn:
            rows = conn.execute(
                "SELECT id FROM actions WHERE status = 'executing' AND executed_at <= ? ORDER BY id", (cutoff,)
            ).fetchall()
            for (action_id,) in rows:
                conn.execute("UPDATE actions SET status = 'unknown' WHERE id = ?", (action_id,))
                self._event(conn, action_id, "unknown", _stamp(now),
                            json.dumps({"reason": "the process stopped while it was running; the outcome is not known"}))
        return len(rows)

    # ---- checking the store itself ----
    def verify_integrity(self):
        """Everything that should always be true of the store, checked; returns a list of problems (empty when
        it is sound): an event with no action, an unknown event or actor, an event recorded by the wrong actor
        (only the owner approves), a status that disagrees with the action's own history, arguments that do not
        match their hash."""
        problems = []
        with self._read() as conn:
            rows = conn.execute("SELECT id, kind, args, args_hash, status, tainted, taint_sources FROM actions ORDER BY id").fetchall()
            events = conn.execute("SELECT id, action_id, event, actor FROM action_events ORDER BY id").fetchall()
        known = {row[0] for row in rows}
        history = {}
        for event_id, action_id, event, actor in events:
            if action_id not in known:
                problems.append(f"event {event_id} belongs to action {action_id}, which does not exist")
            if event not in EVENT_STATUS:
                problems.append(f"event {event_id} is of an unknown kind {event!r}")
            elif actor != EVENT_ACTOR[event]:
                problems.append(f"event {event_id} ({event}) was recorded by {actor!r}, not {EVENT_ACTOR[event]!r}")
            if actor not in ACTORS:
                problems.append(f"event {event_id} has an unknown actor {actor!r}")
            history.setdefault(action_id, []).append(event)
        for action_id, kind, args, digest, status, tainted, sources in rows:
            if status not in STATUSES:
                problems.append(f"action {action_id} has an unknown status {status!r}")
            seen = history.get(action_id)
            if not seen:
                problems.append(f"action {action_id} has no events")
            else:
                if seen[0] != "proposed":
                    problems.append(f"action {action_id}'s history does not begin with it being proposed")
                replayed = None
                for event in seen:
                    replayed = EVENT_STATUS.get(event) or replayed
                if replayed != status:
                    problems.append(f"action {action_id} is {status} but its events say {replayed}")
            try:
                parsed = json.loads(args)
            except ValueError:
                problems.append(f"action {action_id}: its arguments are not JSON")
            else:
                if canonical(parsed) != args:
                    problems.append(f"action {action_id}: its arguments are not in canonical form")
                if digest != args_hash(kind, parsed):
                    problems.append(f"action {action_id}: its arguments do not match their hash")
            if bool(tainted) != bool(json.loads(sources)):
                problems.append(f"action {action_id}: its taint flag disagrees with its taint sources")
        return problems

    # ---- internals ----
    def _require_connected(self, kind):
        if kind.connector is not None and not diya_connectors.is_connected(self.config, kind.connector):
            raise NotConnected(f"{kind.label} needs {kind.connector} connected, and it is not")

    def _cannot_run(self, kind, row, args):
        """Why a stored, approved action cannot be started now, or None if it can (D10: checked again at run
        time, not trusted from when it was proposed)."""
        if kind is None:
            return f"there is no kind of action called {row['kind']!r} any more"
        if row["args_hash"] != args_hash(kind.name, args):
            return "the stored arguments do not match what was approved"
        try:
            clean_args(args)
            kind.validate(args)
        except ActionError as exc:
            return f"the arguments no longer pass their checks ({exc})"
        if kind.render(args) != row["summary"]:
            return "what the stored arguments say is not what the owner was shown"
        if kind.connector is not None and not diya_connectors.is_connected(self.config, kind.connector):
            return f"{kind.connector} is no longer connected"
        return None

    @staticmethod
    def _locked(conn, action_id):
        """Inside a write transaction: the action's row, or UnknownAction."""
        row = conn.execute("SELECT status, kind, args, args_hash, summary FROM actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise UnknownAction(f"there is no action {action_id}")
        return dict(zip(("status", "kind", "args", "args_hash", "summary"), row))

    @staticmethod
    def _event(conn, action_id, event, at, detail=None):
        conn.execute(
            "INSERT INTO action_events (action_id, event, actor, at, detail) VALUES (?, ?, ?, ?, ?)",
            (action_id, event, EVENT_ACTOR[event], at, detail),
        )
