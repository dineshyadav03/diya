# Diya: product vision and current state

This document describes what Diya is meant to be and what it is today. The install and run steps are
in the [README](README.md); the Stage 0 work list is in [ROADMAP.md](ROADMAP.md). It is rewritten
when the state changes, not appended to. Last checked against the code on 2026-10-12.
Market and technical context is kept in [RESEARCH.md](RESEARCH.md).

## Promise

Diya is a personal assistant for one person that keeps the sensitive parts local:

1. **Inference stays on the device.** The model, the embeddings and the speech-to-text run on the
   owner's own machine. Only two tools go online, on request: `web_search` and `get_weather`.
2. **Memory that is earned, not assumed.** What Diya learns from conversations is staged for review
   and enters the trusted profile only when it is promoted. A wrong fact must not silently become true.
3. **Proactive, not only reactive.** Scheduled jobs act without being asked.
4. **Extensible.** New tools are added as functions with a schema and tests.

The design follows the architecture in the Truffle research dossier (source: `dossier_content.py`), which
describes a commercial local-first assistant. Diya is a one-person project; the table below shows how far it is.

## Current state

| Area | Status |
|---|---|
| Local inference | Done. Ollama, `qwen2.5:3b` for chat by default (on the owner's computer `diya-chat`, `qwen3:4b-instruct` with its context capped; see `docs/MODEL_BENCHMARK.md`), `nomic-embed-text` for embeddings, via the OpenAI-compatible API. |
| Tools | Eight, in `diya.py`: `search_notes`, `web_search`, `get_weather`, `add_reminder`, `list_reminders` (pending by default, or the ones already ticked off), `add_task`, `list_tasks`, `list_files` (plus a connector's tools while it is connected). `add_reminder` saves nothing unless the message asked for a reminder, reads the time (and a repeat) itself and refuses a time the model changed; `add_task` is the same shape for the to-do list kept inside Diya (docs/TASKS_DESIGN.md) and the model has no tool that closes, edits or deletes a task. Loop capped at 8 rounds; network tools time out after 5 s. `list_files` only lists inside `DIYA_FILES_ROOTS` (default `Documents/Diya`); `get_weather` only reaches the hosts in `DIYA_TOOL_ALLOWED_HOSTS` (default: the two Open-Meteo hosts). No MCP app store. |
| Conversations | Done. Threads and messages in SQLite, a history page with a search box that looks inside every chat (ignoring case, showing the piece that matched), a Rename button on each chat, and reopening a thread. |
| Notes memory | Partial. `search_notes` searches `sample_notes/` (or `DIYA_NOTES_DIR`) through an in-memory Chroma index, built on first use and built again whenever a note is added, edited or removed (no restart needed). `python diya_knowledge.py build` turns a notes folder into Markdown pages, one per recurring name, made only of the person's own sentences, with no model (`docs/KNOWLEDGE_DESIGN.md`); a Knowledge page in the UI reads, builds and hides them, and "what do my notes say about Maya?" in the chat is answered from the page (with no tools: a note is read, never obeyed). No ingestion beyond a folder of text files. |
| Long-term memory | Done for the loop, at small scale: Dreaming stages candidate facts, `diya_review.py` reviews them, and the model is told the accepted ones (see below). Reviewed on the command line or on the UI's Memory page, with an optional second opinion from the model (`judge`, advisory only). **Relevance recall** ([`docs/RECALL_DESIGN.md`](docs/RECALL_DESIGN.md)): once the facts outgrow the 2,000 characters told in one message, the model is told the lasting facts about the person plus those closest to what was just said, and up to 20,000 characters may be kept. **Memory that remembers on its own** ([`docs/AUTO_MEMORY_DESIGN.md`](docs/AUTO_MEMORY_DESIGN.md)) is built and measured, and **on** here since 2026-10-13 (`DIYA_AUTO_MEMORY`): code puts each candidate in a lane (remember, ask, never), the model's own answer to "is this private?" and "does this replace something known?" can only add caution, every automatic fact is marked and can be undone on the Memory page, and a waiting fact that may replace an old one has a one-press "Replace the old one". It is turned on only by the owner, after reading the measurement. |
| Proactivity | Built, and the notifier (`diya_notify.py`, every five minutes) is the one scheduled task behind all of it. Reminders have real due times and can repeat (every day, every weekday, every Monday, every month on the 15th, every 2 weeks), read in code from the person's own words (`docs/SCHEDULE_DESIGN.md`), with snooze, a Reminders page, a Scheduled page and a Today page built in code from the owner's own data. **Diya writes first** (`docs/PROACTIVE_DESIGN.md`): a good-morning with the day, an evening check-in when something is still open, a message when a reminder comes due and a hello after a quiet spell, written in the chat itself and put on the desktop, built in code so nothing is invented. **Automations** (`docs/AUTOMATIONS_DESIGN.md`): "every morning at 8am tell me the weather in Pune" is read in code, stored, and run on schedule with read-only tools, the answer written in the chat; an Automations page lists, pauses, runs and deletes them. A tick on a reminder keeps when, and a question about something the person did ("when did I buy the guitar strings?") is given what they ticked off (`docs/PROACTIVITY_DESIGN.md`). Dreaming runs on a schedule. The notes watcher is a Phase 1 script and is not connected to the assistant. |
| Client | Done for the web. A Next.js UI with chat (replies appear word by word, with an orb while Diya thinks and while she listens), history, tap-to-talk voice input and optional spoken replies, in a light and a dark theme that were checked for contrast (`docs/UI_DESIGN.md`). No native apps. Reaching Diya from a phone is built in three separate, switched-off parts, none tried against a real service or phone: a VPN is the way to reach the UI away from home (`docs/lan.md`, a description only); Web Push tells a subscribed device that a reminder, question, action or the day is waiting, by default without saying what (`docs/PUSH_DESIGN.md`); and a Telegram bridge answers only a paired owner's plain-text messages, with no approvals possible from it (`docs/TELEGRAM_DESIGN.md`). One command starts the API and UI together (`diya_run.py`, `docs/ONE_COMMAND_DESIGN.md`). |
| Harness advisor | Step 1 built (`diya_advisor.py`, `docs/ADVISOR_DESIGN.md`): for the reminder gate it searches for small edits that fix the documented misses, checks each against 119 labelled messages and the owner's own history, writes a report and patches, and never applies one. One gate so far. |
| Self-authored tools | Not built. |
| Dedicated always-on hardware | Not started. Diya runs on the owner's Windows machine. |

## Current user experience

- Two themes from one set of tokens (`docs/UI_DESIGN.md`): a warm-paper light theme with one blue, and a near-black dark theme with hairlines
  and white pills. It follows the operating system's setting, or Light/Dark/System at the foot of the sidebar. One sidebar (a menu on a
  phone) is the only navigation, with a count on Reminders (due) and Actions (waiting); the chat is a document-like transcript and a plain
  message box.
- **Chat.** A message goes to `/api/chat/stream` (or `/api/chat` from an API without it). The reply appears as it is written, with an orb while Diya reads the question, and the UI shows which tools it used. Diya has a voice (`diya.PERSONA`): a greeting is answered in a short, different sentence that uses the person's name, with no tools and the model already loaded, so "hey" takes about a second (`docs/SPEED_DESIGN.md`, `docs/STREAMING_DESIGN.md`).
- **Diya writes first.** Cards at the top of the chat show what she wrote on her own (the day, an evening check-in, a reminder that came due); Reply opens that chat and Dismiss hides it.
- **Past chats.** Search inside every chat, and give a chat a name.
- **Automations.** Say what to do and when, in the chat or on the Automations page; a run can only read, and its answer arrives as a message.
- **Plain facts get one line.** A message that only shares a fact ("my flight is Friday at 6") gets a
  one-sentence acknowledgement and no tool calls (`diya_intent.py`). Questions and requests are
  handled normally.
- **Voice in.** Tap the mic to start, tap it again to send (`docs/VOICE_DESIGN.md`); the audio is uploaded and transcribed by faster-whisper (`base`), which only reads the stretches a speech detector finds, because on silence it invents words (measured: four seconds of nothing came back as "You"). A recording with no sound in it is not sent: the microphone that gave it is skipped next time.
  Recording uses the browser's `MediaRecorder`, so it also works where no speech-recognition API exists.
- **Voice out.** Off by default. The "Speak" checkbox turns on the browser's speech synthesis and is
  remembered per browser; "Test voice" always speaks.
- **A failed send** is marked on the message with a "Try again" action instead of being dropped.
- `frontend/tools/design-rig` checks the UI with stub data at three widths: WCAG AA text contrast and
  DOM assertions, without touching the real backend or microphone.

## Architecture

```
browser (Next.js, HTTPS) -> FastAPI diya_web.py (HTTPS, loopback by default)
                              |- Agent (diya.py): tool loop -> Ollama
                              |- Store (diya_db.py): SQLite threads, messages, reminders, tasks, automations, facts, actions
                              '- faster-whisper
scheduled: dreaming.py reads the database -> dream_pending.jsonl (+ dream_state.json, dream_log.txt)
scheduled: diya_notify.py (every 5 min) -> reminders that came due, what Diya writes first, due automations -> the chat and the desktop
```

Nothing is loaded at import time. Settings come from `DIYA_*` variables (`diya_config.py`); the
agent, the database, the notes index and the Whisper model are created on first use or at startup.

## Memory lifecycle

1. **Source.** Every message is stored in the thread it belongs to. Within a thread, the history is
   the memory.
2. **Extraction (Dreaming).** `dreaming.py` reads the user's messages, across all threads, that are newer
   than its checkpoint (`dream_state.json`) and asks the model for genuinely new facts. It never sees
   the profile, so it cannot drop what is already known.
3. **Staging.** Each batch becomes one JSON record appended to
   `dream_pending.jsonl` (timestamp, message id range, model, facts), flushed to disk before the
   checkpoint moves. A crash between the two is repaired on the next run without extracting twice.
   An unreadable queue stops the cycle instead of risking a duplicate.
4. **Review.** `diya_review.py` copies staged facts into `diya.db` as candidates (`facts`, with every
   change recorded in `fact_events`), checks each against the messages it came from, and lets you accept,
   reject, edit, retire or restore them. Nothing Dreaming writes is read by the model.
5. **What the model is told.** The **accepted** facts, as one system message in every thread, at most
   2,000 characters. The old `user_profile.txt` was imported once as accepted facts and is no longer
   read; the `direct` mode that appended unreviewed facts to it was retired. Built: Stage 2, all seven
   units (`docs/STAGE2_DESIGN.md`), including the same review on the UI's Memory page and an optional
   advisory model verifier, measured on invented cases only (not yet against your own decisions).

**Two scheduled jobs, not one.** Dreaming (`dreaming.py`) reads the database, writes the staged queue,
and runs every 30 minutes in the reference deployment. The notes watcher (`milestone4_watcher.py`,
every 15 minutes) reads `sample_notes/` and writes `proactive_context.txt` for the Phase 1
scripts; the assistant does not read that file.

## Safety boundary

- The API listens on 127.0.0.1. LAN access needs `DIYA_LAN=1` plus `DIYA_ALLOWED_HOSTS`; the server
  refuses to start with a non-loopback host otherwise.
- Every route rejects a `Host` that is not allowed (400) and a browser `Origin` that is not the UI's
  (403). CORS names the UI origin; it is never `*`.
- A request body over `DIYA_MAX_BODY_BYTES` gets a 413 before any route -- or the model -- sees it;
  `/api/transcribe` has its own, larger `DIYA_MAX_TRANSCRIBE_BYTES` for audio. Enforced against the
  bytes actually sent, not just a declared Content-Length.
- TLS is required (an mkcert pair); the microphone needs a secure origin.
- `list_files` only lists inside the folders in `DIYA_FILES_ROOTS` (default: `Documents/Diya` under
  the home folder, never the repo). A path is judged after it is fully resolved, so `../` and a
  symlink that points outside are refused, and dotfiles, `.env*`, `*.pem` and `*.key` never appear.
- A per-install access token is generated on the first start and shown once; only its SHA-256 is
  kept, in `diya_token.hash`. An outermost middleware answers 401 (`WWW-Authenticate: Bearer`) to
  any request without `Authorization: Bearer <token>`, on every route, comparing hashes with
  `hmac.compare_digest`. It is required by default, so another process on this computer (or a LAN
  device that merely knows an allowed `Host`) is refused; `DIYA_REQUIRE_TOKEN=0` is the explicit
  opt-out. The UI needs it as `DIYA_TOKEN`. `--rotate-token` (or `DIYA_ROTATE_TOKEN=1`) replaces it.
- The browser never holds that token. It calls the UI's own `/api/*` routes; the Next.js server
  forwards each to the API at a fixed loopback address (`127.0.0.1:<DIYA_PORT>`, never derived from
  the request, so a forged `Host` cannot steer the token) and adds `Authorization: Bearer
  $DIYA_TOKEN`. Nothing else is copied from the browser's request, the token is sent only over
  https or to this computer, and a thread id must be a whole number. A phone that reaches the UI at
  a LAN address therefore needs no LAN mode on the API.
- `get_weather` reaches only the hosts in `DIYA_TOOL_ALLOWED_HOSTS` (default: the two Open-Meteo
  hosts). The host is checked before any request is sent, by two URL parsers that must agree, and
  redirects are not followed; loopback and private addresses are refused like any host that is not
  on the list. `web_search` is not covered (see Known gaps).
- Personal data (`diya.db`, `user_profile.txt`, the `dream_*` and `watcher_*` files, certificates) is
  gitignored. The test suite and the evals cannot reach the live database.

**Known gaps.** `web_search` is outside the outbound-host allowlist: its requests are made by the
`ddgs` library (through `primp`), which this code cannot wrap, and "the open web on request" has no
short list of hosts to allow; the options are in `docs/STAGE1_DESIGN.md` section 4. The token is a
single long-lived secret per install: it does not expire, and only rotating it (`--rotate-token`)
invalidates it, a deliberate choice for one user on one machine. Models are pulled by tag, not
pinned -- `ollama pull` has no way to require an exact digest, a Stage 0 item in `ROADMAP.md`.

## Deployment today

Windows. The backend and the frontend dev server run in two terminals. Dreaming and the notes
watcher run from Task Scheduler with `pythonw.exe`, which has no console, so their output is redirected
to `dream_log.txt` and `watcher_log.txt`.

## Verified

- The test suite passes offline, with a fake model client; the dated count is in the README only.
- Nine evals against the real model check tool routing and answer content. Small-model behaviour
  varies between runs.
- Voice input and output were exercised from a phone browser on the local network, before the loopback
  default; LAN mode has not been re-tested on a device since.
- CI (`.github/workflows/ci.yml`) runs on every push to GitHub and is green on the latest commit. The microphone's recovery steps, the phone channels (Web Push, Telegram), the Google Calendar OAuth
  flow and Todoist were never exercised against a real microphone, phone, bot or account; they are built and tested against stand-ins only.

## Known limitations

- **Tool over-use.** The 3B model sometimes calls `add_reminder` on plain arithmetic (roughly 40-50%
  of past runs). Tightening the tool description and lowering the temperature did not fix it; it is a
  model-size limit, to be revisited with a larger model. Since reminders can now fire, the tool itself refuses
  unless the message asks for one: on invented messages the model still tried in 9 of 57 runs and none saved a
  reminder (before the guard, 6 of 38 did). It also changes the times people give ("morning" to "8am", a dropped
  date), so the tool checks them against the person's own words and refuses what was changed; the model then asks
  again (`docs/PROACTIVITY_DESIGN.md`, measured).
- **Speech.** Whisper `base` can mishear the assistant's name.
- **Renamed cities.** The geocoder can match an old city name only to the wrong place, so
  `CITY_ALIASES` maps a few well-known cases to their current names; it is not exhaustive.

## Next

Everything the roadmap planned for Phases 1 and 2 is built in code except what needs hardware or an account that only the owner has: model pinning (blocked on Ollama's own tooling), the Mac mini,
a real Google or Todoist account, and a phone. What is not built at all: Diya writing her own tools, call management and a streaming voice pipeline, each needing its own design and the owner's yes.
The next real step is use: a few days of daily use will say what to fix, which is more useful than more features. What the newest research says to build next, in order, with what each needs from the owner, is in `docs/RESEARCH_PLAN_2026-10.md`. The stage list and the owner's own steps are in `ROADMAP.md`.
