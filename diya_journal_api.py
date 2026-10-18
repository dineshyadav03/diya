"""The activity journal over HTTP (docs/ACTIVITY_JOURNAL_DESIGN.md): the route behind the Activity page.

    GET /api/journal    {"entries": [{id, at, tool, kind, origin, thread_id, message_id, args_digest, args_preview, status, result_chars, duration_ms, note}], "last_day": {"ok": 12, "error": 1, "refused": 0}}
                        the newest entries first (at most MAX_ENTRIES), and how the last 24 hours came out

Read-only: there is no way over HTTP, or anywhere, to change or delete an entry (the database refuses it). Like every route it is behind the access token, and everything sent back goes through
diya_memory.printable().
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from diya_memory import printable

MAX_ENTRIES = 100


def register(app, config, agent):
    @app.get("/api/journal")
    def journal():
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        entries = agent.store.journal_recent(MAX_ENTRIES)
        shown = [
            dict(e, tool=printable(e["tool"], 60), args_preview=printable(e["args_preview"] or "", 120), note=printable(e["note"], 200) if e["note"] else None) for e in entries
        ]
        counts = agent.store.journal_counts(since)
        return {"entries": shown, "last_day": {status: counts.get(status, 0) for status in ("ok", "error", "refused")}}
