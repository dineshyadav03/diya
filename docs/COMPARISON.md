# Diya next to the projects like it: what each one does, and whether Diya has it

> **Status (2026-10-13):** written after the owner asked, of the 51 similar repositories in `RESEARCH.md` entry 33, "all those repos create a file and list them all and also mention what do they do and
> do we have those features or not". **How it was made:** I read each project's README on GitHub that day (and, for OpenClaw, Khoj, Hindsight and the memory libraries, the READMEs only: not their code or their
> docs sites), listed the features each one claims, and marked whether Diya has it from Diya's own code. A feature is listed only if the README says it; **"not stated" never means "absent"**, and a claim
> is the project's own, not tested here. Licences are from the GitHub API and the LICENSE files. No project's restrictions on AI tools or agents were found (see the end).

Legend for the Diya column: **yes** = built and tested; **part** = some of it, or built but never tried against the real thing; **no** = not built; **no, on purpose** = a decision (the reason is given).

## What nearly everyone has now, and where Diya stands

| Feature | Who lists it | Diya |
|---|---|---|
| Runs with local models (Ollama or similar) | nearly all of them | yes |
| Memory of facts about you across chats | Open WebUI, AnythingLLM, Hermes, Leon, every memory library | yes, **reviewed by you before the model is told** |
| Scheduled prompts / automations | Open WebUI, AnythingLLM, Hermes, Khoj, OpenClaw | yes (automations; repeating reminders) |
| Voice in with a local speech model | Open WebUI (local Whisper), Hermes (voice memos), OpenClaw (voice in its apps) | yes (tap to talk, Whisper) |
| Lives in your chat apps (WhatsApp, Telegram, Slack...) | OpenClaw, Hermes, Khoj | part (a Telegram bot, built, never tried) |
| Phone or desktop apps | OpenClaw, AnythingLLM, Jan, Open WebUI (PWA) | no (a web page that works in a phone browser over a VPN) |
| Plugins, skills or MCP servers | OpenClaw, Hermes, Open WebUI, Jan, Leon, AnythingLLM | no, on purpose for plugins and skills (the biggest security record of the category is here, `RESEARCH.md` entry 17); MCP is a plan (M1) |
| Chat with your documents (PDF, Word, notes) | AnythingLLM, Khoj, Open WebUI | part (one notes folder, one note back); the plan is K1 |
| Knowledge graph or entity memory | cognee, graphiti, MemOS, Hindsight, mem0 | part (people-tagged facts only) |
| Several users with roles | Open WebUI, AnythingLLM | no, on purpose (one person) |
| A terminal, files and computer use for the agent | OpenClaw, Hermes, Leon, Open WebUI, Sentient OS | no, on purpose |
| An agent that writes and improves its own skills | Hermes | no (the plan is H1, propose-only) |
| Published memory benchmarks | mem0, Hindsight, supermemory, MemOS | no (Diya has its own measurements, not these benchmarks) |

## What Diya does that none of the READMEs read says it does

- **A memory the person reviews before the model sees it.** Every project above that has memory says it learns or extracts on its own. Diya's default is review; its automatic mode keeps lanes decided by code,
  a question for what is doubtful, private or a possible replacement, a cap, a circuit breaker and Undo.
- **A question when a remembered day has passed** ("You told me ... Is that still true?") and when a fact may replace an old one. Mem0 and supermemory handle contradictions *automatically*; Diya asks.
- **Actions that wait for one-by-one approval** (a Todoist task, only when you name Todoist), with an append-only record of every step. (Open WebUI lists "approval flows" as something a plugin could build.)
- **A reminder remembers when you ticked it off**, so "when did I buy the guitar strings?" has an answer; an unattended automation can only read.
- **Measured with the real model on a CPU laptop**: the gates in code were chosen because a benchmark showed the small model was worse at them (`docs/GATE_BENCHMARK.md`).

All five are choices about trust, not size. None of them is a reason to prefer Diya if you want the most features today.

## Project by project

### OpenClaw (MIT, 391,842 stars, pushed 2026-10-13): an assistant that meets you in your chats

