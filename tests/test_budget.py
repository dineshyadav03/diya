"""A budget for what every message pays to the model (added 2026-10-28; the idea is Atticus's "Budget" rule: new features must fit under limits that tests enforce, atticus.py --budget, MIT).

Diya's first real turns took 5 to 15 minutes because every message carried 49 tool descriptions (about 9,000 tokens); trimming them brought a turn to seconds (docs/SPEED_DESIGN.md). Nothing kept it from
growing back one tool at a time, so these are the limits, with room above today's numbers (persona 1,155 characters, 10 tools, 5,360 characters of tool descriptions): a new feature that goes over them has
to say so here, in a commit, on purpose.
"""
import json

import pytest

import diya
import diya_config
from fakes import FakeClient

PERSONA_CHARS = 1_600  # the voice and rules sent first on every message
ORDINARY_TOOLS = 12  # tools offered for a message that asks for no action
ORDINARY_TOOL_CHARS = 7_000  # their descriptions, as JSON


@pytest.fixture
def agent():
    return diya.Agent(diya_config.load_config(), client=FakeClient([]))


def test_the_persona_stays_short():
    assert len(diya.PERSONA) <= PERSONA_CHARS, len(diya.PERSONA)


@pytest.mark.parametrize("message", ["tell me a joke", "what is the capital of France", "what is the weather in Pune", "hey", "write a short note to my landlord"])
def test_an_ordinary_message_is_offered_few_tools_with_short_descriptions(agent, message):
    offered = agent._tools_asked_for(agent.tools, message)
    assert len(offered) <= ORDINARY_TOOLS, [t["function"]["name"] for t in offered]
    assert len(json.dumps(offered)) <= ORDINARY_TOOL_CHARS, len(json.dumps(offered))


def test_a_message_that_asks_for_one_kind_of_action_adds_only_that_kind(agent):
    plain = len(agent._tools_asked_for(agent.tools, "tell me a joke"))
    asked = len(agent._tools_asked_for(agent.tools, "make a Drive folder called Diya notes"))
    assert plain <= asked <= plain + 3  # (equal while Google Drive is not connected: a kind is offered only while its account is)
