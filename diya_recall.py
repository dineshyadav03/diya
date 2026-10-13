"""Relevance recall: when Diya knows more about you than fits in one message, tell the model the facts that matter for THIS message (docs/RECALL_DESIGN.md, unit R1).

Until now the model was told every accepted fact, in one list of at most 2,000 characters (about 35 short facts), and a memory that reached the limit refused any new fact. That is the right design while
the memory is small (ConvoMem, RESEARCH.md entry 28: a small history in the prompt beats a retrieval system), and it stops being possible once automatic memory has been running for a few weeks.

What is changed is only what is TOLD, never what is KEPT or what is accepted:

* Under the limit nothing is different: every accepted fact, in the same order, as before.
* Over it, the model is told (1) the plain, lasting facts about the person that should always be there (a name, a place, an allergy, a job: `is_core`), up to 45% of the room, and (2) the rest ranked
  by how close their meaning is to the message just sent and the one before it (embeddings from the model Diya already uses for notes), filled in until the room is used. Nothing is dropped from the
  memory; the Memory page still lists every fact.
* If the embeddings cannot be had (Ollama down, the embedding model missing), the facts told are the core ones and then the newest, so a chat never fails because recall did.

Embeddings are kept in the `fact_embeddings` table, one row per fact and per embedding model, made the first time recall is needed and again only for a fact whose words have changed.
No model writes anything here: ranking is arithmetic over vectors and the facts' own text.
"""
from __future__ import annotations

import json
import math
import re

CORE_SHARE = 0.45  # of the room, at most, for the facts that are always told
QUERY_CHARS = 400  # of the last two messages the person sent, what the facts are matched against
# A lasting fact about who the person is: told whatever they ask. Deliberately short and in code, like the other checks: a miss only means the fact has to be relevant to be told.
_CORE = re.compile(
    r"\b(?:name\s+is|called|nickname|allerg\w*|intoleran\w*|diabet\w*|asthma\w*|medicat\w*|vegetarian|vegan|pronouns?|lives?\s+in|living\s+in|from|born|birthday|works?\s+(?:as|at|for)|"
    r"studies|student|married|wife|husband|partner|mother|father|sister|brother|son|daughter|timezone|time\s+zone|language)\b",
    re.IGNORECASE,
)
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