| What the README says | Diya |
|---|---|
| Lives in WhatsApp, Telegram, Slack, Discord, iMessage and 20+ more through one gateway | part (Telegram only, never tried) |
| Native apps for macOS, iOS, Android, Windows, Linux; companion nodes for voice, camera, screen | no |
| A control UI, a CLI and a TUI | part (a web UI and a terminal chat) |
| Hosted and local models as swappable plugins | part (Ollama; the model is a setting) |
| Tools, skills and plugins, with a registry (ClawHub) | no, on purpose |
| Pairing for unknown senders; tools run on the host unless sandboxed | yes for the idea (a paired owner only, no host tools) |
| State, memory and credentials on your hardware | yes |

### Hermes Agent (MIT, 253,307 stars): "the self-improving agent", native on Windows

| What the README says | Diya |
|---|---|
| A terminal UI with history and interrupt-and-redirect | part (a terminal chat) |
| One gateway to Telegram, Discord, Slack, WhatsApp, Signal; voice-memo transcription | part (Telegram bot; browser voice) |
| Agent-curated memory with periodic nudges | no, on purpose (memory is reviewed) |
| Skills it writes and improves itself | no (H1 would only propose) |
| Full-text search of past sessions, with summaries | yes (search inside every chat; no summaries) |
| A built-in cron scheduler that delivers to any platform | yes for the scheduler (automations); delivery to the chat and the desktop |
| Subagents; scripts that call tools; seven terminal backends | no, on purpose |
| Batch trajectories for training models | no |

### Khoj (AGPL-3.0, 37,669 stars, last push 2026-08-02): a "second brain"

| What the README says | Diya |
|---|---|
| Chat with local or online models | yes (local) |
| Answers from the internet and from your documents (PDF, Markdown, org-mode, Word, Notion, images) | part (web yes; documents: a notes folder) |
| Browser, Obsidian, Emacs, desktop, phone and WhatsApp | part (browser, a phone browser) |
| Custom agents with their own knowledge, persona and tools | no |
| Automations: newsletters and notifications delivered to your inbox | part (automations write into the chat and the desktop, no email) |
| Semantic search of your documents | part (embeddings over a notes folder) |
| Image generation; speaking out loud | no; part (browser voice) |
| Self-hostable, "always"; a hosted cloud (shut down in April, entry 16) | yes (self-hosted only) |

### Leon (MIT, 17,575 stars): an open-source assistant since 2019, now a "2.0 developer preview"

| What the README says | Diya |
|---|---|
| Three modes: smart, controlled (deterministic skills), agent (plans) | part (code decides what to do for the sensitive cases; the model does the rest) |
| Native skills and SKILL.md agent skills | no, on purpose |
| Real tools instead of free-form guessing | yes |
| Computer use on the desktop and browser | no, on purpose |
| Layered memory: durable preferences, day-to-day context, recent discussion | part (one list of accepted facts; a plan to split it) |
| A bounded "proactive pulse" | yes (Diya writes first: morning, evening, reminders) |
| Local and remote model providers | part (local) |
| Windows, Linux, macOS | part (Windows only tested) |

### Open WebUI (a BSD-3-style licence with a no-rebranding clause, 155,505 stars): "a home for AI"

| What the README says | Diya |
|---|---|
| Ollama and any OpenAI-compatible API, mixed freely | part (Ollama) |
| Roles, groups and permissions | no, on purpose |
| Plugins (filters, actions, pipes, tools, skills), MCP and OpenAPI tool servers | no; MCP is a plan |
| Custom models and agents with instructions, tools and knowledge | no |
| An agent with a terminal and filesystem | no, on purpose |
| Notes workspace; shared channels | no |
| **Persistent memory** across conversations | yes (reviewed) |
| A built-in calendar with reminders; models manage it by function calling | part (Reminders, Today, Scheduled pages; Google Calendar read-only, never tried) |
| **Automations**: scheduled prompts whose runs show on the calendar | yes (automations; no calendar view) |
| A PWA; hands-free voice and video calls, local Whisper | part (a web page; tap to talk) |

### AnythingLLM (MIT, 67,014 stars): "the all-in-one AI app"

| What the README says | Diya |
|---|---|
| Chat with your documents, with citations | part (one note back; no citations) |
| Agents that browse the web; a no-code agent builder | part (web lookup; no builder) |
| Dynamic routing of each chat to the best model | no, on purpose (one model on a CPU laptop) |
| Automatic and user-managed memories | yes (automatic and reviewed) |
| **Scheduled tasks** on a cron schedule with agent abilities | yes (automations; read-only) |
| Multi-user with permissions (Docker); embeddable widget; desktop apps; Android | no |

