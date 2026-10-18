""""How do you know that?": Diya says where a remembered fact came from, in words made by code from the record, never by the model (docs/PROVENANCE_DESIGN.md), added 2026-10-18.

A question like "how do you know I have a dog?", "where did you get that?", "who told you my exam is on Friday?" or "when did I tell you about Rocky?" is answered here. The answer is built from
what the memory actually holds for the fact: the person's own message it came from (quoted, with its date), how it got in (typed by the person, imported from the old profile file, or read from a
message and then taken on by Diya under the memory policy, or accepted by the person), and when. A model asked the same question would invent a plausible history; this cannot, because it only
reads the record, and it says plainly when there is no record.

What it does not do: it knows only what the memory records. An answer that came from the model's general knowledge, from the web or from a tool has no fact behind it, and this says so rather than guessing
(the Activity page shows what tools ran). It never changes anything.

Importing this module has no side effects.
"""
from __future__ import annotations

import re
from datetime import datetime

import diya_time
from diya_memory import FLAG_SOURCE_PREFIX, printable

MAX_FACTS = 3
QUOTE_CHARS = 160
MAX_QUESTION_CHARS = 200

_LEAD = r"^\W*(?:(?:hey|hi|ok|okay|so|and|but|wait|hold\s+on|diya|just|please)\b[\s,]*)*"
_ASKS = (
    re.compile(_LEAD + r"(?:why|how)\s+(?:do|did|would|can|could|come)\s+you\s+(?:even\s+)?(?:know|remember)\b(?P<rest>.*)$", re.IGNORECASE),
    re.compile(_LEAD + r"where\s+(?:did|do)\s+you\s+(?:get|got|learn|learned|learnt|hear|heard|read|find|found|pick)\b(?P<rest>.*)$", re.IGNORECASE),
    re.compile(_LEAD + r"who\s+told\s+you\b(?P<rest>.*)$", re.IGNORECASE),
    re.compile(_LEAD + r"when\s+did\s+(?:i|we)\s+(?:tell|say|mention|talk)\b(?P<rest>.*)$", re.IGNORECASE),
    re.compile(_LEAD + r"what(?:'s|\s+is|\s+was)\s+your\s+(?:source|basis)\b(?P<rest>.*)$", re.IGNORECASE),
)
_FIRST_PERSON = re.compile(r"\b(?:i|i'm|i've|i'd|me|my|mine|myself|we|our)\b", re.IGNORECASE)
_THAT = re.compile(r"^\W*(?:that|this|it|so|all\s+that|any\s+of\s+(?:that|this)|about\s+(?:that|this|it)|(?:that|this)\s+(?:about\s+me|one)|from)?\W*$", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_COMMON = frozenset(
    "the and for you your yours are was were that this these those with have has had not but from into about they them their there then than what when where which who whom how why did does doing done "
    "can could would should will its it's i'm i've i'd mine our ours his her hers him she he we us me my any all one get got tell told say said know knew known remember remembered learn learned heard".split()
)


def _stem(word):
    """A word with its plural or tense ending taken off, so "lives" and "live", "dogs" and "dog" are the same word. Crude on purpose: it only has to line a question up with a fact."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _words(text):
    found = set()
    for match in _WORD.finditer(text.casefold().replace("’", "'")):
        word = match.group(0)
        word = word[:-2] if word.endswith("'s") else word
        if len(word) >= 3 and word not in _COMMON:
            found.add(_stem(word))
    return found


def asks_where_from(text):
    """(rest of the question) if `text` asks how or where Diya knows something, told by someone, or when it was said; else None. The rest may be empty: "how do you know that?" """
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_QUESTION_CHARS or "\n" in text.strip():
        return None
    for pattern in _ASKS:
        found = pattern.match(text.replace("’", "'").strip())
        if found:
            return found.group("rest").strip(" ?!.\"'")
    return None


def _when(at):
    """A stored moment as the person's local wall-clock time, in words; the raw text if it is not a time."""
    try:
        moment = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        return diya_time.describe_local(moment.astimezone().replace(tzinfo=None))
    except (ValueError, TypeError):
        return printable(at, 20)


def _matching(facts, wanted):
    scored = []
    for fact in facts:
        overlap = len(wanted & _words(fact["text"]))
        if overlap:
            scored.append((overlap, fact["id"], fact))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [fact for _score, _id, fact in scored[:MAX_FACTS]]


def _source_messages(store, fact):
    """The person's messages this fact was read from: the one the checks matched best, or (a small range) every message it was read from. [] when none is recorded."""
    ids = [int(flag[len(FLAG_SOURCE_PREFIX):]) for flag in fact["flags"] if flag.startswith(FLAG_SOURCE_PREFIX) and flag[len(FLAG_SOURCE_PREFIX):].isdigit()]
    if not ids and fact["batch_first"] is not None and fact["batch_last"] is not None and fact["batch_last"] - fact["batch_first"] <= 4:
        ids = list(range(fact["batch_first"], fact["batch_last"] + 1))
    if not ids:
        return []
    found = []
    for message in store.get_messages_between(min(ids), max(ids)):
        if message["id"] in ids and message["role"] == "user":
            found.append(message)
    return found


def _how_it_got_in(memory, fact):
    """(how, when) from the fact's history: the event that made it accepted, and who did that."""
    accepted = None
    for event, actor, at, _detail in memory.events(fact["id"]):
        if event in ("accepted", "restored") and accepted is None:
            accepted = (event, actor, at)
    return accepted


def describe(memory, store, fact):
    """One fact's history as a few plain sentences."""
    lines = [f"“{printable(fact['text'], 200)}”"]
    source, status = fact["source"], fact["status"]
    messages = _source_messages(store, fact)
    accepted = _how_it_got_in(memory, fact)
    if source == "manual":
        lines.append(f"You added this yourself ({_when(fact['created_at'])}).")
    elif source == "legacy_profile":
        lines.append("It came from your old profile file, which was imported when memory moved into the database.")
    elif source == "markdown_export":
        lines.append(f"It was restored from a Markdown copy of my memory that you exported earlier ({_when(fact['created_at'])} is when it was first taken in). Which message it was read from is not kept.")
    elif messages:
        times = store.message_times([m["id"] for m in messages])
        for message in messages:
            lines.append(f"You told me: “{printable(message['content'], QUOTE_CHARS)}” ({_when(times.get(message['id']))}).")
    else:
        lines.append("It was read from your messages, but which message is not recorded.")
    if accepted is not None and source not in ("manual", "markdown_export"):
        event, actor, at = accepted
        if actor == "auto":
            lines.append(f"I remembered it on my own under the memory rules ({_when(at)}); nothing asked you first, and you can undo it.")
        elif actor in ("cli", "api", "import"):
            lines.append(f"You accepted it ({_when(at)}).")
        else:
            lines.append(f"It was accepted by the system ({_when(at)}).")
    if status == "accepted":
        said = memory.mentions(fact["id"])
        if said:
            lines.append(f"You said it again {'once' if len(said) == 1 else f'{len(said)} times'}, most recently {_when(said[-1][1])}.")
        faded = memory.fading().get(fact["id"])
        if faded is not None:
            lines.append(f"It sounds like a passing state, so it fades on {faded.astimezone().strftime('%d %b %Y')} unless you say it again or keep it.")
    if status == "retired":
        lines.append("I no longer use it: it was retired, and the Memory page can restore it.")
    elif status == "candidate":
        lines.append("I have not accepted it: it is waiting for you, and I do not use it as true.")
    elif status == "rejected":
        lines.append("You said no to it, so I do not use it.")
    lines.append(f"It is number {fact['id']} on the Memory page, where you can change it or tell me to forget it.")
    return " ".join(lines)


NOTHING_FOR_THAT = ("I can't find anything I have remembered about you that matches that. If I said something, it may have come from what I already know in general, from the web or from a tool "
                    "(the Activity page shows which tools I used), and I don't keep a record of that kind of source as a memory.")
NOTHING_FOR_LAST = ("I can't tie my last answer to anything I have remembered about you. It may have come from what I know in general, from the web or from a tool I used (the Activity page shows those).")


def explain(memory, store, question, previous_answer=None):
    """The answer to a "how do you know" question, or None when the question is not about the person's memory (it is then left to the model). Built only from the record."""
    rest = asks_where_from(question)
    if rest is None:
        return None
    pool = memory.facts("accepted") + memory.facts("retired") + memory.facts("candidate")
    accepted_first = sorted(pool, key=lambda f: (f["status"] != "accepted", -f["id"]))
    if _THAT.match(rest):
        if not previous_answer:
            return None
        wanted = _words(previous_answer)
        chosen = [f for f in _matching(accepted_first, wanted) if f["status"] == "accepted"]
        return "\n\n".join(describe(memory, store, f) for f in chosen) if chosen else NOTHING_FOR_LAST
    wanted = _words(rest)
    chosen = _matching(accepted_first, wanted) if wanted else []
    if chosen:
        live = [f for f in chosen if f["status"] == "accepted"]
        return "\n\n".join(describe(memory, store, f) for f in (live or chosen))
    return NOTHING_FOR_THAT if _FIRST_PERSON.search(rest) else None
