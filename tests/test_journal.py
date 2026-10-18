"""The activity journal (diya_journal, diya_journal_api, Agent._journal; docs/ACTIVITY_JOURNAL_DESIGN.md), added 2026-10-18.

What this proves: every tool the model calls and every flow code runs for the person (web search, notes pages, mail, repository study, a refused request to write mail) leaves one row saying what, when, in which chat and
for which message, unattended or not, with a digest and a short preview of the arguments (a secret-looking value hidden) and how it came out, and never the result itself; a call to a tool that does not exist
is a refusal on the record; the database itself refuses to change or delete a row; a journal that cannot be written never breaks an answer; and the route shows the newest first, read-only, behind the token.
"""
import dataclasses
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_journal as journal
import diya_web
from diya_db import Store
from fakes import FakeClient, text_reply, tool_reply

LOCAL = "https://localhost"


class Quiet:
    def transcribe(self, path):
        return ""


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "j.db"))


def make_agent(tmp_path, replies, **changes):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "a.db"), profile_path=str(tmp_path / "p.txt"), **dict({"lookup": False}, **changes))
    return diya.Agent(config, client=FakeClient(list(replies)))


# ---- the row ---------------------------------------------------------------------------------------------------------------------------

def test_equal_arguments_have_an_equal_digest_whatever_the_order_and_different_ones_do_not():
    assert journal.digest({"a": 1, "b": "x"}) == journal.digest({"b": "x", "a": 1}) and journal.digest({"a": 1}) != journal.digest({"a": 2})


def test_the_preview_is_one_short_line_with_secret_looking_values_hidden_and_nothing_invisible():
    shown = journal.preview({"query": "weather in Pune\n and more " + "x" * 200, "api_token": "sk-live-123456", "Password": "hunter2", "nested": {"k": 1}, "bidi": "a\u202eb"})
    assert "\n" not in shown and len(shown) <= journal.PREVIEW_CHARS + 3 and "sk-live" not in shown and "hunter2" not in shown and "\u202e" not in shown
    full = journal.preview({"api_token": "sk-live-123456", "Password": "hunter2"})
    assert full == "api_token=[hidden], Password=[hidden]"


def test_a_row_records_what_where_and_how_and_not_the_result(store):
    thread = store.create_thread()
    row_id = journal.record(store, "get_weather", {"location": "Pune"}, "ok", thread_id=thread, message_id=3, result="Pune: 31 degrees, sunny, wind 5 km/h", seconds=0.25)
    (entry,) = store.journal_recent()
    assert entry["id"] == row_id and entry["tool"] == "get_weather" and entry["kind"] == "tool" and entry["origin"] == "chat" and entry["thread_id"] == thread and entry["message_id"] == 3
    assert entry["args_preview"] == "location=Pune" and entry["args_digest"] == journal.digest({"location": "Pune"}) and entry["status"] == "ok" and entry["duration_ms"] == 250
    assert entry["result_chars"] == len("Pune: 31 degrees, sunny, wind 5 km/h") and "sunny" not in json.dumps(entry)


@pytest.mark.parametrize("status, kind, origin", [("maybe", "tool", "chat"), ("ok", "thing", "chat"), ("ok", "tool", "elsewhere")])
def test_a_row_that_says_something_that_is_not_so_is_not_written_and_nothing_is_raised(store, status, kind, origin, capsys):
    assert journal.record(store, "x", {}, status, kind=kind, origin=origin) is None and store.journal_recent() == []
    assert "[journal] could not write" in capsys.readouterr().err


def test_a_journal_that_cannot_be_written_never_raises(capsys):
    class Broken:
        def journal_add(self, **fields):
            raise OSError("disk full")

    assert journal.record(Broken(), "x", {}, "ok") is None and "disk full" in capsys.readouterr().err


# ---- append-only ---------------------------------------------------------------------------------------------------------------------------

