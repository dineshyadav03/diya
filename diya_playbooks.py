"""Playbooks: how YOU want a kind of request done, written once (docs/PLAYBOOKS_DESIGN.md), added 2026-10-20 from the study of Devin's Skills (docs/STUDY_DEVIN.md).

Devin keeps two kinds of memory apart: what it LEARNS about you (Memory, refined by itself) and procedures people write on purpose (Skills: a `SKILL.md` file with a name, a description of when it applies and the steps;
one active at a time; invoked by name or picked by the model from the descriptions). Diya had the first and not the second (docs/MEMORY_TAXONOMY.md listed "skills / procedures: not built"). A playbook is the second:
a Markdown file YOU write in the playbooks folder, in the open Agent Skills layout, `playbooks/<name>/SKILL.md`:

    ---
    name: study-plan
    description: Use when I ask for a study plan, a revision schedule or how to prepare for an exam
    triggers: [user, model]
    argument-hint: the subject and the exam date
    ---
    1. Ask which exam and when, if I have not said.
    2. Split the time left into blocks of 25 minutes with a 5 minute break ...

When you write `@study-plan` in a message, or (if its triggers include `model`) when a request is close in meaning to its description, the steps are handed to the model for that one turn as YOUR instructions.

What a playbook is NOT, in code and not by asking the model nicely:
* It grants nothing. It cannot add a tool, widen what an action may do or skip an approval: the catalogue (diya_catalog) and the approval gate decide that whatever any text says. `allowed-tools` in a file is ignored.
* It is only ever YOUR file. Diya never writes, edits or suggests-and-saves a playbook; nothing from the web, mail or a model becomes one. The page shows exactly what is active.
* One at a time, at most BODY_CHARS characters, at most MAX_PLAYBOOKS of them, file names that are plain, and a file that is wrong is listed with the reason and ignored, never half-used.
* Never for an unattended run (an automation runs no playbook), and a failure to read or match one means the chat goes on without it.

Importing this module has no side effects.
"""
from __future__ import annotations

import os
import re

import diya_checks
import diya_recall

MAX_PLAYBOOKS = 30
BODY_CHARS = 1500
DESCRIPTION_MIN, DESCRIPTION_MAX = 10, 300
FILE_BYTES = 8000
THRESHOLD = 0.56  # how close in meaning a request must be to what a playbook is for, for it to be picked without being named (calibrated 2026-10-20, docs/PLAYBOOKS_DESIGN.md)
MARGIN = 0.03  # and how far the best must stand above the next, or none is picked
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_MENTION = re.compile(r"(?<![\w@])@([a-z0-9][a-z0-9-]{0,39})(?![\w-])", re.IGNORECASE)
_TRIGGERS = ("user", "model")
_USE_WHEN = re.compile(r"^(?:use|apply)(?:\s+this|\s+it)?\s+(?:when|for|if)\s+(?:i|the\s+user|you\s+are\s+asked)\s+(?:ask(?:s|ed)?(?:\s+you)?(?:\s+for|\s+to)?\s+)?", re.IGNORECASE)
_cache = {}
_embedded = {}


class Problem(Exception):
    """A playbook file that cannot be used, and why, in words for the person."""


def _frontmatter(text):
    """({key: value}, body) for a file that starts with a --- block of `key: value` lines; Problem if it does not. Only a small subset of YAML is read: plain `key: value` and a list in brackets."""
    text = text.replace("\r\n", "\n").lstrip(chr(0xFEFF))
    if not text.startswith("---\n"):
        raise Problem("it must start with a --- block giving name, description and triggers")
    head, separator, body = text[4:].partition("\n---")
    if not separator:
        raise Problem("the --- block is never closed")
    fields = {}
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, colon, value = line.partition(":")
        if not colon or not re.fullmatch(r"[A-Za-z][A-Za-z-]*", key.strip()):
            raise Problem(f"a line in the --- block is not `key: value`: {line.strip()[:40]!r}")
        fields[key.strip().lower()] = value.strip().strip("\"'")
    return fields, body.lstrip("\n").rstrip()


