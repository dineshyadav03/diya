"""Tell the person a reminder has come due, outside the app (docs/PROACTIVITY_DESIGN.md, D5 and unit P4).

    python diya_notify.py            one pass: a desktop notification for each reminder that has come due and has not
                                     been told yet; each is told once
    python diya_notify.py --dry-run  say what it would tell; tell nothing and record nothing
    python diya_notify.py --test     show one notification that says nothing about your reminders, to see whether
                                     they work here

One pass and never a loop, like Dreaming: run it on a schedule (docs/reminders.md). Nothing here registers itself and
nothing is installed. It reads the reminders in diya.db and, per reminder, shows a Windows notification and then records
that it did (`notified_at`). Notify first and record second means a crash in between can tell a reminder twice, never
zero times: for a reminder, once too often is the better mistake.

The reminder's words go to the notification through environment variables, never into the PowerShell script, so a
reminder that contains quotes, `$(...)` or anything else a script would act on is only ever text. They are shown through
printable(), so a control or direction-changing character in one is a visible escape, not itself.

If many reminders come due at once (a computer that was off for a day), the first few are shown one by one and the rest
as a single "N more are due" notification, so the desktop is never flooded; every one of them is still on the Reminders
page. `DIYA_NOTIFY_SHOW_TEXT=0` shows "A reminder is due" instead of the words, for a screen other people can see.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
from datetime import datetime, timezone

import diya_config
import diya_time
from diya_db import Store
from diya_memory import printable

MAX_NOTIFICATIONS = 5  # in one pass: the first four one by one, then one that stands for the rest
TITLE_CHARS, BODY_CHARS = 60, 200
TIMEOUT_SECONDS = 20
EXIT_OK, EXIT_SOME_FAILED, EXIT_UNUSABLE = 0, 1, 2

# The whole of the PowerShell that runs: a constant. Nothing a person or a model wrote is ever put into it.
TOAST_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode($env:DIYA_TOAST_TITLE)) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode($env:DIYA_TOAST_BODY)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""


class NotifyError(RuntimeError):
    """A notification could not be shown. Says why, in a line that is safe to log."""


@dataclasses.dataclass(frozen=True)
class Report:
    due: int  # reminders that had come due and had not been told
    told: int  # of those, how many were told (a summary notification counts the ones it stands for)
    failed: int  # how many notifications could not be shown; those are tried again next time


def notify_windows(title, body):
    """Show a Windows notification. Raises NotifyError if it could not be shown."""
    env = {**os.environ, "DIYA_TOAST_TITLE": title, "DIYA_TOAST_BODY": body}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flashing up when run from a scheduled task
    try:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", TOAST_SCRIPT],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS, creationflags=flags,
        )
    except FileNotFoundError:
        raise NotifyError("powershell.exe was not found") from None
    except subprocess.TimeoutExpired:
        raise NotifyError(f"the notification took more than {TIMEOUT_SECONDS} seconds") from None
    except OSError as exc:
        raise NotifyError(printable(f"could not start powershell.exe: {exc}", 200)) from None
    if done.returncode != 0:
        raise NotifyError(printable(f"powershell exited with {done.returncode}: {done.stderr.strip()}", 300))


def _words(reminder, show_text):
    if not show_text:
        return "Diya", "A reminder is due"
    when = reminder["due_ts"] and diya_time.describe_local(diya_time.local_from_iso(reminder["due_ts"]))
    return printable(f"Diya: {when}" if when else "Diya reminder", TITLE_CHARS), printable(reminder["content"], BODY_CHARS)


def run_once(store, notify, now=None, show_text=True, dry_run=False, say=print):
    """One pass over the reminders that have come due and have not been told. `notify(title, body)` shows one
    notification or raises NotifyError; a reminder is recorded as told only after it did, so a failure is tried again
    on the next pass. `say(line)` is told what happened (never a reminder's words unless `dry_run`)."""
    now_ts = diya_time.iso_of_local(datetime.now() if now is None else now)
    due = store.due_reminders(now_ts, unnotified_only=True)
    told = failed = 0
    singles, rest = (due, []) if len(due) <= MAX_NOTIFICATIONS else (due[: MAX_NOTIFICATIONS - 1], due[MAX_NOTIFICATIONS - 1:])
    for reminder in singles:
        title, body = _words(reminder, show_text)
        if dry_run:
            say(f"would tell: {title} | {body}")
            continue
        try:
            notify(title, body)
        except NotifyError as exc:
            failed += 1
            say(f"could not tell about reminder {reminder['id']}: {exc}")
            continue
        store.mark_notified(reminder["id"])
        told += 1
    if rest:
        title, body = "Diya", f"{len(rest)} more reminders are due. Open the Reminders page to see them."
        if dry_run:
            say(f"would tell: {title} | {body}")
        else:
            try:
                notify(title, body)
            except NotifyError as exc:
                failed += 1
                say(f"could not tell about {len(rest)} more reminders: {exc}")
            else:
                for reminder in rest:
                    store.mark_notified(reminder["id"])
                told += len(rest)
    return Report(due=len(due), told=told, failed=failed)


def _log_line(config, line):
    """One line in the log, with the time. Ids and counts only: never a reminder's words."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(config.notify_log_path, "a", encoding="utf-8", newline="\n") as log:
            log.write(f"{stamp} {line}\n")
    except OSError:
        pass  # a log that cannot be written must not undo a notification that was shown, or stop the pass


def build_parser():
    parser = argparse.ArgumentParser(prog="diya_notify.py", description="Tell you about reminders that have come due.")
    parser.add_argument("--dry-run", action="store_true", help="say what would be told; tell nothing and record nothing")
    parser.add_argument("--test", action="store_true", help="show one notification that says nothing about your reminders")
    return parser


def main(argv=None, config=None, out=None, notify=None, now=None):
    out = sys.stdout if out is None else out
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse has said what was wrong; a --help is a success
        return exc.code if isinstance(exc.code, int) else EXIT_UNUSABLE
    try:
        config = config or diya_config.load_config()
    except diya_config.ConfigError as exc:
        print(f"diya_notify: {exc}", file=out)
        return EXIT_UNUSABLE
    if notify is None:
        if sys.platform != "win32":
            print("diya_notify: desktop notifications are only implemented for Windows here.", file=out)
            return EXIT_UNUSABLE
        notify = notify_windows
    if args.test:
        try:
            notify("Diya", "Notifications work here. This says nothing about your reminders.")
        except NotifyError as exc:
            print(f"diya_notify: could not show a notification: {exc}", file=out)
            return EXIT_SOME_FAILED
        print("Showed a test notification.", file=out)
        return EXIT_OK
    lines = []

    def say(line):
        lines.append(line)
        print(line, file=out)

    try:
        report = run_once(Store(config.db_path), notify, now=now, show_text=config.notify_show_text, dry_run=args.dry_run, say=say)
    except Exception as exc:  # an unreadable database: say so once and leave everything as it was
        print(f"diya_notify: could not read the reminders: {printable(exc, 200)}", file=out)
        if not args.dry_run:
            _log_line(config, f"error: {printable(type(exc).__name__)}")
        return EXIT_UNUSABLE
    summary = f"{report.due} due, {report.told} told, {report.failed} failed"
    if args.dry_run:
        print(f"Dry run: {summary}; nothing was told or recorded.", file=out)
        return EXIT_OK
    if report.due or report.failed:
        _log_line(config, summary)
        for line in lines:
            if line.startswith("could not"):
                _log_line(config, printable(line.split(":", 1)[0]) + " (" + printable(line.split(":", 1)[-1].strip(), 120) + ")")
    print(summary + ".", file=out)
    return EXIT_SOME_FAILED if report.failed else EXIT_OK


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
