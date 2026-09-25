"""diya_review.py: reviewing staged facts from the command line (docs/STAGE2_DESIGN.md, D6 and unit 4).

What this proves: every command does what it says and refuses, with a message and a non-zero exit and no
change, what it should refuse; the checks are kept current as facts change; whatever is read back from the
database -- model output, or something someone pasted -- reaches the terminal only as visible escapes,
never as an escape sequence; the tool needs no model and no network; and it says the same thing when run
for real as when it is called from a test.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

import diya_config
import diya_memory
import diya_review
from diya_db import Store
from diya_memory import Memory, import_legacy_profile
from dreaming import Dreamer
from fakes import FakeClient, text_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEAD_OLLAMA = "http://127.0.0.1:9/v1"  # nothing listens on port 9
ESC, BIDI, BOM, ZWSP = chr(27), chr(0x202E), chr(0xFEFF), chr(0x200B)
BACKSLASH = chr(92)


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(data / "review.db"),
        profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"),
        dream_log_path=str(data / "dream.log"),
        dream_pending_path=str(data / "pending.jsonl"),
    )


@pytest.fixture
def memory(config):
    return Memory(Store(config.db_path))


def review(config, *argv):
    out, err = io.StringIO(), io.StringIO()
    code = diya_review.main(list(argv), config=config, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def stage(config, *rows_and_replies):
    """Real messages and one real Dreaming cycle per (message, model reply)."""
    store = Store(config.db_path)
    threads = store.list_threads()
    thread = threads[0][0] if threads else store.create_thread()
    for message, reply in rows_and_replies:
        store.add_message(thread, "user", message)
        Dreamer(config, client=FakeClient([text_reply(reply)]), store=store).dream_cycle()


def no_control_characters(text):
    return all(ch == "\n" or (ord(ch) >= 32 and ord(ch) != 127 and not diya_memory._unwanted(ch)) for ch in text)


# --- showing the way ------------------------------------------------------------------------------

def test_help_lists_every_command_and_is_a_success(config, capsys):
    code = diya_review.main(["--help"], config=config)
    text = capsys.readouterr().out
    assert code == 0
    for command in ("ingest", "list", "show", "accept", "reject", "reopen", "retire", "restore", "edit", "add",
                    "export", "import-profile", "verify"):
        assert command in text


@pytest.mark.parametrize("argv", [[], ["nonsense"], ["accept"], ["accept", "abc"], ["show", "1.5"], ["edit", "1"], ["add"],
                                  ["list", "pending"], ["accept", "1", "2"]])
def test_a_command_that_makes_no_sense_is_a_usage_error_and_changes_nothing(config, memory, argv, capsys):
    assert diya_review.main(argv, config=config) == 2
    assert capsys.readouterr().out == ""  # the explanation is on stderr
    assert memory.facts() == []


def test_a_bad_setting_is_a_usage_error(monkeypatch, capsys):
    monkeypatch.setenv("DIYA_DREAM_PROFILE_MODE", "sideways")
    assert diya_review.main(["list"]) == 2
    assert "DIYA_DREAM_PROFILE_MODE" in capsys.readouterr().err


def test_an_empty_store_says_so(config):
    code, out, err = review(config, "list")
    assert (code, err) == (0, "")
    assert "0 of 2000 characters used. 0 candidates, 0 accepted, 0 rejected, 0 retired." in out
    assert "No candidate facts." in out
    assert review(config, "list", "all")[1].endswith("No facts yet.\n")
    assert review(config, "export") == (0, "", "")  # nothing accepted: nothing to export


# --- the whole way through, on what the real producer staged ---------------------------------------

def test_from_what_dreaming_staged_to_what_the_model_may_be_told(config, memory):
    stage(config, ("I adopted a cat named Pixel and I love green tea", "- has a cat named Pixel\n- likes green tea\n- is a doctor"))

    code, out, _ = review(config, "ingest")
    assert code == 0
    assert "Read 1 staged records: 3 new candidates, 0 already known, 0 lines with nothing to keep." in out
    assert "Checked 3 candidates; 3 changed." in out  # each now says which message it came from

    code, out, _ = review(config, "list")
    assert code == 0
    assert "   1  candidate  has a cat named Pixel" in out and "   3  candidate  is a doctor" in out
    assert "flags: ungrounded" in out  # on the invented one

    code, out, _ = review(config, "show", "3")
    assert code == 0
    assert "Fact 3: candidate (dreaming)" in out
    assert "text:    is a doctor" in out and "staged:  - is a doctor" in out
    assert "by:      qwen2.5:3b, staged " in out
    assert "flag:    ungrounded: few of its words appear in the messages it was extracted from" in out
    assert "[1] (chat 1) I adopted a cat named Pixel and I love green tea" in out
    assert "ingested by cli" in out and "flagged by cli" in out

    assert review(config, "accept", "1")[0:2] == (0, "Fact 1 accepted. Memory: 23 of 2000 characters used. 2 candidates, 1 accepted, 0 rejected, 0 retired.\n")
    assert review(config, "reject", "3")[0] == 0
    assert review(config, "accept", "2")[0] == 0
    assert review(config, "export") == (0, "- has a cat named Pixel\n- likes green tea\n", "")
    assert memory.accepted_texts() == ["has a cat named Pixel", "likes green tea"]

    assert review(config, "retire", "2")[0] == 0
    assert review(config, "export")[1] == "- has a cat named Pixel\n"
    assert review(config, "restore", "2")[0] == 0
    assert review(config, "reopen", "3")[0] == 0
    assert [f["status"] for f in memory.facts()] == ["accepted", "accepted", "candidate"]
    assert review(config, "verify") == (0, "Memory is consistent.\n", "")


def test_ingesting_again_reports_what_it_already_knew(config):
    stage(config, ("I like tea", "- likes tea"))
    review(config, "ingest")
    code, out, _ = review(config, "ingest")
    assert code == 0 and "0 new candidates, 1 already known" in out


def test_the_checks_are_kept_current_as_facts_change(config, memory):
    stage(config, ("I like green tea", "- likes green tea"), ("I really like green tea", "- likes green tea a lot"))
    review(config, "ingest")
    assert "flags: source message 2, similar to fact 1" in review(config, "list")[1]  # an earlier candidate counts
    review(config, "reject", "1")  # a rejected fact is nothing to be similar to
    assert "similar" not in review(config, "list")[1]
    review(config, "reopen", "1")
    assert "flags: source message 2, similar to fact 1" in review(config, "list")[1]
    review(config, "accept", "1")
    review(config, "retire", "1")
    assert "similar" not in review(config, "list")[1]


def test_show_explains_a_flag_that_points_at_another_fact(config):
    stage(config, ("I like green tea", "- likes green tea"), ("I like green tea", "- Likes Green Tea"))
    review(config, "ingest")
    review(config, "accept", "1")
    out = review(config, "show", "2")[1]
    assert "flag:    duplicate: says the same as fact 1 (accepted): likes green tea" in out
    assert "flag:    source_message: the message it best matches is 2" in out


# --- refusals ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("argv, message", [
    (["accept", "99"], "there is no fact 99"),
    (["show", "99"], "there is no fact 99"),
    (["reject", "99"], "there is no fact 99"),
    (["edit", "99", "new", "words"], "there is no fact 99"),
])
def test_an_unknown_fact_is_refused(config, argv, message):
    code, out, err = review(config, *argv)
    assert (code, out) == (1, "")
    assert err == f"diya_review: {message}\n"


def test_a_change_that_does_not_apply_is_refused_and_leaves_everything_as_it_was(config, memory):
    stage(config, ("I like tea", "- likes tea\n- likes coffee"))
    review(config, "ingest")
    review(config, "accept", "1")
    before = (memory.facts(), memory.events(1), memory.events(2))
    for argv, phrase in [
        (["accept", "1"], "fact 1 is accepted; only a candidate fact can be accepted"),
        (["retire", "2"], "fact 2 is candidate; only an accepted fact can be retired"),
        (["restore", "1"], "only a retired fact can be restored"),
        (["reopen", "2"], "only a rejected fact can be reopened"),
        (["edit", "1", "reworded"], "only a candidate can be edited"),
    ]:
        code, out, err = review(config, *argv)
        assert (code, out) == (1, ""), argv
        assert phrase in err, (argv, err)
    assert (memory.facts(), memory.events(1), memory.events(2)) == before


def test_a_repeat_and_a_full_profile_are_refused_with_the_reason(config, memory, monkeypatch):
    stage(config, ("I like tea", "- likes tea\n- Likes Tea\n- prefers strong coffee in the morning"))
    review(config, "ingest")
    review(config, "accept", "1")
    code, _out, err = review(config, "accept", "2")
    assert code == 1 and "fact 1 says the same thing and is already accepted" in err
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", 20)
    code, _out, err = review(config, "accept", "3")
    assert code == 1 and "memory is full" in err and "Retire a fact first." in err


def test_a_fact_too_long_to_accept_says_how_to_fix_it(config, memory):
    stage(config, ("a long rambling message", "- " + "long " * 60))
    review(config, "ingest")
    assert "too long to accept as it is" in review(config, "list")[1]
    assert "edit it shorter before accepting" in review(config, "show", "1")[1]
    code, _out, err = review(config, "accept", "1")
    assert code == 1 and "edit it shorter first" in err
    assert review(config, "edit", "1", "likes", "long", "rambles")[0] == 0
    assert review(config, "accept", "1")[0] == 0


def test_an_unreadable_queue_is_reported_and_nothing_is_ingested(config, memory):
    os.mkdir(config.dream_pending_path)
    code, out, err = review(config, "ingest")
    assert (code, out) == (2, "")
    assert "could not read the staged queue" in err
    assert memory.facts() == []


# --- typing facts ----------------------------------------------------------------------------------

def test_a_typed_fact_is_cleaned_and_goes_in_accepted(config, memory):
    code, out, _ = review(config, "add", "-", "works", "in   the", "evenings")
    assert code == 0 and out.startswith("Added as fact 1, already accepted. Memory: 23 of 2000 characters used.")
    assert memory.accepted_texts() == ["works in the evenings"]
    assert memory.get(1)["source"] == "manual"
    assert review(config, "add", "Works In The Evenings")[0] == 1  # a repeat


@pytest.mark.parametrize("words", [["-"], ["NONE"], [ESC], [BOM]])
def test_text_with_nothing_in_it_is_refused(config, memory, words):
    code, out, err = review(config, "add", *words)
    assert (code, out) == (1, "")
    assert "nothing left of that text" in err
    assert memory.facts() == []


def test_an_edit_is_cleaned_the_same_way(config, memory):
    stage(config, ("I like tea", "- likes tea"))
    review(config, "ingest")
    assert review(config, "edit", "1", "*", "likes", "green   tea", ESC)[0] == 0
    assert memory.get(1)["text"] == "likes green tea"


# --- what reaches the terminal ----------------------------------------------------------------------

def test_nothing_read_back_can_send_an_escape_sequence_to_the_terminal(config, memory):
    """The staged line and the user's message are unsanitised evidence: they may carry anything."""
    hostile = "- likes tea " + ESC + "[2J" + ESC + "]0;pwned" + chr(7) + " " + BIDI + "evil" + ZWSP + " " + chr(0x2028) + "next"
    store = Store(config.db_path)
    thread = store.create_thread()
    store.add_message(thread, "user", "I like tea " + ESC + "[31m red " + BIDI + "text\nsecond line")
    with open(config.dream_pending_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"timestamp": "2026-01-01T00:00:00+00:00", "first_message_id": 1, "last_message_id": 1,
                            "model": "m" + ESC, "facts": [hostile]}, ensure_ascii=False) + "\n")
    review(config, "ingest")

    outputs = [review(config, *argv) for argv in (["list"], ["list", "all"], ["show", "1"], ["verify"], ["export"])]

    for code, out, err in outputs:
        assert code == 0 and no_control_characters(out) and no_control_characters(err)
    shown = outputs[2][1]
    assert BACKSLASH + "u001b" in shown  # the escape is visible as text ...
    assert BACKSLASH + "u202e" in shown  # ... and so is the direction override
    assert BACKSLASH + "u200b" in shown
    assert "second line" in shown and "text second line" in shown  # a line break in the message is a space, not a break


