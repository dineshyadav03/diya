"""The model's side of the approval gate (docs/ACTIONS_DESIGN.md, unit A2): what Agent offers, what a proposal
records, and what the model is told back.

What this proves: a kind of action's tool only ever PROPOSES (the effect is never performed in the tool loop);
it is offered only while its connector is connected; a proposal remembers the owner's message it answers and
which tools ran before it in the same turn, per thread of control and never across turns; the model's own
words never decide the description, the taint or the ids; and a proposal that is refused is refused in one
plain sentence the model can relay. Every kind here is a fake -- the real registry is empty.
"""
import json
import threading
import types
from datetime import timedelta

import pytest

import diya
import diya_actions
import diya_config
import diya_connectors
from diya_actions import Actions
from fakes import FakeClient, task_kind, text_reply, tool_calls_reply, tool_reply

PROPOSE = "propose_add_task"


def agent_with(*kinds, replies=(), tmp_path=None):
    config = diya_config.load_config()
    return diya.Agent(config, client=FakeClient(list(replies)), action_kinds=kinds)


def ask(agent, text="please add a task", **ids):
    return agent.ask([{"role": "user", "content": text}], **ids)


def tool_text(agent):
    """What the model was last told by a tool: the content of the last role=tool message it was sent."""
    for call in reversed(agent.client.chat_calls):
        for message in reversed(call["messages"]):
            if isinstance(message, dict) and message.get("role") == "tool":
                return message["content"]
    return None


# ---- what the model is offered ------------------------------------------------------------------

def test_with_no_kinds_the_model_is_offered_exactly_the_tools_it_always_had():
    agent = agent_with()
    assert agent.tools == diya.TOOLS
    assert diya_actions.KINDS == () and agent.actions.kinds == ()
    assert agent._proposal_tools == set()


def test_a_kind_that_needs_no_connector_is_offered(tmp_path):
    kind = task_kind(connector=None)
    agent = agent_with(kind)
    assert agent.tools == diya.TOOLS + [kind.tool]
    assert PROPOSE in agent._functions and agent._proposal_tools == {PROPOSE}


def test_a_kind_is_offered_only_while_its_connector_is_connected(tmp_path):
    kind = task_kind(connector="todoist")
    agent = agent_with(kind)
    assert kind.tool not in agent.tools  # not connected: invisible to the model
    diya_connectors.store_token(agent.config, "todoist", "a-token")
    assert agent.tools[-1] == kind.tool  # connected: offered on the very next turn, no restart
    diya_connectors.disconnect(agent.config, "todoist")
    assert kind.tool not in agent.tools


def test_a_kind_the_model_cannot_propose_is_never_offered_or_registered():
    kind = task_kind(tool=False)
    agent = agent_with(kind)
    assert agent.tools == diya.TOOLS
    assert agent._proposal_tools == set()
    assert agent._functions.keys() == agent_with()._functions.keys()


@pytest.mark.parametrize("taken", ["add_reminder", "web_search", "list_files", "search_notion", "list_calendar_events"])
def test_a_tool_name_another_tool_already_has_refuses_to_start(taken):
    with pytest.raises(ValueError, match="already another tool's"):
        agent_with(task_kind(tool_name=taken))


def test_two_kinds_may_not_share_a_tool_name():
    with pytest.raises(ValueError, match="already another tool's"):
        agent_with(task_kind(), task_kind(name="other_task"))


def test_two_kinds_with_different_tool_names_are_both_offered():
    agent = agent_with(task_kind(), task_kind(name="other_task", tool_name="propose_other_task"))
    assert agent._proposal_tools == {PROPOSE, "propose_other_task"}
    assert len(agent.tools) == len(diya.TOOLS) + 2


