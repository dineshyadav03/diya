# Actions and approvals -- design spec

> **Status (2026-10-04):** designed; **A1 (the trail and the state machine) built and
> mutation-tested, A2-A4 not started.** Nothing here can write anywhere yet: the real registry of
> write actions is empty. Stage 4 of `ROADMAP.md`'s later stages ("durable
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
reminders count in the chat header. A `python diya_actions.py list / show / approve / reject`
command mirrors `diya_review.py`: same trust as the UI (the owner running a command on their own
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

**Finding, checked live 2026-10-04:** C2's Todoist tool and validator call the legacy REST v2
(`/rest/v2/...`). Todoist's current API is v1 (`/api/v1/...`), described in its own docs as "a new
API that unifies the Sync API v9 and the REST API v2", with v2's documentation still available "for
reference". v1 has a plain *Create Task* (`content` required, project optional and defaulting to
the Inbox). Unit A4 therefore moves the Todoist connector to v1 first -- a read-path change with its
own tests -- before adding a write on top of an API line that is on its way out. The v1 list
endpoint is paginated, which v2's was not, so that is a real change, not a URL swap.

## 4. Units

| Unit | What | Files |
|---|---|---|
| A1 | **The trail and the state machine.** Migration 5 (`actions`, `action_events`); `diya_actions.py`: the kind registry (empty, like `CONNECTORS` was at C1), `propose` / `approve` / `reject` / `expire` / `reconcile`, `IllegalTransition`, the hash, the caps and the duplicate check. No network and no model; tested with fake kinds, mutation-tested. | `diya_db.py`, `diya_actions.py` (new) |
| A2 | **The model's side and the taint record.** A kind's tool spec only proposes (D1); `Agent._ask` records which tools ran before a proposal in the same turn; `Agent.tools` offers a kind only while its connector is connected (D2). Fake kinds only. | `diya.py`, `diya_actions.py` |
| A3 | **API, page and command line** (D8): the routes, the proxy routes and tripwire-list updates, `frontend/app/actions`, the header count, `diya_actions.py`'s CLI. Live-checked in a real browser. | `diya_actions_api.py` (new), `diya_web.py`, `frontend/...` |
| A4 | **The first real kind** (D11). Todoist connector moved to API v1; `todoist_add_task`; measured with the real model (fake token): is it proposed when asked, and **how often when not**; the number decides whether the first kind needs a `diya_intent`-style guard like reminders have. **Needs the owner's yes** (section 5). | `diya_connector_tools.py`, `diya_actions.py` |
| later | Standing grants (D7), multi-step workflows with an approval node, more kinds (Notion, Calendar, Home Assistant), snooze and recurrence for reminders (carried over from `docs/PROACTIVITY_DESIGN.md`). Each is its own design. | -- |

Order: A1 before anything (nowhere to put a proposal without it), A2 before A3 (the page needs
something real to show), A3 before A4 (the owner must be able to see and refuse a proposal before the
first real one can exist). A1-A3 add **no write capability at all** -- the registry is empty until A4 --
so they can be built and reviewed without anyone deciding whether Diya may write anywhere.

## 5. What needs the owner's yes

- **Whether Diya may write to any account yet (A4).** `docs/CONNECTORS_DESIGN.md` section 6 left this
  open on purpose. The recommendation is Todoist add-task, one at a time, approved on a page,
  and nothing else; "no, stay read-only for now" is a fine answer and costs nothing -- A1-A3 stand on
  their own.
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
