"""Reading a message for facts the moment it is said (docs/AUTO_MEMORY_DESIGN.md, D7 and unit A4): diya_intent.is_worth_capturing, the table that remembers
what was read (migration 8), diya_memory.ingest_lines, Dreamer.capture_message, Dreaming skipping what was read live, and the chat route's hook.

What this proves: only a short first-person statement is read live, never a question, request, reminder or task; nothing at all happens with automatic
memory off; a message is read once, and one the model could not be asked about is left to the scheduled pass; what it finds goes through exactly the
lanes Dreaming's facts go through (plain remembered, private asked, a secret never kept); a message read live and the batch Dreaming later starts at
that same message cannot take each other's slots; Dreaming does not read it again, and a batch made only of what was read live still moves the checkpoint;
nothing in this can raise into a chat; and the chat route reads a message only after its reply is made, one at a time, and only with the switch on.
"""
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_db
import diya_intent
import diya_memory
import diya_web
import dreaming
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient, FakeClient, text_reply


# --- which messages are worth reading at once ------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "I live in Pune and I love the weather here in winter.",
    "My cat is called Pixel and she is three years old.",
    "I moved to Pune last month, so I no longer live in Delhi.",
    "I don't like spicy food.",
    "we're planning a trip to Goa in December",
    "I'm learning to play the guitar, mostly folk songs.",
    "remember that my sister Maya is allergic to peanuts",
    "FYI I work at the clinic on Tuesdays",
    "  I prefer short, direct answers.  ",
    "I’ve started running before work",
])
def test_a_short_first_person_statement_is_worth_reading_at_once(text):
    assert diya_intent.is_worth_capturing(text) is True


@pytest.mark.parametrize("text", [
    "", "   ", "hey, good morning", "what is 9 times 7?", "Where do I live?", "I live in Pune, do you know the weather?",
    "remind me to call mum at 5", "I need you to remind me about the dentist", "set a reminder for Friday", "add a task to pay rent",
    "please write a poem about my cat", "can you tell me a joke", "tell me about my day", "how do I reverse a list in python",
    "I want to learn guitar", "I need a new laptop", "I don't know what to do", "I can't find my keys", "I'm not sure about Friday",
    "I can’t find my keys", "I don’t know what to do", "I like tea in the morning, right?", "I'll set a reminder for Friday",
    "My note to self: call the bank", "I'll add a task to pay the rent", "the weather is nice", "Maya is visiting in May", "x" * 401, "I like tea. " * 40, None, 42, ["I like tea"], b"I like tea",
])
def test_a_question_a_request_a_reminder_a_task_or_anything_else_is_not(text):
    assert diya_intent.is_worth_capturing(text) is False


def test_the_longest_message_read_is_the_longest_the_fact_share_test_allows():
    assert diya_intent.is_worth_capturing("I like " + "a" * (diya_intent.MAX_CHARS - 7)) is True
    assert diya_intent.is_worth_capturing("I like " + "a" * (diya_intent.MAX_CHARS - 6)) is False


# --- the table of what was read ---------------------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "live.db"))


def test_migration_eight_makes_the_table_and_a_fresh_database_has_every_version(store):
    conn = store.connect()  # opening it is what applies the migrations
    versions = [row[0] for row in conn.execute("SELECT version FROM migrations ORDER BY version")]
    columns = [row[1] for row in conn.execute("PRAGMA table_info(memory_captures)")]
    conn.close()
    assert versions == [v for v, _ in diya_db.MIGRATIONS] and 8 in versions
    assert columns == ["message_id", "at", "facts"]


def test_a_message_marked_as_read_is_found_and_the_others_are_not(store):
    thread = store.create_thread()
    ids = [store.add_message(thread, "user", f"I like thing {n}") for n in range(5)]
    assert store.captured_message_ids(ids) == set()
    store.mark_captured(ids[1], 2)
    store.mark_captured(ids[3], 0)
    assert store.captured_message_ids(ids) == {ids[1], ids[3]}
    assert store.captured_message_ids([ids[0], ids[2]]) == set() and store.captured_message_ids([]) == set()


def test_marking_twice_changes_nothing_and_keeps_the_first_count(store):
    thread = store.create_thread()
    message = store.add_message(thread, "user", "I like tea")
    store.mark_captured(message, 3)
    store.mark_captured(message, 9)
    conn = store.connect()
    rows = conn.execute("SELECT message_id, facts FROM memory_captures").fetchall()
    conn.close()
    assert rows == [(message, 3)]


