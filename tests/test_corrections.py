"""Saying so: a correction replaces what is known, and "forget that" forgets (docs/AUTO_MEMORY_DESIGN.md, D4 and D7; units A3 and A4): the two detectors in
diya_intent, Memory.undo_replace and learned_from, the policy's `corrects`, Dreamer.capture_message for both, the routes, and the chat's answer.

What this proves: a fact replaces a known one WITHOUT a question only when the person's own words correct something AND the model has named the fact it
replaces (either alone still asks); a replacement can be taken back as one act, and a refused undo changes nothing; "forget that ..." retires only a fact
that stands clearly above the others, "forget everything about <person>" retires that person's facts by name, and neither deletes anything; the line
under a reply says what is still true, and never puts the words of something left waiting (which may be private) in a line.
"""
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

import diya
import diya_autonomy as auto
import diya_config
import diya_intent
import diya_memory
import diya_web
import dreaming
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient, FakeClient, text_reply

STAGED_AT = "2026-10-11T00:00:00+00:00"


# --- the two detectors ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "no, I live in Pune", "No. I work at a bank now", "nope, it's Tuesday", "nah I don't", "actually I live in Pune", "I live in Pune actually",
    "that's wrong, I work at a bank", "That is not right: I have two cats", "that’s outdated", "I don't drink tea any more", "I don't drink tea anymore",
    "I no longer live in Delhi", "I'm not working there any longer", "I stopped playing badminton", "I quit teaching", "I gave up the guitar", "I sold the Honda",
    "I moved to Pune last month", "I switched to coffee", "I changed my phone", "I left the school", "I used to live in Delhi", "I now work as a nurse",
    "I now live in Pune", "we now have three cats", "the old Android is gone", "I moved flats and now live in Chennai.",
])
def test_the_words_people_use_to_change_something_are_read_as_a_correction(text):
    assert diya_intent.is_correction(text) is True


@pytest.mark.parametrize("text", [
    "", "   ", "I like tea in the morning", "I live in Pune", "my cat is called Pixel", "I started learning the violin", "I play football on Saturdays",
    "I'm learning to play the guitar", "do you know if I moved?", "should I switch to coffee?", "what changed?", "I work at a bank", "now", "I know a nurse",
    "my sister lives in Mumbai", None, 5, ["no, I live in Pune"],
])
def test_a_plain_statement_a_question_or_anything_else_is_not_a_correction(text):
    assert diya_intent.is_correction(text) is False


@pytest.mark.parametrize("text, target", [
    ("forget that I like tea", ("fact", "I like tea")), ("Forget everything about Maya", ("person", "Maya")), ("please forget about my old address", ("fact", "my old address")),
    ("forget what I said about the dentist", ("fact", "the dentist")), ("forget what I told you about my sister", ("fact", "my sister")),
    ("stop remembering that I like tea", ("fact", "that I like tea".replace("that ", ""))), ("delete everything about my sister Maya", ("person", "my sister Maya")),
    ("forget all about Maya.", ("person", "Maya")), ("  forget that I like tea!  ", ("fact", "I like tea")), ("forget what you know about Maya", ("person", "Maya")),
    ("FORGET THAT I LIKE TEA", ("fact", "I LIKE TEA")), ("forget that I like tea’s taste", ("fact", "I like tea's taste")),
])
def test_a_request_to_forget_says_what_is_to_be_forgotten(text, target):
    assert diya_intent.forget_target(text) == target


@pytest.mark.parametrize("text", [
    "", "forget it?", "should I forget that?", "I forgot my keys", "don't forget the milk", "remember that I like tea", "forgetful people", "forget", "forget  ",
    "forget everything about a b c d e", "x" * 401, None, 7, ["forget that"],
])
def test_anything_else_is_not_a_request_to_forget(text):
    assert diya_intent.forget_target(text) is None


# --- the memory: replacing, taking it back, and what to say about a message -----------------------------------------------------

@pytest.fixture
def memory(tmp_path):
    return Memory(Store(str(tmp_path / "c.db")))


def said_in(memory, text):
    """A message of the person's, so that a fact taken from it has something real to be grounded in."""
    store = memory.store
    threads = store.list_threads()
    return store.add_message(threads[0][0] if threads else store.create_thread(), "user", text)


def waiting(memory, text, flags=(), position=0, person=None, message=None):
    """A candidate taken from `message` (a new message saying exactly this, unless one is given)."""
    message = said_in(memory, text) if message is None else message
    fact_id = memory.add_candidate(text, batch_first=message, batch_last=message, position=position, model="m", extracted_at=STAGED_AT, raw="- " + text, person=person)
    memory.set_flags(fact_id, [f"source_message:{message}", *flags], "system")
    return fact_id


def events(memory, fact_id):
    return [(event, actor, json.loads(detail) if detail else None) for event, actor, _, detail in memory.events(fact_id)]


