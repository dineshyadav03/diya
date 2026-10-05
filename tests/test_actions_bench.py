"""diya_actions_bench.py: the measurement of when the model adds a task (docs/ACTIONS_DESIGN.md, section 6; docs/TASKS_DESIGN.md).

The numbers in those documents come from this script, so the script is tested: against a scripted model (no Ollama), it must
drive the real Agent, count reaching for a tool and recording a task as the two different things they are, tell the list from
Todoist, stub every tool that could touch the network or the disk, leave nothing behind, and say what it measured.
"""
import io
import json

import pytest

import diya
import diya_actions_bench as bench
import diya_intent
from fakes import FakeClient, text_reply, tool_reply
from labelled_task_requests import AMBIGUOUS, ASKED, NOT_ASKED, all_not_asked


REAL_BUILD_AGENT = bench.build_agent  # kept, because some tests replace bench.build_agent with a scripted one


def scripted(tmp_path, replies, todoist=False):
    """The benchmark's own agent, on a scripted model instead of Ollama."""
    agent = REAL_BUILD_AGENT("a-model-that-is-never-called", str(tmp_path), todoist)
    agent._client = FakeClient(list(replies))
    return agent


def add(arguments):
    return tool_reply(bench.LIST_TOOL, json.dumps(arguments))


def propose(arguments):
    return tool_reply(bench.TODOIST_TOOL, json.dumps(arguments))


def names(agent):
    return [tool["function"]["name"] for tool in agent.tools]


# ---- the benchmark's agent ---------------------------------------------------------------------------

def test_the_benchmark_agent_offers_the_list_always_and_todoist_only_when_asked_and_never_reaches_a_real_service(tmp_path):
    agent = REAL_BUILD_AGENT("some-model", str(tmp_path))
    assert agent.config.model == "some-model"
    assert bench.LIST_TOOL in names(agent) and bench.TODOIST_TOOL not in names(agent)
    connected = REAL_BUILD_AGENT("some-model", str(tmp_path / "other"), True)
    assert bench.LIST_TOOL in names(connected) and bench.TODOIST_TOOL in names(connected)  # a made-up token: Todoist counts as connected
    assert agent.config.db_path.startswith(str(tmp_path))  # a temporary database, never the real one
    for name, args, expected in (("web_search", ("x",), "Top result"), ("get_weather", ("x",), "Sunny"), ("search_notes", ("x",), "A note"),
                                 ("list_files", (), "notes.txt"), ("list_reminders", (), "No pending"), ("list_todoist_tasks", (), "Buy milk")):
        assert expected in agent._functions[name](*args), name


def test_the_list_itself_is_not_stubbed_so_reading_it_is_measured_as_it_really_is(tmp_path):
    agent = REAL_BUILD_AGENT("m", str(tmp_path))
    assert agent._functions["list_tasks"] == agent.list_tasks and agent._functions[bench.LIST_TOOL] == agent.add_task


def test_a_reminder_the_model_saves_is_recorded_not_written_to_any_database(tmp_path):
    agent = REAL_BUILD_AGENT("m", str(tmp_path))
    assert agent._functions["add_reminder"]("call mum", None) == "Reminder saved: call mum"
    assert agent.bench_reminders == ["call mum"] and agent.store.reminders("all") == []


def test_the_two_tools_name_where_a_task_ends_up_and_what_they_call_its_due_date():
    assert bench.WHERE == {"add_task": "list", "propose_todoist_task": "todoist"}
    assert bench.DUE_FIELD == {"add_task": "due", "propose_todoist_task": "due_string"}
    assert bench.PROPOSE == bench.TODOIST_TOOL


@pytest.mark.parametrize("text, todoist, where", [
    ("Add a task to buy oat milk", False, "list"), ("Add a task to buy oat milk", True, "list"),
    ("add 'call the dentist' to my Todoist", True, "todoist"), ("add 'call the dentist' to my Todoist", False, None),
    ("todoist: add buy stamps", True, "todoist"), ("Put 'renew passport' on my to-do list", True, "list"),
])
def test_where_a_task_should_end_up(text, todoist, where):
    assert bench.expected_where(text, todoist) == where


