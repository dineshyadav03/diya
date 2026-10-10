# Scheduled work: recurrence, snooze, a way to stop, and a day brief -- design spec

> **Status (2026-10-10):** designed; not yet built. This is the part of the roadmap's "durable workflows" stage (Later stages,
> 4) that `docs/PROACTIVITY_DESIGN.md` D7 and D8 deferred, plus a definition of the empty stage 6 ("daily-driver
> experience"). It needs nothing from anyone else's account. Requested by the owner: "in the roadmap there are things planned
> that were not worked on, the later stages too, work on it too." It follows the pattern of the earlier design docs:
> decisions with a recommendation, units that land one at a time, and what needs the owner's yes.

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
