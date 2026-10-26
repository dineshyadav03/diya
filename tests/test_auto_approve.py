"""Do it straight away (diya_autoapprove.py; docs/ACTIONS_DESIGN.md), added 2026-10-26 on the owner's choice: the four additions that touch only the owner (an event with nobody invited, a Google task, a Drive
folder, a Google Doc) need no Approve when the owner asks for them in their own message.

What this proves, with the real approval system and stand-in Google actions: nothing is switched on by default; only those four kinds can ever be switched on, whoever asks (every other kind, and every kind that
could send, share, change or delete, is refused at the switch and at the check); a switched-on kind is approved with the hash that was recorded and run in the same turn, recorded as an approval `via` "auto" in
its own history and in the activity journal, and told in the reply with what happened; the same kind switched off waits for the owner as before; a proposal made after anything outside the owner's own message
was read waits, switched on or not; so does one made while Diya is paused; a failure is told as a failure and an unknown outcome as unknown, neither tried again; and the switch is on the Actions page and in
the API, which refuse a kind that always asks.
"""
import json

import pytest
from fastapi.testclient import TestClient

import diya
import diya_actions
import diya_autoapprove
import diya_catalog
import diya_config
import diya_connector_tools
import diya_pause
import diya_web
from diya_actions import ActionFailed, ActionUncertain
from fakes import FakeClient, task_kind, text_reply, tool_calls_reply, tool_reply
from test_actions_agent import PROPOSE, agent_with, agent_with_reads, ask

TASKS = "google_tasks_add"  # a real kind's name, on a stand-in that only records what it was asked to do


def kind(**changes):
    return task_kind(name=TASKS, **dict({"auto_ok": lambda args, said: True}, **changes))  # a fake kind that says everything in it is the owner's own words; the real kinds' checks are tested below


def proposing(title="buy milk"):
    return [tool_reply(PROPOSE, json.dumps({"title": title})), text_reply("Done! Why? To test my own system. P.S. your dog is called Hog.")]


# ---- off by default, and only four kinds can ever be switched on ----------------------------------------------------------------

def test_nothing_is_switched_on_until_the_owner_does_it():
    executed = []
    agent = agent_with(kind(executed=executed), replies=proposing())
    answer, _ = ask(agent, "add a task: buy milk")
    assert diya_autoapprove.enabled_kinds(agent.store) == [] and executed == []
    assert agent.actions.actions()[0]["status"] == "pending" and answer.startswith("Ready for your OK:")


def test_only_the_four_additions_that_touch_just_the_owner_can_be_switched_on(tmp_path):
    agent = agent_with(kind())
    for name in diya_autoapprove.AUTO_KINDS:
        assert diya_autoapprove.set_enabled(agent.store, name, True)[-1] == name or name in diya_autoapprove.enabled_kinds(agent.store)
    for refused in ("todoist_add_task", "google_mail_send", "google_calendar_delete_event", "share_file", "", "add_task"):
        with pytest.raises(ValueError):
            diya_autoapprove.set_enabled(agent.store, refused, True)
    assert diya_autoapprove.enabled_kinds(agent.store) == list(diya_autoapprove.AUTO_KINDS)


def test_the_four_are_real_kinds_that_only_add_and_sit_at_the_lowest_risk_that_writes():
    real = {k.name: k for k in diya_connector_tools.real_action_kinds()}
    assert set(diya_autoapprove.AUTO_KINDS) <= set(real)
    for name in diya_autoapprove.AUTO_KINDS:
        entry = diya_catalog.CATALOG[real[name].tool_name]
        assert entry.tier <= 2 and entry.type == "proposal" and real[name].connector.startswith("google_"), name  # nothing at the external-facing or destructive tiers
        assert not any(word in name for word in ("delete", "send", "share", "update", "move", "remove", "mail")), name
    assert "todoist_add_task" not in diya_autoapprove.AUTO_KINDS  # Todoist was never tried against a real account: it asks


# ---- what happens when one is switched on -------------------------------------------------------------------------------------------

