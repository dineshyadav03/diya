# Diya: the complete guide

What Diya is, what it can do, where it falls short, how it is built, how to build one, how this one got built, the research behind it, and the products like it.
Written 2026-10-14 from the code, the tests, the measurements and the research notes as they are today. Where something is a guess it says so; where something was never tried against the real thing it says that too.

## Contents

1. [The two-minute version](#1-the-two-minute-version)
2. [What Diya is, and the idea behind it](#2-what-diya-is-and-the-idea-behind-it)
3. [What Diya can do today](#3-what-diya-can-do-today)
4. [Where Diya falls short](#4-where-diya-falls-short)
5. [How Diya is built](#5-how-diya-is-built)
6. [How to build something like it](#6-how-to-build-something-like-it)
7. [How this one got built](#7-how-this-one-got-built)
8. [The research behind it](#8-the-research-behind-it)
9. [Products like Diya, and how it differs](#9-products-like-diya-and-how-it-differs)
10. [Verdict, and what to do next](#10-verdict-and-what-to-do-next)
11. [Appendices](#11-appendices): glossary, commands, file map, settings, what waits for the owner

---

## 1. The two-minute version

**What it is.** Diya is a personal AI assistant for one person. The model, the memory and the speech run on that person's own computer (a small open model through Ollama). You talk to it in a web page by
typing or by voice. It remembers facts about you, keeps your reminders and tasks, does things on a schedule, writes to you first, answers general questions by looking them up, and can read your notes.

**The idea.** Most assistants are built to do as much as possible. Diya is built to be *trustworthy first*: what it learns about you is reviewed before the model is told it, anything it does outside the
computer waits for your approval, text it reads (a web page, a note, a tool's reply) is treated as information and never as an order, and every claim is measured with the real small model on an ordinary laptop.

**How big.** About 19,000 lines of Python, 5,800 lines of interface code, 39,000 lines of tests (about 6,860 tests in 95 test files), 35 design documents and a 34-entry research file; 174 commits in 25 days (2026-09-20 to
2026-10-14). Almost all of the code was written by an AI (Claude) under the owner's direction; the owner decides, runs and reviews.

**Where it stands.** Everything the roadmap planned is built and tested. But it has been built and tested far more than it has been *lived with*: most messages it has received were typed while building it, answers take
10 to 30 seconds on this laptop's CPU, a model this small is clearly weaker than the free cloud assistants, and nothing real (a notes folder, a calendar, a phone) is connected yet. Several parts (Google Calendar, Todoist,
Telegram, push notifications, any third-party MCP server) were never tried against the real thing.

**Is it special?** Its *features* are not: the category is crowded (51 similar projects were surveyed), and several are bigger, better funded and better tested. What is distinctive is a set of choices about trust,
and the honest, measured way it was built. That is real, but narrow: it matters most to someone who already distrusts cloud assistants, and as a worked example it is valuable to someone learning AI engineering.

**What to do next.** Stop adding features for a couple of weeks and use it: point it at a real notes folder, use plain-word reminders, keep one automation, review the memory. Then decide whether the goal is a tool you
live with (then speed and friction come first) or a showcase and learning project (then write up the findings and keep the scope small). Section 10 has the details.

---

## 2. What Diya is, and the idea behind it

### 2.1 In one sentence

A private, inspectable assistant for one person, built so that you can see why it knows what it knows and why it did what it did.

### 2.2 The problem it answers

An assistant that remembers you and acts for you has to be trusted with two things: **what it believes about you** and **what it does in your name**. The usual designs get both wrong in the same way: they
learn silently, act on whatever they read, and give you no way to see the trail. A wrong "fact" in memory quietly becomes true; a web page can tell the assistant what to do; a mistake leaves no record.

Diya's answer is to treat these as the main problem, not an add-on, and to keep the small, local model on a short leash, because the research and Diya's own measurements agree that a model this size is bad at
the judgement calls that matter (section 8).

### 2.3 The four promises (from `PRODUCT_VISION.md`)

1. **Inference stays on the device.** The model, the embeddings and speech-to-text run on the owner's machine. Only two things go online, and only when used: web searches (the words searched, to DuckDuckGo)
   and the weather (the place, to Open-Meteo), plus any connector you connect yourself.
2. **Memory that is earned, not assumed.** What Diya learns from conversations is staged and reviewed (by you, or by code rules for plain, safe facts, with Undo). A wrong fact must not silently become true.
3. **Proactive, not only reactive.** Scheduled jobs act without being asked: reminders that fire, a good morning with your day, an evening check-in, automations you set up in one sentence.
4. **Extensible, but on a leash.** New abilities are added as functions with a schema and tests; there is no skills marketplace, no shell, no generic web fetcher, and MCP servers are ones you add and approve one tool at a time.

### 2.4 The seven design rules that came out of building it

| Rule | What it means in practice | Where it came from |
|---|---|---|
| **Code decides what must be true; the model writes the words.** | Whether a message asks for a reminder, shares a fact, or is a greeting is decided by plain code. The model wrote the reply, and code tidies it. | Measured: asked the same yes/no question, the 3B model said "no" to all 12 real fact-shares that the code got right (`docs/GATE_BENCHMARK.md`). Prompts did not hold it either: 11 of 12 greetings invented a name until code fixed them. |
| **Review before trust.** | A fact is a *candidate* until accepted; automatic acceptance only for plain facts, in "lanes" decided by code, with a cap, a circuit breaker and Undo. | Memory-poisoning research (entry 17) and Diya's own junk facts. |
| **Nothing outside the computer without approval.** | A write (today: a Todoist task, only when you name Todoist) is a *proposal* shown with its exact arguments; the append-only record shows who did what. | Rule of Two / lethal trifecta (entry 17). |
| **Read it, never obey it.** | Web results, notes and tool replies are given to the model behind a warning and, for the riskiest paths (notes pages, lookups), with no tools offered. | Prompt-injection record of the agent wave (entries 16-17). |
| **Unattended means read-only.** | An automation can read the web, weather, your notes, reminders and tasks; it cannot save, send or act. | Same. |
| **Measure with the real model, on the real machine.** | Every design was checked against the actual small model on a CPU laptop, and several designs changed because of it. | Throughout; `docs/*_BENCHMARK.md`. |
| **Say what was not tried.** | Each doc has a "not measured" or "limits" part; the README lists what was never run against a real service. | A working agreement with the owner. |

### 2.5 Who it is for, and not for

- **For:** one person who wants an assistant whose memory and actions they can inspect, on their own computer, and is willing to run a small model. Also a person learning how agents are built, since every
  decision has a document and a test.
- **Not for:** anyone who wants the best answers today (a cloud assistant is better), a finished app with phone clients, or a team product (it is one user by design).

---

## 3. What Diya can do today

Status words used below: **tested** = built and covered by automated tests (and usually measured with the real model); **never tried for real** = built, but never run against the real account, device or
program it talks to; **off by default** = built, and waiting for you to switch it on. "Tested" mostly means tested on *invented* data, because the owner has not yet fed it much real life.

### 3.1 Talking

| Ability | How you use it | Status |
|---|---|---|
| Chat in a web page, replies appear as they are written | open `https://localhost:3000` | tested |
| Voice in: tap the mic, speak, tap again | local Whisper speech-to-text; silence is never sent | tested (the owner's microphone check was still pending) |
| Spoken replies | the browser's own voice | tested; some browsers' voices are online services |
| General questions | a question that needs today's facts, or that the model gave up on, is searched on the web and answered from the results | tested; measured with the real model |
| Greetings | a short reply, with a name, part of the day and pictures made right in code | tested; measured |
| Search past chats, rename them | History page | tested |
| A first reply after a pause that is not 30 seconds | the model is kept loaded; greetings skip the tools | measured |

### 3.2 Memory

| Ability | How it works | Status |
|---|---|---|
| Facts about you, reviewed | Dreaming reads your chats and stages candidate facts; you accept or reject them on the Memory page (or `python diya_review.py`) | tested |
| Automatic memory with Undo | plain facts go in on their own, marked; private, doubtful or replacing facts become a question in the chat; a cap per day and a circuit breaker | tested; switched **on** here since 2026-10-13 |
| Corrections and forgetting | "no, I live in Pune" replaces; "forget that" forgets; the reply says what memory did, with Undo | tested |
| Time-aware facts | a fact whose day has passed ("next Tuesday") becomes a question | tested |
| Who a fact is about | facts are grouped by person ("Maya works as an architect") | tested |
| Relevance recall | when the facts outgrow the 2,000 characters told in one message, the model is told the lasting facts plus those closest to what you just said (up to 20,000 characters may be kept) | tested; measured on invented facts (12 of 12 against 3 of 12 for newest-only) |
| Questions Diya asks | cards at the top of the chat; one press answers | tested |

### 3.3 Your day

| Ability | How you use it | Status |
|---|---|---|
| Reminders in your own words | "remind me to call mum tomorrow at 5pm"; the time is read by code, and a time the model changed is refused | tested |
| Repeating reminders | every day / weekday / Monday / month on the 15th / 2 weeks; snooze; skip; stop | tested |
| A to-do list inside Diya | "add a task to ..." | tested |
| Pages | Today, Reminders, Scheduled, Tasks, Automations | tested |
| Diya writes first | a good morning with your day, an evening check-in, a message when a reminder is due | tested; needs the notifier scheduled (off by default) |
| Automations | "every morning at 8am tell me the weather in Pune": made by code, run on schedule, read-only, the answer lands in your chat | tested; off until the notifier is scheduled |
| "When did I buy the guitar strings?" | ticking a reminder off keeps when, so this has an answer | tested |

### 3.4 Your notes

| Ability | How you use it | Status |
|---|---|---|
| Search one note | the `search_notes` tool returns the nearest note | tested |
| Knowledge pages | `python diya_knowledge.py build` or the Knowledge page: one page for each name that recurs in your notes, made only of your own sentences, with the note each came from; no model writes it | tested on invented notes only |
| Ask about a name | "what do my notes say about Maya?" is answered from the page, with no tools offered | tested; measured with the real model on invented notes |

You must point `DIYA_NOTES_DIR` at a folder of your own; Diya does not look anywhere you have not pointed it.

### 3.5 Outside the computer

| Ability | Notes | Status |
|---|---|---|
| Google Calendar (read) | set up from the Connections page with your own Google app | **never tried for real** |
| Todoist (read, and one write) | a task is only proposed when your message names Todoist, and waits for Approve | **never tried for real** |
| Google writes (calendar event, Google Task, Drive folder, Google Doc) | each its own Connections card and its own narrow scope; proposed only when you ask for exactly that, shown with the time read from your words, run once after you press Approve (`docs/GOOGLE_WRITE_DESIGN.md`) | tested against a stand-in Google; **never tried for real** |
| Notion, Home Assistant (read) | a pasted token | **never tried for real** |
| Approvals | the Actions page shows exactly what would happen; an append-only trail records every step | tested |
| MCP servers | you add a server (`python diya_mcp.py add`), look at it (`check`), and approve its read-only tools one at a time; the model sees the description you approved, a changed tool is not called, results are read and never obeyed | tested against a real server built with the official SDK; no third-party server tried |
| Web Push to a phone, a Telegram bot | built, off by default, and answer only a paired owner | **never tried for real** |

### 3.6 Trust and safety

- An access token is required by default; the web page can have a passcode login; Host and Origin checks, a CORS limit, a body-size limit, TLS (mkcert) on `localhost` only.
- No shell tool, no skills marketplace, no generic page fetcher; weather only reaches fixed hosts; file listing only inside an allowed folder.
- Personal data is git-ignored, can be moved out of a cloud-synced folder with one command, and usage reporting is switched off in the libraries that would otherwise send some.
- A pre-push audit looks for personal names, secrets and hard-coded addresses before anything goes to GitHub.

### 3.7 Tools for the owner

- **The harness advisor** (`python diya_advisor.py`): finds what a gate gets wrong, proposes a patch, tests it, and never applies it.
- **Benchmarks and evals:** `diya_evals.py` (nine prompts against the real model), `diya_actions_bench.py`, `diya_gate_bench.py`, `diya_schedule_bench.py`, `diya_autonomy_bench.py`.
- **One command to start everything:** `python diya_run.py` (checks Ollama, the models, the certificate and Node, starts the API and the UI).

---

## 4. Where Diya falls short

An honest list, roughly in order of how much it matters.

### 4.1 It has barely been used

Diya has been built and tested much more than it has been lived with. The database shows a short burst of real messages in the first week and very few since; no tasks, no active automations and no approved actions;
seven reminders, none ticked off; memory still holding only the facts imported from the old profile file. The tests and benchmarks pass, but they pass on invented data, so **how it behaves in a real week is unknown.**

### 4.2 The model and the speed

| Problem | Evidence |
|---|---|
| A 3 to 4 billion parameter model is weak | It invented a name in 11 of 12 greetings; it writes muddled answers from a note it does not have a page for; it reaches for a task tool nobody asked for (on 13% of messages with the 3B model, 2% with `qwen3:4b-instruct`); it changes times people give ("morning" became "8am"). |
| It is slow on a CPU | A short answer is a few seconds; a question that needs a tool is two model turns; a page of notes took 10 to 30 seconds; the 8B model that passed more tests was about 6 times slower (551 s against 91 s for the nine evals). |
| Code has to hold it up | Many of the guards (the reminder guard, the fact-share gate, the greeting tidy-up) exist only because the model cannot be trusted with the decision. They make it safer, not smarter. |

### 4.3 Never tried against the real thing

Google Calendar sign-in, Todoist, Notion, Home Assistant, Web Push to a phone, the Telegram bot, the microphone, any third-party MCP server, the one-command launcher's install step. All built, none verified
against a real account or device. Treat them as "probably works" until the owner has run them once.

### 4.4 Not built

| Not built | Why |
|---|---|
| Phone and desktop apps | A web page that works in a phone browser over a VPN is what exists. Native apps are a large separate project. |
| Calls, a streaming voice pipeline | Each needs its own design and the owner's yes (call handling was the Equal AI idea, entry 5). |
| Diya writing her own tools | A big safety question; the only step taken is the propose-only advisor. |
| MCP tools that change things; MCP servers over the network | They need the approval buttons and a design for sign-in. |
| A second source for the knowledge base (Calendar, mail) | Mail is the most sensitive input there is; one source at a time, and only if wanted. |
| Always-on hardware | The Mac mini is deferred indefinitely; Diya runs on the owner's Windows laptop. |
| A tool-call journal | On hold at the owner's request. Today only what you said and what Diya answered is stored, so "what did Diya look at for me overnight?" has no answer. |

### 4.5 Structural risks

- **Written by an AI, owned by one person.** About 68 modules and 95 test files that the owner can read but not yet write independently. If they are overwhelmed by the process (they have said they are), maintenance is a risk.
- **More documents than usage.** 35 design docs and a long research file are far ahead of the evidence of use.
- **Tested on invented data.** The newest parts (knowledge pages, MCP, the advisor, recall) were measured on data I made up. That shows the mechanism works, not that it is useful.
- **One machine, one operating system.** Only run on Windows, on one 16 GB laptop with no GPU. Other systems are untested.
- **Easy to overclaim.** An earlier README said "built, and used every day"; that was not true and has been corrected. The same temptation exists in every status line.
- **A narrow difference.** See section 9: most of what Diya does, others do too.

### 4.6 Compared with what it was modelled on (Truffle)

Truffle is a commercial local assistant sold as a device. Little about it is confirmed (entry 25: who is behind it, what it ships); Diya was built to the *features* in the research dossier, not the hardware.

| Truffle-style capability | Diya |
|---|---|
| Runs a model locally with on-device memory | yes |
| Nightly "Dreaming" memory consolidation | yes, with review, lanes and Undo (and no unreviewed merging) |
| Auditable memory and actions | yes (this is the difference Diya chose to lean on) |
| Dedicated always-on hardware | no (a Windows laptop) |
| Phone and desktop apps, messaging apps | no (a web page; a Telegram bridge never tried) |
| Deep integrations that work out of the box | no (four connectors, none tried for real) |
| A polished first-run experience | no (two servers, a token, a certificate) |

---

## 5. How Diya is built

### 5.1 The pieces

```
browser
  -> Next.js UI (https://localhost:3000): pages and same-origin /api/* routes that forward to the API and add the token
       -> FastAPI app diya_web.py (https://127.0.0.1:8080)
            |- diya.py: the Agent (the tool loop, the gates, the voice, lookups, notes pages, MCP tools)
            |     -> Ollama (http://localhost:11434): a 3-4B chat model, plus nomic-embed-text for embeddings
            |- diya_db.py: SQLite (diya.db): threads, messages, reminders, tasks, automations, facts, actions, ...
            '- faster-whisper (base): speech to text
Scheduled jobs:
  diya_notify.py (every 5 minutes): due reminders, what Diya writes first, due automations -> the chat and the desktop
  dreaming.py (on a schedule): reads chats -> staged facts -> lanes and questions, or the Memory page
Command-line tools you run: diya_review.py, diya_knowledge.py, diya_mcp.py, diya_advisor.py, diya_data.py, diya_run.py ...
```

### 5.2 What happens to one message

1. The page sends it to its own server, which adds the access token and forwards it to the API.
2. The API checks the token, the Host and Origin, and the body size.
3. The Agent decides **in code** what kind of message it is: a greeting, a fact being shared, a request for a reminder, a question about something you did, a question about your notes, a question that needs
   the web, or an ordinary message. Each kind changes what happens next (which note is added to the model's instructions, which tools are offered, whether the reply is streamed).
4. It builds what the model is told: who Diya is and the date, then the facts about you (all of them, or the lasting ones plus those closest to this message), then, at the end, any note for this turn.
5. The model answers, or asks for a tool. A tool call is checked (right arguments? asked for? an approved MCP tool unchanged?), run, and its result goes back to the model, up to 8 rounds.
6. The reply is checked or tidied in code where a rule applies (a fact-share is cut to one sentence; a greeting loses an invented name).
7. The message and the reply are stored. Dreaming reads the stored messages later and may stage facts.

### 5.3 The memory pipeline

`your message -> Dreaming (the model proposes facts, from your own messages only) -> candidate -> checks (is it supported by what you said? private? does it replace something?) -> lane: remember / ask / never ->
accepted (told to the model) or a question card or rejected -> Undo / correct / forget at any time`. Every change is an event in an append-only trail (`fact_events`). Facts are never taken from tool output or web text.

### 5.4 The approval pipeline

The model can only *propose* an action. The proposal is stored with its exact arguments and a hash of them; the Actions page shows them; **Approve** is bound to that hash, so what you approved is exactly what runs;
the result is recorded; a run whose outcome is unknown is shown as such. A proposal made after the model read untrusted text carries a warning that says which tools ran before it.

### 5.5 The main files (the full map is in Appendix C)

| File | What it does |
|---|---|
| `diya.py` | the Agent: tools, the loop, prompts, gates in use, small talk, lookups, notes pages |
| `diya_intent.py` | the gates in code: fact-share, reminder request, small talk, done-question, lookup, notes question, task request, forget/correct |
| `diya_memory.py`, `diya_recall.py`, `diya_checks.py`, `diya_autonomy.py`, `diya_questions.py`, `dreaming.py` | memory: store, relevance recall, grounding checks, lanes and caps, questions, the nightly job |
| `diya_schedule.py`, `diya_repeat.py`, `diya_time.py`, `diya_notify.py`, `diya_proactive.py`, `diya_automations.py` | time, repeats, the notifier, Diya writing first, automations |
| `diya_actions.py`, `diya_connectors.py`, `diya_connector_tools.py`, `diya_google_calendar.py`, `diya_mcp.py` | approvals, connectors, MCP client |
| `diya_knowledge.py`, `diya_knowledge_api.py` | knowledge pages from notes |
| `diya_web.py` and the `*_api.py` files | the HTTP API, one module per area |
| `frontend/` | the Next.js UI: one folder per page, same-origin proxy routes, the sidebar |
| `diya_db.py` | SQLite and numbered migrations (currently 16) |
| `tests/` | 95 test files plus the labelled message sets and helpers they use: unit tests with a fake model, benchmarks, evals, static checks |

### 5.6 How it is tested

- **A fake model client** scripts the model's replies, so thousands of tests run in minutes with no Ollama.
- **Labelled sets** of hand-written messages pin each gate (what must be a reminder request, what must not); the known misses are kept in the file on purpose.
- **Real-model checks** (`diya_evals.py` and the benches) run the real model on a temporary database and are never part of the automated suite.
- **Static tests** keep invisible characters out of the source, keep personal data and addresses out of the repo, list every route and check it needs the token, and check what a module imports.
- **CI** runs the whole suite on every push. A pre-push audit looks for names, secrets and addresses.
- **Mutation checks** (on the to-do list unit: 294 deliberate breakages, 282 caught first time; the rest got a test or were redundant) show whether the tests would notice a break.

---

## 6. How to build something like it

Two meanings of "how to actually build it", and both are covered: (6.1) a recipe for building a local, trustworthy assistant from nothing, in the order that worked here; (6.2) what it takes to turn *this* Diya
into something used every day.

### 6.1 A recipe, in order

Each step lists what to build, what to measure, and the trap found here.

| # | Build | Measure | Trap found here |
|---|---|---|---|
| 1 | **Talk to a model through code.** Install Ollama, pull a small model, call it with a few lines of Python (the OpenAI-compatible endpoint). | time to first word, tokens per second on your CPU | Know your hardware's limits first; a big model that loads slowly ruins everything after it. |
| 2 | **A tool-calling loop.** Describe a few functions (weather, search, notes) as JSON schemas; let the model ask for one; run it; give the result back; cap the rounds. | how often it calls the right tool; how often it calls one nobody asked for | A small model calls tools unasked (a task tool on 13% of unrelated messages with the 3B model here). Guard the tool, not just the prompt. |
| 3 | **Save things.** SQLite: threads, messages; add numbered migrations from day one. | a restart loses nothing | Keep personal data out of git from the first commit. |
| 4 | **Memory, staged.** Let a nightly job propose facts from the person's own messages into a *candidate* table; add a review step before the model is told anything. | how many candidates are junk (here 3 of the first 7 were) | Never extract facts from tool output or web text; a wrong fact quietly becomes true. |
| 5 | **Put the decisions in code.** For each judgement (is this a reminder? a fact? a greeting?), write a rule, a hand-labelled set of messages, and a test; only then ask whether a model would do better. | rule against model on the same labelled messages | The model was worse at every gate tried. Prompts did not hold it. |
| 6 | **Time and scheduling.** Read times and repeats from the person's own words in code; refuse a time the model changed; run a small job every few minutes. | does a reminder fire once, at the right time | Time zones, "next Tuesday", and a model that "improves" the time. |
| 7 | **A UI.** A simple web page with streaming replies; keep the token on the server side; pages for reminders, memory, actions. | does a failed call say what happened (never silence) | A UI that hides a failure is worse than one that crashes. |
| 8 | **Approvals.** The model proposes; a person approves exact arguments; every step is recorded. | an unapproved action never runs | Show the taint (what untrusted text was read first). |
| 9 | **Treat all text as data.** Give web pages, notes and tool replies to the model behind a warning, and no tools for that answer. | does an injected sentence change what happens | Anything that can reach the outside with free text is a leak path (web search is one). |
| 10 | **Measure everything with the real model and write down the limits.** Benches, evals, "not measured" sections. | every claim has a number or an honest "unknown" | Labelled sets that are too thin mislead any search over changes. |
| 11 | **Harden before you add.** A security audit, a login, Host/Origin checks, a pre-push scan. | the audit's findings, fixed or accepted on purpose | Run tests on *tracked* files; one check only looks at files git knows. |
| 12 | **Use it.** Two weeks of real use, then decide what to build. | the list of things that annoyed you | Do this earlier than felt comfortable. |

Rough effort for a first version of steps 1 to 7 on one laptop: a few weeks of focused work for someone who can code; with an AI writing the code and a person reviewing, about the same wall-clock time here
(the whole Diya was built in 25 days), but with the person understanding less of it. The recipe's most important instruction is step 12.

### 6.2 From this Diya to something used every day

| Step | What | Why it comes first | Needs from the owner |
|---|---|---|---|
| 1 | **Use it for two weeks** with the notifier scheduled, one real automation, plain-word reminders, and the Memory page reviewed. | It turns "tested on invented data" into evidence. | Time; a scheduled task (`python diya_run.py --install --with-jobs`). |
| 2 | **Point it at your real notes** (`DIYA_NOTES_DIR`) and press "Read my notes now". | Memory and knowledge pages have nothing to be useful about otherwise. | A folder you choose. |
| 3 | **Connect Google Calendar** if you use it. | The day page and answers about your day become real. | A Google app (`docs/GOOGLE_SETUP.md`). |
| 4 | **Reach it from your phone** over a VPN, or try the Telegram bot. | A tool you only use at your desk gets used less. | A phone; an hour. |
| 5 | **Decide about speed.** If 10 to 30 seconds is the reason you do not use it, a bigger machine (the Mac mini idea) or a smaller prompt is the lever, not more features. | It is the most likely reason it is not a daily tool. | A decision on hardware. |
| 6 | **Decide what it is for:** a daily tool, or a showcase and learning project. | The two lead to different next steps (section 10). | A decision. |

---

## 7. How this one got built

### 7.1 Where it started

The project began on 2026-09-16 as a learning project: the owner (a student learning AI engineering) wanted to understand how a commercial local assistant (Truffle, from a research dossier) works, by building small
honest versions of its mechanisms, on the laptop they had, before any hardware arrived. It became "Diya" that day, and the aim grew into feature parity with what Truffle does, for real daily use, with no end date.

### 7.2 Phase 1: five milestones (finished 2026-09-16)

| Milestone | What was built | What it proved |
|---|---|---|
| 1 | Call a local model from Python, then stream | "an AI chat app" is a program calling a web address |
| 2 | Tool-calling, raw and through MCP (`milestone2_*.py`) | how a model asks for a tool and how a tool server is spoken to |
| 3 | Notes search with embeddings (`milestone3_rag_demo.py`) | retrieval is "find the nearest text" |
| 4 | A proactive watcher and chat (`milestone4_*.py`) | scheduled jobs acting without being asked |
| 5 | A capstone agent loop (`milestone5_capstone.py`) | the pieces together |

These files remain in the repository as the record of the first, learning phase (`archive/`).

### 7.3 Phase 2: building Diya for real (2026-09-20 onward), by stage

| Stage | What was built | Roughly when |
|---|---|---|
| **0. Safety and reproducibility** | pinned dependencies, migrations, tests that cannot reach live data, text-file hygiene, CI | Sep 20-25 |
| **1. Trust** | an access token on every route, Host and Origin checks, body limits, TLS, a UI that explains every failure, later a passcode login | Sep 22-28 |
| **2. Trustworthy memory** | staged facts, review on the command line and the Memory page, grounding checks, person-tagged facts | Sep 25-28 |
| **Proactivity** | reminders that fire, guards against unasked reminders, the notifier | Sep 26-28 |
| **3. Connectors** | Todoist, Notion, Home Assistant, Google Calendar (sign-in from a page later) | Sep 28-Oct 5 |
| **4. Actions and approvals** | proposals, hashes, the Actions page, taint warnings; a native task list | Oct 4-5 |
| **Model bake-off** | `qwen3:4b-instruct` beat `qwen2.5:3b` on routing; not switched at first | Oct 9 |
| **The big October build** | repeating reminders, Scheduled and Today pages, the UI redesign, automatic memory with lanes, questions, corrections and Undo, Diya writes first, the phone channels, one-command launcher, automations, an audit | Oct 10-11 |
| **The research units** | recall (R1), knowledge pages (K1), the harness advisor (H1), the MCP client (M1), a greeting fix | Oct 13-14 |

### 7.4 How the work was run

- **Roles.** The owner decides, runs every command and reviews; Claude writes the code, explains why, proposes the next step and does not assume an explanation stuck.
- **Design first.** Each unit starts as a design document (what, why, what must never happen), then tests, then code, then a measurement with the real model, then a short commit.
- **Working agreements** (written down in `CLAUDE.md` and memory notes): approval before deleting live data; small commits; stop at the checkpoint the owner names; disclose every deviation from "keep behaviour"; **never push
  unless asked**; scan for personal names before any push.
- **Research feeds the plan.** Every post, paper or product the owner shared got an entry (what it is, how it was checked, why it matters, what it led to), and only then maybe a unit in the plan.

### 7.5 Lessons that changed the work

1. **The small model is bad at gating.** Measured, then the gates moved into code (`docs/GATE_BENCHMARK.md`).
2. **Prompts do not hold a 3-4B model.** A greeting still invented a name in 11 of 12 replies after the prompt forbade it; code tidies the reply now.
3. **Measure before you design.** The repeating-reminder design changed after real-model runs (the person's own words are the rule); the model bake-off changed which model is recommended.
4. **A thin labelled set misleads.** The advisor proposed a harmful edit that broke none of 71 cases; 50 everyday messages fixed it.
5. **An invented-data test is not a real test.** Every newest unit says so in its own "not measured" part.
6. **Keep personal data out of prose too.** A design doc once named the owner in an ordinary sentence; only the pre-push audit caught it, and the commit was rewritten before it was pushed.
7. **Never run a background mutation job on the real files.** One was killed and left a mutated file behind; mutation runs now work on private copies.
8. **The tool sandbox is not the real world.** Files written outside the project by the assistant's own tools were not real; probes are done with a throwaway scheduled task instead.
9. **A check that only looks at tracked files passes locally and fails after the push.** A literal invisible character in a new test helper broke CI once.
10. **Do not overclaim.** The README once said "used every day" when it was not.

### 7.6 What the process cost

Speed is the headline (25 days, 174 commits), and the price is that the owner has said it feels like too many tests, summaries and decisions, and that it is hard to be sure what was used from other projects (nothing was
copied; they were only read). Reports are now meant to be short and to lead with what the owner can see.

---

## 8. The research behind it

`RESEARCH.md` has 34 dated entries. Each says what the thing is, how it was checked (and what was *not* read), why it matters and what it led to. Nothing is cited as fact unless it was checked; a secondary summary is said to be one.

### 8.1 By theme

| Theme | Entries | What was taken | What was refused |
|---|---|---|---|
| **Comparable products** | 1 Truffle, 2 Instinct, 3 Perplexity Computer, 4 Meta Muse, 5 Equal AI, 22, 25, 33 | auditability as the difference; approval gates and action trails; call management as a future item | multi-model routing and a capital race; citing unconfirmed Truffle numbers |
| **Agent security** | 16 the open-source agent wave, 17 the lethal trifecta and Rule of Two, 34 numbat | no marketplace, no shell, approve-one-by-one, taint warnings, unattended = read-only; a tool-call journal is the open gap | any skill ecosystem; free web fetching |
| **Memory** | 10 supermemory, 14 Hindsight, 21 Cognition's agent memory repo, 26 Mem0 and Devin "Dreaming", 28 how AI memory works, 29 Sentient OS, 31 entity pages | review before trust; time-aware facts; relevance recall; Markdown pages grouped by name; corrections replace | merging or retiring facts in the background without asking; AGPL code |
| **Proactivity** | 18 ChatGPT Pulse retired for "scheduled tasks" | user-steered recurrence, a Scheduled view, a briefing built from what Diya already reads | new kinds of autonomy |
| **Models, runtime, MCP, speech** | 19, 23, 7 laya-mlx, 8 OpenJev, 9 DeepSeek | a model bake-off; MCP only as a client of servers you choose, behind approval | no runtime or voice change without a measurement |
| **Self-improving agents** | 12 harness tooling, 13 weekly roundup, 15 SkillOpt, 30 a week of papers | the loop in its safe, propose-only form (the advisor) | anything that edits itself unreviewed |
| **Hardware and market** | 20 | keep the Mac mini deferred; spend effort on trust and use | buying hardware for a problem not yet met |
| **Connectors** | 11 | build only for what the owner uses daily | a connector for a service nobody opens |
| **Learning material, and posts checked and found not actionable** | 32 four reading lists; 9, 13, 23, 24, 27 checked | a reading path in the research plan | serving and training at scale; frontier-model news that changes nothing here |
| **Similar projects** | 33 a survey of 51 repositories | `docs/COMPARISON.md`, a licence rule for borrowed code | AGPL code; presenting anything as ours that is not |

### 8.2 Idea to built thing

| Idea (entry) | Built as |
|---|---|
| Rule of Two, the lethal trifecta (17) | approvals with taint, read-only automations, no tools for notes pages and lookups' second pass |
| Memory poisoning (17) | facts only from the person's own messages; staging, lanes, Undo |
| Supermemory's "decision model in the harness" (10) | the gate benchmark, which found code beats the model |
| ConvoMem, LongMemEval, "lost in the middle" (28) | relevance recall only when the memory outgrows the room |
| "Forget" and expiring facts (28) | time-aware questions (D1) |
| Sentient OS, CorpusMap, Cognition's memory repo (21, 29, 31) | knowledge pages (K1) |
| Harness learning, MASS, RSI-Anything (30) | the propose-only advisor (H1) |
| MCP in 2026 (19) | the MCP client with pinned, read-only tools (M1) |
| ChatGPT Pulse retired (18) | repeating reminders, the Scheduled and Today pages, automations |
| numbat (34) | the tool-call journal idea (J1), on hold |

### 8.3 The licence rule

Ideas, designs and formats are free to take. Code from another project goes in only with its licence read, its notice kept and its author credited, and is never presented as ours. MIT and Apache-2.0 code may be
used that way; AGPL code is not used, because Diya is published "all rights reserved" and AGPL would oblige the whole of it to be offered under AGPL. So far **nothing has been copied**; other projects were read.
The rule is in `THIRD_PARTY_NOTICES.md`.

---

## 9. Products like Diya, and how it differs

### 9.1 The landscape

| Kind | Examples | What they do well | Compared with Diya |
|---|---|---|---|
| **Local chat front ends** | Open WebUI, Jan, AnythingLLM | polished, many models, documents, plugins, large communities | far more polished and featured; no reviewed memory or approval design |
| **Personal agents** | OpenClaw, Hermes Agent, Leon | reach (chat apps, voice, many skills), self-improving skills | much bigger reach; a security record that is the reason Diya has no marketplace |
| **"Second brain" and notes** | Khoj (AGPL), Sentient OS (AGPL, Mac only), basic-memory (AGPL) | chat with your documents, overnight knowledge bases, Markdown memory | do more with documents today; Diya's pages are copied sentences, never model-written |
| **Memory libraries** | mem0, supermemory, Hindsight, cognee, graphiti, MemOS, letta | extraction, graphs, benchmarks, connectors, hosted options | far more capable memory machinery; they mostly learn *on their own* where Diya asks first |
| **Commercial** | Truffle (appliance), Instinct, Perplexity Computer, Meta Muse, Equal AI | funding, hardware, finish | different league; Diya is one person's project |
| **Agent audit tools** | numbat (Perplexity) | watching other agents' actions on a computer | the gap it showed in Diya: no journal of read-only tool calls |

`docs/COMPARISON.md` goes project by project. **Caveat:** it was made from each project's README only, so "none of them says X" is weak evidence that none does X.

### 9.2 Where Diya differs

What nearly everyone has now: local models, memory across chats, scheduled prompts, voice, notes search. Diya has these too and does them less polished. What it does differently is a set of trust choices:

1. A **reviewed memory**: the model is told only accepted facts; automatic acceptance has lanes, a cap, a breaker and Undo.
2. **Questions instead of silent merges** when a remembered day has passed or a fact may replace another.
3. **Approvals bound to exact arguments**, with a trail and a taint warning.
4. **Code decides, the model writes**, with the reason measured.
5. **Notes pages made of your own sentences**, so nothing can be invented.
6. **MCP tools pinned and read-only**, so a changed tool is not called.
7. **Everything measured on a CPU laptop with the real model**, and the limits written next to the claims.

### 9.3 Is that special?

- **As a product:** not yet. These choices matter to a small audience (people who distrust cloud assistants and are willing to run a small model), and they sit on top of a weaker model and a rougher experience.
  Each choice also exists somewhere else, and the combination is narrow rather than protected. No business case has been shown.
- **As a worked example:** yes. A complete, tested, documented local agent that says plainly what it measured and what it did not is rare, and is real value for an AI-engineering student or a portfolio.
- **As findings:** some are worth writing up on their own: code beats a small model at gating decisions; a small labelled set misleads any search over changes; review-before-trust memory and approvals are cheap to
  build and expensive to retrofit.

---

## 10. Verdict, and what to do next

### 10.1 Scorecard

| | |
|---|---|
| Engineering and safety quality | **High**: tested, measured, audited, honest limits |
| Real daily use | **Very low** so far |
| Differentiation as a product | **Narrow**: a trust philosophy rather than features |
| Market or business case | **None shown** |
| Learning and portfolio value | **High** |
| Biggest risks | unused feature sprawl; AI-written code the owner cannot yet maintain; overclaiming; a model that may simply be too small |

### 10.2 Does it have any use?

- **Today, for the owner:** little in daily life, because it is slow, weaker than the free assistants, and not yet connected to anything real. It becomes useful only when it holds real information and is used.
- **As a private notes-and-reminders assistant,** it could be: plain-word reminders, a morning weather automation, "what do my notes say about X?", a memory you control. Cloud assistants do the first and the last better with less
  effort; the reason to prefer Diya is privacy and inspectability.
- **As a base:** its parts (the reviewed memory, the approval gate, the advisor, the pinned MCP tools) could be separated into a small library or a write-up.

### 10.3 A 30-day plan

| Week | Do | Success looks like |
|---|---|---|
| 1 | Schedule the notifier; set `DIYA_NOTES_DIR`; build the pages; review the waiting facts; keep one real automation. | You open Diya on most days. |
| 2 | Use plain-word reminders and the Today page for real; note every annoyance. | A written list of what annoyed you, ranked. |
| 3 | Fix the top three annoyances only; try Google Calendar; try the phone over a VPN. | The list got shorter; one connector works for real. |
| 4 | Decide the goal: daily tool, or showcase. If daily: speed (hardware or prompt size). If showcase: write up the findings and trim the scope. | A decision written in `ROADMAP.md`. |

### 10.4 What I would not do next

- Add more features before the two weeks of use.
- Build MCP tools that change things before a real server has been tried read-only.
- Buy hardware before knowing whether speed is really the reason it is not used.

---

## 11. Appendices

### A. Glossary

| Word | Meaning here |
|---|---|
| **Ollama** | a program that runs open language models on your computer and answers over a local web address |
| **Model, 3B / 4B** | a language model with 3 or 4 billion parameters: small enough for a laptop CPU, much weaker than cloud models |
| **Tool** | a function the model may ask the program to run (search the web, add a reminder) |
| **Gate** | a yes/no decision made in code before the model answers (is this a reminder request?) |
| **Embedding** | a list of numbers that stands for the meaning of a text, used to find the nearest text |
| **Dreaming** | the scheduled job that reads your chats and proposes facts |
| **Candidate / accepted / rejected / retired** | the states of a fact |
| **Lane** | where a candidate goes: remember, ask, or never |
| **Taint** | a warning that untrusted text was read earlier in the turn |
| **Rule of Two** | an agent should have at most two of: untrusted input, access to private data, the ability to act outwards |
| **MCP** | the Model Context Protocol: a way for a program (the server) to offer tools to an AI client |
| **Pin** | a hash of a tool as you approved it; if it changes, the tool is not called |
| **Mutation test** | break the code on purpose and see whether a test notices |
| **Labelled set** | hand-written messages with the right answer for each, used to test a gate |

### B. Commands

| To | Run |
|---|---|
| start everything | `python diya_run.py` (or `python diya_web.py` and, in `frontend/`, `npm run dev`) |
| the terminal chat | `python diya.py new` |
| the whole test suite | `python -m pytest` (about 8 minutes) |
| review memory | `python diya_review.py list | accept ID | reject ID | retire ID | restore ID` |
| build knowledge pages | `python diya_knowledge.py build` (or the Knowledge page) |
| add an MCP server | `python diya_mcp.py add NAME -- COMMAND` then `check NAME`, `approve NAME TOOL` |
| ask the advisor for patches | `python diya_advisor.py propose` |
| move your data out of a synced folder | `python diya_data.py move --to "<folder>" --dry-run` first |
| real-model checks | `python diya_evals.py`, `python diya_actions_bench.py --runs 3`, `python diya_gate_bench.py` |

### C. File map

- **The assistant:** `diya.py`, `diya_intent.py`, `diya_web.py`, `diya_config.py`, `diya_db.py`.
- **Memory:** `diya_memory.py`, `diya_recall.py`, `diya_checks.py`, `diya_autonomy.py`, `diya_questions.py`, `diya_verifier.py`, `dreaming.py`, `diya_review.py`.
- **Time and day:** `diya_time.py`, `diya_repeat.py`, `diya_schedule.py`, `diya_tasks.py`, `diya_notify.py`, `diya_proactive.py`, `diya_brief.py`, `diya_automations.py`.
- **Outside:** `diya_actions.py`, `diya_connectors.py`, `diya_connector_tools.py`, `diya_google_calendar.py`, `diya_mcp.py`, `diya_push.py`, `diya_telegram.py`, `diya_events.py`.
- **Notes and knowledge:** `diya_knowledge.py`.
- **API modules:** the `diya_*_api.py` files, one per area.
- **Benchmarks and tools:** `diya_evals.py`, `diya_*_bench.py`, `diya_advisor.py`, `diya_data.py`, `diya_run.py`, `diya_warm.py`.
- **Interface:** `frontend/` (`app/` pages and `api/` proxy routes, `components/`, `lib/`).
- **First phase:** `milestone*.py`, `archive/`. **Research:** `RESEARCH.md`, `Truffle_Research_Dossier.pdf`, `docs/COMPARISON.md`.

### D. Settings that matter (all are `DIYA_*` environment variables; the full list is in `diya_config.py`)

| Setting | Default | What it does |
|---|---|---|
| `DIYA_MODEL` | `qwen2.5:3b` | the chat model (the owner uses a capped alias of `qwen3:4b-instruct`) |
| `DIYA_NOTES_DIR` | `sample_notes` | the folder your notes are read from |
| `DIYA_KNOWLEDGE_DIR` | `knowledge` | where knowledge pages are written (git-ignored) |
| `DIYA_AUTO_MEMORY` | off | plain facts are remembered on their own, with Undo |
| `DIYA_RECALL`, `DIYA_MEMORY_STORE_CHARS` | on, 20000 | relevance recall, and how much may be kept |
| `DIYA_LOOKUP`, `DIYA_KNOWLEDGE_CHAT`, `DIYA_MCP` | on | web lookups, answers from notes pages, MCP tools |
| `DIYA_CATEGORIES` | on | each message you send is put in one category after the reply (`docs/ONE_CHAT_DESIGN.md`); `0` stops the sorting |
| `DIYA_MAIL` | on | once Gmail is connected, "any email from the college?" looks through the mail, read-only (`docs/GMAIL_DESIGN.md`) |
| `DIYA_PROTECT_SECRETS` | on | connector sign-ins and Google's client secret are stored encrypted for this Windows user (`docs/SECRETS_DESIGN.md`); `0` keeps them plain |
| `DIYA_BACKUP`, `DIYA_BACKUP_DIR` | on, `backups/` | a checked snapshot of the memory when the API starts and once a day (`docs/BACKUP_DESIGN.md`); by hand: `python diya_backup.py make` |
| `DIYA_REPO_STUDY` | on | "study https://github.com/owner/repo" reads a public repository, read-only, and shows the evidence (`docs/REPO_STUDY_DESIGN.md`) |
| `DIYA_DATA_DIR` | beside the code | one folder for everything Diya writes about you |
| `DIYA_TOKEN`, `DIYA_UI_PASSCODE` | generated / unset | the API token the UI sends, and the page's login |
| `DIYA_PUSH`, `DIYA_TELEGRAM`, `DIYA_AUTOMATIONS`, `DIYA_PROACTIVE` | off, off, on, on | the phone channels, automations, Diya writing first |

### E. The documents, by topic

Memory: `STAGE2_DESIGN`, `PERSON_MEMORY_DESIGN`, `AUTO_MEMORY_DESIGN`, `RECALL_DESIGN`, `dreaming`. Your day: `PROACTIVITY_DESIGN`, `SCHEDULE_DESIGN`, `TASKS_DESIGN`, `PROACTIVE_DESIGN`, `AUTOMATIONS_DESIGN`, `reminders`.
Talking: `SPEED_DESIGN`, `STREAMING_DESIGN`, `VOICE_DESIGN`, `LOOKUP_DESIGN`, `UI_DESIGN`. Outside: `CONNECTORS_DESIGN`, `GOOGLE_SETUP`, `ACTIONS_DESIGN`, `MCP_DESIGN`, `PUSH_DESIGN`, `TELEGRAM_DESIGN`, `PHONE_CHANNEL_DESIGN`.
Trust: `STAGE1_DESIGN`, `UI_LOGIN_DESIGN`, `lan`, `AUDIT_2026-10-10`. Notes and tools: `KNOWLEDGE_DESIGN`, `ADVISOR_DESIGN`. Measurements: `GATE_BENCHMARK`, `MODEL_BENCHMARK`.
Research and plans: `RESEARCH.md`, `RESEARCH_PLAN_2026-10`, `COMPARISON`, `ONE_COMMAND_DESIGN`. All are in `docs/` except `RESEARCH.md`, `ROADMAP.md`, `PRODUCT_VISION.md` and `README.md`.

### F. What waits for the owner

1. A notes folder of your own (`DIYA_NOTES_DIR`), and pressing "Read my notes now".
2. Scheduling the notifier and Dreaming (the commands are in `docs/reminders.md` and `docs/dreaming.md`).
3. Reviewing the four facts waiting on the Memory page.
4. Trying, once, the things that were never tried for real: the microphone, Google Calendar, Todoist, the phone channels, a first MCP server.
5. Applying (or declining) the six reminder-gate patches the advisor proposed.
6. Moving the data folder out of the cloud-synced folder (`python diya_data.py move`).
7. Deciding what Diya is for (section 10), and what to build or stop building.
