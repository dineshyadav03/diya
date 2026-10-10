"""The login in front of the UI (docs/UI_LOGIN_DESIGN.md; audit finding F1): frontend/server/ui-login.mjs, run under plain Node.

What this proves: a passcode is compared without regard to how it differs; a session is accepted only if it is ours, unaltered, unexpired
and made with this passcode; the page after signing in can only be a place on this site; the middleware lets everything through when no
passcode is set, and otherwise lets through only a good session (plus the sign-in page and /session), sends a page to the sign-in page,
answers an API call with a 511, and refuses a change that says it came from another site; sign-in is slowed, locked after five wrong
passcodes for a time that doubles to an hour, and a right one resets it; the cookie has the attributes the design says.
Time and the sleep are passed in, so none of it waits.
"""
import json
import pathlib
import re
import shutil
import subprocess
from urllib.parse import quote

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "ui_login_harness.mjs"
MODULE = ROOT / "frontend" / "server" / "ui-login.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

PASS = "correct horse battery"
ENV = {"DIYA_UI_PASSCODE": PASS}
NOW = 1_800_000_000_000
DAY = 24 * 3600 * 1000
HOST = {"host": "diya.test:3000"}
ORIGIN = "https://diya.test:3000"


def run(*steps):
    result = subprocess.run(["node", str(HARNESS)], input=json.dumps(list(steps)), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def one(step):
    return run(step)[0]


def body(response):
    return json.loads(response["body"])


def cookie_of(response):
    return response["headers"]["set-cookie"].split(";")[0].split("=", 1)[1]


# --- the passcode ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("passcode, attempt, expected", [
    (PASS, PASS, True),
    (PASS, PASS + "x", False),
    (PASS, PASS[:-1], False),
    (PASS, PASS.upper(), False),
    (PASS, "  " + PASS + "  ", True),   # a phone keyboard's stray space is not a wrong passcode
    (PASS, "", False),
    ("", "", False),                    # no passcode set: nothing can match
    ("", PASS, False),
    (PASS, None, False),
    (PASS, 123, False),
    ("pässcode wörds ✓✓✓", "pässcode wörds ✓✓✓", True),
    ("pässcode wörds ✓✓✓", "passcode words ✓✓✓", False),
])
def test_a_passcode_matches_only_itself(passcode, attempt, expected):
    assert one({"op": "passcodeMatches", "passcode": passcode, "attempt": attempt}) is expected


def test_the_passcode_comes_from_the_environment_trimmed_or_not_at_all():
    out = run({"op": "guard", "url": "https://diya.test/tasks", "env": {"DIYA_UI_PASSCODE": "   "}},
              {"op": "guard", "url": "https://diya.test/tasks", "env": {}},
              {"op": "guard", "url": "https://diya.test/tasks", "env": {"DIYA_UI_PASSCODE": "  " + PASS + " "}})
    assert out[0] is None and out[1] is None and out[2]["status"] == 307  # blank is "not turned on"; padding is ignored


# --- a session --------------------------------------------------------------------------------------------------------

def test_a_session_made_now_is_valid_until_thirty_days_from_now():
    token = one({"op": "makeSession", "passcode": PASS, "now": NOW})
    assert re.fullmatch(r"v1\.\d+\.[0-9a-f]{64}", token) and token.split(".")[1] == str(NOW + 30 * DAY)
    checks = run(*[{"op": "sessionValid", "passcode": PASS, "token": token, "now": NOW + offset} for offset in (0, DAY, 30 * DAY - 1, 30 * DAY, 30 * DAY + 1)])
    assert checks == [True, True, True, False, False]  # at the expiry itself it is over


