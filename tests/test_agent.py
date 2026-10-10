import dataclasses
import types
from datetime import datetime

import pytest

import diya
import diya_config
import diya_connector_tools
import diya_connectors
import diya_memory
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


NOW = datetime(2026, 9, 23, 10, 15)  # a Wednesday: the agent's clock in the tests that read a time


def make_agent(config, *replies, clock=None, **client_kwargs):
    client = FakeClient(replies, **client_kwargs)
    return Agent(config, client=client, clock=clock), client


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


def test_the_notes_index_is_built_with_chromas_usage_reporting_off(config, monkeypatch):
    import chromadb

    made = []
    real = chromadb.Client
    monkeypatch.setattr(chromadb, "Client", lambda settings=None: made.append(settings) or real(settings))
    agent, _ = make_agent(config)
    agent.notes  # built on first use
    assert len(made) == 1 and made[0].anonymized_telemetry is False


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
    agent, _ = make_agent(config, clock=lambda: NOW)
    assert agent.list_reminders() == "No pending reminders."
    assert agent.add_reminder("call mom") == "Reminder saved: call mom. It has NO time, so it will not fire: tell the user that, and ask when they want it."
    assert agent.add_reminder("buy strings", "Friday 5pm") == "Reminder saved: buy strings, for Friday 25 Sep 2026, 17:00"
    assert agent.list_reminders() == "#1: call mom\n#2: buy strings (due Friday 25 Sep 2026, 17:00)"
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
    """The old profile file's lines were imported as accepted facts (test_switch.py has the details), and
    accepted facts are what the model is told, one bullet each."""
    (tmp_path / "agent_profile.txt").write_text("Likes guitar.\n")
    agent, _ = make_agent(config)
    history = [{"role": "user", "content": "hi"}]
    result = agent.with_profile(history)
    assert result == [
        {"role": "system", "content": "What you know about the user so far:\n- Likes guitar."},
        {"role": "user", "content": "hi"},
    ]
    assert history == [{"role": "user", "content": "hi"}]


def test_with_profile_groups_a_named_persons_facts_in_their_own_block(config):
    """docs/PERSON_MEMORY_DESIGN.md, M4: a fact tagged to someone other than the user gets its own
    labelled block in the same system message, not a second message and not mixed into the flat list."""
    agent, _ = make_agent(config)
    memory = diya_memory.Memory(agent.store)
    memory.add_manual("likes green tea", "cli")
    fact_id = memory.add_manual("sister Maya is visiting in May", "cli")
    memory.set_person(fact_id, "Maya", "cli")

    result = agent.with_profile([{"role": "user", "content": "hi"}])

    assert result[0] == {
        "role": "system",
        "content": "What you know about the user so far:\n- likes green tea\n\nAbout Maya:\n- sister Maya is visiting in May",
    }


# --- the tool-calling loop (behaviour carried over verbatim) ----------------------

def test_a_direct_answer_returns_with_no_tools(config):
    agent, client = make_agent(config, text_reply("Four."))
    assert agent.ask([{"role": "user", "content": "2+2?"}]) == ("Four.", [])
    assert client.chat_calls[0]["model"] == "qwen2.5:3b"
    # agent.tools is built fresh each call (docs/CONNECTORS_DESIGN.md, D4), not the same list object
    # as diya.TOOLS, but with nothing connected the content is exactly it.
    assert client.chat_calls[0]["tools"] == diya.TOOLS


