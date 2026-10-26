"""Google Contacts: look someone up, turn a name into an address for an email, and add, change, group and delete contacts when approved (diya_google_contacts.py; DIYA-110, -111, -112, -113; docs/GOOGLE_CHANGES.md),
added 2026-10-26.

No test here reaches the real Google: a stateful stand-in People API answers, keeps every request, applies what it is sent and refuses a stale etag. What this proves: each card's list of allowed requests; a question about
one contact is answered by code (no model) and, when no one by that name is in the contacts, left to the chat; an email goes to a NAME only if exactly one contact has that name and exactly one address (two people, no
one, or two addresses refuses it and says what to ask), the card says which contact was used, and an address the person typed is still used as typed and nothing else ever is; a contact is added once (a duplicate is
refused), with only details the person typed; an address or number is added to a contact found now, against the version it was proposed at; a contact is put in or taken out of one of the person's own groups and read back;
deleting says it cannot be undone; none of it can be done straight away.
"""
import dataclasses
import json
import types

import pytest

import diya
import diya_actions
import diya_autoapprove
import diya_catalog
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_cards
import diya_google_client as client
import diya_google_contacts as gc
import diya_google_mailwrite as mw
import diya_intent_google as asks
from fakes import FakeClient, text_reply, tool_reply

PEOPLE = gc.PEOPLE
CARDS = (gc.READ, gc.CHANGE, mw.SEND, mw.DRAFTS)


def resp(status=200, body=None):
    return types.SimpleNamespace(status_code=status, headers={}, json=lambda: body if body is not None else {}, text="")


def person(rid, name, emails=(), phones=(), groups=(), etag=None):
    return {"resourceName": f"people/{rid}", "etag": etag or f"e-{rid}-1", "names": [{"displayName": name, "metadata": {"primary": True}}], "emailAddresses": [{"value": e} for e in emails],
            "phoneNumbers": [{"value": p} for p in phones], "memberships": [{"contactGroupMembership": {"contactGroupResourceName": g}} for g in groups]}


class People:
    """A stand-in People API: contacts with versions, the person's groups, and the requests Diya makes."""

    def __init__(self):
        self.people, self.requests, self.fail_status, self.next = {}, [], {}, 100
        self.groups = [{"resourceName": "contactGroups/classmates", "name": "Classmates", "groupType": "USER_CONTACT_GROUP"}, {"resourceName": "contactGroups/myContacts", "name": "myContacts", "groupType": "SYSTEM_CONTACT_GROUP"}]
        for p in (person("c1", "Maya Rao", ["maya@example.com"], ["+91 98765 43210"]), person("c2", "Sam Lee", ["sam@example.com", "sam.lee@work.example"]), person("c3", "Sam Park", ["sampark@example.com"]),
                  person("c4", "Dad", ["dad@example.com"], groups=["contactGroups/classmates"]), person("c5", "Priya"), person("c6", "Anil Rao", ["anil@example.com"])):
            self.people[p["resourceName"]] = p

    def __call__(self, *args, **kwargs):
        method, url = (args[0], args[1]) if len(args) == 2 else ("GET", args[0])
        params, body = kwargs.get("params") or {}, kwargs.get("json")
        self.requests.append((method, url, dict(params), body))
        if method in self.fail_status:
            return resp(self.fail_status[method], {"error": {"message": "backend error"}})
        tail = url[len(PEOPLE):].strip("/")
        if tail == "people/me/connections":
            return resp(200, {"connections": list(self.people.values())})
        if tail == "contactGroups":
            return resp(200, {"contactGroups": self.groups})
        if tail == "people:createContact":
            self.next += 1
            made = person(f"c{self.next}", " ".join(filter(None, [body["names"][0].get("givenName"), body["names"][0].get("familyName")])), [e["value"] for e in body.get("emailAddresses", [])], [p["value"] for p in body.get("phoneNumbers", [])])
            self.people[made["resourceName"]] = made
            return resp(200, made)
        if tail.startswith("contactGroups/") and tail.endswith("/members:modify"):
            group = "contactGroups/" + tail.split("/")[1]
            for rid in body.get("resourceNamesToAdd", []):
                self.people[rid]["memberships"].append({"contactGroupMembership": {"contactGroupResourceName": group}})
            for rid in body.get("resourceNamesToRemove", []):
                self.people[rid]["memberships"] = [m for m in self.people[rid]["memberships"] if m["contactGroupMembership"]["contactGroupResourceName"] != group]
            return resp(200, {})
        resource = tail.split(":")[0]
        found = self.people.get(resource)
        if found is None:
            return resp(404, {"error": {"message": "not found"}})
        if method == "GET":
            return resp(200, found)
        if method == "DELETE":
            del self.people[resource]
            return resp(200, {})
        if method == "PATCH":
            if body.get("etag") != found["etag"]:
                return resp(400, {"error": {"status": "FAILED_PRECONDITION", "message": "etag mismatch"}})
            for key in ("emailAddresses", "phoneNumbers"):
                if key in body:
                    found[key] = body[key]
            found["etag"] = found["etag"] + "x"
            return resp(200, found)
        return resp(400)

    def mutations(self):
        return [r for r in self.requests if r[0] in ("POST", "PUT", "DELETE", "PATCH")]


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False, lookup=False, mail=True)
    for name in CARDS:
        diya_connectors.store_token(config, name, "refresh")
    return config