def test_facts_with_ordinary_non_ascii_text_are_shown_as_they_are(config, memory):
    stage(config, ("I run a café", "- owns a café\n- 山田 lives in Osaka"))
    review(config, "ingest")
    out = review(config, "list")[1]
    assert "owns a café" in out and "山田 lives in Osaka" in out and BACKSLASH not in out


def test_printable_collapses_whitespace_escapes_the_hidden_and_cuts_long_text():
    assert diya_review.printable("a\n\tb   c") == "a b c"
    assert diya_review.printable("x" + ESC + "y") == "x" + BACKSLASH + "u001by"
    assert diya_review.printable(chr(0x1F468) + chr(0x200D) + chr(0x1F469)) == chr(0x1F468) + chr(0x200D) + chr(0x1F469)  # a joiner in an emoji is fine
    assert diya_review.printable(chr(0xE000)) == BACKSLASH + "ue000"
    assert diya_review.printable("z" * 50, limit=10) == "z" * 10 + "..."
    assert diya_review.printable("z" * 10, limit=10) == "z" * 10
    assert diya_review.printable(12) == "12"


def test_a_long_source_message_is_cut(config, memory):
    stage(config, ("word " * 200, "- says a word"))
    review(config, "ingest")
    line = next(l for l in review(config, "show", "1")[1].split("\n") if l.strip().startswith("[1]"))
    assert line.endswith("...") and len(line) < 400