# ---- asking one message ------------------------------------------------------------------------------

def test_a_task_that_was_asked_for_goes_on_the_list_and_is_recorded_then_cleared_away(tmp_path):
    agent = scripted(tmp_path, [add({"content": "Buy oat milk"}), text_reply("Added."), add({"content": "Buy oat milk"}), text_reply("Added.")])
    result = bench.ask_once(agent, "Add a task to buy oat milk")
    assert bench.proposed(result)
    assert [(a["tool"], a["args"]) for a in result["attempts"]] == [("add_task", {"content": "Buy oat milk"})]
    assert result["attempts"][0]["result"] == "Added to the to-do list: Buy oat milk."
    assert result["recorded"] == [{"where": "list", "args": {"content": "Buy oat milk"}}]
    assert result["tools"] == [bench.LIST_TOOL] and result["answer"] == "Added."
    assert agent.tasks.tasks("open") == []  # the next message starts clean...
    again = bench.ask_once(agent, "Add a task to buy oat milk")  # ...so the same words are not refused as a copy
    assert again["recorded"] == [{"where": "list", "args": {"content": "Buy oat milk"}}]


def test_a_task_that_names_todoist_is_a_card_for_the_owner_when_it_is_connected_and_is_cleared_away(tmp_path):
    agent = scripted(tmp_path, [propose({"content": "Buy oat milk"}), text_reply("It is waiting for you.")], todoist=True)
    result = bench.ask_once(agent, "Add a task to Todoist to buy oat milk")
    assert [(a["tool"], a["args"]) for a in result["attempts"]] == [("propose_todoist_task", {"content": "Buy oat milk"})]
    assert result["attempts"][0]["result"].startswith("Proposed as action #1")
    assert result["recorded"] == [{"where": "todoist", "args": {"content": "Buy oat milk"}}]
    assert agent.actions.pending() == [] and agent.actions.counts()["rejected"] == 1
    assert agent.tasks.tasks("all") == []  # nothing reached the list


def test_a_task_nobody_asked_for_is_reached_for_but_not_recorded(tmp_path):
    agent = scripted(tmp_path, [add({"content": "Buy milk"}), text_reply("Noted.")])
    result = bench.ask_once(agent, "I need to buy milk")
    assert bench.proposed(result) and result["recorded"] == [] and agent.tasks.tasks("all") == []
    assert result["attempts"][0]["result"] == diya.TASK_NOT_ASKED


def test_todoists_tool_without_todoist_in_the_message_is_refused_even_if_the_message_asks_for_a_task(tmp_path):
    agent = scripted(tmp_path, [propose({"content": "Buy milk"}), text_reply("ok")], todoist=True)
    result = bench.ask_once(agent, "Add a task to buy milk")
    assert bench.proposed(result) and result["recorded"] == []


def test_the_lists_tool_with_todoist_in_the_message_is_refused_and_says_whose_it_is(tmp_path):
    agent = scripted(tmp_path, [add({"content": "Buy milk"}), text_reply("ok")], todoist=True)
    result = bench.ask_once(agent, "Add a task to Todoist to buy milk")
    assert result["recorded"] == [] and result["attempts"][0]["result"] == diya.TASK_IS_TODOISTS


def test_a_message_the_model_just_answers_has_no_attempt_and_nothing_recorded(tmp_path):
    agent = scripted(tmp_path, [text_reply("Paris.")])
    result = bench.ask_once(agent, "What's the capital of France?")
    assert not bench.proposed(result) and result["attempts"] == [] and result["recorded"] == [] and result["tools"] == []


def test_a_made_up_due_date_is_visible_in_the_attempt_and_left_off_the_record(tmp_path):
    agent = scripted(tmp_path, [add({"content": "Call mum", "due": "tomorrow at 5pm"}), text_reply("ok")])
    result = bench.ask_once(agent, "add task call mum")
    assert result["attempts"][0]["args"] == {"content": "Call mum", "due": "tomorrow at 5pm"}  # what the model chose
    assert result["recorded"] == [{"where": "list", "args": {"content": "Call mum"}}]  # what the owner would see


