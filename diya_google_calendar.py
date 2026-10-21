"""Google Calendar (docs/CONNECTORS_DESIGN.md, unit C3): Diya's first OAuth connector, and a revision
of D6's original "browser redirect ending back on this page" for what a single-machine, one-owner app
actually needs -- since the browser and the server are the same machine, there is no separate page to
navigate back to. Clicking Connect for this connector, per RFC 8252 ("OAuth 2.0 for Native Apps" --
the pattern Google, and every other IdP, recommends for exactly this shape of app), opens the owner's
own browser to Google's own consent screen and BLOCKS until a temporary local server on an OS-assigned
loopback port catches the redirect back, then exchanges the code for a refresh token -- the credential
that gets stored, through the same diya_connectors.store_token every connector uses.

Needs a client id and secret, from an OAuth client the owner registers themselves (Google Cloud
Console, "Desktop app" type, since only that type gets RFC 8252's loopback exception -- an arbitrary
port, not one fixed at registration time) -- Diya cannot create one. They are pasted once on the
Connections page (stored in a file of their own beside the connector tokens) or set as
DIYA_GOOGLE_CLIENT_ID and DIYA_GOOGLE_CLIENT_SECRET, which win if both exist. The client secret is not
treated as fully confidential here either way (Google's own guidance: a desktop app cannot keep one
secret, which is exactly why the loopback redirect and a one-time code exist), but it is still the
owner's, never committed, never sent back to the page, like every other credential.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import urllib.parse
import webbrowser
from datetime import datetime, timezone

import httpx

import diya_connectors
import diya_secrets
from diya_connectors import ConnectorError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"  # read-only (D2): nothing here can write
CALLBACK_TIMEOUT = 120  # seconds to let the owner finish in their browser
NETWORK_TIMEOUT = 10.0


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catches exactly one redirect from Google on the server's own loopback port and hands its query
    string back to whoever is waiting. Never logs to stderr -- BaseHTTPRequestHandler's default does,
    on every request, which has no home in Diya's own logs."""

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self.server.result = {k: v[0] for k, v in query.items()}
        body = b"<p>Google has answered. Go back to Diya: the Connections page says whether the connection worked. You can close this tab.</p>"  # (said before the code is exchanged, so it must not claim success)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _wait_for_redirect(timeout):
    """Starts a loopback HTTP server on an OS-assigned port. Returns (port, a function that blocks
    until Google's redirect arrives or `timeout` elapses, then returns its query params or raises)."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.timeout = timeout
    server.result = None

    def wait():
        server.handle_request()  # blocks for at most `timeout`, serving exactly one request
        server.server_close()
        if server.result is None:
            raise ConnectorError("Google never redirected back -- the request timed out or was cancelled")
        return server.result

    return server.server_address[1], wait


def pkce_pair():
    """A fresh PKCE (RFC 7636) verifier and its S256 challenge: Google gets the challenge when the sign-in starts and the verifier when the code is exchanged, so a code someone else caught on the
    loopback port is no use to them without the verifier, which never leaves this process."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _authorization_url(client_id, redirect_uri, state, scope=SCOPE, challenge=None):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",  # otherwise a returning owner may not be issued a refresh token at all
        "state": state,
    }
    if challenge:
        params.update({"code_challenge": challenge, "code_challenge_method": "S256"})
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _exchange(data):
    """The one Google token-endpoint shape both the initial code exchange and a later refresh use."""
    try:
        response = httpx.post(TOKEN_URL, data=data, timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"couldn't reach Google: {exc}")
    if response.status_code != 200:
        raise ConnectorError(f"Google answered with HTTP {response.status_code}{_reason(response)}")
    return response.json()


def _reason(response):
    """Google's own short reason for a refusal ("invalid_client", "invalid_grant", and its one line of explanation), as text to add to an error message: ' (invalid_client: Unauthorized)'. Empty when there is
    none. It names a reason, never a value: the answer holds no secret, and only its two short text fields are read."""
    try:
        body = response.json()
        code, why = str(body.get("error", ""))[:60], str(body.get("error_description", ""))[:120]
    except (ValueError, AttributeError):
        return ""
    return f" ({code}: {why})" if code and why else f" ({code})" if code else ""


CLIENT_ID_SHAPE = re.compile(r"[0-9A-Za-z._-]{8,200}\.apps\.googleusercontent\.com")
CLIENT_SECRET_SHAPE = re.compile(r"[0-9A-Za-z._~-]{8,200}")


