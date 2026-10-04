"""The switch (docs/STAGE2_DESIGN.md, D7, D8 and unit 5): what the model is told is now the ACCEPTED facts
of reviewed memory, and the old user_profile.txt is imported into it once.

What this proves: only an accepted fact is ever given to the model -- never a staged one, a candidate, a
rejected one or a retired one -- in exactly the shape (header, bullets) it always had; the model cannot lose
what it knew because the switch happened (the old file is imported on first use, by every entry point,
without changing the file, without ever bringing back what someone retired, and without re-reading the
file afterwards); the person is told at startup what the model is being told and what is waiting; and the
API and the terminal chat both tell them.
"""
import dataclasses
import hashlib
import os
import pathlib
import types

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_memory
import diya_web
from diya_db import Store
from diya_memory import Memory, SourceUnreadable, ingest_queue
from dreaming import Dreamer
from fakes import FakeClient, text_reply

HEADER = "What you know about the user so far:\n"
STAGED_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def config(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "dentist.txt").write_text("Dentist appointment on Tuesday at 3pm.")
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(data / "switch.db"),
        profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"),
        dream_log_path=str(data / "dream.log"),
        dream_pending_path=str(data / "pending.jsonl"),
        notes_dir=str(notes),
        require_token=False,
    )


@pytest.fixture
def memory(config):
    return Memory(Store(config.db_path))


def agent_for(config, *replies):
    return diya.Agent(config, client=FakeClient(replies))


def write_profile(config, text):
    pathlib.Path(config.profile_path).write_bytes(text.encode("utf-8") if isinstance(text, str) else text)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


HISTORY = [{"role": "user", "content": "hi"}]


# --- what the model is told -------------------------------------------------------------------------

def test_the_model_is_told_the_accepted_facts_in_the_shape_it_always_had(config, memory):
    memory.add_manual("likes tea", "cli")
    memory.add_manual("has a cat named Pixel", "cli")
    told = agent_for(config).with_profile(list(HISTORY))
    assert told == [{"role": "system", "content": HEADER + "- likes tea\n- has a cat named Pixel"}] + HISTORY


def test_nothing_accepted_means_the_history_is_returned_as_it_is(config, memory):
    history = list(HISTORY)
    assert agent_for(config).with_profile(history) is history  # not even a copy: nothing was added


@pytest.mark.parametrize("status", ["candidate", "rejected", "retired"])
def test_a_fact_that_is_not_accepted_is_never_told(config, memory, status):
    fact_id = memory.add_candidate("has a cat named Pixel", batch_first=1, batch_last=1, position=0, model="m",
                                   extracted_at=STAGED_AT, raw="- has a cat named Pixel")
    for action in {"candidate": [], "rejected": ["reject"], "retired": ["accept", "retire"]}[status]:
        memory.decide(fact_id, action, "cli")
    history = list(HISTORY)
    assert agent_for(config).with_profile(history) is history
    memory.add_manual("likes tea", "cli")
    told = agent_for(config).with_profile(list(HISTORY))[0]["content"]
    assert "Pixel" not in told and "- likes tea" in told


def test_a_fact_dreaming_staged_never_reaches_the_model_until_it_is_accepted(config, memory):
    """Stage 2's whole point, end to end with the real producer: staged, then ingested as a candidate,
    then accepted -- and only then told."""
    store = Store(config.db_path)
    store.add_message(store.create_thread(), "user", "I adopted a cat named Pixel")
    Dreamer(config, client=FakeClient([text_reply("- has a cat named Pixel")]), store=store).dream_cycle()
    agent = agent_for(config)
    history = list(HISTORY)
    assert agent.with_profile(history) is history  # staged
    ingest_queue(memory, config)
    assert agent.with_profile(history) is history  # a candidate
    memory.decide(1, "accept", "cli")
    assert agent.with_profile(list(HISTORY))[0]["content"] == HEADER + "- has a cat named Pixel"  # accepted
    memory.decide(1, "retire", "cli")
    assert agent.with_profile(history) is history  # and retired: gone again on the very next call


def test_it_reflects_memory_as_it_is_now_not_as_it_was_when_the_agent_started(config, memory):
    agent = agent_for(config)
    assert agent.with_profile(list(HISTORY)) == HISTORY
    fact_id = memory.add_manual("likes tea", "cli")
    assert agent.with_profile(list(HISTORY))[0]["content"] == HEADER + "- likes tea"
    memory.decide(fact_id, "retire", "cli")
    assert agent.with_profile(list(HISTORY)) == HISTORY