def test_a_due_date_the_person_said_is_on_the_record(tmp_path):
    agent = scripted(tmp_path, [add({"content": "Call mum", "due": "Friday"}), text_reply("ok")])
    result = bench.ask_once(agent, "add task call mum Friday")
    assert result["recorded"] == [{"where": "list", "args": {"content": "Call mum", "due": "Friday"}}]


def test_a_made_up_due_date_on_todoist_is_left_off_its_card_too(tmp_path):
    agent = scripted(tmp_path, [propose({"content": "Call mum", "due_string": "tomorrow at 5pm"}), text_reply("ok")], todoist=True)
    result = bench.ask_once(agent, "add task call mum to Todoist")
    assert result["attempts"][0]["args"] == {"content": "Call mum", "due_string": "tomorrow at 5pm"}
    assert result["recorded"] == [{"where": "todoist", "args": {"content": "Call mum"}}]


def test_a_reminder_the_model_saves_while_answering_is_reported_for_reference(tmp_path):
    agent = scripted(tmp_path, [tool_reply("add_reminder", json.dumps({"content": "call the plumber"})), text_reply("Saved.")])
    result = bench.ask_once(agent, "Make a note to call the plumber")
    assert result["reminders"] == ["call the plumber"] and not bench.proposed(result)


def test_one_message_s_reminders_are_not_counted_against_the_next(tmp_path):
    agent = scripted(tmp_path, [tool_reply("add_reminder", json.dumps({"content": "call the plumber"})), text_reply("Saved."), text_reply("Paris.")])
    assert bench.ask_once(agent, "Make a note to call the plumber")["reminders"] == ["call the plumber"]
    assert bench.ask_once(agent, "What's the capital of France?")["reminders"] == []


def test_the_measured_functions_are_put_back_after_every_message(tmp_path):
    agent = scripted(tmp_path, [text_reply("a"), add({"content": "x"}), text_reply("b")], todoist=True)
    before = {name: agent._functions[name] for name in bench.WHERE}
    bench.ask_once(agent, "hello")
    assert {name: agent._functions[name] for name in bench.WHERE} == before
    bench.ask_once(agent, "add a task x")
    assert {name: agent._functions[name] for name in bench.WHERE} == before


def test_the_functions_put_back_even_when_the_model_fails(tmp_path):
    agent = scripted(tmp_path, [], todoist=True)
    agent.client._chat_error = RuntimeError("Ollama is down")
    before = {name: agent._functions[name] for name in bench.WHERE}
    with pytest.raises(RuntimeError):
        bench.ask_once(agent, "hello")
    assert {name: agent._functions[name] for name in bench.WHERE} == before


def test_when_todoist_is_not_connected_its_tool_is_not_offered_and_asking_still_works(tmp_path):
    agent = scripted(tmp_path, [text_reply("a")])
    assert bench.TODOIST_TOOL not in names(agent)  # registered, as always, but never shown to the model
    assert bench.ask_once(agent, "hello")["tools"] == []


def test_what_the_tool_loop_prints_does_not_reach_the_report(tmp_path, capsys):
    agent = scripted(tmp_path, [add({"content": "x"}), text_reply("ok")])
    bench.ask_once(agent, "add a task x")
    assert "[tool call]" not in capsys.readouterr().out


# ---- a whole run ----------------------------------------------------------------------------------------

def test_a_run_asks_every_labelled_message_the_stated_number_of_times(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir, todoist=False: scripted(tmp_path, [text_reply("fine")] * 400))
    results = bench.run_model("m", runs=2, limit=0)
    assert len(results["asked"]) == 2 * len(ASKED)
    assert {c: len(rs) for c, rs in results["not_asked"].items()} == {c: 2 * len(texts) for c, texts in NOT_ASKED.items()}
    assert len(results["ambiguous"]) == 2 * len(AMBIGUOUS)
    assert results["model"] == "m" and results["runs"] == 2 and isinstance(results["seconds"], int) and results["todoist"] is False


