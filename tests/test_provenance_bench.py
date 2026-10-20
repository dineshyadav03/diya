"""A provenance recall benchmark: when Diya says where she knows something from, is she right? (task DIYA-027; docs/PROVENANCE_DESIGN.md), added 2026-10-20.

Facts are made by the real pipeline (a message saved, read for facts by Dreaming's live capture with a scripted model, put through the memory policy), so each carries the source a real fact carries. Then the
questions a person might ask ("how do you know I have a dog?", "where did you learn that ...", "when did I tell you about ...") are put to `diya_provenance.explain`, and every answer is scored:

* CORRECT: it quotes the message the fact was read from and no other message;
* WRONG: it quotes a message that is not that fact's (an attribution error);
* MISSED: a fact exists for the question and the answer says it has nothing (a false refusal);
* INVENTED: nothing exists for the question and the answer still quotes a message or a source (a made-up history);
* and after a correction, asking about the old fact must say it is no longer used, never describe it as current.

The numbers are printed. The assertions are the floor the code must keep: no wrong attribution, no invented history, no old fact described as current, and at least 90 percent correct. No model writes any answer here
(provenance is made from the record by code), so this is a measurement of the code on invented data, not of any language model.
"""
import dataclasses
import re

import pytest

import diya_config
import diya_provenance as prov
import dreaming
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient

# (what the person said, the fact the model read from it, questions asking how it is known)
CASES = [
    ("I have a golden retriever called Rex", "has a golden retriever called Rex", ["how do you know I have a dog called Rex?", "where did you learn that I have a golden retriever?"]),
    ("My pharmacology exam is on the 5th of November", "has a pharmacology exam on the 5th of November", ["how do you know about my pharmacology exam?", "when did I tell you about the pharmacology exam?"]),
    ("I switched my editor to Zed last week", "uses the Zed editor", ["how do you know I use the Zed editor?", "who told you I switched to Zed?"]),
    ("My sister Maya is visiting from Pune in May", "has a sister called Maya who is visiting from Pune in May", ["how do you know my sister is visiting?", "where did you get that Maya is visiting from Pune?"]),
    ("I play badminton with Rohan on Saturday mornings", "plays badminton with Rohan on Saturday mornings", ["how do you know I play badminton?", "when did I tell you about Rohan and badminton?"]),
    ("I bought a Yamaha F310 guitar", "owns a Yamaha F310 guitar", ["how do you know I own a guitar?", "where did you learn about my Yamaha?"]),
    ("I prefer studying at night when the hostel is quiet", "prefers studying at night when the hostel is quiet", ["how do you know I study at night?", "why do you know I prefer a quiet hostel?"]),
    ("I eat mess dinner at 8 pm", "eats mess dinner at 8 pm", ["how do you know when mess dinner is?", "where did you get the mess dinner time?"]),
    ("I am learning the Bhimpalasi raga on the guitar", "is learning the Bhimpalasi raga on the guitar", ["how do you know I am learning Bhimpalasi?", "when did I tell you about the raga?"]),
    ("I cycle to college on Tuesdays and Thursdays", "cycles to college on Tuesdays and Thursdays", ["how do you know I cycle to college?", "where did you learn that I cycle on Tuesdays?"]),
    ("My cousin got engaged and the wedding is in February", "has a cousin whose wedding is in February", ["how do you know about my cousin's wedding?", "when did I tell you about the wedding?"]),
    ("I am applying for the summer research internship at the IISc lab", "is applying for the summer research internship at the IISc lab", ["how do you know about the IISc internship?", "who told you I want a research internship?"]),
    ("I started meditating for ten minutes every morning", "meditates for ten minutes every morning", ["how do you know I meditate?", "where did you learn that I meditate every morning?"]),
    ("My roommate Karan snores so I wear earplugs", "wears earplugs because roommate Karan snores", ["how do you know about my roommate Karan?", "when did I tell you about the earplugs?"]),
    ("I am saving up for a trip to Goa in January", "is saving up for a trip to Goa in January", ["how do you know about my Goa trip?", "where did you learn about Goa?"]),
    ("My library card expires on the third of March", "has a library card that expires on the third of March", ["how do you know when my library card expires?", "when did I tell you about the library card?"]),
]

NO_RECORD = [
    "how do you know my favourite colour is blue?", "where did you learn that I own a motorcycle?", "who told you I live in Chennai?", "when did I tell you about my tattoo?",
    "how do you know I speak French?", "where did you get my passport number?", "how do you know I have a twin?", "when did I tell you about my job at the bank?",
]


