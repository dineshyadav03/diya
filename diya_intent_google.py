"""Did the person ask Diya to CHANGE something that is already in their Google account? (docs/GOOGLE_CHANGES.md), added 2026-10-26.

The same rule as for adding (diya_intent, 'did the person ask for something to be added'): a change is proposed only when the latest message asks for exactly that thing, in these words; missing an unusual phrasing is the safe
direction (they can say it again plainly), and a proposal nobody asked for is refused before anything is recorded. A question about how ("how do i delete a task"), a refusal ("don't delete it") and a message about a
different place are never a request. Each function answers one kind of change at one service; they are used as the `asked` check of the matching ActionKind and so are called with the owner's whole message.

Importing this module has no side effects.
"""
from __future__ import annotations

import re

import diya_intent as intent

_QUESTION_HOW = re.compile(r"^\W*(?:how|what|why|where|when|can\s+i|could\s+i|do\s+i|does\s+it|is\s+it|is\s+there)\b", re.IGNORECASE)
_NO = re.compile(r"\b(?:don'?t|do\s+not|never|no\s+need\s+to|stop)\s+(?:\w+\s+){0,2}?(?:delete|remove|complete|mark|change|rename|move|update|edit|send|share|cancel|archive|trash)\b", re.IGNORECASE)


def _plain(text):
    """The message as one short line of text, or None: not text, long, or several lines."""
    if not isinstance(text, str) or not text.strip() or len(text) > 400 or "\n" in text.strip():
        return None
    return text.replace(chr(0x2019), "'")


def _asks(text, verbs, *, place=None):
    """The message gives an instruction with one of `verbs`, is not a question about how, not a refusal, not a reminder, and (if `place` is given) names that place."""
    said = _plain(text)
    if said is None or _QUESTION_HOW.match(said) or _NO.search(said) or intent.is_reminder_request(said):
        return False
    return re.search(verbs, said, re.IGNORECASE) is not None and (place is None or place(said))


# ---- Google Tasks ----------------------------------------------------------------------------------------------------------------------------------

_DONE = r"\b(?:mark|tick|check|cross)\b[^.?!]{0,60}\b(?:done|complete|completed|finished|off)\b|\b(?:complete|finish)\b"
_CHANGE = r"\b(?:rename|retitle|change|update|edit|reschedule)\b"
_REMOVE = r"\b(?:delete|remove|get\s+rid\s+of)\b"
_MOVE = r"\bmove\b[^.?!]{0,80}\b(?:to\s+the\s+top|under|below)\b|\bmake\b[^.?!]{0,60}\ba\s+subtask\b"


def completes_google_task(text):
    return _asks(text, _DONE, place=intent.names_google_tasks)


def changes_google_task(text):
    return _asks(text, _CHANGE, place=intent.names_google_tasks)


def deletes_google_task(text):
    return _asks(text, _REMOVE, place=intent.names_google_tasks)


def moves_google_task(text):
    return _asks(text, _MOVE, place=intent.names_google_tasks)