def test_a_limited_run_takes_the_first_few_of_each_list_and_skips_the_ambiguous_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir, todoist=False: scripted(tmp_path, [text_reply("fine")] * 100))
    results = bench.run_model("m", runs=1, limit=2)
    assert [r["text"] for r in results["asked"]] == ASKED[:2]
    assert all(len(rs) <= 2 for rs in results["not_asked"].values()) and results["ambiguous"] == []


def test_a_run_says_whether_todoist_was_connected_and_hands_that_on_to_the_agent(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir, todoist=False: seen.append(todoist) or scripted(tmp_path, [text_reply("fine")] * 10))
    assert bench.run_model("m", 1, 1, True)["todoist"] is True and seen == [True]
    assert bench.run_model("m", 1, 1)["todoist"] is False and seen == [True, False]


# ---- the report ----------------------------------------------------------------------------------------

def result(text, attempts=(), recorded=(), tools=(), reminders=(), answer=""):
    """attempts: (tool, args, result); recorded: (where, args)."""
    return {"text": text, "tools": list(tools), "attempts": [{"tool": t, "args": a, "result": r} for t, a, r in attempts],
            "recorded": [{"where": w, "args": a} for w, a in recorded], "reminders": list(reminders), "answer": answer}


SAMPLE = {
    "model": "m", "runs": 1, "seconds": 7, "todoist": False,
    "asked": [
        result("Add a task to buy milk", [("add_task", {"content": "Buy milk"}, "Added to the to-do list: Buy milk.")], [("list", {"content": "Buy milk"})], ["add_task"]),
        result("add task call mum", [("add_task", {"content": "Call mum", "due": "tomorrow at 5pm"}, "Added to the to-do list: Call mum. It has no due")],
               [("list", {"content": "Call mum"})], ["add_task"]),
        result("add a task", [("add_task", {"content": "x", "due": ""}, "Not added: a task needs words")], [], ["add_task"]),
        result("Could you put it on my list?", [], [], []),
        result("add 'x' to my Todoist", [("add_task", {"content": "x"}, "Not added to the to-do list inside Diya: the user named Todoist")], [], ["add_task"]),
    ],
    "not_asked": {
        "needs": [result("I need to buy milk", [("add_task", {"content": "Buy milk"}, "Not added: the user did not ask for a task.")], [], ["add_task"]),
                  result("I want tea")],
        "reminders": [result("Make a note to call the plumber", reminders=["call the plumber"])],
        "reading the list": [result("What's on my to-do list?", tools=["list_tasks"]), result("What do I need to do today?", tools=["list_reminders"]),
                             result("Show my tasks", tools=["list_tasks", "list_reminders"]), result("Any tasks left?")],
    },
    "ambiguous": [result("Add milk to my shopping list", [("add_task", {"content": "Milk"}, "Added")], [("list", {"content": "Milk"})]), result("todo: x")],
}


def report_of(results):
    out = io.StringIO()
    bench.report(results, out)
    return out.getvalue()


def test_the_report_counts_reaching_for_a_tool_and_recording_a_task_separately_and_says_whether_todoist_was_connected():
    text = report_of(SAMPLE)
    assert "Model m: 5 asked, 7 not asked, 1 run(s) each, 7 s. Todoist not connected." in text
    assert "Asked for a task:   the model reached for a task tool in 4 of 5 (80%); a task was recorded in 2 (40%)" in text
    assert "Not asked:          the model reached for a task tool in 1 of 7 (14%); a task was recorded in 0 (0%)" in text
    assert "needs                        reached 1, recorded 0, of 2" in text
    assert "reminders                    reached 0, recorded 0, of 1" in text
    assert "unasked: 'I need to buy milk' -> recorded=False [{'content': 'Buy milk'}]" in text
    assert "Todoist connected" not in text


