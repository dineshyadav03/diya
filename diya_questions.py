"""Questions Diya raises herself (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5).

Memory that remembers on its own is only as good as what it does when it is not sure. The facts it will not decide alone wait for a person (the
Memory page lists them all); this module is the part that goes TO the person, at a pace that is a help and not a nag, in words made by code:

    doubt        a fact the checks or the model could not be sure of            "I am not sure about this: ... Is it right?"
    sensitive    a fact that looks private                                      "... looks private, so I did not keep it without asking."
    conflict     a fact that may replace one that is known                      "Does ... replace what I knew: ...?"
    stale        something remembered whose day has gone                        "You told me ... Is that still true?"
    offer        something remembered that is going to happen                   "... is on Friday at 15:00. Want a reminder at 14:00?"

Nothing here is written by a model. A question's words come from the fact's own text through `diya_memory.printable`; the time in a stale question or an
offer is read from the fact's words by `diya_time`, or there is no such question. A question is never asked about a secret (a discarded secret has no text), a
fact is never asked about twice in the same way, and the person's answer is the only thing that accepts, rejects or retires: an ignored question is dropped
and its fact stays unused, never accepted by silence.

The pace (D5): at most three open at once; at most two new in a day; none shown between 22:00 and 07:00 (settable); a question that is shown and not answered
for a day waits three days, and is dropped after the second time.

Times: `now` is always the machine's local wall-clock time as a naive datetime (the Agent's own clock), as in diya_brief; what is stored is UTC text.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import diya_intent
import diya_memory
import diya_time
from diya_time import is_quiet, parse_quiet  # noqa: F401 -- the quiet hours are diya_time's; re-exported here, where they are used

MAX_OPEN = 3
MAX_NEW_PER_DAY = 2
IGNORED_AFTER = timedelta(hours=24)
WAIT = timedelta(days=3)
DROP_AFTER_IGNORES = 2
REMIND_BEFORE = timedelta(hours=1)
KINDS = ("doubt", "conflict", "sensitive", "stale", "offer")
DEFAULT_QUIET = (22, 7)
_FROM_FLAG = ("doubt", "conflict", "sensitive")  # the kinds a waiting fact's `ask:` flag can name

# A fact is something that is going to happen (or did) only if it says so with a word like this; "plays badminton on Sunday" is a habit and is not asked about.
_COMMITMENT = re.compile(
    r"\b(?:appointment|meeting|flight|trip|travel(?:l?ing)?|exam|test|interview|deadline|call|dinner|lunch|breakfast|party|wedding|surgery|check-?up|booking|"
    r"reservation|conference|holiday|vacation|class|lesson|visit(?:ing)?|leaves?|leaving|arrives?|arriving|due|moving|concert|match|game|train|bus|delivery)\b",
    re.IGNORECASE,
)
# A word before a day that changes what day it is: "next Friday" is refused by diya_time as two possible days, and must not be read as "Friday" for that.
_MODIFIERS = frozenset({"next", "last", "following", "coming", "after", "before", "until", "till", "since", "every", "each", "past", "previous"})
_HABIT = re.compile(r"\b(?:usually|always|often|sometimes|typically|normally|generally|weekends?|weekdays?|mornings|afternoons|evenings|nights|every)\b", re.IGNORECASE)


def horizon(text, anchor):
    """When a fact says something is going to happen, as diya_time.When, or None: read from its own words, relative to `anchor` (the local time it was
    said). Only a fact that names an event (an appointment, a flight, an exam...) and is not a habit has one; a phrase diya_time will not guess at
    ("next week", "the 14th", a bare "at 5") is none."""
    if not _COMMITMENT.search(text) or diya_intent.mentions_repeat(text) or _HABIT.search(text):
        return None
    words = text.split()  # a comma or a semicolon after a word is diya_time's to deal with
    for start in range(len(words)):
        after_modifier = start > 0 and words[start - 1].casefold().strip(".:;!?") in _MODIFIERS
        for length in range(min(6, len(words) - start), 0, -1):
            try:
                when = diya_time.parse_when(" ".join(words[start:start + length]), anchor)
            except diya_time.NotUnderstood:
                continue
            return None if after_modifier else when  # a day that a word like "next" or "after" changes is not the day it reads as, and nothing later in the fact makes up for it
    return None


def _iso(local):
    return diya_time.iso_of_local(local)


def _local_of_created(created_at):
    """The local wall-clock time a fact was made, from the text the memory stores (UTC, with an offset)."""
    return datetime.fromisoformat(created_at).astimezone().replace(tzinfo=None)


class Questions:
    """The queue of questions, kept in the `memory_questions` table beside the facts they are about."""

    COLUMNS = "id, fact_id, kind, state, created_at, shown_at, ignores, wait_until, notified_at, answered_at, answer, detail"

    def __init__(self, store, quiet=DEFAULT_QUIET):
        self.store = store
        self.quiet = quiet

    # ---- reading ----
    def _rows(self, where="", args=()):
        conn = self.store.connect()
        try:
            rows = conn.execute(f"SELECT {self.COLUMNS} FROM memory_questions {where}", args).fetchall()  # `where` is text written in this module, never the person's
        finally:
            conn.close()
        keys = self.COLUMNS.replace(" ", "").split(",")
        out = []
        for row in rows:
            question = dict(zip(keys, row))
            question["detail"] = json.loads(question["detail"]) if question["detail"] else {}
            out.append(question)
        return out

    def get(self, question_id):
        found = self._rows("WHERE id = ?", (question_id,))
        if not found:
            raise diya_memory.UnknownFact(f"there is no question {question_id}")
        return found[0]

    def open(self):
        """Every open question, oldest first, whether or not it may be shown now."""
        return self._rows("WHERE state = 'open' ORDER BY id")

    def visible(self, now):
        """The questions that may be put in front of the person now: open, not waiting, and not inside the quiet hours."""
        if is_quiet(now, self.quiet):
            return []
        stamp = _iso(now)
        return [q for q in self.open() if q["wait_until"] is None or q["wait_until"] <= stamp]

    def unnotified(self, now):
        """The questions that may be shown now and that the desktop notifier has not yet told the person about."""
        return [question for question in self.visible(now) if question["notified_at"] is None]

    def mark_notified(self, ids, now):
        """Record that the person was told (once) that there is a question."""
        conn = self.store.connect()
        try:
            for question_id in ids:
                conn.execute("UPDATE memory_questions SET notified_at = ? WHERE id = ? AND notified_at IS NULL", (_iso(now), question_id))
            conn.commit()
        finally:
            conn.close()

    # ---- the pace ----
    def seen(self, ids, now):
        """Record that these questions were put in front of the person (the first time only): a question shown and left for a day counts as ignored."""
        conn = self.store.connect()
        try:
            for question_id in ids:
                conn.execute("UPDATE memory_questions SET shown_at = ? WHERE id = ? AND state = 'open' AND shown_at IS NULL", (_iso(now), question_id))
            conn.commit()
        finally:
            conn.close()

    def _age(self, now):
        """A question shown and not answered for a day waits three days; after the second time it is dropped, and its fact stays as it is."""
        limit = _iso(now - IGNORED_AFTER)
        conn = self.store.connect()
        try:
            for question in self._rows("WHERE state = 'open' AND shown_at IS NOT NULL AND shown_at <= ?", (limit,)):
                ignores = question["ignores"] + 1
                if ignores >= DROP_AFTER_IGNORES:
                    conn.execute("UPDATE memory_questions SET state = 'dropped', ignores = ?, answered_at = ?, answer = 'ignored' WHERE id = ?", (ignores, _iso(now), question["id"]))
                else:
                    conn.execute("UPDATE memory_questions SET ignores = ?, shown_at = NULL, wait_until = ? WHERE id = ?", (ignores, _iso(now + WAIT), question["id"]))
            conn.commit()
        finally:
            conn.close()

    def _close_settled(self, memory, now):
        """Close a question whose fact has been dealt with some other way (accepted on the Memory page, forgotten): there is nothing left to ask."""
        conn = self.store.connect()
        try:
            for question in self.open():
                try:
                    status = memory.get(question["fact_id"])["status"]
                except diya_memory.FactError:
                    status = None
                waiting_for = "accepted" if question["kind"] in ("stale", "offer") else "candidate"
                if status != waiting_for:
                    conn.execute("UPDATE memory_questions SET state = 'answered', answered_at = ?, answer = 'handled elsewhere' WHERE id = ?", (_iso(now), question["id"]))
            conn.commit()
        finally:
            conn.close()

    # ---- what to ask ----
    def _wanted(self, memory, now, known):
        """(kind, fact, detail) for every question worth asking that has not been asked, the doubtful and private first, then what has gone stale, then offers."""
        for fact in memory.facts("candidate"):
            for flag in fact["flags"]:
                if flag.startswith(diya_memory.ASK_PREFIX):
                    kind = flag[len(diya_memory.ASK_PREFIX):].partition(":")[0]
                    if kind in _FROM_FLAG and (fact["id"], kind) not in known:
                        replaces = diya_memory.replaced_fact_id(fact["flags"])  # only a conflict's flag names one
                        yield kind, fact, ({"replaces": replaces} if replaces is not None else {})
                    break
        accepted = memory.facts("accepted")
        for fact in accepted:
            if (fact["id"], "stale") in known:
                continue
            when = horizon(fact["text"], _local_of_created(fact["created_at"]))
            if when is not None and when.local <= now:
                yield "stale", fact, {"was": when.describe()}
        for fact in accepted:
            if (fact["id"], "offer") in known:
                continue
            when = horizon(fact["text"], _local_of_created(fact["created_at"]))
            if when is None:
                continue
            clock_given = not any("no time was given" in note for note in when.assumed)
            remind = when.local - REMIND_BEFORE if clock_given else when.local
            if remind <= now:
                remind = when.local
            if remind <= now:
                continue
            yield "offer", fact, {"event": when.describe(), "due": _iso(remind), "due_text": diya_time.describe_local(remind)}

    def refill(self, memory, now):
        """Put new questions in the queue, as many as the pace allows (three open, two new in a day), after closing what is settled and ageing what was
        ignored. Returns how many were made."""
        self._close_settled(memory, now)
        self._age(now)
        everything = self._rows("")
        open_now = sum(1 for q in everything if q["state"] == "open")
        since = _iso(now - timedelta(hours=24))
        made_today = sum(1 for q in everything if q["created_at"] >= since)
        room = min(MAX_OPEN - open_now, MAX_NEW_PER_DAY - made_today)
        if room <= 0:
            return 0
        known = {(q["fact_id"], q["kind"]) for q in everything}
        created = 0
        conn = self.store.connect()
        try:
            for kind, fact, detail in self._wanted(memory, now, known):
                conn.execute("INSERT INTO memory_questions (fact_id, kind, state, created_at, ignores, detail) VALUES (?, ?, 'open', ?, 0, ?)",
                             (fact["id"], kind, _iso(now), json.dumps(detail, sort_keys=True) if detail else None))
                created += 1
                if created >= room:
                    break
            conn.commit()
        finally:
            conn.close()
        return created

    # ---- the words ----
    def describe(self, memory, question):
        """One question as the page and the chat show it: {"id", "kind", "fact_id", "text", "options": [{"answer", "label"}]}. The words are built here from the
        fact's own text, made safe to show."""
        fact = memory.get(question["fact_id"])
        text = diya_memory.printable(fact["text"], 160)
        kind, detail = question["kind"], question["detail"]
        if kind == "doubt":
            words = f"I am not sure about this: “{text}”. Is it right?"
            options = [("yes", "Yes, remember it"), ("no", "No"), ("edit", "Edit it")]
        elif kind == "sensitive":
            words = f"“{text}” looks private, so I did not keep it without asking. May I remember it?"
            options = [("yes", "Yes, remember it"), ("no", "No, do not")]
        elif kind == "conflict":
            old = None
            if detail.get("replaces") is not None:
                try:
                    old = memory.get(detail["replaces"])
                except diya_memory.FactError:
                    old = None
            if old is not None and old["status"] == "accepted":
                words = f"Does “{text}” replace what I knew: “{diya_memory.printable(old['text'], 160)}”?"
                options = [("yes", "Yes, replace it"), ("keep", "Keep both"), ("no", "No")]
            else:
                words = f"“{text}” is close to something I already know. Should I remember it too?"
                options = [("keep", "Yes, remember it"), ("no", "No")]
        elif kind == "stale":
            words = f"You told me “{text}”. Is that still true?"
            options = [("yes", "Still true"), ("no", "No longer")]
        else:
            words = f"“{text}” is on {detail.get('event', 'a day I know')}. Want a reminder at {detail.get('due_text', 'the time')}?"
            options = [("yes", "Yes, remind me"), ("no", "No thanks")]
        return {"id": question["id"], "kind": kind, "fact_id": question["fact_id"], "text": words, "options": [{"answer": a, "label": l} for a, l in options]}

    # ---- the answer ----
    def answer(self, memory, question_id, answer, now, text=None, add_reminder=None):
        """Act on the person's answer, then close the question. Raises diya_memory.FactError (and changes nothing) when the fact is no longer as the question
        assumed, an answer the question does not offer, or an edit with nothing to say. `add_reminder(content, due_text, due_ts)` makes the reminder an
        accepted offer asks for. Returns the closed question."""
        question = self.get(question_id)
        if question["state"] != "open":
            raise diya_memory.IllegalTransition(f"question {question_id} is {question['state']}; only an open question can be answered")
        offered = {option["answer"] for option in self.describe(memory, question)["options"]}
        if answer not in offered:
            raise diya_memory.InvalidFact(f"this question can be answered {', '.join(sorted(offered))}, not {answer!r}")
        kind, fact_id, detail = question["kind"], question["fact_id"], question["detail"]
        if kind in ("doubt", "sensitive", "conflict"):
            if answer == "no":
                memory.decide(fact_id, "reject", "api")
            elif answer == "edit":
                cleaned = diya_memory.normalise_fact(text or "")
                if cleaned is None:
                    raise diya_memory.InvalidFact("there is nothing left of that text once it is cleaned up")
                memory.edit(fact_id, cleaned.text, "api")
                memory.decide(fact_id, "accept", "api")
            elif answer == "yes" and kind == "conflict":  # "yes" is only offered when the fact it replaces is still known
                memory.supersede(fact_id, detail["replaces"], "api")
            else:
                memory.decide(fact_id, "accept", "api")
        elif kind == "stale":
            if answer == "no":
                memory.decide(fact_id, "retire", "api")
        elif answer == "yes":
            if add_reminder is None:
                raise diya_memory.InvalidFact("no way to make a reminder was given")
            fact = memory.get(fact_id)
            if fact["status"] != "accepted":
                raise diya_memory.IllegalTransition(f"fact {fact_id} is {fact['status']}; a reminder is offered only for a fact that is remembered")
            add_reminder(fact["text"], detail.get("due_text"), detail["due"])
        conn = self.store.connect()
        try:
            conn.execute("UPDATE memory_questions SET state = 'answered', answered_at = ?, answer = ? WHERE id = ?", (_iso(now), answer, question_id))
            conn.commit()
        finally:
            conn.close()
        return self.get(question_id)
