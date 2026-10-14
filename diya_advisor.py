"""A harness advisor: finds what a gate gets wrong, proposes a patch, tests it, and stops (docs/ADVISOR_DESIGN.md, unit H1 step 1).

    python diya_advisor.py propose [--gate reminder] [--db PATH] [--run-tests]   search, write the report and the patches
    python diya_advisor.py add GATE "a message" yes|no                           record a message the gate got wrong (yes = it IS what the gate looks for)
    python diya_advisor.py list                                                  the gates, their cases, and the known misses

It NEVER changes a file of Diya's. It reads the gate's source, makes candidate edits in memory, runs each candidate against every labelled case and against a background of the person's own past
messages (read-only; nothing leaves the computer), and writes a report and unified diffs into DIYA_ADVISOR_DIR (git-ignored: it can quote the person's own messages). Applying a patch is the
person's act (`git apply`). No model is used: the proposer is a search over small edits, and what decides is arithmetic over cases.

Why a background: the labelled cases alone cannot tell a good edit from a harmful one (measured: `\\bcall\\b` fixes "Ping me at 5 about the call" and breaks none of the 71 labelled cases), so an edit
is also counted against the person's real history, and one that would newly match more than MAX_NEW of their past messages is not proposed.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path

import diya_config
from diya_memory import printable

MAX_NEW = 2  # past messages a proposal may newly match
MIN_WORDS, MAX_WORDS = 2, 5  # words of the missed message's start that a candidate is made of
BACKGROUND_LIMIT = 5000
MAX_CASE_CHARS = 500
EXAMPLES = 3
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
ROOT = os.path.dirname(os.path.abspath(__file__))
_LEAD_IN = re.compile(r"^\W*(?:(?:please|hey|hi|ok|okay|diya|can you|could you|would you|will you|and|then)\b[\s,]*)+", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z']*|\d\S*")
_ME = frozenset({"me", "us", "myself", "ourselves"})


@dataclass(frozen=True)
class Gate:
    """One yes/no gate that is a single regular expression: where it lives, what it is tested against, and which tests pin it."""

    name: str
    module: str  # file, relative to the repository root
    function: str  # the gate: text -> bool
    pattern: str  # the module-level name of the compiled regular expression the function searches with
    sources: tuple  # the labelled cases: (file relative to the root, name of a list in it, what the gate should say, whether the list holds cases it is KNOWN to get wrong)
    tests: tuple  # test files to run on a private copy with --run-tests


GATES = {
    "reminder": Gate(
        "reminder", "diya_intent.py", "is_reminder_request", "_REMINDER_REQUEST",
        sources=(
            ("tests/labelled_requests.py", "REQUESTS", True, False), ("tests/labelled_requests.py", "LIMIT_REFUSED", True, True),
            ("tests/labelled_requests.py", "NOT_REQUESTS", False, False), ("tests/labelled_requests.py", "LIMIT_ALLOWED", False, True),
            ("tests/labelled_everyday.py", "EVERYDAY", False, False), ("tests/labelled_everyday.py", "EVERYDAY_ALLOWED", False, True),
        ),
        tests=("tests/test_reminders.py", "tests/test_gate_bench.py"),
    ),
}


class AdvisorError(Exception):
    """Something the person has to fix, said in plain words."""


@dataclass
class Case:
    text: str
    expected: bool
    origin: str  # "labelled" or "added"
    known_miss: bool = False


@dataclass
class Proposal:
    alternative: str  # the regular expression added
    misses: list  # the cases it fixes (texts)
    newly_matched: list  # past messages it would newly match
    background_size: int
    patch: str  # a unified diff of the gate's file
    source: str  # the whole file as patched


@dataclass
class Result:
    gate: Gate
    cases: int = 0
    added: int = 0
    background: int = 0
    right_before: int = 0
    proposals: list = field(default_factory=list)
    no_safe_fix: list = field(default_factory=list)  # (miss, best alternative tried, how many past messages it would newly match, or None if it broke a labelled case)
    false_allowances: list = field(default_factory=list)  # cases the gate says yes to that are not requests: not proposed for
    combined: object = None  # the proposal that applies all of them at once


# ---- the gate's source, as a private module ------------------------------------------------------------------------


def _load_source(root, relative):
    with open(os.path.join(root, relative), encoding="utf-8", newline="") as handle:
        return handle.read()


def module_from_source(source, name="advisor_private_copy", filename="<advisor>"):
    """The gate's file run as a module of its own, so the real one is never touched and a candidate is judged by the code that would exist."""
    module = types.ModuleType(name)
    module.__file__ = filename
    exec(compile(source, filename, "exec"), module.__dict__)  # noqa: S102 -- Diya's own file, read from the repository, never anything from a message
    return module


