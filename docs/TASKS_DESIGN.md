# A to-do list inside Diya -- design spec

> **Status (2026-10-05):** designed and built in two units (T1 the list and what the model may do with it, T2 the
> page and its API); section 5 says what was measured and what was not. Requested by the owner right after A4 shipped
> a Todoist write: *"build the to do list inside the product only -- why API?"* This document answers the question
> first, because the answer changes what is built. Committed locally, **not pushed**.

## 1. Why an API at all? (the honest answer, and why it is the wrong default)

Stage 3 made every outside account a menu item (`docs/CONNECTORS_DESIGN.md`, D5), and A4 then added the first
write, to Todoist, because a to-do list was the lowest-risk write there was. That reasoning assumed the list lives
somewhere else. For a local-first assistant it should not:

- **It needs nothing.** No account, no token, no network, no OAuth. The thing Diya is for -- a private assistant
  on hardware you own -- is exactly a list that never leaves the machine.
- **It cannot be retired from under it.** Todoist shut down the API the first Todoist connector was built on
  between 2026-09-28 and 2026-10-04 (`/rest/v2` now answers 410 Gone); nothing in the tests noticed. A table in
  Diya's own database cannot do that.
- **It needs no approval step.** `docs/ACTIONS_DESIGN.md` D2 draws the line at "could this leave this machine or
  touch an account". A line added to Diya's own list does neither: it is local, visible on a page, and the owner can
  tick it off. It is the same kind of thing as a reminder, which D2 deliberately did not gate. The approval
  machinery stays for what really leaves the machine (Todoist, if connected, and later kinds).
- **What A4 measured still applies.** The model proposed tasks nobody asked for (7% of unasked messages, 29% of
  "needs") and made up due dates (over half the time it gave one). Writing straight to Diya's own list does not
  make that harmless -- stray lines are noise and a wrong due date is a lie on a list you trust -- so the same
  three guards apply (below), and the same measurement is repeated for the new tool.

So: the built-in list is the default home for "add a task". Todoist stays an optional connector (off until you
connect it); see D6 for how the two avoid colliding.

## 2. Decisions

### D1. Tasks are rows in Diya's own database

Migration 6 adds `tasks` (id, `content`, `content_key` -- the case-folded words, the identity D5 uses --, `due_at`
-- the person's own words for when --, `due_ts` -- that read as a UTC instant when `diya_time` can read it, null
otherwise --, `done`, `created_at`, `completed_at`, `source` -- `chat` or `page` --, `thread_id`, `message_id` -- the
chat and message a task from chat answered, null for one typed on the page). The same shape as `reminders` (migration
3) and for the same reason: the words stay what the person said, and anything that acts on a time acts on a real one.
A task has no notification: a reminder tells you, a task waits to be looked at. Two things are enforced by the
database itself, not only by the code above it: one OPEN task per `content_key` (a unique partial index) and the
two checked columns (`done` is 0 or 1, `source` is `chat` or `page`).

### D2. Not an action: no approval card

A task added from chat is saved at once, like `add_reminder`, and says exactly what was saved. It is never offered
for approval, because there is nothing to approve that the Tasks page does not already show and let you undo.

### D3. The model gets two tools, and no power to close things

`add_task(content, due?)` saves a task; `list_tasks(status?)` reads them. There is deliberately **no** `complete_task`
(or delete, or edit) for the model: closing or changing something nobody asked about is a worse failure than a stray
new line, so the owner does those on the page. A small model is trusted with the cheap, visible, easily-undone write
and with reading, and with nothing else.

### D4. The three guards from A4, unchanged in spirit

1. **An empty optional argument is no argument** (`normalise_args`, already shared): `due: ""` does not bounce the task.
2. **A task is saved only if the latest message asks for one** (`diya_intent.is_task_request`, the guard A4 measured:
   0 of 153 unasked messages produced a proposal with it, against 10 before). Outside a turn (a direct call, a test) it is
   not judged by an old message, as `add_reminder` is not.
3. **A due date is kept only if the person said it** (whole words, any capitals): otherwise it is left out and the model
   is told. Said and readable by `diya_time` -> `due_ts` set; said and not readable ("when I'm back") -> kept as words, no
   `due_ts`, and the page shows the words as they were said.

The check against what the person said is `diya_connector_tools._said`; it moves to `diya_intent.said_in` so both the
list and the Todoist kind use one copy.

### D5. Limits on the list itself

Content is one trimmed line of at most 200 characters (`diya_memory.check_text`'s rules, like every other piece of
text the model can put in front of the owner: no control or invisible characters). At most 500 open tasks; one more is
refused with a plain sentence, because a model that adds a task every turn should hit a wall long before the page does.
The same task (same words, any capitals, still open) cannot be added twice: the model is told it is already there.

### D6. Todoist and the list do not collide

