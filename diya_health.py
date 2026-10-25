"""Is Diya well? One honest answer per part, for the Status page (docs/HEALTH_DESIGN.md), added 2026-10-18.

    GET /api/health    {"overall": "ok" | "warn" | "bad", "items": [{"name", "label", "status": "ok" | "warn" | "bad" | "off", "text"}]}

Each item looks at the real thing and says what it saw in a sentence: the database (opens, SQLite's quick check, how much is in it), the chat model (Ollama answers and has the model), the queue of messages
waiting to be read for facts, Dreaming (when it last ran), the connections (which are connected, and any whose sign-in cannot be read here), the newest backup, how sign-ins are stored, and how many tool calls
failed in the last day. Nothing here changes anything, and nothing says "ok" for a thing it did not look at. A part that is switched off says "off", not "ok".

Importing this module has no side effects.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx

import diya_backup
import diya_connectors
import diya_machine
import diya_pause
import diya_resources
import diya_secrets
import diya_warm
from diya_memory import printable

DREAM_STALE_HOURS = 36
BACKUP_STALE_HOURS = 48
PING_TIMEOUT = 2.0


def ping_ollama(config):
    """(reachable, models) from Ollama's own list; ([] and False) when it does not answer."""
    try:
        response = httpx.get(diya_warm.native_address(config.ollama_url) + "/api/tags", timeout=PING_TIMEOUT)
        if response.status_code != 200:
            return False, []
        return True, [str(m.get("name", "")) for m in (response.json().get("models") or []) if isinstance(m, dict)]
    except (httpx.HTTPError, ValueError):
        return False, []


def _ago(hours):
    if hours < 1:
        return "less than an hour ago"
    if hours < 2:
        return "1 hour ago"
    if hours < 48:
        return f"{int(hours)} hours ago"
    return f"{int(hours // 24)} days ago"


def _item(name, label, status, text):
    return {"name": name, "label": label, "status": status, "text": printable(text, 240)}


def _api():
    return _item("api", "Diya's API", "ok", "Running: this page was answered by it.")


def _pause(store):
    paused = diya_pause.state(store)
    if not paused["paused"]:
        return _item("pause", "Pause switch", "ok", "Not paused: approved actions run, automations run, and Diya may write first.")
    why = f" ({paused['reason']})" if paused["reason"] else ""
    return _item("pause", "Pause switch", "warn", f"Paused since {paused['since'][:16].replace('T', ' ')} UTC{why}: approved actions are not run, automations do not run, and Diya does not write first. Reminders still fire.")


