"""One append-only journal of everything Diya did with a tool or a connector (docs/ACTIVITY_JOURNAL_DESIGN.md).

Until now the trail was in pieces: facts had their events, actions had theirs, connectors had a plain log, and a tool the model called on its own left only a line on the console. A question like "what did
Diya look at for me this morning, and what did she do with my mail?" had no single answer. This is that answer: every tool the model called, and every thing code did on the person's behalf
(searched the web, read a notes page, looked through the mail, studied a repository, refused to send a mail), as one row each, never changed and never deleted (the database itself refuses an UPDATE
or a DELETE on it).

What a row holds is deliberately small: when, which tool, what kind of thing it was, whether it ran in a chat or unattended, which chat and message it came from, a digest of its arguments (so two identical
calls can be seen to be identical) and a short preview of them with anything that looks like a secret hidden, how it came out (ok, error or refused), how long the result was and how long it took. Not the
result: a mail, a page or a repository is not copied into a log.

Recording never raises and never slows an answer by more than one small insert: a journal that could break a chat would be worse than none.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys

STATUSES = ("ok", "error", "refused")
KINDS = ("tool", "flow")  # tool: the model called it; flow: code did it because of what the person said
ORIGINS = ("chat", "unattended")
PREVIEW_CHARS = 100
VALUE_CHARS = 40
NOTE_CHARS = 200
_SECRET_NAME = re.compile(r"token|secret|password|passcode|passwd|key|authorization|credential|cookie", re.IGNORECASE)


def _canonical(args):
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(args)


def digest(args):
    """A fingerprint of the arguments: equal arguments, equal digest."""
    return hashlib.sha256(_canonical(args).encode("utf-8")).hexdigest()[:16]


# A value that looks like a credential or like a person's contact detail is hidden even when its name is innocent ("query", "text"): an API key, a Google token, a login token (three dotted parts), a long run of letters
# and digits with no spaces, an email address, a card-like or phone-like number. Hiding too much of a preview costs a little detail; leaking costs more (DIYA-215).
_SECRET_VALUE = re.compile(
    r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}|\bya29\.[A-Za-z0-9._-]{10,}|\b1//[A-Za-z0-9._-]{20,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|\bAIza[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\b[A-Za-z0-9+/=_-]{32,}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b|\b(?:\d[ -]?){13,19}\b|\+\d[\d ()-]{8,}\d",
)


def _hide_secrets(text):
    return _SECRET_VALUE.sub("[hidden]", text)


def preview(args, limit=PREVIEW_CHARS):
    """The arguments in one short line for a person to read: names and cut-down values, with the value of anything named like a secret hidden, and anything that looks like a credential, an email address or a card or phone
    number hidden wherever it is."""
    import diya_memory

    if isinstance(args, dict):
        parts = []
        for name, value in args.items():
            shown = "[hidden]" if _SECRET_NAME.search(str(name)) else _hide_secrets(diya_memory.printable(value if isinstance(value, str) else _canonical(value), VALUE_CHARS * 3))
            parts.append(f"{diya_memory.printable(name, 30)}={diya_memory.printable(shown, VALUE_CHARS)}")
        return diya_memory.printable(", ".join(parts), limit)
    return diya_memory.printable(_hide_secrets(diya_memory.printable(args, limit * 3)), limit)


def record(store, tool, args, status, *, kind="tool", origin="chat", thread_id=None, message_id=None, result=None, seconds=None, note=None):
    """Write one row. Returns its id, or None if it could not be written (said on the console, never raised)."""
    try:
        if status not in STATUSES or kind not in KINDS or origin not in ORIGINS:
            raise ValueError(f"not a journal entry: {status!r} {kind!r} {origin!r}")
        import diya_memory

        words = getattr(store, "journal_previews", True)  # False (DIYA_JOURNAL_PREVIEWS=0): nothing that says what a tool was asked is kept, only that it happened, when, how it came out and how long it took
        return store.journal_add(
            tool=diya_memory.printable(tool, 60), kind=kind, origin=origin, thread_id=thread_id, message_id=message_id, args_digest=digest(args), args_preview=preview(args) if words else None, status=status,
            result_chars=len(result) if isinstance(result, str) else None, duration_ms=None if seconds is None else int(seconds * 1000),
            note=None if note is None or not words else _hide_secrets(diya_memory.printable(note, NOTE_CHARS)),
        )
    except Exception as exc:  # noqa: BLE001 -- a journal must never be what breaks an answer
        print(f"[journal] could not write an entry ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None


def prune(store, days, now=None):
    """Remove the rows older than `days` days (0 or less: nothing is removed). Returns how many were removed; a receipt (journal_receipts) says so. Never raises: a journal that could not be tidied is still a journal."""
    from datetime import datetime, timedelta, timezone

    try:
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            return 0
        before = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        return store.journal_prune(before)
    except Exception as exc:  # noqa: BLE001
        print(f"[journal] could not remove old rows ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0
