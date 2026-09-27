import dataclasses
import http.server
import json
import os
import pathlib
import subprocess
import sys
import threading
from datetime import datetime, timedelta

import pytest

import diya
import diya_config
import dreaming
from diya_db import Store
from dreaming import Dreamer
from fakes import FakeClient, text_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEAD_OLLAMA = "http://127.0.0.1:9/v1"  # port 9 (discard): nothing listens
PYTHONW = pathlib.Path(sys.executable).with_name("pythonw.exe")
STAGED_HEADER = "New facts staged for review (not added to profile):\n"


@pytest.fixture
def data(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


@pytest.fixture
def config(data):
    """The default configuration: staged mode."""
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(data / "dream.db"),
        profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"),
        dream_log_path=str(data / "dream.log"),
        dream_pending_path=str(data / "pending.jsonl"),
    )


def seed(config, *messages):
    store = Store(config.db_path)
    threads = store.list_threads()
    thread = threads[0][0] if threads else store.create_thread()
    for role, content in messages:
        store.add_message(thread, role, content)
    return store


def dreamer(config, *replies, **client_kwargs):
    client = FakeClient(replies, **client_kwargs)
    return Dreamer(config, client=client), client


def state(config):
    with open(config.dream_state_path) as f:
        return json.load(f)


def pending(config):
    """The parsed records in the pending file (must be strictly one JSON object per line)."""
    raw = pathlib.Path(config.dream_pending_path).read_bytes()
    assert b"\r" not in raw and (not raw or raw.endswith(b"\n"))
    return [json.loads(line) for line in raw.decode("utf-8").split("\n") if line]


def script_env(config):
    return {
        "DIYA_DB_PATH": config.db_path,
        "DIYA_PROFILE_PATH": config.profile_path,
        "DIYA_DREAM_STATE_PATH": config.dream_state_path,
        "DIYA_DREAM_LOG_PATH": config.dream_log_path,
        "DIYA_DREAM_PENDING_PATH": config.dream_pending_path,
        "DIYA_OLLAMA_URL": DEAD_OLLAMA,
        "NO_PROXY": "127.0.0.1,localhost",
    }


def run_script(cwd, env, exe=None, **kwargs):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_")}
    full_env.update(env)
    return subprocess.run(
        [exe or sys.executable, str(ROOT / "dreaming.py")],
        cwd=cwd, env=full_env, capture_output=True, text=True, timeout=60, **kwargs,
    )


