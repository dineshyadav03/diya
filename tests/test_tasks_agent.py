"""The model's side of the to-do list (docs/TASKS_DESIGN.md, D2, D3, D4, D6 and unit T1): the tools add_task and list_tasks.

What this proves: the model can add a task and read the list and nothing else (no tool closes, edits or deletes one);
a task is saved only while the latest message asks for one, judged by the owner's own words and never by an old message;
a message that names Todoist is Todoist's and never lands on this list; a due date is kept only if the person said it
(and kept as words if it cannot be read); the model is told in one plain sentence exactly what was saved or why not; and
the tools never count as "outside content" for a proposal later in the same turn.
"""
import dataclasses
from datetime import datetime

import pytest

import diya
import diya_config
import diya_connectors
import diya_intent
import diya_tasks
from fakes import FakeClient, task_kind, text_reply, tool_calls_reply, tool_reply

NOW = datetime(2026, 9, 23, 10, 15)  # a Wednesday, 10:15 local


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "t.db"), profile_path=str(tmp_path / "p.txt"),
                               connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "c.log"))


def make_agent(config, *replies, kinds=()):
    return diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: NOW, action_kinds=kinds)


def ask(agent, message, **ids):
    return agent.ask([{"role": "user", "content": message}], **ids)


def told(agent):
    """What the model was last told by a tool."""
    for call in reversed(agent.client.chat_calls):
        for message in reversed(call["messages"]):
            if isinstance(message, dict) and message.get("role") == "tool":
                return message["content"]
    return None


def add_call(**args):
    import json
    return tool_reply("add_task", json.dumps(args))


def saying(config, message, **args):
    """Ask `message` with a scripted model that calls add_task(**args); return (agent, what the model was told)."""
    agent = make_agent(config, add_call(**args), text_reply("ok"))
    ask(agent, message)
    return agent, told(agent)


def contents(agent, state="all"):
    return [t["content"] for t in agent.tasks.tasks(state)]


# ---- what the model is offered ------------------------------------------------------------------

def test_the_model_can_add_a_task_and_read_the_list_and_has_no_tool_to_change_one(config):
    agent = make_agent(config)
    names = [tool["function"]["name"] for tool in agent.tools]
    assert "add_task" in names and "list_tasks" in names
    for name in names:
        assert not any(word in name for word in ("complete", "delete", "remove", "edit", "update", "reopen", "close")), name
    assert agent._functions["add_task"] == agent.add_task and agent._functions["list_tasks"] == agent.list_tasks


def test_the_list_needs_no_connector_so_it_is_offered_with_nothing_connected(config):
    assert [t for t in agent_tools(config) if t in ("add_task", "list_tasks")] == ["add_task", "list_tasks"]


def agent_tools(config):
    return [tool["function"]["name"] for tool in make_agent(config).tools]


def test_each_tool_spec_names_its_required_arguments_and_nothing_hidden():
    specs = {t["function"]["name"]: t["function"] for t in diya.TOOLS}
    add = specs["add_task"]["parameters"]
    assert add["required"] == ["content"] and set(add["properties"]) == {"content", "due"}
    lst = specs["list_tasks"]["parameters"]
    assert lst["required"] == [] and set(lst["properties"]) == {"status"}


def test_a_name_collision_with_a_proposal_tool_refuses_to_start(config):
    with pytest.raises(ValueError, match="already another tool's"):
        make_agent(config, kinds=(task_kind(tool_name="add_task"),))


# ---- adding while a message is being answered ------------------------------------------------------

def test_a_task_that_was_asked_for_is_saved_with_the_chat_and_message_it_answers(config):
    agent, said = saying(config, "Add a task to buy oat milk", content="Buy oat milk")
    assert said == "Added to the to-do list: Buy oat milk."
    (task,) = agent.tasks.tasks("all")
    assert task["content"] == "Buy oat milk" and task["source"] == "chat" and task["due_at"] is None
    agent = make_agent(config, add_call(content="Call mum"), text_reply("ok"))
    ask(agent, "Add a task to call mum", thread_id=4, message_id=9)
    assert [(t["thread_id"], t["message_id"]) for t in agent.tasks.tasks("all") if t["content"] == "Call mum"] == [(4, 9)]