def test_a_switched_on_kind_is_approved_with_its_recorded_hash_run_in_the_same_turn_and_told_by_code():
    executed = []
    agent = agent_with(kind(executed=executed, reply="Added to your Google Tasks and read back to check: buy milk. https://tasks.google.com/x"), replies=proposing())
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    answer, _ = ask(agent, "add a task: buy milk", thread_id=3, message_id=7)
    (action,) = agent.actions.actions()
    assert executed == [{"title": "buy milk"}] and action["status"] == "succeeded"
    assert answer == "Done: Add the task 'buy milk'. Added to your Google Tasks and read back to check: buy milk. https://tasks.google.com/x"  # the code's words: no "Why?", no pet, no offer
    events = [(event, actor, json.loads(detail) if detail else None) for event, actor, _at, detail in agent.actions.events(action["id"])]
    assert [e[0] for e in events] == ["proposed", "approved", "executing", "succeeded"] and events[1] == ("approved", "owner", {"via": "auto"})
    latest = [row["tool"] for row in agent.store.journal_recent(limit=6)]
    assert f"approved:{TASKS}" in latest and "auto_approve_on" in latest  # what was done, and that the switch was turned on, are both on record


def test_switched_off_again_it_waits_for_the_owner_as_before():
    executed = []
    agent = agent_with(kind(executed=executed), replies=proposing())
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    diya_autoapprove.set_enabled(agent.store, TASKS, False)
    answer, _ = ask(agent, "add a task: buy milk")
    assert executed == [] and agent.actions.actions()[0]["status"] == "pending" and answer.startswith("Ready for your OK:")


def test_a_proposal_made_after_reading_something_that_is_not_the_owners_still_waits():
    executed = []
    replies = [tool_reply("search_notes", '{"query": "milk"}'), tool_reply(PROPOSE, '{"title": "buy milk"}'), text_reply("ok")]
    agent = agent_with_reads(kind(executed=executed), replies=replies)
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    answer, _ = ask(agent, "add a task: buy milk")
    (action,) = agent.actions.actions()
    assert action["tainted"] is True and action["status"] == "pending" and executed == [] and answer.startswith("Ready for your OK:")


def test_while_paused_nothing_is_done_and_the_proposal_waits():
    executed = []
    agent = agent_with(kind(executed=executed), replies=proposing())
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    diya_pause.pause(agent.store, "testing")
    answer, _ = ask(agent, "add a task: buy milk")
    assert executed == [] and agent.actions.actions()[0]["status"] == "pending" and answer.startswith("Ready for your OK:")


def test_a_message_that_did_not_ask_for_it_proposes_nothing_so_nothing_is_done():
    executed = []
    agent = agent_with(kind(executed=executed, asked=lambda text: "add a task" in text.lower()), replies=[tool_reply(PROPOSE, '{"title": "buy milk"}'), text_reply("ok")])
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    ask(agent, "I need to buy milk")
    assert executed == [] and agent.actions.actions() == []


def test_a_kind_that_is_not_one_of_the_four_waits_even_when_the_database_says_otherwise():
    executed = []
    agent = agent_with(task_kind(name="todoist_add_task", executed=executed), replies=proposing())
    conn = agent.store.connect()
    conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", ("auto_approve:todoist_add_task", "2026-10-26T00:00:00+00:00"))  # forced into the table by hand
    conn.commit()
    conn.close()
    ask(agent, "add a task: buy milk")
    assert executed == [] and agent.actions.actions()[0]["status"] == "pending"


def test_a_failure_is_told_as_a_failure_and_an_unknown_outcome_as_unknown_and_neither_is_run_again():
    failing = []
    agent = agent_with(kind(executed=failing, raises=ActionFailed("Google refused: the Tasks API is not switched on.")), replies=proposing())
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    answer, _ = ask(agent, "add a task: buy milk")
    assert answer == "Not done: Add the task 'buy milk'. Google refused: the Tasks API is not switched on." and agent.actions.actions()[0]["status"] == "failed" and len(failing) == 1
    unknown = []
    other = agent_with(kind(executed=unknown, raises=ActionUncertain("Google did not answer.")), replies=proposing())
    diya_autoapprove.set_enabled(other.store, TASKS, True)
    said, _ = ask(other, "add a task: buy milk")
    assert said.startswith("Not sure it was done: Add the task 'buy milk'. Google did not answer.") and "will not be tried again" in said
    assert other.actions.actions()[-1]["status"] == "unknown" and len(unknown) == 1  # (both agents share the test's one database: the newest action is this one)


