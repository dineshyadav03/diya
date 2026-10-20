"""The playbooks, over HTTP (docs/PLAYBOOKS_DESIGN.md): the route behind the UI's Playbooks page.

    GET /api/playbooks    {"enabled", "folder", "exists", "playbooks": [{name, description, triggers, hint, steps, chars}], "problems": [{file, reason}], "limits": {...}}

Read-only, and the only method: a playbook is the person's own file and is written in an editor, not here (nothing in Diya writes, edits or saves one). Behind the access token like the rest of the API. Everything
sent back goes through diya_memory.printable(): a file in that folder may hold anything.
"""
from __future__ import annotations

import os

import diya_playbooks
from diya_memory import printable


def register(app, config, agent):
    """Add the route to `app`, directly, like every other route. Nothing is read here: registering is free."""

    @app.get("/api/playbooks")
    def playbooks():
        found, problems = diya_playbooks.load(config.playbooks_dir) if config.playbooks else ([], [])
        return {
            "enabled": bool(config.playbooks),
            "folder": printable(config.playbooks_dir),
            "exists": os.path.isdir(config.playbooks_dir),
            "playbooks": [
                {"name": printable(p["name"]), "description": printable(p["description"], diya_playbooks.DESCRIPTION_MAX), "triggers": [printable(t) for t in p["triggers"]], "hint": printable(p["hint"]),
                 "steps": printable(p["body"], diya_playbooks.BODY_CHARS), "chars": len(p["body"])}
                for p in found
            ],
            "problems": [{"file": printable(where), "reason": printable(why, 200)} for where, why in problems],
            "limits": {"playbooks": diya_playbooks.MAX_PLAYBOOKS, "steps_chars": diya_playbooks.BODY_CHARS},
        }