def test_a_tool_call_is_executed_and_its_result_fed_back(config, capsys):
    agent, client = make_agent(
        config,
        tool_reply("add_reminder", '{"content": "call mom"}', call_id="c1"),
        text_reply("Saved."),
    )
    messages = [{"role": "user", "content": "remind me to call mom"}]
    answer, tools = agent.ask(messages)
    assert (answer, tools) == ("Saved.", ["add_reminder"])
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "Reminder saved: call mom. It has NO time, so it will not fire: tell the user that, and ask when they want it."}
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
    """Every tool the model could ever be offered -- the fixed ones, always, plus a connector's tool
    once it exists (docs/CONNECTORS_DESIGN.md, unit C2), plus the proposal tool of each kind of action
    (docs/ACTIONS_DESIGN.md, unit A4) -- has a real function behind it, whether or not that connector
    happens to be connected right now (agent.tools filters that separately), and nothing else does."""
    agent, _ = make_agent(config)
    advertised = {t["function"]["name"] for t in diya.TOOLS}
    connector_tools = {spec["function"]["name"] for _name, spec, _func in diya_connector_tools.tool_specs(config)}
    proposal_tools = {kind.tool_name for kind in agent.actions.kinds if kind.tool is not None}
    assert proposal_tools == {"propose_todoist_task"}  # the one kind of action Diya has
    assert advertised | connector_tools | proposal_tools == set(agent._functions)


def test_a_connectors_tool_is_offered_only_once_it_is_connected(config):
    agent, _ = make_agent(config)
    assert "search_home_assistant" not in {t["function"]["name"] for t in agent.tools}

    connector = diya_connectors.by_name(diya_connector_tools.real_connectors(config), "home_assistant")
    diya_connectors.connect(config, dataclasses.replace(connector, validate=lambda token: None), "a-token")

    assert "search_home_assistant" in {t["function"]["name"] for t in agent.tools}
    diya_connectors.disconnect(config, "home_assistant")
    assert "search_home_assistant" not in {t["function"]["name"] for t in agent.tools}


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
    import httpx
    import openai

    agent, client = make_agent(config, text_reply("Hi there."))
    thread = agent.store.create_thread()
    typed = iter(["hello", "", "again", "exit"])

    def next_input(prompt=""):
        line = next(typed)
        if line == "again":  # the model goes away after its first answer
            client._chat_error = openai.APIConnectionError(message="refused", request=httpx.Request("POST", "http://localhost:11434/v1"))
        return line

    monkeypatch.setattr("builtins.input", next_input)
    diya.chat_loop(agent, thread, [])
    out = capsys.readouterr().out
    assert "assistant> Hi there." in out
    assert "assistant> Couldn't reach the model (" in out
    assert agent.store.get_history(thread) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there."},
        {"role": "user", "content": "again"},
    ]


