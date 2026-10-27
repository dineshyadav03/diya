"""Relevance recall: when Diya knows more about you than fits in one message, tell the model the facts that matter for THIS message (docs/RECALL_DESIGN.md, unit R1).

Until now the model was told every accepted fact, in one list of at most 2,000 characters (about 35 short facts), and a memory that reached the limit refused any new fact. That is the right design while
the memory is small (ConvoMem, RESEARCH.md entry 28: a small history in the prompt beats a retrieval system), and it stops being possible once automatic memory has been running for a few weeks.

What is changed is only what is TOLD, never what is KEPT or what is accepted:

* Under the limit nothing is different: every accepted fact, in the same order, as before.
* Over it, the model is told (1) the plain, lasting facts about the person that should always be there (a name, a place, an allergy, a job: `is_core`), up to 45% of the room, and (2) the rest ranked
  by how close their meaning is to the message just sent and the one before it (embeddings from the model Diya already uses for notes), filled in until the room is used. Nothing is dropped from the
  memory; the Memory page still lists every fact.
* If the embeddings cannot be had (Ollama down, the embedding model missing), the facts told are the core ones and then the newest, so a chat never fails because recall did.

Tight mode (`pick`, 2026-10-27): a store that fits is no longer a reason to tell everything. Told every fact on every message, the 4B model kept bringing up a dog and a favourite colour in answers that were
not about them. With recall on, a message is now told only (1) the few always-on facts (a name, an allergy or condition, pronouns, a time zone: `is_always`, at most 25% of the room) and (2) the facts whose
meaning is close to THIS message (cosine at least THRESHOLD, at most TOP of them). Measured on 13 real facts and 12 messages with nomic-embed-text: facts that were for the message scored 0.52 to 0.68, facts that
were not scored up to 0.49. A question about the memory itself ("what do you know about me") is still told everything. The note that the view is partial stays, so a fact out of view is "maybe not in view",
never "never told".

Embeddings are kept in the `fact_embeddings` table, one row per fact and per embedding model, made the first time recall is needed and again only for a fact whose words have changed.
No model writes anything here: ranking is arithmetic over vectors and the facts' own text.
"""
from __future__ import annotations

import json
import math
import re

CORE_SHARE = 0.45  # of the room, at most, for the facts that are always told
ALWAYS_SHARE = 0.25  # of the room, at most, for the always-on facts in tight mode
THRESHOLD = 0.52  # cosine of a fact with the message just sent, from which the fact counts as being for it (measured 2026-10-27: for it 0.52 to 0.68, not for it up to 0.49)
TOP = 6  # facts at most that tight mode tells for one message, besides the always-on ones
QUERY_CHARS = 400  # of the last two messages the person sent, what the facts are matched against
# A lasting fact about who the person is: told whatever they ask. Deliberately short and in code, like the other checks: a miss only means the fact has to be relevant to be told.
_CORE = re.compile(
    r"\b(?:name\s+is|called|nickname|allerg\w*|intoleran\w*|diabet\w*|asthma\w*|medicat\w*|vegetarian|vegan|pronouns?|lives?\s+in|living\s+in|from|born|birthday|works?\s+(?:as|at|for)|"
    r"studies|student|married|wife|husband|partner|mother|father|sister|brother|son|daughter|timezone|time\s+zone|language)\b",
    re.IGNORECASE,
)
# Tight mode's always-on facts: only what must never be missed whatever is asked (a name, an allergy or condition, pronouns, a time zone). Much narrower than _CORE, which also took "from" and "student".
_ALWAYS = re.compile(r"\b(?:name\s+is|called|nickname|allerg\w*|intoleran\w*|diabet\w*|asthma\w*|medicat\w*|vegetarian|vegan|pronouns?|time\s*zone)\b", re.IGNORECASE)
# A short follow-up that points back ("what should I feed him?"): the facts for the message before it are told too.
_ANAPHORA = re.compile(r"\b(?:he|him|his|she|her|hers|it|its|they|them|their|that|this|these|those|there)\b", re.IGNORECASE)
# A question about the memory itself wants all of it.
_ASKS_ALL = re.compile(r"\bwhat\s+(?:do|did|can)\s+you\s+(?:know|remember)(?:\s+about\s+me)?\s*[?.!]*\s*$|\b(?:know|knew|remember|remembered)\b[^.?!]{0,30}\babout\s+me\b|\beverything\s+you\s+(?:know|remember)\b", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]{3,}")
_COMMON = frozenset("the and for with that this have has from your what when where which who how are was were you not but can will about there their they them she her his him its out any all".split())


def is_core(text):
    """Is this a lasting fact about who the person is, that belongs in every message?"""
    return _CORE.search(text) is not None


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


def _words(text):
    return {w for w in (m.group(0).casefold() for m in _WORD.finditer(text)) if w not in _COMMON}


def query_of(messages):
    """What the facts are matched against: the person's last two messages, joined and cut."""
    users = [m["content"] for m in messages if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)]
    return " ".join(users[-2:])[-QUERY_CHARS:].strip()