def test_the_report_says_whether_each_asked_task_ended_up_where_it_should():
    text = report_of(SAMPLE)
    assert "for the to-do list" in text and "recorded in the right place in 2 of 4 (50%)" in text
    assert "naming Todoist, not connected" in text and "recorded in the right place in 1 of 1 (100%)" in text  # refused: right
    assert "naming Todoist, connected" not in text  # none of those messages here
    assert "not as expected: 'add a task'" in text and "not as expected: 'Could you put it on my list?'" in text
    assert "not as expected: 'Add a task to buy milk'" not in text and "not as expected: \"add 'x' to my Todoist\"" not in text


def test_with_todoist_connected_a_message_naming_it_is_right_only_in_todoist():
    connected = dict(SAMPLE, todoist=True, not_asked={}, ambiguous=[], asked=[
        result("add 'x' to my Todoist", [("propose_todoist_task", {"content": "x"}, "Proposed as action #1")], [("todoist", {"content": "x"})], ["propose_todoist_task"]),
        result("Add 'y' to Todoist", [("add_task", {"content": "y"}, "Added to the to-do list: y.")], [("list", {"content": "y"})], ["add_task"]),
        result("Add a task to buy milk", [("add_task", {"content": "Buy milk"}, "Added")], [("list", {"content": "Buy milk"})], ["add_task"]),
    ])
    text = report_of(connected)
    assert "Todoist connected." in text
    assert "naming Todoist, connected" in text and "recorded in the right place in 1 of 2 (50%)" in text
    assert "for the to-do list" in text and "recorded in the right place in 1 of 1 (100%)" in text
    assert "not as expected: \"Add 'y' to Todoist\"" in text and "recorded=['list']" in text


def test_a_task_in_the_wrong_place_is_not_the_right_place_even_though_one_was_recorded():
    wrong = dict(SAMPLE, not_asked={}, ambiguous=[], asked=[
        result("Add a task to buy milk", [("propose_todoist_task", {"content": "Buy milk"}, "Proposed")], [("todoist", {"content": "Buy milk"})], ["propose_todoist_task"])])
    text = report_of(wrong)
    assert "a task was recorded in 1 (100%)" in text and "recorded in the right place in 0 of 1 (0%)" in text
    assert "not as expected: 'Add a task to buy milk'" in text


def test_the_report_counts_an_unasked_message_that_did_end_up_recorded():
    leaky = dict(SAMPLE, asked=[], ambiguous=[], not_asked={
        "needs": [result("I need to buy milk", [("add_task", {"content": "Buy milk"}, "Added to the to-do list: Buy milk.")], [("list", {"content": "Buy milk"})], ["add_task"]),
                  result("I want tea")]})
    text = report_of(leaky)
    assert "Not asked:          the model reached for a task tool in 1 of 2 (50%); a task was recorded in 1 (50%)" in text
    assert "needs                        reached 1, recorded 1, of 2" in text
    assert "unasked: 'I need to buy milk' -> recorded=True [{'content': 'Buy milk'}]" in text


def test_the_report_counts_the_due_dates_the_model_made_up_before_and_after_the_checks():
    text = report_of(SAMPLE)
    assert "Due phrases that are not the person's own words: 1 of 1 the model gave; 0 of 0 on a recorded task" in text
    assert "'add task call mum' -> due 'tomorrow at 5pm'" in text


def test_the_report_reads_the_due_field_each_tool_uses():
    mixed = dict(SAMPLE, not_asked={}, ambiguous=[], asked=[
        result("Add a task to Todoist for later", [("propose_todoist_task", {"content": "x", "due_string": "next week"}, "Proposed")],
               [("todoist", {"content": "x", "due_string": "next week"})], ["propose_todoist_task"]),
        result("Add a task for later", [("add_task", {"content": "x", "due": "soon"}, "Added")], [("list", {"content": "x", "due": "soon"})], ["add_task"])])
    text = report_of(mixed)
    assert "Due phrases that are not the person's own words: 2 of 2 the model gave; 2 of 2 on a recorded task" in text
    assert "-> due 'next week'" in text and "-> due 'soon'" in text


