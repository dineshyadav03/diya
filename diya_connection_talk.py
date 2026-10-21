"""Answering "are you connected to my Google Calendar?" from the connection record, not from the model (task found on 2026-10-21 by the first real sign-in).

After Google Calendar was connected, Diya's model answered "No, I'm not connected to Google Calendar... you'd need to open Google Calendar yourself": it had the calendar tool, but a question ABOUT being connected does not
call a tool, so the model answered from what it knows in general, which is wrong about this one computer. What is connected is a fact in a file, so code says it, as it does for "how do you know that?"
(diya_provenance) and for what a note says: the answer names each connection, whether it is connected, and in the words the Connections page uses what it can and cannot do. The model is not asked.

Only a short message that is plainly that question is taken ("are you connected to the calendar?", "is Gmail connected?", "which accounts are connected?", "can you see my calendar?"); anything longer, or that asks for something
("what is on my calendar tomorrow?"), goes on to the model and its tools as before. Importing this module has no side effects.
"""
from __future__ import annotations

import re

import diya_connectors

MAX_CHARS = 90

_ARE = re.compile(r"\b(?:are|is|do|does)\s+(?:you|diya)\b.*\b(?:connected|linked|signed\s+in|logged\s+in|have\s+access|able\s+to\s+(?:see|read|access))\b", re.IGNORECASE)
_IS_X_CONNECTED = re.compile(r"\bis\s+(?:my\s+|the\s+)?(?:google\s+)?[a-z ]{3,25}\s+(?:connected|linked)\b", re.IGNORECASE)
_WHICH = re.compile(r"\b(?:which|what)\s+(?:accounts?|services?|apps?|connections?|things)\b.*\b(?:connected|linked|have\s+access\s+to)\b", re.IGNORECASE)
_CAN = re.compile(r"^\W*can\s+you\s+(?:see|read|access)\s+(?:my\s+)?(?:google\s+)?[a-z ]{3,25}\W*$", re.IGNORECASE)

# what the person says -> a piece of a connection's label (compared in lower case)
SUBJECTS = (
    ("home assistant", "home assistant"), ("calendar", "calendar"), ("gmail", "gmail"), ("e-mail", "gmail"), ("email", "gmail"), ("mail", "gmail"), ("inbox", "gmail"),
    ("tasks", "tasks"), ("todoist", "todoist"), ("drive", "drive"), ("docs", "drive"), ("documents", "drive"), ("notion", "notion"),
)


def asks_about_connection(text):
    """None if `text` is not the question; otherwise the piece of a connection's label it asks about ("calendar", "gmail", ...), or "" for "which accounts are connected?"."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS or "\n" in text:
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    if not (_ARE.search(flat) or _IS_X_CONNECTED.search(flat) or _WHICH.search(flat) or _CAN.search(flat)):
        return None
    lowered = flat.lower()
    for word, piece in SUBJECTS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return piece
    if _WHICH.search(flat) or re.search(r"\b(?:google|accounts?|services?|anything|any\s+of|everything)\b", lowered):
        return ""  # about all of them
    return None  # "are you connected to the internet?": not about an account, so the model answers


def answer(config, connectors, subject):
    """The reply, in plain words, from the record; None when the question names something no connection is about (then the model is left to answer)."""
    real = [c for c in connectors if c.implemented]
    chosen = [c for c in real if not subject or subject in c.label.lower()]
    if not chosen:
        return None
    lines = []
    for connector in chosen:
        if diya_connectors.is_connected(config, connector.name):
            can = " ".join(sentence.rstrip(".") + "." for sentence in getattr(connector, "access", ()) or ())
            lines.append(f"Yes: {connector.label} is connected." + (f" {can}" if can else ""))
        else:
            lines.append(f"No: {connector.label} is not connected.")
    if not subject:
        on = [c.label for c in chosen if diya_connectors.is_connected(config, c.name)]
        off = [c.label for c in chosen if not diya_connectors.is_connected(config, c.name)]
        lines = [("Connected now: " + ", ".join(on) + ".") if on else "Nothing is connected now.", ("Not connected: " + ", ".join(off) + ".") if off else ""]
    tail = "I look inside one only when you ask, and I can change something in one only after you press Approve on the Actions page. The Connections page connects and disconnects them."
    return "\n".join([line for line in lines if line] + [tail])
