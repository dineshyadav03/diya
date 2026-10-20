# Supermemory, studied with REA's method (2026-10-16)

**Target:** <https://github.com/supermemoryai/supermemory> (MIT licence, 938 files, last pushed 2026-10-15).
**Method:** REA's (<https://github.com/morluto/rea>, MIT), applied by hand: every statement is **observed** (read from a named file), **inferred** (a guess, with its basis), or **not established**. REA's own instructions say that for a complete open-source repository you read it with ordinary repository tools and do not run REA, because REA exists for closed binaries and apps; so nothing of REA was run and nothing of supermemory was downloaded to disk or run (see "What was not done"). Diya's new repo-study skill (`diya_repostudy.py`) produced the file-tree and manifest facts below; the rest was read from the files named.

## 1. What it is

**Observed** (`README.md`): "the memory and context layer for AI". It extracts facts from conversations, builds user profiles, handles updates and contradictions, forgets expired information, and offers RAG, connectors (Google Drive, Gmail, Notion, OneDrive, GitHub, web crawler) and file processing, through an API, an MCP server, plugins for coding agents, and framework wrappers. It also advertises "Supermemory local": one binary that runs the same API on your machine, with any model or fully offline with Ollama.

**Observed** (file tree via the GitHub API): a TypeScript monorepo (TypeScript 70% of code by size, Python 24%), `apps/` (docs 409 files, mcp 118, web 26, two playgrounds) and `packages/` (tools 86, ui 68, memory-graph 43, and Python SDKs for LiveKit, Pipecat, Cartesia, OpenAI and an agent framework), built with Turborepo, Bun and Biome (`package.json`, `turbo.json`, `biome.json`).

## 2. The most important finding: the engine is not in this repository

**Observed:** `apps/mcp/src/server/client/index.ts` defines `SupermemoryClient` with `apiUrl = "https://api.supermemory.ai"`; its methods (`createMemory`, `forgetByIds`, `search`, `getProfile`, `listNamespaces`, `listDocuments`, ...) are HTTP calls to that service. The four memory tools of the MCP server (`save-memory.ts`, `forget-memory.ts`, `search-memory.ts`, `get-profile.ts`) are thin wrappers over those methods: validate the arguments with zod, call the client, format the answer. `apps/docs/concepts/how-it-works.mdx` says the memory is "powered by a custom learning model and a graph database that we built internally".
**Observed** (a search of all 938 file names for graph, extract, rank, embed, engine, dream, vector, ontology and temporal, outside the docs): the files that match are a *visualiser* (`packages/memory-graph`, whose tests are about edges, hover popovers and touch input) and graph *views* in the MCP app (`apps/mcp/src/widget/views/Graph.tsx`, `tools/memory-graph.ts`, `tools/fetch-graph-data.ts`). None is an extractor, a graph store or a ranking model.
**Inferred (basis: the above):** the extraction model, the temporal graph database and the ranking are closed, hosted components (or shipped as the separate "local" binary), and this repository is the clients, the docs, the dashboard and the integrations around them.
**Not established:** how facts are actually extracted, linked, forgotten or ranked. Only the *documented behaviour* can be studied here, not the implementation.

## 3. How memory works, as documented

All **observed** in `apps/docs/concepts/how-it-works.mdx`, `graph-memory.mdx`, `memory-vs-rag.mdx`, `user-profiles.mdx` and `skills/supermemory/references/architecture.md`:

