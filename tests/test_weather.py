"""The weather for Home's panel and the colour of the sky (diya_weather.py, diya_weather_api.py, components/WeatherProvider.jsx; docs/HOME_DESIGN.md), added 2026-10-27.

What this proves: with no shared place there is no weather and nothing is asked of anyone; a shared place is rounded, kept in the local database and is the only thing sent, to the one weather host; the answer is
kept ten minutes and a failure one; a place that is not on Earth is refused; the place can be forgotten; and every colour that tints the sky stays on the safe side of the page's background, so the contrast the
theme tokens prove holds on every pixel.
"""
import dataclasses
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_weather
import diya_web
from diya_db import Store
from fakes import FakeClient, text_reply

ROOT = Path(__file__).resolve().parent.parent
LOCAL = "https://localhost"


class Reply:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def forecast(code=2, temp=25.4, feels=24.6, day=1, sunset="2026-10-27T17:55"):
    return {"current": {"temperature_2m": temp, "apparent_temperature": feels, "weather_code": code, "is_day": day}, "daily": {"sunset": [sunset]}}


class Service:
    """A scripted weather service that keeps every request."""

    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data if data is not None else forecast(), error, []

    def __call__(self, url, params, timeout, hosts):
        self.calls.append((url, dict(params), hosts))
        if self.error:
            raise self.error
        return Reply(self.data)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "w.db"))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_without_a_shared_place_there_is_no_weather_and_nothing_is_asked(store):
    service = Service()
    assert diya_weather.Weather(store, fetch=service).payload() == {"known": False} and service.calls == []


def test_a_shared_place_is_rounded_kept_and_the_only_thing_sent(store):
    service = Service()
    weather = diya_weather.Weather(store, fetch=service)
    assert weather.set_location(18.520431, 73.856744) is True and weather.location() == (18.52, 73.86)
    assert diya_weather.Weather(store, fetch=service).location() == (18.52, 73.86)  # kept in the database, not in memory
    data = weather.payload()
    assert data == {"known": True, "temp": 25, "feels": 25, "label": "Partly cloudy", "sky": "cloudy", "day": True, "sunset": "17:55"}
    (url, params, hosts), = service.calls
    assert url == "https://api.open-meteo.com/v1/forecast" and (params["latitude"], params["longitude"]) == (18.52, 73.86) and "api.open-meteo.com" in hosts
    assert set(params) == {"latitude", "longitude", "current", "daily", "timezone", "forecast_days"}  # nothing of the person but the rounded place


@pytest.mark.parametrize("lat, lon", [(91, 0), (0, 181), (-90.1, 0), ("north", 5), (None, None), (float("nan"), 0), (float("inf"), 0)])
def test_a_place_that_is_not_on_earth_is_refused(store, lat, lon):
    weather = diya_weather.Weather(store, fetch=Service())
    assert weather.set_location(lat, lon) is False and weather.location() is None and weather.payload() == {"known": False}


def test_the_answer_is_kept_ten_minutes_and_a_failure_one(store):
    clock, service = Clock(), Service()
    weather = diya_weather.Weather(store, fetch=service, clock=clock)
    weather.set_location(18.5, 73.8)
    weather.payload()
    clock.now += diya_weather.CACHE_SECONDS - 1
    weather.payload()
    assert len(service.calls) == 1
    clock.now += 2
    weather.payload()
    assert len(service.calls) == 2

    failing = Service(error=httpx.ConnectError("no internet"))
    weather = diya_weather.Weather(store, fetch=failing, clock=clock)
    assert weather.payload() == {"known": True, "problem": "Couldn't reach the weather service."}
    weather.payload()
    assert len(failing.calls) == 1
    clock.now += diya_weather.FAILURE_SECONDS + 1
    weather.payload()
    assert len(failing.calls) == 2


def test_sharing_a_new_place_or_forgetting_it_drops_what_was_kept(store):
    service = Service()
    weather = diya_weather.Weather(store, fetch=service)
    weather.set_location(18.5, 73.8)
    weather.payload()
    weather.set_location(12.97, 77.59)
    weather.payload()
    assert len(service.calls) == 2 and service.calls[1][1]["latitude"] == 12.97
    weather.forget()
    assert weather.payload() == {"known": False} and weather.location() is None and len(service.calls) == 2


@pytest.mark.parametrize("data", [{}, {"current": {}}, {"current": {"temperature_2m": "warm", "apparent_temperature": 1, "weather_code": 1}}, []])
def test_a_reply_that_cannot_be_read_is_said_not_raised(store, data):
    weather = diya_weather.Weather(store, fetch=Service(data=data))
    weather.set_location(18.5, 73.8)
    assert weather.payload() == {"known": True, "problem": "The weather service sent something I could not read."}


def test_a_host_that_is_not_allowed_is_said(store):
    weather = diya_weather.Weather(store, fetch=Service(error=diya.HostNotAllowed("nope")))
    weather.set_location(18.5, 73.8)
    assert "not on the list" in weather.payload()["problem"]


