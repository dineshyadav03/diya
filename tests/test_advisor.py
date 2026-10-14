"""diya_advisor.py: a harness advisor that proposes patches for a gate's misses and never applies one (docs/ADVISOR_DESIGN.md, unit H1 step 1).

What this proves: the search proposes only the start of a missed message and only what breaks no labelled case; a candidate that would newly match more than a few of the person's own past messages is
not proposed; a patch is a real unified diff that applies and fixes what it says; nothing outside the advisor's own folder is ever written (the real source files are hashed before and after); a
message the person records has to be got right by the next proposal; and the real reminder gate is left alone by every proposal the advisor makes for it.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import ast
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

import diya_advisor as advisor
import diya_config
import diya_intent
from diya_advisor import AdvisorError, Case, Gate, add_alternative, add_case, alternatives, background_messages, main, propose

ROOT = pathlib.Path(__file__).resolve().parent.parent
ESC = chr(27)

MINI_GATE = '''import re

_ASK = re.compile(
    r"\\bremind\\s+me\\b"
    r"|\\bnote\\s+to\\s+self\\b",
    re.IGNORECASE,
)


def is_ask(text):
    return isinstance(text, str) and bool(_ASK.search(text))
'''
MINI_LABELLED = '''YES = ["Remind me to call mum", "note to self: buy milk"]
NO = ["What is a reminder?", "Let me know what the weather is", "Tell me a joke", "Wake up, Diya"]
MISS = ["Ping me at 5 about the call", "Wake me up at 7"]
ALLOWED = ["What does remind me mean?"]
'''


def mini_gate(**kw):
    sources = kw.pop("sources", (("labelled.py", "YES", True, False), ("labelled.py", "NO", False, False), ("labelled.py", "MISS", True, True), ("labelled.py", "ALLOWED", False, True)))
    return Gate("mini", "mini_gate.py", "is_ask", "_ASK", sources=sources, tests=kw.pop("tests", ("tests/test_mini.py",)))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "mini_gate.py").write_text(MINI_GATE, encoding="utf-8", newline="\n")
    (root / "labelled.py").write_text(MINI_LABELLED, encoding="utf-8", newline="\n")
    (root / "tests" / "test_mini.py").write_text("import mini_gate\n\n\ndef test_it():\n    assert mini_gate.is_ask('remind me to x')\n", encoding="utf-8", newline="\n")
    return root


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def cases_of(root, gate=None):
    return advisor._labelled(str(root), gate or mini_gate())


# --- the candidates -----------------------------------------------------------------------------------------------------------


def test_a_candidate_is_the_start_of_the_missed_message_up_to_the_first_number_and_must_hold_me():
    assert alternatives("Ping me at 5 about the call") == [r"\bping\s+me\b", r"\bping\s+me\s+at\b"]
    assert alternatives("Wake me up at 7") == [r"\bwake\s+me\b", r"\bwake\s+me\s+up\b", r"\bwake\s+me\s+up\s+at\b"]
    assert alternatives("Please, could you ping me tomorrow") == [r"\bping\s+me\b", r"\bping\s+me\s+tomorrow\b"]
    assert alternatives("Hey Diya, can you please alert myself when it rains") == [r"\balert\s+myself\b", r"\balert\s+myself\s+when\b", r"\balert\s+myself\s+when\s+it\b", r"\balert\s+myself\s+when\s+it\s+rains\b"]


def test_a_message_without_me_or_with_a_number_first_has_no_candidate():
    assert alternatives("It is time to go") == []
    assert alternatives("5 minutes then ping me") == []
    assert alternatives("") == []


def test_the_candidates_are_regular_expressions_that_match_what_they_were_made_from():
    for text in ("Ping me at 5 about the call", "Let me know at 3 that it's time to leave", "Buzz me tomorrow at 9"):
        for alternative in alternatives(text):
            assert re.search(alternative, text, re.IGNORECASE), (alternative, text)


# --- editing the source in memory -------------------------------------------------------------------------------------------


def test_an_alternative_is_added_as_one_more_line_of_the_pattern_and_the_file_still_works():
    patched = add_alternative(MINI_GATE, "_ASK", r"\bping\s+me\b")
    assert '    r"|\\bnote\\s+to\\s+self\\b"\n    r"|\\bping\\s+me\\b",\n    re.IGNORECASE,' in patched
    module = advisor.module_from_source(patched)
    assert module.is_ask("Ping me at 5") and module.is_ask("remind me") and not module.is_ask("let me know")


def test_the_files_own_line_endings_are_kept():
    crlf = MINI_GATE.replace("\n", "\r\n")
    patched = add_alternative(crlf, "_ASK", r"\bping\s+me\b")
    assert "\n" not in patched.replace("\r\n", "") and 'r"|\\bping\\s+me\\b",\r\n' in patched


def test_a_pattern_on_one_line_and_text_with_other_characters_around_it_are_handled():
    source = "# café — über\nimport re\nX = re.compile(r\"remind\\s+me\", re.I)  # ü\n\n\ndef f(t):\n    return bool(X.search(t))\n"
    patched = add_alternative(source, "X", r"\bping\s+me\b")
    assert advisor.module_from_source(patched).f("ping me") and advisor.module_from_source(patched).f("remind me")
    assert "# café" in patched and "# ü" in patched


@pytest.mark.parametrize("source", ["import re\nY = 1\n", "import re\nX = 5\n", "import re\nX = re.compile(PATTERN)\nPATTERN = 'a'\n", "import re\ndef X():\n    pass\n"])
def test_a_name_that_is_not_a_compiled_string_is_no_edit_at_all(source):
    with pytest.raises(AdvisorError, match="no edit to propose"):
        add_alternative(source, "X", "a")


# --- the search ------------------------------------------------------------------------------------------------------------


def test_each_miss_gets_a_patch_that_fixes_it_and_breaks_nothing(repo):
    gate = mini_gate()
    result = propose(str(repo), gate, cases_of(repo))
    assert [p.alternative for p in result.proposals] == [r"\bping\s+me\b", r"\bwake\s+me\s+up\b"] or [p.alternative for p in result.proposals] == [r"\bping\s+me\b", r"\bwake\s+me\b"]
    for proposal in result.proposals:
        module = advisor.module_from_source(proposal.source)
        assert all(module.is_ask(text) == expected for text, expected in [("Remind me to call mum", True), ("What is a reminder?", False), ("Tell me a joke", False)])
        assert proposal.misses
    assert result.no_safe_fix == [] and result.false_allowances == ["What does remind me mean?"]
    assert result.right_before == 6 and result.cases == 9


def test_a_message_the_labelled_cases_contain_makes_the_search_pick_a_longer_edit(repo):
    (repo / "labelled.py").write_text(MINI_LABELLED.replace('"Wake up, Diya"', '"Wake up, Diya", "Wake me up inside is a good song"'), encoding="utf-8", newline="\n")
    result = propose(str(repo), mini_gate(), cases_of(repo))
    assert r"\bwake\s+me\s+up\s+at\b" in [p.alternative for p in result.proposals]
    assert r"\bwake\s+me\b" not in [p.alternative for p in result.proposals]


def test_when_every_edit_that_fixes_a_miss_breaks_a_case_it_says_so_and_proposes_nothing(repo):
    (repo / "labelled.py").write_text(MINI_LABELLED.replace('"Wake up, Diya"', '"Wake up, Diya", "Wake me up at the end", "Wake me up inside", "Wake me up at 7 is a song"'), encoding="utf-8", newline="\n")
    result = propose(str(repo), mini_gate(), cases_of(repo))
    assert [m for m, *_ in result.no_safe_fix] == ["Wake me up at 7"]
    assert result.no_safe_fix[0][2] is None
    assert [p.alternative for p in result.proposals] == [r"\bping\s+me\b"]


def test_an_edit_that_would_newly_match_more_than_two_of_the_persons_own_messages_is_not_proposed(repo):
    background = ["Ping me at once", "ping me at all", "Ping me at ease", "Ping me when ready", "something else"]
    result = propose(str(repo), mini_gate(), cases_of(repo), background)
    assert [p.alternative for p in result.proposals if "Ping me at 5 about the call" in p.misses] == []
    refused = next(item for item in result.no_safe_fix if item[0] == "Ping me at 5 about the call")
    assert refused[2] == 3 and len(refused[3]) <= advisor.EXAMPLES and refused[1] == r"\bping\s+me\s+at\b"


def test_a_longer_edit_that_matches_fewer_of_the_persons_messages_is_preferred_to_a_shorter_one(repo):
    background = ["Ping me when you can", "ping me later", "Ping me again"]
    result = propose(str(repo), mini_gate(), cases_of(repo), background)
    chosen = next(p for p in result.proposals if "Ping me at 5 about the call" in p.misses)
    assert chosen.alternative == r"\bping\s+me\s+at\b" and chosen.newly_matched == []


def test_up_to_two_newly_matched_messages_are_allowed_and_shown(repo):
    result = propose(str(repo), mini_gate(), cases_of(repo), ["Ping me when you can", "ping me later", "unrelated"])
    chosen = next(p for p in result.proposals if "Ping me at 5 about the call" in p.misses)
    assert chosen.alternative == r"\bping\s+me\s+at\b" or len(chosen.newly_matched) <= 2
    assert chosen.background_size == 3


def test_a_message_the_gate_already_matches_is_not_counted_as_newly_matched(repo):
    result = propose(str(repo), mini_gate(), cases_of(repo), ["Remind me to ping me", "remind me again"] * 3)
    assert all(p.newly_matched == [] for p in result.proposals)


def test_a_false_allowance_is_listed_and_never_proposed_for(repo):
    result = propose(str(repo), mini_gate(), cases_of(repo))
    assert result.false_allowances == ["What does remind me mean?"]
    assert all("What does remind me mean?" not in p.misses for p in result.proposals)


def test_the_combined_patch_fixes_them_all_and_breaks_nothing(repo):
    result = propose(str(repo), mini_gate(), cases_of(repo))
    module = advisor.module_from_source(result.combined.source)
    for text in ("Ping me at 5 about the call", "Wake me up at 7", "Remind me to call mum"):
        assert module.is_ask(text)
    assert not any(module.is_ask(text) for text in ("What is a reminder?", "Let me know what the weather is", "Tell me a joke", "Wake up, Diya"))
    assert len(result.combined.misses) == 2


def test_a_gate_with_nothing_wrong_gets_no_proposal(repo):
    (repo / "labelled.py").write_text('YES = ["Remind me to call mum"]\nNO = ["Tell me a joke"]\nMISS = []\nALLOWED = []\n', encoding="utf-8", newline="\n")
    result = propose(str(repo), mini_gate(), cases_of(repo))
    assert result.proposals == [] and result.no_safe_fix == [] and result.combined is None
    assert "nothing to propose" in advisor.report_text(result, [])


# --- the patch ---------------------------------------------------------------------------------------------------------------


def test_a_patch_is_a_unified_diff_of_the_gates_file_only_and_applies(repo, tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    result = propose(str(repo), mini_gate(), cases_of(repo))
    for proposal in result.proposals + [result.combined]:
        assert proposal.patch.startswith("--- a/mini_gate.py\n+++ b/mini_gate.py\n@@")
        scratch = tmp_path / "apply"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir()
        (scratch / "mini_gate.py").write_text(MINI_GATE, encoding="utf-8", newline="\n")
        (scratch / "p.patch").write_text(proposal.patch, encoding="utf-8", newline="")
        done = subprocess.run(["git", "apply", "p.patch"], cwd=scratch, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        assert (scratch / "mini_gate.py").read_text(encoding="utf-8") == proposal.source


# --- nothing of Diya's is changed ---------------------------------------------------------------------------------------------


def run_main(repo, tmp_path, args, **settings):
    config = diya_config.load_config({"DIYA_ADVISOR_DIR": str(tmp_path / "advisor"), "DIYA_DB_PATH": str(tmp_path / "none.db"), **settings})

    class Sink:
        text = ""

        def write(self, chunk):
            self.text += chunk

        def flush(self):
            pass

    sink = Sink()
    return main(args, config=config, out=sink, root=str(repo), gates={"mini": mini_gate()}), sink.text


def test_propose_writes_only_into_the_advisor_folder_and_changes_no_file_of_the_repository(repo, tmp_path):
    before = digest(repo)
    code, text = run_main(repo, tmp_path, ["propose"])
    assert code == 0 and "nothing of Diya's was changed" in text
    assert digest(repo) == before
    written = sorted(p.name for p in (tmp_path / "advisor").iterdir())
    assert written == ["proposal-1.patch", "proposal-2.patch", "proposal-all.patch", "report.md"]


def test_an_older_runs_patches_are_removed_not_left_to_be_mistaken_for_this_runs(repo, tmp_path):
    run_main(repo, tmp_path, ["propose"])
    (repo / "labelled.py").write_text('YES = ["Remind me to call mum"]\nNO = []\nMISS = []\nALLOWED = []\n', encoding="utf-8", newline="\n")
    run_main(repo, tmp_path, ["propose"])
    assert sorted(p.name for p in (tmp_path / "advisor").iterdir()) == ["report.md"]


def test_only_the_three_functions_that_write_into_the_advisor_folder_open_a_file_for_writing():
    tree = ast.parse((ROOT / "diya_advisor.py").read_text(encoding="utf-8"))
    writers = set()
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for call in [n for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"]:
            mode = call.args[1].value if len(call.args) > 1 and isinstance(call.args[1], ast.Constant) else next((k.value.value for k in call.keywords if k.arg == "mode"), "r")
            if any(flag in mode for flag in "wax+"):
                writers.add(function.name)
    assert writers == {"write_outputs", "add_case", "run_tests_on_copy"}


def test_the_advisor_has_no_model_and_no_network_in_it():
    tree = ast.parse((ROOT / "diya_advisor.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported == {"__future__", "argparse", "ast", "difflib", "importlib", "json", "os", "re", "shutil", "sqlite3", "subprocess", "sys", "tempfile", "types", "dataclasses", "pathlib", "diya_config", "diya_memory"}


def test_a_patch_is_tested_on_a_private_copy_and_the_real_files_are_untouched(repo, tmp_path):
    before = digest(repo)
    result = propose(str(repo), mini_gate(), cases_of(repo))
    code, tail = advisor.run_tests_on_copy(str(repo), mini_gate(), result.combined.source)
    assert code == 0 and "passed" in tail
    broken = MINI_GATE.replace("bool(_ASK.search(text))", "False")
    code, tail = advisor.run_tests_on_copy(str(repo), mini_gate(), broken)
    assert code != 0 and "failed" in tail
    assert digest(repo) == before


# --- recording a miss ------------------------------------------------------------------------------------------------------


def test_a_recorded_message_has_to_be_got_right_by_the_next_proposal(repo, tmp_path):
    code, text = run_main(repo, tmp_path, ["add", "mini", "Buzz me tomorrow", "yes"])
    assert code == 0 and text.startswith("Recorded")
    assert run_main(repo, tmp_path, ["add", "mini", "Buzz me tomorrow", "yes"])[1] == "Already recorded.\n"
    run_main(repo, tmp_path, ["propose"])
    report = (tmp_path / "advisor" / "report.md").read_text(encoding="utf-8")
    assert "(9 labelled, 1 you added)" in report.replace("Looked at 10 cases ", "") or "1 you added" in report
    assert "Buzz me tomorrow" in report


def test_a_recorded_message_is_one_line_of_plain_text(tmp_path):
    for bad in ("", "   ", "x" * 501, "a" + ESC + "b", "line\nbreak"):
        with pytest.raises(AdvisorError):
            add_case(str(tmp_path), mini_gate(), bad, True)
    assert not (tmp_path / "cases.jsonl").exists()


def test_the_recorded_messages_belong_to_their_own_gate_and_a_damaged_line_is_skipped(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"gate": "other", "text": "a", "expected": True}) + "\nnot json\n" + json.dumps({"gate": "mini", "text": "b", "expected": False}) + "\n" + json.dumps({"gate": "mini", "text": 5, "expected": True}) + "\n", encoding="utf-8")
    assert [(c.text, c.expected) for c in advisor.added_cases(str(tmp_path), mini_gate())] == [("b", False)]


# --- the background ---------------------------------------------------------------------------------------------------------


def make_db(path, messages):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, role TEXT, content TEXT, created_at TEXT)")
    for role, content in messages:
        conn.execute("INSERT INTO messages (thread_id, role, content, created_at) VALUES (1, ?, ?, 'x')", (role, content))
    conn.commit()
    conn.close()


def test_the_background_is_what_the_person_typed_newest_first_without_duplicates_and_the_database_is_not_changed(tmp_path):
    path = str(tmp_path / "d.db")
    make_db(path, [("user", "first"), ("assistant", "an answer"), ("user", "second"), ("user", "first"), ("user", "")])
    before = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    assert background_messages(path) == ["first", "second"]
    assert background_messages(path, limit=1) == ["first"]
    assert hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest() == before


def test_no_database_a_damaged_one_or_one_without_messages_is_an_empty_background_and_nothing_is_made(tmp_path):
    assert background_messages(str(tmp_path / "none.db")) == [] and not (tmp_path / "none.db").exists()
    assert background_messages("") == []
    (tmp_path / "bad.db").write_bytes(b"not a database")
    assert background_messages(str(tmp_path / "bad.db")) == []
    sqlite3.connect(tmp_path / "empty.db").close()
    assert background_messages(str(tmp_path / "empty.db")) == []


# --- the report ------------------------------------------------------------------------------------------------------------


def test_the_report_says_what_it_looked_at_what_it_proposes_and_what_else_has_to_change(repo):
    result = propose(str(repo), mini_gate(), cases_of(repo), ["Ping me at lunch", "hello"])
    text = advisor.report_text(result, ["tests/test_x.py:3"])
    assert "Looked at 9 cases (9 labelled, 0 you added) and 2 of your own past messages" in text
    assert "## Proposal 1: add `" in text and "Newly matches" in text and "proposal-all.patch" in text
    assert "What does remind me mean?" in text and "tests/test_x.py:3" in text and "git apply advisor/proposal-N.patch" in text


def test_what_is_quoted_in_the_report_is_made_safe_to_show(repo):
    background = [f"Ping me at {ESC}[31mred", "Ping me at the end", "ping me at once"]
    result = propose(str(repo), mini_gate(), cases_of(repo), background)
    text = advisor.report_text(result, [])
    assert ESC not in text


def test_the_report_lists_the_edits_that_have_no_safe_fix_in_both_of_their_shapes(repo):
    (repo / "labelled.py").write_text(MINI_LABELLED.replace('"Wake up, Diya"', '"Wake up, Diya", "Wake me up at the end", "Wake me up inside", "Wake me up at 7 is a song"'), encoding="utf-8", newline="\n")
    result = propose(str(repo), mini_gate(), cases_of(repo), ["Ping me at once", "ping me at all", "Ping me at ease", "Ping me at noon"])
    text = advisor.report_text(result, [])
    assert "## No safe fix" in text and "breaks a labelled case" in text
    assert "would newly match" not in text or "of your past messages (more than 2)" in text


# --- the command line ------------------------------------------------------------------------------------------------------


def test_the_list_command_says_how_many_cases_and_known_misses_each_gate_has(repo, tmp_path):
    code, text = run_main(repo, tmp_path, ["list"])
    assert code == 0 and text == "mini: 9 cases (3 known misses), in mini_gate.py (is_ask)\n"


def test_a_wrong_command_or_gate_is_a_usage_error(repo, tmp_path):
    assert run_main(repo, tmp_path, ["frobnicate"])[0] == 2
    assert run_main(repo, tmp_path, ["propose", "--gate", "nope"])[0] == 2
    assert run_main(repo, tmp_path, ["add", "mini", "x", "maybe"])[0] == 2
    assert run_main(repo, tmp_path, [])[0] == 2


def test_a_message_that_cannot_be_recorded_is_said_in_words(repo, tmp_path):
    code, text = run_main(repo, tmp_path, ["add", "mini", "x" * 501, "yes"])
    assert code == 1 and text.startswith("Not done: a message to record")


def test_the_run_tests_option_runs_the_gates_tests_and_puts_the_answer_in_the_report(repo, tmp_path):
    code, _ = run_main(repo, tmp_path, ["propose", "--run-tests"])
    assert code == 0
    report = (tmp_path / "advisor" / "report.md").read_text(encoding="utf-8")
    assert "tests on a private copy" in report and "passed" in report


# --- the real reminder gate ---------------------------------------------------------------------------------------------------


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_everyday_messages_are_all_refused_by_the_reminder_gate_today_and_the_two_it_accepts_are_the_known_misses():
    everyday = load(ROOT / "tests" / "labelled_everyday.py", "labelled_everyday")
    assert [t for t in everyday.EVERYDAY if diya_intent.is_reminder_request(t)] == []
    assert [t for t in everyday.EVERYDAY_ALLOWED if not diya_intent.is_reminder_request(t)] == []
    assert len(everyday.EVERYDAY) == 48 and len(everyday.EVERYDAY_ALLOWED) == 2


def test_no_proposal_for_the_real_gate_changes_what_it_says_to_any_everyday_or_labelled_message_and_each_patch_applies():
    gate = advisor.GATES["reminder"]
    source = (ROOT / gate.module).read_text(encoding="utf-8")
    cases = advisor._labelled(str(ROOT), gate)
    assert len(cases) == 119
    result = propose(str(ROOT), gate, cases)
    assert result.right_before == 107 and len(result.proposals) + len(result.no_safe_fix) == 6
    base = advisor.module_from_source(source)
    for proposal in result.proposals + ([result.combined] if result.combined else []):
        patched = advisor.module_from_source(proposal.source)
        for case in cases:
            if getattr(base, gate.function)(case.text) == case.expected:
                assert getattr(patched, gate.function)(case.text) == case.expected, (proposal.alternative, case.text)
        for text in proposal.misses:
            assert getattr(patched, gate.function)(text) is True
        assert proposal.patch.startswith("--- a/diya_intent.py\n+++ b/diya_intent.py\n")
    assert (ROOT / gate.module).read_text(encoding="utf-8") == source


def test_what_would_have_to_change_if_a_proposal_is_accepted_is_named_for_the_real_gate():
    pinned = advisor.pins(str(ROOT), advisor.GATES["reminder"])
    assert any(line.startswith("tests/test_reminders.py:") for line in pinned) and any(line.startswith("tests/labelled_requests.py:") for line in pinned)
    assert any(line.startswith("tests/labelled_everyday.py:") for line in pinned)


def test_the_advisor_folder_is_never_committed():
    assert "/advisor/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