def _client_file(config):
    return os.path.join(config.connector_tokens_dir, "google_calendar.client")


def _stored_client(config):
    """The client id and secret pasted on the Connections page, or None (nothing stored, or a file that is not what save_client writes)."""
    try:
        with open(_client_file(config), encoding="utf-8") as f:
            stored = f.read()
    except OSError:
        return None
    text = diya_secrets.unprotect(stored.strip())  # None: protected for another Windows user or damaged
    try:
        data = json.loads(text) if text else None
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    client_id, client_secret = str(data.get("client_id") or "").strip(), str(data.get("client_secret") or "").strip()
    if not (client_id and client_secret):
        return None
    if getattr(config, "protect_secrets", True) and diya_secrets.available() and not diya_secrets.is_protected(stored.strip()):
        try:
            _write_client(config, client_id, client_secret)  # a file from before secrets were protected: rewritten protected, once
        except OSError:
            pass
    return client_id, client_secret


def _write_client(config, client_id, client_secret):
    os.makedirs(config.connector_tokens_dir, exist_ok=True)
    path = _client_file(config)
    temporary = path + ".tmp"
    text = json.dumps({"client_id": client_id, "client_secret": client_secret})
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        f.write(diya_secrets.protect(text, getattr(config, "protect_secrets", True)) + "\n")
    try:
        os.chmod(temporary, 0o600)  # a no-op for most of what Windows means by permissions; the folder is the owner's own either way
    except OSError:
        pass
    os.replace(temporary, path)


def client_state(config):
    """Where Google's client id and secret are now: "environment" (the DIYA_GOOGLE_* settings, which win), "file" (pasted on the page) or None."""
    if (config.google_client_id or "").strip() and (config.google_client_secret or "").strip():
        return "environment"
    return "file" if _stored_client(config) else None


def save_client(config, values):
    """Check a pasted client id and secret for the shape Google gives them and store them (atomically, readable by the owner only where the system allows). ConnectorError, and nothing
    stored, for ones that cannot be right: a refusal says what the shape is, never what was pasted."""
    client_id, client_secret = values.get("client_id", "").strip(), values.get("client_secret", "").strip()
    if not CLIENT_ID_SHAPE.fullmatch(client_id):
        raise ConnectorError("that does not look like a Google client ID: it is a long text that ends in .apps.googleusercontent.com")
    if not CLIENT_SECRET_SHAPE.fullmatch(client_secret):
        raise ConnectorError("that does not look like a Google client secret: letters, digits, - and _ only, no spaces")
    _write_client(config, client_id, client_secret)


# The other Google connectors that sign in with this client: forgetting it signs them out too (a sign-in belongs to the app it was made with).
SHARING_CLIENT = ("google_mail", "google_calendar_edit", "google_tasks", "google_drive_files")
ALL_GOOGLE = ("google_calendar",) + SHARING_CLIENT


def revoke_for(name):
    """The `revoke` step of one Google connector (diya_connectors.Connector.revoke): tell Google to forget its permission. True if Google confirmed, False if it could not be reached or refused. None, and
    nothing sent, while another Google card is still connected: Google may treat the permissions of one app as one, so revoking now could sign the others out. The last card to be disconnected revokes."""
    def revoke(config, token):
        if any(other != name and diya_connectors.is_connected(config, other) for other in ALL_GOOGLE):
            return None
        try:
            response = httpx.post(REVOKE_URL, data={"token": token}, timeout=NETWORK_TIMEOUT)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    return revoke


def clear_client(config):
    """Forget what the page stored. True if there was something. What the DIYA_GOOGLE_* settings say is the owner's to change, not this page's. The client is Google's and is shared by every Google
    connector (Calendar, Gmail), and a sign-in belongs to the app it was made with, so Gmail is disconnected with it (the framework disconnects the connector whose card was used)."""
    for name in SHARING_CLIENT:
        if diya_connectors.is_connected(config, name):
            diya_connectors.disconnect(config, name)
    try:
        os.remove(_client_file(config))
        return True
    except FileNotFoundError:
        return False


def _client_credentials(config):
    client_id = (config.google_client_id or "").strip()
    client_secret = (config.google_client_secret or "").strip()
    if not client_id or not client_secret:
        stored = _stored_client(config)
        if stored is None:
            raise ConnectorError("Google is not set up yet: paste your Google client ID and secret on the Connections page first (or set DIYA_GOOGLE_CLIENT_ID and DIYA_GOOGLE_CLIENT_SECRET; docs/GOOGLE_SETUP.md)")
        client_id, client_secret = stored
    return client_id, client_secret


