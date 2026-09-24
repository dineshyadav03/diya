# Diya: product vision and current state

This document describes what Diya is meant to be and what it is today. The install and run steps are
in the [README](README.md); the Stage 0 work list is in [ROADMAP.md](ROADMAP.md). It is rewritten
when the state changes, not appended to. Last checked against the code on 2026-09-21.
Market and technical context is kept in [RESEARCH.md](RESEARCH.md).

## Promise

Diya is a personal assistant for one person that keeps the sensitive parts local:

1. **Inference stays on the device.** The model, the embeddings and the speech-to-text run on the
   owner's own machine. Only two tools go online, on request: `web_search` and `get_weather`.
2. **Memory that is earned, not assumed.** What Diya learns from conversations is staged for review
   and enters the trusted profile only when it is promoted. A wrong fact must not silently become true.
3. **Proactive, not only reactive.** Scheduled jobs act without being asked.
4. **Extensible.** New tools are added as functions with a schema and tests.

The design follows the architecture in the Truffle research dossier (source: `render_pdf.py`), which
describes a commercial local-first assistant. Diya is a one-person project; the table below shows how far it is.

## Current state

| Area | Status |
|---|---|
| Local inference | Done. Ollama, `qwen2.5:3b` for chat, `nomic-embed-text` for embeddings, via the OpenAI-compatible API. |
| Tools | Six, in `diya.py`: `search_notes`, `web_search`, `get_weather`, `add_reminder`, `list_reminders`, `list_files`. Loop capped at 8 rounds; network tools time out after 5 s. `list_files` only lists inside `DIYA_FILES_ROOTS` (default `Documents/Diya`). No MCP app store. |
| Conversations | Done. Threads and messages in SQLite, a history page, reopening a thread. Not built: renaming, search. |
| Notes memory | Partial. `search_notes` searches `sample_notes/` (or `DIYA_NOTES_DIR`) through an in-memory Chroma index rebuilt at each start. No ingestion beyond that folder. |
| Long-term memory | Partial. Dreaming stages candidate facts; nothing reviews or promotes them yet (see below). |
| Proactivity | Dreaming runs on a schedule. The notes watcher is a Phase 1 script and is not connected to the assistant. |
| Client | Done for the web. A Next.js UI with chat, history, hold-to-talk voice input and optional spoken replies. No native apps. |
| Self-authored tools | Not built. |
| Dedicated always-on hardware | Not started. Diya runs on the owner's Windows machine. |

## Current user experience

- One dark surface with a warm oat accent; the flame logo is the only saturated colour.
- **Chat.** A message goes to `/api/chat`. Diya answers, and the UI shows which tools it used.
- **Plain facts get one line.** A message that only shares a fact ("my flight is Friday at 6") gets a
  one-sentence acknowledgement and no tool calls (`diya_intent.py`). Questions and requests are
  handled normally.
- **Voice in.** Hold the mic button; audio is uploaded and transcribed by faster-whisper (`base`).
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
                              |- Store (diya_db.py): SQLite threads, messages, reminders
                              '- faster-whisper
scheduled: dreaming.py reads the database -> dream_pending.jsonl (+ dream_state.json, dream_log.txt)
```

Nothing is loaded at import time. Settings come from `DIYA_*` variables (`diya_config.py`); the
agent, the database, the notes index and the Whisper model are created on first use or at startup.

## Memory lifecycle

1. **Source.** Every message is stored in the thread it belongs to. Within a thread, the history is
   the memory.
2. **Extraction (Dreaming).** `dreaming.py` reads the user's messages, across all threads, that are newer
   than its checkpoint (`dream_state.json`) and asks the model for genuinely new facts. It never sees
   the profile, so it cannot drop what is already known.
3. **Staging.** In the default `staged` mode each batch becomes one JSON record appended to
   `dream_pending.jsonl` (timestamp, message id range, model, facts), flushed to disk before the
   checkpoint moves. A crash between the two is repaired on the next run without extracting twice.
   An unreadable queue stops the cycle instead of risking a duplicate.
4. **Profile.** `user_profile.txt`, if it exists, is given to the model in every thread. In `staged`
   mode Dreaming never writes it. `DIYA_DREAM_PROFILE_MODE=direct` appends unreviewed facts straight
   to it and is kept only as an explicit compatibility option.
5. **Promotion: not built.** Nothing reads the staged queue yet, so staged facts do not reach the
   model. Reviewing and promoting them is the next memory feature.

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
- Personal data (`diya.db`, `user_profile.txt`, the `dream_*` and `watcher_*` files, certificates) is
  gitignored. The test suite and the evals cannot reach the live database.

**Known gaps.** There is no per-install token, so any local process can call the API (and in LAN mode,
any device that sends an allowed `Host`). Models are pulled by tag, not pinned -- `ollama pull` has no way to require an exact digest. These
are the Stage 0 items in `ROADMAP.md`.

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
- CI (`.github/workflows/ci.yml`) has not had a real GitHub-hosted run yet; its three commands were
  run in a plain Linux container first, which is where it is verified from for now.

## Known limitations

- **Tool over-use.** The 3B model sometimes calls `add_reminder` on plain arithmetic (roughly 40-50%
  of past runs). Tightening the tool description and lowering the temperature did not fix it; it is a
  model-size limit, to be revisited with a larger model.
- **Speech.** Whisper `base` can mishear the assistant's name.
- **Renamed cities.** The geocoder can match an old city name only to the wrong place, so
  `CITY_ALIASES` maps a few well-known cases to their current names; it is not exhaustive.

## Next

Stage 0 (`ROADMAP.md`): the per-install token behind a
Next.js proxy, model pinning (blocked on Ollama's own tooling). Then the review and
promotion step for staged facts. The stage list is in the roadmap.
