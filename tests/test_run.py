"""The one-command start (docs/ONE_COMMAND_DESIGN.md, units O1 and O2): diya_run.py.

What this proves, with nothing really started (the process, the probes, the clock and PowerShell are all stand-ins): it says what is wrong before it starts anything and starts
nothing when something is; it starts the API first and the UI second, and waits for each to ANSWER (a refused request is the proof the API is up) before going on; it leaves
alone anything that already answers; a child that dies is started again after a wait that grows, and is given up on after five quick failures in a row; asking it to stop (a note
in the data folder, or Ctrl+C) stops what it started, the UI first, and nothing else; a new access token the API prints is never written to the log and is saved only when asked;
the PowerShell that registers the logon task is a constant that gets its two paths from environment variables, registers only what is missing, and removes only its own task;
and importing the module does nothing.
"""
import dataclasses
import io
import json
import os
import pathlib
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest

import diya_config
import diya_run as run

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET = "tok_" + "9f8e7d6c5b4a39281706f5e4d3c2b1a0"  # looks like a real token, is not one
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)


# ---- stand-ins -------------------------------------------------------------------------------------------------------------------

class FakeProcess:
    _pids = iter(range(1000, 10_000))

    def __init__(self, lines=(), returncode=None):
        self.stdout = io.StringIO("".join(line + "\n" for line in lines))
        self.returncode = returncode
        self.pid = next(self._pids)

    def poll(self):
        return self.returncode

    def die(self, code=1):
        self.returncode = code


class World:
    """The clock, the sleeping, the probes and the process starter, in one place, so a test can say what happens when."""

    def __init__(self, folder, api_lines=(), ui_lines=()):
        self.folder = folder
        self.now = 0.0
        self.sleeps = []
        self.started = []  # (name, argv, cwd, env) in the order they were started
        self.popen_kwargs = []
        self.start_times = []  # (name, seconds on the fake clock)
        self.processes = {"api": [], "ui": []}
        self.api_lines, self.ui_lines = list(api_lines), list(ui_lines)
        self.api_up = False
        self.ui_up = False
        self.api_comes_up = True  # does the API answer once started?
        self.ui_comes_up = True
        self.dies_at_start = set()
        self.on_sleep = None
        self.killed = []
        self.printed = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        assert len(self.sleeps) < 3000, "the launcher never stopped"
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self)

    def popen(self, argv, cwd=None, env=None, **kwargs):
        name = "api" if any("diya_web.py" in part for part in argv) else "ui"
        lines = self.api_lines if name == "api" else self.ui_lines
        process = FakeProcess(lines, returncode=1 if name in self.dies_at_start else None)
        self.started.append((name, list(argv), cwd, env))
        self.popen_kwargs.append(kwargs)
        self.start_times.append((name, self.now))
        self.processes[name].append(process)
        if name == "api" and self.api_comes_up:
            self.api_up = True
        if name == "ui" and self.ui_comes_up:
            self.ui_up = True
        return process

    def kill(self, process):
        self.killed.append(process)
        process.die(-9)

    def api(self, config):
        return self.api_up

    def ui(self, config):
        return self.ui_up

    def out(self, line):
        self.printed.append(line)

    @property
    def text(self):
        return "\n".join(self.printed)

    def last(self, name):
        return self.processes[name][-1]


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.Config(), data_dir=str(tmp_path / "data"), port=8080, frontend_port=3000)


@pytest.fixture
def repo(tmp_path):
    """A repo folder with what the checks look for: a certificate pair and the UI's packages."""
    folder = tmp_path / "repo"
    (folder / "frontend" / "node_modules").mkdir(parents=True)
    (folder / "localhost+2.pem").write_text("cert")
    (folder / "localhost+2-key.pem").write_text("key")
    return folder


@pytest.fixture
def world(config):
    os.makedirs(config.data_dir, exist_ok=True)
    return World(config.data_dir)


def make_launcher(config, repo, world, **extra):
    return run.Launcher(config, repo=str(repo), popen=world.popen, api=world.api, ui=world.ui, clock=world.clock, sleep=world.sleep, now=lambda: NOW + timedelta(seconds=world.now),
                        out=world.out, which=lambda name: f"/usr/bin/{name}", kill=world.kill, python="python.exe", data_dir=config.data_dir, **extra)


def everything_is_fine(config):
    return ["diya-chat:latest", "nomic-embed-text:latest", "qwen2.5:3b"]


def go(launcher, models=everything_is_fine):
    return launcher.run(models=models)


def log_text(config, name):
    path = os.path.join(config.data_dir, "logs", f"{name}.log")
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


def waits_told(world):
    """The waits (seconds) the launcher said it would make before starting the UI again."""
    return [int(m.group(1)) for line in world.printed for m in [re.search(r"^The ui exited \(.*\); starting it again in (\d+) seconds\.$", line)] if m]


def finish_reading(launcher):
    for child in launcher.children:
        if child.reader is not None:
            child.reader.join(timeout=5)


# ---- importing and the parser ----------------------------------------------------------------------------------------------------

def test_importing_does_nothing(run_python):
    done = run_python("import diya_run, os, sys; print(sorted(n for n in os.listdir('.') if n != '__pycache__'))")
    assert done.returncode == 0 and done.stdout.strip() == "[]"


def test_the_constants_are_what_the_design_says():
    assert (run.READY_WAIT_SECONDS, run.QUICK_FAILURES_LIMIT, run.QUICK_SECONDS, run.POLL_SECONDS) == (180.0, 5, 30.0, 2.0)
    assert (run.BACKOFF_FIRST, run.BACKOFF_MAX, run.HEARTBEAT_FRESH_SECONDS) == (2.0, 60.0, 10.0)
    assert (run.EXIT_OK, run.EXIT_FAILED, run.EXIT_UNUSABLE) == (0, 1, 2)
    assert (run.STATE_NAME, run.STOP_NAME, run.TASK_NAME) == ("diya_run.json", "diya_run.stop", "Diya_Run")


# ---- the log ---------------------------------------------------------------------------------------------------------------------

def test_a_log_gets_one_line_per_write_and_keeps_what_was_written(tmp_path):
    log = run.RotatingLog(str(tmp_path / "logs" / "x.log"))
    log.write("one")
    log.write("two\n")
    assert (tmp_path / "logs" / "x.log").read_text(encoding="utf-8") == "one\ntwo\n"


def test_a_big_log_starts_a_new_file_and_keeps_only_the_last_few(tmp_path):
    path = tmp_path / "x.log"
    log = run.RotatingLog(str(path), limit=20, keep=3)
    for number in range(12):
        log.write(f"line-{number:02d} padding")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["x.log", "x.log.1", "x.log.2"]
    assert "line-11" in path.read_text() and "line-00" not in "".join(p.read_text() for p in tmp_path.iterdir())
    older = (tmp_path / "x.log.1").read_text()
    oldest = (tmp_path / "x.log.2").read_text()
    assert older and oldest and "line-" in older and older.split()[0] > oldest.split()[0]


def test_a_log_below_its_limit_is_not_rotated(tmp_path):
    path = tmp_path / "x.log"
    log = run.RotatingLog(str(path), limit=1000, keep=3)
    for number in range(10):
        log.write(f"line {number}")
    assert [p.name for p in tmp_path.iterdir()] == ["x.log"]


def test_a_log_that_cannot_be_written_does_not_raise(tmp_path):
    (tmp_path / "x.log").mkdir()  # a folder where the file should be
    run.RotatingLog(str(tmp_path / "x.log")).write("still fine")


