"""Playbooks (diya_playbooks.py, Agent._playbook_note, `python diya_playbooks.py`; docs/PLAYBOOKS_DESIGN.md), added 2026-10-20 from the study of Devin's Skills (docs/STUDY_DEVIN.md).

What this proves, with real files in a real folder, the real agent and a stand-in for the embedding model (hashed words, so that closeness is predictable): a SKILL.md with a --- block is read, and every way
a file can be wrong is refused with a reason and the file is ignored, never half-used; the three samples in sample_playbooks/ are valid; a playbook is used when the message names it (`@name`, and not in an
address), or, if it allows that, when the request is close in meaning to what it is for and clearly closer than any other; one at a time; arguments are filled in the Agent Skills way; the note says the steps are
the user's and change nothing about tools or approvals, and the tools offered to the model are exactly the same with and without a playbook; an unattended run, a switch that is off, a missing folder and a broken
embedding use none; and the use is journalled by name only. It does not prove that the real embedding model picks the right playbook for real requests: that was measured on 24 invented requests (8 of 10 right,
0 of 14 wrongly picked, docs/PLAYBOOKS_DESIGN.md), and a miss means the person types `@name`.
"""
import dataclasses
import io
import os
import pathlib
import zlib

import pytest

import diya
import diya_checks
import diya_config
import diya_playbooks as pb
from fakes import FakeClient, text_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
STUDY = """---
name: study-plan
description: Use when I ask for a study plan, a revision schedule, or how to prepare for an exam or a test
triggers: [user, model]
argument-hint: the subject and the exam date
---
1. Ask which exam and when, if I have not said.
2. Split the days left into blocks of 25 minutes.
"""
REVIEW = """---
name: weekly-review
description: Use when I ask for a weekly review, how my week went, or what I should focus on next week
triggers: [user]
---
Say what got done, what slipped, and one thing to focus on.
"""


def embed_words(text):
    vector = [0.0] * 256
    for word in diya_checks.content_words(text):
        vector[zlib.crc32(word.encode()) % 256] += 1.0
    return vector


def folder_with(tmp_path, **playbooks):
    root = tmp_path / "playbooks"
    for name, text in playbooks.items():
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "SKILL.md").write_text(text, encoding="utf-8")
    return root


# ---- reading a file ---------------------------------------------------------------------------------------------------


def test_a_playbook_file_is_read():
    p = pb.parse(STUDY, "ignored")
    assert p["name"] == "study-plan" and p["triggers"] == ("user", "model") and p["hint"] == "the subject and the exam date"
    assert p["description"].startswith("Use when I ask for a study plan") and p["body"].startswith("1. Ask which exam")


def test_the_defaults_and_the_formats_a_person_might_use():
    text = "﻿---\r\ndescription: Use when I ask for something specific\r\n---\r\nDo the thing.\r\n"
    p = pb.parse(text, "my-folder")  # the name falls back to the folder's, triggers to both, a BOM and CRLF are fine
    assert p["name"] == "my-folder" and p["triggers"] == ("user", "model") and p["body"] == "Do the thing."
    assert pb.parse(STUDY.replace("[user, model]", "model"), "x")["triggers"] == ("model",)
    assert pb.parse(STUDY.replace("[user, model]", "[ \"user\" ]"), "x")["triggers"] == ("user",)


@pytest.mark.parametrize("text, why", [
    ("no block at all\nsteps", "--- block"),
    ("---\nname: x\ndescription: Use when I ask for something\nsteps never closed", "never closed"),
    ("---\nthis is not a pair\n---\nbody", "key: value"),
    ("---\nname: Study Plan\ndescription: Use when I ask for something\n---\nbody", "lowercase"),
    ("---\nname: " + "a" * 41 + "\ndescription: Use when I ask for something\n---\nbody", "lowercase"),
    ("---\nname: ok\ndescription: short\n---\nbody", "description"),
    ("---\nname: ok\ndescription: " + "d" * 301 + "\n---\nbody", "description"),
    ("---\nname: ok\ndescription: Use when I ask for something\ntriggers: [user, anyone]\n---\nbody", "triggers"),
    ("---\nname: ok\ndescription: Use when I ask for something\ntriggers: []\n---\nbody", "triggers"),
    ("---\nname: ok\ndescription: Use when I ask for something\n---\n", "steps"),
    ("---\nname: ok\ndescription: Use when I ask for something\n---\n" + "x" * 1501, "steps"),
    ("---\nname: ok\ndescription: Use when I ask for something\n---\nbody \x07 bell", "control"),
    ("---\nname: ok\ndescription: Use when I ask for something\n---\n" + "x" * 9000, "bytes"),
    (None, "bytes"), (5, "bytes"),
])
def test_every_way_a_file_can_be_wrong_is_refused_with_a_reason(text, why):
    with pytest.raises(pb.Problem) as caught:
        pb.parse(text, "x")
    assert why in str(caught.value)