def test_a_long_list_of_ids_is_asked_in_pieces_and_none_is_lost(store):
    thread = store.create_thread()
    ids = [store.add_message(thread, "user", f"m{n}") for n in range(1203)]
    for n in (0, 499, 500, 501, 999, 1000, 1202):
        store.mark_captured(ids[n], 1)
    assert store.captured_message_ids(ids) == {ids[n] for n in (0, 499, 500, 501, 999, 1000, 1202)}


# --- turning lines into candidates ------------------------------------------------------------------------------------------

def test_lines_become_candidates_in_slots_that_start_where_they_are_told(store):
    memory = Memory(store)
    new, already, skipped = diya_memory.ingest_lines(memory, ["- likes tea", "-", "- has a cat [Maya]"], first_message_id=7, last_message_id=7, model="m",
                                                    staged_at="2026-10-10T00:00:00+00:00", actor="system", position_base=1000)
    assert (new, already, skipped) == (2, 0, 1)
    facts = memory.facts()
    assert [(f["text"], f["person"]) for f in facts] == [("likes tea", None), ("has a cat", "Maya")]
    conn = store.connect()
    positions = [row[0] for row in conn.execute("SELECT position FROM facts ORDER BY id")]
    conn.close()
    assert positions == [1000, 1002]  # the skipped line took its place: slots never shift


def test_the_same_lines_twice_are_recorded_once(store):
    memory = Memory(store)
    args = dict(first_message_id=7, last_message_id=7, model="m", staged_at="t", actor="system", position_base=1000)
    assert diya_memory.ingest_lines(memory, ["- likes tea"], **args) == (1, 0, 0)
    assert diya_memory.ingest_lines(memory, ["- likes tea"], **args) == (0, 1, 0)
    assert len(memory.facts()) == 1


def test_a_live_slot_and_a_batch_slot_for_the_same_first_message_do_not_collide(store):
    memory = Memory(store)
    live = dict(first_message_id=7, last_message_id=7, model="m", staged_at="t", actor="system", position_base=dreaming.LIVE_POSITION_BASE)
    batch = dict(first_message_id=7, last_message_id=9, model="m", staged_at="t", actor="system")
    assert diya_memory.ingest_lines(memory, ["- likes tea"], **live) == (1, 0, 0)
    assert diya_memory.ingest_lines(memory, ["- has a cat"], **batch) == (1, 0, 0)  # slot (7, 0) is free: the live one is at (7, 1000)
    assert sorted(f["text"] for f in memory.facts()) == ["has a cat", "likes tea"]


# --- Dreamer.capture_message ------------------------------------------------------------------------------------------------

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
    _, store, thread = world
    return store.add_message(thread, role, text)


def dreamer(world, client):
    config, store, _ = world
    return dreaming.Dreamer(config, client=client, store=store)


def test_a_plain_statement_is_read_and_remembered_at_once(world):
    message = said(world, "I like tea in the morning")
    client = ByQuestionClient(extraction=["- likes tea in the morning"])
    assert dreamer(world, client).capture_message(message) == 1
    (fact,) = Memory(world[1]).facts()
    assert fact["text"] == "likes tea in the morning" and fact["status"] == "accepted" and f"source_message:{message}" in fact["flags"]
    assert (fact["batch_first"], fact["batch_last"]) == (message, message) and fact["model"] == world[0].model and fact["source"] == "dreaming"
    assert world[1].captured_message_ids([message]) == {message}
    conn = world[1].connect()
    assert conn.execute("SELECT facts FROM memory_captures WHERE message_id = ?", (message,)).fetchone() == (1,)  # how many it made is kept
    conn.close()
    assert len(client.asked("extraction")) == 1 and len(client.asked("privacy")) == 2  # the fact, and the message it came from


