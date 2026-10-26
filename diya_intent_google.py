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


def _plain(text, limit=400):
    """The message as one short line of text, or None: not text, long, or several lines."""
    if not isinstance(text, str) or not text.strip() or len(text) > limit or "\n" in text.strip():
        return None
    return text.replace(chr(0x2019), "'")


def _asks(text, verbs, *, place=None, limit=400):
    """The message gives an instruction with one of `verbs`, is not a question about how, not a refusal, not a reminder, and (if `place` is given) names that place."""
    said = _plain(text, limit)
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


# ---- Gmail (diya_google_mailwrite) -----------------------------------------------------------------------------------------------------------------
#
# A message that is itself the email's text can be longer than a task, so these allow up to MAIL_ASK_CHARS in one line. Sending, replying and forwarding are told apart by the words used, so that a request to
# "draft" is never taken as a request to send.

MAIL_ASK_CHARS = 2000
_MAIL = re.compile(r"\b(?:e-?mails?|mails?|gmail|messages?)\b", re.IGNORECASE)
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_NOT_A_SEND = re.compile(r"\b(?:drafts?|reply|replies|respond|forward|fwd)\b", re.IGNORECASE)


def _mail_word(said):
    return _MAIL.search(said) is not None


def _has_address(said):
    return _ADDRESS.search(said) is not None


def sends_mail(text):
    """Send a NEW email to an address the person typed ("send an email to dad@x.com saying I will be late", "email dad@x.com that ...")."""
    said = _plain(text, MAIL_ASK_CHARS)
    return said is not None and _NOT_A_SEND.search(said) is None and _asks(said, r"\b(?:send|e-?mail|mail|write|compose)\b", place=_has_address, limit=MAIL_ASK_CHARS)


def replies_to_mail(text):
    """Reply to one email the person names ("reply to Maya's email saying yes")."""
    return _asks(text, r"\b(?:reply|respond|answer)\b", place=_mail_word, limit=MAIL_ASK_CHARS)


def forwards_mail(text):
    """Forward one email to an address the person typed ("forward the email from the bank to mum@x.com")."""
    return _asks(text, r"\b(?:forward|fwd)\b", place=lambda said: _mail_word(said) and _has_address(said), limit=MAIL_ASK_CHARS)


def drafts_mail(text):
    """Save an email as a draft ("draft an email to dad about Sunday", "save a draft to ...")."""
    return _asks(text, r"\bdrafts?\b", place=lambda said: _mail_word(said) or _has_address(said), limit=MAIL_ASK_CHARS)


def discards_draft(text):
    """Throw away one draft ("delete the draft about Sunday")."""
    return _asks(text, r"\b(?:delete|discard|remove|throw\s+away|get\s+rid\s+of|trash)\b", place=lambda said: re.search(r"\bdrafts?\b", said, re.IGNORECASE) is not None)


_FILE_MAIL = (
    r"\barchive\b|\bmark\b[^.?!]{0,60}\b(?:as\s+)?(?:read|unread)\b|\b(?:star|unstar)\b|\b(?:label|unlabel|tag)\b|\b(?:trash|bin)\b|\b(?:delete|remove|get\s+rid\s+of)\b"
    r"|\bmove\b[^.?!]{0,60}\b(?:bin|trash)\b|\b(?:restore|undelete|untrash|bring\s+back|put\s+back)\b"
)


def organises_mail(text):
    """File one email: archive, mark read or unread, star, label, bin, or bring back ("archive the email from the bank", "put the label Exams on Maya's email")."""
    said = _plain(text)
    return said is not None and _asks(said, _FILE_MAIL, place=_mail_word) and re.search(r"\bdrafts?\b", said, re.IGNORECASE) is None