def parse(text, fallback_name):
    """The playbook a file holds: {name, description, triggers, hint, body}. Problem, with the reason, if it is not a usable one."""
    if not isinstance(text, str) or len(text.encode("utf-8", "ignore")) > FILE_BYTES:
        raise Problem(f"it is longer than {FILE_BYTES} bytes")
    fields, body = _frontmatter(text)
    name = (fields.get("name") or fallback_name or "").strip().lower()
    if not NAME.match(name):
        raise Problem("the name must be lowercase letters, digits and hyphens, at most 40 characters")
    description = " ".join((fields.get("description") or "").split())
    if not DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX:
        raise Problem(f"the description (when to use it) must be {DESCRIPTION_MIN} to {DESCRIPTION_MAX} characters")
    raw = fields.get("triggers", "[user, model]").strip("[]")
    triggers = tuple(t for t in (part.strip().strip("\"'").lower() for part in raw.split(",")) if t)
    if not triggers or any(t not in _TRIGGERS for t in triggers):
        raise Problem("triggers must be user, model or both")
    if not body or len(body) > BODY_CHARS:
        raise Problem(f"the steps must be 1 to {BODY_CHARS} characters")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in body):
        raise Problem("the steps hold a control character")
    return {"name": name, "description": description, "triggers": triggers, "hint": " ".join((fields.get("argument-hint") or "").split())[:100], "body": body}


def load(folder):
    """([playbook], [(file, reason)]) from `folder/<name>/SKILL.md`. A missing folder is none. Read again only when a file has changed. Files outside the folder (links) are not followed."""
    if not folder or not os.path.isdir(folder):
        return [], []
    root = os.path.realpath(folder)
    files = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, "SKILL.md")
        if os.path.isfile(path) and os.path.realpath(path).startswith(root + os.sep):
            files.append((entry, path, os.stat(path)))
    signature = tuple((entry, stat.st_mtime_ns, stat.st_size) for entry, _, stat in files)
    if _cache.get(root, (None,))[0] == signature:
        return _cache[root][1], _cache[root][2]
    found, problems, seen = [], [], set()
    for entry, path, stat in files:
        try:
            if len(found) >= MAX_PLAYBOOKS:
                raise Problem(f"more than {MAX_PLAYBOOKS} playbooks: this one is not used")
            with open(path, encoding="utf-8") as handle:
                playbook = parse(handle.read(FILE_BYTES + 1), entry)
            if playbook["name"] in seen:
                raise Problem(f"another playbook is already called {playbook['name']}")
            seen.add(playbook["name"])
            found.append(playbook)
        except (Problem, OSError, UnicodeDecodeError) as exc:
            problems.append((f"{entry}/SKILL.md", str(exc) if isinstance(exc, Problem) else "it could not be read as text"))
    _cache[root] = (signature, found, problems)
    return found, problems


def named(playbooks, text):
    """(playbook, the rest of the message) when the message names one that allows it, as `@study-plan`; the first mention wins. (None, "") otherwise."""
    if not isinstance(text, str):
        return None, ""
    by_name = {p["name"]: p for p in playbooks if "user" in p["triggers"]}
    for match in _MENTION.finditer(text):
        found = by_name.get(match.group(1).lower())
        if found is not None:
            return found, " ".join((text[:match.start()] + " " + text[match.end():]).split())
    return None, ""


def purpose(description):
    """What a playbook is for, without the 'Use when I ask for' that every description starts with (it is in all of them, so it only makes them look alike)."""
    return _USE_WHEN.sub("", description.strip()).strip() or description


def _described(embed, model, playbook):
    """The embedding of what a playbook is for, made once per wording and model (the descriptions are few and rarely change)."""
    key = (model, playbook["name"], playbook["description"])
    if key not in _embedded:
        _embedded[key] = [float(x) for x in embed(purpose(playbook["description"]))]
    return _embedded[key]