def vectors(store, facts, embed, model):
    """The embedding of each fact, `{fact_id: vector}`: from the table when it is there for these words, made (and kept) when not. `embed(text)` raises if it cannot."""
    conn = store.connect()
    try:
        # A vector is derived from a fact's words, so it goes when the fact stops being one the model is told (retired, rejected, forgotten): a forgotten thing must not linger as a vector (DIYA-024).
        conn.execute("DELETE FROM fact_embeddings WHERE fact_id IN (SELECT id FROM facts WHERE status != 'accepted')")
        conn.commit()
        kept = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT fact_id, text_key, vector FROM fact_embeddings WHERE model = ?", (model,)).fetchall()}
        out = {}
        for fact in facts:
            have = kept.get(fact["id"])
            if have is not None and have[0] == fact["text_key"]:
                out[fact["id"]] = json.loads(have[1])
                continue
            vector = [float(x) for x in embed(fact["text"])]
            conn.execute("INSERT OR REPLACE INTO fact_embeddings (fact_id, text_key, model, vector) VALUES (?, ?, ?, ?)", (fact["id"], fact["text_key"], model, json.dumps(vector)))
            conn.commit()
            out[fact["id"]] = vector
        return out
    finally:
        conn.close()


def choose(facts, query, limit, render, store=None, embed=None, model=""):
    """Which of `facts` to tell the model, in their own order. `facts` are dicts with id, text, text_key, person; `render(chosen)` is the text that would be sent (its length is what `limit` is
    measured on). Returns every fact when they all fit."""
    if len(render(facts)) <= limit:
        return facts
    chosen, core_room = [], limit * CORE_SHARE
    for fact in facts:
        if is_core(fact["text"]) and len(render(chosen + [fact])) <= core_room:
            chosen.append(fact)
    left = [f for f in facts if f not in chosen]
    ranked = None
    if embed is not None and store is not None and query:
        try:
            wanted = embed(query)
            have = vectors(store, left, embed, model)
            asked = _words(query)
            ranked = sorted(left, key=lambda f: (-(cosine(wanted, have[f["id"]]) + (0.05 if asked & _words(f["text"]) else 0.0)), -f["id"]))
        except Exception:  # noqa: BLE001 -- Ollama down or the model missing: recall must never fail a chat
            ranked = None
    if ranked is None:
        ranked = sorted(left, key=lambda f: -f["id"])  # the newest first
    for fact in ranked:
        if len(render(chosen + [fact])) <= limit:
            chosen.append(fact)
    return sorted(chosen, key=lambda f: f["id"])


def is_always(text):
    """Is this a fact that belongs in every message (a name, an allergy or condition, pronouns, a time zone)?"""
    return _ALWAYS.search(text) is not None


def last_of(messages):
    """The message the person just sent, cut: what tight mode matches the facts against."""
    users = [m["content"] for m in messages if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)]
    return users[-1][-QUERY_CHARS:].strip() if users else ""


def previous_of(messages):
    """The message the person sent before the one just sent, cut: for a follow-up that points back at it."""
    users = [m["content"] for m in messages if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)]
    return users[-2][-QUERY_CHARS:].strip() if len(users) > 1 else ""


def pick(facts, focus, limit, render, store=None, embed=None, model="", before=""):
    """Tight mode: the always-on facts, then the facts whose meaning is close to `focus` (the message just sent), at most TOP of them, in their own order. A question about the memory itself gets `choose`
    (everything that fits). A follow-up that points back ("what should I feed him?": `_ANAPHORA`) is also matched against `before`, the message before it, so the fact it points at is still told. Without embeddings (Ollama down, or too slow) only a fact sharing a meaningful word (as a stem) with the message is added, so a chat never fails because recall did."""
    if _ASKS_ALL.search(focus):
        return choose(facts, focus, limit, render, store=store, embed=embed, model=model)
    chosen, always_room = [], limit * ALWAYS_SHARE
    for fact in facts:
        if is_always(fact["text"]) and len(render(chosen + [fact])) <= always_room:
            chosen.append(fact)
    left = [f for f in facts if f not in chosen]
    wanted = have = wanted_before = None
    follow_up = bool(before) and _ANAPHORA.search(focus) is not None
    if embed is not None and store is not None and focus and left:
        try:
            wanted = embed(focus)
            have = vectors(store, left, embed, model)
            wanted_before = embed(before) if follow_up else None
        except Exception:  # noqa: BLE001 -- Ollama down or the model missing
            wanted = have = wanted_before = None
    if wanted is None:
        import diya_checks  # (here, not at the top: diya_checks and diya_memory import each other's neighbours)

        asked = diya_checks.content_words(focus + (" " + before if follow_up else "")) - {"user"}  # stems, so "name" finds "named" and "dog's" finds "dog"
    scored = []
    for fact in left:
        if wanted is not None:
            score = cosine(wanted, have[fact["id"]])
            if wanted_before is not None:
                score = max(score, cosine(wanted_before, have[fact["id"]]))
            if score >= THRESHOLD:
                scored.append((score, fact))
        elif asked & diya_checks.content_words(fact["text"]):
            scored.append((1.0, fact))
    scored.sort(key=lambda row: (-row[0], -row[1]["id"]))
    for _score, fact in scored[:TOP]:
        if len(render(chosen + [fact])) <= limit:
            chosen.append(fact)
    return sorted(chosen, key=lambda f: f["id"])
