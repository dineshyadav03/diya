"""Automations: say it once, Diya does it on a schedule and writes you the answer (docs/AUTOMATIONS_DESIGN.md).

    "every morning at 8am tell me the weather in Pune"      ->  every day at 08:00 she looks up the weather and writes you a message in the chat
    "every Friday at 5pm search the web for news about Ollama and sum it up"

This is the thing the open-source personal agents (OpenClaw, Hermes, Khoj) are used for most (docs: RESEARCH.md entries 16 and 18): a request that runs on a clock, with live tools, and arrives
as a message. It is Diya's own version of it, built from what she already has: the repeat reader (diya_repeat), the agent and its tools, and the proactive messages (diya_proactive).

How it stays safe: an automation is read-only. It runs with only the tools that read (notes, the web, the weather, your reminders and tasks, the files you allow), whatever the model asks for;
what it finds goes to one place, your own chat; it cannot save a reminder, a task or an action, or send anything anywhere. It reads the web, which is untrusted text, and it can read private
things, so the one thing it must never be able to do is the third: act or send (RESEARCH.md entry 17, the Rule of Two). Setting one up is done by code reading your own words, not by the model.

What is here: parse_request (a chat message that is an automation), Automations (the table: add, list, pause, resume, delete, which are due, record a run), run (one automation, now) and run_due (the
scheduled pass, called by the notifier).
"""
from __future__ import annotations

import re
from datetime import datetime

import diya_intent
import diya_repeat
import diya_time
from diya_memory import printable

READ_ONLY_TOOLS = ("search_notes", "web_search", "get_weather", "list_reminders", "list_tasks", "list_files")
MAX_AUTOMATIONS = 10
MAX_INSTRUCTION_CHARS = 300
MAX_REQUEST_CHARS = 400
RUNS_PER_PASS = 1  # the notifier has five minutes; a model with tools can take one of them
STATES = ("active", "paused")

# What a message must say, besides when, to be an automation and not a chat: that the person wants something told or looked up. Deliberately narrow, like the other intent checks: missing
# one only means the model answers the message as it always did.
_ASKS_FOR_SOMETHING = re.compile(
    r"\b(?:tell|give|send|show|brief|update|message|text|ping|let)\s+me\b|\b(?:check|search|summari[sz]e|look\s+up|find|list|read|remind\s+me\s+what)\b|\bsum\s+(?:it\s+)?up\b",
    re.IGNORECASE,
)
_QUESTION_START = re.compile(r"^\s*(?:what|what's|whats|how|why|where|when|who|which|is|are|does|do|did|can|could|should|would)\b", re.IGNORECASE)
_BARE_HOUR = re.compile(r"\s*(?:at\s+)?\d")  # "every morning at 8 tell me": an hour with no am or pm


class AutomationError(Exception):
    """An automation that cannot be made or changed as asked. The text can be shown to the person."""


class Request:
    """A chat message that is an automation: what to do (`instruction`), the person's words for when (`words`) and the rule they read as."""

    def __init__(self, instruction, words, rule):
        self.instruction, self.words, self.rule = instruction, words, rule


