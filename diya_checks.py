"""Deterministic checks on a candidate fact (docs/STAGE2_DESIGN.md, D5): pure functions, no database,
no model. They ANNOTATE; nothing here decides anything. A check that is wrong costs a reviewer a glance
at the source message shown beside the fact, so the methods are deliberately simple and their limits are
stated rather than hidden:

- grounding is lexical. It finds an invented fact, but it flags a good paraphrase ("owns a feline" for "I
  adopted a cat"), and it passes a fact with the right words and the wrong entity ("a cat named Rex" when
  the message said Pixel).
- similarity is shared words. It surfaces a likely repeat or update of an existing fact; it cannot tell a
  contradiction from an elaboration.
- "instruction shaped" is a handful of patterns. It catches the crude cases of a fact that addresses the
  assistant or issues an order; a plain statement phrased as a fact passes.

The thresholds below were set on the hand-written labelled cases in tests/labelled_facts.py and the tests
assert what they measure there. That is a small set written by the same author as the rules: it shows the
rules do what they say, not how they will do on real conversations.

Importing this module has no side effects.
"""
from __future__ import annotations

import re

# Flag names. Those that carry a fact or message id are written "name:<id>".
FLAG_NO_SOURCE = "no_source"  # none of the user messages this fact was extracted from are in the database
FLAG_UNGROUNDED = "ungrounded"  # too few of its content words appear in those messages
FLAG_SOURCE_MESSAGE = "source_message"  # :<id> -- the user message that best matches it (provenance, not a warning)
FLAG_INSTRUCTION = "instruction_shaped"
FLAG_DUPLICATE = "duplicate"  # :<id> -- the same fact, in other capitals, is already accepted (or came first)
FLAG_SIMILAR = "similar"  # :<id> -- shares most of its words with that fact
FLAG_PREVIOUSLY_REJECTED = "previously_rejected"  # :<id> -- the same words were rejected before

# The flags a person's own reading of a line produces (memory.normalise_fact); running the checks never
# removes or recomputes these.
CLEANING_FLAGS = frozenset({"preamble", "too_long"})

# A fact is grounded when at least this share of its content words appear in the user messages it came from.
GROUNDED_MIN = 0.6
# Two facts are similar when they share at least this many content words and at least this share of all
# the content words either has between them (Jaccard).
SIMILAR_MIN_SHARED = 2
SIMILAR_MIN_JACCARD = 0.4

_STOP = frozenset("""
a an the and or but if then so of to in on at by for with from into onto about as is are was were be been being
am do does did doing done have has had having will would shall should can could may might must not no nor
i me my mine myself we us our ours you your yours he him his she her hers it its they them their theirs
this that these those there here who whom what which when where why how also very just really quite too
than up out over under again once only own same some such any all each both more most other s t d ll m re ve
""".split())

_TOKEN = re.compile(r"[^\W_]+")


def _stem(word):
    """A crude stem, applied to both sides of every comparison, so what matters is that it is consistent
    (plural and tense endings do not make two mentions of a word differ), not that it is right."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    # A silent e goes too, so that name, names, named and naming (and like, likes, liked, liking) meet.
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


def content_words(text):
    """The words of `text` that carry its meaning: lower-cased, stop words and one-letter words removed
    (numbers are kept), lightly stemmed."""
    words = set()
    for token in _TOKEN.findall(text.casefold()):
        if token in _STOP or (len(token) < 2 and not token.isdigit()):
            continue
        words.add(_stem(token))
    return frozenset(words)


def grounding(fact_text, messages):
    """How well the user's own messages support a fact: (score, id of the best-matching message).

    `messages` is (id, text) for each user message the fact was extracted from. The score is the share of
    the fact's content words found among ALL of them together (the extractor saw them together, so a fact
    can draw on several); the best message is the single one that shares the most, the earliest on a tie,
    or None if none shares any. A fact with no content words has nothing to be grounded in: score 0."""
    words = content_words(fact_text)
    if not words:
        return 0.0, None
    found = set()
    best_id, best_shared = None, 0
    for message_id, text in messages:
        shared = words & content_words(text)
        found |= shared
        if len(shared) > best_shared:
            best_id, best_shared = message_id, len(shared)
    return len(found) / len(words), best_id


def similarity(a_text, b_text):
    """(words shared, Jaccard) of two facts' content words."""
    a, b = content_words(a_text), content_words(b_text)
    union = a | b
    shared = len(a & b)
    return shared, (shared / len(union) if union else 0.0)