Both would match "add a task to buy milk". The rule is one clause each, in code, not in the model's judgement: **a
message that names Todoist is Todoist's** (`add_task` refuses it, saying the user named Todoist), and **Todoist's tool
needs the message to name Todoist** (its `asked` check requires it). Anything else is the built-in list's. Todoist
connected or not makes no difference to what "add a task to buy milk" does. If you would rather not have the Todoist
write at all, it is one line (`real_action_kinds()` returning `()`), and nothing else depends on it.

### D7. The page and the API

`/tasks`, like Reminders: open tasks first (oldest first, due ones marked), an add box (text, optional "when"), Done
and Reopen on each, and the done ones in a collapsed section. `GET /api/tasks`, `POST /api/tasks` (typed on the page:
the `when` is read by `diya_time` exactly as the model's is, and one it cannot read is kept as words), `POST
/api/tasks/{id}/done`, `POST /api/tasks/{id}/reopen`. No delete in this slice: Done hides a task without losing it, and a
delete button is a separate decision. Everything shown goes through `printable()`.

## 3. Units

| Unit | What | Files |
|---|---|---|
| T1 | **The list and what the model may do with it.** Migration 6; `diya_tasks.Tasks` (not more `Store` methods: the rules live beside the list, like `diya_actions.py` beside the actions); `add_task` and `list_tasks` on the Agent, offered always; the three guards and the Todoist rule (D6); `said_in` moved to `diya_intent`; the benchmark rewritten to measure the tools as they really are offered; measured with the real model before it is called done. | `diya_db.py`, `diya_tasks.py` (new), `diya.py`, `diya_intent.py`, `diya_connector_tools.py`, `diya_actions_bench.py` |
| T2 | **The page and its API** (D7), a link from every page, tripwire lists, live-checked in a real browser. | `diya_tasks_api.py` (new), `diya_web.py`, `frontend/app/tasks/page.js`, `frontend/app/api/tasks/**`, `frontend/lib/proxy.mjs`, `frontend/app/globals.css` |

## 4. What needs the owner's yes

- **Whether the Todoist write stays** (D6). It is built, tested and off by default (it needs Todoist connected, and a
  message that names Todoist); it costs nothing to keep and one line to remove. Left in unless you say otherwise.
- **Delete** is not in this slice (D7). If you want it, say so.
- **Whether the header should count overdue tasks**, the way it counts due reminders and waiting actions. Not built:
  one more number competing for attention in a header that has no slack on a phone is a taste decision.

## 5. As built

*Unit T1 (`diya_tasks.py`, migration 6 in `diya_db.py`, `add_task` and `list_tasks` in `diya.py`, `is_todoist_task_request`
and `said_in` in `diya_intent.py`).* `Tasks(store, clock)` is the whole surface: `add` (content, the person's words for
when, where it came from), `complete` and `reopen` (each says whether it did anything, so a double click is harmless),
`tasks(state, limit)` and `counts`. Every rule in D5 is checked inside one write transaction (`BEGIN IMMEDIATE`, as the
action store does), so two callers cannot both pass "is it already open?": eight threads adding the same words at once get
one task and seven refusals. A due phrase that cannot be read is kept as the person's words and is not an error;
`describe_due` shows a task due "Friday" as the day and never as nine o'clock (reading "Friday" gives 09:00, the time
reader's own default), and shows a time only when the person named one; `is_overdue` is late after a named moment but,
for a day, only once the day is over. The model's `add_task` is `add_reminder`'s shape: judged by the owner's own latest
message while a message is being answered, not judged by an old one outside a turn, told in one sentence what was
saved. `list_tasks`, like `list_reminders`, is the owner's own list and not "outside content": a Todoist proposal later
in the same turn does not list it as a source.

*Unit T2 (`diya_tasks_api.py`, `frontend/app/tasks/page.js`, the three proxy routes, a link from every page).* The routes
of D7. A refusal has its own status (404 no such task, 409 the same words already open or a full list, 422 text that
cannot be stored), and the person is never shown a task number, so the one thing the model is told ("already on the list
(#3)") is cut from what the page says. The page is the Reminders page's shape: the same once-a-minute quiet refresh
that never wipes an action's result, the same plain failure messages (a 401 is never "didn't answer"), the finished tasks
in a section that starts closed, an overdue task outlined *and* worded ("Overdue"), everything rendered as text.

**What was measured, and what it called for.** `python diya_actions_bench.py` was rewritten to measure the tools as they
really are offered (the list always, Todoist only when connected, `--todoist`), to say where a recorded task landed
and whether that was the right place, and to count answers that say a task was added when none was. The first run:
`qwen2.5:3b`, the same 25 requests and 51 non-requests as A4, three times each, Todoist not connected (the owner's real
state):

| | |
|---|---|
| asked for the list (20 messages x 3): saved on the list | 59 of 60 (98%); the one miss was the model saying nothing useful |
| asked in Todoist while it is not connected (5 x 3): saved anywhere | 0 of 15 (right: each was refused with a sentence that said why) |
| not asked: a task saved | **0 of 153** |
| not asked: the model reached for the tool at all | 24 of 153 (16%), all refused (A4's Todoist tool alone: 13 of 153, 8%) |
| due phrases the model gave that were not the person's words | 22 of 42; **0 of 15** on a saved task (A4: 23 of 42, 0 of 20) |
| asked what is on "the list": the model read it with `list_tasks` | 16 of 18; the other 2 used `list_reminders` ("Do I have anything overdue?") |

So the guards of A4 carry over unchanged and held: nothing was saved that nobody asked for, and no invented date got
onto a task. Two things the table does not show were found by reading the answers, not the counts, and fixed:

1. **The list's words were wrong even when the list was right.** After the tool refused ("Not added ... Answer what they
   asked"), the model still told the person it had added the task, or would, in 3 of the 153 unasked messages ("I added a
   task to your to-do list to pay the electricity bill", for "I forgot to pay the electricity bill"). The refusal now says
   so in capitals ("NOTHING was added. Do not say you added, saved or will add one"). Measured again on the 14 messages where it
   happened (needs and wishes, reading the list; 3 runs, 42 asks): 1 such answer instead of 3, and the model reached for
   the tool 5 times instead of 9. That is a direction, not a result: the events are 3 and 1, a 3B model's answer varies
   from run to run, and the one that is left is the same message. The count is a rough pattern match on the words
   (`claims_added`), verified by hand on the cases found, not an understanding of them; the answers are in the `--out` file.
2. **Asked for "my Todoist tasks" while Todoist was not connected, the model showed the local list as if it were Todoist's**
   ("Here are your current tasks in your to-do list" and, once, "no tasks currently open on your Todoist list"). `list_tasks`
   now says whose list it is in what it returns ("Tasks on the to-do list inside Diya (this is not Todoist):", "No open tasks
   on the to-do list inside Diya (this is not Todoist)."), and its description says to use `list_todoist_tasks` for Todoist.
   On the same three-run look the three "List my Todoist tasks" answers all said it was Diya's own list or that Todoist
   was out of reach.

**What this does not show.** The labelled messages were written by the author of the guard, so they say what the guard and
the model do with THESE phrasings, not how either does on the way a real person writes. Three runs of one small model are a
pattern, not a rate, and the second look (42 asks) is smaller still. `qwen3:8b` was not measured for the list at all. The
benchmark stubs `add_reminder` with a tool that always succeeds, so the model's claims of "I've saved a reminder" in the
answers are partly that stub's doing and are not counted (the real tool refuses them); the real `add_reminder` was measured
in its own unit. The page has no automated test of its own: it was checked in a real browser on scratch ports (a scratch database,
a scripted model, the real routes and the real page): adding a task with a time, the same words twice, ticking one off, putting
one back, an overdue task, a hostile `<img onerror>` title shown as plain text, a very long title wrapping, the finished section,
and a phone-width window. The first request to each route after a cold start took a few seconds, which looked like a hung
button until it finished; that is the dev server compiling, not the page. No part of this has been used for real yet: it is
the owner's list from the first task on.

**Known limits, kept on purpose.** The Todoist rule is a word, not an understanding: "Add a task to update my Todoist
password" goes to Todoist, so it is a card to approve, or (when Todoist is not connected) a refusal that says why, never a
task saved where the person did not look (`tests/test_task_intent.py` keeps the case). "Do I have anything overdue?" is
sometimes answered from the reminders, which is a fair reading of the question. There is no delete, no edit and no
notification: a task waits to be looked at (D1, D3, D7).

**Measured, not assumed.** 115 tests for the list (`tests/test_tasks.py`), 55 for the model's two tools, 68 for the routes, 265 for the
intent guards (the 203 from A4, the Todoist-by-name rule and the moved due-phrase check added), 96 for the benchmark's own machinery, and the route and page
tripwires extended (every route needs the token; every API route has a proxy route; the browser's fetches are a short fixed
list; every page links to the Tasks page). **294 mutations** of the new code, with every one run against only the tests that cover
it: 282 caught at once, and 12 survived. Ten of those showed real gaps, now closed with tests: the write lock was never tested
directly (eight threads adding the same words usually pass without it, because the unique index and a small window hide
the race), the safety layers on what the page sends back were never exercised (nothing today can put a hidden character in a reason or
a date, so a test now makes a refusal say one), a model-facing list loading everything instead of one more than it shows, and
five holes in the benchmark's own new "said it was added" counting and routing line. One was redundant code and was removed
rather than tested (a second "is the due date text?" check that the first already made). One is equivalent and stays: a task
number of 0 is refused by the route's own bound and, with that bound loosened, by the list with the same words and the same 404.
The run was first tried one mutant at a time against the real files (about 28 seconds each, 2.3 hours), which is too close to the
hour a background task is allowed and would leave a mutated, untracked file behind if cut off; it now runs in eight private
copies of the repository, so the real files are never touched (16 minutes).