@pytest.mark.parametrize("code, sky", [(0, "clear"), (1, "clear"), (2, "cloudy"), (3, "cloudy"), (45, "fog"), (53, "rain"), (65, "rain"), (81, "rain"), (73, "snow"), (86, "snow"), (95, "storm"), (99, "storm"), (999, "clear")])
def test_the_sort_of_sky_comes_from_the_weather_code(code, sky):
    assert diya_weather.sky_of(code) == sky


def test_night_and_a_missing_sunset_are_read(store):
    weather = diya_weather.Weather(store, fetch=Service(data={"current": {"temperature_2m": 18, "apparent_temperature": 17, "weather_code": 0, "is_day": 0}}))
    weather.set_location(18.5, 73.8)
    assert weather.payload()["day"] is False and weather.payload()["sunset"] is None and weather.payload()["sky"] == "clear"


# ---- the route ---------------------------------------------------------------------------------------------------------------------------------


def app_for(tmp_path, monkeypatch, service):
    monkeypatch.setattr(diya, "_fetch", service)
    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(
        diya_config.load_config(), db_path=str(data / "w.db"), profile_path=str(data / "profile.txt"), dream_state_path=str(data / "state.json"), dream_log_path=str(data / "dream.log"),
        dream_pending_path=str(data / "pending.jsonl"), connector_tokens_dir=str(data / "tokens"), connectors_log_path=str(data / "c.log"), require_token=False,
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 2))
    return TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL)


def test_the_route_shares_reads_and_forgets_a_place(tmp_path, monkeypatch):
    service = Service()
    client = app_for(tmp_path, monkeypatch, service)
    assert client.get("/api/weather").json() == {"known": False} and service.calls == []
    shared = client.post("/api/weather", json={"lat": 18.5204, "lon": 73.8567}).json()
    assert shared["known"] and shared["sky"] == "cloudy" and shared["temp"] == 25
    assert client.get("/api/weather").json() == shared and len(service.calls) == 1  # the second look used the first answer
    assert client.delete("/api/weather").json() == {"known": False} and client.get("/api/weather").json() == {"known": False}


def test_the_route_refuses_a_place_that_is_not_on_earth(tmp_path, monkeypatch):
    client = app_for(tmp_path, monkeypatch, Service())
    assert client.post("/api/weather", json={"lat": 120, "lon": 0}).status_code == 422
    assert client.post("/api/weather", json={"lat": "x"}).status_code == 422
    assert client.get("/api/weather").json() == {"known": False}


# ---- the sky -----------------------------------------------------------------------------------------------------------------------------------


def luminance(r, g, b):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def colours(rule):
    return [tuple(int(n) for n in m) for m in re.findall(r"rgba\((\d+), (\d+), (\d+), [\d.]+\)", rule)]


def test_every_colour_that_tints_the_sky_stays_on_the_safe_side_of_the_background():
    css = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    dark_bg, light_bg = luminance(0x43, 0x4B, 0x78), luminance(0xD9, 0xE0, 0xF0)
    light = re.findall(r'^:root\[data-sky="(\w+)"\] \{ --sky-weather: (.*) \}$', css, re.M)
    dark = re.findall(r'^:root\[data-theme="dark"\]\[data-sky="(\w+)"\] \{ --sky-weather: (.*) \}$', css, re.M)
    system = re.findall(r'^  :root:not\(\[data-theme="light"\]\)\[data-sky="(\w+)"\] \{ --sky-weather: (.*) \}$', css, re.M)
    assert [n for n, _ in light] == [n for n, _ in dark] == [n for n, _ in system] == ["clear", "cloudy", "fog", "rain", "storm", "snow"]
    assert dark == system  # the dark tint is the same whether the system or the menu chose it
    for name, rule in light:
        assert all(luminance(*c) >= light_bg for c in colours(rule)), name  # never darker than the lightest-contrast sky of the light theme
    for name, rule in dark:
        assert all(luminance(*c) <= dark_bg for c in colours(rule)), name  # never lighter than the lightest dusk
    night = re.findall(r"--sky-night: (.*?);", css)
    assert len(night) == 2 and all(luminance(*c) <= dark_bg for rule in night for c in colours(rule))  # the night veil is dark-theme only, and dark
    assert not re.search(r':root\[data-sky="\w+"\]\[data-daytime[^{]*\{[^}]*--sky-night', css)  # none in the light theme, where a veil would be darker than the background allows


def test_the_page_follows_the_weather_only_for_a_sky_it_knows_and_never_before_signing_in():
    provider = (ROOT / "frontend" / "components" / "WeatherProvider.jsx").read_text(encoding="utf-8")
    shell = (ROOT / "frontend" / "components" / "AppShell.jsx").read_text(encoding="utf-8")
    assert "const SKIES = ['clear', 'cloudy', 'fog', 'rain', 'snow', 'storm']" in provider and "SKIES.includes(weather.sky)" in provider
    assert "delete root.dataset.sky" in provider  # no weather, no tint
    wrapper = shell[shell.index("export default function AppShell"):shell.index("function Shell(")]
    assert wrapper.index("if (pathname === '/login') return <>{children}</>") < wrapper.index("<WeatherProvider>")  # the sign-in page asks nothing of the API
