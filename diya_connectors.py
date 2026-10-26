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

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import diya_secrets

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
AUTH_KINDS = ("token", "oauth")


class ConnectorError(Exception):
    """A token that fails its own validation, or a connector that is not ready to connect yet."""


@dataclass(frozen=True)
class Setup:
    """What an OAuth connector needs given once before it can connect, and where it comes from (docs/CONNECTORS_DESIGN.md, "Setting up Google from the page"). `fields` are
    (name, label, secret) for the form; `steps` is the plain-words list of what to do in the other service to get them; `state(config)` says where they are now ("file" for the page,
    "environment" for a DIYA_* setting, or None); `save(config, values)` checks and stores them, raising ConnectorError for ones that cannot be right; `clear(config)` forgets what the page
    stored (and says whether there was any)."""

    fields: tuple
    steps: tuple
    state: object
    save: object
    clear: object


@dataclass(frozen=True)
class Connector:
    """One connector TYPE (docs/CONNECTORS_DESIGN.md, D6): what the Connections page offers, not a
    live connection. `auth_kind` is "token" (a form: paste a token, checked by `validate` before
    saving) or "oauth" (`oauth_connect(config)` runs the whole browser flow and stores the result
    itself -- see docs/CONNECTORS_DESIGN.md, D6 revised for unit C3). `implemented` is False for a
    connector type that is documented but has nothing real behind it yet."""

    name: str
    label: str
    description: str
    auth_kind: str
    implemented: bool = False
    validate: object = None  # token-kind only: callable(token) -> None, raises ConnectorError
    oauth_connect: object = None  # oauth-kind only: callable(config) -> None, raises ConnectorError
    setup: object = None  # a Setup, for a connector that needs something given once (a client id and secret) before it can connect; None for the rest
    access: tuple = ()  # what this connection can do, one plain sentence each (the permissions page shows them as they are)
    scope: str = ""  # the permission it asks the service for, as the service names it ("" for a pasted token)
    revoke: object = None  # callable(config, token) -> bool: takes the permission back at the service itself when the owner disconnects (Google); None for a connector that has no such step

    def __post_init__(self):
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"a connector name must be lowercase letters, digits and underscores: {self.name!r}")
        if self.auth_kind not in AUTH_KINDS:
            raise ValueError(f"auth_kind must be one of {AUTH_KINDS}, got {self.auth_kind!r}")
        if self.implemented and self.auth_kind == "token" and self.validate is None:
            raise ValueError(f"{self.name}: an implemented token connector needs a validate function")
        if self.implemented and self.auth_kind == "oauth" and self.oauth_connect is None:
            raise ValueError(f"{self.name}: an implemented oauth connector needs an oauth_connect function")


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


def _signed_out_path(config, name):
    return os.path.join(config.connector_tokens_dir, f"{name}.signedout")


