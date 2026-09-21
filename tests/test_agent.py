import dataclasses
import types

import pytest

import diya
import diya_config
from diya import Agent, OllamaUnavailable
from diya_db import Store
from fakes import FakeClient, text_reply, tool_reply

DEAD_OLLAMA = {"DIYA_OLLAMA_URL": "http://127.0.0.1:9/v1"}  # port 9 (discard): nothing listens


@pytest.fixture
def notes_dir(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "dentist.txt").write_text("Dentist appointment on Tuesday at 3pm.")
    (folder / "guitar.txt").write_text("Buy new guitar strings before the weekend.")
    (folder / "garden.txt").write_text("Water the garden every morning.")
    return folder


@pytest.fixture
def config(tmp_path, notes_dir):
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(tmp_path / "agent.db"),
        notes_dir=str(notes_dir),
        profile_path=str(tmp_path / "agent_profile.txt"),
    )


def make_agent(config, *replies, **client_kwargs):
    client = FakeClient(replies, **client_kwargs)
    return Agent(config, client=client), client


# --- importing and constructing are free of side effects ---------------------------

def test_importing_diya_has_no_side_effects(run_python, tmp_path):
    code = (
        "import sys, diya\n"
        "assert 'chromadb' not in sys.modules, 'chromadb was loaded at import time'\n"
        "print('ok')\n"
    )
    result = run_python(code, env=DEAD_OLLAMA)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    assert list(tmp_path.iterdir()) == []