def test_allowed_tools_in_a_file_is_ignored_because_a_playbook_grants_nothing():
    p = pb.parse(STUDY.replace("argument-hint", "allowed-tools: propose_google_doc, web_search\nargument-hint"), "x")
    assert "allowed-tools" not in p and "propose_google_doc" not in str(p)


def test_the_three_samples_that_ship_are_valid():
    found, problems = pb.load(str(ROOT / "sample_playbooks"))
    assert problems == [] and [p["name"] for p in found] == ["study-plan", "summarise-notes", "weekly-review"]
    assert {p["name"]: p["triggers"] for p in found}["weekly-review"] == ("user",)


# ---- the folder -------------------------------------------------------------------------------------------------------


def test_a_missing_or_empty_folder_has_no_playbooks(tmp_path):
    assert pb.load(str(tmp_path / "none")) == ([], []) and pb.load("") == ([], []) and pb.load(None) == ([], [])
    (tmp_path / "empty").mkdir()
    assert pb.load(str(tmp_path / "empty")) == ([], [])


def test_a_wrong_file_is_listed_with_its_reason_and_the_others_are_still_used(tmp_path):
    root = folder_with(tmp_path, **{"study-plan": STUDY, "broken": "just text", "weekly-review": REVIEW})
    (root / "stray.txt").write_text("not a playbook")
    (root / "no-skill-file").mkdir()
    found, problems = pb.load(str(root))
    assert [p["name"] for p in found] == ["study-plan", "weekly-review"]
    assert problems == [("broken/SKILL.md", "it must start with a --- block giving name, description and triggers")]


def test_two_playbooks_with_one_name_use_the_first_and_say_so(tmp_path):
    root = folder_with(tmp_path, a=STUDY, b=STUDY)
    found, problems = pb.load(str(root))
    assert len(found) == 1 and "already called study-plan" in problems[0][1]


def test_more_than_the_limit_are_not_used(tmp_path):
    texts = {f"p{n:02d}": STUDY.replace("study-plan", f"p{n:02d}") for n in range(pb.MAX_PLAYBOOKS + 2)}
    found, problems = pb.load(str(folder_with(tmp_path, **texts)))
    assert len(found) == pb.MAX_PLAYBOOKS and len(problems) == 2 and "not used" in problems[0][1]


def test_a_file_that_changes_is_read_again_and_one_that_does_not_is_not(tmp_path):
    root = folder_with(tmp_path, **{"study-plan": STUDY})
    first, _ = pb.load(str(root))
    again, _ = pb.load(str(root))
    assert again is first  # the same list: nothing was re-read
    (root / "study-plan" / "SKILL.md").write_text(STUDY.replace("25 minutes", "50 minutes"), encoding="utf-8")
    changed, _ = pb.load(str(root))
    assert "50 minutes" in changed[0]["body"]


def test_a_file_that_is_not_text_is_a_problem_not_a_crash(tmp_path):
    root = tmp_path / "playbooks" / "binary"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_bytes(b"\xff\xfe\x00bad")
    found, problems = pb.load(str(tmp_path / "playbooks"))
    assert found == [] and problems[0][1] == "it could not be read as text"