def _fingerprint(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def mark_signed_out(config, name):
    """Remember that the SERVICE said this sign-in no longer works (Google's invalid_grant: the person removed Diya at Google, or the grant ran out), so nothing asks it again until the person connects again
    (DIYA-065). What is kept is a short fingerprint of the stored token and the time, never the token: a new connection has another token, so the mark stops applying by itself."""
    token = read_token(config, name)
    if token is None:
        return
    os.makedirs(config.connector_tokens_dir, exist_ok=True)
    path = _signed_out_path(config, name)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{_fingerprint(token)}\n{datetime.now(timezone.utc).isoformat()}\n")
    os.replace(path + ".tmp", path)
    log_call(config, name, "signed out by the service", False)


def signed_out(config, name):
    """Has the service signed this connection out (and has it not been connected again since)?"""
    token = read_token(config, name)
    if token is None:
        return False
    try:
        with open(_signed_out_path(config, name), encoding="utf-8") as f:
            return f.readline().strip() == _fingerprint(token)
    except OSError:
        return False


def is_connected(config, name):
    """Is there a sign-in that can be used? One that cannot be decrypted here (a protected file copied from another Windows user or machine) counts as none: reconnecting is the way out."""
    return read_token(config, name) is not None


def _protecting(config):
    return getattr(config, "protect_secrets", True) and diya_secrets.available()


def read_token(config, name):
    """The stored token, or None if this connector has never been connected (or was disconnected, or its file cannot be decrypted here). A token stored before secrets were protected (plain text) is
    read as it is and rewritten protected, once (docs/SECRETS_DESIGN.md)."""
    try:
        with open(_token_path(config, name), encoding="utf-8") as f:
            stored = f.read().strip()
    except FileNotFoundError:
        return None
    token = diya_secrets.unprotect(stored) if stored else None
    if token and _protecting(config) and not diya_secrets.is_protected(stored):
        try:
            _write_token(config, name, token)
        except OSError:
            pass  # a folder that cannot be written to still gives its token; it stays plain
    return token or None


def _write_token(config, name, token):
    os.makedirs(config.connector_tokens_dir, exist_ok=True)
    path = _token_path(config, name)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        f.write(diya_secrets.protect(token, _protecting(config)) + "\n")
    os.replace(temporary, path)  # never leaves a half-written file where a real token was


def store_token(config, name, token):
    """Write `name`'s credential to its own file, atomically, protected for this Windows user where the system can (docs/SECRETS_DESIGN.md) -- the part of connecting that is the
    same whether the credential was pasted (a token-kind connector) or came out of an OAuth exchange
    (an oauth-kind one, docs/CONNECTORS_DESIGN.md, D6): validation differs by connector, storage does
    not. Logs the same "connected" line either way."""
    _write_token(config, name, token)
    log_call(config, name, "connected", True)


def connect(config, connector, token):
    """The token-kind path (docs/CONNECTORS_DESIGN.md, D6): validate a pasted `token` and store it.
    Raises ConnectorError, and writes nothing, for a connector that is not implemented yet, an empty
    token, or one `connector.validate` refuses. An oauth-kind connector's own `oauth_connect(config)`
    calls `store_token` directly instead -- there is no pasted token to validate here."""
    if not connector.implemented:
        raise ConnectorError(f"{connector.label} is not available yet")
    token = token.strip()
    if not token:
        raise ConnectorError("a token cannot be empty")
    if connector.validate is not None:
        connector.validate(token)  # raises ConnectorError for one that doesn't work; nothing written yet
    store_token(config, connector.name, token)


def disconnect(config, name):
    """Remove the stored token, if there is one. Idempotent: disconnecting something that was never
    connected is not an error, it is already the state being asked for. Never touches anything the
    connector already fetched (docs/CONNECTORS_DESIGN.md, D6) -- only stops future calls."""
    try:
        os.remove(_token_path(config, name))
        removed = True
    except FileNotFoundError:
        removed = False
    for leftover in (_granted_path(config, name), _signed_out_path(config, name), _together_path(config, name)):
        try:
            os.remove(leftover)
        except OSError:
            pass
    log_call(config, name, "disconnected", True, detail=None if removed else "was not connected")
    return removed


def _granted_path(config, name):
    return os.path.join(config.connector_tokens_dir, f"{name}.granted")


def store_granted(config, name, scope_text):
    """Remember which permissions the service SAID it granted when the sign-in finished (Google's token answer lists them), so the permissions page can show what was actually granted and not only what was
    asked for. Not a secret (it names permissions, not a credential). A missing or empty answer stores nothing."""
    if not isinstance(scope_text, str) or not scope_text.strip():
        return
    os.makedirs(config.connector_tokens_dir, exist_ok=True)
    with open(_granted_path(config, name), "w", encoding="utf-8", newline=chr(10)) as f:
        f.write(" ".join(scope_text.split()) + chr(10))


def _together_path(config, name):
    return os.path.join(config.connector_tokens_dir, f"{name}.together")


def store_together(config, name, asked):
    """Remember that this connection was made in ONE sign-in that asked the service for several permissions at once (Google's "Connect all"), and which: the permissions page then compares what the service
    granted with the whole list that was asked, not with this one connector's own permission. Not a secret (it names permissions). Written beside the token and removed with it."""
    os.makedirs(config.connector_tokens_dir, exist_ok=True)
    with open(_together_path(config, name), "w", encoding="utf-8", newline=chr(10)) as f:
        f.write(" ".join(sorted(set(asked))) + chr(10))


def read_together(config, name):
    """The permissions the one shared sign-in asked for, as a list, or None when this connection was made on its own."""
    try:
        with open(_together_path(config, name), encoding="utf-8") as f:
            found = f.read().split()
    except OSError:
        return None
    return found or None


def clear_together(config, name):
    """This connection is now made on its own (connected again by its own card): it no longer shares a sign-in."""
    try:
        os.remove(_together_path(config, name))
    except OSError:
        pass


def read_granted(config, name):
    """The permissions the service said it granted, as a list, or None when it did not say (or the sign-in is from before this was kept)."""
    try:
        with open(_granted_path(config, name), encoding="utf-8") as f:
            found = f.read().split()
    except OSError:
        return None
    return found or None


def revoke_and_disconnect(config, connector):
    """Disconnect, and where the service has a way, take the permission back there too, so that removing the sign-in here is not only forgetting it here. True: the service was told and agreed.
    False: it could not be reached or refused, so the permission can still be removed by hand at the service. None: this connector has no such step, or the step was left for later (Google: another Google
    card still uses the same app). Nothing is raised: disconnecting always happens."""
    revoked = None
    if connector.revoke is not None:
        token = read_token(config, connector.name)
        if token is not None:
            try:
                answer = connector.revoke(config, token)  # None: not now (another connector still uses the same app's permission)
                revoked = None if answer is None else bool(answer)
            except Exception:  # noqa: BLE001 -- whatever the service did, the sign-in here is removed below
                revoked = False
    disconnect(config, connector.name)
    if revoked is not None:
        log_call(config, connector.name, "permission revoked at the service", revoked)
    return revoked


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


def setup_status(config, connector):
    """The page's view of a connector's one-time setup: what to ask for, what to do to get it, and whether it is done and from where. Never the values themselves."""
    setup = connector.setup
    state = setup.state(config)
    return {
        "fields": [{"name": name, "label": label, "secret": bool(secret)} for name, label, secret in setup.fields],
        "steps": list(setup.steps),
        "done": state is not None,
        "from": state,
    }


def save_setup(config, connector, values):
    """Check and store a connector's one-time setup. ConnectorError, and nothing stored, for a connector that has none or values that cannot be right."""
    if connector.setup is None:
        raise ConnectorError(f"{connector.label} does not need any setup")
    wanted = {name for name, _label, _secret in connector.setup.fields}
    given = {str(k): str(v) for k, v in (values or {}).items() if str(k) in wanted}
    missing = [label for name, label, _secret in connector.setup.fields if not given.get(name, "").strip()]
    if missing:
        raise ConnectorError(f"fill in: {', '.join(missing)}")
    connector.setup.save(config, {k: v.strip() for k, v in given.items()})
    log_call(config, connector.name, "setup saved", True)


def clear_setup(config, connector):
    """Forget what the page stored for a connector, and disconnect it: a stored sign-in belongs to the app it was made with, so it cannot outlive a change of app."""
    if connector.setup is None:
        raise ConnectorError(f"{connector.label} does not need any setup")
    removed = connector.setup.clear(config)
    disconnect(config, connector.name)
    log_call(config, connector.name, "setup cleared", True, detail=None if removed else "had none stored")
    return removed


def status(config, connectors):
    """Every known connector type and its state, for the Connections page and its API."""
    found = []
    for c in connectors:
        entry = {
            "name": c.name,
            "label": c.label,
            "description": c.description,
            "auth_kind": c.auth_kind,
            "implemented": c.implemented,
            "connected": is_connected(config, c.name),
        }
        if c.setup is not None:
            entry["setup"] = setup_status(config, c)
        found.append(entry)
    return found