def test_a_field_one_tool_does_not_have_is_not_read_from_the_other():
    other = dict(SAMPLE, not_asked={}, ambiguous=[], asked=[
        result("Add a task for later", [("add_task", {"content": "x", "due_string": "yesterday"}, "Not added")], [], ["add_task"])])
    assert "0 of 0 the model gave" in report_of(other)


def test_the_report_counts_a_due_date_that_survives_as_the_persons_own_words():
    own = dict(SAMPLE, asked=[result("Add a task due tomorrow", [("add_task", {"content": "x", "due": "tomorrow"}, "Added")],
                                     [("list", {"content": "x", "due": "tomorrow"})], ["add_task"])], not_asked={}, ambiguous=[])
    assert "Due phrases that are not the person's own words: 0 of 1 the model gave; 0 of 1 on a recorded task" in report_of(own)


def test_the_report_says_how_the_arguments_the_model_chose_fared():
    text = report_of(SAMPLE)
    assert "Arguments the model chose when asked (4 attempts): a due phrase in 1, empty or null due phrase in 1, unknown arguments in 0, refused by the checks in 2" in text
    assert "refused: {'content': 'x', 'due': ''} -> Not added: a task needs words" in text
    assert "refused: {'content': 'x'} -> Not added to the to-do list inside Diya: the user named Todoist" in text


def test_either_tools_refusal_counts_as_refused_and_so_does_nothing_else():
    assert bench.REFUSED == ("Not added", "Not proposed")


def test_an_argument_the_tool_does_not_have_is_counted_as_unknown():
    odd = dict(SAMPLE, not_asked={}, ambiguous=[], asked=[
        result("Add a task", [("add_task", {"content": "x", "priority": 4}, "Error: add_task() got an unexpected keyword argument 'priority'"),
                              ("propose_todoist_task", {"content": "x", "due_string": "today", "labels": ["a"]}, "Proposed")], [], [])])
    assert "unknown arguments in 2" in report_of(odd)
    ok = dict(odd, asked=[result("Add a task", [("add_task", {"content": "x", "due": "today"}, "Added"), ("propose_todoist_task", {"content": "x", "due_string": "today"}, "P")])])
    assert "unknown arguments in 0" in report_of(ok)


def test_the_report_says_which_tool_read_the_list_when_asked_to():
    text = report_of(SAMPLE)
    assert "Asked to read a list (4 messages): list_tasks in 2, list_reminders in 2, list_todoist_tasks in 0, none of them in 1" in text


def test_a_run_with_no_reading_messages_says_nothing_about_reading():
    assert "Asked to read a list" not in report_of(dict(SAMPLE, not_asked={"needs": [result("I want tea")]}))


def test_the_report_gives_the_reminder_count_for_reference_and_lists_the_ambiguous_ones_unscored():
    text = report_of(SAMPLE)
    assert "(for reference: add_reminder was reached for on 1 of the not-asked messages)" in text
    assert "proposed  'Add milk to my shopping list'" in text and "did not     'todo: x'" in text


def test_percent_of_nothing_is_not_a_number():
    assert bench.percent(1, 4) == "25%" and bench.percent(0, 5) == "0%" and bench.percent(5, 5) == "100%" and bench.percent(0, 0) == "n/a"


# ---- what the model said about it -------------------------------------------------------------------------

