"""One list of what is worth interrupting the person for, and who has been told (docs/PUSH_DESIGN.md, sections 2 and 3, unit P3).

Two channels say "something is waiting": the Windows toast (diya_notify.py) and the Web Push (diya_push.py). They must not disagree about what is worth saying or
how it is worded, so the words and the rules are here and both read them:

    reminder_words / more_words / question_words / action_words / day_words   the exact words of each kind, with the text hidden or shown
    split_flood                      more than five due at once: the first four one by one, then one that stands for the rest
    pending                          everything worth telling on one channel now, given what that channel has already been told

An Event is one message: a title, a body and the delivery keys it stands for ("reminder:7"; a "3 more" message stands for three). Nothing here sends anything. A
channel sends the events and, only after the message was ACCEPTED, records their keys with Deliveries.record, so a failed send is found again on the next pass.

No word here is written by a model. A reminder's own text can be shown (it is the person's), and goes through diya_memory.printable() as the toast always did; a
question, an action and the day are never described, only counted, because a notification can be read by anyone passing the screen.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import diya_time
from diya_memory import printable

MAX_NOTIFICATIONS = 5  # in one pass: the first four one by one, then one that stands for the rest
TITLE_CHARS, BODY_CHARS = 60, 200
REMINDER_MAX_AGE = timedelta(hours=24)  # a push is for NOW: a reminder that came due longer ago than this is on the Reminders page, and is not pushed
DAY_WINDOW = timedelta(hours=3)  # "your day" is sent from the chosen time and for this long after it; a computer that was off at 08:00 does not say "your day" at 14:00


@dataclasses.dataclass(frozen=True)
class Event:
    kind: str
    keys: tuple  # the delivery keys this message stands for
    title: str
    body: str


def utc_of_local(local):
    """A naive local datetime as an aware UTC one, by the operating system's rules for that date."""
    return datetime.strptime(diya_time.iso_of_local(local), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---- the words -------------------------------------------------------------------------------------------------------------------

def reminder_words(reminder, show_text):
    """(title, body) for one reminder: its time and its own words, or "A reminder is due" when the text is hidden."""
    if not show_text:
        return "Diya", "A reminder is due"
    when = reminder["due_ts"] and diya_time.describe_local(diya_time.local_from_iso(reminder["due_ts"]))
    return printable(f"Diya: {when}" if when else "Diya reminder", TITLE_CHARS), printable(reminder["content"], BODY_CHARS)


def more_words(count):
    return "Diya", f"{count} more reminders are due. Open the Reminders page to see them."


def question_words(count):
    return "Diya", "Diya has a question for you." if count == 1 else f"Diya has {count} questions for you."


def action_words(count):
    return "Diya", "An action is waiting for your approval." if count == 1 else f"{count} actions are waiting for your approval."


def day_words(headline, show_text):
    return "Diya", (f"Your day is ready. {headline}" if show_text and headline else "Your day is ready.")


def split_flood(items):
    """(the ones told one by one, the ones a single message stands for): at most MAX_NOTIFICATIONS messages in one pass."""
    if len(items) <= MAX_NOTIFICATIONS:
        return list(items), []
    return list(items[: MAX_NOTIFICATIONS - 1]), list(items[MAX_NOTIFICATIONS - 1:])


def reminder_events(due, show_text):
    """The messages for reminders that are due and not yet told: one each, then one that stands for the rest of a flood."""
    singles, rest = split_flood(due)
    events = []
    for reminder in singles:
        title, body = reminder_words(reminder, show_text)
        events.append(Event("reminder", (f"reminder:{reminder['id']}",), title, body))
    if rest:
        title, body = more_words(len(rest))
        events.append(Event("reminder", tuple(f"reminder:{reminder['id']}" for reminder in rest), title, body))
    return events


# ---- who has been told what ------------------------------------------------------------------------------------------------------

class Deliveries:
    """The `event_deliveries` table for one channel: a key is recorded once, only after the channel accepted the message that carried it."""

    def __init__(self, store, channel):
        self.store, self.channel = store, channel

    def told(self):
        """The set of keys already told on this channel."""
        conn = self.store.connect()
        try:
            return {row[0] for row in conn.execute("SELECT key FROM event_deliveries WHERE channel = ?", (self.channel,))}
        finally:
            conn.close()

    def record(self, keys, now_utc):
        """Record that the message standing for `keys` was accepted at `now_utc` (an aware datetime). Keys already recorded are left as they were."""
        keys = tuple(keys)
        stamp = now_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = self.store.connect()
        try:
            for key in keys:
                conn.execute("INSERT OR IGNORE INTO event_deliveries (channel, key, batch, sent_at) VALUES (?, ?, ?, ?)", (self.channel, key, keys[0], stamp))
            conn.commit()
        finally:
            conn.close()

    def messages_since(self, since_utc):
        """How many messages (not events: "3 more" is one) were accepted on this channel at or after `since_utc` (an aware datetime)."""
        stamp = since_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = self.store.connect()
        try:
            return conn.execute("SELECT COUNT(DISTINCT batch) FROM event_deliveries WHERE channel = ? AND sent_at >= ?", (self.channel, stamp)).fetchone()[0]
        finally:
            conn.close()


# ---- what is pending -------------------------------------------------------------------------------------------------------------

def _waiting_actions(store, now_local):
    """The ids of actions waiting for the owner whose time has not run out, oldest first. Reads only: closing the expired ones is the actions store's job."""
    stamp = diya_time.iso_of_local(now_local)
    conn = store.connect()
    try:
        return [row[0] for row in conn.execute("SELECT id FROM actions WHERE status = 'pending' AND expires_at > ? ORDER BY id", (stamp,))]
    finally:
        conn.close()


def day_headline(store, now_local):
    """The brief's own one-sentence headline for the local day of `now_local`, or None when nothing is due (there is then no "your day" to send)."""
    import diya_brief
    import diya_schedule
    import diya_tasks

    schedule = diya_schedule.Schedule(store, clock=lambda: now_local)
    reminders = store.reminders("pending")
    series_ids = schedule.series_of([row["id"] for row in reminders])
    brief = diya_brief.build(now_local, reminders, diya_tasks.Tasks(store, clock=lambda: now_local).tasks("open"), schedule.series("active"), series_ids)
    return None if brief["headline"] == "Nothing is due today." else brief["headline"]


def pending(store, now_local, told, *, show_text=False, quiet=None, questions_on=False, day_at=None):
    """Every message worth sending on a channel now, most urgent first, given `told` (the set of keys that channel was already told).

    `now_local` is a naive local datetime. `quiet` is what diya_time.parse_quiet gives (None: never quiet): inside the quiet hours only reminders (which the
    person asked for at a time) are kept. `questions_on` is whether memory raises questions at all (DIYA_AUTO_MEMORY). `day_at` is (hour, minute) or None for no day message.
    Reminders older than REMINDER_MAX_AGE are left out: a push is for now."""
    events = []
    now_ts = diya_time.iso_of_local(now_local)
    oldest = diya_time.iso_of_local(now_local - REMINDER_MAX_AGE)
    due = [r for r in store.due_reminders(now_ts) if r["due_ts"] >= oldest and f"reminder:{r['id']}" not in told]
    events.extend(reminder_events(due, show_text))
    if diya_time.is_quiet(now_local, quiet):
        return events
    if questions_on:
        import diya_questions

        waiting = [q for q in diya_questions.Questions(store, None).visible(now_local) if f"question:{q['id']}" not in told]
        if waiting:
            title, body = question_words(len(waiting))
            events.append(Event("question", tuple(f"question:{q['id']}" for q in waiting), title, body))
    actions = [i for i in _waiting_actions(store, now_local) if f"action:{i}" not in told]
    if actions:
        title, body = action_words(len(actions))
        events.append(Event("action", tuple(f"action:{i}" for i in actions), title, body))
    if day_at is not None:
        start = datetime.combine(now_local.date(), datetime.min.time()).replace(hour=day_at[0], minute=day_at[1])
        key = f"day:{now_local.date().isoformat()}"
        if start <= now_local < start + DAY_WINDOW and key not in told:
            headline = day_headline(store, now_local)
            if headline is not None:
                title, body = day_words(headline, show_text)
                events.append(Event("day", (key,), title, body))
    return events

