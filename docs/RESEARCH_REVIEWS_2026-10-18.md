# Research reviews done on 2026-10-18 (task sheet rows DIYA-183, 184, 236, 239, 241, 274, 278, 292, 298)

The task sheet's research-review rows all share one definition of done: *"Retain source URLs and claims; verify source/feasibility/license; link to an engineering task or explicitly decide experiment, defer or
archive."* This file is that, for the eight rows that could be closed honestly today. The long-form notes stay in `RESEARCH.md` (entries 10, 14, 28, 34) and `docs/STUDY_SUPERMEMORY.md`, `docs/STUDY_REA.md`;
this adds what was **rechecked today** and **the decision**, in one place. Each statement is **observed** (read or queried today), **inferred** (with its basis) or **not established**.

## Licences and activity, queried today (`gh api repos/<owner>/<repo>`, 2026-10-18)

| Repository | Licence | Stars | Last push | Rule for Diya |
|---|---|---|---|---|
| supermemoryai/supermemory | MIT | 31,274 | 2026-10-18 | clients and docs; may be read and copied from with the notice kept; the engine is **not** here |
| supermemoryai/company-brain | Apache-2.0 | 1,015 | 2026-10-02 | may be copied from with the notice kept; ideas taken, no code copied (different language and stack) |
| morluto/rea | MIT | 315,613 | 2026-10-18 | method only; not run |
| vectorize-io/hindsight | MIT | 51,036 | 2026-10-17 | read, not run; ideas taken |
| mem0ai/mem0 | Apache-2.0 | 67,376 | 2026-10-17 | not read in depth |
| microsoft/SkillOpt | MIT | 18,520 | 2026-10-17 | not read in depth (validation-gated edits; reopen with the "skills" work) |
| openclaw/openclaw, NousResearch/hermes-agent | MIT | 392,338 / 254,820 | 2026-10-18 | compared before (RESEARCH.md 16–20); no code taken |
| khoj-ai/khoj | **AGPL-3.0** | 37,730 | 2026-08-02 | **never copied from**: AGPL would put Diya's own code under AGPL |
| Sentient-OS-Labs/sentient-os | **AGPL-3.0** | 590 | 2026-10-18 | **never copied from**, same reason |
| perplexityai/numbat | Apache-2.0 | 1,126 | 2026-10-16 | ideas only (Go, different job) |
| rasbt/LLMs-from-scratch | NOASSERTION | 106,780 | 2026-10-02 | no licence stated by the API: read, never copy |
| ufo-ai/ufo-core, walkinglabs/learn-harness-engineering, kunchenguid/backpass, HelixDB/helix-db, HelixDB/helix-foundry, mariagorskikh/open-instinct, mizorewww/laya-mlx, karpathy/nanochat | Apache-2.0 / MIT | various | 2026-09 to 2026-10 | listed in the sheet, not part of today's reviews |

**The licence rule** (the "license-aware dependency policy" the sheet asks for): code may be copied only from MIT / BSD / Apache-2.0 sources, with the notice kept and the source named in the file; AGPL,
GPL, "no licence" and NOASSERTION sources are read for ideas and never copied; a closed binary or hosted service is never given the owner's memory; nothing from a repository is installed or run without the
owner's yes in the chat.

## DIYA-239 — U04: reverse-engineer `morluto/rea` and `supermemoryai/supermemory`, integrate ideas
* **Sources:** https://github.com/morluto/rea, https://github.com/supermemoryai/supermemory, https://github.com/supermemoryai/company-brain. **Claims retained:** `docs/STUDY_REA.md` (8 ideas, all cited to files), `docs/STUDY_SUPERMEMORY.md` §3 (documented behaviour) and §8 (company-brain source).
* **Verified today:** licences and activity (table above). **Feasibility:** only the *policy* ideas are portable; the supermemory engine is closed (`overview.mdx`: "the server binary is not open source").
* **Decision:** integrate ideas, not code, and not the binary. **Built:** `diya_repostudy.py` (REA's observed / inferred / not-established report), `diya_fade.py` + mentions + Keep (company-brain's decay-unless-reinforced), the partial-view note on recall. **Deferred:** aliases/entity pages, a topic map (`STUDY_SUPERMEMORY.md` §8). **Not done:** REA and "Supermemory local" were not run; each needs the owner's explicit yes.

## DIYA-183 — Analyze REA and Supermemory with actual source citations
* Done as above: every claim in the two study files names the file it came from, or is marked inferred / not established; the proposals are in `STUDY_SUPERMEMORY.md` §6 and §8 (a table of what was taken, built, deferred, skipped), none a wholesale copy.
* **What was not read** is stated in both files (REA: all but about 8 of 3,981 files; supermemory: about 15 of 938 files, plus 16 company-brain files). A reader should not take silence as absence.