def test_a_log_can_be_written_from_two_threads_without_losing_lines(tmp_path):
    log = run.RotatingLog(str(tmp_path / "x.log"), limit=10**9)

    def many(tag):
        for number in range(200):
            log.write(f"{tag} {number}")

    threads = [threading.Thread(target=many, args=(tag,)) for tag in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len((tmp_path / "x.log").read_text().splitlines()) == 400


# ---- a new token is never logged -------------------------------------------------------------------------------------------------

BANNER = "A new access token was generated for Diya's API. Save it now: it is shown only this once, and only its hash is kept (in diya.db)."


def test_the_line_after_the_banner_is_the_token_and_is_held_back_from_the_log():
    keep = run.TokenFilter()
    assert keep.feed("starting") == ("starting", None, False)
    assert keep.feed(BANNER) == (BANNER, BANNER, False)
    logged, shown, was_token = keep.feed(f"    {SECRET}")
    assert SECRET not in logged and was_token and shown == f"    {SECRET}" and keep.token == SECRET
    assert keep.feed("after") == ("after", None, False)
    assert keep.feed(SECRET)[0] == SECRET  # outside the banner it is just a line (nothing else prints it)


def test_a_blank_line_between_the_banner_and_the_token_is_skipped():
    keep = run.TokenFilter()
    keep.feed(BANNER)
    assert keep.feed("") == ("", None, False)
    assert keep.feed(f"  {SECRET}  ")[2] is True and keep.token == SECRET


def test_save_token_makes_the_file_and_replaces_only_its_own_line(tmp_path):
    path = tmp_path / ".env.local"
    run.save_token(str(path), SECRET)
    assert path.read_text() == f"DIYA_TOKEN={SECRET}\n"
    path.write_text("DIYA_UI_PASSCODE=whatever\nDIYA_TOKEN=old\n  DIYA_TOKEN=older\nOTHER=1", encoding="utf-8")
    run.save_token(str(path), SECRET)
    assert path.read_text().splitlines() == ["DIYA_UI_PASSCODE=whatever", "OTHER=1", f"DIYA_TOKEN={SECRET}"]


def test_save_token_writes_unix_line_endings(tmp_path):
    path = tmp_path / ".env.local"
    path.write_bytes(b"A=1\r\nB=2\r\n")
    run.save_token(str(path), SECRET)
    assert b"\r" not in path.read_bytes()


# ---- looking ---------------------------------------------------------------------------------------------------------------------

def test_probe_http_says_the_status_an_address_answers_with_and_none_when_nothing_does():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response({"/ok": 200, "/no": 401, "/gone": 404}.get(self.path, 500))
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert [run.probe_http(base + path) for path in ("/ok", "/no", "/gone", "/boom")] == [200, 401, 404, 500]
    finally:
        server.shutdown()
        server.server_close()
    assert run.probe_http(base + "/ok", timeout=1) is None


def test_the_api_is_up_when_it_answers_or_refuses_and_not_otherwise(config):
    seen = []

    def probe_returning(status):
        def probe(url, **kwargs):
            seen.append(url)
            return status
        return probe

    answers = {status: run.api_answers(config, probe=probe_returning(status)) for status in (200, 401, 403, 404, 500, 502, None)}
    assert answers == {200: True, 401: True, 403: False, 404: False, 500: False, 502: False, None: False}
    assert set(seen) == {"https://127.0.0.1:8080/api/threads"}


def test_the_api_check_uses_the_configured_port(config):
    seen = []
    run.api_answers(dataclasses.replace(config, port=9191), probe=lambda url, **kw: seen.append(url) or 401)
    assert seen == ["https://127.0.0.1:9191/api/threads"]


def test_the_ui_is_up_when_it_answers_anything(config):
    seen = []
    assert run.ui_answers(config, probe=lambda url, **kw: seen.append(url) or 307) is True
    assert run.ui_answers(config, probe=lambda url, **kw: None) is False
    assert run.ui_answers(config, probe=lambda url, **kw: 500) is True
    assert seen == ["https://localhost:3000/login"]


def test_ollama_models_reads_the_names_and_none_when_it_does_not_answer(config):
    asked = []
    assert run.ollama_models(config, probe_json=lambda url: asked.append(url) or ["a:latest"]) == ["a:latest"]
    assert asked == ["http://localhost:11434/api/tags"]
    asked.clear()
    run.ollama_models(dataclasses.replace(config, ollama_url="http://example.test:1234"), probe_json=lambda url: asked.append(url) or [])
    assert asked == ["http://example.test:1234/api/tags"]

    def broken(url):
        raise OSError("down")

    assert run.ollama_models(config, probe_json=broken) is None


def test_has_model_accepts_the_bare_name_and_latest_only():
    assert run.has_model(["diya-chat:latest"], "diya-chat") and run.has_model(["diya-chat"], "diya-chat") and run.has_model(["qwen2.5:3b"], "qwen2.5:3b")
    assert not run.has_model(["diya-chat-old:latest"], "diya-chat") and not run.has_model(["qwen2.5:3b"], "qwen2.5") and not run.has_model([], "x")


# ---- the checks ------------------------------------------------------------------------------------------------------------------

def checked(config, repo, models=everything_is_fine, which=lambda name: "/usr/bin/node"):
    return run.check(dataclasses.replace(config, model="diya-chat", privacy_model="qwen2.5:3b"), repo=str(repo), which=which, models=models)


def test_nothing_is_wrong_when_nothing_is(config, repo):
    assert checked(config, repo) == []


def test_ollama_not_answering_is_said_and_the_models_are_not_blamed_too(config, repo):
    problems = checked(config, repo, models=lambda c: None)
    assert [p[0] for p in problems] == [f"Ollama does not answer at {config.ollama_url}"] and "ollama serve" in problems[0][1]


def test_each_missing_model_is_named_with_its_remedy(config, repo):
    problems = checked(config, repo, models=lambda c: ["nomic-embed-text:latest"])
    assert [p[0] for p in problems] == ["the chat model 'diya-chat' is not in Ollama", "the privacy model 'qwen2.5:3b' is not in Ollama"]
    assert "DIYA_MODEL" in problems[0][1] and problems[1][1] == "run `ollama pull qwen2.5:3b`"
    only_embedding = checked(config, repo, models=lambda c: ["diya-chat", "qwen2.5:3b"])
    assert only_embedding == [("the embedding model 'nomic-embed-text' is not in Ollama", "run `ollama pull nomic-embed-text`")]


def test_no_privacy_model_set_means_nothing_to_check_for_it(config, repo):
    quiet = run.check(dataclasses.replace(config, model="diya-chat", privacy_model=""), repo=str(repo), which=lambda n: "node", models=lambda c: ["diya-chat", "nomic-embed-text"])
    assert quiet == []


def test_a_missing_certificate_pair_is_said(config, repo):
    for name in ("localhost+2.pem", "localhost+2-key.pem"):
        (repo / name).unlink()
    problems = checked(config, repo)
    assert len(problems) == 1 and "certificate" in problems[0][0] and "mkcert" in problems[0][1]


def test_two_certificate_pairs_is_said_in_the_configuration_errors_own_words(config, repo):
    (repo / "other+1.pem").write_text("c")
    (repo / "other+1-key.pem").write_text("k")
    problems = checked(config, repo)
    assert len(problems) == 1 and "More than one mkcert certificate" in problems[0][0]


def test_a_missing_node_and_missing_packages_are_both_said(config, repo):
    (repo / "frontend" / "node_modules").rmdir()
    problems = checked(config, repo, which=lambda name: None)
    assert [p[0] for p in problems] == ["Node.js was not found", "the UI's packages are not installed"]
    assert "npm install" in problems[1][1]


# ---- which Python ----------------------------------------------------------------------------------------------------------------

def test_a_scheduled_task_pythonw_is_swapped_for_its_python_exe_when_there_is_one(tmp_path):
    (tmp_path / "pythonw.exe").write_text("")
    (tmp_path / "python.exe").write_text("")
    assert run.python_for_children(str(tmp_path / "pythonw.exe")) == str(tmp_path / "python.exe")
    assert run.python_for_children(str(tmp_path / "python.exe")) == str(tmp_path / "python.exe")
    (tmp_path / "python.exe").unlink()
    assert run.python_for_children(str(tmp_path / "pythonw.exe")) == str(tmp_path / "pythonw.exe")


# ---- starting --------------------------------------------------------------------------------------------------------------------

def stop_after(world, launcher_config, seconds):
    """Leave the note that asks the launcher to stop, once `seconds` have gone by."""
    def on_sleep(w):
        if w.now >= seconds:
            open(os.path.join(launcher_config.data_dir, run.STOP_NAME), "w").write("stop\n")
    world.on_sleep = on_sleep


def test_it_starts_the_api_then_the_ui_and_waits_for_each(config, repo, world):
    stop_after(world, config, 10)
    launcher = make_launcher(config, repo, world)
    world.api_comes_up = False  # the API takes a moment: it answers only after a few polls
    polls = {"n": 0}
    original = world.api

    def slow_api(c):
        polls["n"] += 1
        world.api_up = polls["n"] > 3
        return original(c)

    launcher.api = slow_api
    ui_was_started_before_api_answered = []
    real_popen = world.popen

    def watching_popen(argv, **kw):
        if "diya_web.py" not in " ".join(argv):
            ui_was_started_before_api_answered.append(world.api_up)
        return real_popen(argv, **kw)

    launcher.popen = watching_popen
    assert go(launcher) == run.EXIT_OK
    assert [name for name, *_ in world.started] == ["api", "ui"] and ui_was_started_before_api_answered == [True]
    assert "Diya is running. Open https://localhost:3000" in world.text and "Asked to stop." in world.text


def test_the_commands_are_the_ones_a_person_would_type_and_carry_no_secret(config, repo, world):
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world)
    go(launcher)
    (api_name, api_argv, api_cwd, api_env), (ui_name, ui_argv, ui_cwd, ui_env) = world.started
    assert api_argv == ["python.exe", "diya_web.py"] and api_cwd == str(repo)
    assert ui_argv == ["/usr/bin/node", os.path.join("tools", "next-tls.mjs"), "dev"] and ui_cwd == os.path.join(str(repo), "frontend")
    assert all(SECRET not in " ".join(argv) for argv in (api_argv, ui_argv))
    assert api_env["PYTHONUTF8"] == "1" and api_env["PYTHONIOENCODING"] == "utf-8"