@pytest.mark.parametrize("message", [
    "I need to buy milk", "I'm running low on printer ink", "Make a note to call the plumber", "What's on my to-do list?",
    "Don't add a task for that", "How do I add a task?", "Remind me to call mum", "What's 9 times 7?",
])
def test_a_message_that_does_not_ask_for_a_task_saves_none(config, message):
    agent, said = saying(config, message, content="Buy milk")
    assert said == diya.TASK_NOT_ASKED and contents(agent) == []


def test_it_is_judged_by_the_owners_own_latest_message_exactly(config, monkeypatch):
    seen = []
    real = diya_intent.is_task_request
    monkeypatch.setattr(diya_intent, "is_task_request", lambda text: seen.append(text) or real(text))
    agent = make_agent(config, add_call(content="x"), text_reply("ok"))
    agent.ask([{"role": "user", "content": "add a task to call mum"}, {"role": "assistant", "content": "Sure"},
               {"role": "user", "content": "I need to buy milk"}])
    assert seen == ["I need to buy milk"] and contents(agent) == []


@pytest.mark.parametrize("message", [
    "add 'call the dentist' to my Todoist", "Create a Todoist task to book the vet", "todoist: add buy stamps",
    "Add a task to Todoist to buy oat milk",
])
def test_a_message_that_names_todoist_is_todoists_and_never_lands_on_this_list(config, message):
    agent, said = saying(config, message, content="Buy oat milk")
    assert said == diya.TASK_IS_TODOISTS and contents(agent) == []
    assert "propose_todoist_task" in said and "Connections" in said


def test_naming_todoist_without_asking_for_a_task_is_just_not_asked(config):
    agent, said = saying(config, "What's in my Todoist?", content="x")
    assert said == diya.TASK_NOT_ASKED and contents(agent) == []


def test_a_direct_call_is_not_judged_by_an_old_message(config):
    agent = make_agent(config, add_call(content="x"), text_reply("ok"))
    ask(agent, "I need to buy milk")
    assert contents(agent) == []
    assert agent.add_task("Buy milk") == "Added to the to-do list: Buy milk."  # no turn is running
    assert contents(agent) == ["Buy milk"]


def test_what_the_turn_knew_is_forgotten_when_it_ends(config):
    agent = make_agent(config, text_reply("hi"))
    ask(agent, "Add a task to Todoist", thread_id=1, message_id=2)
    assert agent._turn.active is False and agent._turn.user_text is None
    agent.add_task("Later")
    (task,) = agent.tasks.tasks("all")
    assert task["thread_id"] is None and task["message_id"] is None


# ---- the due date ------------------------------------------------------------------------------------

def test_a_due_date_the_person_said_is_kept_and_read(config):
    agent, said = saying(config, "Add a task called prepare slides, due tomorrow at 5pm", content="Prepare slides", due="tomorrow at 5pm")
    (task,) = agent.tasks.tasks("all")
    assert task["due_at"] == "tomorrow at 5pm" and task["due_ts"] is not None
    assert said == "Added to the to-do list: Prepare slides, due Thursday 24 Sep 2026, 17:00."


def test_a_day_alone_is_told_back_as_a_day(config):
    _, said = saying(config, "Add a task for Friday: submit the expense report", content="Submit the expense report", due="Friday")
    assert said == "Added to the to-do list: Submit the expense report, due Friday 25 Sep 2026."


def test_a_due_date_the_person_did_not_say_is_left_out_and_the_model_is_told(config):
    agent, said = saying(config, "add task call mum", content="Call mum", due="tomorrow at 5pm")
    (task,) = agent.tasks.tasks("all")
    assert task["due_at"] is None and task["due_ts"] is None
    assert said == ("Added to the to-do list: Call mum. It has no due date: 'tomorrow at 5pm' was left out, because the user "
                    "did not say when.")


def test_a_due_phrase_the_person_said_with_other_capitals_and_a_full_stop_is_kept(config):
    agent, _ = saying(config, "Add a task to call the bank. Make it due Friday.", content="Call the bank", due="friday")
    assert agent.tasks.tasks("all")[0]["due_at"] == "friday"