def test_a_session_is_refused_if_it_was_altered_or_is_not_ours():
    token = one({"op": "makeSession", "passcode": PASS, "now": NOW})
    version, expiry, mac = token.split(".")
    flipped = mac[:-1] + ("0" if mac[-1] != "0" else "1")
    longer = f"{version}.{int(expiry) + 1}.{mac}"  # a later expiry with the old signature
    other = one({"op": "makeSession", "passcode": PASS + "!", "now": NOW})
    tokens = [flipped, longer, other, mac.upper(), f"v2.{expiry}.{mac}", f"{version}.{expiry}", f"{version}.{expiry}.{mac}.x", "", "garbage", f"{version}..{mac}",
              f"{version}.{expiry}.{mac[:-1]}", f"{version}.-5.{mac}", f"{version}.{expiry}x.{mac}"]
    assert run(*[{"op": "sessionValid", "passcode": PASS, "token": t, "now": NOW} for t in tokens]) == [False] * len(tokens)
    assert one({"op": "sessionValid", "passcode": PASS, "token": token, "now": NOW}) is True  # and the real one still is


@pytest.mark.parametrize("passcode, token", [("", "x"), (PASS, None), (PASS, 5), (PASS, ["v1"]), (None, "x")])
def test_a_session_needs_both_a_passcode_and_a_token(passcode, token):
    assert one({"op": "sessionValid", "passcode": passcode, "token": token, "now": NOW}) is False


def test_changing_the_passcode_ends_every_session():
    token = one({"op": "makeSession", "passcode": PASS, "now": NOW})
    assert one({"op": "sessionValid", "passcode": "another passcode here", "token": token, "now": NOW}) is False


# --- where to go after signing in -------------------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("/", "/"), ("/tasks", "/tasks"), ("/history?id=3", "/history?id=3"), ("/memory#facts", "/memory#facts"),
    (None, "/"), (5, "/"), ("", "/"), ("tasks", "/"), ("https://evil.example/", "/"), ("//evil.example", "/"), ("/\\evil.example", "/"),
    ("/a\\b", "/"), ("javascript:alert(1)", "/"), ("/\nSet-Cookie: x=1", "/"), ("/\x00", "/"), ("/\x7f", "/"),
    ("/login", "/"), ("/login?next=/tasks", "/"), ("/session", "/"), ("/sessions", "/"),
    ("/" + "a" * 1999, "/" + "a" * 1999), ("/" + "a" * 2000, "/"),
])
def test_only_a_place_on_this_site_can_follow_signing_in(value, expected):
    assert one({"op": "safeNext", "value": value}) == expected


@pytest.mark.parametrize("header, name, expected", [
    ("a=1; diya_session=tok; b=2", "diya_session", "tok"),
    ("diya_session=tok", "diya_session", "tok"),
    ("  diya_session = tok ", "diya_session", "tok"),
    ("a=1; b=2", "diya_session", None),
    ("", "diya_session", None),
    (None, "diya_session", None),
    ("xdiya_session=bad; diya_session=good", "diya_session", "good"),
    ("diya_session=a=b", "diya_session", "a=b"),
    ("diya_session", "diya_session", None),
])
def test_reading_one_cookie(header, name, expected):
    assert one({"op": "readCookie", "header": header, "name": name}) == expected


# --- the middleware's decision ----------------------------------------------------------------------------------------

def signed_in_cookie():
    return "diya_session=" + one({"op": "makeSession", "passcode": PASS, "now": NOW})


def guard(url, method="GET", headers=None, env=ENV, now=NOW):
    return one({"op": "guard", "url": url, "method": method, "headers": headers or {}, "env": env, "now": now})


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
@pytest.mark.parametrize("path", ["/", "/tasks", "/api/chat", "/login", "/session"])
def test_with_no_passcode_nothing_is_asked_of_anyone(path, method):
    assert guard("https://diya.test" + path, method, {"origin": "https://evil.example"}, env={}) is None


@pytest.mark.parametrize("path, query", [("/", ""), ("/tasks", ""), ("/memory", "?filter=old"), ("/history", "?a=1&b=2")])
def test_a_page_without_a_session_goes_to_the_sign_in_page_and_comes_back(path, query):
    response = guard("https://diya.test:3000" + path + query)
    assert response["status"] == 307 and response["headers"]["cache-control"] == "no-store"
    assert response["headers"]["location"] == "https://diya.test:3000/login?next=" + quote(path + query, safe="")


