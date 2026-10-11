"""Web Push over HTTP (docs/PUSH_DESIGN.md, unit P2): the routes behind the UI's "Notify this device" button.

    GET  /api/push/status        {"enabled": bool, "problem": str|None, "devices": [{id, service, created_at, last_ok_at, failures}]}   never an endpoint or a key
    GET  /api/push/key           {"key": "<the application server key, public>"}   what the browser subscribes with
    POST /api/push/subscribe     {"endpoint": ..., "keys": {"p256dh": ..., "auth": ...}}   what a browser's PushSubscription.toJSON() gives; 201 {"id": n}
    POST /api/push/unsubscribe   {"endpoint": ...}   {"removed": bool}
    POST /api/push/test          send one notification that says nothing about the person to every device: {"accepted": n, "failed": m}

Everything but /status is refused (409, with the reason) unless DIYA_PUSH=1 and the cryptography package is installed; /status says why not. Like every other route these are behind
the access token. A refusal of a subscription is a 422 with the rule it broke; the body of a failed request is never echoed, and no response, error or log line holds an endpoint.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya_events
import diya_push
from diya_memory import printable


class Keys(BaseModel):
    p256dh: str
    auth: str


class SubscribeBody(BaseModel):
    endpoint: str
    keys: Keys
    expirationTime: float | None = None  # sent by browsers; not used


class UnsubscribeBody(BaseModel):
    endpoint: str


def register(app, config, agent, post=None):
    """Add the push routes to `app`, directly, like every other route. `post` is for tests (a stand-in for the HTTPS request to a push service)."""
    send = post or diya_push.post_https

    def ready():
        problem = diya_push.readiness(config)
        if problem:
            raise HTTPException(status_code=409, detail=problem)

    @app.get("/api/push/status")
    def status():
        problem = diya_push.readiness(config)
        devices = diya_push.Subscriptions(agent.store).public() if problem is None else []
        return {"enabled": problem is None, "problem": problem, "devices": devices}

    @app.get("/api/push/key")
    def key():
        ready()
        try:
            return {"key": diya_push.Vapid.load_or_create(config.push_vapid_path).public_b64u}
        except diya_push.PushError as exc:
            raise HTTPException(status_code=500, detail=printable(exc))

    @app.post("/api/push/subscribe", status_code=201)
    def subscribe(body: SubscribeBody):
        ready()
        try:
            return {"id": diya_push.Subscriptions(agent.store).add(body.endpoint, body.keys.p256dh, body.keys.auth, diya_events.utc_of_local(agent.now()))}
        except diya_push.InvalidSubscription as exc:
            raise HTTPException(status_code=422, detail=printable(exc))

    @app.post("/api/push/unsubscribe")
    def unsubscribe(body: UnsubscribeBody):
        ready()
        return {"removed": diya_push.Subscriptions(agent.store).remove_endpoint(body.endpoint)}

    @app.post("/api/push/test")
    def test():
        ready()
        try:
            accepted, failed = diya_push.send_test(agent.store, config, post=send)
        except diya_push.PushError as exc:
            raise HTTPException(status_code=500, detail=printable(exc))
        return {"accepted": accepted, "failed": failed}