@pytest.fixture
def people(monkeypatch):
    service = People()
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "tok" if name in CARDS else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return service


def agent_for(config, replies=(), kinds=None):
    return diya.Agent(config, client=FakeClient(list(replies)), action_kinds=list(kinds if kinds is not None else gc.action_kinds()))


def propose(config, message_text, tool, args, kinds=None):
    agent = agent_for(config, [tool_reply(tool, json.dumps(args)), text_reply("ok")], kinds)
    agent.ask([{"role": "user", "content": message_text}])
    return agent


def run_approved(agent):
    (action,) = agent.actions.pending()
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    return agent.actions.run(action["id"])


# ---- what each card may ask for ------------------------------------------------------------------------------------------------------------------

def test_the_read_card_reads_the_contacts_and_the_change_card_can_add_change_delete_and_group_but_not_more():
    one, many = f"{PEOPLE}/people/c1", f"{PEOPLE}/people/me/connections"
    assert client.permitted(gc.READ, "GET", many) and client.permitted(gc.READ, "GET", f"{PEOPLE}/contactGroups") and not client.permitted(gc.READ, "GET", one)
    assert not any(client.permitted(gc.READ, m, url) for m in ("POST", "PATCH", "DELETE") for url in (many, f"{PEOPLE}/people:createContact", f"{one}:updateContact", f"{one}:deleteContact"))
    assert client.permitted(gc.CHANGE, "POST", f"{PEOPLE}/people:createContact") and client.permitted(gc.CHANGE, "PATCH", f"{one}:updateContact") and client.permitted(gc.CHANGE, "DELETE", f"{one}:deleteContact")
    assert client.permitted(gc.CHANGE, "POST", f"{PEOPLE}/contactGroups/classmates/members:modify") and client.permitted(gc.CHANGE, "GET", one)
    for method, url in (("POST", f"{PEOPLE}/contactGroups"), ("DELETE", f"{PEOPLE}/contactGroups/classmates"), ("POST", f"{PEOPLE}/people:batchCreateContacts"), ("POST", f"{PEOPLE}/people:batchDeleteContacts"),
                        ("DELETE", f"{PEOPLE}/otherContacts/c1")):
        assert not client.permitted(gc.CHANGE, method, url), (method, url)


def test_both_cards_are_real_connectors_with_their_one_permission_and_are_known_to_disconnect(config):
    from diya_connector_tools import real_connectors

    made = {c.name: c for c in real_connectors(config)}
    for name, scope in gc.SCOPES.items():
        assert made[name].scope == scope and made[name].implemented and name in gcal.every_card() and name in diya_google_cards.names()
    assert made[gc.READ].scope.endswith("contacts.readonly") and made[gc.CHANGE].scope.endswith("auth/contacts")


