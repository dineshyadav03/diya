"""Where does Diya's routing really stand? A held-out benchmark (docs/HELDOUT_BENCH.md; DIYA-191), added 2026-10-26.

    python diya_heldout_bench.py                         the held-out messages of tests/labelled_heldout.py against the configured chat model
    python diya_heldout_bench.py --model a,b             the same messages, tools and conditions for each model, then a comparison
    python diya_heldout_bench.py --runs 3 --out FILE     three trials of each message; every answer and tool call written to FILE after each message
    python diya_heldout_bench.py --category notes,task-unasked --limit 5      a quick look

Every other benchmark here was written by the author of the guard it measures; these messages were not tuned on, so this is the number that says how Diya does on messages nobody has looked at. The run is
the same for every model: the same prompts, the same tools, the same fixture notes, temperature 0 and one seed (`--seed`), and a throwaway database (the live one is refused, as in diya_evals.py). A message
passes only if ROUTING is right (the right tool, or none, none of the forbidden ones, the words that must be in the call) and the ANSWER is right (the words it must hold, the words it must not, its length); the
two are counted apart, because a model that routes well and answers badly needs a different fix. The report ends with every failure in full: the prompt, what was called, what was said and why it failed. Read
them: a label can be wrong, and a number that nobody has read the failures behind is not worth much.

Needs Ollama and the model. About two to three minutes for a small model on this laptop's processor, once the model is loaded (the first message waits for it). It touches none of your data.
Importing this module has no side effects.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time

import diya
import diya_config
import diya_evals

DEFAULT_SEED = 7
ROOT = os.path.dirname(os.path.abspath(__file__))


def load_cases(path=None):
    """The held-out cases, loaded by path (tests/ is not a package)."""
    path = path or os.path.join(ROOT, "tests", "labelled_heldout.py")
    spec = importlib.util.spec_from_file_location("labelled_heldout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CASES


def cases_hash(cases):
    """A short fingerprint of the cases, written into every result, so two runs can be compared only if they asked the same things."""
    return hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


class FixedConditions:
    """Wraps a model client so every request carries the same temperature and seed, whatever the agent would have asked for, and so one model can be compared with another."""

    def __init__(self, client, temperature=0.0, seed=DEFAULT_SEED):
        self._client, self.temperature, self.seed = client, temperature, seed
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        kwargs["temperature"] = self.temperature
        kwargs["seed"] = self.seed
        return self._client.chat.completions.create(**kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)


# What the model "knows about the user" in this benchmark: made up, never the owner's. The chat always puts the persona and this list in front of the model, and with them in front the small model answered
# "I don't have access to your notes" to 3 of 5 questions about the notes that it routed correctly without them (found 2026-10-26), so the benchmark is asked the way the chat asks.
PROFILE_LINES = ["Has a golden retriever named Rocky", "Plays the guitar", "Is studying AI at college", "Lives in Nellore", "Is allergic to peanuts"]


def make_agent(workdir, model, client):
    """An agent on a throwaway database with the fixture notes (as diya_evals makes it), the made-up profile, and `model`."""
    profile = os.path.join(workdir, "profile.txt")
    with open(profile, "w", encoding="utf-8", newline=chr(10)) as f:
        f.write(chr(10).join(PROFILE_LINES) + chr(10))
    config = dataclasses.replace(
        diya_config.load_config(), model=model, db_path=os.path.join(workdir, "heldout.db"), profile_path=profile, notes_dir=diya_evals.FIXTURE_NOTES, files_roots=(diya_evals.FIXTURE_NOTES,), auto_memory=False,
    )
    agent = diya.Agent(config, client=client)
    diya_evals.assert_isolated(agent)
    return agent


ROUTING_KEYS = ("tool", "forbidden", "args")


def grade(case, answer, tools, previews):
    """What was wrong, as [(kind, words)] where kind is "tool", "forbidden", "args" (routing) or "answer". `tools` is the names called; `previews` maps a name to the short text of the arguments of each call of it."""
    issues = []
    expected = case.get("tool")
    if expected is None:
        unexpected = [name for name in tools if name not in case.get("allowed_tools", [])]  # a read-only look that does no harm may be allowed by the case
        if unexpected:
            issues.append(("tool", f"expected no tool, got {tools}"))
    elif expected not in tools:
        issues.append(("tool", f"expected {expected}, got {tools or 'no tool'}"))
    for name in case.get("forbidden_tools", []):
        if name in tools:
            issues.append(("forbidden", f"{name} must not be called, and was"))
    if expected is not None and expected in tools:
        called = " | ".join(previews.get(expected, [])).lower()
        for term in case.get("args_have", []):
            if term.lower() not in called:
                issues.append(("args", f"the call should hold {term!r}: {called!r}"))
    text = (answer or "").lower()
    words = len((answer or "").split())
    wanted = case.get("answer_any", [])
    if wanted and not any(w.lower() in text for w in wanted):
        issues.append(("answer", f"expected one of {wanted} in the answer"))
    for term in case.get("answer_none", []):
        if term.lower() in text:
            issues.append(("answer", f"the answer must not hold {term!r}"))
    if case.get("max_words") is not None and words > case["max_words"]:
        issues.append(("answer", f"at most {case['max_words']} words, got {words}"))
    if case.get("min_words") is not None and words < case["min_words"]:
        issues.append(("answer", f"at least {case['min_words']} words, got {words}"))
    return issues


def run_case(agent, case):
    """One trial of one message: what the model did, what was called with what, and whether it passed."""
    before = max([e["id"] for e in agent.store.journal_recent(1)] or [0])
    started = time.monotonic()
    try:
        answer, tools = agent.ask(agent.with_profile([{"role": "user", "content": case["prompt"]}]))  # as the chat asks: the persona and what is known about the person in front
        crashed = None
    except Exception as exc:  # noqa: BLE001 -- a crash is a failure to report, not a reason to stop the run
        answer, tools, crashed = "", [], f"{type(exc).__name__}: {exc}"
    seconds = time.monotonic() - started
    previews = {}
    for entry in reversed(agent.store.journal_recent(40)):
        if entry["id"] > before and entry["kind"] in ("tool", "flow"):  # a search that code made (the notes) is a call too: its preview is what was searched for
            previews.setdefault(entry["tool"], []).append(entry["args_preview"] or "")
    issues = [("tool", f"crashed with {crashed}")] if crashed else grade(case, answer, list(tools), previews)
    return {
        "id": case["id"], "category": case["category"], "prompt": case["prompt"], "answer": answer, "tools": list(tools), "previews": previews, "seconds": round(seconds, 1),
        "issues": issues, "routing_ok": not any(kind in ROUTING_KEYS for kind, _ in issues), "answer_ok": not any(kind == "answer" for kind, _ in issues), "passed": not issues,
    }


def run(agent, cases, runs=1, say=print, save=None):
    records = []
    for trial in range(1, runs + 1):
        for case in cases:
            record = dict(run_case(agent, case), trial=trial)
            records.append(record)
            say(f"[{'PASS' if record['passed'] else 'FAIL'}] {case['id']} ({case['category']}) {record['seconds']} s: {case['prompt']!r}")
            if save:
                save(records)
    return records


def summarize(records):
    """{category: (passed, routing_ok, answer_ok, trials)} and the same for 'all'."""
    out = {}
    for record in records:
        for key in (record["category"], "all"):
            p, r, a, n = out.get(key, (0, 0, 0, 0))
            out[key] = (p + record["passed"], r + record["routing_ok"], a + record["answer_ok"], n + 1)
    return out


def render(model, records, settings):
    lines = [f"Held-out routing benchmark: {model}, cases {settings['cases_hash']}, {settings['runs']} trial(s) of each, temperature {settings['temperature']}, seed {settings['seed']}", ""]
    table = summarize(records)
    lines.append(f"{'category':<18}{'passed':>8}{'routing':>9}{'answer':>8}")
    for key in sorted(k for k in table if k != "all") + ["all"]:
        p, r, a, n = table[key]
        lines.append(f"{key:<18}{f'{p}/{n}':>8}{f'{r}/{n}':>9}{f'{a}/{n}':>8}")
    seconds = sorted(r["seconds"] for r in records)
    if seconds:
        lines.append(f"\nTime per message: half {seconds[len(seconds) // 2]} s, slowest {seconds[-1]} s.")
    failed = [r for r in records if not r["passed"]]
    lines.append(f"\n{len(failed)} failure(s). Read them: a label can be the mistake, and then the case is fixed here and said so in docs/HELDOUT_BENCH.md.")
    for r in failed:
        lines.append(f"\n  {r['id']} ({r['category']}, trial {r['trial']}): {r['prompt']!r}")
        lines.append(f"    called: {r['tools'] or 'nothing'}  {r['previews'] or ''}")
        lines.append(f"    said:   {r['answer'][:300]!r}")
        for kind, words in r["issues"]:
            lines.append(f"    - [{kind}] {words}")
    return "\n".join(lines)


def main(argv=None, client_factory=None, say=print, warm=True):
    parser = argparse.ArgumentParser(prog="diya_heldout_bench.py", description="Held-out routing benchmark.")
    parser.add_argument("--model", default=None, help="the Ollama model, or several separated by commas (default: DIYA_MODEL)")
    parser.add_argument("--runs", type=int, default=1, help="how many times to ask each message")
    parser.add_argument("--limit", type=int, default=0, help="only the first N messages of each category")
    parser.add_argument("--category", default="", help="only these categories, comma-separated")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", default=None, help="write every answer to this JSON file, after each message")
    args = parser.parse_args(argv)
    diya.configure_console()
    cases = load_cases()
    if args.category:
        wanted = {c.strip() for c in args.category.split(",") if c.strip()}
        cases = [c for c in cases if c["category"] in wanted]
    if args.limit:
        kept, seen = [], {}
        for case in cases:
            seen[case["category"]] = seen.get(case["category"], 0) + 1
            if seen[case["category"]] <= args.limit:
                kept.append(case)
        cases = kept
    models = [m.strip() for m in (args.model or diya_config.load_config().model).split(",") if m.strip()]
    settings = {"cases_hash": cases_hash(cases), "runs": args.runs, "temperature": args.temperature, "seed": args.seed, "cases": len(cases)}
    results = {}
    for model in models:
        base = diya_config.load_config()
        if client_factory is not None:
            client = client_factory(model)
        else:
            from openai import OpenAI

            client = FixedConditions(OpenAI(base_url=base.ollama_url, api_key="ollama"), args.temperature, args.seed)
        with tempfile.TemporaryDirectory(prefix="diya-heldout-", ignore_cleanup_errors=True) as workdir:
            agent = make_agent(workdir, model, client)
            if warm:
                diya.warm_up_or_exit(agent)

            def save(records, model=model):
                if args.out:
                    with open(args.out, "w", encoding="utf-8") as handle:
                        json.dump({"settings": settings, "results": {**{m: r for m, r in results.items()}, model: records}}, handle, ensure_ascii=False, indent=1)

            say(f"== {model}: {len(cases)} messages x {args.runs}")
            results[model] = run(agent, cases, args.runs, say, save)
        say("\n" + render(model, results[model], settings) + "\n")
    if len(models) > 1:
        say("Comparison (same messages, tools and conditions):")
        for model in models:
            p, r, a, n = summarize(results[model])["all"]
            say(f"  {model:<32} passed {p}/{n}  routing {r}/{n}  answer {a}/{n}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"settings": settings, "results": results}, handle, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
