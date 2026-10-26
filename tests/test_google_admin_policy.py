"""Diya holds no administrative or cloud power over Google (DIYA-135, -136, -137, -138; docs/GOOGLE_ADMIN_POLICY.md), added 2026-10-25.

What this proves, from the source and the registries, not from a promise: the set of Google permission scopes the app asks for is exactly eleven (the original five, the three Gmail cards of 2026-10-26: drafts, send,
organise, the Drive read card, and the two Contacts cards), all about the owner's own calendar, mail, tasks and files; none of
them, and nothing else in the app, names an administrative or cloud power; the connector registry has no connector for cloud or directory administration; the catalog has nothing at the external-facing or
destructive tiers and nothing whose effect is about billing, projects, roles or accounts; and the policy page says what any future power would have to meet. A new scope, connector or tier-3/4 entry makes this
fail until the decision is made on purpose.
"""
import re
from pathlib import Path

import diya_catalog
import diya_config
import diya_connector_tools

ROOT = Path(__file__).resolve().parent.parent
SCOPE = re.compile(r"https://(?:www\.googleapis\.com/auth/[A-Za-z0-9._-]+|mail\.google\.com/)")
ALLOWED = {
    "https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/tasks", "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.modify",  # the Gmail cards (docs/GOOGLE_CHANGES.md)
    "https://www.googleapis.com/auth/drive.readonly",  # the Drive read card: searching and reading the owner's own files
    "https://www.googleapis.com/auth/contacts.readonly", "https://www.googleapis.com/auth/contacts",  # the Contacts cards: the owner's own address book
}
POWER = re.compile(r"admin|directory|cloud-platform|cloud-billing|billing|\biam\b|compute|groups|vault|reseller|chrome\.management|apps\.order|ediscovery", re.IGNORECASE)


def app_sources():
    return [p for p in sorted(ROOT.glob("*.py")) if not p.name.startswith(("milestone", "diya_chat", "dossier"))]


def test_the_google_permissions_the_app_asks_for_are_exactly_these_eleven():
    found = set()
    for path in app_sources():
        found |= set(SCOPE.findall(path.read_text(encoding="utf-8")))
    assert found == ALLOWED, (sorted(found - ALLOWED), sorted(ALLOWED - found))


def test_none_of_them_and_nothing_else_the_app_asks_google_for_names_an_administrative_power():
    for path in app_sources():
        for scope in SCOPE.findall(path.read_text(encoding="utf-8")):
            assert not POWER.search(scope), (path.name, scope)


def test_no_connector_is_for_cloud_or_directory_administration():
    for connector in diya_connector_tools.real_connectors(diya_config.load_config()):
        text = f"{connector.name} {connector.label} {connector.description}"
        assert not re.search(r"admin|directory|cloud console|billing|provision", text, re.IGNORECASE), text


def test_the_catalog_has_nothing_external_facing_or_destructive_and_nothing_about_money_or_accounts():
    for entry in diya_catalog.CATALOG.values():
        assert entry.tier <= 3, (entry.name, entry.tier)  # tier 3 (reaches other people, or removes what Diya cannot bring back) exists, one proposal at a time; tier 4 (destructive or privileged at scale) is never built
        assert not re.search(r"billing|provision|\biam\b|role|organisation|organization|domain-wide", f"{entry.name} {entry.effect}", re.IGNORECASE), (entry.name, entry.effect)


def test_the_policy_page_says_what_any_future_power_must_meet():
    page = (ROOT / "docs" / "GOOGLE_ADMIN_POLICY.md").read_text(encoding="utf-8")
    for task in ("DIYA-135", "DIYA-136", "DIYA-137", "DIYA-138"):
        assert task in page
    assert "own Google Cloud project, OAuth client and connector" in page and "second, independent" in page and "super administrator" in page and "domain-wide delegation refused" in page