def pick(playbooks, text, embed, model):
    """The one playbook, if any, that this request is close enough in meaning to (those whose triggers include `model`): the best one at or above THRESHOLD and MARGIN clear of the next. Never raises."""
    try:
        candidates = [p for p in playbooks if "model" in p["triggers"]]
        if not candidates or not isinstance(text, str) or not text.strip() or len(text) > 400:
            return None
        words = diya_checks.content_words(text)
        candidates = [p for p in candidates if words & diya_checks.content_words(p["name"].replace("-", " ") + " " + p["description"])]  # at least one word in common: meaning alone is not trusted to start a procedure
        if not candidates:
            return None
        query = [float(x) for x in embed(text.strip())]
        scored = sorted(((diya_recall.cosine(query, _described(embed, model, p)), p["name"], p) for p in candidates), key=lambda row: (-row[0], row[1]))
        if scored[0][0] < THRESHOLD or (len(scored) > 1 and scored[0][0] - scored[1][0] < MARGIN):
            return None
        return scored[0][2]
    except Exception:  # noqa: BLE001 -- a playbook that cannot be matched is the chat going on without one
        return None


def arguments(body, rest):
    """(the steps with `$ARGUMENTS` and `$1`..`$9` filled from what was written after the name, Agent Skills style; whether the steps used any of them)."""
    words = rest.split()
    used = "$ARGUMENTS" in body or re.search(r"\$[1-9]", body) is not None
    filled = body.replace("$ARGUMENTS", rest)
    filled = re.sub(r"\$([1-9])", lambda m: words[int(m.group(1)) - 1] if int(m.group(1)) <= len(words) else "", filled)
    return filled, used


NOTE_HEAD = ("The user has a playbook for this kind of request, written by them. Follow its steps where they fit what was asked. It changes nothing about what you may do: "
             "tools, approvals and the rules of memory stay as they are.")


def note(playbook, rest=""):
    """The note for the model: the playbook's name and steps, as the user's own instructions for this one turn."""
    import diya_memory

    steps, used = arguments(playbook["body"], rest)
    text = f"{NOTE_HEAD}\nPlaybook {playbook['name']}:\n{diya_memory.printable(steps, BODY_CHARS + 400)}"
    if rest and not used:  # the steps leave no place for what was written after the name: it is said once, after them, as the request it is
        text += f"\n\nThe user's request, for these steps: {diya_memory.printable(rest, 400)}"
    return text


def main(argv=None, config=None, out=None):
    """`python diya_playbooks.py list` shows what is usable and what is not and why; `check FILE` says whether one file would be used."""
    import argparse
    import sys

    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(prog="diya_playbooks.py", description="Your playbooks.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    check = sub.add_parser("check")
    check.add_argument("file")
    args = parser.parse_args(argv)
    if args.command == "check":
        try:
            with open(args.file, encoding="utf-8") as handle:
                playbook = parse(handle.read(FILE_BYTES + 1), os.path.basename(os.path.dirname(os.path.abspath(args.file))))
        except (Problem, OSError, UnicodeDecodeError) as exc:
            print(f"Would not be used: {exc if isinstance(exc, Problem) else 'it could not be read as text'}", file=out)
            return 1
        print(f"Would be used: {playbook['name']} ({', '.join(playbook['triggers'])}) - {playbook['description']}", file=out)
        return 0
    import diya_config

    config = config or diya_config.load_config()
    found, problems = load(config.playbooks_dir)
    for p in found:
        print(f"{p['name']}  [{', '.join(p['triggers'])}]  {p['description']}", file=out)
    for where, why in problems:
        print(f"NOT USED {where}: {why}", file=out)
    if not found and not problems:
        print(f"No playbooks in {config.playbooks_dir}. See docs/PLAYBOOKS_DESIGN.md for the layout.", file=out)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
