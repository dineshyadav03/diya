"""Why "hey" was slow, and what was done (docs/SPEED_DESIGN.md): diya_warm.py and the small-talk check.

What this proves: the keep-warm asks Ollama, at its own native address, to keep the chat model for the configured time, says so once when that starts working and once when it stops, never raises
when Ollama is not there, reads the very system message and tools a chat sends (and only that) when priming, repeats on its interval until stopped, and is off when the setting says so; a greeting,
a thank-you, a goodbye or "how are you" is answered without the tools being offered and anything more than that is offered them as before; and the settings are validated.
"""
import dataclasses
import threading

import pytest

import diya
import diya_config
import diya_intent
import diya_warm as warm
from fakes import FakeClient, text_reply

MODEL_PAYLOAD = {"model": "diya-chat", "keep_alive": "30m", "stream": False}


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config({}), model="diya-chat", db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "profile.txt"))


class Ollama:
    def __init__(self, up=True):
        self.up, self.requests = up, []

    def post(self, url, payload, timeout):
        self.requests.append((url, payload, timeout))
        return self.up


# ---- the keep-warm ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("given, expected", [("http://localhost:11434/v1", "http://localhost:11434"), ("http://localhost:11434/v1/", "http://localhost:11434"),
                                             ("http://localhost:11434", "http://localhost:11434"), ("http://example.test:1234/v1", "http://example.test:1234"),
                                             ("http://example.test/v1x", "http://example.test/v1x")])
def test_the_native_address_is_the_openai_style_one_without_its_v1(given, expected):
    assert warm.native_address(given) == expected


def test_renewing_asks_for_the_model_to_be_kept_with_no_prompt_so_nothing_is_read_or_made(config):
    ollama, said = Ollama(), []
    keeper = warm.KeepWarm(config, post=ollama.post, say=said.append)
    assert keeper.renew() is True
    assert ollama.requests == [("http://localhost:11434/api/generate", MODEL_PAYLOAD, warm.REQUEST_TIMEOUT)]
    assert "prompt" not in ollama.requests[0][1]


def test_the_keep_alive_and_model_come_from_the_settings(config):
    ollama = Ollama()
    warm.KeepWarm(dataclasses.replace(config, model="other:1b", keep_alive="2h"), post=ollama.post, say=lambda line: None).renew()
    assert ollama.requests[0][1] == {"model": "other:1b", "keep_alive": "2h", "stream": False}


def test_it_says_once_when_the_model_is_loaded_and_once_when_ollama_stops_answering_and_once_when_it_is_back(config):
    ollama, said = Ollama(), []
    keeper = warm.KeepWarm(config, post=ollama.post, say=said.append)
    keeper.renew()
    keeper.renew()
    assert len(said) == 1 and "diya-chat" in said[0] and "kept loaded" in said[0]
    ollama.up = False
    keeper.renew()
    keeper.renew()
    assert len(said) == 2 and "not answering" in said[1]
    ollama.up = True
    keeper.renew()
    assert len(said) == 3 and "kept loaded" in said[2]


def test_ollama_not_running_at_the_start_is_not_news_and_not_an_error(config):
    said = []
    keeper = warm.KeepWarm(config, post=Ollama(up=False).post, say=said.append)
    assert keeper.renew() is False and said == []


def test_the_real_post_never_raises_when_nothing_answers(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert warm.post_json("http://localhost:1/api/generate", {}, 1) is False
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.InvalidURL("bad")))
    assert warm.post_json("nonsense", {}, 1) is False
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(500))
    assert warm.post_json("http://localhost:1/api/generate", {}, 1) is False
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: httpx.Response(200))
    assert warm.post_json("http://localhost:1/api/generate", {}, 1) is True


def test_priming_reads_the_system_message_and_the_tools_a_chat_sends_and_one_token_of_answer(config):
    client = FakeClient([text_reply("x")])
    agent = diya.Agent(config, client=client)
    assert warm.KeepWarm(config, agent, post=Ollama().post, say=lambda line: None).prime() is True
    (call,) = client.chat_calls
    assert call["model"] == "diya-chat" and call["options"] == {"max_tokens": 1} and call["tools"] == agent.tools
    assert [m["role"] for m in call["messages"]][-1] == "user" and call["messages"][-1]["content"] == "hello"
    chat_prefix = agent._model_messages(agent.with_profile([{"role": "user", "content": "anything else"}]), False)
    assert call["messages"][:-1] == chat_prefix[:-1]  # the same leading messages a real chat starts with


