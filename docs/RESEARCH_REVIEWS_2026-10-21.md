# Research reviews done on 2026-10-21 (task sheet rows DIYA-237, 244, 245, 251, 252, 255, 262, 264, 271, 272, 276, 279, 280, 281, 282, 283, 286, 288, 293, 294, 295, 297)

Same definition of done as the 2026-10-18 reviews (`docs/RESEARCH_REVIEWS_2026-10-18.md`): *"Retain source URLs and claims; verify source/feasibility/license; link to an engineering task or explicitly decide
experiment, defer or archive."* Everything below that says **today** was fetched on 2026-10-21 with `gh api` (licence, stars, last push, archived flag, README) or a plain HTTP request (status, title) and the arXiv
abstract pages. The long-form notes stay in `RESEARCH.md`; this adds what was **rechecked today** and **the decision**. Each statement is **observed** (read today), **recorded** (from the RESEARCH.md entry, not re-read
today) or **not established**. Nothing was installed or run: a repository is read, never executed (the owner's rule, `docs/DECISIONS_2026-10-18.md`).

## Licences and activity, queried today

| Repository | Licence | Stars | Last push | Rule for Diya |
|---|---|---|---|---|
| mizorewww/laya-mlx | Apache-2.0 | 6,990 | 2026-10-20 | may be read and copied from with the notice kept; Apple-silicon only, so nothing to copy |
| NandhaKishorM/laya (upstream of the above) | Apache-2.0 | 33,732 | 2026-10-19 | same |
| ufo-ai/ufo-core | Apache-2.0 | 100 | 2026-10-21 | ideas only (a multi-tenant team runtime) |
| walkinglabs/learn-harness-engineering | MIT | 21,047 | 2026-10-20 | a course; read for vocabulary |
| kunchenguid/backpass | MIT | 1,402 | 2026-10-20 | ideas only (Node; the README's platform badge says macOS and Linux) |
| microsoft/SkillOpt | MIT | 18,596 | 2026-10-18 | ideas only (needs a held-out score and an optimiser model) |
| openclaw/openclaw, NousResearch/hermes-agent | MIT, MIT | 392,707 / 255,656 | 2026-10-21 | reference for what people use daily; no code taken |
| khoj-ai/khoj | **AGPL-3.0** | 37,765 | **2026-08-02** | never copied from (AGPL would put Diya's own code under AGPL); no push for about 11 weeks |
| mariagorskikh/open-instinct | MIT | 376 | 2026-10-21 | ideas only |
| HelixDB/helix-foundry, HelixDB/helix-db | Apache-2.0, Apache-2.0 | 1,637 / 6,222 | 2026-10-13 / 2026-10-20 | not adoptable (Docker + graph database + DuckDB) |
| Sentient-OS-Labs/sentient-os | **AGPL-3.0** | 600 | 2026-10-20 | never copied from |
| lyogavin/airllm | Apache-2.0 | 39,966 | 2026-10-20 | read; not run |
| NVIDIA/Model-Optimizer | Apache-2.0 | 5,387 | 2026-10-21 | read the description only; needs NVIDIA hardware for its main paths (recorded) |
| google-research/timesfm | Apache-2.0 | 34,673 | 2026-09-29 | no use for Diya now |
| karpathy/nanochat | MIT | 58,824 | 2026-09-07 | education |
| rasbt/LLMs-from-scratch | **NOASSERTION** (no licence the API can read) | 106,996 | 2026-10-02 | read, never copy |
| Ramakm/folio-anatomy | MIT | 10 | 2026-10-13 | candidate for the "Anatomy" note (see DIYA-251) |

**The licence rule is unchanged** (RESEARCH_REVIEWS_2026-10-18): code is copied only from MIT / BSD / Apache-2.0 sources with the notice kept; AGPL, GPL, "no licence" and NOASSERTION sources are read for ideas only;
a closed binary or hosted service is never given the owner's memory.

## DIYA-271 — R07: laya-mlx
* **Sources:** https://github.com/mizorewww/laya-mlx and its upstream https://github.com/NandhaKishorM/laya (both queried today). **Claims retained** (README heads read today): laya-mlx: "13.4 ms median end-to-end for a short English typed decision",
  "7.4 ms with the multilingual checkpoint", "0 output tokens", native MLX with no PyTorch or cloud API (the repository description says the timing is on an M3 Max). Upstream: "typed decisions over 100+ languages in a single forward pass — 33 ms",
  with optional ONNX, HTTP and MCP extras. The older note's "50x faster than Jev" is the porter's own claim and was **not found** in the README text read today.
* **Feasibility:** MLX runs on Apple silicon only, so laya-mlx cannot run on this Windows laptop. The upstream package states Python 3.10+ and an ONNX extra, so it could run on this CPU, but **that was not tried**.
* **Decision: defer, as a baseline for DIYA-199** (evaluate a fast router against deterministic rules). Diya decides with code first, and the measurement already made says why: the local model was worse than the code checks at the decision gates (`docs/GATE_BENCHMARK.md`).

## DIYA-272 — R08: OpenJev
* **Source:** the Hugging Face organisation `com-kotobalabs` (https://huggingface.co/com-kotobalabs answers HTTP 200 today; the original source was a social reel and its exact demo is still unverified). The models there were not opened.
* **Claim retained:** voice → transcript → a tiny decision model → execute, with no large model in the routing loop. The pattern is sound; Diya already has both ends (Whisper in, speech out).
* **Decision: defer.** Linked to DIYA-199 (router baseline) and DIYA-205 (partial transcripts and interruption).

## DIYA-245 — U10: Jev, OpenJev-type fast deciders, THX-01 and "~10 ms"
* **Observed today:** the ~10 ms figure is in the range laya-mlx publishes (7.4 and 13.4 ms) but on Apple silicon; upstream's own figure is 33 ms. A GitHub search for "THX-01" found nothing relevant, so **THX-01 is not identified**. Jev itself is a closed API (recorded).
* **Decision: benchmark only, never assume** (the sheet's own wording). Linked to DIYA-199. Nothing about speed is claimed for this laptop.

## DIYA-276 — R12: UFO, the "Learn Harness Engineering" course, backpass
* **Sources:** https://github.com/ufo-ai/ufo-core, https://github.com/walkinglabs/learn-harness-engineering, https://github.com/kunchenguid/backpass (all three queried and their READMEs read today). **Claims retained:** UFO: "Run AI agents for your team on your own infrastructure", each turn "a DBOS workflow that survives a crash",
  "a member grants an account to an agent in chat", every row carries a workspace id. backpass: reads the transcript stores of seven agent harnesses; every `add`, `rewrite` or `remove` edit "needs evidence from at least two distinct sessions"; "Analysis never writes".
* **Decision (unchanged from RESEARCH.md entry 12):** no adoption. Three ideas are kept and linked: durable turns → DIYA-166 (a workflow runner with checkpoints); grants in chat → DIYA-167 (authority envelopes: a background trigger cannot gain scopes);
  evidence-gating for edits → DIYA-186 (a proposed change is tested before it can be accepted). UFO's multi-tenant shape is a gap Diya does not have.

## DIYA-279 — R15: SkillOpt
* **Sources:** https://github.com/microsoft/SkillOpt and the paper https://arxiv.org/abs/2605.23904 ("SkillOpt: Executive Strategy for Self-Evolving Agent Skills", submitted 2026-05-22; both answered today). **Claim retained, from the abstract:** a separate optimiser model turns scored rollouts into bounded
  edits on one skill document, and "an edit is accepted only when it strictly improves a held-out validation score". The paper's own results (52 evaluated cells) were **not reproduced**.
* **What changed since the earlier note:** Diya now has playbooks (steps the owner writes, `docs/PLAYBOOKS_DESIGN.md`), the first skill-like documents it has. SkillOpt's subject still does not transfer (the playbooks are the owner's words and grant nothing), but its gate does.
* **Decision: no adoption; keep the gate.** If playbooks or the harness are ever to be improved by a model, the change is a proposal, tested on held-out cases, accepted by hand: that is what `diya_advisor.py` already does for the reminder gate. Linked to DIYA-185, 186 and 187.

## DIYA-280 — R16: OpenClaw / Hermes / Khoj
* **Sources:** https://github.com/openclaw/openclaw (MIT, 392,707 stars), Hermes Agent (MIT, 255,656), Khoj (AGPL-3.0, 37,765, **last push 2026-08-02**) and Microsoft's "Running OpenClaw safely" post (HTTP 200 today).
* **Claims retained** (entry 16): these live in the chat apps people already open; Microsoft's verdict on the leader is to run it on a separate machine with throwaway credentials. **Truffle**: not re-checked today (entry 25).
* **Decision: reference only.** Reach is the one thing they have and Diya lacks; it was built as optional channels (`diya_telegram.py`, `diya_push.py`, `docs/PHONE_CHANNEL_DESIGN.md`) that are off and **never tried against a real service**. Khoj and Sentient are AGPL: never copied.

## DIYA-281 — R17: agent security (lethal trifecta, Rule of Two, memory poisoning)
* **Sources, all answered today:** https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/, https://ai.meta.com/blog/practical-ai-agent-security/, https://thehackernews.com/2026/07/new-memghost-attack-plants-persistent.html; arXiv 2606.04329 ("From Untrusted Input to Trusted Memory"), 2605.15338
  ("Hidden in Memory: Sleeper Memory Poisoning in LLM Agents"), 2607.05189 ("When Claws Remember but Do Not Tell"), 2509.10540 (EchoLeak). Abstracts of the papers were not re-read; titles and dates are as the arXiv pages give them today.
* **The entry's two actions.** (a) *Write the Rule-of-Two accounting per tool and add a test that fails when a new tool completes all three without the approval gate*: **built today** (`diya_catalog.py` `legs()`, `rule_of_two_violations()`, `session_exposure()`; `tests/test_rule_of_two.py`, 8 tests; a table in `docs/AUTHORITY_MODEL.md`).
  (b) *"The reader never writes memory"* is already enforced: Dreaming reads only the owner's own messages, and `tests/test_hog_regression.py` and `tests/test_adversarial_suite.py` try a malicious email.
* **A finding that is the owner's to decide.** No single tool has all three legs, but **a chat session does**: the tools that bring in the owner's data and other people's words (`list_files`, `search_notes`, the Notion/Todoist/Calendar/Tasks/Home Assistant reads) sit next to `web_search` and `get_weather`, which send the model's own words out with no approval.
  A hidden sentence in a note could in principle make the model put private text in a search query. The doc states it and the test pins it so it cannot grow unseen; closing it (approve each search, or a search that sees no private text) is a decision, not built.
* **Linked:** DIYA-043 (data-origin taint labels), DIYA-040 (allowlists).

## DIYA-282 — R18: ChatGPT Pulse retired for "scheduled tasks"
* **Sources:** the digit.in report answers (HTTP 200 today); OpenAI's help page answers **403** to an automated request, so its text was **not verified today**. The reasons are OpenAI's, second-hand (entry 18 says so).
* **Decision:** the lesson (the user steers what runs and when) was built in October as repeating reminders, snooze, the Scheduled and Today pages and Automations (`docs/PROACTIVITY_DESIGN.md`, `docs/AUTOMATIONS_DESIGN.md`). Still open and linked: DIYA-169 (a rate-limited brief with quiet hours) and DIYA-177 (helpful / not helpful on a suggestion).

## DIYA-283 — R19: local models, runtime, MCP and speech
* **Sources:** https://docs.ollama.com/capabilities/web-search answers 200 today; `https://ollama.com/api/web_search` answers 405 to a plain GET (it is a POST endpoint with a key; not called).
* **Decision:** the bake-off was done on 2026-10-09 (`docs/MODEL_BENCHMARK.md`): `qwen3:4b-instruct` beat `qwen2.5:3b` at about 1.4 times the time per message; **nothing was switched** and it is still the owner's choice. MCP: a client exists (`docs/MCP_DESIGN.md`) that only uses servers the owner added, read-only, pinned. Speech unchanged.
  Repeating the measurement with newer models is DIYA-193 and DIYA-194.

## DIYA-286 — R22: Instinct, open-instinct, Littl, Bonsai
* **Sources:** https://github.com/mariagorskikh/open-instinct (MIT, 376 stars, README read today), https://dolittl.ai (HTTP 200). The "$1B" and Bonsai items rest on the pasted post only (**unverified**).
* **Claims retained (open-instinct README):** you text a phone number; the agent lives in its own microVM with a desktop; "seven tiers, enforced in code before any tool runs"; a purchase asks a wallet for a single-use card for the exact total and the owner approves on the phone.
* **Decision: nothing to build from it.** Approval on a separate channel is Diya's own rule (a button or the command line, never a chat reply); trust tiers solve a many-person problem Diya does not have. The "everything it knows, readable and portable" test is met for facts (Markdown copy, `diya_memory_repo.py`) and **not yet** for history, tasks and reminders (DIYA-214).

## DIYA-288 — R24: helix-foundry / HelixDB
* **Sources:** https://github.com/HelixDB/helix-foundry (Apache-2.0, 1,637 stars) and https://github.com/HelixDB/helix-db (Apache-2.0, 6,222; "an OLTP graph database with native vector and full-text search built in Rust on Object Storage"). Foundry's README, read today: a local-first workspace built on HelixDB and DuckDB that needs Docker and downloads several GB on first run.
* **Decision: archive** as not adoptable (a company-data tool; Docker plus a graph database plus DuckDB; Windows untested, recorded). The idea kept is "an answer shows where it came from", which Diya has for memory ("how do you know that?", `docs/PROVENANCE_DESIGN.md`).

## DIYA-293 — R29: Sentient OS
* **Source:** https://github.com/Sentient-OS-Labs/sentient-os (AGPL-3.0, 600 stars, pushed 2026-10-20; README read today). macOS only (recorded).
* **Decision: ideas only, code never.** The idea (a linked Markdown knowledge base built from the owner's own documents) was built by Diya's own code as K1 (`docs/KNOWLEDGE_DESIGN.md`, `diya_knowledge.py`): pages made by code from the owner's sentences, no model, no code taken.

## DIYA-294 — R30: harness-learning papers
* **Sources, all answered today:** arXiv 2610.12176 (MASS, "Recursive Self-Improvement through Multi-Agent Self-Supervision", 2026-10-08), 2610.13912 (RSI-Anything), 2610.00972 (VeriHarness), 2610.01509 ("Sharpening Tax in Post-Training"), 2610.02185 ("Decoding Looped Transformers Better for (Almost) Free"). HERMES and VERA: no arXiv number was recorded, so **not re-verified**.
* **Claim retained (MASS abstract):** one base model proposes, runs and grades multi-agent workflows, then is fine-tuned on its own trajectories; "1.2-1.6x higher performance per output tokens" over two cycles **with Qwen3.6-27B**. That needs a 27B model and fine-tuning: not possible on this laptop.
* **Decision: archive the methods, keep the rule** from RESEARCH.md entry 30: harness changes are propose-only with an external held-out verifier (what `diya_advisor.py` does). Linked to DIYA-185 to 187.

## DIYA-295 — R31: CorpusMap / entity pages
* **Source identified today:** arXiv 2609.37226, "Follow the Entities: A Corpus Map for Agentic Search" (Jeong, Jauhar, Hwang; 2026-09-29). **Claim retained (abstract):** each recurring entity gets an Entity Page that aggregates what is known and links to every document that mentions it, built offline so links are shared across queries; across 7 models and 3 benchmarks it improves evidence discovery and answers "while using fewer tokens on average".
  The specific numbers in RESEARCH.md entry 31 (+6.4 to +11.7 points, 34-57% fewer tokens) came from a secondary summary and are **not in the abstract**: treat them as unverified.
* **Decision: realised in our own code as K1** (pages by code from the owner's own notes, sources linked, nothing becomes a fact on its own). The schema for people, projects and places across sources is DIYA-147 to DIYA-149, not started.

## DIYA-297 — R33: survey of comparable GitHub repositories
* **Rechecked today:** 19 of the surveyed repositories (the table above plus: leon-ai/leon MIT, Mintplex-Labs/anything-llm MIT, mem0ai/mem0 Apache-2.0, vectorize-io/hindsight MIT, supermemoryai/supermemory MIT, topoteretes/cognee, getzep/graphiti, letta-ai/letta, MemTensor/MemOS all Apache-2.0, basicmachines-co/basic-memory **AGPL-3.0**, open-webui/open-webui and janhq/jan **NOASSERTION**). No licence changed since 2026-10-13; every project is still active except Khoj.
* **Decision:** no adoption; the table and the licence rule stand. Open WebUI, Jan and LLMs-from-scratch have no licence the API can read, so they are read-only sources. Which of these to *try* is a decision for the owner, not a default.

## DIYA-252 — U17: arXiv 2609.20804
* **Observed today (abstract):** the paper is "An Empirical Study of Harness Design for Coding Agents" (Fan, Zhang, Ma and others; 2026-09-17). It is **not** a self-improving-harness paper, as the social post that sent it said: it varies planning, action space and context management in a fixed loop over 176 matched settings on SWE-Bench Verified and Terminal-Bench 2.1.
* **Findings worth keeping:** "Staging rule-based elision before LLM-based summarization provides the strongest overall efficiency"; making elided content recoverable "adds machinery that models rarely use and yields no accuracy gain"; planning is an accuracy scaffold for weak models and a cost saver for strong ones.
* **Decision: do not reproduce** (its benchmarks need large models and a container sandbox, and the job is coding agents). It supports what Diya already does: history is cut by rule, nothing is summarised by a model, and the model is told when its view is partial.

## DIYA-244 — U09: very large models one layer at a time, AirLLM, NVIDIA Model Optimizer
* **Sources:** https://github.com/lyogavin/airllm (Apache-2.0, README read today) and https://github.com/NVIDIA/Model-Optimizer (Apache-2.0; repository description read today).
* **Claims retained (AirLLM README):** runs a 70B model on a 4 GB GPU "without quantization, distillation, or pruning"; CPU inference supported since v2.10.1; the model "is first decomposed and saved layer-wise" so it needs disk space; "the bottleneck is mainly at the disk loading"; 4/8-bit block-wise compression up to "3x" faster (the project's claim). No tokens-per-second figure for a CPU-only machine was seen: **not established**.
* **Decision: defer to DIYA-198** (go or no-go on full-task responsiveness on this laptop). The reasoning stays inference: reading layers from disk for every token will not be fast on a 15.7 GB machine, which is why this is measured before it is believed.

## DIYA-251 — U16: the "Anatomy" explanation skill
* **What was found today:** the note named no repository. A GitHub search finds `Ramakm/folio-anatomy` (MIT, 10 stars, created 2026-10-11): "Explain any idea the way a museum explains a specimen", a Claude Code skill that makes live isometric HTML plates; and `Hainrixz/claude-anatomy`, a decision tree for what to build in Claude Code (not an explainer). **Which one the owner meant is not established.**
* **Decision: defer.** Nothing is imported (the sheet says "no unidentified import"). The owner can say which repository it was (DIYA-189). A teaching mode in Diya's own terms (explain at levels, one example, a quiz) is DIYA-190 and could start as a playbook the owner writes.

## DIYA-264 — U29: Karpathy nanochat, LLMs-from-scratch, openSUSE talk, company-brain, Edge0
* **Observed today:** nanochat MIT, 58,824 stars, last push 2026-09-07 ("The best ChatGPT that $100 can buy."); LLMs-from-scratch NOASSERTION, 106,996 stars; company-brain Apache-2.0, 1,034 stars. The training-cost claim, the openSUSE talk and **Edge0** were not verified or identified.
* **Decision: archive** as education and time-bound social claims (the sheet says to treat costs and popularity that way). Nothing to build.

## DIYA-262 — U27: "Smcp", Parallax (Joel Foku), Google TimesFM
* **Observed today:** `google-research/timesfm` Apache-2.0, 34,673 stars, pushed 2026-09-29: a time-series forecasting model. Diya has no numeric series to forecast. "Smcp" and "Parallax (Joel Foku)" could not be identified.
* **Decision:** archive TimesFM; keep "Smcp" and "Parallax" as ambiguous leads until the owner says what they were (the sheet's own instruction).

## DIYA-237 — U02: add / rename / merge categories, server and UI in step
* **Source:** the owner's own request (source PDF p1), so no third-party licence to verify. **Linked work:** `docs/ONE_CHAT_DESIGN.md`, `diya_categories.py`, `diya_categories_api.py`, `frontend/app/categories/page.js`.
* **The sheet's two checks.** *Server/UI parity*: `tests/test_category_undo_search.py::test_every_thing_the_categories_api_can_do_has_a_control_on_a_page` reads the API's actions (assign, add, rename, merge, browse, undo a merge, search, suggest, sort earlier chats, answer a suggestion) and fails if one has no control in the pages. *Reversible merge and audit*: built today (DIYA-156): a merge is recorded and can be undone from the page, with the list of merges as the audit trail.
* **Decision:** implemented and tested; closed. Whether the owner *likes* the categories is DIYA-155 (owner-labelled evaluation), which stays open.

## DIYA-255 — U20: messages separated day by day; change the Diya logo
* **Source:** the owner's own request (source PDF p3). **Linked work:** day separators are built (DIYA-158: `frontend/lib/day-labels.mjs`, `tests/test_day_labels.py`, drawn by the design rig). The logo is **DIYA-162**, which needs the owner's taste and a documented brand decision; it is **not** done, and this review does not close it.
* **Decision:** the day-by-day half is implemented; the logo half is deferred to DIYA-162 and the owner.