@pytest.mark.parametrize("answer, claimed", [
    ("I added a task to your to-do list to pay the electricity bill tomorrow at 5 PM.", True),
    ("I forgot to remind you to pay the bill. I will add this task to your to-do list. You will be reminded.", True),
    ("I've added a reminder to add a task to your to-do list at the end of the year.", True),
    ("I have added the task.", True),
    ("I'll add it to your to-do list.", True),
    ("I just created a task for it.", True),
    ("The task has been added.", True),
    ("I’ve added the task.", True),
    ("Sure.\nI saved it as a task.", True),
    ("I won't add it as a task unless you tell me to, as tasks are only added with your explicit request.", False),
    ("I haven't added anything to your to-do list yet, as you didn't tell me what tasks to add.", False),
    ("I never added a task.", False),
    ("No, I did not add the task.", False),
    ("It seems like no tasks were added since you did not ask me to add any.", False),
    ("I have added a reminder for you to check your printer ink levels tomorrow morning.", False),  # a reminder, not a task
    ("I can't add a task since you didn't ask for one. However, I've saved a reminder for you to turn on the light.", False),
    ("9 times 7 is 63.", False),
    ("", False),
])
def test_what_counts_as_saying_a_task_was_added(answer, claimed):
    assert bench.claims_added(answer) is claimed


@pytest.mark.parametrize("answer", [None, 5, ["I added a task"], b"I added a task"])
def test_something_that_is_not_an_answer_claims_nothing(answer):
    assert bench.claims_added(answer) is False


def test_the_report_counts_answers_that_say_a_task_was_added_when_none_was_recorded():
    said = "I added a task to your to-do list to pay the electricity bill."
    lying = dict(SAMPLE, todoist=False, ambiguous=[], asked=[
        result("Add a task to buy milk", [("add_task", {"content": "Buy milk"}, "Added")], [("list", {"content": "Buy milk"})], ["add_task"], answer=said),
        result("add 'x' to my Todoist", [("add_task", {"content": "x"}, "Not added to the to-do list inside Diya: the user named Todoist")], [], ["add_task"],
               answer="I've added x to your Todoist task list."),
    ], not_asked={
        "needs": [result("I forgot to pay the electricity bill", [("add_task", {"content": "Pay"}, "Not added")], [], ["add_task"], answer=said),
                  result("I want tea", answer="Ok, tea.")],
    })
    text = report_of(lying)
    assert "Said a task was or would be added when none was recorded: 2 of 3 " in text  # the recorded one is true, not counted
    assert "said so: 'I forgot to pay the electricity bill' -> 'I added a task to your to-do list to pay the electricity bill.'" in text
    assert "said so: \"add 'x' to my Todoist\"" in text and "said so: 'Add a task to buy milk'" not in text
    assert "rough pattern match" in text


def test_a_run_where_no_answer_claims_anything_says_zero():
    assert "Said a task was or would be added when none was recorded: 0 of 10 " in report_of(SAMPLE)


# ---- a targeted look ---------------------------------------------------------------------------------------

def test_a_run_limited_to_some_categories_asks_only_those_and_skips_the_asked_and_ambiguous_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir, todoist=False: scripted(tmp_path, [text_reply("fine")] * 400))
    results = bench.run_model("m", 2, 0, False, ["needs and wishes", "reading the list"])
    assert results["asked"] == [] and results["ambiguous"] == []
    assert set(results["not_asked"]) == {"needs and wishes", "reading the list"}
    assert {c: len(rs) for c, rs in results["not_asked"].items()} == {c: 2 * len(NOT_ASKED[c]) for c in results["not_asked"]}


def test_no_categories_means_everything_and_an_empty_list_means_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir, todoist=False: scripted(tmp_path, [text_reply("fine")] * 400))
    for categories in (None, []):
        results = bench.run_model("m", 1, 1, False, categories)
        assert len(results["asked"]) == 1 and set(results["not_asked"]) == set(NOT_ASKED)


def test_the_categories_flag_is_split_trimmed_and_passed_on(monkeypatch):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, todoist=False, categories=None: seen.update(categories=categories) or SAMPLE)
    bench.main(["--categories", "needs and wishes, reading the list ,"], out=io.StringIO())
    assert seen == {"categories": ["needs and wishes", "reading the list"]}
    seen.clear()
    bench.main([], out=io.StringIO())
    assert seen == {"categories": None}