def test_lan_adds_the_flag_the_package_script_adds(config, repo, world):
    stop_after(world, config, 4)
    go(make_launcher(config, repo, world, lan=True))
    assert world.started[1][1][-2:] == ["dev", "--lan"] and "--lan" not in world.started[0][1]


def test_a_problem_found_by_the_checks_starts_nothing(config, repo, world):
    launcher = make_launcher(config, repo, world)
    assert go(launcher, models=lambda c: None) == run.EXIT_UNUSABLE
    assert world.started == [] and "Not started: Ollama does not answer" in world.text and "To fix it:" in world.text


def test_an_api_that_already_answers_is_left_alone_and_only_the_ui_is_started(config, repo, world):
    world.api_up = True
    stop_after(world, config, 4)
    assert go(make_launcher(config, repo, world)) == run.EXIT_OK
    assert [name for name, *_ in world.started] == ["ui"] and "The API already answers on port 8080; leaving it alone." in world.text


def test_a_ui_that_already_answers_is_left_alone_and_only_the_api_is_started(config, repo, world):
    world.ui_up = True
    stop_after(world, config, 4)
    go(make_launcher(config, repo, world))
    assert [name for name, *_ in world.started] == ["api"] and "The UI already answers on port 3000; leaving it alone." in world.text


def test_both_already_running_means_nothing_is_started_and_nothing_is_stopped(config, repo, world):
    world.api_up = world.ui_up = True
    assert go(make_launcher(config, repo, world)) == run.EXIT_OK
    assert world.started == [] and world.killed == [] and "already running" in world.text
    assert not os.path.exists(os.path.join(config.data_dir, run.STATE_NAME))


def test_a_child_that_stops_while_starting_is_reported_with_where_to_look(config, repo, world):
    world.dies_at_start = {"api"}
    world.api_comes_up = False
    code = go(make_launcher(config, repo, world))
    assert code == run.EXIT_FAILED and [name for name, *_ in world.started] == ["api"]
    assert "The api stopped while starting" in world.text and os.path.join("logs", "api.log") in world.text


def test_a_child_that_never_answers_is_given_up_on_after_the_wait(config, repo, world):
    world.api_comes_up = False
    code = go(make_launcher(config, repo, world))
    assert code == run.EXIT_FAILED and world.now >= run.READY_WAIT_SECONDS and world.now < run.READY_WAIT_SECONDS + 5
    assert "did not answer within 180 seconds" in world.text and world.killed == [world.last("api")]


def test_asking_to_stop_while_waiting_is_not_a_failure(config, repo, world):
    world.api_comes_up = False
    stop_after(world, config, 6)
    assert go(make_launcher(config, repo, world)) == run.EXIT_OK and world.killed == [world.last("api")]


def test_if_the_ui_fails_to_start_the_api_that_was_started_is_stopped_again(config, repo, world):
    world.dies_at_start = {"ui"}
    world.ui_comes_up = False
    assert go(make_launcher(config, repo, world)) == run.EXIT_FAILED
    assert world.killed == [world.last("api")]


# ---- supervising -----------------------------------------------------------------------------------------------------------------

def test_a_child_that_dies_is_started_again_after_a_short_wait(config, repo, world):
    launcher = make_launcher(config, repo, world)
    state = {"died": False}

    def on_sleep(w):
        if not state["died"] and w.now >= 100:
            w.last("ui").die(1)
            state["died"] = True
        if state["died"] and len(w.processes["ui"]) == 2 and w.now >= 110:
            open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    assert go(launcher) == run.EXIT_OK
    assert len(world.processes["ui"]) == 2 and len(world.processes["api"]) == 1
    assert "The ui exited (1); starting it again in 2 seconds." in world.text and "Starting the ui again..." in world.text


def test_quick_failures_wait_longer_each_time_and_five_in_a_row_are_given_up_on(config, repo, world):
    launcher = make_launcher(config, repo, world)

    def on_sleep(w):
        for name in ("ui",):
            child = w.processes[name][-1]
            if child.returncode is None and w.now > 10:
                child.die(3)

    world.on_sleep = on_sleep
    assert go(launcher) == run.EXIT_FAILED
    waits = waits_told(world)
    assert waits == [2, 4, 8, 16]
    assert "giving up on it" in world.text and "5 times in a row" in world.text and len(world.processes["ui"]) == 5
    assert world.killed == [world.last("api")]  # the UI had already exited; the API that was left is stopped with the launcher


def test_a_long_run_resets_the_failure_count_and_the_wait(config, repo, world):
    launcher = make_launcher(config, repo, world)
    lives = {1: 3, 2: 3, 3: 60}  # how long each start of the UI lives before it dies: two quick deaths, then a long life

    def on_sleep(w):
        number = len(w.processes["ui"])
        child = w.processes["ui"][-1]
        age = w.now - launcher.children[1].started_at
        if number in lives and child.returncode is None and age >= lives[number]:
            child.die(1)
        if number >= 4:
            open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    assert go(launcher) == run.EXIT_OK
    # two quick failures wait 2 s and 4 s; the third start lived 60 s, which is not quick, so the next wait starts again from the first step
    assert waits_told(world) == [2, 4, 2] and launcher.children[1].quick_failures == 0