def _labelled(root, gate):
    modules, cases = {}, []
    for relative, name, expected, known_miss in gate.sources:
        if relative not in modules:
            spec = importlib.util.spec_from_file_location("advisor_labelled_" + re.sub(r"\W", "_", relative), os.path.join(root, relative))
            modules[relative] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modules[relative])
        for text in getattr(modules[relative], name):
            if isinstance(text, str):  # the lists also hold None and numbers, to test that the gate is not fooled by them
                cases.append(Case(text, expected, "labelled", known_miss=known_miss))
    return cases


def added_cases(directory, gate):
    path = os.path.join(directory, "cases.jsonl")
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("gate") == gate.name and isinstance(row.get("text"), str) and isinstance(row.get("expected"), bool):
                out.append(Case(row["text"], row["expected"], "added", known_miss=True))
    return out


def background_messages(db_path, limit=BACKGROUND_LIMIT):
    """What the person has typed to Diya, newest first, without opening the database for writing or making one that is not there."""
    if not db_path or not os.path.isfile(db_path):
        return []
    try:
        conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT content FROM messages WHERE role = 'user' AND length(content) BETWEEN 1 AND 2000 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return list(dict.fromkeys(row[0] for row in rows if isinstance(row[0], str)))


# ---- candidates ----------------------------------------------------------------------------------------------------


def alternatives(text):
    """Regular expressions made of the START of a message that a gate refused: its first MIN_WORDS to MAX_WORDS words (after "please", "can you" ...), up to the first number, and only those that
    contain "me": the shape of a request addressed to Diya about the speaker, not any word the message happens to hold."""
    text = _LEAD_IN.sub("", text.replace(chr(0x2019), "'"), count=1)
    words = []
    for token in _WORD.findall(text):
        if token[0].isdigit():
            break
        words.append(token.lower())
        if len(words) == MAX_WORDS:
            break
    out = []
    for size in range(MIN_WORDS, len(words) + 1):
        span = words[:size]
        if _ME & set(span):
            out.append(r"\b" + r"\s+".join(re.escape(word) for word in span) + r"\b")
    return out


def _call_node(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name and isinstance(node.value, ast.Call) and node.value.args:
            first = node.value.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return node, first
    raise AdvisorError(f"{name} is not a re.compile(...) of one string at the top of the file, so there is no edit to propose")


def add_alternative(source, name, alternative):
    """The file's source with `|alternative` added to the end of the pattern `name`, as one more line of its string, in the file's own line endings."""
    tree = ast.parse(source)
    _, string = _call_node(tree, name)
    lines = source.splitlines(keepends=True)
    ending = "\r\n" if "\r\n" in source else "\n"
    first_line = lines[string.lineno - 1]
    indent = re.match(r"\s*", first_line).group(0) if first_line[: string.col_offset].strip() == "" else "    "
    cut = len(lines[string.end_lineno - 1].encode("utf-8")[: string.end_col_offset].decode("utf-8"))
    last = lines[string.end_lineno - 1]
    lines[string.end_lineno - 1] = last[:cut] + ending + indent + 'r"|' + alternative + '"' + last[cut:]
    return "".join(lines)


def diff(old, new, relative):
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile="a/" + relative, tofile="b/" + relative))


