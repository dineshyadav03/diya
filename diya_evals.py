import dataclasses
import os
import sys
import tempfile

import diya
import diya_config

# The cases below were written against these fixture notes (a dentist note saying "Thursday
# at 3pm"), so they are pinned here rather than following DIYA_NOTES_DIR to real notes. The same
# folder doubles as the eval agent's only allowed list_files root (see make_eval_agent) -- pinned
# for the same reason: the file-listing case needs a folder with known, fixed contents, not
# whatever DIYA_FILES_ROOTS resolves to on the machine actually running the evals.
FIXTURE_NOTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_notes")

TEST_CASES = [
    {
        "name": "arithmetic -- should need no tool at all",
        "prompt": "What's 9 times 7?",
        "expected_tool": None,
        "expected_in_answer": ["63"],
    },
    {
        "name": "notes retrieval -- dentist appointment",
        "prompt": "What did I say about my dentist?",
        "expected_tool": "search_notes",
        "expected_in_answer": ["3pm", "thursday"],
    },
    {
        "name": "weather -- geocoding disambiguation regression check",
        "prompt": "What's the weather in Madras?",
        "expected_tool": "get_weather",
        "expected_in_answer": ["india", "tamil nadu", "chennai", "madras"],
        "forbidden_in_answer": ["oregon", "united states"],
    },
    {
        "name": "file listing",
        "prompt": "What files are in the current folder?",
        "expected_tool": "list_files",
        "expected_in_answer": ["dentist.txt"],
    },
    {
        "name": "add a reminder",
        "prompt": "Remind me to review the eval suite results.",
        "expected_tool": "add_reminder",
        "expected_in_answer": ["remind"],
    },
    {
        "name": "list reminders",
        "prompt": "What are my current reminders?",
        "expected_tool": "list_reminders",
        "expected_in_answer": [],
    },
    # Sharing a fact is not asking for anything: expect a one-sentence acknowledgement and no
    # tool at all (unprompted, the model saved a reminder or ran a web search and wrote
    # paragraphs). The prompts are fictional; they have the shape of a real exam-and-travel share.
    {
        "name": "fact-share -- exam and travel detail: short acknowledgement, no tool",
        "prompt": "My driving test is on October 12 from 9 to 10am and I take the train from Leeds to York for it.",
        "expected_tool": None,
        "expected_in_answer": ["october"],
        "max_words": 30,
    },
    {
        "name": "fact-share -- personal detail: short acknowledgement, no research",
        "prompt": "My sister Anna lives in Lisbon and her birthday is on March 3rd.",
        "expected_tool": None,
        "expected_in_answer": ["anna"],
        "max_words": 30,
    },
    # ...but a real question still gets a real answer, not a clipped one.
    {
        "name": "question -- still explained in full",
        "prompt": "Explain what a mortgage is.",
        "expected_tool": None,
        "expected_in_answer": ["mortgage"],
        "min_words": 30,
    },
]


class EvalIsolationError(RuntimeError):
    """The eval run was about to use Diya's live database."""


