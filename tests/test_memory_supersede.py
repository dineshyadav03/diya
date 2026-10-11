"""Replacing a fact the person says is out of date (docs/AUTO_MEMORY_DESIGN.md, D4 and unit A3): `Memory.supersede`, the route that carries it, and the
button on the Memory page.

What this proves: the waiting fact is accepted and the accepted one retired together or not at all; each says in its own event which fact it replaced or
was replaced by; every refusal (the same fact, a fact that is not there, a candidate that is not waiting, an old fact that is not accepted, a duplicate,
no room) changes nothing at all; the room the old fact frees counts; the question's own flag is cleared; the old fact can be remembered again; what the
person took back counts for the circuit breaker; and the page offers the button only when the API says a waiting fact may replace one that is still known.
"""
import dataclasses
import json
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import diya
import diya_autonomy
import diya_config
import diya_memory
import diya_web
from diya_db import Store
from diya_memory import FactError, IllegalTransition, Memory, UnknownFact
from fakes import FakeClient, text_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "app" / "memory" / "page.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
STAGED_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def memory(tmp_path):
    return Memory(Store(str(tmp_path / "s.db")))


def waiting(memory, text, flags=(), position=0, person=None):
    fact_id = memory.add_candidate(text, batch_first=1, batch_last=1, position=position, model="m", extracted_at=STAGED_AT, raw="- " + text, person=person)
    if flags:
        memory.set_flags(fact_id, list(flags), "system")
    return fact_id


def events(memory, fact_id):
    return [(event, actor, json.loads(detail) if detail else None) for event, actor, _, detail in memory.events(fact_id)]


def snapshot(memory):
    return [(f["id"], f["status"], f["flags"]) for f in memory.facts()], [memory.events(f["id"]) for f in memory.facts()]


# --- the store ------------------------------------------------------------------------------------------------------------