def test_a_reason_given_to_supersede_is_kept_beside_the_fact_it_replaced(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto", why={"lane": "remember", "reasons": ["correction"]})
    assert events(memory, new)[-1] == ("accepted", "auto", {"lane": "remember", "reasons": ["correction"], "replaces": old})


def test_without_a_reason_the_event_is_what_it_was(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "api")
    assert events(memory, new)[-1] == ("accepted", "api", {"replaces": old})


def test_what_a_fact_replaced_is_read_from_the_trail(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    other = memory.add_manual("likes tea", "api")
    assert memory.replaced(new) is None and memory.replaced(other) is None
    memory.supersede(new, old, "api")
    assert memory.replaced(new) == old and memory.replaced(old) is None and memory.replaced(9999) is None


def test_a_replaced_fact_that_was_brought_back_by_hand_is_no_longer_what_was_replaced(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "api")
    memory.decide(new, "retire", "api")
    memory.decide(old, "restore", "api")
    assert memory.replaced(new) is None


def test_taking_a_correction_back_retires_the_new_fact_and_remembers_the_old_one_again(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto")
    assert memory.undo_replace(new, "api") == old
    assert memory.get(new)["status"] == "retired" and memory.get(old)["status"] == "accepted" and memory.verify_integrity() == []
    assert events(memory, new)[-1] == ("retired", "api", {"brought_back": old, "undid": True})
    assert events(memory, old)[-1] == ("restored", "api", {"undid": new})


def test_taking_back_what_diya_did_counts_as_taking_it_back(memory):
    from datetime import datetime, timedelta, timezone

    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto")
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert memory.taken_back_count(since) == 0
    memory.undo_replace(new, "api")
    assert memory.taken_back_count(since) == 1  # the new fact was Diya's own doing and the person has retired it: that is what the breaker counts


def test_a_correction_that_replaced_nothing_cannot_be_taken_back(memory):
    fact = memory.add_manual("likes tea", "api")
    before = [(f["id"], f["status"]) for f in memory.facts()]
    with pytest.raises(diya_memory.IllegalTransition, match="did not replace anything"):
        memory.undo_replace(fact, "api")
    assert [(f["id"], f["status"]) for f in memory.facts()] == before


def test_a_correction_cannot_be_taken_back_twice_or_after_the_new_fact_is_forgotten(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto")
    memory.undo_replace(new, "api")
    with pytest.raises(diya_memory.IllegalTransition):
        memory.undo_replace(new, "api")
    new2 = waiting(memory, "works as a baker", position=1)
    memory.supersede(new2, old, "auto")
    memory.decide(new2, "retire", "api")  # forgotten by hand first: nothing to take back
    with pytest.raises(diya_memory.IllegalTransition, match="not accepted"):
        memory.undo_replace(new2, "api")


def test_a_correction_whose_old_fact_can_no_longer_come_back_is_refused_and_changes_nothing(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto")
    memory.add_manual("works as a teacher", "api")  # an accepted fact now says the same as the old one
    before = [(f["id"], f["status"]) for f in memory.facts()]
    with pytest.raises(diya_memory.DuplicateFact):
        memory.undo_replace(new, "api")
    assert [(f["id"], f["status"]) for f in memory.facts()] == before


def test_an_unknown_actor_cannot_take_a_correction_back(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto")
    with pytest.raises(ValueError):
        memory.undo_replace(new, "a stranger")
    assert memory.get(new)["status"] == "accepted"


def test_the_line_under_a_reply_says_what_is_still_true_and_nothing_private(memory):
    old = memory.add_manual("works as a teacher", "api")
    said = said_in(memory, "likes tea works as a nurse takes metformin every morning my password is hunter2")
    remembered = waiting(memory, "likes tea", message=said)
    memory.decide(remembered, "accept", "auto")
    replaced = waiting(memory, "works as a nurse", position=1, message=said)
    memory.supersede(replaced, old, "auto")
    asked = waiting(memory, "takes metformin every morning", flags=["ask:sensitive:model_private"], position=2, message=said)
    secret = waiting(memory, "my password is hunter2", position=3, message=said)
    memory.discard_secret(secret, "password", "auto")
    got = memory.learned_from(said)
    kinds = [(item["kind"], item["id"]) for item in got]
    assert kinds == [("remembered", remembered), ("replaced", replaced), ("asked", asked), ("not_kept", secret)]
    assert got[1]["text"] == "works as a nurse" and got[1]["old_id"] == old and got[1]["old_text"] == "works as a teacher"
    assert "text" not in got[2] and "text" not in got[3] and "metformin" not in json.dumps(got) and "hunter2" not in json.dumps(got)


def test_a_fact_the_person_accepted_or_undid_is_not_on_the_line(memory):
    said = said_in(memory, "likes tea likes coffee a repeat")
    by_hand = waiting(memory, "likes tea", message=said)
    memory.decide(by_hand, "accept", "api")
    undone = waiting(memory, "likes coffee", position=1, message=said)
    memory.decide(undone, "accept", "auto")
    memory.decide(undone, "retire", "api")
    rejected = waiting(memory, "a repeat", position=2, message=said)
    memory.decide(rejected, "reject", "auto")
    assert memory.learned_from(said) == []


def test_only_the_message_asked_about_is_listed(memory):
    first, second = said_in(memory, "likes tea"), said_in(memory, "likes coffee")
    one = waiting(memory, "likes tea", message=first)
    memory.decide(one, "accept", "auto")
    two = waiting(memory, "likes coffee", position=1, message=second)
    memory.decide(two, "accept", "auto")
    assert [i["id"] for i in memory.learned_from(first)] == [one] and [i["id"] for i in memory.learned_from(second)] == [two] and memory.learned_from(second + 1) == []
    assert memory.learned_from(first + 10) == [] and memory.learned_from(1000 + first) == []  # "source_message:1" is not "source_message:11" or "source_message:1001"


def test_a_fact_forgotten_on_request_is_on_the_line_until_it_is_remembered_again(memory):
    fact = memory.add_manual("likes tea", "api")
    memory.decide(fact, "retire", "auto", {"lane": "forget", "reasons": ["asked_to_forget:fact"], "message": 7})
    assert memory.learned_from(7) == [{"kind": "forgot", "id": fact, "text": "likes tea"}]
    memory.decide(fact, "restore", "api")
    assert memory.learned_from(7) == []
    assert memory.learned_from(8) == []


# --- the policy: both halves are needed -------------------------------------------------------------------------------------

def replacing(old_id):
    return lambda fact: auto.Replacement("replaces", old_id)


def test_a_correction_the_model_placed_replaces_the_known_fact_without_a_question(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    report = auto.apply(memory, replaces=replacing(old), corrects=lambda fact: True)
    assert report == auto.Report(0, 0, 0, 0, 1) and memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "retired"
    assert events(memory, new)[-1][2] == {"lane": "remember", "reasons": ["correction"], "replaces": old}


def test_a_correction_the_model_could_not_place_still_asks(memory):
    new = waiting(memory, "works as a nurse")
    auto.apply(memory, replaces=lambda fact: auto.Replacement("unclear", None), corrects=lambda fact: True)
    assert memory.get(new)["status"] == "candidate" and "ask:conflict:replaces_unclear" in memory.get(new)["flags"]


def test_a_replacement_the_person_did_not_say_is_one_the_model_thought_of_so_it_asks(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    report = auto.apply(memory, replaces=replacing(old), corrects=lambda fact: False)
    assert report == auto.Report(0, 1, 0, 0, 0) and memory.get(old)["status"] == "accepted" and f"ask:conflict:replaces:{old}" in memory.get(new)["flags"]


def test_without_a_judgement_of_corrections_nothing_is_replaced_on_its_own(memory):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    auto.apply(memory, replaces=replacing(old))
    assert memory.get(new)["status"] == "candidate" and memory.get(old)["status"] == "accepted"


def test_a_correction_where_the_model_says_nothing_is_replaced_is_remembered_beside_what_is_known(memory):
    old = memory.add_manual("likes tea", "api")
    new = waiting(memory, "plays chess")
    report = auto.apply(memory, replaces=lambda fact: auto.Replacement("none", None), corrects=lambda fact: True)
    assert report == auto.Report(1, 0, 0, 0, 0) and memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "accepted"


def test_a_correction_that_cannot_be_made_waits_as_a_question_and_changes_nothing(memory):
    old = memory.add_manual("works as a teacher", "api")
    memory.add_manual("works as a nurse", "api")  # an accepted fact already says it: the new one would be a repeat
    new = waiting(memory, "works as a nurse")
    before = [(f["id"], f["status"]) for f in memory.facts()]
    report = auto.apply(memory, replaces=replacing(old), corrects=lambda fact: True)
    assert [(f["id"], f["status"]) for f in memory.facts()][:2] == before[:2] and memory.get(old)["status"] == "accepted"
    assert report.replaced == 0


def test_a_correction_counts_toward_the_daily_limit(memory):
    olds = [memory.add_manual(text, "api") for text in ("lives in Delhi", "drives a Honda", "uses an Android phone")]
    news = [waiting(memory, text, position=n) for n, text in enumerate(("lives in Pune", "rides a scooter", "owns an iPhone"))]
    mapping = dict(zip(news, olds))
    report = auto.apply(memory, limit=2, replaces=lambda fact: auto.Replacement("replaces", mapping[fact["id"]]), corrects=lambda fact: True)
    assert report.replaced == 2 and memory.get(news[2])["status"] == "candidate" and "ask:doubt:daily_cap" in memory.get(news[2])["flags"]


def test_a_correction_is_not_made_while_the_breaker_is_open(memory):
    from datetime import datetime, timezone

    old = memory.add_manual("works as a teacher", "api")
    for n in range(auto.BREAKER_LIMIT):
        taken = waiting(memory, f"taken back {n}", position=10 + n)
        memory.decide(taken, "accept", "auto")
        memory.decide(taken, "retire", "api")
    new = waiting(memory, "works as a nurse", position=1)
    report = auto.apply(memory, replaces=replacing(old), corrects=lambda fact: True)
    assert report.replaced == 0 and memory.get(new)["status"] == "candidate" and "ask:doubt:breaker_open" in memory.get(new)["flags"]


def test_the_report_with_no_replacements_equals_the_old_four_numbers():
    assert auto.Report(1, 2, 3, 4) == auto.Report(1, 2, 3, 4, 0) and auto.Report(1, 2, 3, 4) != auto.Report(1, 2, 3, 4, 1)


# --- Dreaming: a message that corrects, and a message that forgets ------------------------------------------------------------

def make_config(tmp_path, **changes):
    settings = dict(db_path=str(tmp_path / "d.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"),
                    dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "profile.txt"), auto_memory=True)
    return dataclasses.replace(diya_config.load_config({}), **{**settings, **changes})


@pytest.fixture
def world(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.db_path)
    return config, store, store.create_thread()


def said(world, text, role="user"):
    return world[1].add_message(world[2], role, text)


def reader(world, client):
    return dreaming.Dreamer(world[0], client=client, store=world[1])


def test_a_message_that_corrects_replaces_the_fact_the_model_names_and_the_line_says_so(world):
    _, store, _ = world
    old = Memory(store).add_manual("works as a teacher at a school", "api")
    message = said(world, "no, I now work as a nurse at a hospital")
    client = ByQuestionClient(extraction=["- works as a nurse at a hospital"], replace=["1"])
    assert reader(world, client).capture_message(message) == 1
    memory = Memory(store)
    nurse = next(f for f in memory.facts() if f["text"] == "works as a nurse at a hospital")
    assert nurse["status"] == "accepted" and memory.get(old)["status"] == "retired" and memory.replaced(nurse["id"]) == old
    assert memory.learned_from(message) == [{"kind": "replaced", "id": nurse["id"], "text": "works as a nurse at a hospital", "old_id": old, "old_text": "works as a teacher at a school"}]


def test_a_message_that_only_states_something_new_still_asks_when_the_model_thinks_it_replaces(world):
    _, store, _ = world
    old = Memory(store).add_manual("works as a teacher at a school", "api")
    message = said(world, "I work as a nurse at a hospital")
    reader(world, ByQuestionClient(extraction=["- works as a nurse at a hospital"], replace=["1"])).capture_message(message)
    nurse = next(f for f in Memory(store).facts() if f["text"] == "works as a nurse at a hospital")
    assert nurse["status"] == "candidate" and f"ask:conflict:replaces:{old}" in nurse["flags"] and Memory(store).get(old)["status"] == "accepted"


def test_a_correction_about_something_private_is_asked_and_not_replaced(world):
    _, store, _ = world
    old = Memory(store).add_manual("takes ibuprofen when needed", "api")
    message = said(world, "no, I now take sertraline every morning")
    client = ByQuestionClient(extraction=["- takes sertraline every morning"], privacy=["PRIVATE", "PRIVATE"], replace=["1"])
    reader(world, client).capture_message(message)
    fact = next(f for f in Memory(store).facts() if f["text"] == "takes sertraline every morning")
    assert fact["status"] == "candidate" and Memory(store).get(old)["status"] == "accepted" and client.asked("replace") == []


def test_forget_that_retires_the_one_fact_it_is_about_without_asking_the_model(world):
    _, store, _ = world
    memory = Memory(store)
    tea = memory.add_manual("likes tea in the morning", "api")
    memory.add_manual("plays badminton on Sundays", "api")
    message = said(world, "forget that I like tea")
    client = ByQuestionClient()
    assert reader(world, client).capture_message(message) == 1
    assert client.chat_calls == [] and memory.get(tea)["status"] == "retired" and [f["text"] for f in memory.facts("accepted")] == ["plays badminton on Sundays"]
    assert store.captured_message_ids([message]) == {message}
    assert memory.learned_from(message) == [{"kind": "forgot", "id": tea, "text": "likes tea in the morning"}]
    assert events(memory, tea)[-1] == ("retired", "auto", {"lane": "forget", "message": message, "reasons": ["asked_to_forget:fact"]})


def test_forget_that_does_nothing_when_it_is_not_clear_which_fact_is_meant(world):
    _, store, _ = world
    memory = Memory(store)
    memory.add_manual("likes tea in the morning", "api")
    memory.add_manual("likes coffee in the evening", "api")
    message = said(world, "forget that I like it")
    assert reader(world, ByQuestionClient()).capture_message(message) == 0
    assert len(memory.facts("accepted")) == 2


def test_forget_that_does_nothing_when_nothing_is_like_it(world):
    _, store, _ = world
    memory = Memory(store)
    memory.add_manual("likes tea in the morning", "api")
    message = said(world, "forget that I own a boat")
    assert reader(world, ByQuestionClient()).capture_message(message) == 0
    assert len(memory.facts("accepted")) == 1 and store.captured_message_ids([message]) == {message}


def test_two_facts_equally_like_it_means_neither_is_forgotten(world):
    _, store, _ = world
    memory = Memory(store)
    memory.add_manual("likes tea in the morning", "api")
    memory.add_manual("likes tea in the evening", "api")
    message = said(world, "forget that I like tea")
    assert reader(world, ByQuestionClient()).capture_message(message) == 0
    assert len(memory.facts("accepted")) == 2


def test_forget_everything_about_a_person_retires_that_persons_facts_by_name(world):
    _, store, _ = world
    memory = Memory(store)
    a = memory.add_manual("is visiting in May", "api")
    b = memory.add_manual("is allergic to peanuts", "api")
    c = memory.add_manual("likes tea", "api")
    memory.set_person(a, "Maya", "api")
    memory.set_person(b, "Maya", "api")
    message = said(world, "forget everything about my sister Maya")
    assert reader(world, ByQuestionClient()).capture_message(message) == 2
    assert [f["id"] for f in memory.facts("accepted")] == [c]
    assert sorted(item["id"] for item in memory.learned_from(message)) == [a, b]


def test_the_name_has_to_be_a_whole_word_and_a_person_diya_knows(world):
    _, store, _ = world
    memory = Memory(store)
    fact = memory.add_manual("is visiting in May", "api")
    memory.set_person(fact, "Maya", "api")
    for text in ("forget everything about Mayank", "forget everything about Priya"):
        message = said(world, text)
        assert reader(world, ByQuestionClient()).capture_message(message) == 0
    assert memory.get(fact)["status"] == "accepted"


def test_with_the_switch_off_nothing_is_forgotten(tmp_path):
    config = make_config(tmp_path, auto_memory=False)
    store = Store(config.db_path)
    memory = Memory(store)
    fact = memory.add_manual("likes tea in the morning", "api")
    message = store.add_message(store.create_thread(), "user", "forget that I like tea")
    assert dreaming.Dreamer(config, client=ByQuestionClient(), store=store).capture_message(message) is None
    assert memory.get(fact)["status"] == "accepted"


def test_a_request_to_forget_that_was_said_by_the_assistant_is_not_obeyed(world):
    _, store, _ = world
    memory = Memory(store)
    fact = memory.add_manual("likes tea in the morning", "api")
    message = said(world, "forget that I like tea", role="assistant")
    assert reader(world, ByQuestionClient()).capture_message(message) is None
    assert memory.get(fact)["status"] == "accepted"


def test_a_forget_message_is_read_once(world):
    _, store, _ = world
    memory = Memory(store)
    tea = memory.add_manual("likes tea in the morning", "api")
    message = said(world, "forget that I like tea")
    d = reader(world, ByQuestionClient())
    assert d.capture_message(message) == 1
    memory.decide(tea, "restore", "api")
    assert d.capture_message(message) is None and memory.get(tea)["status"] == "accepted"


def test_the_scheduled_pass_does_not_read_a_message_that_asked_to_forget(world):
    config, store, _ = world
    message = said(world, "forget that I like tea")
    Memory(store).add_manual("likes tea in the morning", "api")
    reader(world, ByQuestionClient()).capture_message(message)
    client = ByQuestionClient(extraction=["NONE"])
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    assert client.asked("extraction") == []  # read already (and it is not a statement either)


# --- the routes and the chat's answer ----------------------------------------------------------------------------------------

@pytest.fixture
def parts(tmp_path):
    def build(auto_memory=True, client=None):
        config = make_config(tmp_path, auto_memory=auto_memory, require_token=False)
        agent = diya.Agent(config, client=client or ByQuestionClient())
        return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost"), agent, config
    return build


def test_the_chat_says_which_message_it_saved_and_whether_memory_is_going_to_read_it(parts):
    client, agent, _ = parts(client=ByQuestionClient(extraction=["- likes tea in the morning"]))
    body = client.post("/api/chat", json={"message": "I like tea in the morning"}).json()
    assert body["message_id"] == 1 and body["reading"] is True
    asked = client.post("/api/chat", json={"message": "what is 9 times 7?"}).json()
    assert asked["reading"] is False and asked["message_id"] == 3
    forget = client.post("/api/chat", json={"message": "forget that I like tea"}).json()
    assert forget["reading"] is True


def test_with_memory_off_the_chat_never_says_it_is_reading(parts):
    client, _, _ = parts(auto_memory=False)
    assert client.post("/api/chat", json={"message": "I like tea in the morning"}).json()["reading"] is False


def test_the_learned_route_reports_what_was_done_and_that_reading_is_over(parts):
    client, agent, _ = parts(client=ByQuestionClient(extraction=["- likes tea in the morning"]))
    sent = client.post("/api/chat", json={"message": "I like tea in the morning"}).json()
    body = client.get("/api/memory/learned", params={"message_id": sent["message_id"]}).json()
    assert body["reading"] is False and [(i["kind"], i["text"]) for i in body["items"]] == [("remembered", "likes tea in the morning")]


def test_the_learned_route_says_reading_while_a_worthy_message_has_not_been_read_yet(parts):
    client, agent, _ = parts()
    message = agent.store.add_message(agent.store.create_thread(), "user", "I like tea in the morning")
    assert client.get("/api/memory/learned", params={"message_id": message}).json() == {"reading": True, "items": []}
    agent.store.mark_captured(message, 0)
    assert client.get("/api/memory/learned", params={"message_id": message}).json() == {"reading": False, "items": []}


@pytest.mark.parametrize("text, role, auto_memory", [
    ("what is 9 times 7?", "user", True), ("I like tea in the morning", "assistant", True), ("I like tea in the morning", "user", False),
])
def test_the_learned_route_does_not_say_reading_for_what_will_never_be_read(parts, text, role, auto_memory):
    client, agent, _ = parts(auto_memory=auto_memory)
    message = agent.store.add_message(agent.store.create_thread(), role, text)
    assert client.get("/api/memory/learned", params={"message_id": message}).json()["reading"] is False


def test_the_learned_route_sends_text_made_safe_to_show(parts, monkeypatch):
    client, agent, _ = parts()
    bad = "likes tea " + chr(27) + "[31m" + chr(0x202E)
    monkeypatch.setattr(Memory, "learned_from", lambda self, message_id: [
        {"kind": "replaced", "id": 2, "text": bad, "old_id": 1, "old_text": bad}, {"kind": "remembered", "id": 3, "text": bad}])
    items = client.get("/api/memory/learned", params={"message_id": 1}).json()["items"]
    assert len(items) == 2 and all(chr(27) not in item[key] and chr(0x202E) not in item[key] for item in items for key in ("text", "old_text") if key in item)
    assert items[0]["old_id"] == 1


@pytest.mark.parametrize("params", [{}, {"message_id": "abc"}, {"message_id": "1.5"}])
def test_the_learned_route_needs_a_whole_number(parts, params):
    client, _, _ = parts()
    assert client.get("/api/memory/learned", params=params).status_code == 422


@pytest.mark.parametrize("message_id", [0, -1, 2**63])
def test_the_learned_route_turns_away_an_id_that_cannot_exist(parts, message_id):
    client, _, _ = parts()
    assert client.get("/api/memory/learned", params={"message_id": message_id}).status_code == 404


def test_the_undo_route_takes_a_correction_back_and_says_what_came_back(parts):
    client, agent, _ = parts()
    memory = Memory(agent.store)
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto")
    body = client.post(f"/api/memory/{new}/undo-replace").json()
    assert body["fact"]["status"] == "retired" and body["restored"]["id"] == old and body["restored"]["status"] == "accepted" and body["summary"]["counts"]["accepted"] == 1
    assert events(memory, new)[-1][1] == "api"


@pytest.mark.parametrize("fact_id, status, reason", [(9999, 409, "did not replace anything"), (0, 404, "there is no fact 0"), (2**63, 404, "there is no fact")])
def test_the_undo_route_refuses_what_cannot_be_taken_back_and_changes_nothing(parts, fact_id, status, reason):
    client, agent, _ = parts()
    memory = Memory(agent.store)
    memory.add_manual("likes tea", "api")
    before = [(f["id"], f["status"]) for f in memory.facts()]
    response = client.post(f"/api/memory/{fact_id}/undo-replace")
    assert response.status_code == status and reason in response.json()["detail"]
    assert [(f["id"], f["status"]) for f in memory.facts()] == before


def test_a_correction_said_in_chat_replaces_the_old_fact_and_is_shown_under_the_reply(parts):
    client, agent, _ = parts(client=ByQuestionClient(extraction=["- works as a nurse at a hospital"], replace=["1"]))
    old = Memory(agent.store).add_manual("works as a teacher at a school", "api")
    sent = client.post("/api/chat", json={"message": "no, I now work as a nurse at a hospital"}).json()
    items = client.get("/api/memory/learned", params={"message_id": sent["message_id"]}).json()["items"]
    assert [(i["kind"], i["old_id"], i["old_text"]) for i in items] == [("replaced", old, "works as a teacher at a school")]
    undone = client.post(f"/api/memory/{items[0]['id']}/undo-replace").json()
    assert undone["restored"]["id"] == old
    assert client.get("/api/memory/learned", params={"message_id": sent["message_id"]}).json()["items"] == []  # undone: no longer true, no longer said


# --- the edges: each of these is a way the code above could be wrong without any test above noticing ---------------------------

def test_the_words_any_more_alone_are_enough_to_read_a_message_as_a_correction():
    assert diya_intent.is_correction("I'm over tea any more") is True and diya_intent.is_correction("I'm over tea anymore") is True


def test_a_request_to_forget_that_is_too_long_to_be_one_is_not_one():
    assert diya_intent.forget_target("forget that " + "a" * 400) is None and diya_intent.forget_target("forget that " + "a" * 380) is not None


def test_a_name_that_is_only_punctuation_is_no_person_and_trailing_punctuation_is_not_part_of_a_name():
    assert diya_intent.forget_target("forget everything about !!") is None
    assert diya_intent.forget_target("forget everything about Maya!!") == ("person", "Maya")
    assert diya_intent.forget_target("forget everything about a b c d e") is None  # five words are not a name


@pytest.mark.parametrize("text", ["no, thanks", "no, that's wrong", "actually, never mind", "that's outdated"])
def test_a_correction_that_says_nothing_about_the_person_is_not_read_for_facts(text):
    assert diya_intent.is_correction(text) is True and diya_intent.is_worth_capturing(text) is False


@pytest.mark.parametrize("text", ["no, I live in Pune", "actually I work at a bank", "Actually, we moved", "no, my sister lives in Dubai now"])
def test_a_correction_that_does_say_something_about_the_person_is_read_though_it_does_not_start_with_me(text):
    assert diya_intent.is_worth_capturing(text) is True


def test_taking_a_correction_back_needs_the_old_fact_to_be_retired_still(memory, monkeypatch):
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    memory.supersede(new, old, "auto")
    memory.decide(old, "restore", "api")  # brought back by hand in the meantime
    monkeypatch.setattr(Memory, "replaced", lambda self, fact_id: old)  # but the trail still names it
    before = [(f["id"], f["status"]) for f in memory.facts()]
    with pytest.raises(diya_memory.IllegalTransition, match="only a retired fact"):
        memory.undo_replace(new, "api")
    assert [(f["id"], f["status"]) for f in memory.facts()] == before


def test_taking_a_correction_back_counts_the_label_a_named_persons_old_fact_carries(memory):
    old = memory.add_manual("lives in Mumbai", "api")
    memory.set_person(old, "Maya", "api")
    new = waiting(memory, "lives in Dubai", person="Maya")
    for n in range(9):
        memory.add_manual(f"{n} " + "y" * 194, "api")
    memory.supersede(new, old, "auto")
    pairs = [(f["text"], f["person"]) for f in memory.facts("accepted")]
    filler = diya_memory.MAX_PROFILE_CHARS - len(diya_memory.render_grouped(pairs)) - len("\n- ")
    assert 1 <= filler <= diya_memory.MAX_FACT_CHARS
    memory.add_manual("f" * filler, "api")  # the profile has grown into exactly the room the correction left, with the new fact in it
    others = [(text, None) for text in memory.accepted_texts() if text != "lives in Dubai"]
    assert len(diya_memory.render_grouped(others + [("lives in Mumbai", None)])) <= diya_memory.MAX_PROFILE_CHARS  # the old fact would fit as plain text
    assert len(diya_memory.render_grouped(others + [("lives in Mumbai", "Maya")])) > diya_memory.MAX_PROFILE_CHARS  # but not with the label of the person it is about
    before = [(f["id"], f["status"]) for f in memory.facts()]
    with pytest.raises(diya_memory.BudgetExceeded):
        memory.undo_replace(new, "api")
    assert [(f["id"], f["status"]) for f in memory.facts()] == before


def test_a_discarded_secret_keeps_only_the_number_of_the_message_it_came_from(memory):
    fact = waiting(memory, "my password is hunter2", flags=["ungrounded", "verifier:no", "ask:doubt:x", "source_message:abc"])
    memory.set_flags(fact, ["ungrounded", "verifier:no", "ask:doubt:x", "source_message:abc", "source_message:7", "source_message:"], "system")
    memory.discard_secret(fact, "password", "auto")
    assert memory.get(fact)["flags"] == ["source_message:7"]


def test_a_waiting_fact_with_no_question_on_it_is_not_said_on_the_line(memory):
    said = said_in(memory, "likes tea takes metformin")
    waiting(memory, "likes tea", flags=["ungrounded"], message=said)
    assert memory.learned_from(said) == []


def test_only_what_diya_forgot_because_it_was_asked_to_is_said_as_forgotten(memory):
    one, two, three, four = (memory.add_manual(f"fact number {n} here", "api") for n in range(4))
    memory.decide(one, "retire", "auto", {"lane": "forget", "reasons": ["asked_to_forget:fact"], "message": 7})
    memory.decide(two, "retire", "api", {"lane": "forget", "reasons": ["asked_to_forget:fact"], "message": 7})  # by a person: not Diya's doing
    memory.decide(three, "retire", "auto", {"lane": "other", "reasons": [], "message": 7})  # not a forgetting
    memory.decide(four, "retire", "auto", {"lane": "forget", "reasons": ["asked_to_forget:fact"], "message": 8})  # another message
    assert [item["id"] for item in memory.learned_from(7)] == [one] and [item["id"] for item in memory.learned_from(8)] == [four]


def test_a_message_number_that_merely_starts_the_same_is_not_the_same_message(memory):
    first = said_in(memory, "likes tea")
    for _ in range(10):
        later = said_in(memory, "likes coffee")  # ids 2..11
    fact = waiting(memory, "likes coffee", position=1, message=later)
    memory.decide(fact, "accept", "auto")
    assert first == 1 and later == 11 and memory.learned_from(first) == [] and [i["id"] for i in memory.learned_from(later)] == [fact]


def test_a_correction_the_memory_cannot_make_any_more_waits_as_a_question_and_is_not_counted(memory):
    gone = memory.add_manual("works as a teacher", "api")
    memory.decide(gone, "retire", "api")  # the model named a fact that is no longer accepted
    new = waiting(memory, "works as a nurse")
    report = auto.apply(memory, replaces=replacing(gone), corrects=lambda fact: True)
    assert report == auto.Report(0, 1, 0, 0, 0) and memory.get(new)["status"] == "candidate" and f"ask:conflict:replaces:{gone}" in memory.get(new)["flags"]


def test_the_correction_judge_is_true_if_any_of_the_messages_a_fact_came_from_corrects_and_never_for_the_assistants(world):
    config, store, _ = world
    plain = said(world, "I like tea")
    corrects = said(world, "no, I live in Pune")
    spoken = said(world, "no, I live in Pune", role="assistant")
    judge = reader(world, ByQuestionClient())._correction_judge()
    assert judge({"flags": [f"source_message:{plain}"]}) is False and judge({"flags": [f"source_message:{corrects}"]}) is True
    assert judge({"flags": [f"source_message:{plain}", f"source_message:{corrects}"]}) is True
    assert judge({"flags": [f"source_message:{spoken}"]}) is False and judge({"flags": []}) is False


def test_forget_that_needs_most_of_what_was_said_to_be_in_the_fact(world):
    _, store, _ = world
    memory = Memory(store)
    tea = memory.add_manual("likes tea in the morning", "api")
    message = said(world, "forget that I like tea and coffee and cake")  # only a half of those words are in the fact
    assert reader(world, ByQuestionClient()).capture_message(message) == 0 and memory.get(tea)["status"] == "accepted"


def test_forget_that_counts_what_was_said_not_how_long_the_fact_is(world):
    _, store, _ = world
    memory = Memory(store)
    tea = memory.add_manual("likes tea in the morning and in the evening with a plate of biscuits", "api")
    message = said(world, "forget about tea")
    assert reader(world, ByQuestionClient()).capture_message(message) == 1 and memory.get(tea)["status"] == "retired"


def test_forgetting_a_person_does_not_mind_capitals(world):
    _, store, _ = world
    memory = Memory(store)
    fact = memory.add_manual("is visiting in May", "api")
    memory.set_person(fact, "Maya", "api")
    assert reader(world, ByQuestionClient()).capture_message(said(world, "forget everything about maya")) == 1
    assert memory.get(fact)["status"] == "retired"


def test_a_fact_that_cannot_be_retired_any_more_is_skipped_and_the_rest_are_still_forgotten(world, monkeypatch):
    _, store, _ = world
    memory = Memory(store)
    a = memory.add_manual("is visiting in May", "api")
    b = memory.add_manual("is allergic to peanuts", "api")
    memory.set_person(a, "Maya", "api")
    memory.set_person(b, "Maya", "api")
    real = Memory.decide

    def flaky(self, fact_id, action, actor, detail=None):
        if fact_id == a:
            raise diya_memory.IllegalTransition("it was retired a moment ago")
        return real(self, fact_id, action, actor, detail)

    monkeypatch.setattr(Memory, "decide", flaky)
    assert reader(world, ByQuestionClient()).capture_message(said(world, "forget everything about Maya")) == 1
    assert memory.get(b)["status"] == "retired" and memory.get(a)["status"] == "accepted"


def test_the_learned_route_says_a_request_to_forget_is_being_read_until_it_has_been(parts):
    client, agent, _ = parts()
    message = agent.store.add_message(agent.store.create_thread(), "user", "forget that I like tea")
    assert client.get("/api/memory/learned", params={"message_id": message}).json()["reading"] is True
    agent.store.mark_captured(message, 0)
    assert client.get("/api/memory/learned", params={"message_id": message}).json()["reading"] is False


def test_after_taking_a_correction_back_the_other_waiting_facts_are_checked_against_what_is_known_now(parts):
    client, agent, _ = parts()
    memory = Memory(agent.store)
    old = memory.add_manual("works as a teacher", "api")
    new = waiting(memory, "works as a nurse")
    twin = waiting(memory, "works as a teacher", position=1)
    memory.supersede(new, old, "auto")
    client.post(f"/api/memory/{new}/undo-replace")
    assert f"duplicate:{old}" in memory.get(twin)["flags"]
