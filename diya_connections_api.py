"""Connectors over HTTP (docs/CONNECTORS_DESIGN.md, D6): the routes behind the UI's Connections page.

    GET  /api/connections                     every known connector type and its state
    POST /api/connections/{name}/connect      a token-kind connector: {"token": ...}. An oauth-kind
                                               one (unit C3): no body -- this call runs the whole
                                               browser flow itself and blocks until it finishes.
    POST /api/connections/connect-google     every Google card in ONE sign-in (no body; blocks until the owner finishes in the browser): {"connectors", "connected": [labels], "left_out": [labels]}.
                                               A card whose permission was unticked on Google's screen is left out and stays as it was. 422 with the reason when nothing could be connected.
    POST /api/connections/{name}/disconnect   remove a connector's stored credential (idempotent), and where the service has a way (Google) take the permission back there too:
                                               the answer says `revoked` true (done), false (could not be confirmed) or null (nothing to do, or left for the last Google card)
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
import diya_google_calendar
from diya_connectors import ConnectorError
from diya_memory import printable


class ConnectBody(BaseModel):
    token: str


class SetupBody(BaseModel):
    values: dict[str, str]


def register(app, config, agent, connectors=diya_connectors.CONNECTORS, connect_all=diya_google_calendar.connect_all):
    """Add the connections routes to `app`. `connectors` defaults to the real registry but can be
    overridden (tests use fakes, since C1 itself registers none for real). `connect_all` is the one Google
    sign-in for every Google card (tests stand in for Google's side of it)."""

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

    @app.post("/api/connections/connect-google")
    def connect_google():
        group = {c.name: c.scope for c in connectors if c.name in diya_google_calendar.ALL_GOOGLE and c.implemented and c.scope}
        labels = {c.name: c.label for c in connectors}
        try:
            connected, left_out = connect_all(config, group)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=printable(str(exc)))
        return {
            "connectors": diya_connectors.status(config, connectors),
            "connected": [printable(labels.get(name, name)) for name in connected],
            "left_out": [printable(labels.get(name, name)) for name in left_out],
        }

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
        connector = find(name)
        revoked = diya_connectors.revoke_and_disconnect(config, connector)  # also takes the permission back at the service where it can; always disconnects
        return {"connectors": diya_connectors.status(config, connectors), "revoked": revoked}
