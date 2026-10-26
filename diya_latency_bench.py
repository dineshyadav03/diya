"""How fast does the model really answer on this computer? First word, whole answer, words a second, over repeated trials (docs/HELDOUT_BENCH.md; DIYA-194), added 2026-10-26.

    python diya_latency_bench.py                      5 trials of each of 4 fixed prompts, quiet
    python diya_latency_bench.py --trials 10 --load   also the same with the processor kept busy by other work (half of its cores), which is what a Dreaming pass or a browser does to a chat
    python diya_latency_bench.py --model a,b --out FILE

For each prompt and trial it asks Ollama directly (its own streaming chat route, the way Diya's warm-up does, with no tools and no memory in the prompt, so only the model is timed) and records: the time to
the FIRST word of the answer, the time to the LAST, and the words it wrote per second as Ollama counts them (tokens in its own `eval_count` and `eval_duration`, which exclude loading the model). The model is
loaded and asked one throwaway question first, so a load is not counted as an answer: a cold start is measured on its own with `--cold` (the model is unloaded, then asked). The report gives, per condition, the
half-way time (P50) and the slow end (P95) of first word and whole answer, and the median words a second.

An honest note on the slow end: with n trials the 95th percentile is the slowest trial or the one next to it. Five trials of four prompts is twenty numbers, enough to see 30 seconds from 3, not to promise a P95.
The numbers are for THIS machine on THIS day with whatever else is running (the free memory is printed); a different day is a different measurement. Nothing here reads your data.
Importing this module has no side effects.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import time

import httpx

import diya_config
import diya_machine
import diya_warm

PROMPTS = [
    ("one word", "Reply with just the word yes."),
    ("a sentence", "In one sentence, what is a mortgage?"),
    ("a paragraph", "Explain in a short paragraph why the sky is blue."),
    ("a list", "Give me five tips for revising for an exam, one line each."),
]
TIMEOUT = 600.0


def percentile(values, fraction):
    """The nearest-rank percentile of `values` (0 < fraction <= 1), or None for none."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-int(fraction * 1000) * len(ordered) // 1000))  # ceiling of fraction * n, without float surprises
    return ordered[min(rank, len(ordered)) - 1]


def read_stream(lines, clock=time.monotonic):
    """Read Ollama's streamed lines (one JSON object each) as they arrive. Returns {first, total, words, tokens, tokens_per_second}: seconds to the first non-empty piece and to the end (from the call), the words
    written, and Ollama's own count of tokens and speed from its last line (None if it did not say). `clock` is read once per line, so a test can feed a made-up clock."""
    started = clock()
    first, words, tokens, per_second = None, 0, None, None
    text = ""
    for line in lines:
        if not line.strip():
            continue
        piece = json.loads(line)
        content = (piece.get("message") or {}).get("content") or ""
        if content and first is None:
            first = clock() - started
        text += content
        if piece.get("done"):
            count, nanos = piece.get("eval_count"), piece.get("eval_duration")
            if count and nanos:
                tokens, per_second = count, count / (nanos / 1e9)
    return {"first": first, "total": clock() - started, "words": len(text.split()), "tokens": tokens, "tokens_per_second": per_second}


def ask(base, model, prompt, keep_alive="10m", opener=None):
    """One streamed question to Ollama's chat route; the lines as they come."""
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True, "keep_alive": keep_alive, "options": {"temperature": 0, "seed": 7}}
    if opener is not None:
        return opener(base, body)

    def lines():
        with httpx.stream("POST", base + "/api/chat", json=body, timeout=TIMEOUT) as response:
            response.raise_for_status()
            yield from response.iter_lines()

    return lines()


def _busy(stop):
    while not stop.is_set():
        sum(i * i for i in range(20000))


