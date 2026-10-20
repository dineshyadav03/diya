"""Memory as an Agent Memory Repo: a folder of Markdown notes with a short entry point (docs/STUDY_DEVIN.md, docs/MEMORY_REPO_DESIGN.md), added 2026-10-20.

Cognition's open standard for agent memory (https://cognition.com/agent-memory-repo, read 2026-10-20) says memory is a folder, usually a Git repository, of Markdown notes: `MEMORY.md` at the root is what an agent
loads first ("keep it short: include only what every session needs, plus links to everything else"), every entry is one bullet on one line with optional metadata at the end as `[key: value; key: value]`
(recommended keys `source` and `added`), and notes link to each other as `[[path/without-.md]]`. Devin's own Memory is built on it (https://docs.devin.ai/product-guides/memory).

This writes Diya's memory in that shape. It is a one-way COPY, like the Markdown copy in diya_markdown.py but for reading by people and by other tools rather than for restoring: Diya's database stays the only
truth, nothing is read back from the folder, and a fact that is edited in the folder changes nothing in Diya. Facts still waiting for a decision, facts turned down and facts forgotten for good are not in it.

Layout:
    MEMORY.md          what every session needs: the lasting facts about you (up to MAIN_CHARS of them), then an `## Index` of links
    about-you-more.md  the rest of the lasting facts about you, only when they do not fit in MEMORY.md
    people/<name>.md   one note per named person: the facts about them
    passing.md         facts that fade unless said again (diya_fade), each with the date it fades
    retired.md         facts Diya no longer uses

An entry is `- <the fact> [source: <where>; added: <date>; by: <who>; said-again: <n>; fades: <date>]` with only the keys that apply. `source` is `message <n>` (the number of your message it was read from, as far
as the record says), `typed` or `old profile`. `by` is `you` (you typed or accepted it), `auto` (Diya took it on her own under the memory rules) or `imported`.

Importing this module has no side effects. Nothing is ever written over an existing file: the folder must not exist or be empty.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import diya_markdown
import diya_memory

FORMAT_URL = "https://cognition.com/agent-memory-repo"
MAIN_CHARS = 2000  # how much of the lasting facts about you MEMORY.md holds; the entry point stays short
ENTRY_FIELDS = ("source", "added", "by", "said-again", "fades")


class RepoError(Exception):
    """The folder could not be written; nothing was changed in the database, and nothing existing was overwritten."""


def slug(name, taken=()):
    """A safe file name for a person: lowercase letters, digits and hyphens only (so a name can never name a path), made different from any already taken."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").casefold().encode("ascii", "ignore").decode()).strip("-")[:40] or "person"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


def _text(fact_text):
    """A fact as it goes on one line: the link syntax is neutralised so a fact can never create or break a link."""
    return fact_text.replace("[[", "[ [").replace("]]", "] ]")


def _meta(pairs):
    pairs = [(key, value) for key, value in pairs if value not in (None, "", 0)]
    return f" [{'; '.join(f'{key}: {value}' for key, value in pairs)}]" if pairs else ""


def _source(fact):
    if fact["source"] == "manual":
        return "typed"
    if fact["source"] == "legacy_profile":
        return "old profile"
    if fact["source"] == "markdown_export":
        return "restored copy"
    message = diya_memory.source_message_id(fact)
    return f"message {message}" if message is not None else None


def _day(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _entry(memory, fact, said, fades):
    when = fades.get(fact["id"])
    return f"- {_text(fact['text'])}" + _meta((
        ("source", _source(fact)), ("added", _day(fact["created_at"])), ("by", diya_markdown._by(memory, fact["id"])),
        ("said-again", said.get(fact["id"], 0)), ("fades", when.astimezone().strftime("%Y-%m-%d") if when is not None else None),
    ))


def build(memory, now=None):
    """{relative path: file text} for the whole repository. Pure reading."""
    moment = (now or datetime.now(timezone.utc)).astimezone().strftime("%Y-%m-%d")
    accepted, retired = memory.facts("accepted"), memory.facts("retired")
    said, fades = memory.mention_counts(), memory.fading()
    files = {}

    mine = [f for f in accepted if f["person"] is None and f["id"] not in fades]
    main, more, used = [], [], 0
    for fact in mine:  # oldest first: the facts that have been true longest are what every session needs
        line = _entry(memory, fact, said, fades)
        if used + len(line) <= MAIN_CHARS and not more:
            main.append(line)
            used += len(line)
        else:
            more.append(line)

    people = {}
    for fact in accepted:
        if fact["person"] is not None:
            people.setdefault(fact["person"], []).append(fact)
    taken, names = set(), {}
    for person in sorted(people, key=str.casefold):
        names[person] = slug(person, taken)
        taken.add(names[person])
        files[f"people/{names[person]}.md"] = "\n".join(
            [f"# {_text(person)}", "", f"What Diya remembers about {_text(person)} (as told by you). Exported {moment}.", ""] + [_entry(memory, f, said, fades) for f in people[person]]) + "\n"

    passing = [f for f in accepted if f["id"] in fades]
    if passing:
        files["passing.md"] = "\n".join(["# Passing states", "", "Facts that sound like they will not last. Each fades on the date shown unless you say it again or keep it.", ""] + [_entry(memory, f, said, fades) for f in passing]) + "\n"
    if retired:
        files["retired.md"] = "\n".join(["# No longer used", "", "Facts Diya has stopped using. The Memory page can bring one back.", ""] + [_entry(memory, f, said, fades) for f in retired]) + "\n"
    if more:
        files["about-you-more.md"] = "\n".join(["# About you (continued)", "", "The rest of the lasting facts about you.", ""] + more) + "\n"

    index = []
    if more:
        index.append(f"- [[about-you-more]] - {len(more)} more lasting facts about you")
    index += [f"- [[people/{names[p]}]] - {len(people[p])} fact{'' if len(people[p]) == 1 else 's'} about {_text(p)}" for p in sorted(people, key=str.casefold)]
    if passing:
        index.append(f"- [[passing]] - {len(passing)} passing state{'' if len(passing) == 1 else 's'} that will fade")
    if retired:
        index.append(f"- [[retired]] - {len(retired)} fact{'' if len(retired) == 1 else 's'} no longer used")
    files["MEMORY.md"] = "\n".join(
        ["# What Diya remembers about you", "",
         f"A copy in the Agent Memory Repo format ({FORMAT_URL}), exported {moment}. Diya's database is the truth: change a fact on the Memory page, not here.", "",
         "## About you", ""] + (main or ["_Nothing yet._"]) + ["", "## Index", ""] + (index or ["_Nothing else yet._"])) + "\n"
    return files


def export_repo(memory, folder, now=None):
    """Write the repository into `folder`, which must not exist or be empty. Returns the list of files written. RepoError, with nothing written, if the folder is in use or cannot be made."""
    folder = os.path.abspath(folder)
    if os.path.exists(folder) and (not os.path.isdir(folder) or os.listdir(folder)):
        raise RepoError(f"{folder} already exists and is not empty; nothing was written (choose a new folder)")
    files = build(memory, now=now)
    root = folder + os.sep
    written = []
    try:
        for relative in sorted(files):
            path = os.path.abspath(os.path.join(folder, *relative.split("/")))
            if not path.startswith(root):  # (a name can never reach here: slugs are plain; this is the last check)
                raise RepoError(f"refusing to write outside the folder: {relative}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(files[relative])
            written.append(relative)
    except OSError as exc:
        raise RepoError(f"could not write {folder}: {exc}") from exc
    return written
