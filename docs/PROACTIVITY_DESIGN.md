# Proactivity, first slice: reminders that fire -- design spec

> **Status (2026-09-26):** designed and built: **P1 (the time reader), P2 (real due times, the tool, two guards), P3 (the API
> and page) and P4 (the notifier)**. Not done: registering the notifier as a scheduled task (the owner's step, see
> `docs/reminders.md`), snooze, recurrence, and the morning brief. This is the local, no-connector part of the roadmap's
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

*As built (P1):* `diya_time.py`, pure code, no database, no clock of its own (`now` is a parameter). It reads
today, tonight, tomorrow, the day after tomorrow, weekday names (with the usual abbreviations), "in N minutes /
hours / days / weeks" (also "in an hour", "in half an hour"), dates with a month name or as 2026-09-26, and a time
as 5pm, 5:30pm, 17:30, noon, or morning / afternoon / evening (09:00, 15:00, 18:00), with "in the morning" too.
It refuses what it cannot account for word by word, so "Friday 5pm; ignore all previous instructions" is refused
whole, not read as Friday 5pm. Where it differs from what this document first implied:

- **A day with no time is read, with an assumption reported**, not refused: "tomorrow" is 09:00 and `assumed`
  says "no time was given, so 09:00" for the caller to show. A time with no day is the next time it is that
  time (today, or tomorrow if it has passed), and says so. A date with no year that has passed this year is next
  year, and says so. A weekday that has passed this week is next week, and says so.
- **What it refuses on purpose, because two people mean two things:** "next Friday", a bare "at 5" (morning or
  evening), "3/4" (March 4th or April 3rd), and midnight (which side of the date). "Exactly now" has passed.
- An explicit time wins over a part of the day ("morning 5pm" is 17:00); it does not refuse the contradiction.

