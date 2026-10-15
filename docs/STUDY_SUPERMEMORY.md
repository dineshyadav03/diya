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
