# Proactivity, first slice: reminders that fire -- design spec

> **Status (2026-09-25):** designed, nothing built. This is the local, no-connector part of the roadmap's
> "durable workflows" stage (Later stages, 4): the part that needs nothing from anyone else's account. It
> follows the pattern of `docs/STAGE1_DESIGN.md` and `docs/STAGE2_DESIGN.md`: decisions with a
> recommendation, units that land one at a time, and a list of what needs the owner's yes.

## 1. What is true today

Diya is not proactive. It answers when it is asked. Checked in the code, not remembered:

- **One thing runs on a schedule:** Dreaming (`dreaming.py`), through Task Scheduler with `pythonw.exe`, every
  30 minutes. It reads the database and writes a queue. It never tells the person anything.
- **Reminders exist and do nothing.** The table is `reminders(id, content, due_at TEXT, created_at, done)`
  (`diya_db.py:32`). `due_at` is whatever words the model passed: the tool schema asks for "plain words (e.g.
  'Friday 5pm')" (`diya.py:263`). Nothing parses those words, nothing compares them with a clock, and nothing
  shows a reminder except the `list_reminders` tool when the person asks for the list. There is no API route or
  page for reminders; `Store.complete_reminder` exists and nothing calls it.
- **The model is never told the time.** `diya.py` has no notion of the current date. "Friday 5pm" cannot become
  a moment, even in principle, from the model's side.
- **The model sometimes saves reminders nobody asked for** (`ROADMAP.md`, Later stages 1: the 3B model calls
  `add_reminder` on plain arithmetic in roughly 40-50% of past runs; the fact-share guard in `diya_intent.py`
  removed the worst of it, for one kind of message only). A reminder that sits in a table is harmless; a
  reminder that *fires* is not, so this stops being cosmetic the moment reminders become active.
- **The notes watcher** (`milestone4_watcher.py`) is a Phase 1 script; the assistant does not read its output.

## 2. What "proactive" should mean here

Ranked by what it can do to the person, lowest first. This document covers levels 1 to 3 and nothing beyond.

| Level | What Diya does | Side effects | In this document |
|---|---|---|---|
| 0 | Answers when asked | none | today |
| 1 | Shows what is due when the person opens the app | none: read-only, on this machine | yes (P1-P3) |
| 2 | Tells the person outside the app (a desktop notification) when something is due | a notification on this machine | yes (P4), off until switched on |
| 3 | Prepares something on a schedule for the person to read (a morning brief) | text written locally, unsent | named, not designed: see D8 |
| 4 | Acts for the person (sends, buys, posts, books) | outside the machine | no: needs connectors and approval gates, the rest of Later stage 3 and 4 |

Nothing in levels 1 to 3 sends data off this machine.

## 3. Decisions

### D1. Where a real due time lives

**Recommendation: a new column `due_ts` (an ISO 8601 UTC instant, or null) beside the existing free-text
`due_at`, in migration 3**, plus `notified_at` (null until level 2 has told the person). Existing rows keep
their words and never become "due", because nothing can say when "Friday 5pm" was meant; they show as "no time
set". Reinterpreting `due_at` in place was rejected: it would silently give old junk rows a meaning.

### D2. Who turns "Friday 5pm" into a moment

