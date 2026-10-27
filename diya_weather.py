"""The weather, for Home's weather panel and for the colour of the sky behind every page (docs/HOME_DESIGN.md, 2026-10-27; Hark's background follows the weather, and the owner asked for the same).

Where: the person shares their location from the browser (the button on Home, as Hark's "Share your location"). The point is rounded to two decimals (about a kilometre), kept in this computer's own database
(`app_state`), and sent to nobody but the weather service the weather tool already uses (Open-Meteo, on the same short list of allowed hosts). It can be forgotten from the panel. Nothing is guessed from the
internet address, so with no shared location there is no weather and the sky is the usual one.

What: the temperature, how it feels, the sort of sky (`clear`, `cloudy`, `fog`, `rain`, `snow`, `storm`), whether it is day, and when the sun sets, all read in code from the service's own numbers. The model
writes none of it. The answer is kept for ten minutes, a failure for one, so the page looking often asks the service rarely.
"""
from __future__ import annotations

import json
import math
import time

import httpx

import diya
import diya_config

KEY = "weather_location"
FORECAST = "https://api.open-meteo.com/v1/forecast"
CACHE_SECONDS = 600
FAILURE_SECONDS = 60
_SKIES = (
    (frozenset({95, 96, 99}), "storm"),
    (frozenset({71, 73, 75, 77, 85, 86}), "snow"),
    (frozenset({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}), "rain"),
    (frozenset({45, 48}), "fog"),
    (frozenset({2, 3}), "cloudy"),
)


def sky_of(code):
    """The sort of sky for a WMO weather code: clear unless the code says otherwise."""
    for codes, sky in _SKIES:
        if code in codes:
            return sky
    return "clear"


def point(lat, lon):
    """(lat, lon) rounded to two decimals, or None when they are not a place on Earth."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 2), round(lon, 2)


class Weather:
    """The shared place and the weather there. `fetch(url, params, timeout, allowed_hosts)` and `clock` are the world, passed in for tests."""

    def __init__(self, store, allowed_hosts=diya_config.DEFAULT_TOOL_ALLOWED_HOSTS, fetch=None, clock=time.monotonic):
        self.store, self._hosts, self._fetch, self._clock, self._cache = store, allowed_hosts, fetch or diya._fetch, clock, None

    # ---- the place ----
    def location(self):
        conn = self.store.connect()
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (KEY,)).fetchone()
        finally:
            conn.close()
        try:
            return point(*json.loads(row[0])) if row else None
        except (TypeError, ValueError):
            return None

    def set_location(self, lat, lon):
        """Keep the place. False, with nothing kept, when it is not a place on Earth."""
        found = point(lat, lon)
        if found is None:
            return False
        conn = self.store.connect()
        try:
            conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (KEY, json.dumps(list(found))))
            conn.commit()
        finally:
            conn.close()
        self._cache = None
        return True

    def forget(self):
        conn = self.store.connect()
        try:
            conn.execute("DELETE FROM app_state WHERE key = ?", (KEY,))
            conn.commit()
        finally:
            conn.close()
        self._cache = None

    # ---- the weather ----
    def payload(self):
        """What the page is given: {"known": False} with no shared place; with one, {"known": True, temp, feels, label, sky, day, sunset} or {"known": True, "problem": words}."""
        place = self.location()
        if place is None:
            return {"known": False}
        now = self._clock()
        held = self._cache
        if held and held["place"] == place and now - held["at"] < held["ttl"]:
            return held["data"]
        data = self._read(place)
        self._cache = {"place": place, "at": now, "ttl": FAILURE_SECONDS if "problem" in data else CACHE_SECONDS, "data": data}
        return data

    def _read(self, place):
        try:
            body = self._fetch(
                FORECAST,
                {"latitude": place[0], "longitude": place[1], "current": "temperature_2m,apparent_temperature,weather_code,is_day", "daily": "sunset", "timezone": "auto", "forecast_days": 1},
                diya.NETWORK_TIMEOUT, self._hosts,
            ).json()
            current = body["current"]
            code = int(current["weather_code"])
            sunset = (body.get("daily") or {}).get("sunset") or []
            label = str(diya.WEATHER_CODES.get(code, "Weather"))
            return {
                "known": True, "temp": round(float(current["temperature_2m"])), "feels": round(float(current["apparent_temperature"])), "label": label[:1].upper() + label[1:],
                "sky": sky_of(code), "day": bool(current.get("is_day", 1)), "sunset": str(sunset[0])[-5:] if sunset else None,
            }
        except diya.HostNotAllowed:
            return {"known": True, "problem": "The weather service is not on the list of places Diya may reach."}
        except httpx.HTTPError:
            return {"known": True, "problem": "Couldn't reach the weather service."}
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            return {"known": True, "problem": "The weather service sent something I could not read."}
