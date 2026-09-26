"""The desktop notifier (docs/PROACTIVITY_DESIGN.md, D5 and unit P4): diya_notify.py.

What this proves: each reminder that has come due is told once, soonest first, and only after the notification was
shown (a failure is tried again on the next pass, and one failure does not stop the others); reminders that are not
due, have no time, are finished or were already told are left alone; a flood of due reminders is shown as a few
notifications and one that stands for the rest; what reaches PowerShell is a constant script plus the reminder's words
in environment variables, so nothing a reminder says can be run; the words shown are made safe and can be hidden
entirely; the command line reports and exits as it says; the log holds ids and counts and never a reminder's words;
and importing the module does nothing.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
import io
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

import diya_config
import diya_notify
import diya_time
from diya_db import Store
from diya_notify import MAX_NOTIFICATIONS, NotifyError, run_once

NOW = datetime(2026, 9, 23, 10, 15)
ESC, BIDI, ZWSP = chr(27), chr(0x202E), chr(0x200B)
ROOT = pathlib.Path(__file__).resolve().parent.parent


def ts(hours=0.0):
    return diya_time.iso_of_local(NOW + timedelta(hours=hours))


class Screen:
    """A stand-in for the notification: records what would be shown, and fails on the attempts it is told to."""

    def __init__(self, failing=()):
        self.shown, self.failing, self.attempts = [], set(failing), 0

    def __call__(self, title, body):
        self.attempts += 1
        if self.attempts in self.failing:  # the n-th attempt, counting failures too
            raise NotifyError("the screen is not there")
        self.shown.append((title, body))


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "n.db"))


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "n.db"), notify_log_path=str(tmp_path / "notify.log"))


def said():
    lines = []
    return lines, lines.append


# --- who is told, and when ------------------------------------------------------------------------------------

def test_each_due_reminder_is_told_once_soonest_first_and_recorded(store):
    later, sooner = store.add_reminder("later one", "x", ts(-1)), store.add_reminder("sooner one", "x", ts(-3))
    screen = Screen()
    report = run_once(store, screen, now=NOW)
    assert (report.due, report.told, report.failed) == (2, 2, 0)
    assert [body for _, body in screen.shown] == ["sooner one", "later one"]
    assert store.get_reminder(sooner)["notified_at"] and store.get_reminder(later)["notified_at"]
    again = Screen()
    assert run_once(store, again, now=NOW) == diya_notify.Report(0, 0, 0) and again.shown == []  # once


def test_reminders_that_are_not_due_have_no_time_are_finished_or_were_told_are_left_alone(store):
    store.add_reminder("future", "x", ts(2))
    store.add_reminder("no time")
    finished = store.add_reminder("finished", "x", ts(-2))
    store.complete_reminder(finished)
    told = store.add_reminder("told", "x", ts(-2))
    store.mark_notified(told)
    words_only = store.add_reminder("from before", "Friday 5pm")
    screen = Screen()
    assert run_once(store, screen, now=NOW).due == 0 and screen.shown == []
    assert store.get_reminder(words_only)["notified_at"] is None


def test_a_reminder_due_exactly_now_is_told_and_one_a_minute_from_now_is_not(store):
    store.add_reminder("now", "x", ts(0))
    store.add_reminder("a minute away", "x", ts(1 / 60))
    screen = Screen()
    run_once(store, screen, now=NOW)
    assert [body for _, body in screen.shown] == ["now"]


def test_a_reminder_that_could_not_be_told_is_not_recorded_and_is_tried_again(store):
    a, b, c = (store.add_reminder(name, "x", ts(-h)) for name, h in (("a", 3), ("b", 2), ("c", 1)))
    lines, say = said()
    screen = Screen(failing={2})  # the second attempt fails
    report = run_once(store, screen, now=NOW, say=say)
    assert (report.due, report.told, report.failed) == (3, 2, 1)
    assert [body for _, body in screen.shown] == ["a", "c"]  # one failure did not stop the next
    assert store.get_reminder(b)["notified_at"] is None and store.get_reminder(a)["notified_at"] and store.get_reminder(c)["notified_at"]
    assert lines == [f"could not tell about reminder {b}: the screen is not there"]
    retry = Screen()
    assert run_once(store, retry, now=NOW).told == 1 and [body for _, body in retry.shown] == ["b"]


def test_a_dry_run_says_what_it_would_tell_and_tells_and_records_nothing(store):
    rid = store.add_reminder("call mum", "x", ts(-1))
    lines, say = said()
    screen = Screen()
    report = run_once(store, screen, now=NOW, dry_run=True, say=say)
    assert (report.due, report.told, report.failed) == (1, 0, 0) and screen.shown == []
    assert lines == ["would tell: Diya: Wednesday 23 Sep 2026, 09:15 | call mum"]
    assert store.get_reminder(rid)["notified_at"] is None


# --- what is shown ----------------------------------------------------------------------------------------------------

def test_the_notification_says_when_it_was_due_and_what_for(store):
    store.add_reminder("call mum", "x", ts(-1))
    screen = Screen()
    run_once(store, screen, now=NOW)
    assert screen.shown == [("Diya: Wednesday 23 Sep 2026, 09:15", "call mum")]


def test_the_words_can_be_hidden_and_then_never_reach_the_screen(store):
    store.add_reminder("see the doctor about the thing", "x", ts(-1))
    screen = Screen()
    run_once(store, screen, now=NOW, show_text=False)
    assert screen.shown == [("Diya", "A reminder is due")]


def test_hidden_characters_are_shown_as_escapes_and_long_words_are_cut(store):
    store.add_reminder("call" + ESC + "[2J mum" + BIDI + "evil" + ZWSP + "x", "x", ts(-1))
    store.add_reminder("y" * 500, "x", ts(-0.5))
    screen = Screen()
    run_once(store, screen, now=NOW)
    first, second = screen.shown
    assert all(ch.isprintable() for ch in first[1]) and chr(92) + "u001b" in first[1] and chr(92) + "u202e" in first[1]
    assert len(second[1]) <= diya_notify.BODY_CHARS + 3 and second[1].endswith("...")
    assert all(len(title) <= diya_notify.TITLE_CHARS + 3 for title, _ in screen.shown)


# --- a flood ------------------------------------------------------------------------------------------------------------

def test_many_due_at_once_are_a_few_notifications_and_one_that_stands_for_the_rest(store):
    ids = [store.add_reminder(f"r{n}", "x", ts(-10 + n)) for n in range(7)]
    screen = Screen()
    report = run_once(store, screen, now=NOW)
    assert (report.due, report.told, report.failed) == (7, 7, 0)
    assert [body for _, body in screen.shown][: MAX_NOTIFICATIONS - 1] == ["r0", "r1", "r2", "r3"]
    assert screen.shown[-1] == ("Diya", "3 more reminders are due. Open the Reminders page to see them.")
    assert len(screen.shown) == MAX_NOTIFICATIONS
    assert all(store.get_reminder(i)["notified_at"] for i in ids)  # the summary stands for them


def test_exactly_the_limit_is_shown_one_by_one_with_no_summary(store):
    for n in range(MAX_NOTIFICATIONS):
        store.add_reminder(f"r{n}", "x", ts(-10 + n))
    screen = Screen()
    run_once(store, screen, now=NOW)
    assert [body for _, body in screen.shown] == [f"r{n}" for n in range(MAX_NOTIFICATIONS)]


def test_a_summary_that_could_not_be_shown_leaves_the_rest_to_be_told_next_time(store):
    ids = [store.add_reminder(f"r{n}", "x", ts(-10 + n)) for n in range(7)]
    lines, say = said()
    screen = Screen(failing={5})  # the fifth attempt is the summary
    report = run_once(store, screen, now=NOW, say=say)
    assert (report.due, report.told, report.failed) == (7, 4, 1)
    assert lines == ["could not tell about 3 more reminders: the screen is not there"]
    assert [bool(store.get_reminder(i)["notified_at"]) for i in ids] == [True] * 4 + [False] * 3
    retry = Screen()
    run_once(store, retry, now=NOW)
    assert [body for _, body in retry.shown] == ["r4", "r5", "r6"]  # three now: one by one


# --- what reaches PowerShell --------------------------------------------------------------------------------------------

class FakeRun:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error
        return self.result or subprocess.CompletedProcess(argv, 0, "", "")


HOSTILE = "'; Remove-Item -Recurse -Force C:\\ #" + ' $(calc.exe) `whoami` "quoted" ' + chr(0x1F525)


def test_the_script_is_a_constant_and_the_words_travel_only_in_the_environment(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    diya_notify.notify_windows("Diya: " + HOSTILE, HOSTILE)
    ((argv, kwargs),) = fake.calls
    assert argv[:5] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"] and argv[5] == "-Command"
    assert argv[6] == diya_notify.TOAST_SCRIPT and len(argv) == 7
    assert "$env:DIYA_TOAST_TITLE" in argv[6] and "$env:DIYA_TOAST_BODY" in argv[6]
    assert not any("Remove-Item" in part or "calc.exe" in part for part in argv)  # nothing of the words is in the command
    assert kwargs["env"]["DIYA_TOAST_TITLE"] == "Diya: " + HOSTILE and kwargs["env"]["DIYA_TOAST_BODY"] == HOSTILE
    assert kwargs["timeout"] == diya_notify.TIMEOUT_SECONDS and kwargs["capture_output"] is True


def test_the_script_has_no_placeholders_and_names_the_powershell_app_id():
    script = diya_notify.TOAST_SCRIPT
    assert "{0}" not in script and "%s" not in script
    assert "ToastText02" in script and "CreateTextNode($env:DIYA_TOAST_TITLE)" in script
    assert "WindowsPowerShell" in script and "powershell.exe" in script


def test_the_environment_of_the_caller_is_kept_and_the_console_stays_hidden(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setenv("SOME_SETTING", "kept")
    diya_notify.notify_windows("t", "b")
    kwargs = fake.calls[0][1]
    assert kwargs["env"]["SOME_SETTING"] == "kept"
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


@pytest.mark.parametrize("error, says", [
    (FileNotFoundError(), "powershell.exe was not found"),
    (subprocess.TimeoutExpired("powershell.exe", 20), "took more than 20 seconds"),
    (PermissionError("denied"), "could not start powershell.exe"),
])
def test_a_powershell_that_cannot_run_is_a_notify_error_that_says_why(monkeypatch, error, says):
    monkeypatch.setattr(subprocess, "run", FakeRun(error=error))
    with pytest.raises(NotifyError, match=says):
        diya_notify.notify_windows("t", "b")


def test_a_powershell_that_fails_is_a_notify_error_with_what_it_said_made_safe(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(result=subprocess.CompletedProcess([], 1, "", "boom" + ESC + "[2J " + "z" * 900)))
    with pytest.raises(NotifyError) as failure:
        diya_notify.notify_windows("t", "b")
    message = str(failure.value)
    assert message.startswith("powershell exited with 1: boom") and all(ch.isprintable() for ch in message) and len(message) < 400


# --- the command line ---------------------------------------------------------------------------------------------------------

def run_main(config, *argv, notify=None, now=NOW):
    out = io.StringIO()
    code = diya_notify.main(list(argv), config=config, out=out, notify=notify if notify is not None else Screen(), now=now)
    return code, out.getvalue()


def test_a_pass_tells_what_is_due_reports_and_logs_ids_and_counts_only(config):
    store = Store(config.db_path)
    rid = store.add_reminder("SECRET WORDS about the doctor", "x", ts(-1))
    screen = Screen()
    code, out = run_main(config, notify=screen)
    assert (code, out) == (0, "1 due, 1 told, 0 failed.\n") and screen.shown[0][1] == "SECRET WORDS about the doctor"
    log = pathlib.Path(config.notify_log_path).read_text(encoding="utf-8")
    assert log.endswith(" 1 due, 1 told, 0 failed\n") and "SECRET" not in log and "doctor" not in log
    assert store.get_reminder(rid)["notified_at"]


def test_a_pass_with_nothing_due_says_so_and_writes_no_log(config):
    Store(config.db_path).add_reminder("later", "x", ts(5))
    code, out = run_main(config)
    assert (code, out) == (0, "0 due, 0 told, 0 failed.\n") and not pathlib.Path(config.notify_log_path).exists()


def test_a_failure_exits_1_and_the_log_names_the_reminder_without_its_words(config):
    store = Store(config.db_path)
    rid = store.add_reminder("SECRET WORDS", "x", ts(-1))
    code, out = run_main(config, notify=Screen(failing={1}))
    assert code == 1 and "1 due, 0 told, 1 failed." in out and f"could not tell about reminder {rid}" in out
    log = pathlib.Path(config.notify_log_path).read_text(encoding="utf-8")
    assert "1 due, 0 told, 1 failed" in log and f"could not tell about reminder {rid}" in log and "SECRET" not in log
    assert store.get_reminder(rid)["notified_at"] is None


def test_a_dry_run_from_the_command_line_changes_nothing_and_writes_no_log(config):
    store = Store(config.db_path)
    rid = store.add_reminder("call mum", "x", ts(-1))
    screen = Screen()
    code, out = run_main(config, "--dry-run", notify=screen)
    assert code == 0 and "would tell: Diya: Wednesday 23 Sep 2026, 09:15 | call mum" in out and out.endswith("Dry run: 1 due, 0 told, 0 failed; nothing was told or recorded.\n")
    assert screen.shown == [] and store.get_reminder(rid)["notified_at"] is None and not pathlib.Path(config.notify_log_path).exists()


def test_the_test_flag_shows_one_notification_that_says_nothing_about_reminders_and_touches_no_database(config):
    screen = Screen()
    code, out = run_main(config, "--test", notify=screen)
    assert (code, out) == (0, "Showed a test notification.\n")
    assert screen.shown == [("Diya", "Notifications work here. This says nothing about your reminders.")]
    assert not pathlib.Path(config.db_path).exists()
    code, out = run_main(config, "--test", notify=Screen(failing={1}))
    assert code == 1 and "could not show a notification" in out


def test_the_words_can_be_hidden_by_the_setting(config):
    Store(config.db_path).add_reminder("private matter", "x", ts(-1))
    screen = Screen()
    run_main(dataclasses.replace(config, notify_show_text=False), notify=screen)
    assert screen.shown == [("Diya", "A reminder is due")]


def test_an_unreadable_database_is_reported_once_and_nothing_is_told(config, monkeypatch):
    def broken(self, *args, **kwargs):
        raise RuntimeError("database disk image is malformed")

    monkeypatch.setattr(Store, "due_reminders", broken)
    screen = Screen()
    code, out = run_main(config, notify=screen)
    assert code == 2 and "could not read the reminders" in out and screen.shown == []
    assert "error: RuntimeError" in pathlib.Path(config.notify_log_path).read_text(encoding="utf-8")


def test_a_log_that_cannot_be_written_does_not_stop_the_pass(config, tmp_path):
    Store(config.db_path).add_reminder("call mum", "x", ts(-1))
    screen = Screen()
    code, out = run_main(dataclasses.replace(config, notify_log_path=str(tmp_path)), notify=screen)  # a folder, not a file
    assert code == 0 and out == "1 due, 1 told, 0 failed.\n" and len(screen.shown) == 1


def test_off_windows_it_says_so_instead_of_pretending(config, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    out = io.StringIO()
    assert diya_notify.main([], config=config, out=out) == 2
    assert "only implemented for Windows" in out.getvalue()


def test_a_bad_setting_or_argument_is_a_usage_error_not_a_crash(monkeypatch):
    monkeypatch.setenv("DIYA_NOTIFY_SHOW_TEXT", "sometimes")
    out = io.StringIO()
    assert diya_notify.main([], out=out, notify=Screen()) == 2 and "DIYA_NOTIFY_SHOW_TEXT" in out.getvalue()
    monkeypatch.delenv("DIYA_NOTIFY_SHOW_TEXT")
    assert diya_notify.main(["--nonsense"], out=io.StringIO(), notify=Screen()) == 2


# --- settings, the ignore file, and what importing does ---------------------------------------------------------------------

def test_the_two_settings_have_their_defaults_and_their_environment_names():
    assert diya_config.load_config({}).notify_show_text is True and diya_config.load_config({}).notify_log_path == "notify_log.txt"
    cfg = diya_config.load_config({"DIYA_NOTIFY_SHOW_TEXT": "0", "DIYA_NOTIFY_LOG_PATH": "n.log"})
    assert (cfg.notify_show_text, cfg.notify_log_path) == (False, "n.log")
    assert diya_config.load_config({"DIYA_NOTIFY_SHOW_TEXT": "yes"}).notify_show_text is True
    with pytest.raises(diya_config.ConfigError, match="DIYA_NOTIFY_SHOW_TEXT"):
        diya_config.load_config({"DIYA_NOTIFY_SHOW_TEXT": "maybe"})


def test_the_notifiers_log_is_ignored_by_git_like_the_other_runtime_logs():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "notify_log.txt" in ignored and "dream_log.txt" in ignored


def test_importing_the_notifier_does_nothing_and_needs_no_model_or_server(run_python):
    result = run_python(
        "import sys, diya_notify\n"
        "print(sorted(name for name in ('openai', 'chromadb', 'fastapi', 'httpx') if name in sys.modules))\n"
    )
    assert result.returncode == 0 and result.stdout.strip() == "[]", result.stdout + result.stderr
