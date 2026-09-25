# Stage 2: Trustworthy memory (review and promote) -- design spec

> **Status (2026-09-25):** design only, nothing in this document is built. The "today" statements and
> `file:line` references are as of `8c8231a`. Two things the first draft reported were fixed before
> any Stage 2 unit: the migration-runner race (`43dcb76`, see "Migration impact") and a stale comment
> in `diya.py` that named a promotion step that does not exist (`8c8231a`).

This is a design document, not an implementation. Nothing in the codebase changes as a result of
writing it. It covers the first item under "Trustworthy memory" in `ROADMAP.md` ("Later stages", 2):
the review-and-promote step for the facts Dreaming stages in `dream_pending.jsonl`, plus the
verification step that roadmap entry points at. Today **nothing reads the staged queue**, so a fact
Dreaming extracts never reaches the model (`docs/dreaming.md`, "Modes"; `PRODUCT_VISION.md`, "Memory
lifecycle" step 5). `ROADMAP.md`'s later-stage numbering is used as it stands; the "Stage 1" doc
(`docs/STAGE1_DESIGN.md`) borrowed its name from a request, this one takes it from the roadmap.

Not covered here: retrieving facts by relevance (embeddings over facts), the model reconciling
contradictions on its own, connectors, and deleting a person's data from every place it was copied
(section 3, D9, says exactly what "forget" does and does not do).

How this was checked. Every claim about current behaviour was checked against the code in this repo
today, not recalled: file and line references point at what is there. Four questions the design
depends on were answered by running scratch experiments on this machine (Windows 11, Python
3.13.4), on temporary files only; their numbers are in section 3, D1 and section 4. The live
`dream_pending.jsonl`, `user_profile.txt`, `dream_log.txt` and `diya.db` were measured for **counts
only** (sizes, record and fact counts, line counts); none of their content is quoted here. Every
example fact below is fictional.

## 1. Where things stand today

### 1.1 The pipeline as built

| Step | Code | What it does today |
|---|---|---|
| Select input | `dreaming.py:120-131` | Reads messages newer than the checkpoint (`dream_state.json`), across all threads. Only `role == "user"` messages go to the model (`:124`, `:157`). |
| Extract | `dreaming.py:159-178` | One prompt to `config.model` (default `qwen2.5:3b`): new facts as short bullets, or exactly `NONE`. The model never sees the profile. |
| Stage | `dreaming.py:185-209`, `_append_pending` `:96-114` | One JSON line: `{timestamp, first_message_id, last_message_id, model, facts[]}`. Each `facts` entry is a reply line, stripped, **bullet marker included** (`"- has a cat named Pixel"`). Flushed and `fsync`ed, then the checkpoint moves. |
| Repair | `_find_staged` `:90-94`, used at `:138-150` | A record whose `first_message_id` equals the next batch's means "staged, died before the checkpoint moved": only advance the checkpoint. |
| Read back | `staged_batches` `:67-88` | Skips torn or corrupt lines; requires integer (non-bool) ids with `last >= first`. It does **not** look at `facts`: a record with a missing or non-list `facts` is returned as well-formed. |
| Consume | -- | Nothing. |
| What the model sees | `diya.py:409-427` | `user_profile.txt`, read on **every turn** (UTF-8, `errors="replace"`), as one system message: `What you know about the user so far:\n<text>`. It is the only reader of that file; the only code that writes it is `direct` mode (`dreaming.py:211-223`) and the `save_profile` helper (`dreaming.py:52-54`), which nothing outside tests calls. |

Six properties of this design have to survive Stage 2. Each is a constraint, not a preference.

- **P1. The queue is append-only evidence.** `_find_staged` needs a staged record to *stay* in
  `dream_pending.jsonl`: if review removed it in the window between staging and the checkpoint, the
  batch would be extracted a second time. Review never edits, truncates or deletes the queue.
- **P2. Extraction stays extraction-only.** The extractor never sees existing facts or review
  decisions (`dreaming.py:152-156`: two measured "rewrite the whole profile" attempts silently dropped
  real facts). All filtering happens downstream of it.
- **P3. Only the user's own words are extractor input, and tool output cannot become one.**
  `dreaming.py:124` filters to `role == "user"`; the app only ever saves user text and the final
  assistant answer (`diya_web.py:320,328`; the terminal chat does the same, `diya.py:539,549`), while
  tool results live only in the in-memory list (`diya.py:490-501`). So a web page or file listing fetched by a tool never reaches the extractor.
  What *can* reach it is anything the user pastes into a chat (section 2, T2).
- **P4. Staged facts never reach the model.** Pinned by `tests/test_dreaming.py:280-289`. After Stage
  2 it reads "*only accepted* facts reach the model".
- **P5. The checkpoint means "extracted through message N", not "reviewed".** Review never touches
  `dream_state.json`.
- **P6. The model sees one shape.** A single system message with the header above
  (`diya.py:425`), merged with the fact-share instructions when there is one (`diya.py:437-443`).
  Tests pin the exact string (`tests/test_agent.py:185`, `tests/test_web.py:144`,
  `tests/test_text_files.py:53`). Changing what is *in* the facts is Stage 2's job; changing the
  shape around them is not.

### 1.2 What the live data looks like (counts only, 2026-09-25)

| | |
|---|---|
| Staged queue | 2 records, 4 facts, 461 bytes, no torn lines; one model (`qwen2.5:3b`); ranges ascending and disjoint; both staged on one day (2026-09-21), none in the four days since |
| Facts per record / length | 2 / 35-53 characters; every fact starts with `- `; none ends in `:`; none is 12 characters or shorter; no repeats |
| Profile | 7 lines, 331 characters, all `- ` bullets, LF only |
| Dreaming log | 211 cycles, among them 193 "nothing new", 10 "no genuine new facts", 2 staged, and 3 `direct`-mode appends (the original behaviour, `diya_config.py:19-22`); 0 errors |
| Database | 35 threads, 179 messages (90 from the user), migrations `[1]`; the checkpoint (179) equals the highest message id, so extraction is caught up |
| Scheduled task | `Diya_Dreaming`: `pythonw.exe`, working directory the repo, every 30 minutes, state Ready, last result 0 |

What this says: **volume is not the problem.** Two batches, four facts, is a list a person reads in a
minute; nothing in Stage 2 needs pagination, ranking or bulk actions to be usable. What this cannot
say is how good the extractions are: four facts is a measurement of volume, not of quality. During
`direct`-mode use the profile once collected lines that were not facts about the user and had to be
cleaned by hand (a one-word acknowledgement, a weather query); that is why staging exists, but it is
not reproducible from the repo, and there is no rate to quote. The design therefore does not assume
the extractor is good or bad; it makes each promoted fact something a person has looked at.

### 1.3 How the pieces are deployed (it matters for rollout)

- The API (`diya_web.py`) is a long-running process: it does not pick up code changes on disk
  until restarted.
- Dreaming is a **fresh process every cycle**, so it runs whatever is in the working tree, at the
  next :13 or :43, before any push and without anyone restarting anything. Landing a commit that
  changes `diya_db.py` therefore changes what runs against the live `diya.db` within half an hour.
- Both call `Store.connect()`, which calls `apply_migrations` on every connection
  (`diya_db.py:119-122`). A schema change is applied by whichever process connects first.

## 2. Threat and failure model

Everything in `dream_pending.jsonl` is model output produced from what a person typed, possibly
pasted from somewhere else. A fact that is promoted becomes part of the **system message of every
future thread**, which is the most trusted place in the prompt. That asymmetry is the whole design.

| # | What goes wrong | How it gets in | Today | Stage 2 answer |
|---|---|---|---|---|
| T1 | A non-fact, invented fact or wrong attribution is remembered ("ok"; a fact the user never said) | The extractor is a 3B model; the prompt asks for "people/pets/things mentioned" (`dreaming.py:161`), so facts about *other* people are in scope by design | Contained only because nothing reads the queue | A person accepts each fact; deterministic checks show where the evidence is (D5); every fact keeps the message range it came from (D3) |
| T2 | **Memory poisoning**: the user pastes an email or page containing instructions; the extractor turns one into a "fact"; once promoted it steers every later chat | Pasted text is user text (P3) | Same containment | The human gate is the defence; the review shows the fact **next to the user messages it came from**, and flags instruction-shaped text (D5). Honest limit: a fact phrased as a plain statement can pass |
| T3 | The review screen is itself attacked: terminal escape sequences or bidirectional controls in a fact hide or rewrite what the reviewer reads; HTML in a web review page | Fact text is model output | -- | Control characters are stripped at ingest, before storage (D4); the CLI prints what is stored; the UI renders text, never HTML (U6) |
| T4 | Unreviewed text reaches the trusted store | Any code path that writes it. `DIYA_DREAM_PROFILE_MODE=direct` is one today (`dreaming.py:211-223`) | Off by default, but the option exists | Decided in D8; a test that nothing but `accept` and the legacy import ever creates an `accepted` fact |
| T5 | The trusted store is torn or lost in a write | Two processes, one file, on Windows | Not reachable today (nobody writes it in staged mode) | Measured in D1: rewriting a file in place is unsafe here, atomically replacing it is unreliable. The design does not use a file for this |
| T6 | Unbounded growth: the profile is sent on **every** turn to a 3B model | Nothing limits it | 331 characters today | Per-fact and total caps, enforced when a fact is accepted, never by silently truncating on read (D7) |
| T7 | No way back: a wrong fact was promoted, or a true one changed | -- | -- | Retire and restore, each recorded (D3, D9) |
| T8 | Privacy: a distilled fact is more sensitive than the chat it came from | -- | The extracted text is also printed into `dream_log.txt` (`dreaming.py:208-209`) | Stays local; Stage 2 adds no new copy of fact text outside `diya.db` and prints ids, not text, in its own logs. It does not remove the copies that already exist (D9) |

**What this design does not defend against, by intent:** a user who accepts a bad fact (the gate is
only as good as the person at it); a process with read/write access to the files on disk (Stage 1's
token protects the API, not `diya.db`); a compromised local model.

## 3. Design

Each decision below lists the options, the tradeoff, and a recommendation. Ten are listed; section 5
collects the ones that need an explicit yes.

### D1. Where accepted facts live

The model reads its facts on every turn, from `Agent.with_profile`, while a second process may be
writing them. So the question is what makes that safe.

- **A. Keep `user_profile.txt` as the trusted store.** Promotion appends or rewrites it. Smallest
  change (`with_profile` untouched, `direct` mode keeps working, a person can read it in a text
  editor). But a fact is only a line of text: no identity, no provenance, retiring one means
  rewriting the file.
- **B. SQLite tables in `diya.db`.** One row per fact, with status, provenance and an event trail;
  `with_profile` renders the accepted rows into the same message. Both processes already use the
  database; transactions make a decision atomic. Costs: a migration, a change to what the model's
  input is read from, and the old file stops being the source.
- **C. Append-only file, never rewritten.** Safe against the race below, but a wrong fact could then
  never be removed, which is T7.

The scratch experiments (temporary files, 4 reader threads reading as fast as they can for 3 seconds,
which is far heavier than one chat turn every few seconds, so read them as *which mechanisms fail*,
not *how often*):

| Question | Result on this machine |
|---|---|
| Replace the profile with `os.replace` while a reader has it open (`with_profile` does, briefly) | **Fails**: `PermissionError` (WinError 5) while a reader holds the file open through Python's `open()`, the same call `with_profile` makes. Works once the reader closes it |
| Rewrite in place (`open(path, "w")`: truncate, then write) while readers hammer it | **1,199 of 2,869 reads saw an empty file**, 0 saw a partial one. `with_profile` treats an empty file as "no profile" (`diya.py:423`), so the turn silently goes ahead without any memory |
| `os.replace` with a 50-try, 5 ms retry loop under the same hammer | 4 of 11 replacements succeeded, 7 gave up; no reader saw a bad file. A retry loop *usually* works and cannot be made to *always* work, which adds a new way for a promotion to fail |
| SQLite as `Store` uses it (fresh connection per call, default settings), writer replaces all 40 rows in one transaction | 341 rewrites against 524 reads: **0 wrong-sized reads, 0 errors on either side** |

**Recommendation: B.** It is the only option that supports the requirements of a memory people are
meant to trust (provenance, retract, an audit trail, no torn reads) without a new failure mode in the
write path. The price is a real one: `user_profile.txt` stops being edited by hand. D8 covers what
happens to the existing file, which is left untouched.

### D2. The queue stays the producer's outbox; review pulls from it

- **Recommended: a separate, idempotent ingest step** copies staged facts into the database as
  *candidates*, keyed by `(first_message_id, position in the record's facts list)`. Dreaming is not
  edited at all: ingest reuses `Dreamer(config).staged_batches()` (constructing a `Dreamer` touches
  nothing; pinned by `tests/test_dreaming.py:150`), so the tolerant reader stays in one place.
  `dream_pending.jsonl` remains what P1 says it is: the immutable record of what the model produced.
  Raw output is evidence; decisions are state; they live in different places.
- **Rejected: Dreaming writes candidates straight into the database.** One store instead of two, but
  it rewrites the producer's crash-safe ordering (stage, fsync, then checkpoint; `dreaming.py:198-206`),
  which the 39 test functions in `tests/test_dreaming.py` pin, for no gain in trust.
- **Rejected: review edits or deletes queue records.** Breaks P1.

Ingest runs when the reviewer looks (the CLI, and later the API), not on a schedule. No third
scheduled job.

### D3. Data model and lifecycle

Two tables, added as migration 2 (the migrations system, `diya_db.py:12-104`, exists for exactly this;
a shipped migration is never edited, so this is a new entry). Sketch; final names are settled in U1:

```
facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,        -- one line, normalised: what the model would see
  status TEXT NOT NULL,      -- candidate | accepted | rejected | retired
  source TEXT NOT NULL,      -- dreaming | legacy_profile | manual
  batch_first INTEGER, batch_last INTEGER,   -- message-id range it was extracted from
  position INTEGER,          -- index in that queue record's facts list
  model TEXT, extracted_at TEXT,             -- from the queue record
  raw TEXT,                  -- the line exactly as staged, before normalisation
  flags TEXT NOT NULL DEFAULT '[]',          -- advisory checks (D5), JSON
  created_at TEXT NOT NULL
)
-- UNIQUE (batch_first, position) for source = 'dreaming': makes ingest idempotent
fact_events(id, fact_id, event, actor, at, detail)  -- append-only
-- event: ingested | edited | accepted | rejected | retired | restored | reopened | added
```

Transitions (nothing else is legal; an illegal one raises and changes nothing):

```
candidate --accept--> accepted --retire--> retired --restore--> accepted
candidate --reject--> rejected --reopen--> candidate
(edit is allowed on a candidate; add creates a manual fact already accepted)
```

Every transition is **one transaction** that changes the status and appends the event, so the two can
never disagree. Two things the implementation must not assume: SQLite here does not enforce foreign
keys (nothing in `diya_db.py` sets `PRAGMA foreign_keys`), so integrity is checked by tests and
queries, not by the engine; and two processes can interleave, so a decision starts with `BEGIN
IMMEDIATE` (check-then-write inside the lock), which is what makes the size cap in D7 hold under
concurrency.

*Events table or status column only?* The events table costs one more table and one more insert per
decision. What it buys is the answer to "why does Diya believe this, and who changed it": the
inspectable-memory claim `RESEARCH.md` (entries 1 and 4) says is the point of difference. Recommended;
it is also the cheapest thing to cut if the owner wants less, because `status` alone is still correct.

### D4. Normalisation and sanitising at ingest

Applied once, when a staged line becomes a candidate. `raw` keeps the original.

- Strip one leading list marker (`-`, `*`, a bullet character, `1.`, `1)`), trim, collapse runs of
  whitespace to one space.
- **Remove control characters**: C0/C1 (including ESC), bidirectional overrides and isolates, zero-width
  characters, U+2028/2029. This is what makes T3 testable: no stored fact can carry a terminal escape.
- A line that is empty after that, or is `NONE`, is skipped and counted in the ingest report (the
  queue still holds it). Nothing else is dropped.
- A line that ends in `:` or begins like a preamble ("Here are...", "New facts") is **kept and
  flagged**, not dropped: hiding a line is a decision, and this stage's decisions are recorded.
- Over-long (proposal: 200 characters) is kept and flagged; it cannot be accepted until edited to fit.

### D5. Verification

The roadmap names the solver/verifier separation (`RESEARCH.md`, entry 6: Apodex) as the reference.
What is borrowed is the structure: **the component that proposes a fact is not the one that admits
it, and nothing enters trusted state on the proposer's say-so.** What is not borrowed is any result:
that entry itself says Apodex's evaluation method is unchecked. Here the proposer is Dreaming's
extractor. The options for the checker:

- **A. Human only.** Simple. Loses the evidence that makes a fast, accurate review possible.
- **B. Human plus deterministic checks that only annotate.** Code, no model, reproducible, testable
  against a fixed set. A check never changes a status.
- **C. B plus a second model call that judges each fact against its source, allowed to reject.**
  The verifier shares the extractor's weights (there is one local model), so its errors are
  correlated with the extractor's, and a false "no" would silently bury a true fact. Rejected.
- **D. B plus the same second call, advisory only, shown next to the human's controls, and measured.**
  Deferred to U7.

**Recommendation: B for Stage 2; D later, only once B has produced human decisions to measure it
against; C never.**

The checks, all computed against the user messages in the fact's own batch range (the exact input the
extractor saw, `dreaming.py:157`), stored in `flags`:

