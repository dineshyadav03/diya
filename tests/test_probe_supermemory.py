"""scripts/probe_supermemory.py (docs/SUPERMEMORY_LOCAL_TRIAL.md), added 2026-10-20.

What this proves, against a stand-in server that behaves as supermemory's published API pages say (a document goes in with POST /ns/{namespace}/document, a search comes back from POST /ns/{namespace}/search
as results that each hold a `memory` or a `chunk`): the probe sends only the invented messages and questions of tests/labelled_episodic.py and nothing else, sends the key only in the Authorization header, waits
for the index, counts the right answers in the top 1, 3 and 5 in both modes and the unrelated questions that still got results, tidies up after itself, and says plainly what failed when the server answers an
error, something that is not JSON or nothing at all. It also refuses any address that is not this computer. It has never been run against the real server.
"""
import io
import json
import threading
import http.server
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import probe_supermemory as probe  # noqa: E402

import diya_checks  # noqa: E402
import labelled_episodic as L  # noqa: E402

KEY = "sm-secret-key-12345"


class Fake(http.server.BaseHTTPRequestHandler):
    docs = {}
    seen = []
    mode = "ok"

    def _read(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _send(self, code, body):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        body = self._read()
        Fake.seen.append((self.command, self.path, body, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._send(401, {"error": "no"})
        if Fake.mode == "error":
            return self._send(500, {"error": "boom"})
        if Fake.mode == "html":
            return self._send(200, b"<html>not json</html>")
        if self.path.endswith("/document"):
            Fake.docs[body["id"]] = body["content"]
            return self._send(200, {"id": body["id"], "status": "queued"})
        if self.path.endswith("/search"):
            wanted = diya_checks.content_words(body["query"])
            scored = sorted(((len(wanted & diya_checks.content_words(text)), text) for text in Fake.docs.values()), key=lambda r: -r[0])
            hits = [text for score, text in scored if score >= 2][: body.get("limit", 10)]
            key = "chunk" if body.get("searchMode") == "hybrid" else "memory"
            return self._send(200, {"results": [{key: text, "similarity": 0.8} for text in hits], "searchTime": 5})
        return self._send(404, {})

    def do_DELETE(self):  # noqa: N802
        Fake.seen.append((self.command, self.path, None, self.headers.get("Authorization")))
        Fake.docs.pop(self.path.rsplit("/", 1)[-1], None)
        return self._send(200, {})

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    Fake.docs, Fake.seen, Fake.mode = {}, [], "ok"
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_it_sends_only_the_invented_messages_and_questions_and_reports_what_it_found(server):
    lines = []
    report = probe.run(server, KEY, out=lines.append, wait=5, poll=0, sleep=lambda s: None)
    sent_documents = [body["content"] for method, path, body, _ in Fake.seen if path.endswith("/document")]
    asked = [body["query"] for method, path, body, _ in Fake.seen if path.endswith("/search")]
    assert sent_documents == L.MESSAGES
    assert set(asked) <= set(L.MESSAGES[-1:]) | {q for q, _ in L.ASKED} | set(L.UNRELATED)  # (and the one canary: the last message)
    assert report["hybrid"]["asked"] == 20 and report["hybrid"]["top5"] >= report["hybrid"]["top3"] >= report["hybrid"]["top1"] > 10
    assert report["memories"]["unrelated"] == 10 and report["hybrid"]["search_ms_median"] >= 0
    text = "\n".join(lines)
    assert "hybrid" in text and "memories" in text and "namespace diya-probe-" in text and KEY not in text


def test_the_key_goes_only_in_the_authorization_header(server):
    probe.run(server, KEY, out=lambda line: None, wait=5, poll=0, sleep=lambda s: None)
    assert all(auth == f"Bearer {KEY}" for _, _, _, auth in Fake.seen)
    assert all(KEY not in json.dumps(body) for _, _, body, _ in Fake.seen)


def test_it_removes_what_it_added_and_says_so(server):
    lines = []
    probe.run(server, KEY, out=lines.append, wait=5, poll=0, sleep=lambda s: None)
    assert Fake.docs == {} and any(f"removed {len(L.MESSAGES)}/{len(L.MESSAGES)}" in line for line in lines)
    assert sum(1 for method, *_ in Fake.seen if method == "DELETE") == len(L.MESSAGES)


@pytest.mark.parametrize("url", ["https://example.com", "http://192.168.1.4:6767", "http://evil.test", "127.0.0.1:6767", ""])
def test_it_talks_only_to_this_computer(url):
    with pytest.raises(SystemExit):
        probe.run(url, KEY, out=lambda line: None)


def test_a_server_that_answers_an_error_or_not_json_is_reported_by_what_it_said(server):
    Fake.mode = "error"
    with pytest.raises(probe.ProbeError) as caught:
        probe.run(server, KEY, out=lambda line: None, wait=1, poll=0, sleep=lambda s: None)
    assert "answered 500" in str(caught.value) and "boom" in str(caught.value)
    Fake.mode = "html"
    with pytest.raises(probe.ProbeError) as caught:
        probe.run(server, KEY, out=lambda line: None, wait=1, poll=0, sleep=lambda s: None)
    assert "not JSON" in str(caught.value)


def test_a_server_that_is_not_there_is_reported_not_guessed_at():
    with pytest.raises(probe.ProbeError) as caught:
        probe.call("http://127.0.0.1:9", KEY, "GET", "/v3/health", timeout=2)
    assert "could not be reached" in str(caught.value)


def test_the_wrong_key_is_refused_by_the_server_and_said(server):
    with pytest.raises(probe.ProbeError) as caught:
        probe.run(server, "wrong-key", out=lambda line: None, wait=1, poll=0, sleep=lambda s: None)
    assert "401" in str(caught.value)


def test_the_command_line_needs_a_key_and_never_echoes_it(capsys, monkeypatch):
    monkeypatch.delenv("SUPERMEMORY_API_KEY", raising=False)
    assert probe.main([]) == 2
    assert "key" in capsys.readouterr().err


def test_every_question_has_the_words_that_show_it_was_answered():
    assert len(probe.ANSWER) == len(L.ASKED)
    for (question, index), words in zip(L.ASKED, probe.ANSWER):
        message = L.MESSAGES[index if isinstance(index, int) else index[0]]
        assert any(w in message.lower() for w in words), (question, words)