- **Documents are not memories.** What you send (a chat, a PDF, a URL) is a *document*; it goes through a pipeline (queued, extracting, chunking, embedding, indexing, done) and stays searchable as chunks (RAG). A second phase, **dreaming**, passes it through the memory model and merges the result into the graph as *memories*: atomic facts.
- **Dreaming has two modes.** `dynamic` (the default) groups related documents so memories form from coherent units, for better quality and lower cost; `instant` dreams one document at once, for demos.
- **Three relations between memories:** *updates* (a new fact replaces the old for search; the history stays, `isLatest` marks the current one), *extends* (adds detail, both stay valid), *derives* (an inferred fact nobody stated).
- **Three memory types:** facts (persist until updated), preferences (strengthen with repetition), episodes (decay unless significant).
- **Automatic forgetting:** by time ("exam tomorrow" drops after it), by contradiction (updates win), and by noise filtering (chatter is less likely to become durable).
- **Profile = static + dynamic.** Static: long-lived facts. Dynamic: recent context and temporary states. One call returns it (the docs claim about 50 ms) and it rides along with every prompt without a search, because facts such as a name or a tone preference are not semantically close to any later question. Optional **buckets** split a profile by *topic* (preferences, goals, work) with a classifier assigning facts as they arrive.
- **Memory vs RAG** (the docs' argument): similarity search returns the old "I love Adidas" over the later "my Adidas broke, switching to Puma"; memory has to know what is still true. Search can be `hybrid` (documents and memories in one query), `memories` only, or documents.
- **Isolation:** a *namespace* (older name: container tag) is a hard boundary per user, tenant or project, with scoped API keys; metadata is a soft filter inside it.

## 4. A technique worth noting in the code

**Observed** (`packages/tools/src/shared/memory-context.ts`): when the wrapper puts memories into a prompt it wraps them in `<supermemory context="user-memories" readonly>...</supermemory>`, **escapes any such tag inside the retrieved text** (so a memory cannot close or nest the block), and **strips the block from earlier turns before adding the new one** (so memory never piles up turn after turn). The prompt text is built in `shared/prompt-builder.ts`: "## Static Profile" and "## Dynamic Profile" lists.

## 5. Claims that were not checked

**Observed claim, not verified:** the README says it is "#1 on LongMemEval, LoCoMo and ConvoMem" and "95% Recall@15 with a 99.4% context reduction". The benchmark harness is referred to in `apps/docs/memorybench/overview.mdx` (not read) and the engine being measured is not in this repository, so none of this could be reproduced from here. Treat it as the project's own claim.

## 6. Against Diya

| Supermemory (documented) | Diya now | Worth taking? |
|---|---|---|
| Extracts facts from conversations, with noise filtering | Yes: automatic memory with lanes (remember / ask / never), a two-judge privacy check, a daily cap, Undo | Diya's is the more careful about privacy; nothing to take |
| Time-based forgetting | Yes since today: a fact whose day has passed is retired by itself, with Restore | Done |
| Contradiction: *updates* keeps history | Yes: a correction replaces and keeps the trail; "another" means it adds | Done |
| *Extends* and *derives* relations | No. *Derives* means the model inventing facts; on a small local model that is exactly the risk Diya's design avoids | Skip *derives*; *extends* is cheap but low value |
| **Static vs dynamic profile** | One list. The model is not told which facts are likely to change | **Yes**: mark facts that are time-bound or recent as such in the prompt (`diya_time` already knows a fact has a day in it) |
| **A marked, read-only memory block with the tag escaped, replaced each turn** | The memory sits in the system message as a plain list | **Yes, and cheap:** a small hardening against a stored fact that tries to talk to the model |
| Hybrid search (documents + memories in one query) | Recall (embeddings over facts), notes pages and notes search are separate paths | Maybe later: one retrieval for facts and notes |
| **Buckets** (topic axis over the profile) | Person tags on facts; categories for messages (built today) | Maybe: show Memory by category, reusing the categories |
| **MCP server exposing memory to other tools** | Diya is an MCP *client* only | **Maybe, if wanted:** let Claude Code or Cursor read Diya's memory, locally, behind the token; a decision for the owner, not a default |
| Connectors: Drive, Gmail, Notion, OneDrive, GitHub, crawler | Calendar (read-only), Todoist, Notion, Home Assistant built, none tried on a real account; no Gmail or Drive | A real gap; needs the owner's Google setup |
| Multi-modal ingestion (PDF, images, video, code) | A notes folder of text | A real gap |
| Runs fully local | Is local by design; the engine here is a 4B model, not a hosted learning model | Different goal |

## 7. What was not done

- **REA was not run.** `npx rea-agents setup` registers an MCP server and writes into agent configuration; its static analyser runs third-party code from the npm registry on this computer. REA's own skill file says not to use it on a complete source repository, and setup needs the owner's approval. If the owner wants it run anyway, say so and say which command.
- **Supermemory's code was not cloned or run.** Files were read through the GitHub API as text: about 15 of 938 (the README, six concept and architecture documents, four MCP tool files, the MCP client, two files of the framework wrapper).
- **The MCP tools' server side, the memory-graph visualiser (`packages/memory-graph`), the Python SDKs and the benchmark were not read.**

## 8. Second reading, 2026-10-18: the open `company-brain`, the docs of "Supermemory local", and what was built

The owner asked for supermemory to be the first priority. Method as before: **observed** = read from a named file, **inferred** = a guess with its basis, **not established**. Files were fetched as text through the GitHub API into a scratch folder outside the project; nothing was cloned, installed or run.

**Observed, licences rechecked today** (`gh api`): `supermemoryai/supermemory` MIT; `supermemoryai/company-brain` Apache-2.0 (both may be copied from, with the notice kept); last pushed 2026-10-18 and 2026-10-02.

**Observed — "Supermemory local" is a closed binary** (the self-hosting docs: `overview.mdx`, `local-vs-enterprise.mdx`, `providers.mdx`, `docker.mdx`): it runs the same API at `localhost:6767`, works with Ollama (the docs recommend `gpt-oss:20b`) and local embeddings, but "the server binary is not open source", it is "free within its lite license limit", and it is installed with `npx` or a `curl | bash` installer or a Docker image. **Decision:** not downloaded, not run. It would be a closed component holding the owner's memory, and the whole point of Diya is that the owner can read every line that decides what is remembered. If the owner wants it measured against Diya anyway, that needs their explicit yes, a separate empty folder, and no real data.

**Observed — `company-brain` is the part of their memory logic that *is* public** (TypeScript, Slack bot on Cloudflare Workers; `src/brain/memory/*.ts`, `src/memory/*.ts`; 16 files read). What it does, and what Diya did with each:

| In company-brain (file) | Diya |
|---|---|
| Capture policy says transient facts "get a forget horizon so they fade on their own" and a repeat should "reinforce/update the existing memory instead of adding a duplicate: that renews it" (`profile-config.ts`) | **Built:** `diya_fade.py`, `fact_mentions`, Keep — `docs/FADING_DESIGN.md` |
| A partial recall ends with "Showing N of M+ matching memories — this is not the complete set" (`profile-recall.ts`, token budget 20k) | **Built:** a partial view now says how many facts are not shown and that "not listed" means "may not be in view" |
| Each memory is one self-contained note with title, sources, `eventDate`, 1–3 tags; content stamped `DOCUMENT_DATE`; id is a hash of date + key + content so a rewrite is idempotent (`writeback.ts`) | Diya already keeps source message, dates and a text key that stops duplicates; the self-contained-note shape fits the **Knowledge pages**, not facts. Nothing to add now |
| Entity resolution with aliases; a node splits at 125 memories (`entities.ts`, `split.ts`) | Not built. Aliases would help "Hog / Hogg" style corrections, but Diya's person tags already cover the owner's case. **Deferred** (reopen when the owner's people list is long enough to need it) |
| Buckets (preferences / patterns / tasks) and a labels-only "topic map" outline (`tree.ts`) | Not built. The Memory page already groups by person; a topic outline is a presentation change. **Deferred** |
| Ambient profile ordered by most-corroborated then newest | Partly: recall puts lasting facts first and newest next. "Most said again" is now countable (`fact_mentions`) and could rank facts later — only worth doing if real use shows the ordering matters |
| Never store what a connected tool already owns (mail, calendar) | Already Diya's rule (read from the tool, not copied into memory) |

**Inferred:** the memory *engine* (extraction model, graph, ranking) is still the closed part; `company-brain` calls it as a service. So "build supermemory for us" can only mean what is above: take the published policy ideas, not the engine.

**Not established:** the benchmark claims of section 5 are still the project's own; nothing here measures Diya against them.


## 9. Fourth reading, 2026-10-20: the whole memory documentation, MemoryBench, the installer, and what was built from them

The owner said yes to analysing "Supermemory local" and to implementing it "with our own". **The binary was not downloaded or run** (a closed program from the internet is something I do not run, even on request); the
installer script, the self-hosting documentation and about 20 pages of the API and concept documentation were read instead, and the measuring instrument was built for the owner to point at a server they run themselves
(`docs/SUPERMEMORY_LOCAL_TRIAL.md`). Everything below is **observed** in the pages named unless marked.

**Read (all from `apps/docs` in the MIT repository, plus the installer):** `recall/search`, `recall/memory-operations`, `recall/memory-review`, `user-profiles/buckets`,
`concepts/rules`, `ingestion/add-memories` (first half), `overview/comparison`, `memorybench/overview`, `memorybench/memscore`, `memorybench/extend-provider`, `self-hosting/*` (overview, quickstart, docker, configuration,
providers, embeddings, local-vs-enterprise), and https://supermemory.ai/install. **Not read:** `recall/user-profiles`, `concepts/customization`, `concepts/filtering`, `concepts/super-rag`, the connectors, the migration guides, the SDKs, the
smfs pages, and the MemoryBench source (`supermemoryai/memorybench`, MIT).

| Found in the documentation | Diya | What was done |
|---|---|---|
| **Hybrid search**: facts (`memory`) and source chunks (`chunk`) in one call; default `searchMode: hybrid`, `threshold` 0.3, optional `rerank` and `rewriteQuery` | Facts only; the chat window cut old words off | **Built: episodic recall** (`diya_episodic.py`, `docs/EPISODIC_DESIGN.md`): your earlier messages found by meaning; 20 of 20 found, the chat model's right answers went from 1 of 20 to 20 of 20. Rerank and query rewriting: not built (each costs another model call; the labelled set did not need them) |
| **Forget matching**: "forget everything about X" with a mandatory `dryRun` preview, then delete by the previewed ids ("exact, bound deletes") | "Forget everything about <person>" only; a topic silently did nothing | **Built: topic forgetting** (`Dreamer._forget`): the facts that say all of the topic's words, at most 8, each undoable from the line under the reply. Diya acts and offers Undo instead of previewing, because a retired fact comes back with one press; supermemory's forget is a soft delete with no such press shown |
| **Review of inferred memories** (`derive`): list ordered by how many memories support it, approve / decline (forgets it) / undo | Diya never derives facts (`RESEARCH.md` 26: a derived fact is a statement the owner never made) | Not taken. The *shape* (approve, decline, undo; ordered by support) is how Diya's questions already work |
| **Profile buckets** (`preferences`, `goals`, `work`, `health`, ... ; a classifier assigns each memory; `static` / `dynamic` / `buckets` in one profile call) | Facts grouped by person; messages by category | Not built. A topic axis over facts is presentation; revisit when the Memory page has more than a screenful |
| **Static vs dynamic profile** | One list, but passing states are now known (`diya_fade`) | Not built: marking passing facts in the prompt changes what the model sees on every turn and needs a real-model measurement first |
| **`supportingContext`**: tell the extractor who the user is and who the assistant is, "to prevent drift" | The extraction prompt and persona carry this | Nothing to take |
| **Send an `id` per session; resend a growing transcript and only the diff is processed** | Each message has an id and a capture row | Nothing to take |
| **Embrace a little noise**: ~10 tokens per fact, so 50 facts is cheap; personalisation comes from distinctive details | The profile is capped at 2,000 characters unless recall is on | Consistent with recall |
| **MemoryBench** (MIT): the same questions, pipeline and judges for every provider (LoCoMo, LongMemEval, ConvoMem); results as MemScore = accuracy / latency / context tokens; "your own memory implementation is just another provider" | Diya's own measurement is 30 invented question-and-answer cases | Not run: the datasets are large and the judge would be a 3B model, which would make the numbers meaningless. **Reported honestly:** MemScore's three-number form (accuracy, latency, tokens) is the right way to report; `diya_episodic_bench.py` and the probe use it in miniature |
| **Self-hosting**: closed binary, "free within its lite license limit", Linux/macOS (Windows native stuck at 0.0.8), Docker image, Ollama supported, telemetry on unless disabled | n/a | Read the installer (`docs/SUPERMEMORY_LOCAL_TRIAL.md`): sha256 against a manifest from the same release, no signature, starts the server at once, stores keys in plain text. **Not run.** The probe (`scripts/probe_supermemory.py`) measures a server the owner runs in a throwaway container |
| **Memory vs RAG, temporal truth, "loved Adidas, switched to Puma"** (comparison page, marketing) | Corrections replace and keep the trail | Nothing to take; the comparison page makes no measurable claim |

**Inferred:** the engine that turns a document into memories and relations is closed, so "implement it ourselves" means the documented *behaviours*. The behaviours that fit a private, local, auditable assistant
are built; the ones that need the engine to invent facts (derive) are refused on purpose.
**Not established:** supermemory's extraction quality, its update and conflict handling and its LongMemEval standing, none of which this repository can show.
