"""diya_actions.py: the approval gate and its trail (docs/ACTIONS_DESIGN.md, unit A1).

What this proves: a write is only ever RECORDED by what the model can call; only the owner's approval of
exactly what was shown lets it run; it runs at most once, ever, and a run that was cut off is flagged
rather than repeated; every change is one transaction that moves the status AND records who did it; and
the caps, the expiry and the duplicate rule hold even when two processes try at once. Every kind here is
a fake: nothing in this unit can reach a real account (the real registry is, and must stay, empty).
"""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

import diya_actions
import diya_config
import diya_connectors
import diya_db
from diya_actions import (
    ActionFailed,
    ActionKind,
    ActionUncertain,
    Actions,
    DuplicatePending,
    HashMismatch,
    IllegalTransition,
    InvalidArgs,
    NotConnected,
    TooManyPending,
    TurnLimit,
    UnknownAction,
    UnknownKind,
)

T0 = datetime(2026, 10, 4, 10, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class World:
    """A fake outside world, one fake kind of action wired to it, and the store that gates it."""

    def __init__(self, tmp_path):
        self.config = diya_config.load_config()
        self.store = diya_db.Store(self.config.db_path)
        self.clock = Clock()
        self.calls = []  # every set of arguments `execute` was actually called with
        self.statuses_during = []  # what the database said about the action WHILE execute ran
        self.reply = "created task 1"
        self.raises = None
        self.refuse_validation = False
        self.render_suffix = ""
        self.kind = ActionKind(
            name="add_task", label="Add a task", connector="fakeservice",
            validate=self._validate, render=self._render, execute=self._execute,
        )
        self.actions = Actions(self.store, self.config, (self.kind,), self.clock)
        diya_connectors.store_token(self.config, "fakeservice", "not-a-real-token")

    def _validate(self, args):
        if self.refuse_validation:
            raise InvalidArgs("refused for the test")
        if not isinstance(args.get("title"), str):
            raise InvalidArgs("a task needs a title")
        if len(args["title"]) > 100:
            raise InvalidArgs("a title is at most 100 characters")

    def _render(self, args):
        return f"Add the task {args['title']!r}{self.render_suffix}"

    def _execute(self, config, args):
        self.statuses_during.append([a["status"] for a in self.actions.actions() if a["args"] == args])
        self.calls.append(dict(args))
        if self.raises is not None:
            raise self.raises
        return self.reply

    def propose(self, title="buy milk", **extra):
        return self.actions.propose("add_task", {"title": title}, **extra)

    def approved(self, title="buy milk", **extra):
        action = self.propose(title, **extra)
        return self.actions.approve(action["id"], action["args_hash"], "ui")

    def disconnect(self):
        diya_connectors.disconnect(self.config, "fakeservice")

    def sql(self, statement, params=()):
        conn = self.store.connect()  # through the Store, so the schema exists even before anything else touched it
        try:
            conn.execute(statement, params)
            conn.commit()
        finally:
            conn.close()


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def events(world, action):
    return [(event, actor) for event, actor, _at, _detail in world.actions.events(action["id"])]


# ---- the registry and the kinds ----------------------------------------------------------------

def test_this_module_declares_no_kinds_of_its_own():
    assert not hasattr(diya_actions, "KINDS")  # a kind needs its connector: the real ones are declared beside the connectors


@pytest.mark.parametrize("change", [
    {"name": "Add Task"}, {"name": "1task"}, {"name": ""}, {"name": "x" * 41},
    {"label": ""}, {"label": "   "}, {"label": None},
    {"connector": "Bad Name"}, {"connector": ""},
    {"validate": None}, {"render": "not callable"}, {"execute": 3},
])
def test_a_kind_refuses_to_be_declared_wrongly(change):
    fields = dict(name="add_task", label="Add", connector=None, validate=lambda a: None,
                  render=lambda a: "x", execute=lambda c, a: "x")
    fields.update(change)
    with pytest.raises(ValueError):
        ActionKind(**fields)


def test_a_kind_may_need_no_connector():
    kind = ActionKind("local_thing", "A local thing", None, lambda a: None, lambda a: "x", lambda c, a: "x")
    assert kind.connector is None


def test_by_name_finds_a_kind_or_none(world):
    assert diya_actions.by_name((world.kind,), "add_task") is world.kind
    assert diya_actions.by_name((world.kind,), "other") is None
    assert diya_actions.by_name((), "add_task") is None


# ---- arguments, canonical form and the hash ------------------------------------------------------

def test_arguments_may_be_plain_text_numbers_booleans_and_none():
    args = {"title": "buy milk", "count": 3, "ratio": 1.5, "urgent": False, "due": None}
    assert diya_actions.clean_args(args) == args


@pytest.mark.parametrize("bad", [
    "not a dict", ["title"], None, 3,
    {"title": {"nested": "dict"}}, {"title": ["a", "b"]}, {"title": b"bytes"},
    {"Title": "bad key"}, {"": "empty key"}, {"a b": "space in key"}, {1: "int key"},
    {"title": ""}, {"title": " leading"}, {"title": "trailing "}, {"title": "two  spaces"},
    {"title": "line\nbreak"}, {"title": "tab\there"}, {"title": "escape\x1b[31m"},
    {"title": "bidi\u202eoverride"}, {"title": "zero\u200bwidth"},
    {"title": float("nan")}, {"title": float("inf")}, {"title": float("-inf")},
    {"title": "x" * (diya_actions.MAX_ARGS_CHARS + 1)},
])
def test_arguments_that_are_not_plain_data_are_refused(bad):
    with pytest.raises(InvalidArgs):
        diya_actions.clean_args(bad)


def test_arguments_exactly_at_the_size_limit_are_accepted():
    overhead = len(diya_actions.canonical({"t": ""}))
    args = {"t": "x" * (diya_actions.MAX_ARGS_CHARS - overhead)}
    assert len(diya_actions.canonical(args)) == diya_actions.MAX_ARGS_CHARS
    assert diya_actions.clean_args(args) == args


def test_canonical_form_does_not_depend_on_the_order_arguments_were_given():
    assert diya_actions.canonical({"b": 1, "a": 2}) == diya_actions.canonical({"a": 2, "b": 1}) == '{"a":2,"b":1}'
    assert diya_actions.canonical({"t": "naïve"}) == '{"t":"naïve"}'  # not escaped to ascii


def test_the_hash_binds_the_kind_and_the_exact_arguments():
    base = diya_actions.args_hash("add_task", {"title": "a"})
    assert base == diya_actions.args_hash("add_task", {"title": "a"})
    assert base != diya_actions.args_hash("add_task", {"title": "b"})
    assert base != diya_actions.args_hash("other_kind", {"title": "a"})
    assert len(base) == 64 and set(base) <= set("0123456789abcdef")


# ---- propose: what the model's side may do --------------------------------------------------------

def test_a_proposal_is_recorded_as_pending_and_nothing_is_performed(world):
    action = world.propose("buy milk", thread_id=4, message_id=9)
    assert action["status"] == "pending"
    assert action["kind"] == "add_task"
    assert action["args"] == {"title": "buy milk"}
    assert action["args_hash"] == diya_actions.args_hash("add_task", {"title": "buy milk"})
    assert action["summary"] == "Add the task 'buy milk'"  # built in code from the arguments
    assert (action["thread_id"], action["message_id"]) == (4, 9)
    assert action["tainted"] is False and action["taint_sources"] == []
    assert action["created_at"] == "2026-10-04T10:00:00Z"
    assert action["expires_at"] == "2026-10-05T10:00:00Z"
    assert action["decided_at"] is None and action["executed_at"] is None and action["result"] is None
    assert world.calls == []  # propose never performs anything
    assert events(world, action) == [("proposed", "model")]


def test_the_summary_is_built_by_the_kind_not_taken_from_anything_the_model_said(world):
    action = world.actions.propose("add_task", {"title": "buy milk", "summary": "Pay the electricity bill"})
    assert action["summary"] == "Add the task 'buy milk'"
    assert "electricity" not in action["summary"]


def test_an_unknown_kind_is_refused_and_writes_nothing(world):
    with pytest.raises(UnknownKind):
        world.actions.propose("send_email", {"to": "someone"})
    assert world.actions.actions() == []


def test_arguments_the_kind_refuses_write_nothing(world):
    with pytest.raises(InvalidArgs):
        world.actions.propose("add_task", {"title": 5})
    with pytest.raises(InvalidArgs):
        world.actions.propose("add_task", {"title": "x" * 101})
    with pytest.raises(InvalidArgs):
        world.actions.propose("add_task", {"title": "line\nbreak"})  # refused before the kind even looks
    assert world.actions.actions() == []


def test_a_kind_whose_connector_is_not_connected_cannot_be_proposed(world):
    world.disconnect()
    with pytest.raises(NotConnected):
        world.propose()
    assert world.actions.actions() == []


def test_a_kind_that_needs_no_connector_can_be_proposed_without_one(world):
    local = ActionKind("local_thing", "A local thing", None, lambda a: None, lambda a: "do it", lambda c, a: "done")
    actions = Actions(world.store, world.config, (local,), world.clock)
    assert actions.propose("local_thing", {})["status"] == "pending"


@pytest.mark.parametrize("summary", [None, 5, ["a"]])
def test_a_description_that_is_not_text_is_refused_by_saying_so(world, summary):
    kind = ActionKind("add_task", "Add", "fakeservice", world._validate, lambda a: summary, world._execute)
    with pytest.raises(InvalidArgs, match="must be text"):
        Actions(world.store, world.config, (kind,), world.clock).propose("add_task", {"title": "x"})


@pytest.mark.parametrize("summary", ["", "two\nlines", "x" * (diya_actions.MAX_SUMMARY_CHARS + 1)])
def test_a_description_that_is_not_plain_short_text_is_refused(world, summary):
    world.kind = ActionKind("add_task", "Add", "fakeservice", world._validate, lambda a: summary, world._execute)
    actions = Actions(world.store, world.config, (world.kind,), world.clock)
    with pytest.raises(InvalidArgs):
        actions.propose("add_task", {"title": "x"})
    assert actions.actions() == []


def test_a_description_exactly_at_the_limit_is_accepted(world):
    text = "x" * diya_actions.MAX_SUMMARY_CHARS
    kind = ActionKind("add_task", "Add", "fakeservice", world._validate, lambda a: text, world._execute)
    action = Actions(world.store, world.config, (kind,), world.clock).propose("add_task", {"title": "x"})
    assert action["summary"] == text


def test_the_same_action_cannot_wait_twice(world):
    world.propose("buy milk")
    with pytest.raises(DuplicatePending):
        world.propose("buy milk")
    assert len(world.actions.actions()) == 1
    world.propose("buy bread")  # a different one is fine


def test_the_same_action_may_be_proposed_again_once_the_first_was_decided(world):
    first = world.propose("buy milk")
    world.actions.reject(first["id"], "ui")
    second = world.propose("buy milk")
    assert second["id"] != first["id"] and second["status"] == "pending"


def test_the_database_itself_refuses_a_second_pending_copy_and_an_unknown_status(world):
    first = world.propose("buy milk")
    insert = ("INSERT INTO actions (kind, args, args_hash, summary, status, created_at, expires_at)"
              " VALUES (?, '{}', ?, 's', ?, 't', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        world.sql(insert, ("add_task", first["args_hash"], "pending"))
    with pytest.raises(sqlite3.IntegrityError):
        world.sql(insert, ("add_task", "another-hash", "bogus"))
    world.sql(insert, ("add_task", first["args_hash"], "rejected"))  # not pending: allowed
    assert len(world.actions.actions()) == 2


def test_no_more_than_the_limit_can_wait_at_once(world):
    for n in range(diya_actions.MAX_PENDING):
        world.propose(f"task {n}")
    with pytest.raises(TooManyPending):
        world.propose("one too many")
    assert len(world.actions.pending()) == diya_actions.MAX_PENDING
    world.actions.reject(world.actions.pending()[0]["id"], "ui")
    world.propose("room again")


def test_one_message_may_lead_to_only_a_few_actions(world):
    for n in range(diya_actions.MAX_PER_TURN):
        world.propose(f"task {n}", message_id=7)
    with pytest.raises(TurnLimit):
        world.propose("a fourth", message_id=7)
    world.propose("another message", message_id=8)  # a different message has its own allowance
    world.propose("no message at all")  # and a proposal with no message id is only held to the overall cap


def test_a_decided_action_still_counts_toward_its_messages_allowance(world):
    first = world.propose("task 0", message_id=7)
    world.actions.reject(first["id"], "ui")
    world.propose("task 1", message_id=7)
    world.propose("task 2", message_id=7)
    with pytest.raises(TurnLimit):
        world.propose("task 3", message_id=7)


def test_actions_that_have_expired_free_the_room_they_held(world):
    for n in range(diya_actions.MAX_PENDING):
        world.propose(f"task {n}")
    world.clock.advance(hours=25)
    assert world.propose("fresh")["status"] == "pending"
    assert world.actions.counts()["expired"] == diya_actions.MAX_PENDING


def test_which_tools_ran_before_a_proposal_is_recorded_once_each_in_order(world):
    action = world.propose(taint_sources=["web_search", "search_notion", "web_search"])
    assert action["tainted"] is True
    assert action["taint_sources"] == ["web_search", "search_notion"]
    clean = world.propose("another", taint_sources=[])
    assert clean["tainted"] is False and clean["taint_sources"] == []


@pytest.mark.parametrize("bad", ["web_search", "search", 5, [5], ["Web Search"], ["x" * 61], [""], None])
def test_taint_sources_must_be_a_list_of_tool_names(world, bad):
    with pytest.raises(InvalidArgs):
        world.propose(taint_sources=bad)
    assert world.actions.actions() == []


def test_at_most_a_set_number_of_taint_sources_are_kept(world):
    names = [f"tool_{n}" for n in range(diya_actions.MAX_TAINT_SOURCES)]
    assert len(world.propose(taint_sources=names)["taint_sources"]) == diya_actions.MAX_TAINT_SOURCES
    with pytest.raises(InvalidArgs):
        world.propose("another", taint_sources=names + ["one_more"])


@pytest.mark.parametrize("field", ["thread_id", "message_id"])
@pytest.mark.parametrize("bad", ["7", 1.5, True])
def test_thread_and_message_ids_must_be_whole_numbers(world, field, bad):
    with pytest.raises(ValueError):
        world.propose(**{field: bad})


# ---- approve and reject: the owner's side ---------------------------------------------------------

def test_the_owner_approving_records_the_decision_and_runs_nothing(world):
    action = world.propose()
    world.clock.advance(minutes=5)
    approved = world.actions.approve(action["id"], action["args_hash"], "ui")
    assert approved["status"] == "approved"
    assert approved["decided_at"] == "2026-10-04T10:05:00Z"
    assert world.calls == []
    assert events(world, approved) == [("proposed", "model"), ("approved", "owner")]
    assert world.actions.events(action["id"])[1][3] == '{"via": "ui"}'


def test_how_the_owner_decided_is_recorded(world):
    action = world.propose("a")
    world.actions.approve(action["id"], action["args_hash"], "cli")
    other = world.propose("b")
    world.actions.reject(other["id"], "cli")
    assert world.actions.events(action["id"])[1][3] == '{"via": "cli"}'
    assert world.actions.events(other["id"])[1][3] == '{"via": "cli"}'


@pytest.mark.parametrize("via", ["model", "", None, "api"])
def test_a_decision_must_say_how_the_owner_made_it(world, via):
    action = world.propose()
    with pytest.raises(ValueError):
        world.actions.approve(action["id"], action["args_hash"], via)
    with pytest.raises(ValueError):
        world.actions.reject(action["id"], via)
    assert world.actions.get(action["id"])["status"] == "pending"


def test_approving_something_other_than_what_was_shown_is_refused(world):
    action = world.propose()
    with pytest.raises(HashMismatch):
        world.actions.approve(action["id"], diya_actions.args_hash("add_task", {"title": "something else"}), "ui")
    with pytest.raises(HashMismatch):
        world.actions.approve(action["id"], "", "ui")
    with pytest.raises(HashMismatch):
        world.actions.approve(action["id"], None, "ui")
    assert world.actions.get(action["id"])["status"] == "pending"
    assert events(world, action) == [("proposed", "model")]


def test_an_action_can_be_approved_once_only(world):
    action = world.propose()
    world.actions.approve(action["id"], action["args_hash"], "ui")
    with pytest.raises(IllegalTransition):
        world.actions.approve(action["id"], action["args_hash"], "ui")
    other = world.propose("other")
    world.actions.reject(other["id"], "ui")
    with pytest.raises(IllegalTransition):
        world.actions.approve(other["id"], other["args_hash"], "ui")


def test_a_proposal_whose_time_is_up_cannot_be_approved(world):
    action = world.propose()
    world.clock.advance(hours=24)  # exactly at the expiry moment: it is over
    with pytest.raises(IllegalTransition, match="expired"):
        world.actions.approve(action["id"], action["args_hash"], "ui")
    assert world.actions.get(action["id"])["status"] == "expired"


def test_a_proposal_one_second_before_its_time_is_up_can_still_be_approved(world):
    action = world.propose()
    world.clock.advance(hours=23, minutes=59, seconds=59)
    assert world.actions.approve(action["id"], action["args_hash"], "ui")["status"] == "approved"


def test_rejecting_closes_an_action_for_good(world):
    action = world.propose()
    world.clock.advance(minutes=1)
    rejected = world.actions.reject(action["id"], "ui")
    assert rejected["status"] == "rejected" and rejected["decided_at"] == "2026-10-04T10:01:00Z"
    assert events(world, rejected) == [("proposed", "model"), ("rejected", "owner")]
    for method in (lambda: world.actions.reject(action["id"], "ui"),
                   lambda: world.actions.approve(action["id"], action["args_hash"], "ui"),
                   lambda: world.actions.run(action["id"])):
        with pytest.raises(IllegalTransition):
            method()
    assert world.calls == []


def test_only_a_pending_action_can_be_rejected(world):
    action = world.approved()
    with pytest.raises(IllegalTransition):
        world.actions.reject(action["id"], "ui")


def test_deciding_on_an_action_that_does_not_exist(world):
    with pytest.raises(UnknownAction):
        world.actions.approve(99, "x", "ui")
    with pytest.raises(UnknownAction):
        world.actions.reject(99, "ui")
    with pytest.raises(UnknownAction):
        world.actions.run(99)
    with pytest.raises(UnknownAction):
        world.actions.get(99)
    with pytest.raises(UnknownAction):
        world.actions.resolve(99, True, "ui")


# ---- run: at most once, ever ------------------------------------------------------------------------

def test_an_approved_action_runs_once_and_the_service_s_reply_is_kept(world):
    action = world.approved()
    world.clock.advance(minutes=2)
    done = world.actions.run(action["id"])
    assert done["status"] == "succeeded"
    assert done["result"] == "created task 1"
    assert done["executed_at"] == "2026-10-04T10:02:00Z"
    assert world.calls == [{"title": "buy milk"}]
    assert events(world, done) == [("proposed", "model"), ("approved", "owner"),
                                   ("executing", "system"), ("succeeded", "system")]


def test_executing_is_on_disk_before_the_effect_is_attempted(world):
    action = world.approved()
    world.actions.run(action["id"])
    assert world.statuses_during == [["executing"]]


def test_the_effect_receives_the_stored_arguments_and_the_config(world):
    seen = []
    kind = ActionKind("add_task", "Add", "fakeservice", world._validate, world._render,
                      lambda config, args: seen.append((config, args)) or "ok")
    actions = Actions(world.store, world.config, (kind,), world.clock)
    action = actions.propose("add_task", {"title": "buy milk"})
    actions.approve(action["id"], action["args_hash"], "ui")
    actions.run(action["id"])
    assert seen == [(world.config, {"title": "buy milk"})]


def test_an_action_that_has_run_cannot_be_run_again(world):
    action = world.approved()
    world.actions.run(action["id"])
    with pytest.raises(IllegalTransition):
        world.actions.run(action["id"])
    assert len(world.calls) == 1


def test_an_action_that_was_never_approved_cannot_be_run(world):
    action = world.propose()
    with pytest.raises(IllegalTransition):
        world.actions.run(action["id"])
    assert world.calls == []
    assert world.actions.get(action["id"])["status"] == "pending"


def test_a_failure_the_effect_describes_is_recorded_and_not_retried(world):
    world.raises = ActionFailed("Todoist said no: rate limited")
    action = world.approved()
    done = world.actions.run(action["id"])
    assert done["status"] == "failed"
    assert done["result"] == "Todoist said no: rate limited"
    assert events(world, done)[-2:] == [("executing", "system"), ("failed", "system")]
    with pytest.raises(IllegalTransition):
        world.actions.run(action["id"])
    assert len(world.calls) == 1


def test_an_effect_that_cannot_tell_whether_it_happened_leaves_the_action_unknown_and_is_never_retried(world):
    world.raises = ActionUncertain("The request was sent but no answer came back")
    action = world.approved()
    done = world.actions.run(action["id"])
    assert done["status"] == "unknown"
    assert done["result"] == "The request was sent but no answer came back"
    assert events(world, done)[-2:] == [("executing", "system"), ("unknown", "system")]
    assert world.actions.events(action["id"])[-1][3] == '{"reason": "The request was sent but no answer came back"}'
    with pytest.raises(IllegalTransition):
        world.actions.run(action["id"])  # the whole point: it is not tried a second time
    assert len(world.calls) == 1
    assert world.actions.verify_integrity() == []


def test_only_an_unknown_outcome_records_a_reason_with_its_event(world):
    ok = world.actions.run(world.approved("ok")["id"])
    assert [d for _e, _a, _t, d in world.actions.events(ok["id"])] == [None, '{"via": "ui"}', None, None]
    world.raises = ActionFailed("no")
    failed = world.actions.run(world.approved("failed")["id"])
    assert [d for _e, _a, _t, d in world.actions.events(failed["id"])][-1] is None
    world.raises = ActionUncertain("maybe")
    unknown = world.actions.run(world.approved("unknown")["id"])
    assert [d for _e, _a, _t, d in world.actions.events(unknown["id"])][-1] == '{"reason": "maybe"}'


def test_an_uncertain_outcome_with_no_words_still_says_something(world):
    world.raises = ActionUncertain()
    assert world.actions.run(world.approved()["id"])["result"] == "the outcome is not known"


def test_an_uncertain_outcome_is_resolved_by_the_owner_like_a_cut_off_one(world):
    world.raises = ActionUncertain("maybe it did")
    action = world.approved()
    world.actions.run(action["id"])
    done = world.actions.resolve(action["id"], True, "ui", note="it is in my list")
    assert done["status"] == "succeeded" and done["result"] == "Recorded by the owner: it happened. it is in my list"
    assert world.actions.verify_integrity() == []
    assert len(world.calls) == 1


def test_a_plain_failure_and_an_uncertain_one_are_not_confused(world):
    world.raises = ActionFailed("no")
    assert world.actions.run(world.approved("a")["id"])["status"] == "failed"
    world.raises = ActionUncertain("maybe")
    assert world.actions.run(world.approved("b")["id"])["status"] == "unknown"
    world.raises = ValueError("a bug in the effect")
    assert world.actions.run(world.approved("c")["id"])["status"] == "failed"  # an unexpected error is a failure, as before


def test_a_failure_with_no_message_still_says_something(world):
    world.raises = ActionFailed()
    done = world.actions.run(world.approved()["id"])
    assert done["result"] == "the action failed"


def test_an_unexpected_error_in_the_effect_is_a_failure_that_names_the_error(world):
    world.raises = KeyError("title")
    done = world.actions.run(world.approved()["id"])
    assert done["status"] == "failed"
    assert done["result"] == "the action stopped with an error: KeyError: 'title'"


def test_a_reply_that_is_not_text_is_kept_as_text_and_a_long_one_is_cut(world):
    world.reply = None
    assert world.actions.run(world.approved("a")["id"])["result"] == ""
    world.reply = 42
    assert world.actions.run(world.approved("b")["id"])["result"] == "42"
    world.reply = "x" * 5000
    long = world.actions.run(world.approved("c")["id"])["result"]
    assert len(long) == diya_actions.MAX_RESULT_CHARS and long.endswith("...")
    world.reply = "y" * diya_actions.MAX_RESULT_CHARS
    assert world.actions.run(world.approved("d")["id"])["result"] == "y" * diya_actions.MAX_RESULT_CHARS


def test_an_approval_does_not_outlive_its_proposal(world):
    action = world.approved()
    world.clock.advance(hours=24)
    with pytest.raises(IllegalTransition, match="expired"):
        world.actions.run(action["id"])
    assert world.actions.get(action["id"])["status"] == "expired"
    assert world.calls == []


def test_an_approval_one_second_before_the_time_is_up_can_still_run(world):
    action = world.approved()
    world.clock.advance(hours=23, minutes=59, seconds=59)
    assert world.actions.run(action["id"])["status"] == "succeeded"


def test_disconnecting_after_approval_stops_the_action_before_anything_is_attempted(world):
    action = world.approved()
    world.disconnect()
    done = world.actions.run(action["id"])
    assert done["status"] == "failed"
    assert done["result"] == "Not run: fakeservice is no longer connected"
    assert world.calls == []
    assert events(world, done)[-1] == ("failed", "system")
    assert world.actions.events(action["id"])[-1][3] == '{"reason": "fakeservice is no longer connected"}'
    assert "executing" not in [event for event, _ in events(world, done)]


def test_arguments_changed_in_the_database_after_approval_are_not_run(world):
    action = world.approved()
    world.sql("UPDATE actions SET args = ? WHERE id = ?", ('{"title":"something else"}', action["id"]))
    done = world.actions.run(action["id"])
    assert done["status"] == "failed"
    assert done["result"] == "Not run: the stored arguments do not match what was approved"
    assert world.calls == []


def test_arguments_and_hash_both_changed_are_caught_by_the_description_the_owner_saw(world):
    action = world.approved()
    changed = {"title": "something else"}
    world.sql("UPDATE actions SET args = ?, args_hash = ? WHERE id = ?",
              (diya_actions.canonical(changed), diya_actions.args_hash("add_task", changed), action["id"]))
    done = world.actions.run(action["id"])
    assert done["status"] == "failed"
    assert done["result"] == "Not run: what the stored arguments say is not what the owner was shown"
    assert world.calls == []


def test_arguments_the_kind_would_now_refuse_are_not_run(world):
    action = world.approved()
    world.refuse_validation = True
    done = world.actions.run(action["id"])
    assert done["status"] == "failed"
    assert done["result"] == "Not run: the arguments no longer pass their checks (refused for the test)"
    assert world.calls == []


def test_stored_arguments_that_are_not_plain_data_are_not_run(world):
    action = world.approved()
    bad = {"title": "line\nbreak"}
    world.sql("UPDATE actions SET args = ?, args_hash = ? WHERE id = ?",
              ('{"title":"line\\nbreak"}', diya_actions.args_hash("add_task", bad), action["id"]))
    done = world.actions.run(action["id"])
    assert done["status"] == "failed" and "no longer pass their checks" in done["result"]
    assert world.calls == []


def test_an_action_whose_kind_is_gone_is_not_run(world):
    action = world.approved()
    gone = Actions(world.store, world.config, (), world.clock)
    done = gone.run(action["id"])
    assert done["status"] == "failed"
    assert done["result"] == "Not run: there is no kind of action called 'add_task' any more"
    assert world.calls == []


def test_a_run_cut_off_mid_effect_is_flagged_unknown_and_never_run_again(world):
    world.raises = KeyboardInterrupt()  # not an Exception: the process is going down
    action = world.approved()
    with pytest.raises(KeyboardInterrupt):
        world.actions.run(action["id"])
    assert world.actions.get(action["id"])["status"] == "executing"  # the outcome was never written
    assert world.actions.reconcile(older_than=timedelta(0)) == 1
    stuck = world.actions.get(action["id"])
    assert stuck["status"] == "unknown"
    assert events(world, stuck)[-1] == ("unknown", "system")
    assert "outcome is not known" in world.actions.events(action["id"])[-1][3]
    with pytest.raises(IllegalTransition):
        world.actions.run(action["id"])
    assert len(world.calls) == 1


def test_reconcile_leaves_a_run_that_may_still_be_in_flight_alone(world):
    world.raises = KeyboardInterrupt()
    action = world.approved()
    with pytest.raises(KeyboardInterrupt):
        world.actions.run(action["id"])
    world.clock.advance(seconds=119)
    assert world.actions.reconcile() == 0
    assert world.actions.get(action["id"])["status"] == "executing"
    world.clock.advance(seconds=1)
    assert world.actions.reconcile() == 1
    assert world.actions.get(action["id"])["status"] == "unknown"


def test_reconcile_touches_nothing_but_actions_that_are_executing(world):
    pending = world.propose("a")
    approved = world.approved("b")
    done = world.actions.run(world.approved("c")["id"])
    world.clock.advance(hours=1)
    world.actions.reconcile(older_than=timedelta(0))
    assert world.actions.get(pending["id"])["status"] == "pending"
    assert world.actions.get(approved["id"])["status"] == "approved"
    assert world.actions.get(done["id"])["status"] == "succeeded"


def test_the_owner_records_what_they_found_for_an_unknown_action(world):
    world.raises = KeyboardInterrupt()
    ids = []
    for title in ("a", "b"):
        action = world.approved(title)
        with pytest.raises(KeyboardInterrupt):
            world.actions.run(action["id"])
        ids.append(action["id"])
    world.actions.reconcile(older_than=timedelta(0))
    happened = world.actions.resolve(ids[0], True, "cli", note="it is in my list")
    assert happened["status"] == "succeeded"
    assert happened["result"] == "Recorded by the owner: it happened. it is in my list"
    assert events(world, happened)[-1] == ("resolved_succeeded", "owner")
    assert world.actions.events(ids[0])[-1][3] == '{"via": "cli", "note": "it is in my list"}'
    didnt = world.actions.resolve(ids[1], False, "ui")
    assert didnt["status"] == "failed" and didnt["result"] == "Recorded by the owner: it did not happen."
    assert events(world, didnt)[-1] == ("resolved_failed", "owner")
    assert len(world.calls) == 2  # finding out never ran anything again


def test_only_an_unknown_action_can_be_resolved(world):
    for action in (world.propose("a"), world.approved("b"), world.actions.run(world.approved("c")["id"])):
        with pytest.raises(IllegalTransition):
            world.actions.resolve(action["id"], True, "ui")


def test_resolving_needs_a_yes_or_no_a_known_channel_and_a_plain_short_note(world):
    world.raises = KeyboardInterrupt()
    action = world.approved()
    with pytest.raises(KeyboardInterrupt):
        world.actions.run(action["id"])
    world.actions.reconcile(older_than=timedelta(0))
    for happened in ("yes", 1, None):
        with pytest.raises(ValueError):
            world.actions.resolve(action["id"], happened, "ui")
    with pytest.raises(ValueError):
        world.actions.resolve(action["id"], True, "model")
    for note in ("two\nlines", "", "x" * (diya_actions.MAX_NOTE_CHARS + 1)):
        with pytest.raises(InvalidArgs):
            world.actions.resolve(action["id"], True, "ui", note=note)
    assert world.actions.get(action["id"])["status"] == "unknown"
    world.actions.resolve(action["id"], True, "ui", note="x" * diya_actions.MAX_NOTE_CHARS)


# ---- expiring and reading --------------------------------------------------------------------------

def test_expire_closes_pending_and_approved_actions_whose_time_is_up_and_nothing_else(world):
    pending = world.propose("a")
    approved = world.approved("b")
    done = world.actions.run(world.approved("c")["id"])
    rejected = world.propose("d")
    world.actions.reject(rejected["id"], "ui")
    world.clock.advance(hours=24)
    assert world.actions.expire() == 2
    statuses = {a["id"]: a["status"] for a in world.actions.actions()}
    assert statuses == {pending["id"]: "expired", approved["id"]: "expired", done["id"]: "succeeded",
                        rejected["id"]: "rejected"}
    assert events(world, world.actions.get(pending["id"]))[-1] == ("expired", "system")
    assert world.actions.expire() == 0  # and only once


def test_expire_leaves_an_action_whose_time_is_not_up(world):
    action = world.propose()
    world.clock.advance(hours=23, minutes=59, seconds=59)
    assert world.actions.expire() == 0
    assert world.actions.get(action["id"])["status"] == "pending"


def test_pending_lists_what_is_waiting_and_never_what_has_expired(world):
    first = world.propose("a")
    world.clock.advance(hours=12)
    second = world.propose("b")
    assert [a["id"] for a in world.actions.pending()] == [first["id"], second["id"]]
    world.clock.advance(hours=13)
    assert [a["id"] for a in world.actions.pending()] == [second["id"]]


def test_actions_can_be_listed_by_status_oldest_first(world):
    a, b = world.propose("a"), world.propose("b")
    world.actions.reject(a["id"], "ui")
    assert [x["id"] for x in world.actions.actions()] == [a["id"], b["id"]]
    assert [x["id"] for x in world.actions.actions("pending")] == [b["id"]]
    assert [x["id"] for x in world.actions.actions("rejected")] == [a["id"]]
    with pytest.raises(ValueError):
        world.actions.actions("bogus")


def test_counts_cover_every_status(world):
    world.propose("a")
    assert world.actions.counts() == {status: (1 if status == "pending" else 0) for status in diya_actions.STATUSES}


# ---- two at once -----------------------------------------------------------------------------------

def test_two_runs_at_once_perform_the_effect_once(world):
    action = world.approved()
    slow = threading.Event()

    def slow_execute(config, args):
        world.calls.append(dict(args))
        slow.wait(0.4)
        return "done"

    world.kind = ActionKind("add_task", "Add", "fakeservice", world._validate, world._render, slow_execute)
    actions = Actions(world.store, world.config, (world.kind,), world.clock)
    results = []

    def attempt():
        try:
            results.append(actions.run(action["id"])["status"])
        except IllegalTransition:
            results.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["refused", "succeeded"]
    assert len(world.calls) == 1


def test_two_approvals_at_once_leave_one_approval(world):
    action = world.propose()
    results = []

    def attempt():
        try:
            world.actions.approve(action["id"], action["args_hash"], "ui")
            results.append("approved")
        except IllegalTransition:
            results.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["approved", "refused", "refused", "refused"]
    assert [e for e, _ in events(world, action)].count("approved") == 1


def test_the_same_proposal_from_several_threads_waits_once(world):
    results = []

    def attempt():
        try:
            world.propose("buy milk")
            results.append("proposed")
        except DuplicatePending:
            results.append("duplicate")

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["duplicate", "duplicate", "duplicate", "proposed"]
    assert len(world.actions.actions()) == 1


# ---- the integrity check ---------------------------------------------------------------------------

def test_a_store_that_has_lived_a_full_life_is_sound(world):
    world.propose("pending", taint_sources=["web_search"])
    world.actions.reject(world.propose("rejected")["id"], "ui")
    world.actions.run(world.approved("succeeded")["id"])
    world.raises = ActionFailed("no")
    world.actions.run(world.approved("failed")["id"])
    world.raises = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        world.actions.run(world.approved("unknown")["id"])
    world.actions.reconcile(older_than=timedelta(0))
    world.actions.resolve(world.actions.actions("unknown")[0]["id"], True, "ui")
    world.propose("expires")
    world.clock.advance(hours=25)
    world.actions.expire()
    assert world.actions.verify_integrity() == []


def test_an_empty_store_is_sound(world):
    assert world.actions.verify_integrity() == []


def problems(world):
    return world.actions.verify_integrity()


def test_integrity_finds_an_event_with_no_action(world):
    world.sql("INSERT INTO action_events (action_id, event, actor, at) VALUES (99, 'proposed', 'model', 't')")
    assert any("action 99, which does not exist" in p for p in problems(world))


def test_integrity_finds_an_unknown_event_and_an_unknown_actor(world):
    action = world.propose()
    world.sql("INSERT INTO action_events (action_id, event, actor, at) VALUES (?, 'teleported', 'system', 't')", (action["id"],))
    world.sql("INSERT INTO action_events (action_id, event, actor, at) VALUES (?, 'expired', 'ghost', 't')", (action["id"],))
    found = problems(world)
    assert any("unknown kind 'teleported'" in p for p in found)
    assert any("unknown actor 'ghost'" in p for p in found)


@pytest.mark.parametrize("event,wrong_actor", [("approved", "model"), ("approved", "system"), ("proposed", "owner"),
                                                ("executing", "owner"), ("succeeded", "model")])
def test_integrity_finds_an_event_recorded_by_someone_who_may_not_record_it(world, event, wrong_actor):
    action = world.approved()
    world.actions.run(action["id"])
    world.sql("UPDATE action_events SET actor = ? WHERE action_id = ? AND event = ?", (wrong_actor, action["id"], event))
    assert any(f"({event}) was recorded by {wrong_actor!r}" in p for p in problems(world))


def test_integrity_finds_a_status_that_disagrees_with_the_history(world):
    action = world.propose()
    world.sql("UPDATE actions SET status = 'approved' WHERE id = ?", (action["id"],))
    assert any("is approved but its events say pending" in p for p in problems(world))


def test_integrity_finds_an_action_with_no_events_and_one_that_does_not_begin_with_a_proposal(world):
    world.sql("INSERT INTO actions (kind, args, args_hash, summary, status, created_at, expires_at)"
              " VALUES ('add_task', '{}', 'h', 's', 'pending', 't', 't')")
    assert any("has no events" in p for p in problems(world))
    action = world.propose("another")
    world.sql("UPDATE action_events SET event = 'approved', actor = 'owner' WHERE action_id = ?", (action["id"],))
    assert any("does not begin with it being proposed" in p for p in problems(world))


def test_integrity_finds_arguments_that_do_not_match_their_hash_or_are_not_canonical_or_not_json(world):
    action = world.propose("a")
    world.sql("UPDATE actions SET args = ? WHERE id = ?", ('{"title":"b"}', action["id"]))
    assert any("do not match their hash" in p for p in problems(world))
    world.sql("UPDATE actions SET args = ? WHERE id = ?", ('{ "title": "a" }', action["id"]))
    assert any("not in canonical form" in p for p in problems(world))
    world.sql("UPDATE actions SET args = ? WHERE id = ?", ("{not json", action["id"]))
    assert any("not JSON" in p for p in problems(world))


def test_integrity_finds_a_taint_flag_that_disagrees_with_its_sources(world):
    action = world.propose(taint_sources=["web_search"])
    world.sql("UPDATE actions SET tainted = 0 WHERE id = ?", (action["id"],))
    assert any("taint flag disagrees" in p for p in problems(world))
    other = world.propose("other")
    world.sql("UPDATE actions SET tainted = 1 WHERE id = ?", (other["id"],))
    assert sum("taint flag disagrees" in p for p in problems(world)) == 2


# ---- the schema --------------------------------------------------------------------------------------

def test_migration_five_adds_the_two_tables_and_changes_nothing_else(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, due_at TEXT,"
                 " created_at TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    conn.execute("INSERT INTO reminders (content, created_at) VALUES ('keep me', 't')")
    conn.commit()
    applied = diya_db.apply_migrations(conn)
    assert applied == [1, 2, 3, 4, 5]
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"actions", "action_events"} <= tables
    assert conn.execute("SELECT content FROM reminders").fetchall() == [("keep me",)]
    assert diya_db.apply_migrations(conn) == []  # up to date: nothing runs again
    conn.close()


# ---- gaps the mutation run pointed at ----------------------------------------------------------------

def test_a_run_that_finishes_after_something_else_moved_the_action_does_not_overwrite_it(world):
    action = world.approved()
    seen = {}

    def execute_while_reconciled(config, args):
        seen["moved"] = world.actions.reconcile(older_than=timedelta(0))  # the action is executing right now
        return "done"

    kind = ActionKind("add_task", "Add", "fakeservice", world._validate, world._render, execute_while_reconciled)
    actions = Actions(world.store, world.config, (kind,), world.clock)
    with pytest.raises(IllegalTransition, match="no longer executing"):
        actions.run(action["id"])
    assert seen["moved"] == 1
    stuck = world.actions.get(action["id"])
    assert stuck["status"] == "unknown" and stuck["result"] is None  # the late "succeeded" was not written
    assert events(world, stuck)[-1] == ("unknown", "system")


def test_every_status_an_action_can_end_in_replays_from_its_events(world):
    ends = {}
    ends["pending"] = world.propose("pending")["id"]
    ends["approved"] = world.approved("approved")["id"]
    world.raises = KeyboardInterrupt()
    executing = world.approved("executing")
    with pytest.raises(KeyboardInterrupt):
        world.actions.run(executing["id"])
    ends["executing"] = executing["id"]
    world.raises = None
    ends["succeeded"] = world.actions.run(world.approved("succeeded")["id"])["id"]
    world.raises = ActionFailed("no")
    ends["failed"] = world.actions.run(world.approved("failed")["id"])["id"]
    world.raises = None
    ends["rejected"] = world.actions.reject(world.propose("rejected")["id"], "ui")["id"]
    ends["expired"] = world.propose("expired")["id"]
    world.sql("UPDATE actions SET expires_at = '2000-01-01T00:00:00Z' WHERE id = ?", (ends["expired"],))
    world.actions.expire()
    assert {a["id"]: a["status"] for a in world.actions.actions()} == {v: k for k, v in ends.items()}
    assert world.actions.verify_integrity() == []
    world.actions.reconcile(older_than=timedelta(0))
    assert world.actions.get(ends["executing"])["status"] == "unknown"
    assert world.actions.verify_integrity() == []
    world.actions.resolve(ends["executing"], True, "ui")
    assert world.actions.verify_integrity() == []


def test_resolving_an_action_as_not_having_happened_replays_to_failed(world):
    world.raises = KeyboardInterrupt()
    action = world.approved()
    with pytest.raises(KeyboardInterrupt):
        world.actions.run(action["id"])
    world.actions.reconcile(older_than=timedelta(0))
    world.actions.resolve(action["id"], False, "ui")
    assert world.actions.get(action["id"])["status"] == "failed"
    assert world.actions.verify_integrity() == []


def test_an_unknown_event_is_reported_as_itself_and_not_also_as_a_wrong_status(world):
    action = world.propose()
    world.sql("INSERT INTO action_events (action_id, event, actor, at) VALUES (?, 'teleported', 'system', 't')", (action["id"],))
    found = problems(world)
    assert any("unknown kind 'teleported'" in p for p in found)
    assert not any("events say" in p for p in found)


def test_an_unknown_status_is_found_even_where_the_database_would_have_refused_it(world):
    action = world.propose()
    conn = world.store.connect()
    conn.execute("PRAGMA ignore_check_constraints = ON")
    conn.execute("UPDATE actions SET status = 'bogus' WHERE id = ?", (action["id"],))
    conn.commit()
    conn.close()
    assert any("unknown status 'bogus'" in p for p in problems(world))


def test_a_row_inserted_with_only_what_is_required_reads_back_with_the_defaults(world):
    world.sql("INSERT INTO actions (kind, args, args_hash, summary, status, created_at, expires_at)"
              " VALUES ('add_task', '{}', 'h', 's', 'pending', 't', 't')")
    action = world.actions.actions()[0]
    assert action["tainted"] is False and action["taint_sources"] == []
    assert action["thread_id"] is None and action["message_id"] is None


def test_the_database_refuses_a_taint_flag_that_is_not_a_yes_or_no(world):
    with pytest.raises(sqlite3.IntegrityError):
        world.sql("INSERT INTO actions (kind, args, args_hash, summary, status, tainted, created_at, expires_at)"
                  " VALUES ('add_task', '{}', 'h', 's', 'pending', 2, 't', 't')")


@pytest.mark.parametrize("missing", ["kind", "args", "args_hash", "summary", "status", "created_at", "expires_at"])
def test_the_database_refuses_an_action_with_a_required_column_empty(world, missing):
    values = {"kind": "'add_task'", "args": "'{}'", "args_hash": "'h'", "summary": "'s'", "status": "'pending'",
              "created_at": "'t'", "expires_at": "'t'"}
    values[missing] = "NULL"
    with pytest.raises(sqlite3.IntegrityError):
        world.sql(f"INSERT INTO actions ({', '.join(values)}) VALUES ({', '.join(values.values())})")


@pytest.mark.parametrize("missing", ["action_id", "event", "actor", "at"])
def test_the_database_refuses_an_event_with_a_required_column_empty(world, missing):
    values = {"action_id": "1", "event": "'proposed'", "actor": "'model'", "at": "'t'"}
    values[missing] = "NULL"
    with pytest.raises(sqlite3.IntegrityError):
        world.sql(f"INSERT INTO action_events ({', '.join(values)}) VALUES ({', '.join(values.values())})")


def test_the_limits_are_the_ones_the_design_recommends():
    assert diya_actions.MAX_PENDING == 10
    assert diya_actions.MAX_PER_TURN == 3
    assert diya_actions.EXPIRY == timedelta(hours=24)
    assert diya_actions.MIN_RECONCILE_AGE == timedelta(seconds=120)
