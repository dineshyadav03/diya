# Research index

Dated market and technical signals that bear on Diya. Each entry records what was noted, why it
matters and what it implies. Figures and claims are as noted from the source on the date shown and
are not independently re-checked unless an entry says so; anything labelled a caveat or
"unverified" is exactly that. This file is context for decisions, not a statement of what Diya
does today (the [README](README.md) and [PRODUCT_VISION.md](PRODUCT_VISION.md) are that).
Stage numbers refer to the [roadmap](ROADMAP.md).

## Entries

### 1. Truffle

- **Source:** https://truffle.net/
- **Noted:** 2026-09-21
- **What it is:** The closest comparable. Truffle-1 is a local appliance with on-device memory and a
  nightly "Dreaming" consolidation, $1,299 ($500 preorder), closed-source.
- **Caveat:** preorder page looks stale (says shipping Q2 2024, 24/50 sold) - availability unverified.
- **Why it matters for Diya:** it addresses the same problem, memory that consolidates on the
  device. Diya's staged JSONL, with a checkpoint that only advances on verified writes, is an
  auditable answer to it.
- **Action:** keep the staged queue and checkpoint design inspectable, and treat auditability as the
  difference from Truffle. Do not cite Truffle-1 as a shipping product until availability is checked.

### 2. Instinct

- **Source:** https://instinct.com
- **Noted:** 2026-09-21
- **What it is:** Invite-only personal AI on iMessage and calls. A cloud computer connected to
  email, calendar and messages takes real-world actions. Fully cloud.
- **Why it matters for Diya:** the experience vision is nearly identical to Diya's: one
  conversation, durable outcomes. Launch-week criticism (retained data, an unapproved email,
  prompt-injection via email) maps to Diya design requirements: a prompt-injection boundary, an
  authority model for actions, and provable data ownership.
- **Action:** carry those three into the Stage 0 and Stage 4 work, and make them public claims, not
  only hygiene (see cross-cutting note 3).

### 3. Perplexity Computer

- **Source:** https://www.perplexity.ai/hub/blog/introducing-perplexity-computer
- **Noted:** 2026-09-21
- **What it is:** Launched Feb 2026. A cloud "digital worker": describe an outcome, it spawns
  sub-agents with their own compute and runs for hours. Multi-model orchestration (Opus for
  reasoning, Gemini for research).
- **Why it matters for Diya:** it is the opposite of Diya's one-local-model constraint.
- **Action:** do not chase multi-model routing. It is a capital play and the wrong game for Diya.

### 4. Meta Muse

- **Source:** https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/ (Reuters report on
  internal testing: https://www.reuters.com/business/meta-launches-ai-agent-that-can-access-other-apps-send-emails-make-payments-2026-09-08/)
- **Noted:** 2026-09-21 (announced Sept 2026; internal name "Hatch")
- **What it is:** Meta's cloud personal agent on iOS, Android, web and WhatsApp. It connects email,
  calendar, payments, health and smart-home, keeps working after the app closes, and runs on a
  dedicated cloud VM per user plus a separate "Sentinel" safety agent for approvals and audit
  trails. Free tier, paid at $20/$100 per month. US-only; 83K iOS downloads in 2 days.
- **Why it matters for Diya:** (a) the category is validated at platform scale. (b) "Private and
  safe" no longer differentiates: Meta already claims VM isolation, approvals and audit trails, so
  Diya's answer must be proof: local-only data paths, inspectable memory, reproducible controls.
  Reuters reported Muse's internal testing had stalls and unauthorized data exposure - reliability
  before connectors.
- **Action:** (c) steal the ideas, not the model: approval gates, action trails and separate safety
  enforcement map to Stage 0 and Stage 4.

### 5. Equal AI

- **Source:** https://myequal.ai/
- **Noted:** 2026-09-21
- **What it is:** A consumer app that answers and manages your phone calls: screening, callbacks.
- **Why it matters for Diya:** a market signal, not a technical reference. Personal AI assistant is
  a proven consumer category, and call management is their wedge.
- **Action:** a future item for Diya: call management (see the roadmap).

### 6. Apodex

- **Source:** https://www.apodex.com/
- **Noted:** 2026-09-21
- **What it is:** A research-focused AI system that structurally separates SOLVER from VERIFIER.
  Three tiers: Deep Research, Deep Solve, Deep Discover. The pitch is "grounded, auditable
  intelligence" with each reasoning step verified.
- **Skeptic note:** "verified reasoning" is a claim, not a result - eval methodology unverified.
- **Why it matters for Diya:** same design philosophy as Diya's staged memory (nothing enters
  trusted state until verified).
- **Action:** use the solver/verifier separation as the reference for memory verification in
  Stage 2. Do not rely on Apodex's results until its evaluation method has been checked.

### 7. laya-mlx

- **Source:** https://github.com/mizorewww/laya-mlx (upstream https://github.com/NandhaKishorM/laya, on PyPI)
- **Noted:** 2026-09-21
- **What it is:** An open-source typed decision layer: probability-based classification,
  MLX/Apple silicon, about 1GB.
- **Caveats:** "50x faster than Jev" is the porter's own claim, check BENCHMARKS.md; MLX is Apple
  silicon only, so it targets the future Mac box, not the current Windows machine.
- **Why it matters for Diya:** it validates the Jev category rather than closing it. Unlike Jev
  (closed, API-only) this one is readable.
- **Action:** a free open-source baseline for the Stage 5 Jev benchmark.

### 8. OpenJev

- **Source:** Hugging Face, organisation com-kotobalabs (page URL not recorded)
- **Noted:** 2026-09-21
- **What it is:** A voice pipeline reference pattern: voice -> transcript -> tiny decision model ->
  execute. No big model in the routing loop, so decisions cost milliseconds.
- **Caveat:** Source was a social reel - specific demo unverified, pattern sound.
- **Why it matters for Diya:** Diya already has both halves (Whisper in, TTS out); the missing
  middle is the fast decider.
- **Action:** Whisper -> OpenJev/Jev decides intent -> Diya executes. "Responds before he finishes
  speaking" means streaming faster-whisper partial transcripts into the decider early.

### 9. DeepSeek-V4.1-Flash

- **Source:** https://arxiv.org/abs/2609.19969
- **Noted:** 2026-09-21
- **What it is:** A KV-cache compression signal: long context on local hardware keeps getting
  cheaper. Write-up: [docs/research/deepseek-v41-flash-kv-cache.md](docs/research/deepseek-v41-flash-kv-cache.md).
- **Why it matters for Diya:** it bears on how much context a local model can carry.
- **Action:** Not actionable; track.

### 10. supermemory (company-brain open-sourced; Jev in the memory pipeline)

- **Source:** two posts by supermemory's founder (Dhravya Shah) on X, shared with Diya 2026-09-27; the
  harness itself: https://github.com/supermemoryai/company-brain (checked live: Apache-2.0, 617 stars, a
  Slack bot on Cloudflare Workers/the Agents SDK, discontinued as a paid product and now open source).
- **Noted:** 2026-09-27
- **What it is:** (a) supermemory open-sourced their team-memory Slack bot after shutting it down as a
  product. (b) A companion post argues a class of small, fast "decision" models (their name for the
  category is Jev, already entry 8) can improve several stages of a generic memory pipeline: reranking
  search results, chunking documents, filtering what reaches the extractor, and deciding in the harness
  itself -- not the main model, not a hook -- whether a tool or a memory lookup applies at all.
- **Skeptic note:** vendor content about the vendor's own paid product; every section closes by
  recommending it. The reranking, chunking and cost figures are the vendor's own internal benchmarks,
  not independently reproduced here.
- **Why it matters for Diya:** the generic pipeline it describes (batch raw messages, extract off-loop
  on a schedule, store, inject into the harness) is, step for step, what Dreaming and Stage 2 already
  do (`dreaming.py`'s checkpoint batches, the scheduled cycle, `facts`, one system message of accepted
  facts) -- this validates the existing design rather than adding to it. Its harness-level
  decision-gating idea (a fast model deciding whether memory or a tool applies, instead of a hook or
  the main model) is the same shape of problem `diya_intent.py` already solves (fact-share detection,
  and the reminder-request guard added this session) -- in code, not a second model, because Diya has
  no cheap second model available and has repeatedly chosen determinism and measurement over a model's
  say-so on control flow (docs/STAGE2_DESIGN.md D5, docs/PROACTIVITY_DESIGN.md D9). The reranking and
  chunking findings solve a scale problem (many documents, a vector index) that Diya's 2,000-character
  profile and single-file `search_notes` lookup does not have.
- **Action:** measured, not assumed -- `python diya_gate_bench.py` runs `diya_intent.py`'s checks and the
  local model on the same labelled cases (`docs/GATE_BENCHMARK.md`, 2026-09-27). The model was worse at
  both: it said no to every one of 12 genuine fact-shares (0 of 12; the code check gets 47 of 47), and
  was net worse at reminder requests too (57 of 71 against the code's 61), though it did recover 5 of 6
  of the code check's own documented blind spots there. No new build: keep `diya_intent.py`'s checks as
  the reference. Do not adopt Cloudflare Workers, a vector database or a reranker: wrong stack (Diya is
  Python/SQLite/local; `company-brain` is TypeScript/Cloudflare/multi-tenant) and wrong scale, and it
  would break cross-cutting note 4. Revisit only once Diya's memory outgrows a single embedding lookup
  and a 2,000-character profile, or a faster/better model changes the gate-benchmark numbers.

### 11. Personal connector landscape (calendar, email, tasks, local smart-home, messaging)

- **Source:** current vendor documentation, checked live 2026-09-28 (Google, Microsoft Learn, Meta for
  Developers, Home Assistant developer docs, Notion, Todoist, Spotify for Developers) -- see individual
  claims below; this is Diya's own survey, not a single third-party report.
- **Noted:** 2026-09-28, ahead of Stage 3 (connectors and permissions).
- **What it is:** what a single-user, no-company, local-first app can actually reach without creating
  a new account or a business identity, and what each path costs in complexity, money or risk:
  - **Google Calendar API:** free at Diya's scale (10,000 req/min per project). A personal OAuth app
    kept in "Testing" publishing status never needs Google's verification (that only triggers at
    scale, for external users this app will never have) -- but a Testing-mode refresh token expires
    every 7 days, so the owner re-authenticates in a browser about weekly unless the app is later
    published. Calendar's own scopes are not in Google's "restricted" tier, so publishing likely needs
    only the free standard review, not the paid assessment below -- not itself checked.
  - **Gmail API:** the same free Testing-mode path works for read/send too, with the same 7-day
    refresh-token limit. The real cost only appears at *publishing*: a restricted scope (full mail
    access, `https://mail.google.com/`) requires an annual third-party CASA Tier 2 security assessment
    ($540-$1,000/year per one source) to go live for real users. For a single owner who never
    publishes, this is avoidable -- at the price of that weekly re-auth.
  - **Microsoft Graph (Outlook mail/calendar):** a free Azure app registration, OAuth against a personal
    Microsoft account via the `/common` endpoint. No CASA-equivalent found for this path. A real
    alternative if the owner uses Outlook/Hotmail instead of, or alongside, Google.
  - **Home Assistant:** fully local. A long-lived Bearer token from the instance's own profile page,
    no cloud, no OAuth, no company review of any kind -- the single closest fit to Diya's own
    "inspectable, local-only" claim (cross-cutting note 1), conditional on the owner actually running
    a Home Assistant instance.
  - **Notion:** an "internal integration" token (`secret_...`), not real OAuth -- created once, scoped
    to whichever pages/databases it is explicitly connected to. Simplest of everything here, if notes
    actually live there rather than locally.
  - **Todoist:** a personal API token from account settings, plain Bearer auth, no OAuth flow at all.
  - **Spotify Web API:** viable for exactly one real user (Development Mode allows 5 allowlisted users
    and needs the app owner to have Premium); the widely-reported 2026 lockout is about *scaling past
    that*, not about a single person controlling their own playback.
  - **WhatsApp:** the official Cloud API is built for a *new* business-verified number and phone-based
    tiers -- it does not fit "send messages from the number I already have" without business
    verification. Unofficial session-based libraries (automating the WhatsApp Web session) exist and
    are commonly used for exactly this personal case, but they are outside Meta's terms and carry a
    real account-ban risk that the plain vendor APIs above do not.
  - **iMessage:** a dead end on Windows. Apple ships no Windows client, no web inbox and no
    general-purpose message API; Messages developer products are for approved business workflows only.
