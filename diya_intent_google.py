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


_MAIL_TO_NAME = re.compile(r"\b(?:send|write|compose)\s+(?:an?\s+|the\s+)?(?:e-?mail|mail|message)\s+to\s+[A-Za-z]|\be-?mail\s+[A-Z][a-z]+\b|\bmail\s+[A-Z][a-z]+\b")


def _mails_a_name(said):
    """Does the message send mail to someone by NAME ("send an email to Maya", "email Maya that ..."): Diya turns a name into an address only through the contacts."""
    return _MAIL_TO_NAME.search(said) is not None


def sends_mail(text):
    """Send a NEW email to an address the person typed ("send an email to dad@x.com saying I will be late", "email dad@x.com that ...")."""
    said = _plain(text, MAIL_ASK_CHARS)
    return said is not None and _NOT_A_SEND.search(said) is None and _asks(said, r"\b(?:send|e-?mail|mail|write|compose)\b", place=lambda s: _has_address(s) or _mails_a_name(s), limit=MAIL_ASK_CHARS)


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


# ---- Google Contacts (diya_google_contacts) -------------------------------------------------------------------------------------------------------

_CONTACT = re.compile(r"\bcontacts?\b|\baddress\s*book\b", re.IGNORECASE)
_PHONE_OR_MAIL = re.compile(r"\b(?:e-?mail|number|phone|mobile)\b", re.IGNORECASE)


def adds_contact(text):
    """Save a new contact ("add Maya to my contacts: maya@example.com", "save a new contact called Sam, number 98xxxxxxx")."""
    return _asks(text, r"\b(?:add|save|create|make|put)\b", place=lambda said: _CONTACT.search(said) is not None)


def updates_contact(text):
    """Add an email or number to a contact ("add a number to Maya's contact: 98xxxxxxx", "update Sam's email in my contacts")."""
    return _asks(text, r"\b(?:update|change|set|add|put|correct)\b", place=lambda said: _CONTACT.search(said) is not None and _PHONE_OR_MAIL.search(said) is not None)


def deletes_contact(text):
    """Delete one contact ("delete Maya from my contacts")."""
    return _asks(text, r"\b(?:delete|remove|get\s+rid\s+of)\b", place=lambda said: _CONTACT.search(said) is not None)


def groups_contact(text):
    """Put a contact in a group (label), or take them out ("put Maya in my Classmates group", "remove Sam from the family group")."""
    return _asks(text, r"\b(?:put|add|move|remove|take)\b[^.?!]{0,80}\b(?:group|label)\b", place=lambda said: _CONTACT.search(said) is not None or re.search(r"\b(?:group|label)\b", said, re.IGNORECASE) is not None and not _drive_word(said) and not _mail_word(said))


# ---- Google Drive and Docs changes (diya_google_drive) ---------------------------------------------------------------------------------------------

_DRIVE_THING = re.compile(r"\b(?:drive|files?|folders?|documents?|docs?|sheets?|spreadsheets?|slides?|presentations?)\b", re.IGNORECASE)
_NOT_DRIVE = re.compile(r"\b(?:e-?mails?|mails?|calendar|events?|meetings?|appointments?|tasks?|reminders?|drafts?)\b", re.IGNORECASE)
_DOC_WORD = re.compile(r"\b(?:google\s+)?(?:docs?|documents?)\b", re.IGNORECASE)
_MAKE_A_DOC = re.compile(r"\b(?:create|make|start|new)\b[^.?!]{0,30}\b(?:docs?|documents?)\b", re.IGNORECASE)


def _drive_word(said):
    return _DRIVE_THING.search(said) is not None and _NOT_DRIVE.search(said) is None


def renames_drive_file(text):
    """Rename one file or folder in Drive ("rename the file Notes to Exam notes")."""
    return _asks(text, r"\b(?:rename|retitle)\b", place=_drive_word)


def moves_drive_file(text):
    """Move one file into a folder ("move Exam notes into the folder Exams")."""
    return _asks(text, r"\bmove\b|\b(?:put|file)\b[^.?!]{0,60}\b(?:in|into|to)\s+(?:the\s+|my\s+)?(?:\w+\s+){0,3}folder\b", place=lambda said: _drive_word(said) or re.search(r"\bfolder\b", said, re.IGNORECASE) is not None)


def trashes_drive_file(text):
    """Put one file or folder in the Drive bin ("delete the file Old notes", "move Old notes to the bin")."""
    return _asks(text, r"\b(?:delete|trash|remove|bin)\b|\bget\s+rid\s+of\b", place=_drive_word)


