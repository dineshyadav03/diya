"""diya_recall.py and what it changes in diya_memory.py (docs/RECALL_DESIGN.md, unit R1).

What this proves: while every accepted fact fits in the room, the model is told every one of them exactly as before and no embedding is asked for; once they do not, the lasting facts about the
person are always there and the rest are chosen by closeness to the message just sent; if the embeddings cannot be had the chat still gets the core and the newest facts; an embedding is made once
per fact and again only for a fact whose words changed; and a memory may KEEP more than it tells only when recall is on (the old limit is unchanged otherwise). Meaning is stood in for by a few
topic words, so nothing here needs Ollama.
"""
import dataclasses
import json

import pytest

import diya
import diya_config
import diya_memory
import diya_recall
from diya_config import ConfigError, load_config
from diya_db import Store
from diya_memory import BudgetExceeded, Memory, open_memory

TOPICS = ["job", "dog", "exam", "bus", "keys", "trip", "gym", "knee"]


def fake_embed(text):
    """A vector with one dimension per topic word: the facts and the question about the same thing point the same way."""
    low = text.casefold()
    return [1.0 if topic in low else 0.0 for topic in TOPICS] + [0.01]


class Counting:
    def __init__(self, fn=fake_embed):
        self.calls, self.fn = [], fn

    def __call__(self, text):
        self.calls.append(text)
        return self.fn(text)


def broken(text):
    raise ConnectionError("ollama is not running")


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "recall.db"))


@pytest.fixture
def memory(store):
    return Memory(store, store_limit=20000)


FILLER = [f"Owns a {colour} umbrella number {n} for the rainy season." for n, colour in enumerate(["red", "blue", "green", "grey", "pink", "gold", "teal", "lilac", "amber", "plum"] * 3)]
ABOUT = {
    "job": "Hospital pharmacy job with a long shift pattern.",
    "dog": "The dog hates the vacuum cleaner.",
    "exam": "Nursing licence exam falls in December.",
    "bus": "Takes the 7:40 bus when the scooter is away.",
    "keys": "Spare keys are with a neighbour.",
    "trip": "Saving up for a trip abroad.",
    "gym": "Gym membership renews in November.",
    "knee": "Has a sore knee from sport.",
}


def fill(memory, with_about=True, filler=FILLER):
    if with_about:
        for text in ABOUT.values():
            memory.add_manual(text, "api")
    for text in filler:
        memory.add_manual(text, "api")


def told(memory, query, embed=fake_embed, room=500):
    old = diya_memory.MAX_PROFILE_CHARS
    diya_memory.MAX_PROFILE_CHARS = room
    try:
        return memory.render_for_model(query=query, embed=embed, model="fake")
    finally:
        diya_memory.MAX_PROFILE_CHARS = old


# --- under the limit, nothing is different -------------------------------------------------------------------------------


def test_everything_that_fits_is_told_exactly_as_before_and_nothing_is_embedded(memory):
    memory.add_manual("Name is Alex.", "api")
    memory.add_manual("Has a cat named Pixel.", "api")
    count = Counting()
    out = memory.render_for_model(query="what is my cat called", embed=count, model="fake")
    assert out == memory.render_for_model()
    assert "Pixel" in out and "Alex" in out
    assert count.calls == []


def test_choose_returns_every_fact_when_they_all_fit():
    facts = [{"id": 1, "text": "Likes tea.", "text_key": "a", "person": None}, {"id": 2, "text": "Has a dog.", "text_key": "b", "person": None}]
    count = Counting()
    assert diya_recall.choose(facts, "dog", 1000, lambda picked: " ".join(f["text"] for f in picked), embed=count) == facts
    assert count.calls == []


# --- over the limit, the facts for this message ----------------------------------------------------------------------------


@pytest.mark.parametrize("topic", TOPICS)
def test_the_fact_a_question_is_about_is_told_though_it_is_not_the_newest(memory, topic):
    fill(memory)
    assert len(memory.render()) > 500
    out = told(memory, f"tell me about my {topic}")
    assert ABOUT[topic] in out
    assert len(out) <= 500


def test_without_relevance_the_old_facts_fall_out_which_is_what_recall_fixes(memory):
    fill(memory)
    out = told(memory, "tell me about my job", embed=None)
    assert ABOUT["job"] not in out  # the newest filler fills the room: the fact asked about is the oldest
    assert "umbrella" in out