def test_the_wait_never_goes_beyond_a_minute(config, repo):
    child = run.Child("x", [], "", None)
    launcher = make_launcher(config, repo, World(config.data_dir))
    shown = []
    launcher.out = shown.append
    for failures in range(1, 5):
        child.quick_failures = failures - 1
        child.process = FakeProcess(returncode=1)
        child.started_at = launcher.clock()
        launcher._note_exit(child)
    assert child.next_start == launcher.clock() + 16  # the fourth quick failure waits 16 seconds
    big = run.Child("y", [], "", None)
    big.process, big.started_at, big.quick_failures = FakeProcess(returncode=1), launcher.clock(), run.QUICK_FAILURES_LIMIT - 2
    launcher._note_exit(big)
    assert big.next_start - launcher.clock() == min(run.BACKOFF_MAX, run.BACKOFF_FIRST * 2 ** 3)


def test_when_one_child_gives_up_everything_is_stopped_and_the_launcher_says_so(config, repo, world):
    def on_sleep(w):
        if w.now > 10 and w.processes["api"][-1].returncode is None:
            w.processes["api"][-1].die(1)

    world.on_sleep = on_sleep
    assert go(make_launcher(config, repo, world)) == run.EXIT_FAILED
    assert "giving up on it" in world.text and "Stopping what was started." in world.text and world.killed == [world.last("ui")]
    assert not os.path.exists(os.path.join(config.data_dir, run.STATE_NAME))


def test_the_heartbeat_is_written_and_everything_is_cleared_when_it_ends(config, repo, world):
    seen = []

    def on_sleep(w):
        path = os.path.join(config.data_dir, run.STATE_NAME)
        if os.path.exists(path) and not seen:
            seen.append(json.load(open(path)))
            open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    go(make_launcher(config, repo, world))
    assert seen and seen[0]["launcher"] is True and set(seen[0]["children"]) == {"api", "ui"} and "heartbeat" in seen[0]
    assert not os.path.exists(os.path.join(config.data_dir, run.STATE_NAME)) and not os.path.exists(os.path.join(config.data_dir, run.STOP_NAME))


def test_the_launcher_can_be_seen_and_stopped_while_it_is_still_waiting_for_the_api(config, repo, world):
    world.api_comes_up = False
    seen = []

    def on_sleep(w):
        beat = run.launcher_beat(config.data_dir, lambda: NOW + timedelta(seconds=w.now))
        seen.append(beat is not None)
        if len(seen) == 3:
            assert run.ask_to_stop(config, data_dir=config.data_dir, now=lambda: NOW + timedelta(seconds=w.now), out=lambda line: None) == run.EXIT_OK

    world.on_sleep = on_sleep
    assert go(make_launcher(config, repo, world)) == run.EXIT_OK
    assert seen == [True, True, True] and world.killed == [world.last("api")]


def test_a_stale_stop_note_from_an_earlier_run_does_not_stop_a_new_one(config, repo, world):
    open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")
    ticks = []

    def on_sleep(w):
        ticks.append(w.now)
        if w.now >= 20:
            open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    go(make_launcher(config, repo, world))
    assert world.now >= 20 and ticks


def test_stopping_stops_the_ui_first_and_the_api_last_and_only_those(config, repo, world):
    stop_after(world, config, 4)
    go(make_launcher(config, repo, world))
    assert world.killed == [world.last("ui"), world.last("api")]


def test_stopping_does_not_touch_a_child_that_was_not_started_by_it(config, repo, world):
    world.api_up = True
    stop_after(world, config, 4)
    go(make_launcher(config, repo, world))
    assert world.killed == [world.last("ui")]


def test_ctrl_c_stops_what_was_started_and_is_a_clean_exit(config, repo, world):
    def on_sleep(w):
        if w.now >= 6:
            raise KeyboardInterrupt

    world.on_sleep = on_sleep
    assert go(make_launcher(config, repo, world)) == run.EXIT_OK
    assert world.killed == [world.last("ui"), world.last("api")]


def test_a_process_that_is_already_gone_is_not_killed_again(config, repo, world):
    def on_sleep(w):
        if w.now >= 6:
            w.last("ui").die(0)
            open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    go(make_launcher(config, repo, world))
    assert world.killed == [world.last("api")]


# ---- the log never holds a new token ---------------------------------------------------------------------------------------------

def test_a_new_token_is_shown_on_the_terminal_and_never_written_to_the_log(config, repo, world):
    world.api_lines = ["starting up", BANNER, f"    {SECRET}", "listening"]
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world)
    go(launcher)
    finish_reading(launcher)
    log = log_text(config, "api")
    assert SECRET not in log and "starting up" in log and "listening" in log and "(the new access token was here" in log
    assert f"    {SECRET}" in world.printed and BANNER in world.printed


def test_with_save_token_the_token_is_written_to_the_ui_file_and_not_printed(config, repo, world):
    world.api_lines = [BANNER, f"    {SECRET}"]
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world, save_the_token=True)
    go(launcher)
    finish_reading(launcher)
    assert (repo / "frontend" / ".env.local").read_text() == f"DIYA_TOKEN={SECRET}\n"
    assert SECRET not in world.text and SECRET not in log_text(config, "api")
    assert "saved to" in world.text and os.path.join("frontend", ".env.local") in world.text


def test_a_token_that_cannot_be_saved_is_shown_once_so_it_is_not_lost(config, repo, world):
    world.api_lines = [BANNER, f"    {SECRET}"]
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world, save_the_token=True)
    (repo / "frontend" / ".env.local").mkdir()  # a folder where the file should be
    go(launcher)
    finish_reading(launcher)
    assert "could not be saved" in world.text and SECRET in world.text and SECRET not in log_text(config, "api")


def test_the_ui_log_is_copied_as_it_is(config, repo, world):
    world.ui_lines = ["ready", "compiled"]
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world)
    go(launcher)
    finish_reading(launcher)
    assert log_text(config, "ui").splitlines() == ["ready", "compiled"]


# ---- status and stop --------------------------------------------------------------------------------------------------------------

def write_state(config, seconds_ago):
    beat = NOW - timedelta(seconds=seconds_ago)
    with open(os.path.join(config.data_dir, run.STATE_NAME), "w") as handle:
        json.dump({"launcher": True, "heartbeat": beat.isoformat(), "children": {}}, handle)


def test_status_says_what_answers_and_whether_a_launcher_looks_after_it(config, world):
    shown = []
    write_state(config, 3)
    code = run.status(config, api=lambda c: True, ui=lambda c: True, now=lambda: NOW, data_dir=config.data_dir, out=shown.append)
    assert code == run.EXIT_OK and shown == ["API  (port 8080): answering", "UI   (port 3000): answering", "Launcher: running, and looking after what it started"]


def test_status_with_a_stale_heartbeat_says_no_launcher_and_that_something_else_started_what_answers(config, world):
    shown = []
    write_state(config, 60)
    code = run.status(config, api=lambda c: True, ui=lambda c: False, now=lambda: NOW, data_dir=config.data_dir, out=shown.append)
    assert code == run.EXIT_FAILED and shown[2] == "Launcher: none running; what answers above was started some other way" and shown[1] == "UI   (port 3000): not answering"


def test_status_with_nothing_at_all(config, world):
    shown = []
    code = run.status(config, api=lambda c: False, ui=lambda c: False, now=lambda: NOW, data_dir=config.data_dir, out=shown.append)
    assert code == run.EXIT_FAILED and shown[2] == "Launcher: none running" and "not answering" in shown[0]


