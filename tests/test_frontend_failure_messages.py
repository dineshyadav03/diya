"""What the UI says when a call to the API doesn't work (frontend/lib/api-failure.mjs), in the three
places it says anything: a chat message that wasn't sent, the History page's list that couldn't be
loaded, and a recording that couldn't be transcribed.

The browser only hears from the UI's own server, so the HTTP status tells the story: a 401 is the
API refusing the access token the UI sends (missing or wrong), which is nothing like "Diya's server
didn't answer" -- the one message each place used to show for every failure, and which sent someone
with a missing token looking for a server that was running fine. The mapping is a pure function,
tested under Node; how each page uses it is checked from its source and, in a real browser, by the
design rig's chat-send-failed-*, history-* and chat-transcribe-* scenarios (frontend/tools/design-rig).
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MODULE = FRONTEND / "lib" / "api-failure.mjs"
CHAT = FRONTEND / "app" / "page.js"
HISTORY = FRONTEND / "app" / "history" / "page.js"
VOICE = FRONTEND / "components" / "VoiceBar.jsx"
RIG = FRONTEND / "tools" / "design-rig" / "shots.mjs"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

REFUSED = "the access token the UI sends is missing or wrong (see docs/lan.md, Access token)"
SEND_UNANSWERED = "Didn’t send. Diya’s server didn’t answer."
LOAD_UNANSWERED = "Diya’s server didn’t answer. Check that it’s running, then try again."
MIC_UNANSWERED = "Couldn't reach Diya's server to transcribe that. Hold the mic to try again."

CODE = (
    "import { pathToFileURL } from 'node:url'\n"
    "const m = await import(pathToFileURL(process.argv[1]).href)\n"
    "const statuses = JSON.parse(process.argv[3]).map((s) => (s === null ? undefined : s))\n"
    "process.stdout.write(JSON.stringify(statuses.map((s) => m[process.argv[2]](s))))\n"
)


def describe(function, *statuses):
    """m.<function>(status) for each status; None means "no status" (the request got no answer)."""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", CODE, str(MODULE), function, json.dumps(list(statuses))],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


FUNCTIONS = ["describeSendFailure", "describeLoadFailure", "describeTranscribeFailure"]
UNANSWERED = {"describeSendFailure": SEND_UNANSWERED, "describeLoadFailure": LOAD_UNANSWERED, "describeTranscribeFailure": MIC_UNANSWERED}


# --- the mapping, for every place it is used ------------------------------------------------------

@needs_node
@pytest.mark.parametrize("function", FUNCTIONS)
def test_a_401_says_the_access_token_is_the_problem_and_not_that_the_server_did_not_answer(function):
    (text,) = describe(function, 401)
    assert "refused" in text and REFUSED in text
    assert "didn’t answer" not in text and "Couldn't reach" not in text


@needs_node
@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize("status", [None, 502, 503, 504])
def test_no_answer_at_all_is_each_places_original_message_unchanged(function, status):
    assert describe(function, status) == [UNANSWERED[function]]


@needs_node
@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize("status", [400, 403, 404, 413, 422, 429, 500, 501])
def test_any_other_error_is_reported_as_an_error_with_its_number(function, status):
    (text,) = describe(function, status)
    assert f"HTTP {status}" in text and "error" in text
    assert "didn’t answer" not in text and "Couldn't reach" not in text and "access token" not in text


@needs_node
@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize("status", [200, 201, 204])
def test_a_success_status_whose_reply_could_not_be_used_says_so(function, status):
    (text,) = describe(function, status)
    assert "read" in text and "HTTP" not in text and "didn’t answer" not in text and "Couldn't reach" not in text


@needs_node
@pytest.mark.parametrize("function", FUNCTIONS)
def test_the_three_kinds_of_failure_read_differently(function):
    unauthorized, unreachable, error = describe(function, 401, None, 500)
    assert len({unauthorized, unreachable, error}) == 3


@needs_node
def test_all_three_places_agree_on_what_each_status_means():
    """One classification, three wordings: a status must never be 'the token' in one place and 'no
    answer' in another."""
    statuses = [None, 200, 204, 400, 401, 403, 404, 500, 502, 503, 504]
    send, load, mic = (describe(f, *statuses) for f in FUNCTIONS)
    for status, s, l, m in zip(statuses, send, load, mic):
        assert ("access token" in s) == ("access token" in l) == ("access token" in m), status
        assert ("didn’t answer" in s) == ("didn’t answer" in l) == ("Couldn't reach" in m), status
        assert (f"HTTP {status}" in s) == (f"HTTP {status}" in l) == (f"HTTP {status}" in m), status


