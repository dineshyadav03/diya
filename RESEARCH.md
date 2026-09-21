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

## Cross-cutting

1. Diya's differentiation is inspectability and data sovereignty. There is a cloud pole (Instinct,
   Perplexity) and a local pole (Truffle); Diya's edge over Truffle is auditability.
2. All comparables lead with "describe an outcome, it follows through". That is Stage 4 (durable
   workflows with receipts). It is the battleground; do not let it slip below memory work.
3. Instinct's failure modes (prompt injection, unauthorized actions, data retention) are
   competitive claims Diya gets to make, not just hygiene.
4. Do not chase multi-model routing or custom hardware. Ollama on one machine is the right constraint.