SETUP = diya_connectors.Setup(
    fields=(("client_id", "Client ID", False), ("client_secret", "Client secret", True)),
    steps=(
        "Open console.cloud.google.com and create a project (any name).",
        "APIs & Services, Library: search for Google Calendar API and press Enable.",
        "APIs & Services, OAuth consent screen (called Google Auth platform in the newer console): choose External, fill in the app name and your email, and add your own Google address as a test user. "
        "Then, under Audience, set Publishing status to In production, or Google ends the sign-in after 7 days (the app stays unverified and shows a warning screen: that is expected for your own app).",
        "APIs & Services, Credentials (Clients, in the newer console): Create credentials, OAuth client ID, Application type Desktop app.",
        "Copy the Client ID and the Client secret it shows into the two boxes here.",
    ),
    state=client_state,
    save=save_client,
    clear=clear_client,
)


def connect(config, open_browser=webbrowser.open):
    """Connect Google Calendar: connect_to with the read-only calendar scope."""
    return connect_to(config, SCOPE, "google_calendar", open_browser)


def connect_to(config, scope, token_name, open_browser=webbrowser.open):
    """The whole flow, one call, for any Google scope (Calendar, Gmail, the adding ones): opens the owner's browser (with a PKCE challenge, RFC 7636), waits for them to finish, stores the
    refresh token under `token_name` (docs/CONNECTORS_DESIGN.md, D6). Raises ConnectorError, and stores nothing, at any
    failed step -- a cancelled or failed attempt never leaves a half-connected state."""
    client_id, client_secret = _client_credentials(config)

    port, wait = _wait_for_redirect(CALLBACK_TIMEOUT)
    redirect_uri = f"http://127.0.0.1:{port}"
    state = secrets.token_urlsafe(16)
    verifier, challenge = pkce_pair()
    open_browser(_authorization_url(client_id, redirect_uri, state, scope, challenge))

    result = wait()
    if "error" in result:
        raise ConnectorError(f"Google reported: {result['error']}")
    if result.get("state") != state:
        raise ConnectorError("that redirect wasn't for this request -- try connecting again")
    if "code" not in result:
        raise ConnectorError("Google's redirect had no authorization code")

    tokens = _exchange({
        "client_id": client_id, "client_secret": client_secret, "code": result["code"],
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise ConnectorError(
            "Google did not return a refresh token -- if you've connected before, remove Diya's access "
            "at https://myaccount.google.com/permissions and try again"
        )
    diya_connectors.store_token(config, token_name, refresh_token)
    diya_connectors.store_granted(config, token_name, tokens.get("scope"))  # what Google says it granted, shown on the permissions page


def _access_token(config):
    return access_token(config, "google_calendar")


def access_token(config, token_name):
    """A fresh access token for the refresh token stored under `token_name`, or None if there is no connection or Google
    refuses the refresh (the same "not connected" answer either way -- the tool has nothing useful to
    say about *why* a refresh failed that the owner can act on mid-conversation)."""
    refresh_token = diya_connectors.read_token(config, token_name)
    if refresh_token is None:
        return None
    try:
        client_id, client_secret = _client_credentials(config)
        tokens = _exchange({
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        })
    except ConnectorError:
        return None
    return tokens.get("access_token")


def list_events(config):
    def tool():
        token = _access_token(config)
        if token is None:
            return "Google Calendar is not connected."
        now = datetime.now(timezone.utc).isoformat()
        try:
            response = httpx.get(
                EVENTS_URL, headers={"Authorization": f"Bearer {token}"},
                params={"timeMin": now, "maxResults": 5, "singleEvents": "true", "orderBy": "startTime"},
                timeout=NETWORK_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return f"Couldn't reach Google Calendar: {exc}"
        if response.status_code != 200:
            return f"Google Calendar answered with HTTP {response.status_code}."
        events = response.json().get("items", [])
        if not events:
            return "No upcoming events."
        lines = []
        for event in events:
            start = event.get("start", {})
            when = start.get("dateTime") or start.get("date", "")
            lines.append(f"{event.get('summary', '(no title)')} ({when})")
        return "\n".join(lines)

    return tool
