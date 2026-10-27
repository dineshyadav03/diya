"""A Google Doc that cites its sources and cannot make one up (diya_google_cited.py; DIYA-096; docs/GOOGLE_CHANGES.md), added 2026-10-27.

What this proves: a source is only a web address that a search showed in this turn or that the person typed (any other the model offers is dropped, and none left refuses the Doc); the text may name no other address; it must
cite with [n] and every n must be a source; the list of sources is added by code, numbered, and is never cut; the Doc is the existing "make a Google Doc" (a proposal the owner approves, never straight away) and is read back; a
message that asks for sources is not the plain Doc kind's, so a sourced Doc cannot be made without the check; and the card says that what a page claims is not checked.
"""
import dataclasses
import json

import pytest

import diya
import diya_actions
import diya_autoapprove
import diya_catalog
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_cited as gc
import diya_google_client as client
import diya_google_write as gw
import diya_intent_google as asks
from fakes import FakeClient, text_reply, tool_reply
from test_saga import World

SEEN = ("https://a.example/spaced", "https://b.example/recall")


def test_addresses_are_found_cleaned_of_trailing_punctuation_and_once():
    assert gc.urls_in("see https://a.example/x, and (https://b.example/y). Again https://a.example/x!") == ["https://a.example/x", "https://b.example/y"]
    assert gc.urls_in("none here") == [] and gc.urls_in(None) == []


def test_only_a_source_that_was_seen_is_kept_and_the_list_is_added_by_code():
    args, notes = gc.prepare({"title": "Spacing", "body": "Spacing helps memory [1] and testing helps too [2].", "sources": "https://a.example/spaced https://b.example/recall https://evil.example/made-up"}, "research spacing", SEEN)
    assert args == {"title": "Spacing", "body": "Spacing helps memory [1] and testing helps too [2]. Sources: [1] https://a.example/spaced [2] https://b.example/recall"}
    assert notes == ["1 address(es) the model offered as sources were left out because no search showed them."]


def test_an_address_the_person_typed_is_a_source_and_a_trailing_slash_or_capitals_do_not_matter():
    args, _ = gc.prepare({"title": "T", "body": "It says so [1].", "sources": "HTTPS://Docs.Example/Page/"}, "use https://docs.example/page for it", ())
    assert args["body"].endswith("Sources: [1] https://docs.example/page")


@pytest.mark.parametrize("args, seen, why", [
    ({"title": "T", "body": "x [1]", "sources": "https://evil.example/a"}, SEEN, "no source can be cited"),
    ({"title": "T", "body": "x [1]", "sources": ""}, SEEN, "no source can be cited"),
    ({"title": "T", "body": "x [1]", "sources": "https://a.example/spaced"}, (), "no source can be cited"),
    ({"title": "T", "body": "no citation here", "sources": "https://a.example/spaced"}, SEEN, "must cite its sources with"),
    ({"title": "T", "body": "x [2]", "sources": "https://a.example/spaced"}, SEEN, "cites \\[2\\] but there are 1 source"),
    ({"title": "T", "body": "x [0] [1]", "sources": "https://a.example/spaced"}, SEEN, "cite only \\[1\\] to \\[1\\]"),
    ({"title": "T", "body": "x [1] see https://evil.example/hidden", "sources": "https://a.example/spaced"}, SEEN, "names an address that was never found"),
    ({"title": "T", "body": "", "sources": "https://a.example/spaced"}, SEEN, "needs its text"),
    ({"title": "T", "body": "x [1] " + "y" * 3100, "sources": "https://a.example/spaced"}, SEEN, "sources list is never cut"),
])
def test_a_doc_that_cannot_be_traced_to_what_was_found_is_refused(args, seen, why):
    with pytest.raises(diya_actions.InvalidArgs, match=why):
        gc.prepare(args, "research it", seen)


def test_a_message_that_asks_for_sources_is_not_the_plain_doc_kinds():
    plain = gw.doc_kind()
    assert plain.asked("make a google doc called Plan") is True and plain.asked("make a google doc called Plan with sources") is False and plain.asked("create a google doc called Plan and cite your sources") is False
    assert asks.asks_for_cited_doc("research spaced practice and make a google doc called Plan with sources") is True and asks.asks_for_cited_doc("make a google doc called Plan") is False