### Jan (Apache-2.0, 44,930 stars): "an open-source ChatGPT replacement"

| What the README says | Diya |
|---|---|
| Downloads and runs models from Hugging Face | no (Ollama does it) |
| Connects to hosted models | no (local only) |
| Custom assistants | no |
| An OpenAI-compatible local server | no |
| MCP for agentic abilities | no (a plan) |

### Memory libraries

| Project (licence, stars) | What the README says | Diya |
|---|---|---|
| **mem0** (Apache-2.0, 67,103) | multi-level memory (user, session, agent); one-pass add-only extraction; entity linking; semantic + keyword + entity retrieval fused; time-aware retrieval; SDKs; benchmark scores on LoCoMo and LongMemEval (its own, on its managed platform) | part: facts per person and user; no retrieval beyond "tell the model everything"; the plan is R1 |
| **Hindsight** (MIT, 49,029) | retain, recall, reflect; observations; mental models and knowledge pages; memory banks; 25+ providers including Ollama; embedded Postgres; claims state of the art on LongMemEval | part: retain and recall in spirit; no reflect, no knowledge pages (K1) |
| **supermemory** (MIT, 31,206) | extracts facts; handles changes, contradictions and forgetting; a profile of stable facts plus recent activity; hybrid search; connectors (Drive, Gmail, Notion, OneDrive, GitHub); PDFs, images, video, code; plugins and MCP for coding assistants; a one-binary local mode that works offline with Ollama | part: facts, changes (asked, not automatic), stale questions; no profile split, no connectors for files and mail |
| **cognee** (Apache-2.0, 32,142) | a self-hosted knowledge graph from documents, code and conversations; runs locally with small CPU models; ontologies | no |
| **graphiti** (Apache-2.0, 31,697) | temporal context graphs that track how facts change, with provenance to the source | part: a fact keeps the messages it came from and an event trail; no graph |
| **MemOS** (Apache-2.0, 11,845) | a memory operating system: a unified API, multi-modal memory, "memory cubes" per user or project, asynchronous ingestion, **correction by natural-language feedback** | part: corrections in words ("no, I live in Pune") yes; the rest no |
| **letta** (Apache-2.0, 25,123) | stateful agents with advanced memory that learn and self-improve (README is short) | no |
| **basic-memory** (**AGPL-3.0**, 4,162) | memory as plain Markdown notes your AI reads and writes; a paid cloud | no (K1 is the same idea, written from the design) |

### Sentient OS (**AGPL-3.0**, 568 stars): a Mac app that reads your life overnight

See `RESEARCH.md` entry 29. A nightly on-device pass writes a Markdown knowledge base from files, messages and mail; Double Tap drafts replies; Sidekick uses the computer for you. **Diya:** no knowledge base
yet (K1), no drafts, no computer use (on purpose), nothing leaves the computer.

## Anything restricting AI tools or agents?

The owner asked to be told if any project says other AI agents may not use it. **None of the 19 checked does.** I read each one's LICENSE (and LICENSING, NOTICE, CONTRIBUTING, AGENTS.md, CLAUDE.md, AI_POLICY
where present) and README for rules against AI tools, agents or scraping:
- Licences: MIT, Apache-2.0 and Jan's Apache-2.0 with an attribution request; **AGPL-3.0** for Khoj, Sentient OS and basic-memory; **Open WebUI**'s own licence (BSD-3 plus a clause that forbids altering or
  removing its branding unless there are 50 users or fewer in 30 days, or with permission).
- OpenClaw's CONTRIBUTING *welcomes* AI-assisted pull requests; Letta's AI_POLICY asks contributors to name any AI tool they used and bans AI-generated media in *contributions to Letta*; neither limits using the code.
- The AGENTS.md and CLAUDE.md files in these repositories are instructions for an agent working *on that repository*, not conditions of using it. I read them as information and do not take orders from them.
- Limits of the check: a keyword scan of those files and READMEs, not of every file, a hosted service's terms (Khoj Cloud, Hindsight Cloud, supermemory's API, mem0's platform), or a licence that changes later.
  Anything of this kind found while reading code for a unit will be reported before it is used.