def test_when_the_source_messages_are_gone_show_says_so(config, memory):
    stage(config, ("I like tea", "- likes tea"))
    review(config, "ingest")
    conn = Store(config.db_path).connect()
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    review(config, "ingest")  # refresh the checks
    out = review(config, "show", "1")[1]
    assert "(none of them are in the database any more)" in out
    assert "its source messages are gone" in review(config, "list")[1]


def test_show_lists_only_the_users_own_messages_which_are_what_the_model_was_shown(config, memory):
    store = Store(config.db_path)
    thread = store.create_thread()
    store.add_message(thread, "user", "I adopted a cat named Pixel")
    store.add_message(thread, "assistant", "Congratulations on the kitten!")
    store.add_message(thread, "user", "and I like tea")
    Dreamer(config, client=FakeClient([text_reply("- has a cat named Pixel")]), store=store).dream_cycle()
    review(config, "ingest")
    out = review(config, "show", "1")[1]
    assert "extracted from your messages 1 to 3" in out
    assert "[1] (chat 1) I adopted a cat named Pixel" in out and "[3] (chat 1) and I like tea" in out
    assert "Congratulations" not in out and "[2]" not in out


def test_an_edit_refreshes_the_flags(config, memory):
    stage(config, ("a long rambling message", "- " + "long " * 60))
    review(config, "ingest")
    assert "too long to accept as it is" in review(config, "list")[1]
    review(config, "edit", "1", "rambles", "on")
    assert "too long" not in review(config, "list")[1]