def test_a_link_that_leaves_the_folder_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text(STUDY, encoding="utf-8")
    root = tmp_path / "playbooks"
    root.mkdir()
    try:
        os.symlink(outside, root / "escape", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create links")
    assert pb.load(str(root)) == ([], [])


# ---- naming one -------------------------------------------------------------------------------------------------------


def test_a_playbook_named_in_the_message_is_found_and_taken_out_of_it(tmp_path):
    found, _ = pb.load(str(folder_with(tmp_path, **{"study-plan": STUDY, "weekly-review": REVIEW})))
    chosen, rest = pb.named(found, "please use @study-plan for my chemistry exam on Friday")
    assert chosen["name"] == "study-plan" and rest == "please use for my chemistry exam on Friday"
    assert pb.named(found, "@Weekly-Review")[0]["name"] == "weekly-review"  # (any capitals)


@pytest.mark.parametrize("text", ["mail me at ana@study-plan.com", "the @study-planner said so", "@nothing-like-it", "study-plan", "", None, 4])
def test_these_name_no_playbook(tmp_path, text):
    found, _ = pb.load(str(folder_with(tmp_path, **{"study-plan": STUDY})))
    assert pb.named(found, text)[0] is None


def test_a_playbook_that_does_not_allow_the_user_to_name_it_is_not_named(tmp_path):
    found, _ = pb.load(str(folder_with(tmp_path, **{"study-plan": STUDY.replace("[user, model]", "[model]")})))
    assert pb.named(found, "@study-plan please")[0] is None


def test_the_first_mention_wins(tmp_path):
    found, _ = pb.load(str(folder_with(tmp_path, **{"study-plan": STUDY, "weekly-review": REVIEW})))
    assert pb.named(found, "@weekly-review and then @study-plan")[0]["name"] == "weekly-review"


# ---- arguments --------------------------------------------------------------------------------------------------------


def test_arguments_fill_the_places_the_steps_leave_for_them_or_are_added_at_the_end():
    assert pb.arguments("Plan for $ARGUMENTS now.", "chemistry on Friday") == ("Plan for chemistry on Friday now.", True)
    assert pb.arguments("Subject: $1, day: $2, extra: $3", "chemistry friday") == ("Subject: chemistry, day: friday, extra: ", True)
    assert pb.arguments("Just do it.", "chemistry") == ("Just do it.", False)
    assert pb.arguments("Just do it.", "") == ("Just do it.", False)


# ---- picking one by meaning -------------------------------------------------------------------------------------------


@pytest.fixture
def playbooks(tmp_path):
    return pb.load(str(folder_with(tmp_path, **{"study-plan": STUDY, "weekly-review": REVIEW, "summarise": STUDY.replace("study-plan", "summarise").replace(
        "a study plan, a revision schedule, or how to prepare for an exam or a test", "summarise, condense or shorten text or notes into bullet points"
    )})))[0]


def test_a_request_close_to_what_a_playbook_is_for_picks_it(playbooks):
    assert pb.pick(playbooks, "make me a study plan for my exam", embed_words, "m")["name"] == "study-plan"
    assert pb.pick(playbooks, "condense my notes into bullet points", embed_words, "m")["name"] == "summarise"


@pytest.mark.parametrize("text", ["what is the capital of France", "tell me a joke about cats", "how did my week go", "what should I focus on next week", "plan my day tomorrow", "", None])
def test_anything_else_picks_nothing_and_a_user_only_playbook_is_never_picked_by_meaning(playbooks, text):
    assert pb.pick(playbooks, text, embed_words, "m") is None


def test_a_request_with_no_word_in_common_is_not_trusted_to_start_a_procedure(playbooks):
    assert pb.pick(playbooks, "revise chemistry", lambda t: [1.0, 0.0] if "revise" in t else [1.0, 0.0], "m") is None  # (the embedding says identical; no shared word: nothing starts)


def test_two_playbooks_equally_close_pick_neither(tmp_path):
    two = pb.load(str(folder_with(tmp_path, a=STUDY.replace("study-plan", "a-plan"), b=STUDY.replace("study-plan", "b-plan"))))[0]
    assert pb.pick(two, "make me a study plan for my exam", lambda t: [1.0, 0.0, 0.0], "m") is None


def test_a_failing_embedding_picks_nothing_and_raises_nothing(playbooks):
    def broken(text):
        raise ConnectionError("down")

    assert pb.pick(playbooks, "make me a study plan for my exam", broken, "m") is None


def test_the_descriptions_are_embedded_once(playbooks):
    calls = []
    pb._embedded.clear()
    pb.pick(playbooks, "make me a study plan for my exam", lambda t: calls.append(t) or embed_words(t), "m")
    first = len(calls)
    pb.pick(playbooks, "make me a study plan for my exam please", lambda t: calls.append(t) or embed_words(t), "m")
    assert len(calls) - first == 1  # the request only: every description was already made


# ---- the note ---------------------------------------------------------------------------------------------------------


def test_the_note_gives_the_steps_as_the_users_and_says_they_change_nothing_else():
    p = pb.parse(STUDY, "x")
    text = pb.note(p, "chemistry")
    assert text.startswith(pb.NOTE_HEAD) and "Playbook study-plan:" in text and "Ask which exam" in text and text.endswith("The user's request, for these steps: chemistry")
    assert "Arguments:" not in text  # (the first version said "Arguments:" and the model copied the word into its answer)
    assert "tools, approvals and the rules of memory stay as they are" in text


def test_hidden_characters_in_the_steps_do_not_reach_the_model():
    p = pb.parse(STUDY.replace("Ask which", "Ask" + chr(0x202E) + chr(0x200B) + " which"), "x")
    assert chr(0x202E) not in pb.note(p) and chr(0x200B) not in pb.note(p)


# ---- the agent --------------------------------------------------------------------------------------------------------


def build(tmp_path, client, **changes):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "p.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False, auto_memory=False, playbooks=True,
        playbooks_dir=str(tmp_path / "playbooks"), **changes,
    )
    agent = diya.Agent(config, client=client)
    agent.embed = embed_words
    return config, agent


def system_of(client, index=-1):
    sent = client.chat_calls[index]["messages"]
    return sent[0]["content"] if sent and sent[0]["role"] == "system" else ""