| Flag | Method | Catches | Misses |
|---|---|---|---|
| `ungrounded` | Share of the fact's content words (stop-words removed, lower-cased) that appear in the batch's user messages | Invented facts | A correct paraphrase ("owns a feline") is a false positive; a true-but-misattributed fact passes |
| best source | The single user message with the highest overlap, stored as a message id and shown beside the fact | Nothing: it is provenance | -- |
| `duplicate` / `similar:<id>` | Normalised equality, then content-word overlap, against accepted and open facts | Repeats; likely updates of an existing fact | Same meaning in different words; contradictions are not detected, only surfaced beside the new fact |
| `previously_rejected:<id>` | Equality with a rejected fact | Re-proposals | -- (shown, never auto-closed: the same words can be true later) |
| `instruction_shaped` | Patterns: "always", "never", "ignore", "from now on", "you must", role-like prefixes ("system:", "assistant:"), a URL, a code fence | Crude injection | Anything phrased as a plain statement |
| length / shape | D4 | Rambling extractions | -- |

The thresholds are **not** fixed by this document. U3 sets them from a written-down labelled set of
fictional cases, and the test asserts the precision and recall it measured, so a change of threshold
is a visible change.

Because the extractor is given every user message in the batch at once (`dreaming.py:157`), a fact
cannot be traced to one message with certainty. What is stored is a message range (certain) and a
best-matching message (a computed guess, labelled as one).

