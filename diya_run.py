"""One command that starts Diya (docs/ONE_COMMAND_DESIGN.md, units O1 and O2).

    python diya_run.py                 check, then start the API and the UI and keep them running; Ctrl+C stops what it started
    python diya_run.py --check         say what is wrong, if anything; start nothing
    python diya_run.py --status        say what is running and whether a launcher is looking after it; start nothing
    python diya_run.py --stop          ask a running launcher to stop what it started
    python diya_run.py --save-token    if the API makes a NEW access token, save it to frontend/.env.local (otherwise it is shown once, on the terminal)
    python diya_run.py --lan           start the UI the way `npm run dev:lan` does (it insists on a passcode)
    python diya_run.py --install       register a Windows task that runs this at logon; with --with-jobs, also the notifier and Dreaming if they are missing
    python diya_run.py --uninstall     remove the logon task this command registered (and only that one)

It does what a person does by hand, and no more: `python diya_web.py` and `npm run dev` (the same script, the same certificate rule), their output kept in a log in the
data folder instead of two terminals. It never prints, logs or passes on a command line the access token or the UI passcode (the UI reads its own `.env.local`; the
one line the API prints a NEW token on is kept out of the log). It never starts a second copy of something that already answers, never stops a process it did not start,
and never registers a task unless asked to with --install.

Everything that touches the world (starting a process, probing a port, the clock, PowerShell) is passed in, so the whole of it is tested without starting anything.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import diya_config

REPO = os.path.dirname(os.path.abspath(__file__))
POLL_SECONDS = 2.0
HEARTBEAT_FRESH_SECONDS = 10.0  # a launcher that has not written for this long is taken to be gone
QUICK_SECONDS = 30.0  # a child that ran for less than this and died has failed quickly
QUICK_FAILURES_LIMIT = 5
BACKOFF_FIRST, BACKOFF_MAX = 2.0, 60.0
READY_WAIT_SECONDS = 180.0  # the API loads a speech model before it listens, and the first start downloads it
LOG_LIMIT_BYTES, LOG_KEEP = 1_000_000, 3
STATE_NAME, STOP_NAME, TASK_NAME = "diya_run.json", "diya_run.stop", "Diya_Run"
EXIT_OK, EXIT_FAILED, EXIT_UNUSABLE = 0, 1, 2
TOKEN_BANNER = "A new access token was generated"  # what diya_web.py prints, on one line, just before the token on the next

# The whole of the PowerShell that registers: a constant. The two paths reach it through environment variables, never through the text of the script.
INSTALL_SCRIPT = """
$ErrorActionPreference = 'Stop'
$dir = $env:DIYA_RUN_DIR
$pythonw = $env:DIYA_RUN_PYTHONW
$withJobs = $env:DIYA_RUN_WITH_JOBS -eq '1'
function Register-Once($name, $arguments, $trigger, $settings) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Write-Output "exists: $name"; return }
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $dir
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings | Out-Null
    Write-Output "registered: $name"
}
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$run = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Register-Once 'Diya_Run' 'diya_run.py' $logon $run
if ($withJobs) {
    $notify = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
    $notifySettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-Once 'Diya_Notify' 'diya_notify.py' $notify $notifySettings
    $dream = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
    $dreamSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    Register-Once 'Diya_Dreaming' 'dreaming.py' $dream $dreamSettings
}
"""
UNINSTALL_SCRIPT = """
$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName 'Diya_Run' -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName 'Diya_Run' -Confirm:$false
    Write-Output 'removed: Diya_Run'
} else {
    Write-Output 'absent: Diya_Run'
}
"""


class RunError(RuntimeError):
    """Something could not be done; says what, in a line safe to print."""


# ---- the log, and keeping a new token out of it ----------------------------------------------------------------------------------

class RotatingLog:
    """A text log that starts a new file when it gets big, keeping the last few (name, name.1, name.2...)."""

    def __init__(self, path, limit=LOG_LIMIT_BYTES, keep=LOG_KEEP):
        self.path, self.limit, self.keep = path, limit, keep
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def write(self, line):
        with self._lock:
            try:
                if os.path.exists(self.path) and os.path.getsize(self.path) >= self.limit:
                    self._rotate()
                with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line.rstrip("\n") + "\n")
            except OSError:
                pass  # a log that cannot be written must not stop Diya

    def _rotate(self):
        for number in range(self.keep - 2, 0, -1):  # name.1 becomes name.2 and so on; moving onto the oldest overwrites it, so `keep` files are left
            if os.path.exists(f"{self.path}.{number}"):
                os.replace(f"{self.path}.{number}", f"{self.path}.{number + 1}")
        os.replace(self.path, f"{self.path}.1")


class TokenFilter:
    """Reads the API's output a line at a time and says what may be logged. The API prints a NEW access token once, on the line after a banner: that line is held back
    (the log says it was shown on the terminal), and handed to whoever asked for it. Nothing else is changed."""

    def __init__(self):
        self._expecting = False
        self.token = None

    def feed(self, line):
        """(the line to log, the line to show on the terminal or None, True when `line` was the token)."""
        stripped = line.strip()
        if self._expecting and stripped:
            self._expecting = False
            self.token = stripped
            return "    (the new access token was here: shown on the terminal once, never kept in this log)", line, True
        if TOKEN_BANNER in line:
            self._expecting = True
            return line, line, False
        return line, None, False


def save_token(path, token):
    """Write `DIYA_TOKEN=<token>` into the UI's settings file (frontend/.env.local), replacing a DIYA_TOKEN line that is there and keeping every other line. The one place
    this program writes a secret, and only when asked."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    kept = [line for line in lines if not line.lstrip().startswith("DIYA_TOKEN=")]
    kept.append(f"DIYA_TOKEN={token}")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(kept) + "\n")


