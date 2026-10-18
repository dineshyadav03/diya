"""Memory as a Markdown file you can read, keep in Git and restore from (docs/MARKDOWN_MEMORY_DESIGN.md), added 2026-10-18 for task DIYA-033.

The sheet asks whether memory can be exported as Markdown "without replacing SQLite truth", with a round trip that preserves references and authority. Devin's memory (read about secondhand, docs/RESEARCH_REVIEWS_
2026-10-18.md) and supermemory's company-brain export (`src/memory/markdown.ts`, Apache-2.0, read) both make memory a plain file a person can open. This is Diya's version, and it is a COPY: the database stays the
only truth, nothing here is read back as an instruction, and nothing edited in the file changes what Diya knows until the owner runs the restore.

What the file holds: every fact Diya uses (accepted) and every fact she has stopped using (retired), grouped by who it is about, one line each with its words in plain Markdown and a hidden comment carrying the
record: who it is about, when it was first taken in, who took it in (you typed it / you accepted it / Diya on her own under the rules / imported), the number of the message it was read from, how many times you said
it again, and whether you kept it. Not in the file, on purpose: facts that are still waiting for a decision (nobody has said they are true), facts you turned down (you said no; a file is the wrong place to keep them),
and facts forgotten for good (their words are gone).

Restoring brings back only what is not already there, as accepted or retired facts with a trail that says exactly what happened ("restored from a Markdown export; originally taken in by Diya on her own"). The
authority is RECORDED, never forged: the restore is its own event, by the importer, so a file cannot make it look as if the owner accepted something on a day they did not. The source message is kept as a number in
the trail and NOT as a live link, because in another database that number is a different message and quoting it would be a lie.

Importing this module has no side effects.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import diya_memory
from diya_memory import InvalidFact, check_person_name, check_text

FORMAT = "diya-memory-markdown 1"
MAX_ITEMS = 5000  # a restore of more facts than this is not a memory, it is something else
_OPEN = " <!-- diya "
_CLOSE = " -->"
BY = ("you", "typed", "auto", "imported")


def _json(meta):
    # "<" and ">" are escaped so that "-->" can never appear inside the comment, whatever a source flag or a name holds
    return json.dumps(meta, sort_keys=True, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")


def _by(memory, fact_id):
    """Who took the fact into its present state: 'typed' (you typed it), 'imported', 'auto' (Diya, under the memory rules) or 'you'."""
    taken = [e for e in memory.events(fact_id) if e[0] in ("accepted", "added", "imported", "restored")]
    if not taken:
        return "you"
    event, actor = taken[-1][0], taken[-1][1]
    if event == "added":
        return "typed"
    if event == "imported" or actor == "import":
        return "imported"
    return "auto" if actor == "auto" else "you"


def export_markdown(memory, now=None):
    """The Markdown copy of memory (see the module note). Pure reading: nothing in the database changes."""
    moment = (now or datetime.now(timezone.utc)).isoformat()
    accepted = memory.facts("accepted")
    retired = memory.facts("retired")
    kept = {f["id"] for f in accepted if memory.is_kept(f["id"])}
    said = memory.mention_counts()

    def line(fact):
        meta = {"id": fact["id"], "status": fact["status"], "person": fact["person"], "created": fact["created_at"], "by": _by(memory, fact["id"]), "source": fact["source"],
                "message": diya_memory.source_message_id(fact), "said": said.get(fact["id"], 0), "kept": fact["id"] in kept}
        return f"- {fact['text']}{_OPEN}{_json(meta)}{_CLOSE}"

    out = [
        "# What Diya remembers about you",
        f"<!-- {FORMAT} · exported {moment} · {len(accepted)} in use, {len(retired)} retired -->",
        "",
        "This is a copy for reading and keeping. Diya's database is the truth: change a fact on the Memory page, not here. Restoring this file adds facts that are not already there; it never changes or removes one.",
        "Waiting facts, facts you turned down and facts you made Diya forget for good are not in it.",
    ]
    groups = {}
    for fact in accepted:
        groups.setdefault(fact["person"], []).append(fact)
    for person in sorted(groups, key=lambda p: (p is not None, (p or "").casefold())):
        out += ["", "## About you" if person is None else f"## About {person}", ""]
        out += [line(fact) for fact in groups[person]]
    if retired:
        out += ["", "## No longer used (retired)", ""]
        out += [line(fact) for fact in retired]
    return "\n".join(out) + "\n"


def _when(value, fallback):
    """An ISO moment as an aware UTC string, never later than `fallback` (a file cannot claim a fact from the future)."""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.isoformat() if moment <= datetime.fromisoformat(fallback) else fallback


def parse_markdown(text):
    """(items, problems): the facts a Markdown export holds, each {text, status, person, created_at, by, message, said, kept}, and a plain sentence for every line that could not be read (it is skipped, never
    guessed at). Raises InvalidFact if this is not a Diya memory export at all."""
    if not isinstance(text, str) or f"<!-- {FORMAT} " not in text:
        raise InvalidFact("this is not a Diya memory export (its first comment should name the format)")
    items, problems = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.startswith("- ") or not raw.endswith(_CLOSE) or _OPEN not in raw:
            if raw.startswith("- "):
                problems.append(f"line {number}: a list line with no record, skipped")
            continue
        words, _, record = raw[2:-len(_CLOSE)].rpartition(_OPEN)
        try:
            meta = json.loads(record)
            if not isinstance(meta, dict) or meta.get("status") not in ("accepted", "retired"):
                raise ValueError("status")
            check_text(words)
            person = meta.get("person")
            if person is not None:
                check_person_name(person)
        except (ValueError, TypeError, InvalidFact) as exc:
            problems.append(f"line {number}: {str(exc)[:80] or 'unreadable'}, skipped")
            continue
        said, message = meta.get("said"), meta.get("message")
        items.append({
            "text": words, "status": meta["status"], "person": person, "created_at": meta.get("created"), "by": meta.get("by") if meta.get("by") in BY else "you",
            "message": message if isinstance(message, int) and not isinstance(message, bool) else None, "said": said if isinstance(said, int) and not isinstance(said, bool) and said >= 0 else 0,
            "kept": meta.get("kept") is True,
        })
    if len(items) > MAX_ITEMS:
        raise InvalidFact(f"this file holds more than {MAX_ITEMS} facts: it is not a memory export")
    return items, problems


def restore_markdown(memory, text, actor="import", now=None):
    """Bring back what the export holds and the memory does not have. Returns (restored, already_there, problems). Nothing already in the memory is changed or removed."""
    items, problems = parse_markdown(text)
    moment = (now or datetime.now(timezone.utc)).isoformat()
    for item in items:
        item["created_at"] = _when(item["created_at"], moment)
    restored, already = memory.restore_exported(items, actor)
    return restored, already, problems
