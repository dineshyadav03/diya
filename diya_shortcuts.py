"""Shortcuts: a short phrase that stands for a longer request (docs/STUDY_ATTICUS.md).

The idea is Atticus's "when I say focus mode, close Slack and open my to-do list. Remembers it. Next time, two words do it all" (Atticus, github.com/SaarthurR/atticus-mac, MIT; see THIRD_PARTY_NOTICES.md).
Atticus saves the commands its AI worked out and replays them with no AI. Diya saves the person's own words instead: the phrase stands for the request they typed, and when they say the phrase, that request
is what Diya answers, as if they had typed all of it. Nothing is skipped by that: every check, gate and approval that a typed request meets is met by an expanded one, and no recorded action is ever run on
trust. What is saved is plain text in Diya's own database (`app_state`); what the model sees is the request, never the phrase.

    when I say morning check, show me my reminders and tasks      teaches it (said back by code, no model)
    morning check                                                 answers "show me my reminders and tasks"
    what shortcuts do I have / forget the shortcut morning check  lists / forgets (by code)

A phrase must be a few plain words that cannot be taken for a yes or a no (so a shortcut can never be a way to approve something), and a request may not be a yes or a no, another teaching, or the phrase of
another shortcut (no chains). At most MAX_SHORTCUTS are kept.
"""
from __future__ import annotations

import json
import re

KEY = "shortcuts"
MAX_SHORTCUTS = 50
PHRASE_MIN, PHRASE_MAX, PHRASE_WORDS = 4, 40, 6
REQUEST_MIN, REQUEST_MAX = 8, 300
_EDGE = " \t\r\n.,!?;:\"'“”‘’"
_TEACH = re.compile(r"^\W*(?:when|whenever|if)\s+i\s+(?:say|type|write)\s+(?P<phrase>.+?)\s*(?:[,:;]|\s+then\s+)\s*(?:please\s+)?(?P<request>.+)$", re.IGNORECASE | re.DOTALL)
_FORGET = re.compile(r"^\W*(?:forget|delete|remove|drop)\s+(?:the\s+|my\s+)?shortcut\s+(?P<phrase>.+?)\W*$", re.IGNORECASE)
_LIST = re.compile(r"^\W*(?:(?:what|which)\s+shortcuts\s+do\s+i\s+have|(?:list|show)(?:\s+me)?\s+(?:all\s+)?(?:my\s+|the\s+)?shortcuts|what\s+are\s+my\s+shortcuts)\W*$", re.IGNORECASE)
# What a typed yes or no is (the same words as Agent._TYPED_YES/_TYPED_NO): a shortcut is never one, and never expands to one.
_RESERVED = re.compile(
    r"^\W*(?:yes|yeah|yep|yup|sure|ok|okay|approve|approved|confirm|go ahead|do it|please do|sounds good|no|nope|cancel|stop|reject|don'?t|do not|never ?mind|no thanks|don'?t do it)"
    r"(?:[,.]?\s+(?:please|do it|go ahead|thanks|thank you))?\W*$", re.IGNORECASE)


def normalize(text):
    """A phrase as it is compared: lower case, one space between words, no quotes or punctuation at the edges."""
    return " ".join(str(text).lower().split()).strip(_EDGE)


def load(store):
    conn = store.connect()
    try:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (KEY,)).fetchone()
    finally:
        conn.close()
    try:
        found = json.loads(row[0]) if row else {}
    except (TypeError, ValueError):
        return {}
    return {k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(found, dict) else {}


def _save(store, items):
    conn = store.connect()
    try:
        conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (KEY, json.dumps(items, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def parse_teaching(text):
    """(phrase, request) when `text` teaches a shortcut ("when I say X, do Y"), else None."""
    if not isinstance(text, str) or len(text) > PHRASE_MAX + REQUEST_MAX + 40:
        return None
    found = _TEACH.match(text.strip())
    return (found.group("phrase"), found.group("request")) if found else None


def learn(store, phrase, request):
    """(whether it was kept, what to say). Refuses, saying why, a phrase that is too short, too long or too many words, one that could be a yes or a no, a request that is a yes or a no or another teaching
    or the phrase of another shortcut, and a 51st shortcut."""
    said = normalize(phrase)
    request = " ".join(str(request).split())
    if not (PHRASE_MIN <= len(said) <= PHRASE_MAX) or len(said.split()) > PHRASE_WORDS or not re.search(r"[a-z]", said):
        return False, f"That phrase is too short or too long to be a shortcut. Use two or three plain words, at most {PHRASE_MAX} letters."
    if _RESERVED.match(said):
        return False, "That could be a yes or a no, and a shortcut must never be a way to answer one. Pick other words."
    if not (REQUEST_MIN <= len(request) <= REQUEST_MAX) or any(ord(c) < 32 for c in request):
        return False, f"What it should do must be a plain request of {REQUEST_MIN} to {REQUEST_MAX} characters."
    items = load(store)
    if _RESERVED.match(request) or parse_teaching(request) or normalize(request) in items or said == normalize(request):
        return False, "A shortcut cannot stand for a yes or a no, for teaching another shortcut, or for another shortcut."
    if said not in items and len(items) >= MAX_SHORTCUTS:
        return False, f"I keep at most {MAX_SHORTCUTS} shortcuts. Forget one first: forget the shortcut <words>."
    again = said in items
    items[said] = request
    _save(store, items)
    return True, f'Okay. When you say "{said}", I will do this: {request}' + (" (it replaces the old one)" if again else "")


def forget(store, phrase):
    items = load(store)
    said = normalize(phrase)
    if said not in items:
        return f'I have no shortcut called "{said}". Ask what shortcuts you have.'
    del items[said]
    _save(store, items)
    return f'Forgot the shortcut "{said}".'


def listing(store):
    items = load(store)
    if not items:
        return 'You have no shortcuts yet. Teach one: "when I say morning check, show me my reminders and tasks".'
    return "Your shortcuts:\n" + "\n".join(f'- "{k}": {v}' for k, v in sorted(items.items()))


def reply_to(store, text):
    """What to say to a message that teaches, forgets or lists shortcuts, or None when it is none of those."""
    taught = parse_teaching(text)
    if taught:
        return learn(store, *taught)[1]
    if isinstance(text, str) and len(text) < 120:
        found = _FORGET.match(text.strip())
        if found:
            return forget(store, found.group("phrase"))
        if _LIST.match(text.strip()):
            return listing(store)
    return None


def expand(store, text):
    """The request a taught phrase stands for, when the WHOLE message is that phrase (any case, any punctuation at its ends); else None."""
    if not isinstance(text, str) or len(text) > PHRASE_MAX + 20:
        return None
    return load(store).get(normalize(text))
