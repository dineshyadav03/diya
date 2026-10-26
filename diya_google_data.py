"""What Diya keeps because of Google, shown, exported and purged on request (DIYA-146; docs/GOOGLE_CHANGES.md), added 2026-10-27.

    python diya_google_data.py show                      what is kept, in counts (changes nothing)
    python diya_google_data.py export --out FILE         the same in full, as JSON, to a new file (never over an old one); no sign-in, token or secret is ever in it
    python diya_google_data.py purge --what WHAT [--yes] remove one kind of it (without --yes it only says how much)

WHAT is one of: `actions` (finished actions on Google, with their words: the recipients and text of an email, the title of an event), `activity` (the words in the activity record for Google tools: the row stays, since the record
cannot be edited, and a receipt says what was blanked), `replies` (Diya's own earlier replies that hold a report from Google: a mail search, a Drive search or file, a calendar list, a plan; with the search index entries made from
them), and `connections` (every Google card is disconnected, and Google is told to forget the permission). Each is separate; nothing is removed unless you name it and say --yes.

What is not reached, said plainly: a reply where the model PUT a mail or a file into its own words has no report mark and is not found; messages you wrote yourself are never touched here (the chat's Forget does those); backups made earlier
keep the old words until they rotate out; and what Google keeps is Google's (revoking the permission is the `connections` purge).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import diya_catalog
import diya_config
import diya_connector_tools
import diya_connectors
import diya_db
import diya_google_calendar

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 1
FINISHED = ("succeeded", "failed", "rejected", "expired", "unknown")
# The first words of the reports that code writes from Google's answers (a model's own words about them are not marked, and are not found).
REPORT_MARKS = (
    "Your mail, searched for", "Google Drive:", "Versions of ", "Your calendar for", "On your calendar in the next", "Plan for ", "A tidy-up of the files", "Possible tasks I noticed", "(From Google Calendar, which I can only read.)",
    "(From your Google Contacts, which I can only read.)", "Nothing on your calendar for",
)


def google_tool_names():
    """The tools, flows and proposals in the catalog that belong to a Google connector."""
    return sorted(name for name, entry in diya_catalog.CATALOG.items() if entry.connector.startswith("google"))


def google_kinds():
    """The kinds of action that need a Google connector."""
    return sorted(kind.name for kind in diya_connector_tools.real_action_kinds() if kind.connector and kind.connector.startswith("google"))


def _marks_clause():
    return " OR ".join("content LIKE ?" for _ in REPORT_MARKS), [f"%{mark}%" for mark in REPORT_MARKS]


def counts(config, store):
    """How much of each kind is kept, as a dict."""
    marks, params = _marks_clause()
    kinds, tools = google_kinds(), google_tool_names()
    conn = store.connect()
    try:
        marks_k = ",".join("?" for _ in kinds)
        marks_t = ",".join("?" for _ in tools)
        actions = conn.execute(f"SELECT COUNT(*) FROM actions WHERE kind IN ({marks_k}) AND status IN ({','.join('?' for _ in FINISHED)})", [*kinds, *FINISHED]).fetchone()[0]
        waiting = conn.execute(f"SELECT COUNT(*) FROM actions WHERE kind IN ({marks_k}) AND status NOT IN ({','.join('?' for _ in FINISHED)})", [*kinds, *FINISHED]).fetchone()[0]
        activity = conn.execute(f"SELECT COUNT(*) FROM tool_journal WHERE tool IN ({marks_t})", tools).fetchone()[0]
        words = conn.execute(f"SELECT COUNT(*) FROM tool_journal WHERE tool IN ({marks_t}) AND (args_preview IS NOT NULL OR note IS NOT NULL)", tools).fetchone()[0]
        replies = conn.execute(f"SELECT COUNT(*) FROM messages WHERE role = 'assistant' AND ({marks})", params).fetchone()[0]
    finally:
        conn.close()
    connected = [name for name in diya_google_calendar.every_card() if diya_connectors.is_connected(config, name)]
    return {"actions_finished": actions, "actions_waiting": waiting, "activity_rows": activity, "activity_rows_with_words": words, "replies_with_google_reports": replies, "cards_connected": connected}


def export(config, store):
    """Everything kept because of Google as a dict (see the module words); nothing secret."""
    marks, params = _marks_clause()
    kinds, tools = google_kinds(), google_tool_names()
    conn = store.connect()
    try:
        actions = [dict(zip(("id", "kind", "summary", "status", "args", "result", "created_at", "decided_at", "executed_at", "tainted", "taint_sources"), row)) for row in conn.execute(
            f"SELECT id, kind, summary, status, args, result, created_at, decided_at, executed_at, tainted, taint_sources FROM actions WHERE kind IN ({','.join('?' for _ in kinds)}) ORDER BY id", kinds)]
        for row in actions:
            for key in ("args", "taint_sources"):
                try:
                    row[key] = json.loads(row[key])
                except (TypeError, ValueError):
                    pass
        activity = [dict(zip(("at", "tool", "kind", "status", "args_preview", "note", "result_chars", "duration_ms"), row)) for row in conn.execute(
            f"SELECT at, tool, kind, status, args_preview, note, result_chars, duration_ms FROM tool_journal WHERE tool IN ({','.join('?' for _ in tools)}) ORDER BY id", tools)]
        replies = [{"message_id": row[0], "thread_id": row[1], "at": row[2], "text": row[3]} for row in conn.execute(f"SELECT id, thread_id, created_at, content FROM messages WHERE role = 'assistant' AND ({marks}) ORDER BY id", params)]
    finally:
        conn.close()
    return {"exported_at": datetime.now(timezone.utc).isoformat(), "what": "what Diya keeps because of Google; no sign-in, token or secret is here", "counts": counts(config, store), "actions": actions, "activity": activity, "replies": replies}


def purge(config, store, what, confirm=False):
    """Remove one kind of it, or (without `confirm`) say how much would go. A report dict; ValueError for an unknown kind."""
    if what not in ("actions", "activity", "replies", "connections"):
        raise ValueError("what is one of actions, activity, replies, connections")
    found = counts(config, store)
    report = {"what": what, "done": bool(confirm)}
    if what == "actions":
        report["would_remove"] = found["actions_finished"]
        report["left"] = f"{found['actions_waiting']} action(s) still waiting for you are not touched (turn them down on the Actions page)"
    elif what == "activity":
        report["would_blank"] = found["activity_rows_with_words"]
        report["left"] = "the rows stay (the record cannot be edited): that it happened, when, and how it came out; only the words are blanked, and a receipt says so"
    elif what == "replies":
        report["would_remove"] = found["replies_with_google_reports"]
        report["left"] = "your own messages are not touched, and a reply where the model put the text into its own words is not found"
    else:
        report["would_disconnect"] = found["cards_connected"]
        report["left"] = "Google is told to forget the permission when the last card goes; the client id and secret you pasted stay until you forget them on the Connections page"
    if not confirm:
        return report
    kinds, tools = google_kinds(), google_tool_names()
    if what == "actions":
        conn = store.connect()
        try:
            conn.execute("PRAGMA secure_delete = ON")
            conn.execute("BEGIN IMMEDIATE")
            marks = ",".join("?" for _ in kinds)
            status = ",".join("?" for _ in FINISHED)
            ids = [row[0] for row in conn.execute(f"SELECT id FROM actions WHERE kind IN ({marks}) AND status IN ({status})", [*kinds, *FINISHED])]
            for chunk in range(0, len(ids), 200):
                part = ids[chunk:chunk + 200]
                keys = ",".join("?" for _ in part)
                conn.execute(f"DELETE FROM action_events WHERE action_id IN ({keys})", part)
                conn.execute(f"DELETE FROM actions WHERE id IN ({keys})", part)
            conn.commit()
            report["removed"] = len(ids)
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    elif what == "activity":
        report["blanked"] = store.journal_scrub_tools(tools)
    elif what == "replies":
        marks, params = _marks_clause()
        conn = store.connect()
        try:
            conn.execute("PRAGMA secure_delete = ON")
            conn.execute("BEGIN IMMEDIATE")
            ids = [row[0] for row in conn.execute(f"SELECT id FROM messages WHERE role = 'assistant' AND ({marks})", params)]
            for chunk in range(0, len(ids), 200):
                part = ids[chunk:chunk + 200]
                keys = ",".join("?" for _ in part)
                for table in ("message_categories", "message_embeddings", "fact_mentions", "reply_feedback", "capture_queue", "memory_captures"):
                    conn.execute(f"DELETE FROM {table} WHERE message_id IN ({keys})", part)
                conn.execute(f"DELETE FROM messages WHERE id IN ({keys})", part)
            conn.commit()
            report["removed"] = len(ids)
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        by_name = {c.name: c for c in diya_connector_tools.real_connectors(config)}
        gone, revoked = [], None
        for name in found["cards_connected"]:
            answer = diya_connectors.revoke_and_disconnect(config, by_name[name])  # the last card takes the permission back at Google; the others leave it for the last
            revoked = answer if answer is not None else revoked
            gone.append(name)
        report["disconnected"], report["revoked_at_google"] = gone, revoked
    return report


def build_parser():
    parser = argparse.ArgumentParser(prog="diya_google_data", description="Show, export and purge what Diya keeps because of Google.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="what is kept, in counts")
    out = sub.add_parser("export", help="what is kept, in full, to a new JSON file")
    out.add_argument("--out", required=True, help="the file to write (it must not exist)")
    purge_p = sub.add_parser("purge", help="remove one kind of it")
    purge_p.add_argument("--what", required=True, choices=("actions", "activity", "replies", "connections"))
    purge_p.add_argument("--yes", action="store_true", help="really do it (without this it only says how much)")
    return parser


def main(argv=None, config=None, out=None, err=None):
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        config = config or diya_config.load_config()
    except diya_config.ConfigError as exc:
        print(f"diya_google_data: {exc}", file=err)
        return EXIT_USAGE
    import diya_backup

    if not diya_backup.guard_migration(config, say=lambda line: print(f"diya_google_data: {line}", file=err)):
        return EXIT_USAGE
    store = diya_db.Store(config.db_path)
    if args.command == "show":
        print(json.dumps(counts(config, store), indent=2), file=out)
        return EXIT_OK
    if args.command == "export":
        if os.path.exists(args.out):
            print(f"diya_google_data: {args.out} already exists; pick a new file (an old export is never written over)", file=err)
            return EXIT_REFUSED
        data = export(config, store)
        with open(args.out, "x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        print(f"Wrote {args.out}: {len(data['actions'])} action(s), {len(data['activity'])} activity row(s), {len(data['replies'])} reply(ies).", file=out)
        return EXIT_OK
    report = purge(config, store, args.what, confirm=args.yes)
    print(json.dumps(report, indent=2), file=out)
    if not args.yes:
        print("Nothing was removed. Say --yes to do it.", file=out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