def _verdicts(module, gate, texts):
    function = getattr(module, gate.function)
    return [bool(function(text)) for text in texts]


# ---- the search ----------------------------------------------------------------------------------------------------


def propose(root, gate, cases, background=()):
    """Search for patches. Never writes anything: returns a Result."""
    source = _load_source(root, gate.module)
    base = module_from_source(source, filename=gate.module)
    texts = [case.text for case in cases]
    before = _verdicts(base, gate, texts)
    result = Result(gate, cases=len(cases), added=sum(1 for c in cases if c.origin == "added"), background=len(background), right_before=sum(1 for c, v in zip(cases, before) if v == c.expected))
    background_before = _verdicts(base, gate, list(background))
    result.false_allowances = [c.text for c, v in zip(cases, before) if v and not c.expected]
    chosen = {}  # alternative -> Proposal
    for case, verdict in zip(cases, before):
        if verdict or not case.expected:
            continue
        best = None  # (newly matched, words, alternative, proposal)
        broke = None
        for alternative in alternatives(case.text):
            patched = add_alternative(source, gate.pattern, alternative)
            try:
                module = module_from_source(patched, filename=gate.module)
            except Exception:  # noqa: BLE001 -- a candidate that does not even compile is no candidate
                continue
            after = _verdicts(module, gate, texts)
            if any(a != c.expected and b == c.expected for a, b, c in zip(after, before, cases)):
                broke = broke or alternative
                continue
            newly = [m for m, b, a in zip(background, background_before, _verdicts(module, gate, list(background))) if a and not b]
            fixed = [c.text for c, a, b in zip(cases, after, before) if a == c.expected and b != c.expected]
            proposal = Proposal(alternative, fixed, newly, len(background), diff(source, patched, gate.module), patched)
            key = (len(newly), alternative.count(r"\s+"))
            if best is None or key < best[0]:
                best = (key, proposal)
        if best is None:
            result.no_safe_fix.append((case.text, broke, None))
        elif best[0][0] > MAX_NEW:
            result.no_safe_fix.append((case.text, best[1].alternative, best[0][0], best[1].newly_matched[:EXAMPLES]))
        else:
            chosen.setdefault(best[1].alternative, best[1])
    result.proposals = list(chosen.values())
    if len(result.proposals) > 1:
        patched = source
        for proposal in result.proposals:
            patched = add_alternative(patched, gate.pattern, proposal.alternative)
        module = module_from_source(patched, filename=gate.module)
        after = _verdicts(module, gate, texts)
        newly = [m for m, b, a in zip(background, background_before, _verdicts(module, gate, list(background))) if a and not b]
        if not any(a != c.expected and b == c.expected for a, b, c in zip(after, before, cases)):
            fixed = [c.text for c, a, b in zip(cases, after, before) if a == c.expected and b != c.expected]
            result.combined = Proposal(" + ".join(p.alternative for p in result.proposals), fixed, newly, len(background), diff(source, patched, gate.module), patched)
    return result


def pins(root, gate):
    """Where the tests (and the labelled file) name the lists of known misses: what has to change if a proposal is accepted."""
    names = {name for _, name, _, known_miss in gate.sources if known_miss}
    found = []
    for folder in ("tests",):
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        for filename in sorted(os.listdir(base)):
            if not filename.endswith(".py"):
                continue
            with open(os.path.join(base, filename), encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if any(name in line for name in names):
                        found.append(f"{folder}/{filename}:{number}")
    return found


def run_tests_on_copy(root, gate, source):
    """Run the gate's tests on a PRIVATE copy of the repository with the patched file in it. Returns (exit code, the last lines of output)."""
    ignore = shutil.ignore_patterns(".git", "node_modules", ".next", "__pycache__", "*.db", "knowledge", "advisor", "backups", "logs", ".pytest_cache", "*.pem", "*.key")
    with tempfile.TemporaryDirectory(prefix="diya-advisor-") as scratch:
        copy = os.path.join(scratch, "repo")
        shutil.copytree(root, copy, ignore=ignore)
        with open(os.path.join(copy, gate.module), "w", encoding="utf-8", newline="") as handle:
            handle.write(source)
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *gate.tests], cwd=copy, capture_output=True, text=True, timeout=900)
        return done.returncode, "\n".join((done.stdout + done.stderr).strip().splitlines()[-12:])


