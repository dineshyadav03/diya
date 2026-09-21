import os
import sqlite3

import pytest

import diya
import diya_config
import diya_evals
from diya_evals import EvalIsolationError
from fakes import FakeClient, text_reply, tool_reply

DEAD_OLLAMA = {"DIYA_OLLAMA_URL": "http://127.0.0.1:9/v1"}


def eval_agent(tmp_path, *replies):
    workdir = tmp_path / "evalwork"
    workdir.mkdir(exist_ok=True)
    client = FakeClient(replies)
    return diya_evals.make_eval_agent(str(workdir), client), client


def live_db_path():
    return diya_config.load_config().db_path


def table_rows(path, table):
    if not os.path.exists(path):
        return None
    return sqlite3.connect(path).execute(f"select count(*) from {table}").fetchone()[0]


# --- import and construction are free ---------------------------------------------------

def test_importing_diya_evals_has_no_side_effects(run_python, tmp_path):
    result = run_python("import sys, diya_evals; print('chromadb' in sys.modules)", env=DEAD_OLLAMA)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
    assert list(tmp_path.iterdir()) == []


def test_the_module_no_longer_offers_the_temporary_diya_shim():
    assert not hasattr(diya, "ask") and not hasattr(diya, "with_profile")


# --- isolation --------------------------------------------------------------------------

def test_the_eval_agent_uses_its_own_database_not_the_live_one(tmp_path):
    agent, _ = eval_agent(tmp_path)
    assert agent.store.path == str(tmp_path / "evalwork" / "evals.db")
    assert not diya_evals._same_file(agent.store.path, live_db_path())


def test_the_eval_agent_pins_the_fixture_notes_even_if_notes_are_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DIYA_NOTES_DIR", str(tmp_path / "my_real_notes"))
    agent, _ = eval_agent(tmp_path)
    assert agent.config.notes_dir == diya_evals.FIXTURE_NOTES
    assert os.path.isfile(os.path.join(diya_evals.FIXTURE_NOTES, "dentist.txt"))


def test_the_eval_agent_still_follows_the_model_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DIYA_MODEL", "some-bigger-model")
    monkeypatch.setenv("DIYA_OLLAMA_URL", "http://other-host:11434/v1")
    agent, _ = eval_agent(tmp_path)
    assert agent.config.model == "some-bigger-model"
    assert agent.config.ollama_url == "http://other-host:11434/v1"


def test_the_guard_refuses_the_configured_live_database(tmp_path):
    live_agent = diya.Agent(client=FakeClient())  # default config -> DIYA_DB_PATH, the "live" DB
    with pytest.raises(EvalIsolationError):
        diya_evals.assert_isolated(live_agent)


def test_the_guard_sees_through_relative_paths_and_aliases(monkeypatch, tmp_path):
    (tmp_path / "sub").mkdir()
    monkeypatch.setenv("DIYA_DB_PATH", str(tmp_path / "sub" / ".." / "test.db"))
    same_file_other_spelling = diya.Agent(
        diya_config.Config(db_path="test.db"), client=FakeClient()
    )
    with pytest.raises(EvalIsolationError):
        diya_evals.assert_isolated(same_file_other_spelling)


def test_the_guard_also_protects_the_default_diya_db_when_it_is_not_the_configured_one(tmp_path):
    default_named = diya.Agent(diya_config.Config(db_path="diya.db"), client=FakeClient())
    with pytest.raises(EvalIsolationError):
        diya_evals.assert_isolated(default_named)


def test_run_evals_refuses_a_live_agent_before_asking_the_model_anything(tmp_path):
    client = FakeClient()
    live_agent = diya.Agent(client=client)
    with pytest.raises(EvalIsolationError):
        diya_evals.run_evals(live_agent)
    assert client.chat_calls == []
    assert not os.path.exists(live_db_path())


def test_make_eval_agent_cannot_be_pointed_at_the_live_database(monkeypatch, tmp_path):
    # Even an eval work dir that happens to contain the live database's name is fine (the file
    # is always <workdir>/evals.db), but a live DB literally called evals.db in that dir is not.
    workdir = tmp_path / "evalwork"
    workdir.mkdir()
    monkeypatch.setenv("DIYA_DB_PATH", str(workdir / "evals.db"))
    with pytest.raises(EvalIsolationError):
        diya_evals.make_eval_agent(str(workdir), FakeClient())


def test_writes_from_an_eval_run_land_only_in_the_eval_database(tmp_path):
    case = {"name": "add", "prompt": "Remind me to stretch.", "expected_tool": "add_reminder",
            "expected_in_answer": ["stretch"]}
    agent, _ = eval_agent(
        tmp_path,
        tool_reply("add_reminder", '{"content": "stretch"}'),
        text_reply("Okay, I'll remind you to stretch."),
    )
    assert diya_evals.run_evals(agent, [case]) is True
    assert table_rows(agent.store.path, "reminders") == 1
    assert not os.path.exists(live_db_path())  # the live database was never even created