def test_what_is_told_is_in_the_order_the_facts_were_kept(memory):
    fill(memory)
    out = [line for line in told(memory, "my keys and my dog").splitlines() if not line.startswith("(")]  # the closing note is not a fact
    assert out == sorted(out, key=lambda line: memory.render().splitlines().index(line))


def test_a_partial_view_says_so_and_stays_inside_the_room(memory):
    fill(memory)
    out = told(memory, "tell me about my job")
    assert out.splitlines()[-1] == diya_memory.partial_note(len(memory.facts()) - (len(out.splitlines()) - 1))  # it counts what is not shown
    assert "never told" in out and len(out) <= 500


def test_a_whole_view_has_no_note(memory):
    memory.add_manual("Name is Alex.", "api")
    assert "not shown" not in memory.render_for_model()


def test_lasting_facts_about_the_person_are_always_told_even_when_the_question_is_about_something_else(memory):
    memory.add_manual("Name is Alex.", "api")
    memory.add_manual("Allergic to peanuts.", "api")
    fill(memory)
    out = told(memory, "tell me about my dog")
    assert "Name is Alex." in out and "Allergic to peanuts." in out
    assert ABOUT["dog"] in out


def test_a_crowd_of_lasting_facts_cannot_crowd_out_the_ones_the_question_is_about(memory):
    for n in range(40):
        memory.add_manual(f"Lives in a town called Place{n} nearby.", "api")
    dog_facts = ["The dog hates the vacuum cleaner.", "The dog sleeps by the door.", "The dog needs a walk at six."]
    for text in dog_facts:
        memory.add_manual(text, "api")
    out = told(memory, "my dog", room=600)
    lines = out.splitlines()
    assert all(f"- {text[0].lower()}{text[1:]}" in lines or f"- {text}" in lines for text in dog_facts)
    assert len(out) <= 600
    assert sum("Lives in" in line for line in lines) < 40


def test_a_fact_about_someone_else_is_still_told_under_their_name(memory):
    fill(memory)
    memory.add_manual("Likes the green umbrella best.", "api")
    memory.set_person(memory.add_manual("Works as an architect in Lisbon.", "api"), "Maya", "api")
    out = told(memory, "what does Maya do for a living", room=600)
    assert "Maya" in out and "architect" in out
    assert len(out) <= 600


# --- when the embeddings cannot be had ----------------------------------------------------------------------------------


def test_a_chat_never_fails_because_recall_did(memory):
    fill(memory)
    out = told(memory, "tell me about my job", embed=broken)
    assert 0 < len(out) <= 500
    assert "umbrella" in out  # the newest, as without recall


def test_no_question_means_no_embedding_and_the_newest(memory):
    fill(memory)
    count = Counting()
    out = told(memory, "", embed=count)
    assert count.calls == [] and len(out) <= 500


# --- the embeddings are kept ------------------------------------------------------------------------------------------------


def test_each_fact_is_embedded_once_across_questions(memory):
    fill(memory)
    count = Counting()
    told(memory, "my job", embed=count)
    first = len(count.calls)
    told(memory, "my dog", embed=count)
    assert len(count.calls) == first + 1  # only the new question
    rows = memory.store.connect().execute("SELECT COUNT(*) FROM fact_embeddings WHERE model = 'fake'").fetchone()[0]
    assert 0 < rows <= len(memory.accepted_texts())


def test_a_fact_whose_words_changed_is_embedded_again_and_one_that_did_not_is_not(memory):
    fill(memory)
    count = Counting()
    told(memory, "my job", embed=count)
    count.calls.clear()
    memory.add_manual("Adopted a second dog.", "api")
    told(memory, "my job", embed=count)
    assert count.calls == ["my job", "Adopted a second dog."]


def test_a_different_embedding_model_has_its_own_rows(store):
    facts = [{"id": 1, "text": "Has a dog.", "text_key": "k", "person": None}]
    count = Counting()
    diya_recall.vectors(store, facts, count, "model-a")
    diya_recall.vectors(store, facts, count, "model-b")
    diya_recall.vectors(store, facts, count, "model-a")
    assert len(count.calls) == 2