def test_a_category_that_does_not_exist_is_a_clean_failure_that_lists_the_real_ones(monkeypatch, capsys):
    monkeypatch.setattr(bench, "run_model", lambda *args, **kwargs: pytest.fail("must not run"))
    assert bench.main(["--categories", "needs and wishes,bogus"], out=io.StringIO()) == 2
    err = capsys.readouterr().err
    assert "no such category 'bogus'" in err and "needs and wishes" in err and "reading the list" in err


# ---- the guard, scored without the model ----------------------------------------------------------------------

def test_scoring_the_guard_needs_no_model_and_reports_what_it_got_wrong():
    out = io.StringIO()
    assert bench.score_guard(out) == 0
    text = out.getvalue()
    assert f"allowed {len(ASKED)} of {len(ASKED)} (100%)" in text
    assert f"allowed 0 of {len(all_not_asked())} (0%)" in text
    assert "refused  'Add milk to my shopping list'" in text and "allowed  'todo: call the bank'" in text


def test_scoring_says_how_many_of_the_asked_messages_go_to_todoist():
    out = io.StringIO()
    bench.score_guard(out)
    assert "Which list:         5 of the 25 asked go to Todoist; 5 name it" in out.getvalue()


def test_scoring_a_guard_that_is_missing_says_so(monkeypatch):
    monkeypatch.delattr(diya_intent, "is_task_request")
    out = io.StringIO()
    assert bench.score_guard(out) == 1 and "no diya_intent.is_task_request yet" in out.getvalue()


def test_scoring_a_poor_guard_lists_its_mistakes(monkeypatch):
    monkeypatch.setattr(diya_intent, "is_task_request", lambda text: text.startswith("Add"))
    out = io.StringIO()
    bench.score_guard(out)
    text = out.getvalue()
    assert "  refused: " in text and "  allowed: " in text


# ---- the command line ----------------------------------------------------------------------------------------

def test_guard_only_runs_without_a_model():
    out = io.StringIO()
    assert bench.main(["--guard-only"], out=out) == 0 and "Asked for a task:   allowed" in out.getvalue()


def test_a_run_prints_its_report_and_can_save_every_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, todoist=False, categories=None: dict(SAMPLE, model=model, runs=runs))
    out, saved = io.StringIO(), tmp_path / "results.json"
    assert bench.main(["--model", "qwen3:8b", "--runs", "2", "--out", str(saved)], out=out) == 0
    assert "Model qwen3:8b:" in out.getvalue()
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["model"] == "qwen3:8b" and data["runs"] == 2 and len(data["asked"]) == 5
    assert b"\r" not in saved.read_bytes()  # LF, like every text file here


def test_the_default_model_is_the_configured_one_and_todoist_is_off_by_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, todoist=False, categories=None: seen.update(model=model, runs=runs, limit=limit, todoist=todoist) or SAMPLE)
    bench.main([], out=io.StringIO())
    assert seen == {"model": "qwen2.5:3b", "runs": 1, "limit": 0, "todoist": False}


def test_the_todoist_flag_is_passed_on(monkeypatch):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, todoist=False, categories=None: seen.update(todoist=todoist) or SAMPLE)
    bench.main(["--todoist"], out=io.StringIO())
    assert seen == {"todoist": True}


@pytest.mark.parametrize("runs, expected", [("0", 1), ("-3", 1), ("4", 4)])
def test_a_run_count_below_one_is_one(monkeypatch, runs, expected):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, todoist=False, categories=None: seen.update(runs=runs) or SAMPLE)
    bench.main(["--runs", runs], out=io.StringIO())
    assert seen["runs"] == expected


def test_a_model_that_cannot_be_reached_is_a_clean_failure_not_a_traceback(monkeypatch, capsys):
    def down(model, runs, limit, todoist=False, categories=None):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(bench, "run_model", down)
    assert bench.main([], out=io.StringIO()) == 2
    assert "could not run against qwen2.5:3b: connection refused" in capsys.readouterr().err


def test_the_labelled_messages_the_benchmark_uses_are_the_ones_the_guard_tests_use():
    assert len(ASKED) == 25 and sum(len(t) for t in NOT_ASKED.values()) == 51