def test_adding_a_fact_refreshes_the_flags_of_the_candidates_it_repeats(config, memory):
    stage(config, ("I like green tea", "- likes green tea"))
    review(config, "ingest")
    assert "same as fact" not in review(config, "list")[1]
    review(config, "add", "Likes", "green", "tea")
    assert "flags: source message 1, same as fact 2" in review(config, "list")[1]


# --- the old profile ---------------------------------------------------------------------------------

def test_the_old_profile_is_imported_reported_and_never_changed(config, memory):
    body = b"- likes tea\r\n- has a cat named Pixel\n"
    pathlib.Path(config.profile_path).write_bytes(body)
    code, out, _ = review(config, "import-profile")
    assert code == 0
    assert "Imported 2 facts" in out and "The file was not changed." in out
    assert pathlib.Path(config.profile_path).read_bytes() == body
    assert review(config, "export")[1] == "- likes tea\n- has a cat named Pixel\n"
    again = review(config, "import-profile")[1]
    assert "Imported 0 facts" in again and "2 were imported before" in again


def test_a_profile_over_the_limit_is_imported_whole_with_a_warning(config, monkeypatch):
    pathlib.Path(config.profile_path).write_text("- " + "a" * 30 + "\n- " + "b" * 30 + "\n", encoding="utf-8")
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", 40)
    out = review(config, "import-profile")[1]
    assert "Imported 2 facts" in out and "over the 40 limit" in out and "nothing new can be accepted until some are retired" in out