def test_the_chat_loop_does_not_blame_the_model_for_what_is_not_the_models_doing(config, monkeypatch, capsys):
    agent, _ = make_agent(config)  # no replies at all: the fake client raises IndexError, which is a defect, not a model that is down
    thread = agent.store.create_thread()
    typed = iter(["hello", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(typed))
    diya.chat_loop(agent, thread, [])
    out = capsys.readouterr().out
    assert "Couldn't reach the model" not in out
    assert "assistant> Something went wrong while answering (IndexError: " in out and "Your message was kept; try again." in out
    assert agent.store.get_history(thread) == [{"role": "user", "content": "hello"}]


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


# --- how much of a chat the model is sent (DIYA_HISTORY_CHARS) -------------------------------------------------------

def chat(*lengths):
    """A chat that alternates user and assistant, starting with the user, each message `length` characters of its own number."""
    return [{"role": "user" if n % 2 == 0 else "assistant", "content": str(n % 10) * length} for n, length in enumerate(lengths)]


def test_a_chat_that_fits_is_sent_whole():
    messages = chat(100, 100, 100)
    assert diya.trim_history(messages, 10_000) == messages


def test_the_oldest_messages_are_the_ones_dropped():
    messages = chat(1000, 1000, 1000, 1000, 1000)  # user, assistant, user, assistant, user
    budget = 3 * (1000 + diya.HISTORY_MESSAGE_OVERHEAD)
    assert diya.trim_history(messages, budget) == messages[2:]  # the last three fit exactly; the budget is a limit, not a target


def test_a_chat_one_character_over_loses_the_oldest_message():
    messages = chat(1000, 1000, 1000)
    budget = 3 * (1000 + diya.HISTORY_MESSAGE_OVERHEAD)
    assert diya.trim_history(messages, budget) == messages
    assert diya.trim_history(messages, budget - 1) == messages[2:]  # the user message went, which left an answer without its question, so that went too


def test_the_last_message_is_kept_however_long_it_is():
    messages = chat(10, 10, 50_000)
    assert diya.trim_history(messages, 1000) == messages[2:]


def test_an_answer_left_at_the_start_without_its_question_is_dropped_too():
    messages = chat(1000, 1000, 1000)  # user, assistant, user
    budget = 2 * (1000 + diya.HISTORY_MESSAGE_OVERHEAD)  # room for the assistant message and the last user message only
    assert diya.trim_history(messages, budget) == messages[2:]


def test_the_message_that_would_not_fit_ends_the_search_so_an_older_short_one_does_not_come_back_in():
    messages = chat(10, 5000, 10)  # a short message, a long one, the last
    assert diya.trim_history(messages, 200) == messages[2:]  # not messages[0] + messages[2]: the chat is never left with a hole in it


def test_a_message_costs_its_text_and_sixteen_characters():
    messages = [{"role": "user", "content": "x" * 100} for _ in range(3)]
    assert diya.HISTORY_MESSAGE_OVERHEAD == 16
    assert diya.trim_history(messages, 2 * 116) == messages[1:] and diya.trim_history(messages, 2 * 116 - 1) == messages[2:]
    assert diya.trim_history(messages, 3 * 116) == messages


def test_every_answer_left_at_the_start_is_dropped_not_only_the_first():
    messages = [{"role": "assistant", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    assert diya.trim_history(messages, 1000) == messages[2:]


def test_a_chat_that_ends_on_an_answer_keeps_it_though_nothing_else_fits():
    messages = [{"role": "user", "content": "q" * 500}, {"role": "assistant", "content": "a" * 500}]
    assert diya.trim_history(messages, 100) == messages[1:]


def test_a_tools_result_left_at_the_start_without_its_call_is_dropped_too():
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "result", "tool_call_id": "1"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "thanks"},
    ]
    assert diya.trim_history(messages[1:], 1000) == messages[3:]  # a result with no call, then an answer to nothing, then the person's next message
    assert diya.trim_history(messages, 1000) == messages[3:]  # nothing in it is the person's but the last: the rest opens on a call with no question


def test_zero_or_less_sends_everything():
    messages = chat(1000, 1000, 1000)
    assert diya.trim_history(messages, 0) == messages and diya.trim_history(messages, -5) == messages


def test_what_is_returned_is_a_new_list_and_the_messages_are_untouched():
    messages = chat(100, 100)
    assert diya.trim_history(messages, 0) is not messages and diya.trim_history(messages, 10_000) is not messages
    assert messages == chat(100, 100)


def test_an_empty_chat_and_a_message_with_no_text_are_fine():
    assert diya.trim_history([], 100) == []
    assert diya.trim_history([{"role": "user", "content": None}], 100) == [{"role": "user", "content": None}]


def test_tool_messages_count_by_their_text_and_stay_with_the_trimmed_list():
    messages = [{"role": "user", "content": "a" * 500}, {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]}, {"role": "tool", "content": "b" * 500}, {"role": "user", "content": "go"}]
    assert diya.trim_history(messages, 100) == messages[3:]


def test_asking_sends_the_model_only_the_newest_part_of_a_long_chat(config):
    agent, client = make_agent(dataclasses.replace(config, history_chars=700), text_reply("ok"))
    messages = chat(300, 300, 300, 300, 300)  # user, assistant, user, assistant, user
    newest = messages[4]["content"]
    agent.ask(messages)
    sent = [m["content"] for m in client.chat_calls[0]["messages"] if m["role"] != "system"]
    assert sent == [newest]  # room for two, which would open on an answer: the question stays alone


