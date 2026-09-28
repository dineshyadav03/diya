"""Connectors and permissions (docs/CONNECTORS_DESIGN.md): a connector is a tool, the same as
get_weather, except it authenticates as a real account the owner owns. This module is the shared
plumbing unit C1 builds -- the registry, credential storage and the plain call log -- not any one
connector: CONNECTORS is empty until a later unit registers the first real ones (C2, C3), the same
way person-tagged memory's storage (M1) came before anything used it.

A connector's credential never lives in the database: it is a file of its own (D1), the same
discipline diya_web.py's own access token already uses, so a database backup or an export never
carries someone else's account access along with it.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
AUTH_KINDS = ("token", "oauth")


class ConnectorError(Exception):
    """A token that fails its own validation, or a connector that is not ready to connect yet."""


@dataclass(frozen=True)
class Connector:
    """One connector TYPE (docs/CONNECTORS_DESIGN.md, D6): what the Connections page offers, not a
    live connection. `auth_kind` is "token" (a form: paste a token, checked by `validate` before
    saving) or "oauth" (a browser redirect, built in a later unit). `implemented` is False for every
    connector C1 lists: the type is real and documented, but there is nothing yet to connect to."""

    name: str
    label: str
    description: str
    auth_kind: str
    implemented: bool = False
    validate: object = None  # token-kind only: callable(token) -> None, raises ConnectorError

    def __post_init__(self):
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"a connector name must be lowercase letters, digits and underscores: {self.name!r}")
        if self.auth_kind not in AUTH_KINDS:
            raise ValueError(f"auth_kind must be one of {AUTH_KINDS}, got {self.auth_kind!r}")
        if self.implemented and self.auth_kind == "token" and self.validate is None:
            raise ValueError(f"{self.name}: an implemented token connector needs a validate function")


CONNECTORS: tuple = ()  # a later unit adds the real ones; empty is C1's own correct state


def by_name(connectors, name):
    """The connector called `name`, or None. `connectors` is passed explicitly (not a hidden global)
    so a test can supply fakes without touching the real registry."""
    for connector in connectors:
        if connector.name == name:
            return connector
    return None


def _token_path(config, name):
    return os.path.join(config.connector_tokens_dir, f"{name}.token")


def is_connected(config, name):
    return os.path.exists(_token_path(config, name))


def read_token(config, name):
    """The stored token, or None if this connector has never been connected (or was disconnected)."""
    try:
        with open(_token_path(config, name), encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def connect(config, connector, token):
    """Validate `token` (docs/CONNECTORS_DESIGN.md, D6: checked before saving) and store it. Raises
    ConnectorError, and writes nothing, for a connector that is not implemented yet, an empty token,
    or one `connector.validate` refuses."""
    if not connector.implemented:
        raise ConnectorError(f"{connector.label} is not available yet")
    token = token.strip()
    if not token:
        raise ConnectorError("a token cannot be empty")
    if connector.validate is not None:
        connector.validate(token)  # raises ConnectorError for one that doesn't work; nothing written yet
    os.makedirs(config.connector_tokens_dir, exist_ok=True)
    path = _token_path(config, connector.name)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        f.write(token + "\n")
    os.replace(temporary, path)  # never leaves a half-written file where a real token was
    log_call(config, connector.name, "connected", True)


def disconnect(config, name):
    """Remove the stored token, if there is one. Idempotent: disconnecting something that was never
    connected is not an error, it is already the state being asked for. Never touches anything the
    connector already fetched (docs/CONNECTORS_DESIGN.md, D6) -- only stops future calls."""
    try:
        os.remove(_token_path(config, name))
        removed = True
    except FileNotFoundError:
        removed = False
    log_call(config, name, "disconnected", True, detail=None if removed else "was not connected")
    return removed


def log_call(config, name, action, ok, detail=None):
    """One plain line per connector action (docs/CONNECTORS_DESIGN.md, D3): what, when, success or
    not, so the owner can always answer "what did Diya do with this connector" without trusting the
    model's own account of it. Never the token, and never more than a short caller-supplied detail."""
    at = datetime.now(timezone.utc).isoformat()
    line = f"{at}  {name}  {action}  {'ok' if ok else 'failed'}"
    if detail:
        line += f"  {detail}"
    with open(config.connectors_log_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def status(config, connectors):
    """Every known connector type and its state, for the Connections page and its API."""
    return [
        {
            "name": c.name,
            "label": c.label,
            "description": c.description,
            "auth_kind": c.auth_kind,
            "implemented": c.implemented,
            "connected": is_connected(config, c.name),
        }
        for c in connectors
    ]
