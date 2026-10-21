"""The Rule of Two, kept as a test (diya_catalog.legs, rule_of_two_violations, session_exposure; RESEARCH.md entry 17, task DIYA-281), added 2026-10-21.

What this proves, with the real catalog: no tool, proposal or flow has all three of "reads words other people wrote", "reaches the person's private data" and "can send something out or change something" unless it is
a proposal the owner approves action by action; a tool that sends the model's own words to a service the owner does not control is named in FREE_TEXT_OUT (so a new one is a decision, not an accident); every read
through one of the owner's own accounts counts as private data; a made-up entry that breaks each rule is caught (so the check itself works); and the one open accounting, a chat session that offers private+untrusted
readers next to free-text senders, is pinned to exactly what it is today and is written in the generated authority document. It does not prove the open accounting is safe: it makes sure it cannot grow unseen.
"""
import dataclasses

import diya_catalog as c

FAKE = c.Entry("fake_tool", "tool", 0, "x", "none", "n/a", "none", False)


def test_the_real_catalog_breaks_no_rule():
    assert c.rule_of_two_violations() == []


def test_no_entry_has_all_three_legs_except_an_approved_proposal():
    assert all(c.leg_count(e) < 3 for e in c.CATALOG.values())
    assert max(c.leg_count(e) for e in c.CATALOG.values()) == 2


def test_the_model_free_text_that_leaves_the_computer_is_named_and_pinned():
    assert set(c.FREE_TEXT_OUT) == {"web_search", "get_weather"}
    for name in c.FREE_TEXT_OUT:
        entry = c.CATALOG[name]
        assert entry.type == "tool" and entry.tier == 0 and entry.approval == "none" and c.legs(entry)["outward"]


def test_every_name_counted_as_private_data_exists_and_every_account_read_is_counted():
    assert c.PRIVATE_DATA <= set(c.CATALOG)
    assert all(e.name in c.PRIVATE_DATA for e in c.CATALOG.values() if e.connector and e.tier == 0)


def test_a_proposal_has_the_outward_leg_and_none_of_the_others():
    for entry in c.CATALOG.values():
        if entry.type == "proposal":
            assert c.legs(entry) == {"untrusted": False, "private": False, "outward": True}
            assert entry.approval == "owner approves each action"


def test_a_made_up_entry_that_breaks_each_rule_is_caught():
    three = dataclasses.replace(FAKE, name="steals", tier=2, untrusted_output=True)
    three_catalog = {"steals": three}
    assert c.leg_count(three) == 2  # untrusted + outward ...
    # ... and with private data counted, it has all three and is not an approved proposal
    original = c.PRIVATE_DATA
    try:
        c.PRIVATE_DATA = original | {"steals"}
        assert c.leg_count(three) == 3 and any("all three legs" in v for v in c.rule_of_two_violations(three_catalog))
        proposal = dataclasses.replace(three, type="proposal", approval="owner approves each action")
        assert c.rule_of_two_violations({"steals": proposal}) == []
    finally:
        c.PRIVATE_DATA = original
    new_network = dataclasses.replace(FAKE, name="fetch_anything", network="any host")
    assert any("not declared in FREE_TEXT_OUT" in v for v in c.rule_of_two_violations({"fetch_anything": new_network}))
    unlisted_read = dataclasses.replace(FAKE, name="read_new_account", network="api.example.com", connector="example", untrusted_output=True)
    assert any("not counted as private data" in v for v in c.rule_of_two_violations({"read_new_account": unlisted_read}))


def test_the_open_accounting_is_pinned_to_what_it_is_today():
    readers, senders = c.session_exposure()
    assert senders == ["get_weather", "web_search"]
    assert readers == ["list_calendar_events", "list_files", "list_google_tasks", "list_todoist_tasks", "search_home_assistant", "search_notes", "search_notion"]
    assert "read_mail" not in readers  # mail is read by a model with no tools, so it never shares a turn with a sender


def test_the_authority_document_states_the_rule_and_the_open_accounting():
    text = c.DOC.read_text(encoding="utf-8")
    assert "The Rule of Two, tool by tool" in text and "No single entry has all three" in text
    for name in c.CATALOG:
        assert f"| `{name}` |" in text
    assert "web_search" in text.split("No single entry has all three", 1)[1]
