"""Short, plain replies (diya_intent.tidy_reply, diya.PERSONA's style rules, diya_style_bench.py; docs/STYLE_BENCH.md), added 2026-10-26 when the owner put Diya's replies beside Hark's.

What this proves: the tidy takes out only what it names and nothing else (a picture, a closing offer of more help, a P.S., a one-word praise or "you're right" at the start), leaves every other word exactly as the model wrote it,
never touches a reply with a code block, keeps the pictures the person used themselves, never empties a reply, and never removes a question that is the whole of the reply; the agent applies it to ordinary replies (and not
when it is switched off); the persona carries the style rules and tells the model to use what it knows about the person only when it changes the answer; and the benchmark's grader finds each fault and nothing else.
The measured effect on the real model is in docs/STYLE_BENCH.md.
"""
import pytest

import diya
import diya_config
import diya_intent as intent
import diya_style_bench as bench
from fakes import FakeClient, text_reply

FLUFF = (
    "It's currently **27.3°C** in Nellore, a bit warm.\n\nSince you're studying AI in the heat, maybe that's a fun reminder:\n🔥 **Deep learning networks learn best with stable data**\n\n"
    "Want me to check tomorrow's weather too? 😊\n\nP.S. Rocky would love the shade. 🐶"
)


def test_pictures_a_closing_offer_and_a_postscript_are_taken_out_and_the_rest_is_left_word_for_word():
    said = intent.tidy_reply(FLUFF, "how hot is it in nellore")
    assert said == "It's currently **27.3°C** in Nellore, a bit warm.\n\nSince you're studying AI in the heat, maybe that's a fun reminder:\n**Deep learning networks learn best with stable data**"


@pytest.mark.parametrize("reply, user, expected", [
    ("Sure! 15% of 240 is 36.", "what is 15% of 240", "15% of 240 is 36."),
    ("Great question! Canberra.", "capital of australia", "Canberra."),
    ("You're absolutely right — and thank you for calling that out! 💡\n\nI can't see your emails.", "but there are mails", "I can't see your emails."),
    ("Canberra. Let me know if you want more about Australia.", "capital", "Canberra."),
    ("Break the work into 25-minute blocks.\n\nI'm here to help whenever you need.", "tip", "Break the work into 25-minute blocks."),
    ("Try a walk. If you'd like, I can also suggest a playlist.", "bored", "Try a walk."),
    ("Done 🎉", "tell me", "Done"),
])
def test_each_thing_it_names_is_taken_out(reply, user, expected):
    assert intent.tidy_reply(reply, user) == expected


@pytest.mark.parametrize("reply", [
    "Sure, here you go: 36.", "Canberra is the capital.", "Want me to set a reminder?", "Let me know.", "Here you are:\n```py\nprint('hi 😀')\n```\nLet me know!", "You're right.",
    "Rocky is a good name. You mentioned it.", "The PS5 is a console. PS5 games cost more.", "", "   ",
])
def test_what_is_not_one_of_them_is_not_touched(reply):
    assert intent.tidy_reply(reply, "x") == reply


def test_a_reply_that_is_only_an_offer_or_only_praise_is_kept_whole():
    assert intent.tidy_reply("Want me to set a reminder?", "x") == "Want me to set a reminder?"
    assert intent.tidy_reply("Sure!", "x") == "Sure!"  # nothing would be left


def test_the_pictures_the_person_used_are_kept_and_so_is_everything_in_a_reply_with_code():
    assert intent.tidy_reply("Party time 🎉", "let's have a party 🎉") == "Party time 🎉"
    code = "Use this:\n```\nx = '😀'\n```\nLet me know if it works!"
    assert intent.tidy_reply(code, "x") == code


def test_not_text_is_returned_as_it_came():
    for value in (None, 5, ["a"]):
        assert intent.tidy_reply(value, "x") == value


@pytest.mark.parametrize("reply, offer, ps, filler", [
    ("Canberra. Let me know if you want more.", True, False, False), ("Canberra.", False, False, False), ("Let me know.", False, False, False),
    ("Fine.\n\nP.S. Rocky says hi.", False, True, False), ("Fine. PS: also this.", False, True, False), ("The PS5 is great.", False, False, False),
    ("Great question! Because of Rayleigh scattering.", False, False, True), ("Sure, because of scattering.", False, False, False),
])
def test_the_detectors_the_benchmark_uses(reply, offer, ps, filler):
    assert intent.ends_with_an_offer(reply) is offer and intent.has_a_postscript(reply) is ps and intent.starts_with_filler(reply) is filler


# ---- in the agent -------------------------------------------------------------------------------------------------------------------

def agent_saying(text):
    return diya.Agent(diya_config.load_config(), client=FakeClient([text_reply(text)]), action_kinds=[])


def test_an_ordinary_reply_is_tidied_and_with_the_switch_off_it_is_not(monkeypatch):
    answer, _ = agent_saying("Canberra. 😊 Let me know if you want more about Australia!").ask([{"role": "user", "content": "what is the capital of australia"}])
    assert answer == "Canberra."
    monkeypatch.setattr(diya, "TIDY_REPLIES", False)
    raw, _ = agent_saying("Canberra. 😊 Let me know if you want more about Australia!").ask([{"role": "user", "content": "what is the capital of australia"}])
    assert raw == "Canberra. 😊 Let me know if you want more about Australia!"


