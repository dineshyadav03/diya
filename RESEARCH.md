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

## Cross-cutting

1. Diya's differentiation is inspectability and data sovereignty. There is a cloud pole (Instinct,
   Perplexity) and a local pole (Truffle); Diya's edge over Truffle is auditability.
2. All comparables lead with "describe an outcome, it follows through". That is Stage 4 (durable
   workflows with receipts). It is the battleground; do not let it slip below memory work.
3. Instinct's failure modes (prompt injection, unauthorized actions, data retention) are
   competitive claims Diya gets to make, not just hygiene.
4. Do not chase multi-model routing or custom hardware. Ollama on one machine is the right constraint.
