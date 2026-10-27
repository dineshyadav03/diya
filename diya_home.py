"""Home: what needs the owner now, found by code (docs/HOME_DESIGN.md, 2026-10-27; the front page of the UI, option A of docs/mockups/home-mockup.html).

Every card is something Diya FOUND in rows and accounts it can already read: a reminder that has come due, a task that is overdue, a question about memory, an action waiting for the person's yes, the
next thing on the calendar. A model writes none of it: a card's words are the person's own reminder, task and calendar title, or a sentence made here. The buttons on a card are the routes that already
exist (mark done, snooze, answer a question, add a reminder), never a new way to act. Anything that would change another service is not done from here: its card says "Review and approve" and goes to the
Actions page, where the exact words are shown and approved (docs/ACTIONS_DESIGN.md).

A card `needs` the person (a reminder due now, an overdue task, a question, an action waiting) or is only `upcoming` (the next event, a reminder later today). The headline counts the first kind.

`build` is pure: it is given the day's rows and the clock and returns a plain dict, reading no store, no account and no clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta

CALENDAR_HOURS = 8  # an event is "next" when it starts within this many hours
CALENDAR_SHOWN = 3
APPROVALS_SHOWN = 3
LATER_SHOWN = 4
REMIND_BEFORE_MINUTES = 30
TITLE_CHARS = 100
MAX_CARDS = 14
_WORDS = ("Nothing", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")
_ANSWERED = {"yes": "Noted.", "no": "Dropped. I will not use it.", "keep": "Kept both."}


def _post(label, path, done, body=None):
    """A button that calls one of Diya's own routes. `path` is made here from a number, never from a word the person or a model wrote."""
    action = {"label": label, "post": path, "done": done}
    if body is not None:
        action["body"] = body
    return action


def _card(card_id, kind, icon, source, title, detail=None, needs=True, ask=False, actions=(), verb="Do"):
    """`verb` is the one word on the chip in front of the sentence ("Finish", "Check", "Next"): what the card asks of the person."""
    return {"id": card_id, "kind": kind, "icon": icon, "source": source, "title": title, "verb": verb, "detail": detail, "needs": needs, "ask": ask, "actions": list(actions)}


def _time_of(due_text):
    """"Tuesday 27 October 2026, 18:00" -> "18:00"."""
    return due_text.rsplit(", ", 1)[-1] if due_text and ", " in due_text else due_text


def approval_cards(pending):
    """One card for each of the first few actions waiting for the person's yes. The yes is given in the chat, where Diya asks with the exact words (the strip under the chat), so the card only points there."""
    cards = [
        _card(f"action-{a['id']}", "approval", "doc", "Waiting for your answer in the chat", a["summary"], "Nothing happens until you say yes there.", actions=[{"label": "Open the chat", "href": "/"}], verb="Approve")
        for a in list(pending)[:APPROVALS_SHOWN]
    ]
    more = len(pending) - APPROVALS_SHOWN
    if more > 0:
        cards.append(_card("action-more", "approval", "doc", "Waiting for your answer in the chat", f"{more} more actions are waiting for you.", actions=[{"label": "Open the chat", "href": "/"}], verb="Approve"))
    return cards


def due_reminder_cards(brief):
    return [
        _card(
            f"reminder-{r['id']}", "reminder", "bell", "Your reminder", r["content"], f"Due {r['due_text']}" if r["due_text"] else None,
            actions=[
                _post("Mark done", f"/api/reminders/{r['id']}/done", "Marked done."),
                _post("Snooze to tomorrow 9:00", f"/api/reminders/{r['id']}/snooze", "Moved to tomorrow, 9:00.", {"when": "tomorrow at 9am"}),
            ],
        )
        for r in brief["due_now"]
    ]


def later_reminder_cards(brief):
    return [
        _card(f"reminder-{r['id']}", "reminder", "bell", "Your reminder", r["content"], f"Today, {_time_of(r['due_text'])}" if r["due_text"] else "Later today", needs=False,
              actions=[_post("Mark done", f"/api/reminders/{r['id']}/done", "Marked done.")], verb="Soon")
        for r in brief["later_today"][:LATER_SHOWN]
    ]