def test_what_it_finds_goes_through_the_same_lanes_as_everything_else(world):
    message = said(world, "I like tea in the morning and I take metformin every morning and my password is hunter2")
    client = ByQuestionClient(extraction=["- likes tea in the morning\n- takes metformin every morning\n- my password is hunter2"], privacy=["OK", "OK", "PRIVATE"])
    dreamer(world, client).capture_message(message)
    by_text = {f["text"]: f for f in Memory(world[1]).facts()}
    assert by_text["likes tea in the morning"]["status"] == "accepted"
    assert by_text["takes metformin every morning"]["status"] == "candidate" and "ask:sensitive:model_private" in by_text["takes metformin every morning"]["flags"]  # no word of the lists, so the model's answer is what asked
    secret = [f for f in by_text.values() if f["status"] == "rejected"]
    assert len(secret) == 1 and secret[0]["text"] == diya_memory.SECRET_PLACEHOLDER and "hunter2" not in json.dumps(list(by_text))


def test_a_person_named_in_the_message_is_kept_on_the_fact(world):
    message = said(world, "my sister Maya is visiting in May")
    dreamer(world, ByQuestionClient(extraction=["- sister is visiting in May [Maya]"])).capture_message(message)
    (fact,) = Memory(world[1]).facts()
    assert fact["person"] == "Maya"


def test_with_the_switch_off_nothing_happens_and_the_model_is_not_asked(tmp_path):
    config = make_config(tmp_path, auto_memory=False)
    store = Store(config.db_path)
    message = store.add_message(store.create_thread(), "user", "I like tea in the morning")
    client = ByQuestionClient(extraction=["- likes tea in the morning"])
    assert dreaming.Dreamer(config, client=client, store=store).capture_message(message) is None
    assert client.chat_calls == [] and Memory(store).facts() == [] and store.captured_message_ids([message]) == set()


@pytest.mark.parametrize("text, role", [
    ("what is 9 times 7?", "user"), ("remind me to call mum", "user"), ("I like tea in the morning", "assistant"), ("hey", "user"),
])
def test_a_message_not_worth_reading_is_left_alone_without_asking_the_model(world, text, role):
    message = said(world, text, role)
    client = ByQuestionClient(extraction=["- something"])
    assert dreamer(world, client).capture_message(message) is None
    assert client.chat_calls == [] and world[1].captured_message_ids([message]) == set()


def test_a_message_that_is_not_there_is_left_alone_quietly(world, capsys):
    client = ByQuestionClient(extraction=["- x"])
    assert dreamer(world, client).capture_message(999) is None and client.chat_calls == []
    assert capsys.readouterr().err == ""  # not a failure to report: there was simply nothing to read


def test_a_message_is_read_once(world):
    message = said(world, "I like tea in the morning")
    client = ByQuestionClient(extraction=["- likes tea in the morning", "- likes tea in the morning"])
    assert dreamer(world, client).capture_message(message) == 1
    calls = len(client.chat_calls)
    assert dreamer(world, client).capture_message(message) is None
    assert len(client.chat_calls) == calls and len(Memory(world[1]).facts()) == 1


def test_a_model_that_cannot_be_asked_leaves_the_message_to_the_scheduled_pass(world, capsys):
    message = said(world, "I like tea in the morning")
    assert dreamer(world, ByQuestionClient()).capture_message(message) is None  # no extraction answer: the call raises
    assert world[1].captured_message_ids([message]) == set() and Memory(world[1]).facts() == []
    assert f"the scheduled pass will read message {message}" in capsys.readouterr().err


def test_a_message_with_nothing_in_it_is_marked_read_with_no_candidates_and_the_lanes_are_not_run(world):
    message = said(world, "I had a long day today")
    client = ByQuestionClient(extraction=["NONE"])
    assert dreamer(world, client).capture_message(message) == 0
    assert world[1].captured_message_ids([message]) == {message} and Memory(world[1]).facts() == []
    assert client.asked("privacy") == [] and client.asked("replace") == []


def test_an_answer_with_no_text_at_all_is_nothing_found_not_a_failure(world, capsys):
    message = said(world, "I had a long day today")
    client = ByQuestionClient()
    client.lists["extraction"] = [text_reply(None)]
    assert dreamer(world, client).capture_message(message) == 0
    assert world[1].captured_message_ids([message]) == {message} and capsys.readouterr().err == ""


def test_a_message_that_finds_nothing_leaves_what_was_already_waiting_alone(world):
    _, store, _ = world
    waiting = said(world, "I take metformin every morning")
    Memory(store).add_candidate("takes metformin every morning", batch_first=waiting, batch_last=waiting, position=0, model="m", extracted_at="t", raw="- x")
    message = said(world, "I had a long day today")
    client = ByQuestionClient(extraction=["NONE"])
    dreamer(world, client).capture_message(message)
    assert client.asked("privacy") == [] and Memory(store).facts()[0]["status"] == "candidate" and Memory(store).facts()[0]["flags"] == []


