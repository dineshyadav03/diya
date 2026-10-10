"""What does the model do with a repeat? (docs/SCHEDULE_DESIGN.md, D7 and unit R3.)

`add_reminder(content, due_at, repeat)` makes a reminder repeat only if the person said how, and a repeat that was not said is
left out. The risk is the one reminders and tasks already showed: a small model makes something happen that was not asked
for ("every day" from a message that said it once), or loses what was asked ("every Monday" saved as a single reminder).
Each labelled message (tests/labelled_repeats.py) goes through the real Agent and the real local model, and the outcome is
scored by what was SAVED in the database, not by what the model said:

    python diya_schedule_bench.py                      every labelled message once, against DIYA_MODEL (default qwen2.5:3b)
    python diya_schedule_bench.py --runs 3             each message three times (a model's answer varies)
    python diya_schedule_bench.py --model qwen3:4b-instruct --limit 5
    python diya_schedule_bench.py --out results.json   also write every answer to a file, after EACH message
    python diya_schedule_bench.py --out results.json --resume   carry on after what an earlier, cut-off run saved there

Needs Ollama running. Everything else is contained: the tools that read (web, weather, notes, files) are stubbed so nothing
reaches the network, the reminders go to a temporary database, and they are cleared after each message. The results file is
rewritten after every message, so a run that is stopped (or outlives a background task's hour) keeps what it measured.
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
from labelled_repeats import NOT_A_REMINDER, ONE_OFF, REPEAT_ASKED, REPEAT_UNSUPPORTED

CATEGORIES = ("repeat asked", "repeat unsupported", "one-off", "not a reminder")
STUBS = {
    "web_search": lambda query="": "Top result: a page about " + str(query)[:40],
    "get_weather": lambda location="": "Sunny, 21 degrees",
    "search_notes": lambda query="": "A note about " + str(query)[:40],
    "list_files": lambda directory=".": "notes.txt, todo.txt",
}
# Does an answer say or imply that something repeats? A rough pattern on the words; the answers are in the --out file.
_SAYS_REPEATS = re.compile(r"\b(?:every|each|daily|weekly|monthly|repeat\w*|recurring|regularly)\b", re.IGNORECASE)


def messages():
    """[(category, text, expected rule or None)] in the order they are asked."""
    return ([("repeat asked", text, rule) for text, rule in REPEAT_ASKED]
            + [("repeat unsupported", text, None) for text in REPEAT_UNSUPPORTED]
            + [("one-off", text, None) for text in ONE_OFF]
            + [("not a reminder", text, None) for text in NOT_A_REMINDER])


def build_agent(model, workdir):
    """A real Agent on the real model, in a temporary folder, with the tools that reach outside stubbed."""
    config = dataclasses.replace(
        diya_config.load_config(), model=model,
        db_path=os.path.join(workdir, "bench.db"), profile_path=os.path.join(workdir, "profile.txt"),
        connector_tokens_dir=os.path.join(workdir, "tokens"), connectors_log_path=os.path.join(workdir, "connectors.log"),
    )
    agent = diya.Agent(config)
    for name, stub in STUBS.items():
        agent._functions[name] = stub
    agent.warm_up = lambda: None  # the notes index is never used here: search_notes is stubbed
    return agent


def saved_now(agent):
    """What is in the database now: the repeating reminders and the one-off reminders (those not made by a series)."""
    series = [{"content": s["content"], "rule": s["rule"].split("#")[0], "said": s["said"]} for s in agent.schedule.series("all")]
    made = agent.schedule.series_of([r["id"] for r in agent.store.reminders("all")])
    one_offs = [{"content": r["content"], "due_at": r["due_at"], "due_ts": r["due_ts"]} for r in agent.store.reminders("all") if r["id"] not in made]
    return series, one_offs


def clear(agent):
    conn = agent.store.connect()
    for table in ("reminders", "reminder_series", "schedule_events"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def ask_once(agent, category, text, expected):
    """Ask one message in a fresh turn and say what was saved. Every call the model made to add_reminder is kept, with the
    arguments it chose and what it was told back."""
    attempts = []
    original = agent._functions["add_reminder"]

    def recording(**args):
        result = original(**args)
        attempts.append({"args": args, "result": result})
        return result

    agent._functions["add_reminder"] = recording
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # the tool loop prints each call; the benchmark prints its own report
            answer, tools = agent.ask([{"role": "user", "content": text}])
        series, one_offs = saved_now(agent)
    finally:
        agent._functions["add_reminder"] = original
        clear(agent)
    return {"category": category, "text": text, "expected": expected, "tools": tools, "attempts": attempts,
            "series": series, "one_offs": one_offs, "answer": answer}


def outcome(result):
    """One word for what was saved: 'right rule', 'wrong rule', 'one-off', 'series' (a repeating reminder where there was no
    expected rule), or 'nothing'."""
    series, one_offs, expected = result["series"], result["one_offs"], result["expected"]
    if series:
        if expected is None:
            return "series"
        return "right rule" if any(s["rule"] == expected for s in series) else "wrong rule"
    return "one-off" if one_offs else "nothing"


def tried_to_repeat(result):
    """Did the model pass a repeat to add_reminder, whether or not it was kept?"""
    return any(a["args"].get("repeat") not in (None, "") for a in result["attempts"])


def run_model(model, runs, limit, out_path=None, resume=False):
    asked = messages()
    if limit:
        asked = [m for category in CATEGORIES for m in [x for x in asked if x[0] == category][:limit]]
    order = [m for _ in range(runs) for m in asked]
    results = {"model": model, "runs": runs, "results": [], "seconds": 0}
    if resume and out_path:
        earlier = load_checkpoint(out_path, model, runs)
        if earlier is None:
            print(f"diya_schedule_bench: nothing to resume from at {out_path}; starting from the first message", file=sys.stderr)
        elif not continues(earlier["results"], order):
            print(f"diya_schedule_bench: the answers saved at {out_path} are not from this list of messages; starting from the first", file=sys.stderr)
        else:
            results = {"model": model, "runs": runs, "results": list(earlier["results"]), "seconds": int(earlier.get("seconds") or 0)}
            print(f"diya_schedule_bench: resuming after {len(results['results'])} of {len(order)} answers", file=sys.stderr)
    started = time.time() - results["seconds"]
    with tempfile.TemporaryDirectory() as workdir:
        agent = build_agent(model, workdir)
        for category, text, expected in order[len(results["results"]):]:
            results["results"].append(ask_once(agent, category, text, expected))
            results["seconds"] = round(time.time() - started)
            if out_path and not write(out_path, results):
                print(f"diya_schedule_bench: could not update {out_path} (something has it open); the answers so far are in {out_path}.part and the run goes on", file=sys.stderr)
    results["seconds"] = round(time.time() - started)
    if out_path and not write(out_path, results):
        print(f"diya_schedule_bench: could not update {out_path} (something has it open); the complete answers are in {out_path}.part", file=sys.stderr)
    return results


def continues(saved, order):
    """Are `saved` answers the first ones of `order`, message for message? (Only then can a run carry on after them.)"""
    return len(saved) <= len(order) and all(
        isinstance(r, dict) and (r.get("category"), r.get("text")) == (category, text) for r, (category, text, _) in zip(saved, order))


def load_checkpoint(path, model, runs):
    """What an earlier run of this model and run count saved: the fullest of `path` and `path`.part (the swap that writes the
    first can be refused part way, leaving the newest answers only in the second), or None if neither can be used."""
    best = None
    for candidate in (path, path + ".part"):
        try:
            with open(candidate, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            continue
        usable = (isinstance(saved, dict) and saved.get("model") == model and saved.get("runs") == runs
                  and isinstance(saved.get("results"), list))
        if usable and (best is None or len(saved["results"]) > len(best["results"])):
            best = saved
    return best


def write(path, results, tries=5, pause=0.2):
    """Rewrite the results file in one step, so a reader never sees half a file. On Windows the swap is refused while anything
    has the old file open (a viewer, a virus scanner), so it is tried a few times. True once it went through; False if it still
    would not, with the complete answers in `path`.part, so a locked file never ends a half-hour measurement."""
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, indent=1)
    for attempt in range(tries):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            if attempt + 1 < tries:
                time.sleep(pause)
    return False


def percent(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def report(results, out):
    rs = results["results"]
    by = {category: [r for r in rs if r["category"] == category] for category in CATEGORIES}
    print(f"Model {results['model']}: {len(rs)} messages ({results['runs']} run(s) each), {results['seconds']} s "
          f"({results['seconds'] / len(rs):.1f} s per message).", file=out)

    asked = by["repeat asked"]
    counts = {name: sum(1 for r in asked if outcome(r) == name) for name in ("right rule", "wrong rule", "one-off", "nothing")}
    print(f"\nAsked for a repeating reminder ({len(asked)}): saved with the right rule {counts['right rule']} ({percent(counts['right rule'], len(asked))}), "
          f"with a wrong rule {counts['wrong rule']}, as a single reminder (the repeat lost) {counts['one-off']}, nothing {counts['nothing']}", file=out)
    for r in asked:
        if outcome(r) != "right rule":
            print(f"  {outcome(r):<10} {r['text']!r}  saved={[s['rule'] for s in r['series']] or [o['due_at'] for o in r['one_offs']]}  "
                  f"attempts={[a['args'] for a in r['attempts']]}", file=out)

    unsupported = by["repeat unsupported"]
    counts = {name: sum(1 for r in unsupported if outcome(r) == name) for name in ("series", "one-off", "nothing")}
    print(f"\nAsked for a repeat that cannot be read ({len(unsupported)}): saved as a repeating reminder {counts['series']} (should be 0), "
          f"as a single reminder with the repeat dropped {counts['one-off']}, nothing saved {counts['nothing']}", file=out)
    for r in unsupported:
        if outcome(r) != "nothing":
            print(f"  {outcome(r):<9} {r['text']!r}  saved={[s['rule'] for s in r['series']] or [o['due_at'] for o in r['one_offs']]}", file=out)
    dropped = [r for r in unsupported if outcome(r) == "one-off" and _SAYS_REPEATS.search(r["answer"])]
    if dropped:
        print(f"  of the single reminders, {len(dropped)} had an answer that sounds as if it repeats (a rough pattern match on the words)", file=out)

    one_off = by["one-off"]
    counts = {name: sum(1 for r in one_off if outcome(r) == name) for name in ("series", "one-off", "nothing")}
    print(f"\nAsked for a single reminder ({len(one_off)}): saved as one {counts['one-off']} ({percent(counts['one-off'], len(one_off))}), "
          f"saved as a repeating reminder {counts['series']} (should be 0), nothing {counts['nothing']}", file=out)
    for r in one_off:
        if outcome(r) == "series":
            print(f"  series {r['text']!r} -> {[s['rule'] for s in r['series']]}", file=out)

    other = by["not a reminder"]
    saved = [r for r in other if r["series"] or r["one_offs"]]
    print(f"\nNot asked for a reminder ({len(other)}): anything saved {len(saved)} (should be 0)", file=out)
    for r in saved:
        print(f"  saved {r['text']!r}", file=out)

    unasked = one_off + other
    tried = [r for r in unasked if tried_to_repeat(r)]
    kept = [r for r in tried if r["series"]]
    print(f"\nPassed a repeat when the message had none ({len(unasked)} messages): the model tried {len(tried)} times, "
          f"and {len(kept)} of those were kept as a repeating reminder (the guard drops a repeat the person did not say)", file=out)
    for r in tried:
        print(f"  {r['text']!r} -> repeat={[a['args'].get('repeat') for a in r['attempts']]}  kept={bool(r['series'])}", file=out)


def main(argv=None, out=None):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description="What does the model do with a repeat?")
    parser.add_argument("--model", default=None, help="the Ollama model (default: DIYA_MODEL)")
    parser.add_argument("--runs", type=int, default=1, help="how many times to ask each message")
    parser.add_argument("--limit", type=int, default=0, help="only the first N messages of each category (a quick look)")
    parser.add_argument("--out", default=None, help="also write every answer to this JSON file, after each message")
    parser.add_argument("--resume", action="store_true", help="carry on after the answers already saved in --out (same model, runs and messages)")
    args = parser.parse_args(argv)
    model = args.model or diya_config.load_config().model
    try:
        results = run_model(model, max(1, args.runs), args.limit, args.out, args.resume)
    except Exception as exc:  # Ollama not running, or the model not pulled
        print(f"diya_schedule_bench: could not run against {model}: {exc}", file=sys.stderr)
        return 2
    report(results, out)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