def test_status_counts_a_note_unreadable_as_no_launcher(config, world):
    open(os.path.join(config.data_dir, run.STATE_NAME), "w").write("not json")
    assert run.launcher_beat(config.data_dir, lambda: NOW) is None
    open(os.path.join(config.data_dir, run.STATE_NAME), "w").write('{"heartbeat": "yesterday"}')
    assert run.launcher_beat(config.data_dir, lambda: NOW) is None
    open(os.path.join(config.data_dir, run.STATE_NAME), "w").write("[1]")
    assert run.launcher_beat(config.data_dir, lambda: NOW) is None


def test_the_heartbeat_is_fresh_for_ten_seconds_and_not_a_moment_more(config, world):
    write_state(config, 10)
    assert run.launcher_beat(config.data_dir, lambda: NOW) is not None
    write_state(config, 11)
    assert run.launcher_beat(config.data_dir, lambda: NOW) is None


def test_stop_leaves_a_note_for_a_running_launcher(config, world):
    shown = []
    write_state(config, 2)
    assert run.ask_to_stop(config, data_dir=config.data_dir, now=lambda: NOW, out=shown.append) == run.EXIT_OK
    assert open(os.path.join(config.data_dir, run.STOP_NAME)).read() == "stop\n" and "Asked the launcher to stop" in shown[0]


def test_stop_with_no_launcher_running_leaves_everything_alone_and_says_so(config, world):
    shown = []
    assert run.ask_to_stop(config, data_dir=config.data_dir, now=lambda: NOW, out=shown.append) == run.EXIT_OK
    assert not os.path.exists(os.path.join(config.data_dir, run.STOP_NAME)) and "No launcher is running" in shown[0] and "left alone" in shown[0]
    write_state(config, 120)  # a launcher that died leaves a note behind
    run.ask_to_stop(config, data_dir=config.data_dir, now=lambda: NOW, out=shown.append)
    assert not os.path.exists(os.path.join(config.data_dir, run.STOP_NAME))


# ---- registering -----------------------------------------------------------------------------------------------------------------

class Powershell:
    def __init__(self, stdout="registered: Diya_Run\n", returncode=0, stderr="", raises=None):
        self.calls = []
        self.stdout, self.returncode, self.stderr, self.raises = stdout, returncode, stderr, raises

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def test_install_runs_the_constant_script_with_the_paths_in_the_environment(tmp_path):
    ps, shown = Powershell(), []
    code = run.install(repo=str(tmp_path / "r e p o"), with_jobs=False, run=ps, platform="win32", out=shown.append)
    argv, kwargs = ps.calls[0]
    assert code == run.EXIT_OK and argv[:5] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"] and argv[-1] == run.INSTALL_SCRIPT
    assert kwargs["env"]["DIYA_RUN_DIR"] == str(tmp_path / "r e p o") and kwargs["env"]["DIYA_RUN_WITH_JOBS"] == "0" and os.path.isfile(kwargs["env"]["DIYA_RUN_PYTHONW"])  # pythonw.exe on Windows when it is there, else the running Python: a file either way
    assert str(tmp_path) not in run.INSTALL_SCRIPT and "registered: Diya_Run" in shown and any("--uninstall" in line for line in shown)


def test_install_with_jobs_says_so_in_the_environment(tmp_path):
    ps = Powershell()
    run.install(repo=str(tmp_path), with_jobs=True, run=ps, platform="win32", out=lambda line: None)
    assert ps.calls[0][1]["env"]["DIYA_RUN_WITH_JOBS"] == "1"


def test_the_install_script_registers_only_what_is_missing_and_runs_the_right_files():
    script = run.INSTALL_SCRIPT
    assert "Get-ScheduledTask -TaskName $name" in script and "exists: $name" in script and "Unregister" not in script and "-Force" not in script
    assert "'diya_run.py'" in script and "'diya_notify.py'" in script and "'dreaming.py'" in script
    assert "-AtLogOn" in script and "PT" not in script and "-Minutes 5" in script and "-Minutes 30" in script and "-Minutes 15" in script
    assert script.index("if ($withJobs)") < script.index("'diya_notify.py'") < script.index("'dreaming.py'")
    assert script.index("'diya_run.py'") < script.index("if ($withJobs)")


def test_the_install_script_takes_nothing_from_a_command_line_and_prints_no_secret():
    for text in (run.INSTALL_SCRIPT, run.UNINSTALL_SCRIPT):
        assert "TOKEN" not in text.upper().replace("DIYA_RUN", "") and "passcode" not in text.lower()


def test_install_reports_a_powershell_failure_without_a_traceback(tmp_path):
    shown = []
    code = run.install(repo=str(tmp_path), run=Powershell(returncode=1, stderr="Access is denied"), platform="win32", out=shown.append)
    assert code == run.EXIT_FAILED and shown == ["Could not register: PowerShell said: Access is denied"]
    shown.clear()
    assert run.install(repo=str(tmp_path), run=Powershell(raises=subprocess.TimeoutExpired("x", 60)), platform="win32", out=shown.append) == run.EXIT_FAILED
    assert run.install(repo=str(tmp_path), run=Powershell(raises=FileNotFoundError("no powershell")), platform="win32", out=shown.append) == run.EXIT_FAILED


def test_install_on_another_system_says_it_is_not_implemented_and_runs_nothing(tmp_path):
    ps, shown = Powershell(), []
    assert run.install(repo=str(tmp_path), run=ps, platform="linux", out=shown.append) == run.EXIT_UNUSABLE and run.uninstall(run=ps, platform="darwin", out=shown.append) == run.EXIT_UNUSABLE
    assert ps.calls == [] and len(shown) == 2


def test_uninstall_removes_only_the_logon_task():
    ps, shown = Powershell(stdout="removed: Diya_Run\n"), []
    assert run.uninstall(run=ps, platform="win32", out=shown.append) == run.EXIT_OK
    script = ps.calls[0][0][-1]
    assert script == run.UNINSTALL_SCRIPT and script.count("Unregister-ScheduledTask") == 1 and "'Diya_Run'" in script
    for other in ("Diya_Notify", "Diya_Dreaming"):
        assert other not in script
    assert shown == ["removed: Diya_Run"]


def test_uninstall_reports_a_failure(tmp_path):
    shown = []
    assert run.uninstall(run=Powershell(returncode=1, stderr="no"), platform="win32", out=shown.append) == run.EXIT_FAILED and shown[0].startswith("Could not remove it")


# ---- the command line ------------------------------------------------------------------------------------------------------------

def test_two_actions_at_once_is_refused_and_unknown_flags_are_a_usage_error(config):
    shown = []
    assert run.main(["--check", "--stop"], out=shown.append, config=config) == run.EXIT_UNUSABLE and "Choose one of" in shown[0]
    assert run.main(["--no-such-flag"], out=shown.append, config=config) == 2


def test_help_exits_cleanly(config):
    assert run.main(["--help"], out=lambda line: None, config=config) == 0


def test_check_prints_each_problem_and_the_count(config, monkeypatch):
    shown = []
    monkeypatch.setattr(run, "check", lambda c: [("a thing is wrong", "do this")])
    assert run.main(["--check"], out=shown.append, config=config) == run.EXIT_UNUSABLE
    assert shown == ["a thing is wrong. To fix it: do this.", "1 thing(s) to fix."]


def test_check_with_nothing_wrong_says_so(config, monkeypatch):
    shown = []
    monkeypatch.setattr(run, "check", lambda c: [])
    assert run.main(["--check"], out=shown.append, config=config) == run.EXIT_OK and shown == ["Nothing is wrong."]


