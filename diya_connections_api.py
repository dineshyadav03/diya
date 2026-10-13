"""Connectors over HTTP (docs/CONNECTORS_DESIGN.md, D6): the routes behind the UI's Connections page.

    GET  /api/connections                     every known connector type and its state
    POST /api/connections/{name}/connect      a token-kind connector: {"token": ...}. An oauth-kind
                                               one (unit C3): no body -- this call runs the whole
                                               browser flow itself and blocks until it finishes.
    POST /api/connections/{name}/disconnect   remove a connector's stored credential (idempotent)
    POST /api/connections/{name}/setup        {"values": {"client_id": ..., "client_secret": ...}}: what a connector needs given once before it can connect (Google's client id
                                               and secret); checked for shape, stored, and never sent back. 409 for a connector that needs none.
    POST /api/connections/{name}/clear-setup  forget what the page stored for it, and disconnect it (a sign-in belongs to the app it was made with)

GET and POST only, like every other route; every route is behind the access token like the rest of
the API. A refusal is an HTTP error with the reason in `detail`: 404 for a connector name that does
not exist, 409 for one that is not implemented yet, 422 for a token (or an OAuth step) its own
connector refuses.

Nothing here ever reads back or echoes a stored token: `status()` reports only whether one exists.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya_connectors
from diya_connectors import ConnectorError
from diya_memory import printable


class ConnectBody(BaseModel):
    token: str


class SetupBody(BaseModel):
    values: dict[str, str]


def register(app, config, agent, connectors=diya_connectors.CONNECTORS):
    """Add the connections routes to `app`. `connectors` defaults to the real registry but can be
    overridden (tests use fakes, since C1 itself registers none for real)."""

    def find(name):
        connector = diya_connectors.by_name(connectors, name)
        if connector is None:
            raise HTTPException(status_code=404, detail=f"there is no connector {printable(name)}")
        return connector

    @app.get("/api/connections")
    def list_connections():
        return {"connectors": diya_connectors.status(config, connectors)}

    @app.post("/api/connections/{name}/connect")
    def connect(name: str, body: ConnectBody | None = None):
        connector = find(name)
        if not connector.implemented:
            raise HTTPException(status_code=409, detail=f"{connector.label} is not available yet")
        try:
            if connector.auth_kind == "token":
                if body is None:
                    raise HTTPException(status_code=422, detail="connecting needs a token")
                diya_connectors.connect(config, connector, body.token)
            else:
                connector.oauth_connect(config)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=printable(str(exc)))
        return {"connectors": diya_connectors.status(config, connectors)}

    @app.post("/api/connections/{name}/setup")
    def setup(name: str, body: SetupBody):
        connector = find(name)
        if connector.setup is None:
            raise HTTPException(status_code=409, detail=f"{connector.label} does not need any setup")
        try:
            diya_connectors.save_setup(config, connector, body.values)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=printable(str(exc)))
        return {"connectors": diya_connectors.status(config, connectors)}

    @app.post("/api/connections/{name}/clear-setup")
    def clear_setup(name: str):
        connector = find(name)
        if connector.setup is None:
            raise HTTPException(status_code=409, detail=f"{connector.label} does not need any setup")
        diya_connectors.clear_setup(config, connector)
        return {"connectors": diya_connectors.status(config, connectors)}

    @app.post("/api/connections/{name}/disconnect")
    def disconnect(name: str):
        find(name)
        diya_connectors.disconnect(config, name)
        return {"connectors": diya_connectors.status(config, connectors)}