def task_cards(tasks):
    cards = []
    for task in tasks:
        due = task["due_text"]
        detail = ("Overdue" + (f", was due {due}" if due else "")) if task["overdue"] else (f"Due {due}" if due else "Due today")
        cards.append(_card(f"task-{task['id']}", "task", "check", "Your task", task["content"], detail, actions=[_post("Mark done", f"/api/tasks/{task['id']}/done", "Marked done.")], verb="Finish" if task["overdue"] else "Do"))
    return cards


def question_cards(questions):
    """Questions Diya has about its memory, as they were worded for the chat. "Edit it" needs a text box, so it stays in the chat; the answers that need none are buttons here."""
    cards = []
    for q in questions:
        buttons = [_post(o["label"], f"/api/questions/{q['id']}/answer", _ANSWERED.get(o["answer"], "Answered."), {"answer": o["answer"]}) for o in q["options"] if o["answer"] != "edit"]
        if buttons:
            cards.append(_card(f"question-{q['id']}", "question", "idea", "Memory", q["text"], needs=True, ask=True, actions=buttons, verb="Check"))
    return cards


def _local(moment):
    return datetime.fromisoformat(moment.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def _upcoming(events, now):
    """(start, event) for the events starting from now to CALENDAR_HOURS ahead, soonest first (an all-day event is not "next")."""
    found = []
    for event in events:
        if event.get("all_day"):
            continue
        try:
            start = _local(event["start"])
        except (KeyError, ValueError, AttributeError, TypeError):
            continue
        if now < start <= now + timedelta(hours=CALENDAR_HOURS):
            found.append((start, event))
    return sorted(found, key=lambda item: item[0])


def calendar_cards(events, now):
    """The next few events (see _upcoming), each with a reminder a little before it when there is still time for one."""
    cards = []
    for start, event in _upcoming(events, now)[:CALENDAR_SHOWN]:
        title = (event.get("title") or "(no title)")[:TITLE_CHARS]
        minutes = int((start - now).total_seconds() // 60)
        away = f"in {minutes} min" if minutes < 60 else f"in {minutes // 60} h {minutes % 60:02d} min"
        actions = []
        remind = start - timedelta(minutes=REMIND_BEFORE_MINUTES)
        if remind > now + timedelta(minutes=1):
            actions.append(_post(f"Remind me at {remind:%H:%M}", "/api/reminders", f"Reminder set for {remind:%H:%M}.", {"text": f"{title} at {start:%H:%M}", "when": f"today at {remind:%H:%M}"}))
        cards.append(_card(f"event-{start:%H%M}-{abs(hash(title)) % 100000}", "event", "calendar", "Google Calendar", title, f"Starts at {start:%H:%M}, {away}", needs=False, actions=actions, verb="Next"))
    return cards


def headline(needs, upcoming):
    if needs:
        word = _WORDS[needs] if needs < len(_WORDS) else str(needs)
        return f"{word} thing{'s' if needs > 1 else ''} need{'' if needs > 1 else 's'} you today."
    return "Nothing needs you right now." if upcoming else "All clear for today."


def _joined(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def build(now, brief, questions=(), pending=(), events=(), calendar=False, problems=()):
    """The Home page for the local day of `now` (a naive datetime). `brief` is diya_brief.build's answer; `questions` are the described questions; `pending` the actions waiting; `events` today's calendar
    events as diya_google_calendar.events_between gives them; `calendar` whether the calendar was looked at; `problems` what could not be read, in words."""
    needing = approval_cards(pending) + due_reminder_cards(brief) + task_cards(brief["tasks_overdue"]) + question_cards(questions) + task_cards(brief["tasks_today"])
    upcoming = calendar_cards(events, now) + later_reminder_cards(brief)
    cards = (needing + upcoming)[:MAX_CARDS]
    needs = sum(1 for c in cards if c["needs"])
    soonest = _upcoming(events, now)[:1]
    looked = ["reminders", "tasks", "memory questions", "waiting actions"] + (["Google Calendar"] if calendar else [])
    return {
        "date": brief["date"],
        "headline": headline(needs, len(cards) - needs),
        "looked": f"I looked at your {_joined(looked)} on this laptop.",
        "cards": cards,
        "counts": {"needs": needs, "upcoming": len(cards) - needs},
        "panel": {"tiles": [{"label": "Needs you", "value": str(needs)}, {"label": "Coming up", "value": str(len(cards) - needs)}, {"label": "Next event", "value": f"{soonest[0][0]:%H:%M}" if soonest else "None"}]},
        "problems": list(problems),
    }