def ask(agent, text, **kwargs):
    return agent.ask([{"role": "user", "content": text}], thread_id=agent.store.main_thread(), message_id=1, **kwargs)


def test_a_playbook_named_in_a_message_reaches_the_model_with_its_arguments(tmp_path):
    folder_with(tmp_path, **{"study-plan": STUDY})
    client = FakeClient([text_reply("ok")])
    _, agent = build(tmp_path, client)
    ask(agent, "@study-plan chemistry before Friday")
    note = system_of(client)
    assert "Playbook study-plan:" in note and "Ask which exam" in note and "The user's request, for these steps: chemistry before Friday" in note


def test_one_close_in_meaning_is_used_without_being_named_and_the_use_is_journalled_by_name_only(tmp_path):
    folder_with(tmp_path, **{"study-plan": STUDY, "weekly-review": REVIEW})
    client = FakeClient([text_reply("ok")])
    _, agent = build(tmp_path, client)
    ask(agent, "make me a study plan for my exam")
    assert "Playbook study-plan:" in system_of(client)
    entries = [e for e in agent.store.journal_recent(limit=20) if e["tool"] == "use_playbook"]
    assert len(entries) == 1 and entries[0]["kind"] == "flow" and "name=study-plan" in entries[0]["args_preview"] and "by=meaning" in entries[0]["args_preview"] and "Ask which exam" not in str(entries[0])


def test_the_tools_offered_to_the_model_are_the_same_with_and_without_a_playbook(tmp_path):
    folder_with(tmp_path, **{"study-plan": STUDY.replace("argument-hint", "allowed-tools: propose_google_doc\nargument-hint")})
    client = FakeClient([text_reply("ok"), text_reply("ok")])
    _, agent = build(tmp_path, client)
    ask(agent, "@study-plan chemistry")
    ask(agent, "what is the capital of France? please tell me")
    with_playbook, without = client.chat_calls[0]["tools"], client.chat_calls[1]["tools"]
    assert with_playbook == without and with_playbook is not None  # nothing was added, removed or reordered


def test_an_unattended_run_a_missing_folder_a_switch_that_is_off_and_a_broken_embedding_use_none(tmp_path):
    folder_with(tmp_path, **{"study-plan": STUDY})
    client = FakeClient([text_reply("ok")] * 6)
    config, agent = build(tmp_path, client)
    ask(agent, "@study-plan chemistry", only_tools=())
    assert "Playbook" not in system_of(client)
    agent.config = dataclasses.replace(config, playbooks=False)
    ask(agent, "@study-plan chemistry")
    assert "Playbook" not in system_of(client)
    agent.config = dataclasses.replace(config, playbooks_dir=str(tmp_path / "no-such-folder"))
    ask(agent, "@study-plan chemistry")
    assert "Playbook" not in system_of(client)
    agent.config = config

    def broken(text):
        raise ConnectionError("down")

    agent.embed = broken
    ask(agent, "make me a study plan for my exam on Friday")  # (meaning cannot be judged: no playbook, and the chat still answers)
    assert "Playbook" not in system_of(client)


def test_a_wrong_file_does_not_stop_the_good_ones_or_the_chat(tmp_path):
    folder_with(tmp_path, **{"study-plan": STUDY, "broken": "nothing useful"})
    client = FakeClient([text_reply("ok")])
    _, agent = build(tmp_path, client)
    ask(agent, "@study-plan chemistry")
    assert "Playbook study-plan:" in system_of(client)


# ---- the command line -------------------------------------------------------------------------------------------------


def test_the_command_line_lists_what_is_used_and_what_is_not_and_checks_a_file(tmp_path):
    root = folder_with(tmp_path, **{"study-plan": STUDY, "broken": "nothing useful"})
    config = dataclasses.replace(diya_config.load_config({}), playbooks_dir=str(root))
    out = io.StringIO()
    assert pb.main(["list"], config=config, out=out) == 0
    text = out.getvalue()
    assert "study-plan  [user, model]" in text and "NOT USED broken/SKILL.md: it must start with a --- block" in text
    out = io.StringIO()
    assert pb.main(["check", str(root / "study-plan" / "SKILL.md")], out=out) == 0 and "Would be used: study-plan" in out.getvalue()
    out = io.StringIO()
    assert pb.main(["check", str(root / "broken" / "SKILL.md")], out=out) == 1 and "Would not be used" in out.getvalue()
    out = io.StringIO()
    assert pb.main(["check", str(root / "missing.md")], out=out) == 1
    out = io.StringIO()
    empty = dataclasses.replace(config, playbooks_dir=str(tmp_path / "nothing"))
    assert pb.main(["list"], config=empty, out=out) == 0 and "No playbooks" in out.getvalue()