### D6. Review surface: a command line first, then the API and UI

- **Recommended order: CLI (U4), switch (U5), HTTP and UI (U6).** The rules that matter (state
  machine, budget, sanitising, provenance) live in one module used by both surfaces; the CLI proves
  them with no HTTP, token or browser in the way, the same "mechanism first, surface later" order
  Stage 1 used for the token. Commands: `ingest`, `list`, `show <id>` (the fact, its flags and the
  source user messages), `accept`, `reject`, `edit`, `retire`, `restore`, `add`, `export`,
  `import-profile`. Commands, not prompts, so tests can drive them. No model and no network.
- **The UI is the eventual home** (the daily surface is the browser), so U6 is planned, not
  optional. What it adds: `GET /api/memory` and `POST /api/memory/<id>/<action>`; same-origin routes
  in `frontend/app/api/memory/`; a page at `frontend/app/memory/`. **Only GET and POST**: CORS allows
  no other method (`diya_web.py:264-269`), and the browser only ever talks to the UI's own routes
  anyway (Stage 1, unit 4). Every new route is covered by the token middleware without a line of
  code (`diya_web.py:102-141` wraps the whole app), and `tests/test_token.py:163` fails until the new
  routes are added to its endpoint list (and its `{thread_id}` substitution learns the new path
  parameters), so the inventory cannot drift.