# ---- the words that ask -------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, fn, expected", [
    ("add Maya to my contacts: maya@example.com", asks.adds_contact, True), ("add buy milk to my google tasks", asks.adds_contact, False),
    ("add a number to Maya's contact: 98765 43210", asks.updates_contact, True), ("delete Maya from my contacts", asks.deletes_contact, True), ("delete the file Old notes", asks.deletes_contact, False),
    ("put Maya in my Classmates group", asks.groups_contact, True), ("remove Sam from the family group in my contacts", asks.groups_contact, True), ("put the label Exams on the email from the bank", asks.groups_contact, False),
])
def test_each_kind_is_asked_for_only_in_its_own_words(text, fn, expected):
    assert fn(text) is expected


@pytest.mark.parametrize("text, name, what", [("what is Maya's email?", "Maya", "email"), ("whats sam's number", "sam", "number"), ("find the contact Sam", "Sam", "contact"), ("what is the contact for Maya Rao", "Maya Rao", "contact")])
def test_a_plain_question_about_one_contact_is_understood(text, name, what):
    assert gc.request(text) == {"name": name, "what": what}


@pytest.mark.parametrize("text", ["what is the weather", "what is my email address", "delete Maya from my contacts", "x" * 200])
def test_other_messages_are_not_questions_about_a_contact(text):
    assert gc.request(text) is None


# ---- looking someone up ----------------------------------------------------------------------------------------------------------------------------

def test_a_contact_is_answered_by_code_from_the_contacts(config, people):
    text, status = gc.lookup(config, {"name": "Maya", "what": "email"})
    assert status == "found" and text.startswith("Maya Rao: maya@example.com") and "which I can only read" in text
    assert gc.lookup(config, {"name": "maya", "what": "number"})[0].startswith("Maya Rao: +91 98765 43210")
    assert gc.lookup(config, {"name": "Priya", "what": "email"})[0].startswith("Priya: no email saved")


def test_two_matching_people_are_listed_and_no_one_is_chosen_and_none_is_said(config, people):
    text, status = gc.lookup(config, {"name": "Sam", "what": "email"})
    assert status == "found" and text.startswith("2 contacts match 'Sam':") and "Sam Lee: sam@example.com, sam.lee@work.example" in text and "Sam Park: sampark@example.com" in text
    assert gc.lookup(config, {"name": "Zoe", "what": "email"}) == ("No one called 'Zoe' is in your contacts.", "nothing")


def test_the_chat_answers_with_no_model_and_leaves_an_unknown_name_to_the_chat(config, people):
    agent = agent_for(config, kinds=[])
    answer, tools = agent.ask([{"role": "user", "content": "what is Maya's email?"}])
    assert answer.startswith("Maya Rao: maya@example.com") and tools == ["read_contacts"] and agent.client.chat_calls == []
    agent = agent_for(config, [text_reply("You told me Zoe's number is 12345.")], kinds=[])
    answer, tools = agent.ask([{"role": "user", "content": "what is Zoe's number?"}])
    assert answer == "You told me Zoe's number is 12345." and "read_contacts" not in tools and len(agent.client.chat_calls) == 1


def test_when_contacts_are_not_connected_the_chat_goes_on_as_before_and_nothing_is_asked_of_google(config, people):
    diya_connectors.disconnect(config, gc.READ)
    agent = agent_for(config, [text_reply("I do not know.")], kinds=[])
    answer, _ = agent.ask([{"role": "user", "content": "what is Maya's email?"}])
    assert answer == "I do not know." and people.requests == []


def test_the_catalog_lists_the_reading_as_a_private_untrusted_flow_and_no_contact_tool_exists():
    flow = diya_catalog.CATALOG["read_contacts"]
    assert flow.type == "flow" and flow.untrusted_output and "read_contacts" in diya_catalog.PRIVATE_DATA and flow.tier == 0
    assert not [n for n, e in diya_catalog.CATALOG.items() if e.type == "tool" and e.connector.startswith("google_contacts")]


# ---- an email to a name (DIYA-113) ----------------------------------------------------------------------------------------------------------------