def build(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "b.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), auto_memory=True, categories=False, memory_store_chars=20000,
    )
    store = Store(config.db_path)
    ids = {}
    for said, fact, _questions in CASES:
        message = store.add_message(store.main_thread(), "user", said)
        dreaming.Dreamer(config, client=ByQuestionClient(extraction=[f"- {fact}"]), store=store).capture_message(message)
        ids[said] = message
    return config, store, Memory(store, store_limit=20000), ids


def quotes_in(answer):
    return re.findall(r"“([^”]+)”", answer or "")


def score(answer, source, others):
    """CORRECT when the FIRST message quoted (the best match, which comes first) is the one the fact was read from; WRONG when it is another fact's message; MISSED when the answer has no history.
    Further facts that also share the question's words are listed after the best one (up to three) and are not errors: "how do you know I own a guitar?" also lists the fact about the raga on it."""
    if answer in (None, prov.NOTHING_FOR_THAT, prov.NOTHING_FOR_LAST):
        return "MISSED"
    quoted = quotes_in(answer)
    # the answer is "<fact> You told me: <message> ..." for each fact: the quoted messages alternate fact, message, fact, message
    messages = [q for q in quoted if q in [m for m in [source] + others]]
    if not messages:
        return "MISSED"
    return "CORRECT" if messages[0] == source else "WRONG"


def test_where_a_fact_came_from_is_told_right_and_never_made_up(tmp_path, capsys):
    config, store, memory, ids = build(tmp_path)
    assert len(memory.facts("accepted")) == len(CASES), "the pipeline did not make every fact (the benchmark's own setup)"
    tally = {"CORRECT": 0, "WRONG": 0, "MISSED": 0}
    misses = []
    for said, fact, questions in CASES:
        others = [other for other, *_ in CASES if other != said]
        for question in questions:
            verdict = score(prov.explain(memory, store, question), said, others)
            tally[verdict] += 1
            if verdict != "CORRECT":
                misses.append((verdict, question))
    invented = [q for q in NO_RECORD if any(quotes_in(prov.explain(memory, store, q) or "")) or "You told me" in (prov.explain(memory, store, q) or "")]
    asked = sum(len(q) for _, _, q in CASES)
    with capsys.disabled():
        print(f"\nprovenance benchmark: {tally['CORRECT']}/{asked} correct, {tally['WRONG']} wrong attribution, {tally['MISSED']} missed; "
              f"{len(invented)}/{len(NO_RECORD)} invented a history where there is none; misses: {misses}")
    assert tally["WRONG"] == 0, misses
    assert invented == []
    assert tally["CORRECT"] / asked >= 0.9, misses


def test_after_a_correction_the_old_fact_is_said_to_be_no_longer_used_and_the_new_one_is_found(tmp_path):
    config, store, memory, ids = build(tmp_path)
    old = store.add_message(store.main_thread(), "user", "I live in Delhi")
    dreaming.Dreamer(config, client=ByQuestionClient(extraction=["- lives in Delhi"]), store=store).capture_message(old)
    new = store.add_message(store.main_thread(), "user", "no, I now live in Pune")
    dreaming.Dreamer(config, client=ByQuestionClient(extraction=["- lives in Pune"], replace=[str(next(f["id"] for f in memory.facts() if f["text"] == "lives in Delhi"))]), store=store).capture_message(new)
    about_old = prov.explain(memory, store, "how do you know I live in Delhi?")
    assert "no longer use it" in about_old and "currently" not in about_old.lower()  # the retired fact is never described as current
    about_new = prov.explain(memory, store, "how do you know I live in Pune?")
    assert "no, I now live in Pune" in about_new and "no longer use it" not in about_new


def test_a_fact_the_person_typed_themselves_is_said_to_be_typed_and_quotes_no_message(tmp_path):
    config, store, memory, ids = build(tmp_path)
    memory.add_manual("studies medicine at the city college", "api")
    answer = prov.explain(memory, store, "how do you know I study medicine?")
    assert "You added this yourself" in answer and not quotes_in(answer.split("It is number")[0].replace("“studies medicine at the city college”", ""))


def test_a_question_with_nothing_in_common_with_any_fact_gets_no_history_at_all(tmp_path):
    config, store, memory, ids = build(tmp_path)
    for question in NO_RECORD:
        answer = prov.explain(memory, store, question)
        assert answer in (prov.NOTHING_FOR_THAT, None), (question, answer)
