"""What Diya is waiting to ask you, on the Today page (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5, first part): a number from the memory, a number in the
day's brief, and a section on the page that says so and points to the Memory page.

What this proves: the number counts exactly the candidates the memory policy left an `ask:` flag on (not accepted, rejected or retired facts, and not
candidates with no such flag); it is a bare number, so nothing a model wrote reaches the day; the brief has it on every call and it is 0 when nothing waits;
and the page shows the section only when there is something to answer, in the right number, with the link.
"""
import dataclasses
import pathlib
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from diya_db import Store
from diya_memory import Memory
from fakes import FakeClient, text_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "app" / "today" / "page.js").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 10, 10, 15)


def waiting(memory, text, flags=(), position=0):
    fact_id = memory.add_candidate(text, batch_first=1, batch_last=1, position=position, model="m", extracted_at="2026-01-01T00:00:00+00:00", raw="- " + text)
    if flags:
        memory.set_flags(fact_id, list(flags), "system")
    return fact_id


@pytest.fixture
def memory(tmp_path):
    return Memory(Store(str(tmp_path / "q.db")))


def test_only_a_candidate_with_the_policys_flag_is_a_question(memory):
    assert memory.questions_waiting() == 0
    waiting(memory, "a plain candidate")
    waiting(memory, "has a note but no question", flags=["ungrounded"], position=1)
    assert memory.questions_waiting() == 0
    waiting(memory, "private", flags=["ask:sensitive:model_private"], position=2)
    waiting(memory, "may replace", flags=["ask:conflict:replaces:1"], position=3)
    waiting(memory, "not sure", flags=["ungrounded", "ask:doubt:ungrounded"], position=4)
    assert memory.questions_waiting() == 3


def test_a_fact_is_one_question_however_many_flags_of_the_policys_it_carries(memory):
    waiting(memory, "odd", flags=["ask:doubt:ungrounded", "ask:sensitive:model_private"])
    assert memory.questions_waiting() == 1


@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_a_question_that_was_answered_is_no_longer_counted(memory, decision):
    fact = waiting(memory, "private", flags=["ask:sensitive:model_private"])
    assert memory.questions_waiting() == 1
    memory.decide(fact, decision, "api")
    assert memory.questions_waiting() == 0


def test_a_fact_that_was_asked_about_and_then_forgotten_is_not_counted(memory):
    fact = waiting(memory, "private", flags=["ask:sensitive:model_private"])
    memory.decide(fact, "accept", "api")
    memory.decide(fact, "retire", "api")
    assert memory.questions_waiting() == 0


@pytest.fixture
def parts(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(diya_config.load_config(), db_path=str(data / "t.db"), profile_path=str(data / "p.txt"), dream_state_path=str(data / "s.json"),
                                 dream_log_path=str(data / "l"), dream_pending_path=str(data / "p.jsonl"), require_token=False)
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 3), clock=lambda: NOW)
    return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost"), Memory(agent.store)


def test_the_brief_says_how_many_questions_wait_and_it_is_zero_when_none_do(parts):
    client, memory = parts
    assert client.get("/api/today").json()["questions"] == 0
    waiting(memory, "the door code is something private", flags=["ask:sensitive:model_private"])
    waiting(memory, "works as a nurse", flags=["ask:conflict:replaces:1"], position=1)
    body = client.get("/api/today").json()
    assert body["questions"] == 2 and isinstance(body["questions"], int)


def test_nothing_a_model_wrote_reaches_the_day_through_the_questions(parts):
    client, memory = parts
    waiting(memory, "SECRET-WORDS-FROM-THE-MODEL", flags=["ask:sensitive:model_private"])
    assert "SECRET-WORDS-FROM-THE-MODEL" not in client.get("/api/today").text


def test_the_headline_and_the_rest_of_the_brief_are_what_they_were(parts):
    client, memory = parts
    waiting(memory, "private", flags=["ask:sensitive:model_private"])
    body = client.get("/api/today").json()
    assert body["headline"] == "Nothing is due today." and body["counts"]["due_now"] == 0


def test_the_page_shows_the_section_only_when_something_waits_and_links_to_memory():
    assert "{data.questions > 0 && (" in PAGE
    assert '<h2 id="today-questions">' in PAGE and "Questions from Diya ({data.questions})" in PAGE and '<Link href="/memory">Open Memory</Link>' in PAGE


def test_the_page_says_one_thing_is_or_many_things_are_and_that_nothing_reaches_the_model_unanswered():
    assert "data.questions === 1 ? 'One thing' : `${data.questions} things`" in PAGE
    assert "data.questions === 1 ? 'is' : 'are'" in PAGE
    assert "None of it is told to the model until you say yes." in PAGE


def test_the_page_still_promises_only_what_is_true_of_it():
    assert "Nothing here is written by Diya&rsquo;s model." in PAGE  # the questions are a number, so this stays true


def test_the_section_sits_before_the_repeating_reminders_and_does_not_replace_the_brief_check():
    assert PAGE.index('aria-labelledby="today-questions"') < PAGE.index('aria-labelledby="today-repeating"')
    assert "Array.isArray(body.repeating)" in PAGE  # an API that sends no number still gives a page: the section just is not there
