"""What the chat says when a message doesn't go through (frontend/lib/send-failure.mjs, used by
frontend/app/page.js).

The browser only hears from the UI's own server, so the HTTP status tells the story: a 401 is the
API refusing the access token the UI sends (missing or wrong), which is nothing like "Diya's server
didn't answer" -- the one message that used to cover every failure, and sent someone with a missing
token looking for a server that was running fine. The mapping is a pure function, tested under
Node; page.js's use of it is checked here from its source and in a real browser by the design rig's
chat-send-failed-* scenarios (frontend/tools/design-rig).
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "frontend" / "lib" / "send-failure.mjs"
PAGE = ROOT / "frontend" / "app" / "page.js"
RIG = ROOT / "frontend" / "tools" / "design-rig" / "shots.mjs"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

DIDNT_ANSWER = "Didn’t send. Diya’s server didn’t answer."


def describe(*statuses):
    """describeSendFailure() for each status; None means "no status" (the request got no answer)."""
    code = (
        "import { pathToFileURL } from 'node:url'\n"
        "const m = await import(pathToFileURL(process.argv[1]).href)\n"
        "const statuses = JSON.parse(process.argv[2]).map((s) => (s === null ? undefined : s))\n"
        "process.stdout.write(JSON.stringify(statuses.map((s) => m.describeSendFailure(s))))\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code, str(MODULE), json.dumps(list(statuses))],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# --- the mapping ------------------------------------------------------------------------------------

@needs_node
def test_a_401_says_the_access_token_is_the_problem_and_not_that_the_server_did_not_answer():
    (text,) = describe(401)
    assert "access token" in text and "missing or wrong" in text and "docs/lan.md" in text
    assert "didn’t answer" not in text


@needs_node
@pytest.mark.parametrize("status", [None, 502, 503, 504])
def test_no_answer_at_all_is_the_original_message_unchanged(status):
    assert describe(status) == [DIDNT_ANSWER]


@needs_node
@pytest.mark.parametrize("status", [400, 403, 404, 413, 422, 429, 500, 501])
def test_any_other_error_is_reported_as_an_error_with_its_number(status):
    (text,) = describe(status)
    assert f"HTTP {status}" in text and "error" in text
    assert "didn’t answer" not in text and "access token" not in text


@needs_node
@pytest.mark.parametrize("status", [200, 201, 204])
def test_a_success_status_whose_reply_could_not_be_used_says_so(status):
    (text,) = describe(status)
    assert "couldn’t read" in text and "didn’t answer" not in text and "HTTP" not in text


@needs_node
def test_the_three_kinds_of_failure_read_differently():
    unauthorized, unreachable, error = describe(401, None, 500)
    assert len({unauthorized, unreachable, error}) == 3


@needs_node
def test_every_message_starts_with_the_words_the_design_rig_and_the_person_look_for():
    for text in describe(None, 200, 401, 404, 500, 502, 503, 504):
        assert text.startswith("Didn’t send.")


@needs_node
def test_a_status_that_is_not_a_number_is_not_mistaken_for_a_401():
    code = (
        "import { pathToFileURL } from 'node:url'\n"
        "const m = await import(pathToFileURL(process.argv[1]).href)\n"
        "process.stdout.write(JSON.stringify(['401', NaN, null, {}, true].map((s) => m.describeSendFailure(s))))\n"
    )
    result = subprocess.run(["node", "--input-type=module", "-e", code, str(MODULE)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert json.loads(result.stdout) == [DIDNT_ANSWER] * 5


def test_no_message_names_a_secret_or_an_address():
    """This is browser code; the 401 message points at the docs rather than spelling out a setting."""
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("DIYA_TOKEN", "Bearer", "Authorization", "8080", "127.0.0.1", "NEXT_PUBLIC"):
        assert forbidden not in source, forbidden


# --- page.js uses it, for the failure it actually saw ----------------------------------------------

def test_the_chat_page_reports_the_status_the_request_actually_got():
    source = PAGE.read_text(encoding="utf-8")
    assert re.search(r"import \{ describeSendFailure \} from '\.\./lib/send-failure\.mjs'", source)
    fetch_at = source.index("fetch('/api/chat'")
    assert fetch_at < source.index("status = res.status") < source.index("if (!res.ok) throw")  # noted before the check
    assert "setFailed(id, describeSendFailure(status))" in source
    assert "let status" in source and source.index("let status") < fetch_at  # visible to the catch below it


def test_the_failure_text_shown_is_the_one_stored_on_the_message_not_a_fixed_sentence():
    source = PAGE.read_text(encoding="utf-8")
    assert "<span>{m.failed}</span>" in source
    for fixed in ("didn&rsquo;t answer", "didn't answer", "Didn&rsquo;t send", "Didn't send"):
        assert fixed not in source, fixed  # the wording lives in one place: lib/send-failure.mjs
    assert "setFailed(id, true)" not in source  # a bare `true` would render nothing


def test_a_retry_clears_the_stored_reason():
    source = PAGE.read_text(encoding="utf-8")
    retry = source[source.index("function retrySend"):]
    assert "setFailed(id, false)" in retry.split("}")[0]


def test_the_design_rig_covers_the_401_the_500_and_the_network_failure():
    rig = RIG.read_text(encoding="utf-8")
    assert "name: 'chat-send-failed-401'" in rig and "mode === '401'" in rig
    assert "/access token/i" in rig and "/HTTP 500/" in rig and "/didn.t answer/i" in rig
