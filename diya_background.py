"""Keep what Diya remembers about the person's pets and instruments out of replies that are not about them (2026-10-27).

The owner asked "what am I doing next Tuesday?" and the reply ended "...and your dog Hog will be proud." The persona and the reminder after the list of facts already tell the model never to bring up a pet or a hobby
(diya.PERSONA, diya.PROFILE_REMINDER), and a small model still does it: it is a request, not a rule. This is the rule, in code, on the finished reply:

* A fact is "about a pet" or "about an instrument" when it says so (a word from PET_WORDS or INSTRUMENT_WORDS); the other words of that fact (the dog's name, its breed) belong to the same topic.
* A reply that says any of those words, when nothing in the person's own message touched that topic, has the sentence (or the clause after a dash) that says it taken out. The rest is left exactly as the model wrote it.
* If the message did touch the topic ("what is my dog's name?"), nothing is taken out. If taking it out would leave nothing, the reply is returned as it was.
* Only a topic the person's accepted facts actually cover is guarded: with no fact about a pet, a pet in a reply is the model's own invention, which this does not judge.

Importing this module has no side effects.
"""
from __future__ import annotations

import re

PET_WORDS = frozenset("dog dogs puppy puppies pup cat cats kitten kittens pet pets parrot rabbit hamster retriever labrador poodle beagle husky".split())
INSTRUMENT_WORDS = frozenset("guitar guitars piano violin drums ukulele flute saxophone cello".split())
TOPICS = {"pet": PET_WORDS, "instrument": INSTRUMENT_WORDS}
# words of a fact that say nothing about its topic (so they never count as a mention of it)
_FILLER = frozenset("""has have had my your his her its the and for with who that this you not are was were been from into new another got get bought buy own owns named name called user users one two
 lives live about golden""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
_GAP = re.compile(r"(?<=[.!?])(\s+)")
_DASH = re.compile(r"\s+[—–]\s+|;\s+")


def _words(text):
    return {w.lower().split("'")[0] for w in _WORD.findall(text or "") if len(w.split("'")[0]) >= 3}


def topics_of(fact_texts):
    """The words that mean each guarded topic, for the facts given: the topic's own words plus the other words of the facts about it (a pet's name). {} when no fact is about a topic."""
    found = {}
    for topic, own in TOPICS.items():
        about = [words for words in (_words(text) for text in fact_texts or ()) if words & own]
        if about:
            found[topic] = set(own).union(*[w - _FILLER for w in about])
    return found


def drop_unasked(reply, user_text, fact_texts):
    """`reply` without what it says about a pet or an instrument the person's message did not touch (see the top of this file). Anything that is not text is returned as it is."""
    if not isinstance(reply, str) or not reply.strip():
        return reply
    said = _words(user_text if isinstance(user_text, str) else "")
    guarded = set()
    for _topic, words in topics_of(fact_texts).items():
        if not (said & words):
            guarded |= words
    if not guarded:
        return reply

    def mentions(piece):
        return bool(_words(piece) & guarded)

    pieces = _GAP.split(reply)
    out = []
    for piece in pieces:
        if not piece.strip() or not mentions(piece):
            out.append(piece)
            continue
        parts = _DASH.split(piece)  # (a mention after a dash goes alone: "You've got this - and your dog will be proud." keeps "You've got this.")
        kept = [part for part in parts if not mentions(part)] if len(parts) > 1 else []
        if kept:
            ending = piece.rstrip()[-1] if piece.rstrip()[-1] in ".!?" else "."
            out.append(" — ".join(part.rstrip(" .!?") for part in kept) + ending)
        else:
            out.append(None)  # the whole sentence goes, and the gap before it
    if out == pieces:
        return reply  # nothing said about a guarded topic: exactly as the model wrote it
    cleaned = []
    for index, piece in enumerate(out):
        if piece is None:
            continue
        if piece.strip() == "" and (index + 1 < len(out) and out[index + 1] is None):
            continue  # the gap that led into a sentence that was taken out
        cleaned.append(piece)
    text = "".join(cleaned).strip()
    return text if text else reply