def test_the_database_itself_refuses_to_change_or_delete_a_row(store):
    journal.record(store, "x", {"a": 1}, "ok")
    conn = store.connect()
    for sql in ("UPDATE tool_journal SET status = 'error'", "DELETE FROM tool_journal", "UPDATE tool_journal SET args_preview = 'rewritten'"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(sql)
    assert conn.execute("SELECT status, args_preview FROM tool_journal").fetchall() == [("ok", "a=1")]
    conn.close()


def test_recent_entries_come_newest_first_and_can_be_filtered_and_counted(store):
    for n, (tool, status) in enumerate([("a", "ok"), ("b", "error"), ("a", "ok"), ("c", "refused")]):
        journal.record(store, tool, {"n": n}, status)
    assert [e["tool"] for e in store.journal_recent()] == ["c", "a", "b", "a"] and [e["args_preview"] for e in store.journal_recent(tool="a")] == ["n=2", "n=0"]
    assert store.journal_counts("2000-01-01") == {"ok": 2, "error": 1, "refused": 1} and store.journal_counts("2999-01-01") == {}


# ---- the agent leaves a row for what it does ----------------------------------------------------------------------------------------------

def test_a_tool_the_model_calls_is_journalled_with_its_chat_and_message(tmp_path, monkeypatch):
    agent = make_agent(tmp_path, [tool_reply("get_weather", json.dumps({"location": "Pune"})), text_reply("It is sunny.")])
    monkeypatch.setitem(agent._functions, "get_weather", lambda location: f"{location}: 31 degrees")
    thread = agent.store.create_thread()
    agent.ask([{"role": "user", "content": "what's the weather in Pune"}], thread_id=thread, message_id=7)
    (entry,) = agent.store.journal_recent()
    assert (entry["tool"], entry["kind"], entry["origin"], entry["status"], entry["thread_id"], entry["message_id"]) == ("get_weather", "tool", "chat", "ok", thread, 7)
    assert entry["args_preview"] == "location=Pune" and entry["result_chars"] == len("Pune: 31 degrees")


def test_a_tool_that_fails_or_does_not_exist_is_on_the_record_too(tmp_path, monkeypatch):
    def boom(location):
        raise RuntimeError("the service is down")

    agent = make_agent(tmp_path, [tool_reply("get_weather", json.dumps({"location": "Pune"})), tool_reply("no_such_tool", "{}"), tool_reply("get_weather", "not json"), text_reply("Sorry.")])
    monkeypatch.setitem(agent._functions, "get_weather", boom)
    agent.ask([{"role": "user", "content": "what's the weather in Pune"}])
    by_status = [(e["tool"], e["status"]) for e in reversed(agent.store.journal_recent())]
    assert by_status == [("get_weather", "error"), ("no_such_tool", "refused"), ("get_weather", "error")]
    assert agent.store.journal_recent()[2]["note"] == "RuntimeError" and agent.store.journal_recent()[1]["note"] == "no such tool, or not offered in this run"


def test_an_unattended_run_says_so_and_a_tool_it_was_not_offered_is_refused_on_the_record(tmp_path):
    agent = make_agent(tmp_path, [tool_reply("add_reminder", json.dumps({"content": "x"})), text_reply("done")])
    agent.ask([{"role": "user", "content": "do it"}], only_tools=("get_weather",))
    (entry,) = agent.store.journal_recent()
    assert (entry["tool"], entry["status"], entry["origin"]) == ("add_reminder", "refused", "unattended")


def test_what_code_does_for_the_person_is_journalled_as_a_flow(tmp_path, monkeypatch):
    import diya_google_calendar as gcal
    import diya_google_mail as gm
    import diya_repostudy as rs

    # a repository study that cannot be read
    agent = make_agent(tmp_path, [], repo_study=True)
    agent._github_get = lambda url: (404, "")
    agent.ask([{"role": "user", "content": "study https://github.com/acme/widget"}])
    # a request to write mail, refused, and a question about mail when Gmail is not connected
    agent_mail = make_agent(tmp_path, [], mail=True)
    agent_mail.ask([{"role": "user", "content": "send an email to mum"}])
    agent_mail.ask([{"role": "user", "content": "check my inbox"}])
    rows = {(e["tool"], e["status"]): e for e in agent_mail.store.journal_recent()}
    assert ("study_repo", "error") in rows and ("mail_write_refused", "refused") in rows and ("read_mail", "error") in rows
    assert all(e["kind"] == "flow" for e in rows.values()) and "could not study" not in json.dumps(list(rows.values())[0]["args_digest"])
    assert rows[("study_repo", "error")]["args_preview"].startswith("question=study https://github.com/acme/widget")


def test_a_journal_that_cannot_be_written_does_not_break_the_answer(tmp_path, monkeypatch):
    agent = make_agent(tmp_path, [tool_reply("get_weather", json.dumps({"location": "Pune"})), text_reply("It is sunny.")])
    monkeypatch.setitem(agent._functions, "get_weather", lambda location: "31 degrees")
    monkeypatch.setattr(agent.store, "journal_add", lambda **fields: (_ for _ in ()).throw(OSError("disk full")))
    answer, tools = agent.ask([{"role": "user", "content": "weather in Pune"}])
    assert answer == "It is sunny." and tools == ["get_weather"]


# ---- the route ------------------------------------------------------------------------------------------------------------------------------

def test_the_route_lists_the_newest_first_with_how_the_last_day_went_and_cannot_change_anything(tmp_path):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "p.txt"), require_token=False)
    agent = diya.Agent(config, client=FakeClient([]))
    client = TestClient(diya_web.create_app(config, agent, Quiet()), base_url=LOCAL)
    for n, status in enumerate(("ok", "ok", "error", "refused")):
        journal.record(agent.store, f"tool_{n}", {"api_key": "sk-secret-9999", "q": "hello"}, status)
    body = client.get("/api/journal").json()
    assert [e["tool"] for e in body["entries"]] == ["tool_3", "tool_2", "tool_1", "tool_0"] and body["last_day"] == {"ok": 2, "error": 1, "refused": 1}
    assert "sk-secret" not in json.dumps(body) and body["entries"][0]["args_preview"] == "api_key=[hidden], q=hello"
    assert client.post("/api/journal", json={}).status_code == 405 and client.delete("/api/journal").status_code == 405


def test_the_route_is_empty_on_a_new_database(tmp_path):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "p.txt"), require_token=False)
    client = TestClient(diya_web.create_app(config, diya.Agent(config, client=FakeClient([])), Quiet()), base_url=LOCAL)
    assert client.get("/api/journal").json() == {"entries": [], "last_day": {"ok": 0, "error": 0, "refused": 0}}