def is_similar(a_text, b_text):
    shared, jaccard = similarity(a_text, b_text)
    return shared >= SIMILAR_MIN_SHARED and jaccard >= SIMILAR_MIN_JACCARD


# A fact is a statement about the user ("likes tea"). One that talks to the assistant, gives an order, wears
# a role label, carries a link or markup is not, and should not be taken on trust just because it reads well.
_ROLE_LABEL = re.compile(r"^\s*(?:system|assistant|user|developer|tool|human|ai)\s*:", re.IGNORECASE)
_ADDRESSES_ASSISTANT = re.compile(
    r"\b(?:you|your|yours|assistant|chatbot|system prompt|the ai|the model|(?:previous|prior|above|earlier) instructions?)\b",
    re.IGNORECASE)
# An order opens with a bare verb ("use", "write", "send"); a statement about the user opens with the
# third-person form ("uses", "writes", "sends"), which the \b after each word already tells apart. "always"
# and "never" open both ("Never mention the weather" / "never eats meat"), so they only count when the next
# word is not a third-person form (one ending in a single s).
_ORDER = re.compile(
    r"^\s*(?:(?:always|never)\s+(?![a-z]+(?<!s)s\b)|ignore|disregard|forget|override|remember to|make sure|do not|don't|"
    r"stop|from now on|whenever|respond|reply|answer|call me|address me|speak|write|use|say|tell|send|give|open|"
    r"run|delete)\b",
    re.IGNORECASE)
_LINK_OR_MARKUP = re.compile(r"https?://|www\.|```|<[a-z/!][^>]*>|<\||\|>|\{\{|\}\}|\[\[|\]\]", re.IGNORECASE)


def instruction_shaped(text):
    return bool(
        _ROLE_LABEL.search(text) or _ADDRESSES_ASSISTANT.search(text) or _ORDER.search(text) or _LINK_OR_MARKUP.search(text)
    )


def check_flags(fact, messages, others):
    """The advisory flags for one candidate, in a fixed order.

    `fact` is {id, text}. `messages` is (id, text) for each USER message in the range it was extracted from
    (an assistant's words are not what the extractor saw, so they never count as support). `others` is
    {id, text, status} for every other fact. Returns a list of strings; never a decision."""
    flags = []
    if not messages:
        flags.append(FLAG_NO_SOURCE)
    else:
        score, best = grounding(fact["text"], messages)
        if score < GROUNDED_MIN:
            flags.append(FLAG_UNGROUNDED)
        if best is not None:
            flags.append(f"{FLAG_SOURCE_MESSAGE}:{best}")
    if instruction_shaped(fact["text"]):
        flags.append(FLAG_INSTRUCTION)

    key = fact["text"].casefold()
    twin = next(
        (o for o in others if o["text"].casefold() == key and (o["status"] == "accepted" or (o["status"] == "candidate" and o["id"] < fact["id"]))),
        None,
    )
    if twin is not None:
        flags.append(f"{FLAG_DUPLICATE}:{twin['id']}")
    else:
        near = [
            (similarity(fact["text"], o["text"])[1], -o["id"], o)
            for o in others
            if (o["status"] == "accepted" or (o["status"] == "candidate" and o["id"] < fact["id"]))
            and is_similar(fact["text"], o["text"])
        ]
        if near:
            flags.append(f"{FLAG_SIMILAR}:{max(near, key=lambda item: item[:2])[2]['id']}")
    rejected = next((o for o in others if o["status"] == "rejected" and o["text"].casefold() == key), None)
    if rejected is not None:
        flags.append(f"{FLAG_PREVIOUSLY_REJECTED}:{rejected['id']}")
    return flags