def test_the_sign_in_page_is_at_the_name_the_browser_used_not_the_one_the_server_calls_itself():
    # a phone that reached this computer by its address is sent to that address, not to the phone's own "localhost"
    response = guard("https://localhost:3000/tasks", headers={"host": "phone-visible.test:3000"})
    assert response["headers"]["location"] == "https://phone-visible.test:3000/login?next=%2Ftasks"
    assert guard("https://localhost:3000/tasks")["headers"]["location"] == "https://localhost:3000/login?next=%2Ftasks"  # no Host header: the URL's own


@pytest.mark.parametrize("path", ["/api/chat", "/api/memory/3/accept", "/api/today", "/api/transcribe"])
def test_an_api_call_without_a_session_gets_a_511_the_pages_can_tell_from_a_refused_token(path):
    response = guard("https://diya.test" + path, "POST", {"origin": ORIGIN, **HOST})
    assert response["status"] == 511 and response["headers"]["content-type"] == "application/json"
    assert "location" not in response["headers"] and "Sign in again" in body(response)["error"]


@pytest.mark.parametrize("path", ["/login", "/session"])
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_the_way_in_is_open_to_anyone_who_asks_in_the_ordinary_way(path, method):
    assert guard("https://diya.test:3000" + path, method, {"origin": ORIGIN, **HOST}) is None


def test_a_good_session_is_let_through_everywhere_else():
    cookie = signed_in_cookie()
    for path, method in [("/", "GET"), ("/tasks", "GET"), ("/api/chat", "POST"), ("/api/today", "GET"), ("/_next/webpack-hmr", "GET"), ("/api/memory/3/accept", "POST")]:
        assert guard("https://diya.test:3000" + path, method, {"cookie": "a=1; " + cookie + "; b=2", "origin": ORIGIN, **HOST}) is None, path


def test_a_session_that_is_over_or_not_ours_is_no_session():
    cookie = signed_in_cookie()
    expired = guard("https://diya.test/tasks", headers={"cookie": cookie}, now=NOW + 31 * DAY)
    other = guard("https://diya.test/tasks", headers={"cookie": cookie}, env={"DIYA_UI_PASSCODE": "a different passcode"})
    torn = guard("https://diya.test/tasks", headers={"cookie": cookie[:-3]})
    named_otherwise = guard("https://diya.test/tasks", headers={"cookie": cookie.replace("diya_session", "other")})
    assert [r["status"] for r in (expired, other, torn, named_otherwise)] == [307] * 4