def parse_request(text, now=None):
    """A Request if `text` asks for something to be done on a schedule, a string (what to fix) if it nearly does, or None if it is an ordinary message.
    Never a reminder (that is the reminders' own path), a task, a question, or a message with more than one repeat."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_REQUEST_CHARS or "\n" in text.strip():
        return None
    found = diya_repeat.find_repeat(text, now)
    if found is None or diya_intent.is_reminder_request(text) or diya_intent.is_task_request(text) or _QUESTION_START.match(text):
        return None
    rest = (text[:found.start] + " " + text[found.end:]).strip()
    if not _ASKS_FOR_SOMETHING.search(rest):
        return None
    if _BARE_HOUR.match(text[found.end:]):  # "every morning at 8 tell me ..." reads as 09:00 without it: do not guess an hour
        return "I need am or pm with that hour (or 24-hour time like 08:00): morning or evening?"
    instruction = re.sub(r"\s+", " ", rest).strip(" ,.;:-")
    if len(instruction) < 4:
        return None
    return Request(instruction[:MAX_INSTRUCTION_CHARS], found.words, found.rule)


def _iso(local):
    return diya_time.iso_of_local(local)


class Automations:
    """The `automations` table. `clock` returns the current local time (naive)."""

    FIELDS = ("id", "instruction", "words", "rule", "state", "next_ts", "last_run_at", "last_status", "runs", "created_at")

    def __init__(self, store, clock=None):
        self.store = store
        self._clock = clock or datetime.now

    def _rows(self, where="", args=()):
        conn = self.store.connect()
        try:
            rows = conn.execute(f"SELECT {', '.join(self.FIELDS)} FROM automations {where}", args).fetchall()
        finally:
            conn.close()
        return [dict(zip(self.FIELDS, row)) for row in rows]

    def list(self):
        return self._rows("ORDER BY id")

    def get(self, automation_id):
        rows = self._rows("WHERE id = ?", (automation_id,))
        if not rows:
            raise AutomationError(f"there is no automation {printable(automation_id)}")
        return rows[0]

    def create(self, instruction, words):
        """Make one that runs by the rule `words` reads as. AutomationError (with words to show) if the rule cannot be read, it is empty, or there are too many already."""
        instruction = re.sub(r"\s+", " ", instruction or "").strip()
        if not instruction:
            raise AutomationError("say what Diya should do")
        if len(instruction) > MAX_INSTRUCTION_CHARS:
            raise AutomationError(f"that is longer than {MAX_INSTRUCTION_CHARS} characters; shorten it")
        now = self._clock()
        try:
            rule = diya_repeat.parse_repeat(words, now)
        except diya_repeat.NotUnderstood as exc:
            raise AutomationError(str(exc)) from None
        if len(self._rows()) >= MAX_AUTOMATIONS:
            raise AutomationError(f"there are already {MAX_AUTOMATIONS} automations: delete one first")
        conn = self.store.connect()
        try:
            cursor = conn.execute("INSERT INTO automations (instruction, words, rule, state, next_ts, runs, created_at) VALUES (?, ?, ?, 'active', ?, 0, ?)",
                                  (instruction, words, rule.canonical(), _iso(rule.next_after(now)), _iso(now)))
            conn.commit()
            return self.get(cursor.lastrowid)
        finally:
            conn.close()

    def _set(self, automation_id, **changes):
        conn = self.store.connect()
        try:
            conn.execute(f"UPDATE automations SET {', '.join(f'{name} = ?' for name in changes)} WHERE id = ?", (*changes.values(), automation_id))
            conn.commit()
        finally:
            conn.close()

    def pause(self, automation_id):
        self.get(automation_id)
        self._set(automation_id, state="paused")

    def resume(self, automation_id):
        """Active again, and the next run is the next time the rule falls from now (not a backlog of the ones missed while it was paused)."""
        row = self.get(automation_id)
        now = self._clock()
        self._set(automation_id, state="active", next_ts=_iso(diya_repeat.Repeat.from_canonical(row["rule"]).next_after(now)))

    def delete(self, automation_id):
        self.get(automation_id)
        conn = self.store.connect()
        try:
            conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
            conn.commit()
        finally:
            conn.close()

    def due(self, now_local):
        """The active automations whose time has come, oldest due first."""
        return self._rows("WHERE state = 'active' AND next_ts <= ? ORDER BY next_ts, id", (_iso(now_local),))

    def claim(self, automation_id, now_local):
        """Move the next run on to the next time the rule falls BEFORE running this one, so a run that is cut off (the notifier has five minutes) is lost and not repeated for ever. At most once
        for each time the rule falls."""
        row = self.get(automation_id)
        self._set(automation_id, next_ts=_iso(diya_repeat.Repeat.from_canonical(row["rule"]).next_after(now_local)), last_status="running")

    def finish(self, automation_id, now_local, status):
        row = self.get(automation_id)
        self._set(automation_id, last_run_at=_iso(now_local), last_status=status, runs=row["runs"] + 1)


def confirmation(row, assumed=()):
    """What Diya says back when one is made in the chat. `assumed` is what the person did not say and was filled in (diya_repeat's own words for it), so it is never silent."""
    rule = diya_repeat.Repeat.from_canonical(row["rule"])
    first = diya_time.describe_local(diya_time.local_from_iso(row["next_ts"]))
    filled = f" ({'; '.join(assumed)[:1].upper()}{'; '.join(assumed)[1:]}.)" if assumed else ""
    return (f"Okay. {rule.describe()} I will: {row['instruction']}. The first one is {first}.{filled} It can look at the weather, the web, your notes, your reminders and tasks, and only read; "
            "what it finds comes to you here. Pause or delete it on the Automations page.")


def from_chat(store, text, clock):
    """If `text` is an automation, make it and return what to say back; a string to say if it nearly is; None if it is an ordinary message."""
    now = clock()
    request = parse_request(text, now)
    if request is None:
        return None
    if isinstance(request, str):
        return request
    try:
        return confirmation(Automations(store, clock).create(request.instruction, request.words), request.rule.assumed)
    except AutomationError as exc:
        return f"I could not set that up: {exc}."


def _title(row):
    """The first line of what Diya writes (it is also what the desktop notification says): which automation this is from."""
    return f"Automation: {row['instruction'][:80]}"


def run(automation, agent, proactive, now_local):
    """Run one automation now: the agent answers its instruction with the read-only tools, and the answer is written in the chat as a message (and so put on the desktop). Returns the
    message row, or None if the agent had nothing to say. Never raises for a model that fails: it says so in the chat, so a silent failure is not mistaken for 'nothing to report'."""
    try:
        answer = agent.briefing(automation["instruction"]).strip()
    except Exception as exc:  # noqa: BLE001 -- a scheduled run must say what it could not do, not vanish
        answer = f"I could not do this one just now ({type(exc).__name__}). I will try again at the next time."
    if not answer:
        return None
    key = f"automation:{automation['id']}:{now_local:%Y-%m-%dT%H:%M:%S}"
    return proactive.post("automation", key, f"{_title(automation)}\n{answer}", now_local)


def run_by_hand(automation, automations, agent, proactive, now_local):
    """The Run now button: the same run, now, and its answer written in the chat; when the next one is due is left as it was. Returns the message row, or None."""
    row = run(automation, agent, proactive, now_local)
    automations.finish(automation["id"], now_local, "done (by hand)" if row else "nothing to say")
    return row


def run_due(store, agent_factory, proactive, now_local, say=print, clock=None):
    """The scheduled pass: run what is due, at most RUNS_PER_PASS of them, each claimed before it runs. `agent_factory()` makes the agent only if something is due (making one is the slow part).
    Returns how many were run."""
    automations = Automations(store, clock or (lambda: now_local))
    due = automations.due(now_local)[:RUNS_PER_PASS]
    if not due:
        return 0
    agent = agent_factory()
    ran = 0
    for automation in due:
        automations.claim(automation["id"], now_local)
        try:
            row = run(automation, agent, proactive, now_local)
            automations.finish(automation["id"], now_local, "done" if row else "nothing to say")
        except Exception as exc:  # noqa: BLE001
            say(f"could not run automation {automation['id']}: {printable(type(exc).__name__)}")
            automations.finish(automation["id"], now_local, "failed")
        ran += 1
    return ran