def _database(config, store):
    try:
        conn = sqlite3.connect("file:" + os.path.abspath(config.db_path).replace("\\", "/") + "?mode=ro", uri=True)
        try:
            quick = conn.execute("PRAGMA quick_check").fetchone()[0]
            messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            facts = conn.execute("SELECT COUNT(*) FROM facts WHERE status = 'accepted'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _item("database", "Memory (database)", "bad", f"The database could not be read ({exc}).")
    if quick != "ok":
        return _item("database", "Memory (database)", "bad", "SQLite's quick check found a problem with the database. Make a backup, then run: python diya_backup.py verify on the newest one.")
    return _item("database", "Memory (database)", "ok", f"Opens and passes SQLite's quick check. {messages} messages and {facts} remembered facts.")


def _model(config, ping):
    reachable, models = ping(config)
    if not reachable:
        return _item("model", "Chat model", "bad", "Ollama did not answer, so Diya cannot think right now. Start Ollama.")
    wanted = config.model
    if any(name == wanted or name.split(":")[0] == wanted.split(":")[0] and ":" not in wanted for name in models):
        return _item("model", "Chat model", "ok", f"Ollama answered and has {wanted}.")
    return _item("model", "Chat model", "warn", f"Ollama answered but does not list {wanted}. Chat will fail until it is pulled or created.")


def _reading(config, store):
    if not config.auto_memory:
        return _item("reading", "Reading messages for facts", "off", "Automatic memory is off, so nothing is read for facts by itself.")
    backlog = store.capture_backlog()
    pending, failed = backlog.get("pending", 0), backlog.get("failed", 0)
    if failed:
        return _item("reading", "Reading messages for facts", "bad", f"{failed} message(s) could not be read after several tries; {pending} waiting.")
    if pending:
        oldest = store.oldest_pending_capture()
        waited = ""
        try:
            minutes = int((datetime.now(timezone.utc) - datetime.fromisoformat(oldest)).total_seconds() // 60)
            waited = f" The oldest has waited {minutes} minute{'' if minutes == 1 else 's'}." if minutes >= 1 else ""
        except (TypeError, ValueError):
            pass
        return _item("reading", "Reading messages for facts", "warn", f"{pending} message(s) are waiting to be read. They are read in order, one at a time.{waited}")
    return _item("reading", "Reading messages for facts", "ok", f"Nothing is waiting. Since this queue began: {backlog.get('done', 0)} read, {backlog.get('skipped', 0)} not worth reading.")


def _dreaming(config, store, now):
    """When Dreaming last ran, from its own receipts (docs/DREAMING_RECEIPTS_DESIGN.md) and, for a run from before there were receipts, from the log file's time. A last pass that went wrong is said."""
    label = "Dreaming (the nightly tidy-up)"
    last = store.dream_last_run()
    if last is not None:
        try:
            ran = datetime.fromisoformat(last["started_at"]).astimezone().replace(tzinfo=None)
        except ValueError:
            ran = None
    else:
        try:
            ran = datetime.fromtimestamp(os.path.getmtime(config.dream_log_path))
        except OSError:
            return _item("dreaming", label, "warn", "Has not run yet, or its log is not where it is expected.")
    hours = max(0.0, (now - ran).total_seconds() / 3600) if ran is not None else 0.0
    when = _ago(hours)
    if hours > DREAM_STALE_HOURS:
        return _item("dreaming", label, "warn", f"Last ran {when}. If it should run every day, its scheduled task may have stopped.")
    if last is not None and last["errors"]:
        return _item("dreaming", label, "warn", f"Last ran {when} and something went wrong in that pass: see the Activity page. Its checkpoint did not move past what failed, so the next pass tries again.")
    return _item("dreaming", label, "ok", f"Last ran {when}.")


def _connections(config):
    import diya_connector_tools

    connected, unreadable = [], []
    for connector in diya_connector_tools.real_connectors(config):
        if diya_connectors.is_connected(config, connector.name):
            connected.append(connector.label)
        elif os.path.exists(os.path.join(config.connector_tokens_dir, f"{connector.name}.token")):
            unreadable.append(connector.label)
    if unreadable:
        return _item("connections", "Connections", "warn", f"{', '.join(unreadable)}: the stored sign-in cannot be read here (copied from another computer or damaged). Connect again on the Connections page.")
    if not connected:
        return _item("connections", "Connections", "ok", "Nothing is connected, so nothing outside this computer is reachable.")
    return _item("connections", "Connections", "ok", f"Connected: {', '.join(connected)}.")


def _backup(config, now):
    if not config.backup:
        return _item("backup", "Backup of the memory", "off", "Automatic backups are off (DIYA_BACKUP=0). Make one by hand: python diya_backup.py make")
    latest = diya_backup.newest(config)
    if latest is None:
        return _item("backup", "Backup of the memory", "warn", "No backup yet. One is made when the API starts, then once a day, or by hand: python diya_backup.py make")
    hours = diya_backup.age_hours(latest, now)
    when = _ago(hours)
    if hours > BACKUP_STALE_HOURS:
        return _item("backup", "Backup of the memory", "warn", f"The newest backup is {when}. A new one is made while the API runs; if Diya has not been running, start it.")
    return _item("backup", "Backup of the memory", "ok", f"The newest backup was made {when}, and was checked when it was made.")


LOW_MEMORY_GB = 1.0


def _machine(sample, store=None, now=None):
    """Memory free, how busy the processor is, and what Diya's API holds (diya_machine): so that a slow answer can be told from a broken one. A warning when less than a gigabyte of memory is free, because the
    models are then pushed out of memory and every answer gets slow."""
    found = sample()
    text = diya_machine.describe(found)
    if text is None:
        return _item("machine", "This computer", "off", "This system cannot be asked how much memory is free or how busy the processor is.")
    if store is not None:  # what the last day was like, from the numbers written every few minutes (diya_resources)
        looked_back = diya_resources.describe(diya_resources.trend(store, (now or datetime.now(timezone.utc)).astimezone(timezone.utc)))
        if looked_back:
            text += " " + looked_back
    if found["ram_free"] < LOW_MEMORY_GB * diya_machine.GB:
        return _item("machine", "This computer", "warn", text + " Memory is nearly full: close something, or answers will be slow while the model is pushed in and out.")
    return _item("machine", "This computer", "ok", text)


def _seconds(ms):
    return f"{ms / 1000:.0f} s" if ms >= 1000 else "under a second"


def _answers(store, now):
    """How fast answers come and whether they fail, from numbers only (turn_stats: no text is kept): the last 7 days, the middle and the slow end, and the failures. Bad when the last five all failed; a warning
    when three of the last ten did."""
    since = (now.astimezone(timezone.utc) - timedelta(days=7)).isoformat()
    turns = store.turn_stats_since(since)
    if not turns:
        return _item("answers", "How fast answers come", "ok", "No answers have been timed in the last 7 days.")
    worked = sorted(ms for ms, ok in turns if ok)
    failed = sum(1 for _, ok in turns if not ok)
    recent = store.turn_stats_last(10)
    parts = [f"Last 7 days: {len(turns)} answer{'' if len(turns) == 1 else 's'}"]
    if worked:
        median = worked[len(worked) // 2]
        slow = worked[min(len(worked) - 1, int(len(worked) * 0.95))]
        parts.append(f"half took {_seconds(median)} or less, 19 in 20 took {_seconds(slow)} or less")
    parts.append(f"{failed} failed" if failed else "none failed")
    text = "; ".join(parts) + "."
    if len(recent) >= 5 and not any(recent[:5]):
        return _item("answers", "How fast answers come", "bad", text + " The last five did not work: is the chat model running?")
    if len(recent) >= 5 and sum(1 for ok in recent if not ok) >= 3:
        return _item("answers", "How fast answers come", "warn", text + " Three of the last ten did not work.")
    return _item("answers", "How fast answers come", "ok", text)


def _secrets(config):
    if config.protect_secrets and diya_secrets.available():
        return _item("secrets", "Sign-ins at rest", "ok", "Connector sign-ins are stored encrypted for this Windows user.")
    if config.protect_secrets:
        return _item("secrets", "Sign-ins at rest", "warn", "This system cannot encrypt them, so connector sign-ins are stored as plain text in their folder.")
    return _item("secrets", "Sign-ins at rest", "off", "Encryption is switched off (DIYA_PROTECT_SECRETS=0): connector sign-ins are stored as plain text.")


def _tools(store, now):
    since = (now.astimezone(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        counts = store.journal_counts(since)
    except sqlite3.Error:
        return _item("tools", "Tools and accounts", "warn", "The activity record could not be read.")
    failed = counts.get("error", 0)
    total = sum(counts.values())
    if failed:
        return _item("tools", "Tools and accounts", "warn", f"{failed} of {total} tool calls in the last day did not work. See the Activity page.")
    return _item("tools", "Tools and accounts", "ok", f"{total} tool call(s) in the last day, none failed." if total else "No tool calls in the last day.")


def collect(config, store, now=None, ping=ping_ollama, sample=None):
    """Every item, in a fixed order, and the overall state: bad if any is bad, else warn if any is, else ok ("off" counts as nothing)."""
    moment = now or datetime.now()
    parts = (
        ("api", "Diya's API", _api),
        ("pause", "Pause switch", lambda: _pause(store)),
        ("database", "Memory (database)", lambda: _database(config, store)),
        ("model", "Chat model", lambda: _model(config, ping)),
        ("machine", "This computer", lambda: _machine(sample or diya_machine.sample, store, moment)),
        ("reading", "Reading messages for facts", lambda: _reading(config, store)),
        ("dreaming", "Dreaming (the nightly tidy-up)", lambda: _dreaming(config, store, moment)),
        ("connections", "Connections", lambda: _connections(config)),
        ("backup", "Backup of the memory", lambda: _backup(config, moment)),
        ("secrets", "Sign-ins at rest", lambda: _secrets(config)),
        ("tools", "Tools and accounts", lambda: _tools(store, moment)),
        ("answers", "How fast answers come", lambda: _answers(store, moment)),
    )
    items = []
    for name, label, look in parts:
        try:
            items.append(look())
        except Exception as exc:  # noqa: BLE001 -- a report that falls over because a part is broken would hide exactly the part that is
            items.append(_item(name, label, "bad", f"Could not be checked ({type(exc).__name__}: {exc})."))
    states = {item["status"] for item in items}
    return {"overall": "bad" if "bad" in states else "warn" if "warn" in states else "ok", "items": items}