def test_the_memory_message_and_the_fact_share_instructions_stay_one_system_message(config, memory):
    memory.add_manual("likes tea", "cli")
    agent = agent_for(config)
    sent = agent._model_messages(agent.with_profile([{"role": "user", "content": "My flight is on Friday at 6."}]), fact_share=True)
    assert [m["role"] for m in sent] == ["system", "user"]
    assert sent[0]["content"].startswith(diya.FACT_SHARE_PROMPT) and sent[0]["content"].endswith(HEADER + "- likes tea")


def test_through_the_api_the_model_receives_the_accepted_fact_and_the_thread_never_stores_it(config, memory):
    memory.add_manual("plays guitar", "cli")
    memory.add_candidate("works at a bank", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- x")
    model = FakeClient([text_reply("Nice.")])
    agent = diya.Agent(config, client=model)
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")

    body = client.post("/api/chat", json={"message": "hi"}).json()

    assert model.chat_calls[0]["messages"][0] == {"role": "system", "content": HEADER + "- plays guitar"}
    assert "bank" not in str(model.chat_calls[0]["messages"])
    assert all(m["role"] != "system" for m in agent.store.get_history(body["thread_id"]))


# --- the old profile file: imported once, never lost, never re-read -----------------------------------

def test_a_profile_that_exists_when_the_switch_happens_is_not_lost(config, memory):
    write_profile(config, "- likes tea\n- has a cat named Pixel\n- works in the evenings\n")
    told = agent_for(config).with_profile(list(HISTORY))
    assert told[0]["content"] == HEADER + "- likes tea\n- has a cat named Pixel\n- works in the evenings"  # exactly as before
    assert [(f["source"], f["status"]) for f in memory.facts()] == [("legacy_profile", "accepted")] * 3


def test_the_old_file_is_never_changed_and_never_read_again(config, memory):
    write_profile(config, "- likes tea\n")
    before = sha(config.profile_path)
    agent = agent_for(config)
    agent.with_profile(list(HISTORY))
    write_profile(config, "- likes tea\n- a line added by hand afterwards\n")  # the file is no longer where facts come from
    added = sha(config.profile_path)
    assert agent_for(config).with_profile(list(HISTORY))[0]["content"] == HEADER + "- likes tea"
    assert agent.with_profile(list(HISTORY))[0]["content"] == HEADER + "- likes tea"
    assert sha(config.profile_path) == added != before  # untouched by any of it


def test_every_agent_imports_on_its_first_use_but_only_once_ever(config, memory, monkeypatch):
    write_profile(config, "- likes tea\n- has a cat\n")
    first, second = agent_for(config), agent_for(config)
    first.with_profile(list(HISTORY))
    second.with_profile(list(HISTORY))
    assert memory.accepted_texts() == ["likes tea", "has a cat"]  # not doubled
    calls = []
    real = diya_memory.import_legacy_profile
    monkeypatch.setattr(diya_memory, "import_legacy_profile", lambda *a, **k: calls.append(1) or real(*a, **k))
    third = agent_for(config)
    third.with_profile(list(HISTORY))  # already imported: nothing to do
    assert calls == []


def test_the_import_happens_on_the_first_call_only_not_on_every_turn(config, memory, monkeypatch):
    agent = agent_for(config)
    checks = []
    real = agent.ensure_profile_imported
    monkeypatch.setattr(agent, "ensure_profile_imported", lambda: checks.append(1) or real())
    for _ in range(5):
        agent.with_profile(list(HISTORY))
    assert checks == [1]


def test_a_fact_someone_retired_does_not_come_back_from_the_old_file(config, memory):
    write_profile(config, "- likes tea\n- has a cat named Pixel\n")
    agent_for(config).with_profile(list(HISTORY))
    memory.decide(1, "retire", "cli")
    told = agent_for(config).with_profile(list(HISTORY))[0]["content"]  # a new agent, the file still says "likes tea"
    assert told == HEADER + "- has a cat named Pixel"


def test_ensure_profile_imported_says_what_it_did_and_does_nothing_when_there_is_nothing_to_do(config, memory):
    agent = agent_for(config)
    assert agent.ensure_profile_imported() is None  # no file
    write_profile(config, "  \n\n")
    assert agent.ensure_profile_imported() is None  # an empty one
    write_profile(config, "- likes tea\n- has a cat\n")
    result = agent.ensure_profile_imported()
    assert (result.imported, result.already) == (2, 0)
    assert agent.ensure_profile_imported() is None  # never twice


def test_a_profile_that_cannot_be_read_is_an_error_not_a_silently_empty_memory(config, memory):
    os.mkdir(config.profile_path)
    with pytest.raises(SourceUnreadable):
        agent_for(config).with_profile(list(HISTORY))


# --- what the person is told at startup ---------------------------------------------------------------

def lines_for(config):
    return diya.memory_startup_lines(diya.Agent(config, client=FakeClient()))


def test_a_fresh_install_says_nothing_is_told_and_nothing_waits(config):
    assert lines_for(config) == [
        "Memory: 0 accepted facts (0 of 2000 characters) are given to the model; 0 candidates wait for review "
        "(`python diya_review.py list`)."
    ]


def test_the_first_start_after_the_switch_says_the_old_profile_was_taken_in_and_only_the_first(config, memory):
    write_profile(config, "- likes tea\n- has a cat named Pixel\n")
    first = lines_for(config)
    assert first[0] == (f"Memory: took 2 lines of {config.profile_path} in as accepted facts. That file was not changed and "
                        "is not read any more: change what Diya knows with `python diya_review.py`.")
    assert first[1].startswith("Memory: 2 accepted facts (") and "are given to the model" in first[1]
    assert len(lines_for(config)) == 1  # the second start does not repeat it
    assert pathlib.Path(config.profile_path).read_bytes() == b"- likes tea\n- has a cat named Pixel\n"


def test_facts_waiting_for_review_are_counted(config, memory):
    for position in range(3):
        memory.add_candidate(f"fact {position}", batch_first=1, batch_last=1, position=position, model="m", extracted_at=STAGED_AT, raw="- x")
    assert "3 candidates wait for review" in lines_for(config)[-1]


def test_lines_added_to_the_old_file_after_the_switch_are_pointed_out_because_nothing_reads_it(config, memory):
    write_profile(config, "- likes tea\n")
    lines_for(config)
    write_profile(config, "- likes tea\n- a new line\n- another new line\n")
    last = lines_for(config)[-1]
    assert last == (f"Memory: 2 lines in {config.profile_path} are in no fact, and that file is not read any more. "
                    "`python diya_review.py import-profile` takes them in.")
    memory_now = Memory(Store(config.db_path))
    memory_now.add_manual("a new line", "cli")  # once it is a fact it is no longer "in no fact"
    assert "1 lines" in lines_for(config)[-1]
    rejected = memory_now.add_candidate("another new line", batch_first=1, batch_last=1, position=0, model="m",
                                        extracted_at=STAGED_AT, raw="- another new line")
    memory_now.decide(rejected, "reject", "cli")  # ...of ANY status: a line someone has already decided about is not nagged about
    assert len(lines_for(config)) == 1


def test_an_unreadable_old_profile_is_reported_at_startup_not_raised(config):
    os.mkdir(config.profile_path)
    lines = lines_for(config)
    assert lines[0].startswith("Memory: could not take in the old profile: could not read the profile")


# --- the entry points say it ----------------------------------------------------------------------------

def test_the_live_terminal_chat_prints_the_memory_lines_and_a_one_shot_run_does_not(config, memory, monkeypatch, capsys):
    memory.add_manual("likes tea", "cli")
    agent = agent_for(config, text_reply("Four."))
    monkeypatch.setattr(diya, "Agent", lambda: agent)

    monkeypatch.setattr("sys.argv", ["diya.py", "new", "2+2?"])  # one-shot: its output is for scripts
    diya.main()
    assert "Memory:" not in capsys.readouterr().out

    monkeypatch.setattr("sys.argv", ["diya.py", "new"])  # live chat
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError()))
    diya.main()
    out = capsys.readouterr().out
    assert "[Memory: 1 accepted facts (" in out and "are given to the model; 0 candidates wait for review" in out


