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
- **Action:** no new build. `diya_intent.py`'s checks are the existing, already-measured answer to the
  decision-gating idea; keep them as the reference rather than adding a second model. Do not adopt
  Cloudflare Workers, a vector database or a reranker: wrong stack (Diya is Python/SQLite/local;
  `company-brain` is TypeScript/Cloudflare/multi-tenant) and wrong scale, and it would break
  cross-cutting note 4. Revisit only once Diya's memory outgrows a single embedding lookup and a
  2,000-character profile.

## Cross-cutting

1. Diya's differentiation is inspectability and data sovereignty. There is a cloud pole (Instinct,
   Perplexity) and a local pole (Truffle); Diya's edge over Truffle is auditability.
2. All comparables lead with "describe an outcome, it follows through". That is Stage 4 (durable
   workflows with receipts). It is the battleground; do not let it slip below memory work.
3. Instinct's failure modes (prompt injection, unauthorized actions, data retention) are
   competitive claims Diya gets to make, not just hygiene.
4. Do not chase multi-model routing or custom hardware. Ollama on one machine is the right constraint.
