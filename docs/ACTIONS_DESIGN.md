# Actions and approvals -- design spec

> **Status (2026-10-04):** designed and **built: A1 (the trail and the state machine), A2 (the model's
> side), A3 (the API, the Actions page and the command line) and A4 (the first real write: adding a task
> in Todoist, on the owner's yes).** Todoist is the only account Diya can write to, one approved task at
> a time; every other connector is still read-only. Stage 4 of `ROADMAP.md`'s later stages ("durable
> workflows"), first slice only: the approval gate and the action trail. Stage 3 (connectors) is
> built, which was the owner's own precondition for starting this (2026-09-28): there is now a real
> connector to design the gate against. Everything a connector can do today is a *read*
> (`docs/CONNECTORS_DESIGN.md`, D2), so nothing here is needed yet to keep Diya safe -- it is needed
> before the first *write* exists, so that no write is ever built without it. Multi-step workflows
> ("describe an outcome, it follows through") are deliberately not in this document: they are a
> graph of steps that each need this gate, so the gate comes first.

## 1. What is true today

`diya.Agent._ask` runs whatever tool the model names the instant it names it: `func(**args)`, then
the result goes straight back to the model. That is correct for everything Diya can do now: every
tool either reads (weather, search, notes, files, the four connectors) or writes only to Diya's own
database in a way the owner sees and can delete (`add_reminder`, guarded by `diya_intent` so it only
saves when asked). Nothing in the loop can change anything outside this machine.

The moment a tool *can* -- create a calendar event, add a task, send a message, switch a light -- that
loop is the wrong shape, because it lets one model output become a real-world action with nobody
between them. The model that would be proposing the action is the 3B-class model whose measured
habits include calling `add_reminder` on "What's 9 times 7?" about 40-50% of the time
(`ROADMAP.md`, item 1), and which reads web pages, Notion pages and calendar titles that a stranger
can write. This document is about putting a person, and plain code, between that output and the world.

## 2. What the research said (all in `RESEARCH.md`)

- **Instinct (entry 2):** an email sent without approval, and prompt injection through email. The
  failure is "an action happened that the owner did not choose".
- **Meta Muse (entry 4):** approvals, audit trails, and a *separate* safety enforcer rather than the
  agent policing itself. Reuters' report of unauthorized data exposure in internal testing is the
  reminder that claiming these is not the same as having them.
- **UFO (entry 12a):** access is granted explicitly, in the open, and *the grant is itself the audit
  record*; the agent never silently borrows the identity of whoever is talking to it.
- **The harness-engineering course (12b):** a graph needs *human-approval nodes*; state lives in
  durable external storage, not in the model's context.
- **The gate benchmark and the JEV-as-a-Judge paper (entries 10, 13):** a small model is worse than
  plain code at gating, and cheap judges are unreliable exactly where text is adversarially written --
  which is what injected text is. So the gate is code, not a second model.
- **backpass and SkillOpt (12c, 15):** nothing changes behaviour on a plausible-looking diff alone;
  there is a held-out check. Here that means: measure the real model before a write kind ships.

## 3. Decisions

### D1. The model proposes; code executes; only the owner approves

**Recommendation:** a write-capable tool never performs its effect inside the tool loop. Called by the
model, it does exactly three things -- check its arguments, record a `pending` action (D3), and
return a fixed sentence to the model ("Proposed as action #12, waiting for the owner to approve it
on the Actions page. Nothing has happened yet; say so."). The code that actually performs the effect
(`execute`, D4) is reachable from exactly one place: the approve route (or CLI) -- there is no tool
by which the model can call it, and no chat phrase that triggers it.

Approval is therefore **a button in the UI, not a chat reply.** "Yes, do it" typed into the chat goes
through the model, and text an attacker planted in a Notion page can imitate it; a button press goes
through the authenticated API (access token, Host and Origin checks, all already in place) and
reaches no model at all. This is the one place this design departs from UFO's "grant in chat": UFO's
chat is a team product with several humans, each speaking as themselves; Diya's chat is one person
and one model, reading outside text, so the confirmation has to live outside the model's channel.

### D2. What counts as an action (and what does not)

**Recommendation:** an **action** is anything that changes state outside Diya's own database, or sends
something to a third party. Gated: every write a connector can make. Not gated: reads (already
logged, Stage 3 D3), fact-shares (no tools at all in that turn), and reminders (local, visible on the
Reminders page, deletable, and already guarded by `diya_intent.is_reminder_request`) -- gating
reminders would make the page everyone checks daily into a page of approvals, and teach the owner to
click without reading. The line is "could this leave this machine or touch an account", not "does
this write".

An **action kind** is one frozen declaration, like a `Connector`: a name, a label, the connector it
needs, `validate(args)`, `render(args)` (the sentence the owner sees, built in code from the
arguments, never from model prose), and `execute(config, args)`. A kind is offered to the model only
while its connector is connected (Stage 3 D4), and `execute` re-checks that at run time.

### D3. The trail is the database: one row per action, one row per thing that happened to it

**Recommendation:** migration 5 adds `actions` (id, kind, `args` as canonical JSON, `args_hash`,
`summary` as rendered at proposal time, `status`, `thread_id`, `message_id` of the owner's message
that led here, `tainted` and `taint_sources` (D6), `created_at`, `expires_at`, `decided_at`,
`executed_at`, `result`) and `action_events` (action_id, event, **actor** -- `model`, `owner` or
`system` -- `at`, detail), append-only, exactly the shape `facts` and `fact_events` already have and
for the same reason: the row says where things stand, the events say how they got there, and neither
is ever deleted. States: `pending -> approved -> executing -> succeeded | failed`, or `pending ->
rejected | expired`, or `executing -> unknown` (D4). Transitions are enforced in code
(`IllegalTransition`, as `Memory` does) and the status vocabulary by a `CHECK`.

This answers "what did Diya do on my behalf, and who said it could" without trusting the model's
own account of it -- the question UFO answers by making the grant the record. Here the record is
the approval event: the owner, the moment, the exact arguments they saw (by hash, D5).

### D4. Exactly once, or flagged -- never silently retried

**Recommendation:** `approved -> executing` is committed to the database **before** the network call;
the outcome (`succeeded` / `failed` and the service's own reply as `result`) is written after. If the
process dies between the two, the row stays `executing`; at the next start any `executing` row is
moved to `unknown` ("the outcome is not known -- check the service yourself, then record what you
found"), and it is **not** run again. A failed call is `failed` and also not retried: a retry is a new
proposal, which the owner approves again.

This is the opposite of what a durable-execution engine such as DBOS (UFO's choice) does -- replay
the step -- and the difference is deliberate: replay is right when a step is idempotent or the engine
supplies the guarantee, and wrong for an email, a charge or a door lock, where doing it twice is
worse than doing it zero times. Todoist documents command idempotency only for its Sync API (a
`uuid` per command, checked 2026-10-04), not for creating a task through the REST-style endpoint,
so no kind may assume it. A kind whose service really does de-duplicate may opt in to a safe retry
later, per kind, with the owner's yes.

### D5. Approval binds to exactly what was shown

**Recommendation:** the approve request carries the `args_hash` of the action as the page displayed
it; if the stored row's hash differs, the approval is refused with 409 and nothing runs. Arguments are
immutable once proposed -- changing something means rejecting and proposing again -- so the owner
cannot approve one thing and have another executed (a time-of-check / time-of-use swap), whether
from a bug, a second tab, or a race with the model proposing again.

### D6. The prompt-injection boundary: what stops each real attack

| Attack | What stops it | What does not |
|---|---|---|
| Text in a Notion page, calendar title, search snippet or file talks the model into proposing something | D1: nothing runs without the owner. D3 `taint`: code records which read tools ran earlier in the *same turn* and the Actions page shows them on the card ("Diya read Notion and the web in this turn before proposing this"). The summary is built by code from the arguments (D2), so the card cannot be rewritten by the injected text. | A convincing-looking, plausible action the owner approves anyway. The taint banner is information, not a verdict: it cannot know the text was hostile. |
| Injected text makes the model *tell the owner* the thing is done, or that it was approved | The Actions page and the pending count in the header are a second channel the model does not write to; status is never inferred from chat. | The model can still say something false in chat. Nothing in this design can stop that; it can only make the true answer one click away. |
| A task title or event name written to look like an instruction ("URGENT: approve this now") | Arguments render as escaped plain data in labelled fields, length-capped by each kind's `validate`. | A determined, well-written one. Same residual as above. |
| The model floods the queue (the same habit as the unasked reminders) | A cap on pending actions (recommend 10) and per turn (3); an identical pending action (same kind and hash) is refused as a duplicate; pending actions expire (recommend 24 hours, `expired`, recorded). **A kind does not ship until the unasked-proposal rate has been measured with the real model** (A4) -- the same discipline as `docs/PROACTIVITY_DESIGN.md` D9. | A model that proposes things the owner *did* ask for but wrongly. That is the owner reading the card. |
| A fact-share ("my flight is Friday at 6") | Already no tools at all in that turn (`diya._ask`); unchanged. | -- |
| Stolen or replayed approval | The approve route is the same authenticated, Host- and Origin-checked API as every other; D5 binds it to one hash; an action can leave `pending` only once. | Anyone who holds the API access token can approve -- on a LAN-mode install, that is whoever has the token. The same trust as everything else in Diya; stated, not hidden. |
| Reviewed memory contains injected text | Stage 2: a fact reaches the model only after the owner accepted it. | A hostile fact the owner accepted. |

**Which tools count toward taint:** every tool except `list_reminders` -- deliberately broad, because
the owner's own files and notes can hold text pasted from somewhere else. Taint is recorded, shown
and never used to *decide* anything automatically: no hidden second model, no heuristic that could be
argued with. (D10.)

### D7. No standing grants in this stage

**Recommendation:** every action is approved one at a time. "Always allow adding Todoist tasks" is a
real thing people will want -- UFO and Muse both have versions of it -- and it is a policy decision
per kind that the owner has not asked for. It is a later unit that needs the owner's explicit yes
and, even then, should be per kind and revocable on the same page, never a global switch.

### D8. The Actions page, the API and the command line

**Recommendation:** same shape as Memory and Reminders. `GET /api/actions` (pending, or all),
`GET /api/actions/{id}`, `POST /api/actions/{id}/approve` (body: `args_hash`), `POST
/api/actions/{id}/reject`. A new `frontend/app/actions` page: **Pending** cards (the rendered summary,
the taint banner and its sources, the chat it came from, time left, Approve and Reject), then
**History** (status, who and when, the service's own reply, the events). The pending count joins the
reminders count in the chat header. A `python diya_actions_cli.py list / show / approve / reject`
command (its own module, as `diya_review.py` is beside `diya_memory.py`) mirrors `diya_review.py`: same trust as the UI (the owner running a command on their own
machine), and it is what the tests drive first. Every new route needs adding to the two tripwire
lists (`tests/test_frontend_proxy.py`, `tests/test_token.py`) -- a known cost from M3 and C3.

### D9. Receipts

**Recommendation:** after execution the service's own reply (the created task's id, or the error text)
is stored as the action's `result`, shown on the History card, and written to the connector log
(`docs/CONNECTORS_DESIGN.md` D3) as `action #N`. The owner can answer "what did it do" from the page,
the log, or the database, and the three agree because they are written by the same function.

### D10. Separate enforcement, in code, no second model

**Recommendation:** Muse's "Sentinel" is a separate agent; Diya's equivalent is a separate *module*
with no model in it. `diya_actions.py` owns the state machine, the caps, the expiry, the hash check
and `execute`; the tool loop can only call `propose`. `validate` runs at proposal **and** again at
execution (the connector may have been disconnected, the arguments are checked as stored, not as
remembered). The reason it is not a second model is measured, not assumed: `docs/GATE_BENCHMARK.md`
found the local model worse than plain code at every gating decision tried, and entry 13's JEV
paper found cheap judges fail most where text is written to mislead.

### D11. The first write kind, and a finding about the connector under it

**Recommendation:** `todoist_add_task` (`content`, an optional `due_string`; no project, so Todoist puts
it in the Inbox). Why this one: it needs only the paste-a-token connector C2 already validates (C3's
OAuth path is still unverified against the real Google, so Calendar cannot be the first); it is
reversible (a task can be deleted); the worst outcome is a wrong line in a to-do list; and it can be
tested the way C2 was -- fake token, the real model, the real service refusing it for real. Later
kinds, each its own decision: Notion create-page, Google Calendar create-event once C3 is proven, and
Home Assistant service calls last and only behind a per-entity allowlist, because that one moves
physical things.

**Finding, checked live 2026-10-04:** C2's Todoist tool and validator called the legacy REST v2
(`/rest/v2/...`). Todoist's current API is v1 (`/api/v1/...`), described in its own docs as "a new
API that unifies the Sync API v9 and the REST API v2". v1 has a plain *Create Task* (`content`
required, project optional and defaulting to the Inbox). When this section was first written the
expectation was that v2 was merely "on its way out"; checking it against the real service for A4
showed it was already gone: **`/rest/v2/...` answers 410 Gone**, so the connector could not connect to
a real account at all. A4 therefore moved the Todoist connector to v1 first, as its own commit
(`docs/CONNECTORS_DESIGN.md`, "Found later, and fixed"), before building a write on it. The v1 list
endpoints are paginated (`{"results": [...], "next_cursor"}`), which v2's were not.

## 4. Units

| Unit | What | Files |
|---|---|---|
| A1 | **The trail and the state machine.** Migration 5 (`actions`, `action_events`); `diya_actions.py`: the kind registry (empty, like `CONNECTORS` was at C1), `propose` / `approve` / `reject` / `expire` / `reconcile`, `IllegalTransition`, the hash, the caps and the duplicate check. No network and no model; tested with fake kinds, mutation-tested. | `diya_db.py`, `diya_actions.py` (new) |
| A2 | **The model's side and the taint record.** A kind's tool spec only proposes (D1); `Agent._ask` records which tools ran before a proposal in the same turn; `Agent.tools` offers a kind only while its connector is connected (D2). Fake kinds only. | `diya.py`, `diya_actions.py` |
| A3 | **API, page and command line** (D8): the routes, the proxy routes and tripwire-list updates, `frontend/app/actions`, the header count, the command line. Live-checked in a real browser. | `diya_actions_api.py` (new), `diya_actions_cli.py` (new), `diya_web.py`, `frontend/...` |
| A4 | **The first real kind** (D11). Todoist connector moved to API v1; `todoist_add_task`; measured with the real model (fake token): is it proposed when asked, and **how often when not**; the number decides whether the first kind needs a `diya_intent`-style guard like reminders have. The owner said yes to Todoist (2026-10-04). **Built** (section 6): the number did call for guards, and they are in. | `diya_connector_tools.py`, `diya_actions.py`, `diya.py`, `diya_intent.py`, `diya_actions_bench.py` |
| later | Standing grants (D7), multi-step workflows with an approval node, more kinds (Notion, Calendar, Home Assistant), snooze and recurrence for reminders (carried over from `docs/PROACTIVITY_DESIGN.md`). Each is its own design. | -- |

Order: A1 before anything (nowhere to put a proposal without it), A2 before A3 (the page needs
something real to show), A3 before A4 (the owner must be able to see and refuse a proposal before the
first real one can exist). A1-A3 add **no write capability at all** -- the registry is empty until A4 --
so they can be built and reviewed without anyone deciding whether Diya may write anywhere.

## 5. What needs the owner's yes

- **Whether Diya may write to any account yet (A4).** *Answered, 2026-10-04: yes, to Todoist, adding a
  task.* `docs/CONNECTORS_DESIGN.md` section 6 left this open on purpose; the recommendation was Todoist
  add-task, one at a time, approved on a page, and nothing else, and that is exactly what was built. No
  other connector and no other kind of write is covered by that yes: each is its own decision.
- **The caps and the expiry** (10 pending, 3 per turn, 24 hours) are recommendations, not decisions
  anyone should have to make; change them freely.
- **Standing grants** are not asked for here (D7). If wanted, say so, and it becomes its own design.

## 6. As built

*Unit A1 (`diya_actions.py`, migration 5 in `diya_db.py`, `tests/test_actions.py`).* The trail and the
state machine, with no network and no model in it; every kind in the tests is a fake. `Actions(store,
config, kinds, clock)` is the whole surface: `propose` (the only thing a model-callable tool may do),
`approve(id, shown_hash, via)` and `reject(id, via)` (the owner), `run(id)` (the only path to
`ActionKind.execute`), `resolve(id, happened, via, note)` (the owner, for an `unknown` action),
`expire`, `reconcile`, reads, and `verify_integrity`. The real registry, `diya_actions.KINDS`, is
empty, and a test pins that it stays so until a unit adds the first real kind.

Where it went beyond or past what the sections above say, disclosed rather than quietly absorbed:

- **Who may record what is enforced, not just recorded.** Each event has exactly one legal actor
  (`EVENT_ACTOR`): only the model proposes; only the owner approves, rejects or resolves; the rest is the
  system. `approve` takes no actor argument at all, so there is no call that approves "as the model", and
  `verify_integrity` flags an event written by the wrong one.
- **`approve` and `run` are two methods, not one.** `approve` only records the owner's decision; `run`
  performs it. The approve route will call both in turn (A3). A crash between them leaves `approved`,
  which is safe to leave (nothing was attempted) and which expires with the proposal.
- **Expiry covers `approved` as well as `pending`** (D6 said pending): an approval does not outlive its
  proposal, so an approval that was never run cannot fire a day later. One `now` is taken per call and
  shared with the expiry, so there is no second, racing check.
- **`run` re-checks more than D10 asked.** Beyond re-validating and re-checking the connector, it
  recomputes the hash from the stored arguments, and re-renders the description and compares it with the
  one the owner was shown -- so changing the stored arguments *and* their hash directly in the database is
  still caught, because the description no longer matches. A kind whose wording changes in a later
  release will therefore refuse to run an action approved before the upgrade (a 24-hour window): it fails
  closed, with "Not run: ..." as the result, not open.
- **Arguments are a flat set of named plain values** (text, numbers, true/false, empty), text held to
  `diya_memory.check_text`'s rules (one trimmed line, no control or invisible characters), whole at most
  4,000 characters. D3 said "canonical JSON"; this is what makes it canonical.
- **`resolve` and `via`** are in the code because D4 and D8 implied them: the owner's way out of
  `unknown`, and a record of whether a decision came from the page or the command line.
- **Cut-off detection is by age, not by "next start".** `reconcile` moves only an `executing` action older
  than two minutes (the network timeout is five seconds), so a run still in flight in another process is
  left alone.

Measured, not assumed: 156 tests, then 170 mutations of `diya_actions.py` and migration 5 -- each a
deliberate break that a test must catch -- all caught in the end. The first pass left one alive (a
taint-sources test used `"web_search"`, whose underscore made it fail for the wrong reason, so a string
passed as a list was never really tested) and 21 patterns that matched nothing because the new files had
been written with CRLF line endings; the survivor got a new test case, the files were converted to the
repo's LF, and the 22 were re-run. Not mutated because behaviour cannot differ: the three indexes (speed
only), the kind filter in the duplicate query (the hash already includes the kind), the `message_id is
not None` guard in the per-message count (`= NULL` matches nothing anyway), and passing one `now` into
`expire` rather than letting it read the clock again (the same instant in every test).

*Unit A2 (`diya.py`, `diya_actions.py`, `diya_db.py`, `diya_web.py`, `tests/test_actions_agent.py`).* The model's
side, with fake kinds only. A kind of action gained an optional `tool` (the function spec the model is shown);
`Agent(..., action_kinds=...)` builds an `Actions` from the kinds it is given (the real registry, still empty, by
default), registers each tool as a function that only **proposes**, and offers it in `Agent.tools` only while its
connector is connected -- re-read every turn, like a connector's own tool, so connecting or disconnecting takes
effect on the next message. A tool name another tool already has refuses to start rather than shadow it.
`Agent.ask` takes `thread_id` and `message_id`, and the chat route, the terminal chat and the one-message
run now pass them (`Store.add_message` returns the new id for that); a proposal records them as its own, never
as anything the model said. Which tools ran earlier in the *same turn* is recorded, in order and once each, as
the taint (D6): every tool except `list_reminders` (the owner's own list), not another proposal, and written
down before the tool runs so one that fails is still listed. The turn's state is per thread of control, and
is cleared when the turn ends, so it cannot leak into the next turn.

Where it went beyond or past the sections above: the one repair the model's side makes is **whitespace** in
its text arguments (`normalise_args`: runs of spaces, tabs, line breaks and non-breaking spaces become one
space), so "buy  milk" is proposed as "buy milk" instead of bouncing; the owner sees, and the hash binds, the
tidied text. A control or invisible character is still refused, not repaired. The model is told one fixed
sentence either way (`proposed_text`, `refused_text`): that it is only a proposal and not to say it is done,
or that nothing was recorded. `kind` is a positional-only parameter of the proposing function, so an argument
the model happens to name `kind` is refused by the kind's own check instead of crashing the tool loop. Startup
(`actions_startup_lines`, printed by the API and the terminal chat) first moves any run cut off long ago to
`unknown`, then says how many are waiting or still need the owner's word -- and says nothing when there is
nothing to say.

Measured, not assumed: 51 tests; 60 mutations of the new code, all caught in the end. The first pass left one
alive (the per-turn record is cleared when a turn ends, but nothing checked that after a turn that had
actually read something -- the next turn's own reset hid it) and two patterns that matched `add_reminder`'s
identical line as well; the survivor got an assertion and the patterns got context. Not mutated because
behaviour cannot differ: falling back to the real registry when no kinds are passed (it is empty).

*Unit A3 (`diya_actions_api.py`, `diya_actions_cli.py`, `frontend/app/actions`, `frontend/app/api/actions`,
`frontend/lib/actions-format.mjs`, the proxy helpers and tripwire lists).* The surface the owner decides on.
`GET /api/actions` (what is waiting, the 50 most recent decided or finished, the counts, and which kinds exist
and are available), `GET /api/actions/{id}` (the action, the message it answered, its events) and `POST
.../approve`, `.../reject`, `.../resolve`. The approve route is the one place an effect can start from the
web: it records the owner's approval of the hash the page sent, then runs the action, in one request, and
answers with how it ended -- a failed effect is still a 200 with the failure in it, because the request did what
was asked. Everything shown goes through `printable`; the arguments go out as named fields beside the one
sentence the code built. A page for it, a pending count in the chat header (waiting plus unknown, and nothing
when it cannot be told), an Actions link on every page, and a command line, `python diya_actions_cli.py`, that
asks before approving and holds the approval to the version it just displayed.

Where it went beyond or past D8, disclosed: a **`resolve` route and page control**, because an `unknown` action
needs a way out in the browser as much as in the terminal; the **command line is its own module** (as
`diya_review.py` is beside `diya_memory.py`), not `diya_actions.py`; **listing is not a pure read** -- it
closes what has expired and moves a run cut off more than two minutes ago to `unknown`, so the page never
shows either as live; and the page says plainly, when no kind is registered, that Diya has no way to propose
any change at all, rather than showing an empty list that looks like "nothing yet". Reading the pending list
is by id order and the history newest first, capped at 50: enough for one person's day, and a number to
revisit when it stops being true.

Measured, not assumed: 47 API tests, 72 command-line tests, 47 formatting tests (Node), 56 proxy tests for the new
routes, and the two route-exhaustiveness tripwires extended; 139 mutations of the new code all caught in the end
(three survived the first pass: two were `sorted()` calls on arguments that are already stored in sorted order, so
they were removed as dead code rather than tested, and one was a test that passed because proposing a new
action had already expired the old one, so it now waits for the listing to do it). **Live-checked** in a real
browser, against a scratch API with a fake kind and a scratch database on other ports: Approve ran the effect exactly
once; Turn down never ran it; "It happened" with a note recorded the note and ran nothing; a title written to
look like an instruction was shown as plain text; the caution listed what had been read; the header badge counted
what was waiting. **Not covered by an automated test:** the page component's own behaviour (the repo has no
component tests for any page); the live check above is what stands in for it, and the pure helpers and the proxy
routes under it are tested.

*Unit A4 (`diya_connector_tools.py`, `diya_actions.py`, `diya.py`, `diya_intent.py`, `diya_actions_bench.py`,
`tests/labelled_task_requests.py`).* The first real write, on the owner's yes (2026-10-04): **adding a task to
Todoist**. The kind is `todoist_add_task` (`content`, an optional `due_string`; no project, so Todoist files it
in the Inbox); the sentence the owner approves is `Add to your Todoist Inbox: <content> (due <when>)`; the
effect is one `POST /api/v1/tasks`, made only by `Actions.run` after the owner approved exactly those
arguments, and what is sent is a short list of its own (the content, and the due phrase if there is one),
whatever else the arguments held. It is offered to the model only while Todoist is connected, like the
connector's own tool. The registry moved: a kind needs its connector, so the real one is
`diya_connector_tools.real_action_kinds()` and `diya_actions.KINDS` is gone (the Agent and the command line
default to it). The Connections page now says Diya reads on its own and anything that would change an account
waits for approval, and Todoist's card says it can add a task when you approve it.

**It began with a repair.** Checking the Todoist API against the real service before building on it showed C2's
connector was already broken: `/rest/v2/...` now answers 410 Gone, so a real token could not even be connected.
That was fixed first, as its own commit (`docs/CONNECTORS_DESIGN.md`, "Found later, and fixed").

**An outcome that cannot be told is `unknown`, not `failed`** (beyond what D4 described). A POST that was sent
and got no answer -- a read or write timeout, a dropped connection, a garbled reply, or a 5xx from Todoist --
may have created the task, and calling that a failure would invite a second attempt that does it twice. An
effect says so by raising `ActionUncertain`; the action lands in `unknown` with the reason as its result, is
never run again, and the owner resolves it exactly as they would a run cut off by a crash. Only what cannot have
been sent (a refused connection, a connect or pool timeout, an unsupported protocol) is a plain `failed`, and so
are the answers that mean it was not created (401, 403, 429, any other 4xx). The Actions page words an approval
that ended `unknown` as "Not sure it was done", never "Not done".

**The measurement D6 asked for, and what it called for.** `python diya_actions_bench.py` sends 25 messages that
ask for a task and 51 that do not (eight categories, including needs and wishes, reminders, reading the list and
mentioning the word "task"; `tests/labelled_task_requests.py`), three times each, through the real Agent and the
real model (`qwen2.5:3b`) with the proposal tool offered; the tools that read are stubbed, Todoist is "connected"
with a made-up token, and a proposal is only recorded. It counts the model *reaching for* the tool separately
from a proposal being *recorded*, which is what the owner would see.

| | before any guard | with the guards |
|---|---|---|
| asked for a task: a proposal recorded | 67 of 75 (89%) | 72 of 75 (96%) |
| not asked: a proposal recorded | 10 of 153 (7%) | **0 of 153 (0%)** |
| due phrases on a recorded proposal that were not the person's own words | 23 of 42 given | **0 of 20** |
| refused because the model sent `"due_string": ""` | 6 | 0 |
| not asked: the model reached for the tool at all | 10 of 153 | 13 of 153 (all refused) |

Without a guard the model proposed a task nobody asked for in 7% of the not-asked messages and in 29% of the "needs
and wishes" ones ("I need to buy milk", "I'm running low on printer ink"), and "make a note to call the plumber"
three times in three; plain questions, facts, list-reading and mentions of the word were all zero. More worrying
than the noise: in over half the cases where it gave a due date the date was invented ("add task call mum" came
back "due tomorrow at 5pm"), the same failure `add_reminder` had, and the six empty-`due_string` refusals were
never recovered: the model told the owner it "could not add the task without a due date", which was false. So
the number did call for guards, three of them, all deterministic and none a second model (D10):

1. **An empty optional argument is no argument** (`normalise_args` drops `""` and null): fixes the false refusals.
2. **A task is proposed only if the latest message asks for one** (`ActionKind.asked`, here
   `diya_intent.is_task_request`, the same shape as `is_reminder_request`): stops every unasked proposal.
3. **A due phrase the person did not say is left out, and the model is told** (`ActionKind.prepare`, here
   `todoist_add_task_prepare`; whole words, any capitals): a card shows only what the owner said.

Both checks apply only while a message is being answered, as `add_reminder`'s does; a call made outside a turn is
not judged by an old message. The guard is a short list of the ways people ask, so missing an unusual phrasing is
the safe direction (they can say "add a task to ..."): it refuses "jot 'x' in Todoist", "stick it on my to-do list"
and "queue up a task", and it allows a few things that only mention adding a task ("she asked me to add a task to the
board"); both lists are kept in `tests/test_task_intent.py` on purpose. Probing it with phrasings it was not
tuned on found one unsafe gap (a negation, "don't add a task for that", passed), which is now refused.

**What this does not show.** The labelled messages were written by the author of the guard, so they show what the
guard and the model do with THESE phrasings, not how either does on the way a real person writes; three runs
of one small model is a pattern, not a rate; the model ran without the owner's accepted facts in its prompt; and
`qwen2.5:3b` is the default model, not the only one, and **the larger installed model is barely measured**: a first
attempt against `qwen3:8b` (about six times slower on this machine) ran out of the hour a background task is allowed and a
second was cut off with the session; the third, on the first two messages of each list, once (18 messages, 17 minutes),
finished. It proposed a task for both that asked, reached for the tool on 1 of 16 that did not ("I need to buy milk", refused
by the guard, none recorded), and gave no due date at all, so it invented none. That is a sample of 18, enough to say the
larger model is not obviously worse and nothing about whether it is better. **No real Todoist account has been used**: every network call in the tests is faked, the live check
(a real browser, a scratch database, the real kind with only `httpx.post` faked) drove one approval to success
and one to "sent, no answer", and the service itself was asked only what it says to a fake token (a 401 on every
path used). The first real task, from the owner's own token, is the one thing still unverified.

Measured, not assumed: 136 connector-tool tests (the migration, the write, every status and every kind of network
failure, the whole flow through the approval store, the guard and the due check through the real Agent), 203 for the
guard's phrasing, 29 for the benchmark's own machinery, and the store, agent, API and command-line tests extended;
**204 mutations of the new code, 203 caught** (the other, `.match` for `.search` on a pattern anchored with `^`, cannot
behave differently). The first pass left twelve alive and four patterns unmatched: three of the survivors were
redundancy in the regex itself (an article `an` that is ungrammatical before "task", a `new` already covered a
few characters later, a `todo` that `to-?do` already matches), which were removed rather than tested; the rest were
real gaps (destination forms for `log`, `enter` and `record`; two "question" cases that were never requests and so
tested nothing; the Todoist body being a short list of its own; the benchmark's unasked-recorded count), which
got tests.

**Changed afterwards (2026-10-05, `docs/TASKS_DESIGN.md`).** Right after A4 the owner asked for the to-do list to live
"inside the product only", and a list inside Diya's own database is not an action (D2 above: nothing leaves this
computer), so it is saved at once and never waits on this page. That left two tools that both match "add a task to buy
milk", so the choice is made in code, not by the model: a message that names Todoist is Todoist's (`diya_intent.
is_todoist_task_request`, now this kind's `asked`), any other is the list's. Todoist is still optional and still approved
card by card; it just has to be named. The tables above were measured BEFORE that change, with every one of the
25 requests going to Todoist: only the 5 that name it would be proposed now, and the model's side of the other 20 is
measured for the list in `docs/TASKS_DESIGN.md`.