def test_status_and_stop_are_routed(config, monkeypatch):
    called = []
    monkeypatch.setattr(run, "status", lambda c, out=print: called.append("status") or 7)
    monkeypatch.setattr(run, "ask_to_stop", lambda c, out=print: called.append("stop") or 8)
    assert (run.main(["--status"], out=print, config=config), run.main(["--stop"], out=print, config=config)) == (7, 8)
    assert called == ["status", "stop"]


def test_install_and_uninstall_are_routed(config, monkeypatch):
    seen = []
    monkeypatch.setattr(run, "install", lambda with_jobs=False, run=None, platform=None, out=print: seen.append(("install", with_jobs)) or 3)
    monkeypatch.setattr(run, "uninstall", lambda run=None, platform=None, out=print: seen.append(("uninstall",)) or 4)
    assert run.main(["--install", "--with-jobs"], config=config) == 3 and run.main(["--uninstall"], config=config) == 4
    assert seen == [("install", True), ("uninstall",)]


def test_with_no_flag_it_builds_a_launcher_from_the_flags_and_runs_it(config):
    built = {}

    class Fake:
        def __init__(self, cfg, out=print, save_the_token=False, lan=False):
            built.update(config=cfg, save=save_the_token, lan=lan)

        def run(self):
            return 42

    assert run.main(["--save-token", "--lan"], config=config, launcher_factory=Fake) == 42
    assert built == {"config": config, "save": True, "lan": True}
    assert run.main([], config=config, launcher_factory=Fake) == 42 and built["save"] is False and built["lan"] is False


def test_a_bad_setting_is_one_line_and_exit_two(monkeypatch):
    shown = []
    monkeypatch.setenv("DIYA_PORT", "not-a-number")
    assert run.main(["--status"], out=shown.append) == run.EXIT_UNUSABLE and shown[0].startswith("diya_run: ") and len(shown) == 1


def test_it_creates_the_data_folder_so_the_logs_and_notes_have_somewhere_to_go(tmp_path, monkeypatch):
    target = tmp_path / "newdata"
    monkeypatch.setenv("DIYA_DATA_DIR", str(target))
    monkeypatch.setattr(run, "status", lambda c, out=print: 0)
    assert run.main(["--status"], out=print) == 0 and target.is_dir()


# ---- the edges: each of these is a way the code could be wrong without any test above noticing -----------------------------------

def test_a_request_goes_out_with_the_loopback_context_and_the_timeout_it_was_given(monkeypatch):
    seen = {}

    class Reply:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url, timeout=None, context=None):
        seen.update(url=url, timeout=timeout, context=context)
        return Reply()

    monkeypatch.setattr(run.urllib.request, "urlopen", fake_urlopen)
    assert run.probe_http("https://127.0.0.1:1/x", timeout=7.5) == 204
    assert seen["timeout"] == 7.5 and seen["context"].verify_mode == run.ssl.CERT_NONE and seen["context"].check_hostname is False
    mine = object()
    run.probe_http("https://127.0.0.1:1/x", context=mine)
    assert seen["context"] is mine


def test_the_loopback_context_does_not_verify_and_nothing_else_about_it_is_odd():
    context = run._loopback_context()
    assert context.verify_mode == run.ssl.CERT_NONE and context.check_hostname is False and isinstance(context, run.ssl.SSLContext)


def test_ollama_names_survive_a_trailing_slash_and_odd_answers(config, monkeypatch):
    asked = []
    run.ollama_models(dataclasses.replace(config, ollama_url="http://example.test:1/v1/"), probe_json=lambda url: asked.append(url) or [])
    run.ollama_models(dataclasses.replace(config, ollama_url="http://example.test:1/"), probe_json=lambda url: asked.append(url) or [])
    run.ollama_models(dataclasses.replace(config, ollama_url="http://example.test:1/v1-extra"), probe_json=lambda url: asked.append(url) or [])
    assert asked == ["http://example.test:1/api/tags", "http://example.test:1/api/tags", "http://example.test:1/v1-extra/api/tags"]

    def answering(body):
        monkeypatch.setattr(run.urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(body.encode("utf-8")))
        return run.ollama_models(config)

    assert answering('{"models": [{"name": "a:latest"}, {"name": "b"}]}') == ["a:latest", "b"]
    assert answering("{}") == [] and answering('{"models": []}') == []
    assert answering("not json") is None and answering('{"models": [{"nom": "x"}]}') is None and answering('{"models": null}') is None


def test_no_models_at_all_is_each_model_missing_not_ollama_being_down(config, repo):
    problems = checked(config, repo, models=lambda c: [])
    assert [p[0] for p in problems] == ["the chat model 'diya-chat' is not in Ollama", "the embedding model 'nomic-embed-text' is not in Ollama", "the privacy model 'qwen2.5:3b' is not in Ollama"]


def test_the_certificate_is_looked_for_in_the_repo_not_the_working_folder(config, repo, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    os.chdir(other)
    assert checked(config, repo) == []
    for name in ("localhost+2.pem", "localhost+2-key.pem"):
        (repo / name).unlink()
    (other / "localhost+2.pem").write_text("c")
    (other / "localhost+2-key.pem").write_text("k")
    assert len(checked(config, repo)) == 1


def test_the_pythonw_swap_does_not_depend_on_capitals(tmp_path):
    (tmp_path / "python.exe").write_text("")
    assert run.python_for_children(str(tmp_path / "PythonW.EXE")) == str(tmp_path / "python.exe")
    assert run.python_for_children(str(tmp_path / "python3.exe")) == str(tmp_path / "python3.exe")


def test_with_no_argument_the_python_that_is_running_is_used(monkeypatch):
    monkeypatch.setattr(run.sys, "executable", "/some/other/python")
    assert run.python_for_children() == "/some/other/python"


def test_stopping_a_process_tree_uses_taskkill_on_windows_and_terminate_elsewhere(monkeypatch):
    calls = []
    monkeypatch.setattr(run.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)))
    process = FakeProcess()
    monkeypatch.setattr(run.sys, "platform", "win32")
    run._kill_tree(process)
    assert calls[0][0] == ["taskkill", "/PID", str(process.pid), "/T", "/F"] and calls[0][1]["capture_output"] is True and calls[0][1]["timeout"] == 15
    terminated = []
    process.terminate = lambda: terminated.append(True)
    monkeypatch.setattr(run.sys, "platform", "linux")
    run._kill_tree(process)
    assert terminated == [True] and len(calls) == 1


def test_stopping_never_raises_whatever_goes_wrong(monkeypatch):
    def broken(argv, **kw):
        raise RuntimeError("anything at all")

    monkeypatch.setattr(run.subprocess, "run", broken)
    monkeypatch.setattr(run.sys, "platform", "win32")
    run._kill_tree(FakeProcess())


def test_children_are_started_with_their_output_piped_as_utf8_text_and_without_a_window(config, repo, world):
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world)
    go(launcher)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    for kwargs in world.popen_kwargs:
        assert kwargs["stdout"] == subprocess.PIPE and kwargs["stderr"] == subprocess.STDOUT and kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace" and kwargs["creationflags"] == flags
    finish_reading(launcher)
    assert all(child.reader.daemon for child in launcher.children)


def test_a_saved_token_is_said_in_one_exact_line_and_the_banner_is_still_shown_once(config, repo, world):
    world.api_lines = [BANNER, f"    {SECRET}"]
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world, save_the_token=True)
    go(launcher)
    finish_reading(launcher)
    saved = [line for line in world.printed if "access token" in line and "saved" in line]
    assert saved == [f"The API made a new access token and it was saved to {os.path.join('frontend', '.env.local')}. Restart the UI if it was already running."]
    assert world.printed.count(BANNER) == 1 and (repo / "frontend" / ".env.local").read_text() == f"DIYA_TOKEN={SECRET}\n"