def test_a_due_phrase_that_cannot_be_read_is_kept_as_words_when_the_person_said_it(config):
    agent, said = saying(config, "Add a task to water the plants when I'm back", content="Water the plants", due="when I'm back")
    (task,) = agent.tasks.tasks("all")
    assert task["due_at"] == "when I'm back" and task["due_ts"] is None
    assert said == "Added to the to-do list: Water the plants, due \"when I'm back\" (kept as words: that is not a date this can read)."


@pytest.mark.parametrize("due", ["", "   ", None])
def test_an_empty_due_date_is_no_due_date_and_does_not_bounce(config, due):
    agent, said = saying(config, "Add a task to buy oat milk", content="Buy oat milk", due=due)
    assert said == "Added to the to-do list: Buy oat milk." and agent.tasks.tasks("all")[0]["due_at"] is None


@pytest.mark.parametrize("due", [5, ["Friday"], True])
def test_a_due_date_that_is_not_words_is_left_out_in_a_turn(config, due):
    agent, said = saying(config, "Add a task to buy oat milk by Friday", content="Buy oat milk", due=due)
    assert agent.tasks.tasks("all")[0]["due_at"] is None and "left out" in said


def test_outside_a_turn_a_due_date_is_taken_as_given(config):
    agent = make_agent(config)
    assert agent.add_task("Call mum", "Friday") == "Added to the to-do list: Call mum, due Friday 25 Sep 2026."
    assert agent.add_task("Other", 5).startswith("Not added: when it is due must be words")


# ---- refusals the model can relay -------------------------------------------------------------------

def test_the_same_task_twice_is_refused_and_the_model_is_told_where_it_is(config):
    agent = make_agent(config, add_call(content="Buy oat milk"), text_reply("ok"))
    ask(agent, "Add a task to buy oat milk")
    agent.client.replies.extend([add_call(content="buy OAT milk"), text_reply("ok")])
    ask(agent, "Add a task to buy oat milk")
    assert told(agent) == "Not added: that task is already on the list (#1). Do not add it again; tell the user it is already there."
    assert contents(agent) == ["Buy oat milk"]


def test_a_full_list_is_refused_and_the_model_is_told_to_say_so(config, monkeypatch):
    monkeypatch.setattr(diya_tasks, "MAX_OPEN", 1)
    agent = make_agent(config)
    agent.add_task("first")
    _, said = saying(config, "Add a task to buy oat milk", content="Buy oat milk")
    assert said == "Not added: the list already has 1 open tasks; none more until some are done. Tell the user to tick some off first."


@pytest.mark.parametrize("content, why", [
    ("", "a task needs words"), ("   ", "a task needs words"), (None, "a task must be words"), (5, "a task must be words"),
    ("x" * 201, "a task is at most 200 characters"), ("pay" + chr(7) + "bill", "a task cannot contain the character"),
])
def test_words_that_are_not_a_task_are_refused_with_the_reason(config, content, why):
    agent, said = saying(config, "Add a task to pay the bill", content=content)
    assert said.startswith(f"Not added: {why}") and said.endswith(". Fix that and try again, or tell the user.")
    assert contents(agent) == []


def test_a_tool_error_such_as_an_unknown_argument_saves_nothing(config):
    agent, said = saying(config, "Add a task to buy oat milk", content="Buy oat milk", priority=4)
    assert said.startswith("Error:") and contents(agent) == []


# ---- reading the list ---------------------------------------------------------------------------------

HEADER = "Tasks on the to-do list inside Diya (this is not Todoist):"


def test_an_empty_list_says_so_and_whose_list_it_is(config):
    agent = make_agent(config)
    assert agent.list_tasks() == "No open tasks on the to-do list inside Diya (this is not Todoist)."
    assert agent.list_tasks("done") == "No done tasks on the to-do list inside Diya (this is not Todoist)."
    assert agent.list_tasks("all") == "No tasks on the to-do list inside Diya (this is not Todoist)."


