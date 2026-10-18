"""The health report over HTTP (docs/HEALTH_DESIGN.md): the route behind the Status page.

    GET /api/health    {"overall": "ok" | "warn" | "bad", "items": [{name, label, status, text}]}   see diya_health.collect
    POST /api/pause    {"reason": "..."} (optional): the kill switch, docs/PAUSE_DESIGN.md. Answers the state {"paused", "since", "reason"}
    POST /api/resume   the same state, after it is lifted

Behind the access token like every route. Looking (GET) changes nothing and costs a quick SQLite check, a few file reads and one short question to Ollama (two seconds at most).
"""
from __future__ import annotations

from pydantic import BaseModel

import diya_health
import diya_pause


class PauseBody(BaseModel):
    reason: str = ""


def register(app, config, agent, ping=diya_health.ping_ollama):
    @app.get("/api/health")
    def health():
        return diya_health.collect(config, agent.store, ping=ping)

    @app.post("/api/pause")
    def pause(body: PauseBody | None = None):
        """Stop Diya acting on her own (docs/PAUSE_DESIGN.md): approved actions are not run, automations do not run, she does not write first. Reminders still fire."""
        return diya_pause.pause(agent.store, body.reason if body else "")

    @app.post("/api/resume")
    def resume():
        return diya_pause.resume(agent.store)