def test_an_unsaved_token_is_shown_in_the_line_that_says_why(config, repo, world):
    world.api_lines = [BANNER, f"    {SECRET}"]
    stop_after(world, config, 4)
    launcher = make_launcher(config, repo, world, save_the_token=True)
    (repo / "frontend" / ".env.local").mkdir()
    go(launcher)
    finish_reading(launcher)
    (line,) = [line for line in world.printed if "could not be saved" in line]
    assert line.startswith("The API made a new access token, but it could not be saved (") and line.endswith(f"It is shown only once: {SECRET}")


def test_the_wait_for_an_answer_is_made_of_polls_of_the_poll_length(config, repo, world):
    world.api_comes_up = False
    go(make_launcher(config, repo, world))
    assert set(world.sleeps) == {run.POLL_SECONDS} and len(world.sleeps) == int(run.READY_WAIT_SECONDS / run.POLL_SECONDS)


def test_a_child_is_started_again_exactly_when_its_wait_is_over(config, repo, world):
    launcher = make_launcher(config, repo, world)
    deaths = []

    def on_sleep(w):
        ui = w.processes["ui"][-1]
        if ui.returncode is None and len(w.processes["ui"]) <= 3 and w.now - launcher.children[1].started_at >= 3:
            ui.die(1)
            deaths.append(w.now)
        if len(w.processes["ui"]) >= 4:
            open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    go(launcher)
    starts = [at for name, at in world.start_times if name == "ui"]
    # the death is noticed at the top of the next pass (the fake clock does not move in between), and the wait (2 s, then 4 s, then 8 s) counts from that
    assert [round(start - died) for start, died in zip(starts[1:], deaths)] == [2, 4, 8]


def test_a_run_of_exactly_the_quick_time_is_not_quick(config, repo):
    launcher = make_launcher(config, repo, World(config.data_dir))
    launcher.out = lambda line: None
    for lived, expected in ((run.QUICK_SECONDS - 0.5, 1), (run.QUICK_SECONDS, 0), (run.QUICK_SECONDS + 0.5, 0)):
        child = run.Child("ui", [], "", None)
        child.quick_failures = 0
        child.started_at = launcher.clock()
        launcher.clock = lambda lived=lived, start=child.started_at: start + lived
        child.process = FakeProcess(returncode=1)
        launcher._note_exit(child)
        assert child.quick_failures == expected
        launcher.clock = lambda: 0.0


def test_one_more_quick_failure_after_a_long_run_does_not_carry_the_old_count(config, repo):
    launcher = make_launcher(config, repo, World(config.data_dir))
    launcher.out = lambda line: None
    child = run.Child("ui", [], "", None)
    child.quick_failures, child.started_at = run.QUICK_FAILURES_LIMIT - 1, -100.0
    child.process = FakeProcess(returncode=1)
    launcher._note_exit(child)
    assert child.quick_failures == 0 and child.gave_up is False
    child.started_at = 0.0
    child.quick_failures = run.QUICK_FAILURES_LIMIT - 1
    child.process = FakeProcess(returncode=1)
    launcher._note_exit(child)
    assert child.quick_failures == run.QUICK_FAILURES_LIMIT and child.gave_up is True


def test_a_heartbeat_from_the_future_is_not_a_launcher(config, world):
    write_state(config, -3600)
    assert run.launcher_beat(config.data_dir, lambda: NOW) is None
    write_state(config, -5)
    assert run.launcher_beat(config.data_dir, lambda: NOW) is not None  # a clock a few seconds off is fine
    open(os.path.join(config.data_dir, run.STATE_NAME), "w").write("{}")
    assert run.launcher_beat(config.data_dir, lambda: NOW) is None


def test_install_falls_back_to_the_running_python_when_pythonw_is_missing(tmp_path, monkeypatch):
    (tmp_path / "python.exe").write_text("")
    monkeypatch.setattr(run.sys, "executable", str(tmp_path / "python.exe"))
    ps = Powershell()
    run.install(repo=str(tmp_path), run=ps, platform="win32", out=lambda line: None)
    assert ps.calls[0][1]["env"]["DIYA_RUN_PYTHONW"] == str(tmp_path / "python.exe")
    (tmp_path / "pythonw.exe").write_text("")
    run.install(repo=str(tmp_path), run=ps, platform="win32", out=lambda line: None)
    assert ps.calls[1][1]["env"]["DIYA_RUN_PYTHONW"] == str(tmp_path / "pythonw.exe")


def test_install_gives_powershell_a_minute_and_no_window(tmp_path):
    ps = Powershell()
    run.install(repo=str(tmp_path), run=ps, platform="win32", out=lambda line: None)
    kwargs = ps.calls[0][1]
    assert kwargs["timeout"] == 60 and kwargs["capture_output"] is True and kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_the_install_script_pins_what_it_must_say():
    script = run.INSTALL_SCRIPT
    assert 'if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Write-Output "exists: $name"; return }' in script
    assert "-ExecutionTimeLimit (New-TimeSpan -Seconds 0)" in script and script.count("-MultipleInstances IgnoreNew") == 3
    assert "$notify = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)" in script
    assert "$dream = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)" in script
    assert "-ExecutionTimeLimit (New-TimeSpan -Minutes 5)" in script and "-ExecutionTimeLimit (New-TimeSpan -Minutes 15)" in script
    assert "Register-Once 'Diya_Run' 'diya_run.py' $logon $run" in script and "-WorkingDirectory $dir" in script and "-Execute $pythonw" in script
    assert "$withJobs = $env:DIYA_RUN_WITH_JOBS -eq '1'" in script and "$dir = $env:DIYA_RUN_DIR" in script and "$pythonw = $env:DIYA_RUN_PYTHONW" in script
    assert "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries" in script and "-StartWhenAvailable" in script