def test_the_persona_has_the_style_rules_and_uses_what_it_knows_only_when_it_matters():
    for needle in ("the answer first, then stop", "No emoji", "no \"P.S.\"", "no offer at the end", "Never bring up their pets, hobbies, studies or home unless the question is about them"):
        assert needle in diya.STYLE_RULES, needle
    assert "use it only when it changes the answer" in diya.PERSONA_VOICE and "Use what you know about the user below" not in diya.PERSONA_VOICE


# ---- the benchmark's grader -----------------------------------------------------------------------------------------------------------

CASES, PROFILE, WORDS = bench.load_cases()
BY_ID = {case["id"]: case for case in CASES}


def kinds(case_id, reply):
    return sorted(kind for kind, _ in bench.grade(BY_ID[case_id], reply, WORDS))


def test_the_cases_are_twelve_to_tune_on_and_twelve_that_are_not_and_none_is_about_the_profile():
    assert [c["split"] for c in CASES].count("dev") == 12 and [c["split"] for c in CASES].count("held-out") == 12 and len({c["id"] for c in CASES}) == 24
    for case in CASES:
        assert not any(word in case["prompt"].lower() for word in WORDS), case["id"]  # a message that names the dog or the guitar would make mentioning it right


def test_the_grader_finds_each_fault_and_a_short_plain_reply_is_clean():
    assert kinds("d03", "Canberra.") == []
    assert kinds("d03", "Canberra, the capital of Australia, is a planned city located between Sydney and Melbourne, built in the early twentieth century, and it is home to the parliament and many national museums.") == ["length"]
    assert kinds("d03", "Canberra 😊") == ["picture"]
    assert kinds("d03", "Canberra. Let me know if you want more.") == ["offer"]
    assert kinds("d03", "Canberra.\n\nP.S. How is Rocky?") == ["postscript", "volunteered"]
    assert kinds("d03", "Great question! Canberra.") == ["filler"]
    assert kinds("d03", "# Answer\nCanberra.") == ["heading"]
    assert kinds("d02", "Try 25-minute blocks, and maybe play your guitar on breaks.") == ["volunteered"]


def test_a_profile_fact_the_message_makes_relevant_is_not_volunteering():
    assert kinds("h09", "Try something new, or pick up your guitar again.") == []  # a hobby question
    assert kinds("d08", "Not peanuts, with your allergy: dal and rice.") == []  # dinner, and the allergy matters
    assert kinds("d08", "Dal and rice. Rocky would like the leftovers.") == ["volunteered"]


def test_a_message_that_asks_about_a_place_may_name_it():
    case = {"id": "x", "kind": "weather", "prompt": "how hot is it in nellore", "max_words": 40}
    assert bench.grade(case, "27 degrees in Nellore.", WORDS) == []


def test_the_summary_counts_clean_replies_and_each_kind_of_fault():
    records = [{"words": 5, "issues": [], "clean": True}, {"words": 9, "issues": [("picture", "x"), ("offer", "y")], "clean": False}, {"words": 7, "issues": [("picture", "x")], "clean": False}]
    assert bench.summarize(records) == {"clean": 1, "of": 3, "median_words": 7, "issues": {"offer": 1, "picture": 2}}
    assert "mode" in bench.render({"before": [dict(records[1], id="d01", kind="chat", prompt="p", reply="r")]})

def test_the_reminder_that_the_facts_are_background_is_only_with_the_voice_and_only_when_something_is_known(tmp_path, monkeypatch):
    import dataclasses

    import diya_memory

    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "r.db"), profile_path=str(tmp_path / "p.txt"))
    monkeypatch.setattr(diya, "PERSONA", diya.PERSONA_VOICE + " " + diya.STYLE_RULES)
    agent = diya.Agent(config, client=FakeClient([]))
    assert diya.PROFILE_REMINDER not in agent.with_profile([])[0]["content"]  # nothing known: no list, no reminder
    diya_memory.Memory(agent.store).add_manual("has a dog named Rocky", "api")
    told = agent.with_profile([])[0]["content"]
    assert told.endswith(diya.PROFILE_REMINDER) and told.index("- has a dog named Rocky") < told.index(diya.PROFILE_REMINDER)
    monkeypatch.setattr(diya, "PERSONA", "")  # the voice off: the old shape, exactly
    assert diya.PROFILE_REMINDER not in agent.with_profile([])[0]["content"]


# ---- the persona's honesty about being small is said when asked, not at the end of a fact ------------------------------------------------------

def test_a_sentence_that_says_diya_is_a_smaller_model_is_taken_out_unless_the_person_asked_about_the_model():
    said = "Alexander Graham Bell invented the telephone in 1876.\n\nI'm smaller than cloud models like Claude or GPT, no fancy tricks, just facts."
    assert intent.tidy_reply(said, "who invented the telephone") == "Alexander Graham Bell invented the telephone in 1876."
    assert intent.tidy_reply(said, "are you smaller than gpt?") == said  # asked about it: said
    assert intent.tidy_reply(said, "what model are you") == said
    assert intent.tidy_reply("I'm a small open-source model, so double check.", "what is 2+2") == "I'm a small open-source model, so double check."  # nothing else would be left
