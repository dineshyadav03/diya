"""Are Diya's replies short and plain, like Hark's? A reply-style benchmark (docs/STYLE_BENCH.md), added 2026-10-26 when the owner put Diya's replies beside Hark's.

    python diya_style_bench.py                       every message, every mode, against the configured chat model
    python diya_style_bench.py --split held-out      only the messages that were never tuned on
    python diya_style_bench.py --modes before,persona --out FILE

The same twenty-four ordinary messages (tests/labelled_style.py: a fact, a tip, an explanation, a little chat, the weather) are put to the real model with a made-up profile of the person ("has a golden retriever
named Rocky", "plays the guitar", ...), through the same path a chat uses (the persona and the profile in front, temperature 0 and one seed, so that two modes differ only in what is being compared). Each reply is
checked for what the owner saw in Hark's and not in Diya's: too long for what was asked, a picture, a closing offer ("want me to ...?", "let me know ..."), a P.S., praise or "you're right" at the start, a heading,
and, most of all, something from the profile brought up when the message was not about it. A reply is CLEAN only if none of those is found.

Modes: `before` is the persona as it was until 2026-10-26 with no tidy; `rules` adds the style rules to the persona; `reminder` adds, after the list of what is known about the person, the reminder that it is only
background; `shipped` is all of that and diya_intent.tidy_reply (what the person reads: it takes out only pictures, a closing offer, a P.S. and an opening praise). Needs Ollama and the model; about four minutes a mode on this laptop. It touches none of your data.
Importing this module has no side effects.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import importlib.util
import io
import json
import os
import statistics
import sys
import tempfile
import time

import diya
import diya_config
import diya_evals
import diya_intent
from diya_heldout_bench import DEFAULT_SEED, FixedConditions

ROOT = os.path.dirname(os.path.abspath(__file__))
# The persona as it was before the style rules (2026-10-11 to 2026-10-26), kept here so that "before" can be measured again whenever it is wanted.
BEFORE_PERSONA = (
    "You are Diya, the user's private assistant, running on their own computer as a small open-source model. Talk like a warm, sharp friend: natural, brief, in your own words, never stiff or "
    "corporate (never say \"How can I assist you today\"). You can talk about anything, not only their tasks: general knowledge, explanations, writing, code, study help, advice. Answer from what "
    "you know. You are much smaller than cloud models like Claude Opus or GPT, so say so honestly when asked, and say you are unsure rather than guess. Use what you know about the user below, "
    "and never make up facts about them or their day. Never describe yourself as built only for tasks, reminders or exams."
)
MODES = ("before", "rules", "reminder", "shipped")
WEATHER = "27.3 degrees C, overcast, light wind of 12 km/h, humidity 70 percent"


def load_cases(path=None):
    """The messages, the profile and the profile's tell-tale words, loaded by path (tests/ is not a package)."""
    path = path or os.path.join(ROOT, "tests", "labelled_style.py")
    spec = importlib.util.spec_from_file_location("labelled_style", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CASES, module.PROFILE_LINES, module.PROFILE_WORDS


def grade(case, reply, profile_words):
    """What is wrong with this reply, as [(kind, words)]: length, picture, offer, postscript, filler, heading, volunteered."""
    issues = []
    text = reply if isinstance(reply, str) else ""
    words = len(text.split())
    if words > case["max_words"]:
        issues.append(("length", f"{words} words, at most {case['max_words']} for a {case['kind']}"))
    if diya_intent.EMOJI.search(text):
        issues.append(("picture", "has an emoji"))
    if diya_intent.ends_with_an_offer(text):
        issues.append(("offer", "ends by offering more help"))
    if diya_intent.has_a_postscript(text):
        issues.append(("postscript", "has a P.S."))
    if diya_intent.starts_with_filler(text):
        issues.append(("filler", "opens with praise or agreement"))
    if any(line.lstrip().startswith("#") for line in text.splitlines()):
        issues.append(("heading", "has a heading"))
    low, prompt = text.lower(), case["prompt"].lower()
    allowed = [a.lower() for a in case.get("allowed_facts", [])]
    for word, what in profile_words.items():
        if word in low and word not in prompt and not any(a in word for a in allowed):
            issues.append(("volunteered", f"brings up {what} ({word!r}) when asked about something else"))
            break
    return issues


def make_agent(workdir, model, client, profile_lines):
    """An agent on a throwaway database whose 'what you know about the user' is the made-up profile, with the weather given a fixed answer."""
    profile = os.path.join(workdir, "profile.txt")
    with open(profile, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(profile_lines) + "\n")
    config = dataclasses.replace(diya_config.load_config(), model=model, db_path=os.path.join(workdir, "style.db"), profile_path=profile, notes_dir=diya_evals.FIXTURE_NOTES, files_roots=(diya_evals.FIXTURE_NOTES,), auto_memory=False)
    agent = diya.Agent(config, client=client)
    diya_evals.assert_isolated(agent)
    agent._functions["get_weather"] = lambda location="": f"{location}: {WEATHER}"
    return agent


@contextlib.contextmanager
def mode_settings(mode):
    """The persona and the tidy as the mode wants them, put back afterwards."""
    persona, tidy, reminder = diya.PERSONA, diya.TIDY_REPLIES, diya.PROFILE_REMINDER
    try:
        diya.PERSONA = BEFORE_PERSONA if mode == "before" else persona
        diya.PROFILE_REMINDER = reminder if mode in ("reminder", "shipped") else ""
        diya.TIDY_REPLIES = mode == "shipped"
        yield
    finally:
        diya.PERSONA, diya.TIDY_REPLIES, diya.PROFILE_REMINDER = persona, tidy, reminder


def ask(agent, prompt):
    messages = agent.with_profile([{"role": "user", "content": prompt}])
    with contextlib.redirect_stdout(io.StringIO()):  # the tool loop prints each call
        return agent.ask(messages)


def run_mode(agent, mode, cases, profile_words, say=print, save=None):
    records = []
    with mode_settings(mode):
        for case in cases:
            started = time.monotonic()
            try:
                reply, tools = ask(agent, case["prompt"])
                crashed = None
            except Exception as exc:  # noqa: BLE001 -- a crash is a failure to report, not a reason to stop
                reply, tools, crashed = "", [], f"{type(exc).__name__}: {exc}"
            issues = [("crash", crashed)] if crashed else grade(case, reply, profile_words)
            record = {"id": case["id"], "split": case["split"], "kind": case["kind"], "prompt": case["prompt"], "mode": mode, "reply": reply, "tools": list(tools), "words": len(reply.split()),
                      "issues": issues, "clean": not issues, "seconds": round(time.monotonic() - started, 1)}
            records.append(record)
            say(f"[{'CLEAN' if record['clean'] else 'issues'}] {mode} {case['id']} {record['words']} words: {case['prompt']!r}" + ("" if record["clean"] else "  <- " + "; ".join(k for k, _ in issues)))
            if save:
                save(records)
    return records


def summarize(records):
    """{'clean': n, 'of': n, 'median_words': x, 'issues': {kind: count}} for one mode's records."""
    kinds = {}
    for record in records:
        for kind, _ in record["issues"]:
            kinds[kind] = kinds.get(kind, 0) + 1
    words = [r["words"] for r in records]
    return {"clean": sum(r["clean"] for r in records), "of": len(records), "median_words": statistics.median(words) if words else 0, "issues": dict(sorted(kinds.items()))}


def render(results):
    """A table of the modes, then every reply that still has something wrong with it, in full."""
    lines = ["mode       clean   median words   what was found"]
    for mode, records in results.items():
        s = summarize(records)
        lines.append(f"{mode:<10} {s['clean']:>2}/{s['of']:<3}  {s['median_words']:>10}      " + (", ".join(f"{k} {v}" for k, v in s["issues"].items()) or "nothing"))
    for mode, records in results.items():
        bad = [r for r in records if not r["clean"]]
        if bad:
            lines += ["", f"--- {mode}: {len(bad)} reply(ies) with something wrong ---"]
            for r in bad:
                lines += [f"  {r['id']} ({r['kind']}): {r['prompt']!r}", "    said: " + r["reply"].replace("\n", " / ")[:400], "    wrong: " + "; ".join(f"{k}: {w}" for k, w in r["issues"])]
    return "\n".join(lines)


def main(argv=None, client_factory=None, say=print, warm=True):
    parser = argparse.ArgumentParser(prog="diya_style_bench.py", description="Reply-style benchmark: are Diya's replies short and plain?")
    parser.add_argument("--model", default=None, help="the Ollama model (default: DIYA_MODEL)")
    parser.add_argument("--split", default="all", choices=("all", "dev", "held-out"))
    parser.add_argument("--modes", default=",".join(MODES), help="comma-separated: before, rules, reminder, shipped")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", default=None, help="write every reply to this JSON file, after each message")
    args = parser.parse_args(argv)
    diya.configure_console()
    cases, profile_lines, profile_words = load_cases()
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not modes or any(m not in MODES for m in modes):
        parser.error(f"--modes must be some of {', '.join(MODES)}")
    model = args.model or diya_config.load_config().model
    if client_factory is not None:
        client = client_factory(model)
    else:
        from openai import OpenAI

        client = FixedConditions(OpenAI(base_url=diya_config.load_config().ollama_url, api_key="ollama"), args.temperature, args.seed)
    results = {}
    with tempfile.TemporaryDirectory(prefix="diya-style-", ignore_cleanup_errors=True) as workdir:
        agent = make_agent(workdir, model, client, profile_lines)
        if warm:
            diya.warm_up_or_exit(agent)

        def save(mode):
            def write(records):
                if args.out:
                    with open(args.out, "w", encoding="utf-8") as handle:
                        json.dump({"settings": {"model": model, "split": args.split, "seed": args.seed, "temperature": args.temperature}, "results": {**results, mode: records}}, handle, ensure_ascii=False, indent=1)
            return write

        for mode in modes:
            say(f"== {model}: {mode}, {len(cases)} messages")
            results[mode] = run_mode(agent, mode, cases, profile_words, say, save(mode))
    say("\n" + render(results))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"settings": {"model": model, "split": args.split, "seed": args.seed, "temperature": args.temperature}, "results": results}, handle, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
