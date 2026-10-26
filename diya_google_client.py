"""One careful way to talk to Google, for every card beyond the first five (DIYA-067, DIYA-069, DIYA-054; docs/GOOGLE_CLIENT.md), added 2026-10-26.

The first five cards each grew their own small request code. Everything built after them goes through here, so that what is true of one is true of all:

* **Typed outcomes.** A read returns what Google said as a dict, or raises GoogleError with a `kind` (not_connected, signed_out, scope, api_disabled, not_found, conflict, rate_limited, server, network, limit,
  bad_request) and words that are safe to show: the caller never has to read an HTTP status. A write raises ActionFailed (nothing was done) or ActionUncertain (it may have been) like every other action.
* **Bounded.** Every request has a timeout. A page of results is asked for with a size, and a list follows `nextPageToken` for at most a few pages and says that it stopped. A read that is refused for being busy
  (429) or fails on Google's side (500 to 504) is tried again at most twice, waiting what Google asked (never more than a few seconds); a write is NEVER tried again by itself: whether it reached Google is not known,
  and asking twice could do it twice.
* **Counted.** Every request to Google is counted for the day; past the daily limit (DIYA_GOOGLE_DAILY_REQUESTS, 5000, 0 for no limit) nothing more is sent until tomorrow, and the answer says so. A runaway loop
  cannot spend the whole quota of the owner's Google project.
* **Allowlisted.** A request is made only to an address and with a method that the card it is made for has been given (`allow`): a host, a path and a verb, never an address the model chose. A request that is not on
  the card's list is refused before a token is fetched.

Importing this module has no side effects.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

import diya_connectors
import diya_google_calendar
from diya_actions import ActionFailed, ActionUncertain

NETWORK_TIMEOUT = 15.0
MAX_READ_ATTEMPTS = 3  # the first try and two more, for a read only
MAX_WAIT_SECONDS = 8.0  # the longest a retry waits, whatever Google asks
DEFAULT_PAGES = 5  # how many pages a list follows
GOOGLE_HOSTS = ("www.googleapis.com", "gmail.googleapis.com", "tasks.googleapis.com", "docs.googleapis.com", "sheets.googleapis.com", "slides.googleapis.com", "people.googleapis.com", "forms.googleapis.com")
KINDS = ("not_connected", "signed_out", "scope", "api_disabled", "not_found", "conflict", "rate_limited", "server", "network", "limit", "bad_request")

_sleep = time.sleep  # a test replaces it so that a retry does not wait


class GoogleError(Exception):
    """A read that did not work, as a kind and words that are safe to show (`str(error)`). `retry_after` is the seconds Google asked to wait, if it said."""

    def __init__(self, kind, words, status=None, retry_after=None):
        super().__init__(words)
        assert kind in KINDS, kind
        self.kind, self.status, self.retry_after = kind, status, retry_after


# ---- what each card may ask for -----------------------------------------------------------------------------------------------------------------

_ALLOWED = []  # (connector, METHOD, compiled pattern for the whole address)


def allow(connector, method, pattern):
    """Let the card `connector` make `method` requests to addresses that match `pattern` (a regular expression for the WHOLE address, query string excluded)."""
    _ALLOWED.append((connector, method.upper(), re.compile(pattern)))


def permitted(connector, method, url):
    """Is this exact request one the card has been given? It must also be https and to one of Google's own hosts, whatever the list says."""
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != "https" or parts.hostname not in GOOGLE_HOSTS or parts.username or parts.password or parts.query or parts.fragment:
        return False
    return any(c == connector and m == method.upper() and pattern.fullmatch(url) for c, m, pattern in _ALLOWED)


# ---- the daily count ------------------------------------------------------------------------------------------------------------------------------

def _count(config):
    """Count one request for today and say whether it may go: False once the day's limit is reached. A database that cannot be written does not stop a read (the limit is a safety net, not a gate)."""
    limit = getattr(config, "google_daily_requests", 5000)
    if not limit:
        return True
    try:
        import diya_db

        conn = diya_db.Store(config.db_path).connect()
        try:
            key = "google_requests:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")
            conn.execute("INSERT INTO app_state (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1", (key,))
            used = int(conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()[0])
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return True
    return used <= limit