@pytest.mark.parametrize("origin", ["https://evil.example", "https://diya.test:3001", "http://diya.test:3000", "null", "not a url", "https://diya.test.evil.example:3000"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_change_that_says_it_came_from_another_site_is_refused_even_with_a_good_session(method, origin):
    response = guard("https://diya.test:3000/api/actions/3/approve", method, {"cookie": signed_in_cookie(), "origin": origin, **HOST})
    assert response["status"] == 403 and "another site" in body(response)["error"]


def test_a_change_that_says_nothing_about_where_it_came_from_is_not_a_browser_cross_site_request():
    assert guard("https://diya.test:3000/api/chat", "POST", {"cookie": signed_in_cookie(), **HOST}) is None


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_reading_is_not_refused_for_its_origin_the_cookie_rules_decide(method):
    assert guard("https://diya.test:3000/tasks", method, {"cookie": signed_in_cookie(), "origin": "https://evil.example", **HOST}) is None


def test_the_other_site_check_comes_before_the_way_in_is_opened():
    assert guard("https://diya.test:3000/session", "POST", {"origin": "https://evil.example", **HOST})["status"] == 403


def test_the_host_the_request_was_made_to_is_what_an_origin_is_compared_with():
    # a phone reaching the laptop by its address: the Host header says so, whatever name the server calls itself
    assert guard("https://localhost:3000/api/chat", "POST", {"cookie": signed_in_cookie(), "origin": "https://192-0-2-1.nip.test:3000", "host": "192-0-2-1.nip.test:3000"}) is None
    assert guard("https://localhost:3000/api/chat", "POST", {"cookie": signed_in_cookie(), "origin": "https://localhost:3000", "host": "192-0-2-1.nip.test:3000"})["status"] == 403


# --- /session ---------------------------------------------------------------------------------------------------------

def session(method="GET", payload=None, headers=None, env=ENV, state="s", now=NOW, url="https://diya.test:3000/session", raw=None):
    step = {"op": "session", "url": url, "method": method, "headers": {"origin": ORIGIN, **HOST, **(headers or {})}, "env": env, "state": state, "now": now}
    if raw is not None:
        step["body"] = raw
    elif payload is not None:
        step["body"] = json.dumps(payload)
        step["headers"]["content-type"] = "application/json"
    return step


def wrong(state="s", now=NOW, passcode="nope nope nope"):
    return session("POST", {"passcode": passcode}, state=state, now=now)


def test_asking_says_whether_sign_in_is_on_and_whether_this_browser_is_signed_in():
    cookie = signed_in_cookie()
    off, out, signed = run(session(env={}), session(), session(headers={"cookie": cookie}))
    assert [body(r) for r in (off, out, signed)] == [{"required": False, "signedIn": False}, {"required": True, "signedIn": False}, {"required": True, "signedIn": True}]
    assert off["headers"]["cache-control"] == "no-store"
    expired = one(session(headers={"cookie": cookie}, now=NOW + 31 * DAY))
    assert body(expired) == {"required": True, "signedIn": False}


def test_a_right_passcode_signs_in_with_a_cookie_that_is_hidden_from_scripts_and_from_other_sites():
    response = one(session("POST", {"passcode": PASS, "next": "/tasks"}))
    assert response["status"] == 200 and body(response) == {"ok": True, "next": "/tasks"}
    attributes = [a.strip() for a in response["headers"]["set-cookie"].split(";")]
    assert attributes[0].startswith("diya_session=v1.")
    assert {"Path=/", "Max-Age=2592000", "HttpOnly", "SameSite=Strict", "Secure"} <= set(attributes)
    assert one({"op": "sessionValid", "passcode": PASS, "token": cookie_of(response), "now": NOW}) is True
    assert one({"op": "sessionValid", "passcode": PASS, "token": cookie_of(response), "now": NOW + 29 * DAY}) is True


def test_the_cookie_is_marked_secure_only_when_the_connection_is_https():
    http = one(session("POST", {"passcode": PASS}, url="http://diya.test:3000/session", headers={"origin": "http://diya.test:3000"}))
    assert "Secure" not in http["headers"]["set-cookie"] and "HttpOnly" in http["headers"]["set-cookie"]


@pytest.mark.parametrize("asked, expected", [("/memory?x=1", "/memory?x=1"), ("https://evil.example/", "/"), ("//evil.example", "/"), (None, "/"), (7, "/"), ("/login", "/")])
def test_the_page_after_signing_in_is_one_on_this_site(asked, expected):
    assert body(one(session("POST", {"passcode": PASS, "next": asked})))["next"] == expected


def test_signing_in_when_no_passcode_is_set_is_a_404_not_a_way_in():
    assert one(session("POST", {"passcode": ""}, env={}))["status"] == 404
    assert one(session("DELETE", env={}))["status"] == 404


def test_a_wrong_passcode_is_a_401_after_a_short_wait_and_leaves_no_cookie():
    response, state = run(wrong(), {"op": "state", "state": "s"})
    assert response["status"] == 401 and body(response) == {"error": "That passcode is not right."} and "set-cookie" not in response["headers"]
    assert state["failures"] == 1 and state["sleeps"] == [400]


def test_a_right_passcode_does_not_wait():
    _, state = run(session("POST", {"passcode": PASS}), {"op": "state", "state": "s"})
    assert state["sleeps"] == []


@pytest.mark.parametrize("payload", [{}, {"passcode": None}, {"passcode": 123}, {"passcode": ["x"]}, {"passcode": ""}, {"other": PASS}, [PASS], "text", 5, None])
def test_anything_but_the_passcode_as_text_counts_as_a_wrong_one(payload):
    response, state = run(session("POST", raw=json.dumps(payload)), {"op": "state", "state": "s"})
    assert response["status"] == 401 and state["failures"] == 1


def test_five_wrong_passcodes_in_a_row_lock_it_for_five_minutes_and_the_fifth_says_so():
    out = run(*[wrong() for _ in range(5)], {"op": "state", "state": "s"})
    assert [r["status"] for r in out[:5]] == [401, 401, 401, 401, 429]
    assert out[4]["headers"]["retry-after"] == "300" and "about 5 minutes" in body(out[4])["error"]
    assert out[5]["lockedUntil"] == NOW + 5 * 60 * 1000 and out[5]["failures"] == 0 and out[5]["locks"] == 1


def test_while_it_is_locked_even_the_right_passcode_is_turned_away_and_nothing_waits_or_counts():
    out = run(*[wrong() for _ in range(5)], session("POST", {"passcode": PASS}, now=NOW + 60_000), {"op": "state", "state": "s"})
    assert out[5]["status"] == 429 and out[5]["headers"]["retry-after"] == "240" and "set-cookie" not in out[5]["headers"]
    assert out[6]["failures"] == 0 and out[6]["sleeps"] == [400] * 5


def test_when_the_lock_has_run_out_the_right_passcode_works_again_and_forgets_the_lock():
    after = NOW + 5 * 60 * 1000
    out = run(*[wrong() for _ in range(5)], session("POST", {"passcode": PASS}, now=after), {"op": "state", "state": "s"})
    assert out[5]["status"] == 200 and out[6]["locks"] == 0 and out[6]["lockedUntil"] == 0 and out[6]["failures"] == 0


def test_each_lock_is_twice_as_long_as_the_one_before_up_to_an_hour():
    steps, starts, now = [], [], NOW
    expected = [min(5 * 60 * 1000 * 2 ** n, 60 * 60 * 1000) for n in range(8)]
    for span in expected:
        starts.append(now)
        steps += [wrong(now=now) for _ in range(5)] + [{"op": "state", "state": "s"}]
        now += span  # the lock is over exactly then
    results = run(*steps)
    spans = [results[5 + 6 * n]["lockedUntil"] - starts[n] for n in range(8)]
    assert spans == expected == [300_000, 600_000, 1_200_000, 2_400_000, 3_600_000, 3_600_000, 3_600_000, 3_600_000]


def test_a_right_passcode_in_the_middle_resets_the_count():
    out = run(*[wrong() for _ in range(4)], session("POST", {"passcode": PASS}), *[wrong() for _ in range(4)], {"op": "state", "state": "s"})
    assert all(r["status"] == 401 for r in out[:4]) and out[4]["status"] == 200
    assert all(r["status"] == 401 for r in out[5:9]) and out[9]["failures"] == 4 and out[9]["locks"] == 0


def test_the_count_is_one_for_everyone_so_a_forged_address_does_not_get_around_it():
    steps = [session("POST", {"passcode": "nope nope nope"}, headers={"x-forwarded-for": f"203.0.113.{n}"}) for n in range(5)]
    assert [r["status"] for r in run(*steps)] == [401, 401, 401, 401, 429]


def test_a_malformed_or_oversized_request_is_refused_without_counting_as_a_guess():
    huge = json.dumps({"passcode": "x" * 5000})
    out = run(session("POST", raw="{not json"), session("POST", raw=""), session("POST", raw=huge),
              session("POST", raw="{}", headers={"content-length": "999999"}), {"op": "state", "state": "s"})
    assert [r["status"] for r in out[:4]] == [400, 400, 413, 413] and out[4]["failures"] == 0 and out[4]["sleeps"] == []


def test_signing_out_clears_the_cookie_and_needs_no_session():
    response = one(session("DELETE"))
    assert response["status"] == 200 and body(response) == {"ok": True}
    cookie = response["headers"]["set-cookie"]
    assert cookie.startswith("diya_session=;") and "Max-Age=0" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie


def test_a_change_from_another_site_is_refused_and_does_not_count_against_the_owner():
    out = run(session("POST", {"passcode": PASS}, headers={"origin": "https://evil.example"}), session("DELETE", headers={"origin": "https://evil.example"}),
              {"op": "state", "state": "s"})
    assert [r["status"] for r in out[:2]] == [403, 403] and out[2]["failures"] == 0 and "set-cookie" not in out[0]["headers"]


@pytest.mark.parametrize("method", ["PUT", "PATCH"])
def test_other_methods_are_not_allowed(method):
    response = one(session(method, {"passcode": PASS}))
    assert response["status"] == 405 and response["headers"]["allow"] == "GET, POST, DELETE"


def test_a_state_of_its_own_means_one_server_does_not_lock_another():
    out = run(*[wrong(state="a") for _ in range(5)], session("POST", {"passcode": PASS}, state="b"))
    assert out[4]["status"] == 429 and out[5]["status"] == 200


# --- the wording of the wait -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seconds_left, words", [(1, "about a minute"), (30, "about a minute"), (60, "about a minute"), (61, "about 2 minutes"), (240, "about 4 minutes"), (300, "about 5 minutes")])
def test_the_wait_is_said_in_whole_minutes_rounded_up(seconds_left, words):
    out = run(*[wrong() for _ in range(5)], session("POST", {"passcode": PASS}, now=NOW + 5 * 60 * 1000 - seconds_left * 1000))
    assert out[5]["status"] == 429 and words in body(out[5])["error"] and out[5]["headers"]["retry-after"] == str(seconds_left)


# --- the module stays free of what the browser side must never name ---------------------------------------------------------

def test_the_module_is_plain_web_standards_so_the_middleware_and_node_can_both_run_it():
    source = MODULE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*import\s", source, re.M) and "require(" not in source and "node:" not in source
    assert "console." not in source  # a passcode is never written anywhere


# --- found by mutation testing: the comparison looks at every byte, not only the last ---------------------------------------

@pytest.mark.parametrize("attempt", ["guess number 165", "guess number 790"])
def test_an_attempt_whose_digest_agrees_with_the_real_ones_in_the_last_or_first_byte_is_still_wrong(attempt):
    """Both were found by search: sha256 of each (with the module's prefix) ends, or begins, with the same byte as the real passcode's."""
    assert one({"op": "passcodeMatches", "passcode": PASS, "attempt": attempt}) is False


@pytest.mark.parametrize("position", [0, 1, 17, 32, 62, 63])
def test_a_signature_altered_anywhere_in_it_is_refused(position):
    token = one({"op": "makeSession", "passcode": PASS, "now": NOW})
    version, expiry, mac = token.split(".")
    other = "0" if mac[position] != "0" else "1"
    altered = f"{version}.{expiry}.{mac[:position]}{other}{mac[position + 1:]}"
    assert one({"op": "sessionValid", "passcode": PASS, "token": altered, "now": NOW}) is False


def test_a_session_made_without_a_passcode_is_no_session_for_no_passcode():
    token = one({"op": "makeSession", "passcode": "", "now": NOW})
    assert one({"op": "sessionValid", "passcode": "", "token": token, "now": NOW}) is False


def test_a_token_that_is_a_list_holding_a_real_one_is_not_a_token():
    token = one({"op": "makeSession", "passcode": PASS, "now": NOW})
    assert one({"op": "sessionValid", "passcode": PASS, "token": [token], "now": NOW}) is False
    assert one({"op": "sessionValid", "passcode": PASS, "token": {"toString": token}, "now": NOW}) is False


def test_the_host_a_request_names_is_compared_in_lower_case():
    cookie = signed_in_cookie()
    assert guard("https://diya.test:3000/api/chat", "POST", {"cookie": cookie, "origin": "https://diya.test:3000", "host": "DIYA.Test:3000"}) is None


def test_the_wait_before_trying_again_is_rounded_up_to_a_whole_second():
    out = run(*[wrong() for _ in range(5)], session("POST", {"passcode": PASS}, now=NOW + 500))  # 299.5 seconds are left
    assert out[5]["headers"]["retry-after"] == "300" and "about 5 minutes" in body(out[5])["error"]
