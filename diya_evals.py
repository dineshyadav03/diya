import dataclasses
import os
import sys
import tempfile

import diya
import diya_config

# The cases below were written against these fixture notes (a dentist note saying "Thursday
# at 3pm"), so they are pinned here rather than following DIYA_NOTES_DIR to real notes.
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
        "prompt": "What files are in this project?",
        "expected_tool": "list_files",
        "expected_in_answer": ["diya.py"],
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
    follow DIYA_* settings (that's what is being evaluated); notes are the fixture set."""
    config = dataclasses.replace(
        diya_config.load_config(),
        db_path=os.path.join(workdir, "evals.db"),
        notes_dir=FIXTURE_NOTES,
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


def main(client=None):
    diya.configure_console()
    with tempfile.TemporaryDirectory(prefix="diya-evals-", ignore_cleanup_errors=True) as workdir:
        agent = make_eval_agent(workdir, client)
        diya.warm_up_or_exit(agent)
        return 0 if run_evals(agent) else 1


if __name__ == "__main__":
    sys.exit(main())