def requests_today(config):
    """How many requests Diya has made to Google today (for the Status page and the tests)."""
    try:
        import diya_db

        conn = diya_db.Store(config.db_path).connect()
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", ("google_requests:" + datetime.now(timezone.utc).strftime("%Y-%m-%d"),)).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


# ---- what Google said ----------------------------------------------------------------------------------------------------------------------------

def _reason(response):
    """Google's own short reason for a refusal ('reason' and its one line), as words to add to a message; '' when there is none."""
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            text = str(error.get("message") or "")[:160]
            return f" ({text})" if text else ""
    except (ValueError, AttributeError):
        pass
    return ""


def _reasons(response):
    """The machine reasons Google gives for a refusal (accessNotConfigured, insufficientPermissions, ...), as a lowercase text to look in."""
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        found = []
        if isinstance(error, dict):
            found.append(str(error.get("status") or ""))
            found += [str(item.get("reason") or "") for item in (error.get("errors") or []) if isinstance(item, dict)]
            found += [str(item.get("reason") or "") for item in (error.get("details") or []) if isinstance(item, dict)]
            found.append(str(error.get("message") or ""))
        return " ".join(found).lower()
    except (ValueError, AttributeError):
        return ""


def _retry_after(response):
    try:
        wait = float(str((getattr(response, "headers", None) or {}).get("Retry-After", "")).strip())
        return wait if wait > 0 else None
    except (ValueError, TypeError):
        return None


def error_for(response, what):
    """The GoogleError for a refusing answer."""
    status = response.status_code
    reason = _reason(response)
    lowered = _reasons(response)
    if status == 401:
        return GoogleError("signed_out", f"Google did not accept the sign-in for {what}. Connect it again on the Connections page.", status)
    if status == 403 and ("accessnotconfigured" in lowered or "has not been used" in lowered or "is disabled" in lowered or "service_disabled" in lowered):
        return GoogleError("api_disabled", f"The Google API for {what} is not switched on in your Google project{reason}. Switch it on in the Google Cloud console, then try again.", status)
    if status == 403 and ("insufficient" in lowered or "scope" in lowered):
        return GoogleError("scope", f"Google says the sign-in for {what} does not allow that{reason}. Add the permission under Data access in your Google project, then connect the card again.", status)
    if status == 403 and ("ratelimit" in lowered or "quota" in lowered or "userratelimit" in lowered):
        return GoogleError("rate_limited", f"Google is limiting requests for {what} right now{reason}.", status, _retry_after(response))
    if status in (403,):
        return GoogleError("scope", f"Google refused{reason} for {what}. Check that the API is switched on and that you allowed Diya to do this, then connect it again.", status)
    if status == 404:
        return GoogleError("not_found", f"Google could not find that in {what}{reason}.", status)
    if status in (409, 412):
        return GoogleError("conflict", f"{what} changed in the meantime{reason}, so nothing was done with the old version.", status)
    if status == 429:
        wait = _retry_after(response)
        return GoogleError("rate_limited", f"Google is limiting requests for {what} right now." + (f" Try again in about {int(wait)} seconds." if wait else " Try again in a minute."), status, wait)
    if 500 <= status <= 599:
        return GoogleError("server", f"Google had an error ({status}) with {what}.", status)
    return GoogleError("bad_request", f"Google answered {what} with HTTP {status}{reason}.", status)


# ---- reads ---------------------------------------------------------------------------------------------------------------------------------------------

def _fetch(config, connector, what, url, params=None):
    """A GET to Google for the card `connector`; the answering response (status 200). Raises GoogleError. Tried again at most twice if Google was busy or failed on its side."""
    if not permitted(connector, "GET", url):
        raise GoogleError("bad_request", f"{what} is not allowed to ask for that, so nothing was asked.")
    if diya_connectors.read_token(config, connector) is None:
        raise GoogleError("not_connected", f"{what} is not connected. Connect it on the Connections page.")
    token = diya_google_calendar.access_token(config, connector)
    if token is None:
        if diya_connectors.signed_out(config, connector):
            raise GoogleError("signed_out", diya_google_calendar.not_connected_words(config, connector, what))
        raise GoogleError("signed_out", f"Google did not accept the sign-in for {what}. Connect it again on the Connections page.")
    last = None
    for attempt in range(1, MAX_READ_ATTEMPTS + 1):
        if not _count(config):
            raise GoogleError("limit", f"Diya has made as many requests to Google today as it is set to (DIYA_GOOGLE_DAILY_REQUESTS), so {what} waits until tomorrow.")
        try:
            response = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=NETWORK_TIMEOUT)
        except httpx.HTTPError as exc:
            last = GoogleError("network", f"Couldn't reach Google for {what} ({type(exc).__name__}).")
        else:
            if response.status_code == 200:
                return response
            last = error_for(response, what)
            if last.kind not in ("rate_limited", "server"):
                raise last
        if attempt < MAX_READ_ATTEMPTS and last.kind in ("rate_limited", "server", "network"):
            _sleep(min(last.retry_after or 2 ** (attempt - 1), MAX_WAIT_SECONDS))
            continue
        break
    raise last


