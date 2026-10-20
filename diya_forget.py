"""Forget for good: delete a message, or a remembered fact, so that its words are gone (docs/FORGET_DESIGN.md), added 2026-10-18 for the owner's decision 234.

Diya keeps everything by default, and "forget that" only RETIRES a fact: the words stay so that Restore works. This is the other thing the owner asked for: a way to delete or forget something for real.

* `forget_fact`: a fact (any status) loses its words, the line it was read from, its links to a message or a person, the words kept in its own history, its questions and its vector
  (diya_memory.Memory.purge); the staged queue file (`dream_pending.jsonl`), which still holds the line it was extracted as, is cleaned of it.
* `forget_message`: one of the person's messages and Diya's reply to it are deleted, with what was derived from them (their category, the record that memory read them). With `also_learned`, the facts
  that were read from that message (precisely: those whose recorded source is that message) are forgotten for good too. Things that were MADE from the message (a task, a repeating reminder, an approved
  action) are kept and unlinked, and reported, because deleting a message is not the same as cancelling what you asked for.
* `dry_run` says what would happen and changes nothing, so a page can ask "are you sure?" with the real numbers.

What it cannot reach, and says so: the activity journal and Dreaming's receipts are append-only by design (they hold counts, ids and short previews of what a tool was asked, never the reply); snapshots
in `backups/` made earlier still hold the old words until they rotate out (the newest 14 are kept) or are deleted by hand; and a copy in a cloud-sync folder's own history is that program's.

Importing this module has no side effects.
"""
from __future__ import annotations

import json
import os

import diya_memory


class ForgetError(Exception):
    """Nothing was changed, and the reason is in the words."""


def _staged_clean(config, texts):
    """Take the given fact texts out of the staged-queue file Dreaming writes (dream_pending.jsonl), replacing each line with a marker. Returns how many lines were cleaned. Missing file: 0."""
    path = config.dream_pending_path
    if not texts or not os.path.exists(path):
        return 0
    wanted = {diya_memory.text_key(t) for t in texts if t and t != diya_memory.PURGED_PLACEHOLDER}
    cleaned, out = 0, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                out.append(line)
                continue
            try:
                record = json.loads(stripped)
            except ValueError:
                out.append(line)
                continue
            facts = record.get("facts") if isinstance(record, dict) else None
            if isinstance(facts, list):
                for i, fact in enumerate(facts):
                    if isinstance(fact, str) and diya_memory.text_key(fact.strip().lstrip("-").strip()) in wanted:
                        facts[i] = "- (forgotten for good)"
                        cleaned += 1
                line = json.dumps(record, ensure_ascii=False) + "\n"
            out.append(line)
    if cleaned:
        temporary = path + ".part"
        with open(temporary, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(out)
        os.replace(temporary, path)
    return cleaned


def forget_fact(memory, config, fact_id, actor="api"):
    """Forget one fact for good. Returns {"fact_id", "staged_lines_cleaned"}. Raises diya_memory.FactError (unknown fact, already forgotten)."""
    old = memory.purge(fact_id, actor)
    return {"fact_id": fact_id, "staged_lines_cleaned": _staged_clean(config, [old])}


def facts_from(memory, message_id):
    """The facts whose recorded source is exactly this message: flagged as read from it, or read from it alone. Not the ones read from a wider batch with no recorded source (those are counted apart)."""
    exact, unsure = [], 0
    for fact in memory.facts():
        if fact["text"] == diya_memory.PURGED_PLACEHOLDER:
            continue
        flagged = {int(flag[len(diya_memory.FLAG_SOURCE_PREFIX):]) for flag in fact["flags"] if flag.startswith(diya_memory.FLAG_SOURCE_PREFIX) and flag[len(diya_memory.FLAG_SOURCE_PREFIX):].isdigit()}
        if message_id in flagged or (fact["batch_first"] == fact["batch_last"] == message_id):
            exact.append(fact)
        elif not flagged and fact["batch_first"] is not None and fact["batch_first"] <= message_id <= fact["batch_last"]:
            unsure += 1
    return exact, unsure


def _exchange(store, message_id):
    """The person's message and Diya's reply to it: the message, and the assistant messages after it in the same chat up to the person's next one."""
    messages = store.get_messages_between(message_id, message_id)
    if not messages or messages[0]["role"] != "user":
        raise ForgetError("that is not one of your messages")
    thread = messages[0]["thread_id"]
    found = [messages[0]]
    conn = store.connect()
    try:
        for row in conn.execute("SELECT id, role FROM messages WHERE thread_id = ? AND id > ? ORDER BY id", (thread, message_id)):
            if row[1] != "assistant":
                break
            found.append({"id": row[0], "role": row[1], "thread_id": thread})
    finally:
        conn.close()
    return found


def forget_message(store, memory, config, message_id, also_learned=True, dry_run=False):
    """Delete the message and its reply (and, with `also_learned`, what was read from it). Returns a report; `dry_run` changes nothing. ForgetError if it is not one of the person's messages."""
    exchange = _exchange(store, message_id)
    ids = [m["id"] for m in exchange]
    facts, unsure = facts_from(memory, message_id) if also_learned else ([], 0)
    marks = ",".join("?" for _ in ids)
    conn = store.connect()
    try:
        kept = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE message_id IN ({marks})", ids).fetchone()[0]
            for table in ("tasks", "actions", "reminder_series")
        }
    finally:
        conn.close()
    report = {
        "dry_run": bool(dry_run), "message_ids": ids, "replies": len(ids) - 1, "facts": len(facts), "facts_unsure": unsure,
        "kept_and_unlinked": {"tasks": kept["tasks"], "actions": kept["actions"], "repeating_reminders": kept["reminder_series"]},
        "not_reached": ["the activity record keeps counts and short previews of what tools were asked (it cannot be edited)", "backups made earlier keep the old words until they rotate out"],
    }
    if dry_run:
        return report
    cleaned = 0
    for fact in facts:  # the facts first: their source flags name the message
        cleaned += forget_fact(memory, config, fact["id"], "api")["staged_lines_cleaned"]
    conn = store.connect()
    try:
        conn.execute("PRAGMA secure_delete = ON")  # the deleted words are overwritten in the file, not left in free space
        conn.execute("BEGIN IMMEDIATE")
        for table in ("message_categories", "capture_queue", "memory_captures", "message_embeddings", "fact_mentions"):
            conn.execute(f"DELETE FROM {table} WHERE message_id IN ({marks})", ids)
        for table in ("tasks", "actions", "reminder_series"):
            conn.execute(f"UPDATE {table} SET message_id = NULL WHERE message_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM messages WHERE id IN ({marks})", ids)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    report["staged_lines_cleaned"] = cleaned
    try:
        import diya_journal

        diya_journal.record(store, "forget_for_good", {"messages": len(ids), "facts": len(facts)}, "ok", kind="flow")  # counts only: never the words
    except Exception:  # noqa: BLE001
        pass
    return report
