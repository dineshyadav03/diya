"""When does the model add a task, and when does it do so unasked? (docs/ACTIONS_DESIGN.md, D6 and unit A4;
docs/TASKS_DESIGN.md, unit T1.)

Two tools can take a task: `add_task` saves it on Diya's own to-do list at once, and `propose_todoist_task` (only while
Todoist is connected) records a proposal for the owner to approve. A message that names Todoist is Todoist's, any other is
the list's (docs/TASKS_DESIGN.md, D6). A wrong one costs a stray line on the list or a card to turn down, but a small model
that adds tasks nobody asked for fills both with noise, so the rate matters and is measured here, not assumed: the same
lesson as `add_reminder`, which the 3B model called on plain arithmetic about half the time. Each labelled message
(tests/labelled_task_requests.py) goes through the real Agent and the real local model with the tools offered as they are
in real use, and the benchmark counts how often a task tool was reached for when a task was asked for, and when it was not,
and whether what was recorded landed in the right place.

    python diya_actions_bench.py                      every labelled message once, against DIYA_MODEL (default qwen2.5:3b)
    python diya_actions_bench.py --todoist            ...with Todoist "connected", so both tools are offered
    python diya_actions_bench.py --runs 3             each message three times (a model's answer varies)
    python diya_actions_bench.py --model qwen3:8b --limit 20
    python diya_actions_bench.py --out results.json   also write every answer to a file
    python diya_actions_bench.py --guard-only         score the two checks on the labelled messages, no model

Needs Ollama running (except with --guard-only). Everything else is contained: the tools that read (web, weather, notes,
files, Todoist) are stubbed so nothing reaches the network, Todoist is "connected" only with --todoist and then with a
made-up token that is never used, and tasks and proposals go to a temporary database and are cleared after each message.
Nothing here changes the live agent: like `python diya_gate_bench.py`, this is a measurement, not a switch.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))

import diya
import diya_config
import diya_connectors
import diya_intent
from labelled_task_requests import AMBIGUOUS, ASKED, NOT_ASKED, all_not_asked

LIST_TOOL = "add_task"
TODOIST_TOOL = "propose_todoist_task"
PROPOSE = TODOIST_TOOL  # what this benchmark measured before the list existed
WHERE = {LIST_TOOL: "list", TODOIST_TOOL: "todoist"}  # the tool a task is taken by -> where it ends up
DUE_FIELD = {LIST_TOOL: "due", TODOIST_TOOL: "due_string"}  # what each calls "when it is due"
REFUSED = ("Not added", "Not proposed")  # how either tool starts an answer that took nothing
STUBS = {
    "web_search": lambda query="": "Top result: a page about " + str(query)[:40],
    "get_weather": lambda location="": "Sunny, 21 degrees",
    "search_notes": lambda query="": "A note about " + str(query)[:40],
    "list_files": lambda directory=".": "notes.txt, todo.txt",
    "list_reminders": lambda: "No pending reminders.",
    "list_todoist_tasks": lambda filter=None: "Buy milk (due today)\nCall the dentist",
}
READERS = ("list_tasks", "list_reminders", "list_todoist_tasks")


def build_agent(model, workdir, todoist=False):
    """A real Agent on the real model, in a temporary folder, with Todoist 'connected' (a made-up token) only if asked."""
    config = dataclasses.replace(
        diya_config.load_config(),
        model=model,
        db_path=os.path.join(workdir, "bench.db"), profile_path=os.path.join(workdir, "profile.txt"),
        connector_tokens_dir=os.path.join(workdir, "tokens"), connectors_log_path=os.path.join(workdir, "connectors.log"),
    )
    if todoist:
        diya_connectors.store_token(config, "todoist", "a-made-up-token-that-is-never-sent")
    agent = diya.Agent(config)
    for name, stub in STUBS.items():
        agent._functions[name] = stub
    reminders = []
    agent._functions["add_reminder"] = lambda content="", due_at=None: reminders.append(content) or f"Reminder saved: {content}"
    agent.bench_reminders = reminders
    return agent


def expected_where(text, todoist):
    """Where a task asked for in `text` should end up: Todoist if it names Todoist and Todoist is connected, nowhere if it
    names Todoist and is not (the model should say so), the list otherwise."""
    if diya_intent.names_todoist(text):
        return "todoist" if todoist else None
    return "list"


def ask_once(agent, text):
    """Ask one message in a fresh turn. Returns what the model did: every tool it called, every attempt to add a task (the
    tool, the arguments it chose, what it was told back), what was actually recorded and where, and which of the tools that
    read a list it used."""
    attempts = []
    originals = {name: agent._functions[name] for name in WHERE if name in agent._functions}

    def recording(name):
        def call(**args):
            result = originals[name](**args)
            attempts.append({"tool": name, "args": args, "result": result})
            return result
        return call

    for name in originals:
        agent._functions[name] = recording(name)
    agent.bench_reminders.clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # the tool loop prints each call; the benchmark prints its own report
            answer, tools = agent.ask([{"role": "user", "content": text}])
    finally:
        agent._functions.update(originals)
    recorded = []
    for task in agent.tasks.tasks("open"):
        recorded.append({"where": "list", "args": {"content": task["content"], **({"due": task["due_at"]} if task["due_at"] else {})}})
        agent.tasks.complete(task["id"])  # so the next message may add the same words: a copy is refused while one is open
    for action in agent.actions.pending():
        recorded.append({"where": "todoist", "args": dict(action["args"])})
        agent.actions.reject(action["id"], "cli")  # keep the queue empty so one message never crowds out the next
    return {"text": text, "tools": tools, "attempts": attempts, "recorded": recorded,
            "reminders": list(agent.bench_reminders), "answer": answer}


def proposed(result):
    """Did the model reach for a task tool at all (whatever came of it)?"""
    return bool(result["attempts"])


def run_model(model, runs, limit, todoist=False, categories=None):
    """Ask the labelled messages. `categories`, if given, names the not-asked categories to ask INSTEAD of everything: a
    targeted look (the asked and the ambiguous messages are skipped)."""
    asked = [] if categories else (ASKED[:limit] if limit else ASKED)
    not_asked = {category: texts[:limit] if limit else texts for category, texts in NOT_ASKED.items() if not categories or category in categories}
    results = {"model": model, "runs": runs, "todoist": bool(todoist), "asked": [], "not_asked": {c: [] for c in not_asked}, "ambiguous": []}
    started = time.time()
    with tempfile.TemporaryDirectory() as workdir:
        agent = build_agent(model, workdir, todoist)
        agent.warm_up = lambda: None  # the notes index is never used here: search_notes is stubbed
        for _ in range(runs):
            for text in asked:
                results["asked"].append(ask_once(agent, text))
            for category, texts in not_asked.items():
                for text in texts:
                    results["not_asked"][category].append(ask_once(agent, text))
            for text in ([] if limit or categories else AMBIGUOUS):
                results["ambiguous"].append(ask_once(agent, text))
    results["seconds"] = round(time.time() - started)
    return results


def percent(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


# Does an answer say a task was added, or will be? A rough reading of the words (a pattern, not understanding), kept because the
# failure it counts is real: after the tool refused ("NOTHING was added"), the 3B model sometimes still told the person it had
# added the task. A sentence counts if it says "I added/created/saved/put ..." or "I will add ..." about a task or the to-do list and
# does not say not/never/no/n't.
_CLAIM = re.compile(
    r"\bi(?:'ve|\s+have)?\s+(?:just\s+|also\s+)?(?:added|created|saved|put)\b"
    r"|\bi(?:'ll|\s+will)\s+(?:also\s+)?(?:add|create|save|put)\b"
    r"|\b(?:has|have)\s+been\s+added\b",
    re.IGNORECASE,
)
_TASK_WORD = re.compile(r"\b(?:tasks?|to-?do)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not|never|no)\b|n't", re.IGNORECASE)


def claims_added(answer):
    if not isinstance(answer, str):
        return False
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer.replace(chr(0x2019), "'")):
        if _TASK_WORD.search(sentence) and _CLAIM.search(sentence) and not _NEGATION.search(sentence):
            return True
    return False


def places(result):
    return [r["where"] for r in result["recorded"]]


def report(results, out):
    todoist = bool(results.get("todoist"))
    asked = results["asked"]
    not_asked = [r for rs in results["not_asked"].values() for r in rs]
    print(f"Model {results['model']}: {len(asked)} asked, {len(not_asked)} not asked, {results['runs']} run(s) each, "
          f"{results['seconds']} s. Todoist {'connected' if todoist else 'not connected'}.", file=out)
    # Two different things: the model REACHING for a task tool, and a task being RECORDED (what the owner would see). With
    # the checks in the tools the second can be lower than the first; without them they are about the same.
    reached = [r for r in asked if proposed(r)]
    kept = [r for r in asked if r["recorded"]]
    print(f"\nAsked for a task:   the model reached for a task tool in {len(reached)} of {len(asked)} "
          f"({percent(len(reached), len(asked))}); a task was recorded in {len(kept)} ({percent(len(kept), len(asked))})", file=out)
    # ...and recorded in the right place: asked for in Todoist -> Todoist (or nowhere if it is not connected), otherwise the list
    for destination, label in (("list", "for the to-do list"), ("todoist", "naming Todoist, connected"), (None, "naming Todoist, not connected")):
        group = [r for r in asked if expected_where(r["text"], todoist) == destination]
        if not group:
            continue
        right = [r for r in group if places(r) == ([destination] if destination else [])]
        print(f"  {label:<31}  recorded in the right place in {len(right)} of {len(group)} ({percent(len(right), len(group))})", file=out)
    for r in asked:
        if places(r) != ([expected_where(r["text"], todoist)] if expected_where(r["text"], todoist) else []):
            print(f"  not as expected: {r['text']!r}  tools={r['tools']}  recorded={places(r)}  "
                  f"attempts={[a['result'][:60] for a in r['attempts']]}", file=out)
    false = [r for r in not_asked if proposed(r)]
    false_kept = [r for r in not_asked if r["recorded"]]
    print(f"Not asked:          the model reached for a task tool in {len(false)} of {len(not_asked)} "
          f"({percent(len(false), len(not_asked))}); a task was recorded in {len(false_kept)} ({percent(len(false_kept), len(not_asked))})", file=out)
    for category, rs in results["not_asked"].items():
        print(f"  {category:<28} reached {sum(1 for r in rs if proposed(r))}, recorded {sum(1 for r in rs if r['recorded'])}, of {len(rs)}", file=out)
    for r in false:
        print(f"  unasked: {r['text']!r} -> recorded={bool(r['recorded'])} {[a['args'] for a in r['attempts']]}", file=out)
    # A due phrase the person never wrote is the same failure add_reminder had (a time the model made up): shown on the
    # card or the list for the owner to see, but worth counting. "Verbatim" is a deliberate under-estimate of what is made up.
    # Counted on what was ATTEMPTED and on what was RECORDED, since the checks can take it out in between.
    def phrases(rs, field):
        found = []
        for r in rs:
            for attempt in (r["attempts"] if field == "attempts" else r["recorded"]):
                tool = attempt["tool"] if field == "attempts" else (LIST_TOOL if attempt["where"] == "list" else TODOIST_TOOL)
                due = attempt["args"].get(DUE_FIELD[tool])
                if due:
                    found.append((r["text"], due))
        return found

    def invented(rs, field):
        return [(text, due) for text, due in phrases(rs, field) if str(due).lower() not in text.lower()]

    everything = asked + not_asked
    arguments = [a for r in asked for a in r["attempts"]]
    print(f"\nDue phrases that are not the person's own words: {len(invented(everything, 'attempts'))} of "
          f"{len(phrases(everything, 'attempts'))} the model gave; {len(invented(everything, 'recorded'))} of "
          f"{len(phrases(everything, 'recorded'))} on a recorded task", file=out)
    for text, due in invented(everything, "attempts"):
        print(f"  {text!r} -> due {due!r}", file=out)
    if arguments:
        def due_of(a):
            return a["args"].get(DUE_FIELD[a["tool"]])

        empty_due = sum(1 for a in arguments if DUE_FIELD[a["tool"]] in a["args"] and not due_of(a))
        extra = sum(1 for a in arguments if set(a["args"]) - {"content", DUE_FIELD[a["tool"]]})
        refused = sum(1 for a in arguments if a["result"].startswith(REFUSED))
        print(f"\nArguments the model chose when asked ({len(arguments)} attempts): a due phrase in "
              f"{sum(1 for a in arguments if due_of(a))}, empty or null due phrase in {empty_due}, "
              f"unknown arguments in {extra}, refused by the checks in {refused}", file=out)
        for a in arguments:
            if a["result"].startswith(REFUSED):
                print(f"  refused: {a['args']} -> {a['result']}", file=out)
    # What the person would be told: an answer that says a task was (or will be) added when none was recorded is a lie on a list
    # they trust, even though the list itself is right. Counted on every message where nothing was recorded.
    said = [r for r in everything if not r["recorded"] and claims_added(r["answer"])]
    print(f"\nSaid a task was or would be added when none was recorded: {len(said)} of {len([r for r in everything if not r['recorded']])} "
          "(a rough pattern match on the answers, which --out keeps)", file=out)
    for r in said:
        print(f"  said so: {r['text']!r} -> {r['answer'][:120]!r}", file=out)
    # Which tool it read a list with, when asked what is on one: the reminders tool's own description says "whatever they need to do".
    readers = list(results["not_asked"].get("reading the list", []))
    if readers:
        used = {name: sum(1 for r in readers if name in r["tools"]) for name in READERS}
        print(f"\nAsked to read a list ({len(readers)} messages): " + ", ".join(f"{name} in {n}" for name, n in used.items())
              + f", none of them in {sum(1 for r in readers if not any(n in r['tools'] for n in READERS))}", file=out)
    reminders = sum(1 for r in not_asked if r["reminders"])
    print(f"(for reference: add_reminder was reached for on {reminders} of the not-asked messages)", file=out)
    if results["ambiguous"]:
        print("\nAmbiguous (not scored):", file=out)
        for r in results["ambiguous"]:
            print(f"  {'proposed' if proposed(r) else 'did not   '}  {r['text']!r}", file=out)


def score_guard(out):
    """The deterministic checks, if there are any, on the labelled messages: no model involved."""
    guard = getattr(diya_intent, "is_task_request", None)
    if guard is None:
        print("There is no diya_intent.is_task_request yet.", file=out)
        return 1
    allowed = [t for t in ASKED if guard(t)]
    wrongly = [t for t in all_not_asked() if guard(t)]
    print(f"Asked for a task:   allowed {len(allowed)} of {len(ASKED)} ({percent(len(allowed), len(ASKED))})", file=out)
    for t in ASKED:
        if not guard(t):
            print(f"  refused: {t!r}", file=out)
    total = len(all_not_asked())
    print(f"Not asked:          allowed {len(wrongly)} of {total} ({percent(len(wrongly), total)})", file=out)
    for t in wrongly:
        print(f"  allowed: {t!r}", file=out)
    named = [t for t in ASKED if diya_intent.names_todoist(t)]
    todoists = [t for t in ASKED if diya_intent.is_todoist_task_request(t)]
    todoists_unasked = [t for t in all_not_asked() if diya_intent.is_todoist_task_request(t)]
    print(f"Which list:         {len(todoists)} of the {len(ASKED)} asked go to Todoist ({len(named)} name it); "
          f"{len(todoists_unasked)} of the {total} not asked do", file=out)
    print("Ambiguous (not scored):", file=out)
    for t in AMBIGUOUS:
        print(f"  {'allowed' if guard(t) else 'refused'}  {t!r}", file=out)
    return 0


def main(argv=None, out=None):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description="When does the model add a task?")
    parser.add_argument("--model", default=None, help="the Ollama model (default: DIYA_MODEL)")
    parser.add_argument("--runs", type=int, default=1, help="how many times to ask each message")
    parser.add_argument("--limit", type=int, default=0, help="only the first N messages of each list (a quick look)")
    parser.add_argument("--categories", default=None, help="only these not-asked categories, comma-separated (a targeted look: no asked or ambiguous messages)")
    parser.add_argument("--todoist", action="store_true", help="act as if Todoist were connected (a made-up token, never used)")
    parser.add_argument("--out", default=None, help="also write every answer to this JSON file")
    parser.add_argument("--guard-only", action="store_true", help="score the checks in diya_intent, no model")
    args = parser.parse_args(argv)
    if args.guard_only:
        return score_guard(out)
    model = args.model or diya_config.load_config().model
    categories = [c.strip() for c in args.categories.split(",") if c.strip()] if args.categories else None
    unknown = [c for c in categories or [] if c not in NOT_ASKED]
    if unknown:
        print(f"diya_actions_bench: no such category {unknown[0]!r}; the categories are: {', '.join(NOT_ASKED)}", file=sys.stderr)
        return 2
    try:
        results = run_model(model, max(1, args.runs), args.limit, args.todoist, categories)
    except Exception as exc:  # Ollama not running, or the model not pulled
        print(f"diya_actions_bench: could not run against {model}: {exc}", file=sys.stderr)
        return 2
    report(results, out)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
