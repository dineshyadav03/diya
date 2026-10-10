# Scheduled work: recurrence, snooze, a way to stop, and a day brief -- design spec

> **Status (2026-10-10):** built (units R1-R5) and measured with the real models; nothing pushed. Section 6 says what was built, what
> the model measurement found (and how it changed D7), and the mutation testing. This is the part of the roadmap's "durable
> workflows" stage (Later stages, 4) that `docs/PROACTIVITY_DESIGN.md` D7 and D8 deferred, plus a definition of the empty stage 6
> ("daily-driver experience"). It needs nothing from anyone else's account. Requested by the owner: "in the roadmap there are things
> planned that were not worked on, the later stages too, work on it too." It follows the pattern of the earlier design docs: decisions
> with a recommendation, units that land one at a time, and what needs the owner's yes.

## 1. What is true today, and what the research said

- A reminder fires once. There is no snooze, no "every Monday", and no page that lists everything scheduled
  (`docs/reminders.md`, "What it does not do"). A Windows toast tells the person once per reminder, run by a task the owner
  schedules (`diya_notify.py`; not scheduled yet).
- PROACTIVITY D7 deferred recurrence because it needs "a definition that outlives one firing, an edit surface, and a way to
  stop it". D8 deferred the morning brief because it assumed the model would write text on a schedule, which wants
  review-before-trust and a measurement.
- The wider field (`RESEARCH.md`, entries 16-18): OpenAI retired ChatGPT Pulse (the AI decides what to tell you each
  morning) in June 2026 for "scheduled tasks" (reminders, recurring tasks, topics to track, and a page to pause, edit and
  delete them). OpenClaw's most-used pattern is a morning briefing on a schedule. Users steer; the assistant does not
  decide what to say. That is what this design builds, and nothing more autonomous.

## 2. Decisions

### D1. A series is the definition; an occurrence is an ordinary reminder