def test_the_stored_vector_is_what_the_embedder_gave(store):
    facts = [{"id": 7, "text": "Has a dog.", "text_key": "k", "person": None}]
    got = diya_recall.vectors(store, facts, fake_embed, "m")
    row = store.connect().execute("SELECT vector FROM fact_embeddings WHERE fact_id = 7").fetchone()[0]
    assert json.loads(row) == got[7] == fake_embed("Has a dog.")


# --- the pieces --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Name is Alex.", "Allergic to peanuts.", "Is vegetarian.", "Lives in Pune.", "Works as a nurse.", "Birthday is on 14 May.", "Has a sister, Maya.", "Mother lives in Nagpur."])
def test_lasting_facts_are_recognised(text):
    assert diya_recall.is_core(text)


@pytest.mark.parametrize("text", ["Likes tea in the morning.", "Plays badminton on Sunday evenings.", "Takes the 7:40 bus.", "Gym membership renews in November."])
def test_passing_facts_are_not_core(text):
    assert not diya_recall.is_core(text)


def test_the_question_is_the_last_two_things_the_person_said():
    history = [
        {"role": "system", "content": "voice"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
        {"role": "tool", "content": "tool output"},
        {"role": "user", "content": "third"},
    ]
    assert diya_recall.query_of(history) == "second third"


def test_a_long_question_is_cut_from_the_front_and_odd_messages_are_skipped():
    history = [{"role": "user", "content": None}, {"role": "user", "content": ["a list"]}, {"role": "user", "content": "x" * 900 + "END"}]
    out = diya_recall.query_of(history)
    assert len(out) == diya_recall.QUERY_CHARS and out.endswith("END")
    assert diya_recall.query_of([]) == ""


def test_cosine_of_nothing_is_zero_not_an_error():
    assert diya_recall.cosine([0, 0], [1, 1]) == 0.0
    assert diya_recall.cosine([1, 0], [1, 0]) == pytest.approx(1.0)


# --- what may be kept ---------------------------------------------------------------------------------------------------------


def test_the_old_limit_is_unchanged_without_a_larger_store(store):
    memory = Memory(store)
    assert memory.store_limit == diya_memory.MAX_PROFILE_CHARS
    with pytest.raises(BudgetExceeded):
        for n in range(200):
            memory.add_manual(f"Owns umbrella number {n} for the rainy season, kept by the door.", "api")


def test_a_larger_store_keeps_more_than_it_tells(store):
    memory = Memory(store, store_limit=20000)
    for n in range(80):
        memory.add_manual(f"Owns umbrella number {n} for the rainy season, kept by the door.", "api")
    assert len(memory.render()) > diya_memory.MAX_PROFILE_CHARS
    assert len(memory.render_for_model()) <= diya_memory.MAX_PROFILE_CHARS


def test_even_a_larger_store_has_a_limit(store):
    memory = Memory(store, store_limit=300)
    with pytest.raises(BudgetExceeded, match="of 300 characters"):
        for n in range(20):
            memory.add_manual(f"Owns umbrella number {n} for the rainy season.", "api")


def test_open_memory_follows_the_settings(store):
    on = dataclasses.replace(load_config(), recall=True, memory_store_chars=12345)
    off = dataclasses.replace(load_config(), recall=False, memory_store_chars=12345)
    assert open_memory(store, on).store_limit == 12345
    assert open_memory(store, off).store_limit == diya_memory.MAX_PROFILE_CHARS


def test_with_recall_off_every_fact_is_still_told_even_past_the_room(store):
    kept = Memory(store, store_limit=20000)
    for n in range(80):
        kept.add_manual(f"Owns umbrella number {n} for the rainy season, kept by the door.", "api")
    off = open_memory(store, dataclasses.replace(load_config(), recall=False))
    assert off.render_for_model(query="umbrella", embed=fake_embed, model="fake") == off.render_for_model()
    assert len(off.render_for_model()) > diya_memory.MAX_PROFILE_CHARS


# --- the settings -------------------------------------------------------------------------------------------------------------


def test_recall_is_on_by_default_in_the_program_and_the_store_is_twenty_thousand(monkeypatch):
    monkeypatch.delenv("DIYA_RECALL")
    config = load_config()
    assert config.recall is True and config.memory_store_chars == 20000


def test_recall_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("DIYA_RECALL", "0")
    assert load_config().recall is False


@pytest.mark.parametrize("value", ["1999", "1000001", "lots", "-5"])
def test_the_store_size_is_checked(monkeypatch, value):
    monkeypatch.setenv("DIYA_MEMORY_STORE_CHARS", value)
    with pytest.raises(ConfigError, match="DIYA_MEMORY_STORE_CHARS"):
        load_config()


@pytest.mark.parametrize("value", ["2000", "50000", "1000000"])
def test_a_store_size_in_range_is_accepted(monkeypatch, value):
    monkeypatch.setenv("DIYA_MEMORY_STORE_CHARS", value)
    assert load_config().memory_store_chars == int(value)


# --- in the chat ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def agent(tmp_path):
    config = dataclasses.replace(
        load_config(), db_path=str(tmp_path / "agent.db"), profile_path=str(tmp_path / "agent_profile.txt"), notes_dir=str(tmp_path), recall=True, keep_warm=False
    )
    return diya.Agent(config)


def test_the_model_is_told_the_facts_for_the_last_message(agent, monkeypatch):
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", 500)
    memory = open_memory(agent.store, agent.config)
    fill(memory)
    monkeypatch.setattr(agent, "embed", fake_embed)
    history = [{"role": "user", "content": "what do you know about my knee"}]
    system = "\n".join(m["content"] for m in agent.with_profile(history) if m["role"] == "system")
    assert ABOUT["knee"] in system


def test_with_recall_off_the_chat_is_told_what_it_always_was(agent, monkeypatch):
    off = dataclasses.replace(agent.config, recall=False)
    agent.config = off
    memory = open_memory(agent.store, off)
    memory.add_manual("Has a cat named Pixel.", "api")
    monkeypatch.setattr(agent, "embed", broken)
    system = "\n".join(m["content"] for m in agent.with_profile([{"role": "user", "content": "hi"}]) if m["role"] == "system")
    assert "Pixel" in system


def test_the_memory_summary_says_what_is_kept_and_what_is_told(tmp_path):
    from fastapi.testclient import TestClient

    import diya_web
    from fakes import FakeClient, text_reply

    def summary(recall):
        config = dataclasses.replace(
            load_config(), db_path=str(tmp_path / f"api{recall}.db"), profile_path=str(tmp_path / f"p{recall}.txt"), notes_dir=str(tmp_path), recall=recall, require_token=False, keep_warm=False
        )
        agent = diya.Agent(config, client=FakeClient([text_reply("ok")]))
        open_memory(agent.store, config).add_manual("has a cat named Pixel", "api")
        client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
        return client.get("/api/memory").json()["summary"]

    on, off = summary(True), summary(False)
    assert (on["limit"], on["told"], on["used"]) == (20000, 2000, len("- has a cat named Pixel"))
    assert (off["limit"], off["told"]) == (2000, 2000)


def test_the_migration_that_makes_the_table_is_numbered_sixteen():
    import diya_db

    assert [number for number, _ in diya_db.MIGRATIONS][-1] >= 16
    assert any(number == 16 and any("fact_embeddings" in statement for statement in statements) for number, statements in diya_db.MIGRATIONS)


def test_the_vector_of_a_fact_that_is_no_longer_accepted_is_removed(store, memory):
    """DIYA-024: a derived vector goes when the fact stops being one the model is told, so a forgotten thing does not linger as an embedding."""
    kept = memory.add_manual("Has a job at the dog shelter", "api")
    gone = memory.add_manual("Owns a dog named Rocky", "api")
    def accepted():
        return [{"id": f["id"], "text": f["text"], "text_key": diya_memory.text_key(f["text"])} for f in memory.facts("accepted")]

    diya_recall.vectors(store, accepted(), fake_embed, "m")

    def stored():
        conn = store.connect()
        try:
            return {row[0] for row in conn.execute("SELECT fact_id FROM fact_embeddings")}
        finally:
            conn.close()

    assert stored() == {kept, gone}
    memory.decide(gone, "retire", "api")
    diya_recall.vectors(store, accepted(), fake_embed, "m")
    assert stored() == {kept}