@pytest.fixture
def fake_ollama():
    """A tiny OpenAI-compatible server, so the real script can be run end to end."""
    servers = []

    def start(reply_text):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)))))
                body = json.dumps({
                    "id": "fake", "object": "chat.completion", "created": 0, "model": "fake",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": reply_text}}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/v1", requests

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


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


def test_the_default_paths_are_the_previous_relative_files_plus_the_review_queue():
    cfg = diya_config.load_config({})
    assert (cfg.profile_path, cfg.dream_state_path, cfg.dream_log_path) == (
        "user_profile.txt", "dream_state.json", "dream_log.txt",
    )
    assert cfg.dream_pending_path == "dream_pending.jsonl"


# --- behaviour the extraction pass always has --------------------------------------------------------

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


@pytest.mark.parametrize("reply", ["NONE", "none -- nothing personal here", "", "   "])
def test_no_facts_still_advances_the_checkpoint_but_writes_nothing(config, data, capsys, reply):
    seed(config, ("user", "quick check"))
    d, _ = dreamer(config, text_reply(reply))
    d.dream_cycle()
    assert "No genuine new facts found." in capsys.readouterr().out
    assert state(config) == {"last_message_id": 1}
    assert not (data / "profile.txt").exists() and not (data / "pending.jsonl").exists()


def test_an_unreachable_model_loses_no_progress(config, data, capsys):
    seed(config, ("user", "I adopted a cat named Pixel"))
    down, _ = dreamer(config, chat_error=ConnectionError("down"))
    down.dream_cycle()
    assert capsys.readouterr().out == "[error] Could not reach the model (down). Will retry next cycle.\n"
    assert not os.path.exists(config.dream_state_path)
    assert not (data / "profile.txt").exists() and not (data / "pending.jsonl").exists()

    recovered, client = dreamer(config, text_reply("- cat: Pixel"))
    recovered.dream_cycle()  # the same message is picked up on the next cycle
    assert "Pixel" in client.chat_calls[0]["messages"][0]["content"]
    assert state(config) == {"last_message_id": 1}


def test_the_prompt_uses_user_messages_only_and_the_configured_model(config):
    seed(config, ("user", "I adopted a cat named Pixel"), ("assistant", "Congrats on the kitten!"))
    d, client = dreamer(config, text_reply("- cat: Pixel"))
    d.dream_cycle()
    call = client.chat_calls[0]
    assert call["model"] == "qwen2.5:3b" and call["tools"] is None
    prompt = call["messages"][0]["content"]
    assert "- I adopted a cat named Pixel" in prompt and "Congrats" not in prompt


def test_the_prompt_asks_for_a_named_persons_tag_in_brackets(config):
    """docs/PERSON_MEMORY_DESIGN.md, unit M2: the prompt, not a second call, asks for who a fact is about."""
    seed(config, ("user", "my sister Maya is visiting in May"))
    d, client = dreamer(config, text_reply("- sister Maya is visiting in May [Maya]"))
    d.dream_cycle()
    prompt = client.chat_calls[0]["messages"][0]["content"]
    assert "[Maya]" in prompt.split("my sister Maya")[0]  # the example is in the instructions, not copied from the message
    assert "square brackets" in prompt and "about the user" in prompt


def test_configured_paths_are_used_and_the_defaults_are_left_alone(config, tmp_path):
    seed(config, ("user", "I adopted a cat named Pixel"))
    d, _ = dreamer(config, text_reply("- cat: Pixel"))
    d.dream_cycle()
    assert os.path.exists(config.dream_state_path)
    for default in ("user_profile.txt", "dream_state.json", "dream_log.txt", "dream_pending.jsonl"):
        assert not (tmp_path / default).exists()  # cwd is tmp_path in every test


# --- staged mode (the default) ----------------------------------------------------------------

def test_staged_extraction_is_one_record_and_the_trusted_profile_is_never_touched(config, data, capsys):
    seed(config, ("user", "I adopted a cat named Pixel"), ("assistant", "Congrats on the kitten!"))
    (data / "profile.txt").write_bytes(b"- likes tea\r\n")
    d, _ = dreamer(config, text_reply("  - has a cat named Pixel\n"))
    d.dream_cycle()

    (record,) = pending(config)
    assert set(record) == {"timestamp", "first_message_id", "last_message_id", "model", "facts"}
    assert (record["first_message_id"], record["last_message_id"]) == (1, 2)
    assert record["model"] == "qwen2.5:3b"
    assert record["facts"] == ["- has a cat named Pixel"]
    stamp = datetime.fromisoformat(record["timestamp"])
    assert stamp.utcoffset() == timedelta(0)  # UTC

    assert (data / "profile.txt").read_bytes() == b"- likes tea\r\n"  # byte-identical
    assert state(config) == {"last_message_id": 2}
    assert capsys.readouterr().out == STAGED_HEADER + "- has a cat named Pixel\n"


def test_staged_mode_never_creates_the_profile(config, data):
    seed(config, ("user", "I adopted a cat named Pixel"))
    d, _ = dreamer(config, text_reply("- cat: Pixel"))
    d.dream_cycle()
    assert not (data / "profile.txt").exists()
    assert pending(config)[0]["facts"] == ["- cat: Pixel"]


def test_each_staged_extraction_is_its_own_record_with_a_disjoint_range(config):
    store = seed(config, ("user", "I adopted a cat named Pixel"))
    dreamer(config, text_reply("- cat: Pixel"))[0].dream_cycle()
    store.add_message(store.list_threads()[0][0], "user", "My favourite colour is teal")
    dreamer(config, text_reply("- likes teal"))[0].dream_cycle()
    first, second = pending(config)
    assert (first["first_message_id"], first["last_message_id"]) == (1, 1)
    assert (second["first_message_id"], second["last_message_id"]) == (2, 2)
    assert state(config) == {"last_message_id": 2}


def test_a_multi_line_reply_becomes_a_fact_list_and_the_file_stays_one_line_per_record(config):
    seed(config, ("user", "lots of facts"))
    reply = "- likes teal\n\n  - café owner \u2028with a separator\n- has a dog"
    dreamer(config, text_reply(reply))[0].dream_cycle()
    raw = pathlib.Path(config.dream_pending_path).read_bytes()
    assert raw.count(b"\n") == 1 and b"\r" not in raw and raw.endswith(b"\n")
    (record,) = pending(config)
    assert record["facts"] == ["- likes teal", "- café owner \u2028with a separator", "- has a dog"]
    assert "\u2028" not in raw.decode("utf-8")  # escaped, so line-splitting readers can't tear the record


def test_the_record_is_flushed_to_disk_before_the_checkpoint_moves(config, monkeypatch):
    seed(config, ("user", "I adopted a cat named Pixel"))
    events = []
    real_fsync, real_save = os.fsync, Dreamer.save_last_dreamed_id

    def spy_fsync(fd):
        events.append(("fsync", len(pathlib.Path(config.dream_pending_path).read_bytes()) > 0))
        return real_fsync(fd)

    def spy_save(self, message_id):
        events.append(("checkpoint", len(pending(config))))  # how many records exist when the checkpoint moves
        return real_save(self, message_id)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(Dreamer, "save_last_dreamed_id", spy_save)
    dreamer(config, text_reply("- cat: Pixel"))[0].dream_cycle()
    assert events == [("fsync", True), ("checkpoint", 1)]


def test_an_unreadable_queue_fails_closed_before_the_model_is_even_asked(config, data, capsys):
    seed(config, ("user", "I adopted a cat named Pixel"))
    (data / "queue_dir").mkdir()  # a directory where the queue file should be
    broken = dataclasses.replace(config, dream_pending_path=str(data / "queue_dir"))
    d, client = dreamer(broken, text_reply("- cat: Pixel"))
    d.dream_cycle()
    out = capsys.readouterr().out
    assert out.startswith("[error] Could not read the review queue (")
    assert out.endswith("Checkpoint left unchanged; will retry next cycle.\n")
    assert client.chat_calls == []  # it could not rule out a duplicate, so it stages nothing
    assert not os.path.exists(config.dream_state_path) and not (data / "profile.txt").exists()


def test_a_staging_failure_leaves_the_checkpoint_alone_and_the_batch_is_retried(config, data, capsys, monkeypatch):
    seed(config, ("user", "I adopted a cat named Pixel"))
    real_append, fail = Dreamer._append_pending, [True]

    def flaky_append(self, record):
        if fail.pop() if fail else False:
            raise OSError("disk full")
        return real_append(self, record)

    monkeypatch.setattr(Dreamer, "_append_pending", flaky_append)
    dreamer(config, text_reply("- cat: Pixel"))[0].dream_cycle()
    out = capsys.readouterr().out
    assert out == "[error] Could not stage the new facts (disk full). Checkpoint left unchanged; will retry next cycle.\n"
    assert not os.path.exists(config.dream_state_path) and not (data / "profile.txt").exists()
    assert not os.path.exists(config.dream_pending_path)

    retry, client = dreamer(config, text_reply("- cat: Pixel"))
    retry.dream_cycle()  # the very same batch, staged now
    assert "Pixel" in client.chat_calls[0]["messages"][0]["content"]
    assert [(r["first_message_id"], r["last_message_id"]) for r in pending(config)] == [(1, 1)]
    assert state(config) == {"last_message_id": 1}


def test_a_crash_between_staging_and_the_checkpoint_cannot_duplicate_the_batch(config, monkeypatch, capsys):
    seed(config, ("user", "I adopted a cat named Pixel"))
    real_save, fail = Dreamer.save_last_dreamed_id, [True]

    def flaky_save(self, message_id):
        if fail.pop() if fail else False:
            raise RuntimeError("disk full")
        return real_save(self, message_id)

    monkeypatch.setattr(Dreamer, "save_last_dreamed_id", flaky_save)
    with pytest.raises(RuntimeError, match="disk full"):
        dreamer(config, text_reply("- cat: Pixel"))[0].dream_cycle()
    assert len(pending(config)) == 1 and not os.path.exists(config.dream_state_path)
    capsys.readouterr()

    retry, client = dreamer(config)  # no replies scripted: a model call would blow up
    retry.dream_cycle()
    assert client.chat_calls == []  # it did not extract again
    assert capsys.readouterr().out == (
        "Messages 1-1 were already staged; checkpoint advanced, nothing staged again.\n"
    )
    assert len(pending(config)) == 1  # not duplicated
    assert state(config) == {"last_message_id": 1}


def test_messages_that_arrive_after_a_crash_are_staged_separately_not_merged_or_lost(config, monkeypatch):
    store = seed(config, ("user", "first thing"), ("user", "second thing"))
    real_save, fail = Dreamer.save_last_dreamed_id, [True]

    def flaky_save(self, message_id):
        if fail.pop() if fail else False:
            raise RuntimeError("crash")
        return real_save(self, message_id)

    monkeypatch.setattr(Dreamer, "save_last_dreamed_id", flaky_save)
    with pytest.raises(RuntimeError):
        dreamer(config, text_reply("- first and second"))[0].dream_cycle()
    store.add_message(store.list_threads()[0][0], "user", "third thing")  # arrives before the retry

    dreamer(config)[0].dream_cycle()  # recovery: moves the checkpoint to 2, extracts nothing
    assert state(config) == {"last_message_id": 2}
    late, client = dreamer(config, text_reply("- third"))
    late.dream_cycle()
    prompt = client.chat_calls[0]["messages"][0]["content"]
    assert "third thing" in prompt and "first thing" not in prompt
    assert [(r["first_message_id"], r["last_message_id"]) for r in pending(config)] == [(1, 2), (3, 3)]
    assert state(config) == {"last_message_id": 3}


def test_a_torn_last_line_is_not_a_staged_batch_and_is_ended_before_the_next_record(config, data):
    seed(config, ("user", "I adopted a cat named Pixel"))
    (data / "pending.jsonl").write_bytes(b'{"timestamp": "x", "first_message_id": 1, "last_mess')  # crash mid-write
    d, client = dreamer(config, text_reply("- cat: Pixel"))
    d.dream_cycle()
    assert len(client.chat_calls) == 1  # the fragment did not count as "already staged"
    lines = (data / "pending.jsonl").read_bytes().split(b"\n")
    assert lines[0].startswith(b'{"timestamp": "x"') and json.loads(lines[1])["facts"] == ["- cat: Pixel"]
    assert [(r["first_message_id"], r["last_message_id"]) for r in d.staged_batches()] == [(1, 1)]
    assert state(config) == {"last_message_id": 1}


@pytest.mark.parametrize("junk", [
    b"not json at all\n",
    b'{"first_message_id": "1", "last_message_id": 2}\n',   # ids must be integers
    b'{"first_message_id": 5, "last_message_id": 2}\n',     # last before first
    b'{"first_message_id": true, "last_message_id": 1}\n',  # True == 1 in Python, but is not an id
    b'{"first_message_id": 1}\n',
    b"[1, 2]\n",
    b"\n\n",
])
def test_lines_that_are_not_well_formed_records_are_ignored(config, data, junk):
    (data / "pending.jsonl").write_bytes(junk)
    assert Dreamer(config, client=FakeClient()).staged_batches() == []


def test_the_next_cycle_only_sees_newer_messages(config, data):
    store = seed(config, ("user", "I adopted a cat named Pixel"))
    dreamer(config, text_reply("- cat: Pixel"))[0].dream_cycle()
    store.add_message(store.list_threads()[0][0], "user", "My favourite colour is teal")
    second, client = dreamer(config, text_reply("- likes teal"))
    second.dream_cycle()
    prompt = client.chat_calls[0]["messages"][0]["content"]
    assert "teal" in prompt and "Pixel" not in prompt  # only what is newer than the checkpoint is shown to the model
    assert [r["facts"] for r in pending(config)] == [["- cat: Pixel"], ["- likes teal"]]
    assert state(config) == {"last_message_id": 2}


# --- main(): what Task Scheduler actually runs ---------------------------------------------------

def test_main_sends_everything_to_the_log_and_nothing_to_the_console(config):
    seed(config, ("user", "I adopted a cat named Pixel"))
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


@pytest.mark.parametrize("mode, expected", [
    ("auto", "[error] DIYA_DREAM_PROFILE_MODE can only be 'staged' (or left unset), got 'auto'"),
    ("direct", "[error] DIYA_DREAM_PROFILE_MODE=direct was retired"),  # the mode the scheduled job used to be able to run in
])
def test_main_refuses_an_unknown_or_retired_profile_mode_and_changes_nothing(config, data, mode, expected):
    seed(config, ("user", "I adopted a cat named Pixel"))
    env = {**script_env(config), "DIYA_DREAM_PROFILE_MODE": mode}
    result = run_script(data, env)
    assert result.returncode == 1 and result.stdout == "" and result.stderr == ""
    # the configuration failed to load, so the error goes to the default log location
    log = (data / "dream_log.txt").read_text(encoding="utf-8")
    assert expected in log
    assert "Remove the setting" in log or mode == "auto"  # the retired mode says what to do instead
    assert not os.path.exists(config.dream_state_path) and not os.path.exists(config.profile_path)
    assert not os.path.exists(config.dream_pending_path)


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


@pytest.mark.skipif(not PYTHONW.exists(), reason="pythonw.exe not available")
def test_main_under_the_real_windowless_interpreter(config, data):
    result = run_script(data, script_env(config), exe=str(PYTHONW), stdin=subprocess.DEVNULL)
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


# --- end to end: the real script against a fake model server ------------------------------------------

EXECUTABLES = [
    pytest.param(sys.executable, id="python"),
    pytest.param(str(PYTHONW), id="pythonw", marks=pytest.mark.skipif(not PYTHONW.exists(), reason="no pythonw.exe")),
]


@pytest.mark.parametrize("exe", EXECUTABLES)
def test_end_to_end_staged_run_stages_and_leaves_the_profile_alone(config, data, fake_ollama, exe):
    url, requests = fake_ollama("- has a cat named Pixel")
    seed(config, ("user", "I adopted a cat named Pixel"), ("assistant", "Congrats!"))
    (data / "profile.txt").write_bytes(b"- likes tea\r\n")
    env = {**script_env(config), "DIYA_OLLAMA_URL": url}

    result = run_script(data, env, exe=exe, stdin=subprocess.DEVNULL)
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    log = pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
    assert log.startswith("\n--- dream cycle at ") and STAGED_HEADER + "- has a cat named Pixel" in log
    (record,) = pending(config)
    assert (record["first_message_id"], record["last_message_id"], record["model"]) == (1, 2, "qwen2.5:3b")
    assert record["facts"] == ["- has a cat named Pixel"]
    assert state(config) == {"last_message_id": 2}
    assert (data / "profile.txt").read_bytes() == b"- likes tea\r\n"
    assert len(requests) == 1 and requests[0]["model"] == "qwen2.5:3b"

    again = run_script(data, env, exe=exe, stdin=subprocess.DEVNULL)  # nothing new: no second call, no duplicate
    assert again.returncode == 0 and len(requests) == 1 and len(pending(config)) == 1
    assert pathlib.Path(config.dream_log_path).read_text(encoding="utf-8").endswith("Nothing new to dream about.\n")

