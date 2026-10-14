# Research plan, October 2026: what the new research says about what we are building

> **Status (2026-10-13):** written the day the owner shared the new research (entries 28-32 of `RESEARCH.md`: a memory guide, Sentient OS, a week of self-improving-agent papers, CorpusMap, and four
> reading lists). I read and checked what could be checked (the papers' abstracts, supermemory's report, Sentient's README) and wrote down what could not. Two small things it showed were
> broken were fixed the same day. Everything else below is a proposal, in the order I would do it, for the owner to change.

## 1. What the research confirms about the way Diya is built

1. **Tell the model everything while the history is small.** ConvoMem (entry 28) finds a whole small conversation in the prompt beats a retrieval-based memory up to roughly 150 conversations
   (Mem0 scored 30-45% there). Diya's 2,000-character list of accepted facts is that design, and the owner's memory is a handful of facts. Retrieval is a later problem with a measurable trigger.
2. **Memory is a lifecycle, and Diya has the whole lifecycle** (write, update, forget, recall), with the part the vendors skip: a way to stop a wrong memory getting in (lanes decided by code,
   secrets never kept, a question for what is unsure, Undo, a circuit breaker).
3. **Code, not the model, decides when to look and what to keep.** Every product in the new research that works well puts its checks in the harness. That is `diya_intent.py` and
   `docs/GATE_BENCHMARK.md`, and it is the thing that fixed "I can't" on the owner's own chat the same day (`docs/LOOKUP_DESIGN.md`).
4. **A model must not be the only judge of its own memory or its own harness.** MASS's own authors warn that a model that is its own optimiser and evaluator can reinforce shared blind spots.
   Diya's verifier is advisory and its decisions are the owner's.
5. **Overnight, on-device consolidation is now the shared bet** (Truffle, Sentient OS, Devin, Mem0). Diya's `Diya_Dreaming` is the same job, with the review step the others leave out.

## 2. What it shows is missing, as units

"Done" is today's work. Effort is for me, in sessions. "Needs you" is a decision or an account only the owner can give.

| Unit | What | Evidence | Today | Effort | Needs you |
|---|---|---|---|---|---|
| **Q1** done | A message that only asks Diya something is never read for facts, and a fact cannot count as "grounded" in a message the extractor never read | found on the owner's own chat the day automatic memory went on: "automate whats the weather in bangalore" produced three junk facts, one accepted on its own | `only_asks` knew "run", "try", "automate", "use", "ask", "say"; `run_checks` ignores such messages as support | done | the three junk facts (13, 14, 15) are still in the owner's memory (Memory page, Undo) |
| **D1** done, more later | Facts with a loose day ("next Tuesday", "before the weekend", "tomorrow", "this month") become a *question* once the latest day they can mean has passed | entry 28 (forget; some facts expire); the owner's own exam and audit facts were never asked about because `diya_time` will not guess "next" | `diya_questions.outer_limit` | done; next: a visible "its day has passed" mark on the Memory page | answer the cards |
| **R1** done | **Relevance recall:** when the accepted facts outgrow what fits, tell the model an always-present short profile plus the facts most relevant to *this* message (the same embeddings as `search_notes`) | ConvoMem (the threshold), LongMemEval and Lost in the Middle (more text in the prompt makes the answer harder to find) | built (`docs/RECALL_DESIGN.md`): over the room, the lasting facts plus the ones closest to the message; measured 12 of 12 against 3 of 12 for the newest facts alone, with real embeddings on invented facts | done | none |
| **K1** steps 1-3 built | **A knowledge base from the owner's documents:** a nightly job (`Diya_Dreaming`) reads the notes folder, writes plain Markdown pages (one per person and project, linked), shown on a page and searchable; what it writes is *inferred*, so it is shown, correctable and never becomes an accepted fact | Sentient OS and CorpusMap (entries 29, 31); Diya's person-tagged facts are the seed | `search_notes` returns one file of one folder | L, in three steps: pages from notes (**built**, `docs/KNOWLEDGE_DESIGN.md`: made by code from the owner's own sentences, no model, measured 13 of 13 names on invented notes); the Knowledge page to read and hide them (**built**); the chat answering from a page (**built**); a second source | **which sources, one at a time** (notes folder first; Calendar next; mail and messages only if you want them) |
| **H1** step 1 built | A **harness advisor:** a script that reads the benches' failures and writes proposed edits (a diff to a prompt or a gate) for the owner to approve; it never applies one | Harness Learning, HERMES, VERA (entry 30); Diya already improves by exactly this loop, by hand | `diya_*_bench.py` and `docs/*_BENCHMARK.md` | M | built for one gate (`docs/ADVISOR_DESIGN.md`): `python diya_advisor.py propose` found a safe-looking patch for each of the six documented misses of the reminder gate and changed nothing; more gates are one table entry each |
| **J1** on hold (owner, 2026-10-13) | **A journal of tool calls:** every tool call the model makes (name, redacted arguments, ok or failed, thread, whether unattended) in an append-only table the owner can read, plus a per-tool Rule-of-Two table with a test that fails when a new tool has all three | numbat (entry 34); entry 17, action (a) | only what the person said and what Diya answered is stored; `action_events` covers proposals to change something | M | none |
| **E1** later | **A memory-usefulness measure:** the same questions answered with and without the owner's memory, so "is memory helping?" is a number | "agent plasticity" (entry 30), LongMemEval's five abilities | `diya_autonomy_bench.py` measures safety, not usefulness | M | consent to use a few of your own chats as test material |
| **V1** maybe | Two extraction passes; where they disagree, ask | VeriHarness (disagreement carries information) | one pass | S, but doubles the CPU of Dreaming | none |
| **M1** open | **Diya as an MCP client:** connectors added as MCP servers, the way Claude does | your question about Google; entry 19 | `diya_connectors.py` is Diya's own registry | L, needs its own design (what a server may do without asking) | priority against K1 |
| **L1** far | Adapt a small model to the owner (LoRA or preference tuning on reviewed facts) | entry 32 (LoRA, DPO, distillation) | none | needs a GPU | no |

## 3. What not to build, and why

- **Anything about serving or training models at scale** (FlashAttention kernels, PagedAttention, MoE routing, ZeRO, ring attention, RL training, the distributed-systems list): Diya runs one small model
  on one laptop through Ollama; these decide how Ollama behaves, and are worth *understanding* (section 5), not copying.
- **Sidekick-style computer use** (clicking for you without asking each time): the opposite of Diya's approval gates (entry 17). A *draft* reply that the owner sends (Double Tap) is fine as a
  later idea; it needs Windows integration and is not part of this plan.
- **Copying code from the projects in the research.** See the next section.

## 4. The licence rule for "we will copy wherever needed"

Ideas, designs and file formats can be copied freely; **code is another matter.** Diya is published *all rights reserved*. Sentient OS's code is **AGPL-3.0**: copying any of it into Diya would oblige
Diya to be offered under the AGPL. supermemory's `company-brain` is Apache-2.0 (entry 10), which allows copying with a notice. Before any code is taken from a project, its licence is read and written
into the commit message; the default is to write our own from the design. Borrowed code is never presented as ours; the rule is written out in `THIRD_PARTY_NOTICES.md`, and `RESEARCH.md` entry 33 lists
fifty similar projects with their licences (MIT and Apache-2.0 ones can be used as dependencies or, with their notice kept, copied; the AGPL ones cannot).

## 5. A reading path (for you; nothing here is a prerequisite)

In the order that each paper makes the next one easier, with something to try on this laptop:

1. **Attention Is All You Need**: what a language model is made of. *Try:* `ollama show diya-chat` (parameters, context length, quantisation).
2. **Efficient Estimation of Word Representations** (word2vec): why words become lists of numbers. *Try:* ask for the embedding of two similar sentences (`nomic-embed-text`) and compare them.
3. **Retrieval-Augmented Generation**: answers drawn from documents outside the model. *Try:* read `Agent.search_notes`, add a note to `sample_notes/`, ask about it (it is found without a restart).
4. **ReAct** and **Toolformer**: a model that acts through tools. *Try:* read `Agent._ask_loop` and watch the `[tool call]` lines in the API's output while you chat.
5. **Chain-of-Thought** and **Scaling LLM Test-Time Compute** (Snell et al.): why spending more inference effort can beat a bigger model. *Try:* turn `DIYA_LOOKUP` off and on and ask "who is the current CEO of OpenAI?".
6. **InstructGPT** then **DPO**: why a model follows instructions at all, and why a small one still needs the gates in `diya_intent.py`.
7. **GQA** and **PagedAttention**: what the KV cache is. *Try:* read `ollama/diya-chat.Modelfile` (the 16,384-token cap) and see why a bigger window would not load.
8. **LongMemEval**, **ConvoMem** and **Lost in the Middle** (entry 28): why memory is more than a big prompt.
9. **LoRA**: the way a model is adapted to one person, if that is ever wanted.

## 6. What I need from you

1. **K1 sources.** The notes folder first (nothing leaves the computer, nothing new to connect)? Then Google Calendar once it is connected? Mail and messages: only if you want, one at a time.
2. **R1.** Wait until the memory grows (my recommendation: the numbers say you are far from needing it), or do it now?
3. **H1.** May I build the propose-only harness advisor?
4. **M1 against K1.** Which first? (My order: K1 pages from your notes, then MCP.)
5. **More research.** Anything else you have, bring it: each piece gets an entry, a verdict and, if it earns it, a unit here.
