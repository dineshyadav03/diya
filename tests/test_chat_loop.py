"""What the tool-calling loop does when the model gets a tool call wrong (diya.py: Agent._ask, _run_tool_call, _tool_arguments).

A small model sometimes names a tool that does not exist, sends arguments that are not JSON, or sends something that is JSON but not an
object. It used to end the whole turn: the lookup and the parsing sat outside the `try`, so the chat route reported "couldn't reach the
model" for a model that had answered. Now each of these is told to the model, as the result of that call, in words it can act on, and the
turn goes on (the model's retries are bounded by MAX_TOOL_ROUNDS). What is pinned here: nothing raises; every call gets exactly one tool
message with its own id; a good call beside a bad one still runs; a bad call runs nothing; and a tool that exists but is not offered
this turn is still refused by the tool itself (tests/test_actions_agent.py, tests/test_repeat_tool.py), not by this loop.
"""
import dataclasses
from datetime import datetime

import pytest

import diya
import diya_config
from fakes import FakeClient, text_reply, tool_calls_reply, tool_reply

NOW = datetime(2026, 10, 10, 10, 0)
ASK = [{"role": "user", "content": "what is on my list?"}]


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "loop.db"), profile_path=str(tmp_path / "p.txt"))


def agent_for(config, *replies):
    return diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: NOW, action_kinds=())


def tool_messages(agent, call=1):
    """The tool messages the model was sent in its `call`-th request (0 is the first)."""
    return [m for m in agent.client.chat_calls[call]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]


# --- a tool that does not exist ------------------------------------------------------------------------------------

def test_a_tool_that_does_not_exist_is_told_to_the_model_and_the_turn_goes_on(config):
    agent = agent_for(config, tool_reply("no_such_tool", "{}"), text_reply("Nothing on it."))
    assert agent.ask(list(ASK)) == ("Nothing on it.", ["no_such_tool"])  # the attempt is on record, as ever
    (told,) = tool_messages(agent)
    assert told["tool_call_id"] == "call_1"
    assert told["content"].startswith("Error: there is no tool called 'no_such_tool'. The tools you can use now: ")
    assert "list_reminders" in told["content"] and "get_weather" in told["content"]


def test_the_tools_that_can_be_used_are_listed_in_alphabetical_order(config):
    agent = agent_for(config, tool_reply("no_such_tool", "{}"), text_reply("ok"))
    agent.ask(list(ASK))
    names = sorted(spec["function"]["name"] for spec in agent.tools)
    assert tool_messages(agent)[0]["content"].endswith("The tools you can use now: " + ", ".join(names) + ".")


def test_a_name_that_is_very_long_is_cut_before_it_is_said_back(config):
    agent = agent_for(config, tool_reply("x" * 500, "{}"), text_reply("ok"))
    agent.ask(list(ASK))
    assert "x" * 61 not in tool_messages(agent)[0]["content"]


def test_with_no_tools_offered_the_error_says_there_are_none(config):
    agent = agent_for(config, tool_reply("no_such_tool", "{}"), text_reply("Noted."))
    agent.ask([{"role": "user", "content": "my flight is on Friday at 6"}])  # a plain fact: the model is given no tools
    assert agent.client.chat_calls[0]["tools"] is None
    assert tool_messages(agent)[0]["content"].endswith("The tools you can use now: none.")


# --- arguments that cannot be used ---------------------------------------------------------------------------------

def test_arguments_that_are_not_json_run_nothing_and_are_told_to_the_model(config):
    agent = agent_for(config, tool_reply("list_reminders", "{not json"), text_reply("ok"))
    ran = []
    agent._functions["list_reminders"] = lambda **args: ran.append(args) or "x"
    assert agent.ask(list(ASK))[0] == "ok"
    assert ran == []
    content = tool_messages(agent)[0]["content"]
    assert content.startswith("Error: the arguments for list_reminders could not be used (not valid JSON: ")
    assert content.endswith("Call it again with a JSON object.")