def test_priming_with_no_agent_or_a_model_that_cannot_answer_is_a_no_not_an_error(config):
    assert warm.KeepWarm(config, post=Ollama().post).prime() is False
    agent = diya.Agent(config, client=FakeClient(chat_error=RuntimeError("down")))
    assert warm.KeepWarm(config, agent, post=Ollama().post).prime() is False


def test_running_loads_and_primes_then_renews_on_the_interval_until_stopped(config):
    client = FakeClient([text_reply("x")])
    ollama, waits = Ollama(), []
    keeper = warm.KeepWarm(config, diya.Agent(config, client=client), post=ollama.post, say=lambda line: None, sleep=lambda seconds: waits.append(seconds) or (keeper.stop() if len(waits) == 3 else None))
    keeper.run()
    assert waits == [warm.RENEW_SECONDS] * 3 and warm.RENEW_SECONDS == 240.0
    assert len(ollama.requests) == 1 + 2 and len(client.chat_calls) == 1  # loaded once at the start, renewed twice (the third wait ended in a stop), primed once


def test_it_does_not_prime_when_ollama_did_not_answer_the_first_request(config):
    client = FakeClient([text_reply("x")])
    keeper = warm.KeepWarm(config, diya.Agent(config, client=client), post=Ollama(up=False).post, say=lambda line: None, sleep=lambda s: keeper.stop())
    keeper.run()
    assert client.chat_calls == []


def test_start_runs_it_in_a_thread_that_does_not_keep_the_program_alive_and_stop_ends_it(config):
    ollama = Ollama()
    keeper = warm.KeepWarm(config, post=ollama.post, say=lambda line: None)
    thread = keeper.start()
    assert isinstance(thread, threading.Thread) and thread.daemon is True and thread.name == "keep-warm"
    keeper.stop()
    thread.join(5)
    assert not thread.is_alive() and len(ollama.requests) >= 1


def test_the_real_wait_ends_early_when_stopped(config):
    keeper = warm.KeepWarm(config, post=Ollama().post, say=lambda line: None)
    keeper.stop()
    import time

    started = time.time()
    keeper._wait(30)
    assert time.time() - started < 5


# ---- the settings -----------------------------------------------------------------------------------------------------------------

def test_the_defaults_keep_the_model_for_half_an_hour_and_it_is_on():
    config = diya_config.load_config({})
    assert config.keep_warm is True and config.keep_alive == "30m"


def test_the_switch_and_the_time_are_read():
    assert diya_config.load_config({"DIYA_KEEP_WARM": "0"}).keep_warm is False and diya_config.load_config({"DIYA_KEEP_WARM": "yes"}).keep_warm is True
    for value in ("30m", "2h", "600", "45s", "-1", "0"):
        assert diya_config.load_config({"DIYA_KEEP_ALIVE": value}).keep_alive == value
    with pytest.raises(diya_config.ConfigError, match="DIYA_KEEP_WARM"):
        diya_config.load_config({"DIYA_KEEP_WARM": "maybe"})


@pytest.mark.parametrize("value", ["forever", "30 m", "m30", "-2", "1.5h", "30min", "1d"])
def test_a_keep_alive_ollama_would_not_understand_is_refused(value):
    with pytest.raises(diya_config.ConfigError, match="DIYA_KEEP_ALIVE"):
        diya_config.load_config({"DIYA_KEEP_ALIVE": value})


def test_importing_the_module_does_nothing(run_python):
    done = run_python("import diya_warm, os; print(sorted(n for n in os.listdir('.') if n != '__pycache__'))")
    assert done.returncode == 0 and done.stdout.strip() == "[]"