def test_a_tool_spec_must_be_a_real_function_spec():
    good = task_kind().tool
    from diya_actions import ActionKind

    def make(tool):
        return ActionKind("add_task", "Add", None, lambda a: None, lambda a: "x", lambda c, a: "x", tool)

    assert make(good).tool_name == PROPOSE and make(None).tool_name is None
    function = good["function"]
    for bad in (
        "not a dict", {}, {"type": "function"}, {"type": "tool", "function": function},
        {"type": "function", "function": {**function, "name": "Propose Add"}},
        {"type": "function", "function": {**function, "name": 5}},
        {"type": "function", "function": {**function, "description": ""}},
        {"type": "function", "function": {**function, "description": "   "}},
        {"type": "function", "function": {**function, "description": None}},
        {"type": "function", "function": {**function, "parameters": "none"}},
        {"type": "function", "function": {"name": "x", "description": "d"}},
    ):
        with pytest.raises(ValueError):
            make(bad)


# ---- proposing: the model's tool call records and performs nothing ----------------------------------

def test_a_proposal_is_recorded_and_the_effect_is_never_performed():
    executed = []
    agent = agent_with(task_kind(executed=executed),
                       replies=[tool_reply(PROPOSE, '{"title": "buy milk"}'), text_reply("It is waiting for you.")])
    answer, called = ask(agent, "add a task: buy milk", thread_id=4, message_id=9)
    assert (answer, called) == ("It is waiting for you.", [PROPOSE])
    assert executed == []  # the gate: nothing happened
    (action,) = agent.actions.actions()
    assert action["status"] == "pending" and action["kind"] == "add_task"
    assert action["args"] == {"title": "buy milk"}
    assert action["summary"] == "Add the task 'buy milk'"
    assert (action["thread_id"], action["message_id"]) == (4, 9)
    assert action["tainted"] is False and action["taint_sources"] == []
    assert [event for event, _actor, _at, _detail in agent.actions.events(action["id"])] == ["proposed"]


def test_the_model_is_told_it_is_only_a_proposal_and_what_to_say():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "buy milk"}'), text_reply("ok")])
    ask(agent)
    told = tool_text(agent)
    assert told == (
        "Proposed as action #1: Add the task 'buy milk'. Nothing has happened yet: the owner has to approve it on "
        "the Actions page. Tell the owner it is waiting for them, and do not say it is done."
    )


def test_text_arguments_are_tidied_and_the_owner_sees_the_tidied_text():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, json.dumps({"title": "  buy \t milk\n today ", "due": " tomorrow  "})),
                                              text_reply("ok")])
    ask(agent)
    (action,) = agent.actions.actions()
    assert action["args"] == {"title": "buy milk today", "due": "tomorrow"}
    assert action["summary"] == "Add the task 'buy milk today', due tomorrow"


def test_normalise_args_changes_whitespace_in_text_and_nothing_else():
    assert diya_actions.normalise_args({"a": " x  y\n", "b": 3, "c": None, "d": True, "e": 1.5}) == {
        "a": "x y", "b": 3, "c": None, "d": True, "e": 1.5}
    assert diya_actions.normalise_args({"a": "   "}) == {"a": ""}
    assert diya_actions.normalise_args("not a dict") == "not a dict"
    assert diya_actions.normalise_args(None) is None


def test_a_control_character_is_still_refused_after_tidying():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, json.dumps({"title": "buy\x1b[31m milk"})), text_reply("ok")])
    ask(agent)
    assert agent.actions.actions() == []
    assert tool_text(agent).startswith("Not proposed: argument 'title' is not plain single-line text")


@pytest.mark.parametrize("arguments, reason", [
    ('{}', "a task needs a title"),
    ('{"title": 5}', "a task needs a title"),
    ('{"title": "x", "when": "now"}', "a task has no when"),
    ('{"title": "x", "kind": "something_else"}', "a task has no kind"),
    ('{"title": "' + "x" * 101 + '"}', "a title is at most 100 characters"),
    ('{"title": "   "}', "argument 'title' is not plain single-line text"),
])
def test_a_proposal_that_is_refused_is_refused_in_one_plain_sentence_and_nothing_is_recorded(arguments, reason):
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, arguments), text_reply("ok")])
    ask(agent)
    assert agent.actions.actions() == []
    told = tool_text(agent)
    assert told.startswith(f"Not proposed: {reason}")
    assert told.endswith(". Nothing was recorded; tell the owner so, plainly.")


