"""When does the model propose a Todoist task, and when does it do so unasked? (docs/ACTIONS_DESIGN.md, D6 and unit A4.)

A proposal is only ever recorded, never performed, so a wrong one costs the owner a card to turn down. But a small model
that proposes tasks nobody asked for would fill the Actions page with noise and teach the owner to click without
reading, so the rate matters, and it is measured here, not assumed: the same lesson as `add_reminder`, which the 3B
model called on plain arithmetic about half the time. Each labelled message (tests/labelled_task_requests.py) goes
through the real Agent and the real local model with the Todoist proposal tool offered, and the benchmark counts how
often the tool was reached for when it was asked for, and when it was not.

    python diya_actions_bench.py                      every labelled message once, against DIYA_MODEL (default qwen2.5:3b)
    python diya_actions_bench.py --runs 3             each message three times (a model's answer varies)
    python diya_actions_bench.py --model qwen3:8b --limit 20
    python diya_actions_bench.py --out results.json   also write every answer to a file
    python diya_actions_bench.py --guard-only         score diya_intent.is_task_request on the labelled messages, no model

Needs Ollama running (except with --guard-only). Everything else is contained: the tools that read (web, weather, notes,
files, the to-do list) are stubbed so nothing reaches the network, Todoist is "connected" with a made-up token that is
never used, and a proposal is only recorded, in a temporary database. Nothing here changes the live agent: like
`python diya_gate_bench.py`, this is a measurement, not a switch.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))

import diya
import diya_config
import diya_connectors
import diya_intent
from labelled_task_requests import AMBIGUOUS, ASKED, NOT_ASKED, all_not_asked

PROPOSE = "propose_todoist_task"
STUBS = {
    "web_search": lambda query="": "Top result: a page about " + str(query)[:40],
    "get_weather": lambda location="": "Sunny, 21 degrees",
    "search_notes": lambda query="": "A note about " + str(query)[:40],
    "list_files": lambda directory=".": "notes.txt, todo.txt",
    "list_reminders": lambda: "No pending reminders.",
    "list_todoist_tasks": lambda filter=None: "Buy milk (due today)\nCall the dentist",
}


def build_agent(model, workdir):
    """A real Agent on the real model, in a temporary folder, with Todoist 'connected' so its tools are offered."""
    config = dataclasses.replace(
        diya_config.load_config(),
        model=model,
        db_path=os.path.join(workdir, "bench.db"), profile_path=os.path.join(workdir, "profile.txt"),
        connector_tokens_dir=os.path.join(workdir, "tokens"), connectors_log_path=os.path.join(workdir, "connectors.log"),
    )
    diya_connectors.store_token(config, "todoist", "a-made-up-token-that-is-never-sent")
    agent = diya.Agent(config)
    for name, stub in STUBS.items():
        agent._functions[name] = stub
    reminders = []
    agent._functions["add_reminder"] = lambda content="", due_at=None: reminders.append(content) or f"Reminder saved: {content}"
    agent.bench_reminders = reminders
    return agent


def ask_once(agent, text):
    """Ask one message in a fresh turn. Returns what the model did: every tool it called, every attempt to propose (with
    the arguments it chose and what it was told back), and what was actually recorded."""
    attempts = []
    original = agent._functions[PROPOSE]

    def recording(**args):
        result = original(**args)
        attempts.append({"args": args, "result": result})
        return result

    agent._functions[PROPOSE] = recording
    agent.bench_reminders.clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # the tool loop prints each call; the benchmark prints its own report
            answer, tools = agent.ask([{"role": "user", "content": text}])
    finally:
        agent._functions[PROPOSE] = original
    recorded = [a["args"] for a in agent.actions.pending()]
    for action in agent.actions.pending():
        agent.actions.reject(action["id"], "cli")  # keep the queue empty so one message never crowds out the next
    return {"text": text, "tools": tools, "attempts": attempts, "recorded": recorded,
            "reminders": list(agent.bench_reminders), "answer": answer}


def proposed(result):
    return bool(result["attempts"])


def run_model(model, runs, limit):
    asked = ASKED[:limit] if limit else ASKED
    not_asked = {category: texts[:limit] if limit else texts for category, texts in NOT_ASKED.items()}
    results = {"model": model, "runs": runs, "asked": [], "not_asked": {c: [] for c in not_asked}, "ambiguous": []}
    started = time.time()
    with tempfile.TemporaryDirectory() as workdir:
        agent = build_agent(model, workdir)
        agent.warm_up = lambda: None  # the notes index is never used here: search_notes is stubbed
        for _ in range(runs):
            for text in asked:
                results["asked"].append(ask_once(agent, text))
            for category, texts in not_asked.items():
                for text in texts:
                    results["not_asked"][category].append(ask_once(agent, text))
            for text in ([] if limit else AMBIGUOUS):
                results["ambiguous"].append(ask_once(agent, text))
    results["seconds"] = round(time.time() - started)
    return results


def percent(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def report(results, out):
    asked = results["asked"]
    not_asked = [r for rs in results["not_asked"].values() for r in rs]
    print(f"Model {results['model']}: {len(asked)} asked, {len(not_asked)} not asked, {results['runs']} run(s) each, "
          f"{results['seconds']} s.", file=out)
    # Two different things: the model REACHING for the tool, and a proposal being RECORDED (what the owner would see). With
    # the checks in Agent._propose the second can be lower than the first; without them they are about the same.
    reached = [r for r in asked if proposed(r)]
    kept = [r for r in asked if r["recorded"]]
    print(f"\nAsked for a task:   the model reached for the tool in {len(reached)} of {len(asked)} "
          f"({percent(len(reached), len(asked))}); a proposal was recorded in {len(kept)} ({percent(len(kept), len(asked))})", file=out)
    for r in asked:
        if not r["recorded"]:
            print(f"  no proposal: {r['text']!r}  tools={r['tools']}  attempts={[a['result'][:60] for a in r['attempts']]}", file=out)
    false = [r for r in not_asked if proposed(r)]
    false_kept = [r for r in not_asked if r["recorded"]]
    print(f"Not asked:          the model reached for the tool in {len(false)} of {len(not_asked)} "
          f"({percent(len(false), len(not_asked))}); a proposal was recorded in {len(false_kept)} ({percent(len(false_kept), len(not_asked))})", file=out)
    for category, rs in results["not_asked"].items():
        print(f"  {category:<28} reached {sum(1 for r in rs if proposed(r))}, recorded {sum(1 for r in rs if r['recorded'])}, of {len(rs)}", file=out)
    for r in false:
        print(f"  unasked: {r['text']!r} -> recorded={bool(r['recorded'])} {[a['args'] for a in r['attempts']]}", file=out)
    # A due phrase the person never wrote is the same failure add_reminder had (a time the model made up): shown on the
    # card for the owner to see, but worth counting. "Verbatim" is a deliberate under-estimate of what is made up. Counted
    # on what was ATTEMPTED and on what was RECORDED, since the checks can take it out in between.
    def invented(rs, field):
        return [(r["text"], args["due_string"]) for r in rs for args in ([a["args"] for a in r["attempts"]] if field == "attempts" else r["recorded"])
                if args.get("due_string") and str(args["due_string"]).lower() not in r["text"].lower()]

    def given(rs, field):
        return sum(1 for r in rs for args in ([a["args"] for a in r["attempts"]] if field == "attempts" else r["recorded"]) if args.get("due_string"))

    everything = asked + not_asked
    arguments = [a for r in asked for a in r["attempts"]]
    print(f"\nDue phrases that are not the person's own words: {len(invented(everything, 'attempts'))} of "
          f"{given(everything, 'attempts')} the model gave; {len(invented(everything, 'recorded'))} of "
          f"{given(everything, 'recorded')} on a recorded proposal", file=out)
    for text, due in invented(everything, "attempts"):
        print(f"  {text!r} -> due {due!r}", file=out)
    if arguments:
        empty_due = sum(1 for a in arguments if "due_string" in a["args"] and not a["args"]["due_string"])
        extra = sum(1 for a in arguments if set(a["args"]) - {"content", "due_string"})
        refused = sum(1 for a in arguments if a["result"].startswith("Not proposed"))
        print(f"\nArguments the model chose when asked ({len(arguments)} attempts): a due phrase in "
              f"{sum(1 for a in arguments if a['args'].get('due_string'))}, empty or null due phrase in {empty_due}, "
              f"unknown arguments in {extra}, refused by the checks in {refused}", file=out)
        for a in arguments:
            if a["result"].startswith("Not proposed"):
                print(f"  refused: {a['args']} -> {a['result']}", file=out)
    reminders = sum(1 for r in not_asked if r["reminders"])
    print(f"(for reference: add_reminder was reached for on {reminders} of the not-asked messages)", file=out)
    if results["ambiguous"]:
        print("\nAmbiguous (not scored):", file=out)
        for r in results["ambiguous"]:
            print(f"  {'proposed' if proposed(r) else 'did not   '}  {r['text']!r}", file=out)


def score_guard(out):
    """The deterministic check, if there is one, on the labelled messages: no model involved."""
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
    print("Ambiguous (not scored):", file=out)
    for t in AMBIGUOUS:
        print(f"  {'allowed' if guard(t) else 'refused'}  {t!r}", file=out)
    return 0


def main(argv=None, out=None):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description="When does the model propose a Todoist task?")
    parser.add_argument("--model", default=None, help="the Ollama model (default: DIYA_MODEL)")
    parser.add_argument("--runs", type=int, default=1, help="how many times to ask each message")
    parser.add_argument("--limit", type=int, default=0, help="only the first N messages of each list (a quick look)")
    parser.add_argument("--out", default=None, help="also write every answer to this JSON file")
    parser.add_argument("--guard-only", action="store_true", help="score diya_intent.is_task_request, no model")
    args = parser.parse_args(argv)
    if args.guard_only:
        return score_guard(out)
    model = args.model or diya_config.load_config().model
    try:
        results = run_model(model, max(1, args.runs), args.limit)
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