class Load:
    """Keeps about half of the processor's cores busy for as long as it is open, to measure what other work does to an answer."""

    def __init__(self, cores=None):
        self.workers, self.stop, self.procs = cores or max(1, (os.cpu_count() or 2) // 2), multiprocessing.Event(), []

    def __enter__(self):
        self.procs = [multiprocessing.Process(target=_busy, args=(self.stop,), daemon=True) for _ in range(self.workers)]
        for proc in self.procs:
            proc.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        for proc in self.procs:
            proc.join(5)
            if proc.is_alive():
                proc.terminate()


def measure(base, model, trials, opener=None, clock=time.monotonic, say=print, prompts=PROMPTS):
    """Every prompt `trials` times, after one throwaway question that loads the model. A list of records."""
    for _ in ask(base, model, "Reply with just the word yes.", opener=opener):
        pass  # the load is not an answer
    records = []
    for trial in range(1, trials + 1):
        for name, prompt in prompts:
            result = read_stream(ask(base, model, prompt, opener=opener), clock)
            records.append(dict(result, prompt=name, trial=trial))
            say(f"  trial {trial} {name:<12} first {result['first'] if result['first'] is None else round(result['first'], 2)} s, whole {round(result['total'], 1)} s, {result['words']} words, "
                f"{round(result['tokens_per_second'], 1) if result['tokens_per_second'] else '?'} tokens/s")
    return records


def summarize(records):
    firsts = [r["first"] for r in records if r["first"] is not None]
    totals = [r["total"] for r in records]
    speeds = [r["tokens_per_second"] for r in records if r["tokens_per_second"]]
    return {
        "n": len(records), "first_p50": percentile(firsts, 0.5), "first_p95": percentile(firsts, 0.95), "total_p50": percentile(totals, 0.5), "total_p95": percentile(totals, 0.95),
        "tokens_per_second_p50": percentile(speeds, 0.5),
    }


def render(model, conditions, machine):
    lines = [f"Latency: {model} on this computer ({machine})", "", f"{'condition':<10}{'n':>4}{'first P50':>11}{'first P95':>11}{'whole P50':>11}{'whole P95':>11}{'tokens/s':>10}"]

    def cell(value, width, digits=2):
        return f"{'-' if value is None else round(value, digits):>{width}}"

    for name, records in conditions.items():
        s = summarize(records)
        lines.append(f"{name:<10}{s['n']:>4}{cell(s['first_p50'], 11)}{cell(s['first_p95'], 11)}{cell(s['total_p50'], 11, 1)}{cell(s['total_p95'], 11, 1)}{cell(s['tokens_per_second_p50'], 10, 1)}")
    lines.append("\nSeconds, except tokens a second. P95 of n trials is the slowest or next to it: read it as 'the slow end', not as a promise.")
    return "\n".join(lines)


def cold_start(base, model, opener=None, clock=time.monotonic):
    """Unload the model, then time the first word of a question: what the first message of the day costs."""
    for _ in ask(base, model, "", keep_alive=0, opener=opener):
        pass
    return read_stream(ask(base, model, "Reply with just the word yes.", opener=opener), clock)


def main(argv=None, opener=None, say=print):
    parser = argparse.ArgumentParser(prog="diya_latency_bench.py", description="How fast does the model answer on this computer?")
    parser.add_argument("--model", default=None, help="the Ollama model, or several separated by commas (default: DIYA_MODEL)")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--load", action="store_true", help="also measure with half of the processor's cores kept busy")
    parser.add_argument("--cold", action="store_true", help="also measure a cold start (the model is unloaded first)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    config = diya_config.load_config()
    base = diya_warm.native_address(config.ollama_url)
    models = [m.strip() for m in (args.model or config.model).split(",") if m.strip()]
    saved = {}
    for model in models:
        say(f"== {model}: {args.trials} trial(s) of {len(PROMPTS)} prompts, quiet")
        machine = diya_machine.describe(diya_machine.sample()) or "state of the computer not known"
        conditions = {"quiet": measure(base, model, args.trials, opener, say=say)}
        if args.load:
            say(f"== {model}: with other work on the processor")
            with Load():
                conditions["loaded"] = measure(base, model, args.trials, opener, say=say)
        if args.cold:
            cold = cold_start(base, model, opener)
            say(f"cold start: first word after {None if cold['first'] is None else round(cold['first'], 1)} s, whole answer {round(cold['total'], 1)} s")
            saved.setdefault(model, {})["cold"] = cold
        say("\n" + render(model, conditions, machine) + "\n")
        saved.setdefault(model, {}).update({"machine": machine, "conditions": conditions})
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(saved, handle, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
