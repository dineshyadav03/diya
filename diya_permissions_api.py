"""What each connection can do, since when, and when it was last used (docs/PERMISSIONS_DESIGN.md), added 2026-10-18 for DIYA-072.

    GET /api/permissions   {"connectors": [{"name", "label", "connected", "access": [sentences], "scope": the permission asked of the service or "", "granted": [what the service said it granted] or null, "granted_matches": bool or null, "since": ISO time or null,
                                            "last_used": {"at", "what", "ok"} or null, "last_action": {"summary", "status", "at"} or null}]}

Everything is taken from facts that are already recorded, never from the model: `access` is what the connector's code declares, `since` is when the stored sign-in was written, `last_used` is the newest row of
the activity journal for a tool that belongs to that connector, and `last_action` is the newest approved action that was run through it. Read-only, behind the access token like every route; no token or
credential is ever in the answer.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import diya_catalog
import diya_connectors
from diya_memory import printable


def _since(config, name):
    try:
        return datetime.fromtimestamp(os.path.getmtime(diya_connectors._token_path(config, name)), tz=timezone.utc).isoformat()
    except OSError:
        return None


def overview(config, agent, connector):
    tools = [entry.name for entry in diya_catalog.CATALOG.values() if entry.connector == connector.name]
    connected = diya_connectors.is_connected(config, connector.name)
    last_used = None
    row = agent.store.journal_last(tools) if tools else None
    if row is not None:
        last_used = {"at": printable(row["at"], 40), "what": printable(diya_catalog.CATALOG[row["tool"]].effect, 120), "ok": row["status"] == "ok"}
    last_action = None
    for action in reversed(agent.actions.actions()):
        kind = next((k for k in agent.actions.kinds if k.name == action["kind"]), None)
        if kind is not None and kind.connector == connector.name and action["executed_at"] is not None:
            last_action = {"summary": printable(action["summary"], 200), "status": action["status"], "at": printable(action["executed_at"], 40)}
            break
    granted = diya_connectors.read_granted(config, connector.name) if connected else None
    return {
        "name": connector.name,
        "label": printable(connector.label),
        "connected": connected,
        "access": [printable(line, 200) for line in connector.access],
        "scope": printable(connector.scope, 120),
        "granted": [printable(item, 120) for item in granted] if granted else None,  # what the service said it granted (None: it did not say)
        "granted_matches": None if not granted or not connector.scope else connector.scope in granted and len(granted) == 1,
        "since": _since(config, connector.name) if connected else None,
        "last_used": last_used,
        "last_action": last_action,
    }


def register(app, config, agent, connectors):
    @app.get("/api/permissions")
    def permissions():
        return {"connectors": [overview(config, agent, c) for c in connectors if c.implemented]}