## DIYA-274 — R10: Supermemory / company-brain (RESEARCH.md entry 10)
* **Source:** https://github.com/supermemoryai/company-brain (Apache-2.0, rechecked today) and the founder's two posts on X (shared 2026-09-27; not re-fetched). **Claims retained:** a small "decision model" can improve capture, filtering and reranking.
* **Measured before, not assumed:** `docs/GATE_BENCHMARK.md` (2026-09-27): the local model was *worse* than Diya's code checks at the decision gates (0 of 12 genuine fact-shares against the code's 47 of 47).
* **Decision:** keep code as the decider (confirmed again by reading company-brain, whose own writes are made by an agent but are stamped, de-duplicated by hash and filtered by a written capture policy). Nothing to build from the TypeScript/Cloudflare stack. **Taken from the policy text:** fading and the partial-view note (`docs/FADING_DESIGN.md`).

## DIYA-278 — R14: Hindsight (RESEARCH.md entry 14)
* **Source:** https://github.com/vectorize-io/hindsight (MIT, rechecked today), README read in full today. **Claims retained:** memories split into world facts, experiences, *observations* (consolidated beliefs with evidence) and mental models; retain / recall / reflect; recall combines semantic, keyword, graph and time, merged and re-ranked; an opt-in "Memory Defense" policy that scans every retain for secrets and personal data (45 patterns) and redacts or blocks; benchmark results said to be independently reproduced (still the vendor's claim, **not established** here).
* **Feasibility:** runnable locally (the README documents an embedded Postgres and Ollama); the comparator run needs a second memory service on the owner's laptop and the owner's yes.
* **Decision:** **defer the side-by-side run**; it is the right comparator when the owner's memory is large enough to measure (a measured comparison on 7 live facts would say nothing). **Taken:** "keep the evidence behind a belief and how often it recurred" → `fact_mentions` and "You said it again N times"; "scan before keeping" → Diya's secret check (`diya_autonomy.secret_kind`) already does it.