def test_one_done_and_one_waiting_are_both_told():
    done, waiting = [], []
    agent = agent_with(kind(executed=done), task_kind(name="todoist_add_task", tool_name="propose_other", executed=waiting),
                       replies=[tool_calls_reply((PROPOSE, '{"title": "a"}'), ("propose_other", '{"title": "b"}')), text_reply("ok")])
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    answer, _ = ask(agent, "add a task: a, and add a task: b")
    assert done == [{"title": "a"}] and waiting == []
    assert answer.startswith("Done: Add the task 'a'. created task 1\n\nReady for your OK: Add the task 'b'.") and "press Approve" in answer


# ---- the switch in the API and on the page -----------------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    import dataclasses

    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "a.db"), profile_path=str(tmp_path / "p.txt"), connector_tokens_dir=str(tmp_path / "tok"),
                                 connectors_log_path=str(tmp_path / "l"), protect_secrets=False, require_token=False)
    return TestClient(diya_web.create_app(config, diya.Agent(config, client=FakeClient()), object()), base_url="https://localhost")


def kinds_of(client):
    return {k["name"]: k for k in client.get("/api/actions").json()["kinds"]}


def test_the_list_says_which_kinds_can_be_switched_and_which_are(client):
    found = kinds_of(client)
    assert {name for name, k in found.items() if k["can_auto"]} == set(diya_autoapprove.AUTO_KINDS) and not any(k["auto"] for k in found.values())
    assert found["todoist_add_task"]["can_auto"] is False


def test_the_route_switches_a_kind_on_and_off_and_answers_with_the_list(client):
    on = client.post("/api/actions/auto", json={"kind": "google_docs_create", "on": True})
    assert on.status_code == 200 and {k["name"]: k["auto"] for k in on.json()["kinds"]}["google_docs_create"] is True and kinds_of(client)["google_docs_create"]["auto"] is True
    off = client.post("/api/actions/auto", json={"kind": "google_docs_create", "on": False})
    assert off.status_code == 200 and kinds_of(client)["google_docs_create"]["auto"] is False


@pytest.mark.parametrize("body, status", [
    ({"kind": "todoist_add_task", "on": True}, 409), ({"kind": "nothing_like_it", "on": True}, 404), ({"kind": "google_docs_create", "on": "yes"}, 422), ({"kind": "google_docs_create"}, 422), ({}, 422),
])
def test_the_route_refuses_a_kind_that_always_asks_one_that_is_not_there_and_a_bad_body(client, body, status):
    assert client.post("/api/actions/auto", json=body).status_code == status
    assert kinds_of(client)["google_docs_create"]["auto"] is False and kinds_of(client)["todoist_add_task"]["auto"] is False


def test_only_post_exists_for_it(client):
    assert client.get("/api/actions/auto").status_code in (404, 405, 422) and client.put("/api/actions/auto", json={"kind": "google_docs_create", "on": True}).status_code == 405


def test_the_actions_page_has_the_switches_and_says_the_one_exception():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    page = (root / "frontend" / "app" / "actions" / "page.js").read_text(encoding="utf-8")
    assert "Do straight away" in page and "fetch('/api/actions/auto'" in page and "kind.can_auto" in page and "aria-label={`${kind.auto ? 'Switch off' : 'Switch on'} doing it straight away" in page
    assert "The only exception is a kind you switch to" in page
    route = root / "frontend" / "app" / "api" / "actions" / "auto" / "route.js"
    assert route.exists() and "'/api/actions/auto'" in route.read_text(encoding="utf-8") and "force-dynamic" in route.read_text(encoding="utf-8")


# ---- only what is made of the owner's own words ----------------------------------------------------------------------------------------------

def test_a_kind_without_its_own_check_is_never_done_straight_away_even_when_switched_on():
    executed = []
    agent = agent_with(task_kind(name=TASKS, executed=executed), replies=proposing())  # no auto_ok
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    ask(agent, "add a task: buy milk")
    assert executed == [] and agent.actions.actions()[0]["status"] == "pending"


def test_a_check_that_says_no_or_fails_sends_the_proposal_to_the_owners_approve():
    for check, title in ((lambda args, said: False, "buy milk"), (lambda args, said: 1 / 0, "buy eggs")):  # a different title each time: the two agents share the test's one database, and a copy of a waiting action is refused
        executed = []
        agent = agent_with(kind(executed=executed, auto_ok=check), replies=proposing(title))
        diya_autoapprove.set_enabled(agent.store, TASKS, True)
        answer, _ = ask(agent, f"add a task: {title}")
        assert executed == [] and agent.actions.actions()[-1]["status"] == "pending" and answer.startswith("Ready for your OK:")


