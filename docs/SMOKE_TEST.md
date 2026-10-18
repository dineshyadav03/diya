# Starting Diya from a fresh clone, and the smoke test (2026-10-18, task DIYA-008)

## From a fresh clone (Windows)
1. Install Python 3.10+, Node 18.18+, [Ollama](https://ollama.com) and [mkcert](https://github.com/FiloSottile/mkcert).
2. `git clone https://github.com/dineshyadav03/diya` and `cd diya`.
3. `ollama pull qwen2.5:3b` and `ollama pull nomic-embed-text`.
4. `pip install .` (every version is pinned in `pyproject.toml`; a test checks the lock file).
5. `mkcert -install`, then `mkcert localhost 127.0.0.1 ::1` in the repository root.
6. **`python scripts/smoke.py`**: builds Diya on a temporary empty folder with a scripted stand-in for the model and checks the critical routes. It needs no Ollama and touches none of your data. If this fails on a fresh clone,
   something tracked is missing; nothing about your machine is to blame.
7. **`python diya_run.py --check`**: checks your machine (Ollama running, both models pulled, the certificate, Node) and starts nothing.
8. `python diya_run.py` starts the API and the UI. It prints the access token once; keep it (only a hash is stored).
9. **`python scripts/smoke.py --live https://127.0.0.1:8080 --token <the token>`**: asks the running Diya the same read-only questions. It writes nothing and refuses an address that is not this computer.

The full setup, with the second terminal and the environment variables, is the README's Quickstart.

## What the smoke test checks (23 checks)
Every migration applied on an empty database; the 19 read-only routes the pages depend on answer 200 (health, chat history, memory, questions, reminders, scheduled, tasks, today, automations, actions, connections,
permissions, journal, Dreaming receipts, categories, knowledge, proactive, push status); a chat message gets an answer and is kept in the history; and with the access token switched on, a call without it is refused.

## What it does not check
That the model is good, that Ollama is installed, that the UI builds (CI runs `npx next build`), or anything about Google, a phone or a microphone. It is the first thing to run after a clone or an update and the last
thing to run before saying "it starts".

## Evidence
`tests/test_smoke.py` runs the script inside the suite (including a live-mode run against a small local server that records what was asked: only GET, always with the token, 19 requests). The fresh-clone run, from a
clone of the committed code in a temporary folder, is recorded in `docs/tracker/progress.csv` under DIYA-008 with the date.
