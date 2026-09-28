"""Google Calendar (docs/CONNECTORS_DESIGN.md, unit C3): Diya's first OAuth connector, and a revision
of D6's original "browser redirect ending back on this page" for what a single-machine, one-owner app
actually needs -- since the browser and the server are the same machine, there is no separate page to
navigate back to. Clicking Connect for this connector, per RFC 8252 ("OAuth 2.0 for Native Apps" --
the pattern Google, and every other IdP, recommends for exactly this shape of app), opens the owner's
own browser to Google's own consent screen and BLOCKS until a temporary local server on an OS-assigned
loopback port catches the redirect back, then exchanges the code for a refresh token -- the credential
that gets stored, through the same diya_connectors.store_token every connector uses.

Needs DIYA_GOOGLE_CLIENT_ID and DIYA_GOOGLE_CLIENT_SECRET, from an OAuth client the owner registers
themselves (Google Cloud Console, "Desktop app" type, since only that type gets RFC 8252's loopback
exception -- an arbitrary port, not one fixed at registration time) -- Diya cannot create one. The
client secret is not treated as fully confidential here either way (Google's own guidance: a desktop
app cannot keep one secret, which is exactly why the loopback redirect and a one-time code exist), but
it is still an owner-supplied setting, never committed, like every other DIYA_* value.
"""
from __future__ import annotations

import http.server
import secrets
import urllib.parse
import webbrowser
from datetime import datetime, timezone

import httpx

import diya_connectors
from diya_connectors import ConnectorError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
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
        body = b"<p>Diya is connected. You can close this tab.</p>"
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


def _authorization_url(client_id, redirect_uri, state):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # otherwise a returning owner may not be issued a refresh token at all
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _exchange(data):
    """The one Google token-endpoint shape both the initial code exchange and a later refresh use."""
    try:
        response = httpx.post(TOKEN_URL, data=data, timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"couldn't reach Google: {exc}")
    if response.status_code != 200:
        raise ConnectorError(f"Google answered with HTTP {response.status_code}")
    return response.json()


def _client_credentials(config):
    client_id = (config.google_client_id or "").strip()
    client_secret = (config.google_client_secret or "").strip()
    if not client_id or not client_secret:
        raise ConnectorError(
            "set DIYA_GOOGLE_CLIENT_ID and DIYA_GOOGLE_CLIENT_SECRET first (docs/CONNECTORS_DESIGN.md, unit C3)"
        )
    return client_id, client_secret


def connect(config, open_browser=webbrowser.open):
    """The whole flow, one call: opens the owner's browser, waits for them to finish, stores the
    refresh token (docs/CONNECTORS_DESIGN.md, D6). Raises ConnectorError, and stores nothing, at any
    failed step -- a cancelled or failed attempt never leaves a half-connected state."""
    client_id, client_secret = _client_credentials(config)

    port, wait = _wait_for_redirect(CALLBACK_TIMEOUT)
    redirect_uri = f"http://127.0.0.1:{port}"
    state = secrets.token_urlsafe(16)
    open_browser(_authorization_url(client_id, redirect_uri, state))

    result = wait()
    if "error" in result:
        raise ConnectorError(f"Google reported: {result['error']}")
    if result.get("state") != state:
        raise ConnectorError("that redirect wasn't for this request -- try connecting again")
    if "code" not in result:
        raise ConnectorError("Google's redirect had no authorization code")

    tokens = _exchange({
        "client_id": client_id, "client_secret": client_secret, "code": result["code"],
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    })
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise ConnectorError(
            "Google did not return a refresh token -- if you've connected before, remove Diya's access "
            "at https://myaccount.google.com/permissions and try again"
        )
    diya_connectors.store_token(config, "google_calendar", refresh_token)


def _access_token(config):
    """A fresh access token for the stored refresh token, or None if there is no connection or Google
    refuses the refresh (the same "not connected" answer either way -- the tool has nothing useful to
    say about *why* a refresh failed that the owner can act on mid-conversation)."""
    refresh_token = diya_connectors.read_token(config, "google_calendar")
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