def read(config, connector, what, url, params=None):
    """A GET to Google for the card `connector`; what Google said as a dict. Raises GoogleError. Tried again at most twice if Google was busy or failed on its side."""
    response = _fetch(config, connector, what, url, params)
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def read_text(config, connector, what, url, params=None, max_chars=20000):
    """A GET whose answer is text (an export of a Google file, the content of a text file), cut to `max_chars`. Raises GoogleError."""
    text = getattr(_fetch(config, connector, what, url, params), "text", "")
    return text[:max_chars] if isinstance(text, str) else ""


def pages(config, connector, what, url, params, key, *, max_pages=DEFAULT_PAGES):
    """The items under `key` across the pages of a list, following nextPageToken at most `max_pages` times: (items, more) where `more` is True if Google had still more when it stopped."""
    items, token, more = [], None, False
    for page in range(max_pages):
        data = read(config, connector, what, url, dict(params or {}, **({"pageToken": token} if token else {})))
        items += [item for item in (data.get(key) or []) if isinstance(item, dict)]
        token = data.get("nextPageToken")
        if not token:
            return items, False
        more = True
    return items, more


# ---- writes --------------------------------------------------------------------------------------------------------------------------------------------

_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)


def send(config, connector, what, method, url, *, params=None, body=None, headers=None, ok=(200,), accept=(), doing="that"):
    """One request that changes something at Google, for an approved action. Returns the response when its status is in `ok` or `accept`. ActionFailed, with nothing done, for a refusal Google gave and
    for a sign-in that is gone; ActionUncertain for a request that may have reached Google with no answer, or a failure on its side part way. NEVER tried again: the one place in Diya that sends a change
    to the newer Google cards (the catalog test names it), called only from the kinds' execute functions (tests/test_google_client.py)."""
    if not permitted(connector, method, url):
        raise ActionFailed(f"{what} is not allowed to make that request, so nothing was done.")
    if diya_connectors.read_token(config, connector) is None:
        raise ActionFailed(f"{what} is not connected, so nothing was done.")
    token = diya_google_calendar.access_token(config, connector)
    if token is None:
        raise ActionFailed(f"Google did not accept the sign-in for {what}, so nothing was done. Connect it again on the Connections page.")
    if not _count(config):
        raise ActionFailed(f"Diya has made as many requests to Google today as it is set to, so nothing was done. It can be proposed again tomorrow.")
    try:
        response = httpx.request(method, url, params=params, json=body, headers={"Authorization": f"Bearer {token}", **(headers or {})}, timeout=NETWORK_TIMEOUT)
    except httpx.HTTPError as exc:
        if isinstance(exc, _NEVER_SENT):
            raise ActionFailed(f"Couldn't reach Google ({type(exc).__name__}), so nothing was done.")
        raise ActionUncertain(f"The request was sent to Google but no answer came back ({type(exc).__name__}), so {doing} may or may not have been done. Look in Google, then record what you found.")
    status = response.status_code
    if status in ok or status in accept:
        return response
    error = error_for(response, what)
    if error.kind in ("server",):
        raise ActionUncertain(f"Google answered with an error (HTTP {status}) part way through, so {doing} may or may not have been done. Look in Google, then record what you found.")
    if error.kind == "conflict":
        raise ActionFailed(f"{error} Look at the new version in Google and ask again if you still want it.")
    raise ActionFailed(f"{error} Nothing was done.")


def as_json(response):
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
