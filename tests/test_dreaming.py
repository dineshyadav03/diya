import dataclasses
import json
import os
import pathlib
import subprocess
import sys

import pytest

import diya_config
import dreaming
from diya_db import Store
from dreaming import Dreamer
from fakes import FakeClient, text_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEAD_OLLAMA = "http://127.0.0.1:9/v1"  # port 9 (discard): nothing listens


@pytest.fixture
def data(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


@pytest.fixture
def config(data):
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(data / "dream.db"),
        profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"),
        dream_log_path=str(data / "dream.log"),
    )


def seed(config, *messages):
    store = Store(config.db_path)
    thread = store.create_thread()
    for role, content in messages:
        store.add_message(thread, role, content)
    return store


def dreamer(config, *replies, **client_kwargs):
    client = FakeClient(replies, **client_kwargs)
    return Dreamer(config, client=client), client


def state(config):
    with open(config.dream_state_path) as f:
        return json.load(f)


def script_env(config):
    return {
        "DIYA_DB_PATH": config.db_path,
        "DIYA_PROFILE_PATH": config.profile_path,
        "DIYA_DREAM_STATE_PATH": config.dream_state_path,
        "DIYA_DREAM_LOG_PATH": config.dream_log_path,
        "DIYA_OLLAMA_URL": DEAD_OLLAMA,
    }


def run_script(cwd, env, exe=None, **kwargs):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_")}
    full_env.update(env)
    return subprocess.run(
        [exe or sys.executable, str(ROOT / "dreaming.py")],
        cwd=cwd, env=full_env, capture_output=True, text=True, timeout=60, **kwargs,
    )


# --- importing and constructing are free of side effects -----------------------------------

def test_importing_dreaming_has_no_side_effects(run_python, tmp_path):
    code = "import sys, dreaming; assert sys.stdout is sys.__stdout__; print('ok')"
    result = run_python(code, env={"DIYA_OLLAMA_URL": DEAD_OLLAMA})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"  # and no dream_log.txt / header line
    assert list(tmp_path.iterdir()) == []


def test_constructing_a_dreamer_touches_nothing(config, data):
    dreamer_, client = dreamer(config)
    assert dreamer_._client is client
    assert Dreamer(config)._client is None  # the model client is built on first use
    assert list(data.iterdir()) == []


def test_a_default_dreamer_follows_the_environment(monkeypatch, data):
    monkeypatch.setenv("DIYA_DREAM_STATE_PATH", str(data / "s.json"))
    monkeypatch.setenv("DIYA_MODEL", "some-other-model")
    d = Dreamer(client=FakeClient())
    assert d.config.dream_state_path == str(data / "s.json")
    assert d.config.model == "some-other-model"


def test_the_default_paths_are_the_previous_relative_files():
    cfg = diya_config.load_config({})
    assert (cfg.profile_path, cfg.dream_state_path, cfg.dream_log_path) == (
        "user_profile.txt", "dream_state.json", "dream_log.txt",
    )


# --- the cycle (behaviour carried over unchanged) --------------------------------------------

def test_nothing_new_means_no_model_call_and_no_files(config, data, capsys):
    d, client = dreamer(config)
    d.dream_cycle()
    assert capsys.readouterr().out == "Nothing new to dream about.\n"
    assert client.chat_calls == []
    assert list(data.iterdir()) == [data / "dream.db"]


def test_assistant_only_messages_teach_nothing(config, capsys):
    seed(config, ("assistant", "Hello!"))
    d, client = dreamer(config)
    d.dream_cycle()
    assert "Nothing new to dream about." in capsys.readouterr().out
    assert client.chat_calls == []


def test_new_facts_are_extracted_from_user_messages_only_and_appended(config, data, capsys):
    seed(config, ("user", "I adopted a dog named Rocky"), ("assistant", "Congrats on the puppy!"))
    (data / "profile.txt").write_text("- likes tea\n")
    d, client = dreamer(config, text_reply("  - has a dog named Rocky\n"))
    d.dream_cycle()

    call = client.chat_calls[0]
    assert call["model"] == "qwen2.5:3b" and call["tools"] is None
    prompt = call["messages"][0]["content"]
    assert "- I adopted a dog named Rocky" in prompt and "Congrats" not in prompt
    assert (data / "profile.txt").read_text() == "- likes tea\n- has a dog named Rocky\n"  # appended, not replaced
    assert state(config) == {"last_message_id": 2}  # the last message overall, assistant's included
    assert capsys.readouterr().out == "New facts appended:\n- has a dog named Rocky\n"


def test_the_next_cycle_only_sees_newer_messages(config, data):
    store = seed(config, ("user", "I adopted a dog named Rocky"))
    first, _ = dreamer(config, text_reply("- dog: Rocky"))
    first.dream_cycle()
    thread = store.list_threads()[0][0]
    store.add_message(thread, "user", "My favourite colour is teal")

    second, client = dreamer(config, text_reply("- likes teal"))
    second.dream_cycle()
    prompt = client.chat_calls[0]["messages"][0]["content"]
    assert "teal" in prompt and "Rocky" not in prompt
    assert (data / "profile.txt").read_text() == "- dog: Rocky\n- likes teal\n"
    assert state(config) == {"last_message_id": 2}


