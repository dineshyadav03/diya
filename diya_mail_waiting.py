"""Mail that is waiting for a reply, found by code (docs/HOME_DESIGN.md, 2026-10-27): the source of Home's mail cards.

The rule is deliberately narrow, because a card that is wrong teaches the person to ignore the next one. It was made narrower after the first look at the real mailbox (2026-10-27): six threads passed
every other test and not one was a person (hackathon offers, a survey, event mail; all single messages, all marked Important and Personal by Gmail, none with a List-Unsubscribe mark). A thread counts only when ALL of this holds:
  * it is in the inbox, in the Primary tab, and newer than three days;
  * it is a CONVERSATION the person is in: an earlier message of the thread is the person's own, so a cold message from someone the person never wrote to (the shape of every offer and newsletter) never counts,
    which also means a first message from a new real person is not found; the person sees it in the inbox, and a card that is wrong costs more than a card that is missed;
  * its LAST message is not the person's own, not a draft of theirs, and not in the bin or spam, so a thread already answered, or one being answered, is never listed;
  * the sender looks like a person: not a no-reply or notification address, and the message carries no bulk-mail marks (List-Unsubscribe, Precedence: bulk or list, Auto-Submitted).
Oldest first, since the longest wait matters most. At most MAX_THREADS threads are looked at: one request to list and one to read each, read only, nothing is changed, and no text of any mail is read
(headers and labels only).

The sender's name and the subject are words from a stranger: they are cleaned (control and invisible characters made visible) and cut, shown as text, and never made into an instruction. `read` is given
the world (`get`, `access_token`) so it is tested without Google.
"""
from __future__ import annotations

import re
from datetime import datetime

import diya_google_calendar
import diya_google_mail as gm
from diya_google_mail import MailError

QUERY = "in:inbox category:primary newer_than:3d -from:me"
MAX_THREADS = 6
LISTED = 12
HEADERS = ["From", "Subject", "Date", "List-Unsubscribe", "Precedence", "Auto-Submitted"]
_AUTOMATIC_ADDRESS = re.compile(r"(?:^|[._+-])(?:no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|mailer[-_.]daemon|postmaster|bounces?|newsletter|automated?)(?:[._+-]|@)", re.IGNORECASE)
_BULK = re.compile(r"\b(?:bulk|list|junk)\b", re.IGNORECASE)
_ADDRESS = re.compile(r"<([^<>@\s]+@[^<>@\s]+)>|([^\s<>@,;]+@[^\s<>@,;]+)")
_SKIPPED_LABELS = {"SENT", "DRAFT", "TRASH", "SPAM"}


def sender_of(value):
    """(display name, lower-case address) of a From header; either may be empty. A header with no name gets one made from the start of the address."""
    value = value or ""
    found = _ADDRESS.search(value)
    address = (found.group(1) or found.group(2)).lower() if found else ""
    name = value.split("<", 1)[0].strip().strip("\"' ").strip()
    if not name or "@" in name:
        name = address.split("@")[0].replace(".", " ").replace("_", " ").title() if address else ""
    return name, address


def automatic(message, address):
    """Does this message look sent by a machine, so that nobody is waiting for an answer?"""
    payload = message.get("payload") or {}
    if _AUTOMATIC_ADDRESS.search(address):
        return True
    if gm._header(payload, "List-Unsubscribe"):
        return True
    if _BULK.search(gm._header(payload, "Precedence")):
        return True
    auto = gm._header(payload, "Auto-Submitted").strip().lower()
    return bool(auto) and auto != "no"


def waiting(thread):
    """{thread, from_name, from_address, subject, sent} when the thread waits for the person's reply, else None."""
    messages = thread.get("messages") or []
    if not messages or not isinstance(messages[-1], dict):
        return None
    last = messages[-1]
    if set(last.get("labelIds") or []) & _SKIPPED_LABELS:
        return None
    if not any(isinstance(m, dict) and "SENT" in (m.get("labelIds") or []) for m in messages[:-1]):
        return None  # nobody here was written to by the person: not a conversation
    payload = last.get("payload") or {}
    name, address = sender_of(gm._header(payload, "From"))
    if not address or automatic(last, address):
        return None
    try:
        sent = datetime.fromtimestamp(int(last["internalDate"]) / 1000)  # local time, naive, like the rest of Home
    except (KeyError, ValueError, TypeError, OSError, OverflowError):
        return None
    return {
        "thread": str(thread.get("id") or ""), "from_name": gm._clean(name, 60), "from_address": address,
        "subject": gm._clean(gm._header(payload, "Subject") or "(no subject)", 100), "sent": sent,
    }


def read(config, get=None, access_token=None):
    """The threads waiting for a reply, oldest first. Raises MailError (safe words) when Gmail is not connected or cannot be read."""
    token = access_token if access_token is not None else diya_google_calendar.access_token(config, gm.TOKEN)
    if not token:
        raise MailError(diya_google_calendar.not_connected_words(config, gm.TOKEN, "Gmail"))
    api = gm._Api(token, get)
    listed = api.json("messages", {"q": QUERY, "maxResults": LISTED})
    thread_ids = []
    for item in listed.get("messages") or []:
        thread_id = item.get("threadId") if isinstance(item, dict) else None
        if isinstance(thread_id, str) and gm._ID.fullmatch(thread_id) and thread_id not in thread_ids:
            thread_ids.append(thread_id)
    found = []
    for thread_id in thread_ids[:MAX_THREADS]:
        item = waiting(api.json(f"threads/{thread_id}", {"format": "metadata", "metadataHeaders": HEADERS}))
        if item:
            found.append(item)
    return sorted(found, key=lambda item: item["sent"])