def restores_drive_file(text):
    """Bring one file back from the Drive bin ("restore Old notes from the bin")."""
    return _asks(text, r"\b(?:restore|undelete|untrash|bring\s+back|put\s+back)\b", place=_drive_word)


def shares_drive_file(text):
    """Share one file with an address the person typed ("share Exam notes with maya@x.com, she can view it")."""
    return _asks(text, r"\bshare\b|\bgive\b[^.?!]{0,40}\baccess\b|\blet\b[^.?!]{0,40}\b(?:view|see|read|comment|edit)\b", place=lambda said: _drive_word(said) and _has_address(said))


def unshares_drive_file(text):
    """Stop sharing one file with an address the person typed."""
    return _asks(text, r"\bunshare\b|\bstop\s+sharing\b|\b(?:remove|take\s+away|revoke)\b[^.?!]{0,40}\baccess\b", place=lambda said: _drive_word(said) and _has_address(said))


def edits_google_doc(text):
    """Add to, or change words in, a Google Doc that Diya made ("add a line to my Study plan doc", "in the Study plan doc change monday to tuesday")."""
    said = _plain(text)
    return said is not None and _MAKE_A_DOC.search(said) is None and _asks(said, r"\b(?:append|replace|insert|add|change|fix|correct|update|rewrite)\b", place=lambda s: _DOC_WORD.search(s) is not None and _NOT_DRIVE.search(s) is None)


# ---- Google Calendar changes (diya_google_calchange) -----------------------------------------------------------------------------------------------

_CAL = re.compile(r"\b(?:calendar|events?|meetings?|appointments?|sessions?|classes|class|lectures?|interviews?|exams?|invit\w+)\b", re.IGNORECASE)
_REPEAT_WORDS = re.compile(
    r"\b(?:daily|weekly|monthly|yearly|annually|every\s+(?:day|week|month|year|mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)\w*|each\s+(?:day|week|month|year))\b", re.IGNORECASE)


def _cal_word(said):
    return _CAL.search(said) is not None and not intent.names_google_tasks(said)


def changes_calendar_event(text):
    """Move, rename or change the length of one calendar event ("move my dentist appointment to friday at 3pm", "rename the physics session")."""
    return _asks(text, r"\b(?:reschedule|move|shift|push|postpone|rename|retitle|change|update|extend|shorten)\b", place=_cal_word)


def cancels_calendar_event(text):
    """Cancel one calendar event ("cancel my dentist appointment")."""
    return _asks(text, r"\b(?:cancel|delete|remove|drop|scrap|call\s+off)\b", place=_cal_word)


def invites_to_event(text):
    """Invite typed addresses to one event ("invite maya@x.com to the physics session")."""
    return _asks(text, r"\binvite\b|\badd\b[^.?!]{0,60}\b(?:guests?|attendees?)\b|\badd\b[^.?!]{0,60}\bto\s+(?:the|my)\s+(?:\w+\s+){0,3}(?:meeting|event|appointment|session)\b", place=lambda said: _cal_word(said) and _has_address(said))


def answers_invitation(text):
    """Accept, decline or say maybe to an invitation ("accept the invitation to the physics session", "decline the meeting with Sam")."""
    return _asks(text, r"\b(?:accept|decline|reject|rsvp|tentatively)\b|\bsay\s+(?:yes|no|maybe)\s+to\b", place=_cal_word)


def adds_repeating_event(text):
    """Add an event that repeats ("add a weekly study session on mondays at 6pm for 8 weeks")."""
    said = _plain(text)
    if said is None or _REPEAT_WORDS.search(said) is None or intent.names_google_tasks(said) or not intent._asks_to_add(said):
        return False
    return re.search(r"\bcalendar\b|\b(?:meeting|appointment|event|session|class|lecture|lesson|interview)\b", said, re.IGNORECASE) is not None


_FILE_MAIL = (
    r"\barchive\b|\bmark\b[^.?!]{0,60}\b(?:as\s+)?(?:read|unread)\b|\b(?:star|unstar)\b|\b(?:label|unlabel|tag)\b|\b(?:trash|bin)\b|\b(?:delete|remove|get\s+rid\s+of)\b"
    r"|\bmove\b[^.?!]{0,60}\b(?:bin|trash)\b|\b(?:restore|undelete|untrash|bring\s+back|put\s+back)\b"
)


def organises_mail(text):
    """File one email: archive, mark read or unread, star, label, bin, or bring back ("archive the email from the bank", "put the label Exams on Maya's email")."""
    said = _plain(text)
    return said is not None and _asks(said, _FILE_MAIL, place=_mail_word) and re.search(r"\bdrafts?\b", said, re.IGNORECASE) is None