@pytest.mark.parametrize("reply", ["NONE", "none -- nothing personal here", "", "   "])
def test_no_facts_still_advances_the_state_but_writes_no_profile(config, data, capsys, reply):
    seed(config, ("user", "quick check"))
    d, _ = dreamer(config, text_reply(reply))
    d.dream_cycle()
    assert "No genuine new facts found." in capsys.readouterr().out
    assert state(config) == {"last_message_id": 1}
    assert not (data / "profile.txt").exists()


def test_an_unreachable_model_loses_no_progress(config, data, capsys):
    seed(config, ("user", "I adopted a dog named Rocky"))
    down, _ = dreamer(config, chat_error=ConnectionError("down"))
    down.dream_cycle()
    assert capsys.readouterr().out == "[error] Could not reach the model (down). Will retry next cycle.\n"
    assert not os.path.exists(config.dream_state_path) and not (data / "profile.txt").exists()

    recovered, client = dreamer(config, text_reply("- dog: Rocky"))
    recovered.dream_cycle()  # the same message is picked up on the next cycle
    assert "Rocky" in client.chat_calls[0]["messages"][0]["content"]
    assert state(config) == {"last_message_id": 1}


def test_profile_helpers(config, data):
    d, _ = dreamer(config)
    assert d.load_profile() == "(no profile yet -- this is the first dream cycle)"
    d.save_profile("  - a fact  \n\n")
    assert (data / "profile.txt").read_text() == "- a fact\n"
    assert d.load_profile() == "- a fact"
    assert d.load_last_dreamed_id() == 0
    d.save_last_dreamed_id(7)
    assert d.load_last_dreamed_id() == 7


def test_configured_paths_are_used_and_the_defaults_are_left_alone(config, tmp_path):
    seed(config, ("user", "I adopted a dog named Rocky"))
    d, _ = dreamer(config, text_reply("- dog: Rocky"))
    d.dream_cycle()
    assert os.path.exists(config.profile_path) and os.path.exists(config.dream_state_path)
    for default in ("user_profile.txt", "dream_state.json", "dream_log.txt"):
        assert not (tmp_path / default).exists()  # cwd is tmp_path in every test


# --- main(): what Task Scheduler actually runs ---------------------------------------------------

def test_main_sends_everything_to_the_log_and_nothing_to_the_console(config):
    seed(config, ("user", "I adopted a dog named Rocky"))
    result = run_script(pathlib.Path(config.db_path).parent, script_env(config))
    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""
    log = pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
    assert log.startswith("\n--- dream cycle at ")
    assert "[error] Could not reach the model" in log  # Ollama is "down": logged, not lost
    assert not os.path.exists(config.dream_state_path)  # ...and no progress lost


def test_main_appends_to_the_log_run_after_run(config):
    cwd = pathlib.Path(config.db_path).parent
    run_script(cwd, script_env(config))
    first = pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
    run_script(cwd, script_env(config))
    second = pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
    assert second.startswith(first) and second.count("--- dream cycle at ") == 2
    assert second.count("Nothing new to dream about.") == 2


def test_main_logs_to_dream_log_txt_in_the_working_directory_by_default(config, tmp_path):
    env = {k: v for k, v in script_env(config).items() if k != "DIYA_DREAM_LOG_PATH"}
    result = run_script(tmp_path, env)  # Task Scheduler's "start in" folder is the working directory
    assert result.returncode == 0
    assert "Nothing new to dream about." in (tmp_path / "dream_log.txt").read_text(encoding="utf-8")


def test_main_records_a_bad_setting_in_the_default_log(config, tmp_path):
    env = {**script_env(config), "DIYA_PORT": "eighty"}
    env.pop("DIYA_DREAM_LOG_PATH")
    result = run_script(tmp_path, env)
    assert result.returncode == 1 and result.stdout == "" and result.stderr == ""
    assert "[error] DIYA_PORT must be an integer" in (tmp_path / "dream_log.txt").read_text(encoding="utf-8")


def test_main_writes_a_crash_traceback_to_the_log(config, data):
    (data / "state.json").write_text("{not json")
    result = run_script(data, script_env(config))
    assert result.returncode == 1 and result.stderr == ""
    log = pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in log and "JSONDecodeError" in log


def test_main_works_when_there_is_no_console_at_all(run_python, config):
    # pythonw.exe starts with sys.stdout and sys.stderr set to None; reproduce that directly.
    code = "import sys; sys.stdout = None; sys.stderr = None; import dreaming; sys.exit(dreaming.main())"
    result = run_python(code, env=script_env(config))
    assert result.returncode == 0, result.stderr
    log = pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
    assert "--- dream cycle at " in log and "Nothing new to dream about." in log


@pytest.mark.skipif(
    not pathlib.Path(sys.executable).with_name("pythonw.exe").exists(), reason="pythonw.exe not available"
)
def test_main_under_the_real_windowless_interpreter(config, data):
    pythonw = str(pathlib.Path(sys.executable).with_name("pythonw.exe"))
    result = run_script(data, script_env(config), exe=pythonw, stdin=subprocess.DEVNULL)
    assert result.returncode == 0
    assert "Nothing new to dream about." in pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")


def test_main_restores_the_console_streams_afterwards(config, capsys, monkeypatch):
    for name, value in script_env(config).items():
        monkeypatch.setenv(name, value)
    before = sys.stdout, sys.stderr
    assert dreaming.main() == 0
    assert (sys.stdout, sys.stderr) == before
    assert capsys.readouterr().out == ""  # nothing leaked to the console during the run
    assert "Nothing new to dream about." in pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