def test_the_callers_list_is_cut_the_same_way_so_a_chat_held_in_memory_stops_growing(config):
    agent, client = make_agent(dataclasses.replace(config, history_chars=700), text_reply("ok"), text_reply("ok"))
    history = chat(300, 300, 300, 300, 300)
    agent.ask(history)
    assert [m["content"] for m in history] == [chat(300, 300, 300, 300, 300)[4]["content"]]
    history += [{"role": "assistant", "content": "a" * 300}, {"role": "user", "content": "b" * 300}]
    agent.ask(history)
    assert [m["content"] for m in history] == ["b" * 300]  # room for the answer and the question, but the answer's own question was cut: it goes too


def test_what_is_known_about_the_person_stays_and_does_not_count_against_the_chat(config, tmp_path):
    (tmp_path / "agent_profile.txt").write_text("Likes guitar.\n")
    agent, client = make_agent(dataclasses.replace(config, history_chars=700), text_reply("ok"))
    history = agent.with_profile(chat(300, 300, 300))
    newest = history[3]["content"]
    assert history[0]["role"] == "system" and len(history) == 4
    agent.ask(history)
    sent = client.chat_calls[0]["messages"]
    assert sent[0]["role"] == "system" and "Likes guitar." in sent[0]["content"] and [m["content"] for m in sent[1:] if m["role"] != "system"] == [newest]


def test_every_leading_system_message_stays_whatever_the_limit(config):
    agent, client = make_agent(dataclasses.replace(config, history_chars=100), text_reply("ok"))
    messages = [{"role": "system", "content": "s" * 500}, {"role": "system", "content": "t" * 500}] + chat(300, 300, 300)
    agent.ask(messages)
    sent = client.chat_calls[0]["messages"]
    assert [m["content"][0] for m in sent if m["role"] == "system"][:2] == ["s", "t"]
    assert [m["role"] for m in messages].count("system") == 2


def test_a_chat_that_fits_reaches_the_model_whole(config):
    agent, client = make_agent(config, text_reply("ok"))
    messages = chat(100, 100, 100)
    agent.ask(messages)
    assert [m["content"] for m in client.chat_calls[0]["messages"] if m["role"] != "system"] == [m["content"] for m in chat(100, 100, 100)]
    assert len(messages) == 3


def test_a_chat_with_no_limit_reaches_the_model_whole(config):
    agent, client = make_agent(dataclasses.replace(config, history_chars=0), text_reply("ok"))
    agent.ask(chat(50_000, 50_000, 50_000))
    assert len([m for m in client.chat_calls[0]["messages"] if m["role"] != "system"]) == 3


def test_the_terminal_chat_and_the_web_chat_both_ask_through_the_one_place_that_trims():
    import inspect

    assert "_within_window" in inspect.getsource(Agent.ask) and "trim_history" in inspect.getsource(Agent._within_window)


def test_the_default_leaves_room_for_an_ordinary_chat_and_fits_the_small_models_window():
    assert diya_config.load_config({}).history_chars == 24_000  # about 6,000 tokens; the capped 4B model's window is 16,384


def test_the_history_limit_is_a_setting():
    assert diya_config.load_config({"DIYA_HISTORY_CHARS": "5000"}).history_chars == 5000
    assert diya_config.load_config({"DIYA_HISTORY_CHARS": " 0 "}).history_chars == 0


@pytest.mark.parametrize("bad", ["abc", "12.5", "-1"])
def test_a_history_limit_that_is_not_a_whole_number_of_zero_or_more_is_refused(bad):
    with pytest.raises(diya_config.ConfigError, match="DIYA_HISTORY_CHARS"):
        diya_config.load_config({"DIYA_HISTORY_CHARS": bad})
