# Diya

A personal AI assistant that runs on your own machine. The model is local
([Ollama](https://ollama.com)), memory is a local SQLite database, and speech-to-text is
local ([faster-whisper](https://github.com/SYSTRAN/faster-whisper)). You talk to it by typing or
by holding a mic button, and it can call tools: search your notes, check the weather, search the
web, and keep reminders.

It is a personal, in-progress project modeled on the architecture in
`Truffle_Research_Dossier.pdf`. It is built for one person's daily use, not packaged for
general distribution. See [`PRODUCT_VISION.md`](PRODUCT_VISION.md) for what is done and what isn't.

## What it does

- **Chat**, in threads saved to SQLite, with a history page to reopen past conversations.
- **Voice in**: hold the mic button, speak, release. The audio is transcribed locally by Whisper.
- **Voice out**: replies are read aloud with the browser's speech synthesis (toggle "Speak").
- **Tools** (the model chooses when to use them): `search_notes`, `web_search`, `get_weather`,
  `add_reminder`, `list_reminders`, `list_files`. The UI shows which ones a reply used.
- **Dreaming** (`dreaming.py`): a scheduled pass that extracts new facts about you from recent
  conversations into a profile, which is fed back in as context.

## Architecture

```
browser (Next.js, :3000, HTTPS)  ──JSON──▶  FastAPI (diya_web.py, :8080, HTTPS)
                                              ├─ diya.py       tool-calling agent loop
                                              ├─ diya_db.py    SQLite threads/messages/reminders
                                              ├─ Whisper       /api/transcribe
                                              └─ Ollama        :11434  (qwen2.5:3b, nomic-embed-text)
```

| Path | What it is |
|---|---|
| `diya.py` | The agent: tool definitions, the tool-calling loop (capped at 8 rounds), notes memory |
| `diya_web.py` | FastAPI JSON API: `/api/chat`, `/api/transcribe`, `/api/threads`, `/api/history/{id}` |
| `diya_db.py` | SQLite access (threads, messages, reminders) |
| `dreaming.py` | Memory-consolidation job (writes `user_profile.txt`) |
| `frontend/` | Next.js UI (chat, history, the voice composer) |
| `milestone*.py` | Phase 1 learning scripts: local inference, tool-calling, RAG, proactivity, capstone |
| `sample_notes/` | Demo notes that `search_notes` indexes at startup |

## Running it

**Prerequisites:** Python 3.10+, Node 18.18+, [Ollama](https://ollama.com), and
[mkcert](https://github.com/FiloSottile/mkcert).

**1. Models**

```bash
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

**2. Python dependencies**

```bash
pip install fastapi uvicorn python-multipart openai chromadb httpx ddgs faster-whisper mcp
```

**3. Local HTTPS certificates.** Browsers only allow microphone access on secure origins, and a
phone on your network needs HTTPS too. Generate a cert for your machine's LAN IP:

```bash
mkcert -install
mkcert 192.168.0.174 localhost 127.0.0.1   # use your own LAN IP
```

Put the two generated `.pem` files in the repo root. The code currently expects the names
`192.168.0.174+2.pem` and `192.168.0.174+2-key.pem`. If your IP differs, update them in
`diya_web.py` (the `uvicorn.run` call) and in the `dev` script in `frontend/package.json`.
The `.pem` files are gitignored on purpose.

**4. Start the backend** (the first run downloads the Whisper `base` model, about a minute):

```bash
python diya_web.py
```

**5. Start the frontend** in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <https://localhost:3000>. The frontend finds the API at the same hostname on port 8080, so
opening it via your LAN IP from a phone works without changes. Ollama must be running, or
`diya.py` exits at startup. Note that the Python server does not hot-reload, so restart it after
editing backend code.

## The voice UI

The composer in `frontend/` is built from the [Libraries.dev](https://libraries.dev) React
libraries, each tied to a real state rather than used as decoration:

| Library | Used for |
|---|---|
| `voice-glow` | The glow along the composer while Diya is listening, thinking or speaking |
| `border-beam` | The composer's edge line, lit on the same condition as the glow |
| `thinking-orbs` | Nine orb states mapped to real moments: listening, transcribing, waiting, and one per tool used |
| `liquid-gooey` | The "+" button that splits into a "New chat" confirm, since New chat clears the view |
| `metal-fx` | A metal ring on Send, only while there is text to send |
| `img-fx` | Installed but **off by default** (`IMG_FX_ENABLED` in `frontend/app/page.js`): its WebGL loop hung the browser used for testing |

## Privacy and security

- The model, memory and transcription run locally. Two tools do use the network: `web_search`
  (DuckDuckGo) and `get_weather` (Open-Meteo). Plain chat needs none.
- Your data lives in `diya.db`, `user_profile.txt` and the dream/watcher state files. They are
  created at runtime and are **gitignored**, as are the TLS certificates.
- **The API has no authentication and allows any CORS origin.** It is meant for a trusted local
  network. Do not expose ports 8080 or 3000 to the internet.

## Status

Phase 1 (foundations) is complete; Phase 2 (building Diya for real) is ongoing and open-ended.
Known gaps are tracked in [`PRODUCT_VISION.md`](PRODUCT_VISION.md) and [`ROADMAP.md`](ROADMAP.md).

## Credits

The composer's markup, CSS and icons are ported from the MIT-licensed
[Libraries.dev](https://github.com/Jakubantalik/Libraries.dev) by Jakub Antalik. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). This repository does not yet have a license of
its own.