# ---- looking ---------------------------------------------------------------------------------------------------------------------

def _loopback_context():
    """Diya's own certificate is one the person made for this computer (mkcert), which Python does not trust by itself. Used only for requests to this computer's own
    loopback address, and never to carry anything secret."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def probe_http(url, timeout=3.0, context=None):
    """The HTTP status the address answers with (an error status counts: 401 is an answer), or None if nothing answers."""
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context or _loopback_context()) as reply:
            return reply.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def api_answers(config, probe=probe_http):
    """Does Diya's API answer on its port? A request with no token is REFUSED (401) by an API that is up, and that refusal is the proof: no route is left open to be asked."""
    return probe(f"https://127.0.0.1:{config.port}/api/threads") in (200, 401)


def ui_answers(config, probe=probe_http):
    """Does the UI answer on its port? Any HTTP answer will do: the sign-in page, or a redirect to it."""
    return probe(f"https://localhost:{config.frontend_port}/login") is not None


def ollama_models(config, probe_json=None):
    """The names of the models Ollama has, or None if it does not answer."""
    base = config.ollama_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    try:
        if probe_json is not None:
            return probe_json(base + "/api/tags")
        with urllib.request.urlopen(base + "/api/tags", timeout=5) as reply:
            return [model["name"] for model in json.load(reply).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        return None


def has_model(names, wanted):
    """Is `wanted` among Ollama's model names? "diya-chat" is "diya-chat:latest"."""
    return any(name == wanted or name == f"{wanted}:latest" for name in names)


# ---- the checks ------------------------------------------------------------------------------------------------------------------

def check(config, repo=REPO, which=shutil.which, models=ollama_models):
    """What is wrong, as (problem, what to do) pairs: an empty list means nothing is. Starts nothing."""
    problems = []
    names = models(config)
    if names is None:
        problems.append((f"Ollama does not answer at {config.ollama_url}", "start Ollama (open the Ollama app, or run `ollama serve`)"))
    else:
        for role, model in (("chat", config.model), ("embedding", config.embed_model), ("privacy", config.privacy_model)):
            if model and not has_model(names, model):
                todo = f"run `ollama pull {model}`" if role != "chat" else f"make it (README) or set DIYA_MODEL to a model you have"
                problems.append((f"the {role} model {model!r} is not in Ollama", todo))
    try:
        if diya_config.tls_files(config, search_dir=repo) is None:
            problems.append(("there is no TLS certificate pair for the API", "make one with mkcert (docs/lan.md)"))
    except diya_config.ConfigError as exc:
        problems.append((str(exc), "fix the certificate settings (docs/lan.md)"))
    if which("node") is None:
        problems.append(("Node.js was not found", "install Node.js 22 or later"))
    if not os.path.isdir(os.path.join(repo, "frontend", "node_modules")):
        problems.append(("the UI's packages are not installed", "run `npm install` in the frontend folder"))
    return problems


# ---- the launcher ----------------------------------------------------------------------------------------------------------------

def python_for_children(executable=None):
    """The Python to run the API with: pythonw.exe (what a scheduled task uses) has no console to print to, so its sibling python.exe is used when there is one."""
    executable = executable or sys.executable
    folder, name = os.path.split(executable)
    if name.lower() == "pythonw.exe" and os.path.exists(os.path.join(folder, "python.exe")):
        return os.path.join(folder, "python.exe")
    return executable


def _kill_tree(process):
    """Stop a process and everything it started (the UI's launcher starts the real server). Never raises."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            process.terminate()
    except Exception:  # noqa: BLE001 -- stopping is best effort, and a process that is already gone is stopped
        pass


@dataclasses.dataclass
class Child:
    name: str
    argv: list
    cwd: str
    log: RotatingLog
    filter: object = None  # a TokenFilter for the API
    process: object = None
    reader: object = None  # the thread copying its output to the log
    started_at: float = 0.0
    quick_failures: int = 0
    next_start: float = 0.0
    gave_up: bool = False


class Launcher:
    """Starts the API and the UI, waits until each answers, and keeps them up. `popen`, `api`, `ui`, `clock`, `sleep` and `now` are the world, passed in."""

    def __init__(self, config, repo=REPO, popen=subprocess.Popen, api=api_answers, ui=ui_answers, clock=time.monotonic, sleep=time.sleep, now=None, out=print,
                 save_the_token=False, lan=False, which=shutil.which, kill=_kill_tree, python=None, data_dir=None):
        self.config, self.repo, self.popen, self.api, self.ui = config, repo, popen, api, ui
        self.clock, self.sleep, self.out, self.which, self.kill = clock, sleep, out, which, kill
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.save_the_token, self.lan = save_the_token, lan
        self.python = python or python_for_children()
        folder = data_dir if data_dir is not None else (config.data_dir or repo)
        self.folder = folder
        self.state_path = os.path.join(folder, STATE_NAME)
        self.stop_path = os.path.join(folder, STOP_NAME)
        self.children = []

    # ---- what to run ----
    def _plan(self, start_api, start_ui):
        children = []
        if start_api:
            children.append(Child("api", [self.python, "diya_web.py"], self.repo, RotatingLog(os.path.join(self.folder, "logs", "api.log")), filter=TokenFilter()))
        if start_ui:
            ui = [self.which("node") or "node", os.path.join("tools", "next-tls.mjs"), "dev"] + (["--lan"] if self.lan else [])
            children.append(Child("ui", ui, os.path.join(self.repo, "frontend"), RotatingLog(os.path.join(self.folder, "logs", "ui.log"))))
        return children

    def _spawn(self, child):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        child.process = self.popen(child.argv, cwd=child.cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                   creationflags=flags)
        child.started_at = self.clock()
        child.reader = threading.Thread(target=self._read, args=(child, child.process), daemon=True)
        child.reader.start()

    def _read(self, child, process):
        """Copy a child's output to its log a line at a time (the new access token, if there is one, is kept out of the log)."""
        try:
            for raw in iter(process.stdout.readline, ""):
                line = raw.rstrip("\n")
                if child.filter is not None:
                    logged, shown, was_token = child.filter.feed(line)
                    child.log.write(logged)
                    if shown is not None:
                        if was_token and self.save_the_token:
                            self._keep_token(child.filter.token)
                        else:
                            self.out(shown)
                else:
                    child.log.write(line)
        except (OSError, ValueError):
            pass  # the pipe closed with the process

    def _keep_token(self, token):
        path = os.path.join(self.repo, "frontend", ".env.local")
        try:
            save_token(path, token)
            self.out(f"The API made a new access token and it was saved to {os.path.relpath(path, self.repo)}. Restart the UI if it was already running.")
        except OSError as exc:
            self.out(f"The API made a new access token, but it could not be saved ({exc}). It is shown only once: {token}")

    # ---- state ----
    def _write_state(self):
        data = {"launcher": True, "heartbeat": self.now().isoformat(), "children": {c.name: {"pid": c.process.pid} for c in self.children if c.process is not None}}
        try:
            with open(self.state_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
        except OSError:
            pass

    def _clear_state(self):
        for path in (self.state_path, self.stop_path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _stop_requested(self):
        return os.path.exists(self.stop_path)

    # ---- running ----
    def run(self, check_first=True, models=ollama_models):
        """Start what is not already running, wait until it answers, and keep it up until asked to stop. Returns an exit code."""
        if check_first:
            problems = check(self.config, repo=self.repo, which=self.which, models=models)
            if problems:
                for problem, todo in problems:
                    self.out(f"Not started: {problem}. To fix it: {todo}.")
                return EXIT_UNUSABLE
        api_up, ui_up = self.api(self.config), self.ui(self.config)
        if api_up:
            self.out(f"The API already answers on port {self.config.port}; leaving it alone.")
        if ui_up:
            self.out(f"The UI already answers on port {self.config.frontend_port}; leaving it alone.")
        self.children = self._plan(not api_up, not ui_up)
        if not self.children:
            self.out("Diya is already running: nothing to start.")
            return EXIT_OK
        self._clear_state()
        try:
            for child in self.children:
                self.out(f"Starting the {child.name}...")
                self._spawn(child)
                if not self._wait_until_it_answers(child):
                    return EXIT_OK if self._stop_requested() else EXIT_FAILED
            self.out(f"Diya is running. Open https://localhost:{self.config.frontend_port} (Ctrl+C here, or `python diya_run.py --stop`, stops what this started).")
            return self._supervise()
        except KeyboardInterrupt:
            return EXIT_OK
        finally:
            self._stop_all()

    def _answers(self, child):
        return self.api(self.config) if child.name == "api" else self.ui(self.config)

    def _wait_until_it_answers(self, child):
        deadline = self.clock() + READY_WAIT_SECONDS
        while self.clock() < deadline:
            self._write_state()  # so --status and --stop can see this launcher while it waits, which can take minutes the first time
            if child.process.poll() is not None:
                self.out(f"The {child.name} stopped while starting (see {os.path.join(self.folder, 'logs', child.name + '.log')}).")
                return False
            if self._answers(child):
                return True
            if self._stop_requested():
                return False
            self.sleep(POLL_SECONDS)
        self.out(f"The {child.name} did not answer within {int(READY_WAIT_SECONDS)} seconds (see {os.path.join(self.folder, 'logs', child.name + '.log')}).")
        return False

    def _supervise(self):
        while not self._stop_requested():
            self._write_state()
            for child in self.children:
                if child.process is not None and child.process.poll() is not None:
                    self._note_exit(child)
                if child.process is None and not child.gave_up and self.clock() >= child.next_start:
                    self.out(f"Starting the {child.name} again...")
                    self._spawn(child)
            if any(child.gave_up for child in self.children):  # half of Diya running, quietly, would be worse than being told
                self.out("Stopping what was started. Look at the log named above, fix what it says, and start again.")
                return EXIT_FAILED
            self.sleep(POLL_SECONDS)
        self.out("Asked to stop.")
        return EXIT_OK

    def _note_exit(self, child):
        lived = self.clock() - child.started_at
        code = child.process.returncode
        child.process = None
        child.quick_failures = child.quick_failures + 1 if lived < QUICK_SECONDS else 0
        if child.quick_failures >= QUICK_FAILURES_LIMIT:
            child.gave_up = True
            self.out(f"The {child.name} exited ({code}) {child.quick_failures} times in a row within {int(QUICK_SECONDS)} seconds; giving up on it. "
                     f"See {os.path.join(self.folder, 'logs', child.name + '.log')}.")
            return
        wait = min(BACKOFF_MAX, BACKOFF_FIRST * (2 ** max(0, child.quick_failures - 1))) if child.quick_failures else BACKOFF_FIRST
        child.next_start = self.clock() + wait
        self.out(f"The {child.name} exited ({code}); starting it again in {int(wait)} seconds.")

    def _stop_all(self):
        for child in reversed(self.children):  # the UI first, the API last: the UI has nothing to talk to without it
            if child.process is not None and child.process.poll() is None:
                self.kill(child.process)
        self._clear_state()


# ---- looking and asking -----------------------------------------------------------------------------------------------------------

def launcher_beat(folder, now):
    """When a launcher last said it was alive, or None if none has in the last few seconds (or the note is unreadable)."""
    try:
        with open(os.path.join(folder, STATE_NAME), encoding="utf-8") as handle:
            beat = datetime.fromisoformat(json.load(handle)["heartbeat"])
        if abs((now() - beat).total_seconds()) <= HEARTBEAT_FRESH_SECONDS:
            return beat
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def status(config, repo=REPO, api=api_answers, ui=ui_answers, now=None, data_dir=None, out=print):
    """Say what is running and whether a launcher is looking after it. Starts and changes nothing."""
    now = now or (lambda: datetime.now(timezone.utc))
    folder = data_dir if data_dir is not None else (config.data_dir or repo)
    launcher = launcher_beat(folder, now)
    api_up, ui_up = api(config), ui(config)
    out(f"API  (port {config.port}): {'answering' if api_up else 'not answering'}")
    out(f"UI   (port {config.frontend_port}): {'answering' if ui_up else 'not answering'}")
    out("Launcher: " + ("running, and looking after what it started" if launcher else "none running" + ("; what answers above was started some other way" if api_up or ui_up else "")))
    return EXIT_OK if api_up and ui_up else EXIT_FAILED


def ask_to_stop(config, repo=REPO, data_dir=None, now=None, out=print):
    """Ask a running launcher to stop what it started, by leaving a note it looks for. Never stops a process itself: it could be the wrong one."""
    now = now or (lambda: datetime.now(timezone.utc))
    folder = data_dir if data_dir is not None else (config.data_dir or repo)
    if launcher_beat(folder, now) is None:
        out("No launcher is running (nothing to stop). Anything that is answering was started some other way, and is left alone.")
        return EXIT_OK
    with open(os.path.join(folder, STOP_NAME), "w", encoding="utf-8") as handle:
        handle.write("stop\n")
    out("Asked the launcher to stop; it looks every couple of seconds.")
    return EXIT_OK


def _powershell(script, env_extra, run=subprocess.run):
    env = {**os.environ, **env_extra}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    done = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script], env=env, capture_output=True, text=True,
               encoding="utf-8", errors="replace", timeout=60, creationflags=flags)
    if done.returncode != 0:
        raise RunError(f"PowerShell said: {done.stderr.strip()[:300]}")
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def install(repo=REPO, with_jobs=False, run=subprocess.run, platform=None, out=print):
    """Register the logon task (and, if asked, the notifier and Dreaming if they are missing; one that exists is never touched)."""
    if (platform or sys.platform) != "win32":
        out("Registering a task is only implemented for Windows here.")
        return EXIT_UNUSABLE
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    pythonw = pythonw if os.path.exists(pythonw) else sys.executable
    try:
        lines = _powershell(INSTALL_SCRIPT, {"DIYA_RUN_DIR": repo, "DIYA_RUN_PYTHONW": pythonw, "DIYA_RUN_WITH_JOBS": "1" if with_jobs else "0"}, run=run)
    except (RunError, OSError, subprocess.TimeoutExpired) as exc:
        out(f"Could not register: {exc}")
        return EXIT_FAILED
    for line in lines:
        out(line)
    out("It runs at your next logon (or now: `python diya_run.py`). Remove it with `python diya_run.py --uninstall`.")
    return EXIT_OK


def uninstall(run=subprocess.run, platform=None, out=print):
    if (platform or sys.platform) != "win32":
        out("Registering a task is only implemented for Windows here.")
        return EXIT_UNUSABLE
    try:
        lines = _powershell(UNINSTALL_SCRIPT, {}, run=run)
    except (RunError, OSError, subprocess.TimeoutExpired) as exc:
        out(f"Could not remove it: {exc}")
        return EXIT_FAILED
    for line in lines:
        out(line)
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="diya_run.py", description="Start Diya: the API and the UI, kept running.")
    parser.add_argument("--check", action="store_true", help="say what is wrong, if anything; start nothing")
    parser.add_argument("--status", action="store_true", help="say what is running; start nothing")
    parser.add_argument("--stop", action="store_true", help="ask a running launcher to stop what it started")
    parser.add_argument("--save-token", action="store_true", help="if the API makes a NEW access token, save it to frontend/.env.local")
    parser.add_argument("--lan", action="store_true", help="start the UI for other devices on the network (needs a passcode)")
    parser.add_argument("--install", action="store_true", help="register a Windows task that runs this at logon")
    parser.add_argument("--with-jobs", action="store_true", help="with --install: also register the notifier and Dreaming, if they are missing")
    parser.add_argument("--uninstall", action="store_true", help="remove the logon task this registered")
    return parser