def test_importing_diya_leaves_the_console_encoding_alone(run_python):
    code = "import sys; before = sys.stdout.encoding; import diya; print(before == sys.stdout.encoding)"
    result = run_python(code, env={**DEAD_OLLAMA, "PYTHONIOENCODING": "ascii"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_constructing_an_agent_touches_nothing(config, tmp_path):
    client = FakeClient()
    agent = Agent(config, client=client)
    assert client.chat_calls == [] and client.embed_calls == []
    assert agent._notes is None
    assert not (tmp_path / "agent.db").exists()


def test_the_model_client_is_built_on_first_use_from_config(config):
    custom = dataclasses.replace(config, ollama_url="http://example.invalid:1234/v1")
    agent = Agent(custom)
    assert agent._client is None
    assert str(agent.client.base_url).startswith("http://example.invalid:1234/v1")


def test_agent_defaults_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DIYA_DB_PATH", str(tmp_path / "from_env.db"))
    monkeypatch.setenv("DIYA_MODEL", "some-other-model")
    agent = Agent(client=FakeClient())
    assert agent.config.model == "some-other-model"
    assert agent.store.path == str(tmp_path / "from_env.db")


# --- the notes index -------------------------------------------------------------

def test_warm_up_indexes_every_note_with_the_configured_embedding_model(config):
    agent, client = make_agent(config)
    agent.warm_up()
    assert sorted(c["input"] for c in client.embed_calls) == sorted(
        [
            "Dentist appointment on Tuesday at 3pm.",
            "Buy new guitar strings before the weekend.",
            "Water the garden every morning.",
        ]
    )
    assert {c["model"] for c in client.embed_calls} == {"nomic-embed-text"}
    assert agent.notes.count() == 3


def test_the_index_is_built_once(config):
    agent, client = make_agent(config)
    agent.warm_up()
    agent.warm_up()
    agent.search_notes("guitar")
    assert len([c for c in client.embed_calls if c["input"].startswith(("Dentist", "Buy", "Water"))]) == 3


def test_search_notes_returns_the_most_relevant_note(config):
    agent, _ = make_agent(config)
    assert agent.search_notes("when is my dentist appointment") == "Dentist appointment on Tuesday at 3pm."
    assert agent.search_notes("guitar") == "Buy new guitar strings before the weekend."


def test_two_agents_in_one_process_do_not_collide(config):
    first, _ = make_agent(config)
    second, _ = make_agent(config)
    first.warm_up()
    second.warm_up()
    assert first.notes.name != second.notes.name


def test_warm_up_reports_an_unreachable_model_server(config):
    agent, _ = make_agent(config, embed_error=ConnectionError("connection refused"))
    with pytest.raises(OllamaUnavailable) as caught:
        agent.warm_up()
    assert "connection refused" in str(caught.value)
    assert "can't reach Ollama at" in str(caught.value)


def test_warm_up_or_exit_keeps_the_legacy_message_and_exit_code(config, capsys):
    agent, _ = make_agent(config, embed_error=ConnectionError("connection refused"))
    with pytest.raises(SystemExit) as caught:
        diya.warm_up_or_exit(agent)
    assert caught.value.code == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Couldn't start Diya: can't reach Ollama at ")
    assert out[1] == "Is Ollama running? Start it, then try again."


def test_warm_up_or_exit_is_quiet_when_ollama_is_up(config, capsys):
    agent, _ = make_agent(config)
    diya.warm_up_or_exit(agent)
    assert capsys.readouterr().out == ""


# --- the stateful tools ----------------------------------------------------------

def test_reminders_go_to_the_agents_own_store(config):
    agent, _ = make_agent(config)
    assert agent.list_reminders() == "No pending reminders."
    assert agent.add_reminder("call mom") == "Reminder saved: call mom"
    assert agent.add_reminder("buy strings", "Friday 5pm") == "Reminder saved: buy strings (due Friday 5pm)"
    assert agent.list_reminders() == "#1: call mom\n#2: buy strings (due Friday 5pm)"
    assert [r[1] for r in Store(config.db_path).list_reminders()] == ["call mom", "buy strings"]


def test_two_agents_with_different_databases_are_isolated(config, tmp_path):
    other = dataclasses.replace(config, db_path=str(tmp_path / "other.db"))
    a, _ = make_agent(config)
    b, _ = make_agent(other)
    a.add_reminder("only in a")
    assert b.list_reminders() == "No pending reminders."


# --- the profile -----------------------------------------------------------------

def test_with_profile_without_a_profile_returns_history_unchanged(config):
    agent, _ = make_agent(config)
    history = [{"role": "user", "content": "hi"}]
    assert agent.with_profile(history) == history


def test_with_profile_ignores_an_empty_profile(config, tmp_path):
    (tmp_path / "agent_profile.txt").write_text("  \n")
    agent, _ = make_agent(config)
    assert agent.with_profile([{"role": "user", "content": "hi"}]) == [{"role": "user", "content": "hi"}]


def test_with_profile_prepends_a_system_message_without_mutating_history(config, tmp_path):
    (tmp_path / "agent_profile.txt").write_text("Likes guitar.\n")
    agent, _ = make_agent(config)
    history = [{"role": "user", "content": "hi"}]
    result = agent.with_profile(history)
    assert result == [
        {"role": "system", "content": "What you know about the user so far:\nLikes guitar."},
        {"role": "user", "content": "hi"},
    ]
    assert history == [{"role": "user", "content": "hi"}]


# --- the tool-calling loop (behaviour carried over verbatim) ----------------------

def test_a_direct_answer_returns_with_no_tools(config):
    agent, client = make_agent(config, text_reply("Four."))
    assert agent.ask([{"role": "user", "content": "2+2?"}]) == ("Four.", [])
    assert client.chat_calls[0]["model"] == "qwen2.5:3b"
    assert client.chat_calls[0]["tools"] is diya.TOOLS


def test_a_tool_call_is_executed_and_its_result_fed_back(config, capsys):
    agent, client = make_agent(
        config,
        tool_reply("add_reminder", '{"content": "call mom"}', call_id="c1"),
        text_reply("Saved."),
    )
    messages = [{"role": "user", "content": "remind me to call mom"}]
    answer, tools = agent.ask(messages)
    assert (answer, tools) == ("Saved.", ["add_reminder"])
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "Reminder saved: call mom"}
    assert "  [tool call] add_reminder({'content': 'call mom'})" in capsys.readouterr().out
    assert [r[1] for r in agent.store.list_reminders()] == ["call mom"]


def test_a_tool_that_raises_becomes_an_error_message_for_the_model(config, capsys):
    agent, _ = make_agent(config, tool_reply("add_reminder", "{}", call_id="c1"), text_reply("Sorry."))
    messages = [{"role": "user", "content": "remind me"}]
    assert agent.ask(messages) == ("Sorry.", ["add_reminder"])
    assert messages[-1]["content"].startswith("Error: ")
    assert "  [tool error] Error: " in capsys.readouterr().out


def test_an_empty_reply_gets_one_retry_on_a_copy_of_the_messages(config):
    agent, client = make_agent(config, text_reply(""), text_reply("Hello!"))
    messages = [{"role": "user", "content": "hi"}]
    assert agent.ask(messages) == ("Hello!", [])
    assert messages == [{"role": "user", "content": "hi"}]  # nudge did not leak into history
    assert client.chat_calls[1]["messages"][-1] == {
        "role": "user",
        "content": "Please answer directly, in one short sentence.",
    }


def test_two_empty_replies_fall_back_to_the_rephrase_message(config):
    agent, _ = make_agent(config, text_reply(""), text_reply(None))
    assert agent.ask([{"role": "user", "content": "hi"}]) == (
        "I didn't get a clear answer -- try rephrasing.",
        [],
    )


def test_the_tool_loop_gives_up_after_the_round_cap(config):
    replies = [tool_reply("list_reminders", "{}", call_id=f"c{i}") for i in range(diya.MAX_TOOL_ROUNDS)]
    agent, client = make_agent(config, *replies)
    answer, tools = agent.ask([{"role": "user", "content": "loop forever"}])
    assert answer == "I couldn't finish that after several tool calls -- something's likely stuck. Try rephrasing."
    assert tools == ["list_reminders"] * diya.MAX_TOOL_ROUNDS
    assert len(client.chat_calls) == diya.MAX_TOOL_ROUNDS


def test_every_advertised_tool_has_an_implementation(config):
    agent, _ = make_agent(config)
    advertised = {t["function"]["name"] for t in diya.TOOLS}
    assert advertised == set(agent._functions)


# --- entry points -----------------------------------------------------------------

def test_running_diya_without_arguments_prints_usage_and_needs_no_ollama(run_python, tmp_path):
    result = run_python("import sys, diya; sys.argv = ['diya.py']; diya.main()", env=DEAD_OLLAMA)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Usage:")
    assert "python diya.py <thread_id|new>" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_running_diya_with_a_dead_ollama_fails_fast(run_python):
    result = run_python("import sys, diya; sys.argv = ['diya.py', 'new']; diya.main()", env=DEAD_OLLAMA)
    assert result.returncode == 1
    assert "Couldn't start Diya: can't reach Ollama at" in result.stdout
    assert "Is Ollama running? Start it, then try again." in result.stdout


def test_one_shot_mode_saves_both_sides_of_the_exchange(config, monkeypatch, capsys):
    agent, _ = make_agent(config, text_reply("Four."))
    monkeypatch.setattr(diya, "Agent", lambda: agent)
    monkeypatch.setattr("sys.argv", ["diya.py", "new", "2+2?"])
    diya.main()
    out = capsys.readouterr().out
    assert "[created thread 1]" in out and "assistant> Four." in out
    assert agent.store.get_history(1) == [
        {"role": "user", "content": "2+2?"},
        {"role": "assistant", "content": "Four."},
    ]


def test_the_chat_loop_saves_messages_and_survives_a_model_error(config, monkeypatch, capsys):
    agent, _ = make_agent(config, text_reply("Hi there."))  # second ask() runs out of replies -> IndexError
    thread = agent.store.create_thread()
    typed = iter(["hello", "", "again", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(typed))
    diya.chat_loop(agent, thread, [])
    out = capsys.readouterr().out
    assert "assistant> Hi there." in out
    assert "assistant> Couldn't reach the model (" in out
    assert agent.store.get_history(thread) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there."},
        {"role": "user", "content": "again"},
    ]


# --- get_weather: old city names and picking the right match (no network: httpx.get is faked) -------

def fake_open_meteo(monkeypatch, places):
    """Answer the geocoding call with `places` and the forecast call with fixed weather."""
    queries = []

    def fake_get(url, params=None, timeout=None):
        if "geocoding" in url:
            queries.append(params["name"])
            return types.SimpleNamespace(json=lambda: {"results": places} if places else {})
        return types.SimpleNamespace(
            json=lambda: {"current": {"temperature_2m": 30.0, "weather_code": 1, "wind_speed_10m": 5.0}}
        )

    monkeypatch.setattr(diya.httpx, "get", fake_get)
    return queries


CHENNAI = {"name": "Chennai", "admin1": "Tamil Nadu", "country": "India", "latitude": 13.1, "longitude": 80.3, "population": 7000000}


@pytest.mark.parametrize("old, current", [("Madras", "Chennai"), (" bombay ", "Mumbai"), ("CALCUTTA", "Kolkata")])
def test_get_weather_looks_up_the_current_name_of_a_renamed_city(monkeypatch, old, current):
    queries = fake_open_meteo(monkeypatch, [CHENNAI])
    diya.get_weather(old)
    assert queries == [current]  # the geocoder may only know the current name, or the wrong place


def test_get_weather_leaves_other_names_alone(monkeypatch):
    queries = fake_open_meteo(monkeypatch, [CHENNAI])
    diya.get_weather("Paris")
    assert queries == ["Paris"]


def test_get_weather_prefers_the_most_populous_match(monkeypatch):
    small = {"name": "Chennai", "admin1": "Oregon", "country": "United States", "latitude": 44.0, "longitude": -123.0, "population": 5000}
    fake_open_meteo(monkeypatch, [small, CHENNAI])
    out = diya.get_weather("Chennai")
    assert out.startswith("Chennai, Tamil Nadu, India: 30.0") and "Oregon" not in out