Measured on hand-written fictional cases (`tests/labelled_times.py`, written by the author of the parser, so they
show it does what it says and not how it does on real phrases): all 79 phrases it should read come out as the
moment they should, all 65 it should refuse are refused with the right reason, and the 13 phrases a person would
understand and it cannot ("next week", "the weekend", "after lunch", "in five minutes", "half past five", "in a
couple of hours", ...) are listed and asserted to be refused, so that gap is a number, not a surprise. A seeded fuzz
run (4,000 random phrases from its own vocabulary, 3,000 random character strings, several absurd numbers) only
ever gave a future moment within five years or a refusal. 44 of 44 mutations were caught (six survived the first
run and were fixed: boundary cases at "exactly now", seconds checked only to the minute, an error test that
passed for the wrong reason, and a year-shape case). **Not verified here:** daylight saving on a real zone. This
machine's zone has none, so the conversion is tested with an injected converter that has it; the default path
(`astimezone` on the naive wall-clock time) is the operating system's.

### D4. Where "due" shows up (level 1)

**Recommendation:** `GET /api/reminders` (pending ones, each marked `overdue`, `upcoming` or `no time`) and
`POST /api/reminders/{id}/done`; a Reminders page in the UI in the style of the Memory page; and a count in the
chat header ("2 due") that re-checks once a minute while the page is open. No push: a browser tab that is closed
learns nothing, which is what level 2 is for. Same token, same same-origin proxy, same `describe*Failure` wording
as everything since Stage 1.

*As built (P3):* `diya_reminders_api.py` registers `GET /api/reminders` (the pending reminders, each `due`, `upcoming`
or `no_time`, judged against the agent's own clock at the moment of the request, with the person's words, the time in
words, and whether they were told), `POST /api/reminders` (`{"text", "when"}`: typed by the person, the time read by the
same reader as the model's, a time it cannot read a 422 with the reason, nothing saved) and `POST /api/reminders/{id}/done`
(404 unknown, 409 already done). Everything sent back goes through `printable()`. The UI gets two same-origin proxy
route files and one helper (the id must be a whole number), a Reminders page in the Memory page's style with an add form
and a Done button, links from History, Memory and the chat header, and a count of what is due in the chat header (asked once a
minute; if it cannot be asked, nothing is shown rather than a 0). The page looks again once a minute while it is open.
That refresh keeps its own note ("Couldn't refresh just now, so this may be out of date"), apart from the line that
reports what the person just did: the first real-browser run showed a background failure showing up as the result of
an action, and a successful refresh able to wipe an action's error, so they no longer share a line. 30 of 31 mutations of
the API and its proxy caught; the survivor (`printable()` on the refusal reason) is equivalent, since the reason already
quotes with `repr()`, and has an invariant test anyway.

### D5. Telling the person outside the app (level 2)

**Recommendation: a second scheduled job, `diya_notify.py`, every 5 minutes, that shows a Windows toast for
each newly due reminder and records `notified_at`, so each fires once.** Same pattern as Dreaming (Task
Scheduler, `pythonw.exe`, its own log), same caveat (it runs the live working-tree files). The toast uses
PowerShell's built-in Windows.UI.Notifications; nothing new is installed. **It is not registered by the code:**
creating a scheduled task on the owner's machine is the owner's step, documented, like Dreaming's. The text
shown is the person's own reminder on their own machine, so it is shown by default; `DIYA_NOTIFY_SHOW_TEXT=0`
shows "A reminder is due" instead, for a screen other people can see.

*As built (P4):* `diya_notify.py`, standard library only, `python diya_notify.py [--dry-run | --test]`, documented in
`docs/reminders.md` with the PowerShell that registers the scheduled task. **Nothing registers it, and it is not
registered.** One pass over the reminders that have come due and have not been told: for each, a Windows
notification, and only then `notified_at`, so a crash in between can tell one twice and never zero times. A failure
is not recorded and is tried again on the next pass. The reminder's words travel to PowerShell in environment
variables; the script itself is a constant, so a reminder that says `$(...)` or holds a quote is only text (a test
runs a hostile string through and checks it appears nowhere in the command). The words go through `printable()`
and are cut to fit. More than five due at once (a computer that was off) is four notifications and one that stands
for the rest. The log, `notify_log.txt` (git-ignored), holds counts and ids, never a reminder's words. Two settings:
`DIYA_NOTIFY_SHOW_TEXT`, `DIYA_NOTIFY_LOG_PATH`. 27 mutations, all caught (one after correcting a mutation that was
equivalent). Verified for real on this Windows machine: `--test` showed a notification and it reached the Action
Center with the text it was given (read back through `ToastNotificationManager.History`, then cleared). Not verified:
a scheduled run (nothing is scheduled), or a screen with Focus Assist on. Off Windows it says so and exits 2.

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

*As built (P2):* migration 3 adds `due_ts` (the moment, as UTC text like `2026-09-25T11:30:00Z`) and `notified_at`
to `reminders`, with a partial index over pending timed ones. Every reminder saved before it keeps its words, has a
null `due_ts`, and can never be due. (The scheduled Dreaming task runs the working-tree code, so it applied the
migration to the live `diya.db` within the half hour, as with migration 2; checked on a copy first: the six existing
reminders unchanged, integrity `ok`.) `Store` gained `reminders(state)`, `get_reminder`, `due_reminders(now_ts,
unnotified_only)` and `mark_notified` (once, and never for a finished reminder); `add_reminder` returns the id and
refuses a moment that is not UTC text; `complete_reminder` says whether it did anything. The tool,
`Agent.add_reminder`, reads the person's words with `diya_time` against the agent's own clock (a parameter, so tests do
not depend on today), stores the words and the moment, and answers the model with what it understood ("Reminder
saved: call mum, for Friday 25 Sep 2026, 17:00 (no time was given, so 09:00)"). A time it cannot read saves nothing
and says why, so the model can ask. No time at all saves a reminder that says it has none and will not fire. The
tool's schema now asks for the person's own words unchanged and "never guess a time".

The guard is `diya_intent.is_reminder_request`: a short list of the ways people ask ("remind me", "set a reminder",
"don't let me forget", "note to self", ...). While `Agent.ask` is answering, `add_reminder` saves nothing unless the
latest user message matches, and says so to the model. The state is per thread, cleared when the turn ends (also on
an error), and a direct call outside a turn is not guarded. On hand-written fictional messages all 30 requests are
allowed and all 31 non-requests are refused (including "What reminders do I have?" and "Send a reminder email to the
team"); the failures are kept on purpose: 4 non-requests it still allows ("How do I set a reminder on my phone?") and 6
real requests it refuses ("Ping me at 5", "Wake me up at 7"). Those cases were written alongside the patterns.

*Measured with the real model, and what it added.* `qwen2.5:3b` at Ollama's default sampling, on invented messages
(12 requests with times, 19 that ask for nothing), 2 to 3 runs each, so the counts are small and noisy:

- **Unasked reminders.** With no guard, the model called `add_reminder` and a reminder was saved in 6 of 38 runs on
  messages that ask for none ("What's 9 times 7?", "What is 15% of 80?", "I need to buy milk tomorrow", "Tomorrow I
  have a meeting at 3pm with Priya"). With the guard: 0 of 57. The model still tried in 9 of the 57; the tool
  refused.
- **Wrong times.** With the time read in code but the model's words trusted, 4 of 24 request runs saved a time the
  person never said: the model dropped "3 October" and passed "2pm" (a reminder for today), turned "morning" into
  "8am", replaced "after lunch" with "in 2 hours", and rewrote "at 5" as "5pm". So the words are now checked against the
  person's own message (`diya_time.disagreement`): the model may not add a day or time they did not say, and may not
  leave out the one they did ("morning" and "9am" count as the same, that being this reader's own default). With
  that check: 0 wrong times in 36 request runs, 22 of the 27 runs that should save did so at the right time, all 9
  that should be refused ("next Friday", "at 5", "after lunch") were, and the other 4 were refused and the model
  asked again. A refusal is the safe direction, and the model's reply to one asked the person to clarify without
  claiming it had saved anything.
- **What the check cannot see.** It looks for days and times it can read. A message with two times ("my 5pm
  meeting at 3pm") gives it nothing to hold the model to, so a wrong pick between them passes; and a date that is
  part of what is being reminded of ("send the invoice for 3 October on Friday at 4pm") makes it refuse a good
  reminder. Both are in `tests/labelled_times.py`.
- **The model does not always relay what the tool says.** Once it told the person a reminder with no time "will go off"
  though the tool had said it would not, so that answer is now blunt ("It has NO time, so it will not fire: tell the
  user that, and ask when they want it."). Not re-measured.

46 mutations of the store, the tool and the guard were run: 45 caught, and the one that survived (the 300-character
limit) was pinned by a test; 21 more on the words check, 20 caught first time and the last fixed. **Deviations:** the
guard changes an existing tool's behaviour, as D9 said it would; the words check is not in the design above (the
measurement showed it was needed); existing tests that pinned the old return text were updated.

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