@pytest.mark.parametrize("answer", ["", "none", "NONE.", "None - nothing new"])
def test_every_way_of_saying_nothing_is_nothing(world, answer):
    message = said(world, "I had a long day today")
    assert dreamer(world, ByQuestionClient(extraction=[answer])).capture_message(message) == 0


def test_a_fact_that_may_replace_what_is_known_waits_as_a_question(world):
    _, store, _ = world
    old = Memory(store).add_manual("works as a teacher", "api")
    message = said(world, "I work as a nurse at a hospital")
    client = ByQuestionClient(extraction=["- works as a nurse at a hospital"], replace=["1"])
    dreamer(world, client).capture_message(message)
    (fact,) = [f for f in Memory(store).facts() if f["source"] == "dreaming"]
    assert fact["status"] == "candidate" and f"ask:conflict:replaces:{old}" in fact["flags"]


def test_nothing_in_it_can_raise_into_a_chat(world, monkeypatch, capsys):
    message = said(world, "I like tea in the morning")
    monkeypatch.setattr(diya_memory, "ingest_lines", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    assert dreamer(world, ByQuestionClient(extraction=["- likes tea"])).capture_message(message) is None
    err = capsys.readouterr().err
    assert "reading message" in err and "disk full" in err


def test_a_failure_while_putting_facts_in_their_lanes_leaves_them_as_candidates_for_the_scheduled_pass(world, monkeypatch):
    message = said(world, "I like tea in the morning")
    monkeypatch.setattr(dreaming.Dreamer, "_put_in_lanes", lambda self, memory: (_ for _ in ()).throw(RuntimeError("model fell over")))
    assert dreamer(world, ByQuestionClient(extraction=["- likes tea in the morning"])).capture_message(message) is None
    (fact,) = Memory(world[1]).facts()
    assert fact["status"] == "candidate" and world[1].captured_message_ids([message]) == {message}  # taken in, so not extracted twice; the lanes come later


# --- Dreaming does not read it again ----------------------------------------------------------------------------------------

def test_the_scheduled_pass_leaves_out_what_was_read_live(world):
    config, store, _ = world
    first = said(world, "I like tea in the morning")
    second = said(world, "I play badminton on Sundays")
    store.mark_captured(first, 1)
    client = ByQuestionClient(extraction=["- plays badminton on Sundays"])
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    (call,) = client.asked("extraction")
    prompt = call["messages"][0]["content"]
    assert "I play badminton on Sundays" in prompt and "I like tea in the morning" not in prompt
    assert json.load(open(config.dream_state_path)) == {"last_message_id": second}


def test_what_was_read_live_in_the_middle_of_a_batch_is_left_out_wherever_it_is(world):
    config, store, _ = world
    first = said(world, "I like tea in the morning")
    middle = said(world, "I play badminton on Sundays")
    last = said(world, "My neighbour grows tomatoes")
    store.mark_captured(middle, 1)
    client = ByQuestionClient(extraction=["NONE"])
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    prompt = client.asked("extraction")[0]["messages"][0]["content"]
    assert "I like tea in the morning" in prompt and "My neighbour grows tomatoes" in prompt and "badminton" not in prompt
    assert json.load(open(config.dream_state_path)) == {"last_message_id": last}


def test_a_batch_made_only_of_what_was_read_live_asks_nothing_and_still_moves_the_checkpoint(world, capsys):
    config, store, _ = world
    first = said(world, "I like tea in the morning")
    reply = said(world, "Noted.", "assistant")
    store.mark_captured(first, 1)
    client = ByQuestionClient()
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    assert client.chat_calls == [] and json.load(open(config.dream_state_path)) == {"last_message_id": reply}
    assert "already read live" in capsys.readouterr().out


def test_a_captured_message_at_the_start_does_not_hold_up_what_comes_after_it(world):
    config, store, _ = world
    config = dataclasses.replace(config, dream_batch_chars=60)
    first = said(world, "I like tea in the morning and in the evening")
    second = said(world, "I play badminton on Sundays with my friends")
    store.mark_captured(first, 1)
    for expected in (first, second):
        client = ByQuestionClient(extraction=["NONE"])
        dreaming.Dreamer(config, client=client, store=store).dream_cycle()
        assert json.load(open(config.dream_state_path)) == {"last_message_id": expected}


def test_a_message_read_live_and_a_batch_that_starts_at_it_both_keep_their_facts(world):
    config, store, _ = world
    first = said(world, "I like tea in the morning")
    second = said(world, "I play badminton on Sundays")
    third = said(world, "My neighbour grows tomatoes")
    memory = Memory(store)
    dreamer(world, ByQuestionClient(extraction=["- likes tea in the morning"])).capture_message(first)
    client = ByQuestionClient(extraction=["- plays badminton on Sundays\n- neighbour grows tomatoes"])
    d = dreaming.Dreamer(config, client=client, store=store)
    d.dream_cycle()
    d.remember_on_its_own()
    texts = {f["text"] for f in memory.facts()}
    assert {"likes tea in the morning", "plays badminton on Sundays", "neighbour grows tomatoes"} <= texts


def test_a_scheduled_pass_with_nothing_read_live_works_as_it_always_did(world):
    config, store, _ = world
    said(world, "I like tea in the morning")
    client = ByQuestionClient(extraction=["- likes tea in the morning"])
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    assert "I like tea in the morning" in client.asked("extraction")[0]["messages"][0]["content"]
    assert json.loads(open(config.dream_pending_path).read().splitlines()[0])["facts"] == ["- likes tea in the morning"]


def test_the_extraction_prompt_is_one_text_for_both_ways_of_reading():
    assert dreaming.EXTRACTION_PROMPT.startswith("Below are things a user said recently.") and dreaming.EXTRACTION_PROMPT.endswith("return exactly: NONE\n\n")
    assert "'- sister Maya is visiting in May [Maya]'" in dreaming.EXTRACTION_PROMPT


# --- a message that only asks is not read for facts when memory is automatic ---------------------------------------------------

@pytest.mark.parametrize("text", [
    "what's a good name for a kitten?", "how many days until Diwali?", "remind me what a monad is", "tell me a joke", "what time is it?",
    "who won the cricket match yesterday?", "what is 9 times 7?", "can you remind me to call mum at 5?", "Maya got a new job, any gift ideas?",
    "please summarise this", "is it going to rain?", "", "   ", "what’s the weather in Pune today?", "write a poem about cats",
    "translate this sentence into French", "go on then, tell me a joke", "the printer isn’t working", "what should the dog eat?",
    "automate whats the weather in bangalore karnataka", "try the new automations page", "run it now", "use the web to find out", "ask her what time it is",  # the owner's own chat: read for facts before these words were here
])
def test_a_message_that_only_asks_or_tells_diya_something_is_only_asking(text):
    assert diya_intent.only_asks(text) is True


@pytest.mark.parametrize("text", [
    "I live in Pune", "Maya is visiting in May", "hey, good morning", "thanks!", "ok", "I moved to Pune, do you know a good dentist?",
    "how do I reverse a list in python?", "write a poem about my cat", "we're planning a trip, any tips?", "our flight is on Friday, what should we pack?",
    "I’m learning guitar, what should I practise?", "what should we pack?", "when is our flight?", "where is my passport?", None, 5, ["what?"],
])
def test_a_message_with_something_in_the_first_person_or_nothing_that_asks_is_not(text):
    assert diya_intent.only_asks(text) is False


def test_with_memory_automatic_the_scheduled_pass_does_not_read_a_message_that_only_asks(world):
    config, store, _ = world
    said(world, "I like tea in the morning")
    said(world, "what's a good name for a kitten?")
    said(world, "remind me what a monad is")
    said(world, "I play badminton on Sundays")
    client = ByQuestionClient(extraction=["NONE"])
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    prompt = client.asked("extraction")[0]["messages"][0]["content"]
    assert "I like tea in the morning" in prompt and "I play badminton on Sundays" in prompt and "kitten" not in prompt and "monad" not in prompt


def test_with_memory_not_automatic_the_scheduled_pass_reads_every_message_as_it_always_did(tmp_path):
    config = make_config(tmp_path, auto_memory=False)
    store = Store(config.db_path)
    thread = store.create_thread()
    for text in ("I like tea in the morning", "what's a good name for a kitten?"):
        store.add_message(thread, "user", text)
    client = ByQuestionClient(extraction=["NONE"])
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    assert "kitten" in client.asked("extraction")[0]["messages"][0]["content"]


def test_a_batch_of_nothing_but_questions_asks_nothing_and_still_moves_the_checkpoint(world, capsys):
    config, store, _ = world
    said(world, "what's a good name for a kitten?")
    last = said(world, "how many days until Diwali?")
    client = ByQuestionClient()
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    assert client.chat_calls == [] and json.load(open(config.dream_state_path)) == {"last_message_id": last}
    assert "only asks something" in capsys.readouterr().out


def test_what_was_read_live_and_what_only_asks_are_both_left_out_of_one_pass(world):
    config, store, _ = world
    first = said(world, "I like tea in the morning")
    said(world, "tell me a joke")
    said(world, "I play badminton on Sundays")
    store.mark_captured(first, 1)
    client = ByQuestionClient(extraction=["NONE"])
    dreaming.Dreamer(config, client=client, store=store).dream_cycle()
    prompt = client.asked("extraction")[0]["messages"][0]["content"]
    assert "badminton" in prompt and "joke" not in prompt and "tea" not in prompt


# --- the chat route ---------------------------------------------------------------------------------------------------------

@pytest.fixture
def chat_parts(tmp_path):
    def build(auto_memory=True, client=None):
        config = dataclasses.replace(
            diya_config.load_config({}), db_path=str(tmp_path / "w.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"),
            dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "profile.txt"), auto_memory=auto_memory, require_token=False,
            categories=False,  # sorting each message asks the model once more; these tests count the model's calls, and tests/test_categories.py has the sorting
        )
        model = client or ByQuestionClient(extraction=["- likes tea in the morning"])
        agent = diya.Agent(config, client=model)
        return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost"), agent, model
    return build


