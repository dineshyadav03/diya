# Diya

Diya is a local-first personal AI assistant: the model and your memory stay on your machine, and facts it learns about you are staged for review before they are trusted.

<!-- Screenshot or demo GIF goes here, e.g. docs/demo.gif -->

## Quickstart

Needs Python 3.10+, Node 18.18+, [Ollama](https://ollama.com) and [mkcert](https://github.com/FiloSottile/mkcert).
Setup note: Diya has only been run on Windows; other systems are untested. Run them from the repo root (the last three in a second terminal):

```bash
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
pip install .                              # every version pinned in pyproject.toml
mkcert -install                            # once per machine
mkcert localhost 127.0.0.1 ::1             # writes localhost+2.pem and localhost+2-key.pem here
python diya_web.py                         # Ollama must be running; first run downloads Whisper
cd frontend                                # second terminal: the server above keeps running
npm install
npm run dev                                # then open https://localhost:3000
```

`pyproject.toml` pins every direct dependency to an exact version; transitive versions are not
locked. Settings are `DIYA_*` environment variables (see `diya_config.py`). For a terminal chat
instead of the UI: `python diya.py new`.

## Works today

- Chat with six tools (notes search, web search, weather, reminders, file listing); threads are saved.
- Hold-to-talk voice input through local Whisper, and optional spoken replies.
- A plain fact ("my flight is Friday at 6") gets a one-line reply, not an essay.
- Facts it extracts wait in a review queue; nothing enters your profile automatically.
- The API listens on localhost only, checks Host and Origin, and rejects an over-size body (413); 409 tests pass (as of 2026-09-22).

## Known limits

- Staged facts are not reviewed or promoted yet, so they never reach the model.
- There is no login: any local process can call the API, and `list_files` can list any folder.
- Models are pulled by tag, not pinned; there is no CI, and the 3B model sometimes calls tools it should not.

## Docs

- [LAN mode and certificates](docs/lan.md): use Diya from a phone, and the mkcert details.
- [Dreaming](docs/dreaming.md): how staged memory works, and how to run and schedule it.
- [Roadmap](ROADMAP.md): the Stage 0 checklist and later stages. [Product vision](PRODUCT_VISION.md): the current state.
- [Research](RESEARCH.md): a dated index of market and technical signals.

## Architecture

```
browser (Next.js, :3000, HTTPS) -> FastAPI diya_web.py (:8080, HTTPS)
                                     |- diya.py Agent (tool loop) -> Ollama :11434 (qwen2.5:3b, nomic-embed-text)
                                     |- diya_db.py -> SQLite diya.db (threads, messages, reminders)
                                     '- faster-whisper (base)
dreaming.py (run separately) reads diya.db -> dream_pending.jsonl
```

`sample_notes/` holds fictional demo notes, embedded into an in-memory Chroma index at each start.
`milestone*.py` and `archive/` record the first, learning phase. Personal data (`diya.db`,
`user_profile.txt`, `dream_*`, `watcher_*`, `*.pem`) is gitignored.

## Tests and evals

```bash
pip install ".[dev]" && python -m pytest  # about 2 minutes, from the repo root
python diya_evals.py                      # needs Ollama and both models; exits 1 if any case fails
```

The tests use a fake model client, temporary directories and a cleared `DIYA_*` environment, so they
cannot reach `diya.db`. The evals send nine prompts to the real model, on a temporary database; one
calls Open-Meteo. Results vary between runs on a 3B model.

## License and credits

All rights reserved: the code is published to read, and no license to use, copy, modify or distribute
it is granted. Third-party parts keep their own licenses (the composer is ported from the MIT-licensed
[Libraries.dev](https://github.com/Jakubantalik/Libraries.dev); see [notices](THIRD_PARTY_NOTICES.md)).
The project is modeled on a research dossier: `render_pdf.py` is its source; the PDF is generated from it.