A recurring reminder is a **series** (its words, its rule, whether it is paused or ended, when its next occurrence is due).
When an occurrence's time comes, the series produces an ordinary row in `reminders` (with `series_id`), and from then on
everything that exists already applies unchanged: it shows under "Due now", the notifier tells the person once, "Done"
closes it. No reminder code learns what recurrence is. The alternative (moving one row's `due_ts` forward) was rejected: the
reminder that just fired would vanish from the Reminders page the moment it fired.

### D2. The rule language is a closed set, read in code

Read by `diya_repeat.parse_repeat`, never by the model (the lesson of `diya_time`): **every day** ("daily", "every morning" =
09:00, "every evening" = 18:00), **every weekday**, **every <weekday> [and <weekday>...]**, **every month on the 15th**, **every N
days / weeks** ("every other day" = 2). Always at a time of day; with none given it is 09:00 and says so, as for a one-off.
Refused, each with a reason the model can relay: more often than once a day ("every hour"), a count or an end ("for 5 weeks",
"until June": stop it from the Scheduled page instead), "every second Tuesday" and "the last Friday", "every week" with no
day, "every month" with no date, and yearly ("every year on 3 March": not in this slice, see section 5). A day-of-month of 29-31 means the
last day of a shorter month, and says so. Every result is checked by the same word-by-word accounting `parse_when` uses:
a word nothing accounts for refuses the whole thing.

### D3. One occurrence per series per look, and the stale one lapses

Occurrences are made when something looks: the notifier pass, the Reminders and Scheduled listings, and `list_reminders`
(`Schedule.materialize`, one write transaction, so two lookers cannot both make it). If a series is behind (the laptop
slept for a week) it makes ONE occurrence for the latest time that has passed, records the others as `missed` events, and
moves on: a week asleep is one reminder, not seven. If the previous occurrence of the same series is still pending when a
newer one arrives, the old one is closed as **lapsed** (recorded, never silent), so a daily "take the bins out" you
ignored does not pile up into a column of stale ones.

### D4. The edit surface: pause, resume, skip, stop, and snooze

- **Pause / resume** a series: nothing is made while paused; on resume the next occurrence is worked out from now.
- **Skip next**: moves the series one step on without making an occurrence.
- **Stop**: ends the series for good (the one pending occurrence, if any, stays until it is done); a stopped series stays
  in the list, greyed, so it can be seen that it ended. There is no delete (as for tasks, `docs/TASKS_DESIGN.md` D7).
- **Snooze** (any reminder, recurring or not): its time moves to "in 10 minutes", "in an hour" or "tomorrow morning" (or any
  words `parse_when` reads), it is told again at the new time, and the series is not touched.
- Editing a series' time or words is not offered: stop it and make a new one. (Said so on the page.)

### D5. The trail

An append-only `schedule_events` table records `created`, `occurred`, `lapsed`, `missed`, `paused`, `resumed`, `skipped`,
`stopped` and `snoozed`, with who did it (the owner on the page, the model's chat message, or the system) and the ids, like the
action trail (`docs/ACTIONS_DESIGN.md` D3). It is what makes "why did this fire / not fire" answerable.

### D6. Not an action, and bounded

A recurring reminder is local, visible, and stoppable, so it is not an "action" (`docs/ACTIONS_DESIGN.md` D2): no approval
card. The model can create one and read the list; it cannot pause, skip, stop or snooze one (the owner does that on the page),
the same line drawn for tasks. At most 20 series are active at once.

### D7. The model's side: one new argument, three guards

`add_reminder(content, due_at, repeat)`. `repeat` is the person's own words ("every Monday at 9am"). (1) The existing guard
stands: nothing is saved unless the latest message asks for a reminder. (2) `repeat` is kept only if the person said it
(`diya_intent.said_in`), else it is left out and the model is told, and the reminder is saved as a one-off if it has a
readable time. (3) The rule is read by code; unreadable words refuse the save with the reason, so the model can ask. With
`repeat`, `due_at` is ignored (the rule carries the time) and the answer says when the first occurrence is. The invention risk
is "the model makes something recur that was said once": measured with the real model before the unit is called done, as the
task tool was (a labelled set, `python diya_schedule_bench.py`).

**Amended after that measurement (2026-10-10): the rule comes from the person's words, not the model's.** The first
measurement (section 6) showed three failures the guards above could not fix, because they all trust the model's `repeat` text:
the 3B model split the time off into `due_at` ("every day" and "8am") so the saved rule was 09:00 while it told the person 8 AM;
it often passed no `repeat` at all, saved a single reminder, and told the person it repeated; and the 4B-instruct model
paraphrased ("daily at noon" as "every day at noon") and was refused for it. So now, when a repeat is **part of the request**
(`diya_intent.attached_repeat`: "remind me every day at 8am to ...", "every Monday, remind me to ..."), code finds the person's own
words for it (`diya_repeat.find_repeat`), reads them, and uses them whatever the model passed; the model's `repeat` is only a
sign that it repeats. A repeat that is not part of the request ("remind me to call mum tomorrow, I do it every Sunday"), or is
followed by words that could change it ("every day except Sunday"), or sits in a message that says something the reader refuses
("until June", "every second Tuesday", two repeats), is not found, and the earlier path applies unchanged: the model's `repeat`
is kept only if it is the person's words verbatim. This moves one decision from the model to code, on structural evidence
visible to the owner (the answer says what was made, and the Scheduled page can stop it); it is the one place D7 departs from
"the model decides whether it repeats".

### D8. The day brief is built in code from the owner's own data, not written by the model

`GET /api/today` and a Today page: what is due now, what is due later today, tasks due today and overdue, and what a series will
make next. Nothing in it is generated text: it is a view of rows the owner or the owner's own words already made. That is
the deliberate departure from PROACTIVITY D8, which assumed a model would write it and so wanted review-before-trust: a
list of facts the person already owns needs none. A model-written summary of it can come later, as its own measured unit; it is
not needed for the brief to be useful. (An optional calendar line comes from the Google Calendar connector once the owner has
connected it; not in this slice.)

### D9. Stage 6, "daily-driver experience", defined

The roadmap line was empty. Here is what it means, in the order it would be built: (1) a way to see the day (D8); (2) things
that come back to you without being asked (D1-D4, with the notifier actually scheduled: the owner's step); (3) reach: a phone
channel, designed on its own under the rules of `RESEARCH.md` entry 17 (a message is the owner's only if it is from the
paired owner; approvals never by chat); (4) one command to start the API, the UI and the notifier together. Of these,
only (1) and (2) are in this design; (3) and (4) each need their own design and the owner's yes.

## 3. Units

| Unit | What | Files |
|---|---|---|
| R1 | **The rule reader and its arithmetic.** `parse_repeat(words, now)` -> a `Repeat` (canonical text, description, `next_after`); pure, no clock, no database. | `diya_repeat.py` (new) |
| R2 | **Series, occurrences, the trail, snooze.** Migration 7 (`reminder_series`, `schedule_events`, `reminders.series_id`); `diya_schedule.Schedule`; the notifier, `list_reminders` and the Reminders listing call `materialize`. | `diya_db.py`, `diya_schedule.py` (new), `diya_notify.py`, `diya.py`, `diya_reminders_api.py` |
| R3 | **The model's side** (D7) and its measurement. | `diya.py`, `diya_intent.py`, `diya_schedule_bench.py` (new), `tests/labelled_repeats.py` (new) |
| R4 | **The Scheduled page, snooze buttons, and their API** (D4). | `diya_schedule_api.py` (new), `frontend/app/scheduled/page.js`, `frontend/app/reminders/page.js`, proxy routes |
| R5 | **The Today page** (D8). | `diya_brief.py` (new), `diya_brief_api.py`, `frontend/app/today/page.js` |

## 4. What needs the owner's yes

- **Tasks do not recur.** A thing that must come back and tell you is a recurring reminder; the to-do list stays one-off (a
  recurring task is a bigger idea: what does "done" mean for next week's copy?). Say so if you want recurring tasks.
- **A missed week is one reminder, and the stale one lapses** (D3). The alternative (keep them all) buries the day.
- **09:00 is the default time** of a series with none given (D2), as for a one-off.
- **The brief is code, not model text** (D8).

## 5. Not in this slice

Yearly rules (birthdays; a date with no year needs its own reading), "until" and counts, ordinal weekdays, editing a series in
place, a recurring task, a model-written summary, calendar events in the brief, and any channel outside the browser and the
desktop toast. The notifier still fires only while the machine is awake and the owner has scheduled it.

## 6. As built, and what was measured

Built 2026-10-10, all five units, nothing pushed: R1 `diya_repeat.py` (the reader, the arithmetic, and `find_repeat`); R2 `diya_schedule.py`
and migration 7 (series, occurrences, the trail, snooze); R3 `add_reminder(..., repeat)` and `diya_schedule_bench.py`; R4
`diya_schedule_api.py`, the Scheduled page and the snooze buttons; R5 `diya_brief.py`, `diya_brief_api.py` and the Today page. The
pages were checked in a real browser against a scratch database (add, an unreadable repeat, pause, skip, the two-press stop, snooze,
the Today page), and the scratch servers were stopped afterwards.

### The model measurement (`python diya_schedule_bench.py --runs 3`)

53 labelled messages (`tests/labelled_repeats.py`: 20 that ask for a repeat, 9 whose repeat it will not read, 12 single reminders, 12
that are not reminders) three times each, 159 answers per model, scored by what was **saved**, on this CPU-only laptop.

| Asked for a repeating reminder (60 per model) | right rule | wrong rule | repeat lost (saved once) | nothing saved |
|---|---|---|---|---|
| `qwen2.5:3b`, first pass (the model's `repeat` text used) | 16 (27%) | 9 | 11 | 24 |
| `qwen2.5:3b`, second pass (the person's words used) | **59 (98%)** | 0 | 0 | 1 |
| `qwen3:4b-instruct`, first pass | 53 (88%) | 0 | 0 | 7 |
| `qwen3:4b-instruct`, second pass | **59 (98%)** | 0 | 0 | 1 |

What the first pass found, in the answers rather than the counts: the 3B model told the person "every day at 8 AM" while the saved rule
was 09:00 (it split the time into `due_at`), and "every Monday at 9 AM" while only a single reminder was saved. The 4B model's seven
failures were all refused paraphrases ("daily" passed on as "every day"), after which it asked the person to confirm their wording.
The second pass is the D7 amendment above. Everything else held in both passes and both models:

- a repeat the reader refuses ("every hour", "until June", "every second Tuesday", ...) was **never** saved as a repeating reminder
  (0 of 27 per pass); `qwen3:4b-instruct` saved one single, timeless reminder for "Remind me twice a day to take my pills" and its
  answer sounds as if it repeats (a rough pattern match; 1 of 27, the same message in both passes);
- a single reminder was **never** made to repeat (0 of 36), and nothing was saved for a message that did not ask for a reminder
  (0 of 36); the 6 (3B) and 4 (4B) single reminders that were not saved are the earlier guard refusing a time the model changed;
- the models passed a repeat that the person had not said 1 and 3 times in 72 messages, and none was kept;
- time per message: 12.3 s to 11.6 s (3B), 15.2 s to 15.1 s (4B).

Caveats, plainly. (1) The 20 labelled requests were looked at while the finder was built, so 98% is partly a fit. Thirty fresh
phrasings written afterwards (kept as tables in `tests/test_repeat_tool.py`): 29 behaved correctly; the one that did not, "I need a
reminder every morning at 7:30 to ...", is a phrase the request check does not know, so it fails safe (no repeating reminder). (2)
One machine, one run of 159 per model per pass, a 3B and a 4B model only. (3) The first 3B pass stopped at 154 of 159 answers
because Windows refused to replace the results file while something had it open (my own read of it); the bench now retries and has
`--resume`, and that pass was finished with it, so the table has all 159.

### Mutation testing

474 deliberate changes to the new code (`diya_repeat.py`, `diya_schedule.py`, `diya_schedule_api.py`, `diya_brief.py`,
`diya_brief_api.py`, the repeat code in `diya.py`, `diya_intent.py`, the "today" rule in `diya_tasks.py`, the notifier and listing
hooks, and the benchmark's checkpointing), each run against the tests that cover it, in private copies of the repo. First run: 389
caught, 84 survived. Each survivor was read: 57 showed behaviour nothing checked (boundaries, messages, tie-breaking, a filter on the
API's lists, raw JSON text) and got a test, two pieces of dead code were removed (a capitalisation of a sentence that always starts
with a digit, and a type check `find_repeat` already makes), and the rest were equivalent. Final: **447 caught, 25 equivalent, 2
mutants gone with the dead code.** The equivalent ones, so they can be checked: a regex alternative another alternative already
covers ("every hour"); an `except` for an error that cannot happen (`from_canonical`'s `TypeError`; fuzzed instead, only
`ValueError` ever comes out); arithmetic on whole minutes where seconds cannot matter (2); two loops that correct themselves (interval
`gap`, `before`'s look-back); two ordinals whose suffix is "th" either way; a prefix strip recomputed afterwards; a single-word run
that cannot be a filler; an `or` branch another alternative already makes; a rollback SQLite does anyway when the connection closes;
bounds on ids where "not found" is the answer either way (0, negatives, the largest: 3); a default only a malformed row could reach (an
empty `said`, a missing `missed` count) or text that is never shown (the due text of an undated task, which is never listed); a sort the
database's own order already gives; and defence-in-depth `printable()` calls on text the code itself generates (5), or on a list the
brief already filters.

### Known limits

- A repeat that is part of the request is read from the person's words; one that is not ("I do it every Sunday") or is followed by
  words that could change it ("every day except Sunday") is not, and then the model's own `repeat` is kept only if it is the person's
  words verbatim, as before. So a model that passes just "every day" for "every day except Sunday" would make a daily reminder.
- Windows only, one laptop. The notifier is still the owner's step to schedule, so nothing tells you outside the app until they do.
- Tasks do not repeat, the Today page has no calendar line, and no model writes a summary of the day: each is a separate decision.