def test_an_eval_run_creates_no_threads(tmp_path):
    case = {"name": "math", "prompt": "What's 9 times 7?", "expected_tool": None, "expected_in_answer": ["63"]}
    agent, _ = eval_agent(tmp_path, text_reply("63"))
    diya_evals.run_evals(agent, [case])
    assert agent.store.list_threads() == []


def test_the_eval_run_does_not_inject_the_users_profile(tmp_path):
    (tmp_path / "profile.txt").write_text("Plays guitar.")  # DIYA_PROFILE_PATH from conftest
    case = {"name": "math", "prompt": "hi", "expected_tool": None, "expected_in_answer": []}
    agent, client = eval_agent(tmp_path, text_reply("hello"))
    diya_evals.run_evals(agent, [case])
    assert [m["role"] for m in client.chat_calls[0]["messages"]] == ["user"]


# --- scoring is unchanged ---------------------------------------------------------------

CASES = [
    {"name": "no tool", "prompt": "9x7?", "expected_tool": None, "expected_in_answer": ["63"]},
    {"name": "wrong tool", "prompt": "weather?", "expected_tool": "get_weather", "expected_in_answer": ["india"]},
    {"name": "forbidden", "prompt": "where?", "expected_tool": None, "expected_in_answer": [],
     "forbidden_in_answer": ["pakistan"]},
    {"name": "crash", "prompt": "boom", "expected_tool": None, "expected_in_answer": []},
]


def test_scoring_output_matches_the_original_format(tmp_path, capsys):
    agent, _ = eval_agent(tmp_path, text_reply("It is 63."), text_reply("Sunny."), text_reply("Karachi, Pakistan"))
    # the 4th case finds the fake client out of replies and crashes
    assert diya_evals.run_evals(agent, CASES) is False
    out = capsys.readouterr().out
    assert "[PASS] no tool" in out
    assert "[FAIL] wrong tool\n       - expected 'get_weather' to be called, but got []\n" in out
    assert "expected one of ['india'] in the answer -- got: 'Sunny.'" in out
    assert "found forbidden term 'pakistan' in the answer: 'Karachi, Pakistan'" in out
    assert "[FAIL] crash: crashed with " in out
    assert out.rstrip().endswith("1/4 passed")


# --- the entry point ----------------------------------------------------------------------

def test_main_runs_in_a_temporary_directory_that_is_cleaned_up(monkeypatch, tmp_path):
    seen = []
    original = diya_evals.make_eval_agent

    def recording(workdir, client=None):
        agent = original(workdir, client)
        seen.append(agent)
        return agent

    monkeypatch.setattr(diya_evals, "make_eval_agent", recording)
    client = FakeClient([text_reply("63")] * len(diya_evals.TEST_CASES) * 2)
    assert diya_evals.main(client) == 1  # the fake model can't pass every case; that's fine here

    (agent,) = seen
    workdir = os.path.dirname(agent.store.path)
    assert os.path.basename(workdir).startswith("diya-evals-")
    assert not os.path.exists(workdir)  # cleaned up
    assert not os.path.exists(live_db_path())  # and the live database was never created


def test_main_fails_fast_when_ollama_is_down(run_python):
    result = run_python("import sys, diya_evals; sys.exit(diya_evals.main())", env=DEAD_OLLAMA)
    assert result.returncode == 1
    assert "Couldn't start Diya: can't reach Ollama at" in result.stdout
    assert "[PASS]" not in result.stdout and "[FAIL]" not in result.stdout


def test_the_original_cases_are_unchanged():
    assert [c["name"] for c in diya_evals.TEST_CASES][:6] == [
        "arithmetic -- should need no tool at all",
        "notes retrieval -- dentist appointment",
        "weather -- geocoding disambiguation regression check",
        "file listing",
        "add a reminder",
        "list reminders",
    ]


def test_the_fact_share_and_question_cases_are_present_and_use_only_fictional_data():
    names = [c["name"] for c in diya_evals.TEST_CASES][6:]
    assert names == [
        "fact-share -- exam and travel detail: short acknowledgement, no tool",
        "fact-share -- personal detail: short acknowledgement, no research",
        "question -- still explained in full",
    ]
    for case in diya_evals.TEST_CASES[6:]:
        assert case["expected_tool"] is None
        assert ("max_words" in case) != ("min_words" in case)


def test_the_word_limits_are_enforced(tmp_path, capsys):
    short_only = {"name": "short", "prompt": "hi", "expected_tool": None, "expected_in_answer": [], "max_words": 3}
    long_only = {"name": "long", "prompt": "hi", "expected_tool": None, "expected_in_answer": [], "min_words": 5}
    agent, _ = eval_agent(tmp_path, text_reply("one two three four"), text_reply("one two three four"),
                          text_reply("one two"))
    assert diya_evals.run_evals(agent, [short_only]) is False
    assert diya_evals.run_evals(agent, [long_only]) is False
    out = capsys.readouterr().out
    assert "expected at most 3 words, got 4" in out and "expected at least 5 words, got 4" in out
    assert diya_evals.run_evals(agent, [short_only]) is True  # 2 words is within the limit
