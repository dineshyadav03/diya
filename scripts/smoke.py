"""A smoke test you can run on a fresh clone, or against Diya while she runs (docs/SMOKE_TEST.md; task DIYA-008).

    python scripts/smoke.py                       build Diya on an empty temporary folder with a scripted stand-in for the model,
                                                  and check the critical routes and one chat round trip. Needs no Ollama, no token,
                                                  no network, and touches none of your data.
    python scripts/smoke.py --live URL --token T  only read: ask a RUNNING Diya (for example https://127.0.0.1:8080) the same
                                                  read-only questions. Nothing is written. URL must be on this computer.

Exit code 0 when every check passed, 1 when any failed. Each line says what was checked, so a failure names the route.

The in-process mode is the one the test suite runs (tests/test_smoke.py), so a clone whose tracked files are incomplete fails here before it fails in use.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# routes that must answer 200 on an empty Diya, and again on a running one
CRITICAL_GETS = (
    "/api/health", "/api/threads", "/api/history/main", "/api/memory", "/api/questions", "/api/reminders", "/api/scheduled", "/api/tasks", "/api/today", "/api/automations",
    "/api/actions", "/api/connections", "/api/permissions", "/api/journal", "/api/dreaming", "/api/categories", "/api/knowledge", "/api/proactive", "/api/push/status",
)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


class ScriptedClient:
    """The smallest possible stand-in for the model: every chat turn is answered with the same sentence, and nothing else is ever asked."""

    def __init__(self, answer="Hello from the smoke test."):
        message = SimpleNamespace(content=answer, tool_calls=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda model, messages, tools=None, **options: self._reply(message, options)))
        self.embeddings = SimpleNamespace(create=lambda model, input: SimpleNamespace(data=[SimpleNamespace(embedding=[0.0, 1.0])]))

    @staticmethod
    def _reply(message, options):
        full = SimpleNamespace(choices=[SimpleNamespace(message=message, delta=SimpleNamespace(content=message.content, tool_calls=None), finish_reason="stop")])
        return iter([full]) if options.get("stream") else full


class Quiet:
    def transcribe(self, path):
        return ""


def _check(results, name, ok, detail=""):
    results.append((name, bool(ok), detail))


def run_in_process():
    """[(what was checked, passed, detail)] for Diya built on an empty temporary folder."""
    import diya
    import diya_config
    import diya_db
    import diya_web
    from fastapi.testclient import TestClient

    results = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        config = dataclasses.replace(
            diya_config.load_config({}), db_path=os.path.join(folder, "smoke.db"), dream_log_path=os.path.join(folder, "log"), dream_state_path=os.path.join(folder, "state.json"),
            dream_pending_path=os.path.join(folder, "pending.jsonl"), profile_path=os.path.join(folder, "profile.txt"), require_token=False, categories=False, lookup=False, auto_memory=False,
        )
        agent = diya.Agent(config, client=ScriptedClient())
        client = TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost")
        conn = agent.store.connect()
        try:
            applied = {row[0] for row in conn.execute("SELECT version FROM migrations")}
        finally:
            conn.close()  # an open file cannot be removed on Windows
        _check(results, "the database was created and every migration applied", applied == {version for version, _ in diya_db.MIGRATIONS}, f"{len(applied)} migrations")
        for path in CRITICAL_GETS:
            reply = client.get(path)
            _check(results, f"GET {path}", reply.status_code == 200, f"status {reply.status_code}")
        sent = client.post("/api/chat", json={"message": "hello"})
        _check(results, "POST /api/chat answers", sent.status_code == 200 and "smoke test" in str(sent.json().get("answer", "")), f"status {sent.status_code}")
        history = client.get("/api/history/main")
        roles = [m["role"] for m in history.json().get("messages", [])] if history.status_code == 200 else []
        _check(results, "the chat was kept: your message and the answer are in the history", roles[-2:] == ["user", "assistant"], f"roles {roles}")
        _check(results, "the access token is required when it is switched on", _token_required(folder), "")
    return results


def _token_required(folder):
    """With the token switched on, a call without it is refused (the most important thing a fresh clone must still do)."""
    import diya
    import diya_config
    import diya_web
    from fastapi.testclient import TestClient

    config = dataclasses.replace(
        diya_config.load_config({}), db_path=os.path.join(folder, "token.db"), dream_log_path=os.path.join(folder, "log2"), dream_state_path=os.path.join(folder, "state2.json"),
        dream_pending_path=os.path.join(folder, "pending2.jsonl"), profile_path=os.path.join(folder, "profile2.txt"), require_token=True, token_path=os.path.join(folder, "token.hash"),
    )
    client = TestClient(diya_web.create_app(config, diya.Agent(config, client=ScriptedClient()), Quiet()), base_url="https://localhost")
    return client.get("/api/memory").status_code in (401, 403)


def run_live(url, token):
    """The same read-only questions asked of a running Diya. Never writes."""
    host = url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0] if "://" in url else ""
    if host not in LOCAL_HOSTS:
        raise SystemExit("smoke: --live only talks to Diya on this computer (localhost, 127.0.0.1 or [::1])")
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE  # a loopback address with a local (mkcert) certificate
    results = []
    silent = False  # nothing answered at all: do not wait for the other eighteen to fail the same way
    for path in CRITICAL_GETS:
        if silent:
            _check(results, f"GET {path}", False, "skipped: nothing is answering at that address")
            continue
        request = urllib.request.Request(url.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            with urllib.request.urlopen(request, timeout=20, context=context) as reply:
                body = json.loads(reply.read().decode("utf-8") or "null")
                _check(results, f"GET {path}", reply.status == 200, f"status {reply.status}")
                if path == "/api/health" and isinstance(body, dict):
                    _check(results, "the Status page reports no bad item", not any(i.get("state") == "bad" for i in body.get("items", [])), "")
        except urllib.error.HTTPError as exc:
            _check(results, f"GET {path}", False, f"status {exc.code}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            silent = True
            _check(results, f"GET {path}", False, str(exc)[:120])
    return results


def main(argv=None, out=None):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(prog="smoke.py", description="Smoke test for Diya.")
    parser.add_argument("--live", metavar="URL", help="ask a running Diya on this computer instead (read-only)")
    parser.add_argument("--token", default=os.environ.get("DIYA_TOKEN", ""), help="the access token for --live (default: $DIYA_TOKEN)")
    args = parser.parse_args(argv)
    results = run_live(args.live, args.token) if args.live else run_in_process()
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'} {name}{'' if ok or not detail else f' ({detail})'}", file=out)
    failed = [r for r in results if not r[1]]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed.", file=out)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