def test_a_statement_said_in_chat_is_remembered_after_the_reply_is_made(chat_parts):
    client, agent, model = chat_parts()
    response = client.post("/api/chat", json={"message": "I like tea in the morning"})
    assert response.status_code == 200 and response.json()["answer"] == "Noted."
    assert [f["text"] for f in Memory(agent.store).facts("accepted")] == ["likes tea in the morning"]
    kinds = [call["kind"] for call in model.chat_calls]
    assert kinds.index("chat") < kinds.index("extraction")  # the reply was made first


def test_the_reply_is_saved_before_memory_starts_reading_and_sent_before_it_is_read(tmp_path):
    import asyncio

    seen = {}

    class Watching(ByQuestionClient):
        def _create(self, model, messages, tools=None, **options):
            if self.kind_of(messages) == "extraction":
                seen["roles_then"] = [m["role"] for m in seen["agent"].store.get_messages(1)]
                seen["events_then"] = list(events)
            return super()._create(model, messages, tools, **options)

    events = []
    config = make_config(tmp_path, require_token=False)
    agent = diya.Agent(config, client=Watching(extraction=["- likes tea in the morning"]))
    seen["agent"] = agent
    app = diya_web.create_app(config, agent, object())
    body = json.dumps({"message": "I like tea in the morning"}).encode()
    sent = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return sent.pop(0) if sent else {"type": "http.disconnect"}

    async def send(event):
        events.append(event["type"] + (":end" if event["type"] == "http.response.body" and not event.get("more_body") else ""))

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https", "path": "/api/chat", "raw_path": b"/api/chat",
             "query_string": b"", "server": ("localhost", 443), "client": ("127.0.0.1", 50000),
             "headers": [(b"host", b"localhost"), (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]}
    asyncio.run(app(scope, receive, send))
    assert seen["roles_then"] == ["user", "assistant"]  # the reply was already saved when memory began to read
    assert seen["events_then"][-1] == "http.response.body:end"  # and the whole response had already been sent
    assert [f["text"] for f in Memory(agent.store).facts("accepted")] == ["likes tea in the morning"]