@needs_node
def test_a_status_that_is_not_an_integer_is_no_answer_not_a_401_or_an_error():
    code = (
        "import { pathToFileURL } from 'node:url'\n"
        "const m = await import(pathToFileURL(process.argv[1]).href)\n"
        "const odd = ['401', NaN, null, {}, true, 401.5, Infinity]\n"
        "process.stdout.write(JSON.stringify(Object.fromEntries(['describeSendFailure', 'describeLoadFailure', 'describeTranscribeFailure'].map((f) => [f, odd.map((s) => m[f](s))]))))\n"
    )
    result = subprocess.run(["node", "--input-type=module", "-e", code, str(MODULE)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    for function, texts in json.loads(result.stdout).items():
        assert texts == [UNANSWERED[function]] * 7, function


# --- wording rules ----------------------------------------------------------------------------------

@needs_node
def test_every_chat_message_starts_with_the_words_the_design_rig_and_the_person_look_for():
    for text in describe("describeSendFailure", None, 200, 401, 404, 500, 502, 503, 504):
        assert text.startswith("Didn’t send.")


@needs_node
def test_every_microphone_message_reads_like_the_other_microphone_messages():
    for text in describe("describeTranscribeFailure", None, 200, 401, 404, 500, 502, 503, 504):
        assert text.startswith("Couldn't") and text.endswith("Hold the mic to try again.")
        assert "’" not in text  # straight apostrophes, like "Didn't catch that" beside it


@needs_node
def test_the_history_sentence_does_not_repeat_the_headline_it_sits_under():
    for text in describe("describeLoadFailure", None, 200, 401, 404, 500, 502):
        assert not text.startswith("Couldn’t load") and not text.startswith("Didn’t send")


def test_no_message_names_a_secret_or_an_address():
    """This is browser code; the 401 message points at the docs rather than spelling out a setting."""
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("DIYA_TOKEN", "Bearer", "Authorization", "8080", "127.0.0.1", "NEXT_PUBLIC"):
        assert forbidden not in source, forbidden


# --- each page uses it, for the failure it actually saw ---------------------------------------------

def test_the_chat_page_reports_the_status_the_request_actually_got():
    source = CHAT.read_text(encoding="utf-8")
    assert re.search(r"import \{[^}]*\bdescribeSendFailure\b[^}]*\} from '\.\./lib/api-failure\.mjs'", source)
    fetch_at = source.index("fetch('/api/chat'")
    assert fetch_at < source.index("status = res.status") < source.index("if (!res.ok) throw")  # noted before the check
    assert "setFailed(id, describeSendFailure(status))" in source
    assert "let status" in source and source.index("let status") < fetch_at  # visible to the catch below it
    assert "<span>{m.failed}</span>" in source
    assert "setFailed(id, true)" not in source  # a bare `true` would render nothing


def test_a_retry_clears_the_stored_reason():
    source = CHAT.read_text(encoding="utf-8")
    retry = source[source.index("function retrySend"):]
    assert "setFailed(id, false)" in retry.split("}")[0]


def test_the_history_page_says_why_the_list_could_not_be_loaded():
    source = HISTORY.read_text(encoding="utf-8")
    assert re.search(r"import \{ describeLoadFailure \} from '\.\./\.\./lib/api-failure\.mjs'", source)
    assert "setProblem(describeLoadFailure(status))" in source
    assert "if (!r.ok) return couldNotLoad(r.status)" in source  # the status of a refused request is passed on
    assert ".catch(() => couldNotLoad())" in source  # no answer at all
    assert "couldNotLoad(r.status)" in source.split("Array.isArray")[1]  # a reply that isn't a list is 'unreadable', not a crash
    assert "<p>{problem}</p>" in source
    # the list is only ever marked "couldn't load" together with its reason
    assert source.count("setThreads(false)") == 1 and source.index("setThreads(false)") > source.index("setProblem(")


def test_the_microphone_says_why_a_recording_could_not_be_transcribed():
    source = VOICE.read_text(encoding="utf-8")
    assert re.search(r"import \{ describeTranscribeFailure \} from '\.\./lib/api-failure\.mjs'", source)
    fetch_at = source.index("fetch('/api/transcribe'")
    assert fetch_at < source.index("status = res.status") < source.index("if (!res.ok) throw")
    assert "onSystemMessage(describeTranscribeFailure(status))" in source
    assert "let status" in source and source.index("let status") < fetch_at
    assert "setMicDisabled(false)" in source[source.index("catch {"):source.index("return\n    }")]  # never stuck on "Transcribing..."


def loading_a_saved_chat():
    """The source of the chat page's loadThread(), which fetches a saved chat's messages."""
    source = CHAT.read_text(encoding="utf-8")
    start = source.index("function loadThread")
    return source[start:source.index("\n  }\n", start)]


def test_the_chat_page_says_why_a_saved_chat_could_not_be_opened():
    source = CHAT.read_text(encoding="utf-8")
    assert re.search(r"import \{ describeLoadFailure, describeSendFailure \} from '\.\./lib/api-failure\.mjs'", source)
    load = loading_a_saved_chat()
    fetch_at = load.index("fetch(`/api/history/${threadId}`)")
    assert load.index("let status") < fetch_at < load.index("status = r.status") < load.index("if (!r.ok) throw")
    assert ".catch(() => setLoadProblem(describeLoadFailure(status)))" in load
    assert "Array.isArray(data.messages)" in load  # a reply that isn't a message list is 'unreadable', not a crash
    assert load.index(".catch(") < load.index(".finally(() => setReady(true))")  # the page is shown either way
    assert ".catch(() => {})" not in source  # nothing on this page swallows a failure silently any more


def test_opening_a_saved_chat_starts_by_clearing_any_earlier_problem_and_is_used_on_mount_and_retry():
    source = CHAT.read_text(encoding="utf-8")
    load = loading_a_saved_chat()
    assert load.index("setLoadProblem('')") < load.index("fetch(")
    assert "if (threadId) loadThread(threadId)" in source  # the mount effect
    assert "onClick={() => loadThread(threadIdRef.current)}" in source  # "Try again" loads the same chat again


def test_a_chat_that_would_not_open_is_shown_instead_of_the_empty_chat_with_a_way_out():
    source = CHAT.read_text(encoding="utf-8")
    shown = source[source.index("(loadProblem ? ("):source.index("Ask Diya anything")]
    assert 'role="alert"' in shown and "<p>{loadProblem}</p>" in shown and "Try again" in shown
    assert "Couldn&rsquo;t load this chat" in shown
    # starting a new chat is the way out of one that will never open, and must clear the error
    new_chat = source[source.index("function handleNewChat"):]
    assert "setLoadProblem('')" in new_chat.split("\n  }\n")[0]


def test_the_design_rig_covers_opening_a_saved_chat_that_fails_and_what_can_be_done_about_it():
    rig = RIG.read_text(encoding="utf-8")
    for scenario in ("chat-resume-failed", "chat-resume-unauthorized", "chat-resume-server-error", "chat-resume-retry",
                     "chat-resume-retry-still-failing", "chat-resume-failed-new-chat"):
        assert f"name: '{scenario}'" in rig, scenario
    assert "window.__historyMode" in rig and "hm === '401'" in rig and "hm === 'down'" in rig
    assert "RESUME_FAIL_CHECKS" in rig


def test_no_page_or_component_keeps_its_own_fixed_sentence_for_a_failed_call():
    """The wording lives in one place, so a fourth place that shows one must use it too."""
    for path in (CHAT, HISTORY, VOICE):
        source = path.read_text(encoding="utf-8")
        for fixed in ("didn&rsquo;t answer", "didn't answer", "didn’t answer", "Couldn't reach Diya", "Didn&rsquo;t send", "Didn't send"):
            assert fixed not in source, (path.name, fixed)


def test_the_design_rig_covers_each_kind_of_failure_in_each_place():
    rig = RIG.read_text(encoding="utf-8")
    for scenario in ("chat-send-failed-401", "history-error", "history-unauthorized", "history-server-error",
                     "chat-transcribe-failed", "chat-transcribe-unauthorized", "chat-transcribe-server-error"):
        assert f"name: '{scenario}'" in rig, scenario
    assert "mode === '401'" in rig and "sc.threads === '401'" in rig and "__txMode === '401'" in rig
    assert "/access token/i" in rig and "/HTTP 500/" in rig and "/didn.t answer/i" in rig and "/couldn.t reach diya.s server/i" in rig