# --- verifying ----------------------------------------------------------------------------------------

def test_verify_reports_damage_and_says_it_with_a_non_zero_exit(config, memory):
    stage(config, ("I like tea", "- likes tea"))
    review(config, "ingest")
    conn = Store(config.db_path).connect()
    conn.execute("UPDATE facts SET status = 'accepted' WHERE id = 1")
    conn.commit()
    conn.close()
    code, out, _ = review(config, "verify")
    assert code == 1 and "PROBLEM: fact 1 is accepted but its events say candidate" in out


# --- for real ------------------------------------------------------------------------------------------

def _env(config):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DIYA_") and k != "PYTHONIOENCODING"}
    env.update(DIYA_DB_PATH=config.db_path, DIYA_PROFILE_PATH=config.profile_path, DIYA_DREAM_PENDING_PATH=config.dream_pending_path,
               DIYA_DREAM_STATE_PATH=config.dream_state_path, DIYA_DREAM_LOG_PATH=config.dream_log_path,
               DIYA_OLLAMA_URL=DEAD_OLLAMA, NO_PROXY="127.0.0.1,localhost")
    return env


def _run(config, *argv):
    return subprocess.run([sys.executable, str(ROOT / "diya_review.py"), *argv], cwd=ROOT, env=_env(config), capture_output=True, timeout=60)


def test_run_as_a_script_with_no_model_and_no_network_it_works_and_speaks_utf8(config, memory):
    """Ollama is deliberately unreachable: the tool must not need it. Output is UTF-8 whatever the console."""
    memory.add_manual("owns a café", "cli")
    memory.add_manual("山田 lives in Osaka", "cli")
    result = _run(config, "list", "accepted")
    assert result.returncode == 0, result.stderr
    text = result.stdout.decode("utf-8")
    assert "owns a café" in text and "山田 lives in Osaka" in text
    # byte for byte: UTF-8 and LF only, even on Windows, so `export > user_profile.txt` is a valid profile
    assert _run(config, "export").stdout == "- owns a café\n- 山田 lives in Osaka\n".encode("utf-8")


def test_run_as_a_script_the_exit_code_and_stderr_carry_a_refusal(config):
    result = _run(config, "accept", "7")
    assert result.returncode == 1
    assert result.stdout == b"" and b"there is no fact 7" in result.stderr
    assert _run(config, "nonsense").returncode == 2


def test_importing_the_tool_does_not_load_the_model_client(run_python):
    result = run_python("import sys, diya_review; print('openai' in sys.modules)")
    assert result.returncode == 0 and result.stdout.strip() == "False", result.stderr
