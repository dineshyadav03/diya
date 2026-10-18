"""Dreaming's receipts over HTTP (docs/DREAMING_RECEIPTS_DESIGN.md): what the scheduled passes read and did, for the Activity page.

    GET /api/dreaming    {"runs": [...], "last_run": {...} or null, "idle_last_day": 41}
                         `runs` are the newest passes that did anything (read a message, staged, remembered, asked, sorted, or went wrong), at most MAX_RUNS; `last_run` is the newest of any kind;
                         `idle_last_day` counts the passes in the last 24 hours that found nothing to do

Read-only: the table refuses any change, and there is no route that makes one. Behind the access token like every route; every text goes through diya_memory.printable().
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from diya_memory import printable

MAX_RUNS = 30


def shown(run):
    errors = []
    if run.get("errors"):
        try:
            errors = [printable(e, 240) for e in json.loads(run["errors"])][:5]
        except (ValueError, TypeError):
            errors = [printable(run["errors"], 240)]
    out = {key: run[key] for key in ("id", "duration_ms", "first_message_id", "last_message_id", "messages_read", "staged", "remembered", "asked", "not_kept", "held", "replaced", "questions", "categories_sorted")}
    out["started_at"] = printable(run["started_at"], 40)
    out["outcome"] = printable(run["outcome"], 120)
    out["errors"] = errors
    return out


def register(app, config, agent):
    @app.get("/api/dreaming")
    def dreaming():
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        last = agent.store.dream_last_run()
        return {
            "runs": [shown(run) for run in agent.store.dream_runs_recent(MAX_RUNS)],
            "last_run": shown(last) if last else None,
            "idle_last_day": agent.store.dream_idle_count(since),
        }