# ---- in the chat, from a search to an approved Doc ---------------------------------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False, lookup=False)
    diya_connectors.store_token(config, "google_drive_files", "refresh")
    return config


@pytest.fixture
def world(monkeypatch):
    service = World()
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "tok" if name == "google_drive_files" else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(gw.httpx, "request", service)
    monkeypatch.setattr(diya, "web_search", lambda query: "Spacing: it helps (https://a.example/spaced)\nRecall: testing helps (https://b.example/recall)")
    return service


def ask(config, replies, message):
    agent = diya.Agent(config, client=FakeClient(list(replies)), action_kinds=list(gc.action_kinds()) + [gw.doc_kind()])
    agent.ask([{"role": "user", "content": message}])
    return agent


def test_a_search_then_a_cited_doc_is_proposed_with_only_the_addresses_the_search_showed(config, world):
    agent = ask(config, [tool_reply("web_search", json.dumps({"query": "spaced practice"}), call_id="c1"),
                         tool_reply("propose_cited_google_doc", json.dumps({"title": "Spacing", "body": "Spacing helps [1]. Testing helps [2].", "sources": "https://a.example/spaced https://b.example/recall https://invented.example/x"}), call_id="c2"),
                         text_reply("ok")], "research spaced practice and make a google doc called Spacing with sources")
    (action,) = agent.actions.actions()
    assert action["kind"] == "google_docs_create_cited" and action["args"]["body"].endswith("Sources: [1] https://a.example/spaced [2] https://b.example/recall") and "invented" not in json.dumps(action["args"])
    assert action["tainted"] and "web_search" in action["taint_sources"] and "that a page says what the text claims is not checked" in action["summary"]


def test_without_a_search_and_with_no_typed_link_there_is_nothing_to_cite_and_nothing_is_proposed(config, world):
    agent = ask(config, [tool_reply("propose_cited_google_doc", json.dumps({"title": "Spacing", "body": "Spacing helps [1].", "sources": "https://a.example/spaced"}), call_id="c1"), text_reply("ok")],
                "make a google doc called Spacing with sources")
    assert agent.actions.actions() == []


def test_a_link_the_person_typed_can_be_cited_without_a_search(config, world):
    agent = ask(config, [tool_reply("propose_cited_google_doc", json.dumps({"title": "Notes", "body": "It says so [1].", "sources": "https://docs.example/page"}), call_id="c1"), text_reply("ok")],
                "make a google doc called Notes with sources from https://docs.example/page")
    (action,) = agent.actions.actions()
    assert action["args"]["body"] == "It says so [1]. Sources: [1] https://docs.example/page"


def test_the_approved_doc_is_made_with_its_text_and_sources_and_read_back_and_never_straight_away(config, world):
    agent = ask(config, [tool_reply("web_search", json.dumps({"query": "spacing"}), call_id="c1"),
                         tool_reply("propose_cited_google_doc", json.dumps({"title": "Spacing", "body": "Spacing helps [1].", "sources": "https://a.example/spaced"}), call_id="c2"), text_reply("ok")],
                "research spacing and make a google doc called Spacing with sources")
    (action,) = agent.actions.pending()
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    done = agent.actions.run(action["id"])
    assert done["status"] == "succeeded" and "read it back to check" in done["result"]
    made = [d for d in world.office.docs.values() if d["title"] == "Spacing"][0]
    assert made["text"] == "Spacing helps [1]. Sources: [1] https://a.example/spaced"
    assert "google_docs_create_cited" not in diya_autoapprove.AUTO_KINDS and gc.action_kinds()[0].auto_ok is None


def test_the_catalog_lists_it_at_level_two():
    assert diya_catalog.CATALOG["propose_cited_google_doc"].tier == 2 and diya_catalog.CATALOG["propose_cited_google_doc"].approval == "owner approves each action"