def test_a_name_becomes_the_one_address_of_the_one_contact_and_the_card_says_so(config, people):
    agent = propose(config, "send an email to Maya saying I will be late", "propose_send_gmail", {"to": "Maya", "subject": "Late", "body": "I will be late."}, mw.action_kinds())
    (action,) = agent.actions.actions()
    assert action["args"]["to"] == "maya@example.com" and action["args"]["contacts"] == "Maya Rao, from your contacts"
    assert action["summary"] == "Send an email to maya@example.com (Maya Rao, from your contacts): 'Late'"


def test_two_people_with_the_name_no_one_or_two_addresses_refuse_the_email_and_nothing_is_recorded(config, people):
    for name in ("Sam", "Zoe", "Priya"):  # two Sams; not in the contacts; a contact with no address
        agent = propose(config, f"send an email to {name} saying hi", "propose_send_gmail", {"to": name, "subject": "Hi", "body": "Hi."}, mw.action_kinds())
        assert agent.actions.actions() == [], name
    with pytest.raises(diya_actions.InvalidArgs, match="has 2 email addresses saved"):
        gc.resolve_names(config, ["Sam Lee"], "email Sam Lee")
    with pytest.raises(diya_actions.InvalidArgs, match="2 contacts match 'Rao'"):
        gc.resolve_names(config, ["Rao"], "email Rao")


def test_a_name_the_person_did_not_say_is_never_looked_up_and_an_address_not_typed_is_never_used(config, people):
    for to in ("Anil", "anil@example.com"):  # the person said Maya
        agent = propose(config, "send an email to Maya saying hi", "propose_send_gmail", {"to": to, "subject": "Hi", "body": "Hi."}, mw.action_kinds())
        assert agent.actions.actions() == [], to
    assert people.requests == [] or all(r[0] == "GET" for r in people.requests)


def test_a_typed_address_stays_as_typed_and_names_and_addresses_can_be_mixed(config, people):
    agent = propose(config, "send an email to Maya and dad@example.com saying hi", "propose_send_gmail", {"to": "Maya, dad@example.com", "subject": "Hi", "body": "Hi."}, mw.action_kinds())
    (action,) = agent.actions.actions()
    assert action["args"]["to"] == "maya@example.com, dad@example.com"
    agent = propose(config, "send an email to maya@elsewhere.example saying hi", "propose_send_gmail", {"to": "maya@elsewhere.example", "subject": "Hi", "body": "Hi."}, mw.action_kinds())
    action = agent.actions.actions()[-1]  # (the newest: this test made two)
    assert action["args"]["to"] == "maya@elsewhere.example" and "contacts" not in action["args"]


def test_a_name_with_contacts_not_connected_is_refused_with_what_to_do(config, people):
    diya_connectors.disconnect(config, gc.READ)
    with pytest.raises(diya_actions.InvalidArgs, match="Google Contacts \\(read\\) connected"):
        gc.resolve_names(config, ["Maya"], "email Maya")
    agent = propose(config, "send an email to Maya saying hi", "propose_send_gmail", {"to": "Maya", "subject": "Hi", "body": "Hi."}, mw.action_kinds())
    assert agent.actions.actions() == []


def test_a_draft_may_name_someone_too(config, people):
    agent = propose(config, "draft an email to Maya about the exam", "propose_gmail_draft", {"to": "Maya", "subject": "The exam", "body": "Hello Maya."}, mw.action_kinds())
    (action,) = agent.actions.actions()
    assert action["args"]["to"] == "maya@example.com" and action["summary"].startswith("Save a draft email to maya@example.com (Maya Rao, from your contacts)")


# ---- add a contact -------------------------------------------------------------------------------------------------------------------------------------

def test_a_contact_is_added_with_only_what_the_person_typed_and_read_back(config, people):
    agent = propose(config, "add Zoe Khan to my contacts: zoe@example.com", "propose_add_contact", {"name": "Zoe Khan", "email": "zoe@example.com"})
    (action,) = agent.actions.actions()
    assert action["summary"] == "Add to your Google Contacts: Zoe Khan, email zoe@example.com" and people.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "Zoe Khan: zoe@example.com" in done["result"]
    (post,) = people.mutations()
    assert post[3]["names"] == [{"givenName": "Zoe", "familyName": "Khan"}] and post[3]["emailAddresses"] == [{"value": "zoe@example.com"}]


