# Diya

Diya is a local-first personal AI assistant for one user: the model, the memory and the speech-to-text
run on your own machine, and only the web-search and weather tools ever go online. Its memory is
staged: facts extracted from conversations are queued for review and are never written to the
trusted profile automatically.

A personal project, not packaged for distribution; it has only been run on Windows.

## Status

Works today:

- **Chat with tools.** Threads persist in SQLite and a history page reopens them. Tools:
  `search_notes` (semantic search over `sample_notes/`), `web_search` (DuckDuckGo), `get_weather`
  (Open-Meteo), `add_reminder`, `list_reminders`, `list_files`. The loop stops after 8 rounds.
- **Short replies to plain facts.** `diya_intent.py` conservatively detects a message that only
  shares a fact ("my flight is Friday at 6"); it gets a one-sentence acknowledgement and no tool
  calls. Everything else reaches the model unchanged.
- **Voice in and out.** Hold the mic button: the audio goes to `/api/transcribe` (faster-whisper
  `base`, CPU, int8). Replies can be read aloud with the browser's speech synthesis; it is off by
  default and the "Speak" checkbox is remembered per browser.
- **Staged memory.** `dreaming.py` (one pass per run) asks the model for new facts in the messages
  since its checkpoint and appends one JSON record per batch to `dream_pending.jsonl`, on disk
  before the checkpoint moves, so a retry never stages a batch twice. In the default `staged` mode it
  does not touch `user_profile.txt`. If that file exists, its text is given to the model in every thread.
- **A closed API boundary.** The API listens on 127.0.0.1 unless LAN mode is on. Every route refuses
  a `Host` that is not on the allowlist (400) and a browser `Origin` that is not the UI's (403).
  CORS names the UI origin; it is not `*`.
- **363 tests**, none of which need Ollama, the network or the live database.

Not built yet:

- Reviewing staged facts and promoting them into the profile. Until then, only
  `DIYA_DREAM_PROFILE_MODE=direct` (unreviewed facts appended straight to the profile) changes
  what the model knows.
- API authentication: any local process can call the API, and in LAN mode so can any device that
  reaches the port with an allowed `Host`.
- Limits on `list_files` (it lists any folder) and on request body size.
- Pinned dependencies and models, database migrations, CI, a license.
- A fix for the 3B model calling `add_reminder` on arithmetic questions (roughly 40-50% of past runs).

## Architecture

```
browser (Next.js, :3000, HTTPS) -> FastAPI diya_web.py (:8080, HTTPS)
                                     |- diya.py Agent (tool loop) -> Ollama :11434 (qwen2.5:3b, nomic-embed-text)
                                     |- diya_db.py -> SQLite diya.db (threads, messages, reminders)
                                     '- faster-whisper (base)
dreaming.py (run separately) reads diya.db -> dream_pending.jsonl
```

`diya_config.py` reads all settings from `DIYA_*` environment variables (blank means unset), for
example `DIYA_MODEL`, `DIYA_OLLAMA_URL`, `DIYA_DB_PATH`, `DIYA_NOTES_DIR` and `DIYA_PORT`.
`sample_notes/` holds fictional demo notes, embedded into an in-memory Chroma index at each start.
`milestone*.py` and `archive/phase1-learning-roadmap.md` record Phase 1; `ROADMAP.md` is the current
Stage 0 checklist; `diya_chat.py` is an early tool-less chat; `PRODUCT_VISION.md` is a dated log,
partly superseded by the code. `diya.db`, `user_profile.txt`, `dream_*`, `watcher_*` and `*.pem` are gitignored.

## Setup

