"""How good is Diya's memory, end to end? (docs/MEMORY_BENCH.md)

The long-term-memory benchmarks (LongMemEval and the like) work like this: a person TELLS an assistant things over a conversation, and later ASKS a question that only what the assistant remembered can
answer; the answer is graded. This is that, at Diya's scale: the cases in tests/labelled_memory_qa.py go through Diya's real memory (the live reading of each message the way the chat does it,
Dreaming's scheduled pass, the privacy checks and the lanes, with the real local models) on a temporary database; then the question is put to the real agent with the memory in its prompt, and the
answer is graded by the words it must and must not contain, and the memory itself is checked for what it must not hold (an old fact that should have been replaced, a secret).

    python diya_memory_qa_bench.py                                 every case once, against DIYA_MODEL (default qwen2.5:3b) with the owner's second privacy judge
    python diya_memory_qa_bench.py --model diya-chat               the model the owner actually chats with
    python diya_memory_qa_bench.py --kinds recall,update --limit 6
    python diya_memory_qa_bench.py --out results.json              also write every result to a file, after EACH case

Needs Ollama running. Everything is temporary: the database and state are throwaway files. The cases were written by the author of the memory, and a score here says how Diya does on these phrasings,
not how it will do on the person's own words, and not how it compares with a hosted service measured on a published benchmark (it is a hundred times smaller).
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
import diya_autonomy_bench
import diya_db
import diya_memory
import dreaming
from labelled_memory_qa import CASES


def grade(case, answer, accepted_facts):
    """How one case went: {ok, missing (the groups no word of which was in the answer), said (the forbidden words that were), kept (the forbidden words that are in an accepted fact)}. Case is ignored."""
    low = str(answer).lower()
    missing = [group for group in case["must"] if not any(word.lower() in low for word in group)]
    said = [word for word in case["must_not"] if word.lower() in low]
    facts_low = " | ".join(str(f).lower() for f in accepted_facts)
    kept = [word for word in case["facts_not"] if word.lower() in facts_low]
    return {"ok": not missing and not said and not kept, "missing": missing, "said": said, "kept": kept}


def run_case(model, case, workdir, client=None, privacy_model=""):
    """One case through the real pipeline; returns what happened, graded."""
    config = dataclasses.replace(diya_autonomy_bench.build_config(model, workdir, privacy_model), lookup=False, categories=False, repo_study=False, automations=False, knowledge_chat=False)
    store = diya_db.Store(config.db_path)
    thread = store.create_thread()
    dreamer = dreaming.Dreamer(config, client=client)
    log = io.StringIO()
    started = time.time()
    with contextlib.redirect_stdout(log):
        for text in case["told"]:
            dreamer.capture_message(store.add_message(thread, "user", text))  # the way the chat reads a message the moment it is said
        dreamer.dream_cycle()  # then the scheduled pass, which reads what the live reading skipped
        dreamer.remember_on_its_own()
    told_seconds = round(time.time() - started, 1)
    agent = diya.Agent(config, client=client, action_kinds=[])
    started = time.time()
    answer, tools = agent.ask(agent.with_profile([{"role": "user", "content": case["ask"]}]))
    ask_seconds = round(time.time() - started, 1)
    memory = diya_memory.Memory(store)
    facts = memory.facts()
    accepted = [f["text"] for f in facts if f["status"] == "accepted"]
    result = {"kind": case["kind"], "told": case["told"], "ask": case["ask"], "answer": answer, "tools": tools, "accepted": accepted,
              "not_accepted": [(f["text"], f["status"], list(f.get("flags") or [])) for f in facts if f["status"] != "accepted"], "seconds": [told_seconds, ask_seconds], "gap": case.get("gap", False)}
    result.update(grade(case, answer, accepted))
    return result


def summarise(results):
    """{kind: (right, total)} and the totals."""
    by_kind = {}
    for r in results:
        right, total = by_kind.get(r["kind"], (0, 0))
        by_kind[r["kind"]] = (right + (1 if r["ok"] else 0), total + 1)
    return by_kind


def percent(part, whole):
    return f"{100 * part // whole}%" if whole else "-"


def report(model, results, privacy_model="", out=print):
    by_kind = summarise(results)
    right = sum(r for r, _ in by_kind.values())
    total = sum(t for _, t in by_kind.values())
    out(f"\nMemory question-and-answer: model {model}, privacy judge {privacy_model or model}, {total} cases")
    for kind, (r, t) in sorted(by_kind.items()):
        out(f"  {kind:10} {r}/{t}  {percent(r, t)}")
    out(f"  {'ALL':10} {right}/{total}  {percent(right, total)}")
    for r in results:
        if not r["ok"]:
            out(f"\n  WRONG [{r['kind']}{', gap?' if r['gap'] else ''}] told {r['told']} asked {r['ask']!r}")
            out(f"    answer: {str(r['answer'])[:240]!r}")
            problems = []
            if r["missing"]:
                problems.append(f"missing {[g[:3] for g in r['missing']]}")
            if r["said"]:
                problems.append(f"said forbidden {r['said']}")
            if r["kept"]:
                problems.append(f"memory kept {r['kept']}")
            out("    " + "; ".join(problems))
            out(f"    memory held: {r['accepted']}   not accepted: {r['not_accepted']}")


def write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main(argv=None, out=print, client=None):
    parser = argparse.ArgumentParser(description="Measure Diya's memory end to end: tell her things, ask later, grade the answer.")
    parser.add_argument("--model", default=os.environ.get("DIYA_MODEL", "qwen2.5:3b"))
    parser.add_argument("--privacy-model", default="qwen2.5:3b", help="the second judge of what is private (the owner's DIYA_PRIVACY_MODEL); '' uses --model alone")
    parser.add_argument("--kinds", default="", help="only these kinds, comma separated")
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases of those chosen")
    parser.add_argument("--out", default="", help="write every result to this file, after each case")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    wanted = [k.strip() for k in args.kinds.split(",") if k.strip()]
    cases = [c for c in CASES if not wanted or c["kind"] in wanted]
    if args.limit:
        cases = cases[: args.limit]
    results = []
    for number, case in enumerate(cases, 1):
        with tempfile.TemporaryDirectory() as workdir:
            result = run_case(args.model, case, workdir, client=client, privacy_model=args.privacy_model)
        results.append(result)
        out(f"[{number}/{len(cases)}] {case['kind']:9} {'ok   ' if result['ok'] else 'WRONG'} {result['seconds']}s  {case['ask']}")
        if args.out:
            write(args.out, {"model": args.model, "privacy_model": args.privacy_model, "results": results})
    report(args.model, results, args.privacy_model, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