def test_the_check_is_given_what_was_proposed_and_what_the_owner_wrote():
    seen = []
    agent = agent_with(kind(auto_ok=lambda args, said: seen.append((dict(args), said)) or True), replies=proposing())
    diya_autoapprove.set_enabled(agent.store, TASKS, True)
    ask(agent, "add a task: buy milk")
    assert seen == [({"title": "buy milk"}, "add a task: buy milk")]


import diya_google_write as gw

EVENT_SAID = "put 'Diya smoke test' on my calendar tomorrow at 5pm for 30 minutes"


@pytest.mark.parametrize("args, said, expected", [
    ({"title": "Diya smoke test", "when": "tomorrow at 5pm", "start": "2026-10-27T11:30:00Z", "duration_minutes": 30}, EVENT_SAID, True),
    ({"title": "Diya smoke test (a test of my system)", "when": "tomorrow at 5pm", "start": "2026-10-27T11:30:00Z"}, EVENT_SAID, False),  # a title the model made longer
    ({"title": "Dentist", "when": "tomorrow", "start": "2026-10-27T03:30:00Z"}, "put the dentist on my calendar tomorrow", False),  # no time of day was said: 9am was filled in, so the owner looks first
    ({"title": "Dentist", "when": "tomorrow morning", "start": "2026-10-27T03:30:00Z"}, "put the dentist on my calendar tomorrow morning", False),  # "morning" is filled in as an hour
    ({"title": "Dentist", "start": "2026-10-27T03:30:00Z"}, "put the dentist on my calendar", False),  # no words for the time at all
])
def test_an_event_is_done_straight_away_only_if_the_title_and_the_time_are_the_owners_own(args, said, expected):
    assert gw.event_auto_ok(args, said) is expected


@pytest.mark.parametrize("check, args, said, expected", [
    (gw.task_auto_ok, {"title": "buy milk"}, "add a Google task: buy milk", True),
    (gw.task_auto_ok, {"title": "buy milk", "notes": "from the shop on the corner"}, "add a Google task: buy milk, from the shop on the corner", True),
    (gw.task_auto_ok, {"title": "buy milk", "notes": "A quick check to make sure I am working"}, "add a Google task: buy milk", False),
    (gw.task_auto_ok, {"title": "Purchase milk"}, "add a Google task: buy milk", False),
    (gw.folder_auto_ok, {"name": "Diya smoke test"}, "make a Drive folder called Diya smoke test", True),
    (gw.folder_auto_ok, {"name": "Diya smoke test folder"}, "make a Drive folder called Diya smoke test", False),
    (gw.doc_auto_ok, {"title": "Diya smoke test", "body": "hello"}, "make a Google Doc called Diya smoke test with the line hello", True),
    (gw.doc_auto_ok, {"title": "Diya smoke test"}, "make a Google Doc called Diya smoke test", True),
    (gw.doc_auto_ok, {"title": "Diya smoke test", "body": "This document was made to test Diya."}, "make a Google Doc called Diya smoke test", False),
    (gw.folder_auto_ok, {"name": 5}, "make a Drive folder called 5", False),
])
def test_a_title_a_name_or_a_line_the_model_made_up_is_not_done_straight_away(check, args, said, expected):
    assert check(args, said) is expected


def test_every_kind_that_can_be_switched_on_has_such_a_check_and_a_made_up_task_note_is_dropped():
    real = {k.name: k for k in diya_connector_tools.real_action_kinds()}
    assert all(real[name].auto_ok is not None for name in diya_autoapprove.AUTO_KINDS)
    assert gw.task_prepare({"title": "buy milk", "notes": "A quick check to make sure I'm working."}, "add a Google task: buy milk") == ({"title": "buy milk"}, [])
    assert gw.task_prepare({"title": "buy milk", "notes": "from the corner shop"}, "add a Google task: buy milk from the corner shop")[0]["notes"] == "from the corner shop"


def test_a_real_run_of_the_action_summary_is_what_the_owner_would_have_approved():
    action = {"summary": "Add the task 'x'", "status": "succeeded", "result": None}
    assert diya_actions.proposal_reply([], [action]) == "Done: Add the task 'x'."
    assert diya_actions.proposal_reply([], [{**action, "status": "failed", "result": None}]) == "Not done: Add the task 'x'. It did not run."
