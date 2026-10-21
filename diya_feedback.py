"""What the person thinks of Diya's replies: helpful or not, why, and a note (docs/FEEDBACK_DESIGN.md), added 2026-10-21.

The weakest part of Diya was the one that tells her she got something wrong: nothing recorded a bad answer, so the only measurements were ones made on invented data. This records, per reply, a rating (helpful or
not helpful), one reason from a fixed list when it was not, and an optional note in the person's own words. It is kept against the person's message that the reply answers, because that message has a number on
every page the moment it is sent.

The shape follows the feedback design of DeepSeek's harness (MIT; harness/LICENSE; THIRD_PARTY_NOTICES.md): a positive or negative rating, an optional category from a fixed list, an optional note that must hold
something and fit a limit and is kept exactly as written, and a version on each item so that a stale edit is refused and shows the current item. The list of reasons and every word here are Diya's own.

Nothing here changes what Diya says or remembers; it is read by the person (the scorecard counts it) and never given to the model. Forgetting the message takes its feedback with it. Importing this module has no side effects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

RATINGS = ("positive", "negative")
CATEGORIES = {
    "wrong": "The answer was wrong",
    "made-up": "It made something up",
    "not-what-i-asked": "It did not do what I asked",
    "slow": "It was too slow",
    "privacy": "It showed or asked for something private or unsafe",
    "other": "Something else",
}
MAX_NOTE_CHARS = 2000


class FeedbackError(ValueError):
    """What was sent cannot be kept: said in words the person can read."""


class Conflict(FeedbackError):
    """The item was changed since the person looked (another page, another device): `current` is what it is now, or None if it is gone."""

    def __init__(self, message, current):
        super().__init__(message)
        self.current = current


def _item(row):
    message_id, rating, category, note, version, updated = row
    return {"message_id": message_id, "rating": rating, "category": category, "note": note, "version": version, "at": updated}


_COLUMNS = "message_id, rating, category, note, version, updated_at"


class Feedback:
    def __init__(self, store):
        self.store = store

    def items(self, message_ids):
        """{message id: item} for those of `message_ids` that have feedback."""
        ids = [int(i) for i in message_ids if isinstance(i, int) and not isinstance(i, bool)]
        if not ids:
            return {}
        conn = self.store.connect()
        try:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM reply_feedback WHERE message_id IN ({','.join('?' * len(ids))})", ids).fetchall()
        finally:
            conn.close()
        return {row[0]: _item(row) for row in rows}

    def put(self, message_id, rating, category=None, note=None, version=None):
        """Keep the person's rating of the reply to message `message_id` and return the item. `version` is None to create and the version the person saw to change one; anything else is a Conflict that carries
        the current item. Saying the same thing again changes nothing (the version stays). FeedbackError for a message that is not the person's own, an unknown rating or reason, or a blank or over-long note."""
        if rating not in RATINGS:
            raise FeedbackError("A reply is helpful or not helpful.")
        if category is not None and category not in CATEGORIES:
            raise FeedbackError("That is not one of the reasons.")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            raise FeedbackError("A note needs some words in it; leave it out if there is nothing to say.")
        if note is not None and len(note) > MAX_NOTE_CHARS:
            raise FeedbackError(f"A note is at most {MAX_NOTE_CHARS} characters.")
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM messages WHERE id = ? AND role = 'user'", (int(message_id),)).fetchone() is None:
                raise FeedbackError("There is no such message of yours.")
            now = datetime.now(timezone.utc).isoformat()
            row = conn.execute(f"SELECT {_COLUMNS} FROM reply_feedback WHERE message_id = ?", (int(message_id),)).fetchone()
            if version is None:
                if row is not None:
                    raise Conflict("This reply already has feedback, changed from another page. Here is how it stands.", _item(row))
                conn.execute("INSERT INTO reply_feedback (message_id, rating, category, note, version, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)", (int(message_id), rating, category, note, now, now))
            else:
                if row is None or row[4] != version:
                    raise Conflict("This feedback was changed from another page since you looked, so your change was not kept.", None if row is None else _item(row))
                if (row[1], row[2], row[3]) == (rating, category, note):
                    conn.commit()
                    return _item(row)
                conn.execute("UPDATE reply_feedback SET rating = ?, category = ?, note = ?, version = version + 1, updated_at = ? WHERE message_id = ?", (rating, category, note, now, int(message_id)))
            conn.commit()
            return _item(conn.execute(f"SELECT {_COLUMNS} FROM reply_feedback WHERE message_id = ?", (int(message_id),)).fetchone())
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete(self, message_id, version):
        """Take the feedback away. Conflict, changing nothing, if it was changed since the person looked or is already gone."""
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(f"SELECT {_COLUMNS} FROM reply_feedback WHERE message_id = ?", (int(message_id),)).fetchone()
            if row is None or row[4] != version:
                raise Conflict("This feedback was changed from another page since you looked, so nothing was removed.", None if row is None else _item(row))
            conn.execute("DELETE FROM reply_feedback WHERE message_id = ?", (int(message_id),))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def summary(self, days=30, now=None):
        """Numbers only: {rated, positive, negative, by_reason: {reason: count}} for the feedback given in the last `days` days. No note and no message is in it."""
        since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        conn = self.store.connect()
        try:
            rows = conn.execute("SELECT rating, category FROM reply_feedback WHERE updated_at >= ?", (since,)).fetchall()
        finally:
            conn.close()
        found = {"rated": len(rows), "positive": sum(1 for r, _c in rows if r == "positive"), "negative": sum(1 for r, _c in rows if r == "negative"), "by_reason": {}}
        for rating, category in rows:
            if rating == "negative":
                found["by_reason"][category or "no reason given"] = found["by_reason"].get(category or "no reason given", 0) + 1
        return found