# ---- small talk -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["hey", "Hey!", "hi", "hi diya", "Hello there!", "good morning", "Good morning Diya!!", "good evening", "morning", "Evening!", "hey, how are you?", "hi how are you doing", "thanks",
                                  "thank you", "thank you so much!", "thx", "ty", "cheers", "bye", "goodbye", "see you later", "see ya", "what's up", "whats up", "how's it going", "how are you", "hey \U0001F60A",
                                  "hello diya how are you today", "ttyl", "HEY DIYA", "heyyy", "hiii", "yo", "sup", "thanks diya", "hi’", "how’s it going", "gm", "  hey  ", "hey\n"])
def test_a_greeting_a_thank_you_a_goodbye_or_how_are_you_is_small_talk(text):
    assert diya_intent.is_small_talk(text) is True


@pytest.mark.parametrize("text", ["", " ", None, 5, "yes", "ok", "okay", "no", "sure", "hey remind me to call mum", "hi, my flight is on Friday", "thanks, now remind me at 5", "hey what's the weather",
                                  "how are you feeling about my schedule", "hi 5pm", "hey diya set a reminder", "good morning plan my day", "what's up with my reminders", "ok thanks", "hey " * 11,
                                  "hello world program in python", "hey diya what is on today", "thanks for the reminder yesterday, add another", "later today I have a call", "hey, what time is it?"])
def test_anything_more_than_small_talk_is_not_small_talk(text):
    assert diya_intent.is_small_talk(text) is False


def test_a_long_message_is_never_small_talk_however_it_starts():
    assert diya_intent.is_small_talk("hey " + "diya " * 20) is False and len("hey" + " there" * 7) > diya_intent.MAX_SMALL_TALK_CHARS and not diya_intent.is_small_talk("hey" + " there" * 7)


def test_a_greeting_is_answered_without_the_tools_being_offered(config):
    client = FakeClient([text_reply("Hello!")])
    agent = diya.Agent(config, client=client)
    answer, tools_called = agent.ask(agent.with_profile([{"role": "user", "content": "hey"}]))
    assert answer == "Hello!" and tools_called == [] and client.chat_calls[0]["tools"] is None


def test_a_request_is_still_offered_the_tools(config):
    client = FakeClient([text_reply("Sure.")])
    agent = diya.Agent(config, client=client)
    agent.ask(agent.with_profile([{"role": "user", "content": "hey what is the weather in Pune"}]))
    assert client.chat_calls[0]["tools"] == agent.tools and len(agent.tools) >= 8


def test_small_talk_does_not_change_how_the_answer_is_made(config):
    client = FakeClient([text_reply("Hello! How can I help you today? I can do many things for you.")])
    agent = diya.Agent(config, client=client)
    answer, _ = agent.ask(agent.with_profile([{"role": "user", "content": "hi"}]))
    assert answer == "Hello! I can do many things for you."  # not shortened (only fact-shares are), but the offer to help is taken out (diya_intent.tidy_small_talk)


def test_a_greeting_that_tries_to_call_a_tool_anyway_is_refused_by_the_tool_not_a_crash(config):
    from fakes import tool_calls_reply

    client = FakeClient([tool_calls_reply(("add_reminder", '{"content": "x"}')), text_reply("Hello!")])
    agent = diya.Agent(config, client=client)
    answer, tools_called = agent.ask(agent.with_profile([{"role": "user", "content": "hello"}]))
    assert answer == "Hello!" and client.chat_calls[1]["messages"][-1] == {"role": "tool", "tool_call_id": "call_1", "content": diya.REMINDER_NOT_ASKED}  # the reminder tool's own guard refuses an unasked reminder


def test_when_the_start_of_the_system_message_changes_it_is_read_again_and_when_it_does_not_it_is_not(config):
    import diya_memory

    client = FakeClient([text_reply("x"), text_reply("y"), text_reply("z")])
    agent = diya.Agent(config, client=client)
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 1:
            diya_memory.Memory(agent.store).add_manual("likes tea", "api")  # a new fact: every message now starts differently
        if len(waits) == 3:
            keeper.stop()

    keeper = warm.KeepWarm(config, agent, post=Ollama().post, say=lambda line: None, sleep=sleep)
    keeper.run()
    assert len(client.chat_calls) == 2  # read at the start, and once more after the fact; the third renewal found nothing new to read
