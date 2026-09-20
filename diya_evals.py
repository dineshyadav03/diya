import diya

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
        "prompt": "What's the weather in Bangalore?",
        "expected_tool": "get_weather",
        "expected_in_answer": ["india", "karnataka", "bengaluru", "bangalore"],
        "forbidden_in_answer": ["pakistan", "sindh"],
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
]


def run_evals():
    passed = 0
    failed = 0

    for case in TEST_CASES:
        thread_id = diya.diya_db.create_thread(title=f"eval: {case['name']}")
        history = [{"role": "user", "content": case["prompt"]}]

        try:
            answer, tools_called = diya.ask(history)
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


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_evals() else 1)
