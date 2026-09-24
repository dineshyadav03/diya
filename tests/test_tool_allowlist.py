"""diya._fetch, get_weather and DIYA_TOOL_ALLOWED_HOSTS (diya.py, diya_config.py): Stage 1 design,
Unit 2 (docs/STAGE1_DESIGN.md, section 4 and the "Rollout plan" -> "Outbound destination
allowlist"). A destination the agent's own network tool may not reach is refused before any request
is sent; web_search is the one tool this cannot cover, and a test says so out loud.
"""
import importlib.metadata
import inspect
import ipaddress
import re
import types
import urllib.parse

import httpx
import pytest

import diya
import diya_config
from diya_config import ConfigError, load_config
from fakes import FakeClient

GEOCODING = "geocoding-api.open-meteo.com"
FORECAST = "api.open-meteo.com"

CHENNAI = {"name": "Chennai", "admin1": "Tamil Nadu", "country": "India",
           "latitude": 13.1, "longitude": 80.3, "population": 7000000}


@pytest.fixture
def sent(monkeypatch):
    """Replace the real HTTP call. `sent` lists every request that would have gone out."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return types.SimpleNamespace(json=lambda: {"ok": True})

    monkeypatch.setattr(diya.httpx, "get", fake_get)
    return calls


def fake_open_meteo(monkeypatch):
    """Answer both Open-Meteo calls; returns the list of URLs that were requested."""
    requested = []

    def fake_get(url, params=None, timeout=None):
        requested.append(url)
        if "geocoding" in url:
            return types.SimpleNamespace(json=lambda: {"results": [CHENNAI]})
        return types.SimpleNamespace(
            json=lambda: {"current": {"temperature_2m": 30.0, "weather_code": 1, "wind_speed_10m": 5.0}}
        )

    monkeypatch.setattr(diya.httpx, "get", fake_get)
    return requested


# --- 1. get_weather against its real two hosts is unchanged ------------------------------------

def test_get_weather_still_reaches_exactly_the_two_open_meteo_hosts(monkeypatch):
    requested = fake_open_meteo(monkeypatch)
    out = diya.get_weather("Chennai")
    assert [urllib.parse.urlsplit(u).hostname for u in requested] == [GEOCODING, FORECAST]
    assert out.startswith("Chennai, Tamil Nadu, India: 30.0")


def test_the_agents_get_weather_still_works_with_no_configuration(monkeypatch, tmp_path):
    requested = fake_open_meteo(monkeypatch)
    agent = diya.Agent(diya_config.Config(db_path=str(tmp_path / "a.db")), client=FakeClient())
    assert agent._functions["get_weather"]("Chennai").startswith("Chennai, Tamil Nadu, India")
    assert len(requested) == 2


# --- 2. _fetch refuses a host that is not on the list, before any request is sent --------------

def test_an_allowed_host_is_fetched_once_with_the_same_arguments(sent):
    response = diya._fetch("https://api.open-meteo.com/v1/forecast", {"a": 1}, 5.0)
    assert sent == [("https://api.open-meteo.com/v1/forecast", {"a": 1}, 5.0)]
    assert response.json() == {"ok": True}


def test_a_host_that_is_not_on_the_list_is_refused_before_any_request_is_sent(sent):
    with pytest.raises(diya.HostNotAllowed):
        diya._fetch("https://evil.example/v1/search", {"name": "x"}, 5.0)
    assert sent == []  # the underlying call was never made -- not made and then discarded


# Everything below is a URL that must never be fetched by default. Loopback and private addresses
# are refused the same way as any host that is not on the list -- the list is external services
# only, so a tool call can't be turned on this machine's own API or another device on the LAN.
REFUSED_URLS = [
    # the machine itself, and private / link-local ranges
    "https://127.0.0.1:8080/api/threads",
    "https://localhost:8080/api/chat",
    "https://[::1]:8080/api/history/1",
    "https://0.0.0.0:8080/",
    "https://10.0.0.1/",
    "https://172.16.0.1/",
    "https://192.168.1.1/",
    "https://169.254.169.254/latest/meta-data/",
    "https://2130706433/",  # 127.0.0.1 written as one decimal number
    "https://0x7f.1/",
    # look-alikes of an allowed host
    "https://api.open-meteo.com@evil.example/v1/forecast",
    "https://api.open-meteo.com.evil.example/v1/forecast",
    "https://evil.example/api.open-meteo.com",
    "https://api.open-meteo.com\\@evil.example/v1/forecast",
    "https://evil.example#@api.open-meteo.com/",
    "https://api.open-meteo.com%2f@evil.example/",
    "https://evil.example?@api.open-meteo.com/",
    "https://api.open-meteo.com./v1/forecast",  # a trailing dot is a different name to the check
    # addresses that can't be read as a host at all
    "https:evil.example/v1",
    "/v1/forecast",
    "not a url",
    "",
    "https://[::1/",
    # addresses two parsers would read differently
    " https://api.open-meteo.com/v1/forecast",
    "https://api.open-meteo.com\t/v1/forecast",
    "https://api.open-meteo.com\n/v1/forecast",
]


@pytest.mark.parametrize("url", REFUSED_URLS)
def test_these_destinations_are_refused_and_nothing_is_sent(sent, url):
    with pytest.raises(diya.HostNotAllowed):
        diya._fetch(url, {}, 5.0)
    assert sent == []


def test_the_host_is_compared_case_insensitively(sent):
    diya._fetch("https://API.Open-Meteo.com/v1/forecast", {}, 5.0)
    assert len(sent) == 1


def test_a_fragment_is_not_a_host_the_allowed_host_stays_the_allowed_host(sent):
    # Both parsers agree the host here is api.open-meteo.com: everything after "#" is a fragment,
    # which is never sent. (The dangerous shape is the reverse, evil.example#@api.open-meteo.com,
    # which is in REFUSED_URLS above.)
    url = "https://api.open-meteo.com#@evil.example/"
    assert diya._request_host(url) == FORECAST
    diya._fetch(url, {}, 5.0)
    assert len(sent) == 1


def test_a_url_the_two_parsers_read_differently_is_refused_even_though_one_would_allow_it():
    url = "https://api.open-meteo.com\t/v1/forecast"
    assert urllib.parse.urlsplit(url).hostname == FORECAST  # urllib alone would have allowed it...
    with pytest.raises(httpx.InvalidURL):
        httpx.URL(url)  # ...but httpx, which makes the connection, will not read it at all
    assert diya._request_host(url) is None


def test_the_allowlist_argument_is_honoured_and_replaces_the_default(sent):
    diya._fetch("https://weather.example/x", {}, 5.0, ("weather.example",))
    assert len(sent) == 1
    with pytest.raises(diya.HostNotAllowed):
        diya._fetch("https://api.open-meteo.com/v1/forecast", {}, 5.0, ("weather.example",))
    assert len(sent) == 1


def test_an_empty_allowlist_refuses_everything(sent):
    with pytest.raises(diya.HostNotAllowed):
        diya._fetch("https://api.open-meteo.com/v1/forecast", {}, 5.0, ())
    assert sent == []


def test_the_refusal_names_the_host_but_not_the_allowlist(sent):
    with pytest.raises(diya.HostNotAllowed) as excinfo:
        diya._fetch("https://evil.example/x", {}, 5.0)
    assert "evil.example" in str(excinfo.value)
    assert "open-meteo" not in str(excinfo.value)


def test_redirects_are_not_followed_so_an_allowed_host_cannot_pass_the_request_on():
    """The allowlist only means something if httpx does not chase a redirect to a host that was
    never checked. httpx.get's default is not to (tests fake httpx.get, so this reads the real
    signature); if a pinned upgrade ever changes that default, this fails and _fetch needs
    follow_redirects=False spelled out."""
    assert inspect.signature(httpx.get).parameters["follow_redirects"].default is False


# --- get_weather turns a refusal into a plain answer, and Agent wires in the configured list ----

def test_get_weather_reports_a_refusal_as_blocked_not_as_a_lost_connection(sent):
    out = diya.get_weather("Paris", allowed_hosts=("weather.example",))
    assert out.startswith("Weather lookup blocked")
    assert "internet" not in out
    assert sent == []


def test_agent_binds_get_weather_to_the_configured_hosts(sent, tmp_path):
    config = diya_config.Config(db_path=str(tmp_path / "a.db"), tool_allowed_hosts=("only.example",))
    agent = diya.Agent(config, client=FakeClient())
    assert agent._functions["get_weather"]("Paris").startswith("Weather lookup blocked")
    assert sent == []


def test_the_env_setting_reaches_the_tool_end_to_end(monkeypatch, sent):
    monkeypatch.setenv("DIYA_TOOL_ALLOWED_HOSTS", "only.example")
    agent = diya.Agent(client=FakeClient())
    assert agent._functions["get_weather"]("Paris").startswith("Weather lookup blocked")
    assert sent == []


# --- 3. web_search is NOT covered, and that is asserted rather than left implicit ---------------

class FakeDDGS:
    def __init__(self, timeout=None):
        pass

    def text(self, query, max_results=3):
        return [{"title": "A title", "body": "A body", "href": "https://result.example"}]


def test_web_search_does_not_go_through_fetch_or_httpx(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("web_search must not reach the allowlisted fetch path today")

    monkeypatch.setattr(diya, "_fetch", refuse)
    monkeypatch.setattr(diya.httpx, "get", refuse)
    monkeypatch.setattr(diya, "DDGS", FakeDDGS)
    assert diya.web_search("anything") == "A title: A body (https://result.example)"


def test_ddgs_makes_its_own_requests_through_primp_not_httpx():
    """Why the test above holds, and the tripwire for it. ddgs's runtime requirements are click,
    lxml and primp (a Rust HTTP client): no httpx, no requests, so this code has nothing to wrap
    or intercept. If a ddgs upgrade changes that, or ddgs is replaced by a direct call through
    _fetch (docs/STAGE1_DESIGN.md section 4, option 1), this fails on purpose: update the
    limitation in ROADMAP.md / PRODUCT_VISION.md / README.md with it."""
    assert diya.DDGS.__module__.split(".")[0] == "ddgs"
    runtime = {
        re.match(r"[A-Za-z0-9_.-]+", requirement).group(0).lower()
        for requirement in importlib.metadata.requires("ddgs")
        if "extra ==" not in requirement
    }
    assert "primp" in runtime
    assert not runtime & {"httpx", "requests"}


# --- configuration: DIYA_TOOL_ALLOWED_HOSTS, parsed exactly like DIYA_ALLOWED_HOSTS -------------

def test_the_default_allowlist_is_exactly_the_two_open_meteo_hosts():
    assert load_config({}).tool_allowed_hosts == (GEOCODING, FORECAST)
    assert diya_config.DEFAULT_TOOL_ALLOWED_HOSTS == (GEOCODING, FORECAST)


def test_the_default_allowlist_holds_no_loopback_or_private_address():
    for host in diya_config.DEFAULT_TOOL_ALLOWED_HOSTS:
        assert not diya_config.is_loopback(host)
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue  # a name, not an address
        assert not (address.is_private or address.is_loopback or address.is_link_local)


def test_configured_hosts_replace_the_default_they_do_not_add_to_it():
    config = load_config({"DIYA_TOOL_ALLOWED_HOSTS": "weather.example"})
    assert config.tool_allowed_hosts == ("weather.example",)


def test_tool_hosts_tolerate_spaces_case_duplicates_and_empty_items():
    config = load_config({"DIYA_TOOL_ALLOWED_HOSTS": " Weather.Example ,, api.example ,weather.example,"})
    assert config.tool_allowed_hosts == ("weather.example", "api.example")


def test_a_blank_setting_counts_as_unset():
    assert load_config({"DIYA_TOOL_ALLOWED_HOSTS": "   "}).tool_allowed_hosts == (GEOCODING, FORECAST)


def test_a_list_with_no_hosts_in_it_blocks_every_destination(sent):
    config = load_config({"DIYA_TOOL_ALLOWED_HOSTS": " , "})
    assert config.tool_allowed_hosts == ()
    assert diya.get_weather("Paris", allowed_hosts=config.tool_allowed_hosts).startswith("Weather lookup blocked")
    assert sent == []


@pytest.mark.parametrize(
    "bad",
    ["*", "*.local", "https://weather.example", "weather.example:8080", "weather.example/", "0.0.0.0", "a@b", "a b", "[::1]"],
)
def test_tool_hosts_reject_wildcards_schemes_ports_and_paths(bad):
    with pytest.raises(ConfigError, match="DIYA_TOOL_ALLOWED_HOSTS"):
        load_config({"DIYA_TOOL_ALLOWED_HOSTS": bad})


def test_the_two_host_settings_are_independent():
    config = load_config({"DIYA_ALLOWED_HOSTS": "phone.local", "DIYA_TOOL_ALLOWED_HOSTS": "weather.example"})
    assert config.allowed_hosts == ("phone.local",)
    assert config.tool_allowed_hosts == ("weather.example",)
    assert load_config({"DIYA_ALLOWED_HOSTS": "phone.local"}).tool_allowed_hosts == (GEOCODING, FORECAST)