def test_the_list_is_one_line_per_task_with_its_number_and_due_date(config):
    agent = make_agent(config)
    agent.add_task("Buy oat milk")
    agent.add_task("Send the invoice", "Friday")
    agent.add_task("Prepare slides", "tomorrow at 5pm")
    agent.add_task("Water the plants", "when I'm back")
    assert agent.list_tasks() == "\n".join([
        HEADER, "#1: Buy oat milk", "#2: Send the invoice (due Friday 25 Sep 2026)", "#3: Prepare slides (due Thursday 24 Sep 2026, 17:00)",
        "#4: Water the plants (due asked as \"when I'm back\")",
    ])


def test_done_tasks_are_listed_only_when_asked_for_and_marked(config):
    agent = make_agent(config)
    agent.add_task("a")
    agent.add_task("b")
    agent.tasks.complete(1)
    assert agent.list_tasks() == f"{HEADER}\n#2: b"
    assert agent.list_tasks("done") == f"{HEADER}\n#1: a (done)"
    assert agent.list_tasks("all") == f"{HEADER}\n#2: b\n#1: a (done)"
    assert agent.list_tasks("  ALL ") == agent.list_tasks("all")
    assert agent.list_tasks(None) == agent.list_tasks("") == agent.list_tasks("   ") == f"{HEADER}\n#2: b"


@pytest.mark.parametrize("status", ["pending", "everything", 5, ["open"]])
def test_an_unknown_status_is_told_what_the_choices_are(config, status):
    assert make_agent(config).list_tasks(status) == "status must be one of open, done, all."


def test_a_long_list_is_cut_after_thirty_and_says_there_is_more(config):
    agent = make_agent(config)
    for n in range(31):
        agent.add_task(f"task {n}")
    lines = agent.list_tasks().split("\n")
    assert len(lines) == 32 and lines[0] == HEADER and lines[1] == "#1: task 0" and lines[30] == "#30: task 29" and lines[31] == "...and more."
    agent.tasks.complete(31)
    assert agent.list_tasks().split("\n")[-1] == "#30: task 29"  # exactly thirty left: nothing more to say


def test_reading_the_list_never_loads_more_than_one_past_what_it_shows(config, monkeypatch):
    agent = make_agent(config)
    asked = []
    real = agent.tasks.tasks
    monkeypatch.setattr(agent.tasks, "tasks", lambda state="open", limit=None: asked.append((state, limit)) or real(state, limit=limit))
    agent.list_tasks()
    agent.list_tasks("done")
    assert asked == [("open", diya.MAX_TASKS_SHOWN + 1), ("done", diya.MAX_TASKS_SHOWN + 1)]  # one more than shown tells it there is more


def test_the_model_reads_the_list_through_the_tool_loop(config):
    agent = make_agent(config, tool_reply("list_tasks", '{"status": "open"}'), text_reply("You have one task."))
    agent.add_task("Buy oat milk")
    answer, tools = ask(agent, "What's on my to-do list?")
    assert tools == ["list_tasks"] and answer == "You have one task." and told(agent) == f"{HEADER}\n#1: Buy oat milk"


# ---- what a later proposal says it came after --------------------------------------------------------

def test_the_owners_own_list_is_not_outside_content_for_a_proposal_later_in_the_turn(config):
    replies = [tool_calls_reply(("add_task", '{"content": "x"}'), ("list_tasks", "{}"), ("search_notes", '{"query": "b"}')),
               tool_reply("propose_add_task", '{"title": "y"}'), text_reply("ok")]
    agent = make_agent(config, *replies, kinds=(task_kind(),))
    agent._functions["search_notes"] = lambda query: "a note"
    ask(agent, "Add a task to x and please add a task y")
    (action,) = agent.actions.actions()
    assert action["taint_sources"] == ["search_notes"]


def test_the_set_of_own_list_tools_is_exactly_these_three():
    assert diya.OWN_LIST_TOOLS == {"list_reminders", "list_tasks", "add_task"}


def test_the_list_tool_says_it_is_not_todoists_and_the_refusal_says_that_nothing_was_added():
    description = {t["function"]["name"]: t["function"] for t in diya.TOOLS}["list_tasks"]["description"]
    assert "not Todoist" in description and "list_todoist_tasks" in description and "list_reminders" in description
    assert "NOTHING was added" in diya.TASK_NOT_ASKED and "Do not say you added" in diya.TASK_NOT_ASKED
