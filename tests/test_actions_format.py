"""How the Actions page words things (frontend/lib/actions-format.mjs, docs/ACTIONS_DESIGN.md unit A3): the tools a
proposal came after, how long it has left, and what each status means. Pure functions, tested under Node the same way
frontend/lib/memory-groups.mjs is (tests/test_memory_groups.py): easier to prove right in isolation than by rendering
the page. Also pins that the one navigation reaches every page and counts what is waiting.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import diya_actions

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MODULE = FRONTEND / "lib" / "actions-format.mjs"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

CODE = (
    "import { pathToFileURL } from 'node:url'\n"
    "const m = await import(pathToFileURL(process.argv[1]).href)\n"
    "const [name, ...args] = JSON.parse(process.argv[2])\n"
    "process.stdout.write(JSON.stringify(m[name](...args)) ?? 'null')\n"
)


def run(name, *args):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", CODE, str(MODULE), json.dumps([name, *args])],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ---- sourceWords --------------------------------------------------------------------------------------

@needs_node
def test_no_sources_is_no_words():
    assert run("sourceWords", []) == ""
    assert run("sourceWords", None) == ""


@needs_node
def test_one_source_is_its_words():
    assert run("sourceWords", ["web_search"]) == "the web"


@needs_node
def test_two_sources_are_joined_with_and_and_three_with_commas_then_and():
    assert run("sourceWords", ["web_search", "search_notes"]) == "the web and your notes"
    assert run("sourceWords", ["web_search", "search_notes", "search_notion"]) == "the web, your notes and Notion"
    assert run("sourceWords", ["a_b", "c_d", "e_f", "g_h"]) == "a b, c d, e f and g h"


@needs_node
@pytest.mark.parametrize("name, words", [
    ("web_search", "the web"), ("get_weather", "the weather service"), ("search_notes", "your notes"),
    ("list_files", "your files"), ("search_home_assistant", "Home Assistant"), ("search_notion", "Notion"),
    ("list_todoist_tasks", "Todoist"), ("list_calendar_events", "Google Calendar"),
])
def test_every_tool_that_can_come_before_a_proposal_has_its_own_words(name, words):
    assert run("sourceWords", [name]) == words


@needs_node
def test_a_tool_the_table_does_not_know_is_shown_by_its_own_name_not_hidden():
    assert run("sourceWords", ["read_the_mail"]) == "read the mail"
    assert run("sourceWords", ["read_the_mail", "web_search"]) == "read the mail and the web"


@needs_node
def test_the_same_source_twice_is_said_once_and_so_is_one_that_has_the_same_words():
    assert run("sourceWords", ["web_search", "web_search"]) == "the web"
    assert run("sourceWords", ["web_search", "search_notes", "web_search"]) == "the web and your notes"


# ---- timeLeft ------------------------------------------------------------------------------------------

NOW = 1_790_000_000_000  # an arbitrary moment, in milliseconds


def left(seconds):
    from datetime import datetime, timezone

    expires = datetime.fromtimestamp(NOW / 1000 + seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return run("timeLeft", expires, NOW)


@needs_node
@pytest.mark.parametrize("seconds, said", [
    (24 * 3600, "expires in 24 h"), (23 * 3600 + 5 * 60, "expires in 23 h 5 min"), (3600, "expires in 1 h"),
    (3601, "expires in 1 h 1 min"), (3599, "expires in 1 h"), (3540, "expires in 59 min"), (3541, "expires in 1 h"),
    (5400, "expires in 1 h 30 min"), (61, "expires in 2 min"),
    (60, "expires in 1 min"), (1, "expires in 1 min"), (90, "expires in 2 min"), (7200, "expires in 2 h"),
])
def test_time_left_is_in_hours_and_minutes_rounded_up(seconds, said):
    assert left(seconds) == said


@needs_node
@pytest.mark.parametrize("seconds", [0, -1, -3600, -10**6])
def test_a_time_that_has_come_is_expired(seconds):
    assert left(seconds) == "expired"


@needs_node
@pytest.mark.parametrize("bad", ["", "soon", "2026-13-45T99:00:00Z", None])
def test_a_time_that_cannot_be_read_says_nothing(bad):
    assert run("timeLeft", bad, NOW) == ""


@needs_node
def test_time_left_uses_the_real_clock_when_not_given_one():
    from datetime import datetime, timedelta, timezone

    soon = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert run("timeLeft", soon) in ("expires in 30 min", "expires in 29 min")
    assert run("timeLeft", "2000-01-01T00:00:00Z") == "expired"


# ---- statusWords -----------------------------------------------------------------------------------------

@needs_node
@pytest.mark.parametrize("status, words", [
    ("pending", "Waiting for you"), ("approved", "Approved, not run yet"), ("executing", "Running"), ("succeeded", "Done"),
    ("failed", "Failed"), ("rejected", "Turned down"), ("expired", "Expired, not done"), ("unknown", "Outcome unknown"),
])
def test_every_status_has_words(status, words):
    assert run("statusWords", status) == words


@needs_node
def test_a_status_the_table_does_not_know_is_shown_as_it_is():
    assert run("statusWords", "teleported") == "teleported"


def test_there_are_words_for_exactly_the_statuses_the_store_has():
    source = MODULE.read_text(encoding="utf-8")
    for status in diya_actions.STATUSES:
        assert f"  {status}: '" in source, status


# ---- the pages -----------------------------------------------------------------------------------------------

def pages():
    return [p for p in (FRONTEND / "app").rglob("page.js") if "api" not in p.relative_to(FRONTEND / "app").parts]


def shell_links():
    source = (FRONTEND / "components" / "AppShell.jsx").read_text(encoding="utf-8")
    return re.findall(r"href: '(/[a-z]*)'", source)


def test_the_one_navigation_links_every_page_there_is_and_no_page_that_is_not():
    """Every page used to carry its own header with its own list of links, and each new page meant editing all of them. The shell
    (components/AppShell.jsx, rendered by the layout) is the only list now, so this is the check that no page is left out of it."""
    routes = {"/" if p.parent.name == "app" else "/" + p.parent.name for p in pages()}
    assert routes == {"/", "/actions", "/connections", "/history", "/memory", "/reminders", "/scheduled", "/tasks", "/today"}
    links = shell_links()
    assert sorted(links) == sorted(routes) and len(links) == len(set(links))


def test_the_layout_renders_the_shell_around_every_page_and_no_page_has_a_header_of_its_own():
    layout = (FRONTEND / "app" / "layout.js").read_text(encoding="utf-8")
    assert "import AppShell from '../components/AppShell'" in layout and "<AppShell>{children}</AppShell>" in layout
    for page in pages():
        source = page.read_text(encoding="utf-8")
        assert "<header" not in source and 'className="app"' not in source, page


def test_the_chat_names_the_two_task_tools_by_what_they_do():
    chat = (FRONTEND / "app" / "page.js").read_text(encoding="utf-8")
    assert "add_task: 'added a task'" in chat
    assert "list_tasks: 'checked your tasks'" in chat


def test_the_navigation_counts_what_is_waiting_or_unknown_and_says_nothing_when_it_cannot_tell():
    shell = (FRONTEND / "components" / "AppShell.jsx").read_text(encoding="utf-8")
    assert "counts.pending + counts.unknown" in shell
    assert "Number.isInteger(counts.pending) && Number.isInteger(counts.unknown)" in shell
    assert "setWaiting(null)" in shell and "n > 0" in shell
    assert "waiting for you" in shell
    # reminders: the same rule, for the number that have come due
    assert "Number.isInteger(body.counts.due)" in shell and "setDue(null)" in shell