def test_the_waiting_fact_is_accepted_and_the_old_one_retired_together(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse", flags=[f"ask:conflict:replaces:{old}"])
    memory.supersede(new, old, "api")
    assert memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "retired"
    assert memory.accepted_texts() == ["works as a nurse"] and memory.verify_integrity() == []


def test_each_events_detail_names_the_other_fact_and_who_did_it(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse", flags=[f"ask:conflict:replaces:{old}"])
    memory.supersede(new, old, "api")
    assert events(memory, old)[-1] == ("retired", "api", {"replaced_by": new})
    assert events(memory, new)[-1] == ("accepted", "api", {"replaces": old})


def test_the_questions_own_flag_is_cleared_and_the_other_notes_stay(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse", flags=["source_message:1", f"ask:conflict:replaces:{old}"])
    memory.supersede(new, old, "api")
    assert memory.get(new)["flags"] == ["source_message:1"]
    flagged = [e for e in events(memory, new) if e[0] == "flagged"]
    assert [e[0] for e in events(memory, new)][-2:] == ["flagged", "accepted"] and len(flagged) == 2  # the one that put the question there, and the one that took it off
    assert flagged[-1][2] == {"from": ["source_message:1", f"ask:conflict:replaces:{old}"], "to": ["source_message:1"]}


def test_a_fact_with_no_question_flag_gets_no_flagged_event(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "api")
    assert "flagged" not in [e[0] for e in events(memory, new)]


def test_the_old_fact_can_be_remembered_again_once_there_is_room_for_it(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "api")
    memory.decide(old, "restore", "api")
    assert sorted(memory.accepted_texts()) == ["works as a nurse", "works as a teacher"]


@pytest.mark.parametrize("actor", ["cli", "api", "system", "auto", "import"])
def test_any_known_actor_may_do_it_and_is_the_one_recorded(memory, actor):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, actor)
    assert events(memory, new)[-1][1] == actor and events(memory, old)[-1][1] == actor


def test_an_unknown_actor_is_refused_and_nothing_changes(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    before = snapshot(memory)
    with pytest.raises(ValueError):
        memory.supersede(new, old, "a stranger")
    assert snapshot(memory) == before


def test_a_fact_cannot_replace_itself(memory):
    old = memory.add_manual("works as a teacher", "api")
    before = snapshot(memory)
    with pytest.raises(IllegalTransition, match="itself"):
        memory.supersede(old, old, "api")
    assert snapshot(memory) == before


@pytest.mark.parametrize("which", ["new", "old"])
def test_a_fact_that_is_not_there_is_refused_and_nothing_changes(memory, which):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    before = snapshot(memory)
    with pytest.raises(UnknownFact):
        memory.supersede(9999 if which == "new" else new, old if which == "new" else 9999, "api")
    assert snapshot(memory) == before


@pytest.mark.parametrize("decision", ["reject", "accept"])
def test_only_a_waiting_fact_can_replace_another(memory, decision):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.decide(new, decision, "api")
    before = snapshot(memory)
    with pytest.raises(IllegalTransition, match="only a candidate can replace"):
        memory.supersede(new, old, "api")
    assert snapshot(memory) == before


@pytest.mark.parametrize("retire_it, message", [(True, "only an accepted fact can be replaced")])
def test_only_an_accepted_fact_can_be_replaced(memory, retire_it, message):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.decide(old, "retire", "api")
    before = snapshot(memory)
    with pytest.raises(IllegalTransition, match=message):
        memory.supersede(new, old, "api")
    assert snapshot(memory) == before


def test_a_waiting_fact_cannot_be_replaced_by_another_waiting_one(memory):
    first = waiting(memory, "works as a teacher")
    second = waiting(memory, "works as a nurse", position=1)
    before = snapshot(memory)
    with pytest.raises(IllegalTransition, match="only an accepted fact can be replaced"):
        memory.supersede(second, first, "api")
    assert snapshot(memory) == before


def test_a_fact_that_repeats_another_accepted_one_is_refused_whole(memory):
    old = memory.add_manual("works as a teacher", "api")
    memory.add_manual("works as a nurse", "api")
    new = waiting(memory, "works as a nurse")
    before = snapshot(memory)
    with pytest.raises(diya_memory.DuplicateFact):
        memory.supersede(new, old, "api")
    assert snapshot(memory) == before and memory.get(old)["status"] == "accepted"


def test_the_room_the_old_fact_frees_counts_and_a_fact_that_still_does_not_fit_changes_nothing(memory):
    big = "x" * 190
    old = memory.add_manual(big, "api")
    for n in range(9):
        memory.add_manual(f"{n} " + "y" * 190, "api")  # nine more, nearly 2,000 characters in all
    new = waiting(memory, "z" * 190)
    memory.supersede(new, old, "api")  # the same size as the one it replaces: it fits
    assert memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "retired"
    too_big = waiting(memory, "w" * 200, position=1)
    victim = memory.add_manual("a short one", "api")
    before = snapshot(memory)
    with pytest.raises(diya_memory.BudgetExceeded):
        memory.supersede(too_big, victim, "api")
    assert snapshot(memory) == before


def test_the_room_check_counts_the_label_a_named_persons_fact_carries(memory):
    victim = memory.add_manual("a short one", "api")
    for n in range(9):
        memory.add_manual(f"{n} " + "y" * 190, "api")
    kept = [(text, None) for text in memory.accepted_texts() if text != "a short one"]  # what is left once the short one is gone
    filler = diya_memory.MAX_PROFILE_CHARS - len(diya_memory.render_grouped(kept + [("z" * 100, None)])) - len("\n- ")
    assert 1 <= filler <= diya_memory.MAX_FACT_CHARS
    memory.add_manual("f" * filler, "api")  # now a plain 100-character fact fills the profile exactly, and a named person's would not fit
    kept += [("f" * filler, None)]
    assert len(diya_memory.render_grouped(kept + [("z" * 100, None)])) == diya_memory.MAX_PROFILE_CHARS
    assert len(diya_memory.render_grouped(kept + [("z" * 100, "Maya")])) > diya_memory.MAX_PROFILE_CHARS  # the label is what tips it over
    named = waiting(memory, "z" * 100, person="Maya")
    plain = waiting(memory, "z" * 100, position=1)
    before = snapshot(memory)
    with pytest.raises(diya_memory.BudgetExceeded):
        memory.supersede(named, victim, "api")
    assert snapshot(memory) == before
    memory.supersede(plain, victim, "api")
    assert memory.get(plain)["status"] == "accepted"


def test_a_fact_over_the_length_limit_is_refused_whole(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "q" * (diya_memory.MAX_FACT_CHARS + 1))
    before = snapshot(memory)
    with pytest.raises(diya_memory.InvalidFact):
        memory.supersede(new, old, "api")
    assert snapshot(memory) == before


def test_what_it_says_about_a_named_person_is_replaced_like_any_other_fact(memory):
    old = memory.add_manual("lives in Mumbai", "api")
    memory.set_person(old, "Maya", "api")
    new = waiting(memory, "lives in Dubai", person="Maya")
    memory.supersede(new, old, "api")
    assert memory.get(new)["person"] == "Maya" and memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "retired"


def test_a_person_replacing_what_diya_took_on_its_own_counts_toward_the_breaker(memory):
    old = memory.add_manual("works as a teacher", "api")
    memory.decide(old, "retire", "api")
    own = waiting(memory, "likes tea")
    memory.decide(own, "accept", "auto")
    new = waiting(memory, "likes coffee", position=1)
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert memory.taken_back_count(since) == 0
    memory.supersede(new, own, "api")
    assert memory.taken_back_count(since) == 1


def test_the_flag_helper_reads_the_policys_flag_and_nothing_else():
    assert diya_memory.replaced_fact_id(["source_message:3", "ask:conflict:replaces:12"]) == 12
    for flags in ([], ["ask:conflict:replaces_unclear"], ["ask:conflict:replaces:x"], ["ask:conflict:replaces:"], ["ask:doubt:replaces:4"], ["replaces:4"], ["ask:conflict:similar:4"]):
        assert diya_memory.replaced_fact_id(flags) is None, flags


# --- what the policy leaves behind is what this answers -------------------------------------------------------------------

def test_a_fact_the_policy_held_back_as_a_replacement_is_answered_by_replacing(tmp_path):
    store = Store(str(tmp_path / "policy.db"))
    memory = Memory(store)
    message = store.add_message(store.create_thread(), "user", "I now work as a nurse")
    old = memory.add_manual("works as a teacher", "api")
    new = memory.add_candidate("works as a nurse", batch_first=message, batch_last=message, position=message, model="m", extracted_at=STAGED_AT, raw="- works as a nurse")
    diya_autonomy.apply(memory, replaces=lambda fact: diya_autonomy.Replacement("replaces", old))
    assert diya_memory.replaced_fact_id(memory.get(new)["flags"]) == old and memory.get(new)["status"] == "candidate"
    memory.supersede(new, diya_memory.replaced_fact_id(memory.get(new)["flags"]), "api")
    assert memory.accepted_texts() == ["works as a nurse"]


# --- the route ------------------------------------------------------------------------------------------------------------

@pytest.fixture
def parts(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(diya_config.load_config(), db_path=str(data / "api.db"), profile_path=str(data / "p.txt"), dream_state_path=str(data / "s.json"),
                                 dream_log_path=str(data / "l"), dream_pending_path=str(data / "p.jsonl"), require_token=False)
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 5))
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    return client, Memory(agent.store)


def test_the_route_replaces_and_returns_both_facts_and_the_summary(parts):
    client, memory = parts
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse", flags=[f"ask:conflict:replaces:{old}"])
    response = client.post(f"/api/memory/{new}/replace", json={"old_id": old})
    body = response.json()
    assert response.status_code == 200
    assert body["fact"]["id"] == new and body["fact"]["status"] == "accepted" and body["replaced"]["id"] == old and body["replaced"]["status"] == "retired"
    assert body["summary"]["counts"]["accepted"] == 1 and memory.verify_integrity() == []


def test_the_route_records_the_person_at_the_page_as_the_one_who_did_it(parts):
    client, memory = parts
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    client.post(f"/api/memory/{new}/replace", json={"old_id": old})
    assert events(memory, new)[-1][1] == "api" and events(memory, old)[-1][1] == "api"


def test_after_replacing_the_other_waiting_facts_are_checked_against_what_is_now_known(parts):
    client, memory = parts
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    twin = waiting(memory, "works as a nurse", position=1)
    assert not any(flag.startswith("duplicate:") for flag in memory.get(twin)["flags"])
    client.post(f"/api/memory/{new}/replace", json={"old_id": old})
    assert f"duplicate:{new}" in memory.get(twin)["flags"]  # it says the same as the fact that was just accepted


def test_a_waiting_fact_says_which_fact_it_may_replace_and_an_accepted_one_does_not(parts):
    client, memory = parts
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse", flags=[f"ask:conflict:replaces:{old}"])
    facts = {f["id"]: f for f in client.get("/api/memory").json()["facts"]}
    assert facts[new]["replaces"] == old and facts[old]["replaces"] is None
    memory.decide(new, "accept", "api")
    assert {f["id"]: f for f in client.get("/api/memory").json()["facts"]}[new]["replaces"] is None  # settled: nothing left to replace


@pytest.mark.parametrize("path_id, body, status, reason", [
    (9999, {"old_id": 1}, 404, "there is no fact 9999"),
    (2, {"old_id": 9999}, 404, "there is no fact 9999"),
    (2, {"old_id": 2}, 409, "itself"),
    (1, {"old_id": 2}, 409, "only a candidate can replace"),
    (0, {"old_id": 1}, 404, "there is no fact 0"),
    (2, {"old_id": 0}, 404, "there is no fact 0"),
    (2, {"old_id": -1}, 404, "there is no fact -1"),
    (2, {"old_id": 2**63}, 404, "there is no fact"),
    (2**63, {"old_id": 1}, 404, "there is no fact"),
])
def test_a_refusal_has_the_right_status_and_a_reason_and_changes_nothing(parts, path_id, body, status, reason):
    client, memory = parts
    memory.add_manual("works as a teacher", "api")  # fact 1, accepted
    waiting(memory, "works as a nurse")  # fact 2, waiting
    before = snapshot(memory)
    response = client.post(f"/api/memory/{path_id}/replace", json=body)
    assert response.status_code == status and reason in response.json()["detail"]
    assert snapshot(memory) == before


@pytest.mark.parametrize("body", [{}, {"old_id": "one"}, {"old_id": None}, {"old_id": 1.5}, {"other": 1}])
def test_a_body_that_does_not_name_a_fact_is_refused_before_anything_happens(parts, body):
    client, memory = parts
    memory.add_manual("works as a teacher", "api")
    waiting(memory, "works as a nurse")
    before = snapshot(memory)
    assert client.post("/api/memory/2/replace", json=body).status_code == 422
    assert snapshot(memory) == before


def test_a_replace_with_no_body_at_all_is_refused(parts):
    client, memory = parts
    assert client.post("/api/memory/2/replace").status_code == 422


def test_the_route_needs_the_access_token_like_every_other(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(diya_config.load_config(), db_path=str(data / "t.db"), profile_path=str(data / "p.txt"), dream_state_path=str(data / "s.json"),
                                 dream_log_path=str(data / "l"), dream_pending_path=str(data / "p.jsonl"), token_path=str(data / "token.hash"), require_token=True)
    agent = diya.Agent(config, client=FakeClient([]))
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    memory = Memory(agent.store)
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    assert client.post(f"/api/memory/{new}/replace", json={"old_id": old}).status_code == 401
    assert memory.get(new)["status"] == "candidate" and memory.get(old)["status"] == "accepted"


def test_the_generic_action_route_still_does_not_know_replace_as_an_action():
    assert "replace" not in diya_memory.ACTIONS


# --- the page -------------------------------------------------------------------------------------------------------------

def test_the_replace_route_has_its_own_proxy_file_and_is_not_one_of_the_plain_actions():
    proxy = (ROOT / "frontend" / "lib" / "proxy.mjs").read_text(encoding="utf-8")
    route = (ROOT / "frontend" / "app" / "api" / "memory" / "[fact_id]" / "replace" / "route.js").read_text(encoding="utf-8")
    assert "new Set(['accept', 'reject', 'reopen', 'retire', 'restore', 'edit'])" in proxy  # the plain actions are the ones the API has, unchanged
    assert "export const POST = (request, context) => forwardFactReplace(request, context)" in route and "force-dynamic" in route
    assert "export const GET" not in route


def test_the_page_offers_to_replace_only_when_the_api_names_a_fact_that_is_still_known():
    assert "const replacedBy = (fact) => (fact.replaces ? accepted.find((other) => other.id === fact.replaces) : undefined)" in PAGE
    assert "{replacedBy(fact) && button('Replace the old one'" in PAGE
    assert "{fact.status === 'candidate' && replacedBy(fact) && (" in PAGE and "It may replace: <q>{replacedBy(fact).text}</q>" in PAGE


def test_the_page_asks_the_route_for_exactly_the_replacement_it_shows():
    block = PAGE[PAGE.index("const replace = (fact, old) =>"):PAGE.index("const decide = (fact, action, note) =>")]
    assert "`/api/memory/${fact.id}/replace`" in block and "method: 'POST'" in block and "JSON.stringify({ old_id: old.id })" in block
    assert "'Content-Type': 'application/json'" in block and "Replaced." in block


def test_keeping_both_is_the_ordinary_accept_and_the_buttons_do_not_change_for_a_fact_that_replaces_nothing():
    assert "button(replacedBy(fact) ? 'Keep both' : 'Accept', replacedBy(fact) ? '' : 'memory-btn--primary', () => decide(fact, 'accept'" in PAGE
    assert "button('Edit'" in PAGE and "button('Reject'" in PAGE
    assert PAGE.count("'retire'") == 2  # replacing retires on the server, in the one transaction: the page adds no retirement of its own


def test_the_new_class_exists_and_uses_only_the_themes_variables():
    line = next(l for l in CSS.splitlines() if l.startswith(".memory-replaces"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", line)