- **Why it matters for Diya:** it turns "connectors" from one undifferentiated roadmap line into a
  real, priced menu. The lowest-friction, lowest-risk starting points (Home Assistant, Notion, Todoist)
  need no OAuth and no ongoing cost at all; the two most requested ones historically for this category
  of product (calendar, email) are genuinely free and low-risk too, provided Diya stays a personal,
  never-published app and the owner accepts a weekly re-auth click -- exactly the kind of "auditable,
  local, one owner" story cross-cutting note 1 already claims. WhatsApp and iMessage are the two paths
  every comparable (Instinct, Muse) leans on that Diya specifically cannot reach cleanly on this stack.
- **Skeptic note:** none of this was tested end to end against a real Google/Microsoft/Home Assistant
  account -- it is current documentation and third-party guides, not a working integration. Testing-mode
  behavior in particular (the 7-day figure, exactly when CASA applies) should be confirmed against the
  real Google Cloud console before it drives a design decision.
- **Action:** design Stage 3 (`docs/CONNECTORS_DESIGN.md`) around whichever of these the owner actually
  uses day to day -- building a connector for a service nobody opens is wasted work regardless of how
  cheap the API is.

### 12. Agent-harness tooling: UFO, the "Learn Harness Engineering" course, and backpass

- **Source:** UFO's marketing page (https://ufo.ai, thin, no real technical content) and its actual
  source, https://github.com/ufo-ai/ufo-core (checked live, Apache-2.0); the course
  https://github.com/walkinglabs/learn-harness-engineering (checked live, MIT, 16.6k stars,
  15 languages, a legitimate China-based AI-education lab's repo, unrelated to UFO despite being
  shared together); backpass, https://github.com/kunchenguid/backpass (checked live, MIT, real
  code: `bin/`, `src/`, `test/`, `templates/`), cited via a case study on the "firstmate" repo
  (linked PR, github.com/kunchenguid/firstmate/pull/5872, not independently opened).
- **Noted:** 2026-09-28, shared by the user directly (a link plus a pasted case study).
- **What it is:** three distinct things about building and tuning agent harnesses, not one signal.
  - **(a) UFO (ufo-core):** an open-source "agent operating system" for teams: `ufo.harness` /
    `ufo.runtime` / `ufo.host` packages, DBOS-backed durable turns that survive a crash, a
    SQLite-to-Postgres+S3+Redis scaling path, workspace-scoped multi-tenant rows, local vs.
    sandboxed (`--remote`) execution modes, and an "everything is an extension" plugin contract
    covering tools, connectors, sub-agents, surfaces, model providers and sandbox carriers. Its
    security model: a team member grants an agent access to *their own* connected account
    explicitly in chat, and that granting turn is itself the permanent audit record -- the agent
    never silently borrows the speaker's identity.
  - **(b) walkinglabs/learn-harness-engineering:** a real, well-regarded open-source course on
    building reliable coding agents, structured around five subsystems (instructions, tools,
    environment, state, feedback). Its "Loop Engineering" module (six primitives: automations,
    worktrees, skills, connectors, sub-agents, external state) and "Graph Engineering" module
    (nodes, edges, shared state, routing, and when a loop's own structural failures force a move to
    a graph -- parallel fan-out/fan-in, conditional rollback, human-approval nodes) are the parts
    that actually bear on Diya.
  - **(c) backpass:** a local-first CLI that reads an agent harness's own past session transcripts
    off disk and proposes evidence-gated edits to `AGENTS.md`/`CLAUDE.md` and skills: every added,
    rewritten or removed line must carry verbatim quotes from at least two distinct real sessions,
    analysis never writes on its own, and a human accepts or rejects each diff before it lands. The
    cited case study (the "firstmate" repo, roughly 48% shorter `AGENTS.md`, mostly by moving
    instructions into skills) is a linked PR, not reproduced or re-checked here.
- **Skeptic note:** UFO's own marketing page is thin; everything substantive above comes from
  reading `ufo-core`'s README directly, not the pitch at ufo.ai. UFO is fundamentally a
  multi-user/team product (workspace-scoped rows, teammates granting each other's agents access) --
  most of its surface area (multi-tenancy, Postgres/S3/Redis scaling) does not apply to a
  single-owner app. backpass is a single-maintainer project; only its own README and the one linked
  case study were checked, not independent adoption evidence.
- **Why it matters for Diya:** UFO's "the granting turn in chat is the audit record" pattern is a
  concretely reusable design input for Diya's still-undesigned Stage 4 (Muse/Instinct-style
  approval gates and action trails, cross-cutting note 3) -- more concrete than the general
  "approval gates" language entry 4 already put on the record. Even single-owner, the moment a
  connector moves past D2's read-only default to anything that writes
  (docs/CONNECTORS_DESIGN.md), modeling that upgrade as one explicit, logged, chat-visible grant
  rather than a silent settings toggle is directly reusable. UFO's durable-turn design validates
  rather than adds to something Diya already does in miniature: `dreaming.py`'s checkpoint batches
  plus atomic JSONL writes are the same crash-recoverable idea at a much smaller scale (the same
  kind of validation entry 10 found with company-brain). The course's Loop/Graph Engineering
  vocabulary is a ready-made reference for Stage 4 specifically: Diya doesn't need a graph yet
  because it has only one loop, but the course's own trigger condition for needing one -- parallel
  fan-out, conditional rollback, human-approval nodes -- is close to what Stage 4 will need once
  more than one connector exists to gate actions against. backpass's evidence-gating principle (a
  memory-file edit needs quotes from two or more real sessions, not one vibe) is a good discipline
  to hold onto for pruning Diya's own auto-memory files, independent of the tool itself.
- **Action:** no build. `CLAUDE.md` is currently short, nowhere near the token bloat backpass's own
  case study addresses, so the tool does not apply yet -- revisit only if this project's memory
  files or `CLAUDE.md` grow large enough to need pruning, and prefer its evidence-gated principle
  over its exact tooling even then. Keep UFO's grant-in-chat pattern and the course's Loop/Graph
  Engineering framing as the two concrete references to pull from when Stage 4 is finally designed
  (still deliberately not started). Do not adopt UFO itself or its multi-tenant architecture --
  Diya's single-owner, single-machine shape is a deliberate constraint (cross-cutting note 4), not
  a gap to fill.

### 13. Weekly frontier-agent research roundup (Sept 21-27)

- **Source:** DAIR.AI Academy's weekly digest, shared by the user 2026-09-28; one paper opened
  directly (https://academy.dair.ai/papers/jev-as-a-judge-accept-when-confident-escalate-when-unsure-2609.26550),
  the other nine taken as reported in the digest's own summaries, not independently opened.
- **Noted:** 2026-09-28.
- **What it is:** ten papers, mostly frontier-scale agent research (80B+-MoE attention
  architectures, multi-agent teams built from o3-mini/Claude/DeepSeek, robot task planning,
  GPU-cluster-trained memory models) that assume compute Diya's single local 3B model does not
  have. One is a direct hit: **JEV-as-a-Judge** (Li, Miao, Krishnan, Padman, Carnegie Mellon)
  benchmarks TypeSafe AI's JEV -- the same "Jev" fast-decision-judge category already tracked in
  entries 7, 8 and 10 -- against sixteen other judges and GPT-6. JEV is 277x cheaper and within 3
  points of GPT-6 on ordinary preference/factuality judgments, but 9-20 points worse whenever a
  judgment needs checking a derivation or rejecting a confidently-wrong answer -- and a cascade
  that escalates only JEV's low-confidence verdicts to GPT-6 recovers 99% of GPT-6's accuracy at
  57% of its cost.
- **Skeptic note:** the other nine papers are reported as the digest summarized them, not
  independently opened or reproduced here -- treat any specific figure from them as "as reported,"
  the same caveat as entry 9.
- **Why it matters for Diya:** the JEV paper is independent, academic confirmation of exactly what
  entry 10's own gate-benchmark already found by measurement -- a fast/cheap judge (Diya's local 3B
  model, in its case) is fine on easy calls and unreliable on anything needing real reasoning;
  docs/STAGE2_DESIGN.md's "a hint, never a decision" rule for the optional fact verifier is the same
  conclusion, arrived at independently. The portable idea, past Jev-tracking itself: "accept when
  confident, escalate when unsure" is a real pattern Diya could use anywhere the local model
  currently gives one unqualified answer with no fallback -- not by calling a paid judge (that
  breaks cross-cutting note 4), but by treating the model's own confidence, or the lack of one, as a
  signal to fall back to a deterministic check or ask the user rather than trust the first answer.
  XYEval (agents silently comply with a confident wrong hint and don't disclose it) is one more
  reason to keep Diya's own tool-calling loop logged and its refusals visible, consistent with Stage
  3's D3 and the reminder-refusal behaviour already in place.
- **Action:** no build. Track HySparse2 / WFM / GAVEL / SIFT / Harness-Zero / ScientistTwo /
  Self-Organizing-Teams / EvoOntology as general frontier-agent research; none of it is actionable
  at Diya's scale (cross-cutting note 4). If Stage 2's verifier, or a future Stage 4 planner, ever
  needs a real accept/escalate threshold, use the JEV paper's checklist (judge both orders, set the
  threshold on your own labelled cases, don't assume it transfers) as the reference.

### 14. Hindsight (vectorize-io) -- a real, runnable comparable memory system

- **Source:** https://github.com/vectorize-io/hindsight, shared by the user 2026-09-28 (checked
  live: MIT, active -- 90 open issues, 83 open PRs, real docs and a published paper).
