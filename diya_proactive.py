"""Diya writes first (docs/PROACTIVE_DESIGN.md).

Until now Diya only ever answered: she spoke when spoken to, and a reminder was a notification with no message behind it. This makes her start the conversation, in the chat itself, so there is
a message waiting when the person opens it (and a notification, when the notifier runs): a good-morning with the day, a check-in in the evening about what is still open, a note when a reminder
comes due, and a hello after a few quiet days. It is the scheduled notifier (diya_notify.py, every five minutes) that calls `make`.

Every word is built here, in code, from the person's own reminders and tasks (diya_brief), never by the model: nothing can be invented, nothing needs the model to be loaded, and a morning
message costs no seconds of CPU. The cost of that is that the messages are plain; the variety is in their timing and their content, and the greeting changes from day to day.

Rules that keep it from nagging: every kind has its time (morning, evening) or its reason (a reminder is due, the person has been away), each is made at most once for its day (`key` is unique),
nothing but a reminder is made in the quiet hours, and no more than DAILY_CAP are made in a day. `DIYA_PROACTIVE=0` turns it all off.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import diya_events
import diya_time
from diya_memory import printable

DAILY_CAP = 6  # messages a day other than a reminder's
MORNING_WINDOW = timedelta(hours=4)  # from its time: a computer that was off at 08:30 does not say "good morning" at 14:00
EVENING_WINDOW = timedelta(hours=3)
AWAY_AFTER = timedelta(days=2)  # nothing said by the person for this long, and she says hello
HELLO_EVERY = timedelta(days=3)  # ... and not more often than this
REMINDER_MAX_AGE = timedelta(hours=24)
MAX_LINES = 6  # items listed in one message
TEXT_CHARS = 120  # of one item
GREETINGS = ("Good morning.", "Morning! Here is your day.", "Good morning, here is what is on today.", "Hi, good morning.")


def _iso(local):
    return diya_time.iso_of_local(local)


def _clock(item_ts):
    return diya_time.local_from_iso(item_ts).strftime("%H:%M")


def _item_lines(brief, only_open=False):
    """The bullet lines for what is on the day: reminders (with their times) then tasks. `only_open` keeps just what is already due or overdue, for the evening."""
    lines = []
    reminders = brief["due_now"] if only_open else brief["due_now"] + brief["later_today"]
    for reminder in reminders:
        text = printable(reminder["content"], TEXT_CHARS)
        lines.append(f"- {_clock(reminder['due'])} {text}" if reminder["due"] else f"- {text}")
    tasks = brief["tasks_overdue"] if only_open else brief["tasks_overdue"] + brief["tasks_today"]
    for task in tasks:
        lines.append(f"- task: {printable(task['content'], TEXT_CHARS)}{' (overdue)' if task['overdue'] else ''}")
    return lines


def _listed(lines):
    shown = lines[:MAX_LINES]
    if len(lines) > MAX_LINES:
        shown.append(f"- and {len(lines) - MAX_LINES} more")
    return "\n".join(shown)


def morning_text(brief, today):
    greeting = GREETINGS[today.toordinal() % len(GREETINGS)]
    lines = _item_lines(brief)
    if not lines:
        return f"{greeting} Nothing is on your list today. Tell me if you want me to remind you of anything."
    return f"{greeting} {brief['headline']}\n{_listed(lines)}"


def evening_text(brief):
    lines = _item_lines(brief, only_open=True)
    if not lines:
        return None  # nothing is open: nothing to say, and she does not say it anyway
    noun = "thing from today is" if len(lines) == 1 else "things from today are"
    return f"Evening check-in: {len(lines)} {noun} still open.\n{_listed(lines)}\nTick off what is done on the Reminders and Tasks pages, or tell me what to move."


def away_text(days):
    return f"It has been {days} days since we talked. Anything you want me to keep track of, or remind you about?"


class Proactive:
    """The `proactive_messages` table and the rules above. `quiet` is what diya_time.parse_quiet gives; `morning` and `evening` are (hour, minute) or None."""

    def __init__(self, store, *, morning=(8, 30), evening=(19, 0), quiet=(22, 7)):
        self.store, self.morning, self.evening, self.quiet = store, morning, evening, quiet

    # ---- the table ----
    def _rows(self, where="", args=()):
        conn = self.store.connect()
        try:
            rows = conn.execute("SELECT id, kind, key, thread_id, message_id, text, created_at, seen_at, toasted_at FROM proactive_messages " + where, args).fetchall()
        finally:
            conn.close()
        return [dict(zip(("id", "kind", "key", "thread_id", "message_id", "text", "created_at", "seen_at", "toasted_at"), row)) for row in rows]

    def _known(self, key):
        return bool(self._rows("WHERE key = ?", (key,)))

    def _thread(self):
        """The chat these messages go in: the one the last of them went in, or a new one called Diya."""
        last = self._rows("ORDER BY id DESC LIMIT 1")
        return last[0]["thread_id"] if last else self.store.create_thread("Diya")

    def _post(self, kind, key, text, now_utc):
        """Say it in the chat and remember that it was said. Returns the row, or None if this key was already said."""
        if self._known(key):
            return None
        thread_id = self._thread()
        message_id = self.store.add_message(thread_id, "assistant", text)
        conn = self.store.connect()
        try:
            conn.execute("INSERT OR IGNORE INTO proactive_messages (kind, key, thread_id, message_id, text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                         (kind, key, thread_id, message_id, text, now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")))
            conn.commit()
        finally:
            conn.close()
        return self._rows("WHERE key = ?", (key,))[0]

    def post(self, kind, key, text, now_local):
        """Say something the person asked for (an automation's answer) in the chat now, whatever the hour: it is not one of the day's own messages, so the quiet hours and the daily cap are not
        applied to it (they are Diya's manners when she speaks on her own; this was asked for). Returns the row, or None if this key was already said."""
        return self._post(kind, key, text, diya_events.utc_of_local(now_local))

    def _made_today(self, now_local):
        since = _iso(datetime.combine(now_local.date(), time.min))
        return sum(1 for row in self._rows("WHERE created_at >= ?", (since,)) if row["kind"] not in ("reminder", "automation"))  # what was asked for does not use up what she says unasked

    # ---- making them ----
    def plan(self, now_local):
        """What would be said now, as (kind, key, text): everything due that has not been said, less what the quiet hours and the day's cap hold back. Says nothing and writes nothing."""
        planned, others = [], self._made_today(now_local)
        for kind, key, text in self._due(now_local):
            if kind != "reminder":
                if diya_time.is_quiet(now_local, self.quiet) or others >= DAILY_CAP:
                    continue
                others += 1
            planned.append((kind, key, text))
        return planned

    def make(self, now_local):
        """Say, in the chat, every message that is due now and has not been said. Returns their rows, oldest first."""
        now_utc = diya_events.utc_of_local(now_local)
        rows = [self._post(kind, key, text, now_utc) for kind, key, text in self.plan(now_local)]
        return [row for row in rows if row]

    def _due(self, now_local):
        today = now_local.date()
        oldest = _iso(now_local - REMINDER_MAX_AGE)
        for reminder in self.store.due_reminders(_iso(now_local)):
            if reminder["due_ts"] >= oldest and not self._known(f"reminder:{reminder['id']}"):
                yield "reminder", f"reminder:{reminder['id']}", f"Reminder: {printable(reminder['content'], 200)}"
        for kind, at, window in (("morning", self.morning, MORNING_WINDOW), ("evening", self.evening, EVENING_WINDOW)):
            if at is None or self._known(f"{kind}:{today.isoformat()}"):
                continue
            start = datetime.combine(today, time(at[0], at[1]))
            if not start <= now_local < start + window:
                continue
            brief = diya_events.day_brief(self.store, now_local)
            text = morning_text(brief, today) if kind == "morning" else evening_text(brief)
            if text:
                yield kind, f"{kind}:{today.isoformat()}", text
        away = self._away_days(now_local)
        if away is not None and not self._known(f"away:{today.isoformat()}"):
            yield "away", f"away:{today.isoformat()}", away_text(away)

    def _away_days(self, now_local):
        """How many whole days since the person last wrote, if it is at least AWAY_AFTER and she has not said hello in HELLO_EVERY; None otherwise (and None for a person who has never written)."""
        conn = self.store.connect()
        try:
            last = conn.execute("SELECT MAX(created_at) FROM messages WHERE role = 'user'").fetchone()[0]
        finally:
            conn.close()
        if not last:
            return None
        written = datetime.fromisoformat(last).astimezone().replace(tzinfo=None)
        if now_local - written < AWAY_AFTER:
            return None
        said = self._rows("WHERE kind = 'away' ORDER BY id DESC LIMIT 1")
        if said and now_local - diya_time.local_from_iso(said[0]["created_at"]) < HELLO_EVERY:
            return None
        return (now_local - written).days

    # ---- reading and answering them ----
    def unseen(self, limit=5):
        """What has been said and not yet looked at, newest first."""
        return self._rows("WHERE seen_at IS NULL ORDER BY id DESC LIMIT ?", (limit,))

    def mark_seen(self, ids, now_utc):
        conn = self.store.connect()
        try:
            for message in ids:
                conn.execute("UPDATE proactive_messages SET seen_at = ? WHERE id = ? AND seen_at IS NULL", (now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), message))
            conn.commit()
        finally:
            conn.close()

    def to_toast(self):
        """What has not yet been put on the desktop: everything but a reminder (its own notification is the toast about the reminder itself) and what was seen already."""
        return self._rows("WHERE toasted_at IS NULL AND seen_at IS NULL AND kind != 'reminder' ORDER BY id")

    def mark_toasted(self, ids, now_utc):
        conn = self.store.connect()
        try:
            for message in ids:
                conn.execute("UPDATE proactive_messages SET toasted_at = ? WHERE id = ? AND toasted_at IS NULL", (now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), message))
            conn.commit()
        finally:
            conn.close()