### D7. What reaches the model, and how much

- Same message, same shape (P6): `What you know about the user so far:\n- <fact>\n- <fact>`, only
  `accepted` facts, oldest first. Nothing else is rendered: not candidates, not rejected, not
  retired.
- **Budget, enforced when a fact is accepted.** Proposal: 200 characters per fact and 2,000 in total
  (about 500 tokens by the usual four-characters-per-token rule of thumb; an estimate, not measured
  with this model's tokenizer). The profile today is 331 characters. An accept that would exceed the
  total is **refused with a message that says why**; nothing is ever truncated silently on read. How
  Ollama truncates an over-long prompt for this model was not verified here, which is one more reason
  not to find out by accident. The numbers are starting points to tune, not findings.
- A database that cannot be read fails the turn, as it already does at `get_history`; this adds no
  new failure mode. The read is one more query on a connection that is already opened per call.

### D8. The old file and `direct` mode

- **`user_profile.txt` is imported once, never modified.** Its lines become `accepted` facts with
  source `legacy_profile`, exempt from the total cap (an existing profile is not thrown away because
  the limit is new; going over only blocks *new* accepts). The import is idempotent, transactional
  (all lines or none), tolerates the same encodings `with_profile` does (`tests/test_text_files.py`),
  and runs at API start with a visible one-line message, the same first-run pattern as the token. It
  must happen **before** `with_profile` stops reading the file, or the model silently loses its
  memory at the switch; U5's tests pin that ordering.
- **`DIYA_DREAM_PROFILE_MODE=direct`: recommend retiring it** at U5 with a clear configuration
  error, because after the switch it would append to a file nothing reads, and because it is the one
  code path that violates the premise of the stage (T4). The alternative is to make it write
  `accepted` rows with source `direct`; that keeps the option, and keeps a bypass. The mode is
  documented as compatibility only (`diya_config.py:19-22`). This removes an option, so it needs the
  owner's explicit yes.

### D9. What "retire" means, honestly

Retiring removes a fact from what the model sees, immediately (the next turn), and is reversible
(`restore`). It does not erase the fact from: the staged queue (P1), `dream_log.txt`, or the message
history it was extracted from. A true "forget this" has to reach all four places and is out of scope
here; saying so plainly is the point. Stage 2's own logs print fact **ids**, not text.

### D10. No automatic promotion

Nothing is promoted without a person accepting it, in this stage. A verifier that has been measured
against real human decisions could later justify *sorting* or *pre-selecting*; deciding that belongs
to a later document with those numbers in it.

## 4. Rollout plan

### Implementation order

Each unit lands as its own commit (or short sequence), tested and mutation-checked on its own, as in
Stage 0 and Stage 1. Order matters for one reason: **U5 is the only unit that changes what the model
sees**, and it must not land before what feeds it (import, checks, a way to review) exists.

| Unit | What | Files | Changes for the live system |
|---|---|---|---|
| U1 | **Storage.** Migration 2 (`facts`, `fact_events`); the state machine, budget and events as one module used by everything after | `diya_db.py`, new `diya_memory.py` | Two empty tables appear in the live `diya.db` the first time any process connects (see "Migration impact"). Nothing reads them |
| U2 | **Ingest and legacy import.** `normalise_fact`, `ingest_queue`, `import_legacy_profile` | `diya_memory.py` | Nothing, until someone runs it. Writes only to `facts`; queue, checkpoint, log and profile are byte-compared unchanged in tests |
| U3 | **Deterministic checks.** The flags in D5, a labelled fictional set, a read-only `Store.get_messages_between` | `diya_memory.py`, `diya_db.py` | Nothing |
| U4 | **Review CLI.** `diya_review.py` | new file, `docs/dreaming.md`, `README.md` | Nothing until run. First point at which a person can accept a fact; still no effect on the model |
| U5 | **The switch.** `Agent.with_profile` renders accepted facts; the legacy import at API start; the `direct` decision; the profile comment at `diya.py:416-420`, which will need rewording again once the file is no longer read; docs | `diya.py`, `diya_web.py`, `diya_config.py`, `docs/*`, `README.md`, `PRODUCT_VISION.md`, `ROADMAP.md` | **The API must be restarted.** The first start prints the import line. Accepted facts reach the model from then on |
| U6 | **HTTP and UI.** Endpoints, same-origin routes, the page, failure messages in the `describe*Failure` style | `diya_web.py`, `frontend/app/api/memory/*`, `frontend/app/memory/`, `frontend/lib/*`, `tests/test_token.py` | UI restart; a "facts waiting" badge is a follow-up |
| U7 | **Advisory model verifier**, gated. Only after U1-U6 have produced decisions to measure against; a case set in `diya_evals.py` (needs Ollama), not pytest | `diya_memory.py`, `diya_evals.py` | Adds a flag; never a status change |

Dreaming (`dreaming.py`) is not edited by any unit.

### Migration impact

- **The live `diya.db` (35 threads, 179 messages) changes when U1 lands in the working tree, not when
  it is pushed.** The scheduled Dreaming process connects at :13 and :43 and runs live files (1.3), so
  it applies migration 2 first. The change is additive (`CREATE TABLE IF NOT EXISTS`, no existing
  table touched), and the running API is unaffected because it ignores tables it has never heard of.
  Per the Stage 0 method, U1's migration is run against a **copy** of the live database first and
  the rows compared, before the commit exists.
- **A race in the migration runner, found while checking this, and fixed first (`43dcb76`).** The
  runner had no lock and its `INSERT INTO migrations` was not idempotent. Measured with two
  simultaneous migrators on a fresh scratch file and a stand-in second migration: **5 of 150 rounds
  with threads, and 9 of 120 with two real processes, one of the two raised `IntegrityError: UNIQUE
  constraint failed: migrations.version`**; the resulting database was correct every time. In
  practice, the first time the API (or the CLI) and the scheduled Dreaming process connected in the
  same instant after a new migration, one of them would have failed once (Dreaming logs a traceback
  and exits 1; an API request returns 500). It now takes the write lock first, looks again under it
  and applies what is left in one transaction (`diya_db.py:44-104`); an up-to-date database still
  never asks for the lock. Re-measured: 0 failures in 120 real-process rounds, and a copy of the live
  `diya.db` is byte-identical after connecting through the new runner.
- **Nothing here deletes anything.** No unit deletes rows from `diya.db`, or touches
  `dream_pending.jsonl`, `dream_state.json`, `dream_log.txt` or `user_profile.txt`. Rows change status;
  they are not removed. The standing rule about showing exact rows before any delete from the live
  database is never triggered.
- **Rollback.** U5 reverts cleanly: the profile file was never modified, so pre-existing facts are
  intact. Facts accepted after the switch live only in the database, so `export` (U4) prints the
  accepted facts in `user_profile.txt`'s own format, which doubles as a readable backup and a way to
  inspect exactly what the model is being given. The two extra tables stay, unused.
- **Tests that change at U5** (they assert injection through the profile *file*): `tests/test_agent.py`
  (167-185), `tests/test_dreaming.py` (280-289), `tests/test_text_files.py` (42-86) and
  `tests/test_web.py` (~144). Five other test files only point `profile_path` at a temp file to isolate
  themselves and need no change if the setting stays (it does: the import reads it).
- **After U5:** restart the API. The `DIYA_TOKEN` step from Stage 1 is unchanged.

### Test strategy per unit, and what each kills

Every unit ships with mutation-checked tests, as in Stage 1: a mutation that survives is a gap. The
strongest cases are named.

1. **U1, storage.**
   - Migration 2 on a fresh database, on one frozen at the version-1 shape, and on a current one
     (the pattern in `tests/test_migrations.py`), with existing rows byte-identical. *Kills* a
     migration that edits migration 1 or rewrites data.
   - The runner's concurrency is already pinned by `tests/test_migrations.py` (`43dcb76`). U1 re-runs
     the real-process check (two interpreters, one file) with the real migration 2, and applies it to
     a copy of the live database first, rows identical. *Kills* a migration 2 that is not safe to
     apply from two places at once.
   - A parametrised matrix of every state against every action: legal ones work, illegal ones raise
     and change nothing. *Kills* a missing guard (accepting a rejected fact, retiring a candidate).
   - After any sequence of actions, every fact's `status` equals its last event's outcome and every
     fact has at least one event; a failure injected between the two writes leaves neither applied.
     *Kills* a non-transactional implementation.
   - Two connections accept two candidates when only one fits the total cap: exactly one succeeds.
     *Kills* check-then-write without `BEGIN IMMEDIATE`. Boundaries: exactly at each cap is accepted,
     one over is refused with a message.
   - `accepted` rows only, in id order, are what the rendering function returns. *Kills* a dropped
     status filter.
2. **U2, ingest and import.**
   - Run twice, then again after the queue grows: same rows, then only the new ones. *Kills* a missing
     uniqueness key.
   - The queue, checkpoint, log and profile are byte-identical after ingest **and Dreaming's own next
     cycle still finds the record with `_find_staged`**. *Kills* any write to the queue (P1).
   - Malformed input: a torn line, a non-object, missing or non-list `facts`, non-string items, a
     boolean id, a 1 MB fact, NUL, ESC sequences, bidi controls, U+2028. Nothing crashes; no stored text
     contains a control character. *Kills* unsanitised storage (T3).
   - A table-driven normalisation test (`- x`, `* x`, `1. x`, a bullet character, padded, `-`, `NONE`,
     a preamble line). *Kills* bullet handling that drops or keeps the wrong thing.
   - Legacy import: idempotent, the file byte-identical afterwards, CRLF, BOM and a stray non-UTF-8
     byte tolerated (the cases in `tests/test_text_files.py`), an unreadable file imports nothing at
     all, and an import larger than the cap succeeds while a new accept is then refused. *Kills* a
     partial import and a cap applied to existing facts.
3. **U3, checks.**
   - A written-down fixture of fictional cases (supported, paraphrased, invented, instruction-shaped,
     duplicate, previously rejected) with the measured precision and recall asserted. *Kills* a moved
     threshold, an emptied stop-word list, a matcher that compares the fact with itself.
   - A batch whose only matching text is an *assistant* message is `ungrounded`. *Kills* a role
     filter that was dropped.
   - After every check runs, no fact's status has changed. *Kills* a helpful auto-reject (D5, D10).
4. **U4, CLI.**
   - Driven as a subprocess against a temporary database with the model deliberately unreachable
     (`DEAD_OLLAMA`, as `tests/test_dreaming.py` does). *Kills* an accidental model or network
     dependency.
   - A fact containing ESC and bidi characters prints without them; `show` prints the batch's user
     messages; acting on an id that does not exist, or twice, fails with a non-zero exit and changes
     nothing. *Kills* raw printing and silent success.
5. **U5, the switch.**
   - A candidate, a rejected and a retired fact are absent from the system message; an accepted one
     is present. Updated `test_the_agent_never_sees_staged_facts` (P4). *Kills* a status filter that
     let a candidate through.
   - The rendered string equals today's byte for byte for the same facts, and a database with no
     accepted facts returns the history object unchanged (`tests/test_agent.py:167`). *Kills* an
     accidental change of shape (P6); the fact-share merge test (`tests/test_fact_share.py`) stays
     green.
   - End to end through `create_app` with a recording fake model (the `tests/test_web.py:144` style):
     the accepted fact is in what the model receives, the staged one is not.
   - A profile file with content and no import yet: the API start imports it or refuses to start with
     a message; it never starts silently without the memory it had. *Kills* the ordering bug D8 names.
   - `direct` mode behaves as decided in D8, with a test.
   - Live check as in Stage 1: a real API on a spare port with scratch data, accept a fact through the
     CLI, see it in the next real request's system message.
6. **U6, HTTP and UI.** The token test's endpoint list includes the new routes (it fails until it
   does); the proxy routes are tested the way `tests/test_frontend_proxy.py` tests the existing four
   (the browser never holds the token; a 401 is reported as a token problem, not "the server didn't
   answer", per `frontend/lib/api-failure.mjs`); a fact containing markup renders as text; a
   design-rig scenario and a real-browser check for the page.
7. **U7, verifier (only if built).** The verifier's prompt contains the fact and its source messages
   and nothing else (no other facts, no extractor output); an unreachable model yields a flag, not an
   error; a verdict never changes a status. Measured on the labelled set through `diya_evals.py`, and
   later against the human decisions in `fact_events`.

## 5. Limits, open questions, and what needs a yes

**Limits, said plainly.**

- The checks are lexical. They find invented facts better than they find subtle ones, they flag good
  paraphrases, and they cannot detect a contradiction; they only put the similar existing fact next to
  the new one.
- A verifier built on the same local model shares its blind spots (D5, option C). Separation by role
  and context is a weaker guarantee than separation by model, and Apodex's own results are not relied
  on (`RESEARCH.md`, entry 6).
- Provenance is a message range plus a computed best match, not a certainty (D5).
- The evidence here is small: 4 staged facts in total. Nothing in this document is a measured
  extraction-quality claim. The caps and thresholds are proposals until U3 and real use say otherwise.
- The database is one file in a folder that is cloud-synced in the reference deployment, with no
  backup story beyond the sync's own history. That was true before Stage 2; it matters more once the
  accepted memory lives there. `export` (U4) is the manual copy. A proper backup is not in this stage.
- `Truffle`'s Dreaming (`RESEARCH.md`, entry 1) is closed-source and its availability is unverified;
  this design does not claim parity with its internals, only the same shape (consolidate on the
  device) with a review gate and an audit trail.

**Not verified here.** How Ollama truncates an over-long prompt for `qwen2.5:3b`; the token cost of
the proposed 2,000-character budget with this model's tokenizer; the SQLite result on a
cloud-synced folder under real sync activity (the scratch database was in a temporary folder);
behaviour on Linux (CI) for anything in the Windows file experiments, which do not matter to the
recommended design but were not run there.

**Decisions for the owner.**

| # | Decision | Recommendation | If not |
|---|---|---|---|
| D1 | Accepted facts live in the database, not `user_profile.txt` | Yes (B) | Keep the file (A): a smaller change, but retire means rewriting a file another process reads, which fails on this machine as measured |
| D3 | Keep an append-only events table | Yes | Status column only: less to build, no answer to "who changed this" |
| D6 | CLI first, then API and UI | Yes | UI first: one surface, but the HTTP, token and browser work lands before the rules are proven |
| D7 | 200 characters per fact, 2,000 in total, refused not truncated | Yes, as tunable starting points | Different numbers; the mechanism does not change |
| D8 | Retire `DIYA_DREAM_PROFILE_MODE=direct` at U5 | Yes | Redirect it into accepted rows: keeps the option and keeps a bypass |
| D10 | No auto-promotion in this stage | Yes | -- |