Needs Python 3.10+ (run on 3.13), Node 18.18+ (run on 24), [Ollama](https://ollama.com) and
[mkcert](https://github.com/FiloSottile/mkcert). There is no lock file yet; last run against
fastapi 0.141, uvicorn 0.34, openai 1.84 and chromadb 1.5.

```bash
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
pip install fastapi uvicorn python-multipart openai chromadb httpx ddgs faster-whisper pytest
```

**Certificates.** Browsers allow the microphone only on secure origins. In the repo root:

```bash
mkcert -install
mkcert localhost 127.0.0.1 ::1     # writes localhost+2.pem and localhost+2-key.pem
```

Keep exactly one such pair in the repo root. The backend and `npm run dev` both find it, or use
`DIYA_SSL_CERT` and `DIYA_SSL_KEY` (relative paths are read from the repo root).

**Run it** (Ollama must be running):

```bash
python diya_web.py                          # repo root; the first run downloads Whisper "base"
cd frontend && npm install && npm run dev   # second terminal
```

Open <https://localhost:3000>. The UI calls `https://<page hostname>:8080`; that port is fixed in
`frontend/lib/api.js`. The API does not hot-reload. For a terminal chat: `python diya.py new`.

**iPhone or another device.** The API is loopback-only by default. To reach it from another device:

1. Add the name or IPv4 address the device will use to the certificate
   (`mkcert localhost 127.0.0.1 ::1 <name-or-ip>`) and remove the old pair.
2. Install and trust mkcert's root CA on the device (`mkcert -CAROOT` shows where it is; on iOS,
   Settings > General > About > Certificate Trust Settings).
3. Start the API in LAN mode with that same name or address. PowerShell:
   `$env:DIYA_LAN = "1"; $env:DIYA_ALLOWED_HOSTS = "<name-or-ip>"; python diya_web.py`
4. Start the UI with `npm run dev:lan`, open `https://<name-or-ip>:3000` on the device, and allow
   inbound TCP 8080 and 3000 in the firewall.

LAN mode listens on all interfaces but answers only loopback and the names in `DIYA_ALLOWED_HOSTS`
(plain names or IPv4 addresses, no port or wildcard), and accepts browser origins
`https://<allowed name>:<DIYA_FRONTEND_PORT>` (default 3000). The server refuses to start with a
non-loopback `DIYA_HOST` and no `DIYA_LAN=1`, or with `DIYA_LAN=1` and no allowed hosts.
`npm run dev` listens on 127.0.0.1 only; `dev:lan` listens on all interfaces.

**Dreaming.** `python dreaming.py` runs one pass and logs to `dream_log.txt`; run it on a schedule
(the author uses Windows Task Scheduler, every 30 minutes). `DIYA_DREAM_PROFILE_MODE` is `staged` or `direct`.

## Tests and evals

```bash
python -m pytest        # 363 tests, about 2 minutes, from the repo root
python diya_evals.py    # needs Ollama and both models; exits 1 if any case fails
```

The tests use a fake model client, temporary directories and a cleared `DIYA_*` environment
(`tests/conftest.py`), so they cannot reach `diya.db`. The evals send nine prompts to the real model
and check tool routing and answer content, on a temporary database and fixture notes; they refuse to
run against the live `diya.db`. The weather case calls Open-Meteo. Results vary between runs on a 3B
model: the arithmetic case fails in roughly 40-50% of them.

## Roadmap

Stage 0, safety and reproducibility:

- [x] Lazy initialisation, `DIYA_*` configuration, app factory
- [x] Tests and evals cannot touch the live database
- [x] Line endings and text encoding pinned (`.gitattributes`, UTF-8; a test enforces it)
- [x] Network boundary: loopback by default, Host and Origin allowlists, no wildcard CORS
- [ ] Per-install auth token (stored hashed) behind a Next.js proxy, so the browser holds no secret
- [ ] Request body-size limits
- [ ] Restrict `list_files` to allowed folders
- [ ] `pyproject.toml`, locked dependencies, and models pinned by digest (tags only today)
- [ ] Database migrations (the schema is `CREATE TABLE IF NOT EXISTS`)
- [ ] CI (no `.github/` yet)
- [ ] Stale docs: this README is current; `PRODUCT_VISION.md` is not

Later stages: (1) hardware and model benchmark; (2) trustworthy memory, including the
review-and-promote step for staged facts; (3) connectors and permissions; (4) durable workflows;
(5) "Jev" decision benchmark; (6) daily-driver experience.

## Credits

The composer is ported from the MIT-licensed [Libraries.dev](https://github.com/Jakubantalik/Libraries.dev)
by Jakub Antalik ([notices](THIRD_PARTY_NOTICES.md)). The project is modeled on
`Truffle_Research_Dossier.pdf`. There is no license of its own yet.
