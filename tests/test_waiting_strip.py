"""The one-tap approval under the chat (frontend/components/WaitingActions.jsx), added 2026-10-26.

The owner found going to the Actions page for every approval tiring, and Diya's reply after a proposal now says "press Approve (under this message, or on the Actions page)". What this proves from the source:
the strip is on the chat page (and not on an earlier chat); it approves with the hash of exactly what was shown and turns down through the same two routes as the Actions page; a proposal made after Diya read
something that is not the owner's, or above risk level 2, is only pointed to, never approved here; a result's address is a link only when it is Google's own; and the menu badge is told to read again.
The API's side of an approval (the hash, the lapse after a day, one decision once) is tests/test_actions_api.py and is unchanged.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRIP = (ROOT / "frontend" / "components" / "WaitingActions.jsx").read_text(encoding="utf-8")
PAGE = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
SHELL = (ROOT / "frontend" / "components" / "AppShell.jsx").read_text(encoding="utf-8")


def test_the_chat_page_shows_the_strip_but_not_in_an_earlier_chat():
    assert "import WaitingActions from '../components/WaitingActions'" in PAGE and "{!earlierChat && <WaitingActions refreshKey={messages.length} />}" in PAGE


def test_it_approves_with_the_hash_of_what_was_shown_and_turns_down_by_the_same_routes_as_the_actions_page():
    assert "`/api/actions/${action.id}/approve`" in STRIP and "JSON.stringify({ args_hash: action.args_hash })" in STRIP and "`/api/actions/${action.id}/reject`" in STRIP
    assert "/resolve" not in STRIP  # an outcome that is not known is looked at on the Actions page, never settled here


def test_only_a_proposal_from_the_owners_own_message_and_of_low_risk_is_approved_here():
    assert "const MAX_RISK_HERE = 2" in STRIP and "!action.tainted && (!action.preview || action.preview.tier <= MAX_RISK_HERE)" in STRIP
    assert "Check it on the Actions page" in STRIP  # the others are pointed to


def test_a_result_address_is_a_link_only_when_it_is_googles_own():
    assert "host === 'google.com' || host.endsWith('.google.com')" in STRIP and "rel=\"noopener noreferrer\"" in STRIP and "/^https:\\/\\//.test(part)" in STRIP


def test_a_decision_tells_the_menu_badge_to_read_again():
    assert "window.dispatchEvent(new Event('diya-actions-changed'))" in STRIP
    assert "window.addEventListener('diya-actions-changed', checkActions)" in SHELL and "window.removeEventListener('diya-actions-changed', checkActions)" in SHELL


def test_the_strip_uses_the_themes_own_tokens_and_no_raw_colours():
    css = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    block = "\n".join(line for line in css.splitlines() if line.startswith(".waiting-"))
    assert block and not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", block)