**Recommendation: code, not the model.** A small deterministic parser (`diya_time.py`) given the current local
time: `today`, `tomorrow`, weekday names (the next one, never today's past), `in 2 hours`, `at 5pm`, `at 17:30`,
an explicit date. It refuses what it cannot read. The tool then answers the model with what was understood
("Saved for Friday 26 Sep, 17:00") or what was not ("I could not tell when 'soonish' is; ask for a day and
a time"), so the model can relay it. Options rejected:

- *Tell the model the current date and ask it for ISO 8601.* A 3B model is unreliable at date arithmetic, and a
  system line about the time changes every ordinary answer (the fact-share prompt, sent on every turn, halved
  answer length: `diya.py`, `FACT_SHARE_PROMPT`). It would need its own measurement first.
- *Both.* More surface, same unreliable half.

The parser is measured on a written-down labelled set of fictional phrases (both what it must read and what it
must refuse), as the checks in Stage 2 were, and its limits are stated with the numbers.

### D3. Time zone and daylight saving

Resolve in the machine's local time with the operating system's own rules (a naive local datetime converted with
`astimezone()`), store the UTC instant, keep the person's original words. No new dependency: `zoneinfo` needs the
`tzdata` package on Windows. Limit: if the machine's zone changes, an instant does not move with it.

### D4. Where "due" shows up (level 1)

**Recommendation:** `GET /api/reminders` (pending ones, each marked `overdue`, `upcoming` or `no time`) and
`POST /api/reminders/{id}/done`; a Reminders page in the UI in the style of the Memory page; and a count in the
chat header ("2 due") that re-checks once a minute while the page is open. No push: a browser tab that is closed
learns nothing, which is what level 2 is for. Same token, same same-origin proxy, same `describe*Failure` wording
as everything since Stage 1.

### D5. Telling the person outside the app (level 2)

**Recommendation: a second scheduled job, `diya_notify.py`, every 5 minutes, that shows a Windows toast for
each newly due reminder and records `notified_at`, so each fires once.** Same pattern as Dreaming (Task
Scheduler, `pythonw.exe`, its own log), same caveat (it runs the live working-tree files). The toast uses
PowerShell's built-in Windows.UI.Notifications; nothing new is installed. **It is not registered by the code:**
creating a scheduled task on the owner's machine is the owner's step, documented, like Dreaming's. The text
shown is the person's own reminder on their own machine, so it is shown by default; `DIYA_NOTIFY_SHOW_TEXT=0`
shows "A reminder is due" instead, for a screen other people can see.

### D6. A reminder that came due while the machine was off

It is shown as overdue at the next open, and told once at the next notifier run. Never dropped, never repeated.
(This is also the honest reason a laptop is a poor home for proactivity: nothing fires while it is asleep. An
always-on machine, the Mac mini in `CLAUDE.md`, is what makes level 2 reliable, not code.)

### D7. Not in this slice

Snooze, and recurrence ("every Monday"). Recurrence is where a reminder becomes a workflow: it needs a definition
that outlives one firing, an edit surface, and a way to stop it. That belongs to the durable-workflow work, with
approval gates and an action trail, and is better designed once levels 1 and 2 have been lived with.

### D8. The morning brief (level 3)

Deferred. It has the model write text on a schedule, so it wants the same review-before-trust treatment facts
got (staged, read by the person, never sent), and a measurement of whether a 3B model's summary of the person's
own notes and reminders is any good. Recommendation: do not design it until levels 1 and 2 exist.

### D9. The misfire problem, before anything fires

**Recommendation: two guards, both in code, both tested.**

1. *The request must look like a request.* `add_reminder` is honoured only if the person's latest message asks
   for one ("remind me", "reminder", "don't let me forget", "remember to", "make a note", and a small labelled
   list of others). If it does not, the tool answers the model "not saved: you were not asked for a reminder", and
   nothing is written. Measured on labelled fictional messages, with the known misses stated (a request phrased in
   an unusual way is refused, which is the safe direction: the person can say it again).
2. *Every saved reminder is visible and undoable* where it happens: the chat's tool chip says what was saved and
   for when, and the Reminders page can mark it done. A wrong reminder is then a click, not a mystery.

Guard 1 changes an existing tool's behaviour, which is why it is a decision and not a detail.

## 4. Units

| Unit | What | Files | Changes for the live system |
|---|---|---|---|
| P1 | **Time reading.** `diya_time.py`: pure, no database, labelled cases, measured | new `diya_time.py`, `tests/labelled_times.py` | none |
| P2 | **Storage and the tool.** Migration 3 (`due_ts`, `notified_at`); store methods; `add_reminder` parses, refuses what it cannot read, says what was understood; the D9 guard | `diya_db.py`, `diya.py` | additive columns; the scheduled Dreaming will migrate the live `diya.db` within 30 minutes (as migration 2 did): test on a copy first. The API needs a restart |
| P3 | **API and page.** The routes, the proxy routes, the Reminders page, the header count | `diya_reminders_api.py`, `frontend/app/reminders/`, `frontend/lib/*`, `tests/test_token.py` | UI restart |
| P4 | **The notifier.** `diya_notify.py` and its docs; never registered by code | new `diya_notify.py`, `docs/` | none until the owner registers the task |

Each is its own commit, tested and mutation-checked, with a real-browser check for P3 and a real toast for P4.

## 5. Limits, and what needs a yes

**Limits, said plainly.**

- The parser reads a small grammar. It will refuse things a person finds obvious ("the weekend", "after lunch"), by
  design; a refusal the model relays is better than a wrong time that fires.
- A 3B model may not call `add_reminder` at all for a request that is phrased loosely, and may pass a time in words
  the parser refuses. Both are visible to the person, and neither is silent.
- Nothing fires while the machine is off or asleep (D6).
- This is not a calendar and imports from none.

**Needs the owner's yes.** D5 (whether level 2 should exist at all, and registering the scheduled task), D7 (that
snooze and recurrence wait), D8 (that the brief waits), and D9 guard 1 (a change to an existing tool). The
recommendations above are being followed as written, on the owner's instruction to continue through the roadmap;
D5's registration is the one step this work will not take on their behalf.
