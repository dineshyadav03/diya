"""diya_actions_cli.py: deciding what Diya proposed from the command line (docs/ACTIONS_DESIGN.md D8, unit A3).

What this proves: every command does what it says and refuses, with a message and a non-zero exit and no change,
what it should refuse; approving asks first, shows what is being approved, and holds to exactly what was shown;
nothing is run unless approved; whatever is read back from the database reaches the terminal only as visible
escapes; and it says the same thing when run for real as when it is called from a test. Every kind is a fake.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
import io
import os
import pathlib
import subprocess
import sys
import types
from datetime import timedelta

import pytest

import diya_actions
import diya_actions_cli
import diya_config
import diya_connectors
from diya_actions import ActionFailed, ActionKind, Actions
from diya_db import Store
from fakes import task_kind

ROOT = pathlib.Path(__file__).resolve().parent.parent
ESC, BIDI = chr(27), chr(0x202E)
BACKSLASH = chr(92)


@pytest.fixture
def world(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(diya_config.load_config(), db_path=str(data / "cli.db"))
    executed = []
    kind = task_kind(executed=executed)
    return types.SimpleNamespace(config=config, kind=kind, executed=executed, actions=Actions(Store(config.db_path), config, (kind,)))


def cli(world, *argv, answers=(), kinds=None):
    """Run the command line; `answers` are what is typed at any question, in order. Returns (code, out, err, asked)."""
    out, err, asked = io.StringIO(), io.StringIO(), []
    typed = iter(answers)

    def input_fn(prompt=""):
        asked.append(prompt)
        try:
            return next(typed)
        except StopIteration:
            raise EOFError

    code = diya_actions_cli.main(list(argv), config=world.config, out=out, err=err,
                                 kinds=(world.kind,) if kinds is None else kinds, input_fn=input_fn)
    return code, out.getvalue(), err.getvalue(), asked


def propose(world, title="buy milk", **extra):
    return world.actions.propose("add_task", {"title": title}, **extra)


def cut_off(world, title="buy milk"):
    action = propose(world, title)
    world.actions.approve(action["id"], action["args_hash"], "cli")
    real = world.actions.kinds
    world.actions.kinds = (task_kind(raises=KeyboardInterrupt()),)
    with pytest.raises(KeyboardInterrupt):
        world.actions.run(action["id"])
    world.actions.kinds = real
    world.actions.reconcile(older_than=timedelta(0))
    return action


# ---- list ---------------------------------------------------------------------------------------------

def test_an_empty_store_says_so(world):
    code, out, err, _ = cli(world, "list")
    assert code == 0 and err == ""
    assert out == "Actions: 0 waiting for you, 0 in all.\nNothing waiting for you.\n"


def test_list_defaults_to_what_is_waiting(world):
    first, second = propose(world, "a"), propose(world, "b")
    world.actions.reject(second["id"], "cli")
    code, out, _, _ = cli(world, "list")
    assert code == 0
    assert out == (f"Actions: 1 waiting for you, 2 in all.\n   {first['id']}  pending    Add the task 'a'\n")


def test_list_all_and_by_status(world):
    first, second = propose(world, "a"), propose(world, "b")
    world.actions.reject(second["id"], "cli")
    _, everything, _, _ = cli(world, "list", "all")
    assert f"{first['id']:>4}  pending    Add the task 'a'" in everything and f"{second['id']:>4}  rejected   Add the task 'b'" in everything
    _, rejected, _, _ = cli(world, "list", "rejected")
    assert "Add the task 'b'" in rejected and "Add the task 'a'" not in rejected


def test_list_says_when_there_are_none_of_a_status_or_none_at_all(world):
    assert cli(world, "list", "rejected")[1].endswith("No rejected actions.\n")
    assert cli(world, "list", "all")[1].endswith("No actions yet.\n")


def test_the_summary_line_mentions_unknown_outcomes_only_when_there_are_some(world):
    assert "unknown" not in cli(world, "list")[1]
    cut_off(world)
    assert cli(world, "list")[1].startswith("Actions: 0 waiting for you, 1 with an unknown outcome, 1 in all.\n")


def test_what_Diya_read_before_proposing_is_marked_in_the_list(world):
    propose(world, "a", taint_sources=["web_search", "search_notion"])
    propose(world, "b")
    out = cli(world, "list")[1]
    assert "Add the task 'a'  [read first: web_search, search_notion]\n" in out
    assert "Add the task 'b'\n" in out


def test_list_closes_what_has_expired(world):
    propose(world)
    # the CLI reads the real clock, so move the stored expiry into the past instead
    conn = Store(world.config.db_path).connect()
    conn.execute("UPDATE actions SET expires_at = '2000-01-01T00:00:00Z'")
    conn.commit()
    conn.close()
    code, out, _, _ = cli(world, "list")
    assert "Nothing waiting for you." in out and world.actions.get(1)["status"] == "expired"


# ---- show -------------------------------------------------------------------------------------------------

def test_show_says_what_it_would_do_and_where_it_came_from(world):
    store = Store(world.config.db_path)
    thread = store.create_thread()
    message = store.add_message(thread, "user", "please add buy milk")
    action = propose(world, "buy milk", thread_id=thread, message_id=message)
    code, out, err, _ = cli(world, "show", str(action["id"]))
    assert code == 0 and err == ""
    lines = out.splitlines()
    assert lines[0] == f"Action {action['id']}: pending"
    assert "  kind:     Add a task" in lines
    assert "  would do: Add the task 'buy milk'" in lines
    assert "            title: buy milk" in lines
    assert f"  chat:     thread {thread}, message {message}" in lines
    assert "  you said: please add buy milk" in lines
    assert any(line.startswith("  expires:  20") for line in lines)
    assert not any(line.startswith("  CAUTION") or line.startswith("  result") or line.startswith("  decided") for line in lines)
    assert "  history:" in lines
    (history,) = [line for line in lines[lines.index("  history:") + 1:]]
    assert history.startswith("    20") and history.endswith("model   proposed")


def test_show_leaves_out_the_lines_that_have_nothing_to_say(world):
    out = cli(world, "show", str(propose(world)["id"]))[1]
    for left_out in ("chat:", "you said:", "CAUTION", "decided:", "ran:", "result:", "None"):
        assert left_out not in out, left_out


def test_show_with_a_chat_but_no_message_names_only_the_chat(world):
    action = propose(world, thread_id=4)
    assert "  chat:     thread 4" in cli(world, "show", str(action["id"]))[1].splitlines()


def test_show_cuts_a_long_message_short_and_copes_with_one_that_is_gone(world):
    store = Store(world.config.db_path)
    thread = store.create_thread()
    long = store.add_message(thread, "user", "x" * 500)
    exact = store.add_message(thread, "user", "y" * 300)
    assert "  you said: " + "x" * 300 + "..." in cli(world, "show", str(propose(world, "a", thread_id=thread, message_id=long)["id"]))[1].splitlines()
    assert "  you said: " + "y" * 300 in cli(world, "show", str(propose(world, "b", thread_id=thread, message_id=exact)["id"]))[1].splitlines()
    code, out, err, _ = cli(world, "show", str(propose(world, "c", message_id=9999)["id"]))
    assert code == 0 and "you said" not in out


def test_show_cuts_a_long_event_detail_short(world):
    action = propose(world)
    conn = Store(world.config.db_path).connect()
    conn.execute("UPDATE action_events SET detail = ? WHERE action_id = ?", ("z" * 500, action["id"]))
    conn.commit()
    conn.close()
    out = cli(world, "show", str(action["id"]))[1]
    assert "z" * 200 + "..." in out and "z" * 201 not in out


def test_show_warns_when_diya_read_outside_text_before_proposing(world):
    action = propose(world, "buy milk", taint_sources=["web_search", "search_notes"])
    out = cli(world, "show", str(action["id"]))[1]
    assert ("  CAUTION:  Diya read from web_search, search_notes before proposing this. That text is not yours: "
            "check the details above are what you wanted.") in out.splitlines()


def test_show_for_a_finished_action_gives_when_and_what_came_of_it(world):
    action = propose(world)
    world.actions.approve(action["id"], action["args_hash"], "cli")
    world.actions.run(action["id"])
    out = cli(world, "show", str(action["id"]))[1]
    assert any(line.startswith("  decided:  20") for line in out.splitlines())
    assert any(line.startswith("  ran:      20") for line in out.splitlines())
    assert "  result:   created task 1" in out.splitlines()
    for event in ("proposed", "approved", "executing", "succeeded"):
        assert event in out


def test_show_a_field_with_no_value_and_a_yes_or_no(world):
    kind = ActionKind("rich", "Rich", None, lambda a: None, lambda a: "Do it", lambda c, a: "ok", None)
    world.kind = kind
    world.actions = Actions(Store(world.config.db_path), world.config, (kind,))
    action = world.actions.propose("rich", {"a": None, "b": True, "c": False, "d": 3})
    out = cli(world, "show", str(action["id"]))[1].splitlines()
    assert "            a: (empty)" in out and "            b: yes" in out and "            c: no" in out and "            d: 3" in out


def test_show_a_kind_that_is_gone_uses_its_name(world):
    action = propose(world)
    out = cli(world, "show", str(action["id"]), kinds=())[1]
    assert "  kind:     add_task" in out.splitlines()


def test_show_an_action_that_is_not_there(world):
    code, out, err, _ = cli(world, "show", "7")
    assert (code, out) == (1, "") and err == "diya_actions_cli: there is no action 7\n"


# ---- approve ------------------------------------------------------------------------------------------------

def test_approve_shows_the_action_asks_and_on_a_yes_approves_and_runs_it(world):
    action = propose(world)
    code, out, err, asked = cli(world, "approve", str(action["id"]), answers=["y"])
    assert (code, err) == (0, "")
    assert asked == ["Approve this and run it now? [y/N] "]
    assert out.index("would do: Add the task 'buy milk'") < out.index("Action 1: succeeded.")  # shown before it ran
    assert out.endswith("Action 1: succeeded. created task 1\n")
    assert world.executed == [{"title": "buy milk"}]
    events = world.actions.events(action["id"])
    assert [(e[0], e[1]) for e in events] == [("proposed", "model"), ("approved", "owner"), ("executing", "system"), ("succeeded", "system")]
    assert events[1][3] == '{"via": "cli"}'  # decided on the command line


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", " yes ", "Yes\n"])
def test_any_ordinary_yes_is_a_yes(world, answer):
    action = propose(world)
    assert cli(world, "approve", str(action["id"]), answers=[answer])[0] == 0
    assert world.executed == [{"title": "buy milk"}]


@pytest.mark.parametrize("answer", ["n", "N", "no", "", "  ", "maybe", "yep", "ye", "y es", "0"])
def test_anything_but_a_yes_means_nothing_is_done(world, answer):
    action = propose(world)
    code, out, err, _ = cli(world, "approve", str(action["id"]), answers=[answer])
    assert code == 1 and out.endswith("Not approved. Nothing was done.\n") and err == ""
    assert world.executed == [] and world.actions.get(action["id"])["status"] == "pending"


def test_no_answer_at_all_is_a_no(world):
    action = propose(world)
    code, out, _, asked = cli(world, "approve", str(action["id"]))  # input ends at once (a closed terminal)
    assert code == 1 and "Not approved." in out and len(asked) == 1
    assert world.executed == []


def test_yes_skips_the_question_for_a_script(world):
    action = propose(world)
    code, out, _, asked = cli(world, "approve", str(action["id"]), "--yes")
    assert code == 0 and asked == [] and "Action 1: succeeded." in out
    assert world.executed == [{"title": "buy milk"}]


def test_what_is_approved_is_what_was_on_the_screen_so_a_change_in_between_is_refused(world):
    action = propose(world)
    world.executed.clear()
    store = Store(world.config.db_path)

    def change_it_while_the_question_is_open(prompt=""):
        conn = store.connect()
        conn.execute("UPDATE actions SET args_hash = ? WHERE id = ?", ("0" * 64, action["id"]))
        conn.commit()
        conn.close()
        return "y"

    out, err = io.StringIO(), io.StringIO()
    code = diya_actions_cli.main(["approve", str(action["id"])], config=world.config, out=out, err=err,
                                 kinds=(world.kind,), input_fn=change_it_while_the_question_is_open)
    assert code == 1 and "not what was shown" in err.getvalue()
    assert world.executed == [] and world.actions.get(action["id"])["status"] == "pending"


def test_approving_something_that_is_not_pending_shows_it_and_refuses_without_asking(world):
    action = propose(world)
    world.actions.reject(action["id"], "cli")
    code, out, err, asked = cli(world, "approve", str(action["id"]), answers=["y"])
    assert code == 1 and asked == []
    assert "Action 1: rejected" in out
    assert err == f"diya_actions_cli: action {action['id']} is rejected; only a pending action can be approved\n"
    assert world.executed == []


def test_approving_an_action_that_is_not_there(world):
    code, _, err, asked = cli(world, "approve", "9", "--yes")
    assert code == 1 and asked == [] and err == "diya_actions_cli: there is no action 9\n"


def test_an_action_whose_effect_fails_is_reported_and_is_a_failure(world):
    world.kind = task_kind(executed=world.executed, raises=ActionFailed("Todoist said no"))
    world.actions = Actions(Store(world.config.db_path), world.config, (world.kind,))
    action = propose(world)
    code, out, _, _ = cli(world, "approve", str(action["id"]), "--yes")
    assert code == 1 and out.endswith("Action 1: failed. Todoist said no\n")


def test_an_action_whose_connector_was_disconnected_is_not_run(world):
    world.kind = task_kind(connector="todoist", executed=world.executed)
    world.actions = Actions(Store(world.config.db_path), world.config, (world.kind,))
    diya_connectors.store_token(world.config, "todoist", "a-token")
    action = propose(world)
    diya_connectors.disconnect(world.config, "todoist")
    code, out, _, _ = cli(world, "approve", str(action["id"]), "--yes")
    assert code == 1 and "Not run: todoist is no longer connected" in out
    assert world.executed == []


def test_a_successful_approval_with_no_reply_text_still_says_it_succeeded(world):
    world.kind = task_kind(executed=world.executed, reply="")
    world.actions = Actions(Store(world.config.db_path), world.config, (world.kind,))
    action = propose(world)
    code, out, _, _ = cli(world, "approve", str(action["id"]), "--yes")
    assert code == 0 and out.endswith("Action 1: succeeded.\n")


# ---- reject and resolve ----------------------------------------------------------------------------------

def test_reject_turns_an_action_down_and_it_is_never_run(world):
    action = propose(world)
    code, out, err, asked = cli(world, "reject", str(action["id"]))
    assert (code, err, asked) == (0, "", [])
    assert out == f"Action {action['id']}: rejected. It will not be done.\n"
    assert world.executed == []
    events = world.actions.events(action["id"])
    assert (events[1][0], events[1][1], events[1][3]) == ("rejected", "owner", '{"via": "cli"}')


def test_reject_refuses_what_is_not_pending_or_not_there(world):
    action = propose(world)
    cli(world, "reject", str(action["id"]))
    code, out, err, _ = cli(world, "reject", str(action["id"]))
    assert (code, out) == (1, "") and "only a pending action can be rejected" in err
    assert cli(world, "reject", "9")[0] == 1


def test_resolve_records_what_the_owner_found(world):
    happened, did_not = cut_off(world, "a"), cut_off(world, "b")
    code, out, err, _ = cli(world, "resolve", str(happened["id"]), "happened", "it", "is", "in", "my", "list")
    assert (code, err) == (0, "")
    assert out == f"Action {happened['id']}: succeeded. Recorded by the owner: it happened. it is in my list\n"
    code, out, _, _ = cli(world, "resolve", str(did_not["id"]), "did-not-happen")
    assert code == 0 and out == f"Action {did_not['id']}: failed. Recorded by the owner: it did not happen.\n"
    events = world.actions.events(happened["id"])
    assert events[-1][0] == "resolved_succeeded" and events[-1][3] == '{"via": "cli", "note": "it is in my list"}'
    assert world.actions.events(did_not["id"])[-1][0] == "resolved_failed"
    assert len(world.executed) == 0


def test_resolve_refuses_what_is_not_unknown_and_a_note_that_is_too_long(world):
    action = propose(world)
    code, _, err, _ = cli(world, "resolve", str(action["id"]), "happened")
    assert code == 1 and "only an unknown action can be resolved" in err
    stuck = cut_off(world, "b")
    code, _, err, _ = cli(world, "resolve", str(stuck["id"]), "happened", "x" * (diya_actions.MAX_NOTE_CHARS + 1))
    assert code == 1 and "over 300 characters" in err
    assert world.actions.get(stuck["id"])["status"] == "unknown"


# ---- kinds and check ---------------------------------------------------------------------------------------

def test_kinds_says_so_when_there_is_none(world):
    code, out, _, _ = cli(world, "kinds", kinds=())
    assert code == 0 and out == "No kind of action is registered: Diya cannot propose any change to anything yet.\n"


def test_kinds_says_what_state_each_is_in(world):
    kinds = (task_kind(), task_kind(name="needs_it", tool_name="propose_needs_it", connector="todoist"),
             task_kind(name="quiet", tool=False))
    out = cli(world, "kinds", kinds=kinds)[1].splitlines()
    assert out == ["add_task                 Add a task: can be proposed",
                   "needs_it                 Add a task: needs todoist connected",
                   "quiet                    Add a task: cannot be proposed by the model"]
    diya_connectors.store_token(world.config, "todoist", "a-token")
    assert cli(world, "kinds", kinds=kinds)[1].splitlines()[1] == "needs_it                 Add a task: can be proposed"


def test_check_says_a_sound_store_is_sound(world):
    propose(world)
    assert cli(world, "check")[1:3] == ("The action store is consistent.\n", "")
    assert cli(world, "check")[0] == 0


def test_check_lists_every_problem_it_finds(world):
    action = propose(world)
    conn = Store(world.config.db_path).connect()
    conn.execute("UPDATE actions SET status = 'approved' WHERE id = ?", (action["id"],))
    conn.commit()
    conn.close()
    code, out, _, _ = cli(world, "check")
    assert code == 1
    assert out.splitlines() == [f"action {action['id']} is approved but its events say pending", "1 problem found."]
    conn = Store(world.config.db_path).connect()
    conn.execute("UPDATE actions SET args = '{}' WHERE id = ?", (action["id"],))
    conn.commit()
    conn.close()
    assert cli(world, "check")[1].splitlines()[-1] == "2 problems found."


# ---- what is printed ---------------------------------------------------------------------------------------

def no_control_characters(text):
    return not [c for c in text if ord(c) < 32 and c != "\n"] and BIDI not in text


def test_whatever_is_read_back_reaches_the_terminal_only_as_visible_escapes(world):
    action = propose(world, taint_sources=["web_search"])
    world.actions.approve(action["id"], action["args_hash"], "cli")
    world.actions.kinds = (task_kind(reply=f"done{ESC}[31m red {BIDI} backwards"),)
    world.actions.run(action["id"])
    conn = Store(world.config.db_path).connect()
    conn.execute("UPDATE actions SET summary = ?, taint_sources = ? WHERE id = ?",
                 (f"Add{ESC}[2J the task{BIDI}", f'["web{BACKSLASH}u001b_search"]', action["id"]))
    conn.commit()
    conn.close()
    for argv in (["list", "all"], ["show", str(action["id"])]):
        code, out, err, _ = cli(world, *argv)
        assert no_control_characters(out + err), argv
        assert BACKSLASH + "u001b[2J" in out and BACKSLASH + "u202e" in out
    shown = cli(world, "show", str(action["id"]))[1]
    assert BACKSLASH + "u001b[31m red " + BACKSLASH + "u202e backwards" in shown


# ---- usage and the real thing -----------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [[], ["nonsense"], ["show"], ["show", "abc"], ["show", "1.5"], ["approve"], ["approve", "x"],
                                  ["reject"], ["resolve"], ["resolve", "1"], ["resolve", "1", "maybe"], ["list", "bogus"],
                                  ["list", "pending", "extra"], ["kinds", "extra"], ["check", "x"], ["approve", "1", "--nope"]])
def test_a_command_that_makes_no_sense_is_a_usage_error_and_changes_nothing(world, argv, capsys):
    action = propose(world)
    code, out, _, asked = cli(world, *argv)
    assert code == 2 and out == "" and asked == []
    assert world.actions.get(action["id"])["status"] == "pending" and world.executed == []


def test_help_is_a_success_and_names_every_command(world, capsys):
    assert diya_actions_cli.main(["--help"], config=world.config) == 0
    text = capsys.readouterr().out
    for command in ("list", "show", "approve", "reject", "resolve", "kinds", "check"):
        assert command in text


def test_a_bad_setting_is_a_usage_error(monkeypatch, capsys):
    monkeypatch.setenv("DIYA_REQUIRE_TOKEN", "sideways")
    assert diya_actions_cli.main(["list"]) == 2
    assert "DIYA_REQUIRE_TOKEN" in capsys.readouterr().err


def run_for_real(world, *argv, stdin=""):
    env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "PYTHONPATH": str(ROOT), "DIYA_DB_PATH": world.config.db_path}
    return subprocess.run([sys.executable, str(ROOT / "diya_actions_cli.py"), *argv], input=stdin.encode(), capture_output=True,
                          cwd=pathlib.Path(world.config.db_path).parent, env=env, timeout=60)


def test_run_for_real_with_no_model_and_no_network_it_works_and_speaks_utf8(world):
    result = run_for_real(world, "kinds")
    assert result.returncode == 0, result.stderr
    # the real registry is empty, so the real command line can propose and approve nothing
    assert result.stdout.decode("utf-8") == "No kind of action is registered: Diya cannot propose any change to anything yet.\n"
    assert run_for_real(world, "list").stdout.decode("utf-8") == "Actions: 0 waiting for you, 0 in all.\nNothing waiting for you.\n"


def test_run_for_real_the_exit_code_and_stderr_carry_a_refusal(world):
    result = run_for_real(world, "show", "7")
    assert result.returncode == 1
    assert result.stdout == b"" and b"there is no action 7" in result.stderr
    assert run_for_real(world, "nonsense").returncode == 2


def test_importing_the_tool_does_not_load_the_model_client(run_python):
    result = run_python("import sys, diya_actions_cli; print('openai' in sys.modules)")
    assert result.returncode == 0 and result.stdout.strip() == "False", result.stderr