def test_a_data_folder_that_cannot_be_made_is_one_line_and_exit_two(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("DIYA_DATA_DIR", str(blocker / "inside"))
    shown = []
    assert run.main(["--status"], out=shown.append) == run.EXIT_UNUSABLE and len(shown) == 1 and shown[0].startswith("diya_run: ")


def test_the_usage_error_exit_code_is_the_parsers(config):
    assert run.main(["--check", "--status", "--stop"], out=lambda line: None, config=config) == run.EXIT_UNUSABLE
    assert run.main(["--uninstall", "--install"], out=lambda line: None, config=config, platform="linux") == run.EXIT_UNUSABLE


def test_with_no_data_folder_the_notes_and_logs_go_in_the_repo_folder(tmp_path, repo):
    bare = dataclasses.replace(diya_config.Config(), data_dir="")
    launcher = run.Launcher(bare, repo=str(repo), out=lambda line: None)
    assert launcher.folder == str(repo) and launcher.state_path == os.path.join(str(repo), run.STATE_NAME) and launcher.stop_path == os.path.join(str(repo), run.STOP_NAME)
    assert run.Launcher(dataclasses.replace(bare, data_dir=str(tmp_path / "d")), repo=str(repo)).folder == str(tmp_path / "d")
    shown = []
    assert run.ask_to_stop(bare, repo=str(repo), out=shown.append) == run.EXIT_OK and "No launcher is running" in shown[0]
    (repo / run.STATE_NAME).write_text(json.dumps({"heartbeat": datetime.now(timezone.utc).isoformat()}))
    run.ask_to_stop(bare, repo=str(repo), out=shown.append)
    assert (repo / run.STOP_NAME).exists()
    seen = []
    run.status(bare, repo=str(repo), api=lambda c: False, ui=lambda c: False, out=seen.append)
    assert seen[2] == "Launcher: running, and looking after what it started"


def test_the_heartbeat_it_writes_by_itself_is_one_status_reads_as_fresh(config, repo, world):
    seen = []

    def on_sleep(w):
        seen.append(run.launcher_beat(config.data_dir, lambda: datetime.now(timezone.utc)))
        open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    launcher = run.Launcher(config, repo=str(repo), popen=world.popen, api=world.api, ui=world.ui, clock=world.clock, sleep=world.sleep, out=world.out,
                            which=lambda name: "node", kill=world.kill, python="python.exe", data_dir=config.data_dir)
    go(launcher)
    assert seen and seen[0] is not None


def test_a_note_that_cannot_be_written_does_not_stop_the_launcher(config, repo, world):
    os.makedirs(os.path.join(config.data_dir, run.STATE_NAME))  # a folder where the note should be
    stop_after(world, config, 6)
    launcher = make_launcher(config, repo, world)
    assert go(launcher) == run.EXIT_OK and "Diya is running" in world.text


def test_blank_lines_from_powershell_are_not_repeated(tmp_path):
    shown = []
    run.install(repo=str(tmp_path), run=Powershell(stdout="registered: Diya_Run\n\n   \nexists: Diya_Notify\n"), platform="win32", out=shown.append)
    assert shown[:2] == ["registered: Diya_Run", "exists: Diya_Notify"] and len(shown) == 3


def test_powershell_errors_are_cut_short_but_not_too_short(tmp_path):
    shown = []
    run.install(repo=str(tmp_path), run=Powershell(returncode=1, stderr="x" * 1000), platform="win32", out=shown.append)
    assert shown == ["Could not register: PowerShell said: " + "x" * 300]


def test_a_log_exactly_at_its_limit_is_rotated_and_one_a_byte_under_is_not(tmp_path):
    path = tmp_path / "x.log"
    path.write_bytes(b"a" * 19 + b"\n")  # 20 bytes
    run.RotatingLog(str(path), limit=20, keep=3).write("new")
    assert (tmp_path / "x.log.1").read_bytes() == b"a" * 19 + b"\n" and path.read_text() == "new\n"
    other = tmp_path / "y.log"
    other.write_bytes(b"a" * 18 + b"\n")  # 19 bytes
    run.RotatingLog(str(other), limit=20, keep=3).write("new")
    assert not (tmp_path / "y.log.1").exists()


def test_a_log_keeps_exactly_the_number_of_files_it_was_told_to(tmp_path):
    for keep in (2, 3, 4):
        folder = tmp_path / f"keep{keep}"
        folder.mkdir()
        log = run.RotatingLog(str(folder / "x.log"), limit=5, keep=keep)
        for number in range(12):
            log.write(f"line-{number:02d}")
        assert sorted(p.name for p in folder.iterdir()) == ["x.log"] + [f"x.log.{n}" for n in range(1, keep)]
        assert "line-11" in (folder / "x.log").read_text() and "line-10" in (folder / "x.log.1").read_text()


def test_a_log_is_written_with_unix_line_endings_even_on_windows(tmp_path):
    log = run.RotatingLog(str(tmp_path / "x.log"))
    log.write("one")
    log.write("two")
    assert (tmp_path / "x.log").read_bytes() == b"one\ntwo\n"


def test_a_socket_error_is_nothing_answering_and_so_is_a_nonsense_address(monkeypatch):
    def timing_out(url, timeout=None, context=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(run.urllib.request, "urlopen", timing_out)
    assert run.probe_http("https://127.0.0.1:1/x") is None
    monkeypatch.undo()
    assert run.probe_http("nonsense without a scheme") is None


def test_the_real_ollama_request_goes_to_the_tags_route(config, monkeypatch):
    asked = []

    def fake(url, timeout=None):
        asked.append((url, timeout))
        return io.BytesIO(b'{"models": []}')

    monkeypatch.setattr(run.urllib.request, "urlopen", fake)
    assert run.ollama_models(config) == [] and asked == [("http://localhost:11434/api/tags", 5)]


def test_children_get_the_environment_the_launcher_has_so_their_settings_reach_them(config, repo, world, monkeypatch):
    monkeypatch.setenv("DIYA_AUTO_MEMORY", "1")
    stop_after(world, config, 4)
    go(make_launcher(config, repo, world))
    assert all(env["DIYA_AUTO_MEMORY"] == "1" and env["PATH"] == os.environ["PATH"] for _, _, _, env in world.started)


def test_a_closed_pipe_ends_the_reader_quietly(config, repo, world):
    launcher = make_launcher(config, repo, world)
    child = run.Child("ui", [], "", run.RotatingLog(os.path.join(config.data_dir, "logs", "ui.log")))
    process = FakeProcess(["one"])
    process.stdout.close()
    launcher._read(child, process)  # must not raise: a closed file is a ValueError
    broken = FakeProcess()

    class Bad:
        def readline(self):
            raise OSError("pipe broke")

    broken.stdout = Bad()
    launcher._read(child, broken)


def test_the_heartbeat_moves_on_while_it_is_running_and_it_is_looked_at_every_poll(config, repo, world):
    beats = []

    def on_sleep(w):
        if "Diya is running" in w.text:
            beats.append(json.load(open(os.path.join(config.data_dir, run.STATE_NAME)))["heartbeat"])
        if len(beats) >= 4:
            open(os.path.join(config.data_dir, run.STOP_NAME), "w").write("stop\n")

    world.on_sleep = on_sleep
    go(make_launcher(config, repo, world))
    assert len(beats) == 4 and len(set(beats)) == 4 and beats == sorted(beats)
    assert set(world.sleeps) == {run.POLL_SECONDS}


def test_uninstall_reports_every_way_powershell_can_fail_without_a_traceback():
    for failure in (subprocess.TimeoutExpired("x", 60), FileNotFoundError("no powershell"), PermissionError("denied")):
        shown = []
        assert run.uninstall(run=Powershell(raises=failure), platform="win32", out=shown.append) == run.EXIT_FAILED and shown[0].startswith("Could not remove it: ")


def test_powershell_is_given_the_environment_it_needs_as_well_as_the_two_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_MARKER_FOR_THE_TEST", "present")
    ps = Powershell()
    run.install(repo=str(tmp_path), run=ps, platform="win32", out=lambda line: None)
    run.uninstall(run=ps, platform="win32", out=lambda line: None)
    assert all(call[1]["env"]["SOME_MARKER_FOR_THE_TEST"] == "present" and call[1]["env"]["PATH"] == os.environ["PATH"] for call in ps.calls)


def test_the_uninstall_script_checks_before_it_removes_and_names_only_its_own_task():
    script = run.UNINSTALL_SCRIPT
    assert "if (Get-ScheduledTask -TaskName 'Diya_Run' -ErrorAction SilentlyContinue) {" in script
    assert "Unregister-ScheduledTask -TaskName 'Diya_Run' -Confirm:$false" in script and "*" not in script and "absent: Diya_Run" in script


# ---- what is checked in ----------------------------------------------------------------------------------------------------------

def test_the_ui_command_is_the_one_in_the_package_scripts():
    scripts = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["dev"] == "node tools/next-tls.mjs dev" and scripts["dev:lan"] == "node tools/next-tls.mjs dev --lan"
    assert (ROOT / "frontend" / "tools" / "next-tls.mjs").exists()


def test_what_the_launcher_writes_when_there_is_no_data_folder_is_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"/logs/", run.STATE_NAME, run.STOP_NAME} <= set(ignored)
