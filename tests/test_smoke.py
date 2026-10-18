"""scripts/smoke.py (docs/SMOKE_TEST.md; task DIYA-008).

What this proves: Diya builds on an empty folder with no model, token or network and answers every critical route and one chat round trip; the access token is still required when it is on; the live mode
only talks to this computer, only reads, and reports a route that fails by name. It does not prove a fresh machine has Ollama, the models, Node and a certificate: `python diya_run.py --check` does that.
"""
import http.server
import io
import json
import sys
import threading
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import smoke  # noqa: E402


def test_a_fresh_diya_passes_every_check_with_nothing_outside_it():
    out = io.StringIO()
    assert smoke.main([], out=out) == 0
    text = out.getvalue()
    assert "FAIL" not in text and "23 of 23 checks passed." in text
    for path in smoke.CRITICAL_GETS:
        assert f"GET {path}" in text


def test_the_token_check_is_in_the_run():
    assert "the access token is required when it is switched on" in "\n".join(name for name, ok, detail in smoke.run_in_process())


def test_live_mode_refuses_an_address_that_is_not_this_computer():
    for url in ("https://example.com", "http://192.168.1.5:8080", "https://evil.test/", "localhost:8080"):
        with pytest.raises(SystemExit):
            smoke.run_live(url, "t")


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []
    broken = "/api/tasks"

    def do_GET(self):  # noqa: N802
        Handler.seen.append((self.command, self.path, self.headers.get("Authorization")))
        if self.path == Handler.broken:
            self.send_response(500)
            self.end_headers()
            return
        body = json.dumps({"items": [{"state": "ok"}]} if self.path == "/api/health" else {}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_live_mode_only_reads_sends_the_token_and_names_the_route_that_failed():
    Handler.seen = []
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        out = io.StringIO()
        code = smoke.main(["--live", f"http://127.0.0.1:{server.server_port}", "--token", "secret"], out=out)
    finally:
        server.shutdown()
    text = out.getvalue()
    assert code == 1 and "FAIL GET /api/tasks (status 500)" in text and text.count("FAIL") == 1
    assert "ok   GET /api/memory" in text
    assert {method for method, _, _ in Handler.seen} == {"GET"}  # it reads and nothing else
    assert all(auth == "Bearer secret" for _, _, auth in Handler.seen)
    assert len(Handler.seen) == len(smoke.CRITICAL_GETS)


def test_live_mode_reports_a_diya_that_is_not_running():
    out = io.StringIO()
    code = smoke.main(["--live", "http://127.0.0.1:9", "--token", "x"], out=out)
    assert code == 1 and out.getvalue().count("FAIL") == len(smoke.CRITICAL_GETS)
