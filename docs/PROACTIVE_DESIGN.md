# Diya writes first (proactive messages): what it does and what it does not

> **Status (2026-10-11):** built (`diya_proactive.py`, `diya_proactive_api.py`, the notifier's pass, cards at the top of the chat). The owner said Diya did not feel proactive: she only ever answered, and
> a reminder was a notification with nothing behind it. This makes her start the conversation.

## What happens

The scheduled notifier (`diya_notify.py`, every five minutes, the task the owner already has) now also asks `diya_proactive` what Diya should say on her own. Whatever is due is written **into the chat
itself**, in one chat called "Diya", so the message is there when the app is opened, and then put on the desktop (a notification, or a Web Push when that is switched on).

| Message | When | What it says |
|---|---|---|
| **Good morning** | from 08:30 for four hours, once a day (`DIYA_PROACTIVE_MORNING`) | the day: the reminders and tasks on it, with times. A day with nothing on it still gets a short hello that says so. The greeting changes from day to day. |
| **Evening check-in** | from 19:00 for three hours, once a day, **only if something is still open** (`DIYA_PROACTIVE_EVENING`) | what came due today and is not ticked off, and where to tick it off |
| **A reminder** | when it comes due (not when it is a day old) | "Reminder: take the pills", in the chat, as well as the notification the reminder already had; also at night |
| **Hello after a quiet spell** | after two days with nothing from the person, at most once in three days | "It has been 3 days since we talked. Anything you want me to keep track of?" |

On the chat page they appear as cards at the top ("Reply" opens that chat and the conversation goes on from her message; "Dismiss" hides it). The page looks again once a minute while it is open.

## What keeps it from nagging

Each message has its own time or reason and is written at most once for its day (a unique key in the table). Nothing but a reminder is written in the quiet hours (22:00 to 07:00, `DIYA_PROACTIVE_QUIET`), and
no more than six of the others a day. `DIYA_PROACTIVE=0` turns all of it off. A person who has never written gets no "hello after a quiet spell".

## Why it is built in code and not by the model

Every word is made from the owner's own reminders and tasks (`diya_brief`), by plain code. A model would sound warmer and would also invent: a four-billion-parameter model asked for a friendly
greeting wrote about roses, coffee and rain that nobody had told it about. A morning message made by code costs no CPU, needs the model to be neither loaded nor running, and cannot say
something false. The price is that these messages are plain. What a model can usefully do (rephrase, suggest a plan for the day) is a later step, behind a switch, and has to be measured first.

## What it does not do

It does not decide what matters by itself, does not read the person's other messages or their memory, does not message anyone but the person, and does not need the model. It cannot act: it
writes. A reply to it is an ordinary chat message, answered by the usual agent, which is shown what Diya wrote first.

## What was found while building it

- A chat whose first message is Diya's own was being cut at the front: the history trimmer always dropped a leading message that was not the person's, so a reply to her would have reached the model with
  no sign of what it replied to. It now drops that only when something was really cut off the front.
- The notifier is a scheduled task that runs the live files, so this starts working on the next five-minute pass after the code is in place; the first morning message is tomorrow at 08:30, the first
  evening one tonight if anything is open.

## Verified, and not

39 tests (every kind, its window to the minute, once a day, the quiet hours, the cap, the thread, seeing and dismissing, the routes, the notifier's pass including a desktop that will not show it, and
the settings). Shown in a real browser against a throwaway database. Not tried over a real week: whether six a day is the right cap, and whether the evening check-in nags, are the owner's call;
the times and the quiet hours are settings, and `DIYA_PROACTIVE=0` is the off switch.