def test_a_contact_who_is_already_there_is_not_added_again_and_invented_details_are_refused(config, people):
    for said, args in (("add Maya Rao to my contacts: maya.new@example.com", {"name": "Maya Rao", "email": "maya.new@example.com"}),  # the name is there
                       ("add Anna to my contacts: anil@example.com", {"name": "Anna", "email": "anil@example.com"}),  # the address is there
                       ("add Zoe to my contacts: zoe@example.com", {"name": "Zoe", "email": "other@example.com"}),  # an address not typed
                       ("add Zoe to my contacts", {"name": "Zoe"}),  # nothing to save
                       ("add Zoe to my contacts: 98765 11111", {"name": "Zoe", "phone": "98765 22222"})):  # a number not typed
        agent = propose(config, said, "propose_add_contact", args)
        assert agent.actions.actions() == [], said
    assert people.mutations() == []


def test_a_number_the_person_typed_is_kept_as_typed(config, people):
    agent = propose(config, "add Zoe to my contacts: 98765 11111", "propose_add_contact", {"name": "Zoe", "phone": "98765 11111"})
    done = run_approved(agent)
    assert done["status"] == "succeeded" and [p["phoneNumbers"] for p in people.people.values() if p["names"][0]["displayName"] == "Zoe"] == [[{"value": "98765 11111"}]]


# ---- change a contact ----------------------------------------------------------------------------------------------------------------------------------

def test_an_address_is_added_to_a_contact_found_now_against_the_version_proposed(config, people):
    agent = propose(config, "add an email to Dad's contact: dad.work@example.com", "propose_update_contact", {"name": "Dad", "email": "dad.work@example.com"})
    (action,) = agent.actions.actions()
    assert action["args"]["resource"] == "people/c4" and action["summary"] == "Add to the contact Dad: the email dad.work@example.com"
    done = run_approved(agent)
    assert done["status"] == "succeeded" and [e["value"] for e in people.people["people/c4"]["emailAddresses"]] == ["dad@example.com", "dad.work@example.com"]
    (patch,) = people.mutations()
    assert patch[2]["updatePersonFields"] == "emailAddresses" and patch[3]["etag"] == "e-c4-1"


def test_a_contact_that_changed_since_is_not_touched_and_an_ambiguous_or_known_detail_is_refused(config, people):
    agent = propose(config, "add an email to Dad's contact: dad.work@example.com", "propose_update_contact", {"name": "Dad", "email": "dad.work@example.com"})
    people.people["people/c4"]["etag"] = "changed-elsewhere"
    done = run_approved(agent)
    assert done["status"] == "failed" and "was changed in Google Contacts after it was proposed" in done["result"] and people.mutations() == []
    before = len(agent.actions.actions())
    for said, args in (("add an email to Sam's contact: new@example.com", {"name": "Sam", "email": "new@example.com"}), ("add an email to Dad's contact: dad@example.com", {"name": "Dad", "email": "dad@example.com"}),
                       ("add an email to Dad's contact: x@example.com", {"name": "Dad", "email": "y@example.com"})):
        assert len(propose(config, said, "propose_update_contact", args).actions.actions()) == before, said


# ---- delete a contact ----------------------------------------------------------------------------------------------------------------------------------

def test_a_contact_is_deleted_after_approval_and_the_card_says_it_cannot_be_brought_back(config, people):
    agent = propose(config, "delete Anil from my contacts", "propose_delete_contact", {"name": "Anil"})
    (action,) = agent.actions.actions()
    assert "Diya cannot bring it back" in action["summary"] and people.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "people/c6" not in people.people and "Google no longer has it" in done["result"]


def test_a_delete_of_an_ambiguous_name_is_refused_and_a_delete_that_may_have_gone_is_unknown(config, people):
    assert propose(config, "delete Sam from my contacts", "propose_delete_contact", {"name": "Sam"}).actions.actions() == []
    agent = propose(config, "delete Anil from my contacts", "propose_delete_contact", {"name": "Anil"})
    people.fail_status["DELETE"] = 500
    done = run_approved(agent)
    assert done["status"] == "unknown" and len([r for r in people.requests if r[0] == "DELETE"]) == 1