def _same_file(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def assert_isolated(agent):
    """Refuse to run against the database Diya actually uses. Evals write real reminders and
    (before this guard existed) left junk threads in the live diya.db."""
    live_paths = {diya_config.load_config().db_path, "diya.db"}
    for live in live_paths:
        if _same_file(agent.store.path, live):
            raise EvalIsolationError(
                f"refusing to run evals against the live database ({agent.store.path}); "
                "evals must use their own temporary storage"
            )


def make_eval_agent(workdir, client=None):
    """An Agent whose database lives in `workdir`. Model, embedding model and Ollama URL still
    follow DIYA_* settings (that's what is being evaluated); notes and the list_files root are
    the fixture set, not whatever DIYA_NOTES_DIR/DIYA_FILES_ROOTS resolve to on this machine."""
    config = dataclasses.replace(
        diya_config.load_config(),
        db_path=os.path.join(workdir, "evals.db"),
        notes_dir=FIXTURE_NOTES,
        files_roots=(FIXTURE_NOTES,),
    )
    agent = diya.Agent(config, client=client)
    assert_isolated(agent)
    return agent


def run_evals(agent, cases=TEST_CASES):
    assert_isolated(agent)
    passed = 0
    failed = 0

    for case in cases:
        history = [{"role": "user", "content": case["prompt"]}]

        try:
            answer, tools_called = agent.ask(history)
        except Exception as exc:
            print(f"[FAIL] {case['name']}: crashed with {exc}")
            failed += 1
            continue

        answer_lower = answer.lower()
        issues = []

        expected_tool = case.get("expected_tool")
        if expected_tool is None:
            if tools_called:
                issues.append(f"expected no tool call, but got {tools_called}")
        elif expected_tool not in tools_called:
            issues.append(f"expected '{expected_tool}' to be called, but got {tools_called}")

        expected_terms = case.get("expected_in_answer", [])
        if expected_terms and not any(t.lower() in answer_lower for t in expected_terms):
            issues.append(f"expected one of {expected_terms} in the answer -- got: {answer!r}")

        words = len(answer.split())
        max_words, min_words = case.get("max_words"), case.get("min_words")
        if max_words is not None and words > max_words:
            issues.append(f"expected at most {max_words} words, got {words}: {answer!r}")
        if min_words is not None and words < min_words:
            issues.append(f"expected at least {min_words} words, got {words}: {answer!r}")

        for term in case.get("forbidden_in_answer", []):
            if term.lower() in answer_lower:
                issues.append(f"found forbidden term '{term}' in the answer: {answer!r}")

        if issues:
            print(f"[FAIL] {case['name']}")
            for issue in issues:
                print(f"       - {issue}")
            failed += 1
        else:
            print(f"[PASS] {case['name']}")
            passed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


def _labelled_cases():
    """The hand-written, fictional cases in tests/labelled_facts.py, loaded by path (tests/ is not a package)."""
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "labelled_facts.py")
    spec = importlib.util.spec_from_file_location("labelled_facts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GROUNDING, module.VERIFIER_PROBES


def verifier_report(result, model, plain_flags):
    """The lines that say how the advisory verifier did. `result` is diya_verifier.measure()'s answer and
    `plain_flags` says, case by case, whether the plain-code grounding check flagged the fact."""
    rows = result["rows"]
    said = {(r["supported"], r["verdict"]): 0 for r in rows}
    for r in rows:
        said[(r["supported"], r["verdict"])] += 1
    unsupported = [(r, f) for r, f in zip(rows, plain_flags) if not r["supported"]]
    supported = [(r, f) for r, f in zip(rows, plain_flags) if r["supported"]]

    def count(pairs, test):
        return sum(1 for r, f in pairs if test(r, f))

    lines = [
        f"Advisory verifier ({model}) on {len(rows)} hand-written, fictional cases: {len(unsupported)} facts the messages do not "
        f"support, {len(supported)} they do. These cases are the numbers' whole basis: they are not real conversations.",
        f"  unsupported facts: verifier said no {said.get((False, 'no'), 0)} (caught), yes {said.get((False, 'yes'), 0)} (missed), "
        f"unclear {said.get((False, 'unclear'), 0)}",
        f"  supported facts:   verifier said yes {said.get((True, 'yes'), 0)}, no {said.get((True, 'no'), 0)} (false alarm), "
        f"unclear {said.get((True, 'unclear'), 0)}",
        f"  the plain-code check on the same cases: caught {count(unsupported, lambda r, f: f)} of {len(unsupported)}, "
        f"false alarms {count(supported, lambda r, f: f)} of {len(supported)}",
        f"  flagged by either (plain code, or the verifier saying no): caught "
        f"{count(unsupported, lambda r, f: f or r['verdict'] == 'no')} of {len(unsupported)}, false alarms "
        f"{count(supported, lambda r, f: f or r['verdict'] == 'no')} of {len(supported)}",
    ]
    limits = [(r, f) for r, f in zip(rows, plain_flags) if r["limit"]]
    if limits:
        lines.append("  the cases the plain-code check is known to get wrong (the verifier's chance to add something):")
        for r, f in limits:
            truth = "supported" if r["supported"] else "not supported"
            lines.append(f"    [{r['limit']}] {r['claim']!r} is {truth}: verifier said {r['verdict']}")
    return lines


def probe_report(result):
    """The lines for the harder probes (implied, steering, tricky). A verdict is right when it says yes for a
    supported fact and no for an unsupported one; `unclear` is never right."""
    lines = ["  harder probes (implied = true only by implication; steering = a message telling it what to say; tricky = negation, hearsay, a question):"]
    for kind in ("implied", "steering", "tricky"):
        rows = [r for r in result["rows"] if r["limit"] == kind]
        wrong = [r for r in rows if r["verdict"] != ("yes" if r["supported"] else "no")]
        lines.append(f"    {kind}: right on {len(rows) - len(wrong)} of {len(rows)}")
        for r in wrong:
            truth = "supported" if r["supported"] else "not supported"
            lines.append(f"      wrong: {r['claim']!r} is {truth}, verifier said {r['verdict']}")
    return lines


def measure_verifier(client=None, model=None, out=None):
    """`python diya_evals.py --verifier`: how good the advisory second opinion (diya_verifier.py) is, on the labelled
    fictional cases. Touches no database and no real message: only the fixture cases go to the model."""
    import diya_checks
    import diya_verifier

    out = sys.stdout if out is None else out
    config = diya_config.load_config()
    model = model or config.model
    if client is None:
        from openai import OpenAI

        client = OpenAI(base_url=config.ollama_url, api_key="ollama", timeout=120)
    cases, probes = _labelled_cases()
    plain_flags = [
        diya_checks.grounding(fact, list(enumerate(messages, 1)))[0] < diya_checks.GROUNDED_MIN for messages, fact, *_ in cases
    ]
    try:
        result = diya_verifier.measure(client, model, cases)
        probed = diya_verifier.measure(client, model, probes)
    except diya_verifier.ModelUnavailable as exc:
        print(f"Could not reach the model ({exc}). Is Ollama running, with {model} pulled?", file=out)
        return 2
    for line in verifier_report(result, model, plain_flags) + probe_report(probed):
        print(line, file=out)
    return 0


def main(client=None, argv=None):
    diya.configure_console()
    if "--verifier" in (sys.argv[1:] if argv is None else argv):
        return measure_verifier(client)
    with tempfile.TemporaryDirectory(prefix="diya-evals-", ignore_cleanup_errors=True) as workdir:
        agent = make_eval_agent(workdir, client)
        diya.warm_up_or_exit(agent)
        return 0 if run_evals(agent) else 1


if __name__ == "__main__":
    sys.exit(main())