@pytest.mark.parametrize("raw, kind", [("[]", "list"), ('"x"', "str"), ("5", "int"), ("null", "NoneType"), ("true", "bool"), ("[1, 2]", "list")])
def test_json_that_is_not_an_object_is_refused_the_same_way(config, raw, kind):
    agent = agent_for(config, tool_reply("list_reminders", raw), text_reply("ok"))
    ran = []
    agent._functions["list_reminders"] = lambda **args: ran.append(args) or "x"
    agent.ask(list(ASK))
    assert ran == [] and f"a JSON object was expected, not {kind}" in tool_messages(agent)[0]["content"]


@pytest.mark.parametrize("raw", ["", "   ", "\n"])
def test_no_arguments_at_all_means_none_not_an_error(config, raw):
    agent = agent_for(config, tool_reply("list_reminders", raw), text_reply("ok"))
    agent.ask(list(ASK))
    assert tool_messages(agent)[0]["content"] == "No pending reminders."


@pytest.mark.parametrize("raw, expected", [
    (None, {}), ("", {}), ("  ", {}), ("{}", {}), ('{"a": 1}', {"a": 1}), ({"a": 2}, {"a": 2}),
])
def test_the_reader_of_arguments(raw, expected):
    assert diya._tool_arguments(raw) == expected


@pytest.mark.parametrize("raw", ["{", "[", "nope", 5, b"{}", ["a"], '"s"', "1"])
def test_the_reader_of_arguments_refuses_what_is_not_an_object_with_a_reason(raw):
    with pytest.raises(ValueError):
        diya._tool_arguments(raw)


# --- the rest of the turn is not spoiled by a bad call ---------------------------------------------------------------

def test_a_good_call_beside_a_bad_one_still_runs_and_each_call_gets_its_own_answer(config):
    agent = agent_for(config, tool_calls_reply(("no_such_tool", "{}"), ("list_reminders", "{}")), text_reply("Nothing."))
    agent.ask(list(ASK))
    first, second = tool_messages(agent)
    assert (first["tool_call_id"], second["tool_call_id"]) == ("call_1", "call_2")
    assert first["content"].startswith("Error: there is no tool called") and second["content"] == "No pending reminders."


def test_a_model_that_keeps_getting_it_wrong_is_stopped_by_the_round_limit_not_by_a_crash(config):
    agent = agent_for(config, *[tool_reply("no_such_tool", "{}") for _ in range(diya.MAX_TOOL_ROUNDS)])
    answer, called = agent.ask(list(ASK))
    assert answer.startswith("I couldn't finish that after several tool calls")
    assert called == ["no_such_tool"] * diya.MAX_TOOL_ROUNDS


def test_a_tool_that_fails_is_still_told_to_the_model_as_an_error(config):
    agent = agent_for(config, tool_reply("list_reminders", "{}"), text_reply("ok"))

    def fail(**args):
        raise RuntimeError("the table is locked")

    agent._functions["list_reminders"] = fail
    agent.ask(list(ASK))
    assert tool_messages(agent)[0]["content"] == "Error: the table is locked"


def test_a_call_with_unusable_arguments_still_counts_as_an_attempt_but_an_unknown_name_does_not(config):
    """What a proposal later in the turn says it came after (docs/ACTIONS_DESIGN.md, D6): a tool attempted, even badly, is listed; a
    name that is no tool is not."""
    agent = agent_for(config, tool_calls_reply(("web_search", "{bad"), ("no_such_tool", "{}"), ("list_reminders", "{}")), text_reply("ok"))
    seen = []

    def spy(**args):
        seen.append(list(agent._turn.reads))
        return "No pending reminders."

    agent._functions["list_reminders"] = spy
    agent.ask(list(ASK))
    assert seen == [["web_search"]]


def test_the_turn_state_is_cleared_after_a_bad_call_as_after_any_other(config):
    agent = agent_for(config, tool_reply("no_such_tool", "{}"), text_reply("ok"))
    agent.ask(list(ASK), thread_id=4, message_id=9)
    assert agent._turn.active is False and agent._turn.reads == [] and agent._turn.thread_id is None
