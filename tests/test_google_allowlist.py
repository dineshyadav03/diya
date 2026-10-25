"""An approved action may ask Google for only these things (diya_google_write.permitted / _send; DIYA-040; and the live-check plan docs/GOOGLE_LIVE_SMOKE.md for DIYA-070), added 2026-10-25.

What this proves: each connector can make exactly the requests its action needs and no other (the primary calendar, the default task list, Drive's top level and Docs, by one id each); a different calendar, a
list, a share, a person's address, another method, another host, a query glued onto the address or another connector's address is refused before a token is fetched or anything is sent; random addresses built
from the real pieces are accepted only when they are exactly one of the allowed shapes; and the live-check plan names every Google operation the catalog has and a stand-in test file that mentions it.
"""
import dataclasses
import random
import re
from pathlib import Path

import pytest

import diya_actions
import diya_catalog
import diya_config
import diya_google_calendar as gcal
import diya_google_write as gw

ROOT = Path(__file__).resolve().parent.parent
CAL, TASKS, DRIVE = "google_calendar_edit", "google_tasks", "google_drive_files"
ID = "abcde12345_-XYZ"

ALLOWED = [
    (CAL, "POST", gw.CALENDAR_API), (CAL, "GET", f"{gw.CALENDAR_API}/{ID}"),
    (TASKS, "POST", gw.TASKS_API), (TASKS, "GET", f"{gw.TASKS_API}/{ID}"),
    (DRIVE, "POST", gw.DRIVE_API), (DRIVE, "GET", f"{gw.DRIVE_API}/{ID}"),
    (DRIVE, "POST", gw.DOCS_API), (DRIVE, "POST", f"{gw.DOCS_API}/{ID}:batchUpdate"), (DRIVE, "GET", f"{gw.DOCS_API}/{ID}"),
]


@pytest.mark.parametrize("connector, method, url", ALLOWED)
def test_each_request_an_action_needs_is_allowed(connector, method, url):
    assert gw.permitted(connector, method, url)


@pytest.mark.parametrize("connector, method, url", [
    (CAL, "POST", "https://www.googleapis.com/calendar/v3/calendars/someone@example.com/events"),  # another calendar
    (CAL, "GET", "https://www.googleapis.com/calendar/v3/users/me/calendarList"),  # a list
    (CAL, "POST", gw.CALENDAR_API + "?sendUpdates=all"),  # a query glued on: mail to guests
    (CAL, "DELETE", f"{gw.CALENDAR_API}/{ID}"), (CAL, "PATCH", f"{gw.CALENDAR_API}/{ID}"), (CAL, "PUT", f"{gw.CALENDAR_API}/{ID}"),
    (CAL, "POST", f"{gw.CALENDAR_API}/{ID}/instances"), (CAL, "GET", f"{gw.CALENDAR_API}/../{ID}"), (CAL, "GET", f"{gw.CALENDAR_API}/a/b"),
    (CAL, "POST", gw.TASKS_API),  # another connector's address
    (TASKS, "POST", gw.CALENDAR_API), (TASKS, "GET", "https://tasks.googleapis.com/tasks/v1/users/@me/lists"),
    (DRIVE, "POST", f"{gw.DRIVE_API}/{ID}/permissions"),  # a share
    (DRIVE, "DELETE", f"{gw.DRIVE_API}/{ID}"), (DRIVE, "GET", gw.DRIVE_API),  # a search of the whole Drive
    (DRIVE, "POST", f"{gw.DOCS_API}/{ID}:copy"),
    (DRIVE, "POST", "https://evil.example.com/v1/documents"), (CAL, "POST", gw.CALENDAR_API.replace("https://", "http://")),
    (CAL, "GET", f"{gw.CALENDAR_API}/ab"),  # an id too short to be one
    ("google_unknown", "POST", gw.CALENDAR_API),
])
def test_everything_else_is_refused(connector, method, url):
    assert not gw.permitted(connector, method, url)


def test_a_request_outside_the_list_is_refused_before_a_token_is_fetched_or_anything_is_sent(monkeypatch, tmp_path):
    config = dataclasses.replace(diya_config.load_config(), connector_tokens_dir=str(tmp_path / "t"), connectors_log_path=str(tmp_path / "l"))

    def boom(*_args, **_kwargs):
        raise AssertionError("reached past the allowlist")

    monkeypatch.setattr(gcal, "access_token", boom)
    monkeypatch.setattr(gw.httpx, "request", boom)
    with pytest.raises(diya_actions.ActionFailed, match="not allowed to make that request"):
        gw._send(config, CAL, "POST", "https://www.googleapis.com/calendar/v3/calendars/other/events", body={})


def test_random_addresses_built_from_the_real_pieces_are_allowed_only_when_they_are_exactly_an_allowed_shape():
    rng = random.Random(7)
    bases = [gw.CALENDAR_API, gw.TASKS_API, gw.DRIVE_API, gw.DOCS_API]
    tails = ["", "/", f"/{ID}", f"/{ID}:batchUpdate", f"/{ID}/permissions", "/a", "/ab/cd", "?x=1", "#f", f"/{ID}?sendUpdates=all", "/%2e%2e/x", f"/{ID}:copy", " ", "\n", f"/{ID}\n", "/" + "x" * 129]
    allowed = tuple(re.compile(pattern) for pattern in (
        r"(?:%s)" % "|".join(re.escape(b) for b in bases),
        r"(?:%s)/[A-Za-z0-9_-]{5,128}" % "|".join(re.escape(b) for b in bases),
        re.escape(gw.DOCS_API) + r"/[A-Za-z0-9_-]{5,128}:batchUpdate",
    ))
    for _ in range(3000):
        url = rng.choice(bases) + rng.choice(tails) + (rng.choice(tails) if rng.random() < 0.2 else "")
        for connector in (CAL, TASKS, DRIVE):
            for method in ("GET", "POST", "DELETE", "PATCH"):
                if gw.permitted(connector, method, url):
                    assert any(pattern.fullmatch(url) for pattern in allowed), (connector, method, url)
                    assert method in ("GET", "POST")


def test_the_live_check_plan_names_every_google_operation_the_catalog_has_and_a_test_file_that_mentions_it():
    plan = (ROOT / "docs" / "GOOGLE_LIVE_SMOKE.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `(\w+)` \|.*`(tests/\w+\.py)` — `(\w+)` \|$", plan, re.MULTILINE)
    named = {name for name, _file, _word in rows}
    in_catalog = {e.name for e in diya_catalog.CATALOG.values() if e.connector.startswith("google")}
    assert named == in_catalog, (sorted(named ^ in_catalog))
    for name, path, word in rows:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert word in text, (name, path, word)