def test_an_argument_the_model_calls_kind_cannot_collide_with_the_kind_itself():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "x", "kind": "evil", "self": 1}'), text_reply("ok")])
    ask(agent)  # would raise TypeError out of the loop if `kind` were an ordinary parameter
    assert agent.actions.actions() == []
    assert tool_text(agent).startswith("Not proposed: a task has no kind, self")


def test_the_same_proposal_twice_is_refused_the_second_time():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "buy milk"}'), text_reply("ok"),
                                              tool_reply(PROPOSE, '{"title":  "buy milk "}'), text_reply("ok")])
    ask(agent)
    ask(agent)
    assert len(agent.actions.actions()) == 1
    assert tool_text(agent).startswith("Not proposed: that exact action is already waiting for the owner")


def test_the_model_calling_a_tool_that_was_not_offered_cannot_get_past_the_connector():
    kind = task_kind(connector="todoist")  # never connected here
    agent = agent_with(kind, replies=[tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")])
    assert kind.tool not in agent.tools
    ask(agent)  # a small model sometimes calls a tool it was not given
    assert agent.actions.actions() == []
    assert tool_text(agent).startswith("Not proposed: Add a task needs todoist connected, and it is not")


def test_too_many_proposals_from_one_message_are_refused_and_the_model_is_told():
    titles = ["a", "b", "c", "d"]
    replies = [tool_calls_reply(*[(PROPOSE, json.dumps({"title": t})) for t in titles]), text_reply("ok")]
    agent = agent_with(task_kind(), replies=replies)
    ask(agent, message_id=7)
    assert [a["args"]["title"] for a in agent.actions.actions()] == ["a", "b", "c"]
    assert tool_text(agent).startswith(f"Not proposed: one message can lead to at most {diya_actions.MAX_PER_TURN} actions")


def test_a_fact_share_turn_has_no_tools_so_nothing_can_be_proposed():
    agent = agent_with(task_kind(), replies=[text_reply("Noted.")])
    ask(agent, "my flight is on Friday at 6")
    assert agent.client.chat_calls[0]["tools"] is None
    assert agent.actions.actions() == []


# ---- the taint record: which tools ran before the proposal, in this turn only --------------------------

def agent_with_reads(*kinds, replies):
    agent = agent_with(*kinds, replies=replies)
    agent._functions["web_search"] = lambda query: "a web page said something"
    agent._functions["search_notes"] = lambda query: "a note"
    return agent


def test_the_tools_that_ran_before_a_proposal_are_recorded_in_order_once_each():
    replies = [tool_calls_reply(("web_search", '{"query": "a"}'), ("search_notes", '{"query": "b"}'), ("web_search", '{"query": "c"}')),
               tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")]
    agent = agent_with_reads(task_kind(), replies=replies)
    ask(agent)
    (action,) = agent.actions.actions()
    assert action["tainted"] is True
    assert action["taint_sources"] == ["web_search", "search_notes"]


def test_a_tool_that_failed_is_still_listed():
    replies = [tool_reply("web_search", '{"query": "a"}'), tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")]
    agent = agent_with(task_kind(), replies=replies)

    def broken(query):
        raise RuntimeError("the network is down")

    agent._functions["web_search"] = broken
    ask(agent)
    assert agent.actions.actions()[0]["taint_sources"] == ["web_search"]


def test_the_owners_own_reminder_list_is_not_a_source_but_other_tools_are():
    replies = [tool_calls_reply(("list_reminders", "{}"), ("search_notes", '{"query": "b"}')),
               tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")]
    agent = agent_with_reads(task_kind(), replies=replies)
    ask(agent)
    assert agent.actions.actions()[0]["taint_sources"] == ["search_notes"]
    replies = [tool_reply("list_reminders", "{}"), tool_reply(PROPOSE, '{"title": "y"}'), text_reply("ok")]
    agent = agent_with(task_kind(), replies=replies)  # the same database: its action is the newest
    ask(agent)
    assert agent.actions.actions()[-1]["args"] == {"title": "y"}
    assert agent.actions.actions()[-1]["tainted"] is False


def test_a_proposal_is_not_a_source_for_the_proposal_after_it():
    replies = [tool_calls_reply((PROPOSE, '{"title": "a"}'), (PROPOSE, '{"title": "b"}')), text_reply("ok")]
    agent = agent_with(task_kind(), replies=replies)
    ask(agent)
    assert [a["tainted"] for a in agent.actions.actions()] == [False, False]


def test_a_tool_that_runs_after_the_proposal_in_the_same_message_is_not_listed_for_it():
    replies = [tool_calls_reply((PROPOSE, '{"title": "a"}'), ("web_search", '{"query": "z"}')), text_reply("ok")]
    agent = agent_with_reads(task_kind(), replies=replies)
    ask(agent)
    assert agent.actions.actions()[0]["taint_sources"] == []


def test_a_proposal_in_a_later_round_is_tainted_by_a_read_in_an_earlier_one():
    replies = [tool_reply("search_notes", '{"query": "b"}'), tool_reply("web_search", '{"query": "c"}'),
               tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")]
    agent = agent_with_reads(task_kind(), replies=replies)
    ask(agent)
    assert agent.actions.actions()[0]["taint_sources"] == ["search_notes", "web_search"]


def test_what_one_turn_read_is_forgotten_before_the_next_turn():
    replies = [tool_reply("web_search", '{"query": "a"}'), text_reply("ok"),
               tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")]
    agent = agent_with_reads(task_kind(), replies=replies)
    ask(agent, "search the web for a")
    assert agent._turn.reads == []  # the turn that read something has let go of it
    ask(agent, "now add a task")
    assert agent.actions.actions()[0]["tainted"] is False
    assert agent._turn.reads == [] and agent._turn.active is False


def test_a_turn_that_fails_still_forgets_what_it_knew():
    agent = agent_with(task_kind(), replies=[])
    agent.client._chat_error = RuntimeError("the model is down")
    with pytest.raises(RuntimeError):
        ask(agent, message_id=5, thread_id=6)
    assert (agent._turn.thread_id, agent._turn.message_id, agent._turn.reads, agent._turn.active) == (None, None, [], False)


def test_a_proposal_made_outside_a_turn_has_no_chat_and_no_sources():
    agent = agent_with(task_kind())
    told = agent._functions[PROPOSE](title="buy milk")
    assert told.startswith("Proposed as action #1")
    (action,) = agent.actions.actions()
    assert (action["thread_id"], action["message_id"], action["tainted"]) == (None, None, False)


def test_a_turn_without_ids_records_none():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")])
    ask(agent)
    (action,) = agent.actions.actions()
    assert (action["thread_id"], action["message_id"]) == (None, None)


def test_two_turns_at_once_each_keep_their_own_chat_and_their_own_reads(tmp_path):
    barrier = threading.Barrier(2, timeout=10)

    class Scripted:
        """Per turn: read, wait for the other turn to have started too, then propose a task named for the message."""

        def __init__(self):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

        def create(self, model, messages, tools=None, **options):
            last_user = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"][-1]["content"]
            steps = sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "tool")
            if steps == 0:
                return tool_reply("web_search", json.dumps({"query": last_user}), call_id="r")
            if steps == 1:
                return tool_reply(PROPOSE, json.dumps({"title": last_user}), call_id="p")
            return text_reply("done")

    def slow_read(query):
        barrier.wait()  # both turns have started and set their own state before either goes on
        return "result"

    config = diya_config.load_config()
    agent = diya.Agent(config, client=Scripted(), action_kinds=[task_kind()])
    agent._functions["web_search"] = slow_read

    def turn(name, message_id):
        ask(agent, name, thread_id=message_id + 1000, message_id=message_id)

    threads = [threading.Thread(target=turn, args=("alpha", 101)), threading.Thread(target=turn, args=("beta", 202))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    by_title = {a["args"]["title"]: a for a in agent.actions.actions()}
    assert (by_title["alpha"]["message_id"], by_title["alpha"]["thread_id"]) == (101, 1101)
    assert (by_title["beta"]["message_id"], by_title["beta"]["thread_id"]) == (202, 1202)
    assert by_title["alpha"]["taint_sources"] == by_title["beta"]["taint_sources"] == ["web_search"]


# ---- the store hands out message ids, and startup tells the truth about actions --------------------------

def test_adding_a_message_returns_its_id(tmp_path):
    agent = agent_with()
    thread = agent.store.create_thread()
    first = agent.store.add_message(thread, "user", "hi")
    second = agent.store.add_message(thread, "assistant", "hello")
    assert isinstance(first, int) and second == first + 1
    assert [m["id"] for m in agent.store.get_messages_between(first, second)] == [first, second]


def test_startup_says_nothing_when_there_is_nothing_to_say():
    assert diya.actions_startup_lines(agent_with(task_kind())) == []


def build_startup_world():
    """An agent whose action store has one of everything a startup message can mention."""
    from datetime import datetime, timezone

    clock = types.SimpleNamespace(now=datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc))
    agent = agent_with(task_kind())
    agent.actions = Actions(agent.store, agent.config, agent.actions.kinds, lambda: clock.now)
    return agent, clock


def test_startup_counts_what_is_waiting_for_approval():
    agent, _ = build_startup_world()
    agent.actions.propose("add_task", {"title": "a"})
    agent.actions.propose("add_task", {"title": "b"})
    (line,) = diya.actions_startup_lines(agent)
    assert line == "Actions: 2 waiting for your approval (Actions page, or `python diya_actions_cli.py list`)."


def test_startup_moves_a_cut_off_run_to_unknown_and_says_it_will_not_be_run_again():
    agent, clock = build_startup_world()
    stuck = agent.actions.propose("add_task", {"title": "stuck"})
    agent.actions.approve(stuck["id"], stuck["args_hash"], "ui")
    agent.actions.kinds = (task_kind(raises=KeyboardInterrupt()),)  # the process goes down mid-effect
    with pytest.raises(KeyboardInterrupt):
        agent.actions.run(stuck["id"])
    clock.now += timedelta(minutes=5)
    lines = diya.actions_startup_lines(agent)
    assert agent.actions.get(stuck["id"])["status"] == "unknown"
    assert len(lines) == 1 and lines[0].startswith("Actions: 1 action was still running when Diya last stopped")
    assert "will not be run again" in lines[0]
    # later starts remind the owner until they have recorded what happened
    assert diya.actions_startup_lines(agent) == [
        "Actions: 1 with an unknown outcome still needs you to record what happened."]
    agent.actions.resolve(stuck["id"], True, "ui")
    assert diya.actions_startup_lines(agent) == []


def test_startup_says_how_many_were_cut_off_in_the_plural():
    agent, clock = build_startup_world()
    agent.actions.kinds = (task_kind(raises=KeyboardInterrupt()),)
    for title in ("a", "b"):
        action = agent.actions.propose("add_task", {"title": title})
        agent.actions.approve(action["id"], action["args_hash"], "ui")
        with pytest.raises(KeyboardInterrupt):
            agent.actions.run(action["id"])
    clock.now += timedelta(minutes=5)
    (line,) = diya.actions_startup_lines(agent)
    assert line.startswith("Actions: 2 actions were still running when Diya last stopped")


def test_the_api_prints_the_action_lines_after_the_memory_lines_and_before_it_listens(monkeypatch, capsys):
    import diya_web

    seen = []
    monkeypatch.setattr(diya, "actions_startup_lines", lambda agent: seen.append(agent) or ["Actions: a line about actions"])
    monkeypatch.setattr(diya, "memory_startup_lines", lambda agent: ["Memory: a line about memory"])
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    monkeypatch.setattr(diya, "Agent", lambda config=None: types.SimpleNamespace(config=config, warm_up=lambda: None))
    monkeypatch.setattr(diya_web, "WhisperTranscriber", lambda name: types.SimpleNamespace(name=name, warm_up=lambda: None))
    import pathlib

    pathlib.Path("some-host+3.pem").write_text("cert")
    pathlib.Path("some-host+3-key.pem").write_text("key")
    diya_web.main()
    out = capsys.readouterr().out
    assert "Actions: a line about actions" in out
    assert out.index("Memory: a line about memory") < out.index("Actions: a line about actions") < out.index("Diya's API is listening")
    assert len(seen) == 1


def test_the_terminal_chat_prints_the_action_lines_too(monkeypatch, capsys):
    agent = agent_with()
    monkeypatch.setattr(diya, "Agent", lambda: agent)
    monkeypatch.setattr(diya, "warm_up_or_exit", lambda a: None)
    monkeypatch.setattr(diya, "actions_startup_lines", lambda a: ["Actions: a line about actions"])
    monkeypatch.setattr(diya, "memory_startup_lines", lambda a: [])

    def hang_up(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", hang_up)
    monkeypatch.setattr("sys.argv", ["diya.py", "new"])
    diya.main()
    assert "[Actions: a line about actions]" in capsys.readouterr().out


def test_the_unknown_outcome_reminder_is_plural_when_there_is_more_than_one():
    agent, clock = build_startup_world()
    agent.actions.kinds = (task_kind(raises=KeyboardInterrupt()),)
    for title in ("a", "b"):
        action = agent.actions.propose("add_task", {"title": title})
        agent.actions.approve(action["id"], action["args_hash"], "ui")
        with pytest.raises(KeyboardInterrupt):
            agent.actions.run(action["id"])
    clock.now += timedelta(minutes=5)
    diya.actions_startup_lines(agent)  # the first start moves them to unknown and says so
    assert diya.actions_startup_lines(agent) == ["Actions: 2 with an unknown outcome still need you to record what happened."]


def test_a_sentence_for_the_model_does_not_double_a_full_stop():
    from diya_actions import ActionKind, InvalidArgs

    def refuse(args):
        raise InvalidArgs("that is too long.")

    agent = agent_with(ActionKind("add_task", "Add", None, refuse, lambda a: "x", lambda c, a: "x", task_kind().tool),
                       replies=[tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")])
    ask(agent)
    assert tool_text(agent) == "Not proposed: that is too long. Nothing was recorded; tell the owner so, plainly."
    kind = ActionKind("add_task", "Add", None, lambda a: None, lambda a: "Do the thing.", lambda c, a: "x", task_kind().tool)
    agent = agent_with(kind, replies=[tool_reply(PROPOSE, '{"title": "x"}'), text_reply("ok")])
    ask(agent)
    assert tool_text(agent).startswith("Proposed as action #1: Do the thing. Nothing has happened yet")


# ---- every way of asking the model hands the chat and the message to the proposal ------------------------

def test_the_chat_route_records_which_chat_and_message_a_proposal_came_from(monkeypatch):
    import diya_web
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DIYA_REQUIRE_TOKEN", "0")
    config = diya_config.load_config()
    agent = diya.Agent(config, client=FakeClient([tool_reply(PROPOSE, '{"title": "x"}'), text_reply("waiting")]),
                       action_kinds=[task_kind()])
    client = TestClient(diya_web.create_app(config, agent, transcriber=object()), base_url="https://localhost")
    answer = client.post("/api/chat", json={"message": "add a task"}).json()
    (action,) = agent.actions.actions()
    (user_message,) = [m for m in agent.store.get_messages_between(1, 99) if m["role"] == "user"]
    assert action["thread_id"] == answer["thread_id"] and action["message_id"] == user_message["id"]


def test_the_terminal_chat_records_which_chat_and_message_a_proposal_came_from(monkeypatch):
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "x"}'), text_reply("waiting")])
    thread = agent.store.create_thread()
    lines = iter(["add a task"])

    def typed(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", typed)
    diya.chat_loop(agent, thread, [])
    (action,) = agent.actions.actions()
    (user_message,) = [m for m in agent.store.get_messages_between(1, 99) if m["role"] == "user"]
    assert (action["thread_id"], action["message_id"]) == (thread, user_message["id"])


def test_a_one_message_terminal_run_records_which_chat_and_message_a_proposal_came_from(monkeypatch):
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "x"}'), text_reply("waiting")])
    thread = agent.store.create_thread()
    monkeypatch.setattr(diya, "Agent", lambda: agent)
    monkeypatch.setattr(diya, "warm_up_or_exit", lambda a: None)
    monkeypatch.setattr("sys.argv", ["diya.py", str(thread), "add a task"])
    diya.main()
    (action,) = agent.actions.actions()
    (user_message,) = [m for m in agent.store.get_messages_between(1, 99) if m["role"] == "user"]
    assert (action["thread_id"], action["message_id"]) == (thread, user_message["id"])