def test_the_reply_is_the_same_whether_or_not_memory_reads_the_message(chat_parts):
    on, _, _ = chat_parts(auto_memory=True)
    assert on.post("/api/chat", json={"message": "I like tea in the morning"}).json()["answer"] == "Noted."


def test_with_the_switch_off_the_chat_makes_no_extra_call_and_remembers_nothing(chat_parts):
    client, agent, model = chat_parts(auto_memory=False)
    client.post("/api/chat", json={"message": "I like tea in the morning"})
    assert [call["kind"] for call in model.chat_calls] == ["chat"] and Memory(agent.store).facts() == []


def test_a_question_asked_in_chat_is_not_read_for_facts(chat_parts):
    client, agent, model = chat_parts()
    client.post("/api/chat", json={"message": "what is 9 times 7?"})
    assert model.asked("extraction") == [] and Memory(agent.store).facts() == []


def test_a_chat_turn_that_failed_reads_nothing(chat_parts):
    class Down(ByQuestionClient):
        def _create(self, model, messages, tools=None, **options):
            raise ConnectionError("down")

    client, agent, _ = chat_parts(client=Down())
    assert client.post("/api/chat", json={"message": "I like tea in the morning"}).status_code in (500, 503)
    assert Memory(agent.store).facts() == []


def test_memory_failing_does_not_break_the_chat_it_follows(chat_parts, monkeypatch):
    monkeypatch.setattr(dreaming.Dreamer, "capture_message", lambda self, message_id: (_ for _ in ()).throw(RuntimeError("boom")))
    client, _, _ = chat_parts()
    try:
        response = client.post("/api/chat", json={"message": "I like tea in the morning"})
    except RuntimeError:
        pytest.fail("a failure in reading for facts reached the person")
    assert response.status_code == 200 and response.json()["answer"] == "Noted."


