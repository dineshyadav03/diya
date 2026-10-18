"""The health report over HTTP (docs/HEALTH_DESIGN.md): the route behind the Status page.

    GET /api/health    {"overall": "ok" | "warn" | "bad", "items": [{name, label, status, text}]}   see diya_health.collect

Read-only, behind the access token like every route. Looking costs a quick SQLite check, a few file reads and one short question to Ollama (two seconds at most).
"""
from __future__ import annotations

import diya_health


def register(app, config, agent, ping=diya_health.ping_ollama):
    @app.get("/api/health")
    def health():
        return diya_health.collect(config, agent.store, ping=ping)
