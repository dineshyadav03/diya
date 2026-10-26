"""A tidy-up of the Drive that shows its plan and how to undo it before anything is moved (DIYA-143; docs/GOOGLE_CHANGES.md), added 2026-10-27.

"Tidy my Drive": code looks at the files Diya made that sit at the top of My Drive, and at the folders Diya made, and a file whose name begins with, or says as a whole word, the name of one of those folders is planned to go into that
folder ("Exams revision plan" into "Exams"). The plan is shown in full as a manifest: every file, where it is now, where it would go, and the line that puts it back. Then the first few moves (one message may lead to at most 3 actions)
are PROPOSED, each as its own move for the owner to approve with the same from / to / how-to-undo on its card; the rest are asked for again. Nothing is moved, renamed or deleted without those approvals, nothing is binned, and Diya
sees only what it made (the narrow drive.file permission), so it cannot tidy anything else.

Not built: choosing folders by file type, making folders, and moving files that Diya did not make. Importing this module has no side effects.
"""
from __future__ import annotations

import re

import diya_google_client as client
import diya_google_drive as gd
import diya_memory

MAX_PLAN = 20
_TIDY = re.compile(r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*(?:tidy|clean)\s*(?:up)?\s+(?:my\s+|the\s+)?(?:google\s+)?drive\s*\.?$|^\W*(?:(?:please|diya)\b[\s,]*)*(?:organi[sz]e|sort)\s+(?:out\s+)?(?:my\s+)?(?:google\s+)?drive(?:\s+files)?\s*\.?$", re.IGNORECASE)


def request(text):
    """True for a plain request to tidy the Drive."""
    return isinstance(text, str) and 0 < len(text) <= 120 and "\n" not in text.strip() and _TIDY.search(text.replace(chr(0x2019), "'").strip()) is not None


def folder_for(file_name, folders):
    """The folder a file belongs in by its name: the folder whose name the file's name begins with, or contains as a whole word; the longest such name wins; None if there is no single best."""
    name = " ".join(re.sub(r"[^\w\s]", " ", file_name.casefold()).split())
    best = []
    for folder in folders:
        wanted = " ".join(re.sub(r"[^\w\s]", " ", folder["name"].casefold()).split())
        if wanted and re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", name):
            best.append((len(wanted), folder))
    if not best:
        return None
    top = max(size for size, _ in best)
    chosen = [f for size, f in best if size == top]
    return chosen[0] if len(chosen) == 1 else None


def plan(config):
    """(moves, text): the moves the plan would make as dicts (name, file_id, version, from_id, from_name, to_id, to_name) and the manifest as lines; GoogleError for a problem."""
    root = gd._root_id(config)
    folders = [f for f in gd._lookup(config, gd.CHANGE, gd._query("", mime=gd.FOLDER), size=100)]
    top = [f for f in gd._lookup(config, gd.CHANGE, gd._query("", not_mime=gd.FOLDER), size=100) if root and f.get("parents") == [root]]
    moves = []
    for file in top:
        target = folder_for(file["name"], folders)
        if target is not None and len(moves) < MAX_PLAN:
            moves.append(dict(gd._ref(file), from_id=root, from_name="the top of My Drive", to_id=target["id"], to_name=diya_memory.printable(target["name"], 60)))
    lines = []
    if not moves:
        lines.append(f"Nothing to tidy: none of the {len(top)} file(s) Diya made at the top of your Drive has a folder's name in its name ({len(folders)} folder(s) of Diya's: {', '.join(diya_memory.printable(f['name'], 30) for f in folders[:6]) or 'none'}).")
        return moves, lines
    lines.append(f"A tidy-up of the files Diya made at the top of your Drive, by the names of the folders Diya made ({len(moves)} move(s)):")
    lines += [f"- '{m['name']}': from {m['from_name']} into '{m['to_name']}'   (to put it back: move '{m['name']}' into My Drive)" for m in moves]
    return moves, lines