# ---- the report ----------------------------------------------------------------------------------------------------


def report_text(result, pinned, tests_ran=None):
    gate = result.gate
    out = [f"# Advisor report: the {gate.name} gate", "",
           f"Looked at {result.cases} cases ({result.cases - result.added} labelled, {result.added} you added) and {result.background} of your own past messages as the background. "
           f"The gate is right on {result.right_before} of {result.cases}.", ""]
    if not result.proposals and not result.no_safe_fix:
        out += ["Every request the gate is meant to catch is caught: nothing to propose.", ""]
    for number, proposal in enumerate(result.proposals, 1):
        out += [f"## Proposal {number}: add `{printable(proposal.alternative)}`", "",
                "Fixes: " + "; ".join(f"\"{printable(t, 80)}\"" for t in proposal.misses) + ".",
                "Breaks: none of the labelled cases.",
                f"Newly matches {len(proposal.newly_matched)} of {proposal.background_size} of your past messages"
                + (": " + "; ".join(f"\"{printable(m, 80)}\"" for m in proposal.newly_matched[:EXAMPLES]) if proposal.newly_matched else "") + ".",
                f"Patch: `proposal-{number}.patch` (changes {gate.module} only).", ""]
    if result.combined is not None:
        out += ["## All of them at once", "",
                f"`proposal-all.patch` adds all {len(result.proposals)}: it fixes {len(result.combined.misses)} case(s), breaks none of the labelled cases and newly matches {len(result.combined.newly_matched)} of {result.combined.background_size} past messages.", ""]
    if result.no_safe_fix:
        out += ["## No safe fix", ""]
        for item in result.no_safe_fix:
            miss, alternative = item[0], item[1]
            if len(item) == 2 or item[2] is None:
                out.append(f"- \"{printable(miss, 80)}\": every edit tried that fixes it breaks a labelled case" + (f" (for example `{printable(alternative)}`)." if alternative else "."))
            else:
                out.append(f"- \"{printable(miss, 80)}\": the best edit (`{printable(alternative)}`) would newly match {item[2]} of your past messages (more than {MAX_NEW}), for example "
                           + "; ".join(f"\"{printable(m, 80)}\"" for m in item[3]) + ".")
        out.append("")
    if result.false_allowances:
        out += ["## Not proposed for (the gate says yes to what is not a request: that needs a guard, not another phrase)", ""]
        out += [f"- \"{printable(t, 80)}\"" for t in result.false_allowances] + [""]
    if result.proposals:
        out += ["## If you accept a proposal", "",
                f"1. `git apply advisor/proposal-N.patch` (it changes {gate.module} only).",
                f"2. Move the cases it fixes from the list of known misses to the list they belong in ({', '.join(sorted({s[0] for s in gate.sources}))}), and update what the tests pin about them. These lines name the lists:", ""]
        out += [f"   - {line}" for line in pinned] + ["", "   Those tests pin the known misses on purpose, so a good fix fails them until you do: that is the proof they are watching.", ""]
    if tests_ran is not None:
        out += ["## The gate's tests on a private copy with the combined patch", "", "```"] + [printable(line) for line in tests_ran[1].splitlines()] + ["```", ""]
    return "\n".join(out) + "\n"