def main(argv=None, out=print, config=None, launcher_factory=None, run=subprocess.run, platform=None):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_UNUSABLE
    chosen = [name for name in ("check", "status", "stop", "install", "uninstall") if getattr(args, name)]
    if len(chosen) > 1:
        out("Choose one of --check, --status, --stop, --install, --uninstall.")
        return EXIT_UNUSABLE
    if args.uninstall:
        return uninstall(run=run, platform=platform, out=out)
    if args.install:
        return install(with_jobs=args.with_jobs, run=run, platform=platform, out=out)
    try:
        config = config or diya_config.load_config()
        diya_config.ensure_data_dir(config)
    except (diya_config.ConfigError, OSError) as exc:
        out(f"diya_run: {exc}")
        return EXIT_UNUSABLE
    if args.status:
        return status(config, out=out)
    if args.stop:
        return ask_to_stop(config, out=out)
    if args.check:
        problems = check(config)
        for problem, todo in problems:
            out(f"{problem}. To fix it: {todo}.")
        out("Nothing is wrong." if not problems else f"{len(problems)} thing(s) to fix.")
        return EXIT_OK if not problems else EXIT_UNUSABLE
    launcher = (launcher_factory or Launcher)(config, out=out, save_the_token=args.save_token, lan=args.lan)
    return launcher.run()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