## DIYA-292 — R28: Supermemory memory guide / memory layers (RESEARCH.md entry 28)
* **Source:** the guide the owner pasted 2026-10-13 plus the three papers it leans on (LongMemEval arXiv 2410.10813, ConvoMem 2511.10523, Lost in the Middle 2307.03172), all fetched and checked on 2026-10-13 (the entry records what checked out). **Claims retained:** memory is a lifecycle (write, update, forget, infer, recall); small histories do best when the whole chat is in the prompt.
* **Layers (the sheet's acceptance wording):** Diya's layers are written down in `docs/MEMORY_TAXONOMY.md` (conversation, working, accepted facts, provisional facts, episodic, commitments, source-backed Knowledge pages, derived cache, Dreaming) with the gaps named (skills/procedures, per-fact expiry — *the second now exists for passing states*, `docs/FADING_DESIGN.md`).
* **Decision:** no build from the guide itself; it fed time-aware facts, relevance recall and the knowledge base (all built) and, today, fading. **Long-term evaluation:** deferred until there are months of real use; the owner's real questions are the only honest test set (`docs/MONTHLY_CHECKS.md`).

## DIYA-298 — R34: numbat, an agent audit journal (RESEARCH.md entry 34)
* **Source:** https://github.com/perplexityai/numbat (Apache-2.0, rechecked today; README and four docs read on 2026-10-13; nothing run). **Claims retained:** one normalised event per tool action in an append-only log; arguments redacted; monitor by default, enforcement only denies; sequence rules (secret read followed by send).
* **Decision: build the journal; do not install numbat.** Built: `diya_journal.py` and the `tool_journal` table (append-only by trigger), one row per tool call or flow, status ok / error / refused, argument digest and a preview with secret-looking values hidden, no result stored; `tests/test_journal.py` (14); Activity page. **Deferred on purpose:** the *sequence* rule (a per-tool Rule-of-Two table as a test); the red-team test `tests/test_red_team.py` covers the same ground by assuming the model obeys every injected instruction.

## DIYA-236 — U01: one continuous chat that sorts itself
* **Source:** the owner's own request (source PDF p1), so there is no third-party licence to verify. **Linked work:** `docs/ONE_CHAT_DESIGN.md`, `diya_categories.py`, `tests/test_one_chat.py` (19 test functions).
* **The sheet's check, "validate no duplicate conversations":** `test_callers_asking_at_the_same_moment_get_the_same_chat_and_only_one_is_made` (concurrent callers get one chat); `test_with_no_chat_at_all_the_one_chat_is_made_once_and_called_diya`; a message that names no chat goes into the one chat every time; looking at the history makes no chat.
* **Decision:** implemented and tested; closed. (Whether *sorting* is right is a different row, DIYA-238, which stays open.)

## DIYA-241 — U06: immediate memory ("Hog"); cache before Dreaming
* **Source:** the owner's own report (the dog "Hog"). **Linked work, all in the sheet as Done:** DIYA-019 (capture outbox saved in the same transaction as the message), DIYA-020 (the fact reaches the model on the next turn), DIYA-026 (`tests/test_hog_regression.py`: next turn, history cut, cold restart, correction, forgetting, malicious email), DIYA-023 (correction), DIYA-024 (forgetting).
* **Decision:** implemented as the sheet's own note asks ("P0: durable outbox + live working memory; test rigorously"); closed.

## DIYA-184 — company-brain, Hindsight and Devin memory ideas, contrasted
The sheet asks for a contrast of **algorithm, locality, licence, safety and benchmark**. Sources: company-brain's source (16 files read today) and README; Hindsight's README (read in full today); Devin from `RESEARCH.md`
entries 21 and 26 (the Cognition docs page https://docs.devin.ai/product-guides/memory, as recorded on 2026-10-10) plus a third-party write-up read today (secondhand: the Cognition page itself could not be fetched today).

| | company-brain (supermemory) | Hindsight (vectorize-io) | Devin Memory (Cognition) | Diya now |
|---|---|---|---|---|
| **Algorithm** | An agent writes memory documents (title, one self-contained text, sources, an event date, 1–3 hierarchical tags), stamped with the date and given a hash id so a rewrite is idempotent; a written capture policy (decay unless reinforced, supersede rather than duplicate); recall = an always-present profile + a topic outline + search, under a token budget with a "not the complete set" note. The extraction/graph/ranking engine is supermemory's hosted service, not in the repository | A model extracts facts, entities and times into world facts and experiences; observations are consolidated beliefs with evidence; recall merges semantic, keyword, graph and time results and re-ranks; retain / recall / reflect | Markdown notes in a Git repository, an index loaded at the start of each session, each note linking to the session it came from; a daily Dreaming pass merges overlapping notes, drops transient ones and ones no session used | Code decides what is kept (lanes, a privacy check by two judges, a daily cap); every fact has a trail; recall chooses the facts closest to the message; passing states fade unless said again; a Markdown copy can be exported and restored |
| **Locality** | Slack bot on Cloudflare Workers plus supermemory's cloud service: **not local** | **Can run fully local** (the README documents embedded Postgres and Ollama) | Cloud product; the repository's hosting is not stated | Everything on this laptop; the only outbound traffic is what a task needs |
| **Licence** | Apache-2.0 (checked today) | MIT (checked today) | Product proprietary; the notes format ("Agent Memory Repo") is described as an open specification, no licence named in what was read | All rights reserved; ideas credited, no third-party code copied for these features |
| **Safety** | Has a permissions guide (`docs/guide/permissions.md`, **not read**); memory is split into private and shared scopes; no defence against instructions hidden in remembered text was seen in the files read | Opt-in "Memory Defense" scan for secrets and personal data (45 patterns) that redacts or blocks | Memory is personal, read-only in the app, off-switchable; automated sessions neither read nor write it | Secrets never kept; text from the web, mail and calendars is read by a second pass with no tools and never obeyed; a red-team test assumes the model obeys every instruction; everything is undoable and journalled |
| **Benchmark** | None in the repository; supermemory's own LongMemEval / LoCoMo / ConvoMem claims are the vendor's (`STUDY_SUPERMEMORY.md` §5) | LongMemEval results, said to be independently reproduced by two institutions: **not verified here** | None given in what was read | A question-and-answer measurement of Diya's own memory (`docs/MEMORY_BENCH.md`); nothing comparable to the vendors' numbers, so no ranking is claimed |

**What follows.** Nothing in this table argues for switching to any of the three; each shows a technique Diya can take without taking the product: fading and the partial-view note (company-brain), the evidence count (Hindsight),
and a Markdown copy of memory (Devin and company-brain), all built today. What none of them shows is a better answer to the thing Diya is for: the owner can read, correct and take back every fact. The comparison run that
would put numbers beside this table (Hindsight locally, same machine, same questions) is deferred under DIYA-278.

## What these reviews do not prove
* They record what was read and decided. They do not show that Diya's memory is *better* than supermemory's or Hindsight's: no head-to-head was run, and the vendors' benchmark numbers were not reproduced.
* Devin's memory is closed; what is known of it is from the vendor's docs page as recorded on 2026-10-10 and a third-party write-up. It is a description, not a verified source.
* Nothing from the three projects was installed or run.