- **Noted:** 2026-09-28.
- **What it is:** an open-source "agent memory that learns" system with a retain/recall/reflect
  API, "mental models" and "knowledge pages" beyond flat fact storage, and explicit Windows support
  with a fully local path (embedded Postgres, Ollama as an LLM backend, no API key required). It
  claims SOTA on the LongMemEval benchmark, stating its own numbers were independently reproduced by
  Virginia Tech's Sanghani Center and The Washington Post; every other vendor's score on the same
  chart is self-reported.
- **Skeptic note:** "independently reproduced" is the vendor's own claim about a third party's work,
  not something checked here, and the comparison chart is still the vendor's own benchmark harness.
  The Virginia Tech/Washington Post claim specifically would be worth confirming before citing it as
  fact anywhere public.
- **Why it matters for Diya:** this is the closest thing found yet to a real, runnable alternative
  implementation of what Stage 2 already does -- unlike Truffle (closed, entry 1) or company-brain
  (Slack/Cloudflare/multi-tenant, entry 10), Hindsight runs locally on Windows against Ollama today,
  with no re-architecture required to even try it. Its "reflect" step (a disposition-aware response
  synthesized from memory, not just a raw recall) is a concept Diya doesn't have: `render_for_model()`
  hands the model grouped facts and leaves all synthesis to the model; Hindsight does some of that
  synthesis inside the memory layer itself.
- **Action:** no build. If Stage 2's review-and-promote design ever feels limiting, this is the
  first place to actually run a side-by-side comparison (same machine, same Ollama, same questions)
  rather than a paper comparison -- it needs nothing new to try. Do not adopt it outright: swapping
  SQLite-plus-review for a new memory service is the kind of re-architecture cross-cutting note 4
  warns against, and Diya's own differentiation (entry 1) is that a person reviews every fact before
  the model sees it -- a design choice, not a limitation Hindsight's "learns automatically" framing
  would necessarily preserve.

### 15. SkillOpt (Microsoft) -- validation-gated self-editing skills

- **Source:** https://github.com/microsoft/SkillOpt, shared by the user 2026-09-28 (checked live:
  MIT, Microsoft-owned, 17.7k stars, 531 commits, covered by Microsoft Research's own blog and
  outside press -- substantially more established than backpass, entry 12c).
- **Noted:** 2026-09-28.
- **What it is:** trains a compact skill document (300-2,000 tokens) for a frozen LLM agent the way
  a neural net is trained -- rollout, score, propose a bounded add/delete/replace edit, accept only
  if it strictly improves a held-out validation score, repeat. "SkillOpt-Sleep" (shipped 2026-07)
  runs this nightly and offline over a coding agent's own real sessions: harvest, mine, replay,
  consolidate, all behind the same held-out validation gate.
- **Why it matters for Diya:** SkillOpt-Sleep is the third independent project this month whose own
  solution takes Dreaming's shape (batch real usage on a schedule, off the interactive path, gated
  before anything is trusted) -- after company-brain's pipeline (entry 10) and UFO's durable turns
  (entry 12a). That is a repeated signal that Dreaming's basic structure is a sound one, not a
  Diya-specific idiosyncrasy. Its actual subject (optimizing a coding agent's own skill
  instructions) doesn't transfer -- Diya isn't a coding agent and has no equivalent skill document --
  but its validation discipline (an edit only survives if it strictly improves a held-out score, not
  just looks better) is the same principle backpass applies to `CLAUDE.md`, now demonstrated at much
  larger scale by a much more credible source.
- **Action:** no build, same conclusion as backpass (entry 12c) -- Diya has no skill-document
  equivalent to optimize and `CLAUDE.md` is too short to need pruning. File this alongside backpass
  as the second, stronger data point: if Diya's memory files or `CLAUDE.md` ever grow large enough
  to need automatic pruning, require a held-out validation gate before any edit lands, not just a
  plausible-looking diff.

### 16. The open-source personal-agent wave: OpenClaw, Hermes Agent, Khoj (and what happened to Truffle's page)