def test_a_message_that_finds_a_read_already_running_is_skipped_not_queued(chat_parts):
    import threading

    started, release = threading.Event(), threading.Event()

    class Slow(ByQuestionClient):
        def _create(self, model, messages, tools=None, **options):
            if self.kind_of(messages) == "extraction":
                started.set()
                release.wait(5)
            return super()._create(model, messages, tools, **options)

    client, agent, model = chat_parts(client=Slow(extraction=["- likes tea in the morning", "- plays badminton on Sundays"]))
    first = threading.Thread(target=lambda: client.post("/api/chat", json={"message": "I like tea in the morning"}))
    first.start()
    assert started.wait(5)  # the first read is running, holding the one place
    client.post("/api/chat", json={"message": "I play badminton on Sundays"})  # finds it taken: skipped
    release.set()
    first.join(10)
    assert len(model.asked("extraction")) == 1
    assert [f["text"] for f in Memory(agent.store).facts()] == ["likes tea in the morning"]


def test_after_a_read_the_place_is_free_again(chat_parts):
    client, agent, model = chat_parts(client=ByQuestionClient(extraction=["- likes tea in the morning", "- plays badminton on Sundays"]))
    client.post("/api/chat", json={"message": "I like tea in the morning"})
    client.post("/api/chat", json={"message": "I play badminton on Sundays"})
    assert len(model.asked("extraction")) == 2 and len(Memory(agent.store).facts("accepted")) == 2


def test_the_same_thing_said_twice_is_remembered_once(chat_parts):
    client, agent, model = chat_parts(client=ByQuestionClient(extraction=["- likes tea in the morning", "- likes tea in the morning"]))
    client.post("/api/chat", json={"message": "I like tea in the morning"})
    client.post("/api/chat", json={"message": "I like tea in the morning"})
    facts = Memory(agent.store).facts()
    assert sorted(f["status"] for f in facts) == ["accepted", "rejected"]  # the second is a repeat of what is already known: not kept again
    assert "duplicate" in json.dumps(Memory(agent.store).events(facts[1]["id"]))


def test_a_message_that_was_not_answered_and_is_sent_again_is_read_once(chat_parts):
    calls = {"chat": 0}

    class FailsOnce(ByQuestionClient):
        def _create(self, model, messages, tools=None, **options):
            if self.kind_of(messages) == "chat":
                calls["chat"] += 1
                if calls["chat"] == 1:
                    raise ConnectionError("down")
            return super()._create(model, messages, tools, **options)

    client, agent, model = chat_parts(client=FailsOnce(extraction=["- likes tea in the morning", "- likes tea in the morning"]))
    assert client.post("/api/chat", json={"message": "I like tea in the morning"}).status_code in (500, 503)
    assert model.asked("extraction") == []  # not answered, so not read yet
    assert client.post("/api/chat", json={"message": "I like tea in the morning"}).status_code == 200  # the same words again: the same message, answered now
    assert len(model.asked("extraction")) == 1 and [f["text"] for f in Memory(agent.store).facts()] == ["likes tea in the morning"]
