"""Day separators in the one chat (frontend/lib/day-labels.mjs, frontend/app/page.js, /api/history; docs/ONE_CHAT_DESIGN.md; task DIYA-158), added 2026-10-21.

What this proves, with Node and fixed clocks and zones: a message is put under the person's own calendar day, not the server's: a message saved at 20:30 UTC is the next morning in Mumbai and the same
evening in London; the days are called Today, Yesterday, then "Mon 19 Oct", with the year only for another year; the first message always starts a day and a message on the same day as the one before
does not; a day that spans a long reconnect (the same instant read again) is not repeated; messages with no time never split a day or start one; a time that is not a time (text, null) is ignored, never
an error; midnight is the edge (23:59 and 00:01 are two days); the clock changing inside a day does not move a message to another day; and the page uses the helper for every kind of message it draws, and
the server gives each message its time. It does not draw the page: the design rig does that (docs/UI_DESIGN.md).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "frontend" / "lib" / "day-labels.mjs"
PAGE = ROOT / "frontend" / "app" / "page.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

CODE = (
    "import { pathToFileURL } from 'node:url'\n"
    "const m = await import(pathToFileURL(process.argv[1]).href)\n"
    "const job = JSON.parse(process.argv[2])\n"
    "const now = new Date(job.now)\n"
    "const out = job.fn === 'dayBreaks' ? m.dayBreaks(job.args[0], now) : job.fn === 'dayLabel' ? m.dayLabel(job.args[0], now) : m.dayKey(job.args[0])\n"
    "process.stdout.write(JSON.stringify(out))\n"
)


def run(fn, *args, now="2026-10-21T12:00:00Z", zone="UTC"):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", CODE, str(MODULE), json.dumps({"fn": fn, "args": list(args), "now": now})],
        capture_output=True, text=True, encoding="utf-8", timeout=30, env={**__import__("os").environ, "TZ": zone},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@needs_node
def test_a_message_is_under_the_persons_own_day_not_the_servers():
    saved = "2026-10-20T20:30:00+00:00"
    assert run("dayKey", saved, zone="Asia/Kolkata") == "2026-10-21"  # 02:00 the next morning in Mumbai
    assert run("dayKey", saved, zone="Europe/London") == "2026-10-20"
    assert run("dayKey", saved, zone="UTC") == "2026-10-20"


@needs_node
@pytest.mark.parametrize("when, label", [
    ("2026-10-21T08:00:00+00:00", "Today"),
    ("2026-10-20T23:59:00+00:00", "Yesterday"),
    ("2026-10-19T09:00:00+00:00", "Mon 19 Oct"),
    ("2026-01-02T09:00:00+00:00", "Fri 2 Jan"),
    ("2025-12-31T09:00:00+00:00", "Wed 31 Dec 2025"),
    ("2024-02-29T09:00:00+00:00", "Thu 29 Feb 2024"),
])
def test_the_days_are_called_what_people_call_them(when, label):
    assert run("dayLabel", when) == label


@needs_node
def test_midnight_is_the_edge_and_a_zone_changes_which_side_of_it_a_message_is_on():
    flagged = run("dayBreaks", [{"at": "2026-10-20T23:59:00+00:00"}, {"at": "2026-10-21T00:01:00+00:00"}], zone="UTC")
    assert flagged == ["Yesterday", "Today"]
    same_day_in_mumbai = run("dayBreaks", [{"at": "2026-10-20T23:59:00+00:00"}, {"at": "2026-10-21T00:01:00+00:00"}], zone="Asia/Kolkata")
    assert same_day_in_mumbai == ["Today", None]  # 05:29 and 05:31 on the 21st there


@needs_node
def test_the_first_message_starts_a_day_and_a_day_is_not_repeated():
    messages = [
        {"at": "2026-10-19T08:00:00+00:00"}, {"at": "2026-10-19T08:00:05+00:00"}, {"at": "2026-10-19T22:00:00+00:00"},
        {"at": "2026-10-21T07:00:00+00:00"}, {"at": "2026-10-21T07:30:00+00:00"},
    ]
    assert run("dayBreaks", messages) == ["Mon 19 Oct", None, None, "Today", None]


@needs_node
def test_a_message_with_no_time_never_splits_a_day_or_starts_one():
    messages = [{"at": "2026-10-21T07:00:00+00:00"}, {}, {"at": None}, {"at": "2026-10-21T09:00:00+00:00"}, {"at": "not a time"}, None, {"at": 5}]
    assert run("dayBreaks", messages) == ["Today", None, None, None, None, None, None]
    assert run("dayBreaks", [{}, {}]) == [None, None] and run("dayBreaks", []) == []
    assert run("dayLabel", "not a time") is None and run("dayKey", None) is None


@needs_node
def test_the_clock_changing_inside_a_day_does_not_move_a_message_to_another_day():
    # Europe/London puts its clocks back at 02:00 BST on 2026-10-25 (01:00 UTC), so 01:30 happens twice that day: both are the same day, and so is 03:00
    now = "2026-10-25T12:00:00Z"
    assert run("dayBreaks", [{"at": "2026-10-24T22:30:00+00:00"}, {"at": "2026-10-25T03:00:00+00:00"}], now=now, zone="Europe/London") == ["Yesterday", "Today"]
    repeated_hour = [{"at": "2026-10-24T22:30:00+00:00"}, {"at": "2026-10-25T00:30:00+00:00"}, {"at": "2026-10-25T01:30:00+00:00"}, {"at": "2026-10-25T03:00:00+00:00"}]
    assert run("dayBreaks", repeated_hour, now=now, zone="Europe/London") == ["Yesterday", "Today", None, None]


def test_the_page_puts_a_label_before_every_kind_of_message_it_draws_and_the_server_gives_the_times():
    page = PAGE.read_text(encoding="utf-8")
    assert "from '../lib/day-labels.mjs'" in page and "dayBreaks(shownMessages)" in page
    assert page.count("return withDay(") == 5  # tools, learned, a message that failed, the person's own, and the rest
    assert "at: new Date().toISOString()" in page and "at: typeof m.at === 'string'" in page  # a message sent while the page is open has a time too
    assert 'role="separator"' in page and "className=\"day-sep\"" in page
    css = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    assert ".day-sep" in css and "var(--text-dim)" in css.split(".day-sep", 1)[1].split("\n", 1)[0] and "var(--glass-edge)" in css.split(".day-sep::before", 1)[1].split("\n", 1)[0]
    assert "#" not in css.split(".day-sep {", 1)[1].split("}", 1)[0]  # tokens only: no colour written out
    rig = (ROOT / "frontend" / "tools" / "design-rig" / "shots.mjs").read_text(encoding="utf-8")
    assert "name: 'chat-days'" in rig  # the design rig draws it in a real browser (run on 2026-10-21 in the dark theme, on a desktop and a phone width: every check passed, no contrast failure; the light theme was not run)


def test_the_history_api_gives_every_message_its_time_including_an_earlier_chat(tmp_path):
    import dataclasses

    from fastapi.testclient import TestClient

    import diya
    import diya_config
    import diya_web
    from fakes import FakeClient, text_reply
    from test_categories import FakeTranscriber, LOCAL

    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "d.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False,
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")]))
    old = agent.store.create_thread()
    agent.store.add_message(old, "user", "an earlier chat")
    main = agent.store.create_thread()
    agent.store.add_message(main, "user", "hello")
    agent.store.add_message(main, "assistant", "hi")
    web = TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL)
    for thread in ("main", str(old)):
        messages = web.get(f"/api/history/{thread}").json()["messages"]
        assert messages and all(isinstance(m.get("at"), str) and m["at"].count("-") >= 2 and "T" in m["at"] for m in messages)