def write_outputs(directory, result, pinned, tests_ran=None):
    os.makedirs(directory, exist_ok=True)
    for name in os.listdir(directory):
        if re.fullmatch(r"proposal-(?:\d+|all)\.patch", name):
            os.remove(os.path.join(directory, name))  # patches from an earlier run are not this run's
    for number, proposal in enumerate(result.proposals, 1):
        with open(os.path.join(directory, f"proposal-{number}.patch"), "w", encoding="utf-8", newline="") as handle:
            handle.write(proposal.patch)
    if result.combined is not None:
        with open(os.path.join(directory, "proposal-all.patch"), "w", encoding="utf-8", newline="") as handle:
            handle.write(result.combined.patch)
    with open(os.path.join(directory, "report.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(report_text(result, pinned, tests_ran))


# ---- recording a miss ----------------------------------------------------------------------------------------------


def add_case(directory, gate, text, expected):
    """Record a message the gate got wrong; the next `propose` has to get it right too. Returns False if it was already there."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_CASE_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise AdvisorError(f"a message to record is one line of text of at most {MAX_CASE_CHARS} characters")
    text = " ".join(text.split())
    if any(c.text == text and c.expected == expected for c in added_cases(directory, gate)):
        return False
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "cases.jsonl"), "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"gate": gate.name, "text": text, "expected": expected}, ensure_ascii=False) + "\n")
    return True


# ---- the command line ----------------------------------------------------------------------------------------------


def main(argv=None, config=None, out=None, root=None, gates=None):
    out = out or sys.stdout
    config = config or diya_config.load_config()
    root = root or ROOT
    gates = gates or GATES
    parser = argparse.ArgumentParser(prog="diya_advisor.py", description="Proposes patches for a gate's misses and never applies one (docs/ADVISOR_DESIGN.md).")
    commands = parser.add_subparsers(dest="command", required=True)
    propose_parser = commands.add_parser("propose", help="search, then write the report and the patches")
    propose_parser.add_argument("--gate", choices=sorted(gates), default=sorted(gates)[0])
    propose_parser.add_argument("--db", help="the database whose messages are the background (default DIYA_DB_PATH)")
    propose_parser.add_argument("--run-tests", action="store_true", help="also run the gate's tests on a private copy with the combined patch")
    add_parser = commands.add_parser("add", help="record a message the gate got wrong")
    add_parser.add_argument("gate", choices=sorted(gates))
    add_parser.add_argument("text")
    add_parser.add_argument("answer", choices=("yes", "no"), help="yes: it IS what the gate looks for")
    commands.add_parser("list", help="the gates and their cases")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK
    directory = config.advisor_dir
    try:
        if args.command == "list":
            for name in sorted(gates):
                gate = gates[name]
                cases = _labelled(root, gate) + added_cases(directory, gate)
                print(f"{name}: {len(cases)} cases ({sum(1 for c in cases if c.known_miss)} known misses), in {gate.module} ({gate.function})", file=out)
        elif args.command == "add":
            gate = gates[args.gate]
            if add_case(directory, gate, args.text, args.answer == "yes"):
                print(f"Recorded. The next `propose` has to get it right too: {printable(args.text, 80)!r} is {'a request' if args.answer == 'yes' else 'not a request'}.", file=out)
            else:
                print("Already recorded.", file=out)
        else:
            gate = gates[args.gate]
            cases = _labelled(root, gate) + added_cases(directory, gate)
            background = background_messages(args.db or config.db_path)
            result = propose(root, gate, cases, background)
            tests_ran = None
            if args.run_tests and result.proposals:
                chosen = result.combined or result.proposals[0]
                tests_ran = run_tests_on_copy(root, gate, chosen.source)
            write_outputs(directory, result, pins(root, gate), tests_ran)
            print(f"The {gate.name} gate is right on {result.right_before} of {result.cases} cases; looked at {result.background} of your past messages as the background.", file=out)
            print(f"{len(result.proposals)} proposal(s), {len(result.no_safe_fix)} with no safe fix, {len(result.false_allowances)} false allowance(s) not proposed for.", file=out)
            print(f"Report and patches are in {printable(directory)}; nothing of Diya's was changed.", file=out)
    except AdvisorError as exc:
        print(f"Not done: {printable(str(exc))}", file=out)
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