def test_the_one_shot_run_still_tells_the_model_what_it_knows(config, memory, monkeypatch, capsys):
    memory.add_manual("likes tea", "cli")
    model = FakeClient([text_reply("Four.")])
    real_agent = diya.Agent
    monkeypatch.setattr(diya, "Agent", lambda: real_agent(config, client=model))
    monkeypatch.setattr("sys.argv", ["diya.py", "new", "2+2?"])
    diya.main()
    assert model.chat_calls[0]["messages"][0] == {"role": "system", "content": HEADER + "- likes tea"}


def test_the_api_prints_the_memory_lines_before_it_starts_listening(config, tmp_path, monkeypatch, capsys):
    (tmp_path / "some-host+3.pem").write_text("cert")
    (tmp_path / "some-host+3-key.pem").write_text("key")
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    monkeypatch.setattr(diya, "Agent", lambda config=None: types.SimpleNamespace(config=config, warm_up=lambda: None))
    monkeypatch.setattr(diya, "memory_startup_lines", lambda agent: ["Memory: a line about memory"])
    monkeypatch.setattr(diya, "actions_startup_lines", lambda agent: [])  # the fake agent has no action store
    monkeypatch.setattr(diya_web, "WhisperTranscriber", lambda name: types.SimpleNamespace(name=name, warm_up=lambda: None))
    diya_web.main()
    out = capsys.readouterr().out
    assert "Memory: a line about memory" in out
    assert out.index("Memory: a line about memory") < out.index("Diya's API is listening")