# ---- groups ----------------------------------------------------------------------------------------------------------------------------------------------

def test_a_contact_is_put_in_and_taken_out_of_one_of_the_persons_own_groups_and_read_back(config, people):
    agent = propose(config, "put Maya in my Classmates group", "propose_contact_group", {"name": "Maya", "group": "Classmates", "action": "add"})
    (action,) = agent.actions.actions()
    assert action["summary"] == "Put the contact Maya Rao in your group Classmates" and action["args"]["group_id"] == "classmates"
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "contactGroups/classmates" in [m["contactGroupMembership"]["contactGroupResourceName"] for m in people.people["people/c1"]["memberships"]]
    agent = propose(config, "take Dad out of the Classmates group in my contacts", "propose_contact_group", {"name": "Dad", "group": "Classmates", "action": "remove"})
    assert run_approved(agent)["status"] == "succeeded" and people.people["people/c4"]["memberships"] == []


def test_a_group_that_does_not_exist_or_is_built_in_or_already_has_them_is_refused(config, people):
    for said, args in (("put Maya in my Family group", {"name": "Maya", "group": "Family", "action": "add"}), ("put Maya in my myContacts group", {"name": "Maya", "group": "myContacts", "action": "add"}),
                       ("put Dad in my Classmates group", {"name": "Dad", "group": "Classmates", "action": "add"}), ("remove Maya from my Classmates group", {"name": "Maya", "group": "Classmates", "action": "remove"})):
        assert propose(config, said, "propose_contact_group", args).actions.actions() == [], said
    assert not [r for r in people.requests if r[1].endswith("contactGroups") and r[0] != "GET"]


# ---- the catalog and the switches ------------------------------------------------------------------------------------------------------------

def test_every_kind_is_in_the_catalog_with_its_tier_and_none_can_be_done_straight_away():
    expected = {"propose_add_contact": 2, "propose_update_contact": 2, "propose_delete_contact": 3, "propose_contact_group": 2}
    assert {name: diya_catalog.CATALOG[name].tier for name in expected} == expected and {k.tool_name for k in gc.action_kinds()} == set(expected)
    assert not {k.name for k in gc.action_kinds()} & set(diya_autoapprove.AUTO_KINDS) and all(k.auto_ok is None for k in gc.action_kinds())
    assert all(diya_catalog.CATALOG[name].approval == "owner approves each action" for name in expected)


def test_the_models_tools_cannot_name_a_contact_id_or_a_version():
    for kind in gc.action_kinds():
        assert not set(kind.tool["function"]["parameters"]["properties"]) & {"resource", "etag", "group_id", "resourceName"}, kind.name


# ---- names for invitations and shares go through the same door ---------------------------------------------------------------------------------

def test_the_one_door_for_people_gives_typed_addresses_as_typed_and_names_as_the_one_contact(config, people):
    assert mw.people(config, "Maya, dad@example.com, Maya", "email Maya and dad@example.com") == ("maya@example.com, dad@example.com", "Maya Rao, from your contacts; Maya Rao, from your contacts")
    for wanted, said in (("Zoe", "email Zoe"), ("Sam", "email Sam"), ("stranger@example.com", "email Maya"), ("Maya", "email Dad")):
        with pytest.raises(diya_actions.InvalidArgs):
            mw.people(config, wanted, said)


def test_an_invitation_and_a_share_may_name_a_person_and_the_card_says_which_contact(config, people):
    import diya_google_calchange as cc
    import diya_google_drive as gd

    for kinds, text in ((cc.action_kinds(), "invite Maya to the study group"), (gd.action_kinds(), "share the file Notes with Maya so she can view it")):
        assert any(k.resolve is not None and k.prepare is not None for k in kinds), text
    assert cc.invite_prepare({"title": "study group", "guests": "Maya"}, "invite Maya to the study group")[0]["guests"] == "Maya"
    assert gd.share_prepare({"name": "Notes", "email": "Maya", "role": "reader"}, "share the file Notes with Maya so she can view it")[0]["email"] == "Maya"
