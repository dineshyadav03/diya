"""Everything Diya holds about you, as plain files you can read and keep (DIYA-214; docs/EXPORT.md), added 2026-10-25.

    python diya_export.py                  write a new folder under exports/ (inside the data folder when there is one)
    python diya_export.py --out FOLDER     write it under FOLDER instead

The folder holds your chats (`messages.jsonl`, and `conversations.md` to read), what Diya remembers about you and when it learned it (`memory.json`, `memory_profile.txt`), your tasks, reminders (one-off and
repeating) and automations, your categories, the replies you rated and your notes, what you asked Diya to do and how it came out (`actions.json`), what Diya did with a tool or an account (`activity.json`), and what
she wrote first (`proactive.json`), plus a `README.txt` that counts them and says what is left out. Left out on purpose, because they are secrets or Diya's own working data and not yours: the access token's
hash, the sign-in tokens of every connection and your Google client secret, the keys of the devices that get notifications, the Telegram bridge's state, the numbers Diya uses to find similar facts, and her own queues
and timings.

It only reads: the database is opened read-only, never migrated, and a database from an older version simply has fewer files. The folder is written beside its final place and moved there whole, so a failed run leaves
nothing half-made, and an export never replaces an earlier one. Invisible and control characters (other than line breaks) are written as visible \\uXXXX escapes, as everywhere else Diya shows your words. Nothing
goes over the network. The files are your private data in the clear: keep them where you keep your own documents, not in a repository (exports/ is ignored by git here).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import diya_config
import diya_memory

EXIT_OK, EXIT_USAGE = 0, 2

# file -> (what it is, the query, the names of its columns). Every query is a plain SELECT.
_JSON = {
    "memory.json": (
        "what Diya remembers about you, every fact with who it is about, where it came from and its history",
        "SELECT f.id, f.text, f.status, f.source, p.name, f.created_at FROM facts f LEFT JOIN people p ON p.id = f.person_id ORDER BY f.id",
        ("id", "text", "status", "source", "person", "created_at"),
    ),
    "tasks.json": ("your tasks", "SELECT id, content, due_at, done, source, created_at, completed_at FROM tasks ORDER BY id", ("id", "content", "due_at", "done", "source", "created_at", "completed_at")),
    "reminders.json": ("your reminders", "SELECT id, content, due_at, done, series_id, created_at, done_at FROM reminders ORDER BY id", ("id", "content", "due_at", "done", "series_id", "created_at", "done_at")),
    "repeating_reminders.json": (
        "your repeating reminders", "SELECT id, content, rule, said, paused, ended, source, created_at, ended_at FROM reminder_series ORDER BY id",
        ("id", "content", "rule", "said", "paused", "ended", "source", "created_at", "ended_at"),
    ),
    "automations.json": (
        "your automations", "SELECT id, instruction, words, rule, state, last_run_at, last_status, runs, created_at FROM automations ORDER BY id",
        ("id", "instruction", "words", "rule", "state", "last_run_at", "last_status", "runs", "created_at"),
    ),
    "categories.json": (
        "the categories and which message is in which", "SELECT m.message_id, c.name, m.source, m.created_at FROM message_categories m JOIN categories c ON c.id = m.category_id ORDER BY m.message_id",
        ("message_id", "category", "source", "created_at"),
    ),
    "feedback.json": (
        "the replies you rated, why, and your notes", "SELECT message_id, rating, category, note, created_at, updated_at FROM reply_feedback ORDER BY message_id",
        ("message_id", "rating", "category", "note", "created_at", "updated_at"),
    ),
    "activity.json": (
        "what Diya did with a tool or an account", "SELECT id, at, tool, kind, origin, thread_id, message_id, args_preview, status, duration_ms, note FROM tool_journal ORDER BY id",
        ("id", "at", "tool", "kind", "origin", "thread_id", "message_id", "args_preview", "status", "duration_ms", "note"),
    ),
    "proactive.json": ("what Diya wrote first", "SELECT id, kind, text, created_at, seen_at FROM proactive_messages ORDER BY id", ("id", "kind", "text", "created_at", "seen_at")),
}
_ACTIONS = ("actions.json", "what you asked Diya to do at a service and how it came out", "SELECT id, kind, args, summary, status, message_id, created_at, decided_at, executed_at, result FROM actions ORDER BY id")
_LEFT_OUT = (
    "the access token's hash and every sign-in token (Google, Gmail, Todoist and the rest), and your Google client secret",
    "the keys of the devices that get notifications, and the Telegram bridge's state",
    "the numbers Diya uses to find similar facts and messages",
    "Diya's own queues, timings and run counts",
)


def _escape_hidden(text):
    """`text` with every control, invisible or direction-changing character other than a line break or a tab written as a visible \\uXXXX escape, so a file cannot show something the data does not say."""
    out = []
    for char in text:
        if char not in "\n\t" and diya_memory._unwanted(char):
            code = ord(char)
            out.append(chr(92) + ("u" + format(code, "04x") if code <= 0xFFFF else "U" + format(code, "08x")))
        else:
            out.append(char)
    return "".join(out)


def _clean(value):
    if isinstance(value, str):
        return _escape_hidden(value)
    if isinstance(value, dict):
        return {_clean(key) if isinstance(key, str) else key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def _rows(conn, sql, columns):
    try:
        return [dict(zip(columns, row)) for row in conn.execute(sql).fetchall()], True
    except sqlite3.OperationalError:  # a table this database does not have (an older version)
        return [], False


def _write_json(folder, name, data):
    (folder / name).write_text(json.dumps(_clean(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _history(conn, table_ok):
    if not table_ok:
        return {}
    try:
        found = {}
        for fact_id, event, actor, at, detail in conn.execute("SELECT fact_id, event, actor, at, detail FROM fact_events ORDER BY id").fetchall():
            found.setdefault(fact_id, []).append({"event": event, "actor": actor, "at": at, "detail": detail})
        return found
    except sqlite3.OperationalError:
        return {}


def _conversations(messages):
    lines = ["# Your chats with Diya", ""]
    current = None
    for message in messages:
        if message["thread_id"] != current:
            current = message["thread_id"]
            title = message["title"] or "(no title)"
            lines += ["", f"## Chat {current}: {_escape_hidden(title)}", ""]
        who = "You" if message["role"] == "user" else "Diya" if message["role"] == "assistant" else message["role"]
        lines += [f"**{who}** ({message['created_at']}):", "", _escape_hidden(message["content"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def build(db_path, folder, now):
    """Write every file into `folder` (which exists and is empty). Returns {file: number of entries}."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        counts, absent = {}, []
        messages, ok = _rows(
            conn, "SELECT m.id, m.thread_id, t.title, m.role, m.content, m.created_at FROM messages m LEFT JOIN threads t ON t.id = m.thread_id ORDER BY m.id", ("id", "thread_id", "title", "role", "content", "created_at"),
        )
        if not ok:
            absent.append("messages.jsonl")
        with open(folder / "messages.jsonl", "w", encoding="utf-8", newline="\n") as out:
            for message in messages:
                out.write(json.dumps(_clean({key: message[key] for key in ("id", "thread_id", "role", "content", "created_at")}), ensure_ascii=False) + "\n")
        counts["messages.jsonl"] = len(messages)
        (folder / "conversations.md").write_text(_conversations(messages), encoding="utf-8", newline="\n")
        counts["conversations.md"] = len({m["thread_id"] for m in messages})
        facts, ok = _rows(conn, _JSON["memory.json"][1], _JSON["memory.json"][2])
        if not ok:
            absent.append("memory.json")
        history = _history(conn, ok)
        for fact in facts:
            fact["history"] = history.get(fact["id"], [])
        _write_json(folder, "memory.json", facts)
        counts["memory.json"] = len(facts)
        accepted = [f"- {_escape_hidden(f['text'])}" for f in facts if f["status"] == "accepted" and f["person"] is None]
        about_others = {}
        for fact in facts:
            if fact["status"] == "accepted" and fact["person"] is not None:
                about_others.setdefault(fact["person"], []).append(f"- {_escape_hidden(fact['text'])}")
        profile = "\n".join(accepted)
        for name in sorted(about_others, key=str.casefold):
            profile += ("\n\n" if profile else "") + f"About {_escape_hidden(name)}:\n" + "\n".join(about_others[name])
        (folder / "memory_profile.txt").write_text(profile + ("\n" if profile else ""), encoding="utf-8", newline="\n")
        counts["memory_profile.txt"] = len(accepted) + sum(len(v) for v in about_others.values())
        for name, (_what, sql, columns) in _JSON.items():
            if name == "memory.json":
                continue
            rows, ok = _rows(conn, sql, columns)
            if not ok:
                absent.append(name)
            _write_json(folder, name, rows)
            counts[name] = len(rows)
        actions, ok = _rows(conn, _ACTIONS[2], ("id", "kind", "args", "summary", "status", "message_id", "created_at", "decided_at", "executed_at", "result"))
        if not ok:
            absent.append("actions.json")
        for action in actions:
            try:
                action["args"] = json.loads(action["args"])
            except (TypeError, ValueError):
                pass
        _write_json(folder, "actions.json", actions)
        counts["actions.json"] = len(actions)
    finally:
        conn.close()
    names = {name: what for name, (what, _sql, _cols) in _JSON.items()}
    names.update({"actions.json": _ACTIONS[1], "messages.jsonl": "every message of every chat, one per line", "conversations.md": "the same chats, to read", "memory_profile.txt": "what Diya remembers, the accepted facts only, as a short list"})
    lines = [f"Diya's export of your data, made {now.strftime('%Y-%m-%d %H:%M:%S')}.", "", "What is here (entries in each):", ""]
    lines += [f"  {name:<28} {counts[name]:>6}   {names[name]}" for name in sorted(counts)]
    if absent:
        lines += ["", "Not in this database (an older version of Diya): " + ", ".join(sorted(absent)) + ". They are written empty."]
    lines += ["", "Left out on purpose, because they are secrets or Diya's own working data:"] + [f"  - {item}" for item in _LEFT_OUT]
    lines += [
        "", "Invisible and control characters other than line breaks are written as visible \\uXXXX escapes.",
        "These files are your private data in the clear. Keep them where you keep your own documents. To delete the export, delete this folder.",
    ]
    (folder / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return counts


def export(config, out_dir=None, now=None):
    """Write a new export folder and return (its path, {file: entries}). Raises FileNotFoundError if there is no database, so that exporting never makes an empty one."""
    if not os.path.isfile(config.db_path):
        raise FileNotFoundError(f"there is no database at {config.db_path}, so there is nothing to export")
    now = now or datetime.now()
    parent = Path(out_dir) if out_dir else Path(config.data_dir or ".") / "exports"
    parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".diya-export-", dir=parent))
    try:
        counts = build(config.db_path, scratch, now)
        stem = "diya-export-" + now.strftime("%Y-%m-%d-%H%M%S")
        final, number = parent / stem, 1
        while final.exists():
            number += 1
            final = parent / f"{stem}-{number}"
        os.replace(scratch, final)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    return final, counts


def main(argv=None, config=None, out=None, err=None):
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    parser = argparse.ArgumentParser(prog="diya_export.py", description="Write everything Diya holds about you as plain files.")
    parser.add_argument("--out", help="the folder to write the export folder into (default: exports/ in the data folder)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        config = config or diya_config.load_config()
        folder, counts = export(config, args.out)
    except (diya_config.ConfigError, FileNotFoundError, OSError) as exc:
        print(f"diya_export: {diya_memory.printable(exc, 300)}", file=err)
        return EXIT_USAGE
    print(f"Wrote {folder}", file=out)
    for name in sorted(counts):
        print(f"  {name:<28} {counts[name]:>6}", file=out)
    print("These files are your private data in the clear: keep them with your own documents.", file=out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