- **Source:** OpenClaw's own README (https://github.com/openclaw/openclaw, fetched 2026-10-05: MIT, 391k stars,
  82.3k forks, run by "the OpenClaw Foundation", an independent 501(c)(3) with donors including Amazon, OpenAI and
  Red Hat); Microsoft Security's post of 2026-02-19 (https://www.microsoft.com/en-us/security/blog/2026/02/19/running-openclaw-safely-identity-isolation-runtime-risk/);
  secondary: Fortune and trade-press coverage of its creator joining OpenAI (2026-02), vendor blogs on Hermes Agent
  (Nous Research, MIT, released 2026-02, "180,000+ stars in under four months" is the vendors' figure) and Khoj
  (its hosted Khoj Cloud was shut down 2026-04-15; the open-source self-hosted version continues).
- **Noted:** 2026-10-05.
- **What it is:** the category Diya is in is no longer niche. OpenClaw (a self-hosted agent runtime that talks to
  20+ chat apps -- WhatsApp, Telegram, Slack, iMessage -- with its own memory, installable "skills" and a scheduler)
  became the most-starred non-aggregator project on GitHub; Hermes Agent adds memory in a local SQLite file with
  full-text search and skills it writes for itself; Khoj is the older "second brain" with scheduled automations.
  What people actually use these for (vendor and community lists, secondary): a morning briefing sent to their chat
  app on a schedule, email triage with drafts they approve, meeting prep from calendar and mail, follow-up
  reminders, calendar changes.
- **Skeptic note:** star counts and "users" are the projects' own; the use-case lists are SEO pages and community
  posts, not usage data. Security-vendor numbers (reported: 300+ malicious skills in its marketplace ClawHub in
  2026-02, a Cornell audit finding 26% of skill packages vulnerable, instances exposed on the default port, a CVE
  in 2026) are from vendor blogs and were NOT re-checked here; Microsoft's own post is primary for the framing.
- **Why it matters for Diya:** (a) the "describe it, it follows through" battleground (cross-cutting note 2) is
  now crowded and fast: Diya will not out-feature a 391k-star project and should not try. (b) The thing every one
  of these has and Diya lacks is reach: they live in the chat apps people already open (and can push to the phone);
  Diya is a web page and a Windows toast. (c) Microsoft's verdict on the leader is the opening for Diya's claim:
  run it only on a separate machine, with throwaway credentials, because it executes untrusted code with
  persistent access. Its three named risks (credentials leaked, **memory altered so it follows an attacker over
  time**, host compromise) come from combining untrusted skills with untrusted text. Diya has no skills
  marketplace, no shell tool, no generic fetch tool.
- **Truffle, rechecked:** truffle.net (2026-10-05) now says "Truffle1", a companion app called Symphony, on-device
  memory and nightly "Dreaming" -- and still no price, no ship date, no specs; one web search found no independent
  review. Whether Truffle ships is still unverified. "Parity with Truffle" (CLAUDE.md) is therefore a target Diya
  cannot check; the comparison set that can be checked is the table above.
- **Action:** no build from this entry alone; it drives entries 17-20. Treat OpenClaw/Hermes as the reference for
  *what users do daily*, and the security record around them as the reference for *what to refuse*.

### 17. Agent security 2026: the lethal trifecta, the Rule of Two, and memory poisoning (Diya's strongest ground)

- **Source:** Simon Willison, "The lethal trifecta" (https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/, fetched);
  Meta, "Agents Rule of Two" (https://ai.meta.com/blog/practical-ai-agent-security/, 2025-10-31, fetched); The Hacker
  News on MemGhost (https://thehackernews.com/2026/07/new-memghost-attack-plants-persistent.html, fetched);
  arXiv 2606.04329 "From Untrusted Input to Trusted Memory" (abstract fetched; also 2605.15338 and 2607.05189,
  titles only); EchoLeak (arXiv 2509.10540, via search).
- **Noted:** 2026-10-05.
- **What it is:** (1) Willison: an agent is dangerous when it combines private data, untrusted content and a way
  to send things out; guardrail/detection products are unreliable (a "95% catch rate" is a failure in security),
  and the only dependable defence is to make it impossible for ingested untrusted input to trigger a
  consequential action. (2) Meta's Rule of Two: within one session an agent should have at most two of: untrusted
  input, access to private data/sensitive systems, ability to change state or communicate outward; otherwise a
  human supervises. (3) Memory poisoning: the 2026 papers and the MemGhost report show that one crafted email can
  make an agent save a false "fact" that steers later sessions, without telling the user. MemGhost's reported
  success rate was 87.5% against OpenClaw on one model and 71.4% against a Claude-based agent; OpenClaw's team
  disputed the test setup (it recommends a separate reader for untrusted mail) and said it is weighing provenance
  tracking and confirmation prompts. The paper abstract adds that agents which write and retrieve memory more
  aggressively are more exploitable and that existing prompt-injection defences do not cover memory poisoning. The
  recommended mitigations are the ones Diya already has: separate reading from memory-writing, tag where a memory
  came from, require the user's confirmation before a memory becomes permanent, and keep an audit log.
- **Skeptic note:** MemGhost is one vendor-reported attack with a disputed setup; attack-success numbers depend on
  the model and harness and do not transfer to Diya's 3B model. Only the arXiv abstract was read, not the paper.
- **Why it matters for Diya:** this is where the project is most clearly on the right track, and it is checkable
  in the code: `dreaming.py` extracts facts only from the owner's own messages (`role == "user"`), never from tool
  output or web text, and every candidate waits for a human before the model sees it (Stage 2); every outside write
  is a proposal the owner approves on exact arguments, with the tools that ran earlier shown as a taint warning
  (Stage 4); there is no skill marketplace, shell or arbitrary-URL tool; outbound hosts are fixed first-party APIs.
  The honest limits: none of this has been attacked by anyone but its author; text the owner pastes into chat
  becomes "the owner's own message" (it still needs review); and `web_search` is the one outbound path where the
  model chooses free text (a query to the search engine, which is not by itself an attacker-visible channel) and it
  is not covered by the host allowlist (README, known limits).
- **Action:** (a) write the Rule-of-Two accounting down per tool (which of the three each gives) and add a test that
  fails when a new tool completes all three without the approval gate -- a public, checkable claim, small effort.
  (b) keep the "reader never writes memory" property as a stated rule before any inbound channel (entry 16) is
  added: a message from a phone is the owner's only if it is from the paired owner.

### 18. ChatGPT Pulse retired for "scheduled tasks" -- proactivity the user steers wins

- **Source:** OpenAI's retirement notice as reported by Digit (https://www.digit.in/news/general/openai-is-retiring-chatgpt-pulse-and-replacing-it-with-scheduled-tasks-here-is-why.html/amp/,
  fetched) and Gigazine (2026-06-19); the Pulse help page (https://help.openai.com/en/articles/12293630-chatgpt-pulse).
- **Noted:** 2026-10-05.
- **What it is:** OpenAI launched Pulse (a daily set of research cards drawn from your chats, memory and connected
  apps) in 2025-09 and announced its retirement in mid-June 2026 (reports say 06-17 or 06-18), replacing it with
  "scheduled tasks": the user sets a reminder, a recurring task or a topic to track, for a time or a part of the day,
  and gets a page to pause, edit and delete them. OpenAI's stated reason (as reported): proactive features are most
  useful when personalised, action-oriented and steerable by the user; engagement was strongest on the task parts.
- **Skeptic note:** the reasons are OpenAI's, second-hand; "most users abandon it" is from an SEO blog and not used.
- **Why it matters for Diya:** the largest assistant on earth tried "the AI decides what to tell you each morning"
  and walked back to "you tell it what to watch, when". That is what Diya's reminders and tasks already are
  (docs/PROACTIVITY_DESIGN.md, docs/TASKS_DESIGN.md), and it says the missing pieces are the boring ones: recurrence,
  a part-of-day time ("every morning"), and one page that lists everything scheduled so it can be paused or deleted.
  OpenClaw's most-used pattern (a morning briefing on a cron) is the same idea with weather, calendar and tasks in it.
- **Action:** the next build should be scheduled tasks (recurrence for reminders and tasks, a "Scheduled" view, and a
  briefing built only from things Diya already reads), not new kinds of autonomy.

### 19. Local models, runtime, MCP and speech in 2026 (what could replace what Diya runs today)

- **Source:** Ollama library pages (fetched 2026-10-05: gemma4, qwen3), Ollama's web-search docs
  (https://docs.ollama.com/capabilities/web-search, fetched), the MCP 2026-07-28 release-candidate coverage and the
  2026-08-22 roadmap (secondary), small-model tool-calling roundups (secondary; several are SEO pages), Home Assistant
  voice-stack write-ups (secondary).
- **Noted:** 2026-10-05.
- **What it is:** (1) Models on Ollama today: Gemma 4 in E2B (4.6-7.5 GB), E4B (6.6-9.5 GB), 12B, 26B MoE and 31B, 128K-256K
  context, thinking modes; Qwen3 in 4B (2.5 GB, 256K context) and 8B (5.2 GB, the one already installed); the page
  fetch did not say which of them support tools. Roundups (secondary) put Qwen3-4B at the top of the sub-7B models for
  tool calling in early 2026 and say Gemma 4 (2026-04) added native function-call tokens; they also repeat the
  advice that code-side guardrails matter more than the model for small models, which is what Diya measured itself.
  (2) Ollama added an MLX engine for Apple silicon, llama.cpp alongside it, hosted `:cloud` models and a web-search
  API (`https://ollama.com/api/web_search`: needs a free account's API key; what it receives is the query string).
  (3) MCP's 2026-07-28 revision (release candidate) makes the protocol stateless and rewrites authorization; the 2026-08
  roadmap makes agent identity a priority. (4) Speech: Piper TTS was archived in 2025-10; Kokoro (82M parameters,
  Apache-2.0) is the usual replacement; Diya uses faster-whisper for input and the browser's speech for output.
- **Skeptic note:** "best small model" claims come from third-party blogs, some plainly SEO; none is a measurement on
  Diya's tasks. The Ollama web-search details are from its docs, untested here.
- **Why it matters for Diya:** the cheapest real experiment in this whole survey is to run the existing benchmark and
  evals (`python diya_actions_bench.py`, `python diya_evals.py`) against `qwen3:4b` and `gemma4:e4b` and compare them
  with `qwen2.5:3b` on the same labelled messages: does either reach for tools unasked less than 16% of the time
  (docs/TASKS_DESIGN.md), and is either fast enough on this CPU laptop (qwen3:8b was about six times slower than the
  3B model, docs/MODEL_BENCHMARK.md)? Ollama's search API is also a candidate way to close the one known gap in the
  host allowlist (`ddgs` cannot be wrapped): one known host, a key, queries visible to Ollama instead of DuckDuckGo --
  a trade the owner would have to choose. MCP is worth being a *client* of only if a connector the owner needs has no
  direct API, and then only for named, pinned servers behind the approval gate (the ClawHub record is the reason).
- **Action:** (a) run the model bake-off, change nothing until it is measured -- **done 2026-10-09**
  (docs/MODEL_BENCHMARK.md, "Second pass"): `qwen3:4b-instruct` passed all nine evals in each of three runs
  (`qwen2.5:3b`: 7, 8, 8) and reached for a task tool unasked on 2% of messages against 13%, invented no due dates (the 3B:
  43% of those it gave) and never said it had added a task it had not, at about 1.4 times the time per message; `gemma4:e4b`
  (7 of 9, five times slower per call) and the thinking build `qwen3:4b` (279 s for a three-word reply) are not usable on
  this CPU. A model with a huge default context (`qwen3:4b`, 262,144 tokens) will not even load on 15.7 GB unless
  `num_ctx` is capped through a Modelfile alias. Nothing was switched; (b) no MCP, voice or runtime change now.

### 20. Market and hardware signals: where "local" is and is not worth paying for

- **Source:** coverage of Meta's purchase of Limitless (2025-12), Amazon's of Bee (2025), HP's of Humane's software
  and team (2025-02, reported $116M, an 86% markdown from peak); Usercentrics' 2026 trust report and CNET/ZDNET
  surveys as reported by eMarketer and others (the eMarketer page itself returned 403, so these figures are from
  search summaries); hardware roundups for DGX Spark (about $4,000, 128 GB), Strix Halo mini PCs (128 GB, roughly $1.5k-2k),
  Mac Studio M5 Ultra (shipped 2026-09) and the Tiiny AI Pocket Lab (a EUR 1,200 Kickstarter, 80 GB); coverage of Apple's
  iOS 27 Siri (WWDC 2026: personal context across mail, messages and files, Gemini-backed with Private Cloud Compute).
- **Noted:** 2026-10-05.
- **What it is:** dedicated AI gadgets are consolidating into the big platforms (the buyers wanted the software and
  the team, not the device); platform assistants are absorbing the basics (Apple's Siri searching your mail and
  messages to make events and reminders, Meta Muse in entry 4); consumers say they are wary of AI with their data
  (52% trust it less than people with it, per Usercentrics) and 52% would pay about 7% more for transparency, but
  few will pay extra for "on-device AI" as such (reported: 3% of smartphone owners; 71% of US adults would not pay extra).
- **Skeptic note:** every figure is second-hand, from surveys of mainstream consumers, not of people who would run
  a home server; none was re-checked. Diya is a personal project, so market willingness to pay is context, not a
  requirement.
- **Why it matters for Diya:** (a) the hardware premise is the weakest part of the original thesis: the evidence says
  value sits in the software and in trust, which fits the decision already taken (Windows and Ollama now, the Mac mini
  deferred, none of the 2026 boxes needed for a 4B-8B model). (b) "Local" alone is not what people pay for; "I can see and
  control what it remembers and does" is, and that is the claim entries 17 and the existing design support. (c) Do not
  chase ambient recording or wearables: the independents sold, and always-on capture of other people raises consent
  questions Diya has no reason to take on.
- **Action:** none. Keep the Mac mini deferred; spend effort on trust and daily use.

### 21. Cognition's "Agent Memory Repo" -- memory as a git folder of Markdown, consolidated by a "Dreaming" agent

- **Source:** https://cognition.com/agent-memory-repo (fetched 2026-10-09; no publication date on the page, its
  examples use 2026 dates), shared by the user 2026-10-09.
- **Noted:** 2026-10-09.
- **What it is:** an open standard for agent memory that persists across sessions. Memory is a folder in a git
  repository of Markdown notes, one line per entry, each with optional metadata (a link to the session it came from,
  the date added); a short `MEMORY.md` is the entry point an agent loads first. Each session clones the repo, searches
  or follows links between notes like a wiki, updates what it learned and pushes. Several repos can be loaded at once,
  and the agent writes each memory to the repo of the person it came from (asking when unclear). A separate
  "Dreaming" agent runs periodically to merge duplicates, remove outdated entries and check sources to resolve
  contradictions; git flags conflicting edits from parallel agents; every repo keeps its own owner, permissions and history.
- **Skeptic note:** a vendor's standard, undated; the page's numbers are illustrative examples (a latency fix, an
  autocomplete rate), not a measurement of the memory design. Nothing on it says how a bad memory is stopped from
  getting in, or how the periodic merge is checked.
- **Why it matters for Diya:** (a) a fourth independent project this autumn to land on Dreaming's shape (batch, off the
  interactive path, consolidate) -- after entries 10, 12a and 15 -- and one that borrows the name; that is a signal about
  the structure, not about Diya. (b) The difference is the one that matters: here the consolidating agent edits the
  memory on its own (merge, delete, settle contradictions), which is a "compaction-driven write" in the memory-poisoning
  papers' terms (entry 17); Diya's Dreaming only stages candidates and a person accepts them. (c) What is worth taking is the
  *form*: plain Markdown under version control gives an owner a diff, a history, a way to edit by hand and a way to
  leave. Diya's accepted facts are SQLite rows with an append-only event trail, and `diya_review.py export` writes only a
  flat bullet list (no person grouping, no history) as a backup that round-trips through `import-profile`.
- **Action:** no build now. If memory portability becomes a goal, the cheap, safe step is a Markdown export that keeps
  the person grouping and the review trail (read-only, so the database stays the source of truth) -- an addition to the
  existing `export`, not a new store. If accepted facts ever pile up enough to need merging or retiring, have Dreaming
  *propose* each merge or retirement and let the owner approve it, the way Stage 4 treats a write; do not let it edit
  accepted facts itself.

### 22. Product signals shared 2026-10-09: Instinct's $1B, open-instinct, Littl, Bonsai (what checked out)

- **Source:** the user's pasted posts; checked against the pages and search results of 2026-10-09 -- the Instinct funding
  coverage (Reuters and TechCrunch as relayed by trade sites), https://github.com/mariagorskikh/open-instinct,
  https://dolittl.ai, and searches for "Bonsai" / "Yaklabs".
- **Noted:** 2026-10-09.
- **What checked out:**
  - **Instinct (entry 2):** reported 2026-09-28 to have raised $1B (Series C, Sequoia, Benchmark, Coatue) at a $10B
    valuation, a month after a $250M round; access is still limited; users reach it by text or phone; a newer tier phones
    businesses to book things; its "Trusted Person Network" lets people's agents talk to each other. Coverage disagrees on
    details (one data provider lists a $6.47B valuation; launch is dated August or February) and revenue is unclear.
  - **open-instinct:** real, MIT, 272 stars, version 0.1 ("treat live deployments as beta"), 837 tests. Not local: you
    text a phone number from a hosted service (Inkbox), each agent runs in its own microVM on a hosted desktop service,
    apps connect through Composio, the default model is Claude, payments use Stripe Link. What is worth reading:
    six trust tiers (owner, partner, family, friend, contact, stranger) enforced in code before any tool runs, and
    payments where the agent never holds a card -- it asks for a single-use card for the exact amount and the owner
    approves on their phone.
  - **Littl:** a pre-launch waitlist (Serendipity AI, Inc.; no founders named). The page says "private by design" and
    that data is not sold to advertisers; it does NOT claim on-device processing, which the pasted post does, and the
    "much faster than global agents" test is unsupported. The idea worth noting is the unit of the product: an outcome
    ("plan our Japan trip", "keep the household running") that it keeps working on, not a prompt.
  - **Bonsai / Yaklabs:** nothing found. Six searches turned up no such company or product; the only source is the
    pasted post, so it is unverified. Its stated principles are the part to keep: what the assistant learns about you
    should be readable, editable, correctable, portable and stored in files on your machine, and not tied to one model.
- **Why it matters for Diya:** (a) $1B into a cloud personal agent you text is the cloud pole of cross-cutting note 1
  getting stronger; it validates the category and says nothing about whether local can win it. (b) Bonsai's principles are
  Diya's own thesis stated by someone else -- the fair test of "are we doing that?" is: can the owner see, correct and
  take with them everything it knows? Today they can see and correct facts (Memory page) and export a flat list, but not
  history, tasks or reminders in one portable form. (c) open-instinct's out-of-band approval (the card is approved on the
  owner's phone, never in the chat with the agent) is the same rule as Diya's D1 (approval is a button or the CLI, never a
  chat reply) and is the right model if Diya ever gets a phone channel (entry 16). (d) Trust tiers solve a multi-person
  problem Diya does not have; do not copy them.
- **Action:** none to build from this entry. Add "everything Diya knows about you can be exported in one readable form"
  to the list of things to check against Bonsai-style claims; it is a small gap, not a missing foundation.

### 23. Frontier-model posts shared 2026-10-09: Kardashev-0.7 and LoopCD (not actionable for Diya)

- **Source:** the user's pasted posts; the paper https://arxiv.org/abs/2610.02185 (abstract fetched); a search for
  Banbury Road / Kardashev-0.7.
- **Noted:** 2026-10-09.
- **What checked out:** **LoopCD** is real: submitted 2026-10-01, a training-free contrastive-decoding method for
  *looped* transformers (models that reuse one block several times), with reported gains that match the post
  (Ouro-2.6B-Thinking on AIME 2024, 61.88% to 73.33%; Huginn on HumanEval, 22.56% to 31.71%) and, in the abstract,
  matching or beating unguided full-depth runs with half the loops at 22.5%-48.2% fewer forward FLOPs. The page does not
  state an affiliation, and the post's remark that frontier models such as "GPT-6 Astra" and "Gemini 4" use looped
  transformers is a rumour that is not in the paper. **Kardashev-0.7** (Banbury Road): the only source found was one
  person's LinkedIn page; "32 models trained together with RLPS" and "0.7%-2% of the inference cost, 3% of the memory"
  are the company's own words with no named baseline, no report and no independent coverage -- unverified.
- **Why it matters for Diya:** neither is runnable by Diya today: looped models are not what Ollama serves, and a swarm of
  32 models is the multi-model route cross-cutting note 4 rules out. The one thing to watch is the direction both point
  to -- more capability per parameter and per watt at small sizes -- because that is what would let a laptop CPU run the
  whole agent loop (see entry 19), and it is the same bet as the pasted opinion that most daily work will run on local models
  within five years (an opinion in that post, not evidence).
- **Action:** none. Re-run the model bake-off (entry 19) when a small model with a better tool-calling record lands on Ollama.

### 24. helix-foundry (HelixDB): "your company's data as one ontology, on your own computer" -- real, narrower than the post says

- **Source:** the user's pasted post (an X post, "I just KILLED Palantir!"); checked 2026-10-10 against
  https://github.com/HelixDB/helix-foundry and https://github.com/HelixDB/helix-db (read through page summaries, not the
  code) and one web search, which found no coverage of helix-foundry itself.
- **Noted:** 2026-10-10.
- **What checked out:** the repo is real and MIT-licensed (621 stars, 86 forks, 44 open pull requests; only 2 commits
  showed on the page I read, no last-commit date). The README describes a local, single-user workspace: connect sources
  (Postgres, MySQL, Stripe, WorkOS, PostHog, files, APIs), get a suggested ontology (objects and relationships) held in
  HelixDB, versioned Parquet snapshots, DuckDB running the queries, and an "Analyst" that answers questions with the SQL it
  ran. It runs from Docker Compose, binds to 127.0.0.1, and defaults to a local model (qwen3:4b through Ollama), with
  Claude or OpenAI as options. HelixDB itself is a Rust graph-plus-vector database, Apache-2.0 on its repo page (one
  search listing said GPL v3; the repo page is the better source), about 6.2k stars, with an embedded mode.
- **What did not check out:** the post says "s3-backed", but the README lists S3-compatible storage only as a place data is
  read *from*, not where the ontology lives. "Killed Palantir" is the poster's framing: the README never mentions Palantir,
  and says the tool is for one user with no accounts, so anyone who can reach the app controls every workspace -- the
  opposite of the governed multi-user platform Foundry is sold as. It was built and validated on Apple-silicon macOS, CI
  runs on Linux, Windows is untested, the first run downloads several GB, and the local model was benchmarked on 16 GB
  machines. It pins HelixDB v0.0.6 while HelixDB's own repo describes a v3 generation; the pages I read do not explain why.
- **Why it matters for Diya:** (a) one more local-first tool whose *default* is a 4B model on a 16 GB machine -- the same bet
  Diya made, and a sign the pattern is spreading. (b) "Answers come with the query that produced them" is a verifiable-answer
  habit worth noting; Diya's list and read tools already build their answers in code from its own tables rather than letting
  the model write queries, which is the safer shape, but it does not show the owner where an answer came from. (c) Not
  adoptable: it is a company-data tool, needs Docker plus a graph database plus DuckDB, and Windows is untested; person-tagged
  memory in SQLite is the right size for one person's facts.
- **Action:** none to build. Idea to keep, not commit to: an optional "where this came from" line on answers about the owner's
  own data (which facts, reminders or tasks were read), in keeping with the auditability thesis (cross-cutting note 1).

### 25. Truffle: who is behind it and what is (and is not) known -- searches of 2026-09-09 to 2026-10-05, written down 2026-10-10

- **Source:** about thirty searches and page fetches made between 2026-09-09 and 2026-10-05 for the Truffle dossier work, never
  recorded here until now: truffle.net, the older docs at docs.itsalltruffles.com, the github.com/deepshard organisation, a
  FundersClub profile, the March 2024 Hacker News launch thread, and search-engine snippets. Several pages returned HTTP 403 and
  were NOT read: truffle.net/press, docs.truffle.net, the G2 reviews page, the Medium launch post, and an eMarketer piece.
- **Noted:** 2026-10-10 (from the saved results; nothing re-fetched today).
- **What the sources say:**
  - **Who:** Deepshard, Inc., doing business as Truffle, Los Angeles; its GitHub organisation says "We're building a personal
    AI computer" (69 followers; the SDK repo has 23 stars). No source I fetched named the founders: the 2024 launch thread
    remarked on exactly that. A search snippet gave a $1.78M seed round from July 2022 on one aggregator, which I could not
    confirm and could not tie with certainty to this Truffle.
  - **Do not confuse it with** Truffle AI (Y Combinator W25, Bengaluru, an API for putting agents inside software) or Truffle
    Security ($25M Series B, November 2025, secret scanning). Both turn up first in searches; neither is this company.
  - **Hardware:** per the 2024 launch thread, Truffle-1 is a Jetson AGX Orin 64 GB in a custom case -- 200 GB/s memory
    bandwidth, 275 TOPS, 60 W -- claiming Mixtral at 22 tokens/s, $1,299 ($500 preorder). Commenters objected to the closed-source
    compiler and noted the bare board costs $300-400 less. One snippet says orders opened and shipping began in January 2025 in a
    run limited to 333 units, with 50 hand-delivered in the US; another mentions "$115/month". Those two are unconfirmed and
    disagree with the $1,299 figure.
  - **Software:** a Truffle app is a set of Python tools exposed through its SDK; the client picks one app per session and the
    docs state there is "no cross-app context" once it has. The older docs list Gemma3-27B, Qwen-32B or Qwen-14B for the hardware
    and DeepSeek R1 for the cloud.
  - **Today's truffle.net:** "private, local exo-cortex", a sculptural shell with a light array, a companion app called Symphony,
    nightly "Dreaming" -- and no price, specs, shipping status or reviews, so it still reads as stale (entry 1). Searches for its
    "Conductor" and "Radiance" apps and a wake word found nothing.
  - **Privacy:** its privacy policy, as relayed by a search, says Google data and tokens stay on the device, nothing goes to a
    third-party cloud model, and nothing is used for training. That is a claim, not an audit. The only "controversy" results were
    about Truffle Security's XSS Hunter, an unrelated company.
- **Why it matters for Diya:** (a) the comparable's own hardware runs 14-32B models; Diya runs a 3-4B model on a CPU, one to two
  orders of magnitude smaller, which is the honest limit on how far "feature parity" can stretch (see entry 19). (b) A closed
  source, founder-opaque appliance leaves the auditability difference (cross-cutting note 1) intact. (c) "No cross-app context"
  is a limit Diya does not have, since one agent holds all its tools -- at the cost, measured in the bake-off, that a small model
  can confuse them.
- **Action:** none to build. Keep public wording to "feature parity with what Truffle does, per the dossier", never its hardware,
  its price or its shipping numbers, and do not cite the unconfirmed figures above.

### 26. Memory that tidies itself, again: Mem0 "Dream" and Devin's "Memory and Dreaming" (what they do, and what Diya's design already does differently)

- **Source:** two posts the user pasted 2026-10-10, checked the same day against https://docs.mem0.ai/platform/features/dream
  (fetched) and, for Devin, two web searches (the blog URL itself returned 404 to my fetch; the launch is confirmed by the
  docs page https://docs.devin.ai/product-guides/memory and trade-press summaries, all dated 2026-10-05). Builds on entry 21
  (the "Agent Memory Repo" standard behind Devin's memory).
- **Noted:** 2026-10-10.
- **Mem0 Dream, as its docs describe it:** three operations over a user's memories. *Merge* folds a duplicate into a canonical
  memory (hidden from search unless asked for); *supersede* marks an older fact replaced by a newer one (still returned, labelled
  as history, unless `latest_only` is set); *synthesis* writes a new "pattern" memory when several memories support one, linking
  back to its sources. Merge and supersede run as memories are added; synthesis is a background job needing at least 20 memories,
  weekly on the Pro plan (daily on Enterprise), covering only memories created after it was switched on. Nothing is deleted, every
  change is recorded and reviewable, and synthesis can be switched off per project. The post says merge needs the new memory to
  keep all the old one's information, supersede needs a clear replacement of the same fact, and "anything ambiguous results in
  no action".
- **Devin Memory and Dreaming, as the post and docs describe it:** per-person notes in a personal git repository of Markdown (the
  open standard of entry 21); the agent saves lessons while it works (preferences, corrections, project gotchas), each linked to
  the session it came from; a daily Dreaming pass merges overlapping notes, drops transient details and notes no session used, and
  looks for lessons missed at the time. The app shows the notes read-only (to change one, you ask Devin), lists recent Dreaming
  sessions with what each changed, and has a switch that stops reading and writing memory while keeping the notes.
- **Skeptic note:** both are vendor posts with no measurement of whether the consolidation is right. Mem0's "a few hundred
  duplicate or contradicting memories in the median active project" has no method behind it, and its docs page gives no accuracy or
  volume numbers. The post and the docs differ: the post says Dream is a Pro/Enterprise feature and mentions `immutable` and
  `exclude_from_dream` memories; the docs page says supersede and merge are on every plan and mentions neither flag. Neither says
  how a wrong memory is kept out in the first place.
- **Why it matters for Diya:** (a) Two more products, in one week, that make memory self-maintaining and automatic; that is the
  direction the owner chose on 2026-10-10 (`docs/AUTO_MEMORY_DESIGN.md`), so this is confirmation of the shape, not new evidence
  that it is safe. (b) Mem0's rules are the same instinct as Diya's lanes: act only when the case is clear and leave the
  ambiguous alone. Diya is stricter in one place -- a possible update of a known fact is *asked about* (the `similar` flag), not
  silently ignored or silently applied. (c) Their lifecycle states (active / superseded / merged, each pointing to its
  replacement, history kept) are what Diya's append-only event trail already gives; the one thing worth copying is that a
  retirement caused by a correction should record *which fact replaced it*, so the Memory page can show "was: ... now: ...".
  (d) Synthesis is the part Diya should not copy as it stands. A pattern memory is a statement the owner never made; Diya's
  rule D2 (only the owner's own words are ever a source) means a synthesized fact could only ever be *offered* to the owner as a
  question, never accepted on its own, and that is a later idea at best. (e) Devin's memory is about how someone likes to work;
  Diya's is about a person's life (health, money, family), which is why Diya has sensitive classes and never-kept secrets and
  they do not need to. (f) Devin removes notes "no session used": Diya puts every accepted fact in every prompt, so it has no
  such signal, and uses a time horizon plus a question instead (design D5, trigger 3).
- **Action:** one small addition to unit A3 (corrections): the retire event written by `Memory.supersede` carries the id of the
  replacing fact. Nothing else to build. Do not add synthesis; if ever revisited, it proposes and the owner decides.

### 27. "Factoring RSA-260" (Cognition, 9 September 2026): checked, and not about anything Diya does

- **Source:** the user's pasted blog post (Eric Lu, Cognition), checked 2026-10-10 against a web search (the post itself, two
  trade-press write-ups) and Wikipedia's page on the RSA numbers, plus arithmetic done locally.
- **Noted:** 2026-10-10.
- **What checked out:** the arithmetic. The posted number has 260 digits and 862 bits; the two posted factors have 130 digits
  each; their product equals the number exactly; both pass 40 rounds of the Miller-Rabin primality test and the number itself
  fails it. Wikipedia's RSA-numbers page lists RSA-260 as factored by Eric Lu on 3 September 2026 with the same number (the
  fetch tool relayed 259 of its 260 digits, all identical to the pasted ones). The "previous record RSA-250, February 2020" is
  the well-known Boudot, Gaudry, Guillevic, Heninger, Thome and Zimmermann result, and the post cites it.
- **What did not (and could not) be checked:** the cost figures ($400k, 4,900 GPU-days), the "10x cheaper than the previous
  public state of the art" claim, and the $30M estimate for RSA-1024 are the author's own estimates, repeated by the press
  without independent verification. The post says plainly that RSA-2048 is unaffected.
- **Why it matters for Diya:** not a technology Diya can use. What it says about working with agents matches how this project
  runs: the author's own account is that the human supplied priorities, a unified set of benchmarks, and the habit of catching
  unproductive work, and that the agents drifted as the code moved away from the upstream project they knew. That is the case
  for measuring with the real model before trusting a feature (the benches), and for keeping Diya close to ordinary, documented
  patterns rather than clever ones.
- **Action:** none.

### 28. "How AI memory actually works" (supermemory's beginner's guide), and the three papers behind its numbers

- **Source:** the guide the owner pasted 2026-10-13 (written at supermemory; vendor content). Checked the same day by fetching the three papers it leans on -- LongMemEval
  (arXiv 2410.10813), ConvoMem (arXiv 2511.10523) and "Lost in the Middle" (arXiv 2307.03172) -- and supermemory's own LongMemEval-S report
  (https://supermemory.ai/research/longmembench). The guide itself could not be found by search.
- **Noted:** 2026-10-13.
- **What the guide says:** a model remembers nothing; the app resends the chat every turn and anything that "remembers you" is notes pasted back in. A bigger window does not fix it (more text
  makes the answer harder to find, and a 100-turn chat resends about 2.5M tokens in total). Raw data can be searched as it is (grep, embeddings, RAG), or a model can first turn it into notes or
  facts, which can notice that a fact changed. Every system has a search step, chunking, learning outside the conversation and code that puts the result back into the prompt. Memory is a
  lifecycle: write (only what would change a future answer), update, forget (some facts expire), infer, and recall (the only live part). A store tracks time and connections. Memory plugs in as a
  tool the model may call, or as hooks the app runs at set moments. supermemory's own design: atomic facts linked by *updates*, *extends* and *derives* (a derived guess is trusted less until
  confirmed), and three ways to read back (source chunks, facts, a short always-present profile).
- **What checked out:** LongMemEval is real (Wu, Wang, Yu, Zhang, Chang, Yu; ICLR 2025): 500 questions, five abilities (extraction, multi-session reasoning, temporal reasoning, knowledge updates,
  abstention); its abstract says commercial assistants and long-context models show "a 30% accuracy drop" on remembering across sustained interactions. ConvoMem is real (Pakhomov, Nijkamp, Xiong,
  13 Nov 2025; 75,336 question-answer pairs) and says what the guide says: for a small history the whole conversation in the prompt does best (about 70-82% accuracy); up to roughly 30
  conversations it is the best, up to roughly 150 it stays workable, beyond that a hybrid or retrieval design is needed; and a retrieval-based memory system, Mem0, scored only about 30-45% on
  histories under 150 interactions. "Lost in the Middle" (Liu et al.) is real: models use the start and the end of a long prompt best and the middle worst.
- **What did not check out:** the guide's "87% with only the answer sessions, 60.6% with the whole ~115k-token history, GPT-4o" is not in LongMemEval's abstract, and supermemory's own report gives
  the full-context baseline for the same setup as **60.2%**, not 60.6%; the 87% was not found. supermemory's headline 97% is *Recall@20* (does the search result contain the answer), not answer
  accuracy, and the report's two tables use different measures; swapping the answer model from gpt-4o to GPT-5 or Gemini 3 Pro lowers its overall score to 84.6% / 85.2%. All of it is the vendor's
  own harness.
- **Why it matters for Diya:** (a) The strongest point for a one-person assistant is ConvoMem's: **while the history is small, tell the model everything.** That is what Diya does (every accepted
  fact, one system message, 2,000 characters), and the owner's memory is seven facts. The guide's own case for search only starts past about 150 conversations. So no retrieval needed *yet*; the
  numbers also give the trigger for building it: when the accepted facts approach the cap or run to a few dozen. (b) The lifecycle is Diya's, almost step for step: write (Dreaming, live
  capture, the lanes), update (the `similar` flag, corrections, `supersede`), forget (retire, "forget that", Undo), recall (all accepted facts). What it adds and Diya lacks: *time* (facts that
  carry when they were true; Diya had only a stale question for an exactly-dated fact, and nothing at all for "next Tuesday" until 2026-10-13), *relevance recall*, a split of an always-present
  profile from recent events, and *documents as a second store* (Diya indexes one notes folder and returns one note). (c) "derives" is the inference that cross-cutting note 8 forbids as a
  silent fact: a derived guess could only ever be *offered* to the owner as a question. (d) Hooks versus a memory tool is the same choice `docs/GATE_BENCHMARK.md` measured (the small model
  was worse at deciding); Diya uses hooks. (e) The code sample is supermemory's hosted API: the owner's facts would leave the computer, so it is a reference for shape only.
- **Action:** no build from this entry alone. It feeds the plan in `docs/RESEARCH_PLAN_2026-10.md` (units D1 time-aware facts, partly done the same day; R1 relevance recall, when the memory
  grows; K1 a knowledge base from the owner's documents).

### 29. Sentient OS (open source, AGPL-3.0, macOS only): "your computer catches up with you overnight"

- **Source:** the founder's launch thread, pasted 2026-10-13; checked the same day against the project's README (https://github.com/Sentient-OS-Labs/sentient-os, fetched) and a web search.
  The founders, the "$1M+ pre-seed from Y Combinator, Afore, Pioneer and a16z speedrun" and the thread's claims about other agents could not be confirmed; secondary sites disagree with each other.
- **Noted:** 2026-10-13.
- **What it is (from the README):** a menu-bar Mac app (Apple silicon, macOS 15.4+, 8 GB; no Windows) with three parts: *Sidekick* (hand off what is on screen; it works with its own cursor and
  does not ask before each click), *Double Tap* (a double tap of a key drafts a reply in place and never sends it), and suggestions prepared overnight. At 3 AM, plugged in, an on-device model
  (Gemma 4 E4B through a modified LiteRT-LM with Metal and speculative decoding) reads the sources the person enabled (files, screenshots, iMessage, WhatsApp, Apple Notes, Mail and Calendar),
  drops what is irrelevant and common sensitive identifiers, and summarises it; the summaries become linked notes about people, projects, plans and preferences, which a *frontier model of the
  person's choice* consolidates into a knowledge base: **a folder of ordinary Markdown files** (plus a graph view of the links). Interrupted runs resume from checkpoints. Suggestions wait for
  approval. The first analysis takes hours.
- **Skeptic note:** the thread's headline ("private on-device inference") is true of the first pass only: the README says plainly that the knowledge base and task context go to the chosen cloud
  provider in normal use, and Sidekick/Double Tap send screenshots. Full Disk Access is required. Claims about speed-ups and about other products are the founders' own.
- **Why it matters for Diya:** (a) It is the same bet as Diya's, built from a different side: Dreaming is the nightly on-device pass, and "knowing you matters more than the next agent benchmark" is
  the project's thesis. (b) The difference that matters: Sentient's input is the person's *documents and messages*, its output a *linked Markdown knowledge base*; Diya reads only the owner's chat
  messages and keeps *reviewed atomic facts*. Diya has no way yet to know what is in the owner's notes, mail or files, which is the gap the thread is about. (c) On safety Diya is stricter in every
  place that counts: nothing leaves the computer, every fact is reviewed or asked about, an action waits for approval; Sentient's own README lists the opposite choices as features. (d) The
  knowledge base format (plain Markdown, one folder, readable and editable by the owner, a link graph) is the right shape for Diya too: it is what entry 21 (Cognition's "Agent Memory Repo")
  describes and it is auditable by construction. (e) **Licence:** AGPL-3.0. "Copy wherever needed" cannot mean its code: Diya is published all rights reserved, and AGPL code copied into it would
  oblige the whole of Diya to be offered under the AGPL. Ideas are free; write our own code. (f) Gemma 4 E4B is a model Diya already benchmarked (`docs/MODEL_BENCHMARK.md`, the bake-off).
- **Action:** plan unit K1 (a nightly Markdown knowledge base built on this computer from the owner's own notes first), design-first, with the sources chosen by the owner.

### 30. One week of "self-improving agent" papers: harness learning, HERMES, VERA, MASS, RSI-Anything, VeriHarness, the Sharpening Tax, plasticity, memory machines, MIMESIS

- **Source:** a weekly roundup of ten items and two posts (Sakana's MASS announcement, RSI-Anything), pasted 2026-10-13. Checked the same day: the MASS and RSI-Anything arXiv pages (fetched) and web
  searches for the rest (abstract-level only). **I read abstracts and summaries, not the papers.**
- **Noted:** 2026-10-13.
- **Status of each item:**
  - *MASS*, "Recursive Self-Improvement through Multi-Agent Self-Supervision" (arXiv 2610.12176, Lee, Xu, Seely, Lee, Sojoudi, Zaharia, Tang; 8 Oct 2026): checked. One base model proposes, runs and
    grades multi-agent workflows; an evolutionary search under structural guardrails keeps the best; the model is then fine-tuned on its own best team's traces; two cycles on Qwen3.6-27B gave 1.2-1.6x
    performance per output token on four open-ended benchmarks, and a student trained on multi-agent traces beat a single-agent student given 1.4x more tokens. Sakana's own post warns that a model
    that is also its own evaluator may reinforce shared blind spots.
  - *RSI-Anything* (arXiv 2610.13912, Cui et al.; 9 Oct 2026): checked. A world model predicts which updates to keep; code repair 26.3% (static verifier) to 29.2% to 31.2% after world-model adaptation, GUI
    tasks with 39.4% fewer actions, lab planning 21.80% to 46.01% over five policy versions; the authors say external feedback is costly and the world model's predictions drift as the policy changes.
  - *Harness Learning* ("Harness Learning Enables Generalizable Test-Time Adaptation", Zhang, Zanette, Song, Khashabi): found; the abstract matches the roundup (a proposer trained with RL edits the
    program around a frozen solver; the reward is the revised harness's task score). The 4B-beats-35B, Reasoning Gym and CMU details were not confirmed.
  - *CorpusMap* ("Follow the Entities: A Corpus Map for Agentic Search", Jeong, Jauhar, Hwang, Nam; 29 Sep 2026): found; the arXiv number (2609.37226) comes from an aggregator and the numbers (+6.4 to
    +11.7 points, 34-57% fewer input tokens) from a secondary summary; the Microsoft attribution is unconfirmed. See entry 31.
  - *VeriHarness* (arXiv 2610.00972 per one secondary entry; the Google attribution unconfirmed; other projects share the name): found, no results seen.
  - *The Sharpening Tax* ("Sharpening Tax in Post-Training", arXiv 2610.01509, Oh et al., Meta Superintelligence Labs and others): checked. Across 14 base/post-trained pairs, four model families and three
    agentic benchmarks (42 cases), RL post-training raises pass@1 but often lowers pass@K coverage at a large budget; the "36 of 42" count and the WebShop figures are from secondary coverage; the
    fix (PTGS) was tested only in two small environments.
  - *HERMES* (components of a repository as resident LLMs), *VERA* (NVIDIA; restartable sandboxes with rubric rewards; AutoCoWorkBench, AutoMedBench), *agent plasticity*, *Continuous Memory Machines* and
    *MIMESIS*: **not found or not checked.** The search for VERA found only NVIDIA's Vera CPU page. Treat their numbers as unverified.
- **Skeptic note:** a roundup is a summary of summaries. The only numbers recorded above as checked are those marked checked.
- **Why it matters for Diya:** (a) The common thread is that the gains are in the **harness**, not the weights, and that the harness is now something an agent can *learn to edit* from execution
  feedback. That is how Diya improved, by hand: every gate in `diya_intent.py`, the voice, the look-it-up rule were found by running the real model against the harness and fixing what the numbers
  showed. (b) The part to copy is the loop, in its safe form: a script that reads the benches' failures and *proposes* edits as diffs for the owner to approve, never applying them. Cross-cutting
  notes 8 and 9 and the Rule of Two (entry 17) say nothing may rewrite itself unreviewed; MASS's own caution (one model as optimiser *and* judge shares its blind spots) is the argument for what Diya
  already does: the verifier is advisory, the lanes are code, and the owner decides. (c) The Sharpening Tax concerns choosing models: the bake-off chose `qwen3:4b-instruct` for single-answer
  routing (pass@1), which is what Diya uses; the tax would only bite if Diya sampled many times and kept the best, which on a CPU laptop it will not. (d) VeriHarness's idea (disagreement carries
  information; agreement can hide a shared error) could make extraction ask when two passes disagree, at double the CPU cost. (e) "Agent plasticity" suggests a measure Diya lacks: does memory
  improve answers over time per unit of cost, with the weights frozen. (f) Not usable: RSI-Anything and MASS train models; Continuous Memory Machines is a network architecture; MIMESIS trains user
  simulators for reinforcement learning.
- **Action:** plan units H1 (a propose-only harness advisor) and E1 (a memory-usefulness measure), later and design-first; nothing built from this entry.

### 31. Entity pages (CorpusMap) and a knowledge base of the owner's own documents

- **Source:** entries 28-30 together, plus Obsidian-style linking in the memory guide; 2026-10-13. CorpusMap's claims are the secondary ones of entry 30.
- **What it is:** treat a document collection by the *entities* that recur in it: give each recurring person, project or place a page that collects what is known about it and links to every document
  that mentions it, built offline once (CorpusMap says without a model) and updated as documents arrive, so an agent follows links instead of searching again on every question. Sentient's linked
  notes about "people, projects, plans, preferences" are the same shape.
- **Why it matters for Diya:** Diya already has the first half: `people` and person-tagged facts (`docs/PERSON_MEMORY_DESIGN.md`). It has no pages, no links and no documents: `search_notes` embeds
  each file of one folder and returns the single closest one. A knowledge base from the owner's notes (and later calendar and mail connectors) with an entity page per person and project would turn
  "what do you know about Maya?" from a list of facts into everything the owner has written about her. It is also where relevance recall (R1) would come from.
- **Caveats:** what is written into such pages is *inferred* from documents, not the owner's words: by cross-cutting note 8 it must be shown to the owner and be easy to correct, and nothing in a page
  may become an accepted fact on its own. Documents can carry instructions (entry 17): a page is read as text, never obeyed. Privacy: mail and messages are the most sensitive input there is and are
  the owner's decision to allow, one source at a time.
- **Action:** plan unit K1.

### 32. Four reading lists the owner shared (ML foundations, systems, reinforcement learning, LLM inference): what to read for Diya, and what to leave

- **Source:** four lists pasted 2026-10-13 (about a hundred papers, each with a one-line summary). **Not read, not checked**; the summaries are the lists' own, and the 2025-2026 papers in them (EAGLE-3,
  Hardware-Efficient Attention for Fast Decoding, the DeepSeek-V4 family, Mamba-3, Gated DeltaNet-2 and others) are beyond what could be checked here.
- **Noted:** 2026-10-13.
- **What they are:** curricula, not product evidence: the ML foundations (Perceptron, Dropout, Adam, word2vec, VAE, GAN, AlexNet, seq2seq, distillation, diffusion, BatchNorm, ResNet, Attention, BERT,
  scaling laws, MoE, CLIP, Mamba, GPT-3, Chinchilla, RAG, SAM, chain of thought, LoRA, Toolformer, InstructGPT, ReAct, DPO); classic systems and networking (Shannon, Dijkstra, Bloom filters, Ethernet,
  end-to-end arguments, DNS, consistent hashing, CAP, PageRank, LZ77, TCP congestion control, GFS, Dynamo, Raft, Tor, MapReduce, Bigtable, Bitcoin, Kafka, the tail at scale, Dremel, Borg);
  reinforcement learning (Q-learning, REINFORCE, policy gradients, DQN, TRPO, GAE, AlphaGo, RLHF, PPO, DeepSeekMath/GRPO, DPO, DeepSeek-R1); and LLM inference (attention, scaling laws, RMSNorm,
  FlashAttention, GQA, continuous batching, speculative decoding, ZeRO, MLA, PagedAttention, ring attention, test-time compute, sparse and linear attention, KV-cache placement, FP4 quantisation).
- **Why it matters for Diya:** most of it is education about how the models Diya *uses* are built and served; very little changes what Diya does. The places it touches the product: word2vec and RAG
  (the `nomic-embed-text` embeddings and `search_notes`; relevance recall); ReAct, Toolformer, chain of thought, GPT-3 and InstructGPT (why a tool-calling loop needs gates when the model is small);
  attention, GQA, FlashAttention, PagedAttention and the KV-cache papers (why `num_ctx` decides whether a model loads on a 16 GB laptop, why the keep-warm prompt prefix is reused, why temperature 0 is
  not reproducible, which is why Diya's evals vary between runs); speculative decoding (a possible speed-up if Ollama ever exposes it); quantisation (which models fit); test-time compute scaling
  (Snell et al.: spending more inference compute can beat a bigger model, which is the case for the look-it-up second pass and for retries, in small doses); LoRA, DPO and distillation (the only
  routes to adapting a small model to one person, a later idea that needs a GPU); the DNS paper (time-to-live: the same idea as facts that expire); "end-to-end arguments" (put the check where
  it can be complete: in code at the end, not the model in the middle, which is `GATE_BENCHMARK.md` again). The distributed-systems papers describe systems Diya deliberately is not (one machine,
  one person); the training and serving-at-scale papers need hardware Diya does not have.
- **Action:** a reading path for the owner, in the order that builds on itself, each with something to try on this laptop, is in `docs/RESEARCH_PLAN_2026-10.md`; nothing is built from this entry.

### 33. Are there already repositories like Diya? A survey of GitHub, read live on 2026-10-13 (51 repositories)

- **Source:** the GitHub search and API (`gh`), run on 2026-10-13 with eight searches ("local-first personal AI assistant", "AI agent long-term memory", "second brain", "openclaw", "hermes agent" and
  similar) plus the projects already in this file; stars, licence and last push are what the API returned that day. READMEs read for Hermes Agent, supermemory and Leon (and OpenClaw, Khoj, Hindsight
  in earlier entries). The owner asked for it ("i feel like there are already repos in github like this already can u check all of them"). "All of them" is not possible: the search found about 50
  that matter and hundreds of small ones, and the listing below is the part that overlaps with what Diya does.
- **Noted:** 2026-10-13.
- **Answer: yes, many, and several are far bigger and better funded.** Stars are popularity, not use; "Last push" is when someone last committed.

| Kind | Project | Licence | Stars | Last push | What it is, in one line |
|---|---|---|---|---|---|
| Personal agent | openclaw/openclaw | MIT | 391,842 | 2026-10-13 | self-hosted agent that lives in 20+ chat apps, with skills and a scheduler (entry 16) |
| Personal agent | NousResearch/hermes-agent | MIT | 253,307 | 2026-10-13 | "self-improving" agent: its own memory (SQLite, full-text search), skills it writes, a built-in cron scheduler, Telegram/Discord/Slack/WhatsApp/Signal, **native Windows** |
| Personal agent | khoj-ai/khoj | **AGPL-3.0** | 37,669 | 2026-08-02 | "second brain": answers from the web or your documents, scheduled automations; its hosted cloud closed in April (entry 16) |
| Personal agent | leon-ai/leon | MIT | 17,575 | 2026-10-12 | open-source assistant since 2019, now a "2.0 developer preview": tools, layered memory, a proactive "pulse", computer use, local models, Windows |
| Chat front end | open-webui/open-webui | not machine-readable (custom) | 155,505 | 2026-10-12 | the usual Ollama web UI |
| Chat front end | Mintplex-Labs/anything-llm | MIT | 67,014 | 2026-10-12 | local chat over your documents |
| Chat front end | janhq/jan | not machine-readable | 44,930 | 2026-10-13 | an offline ChatGPT-style desktop app |
| Memory layer | mem0ai/mem0 | Apache-2.0 | 67,103 | 2026-10-12 | memory for agents as a library and a service (entry 26) |
| Memory layer | vectorize-io/hindsight | MIT | 49,029 | 2026-10-12 | retain, recall and reflect; runs locally with Ollama on Windows (entry 14) |
| Memory layer | supermemoryai/supermemory | MIT | 31,206 | 2026-10-13 | the engine behind entry 28, with a one-binary local mode that works with Ollama: facts, profile, updates and forgetting, hybrid search, connectors |
| Memory layer | topoteretes/cognee, getzep/graphiti, letta-ai/letta, MemTensor/MemOS | Apache-2.0 | 32,142 / 31,697 / 25,123 / 11,845 | 2026-09 to 10 | graph or "stateful agent" memory platforms |
| Memory layer | basicmachines-co/basic-memory | **AGPL-3.0** | 4,162 | 2026-10-12 | memory as plain Markdown notes |
| Knowledge base | Sentient-OS-Labs/sentient-os | **AGPL-3.0** | 568 | 2026-10-11 | entry 29 |
| Knowledge base | supermemoryai/company-brain | Apache-2.0 | 996 | 2026-10-02 | entry 10 |

Not comparable and left out: coding agents (OpenHands, Open Interpreter), browser agents (browser-use), agent frameworks (autogen, agno), and the dozens of OpenClaw skill lists and installers.

- **What this means for Diya:** (a) The *category* is crowded and Diya will not out-feature it (entry 16 said so; the numbers are now 391k and 253k stars). (b) The *parts* are largely available as libraries: a memory
  layer (Hindsight, supermemory local, mem0), a scheduler and cron-style automations (Hermes), a chat front end (Open WebUI), layered memory and a proactive pulse (Leon). Most are **MIT or Apache-2.0**,
  which allow reuse *with* the copyright notice kept; a few important ones are **AGPL-3.0** (Khoj, Sentient OS, basic-memory), which cannot be built into an all-rights-reserved project. (c) What the
  READMEs read do **not** say they do, and Diya does: a memory the person reviews before the model is told it (Hindsight, supermemory and Hermes all say they learn automatically; the AUTO memory switch
  Diya now has keeps lanes, questions and Undo around that), actions that wait for a one-by-one approval, and everything measured with the real small model on a CPU laptop. That is a design
  choice, not a feature count, and it is judged from READMEs only. (d) What Diya genuinely lacks next to them: reach (a phone app or chat apps; Diya's Telegram and Web Push are untried), a skills
  ecosystem (deliberately none), and years of other people's testing.
- **Three honest ways forward (the owner's choice):** *Adopt*: run Hermes Agent (MIT, native Windows) as the daily assistant and keep Diya as the learning project and the audit. *Borrow*: keep
  Diya, and when it needs relevance recall or a knowledge base (units R1 and K1 of `docs/RESEARCH_PLAN_2026-10.md`), try a memory layer as a **dependency** (supermemory local or Hindsight, installed from its
  package, its licence and notice kept) before writing our own. *Build*: keep writing everything, borrowing only ideas. My recommendation is borrow-and-build, plus trying Hermes side by side for a day to
  learn what a finished daily driver feels like (entry 16 suggested the same).
- **The rule that follows (also in `THIRD_PARTY_NOTICES.md`):** code from another project goes in only with its licence read, its notice kept, its name listed and its author credited; it is never presented as ours.
  AGPL code is not used. The owner has decided to take code from these projects: that is done with their MIT and Apache-2.0 code under this rule, and what is taken is listed in `THIRD_PARTY_NOTICES.md`.
- **Action:** `docs/COMPARISON.md` lists, project by project, what each does and whether Diya has it; README says where Diya stands against these projects; `THIRD_PARTY_NOTICES.md` carries the rule; no build.

## Cross-cutting

1. Diya's differentiation is inspectability and data sovereignty. There is a cloud pole (Instinct,
   Perplexity) and a local pole (Truffle); Diya's edge over Truffle is auditability.
2. All comparables lead with "describe an outcome, it follows through". That is Stage 4 (durable
   workflows with receipts). It is the battleground; do not let it slip below memory work.
3. Instinct's failure modes (prompt injection, unauthorized actions, data retention) are
   competitive claims Diya gets to make, not just hygiene.
4. Do not chase multi-model routing or custom hardware. Ollama on one machine is the right constraint.
5. (2026-10-05, entries 16-20) The category is now crowded by open-source agents with enormous reach (OpenClaw, Hermes
   Agent) whose public record is mostly security failures. Diya's lane is "the personal agent you can audit": reviewed
   memory, approved actions, no marketplace. Say that, test it, and do not compete on number of integrations.
6. The market's answer to proactivity is user-steered scheduled tasks (entry 18), not autonomy: build recurrence and a
   "Scheduled" view before anything that decides on its own what to tell the owner.
7. Reach is Diya's real gap (entry 16): every comparable lives in the chat apps people already open. A phone channel is
   the biggest missing piece for daily use, and the one that most needs the security rules of entry 17 first.
8. (2026-10-09, entries 21-23) "What it learns about you belongs to you" is now said by several products; Diya can make it
   checkable: a person can see, correct and take away everything it knows. Memory that consolidates itself is a known
   attack surface (entry 17), so any merge or retirement of accepted facts should be proposed to the owner, never done by
   a background job.
9. (2026-10-10, entries 26-27) Self-tidying memory is now sold by several vendors (Mem0 Dream, Devin Dreaming, Truffle's own
   "Dreaming"). Every one of them acts on its own and none says how a wrong memory is stopped from getting in or how a merge
   is checked. Diya's version is the same idea with the checking built in: lanes decided by code, secrets never kept, sensitive
   classes asked about, a cap and a circuit breaker, Undo, and a measurement on real conversations before it is switched on.
   The rule from note 8 still holds for what the owner did not say: nothing a background job *infers* (a merged, retired or
   synthesized fact) becomes true without the owner.
10. (2026-10-13, entries 28-29, 31) The memory vendors and the open-source "knows you" apps agree on the shape: a nightly on-device pass, a store the person can read, a short profile always
    present. They differ from Diya where it counts: they act on what they infer. For a small memory the evidence says to tell the model everything (entry 28); the real gaps are time (facts
    that go out of date), relevance when the memory has grown, and documents as a second source (a Markdown knowledge base). Everything inferred stays a proposal to the owner (notes 8 and 9).
11. (2026-10-13, entry 30) The week's research says the harness, not the weights, is where agents improve, and that agents can now edit their own harness from execution feedback. For
    Diya the usable form is propose-only: a script may write a suggested edit; only the owner applies one. A model that grades its own work shares its own blind spots.
12. (2026-10-13, entry 29) "Copy wherever needed" is a licence question before it is an engineering one: Sentient OS is AGPL-3.0 and Diya is all rights reserved, so its code cannot be copied
    into Diya; its design can. Read a project's licence before taking any code from it, and say which in the commit.
13. (2026-10-13, entry 33) Fifty projects like Diya exist and the biggest have hundreds of thousands of stars. Diya's reason to exist is not feature count: it is a memory the person
    reviews, actions that wait for approval, and measurement with a small local model. The parts (memory layers, schedulers, chat front ends) are available as MIT or Apache-2.0 libraries; use them
    as dependencies, with their notices, when a unit needs one, and never as code pasted in and renamed.
