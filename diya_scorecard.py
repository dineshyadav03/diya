"""A scorecard of how reliably, how fast and how well Diya works, with a baseline to compare against (docs/SCORECARD.md; task DIYA-224), added 2026-10-21.

    python diya_scorecard.py                  print the scorecard from this computer's real database
    python diya_scorecard.py --write          write docs/SCORECARD.md
    python diya_scorecard.py --save-baseline  keep today's numbers as the baseline (docs/tracker/scorecard_baseline.json)
    python diya_scorecard.py --compare        say what is worse than the baseline

Three kinds of number, kept apart because they are different kinds of proof:
* **Measured now** from the real database, numbers only (no message text is read, so none can appear): how many answers came in the last 7 days, how many failed, the middle and the slow end of the time they
  took (only said when there are at least MIN_TURNS of them: a middle of three answers is not a middle), tool calls that failed in the last day, and what the Status page's checks say.
* **Recomputed now** by code with no model: how many of the labelled messages the category rules place, and how many of those they place right; how many tests exist.
* **Recorded** measurements made earlier with the real models, each with its date and the document that holds it. They are not recomputed here (the models are slow and the machine is shared with the person
  using Diya), so a model that changes does not change them: re-measure, then change the line.

`compare` flags only what is clearly worse: a failure rate that rose by 5 points or more (when both sides have MIN_TURNS), a slow end more than half again as long, fewer labelled messages placed right, fewer
tests than before. A first run has no baseline and says so. Importing this module has no side effects.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOC = ROOT / "docs" / "SCORECARD.md"
BASELINE = ROOT / "docs" / "tracker" / "scorecard_baseline.json"
MIN_TURNS = 20  # fewer answers than this and no middle or slow end is quoted
WINDOW_DAYS = 7
FAILURE_RISE = 0.05
SLOWER_BY = 1.5

# Measured with the real models, by hand, on the dates and in the documents named. Not recomputed here.
RECORDED = (
    ("2026-09-27", "Who decides at the capture gates: the code's checks or the local model", "code 47 of 47 genuine cases right; the model 0 of 12 genuine fact-shares found", "docs/GATE_BENCHMARK.md"),
    ("2026-10-09", "Which chat model: qwen2.5:3b or qwen3:4b-instruct on the nine tool-calling evals", "qwen3:4b-instruct 9 of 9 in each of three runs; qwen2.5:3b 7, 8, 8; about 1.4 times the time per message; not switched", "docs/MODEL_BENCHMARK.md"),
    ("2026-10-20", "Finding an earlier message by meaning (real embedding model, invented messages)", "20 of 20 found; the answer right 1 of 20 without it and 20 of 20 with it", "docs/EPISODIC_DESIGN.md"),
    ("2026-10-20", "Answering how do you know that from the record (invented data)", "32 of 32 correct, 0 wrong, 0 invented", "docs/PROVENANCE_DESIGN.md"),
)


def _percentile(sorted_values, fraction):
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * fraction))]


def measure_live(store, now=None):
    """Numbers from the real database, nothing else: {turns, failed, p50_ms, p95_ms, tool_calls, tool_errors, oldest_wait_hours}. p50_ms and p95_ms are None below MIN_TURNS answers that worked."""
    now = now or datetime.now(timezone.utc)
    since = (now.astimezone(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    turns = store.turn_stats_since(since)
    worked = sorted(ms for ms, ok in turns if ok)
    found = {"turns": len(turns), "failed": sum(1 for _ms, ok in turns if not ok), "p50_ms": None, "p95_ms": None}
    if len(worked) >= MIN_TURNS:
        found["p50_ms"], found["p95_ms"] = _percentile(worked, 0.5), _percentile(worked, 0.95)
    try:
        counts = store.journal_counts((now.astimezone(timezone.utc) - timedelta(hours=24)).isoformat())
    except Exception:  # noqa: BLE001 -- a record that cannot be read is "unknown", not a failed scorecard
        counts = {}
    found["tool_calls"], found["tool_errors"] = sum(counts.values()), counts.get("error", 0)
    oldest = store.oldest_pending_capture()
    wait = None
    if oldest:
        try:
            wait = round((now - datetime.fromisoformat(oldest.replace("Z", "+00:00")).astimezone(timezone.utc)).total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            wait = None
    found["oldest_wait_hours"] = wait
    try:
        import diya_feedback

        summary = diya_feedback.Feedback(store).summary(days=WINDOW_DAYS * 4, now=now)
        found["rated"], found["not_helpful"] = summary["rated"], summary["negative"]
    except Exception:  # noqa: BLE001 -- feedback that cannot be read is "none", not a failed scorecard
        found["rated"], found["not_helpful"] = 0, 0
    return found


def measure_code():
    """Numbers recomputed by code, with no model: how the category rules do on the labelled messages, and how many tests exist."""
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        import diya_categories
        from labelled_categories import LETTERS, MESSAGES

        placed = [(text, letters, diya_categories.by_code(text)) for text, letters in MESSAGES]
        placed = [(t, letters, got) for t, letters, got in placed if got]
        right = sum(1 for _t, letters, got in placed if got in {LETTERS[letter] for letter in letters})
        rules = {"labelled": len(MESSAGES), "placed": len(placed), "right": right}
    except Exception:  # noqa: BLE001
        rules = {"labelled": None, "placed": None, "right": None}
    finally:
        sys.path.pop(0)
    return {"rules": rules, "tests": count_tests()}


def count_tests():
    """How many tests pytest collects, or None if that cannot be found out in two minutes."""
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in reversed(out.strip().splitlines()):
        words = line.split()
        if words and words[0].isdigit() and ("test" in line):
            return int(words[0])
    return None


def metrics(live, code):
    """The flat numbers a baseline keeps."""
    return {
        "turns": live["turns"], "failed": live["failed"], "p50_ms": live["p50_ms"], "p95_ms": live["p95_ms"],
        "category_labelled": code["rules"]["labelled"], "category_placed": code["rules"]["placed"], "category_right": code["rules"]["right"], "tests": code["tests"],
    }


def regressions(now_numbers, baseline):
    """What is clearly worse than the baseline, in words: [] when nothing is (or when there is no baseline to compare with: that is the caller's to say)."""
    worse = []
    if baseline is None:
        return worse
    both = min(now_numbers["turns"], baseline.get("turns") or 0) >= MIN_TURNS
    if both:
        rate_now, rate_then = now_numbers["failed"] / now_numbers["turns"], baseline["failed"] / baseline["turns"]
        if rate_now - rate_then >= FAILURE_RISE:
            worse.append(f"answers that failed rose from {rate_then:.0%} to {rate_now:.0%}")
        if now_numbers["p95_ms"] and baseline.get("p95_ms") and now_numbers["p95_ms"] > baseline["p95_ms"] * SLOWER_BY:
            worse.append(f"the slow end of answers went from {baseline['p95_ms'] / 1000:.0f} s to {now_numbers['p95_ms'] / 1000:.0f} s")
    if now_numbers["category_right"] is not None and baseline.get("category_right") is not None and now_numbers["category_right"] < baseline["category_right"]:
        worse.append(f"labelled messages the category rules place right fell from {baseline['category_right']} to {now_numbers['category_right']}")
    if now_numbers["tests"] is not None and baseline.get("tests") is not None and now_numbers["tests"] < baseline["tests"]:
        worse.append(f"tests fell from {baseline['tests']} to {now_numbers['tests']}")
    return worse


def _seconds(ms):
    return "-" if ms is None else (f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms} ms")


def render(live, code, status_items, now, baseline=None):
    """The scorecard as Markdown."""
    rules = code["rules"]
    lines = [
        f"# Scorecard ({now.date().isoformat()}; generated by `python diya_scorecard.py --write`; do not edit by hand)",
        "",
        "Task DIYA-224. Three kinds of number, kept apart because they are different kinds of proof (see the top of `diya_scorecard.py`). Nothing here is read from a message: only counts and times.",
        "",
        f"## Measured now, from the real database (last {WINDOW_DAYS} days)",
        "",
        "| What | Number | Said only when |", "|---|---|---|",
        f"| Answers timed | {live['turns']} | always |",
        f"| Answers that failed | {live['failed']} | always |",
        f"| Half of answers took | {_seconds(live['p50_ms'])} | at least {MIN_TURNS} answers |",
        f"| 19 in 20 answers took | {_seconds(live['p95_ms'])} | at least {MIN_TURNS} answers |",
        f"| Tool calls in the last day / failed | {live['tool_calls']} / {live['tool_errors']} | always |",
        f"| Replies rated not helpful (last {WINDOW_DAYS * 4} days) | {live['not_helpful']} of {live['rated']} | always |",
        f"| Oldest message waiting to be read for facts | {'none waiting' if live['oldest_wait_hours'] is None else str(live['oldest_wait_hours']) + ' h'} | always |",
        "",
    ]
    if live["turns"] < MIN_TURNS:
        lines += [f"**Too few answers have been timed to say how fast they come** ({live['turns']}; the timing began on 2026-10-20). This line fills in by itself as Diya is used; nothing is guessed in the meantime.", ""]
    lines += ["## What the Status page says right now", "", "| Check | State | Says |", "|---|---|---|"]
    lines += [f"| {item['label']} | {item['status']} | {item['text']} |" for item in status_items]
    lines += [
        "",
        "## Recomputed now, by code with no model",
        "",
        "| What | Number |", "|---|---|",
        f"| Labelled messages the category rules place by themselves | {rules['placed']} of {rules['labelled']} |",
        f"| ... and place right | {rules['right']} of {rules['placed']} |",
        f"| Tests that exist | {code['tests']} |",
        "",
        "The rules leave the rest to the model on purpose (`docs/ONE_CHAT_DESIGN.md`); how the model does on them is in the recorded table below.",
        "",
        "## Recorded earlier with the real models (not recomputed here)",
        "",
        "| Date | What was measured | Result | Where |", "|---|---|---|---|",
    ]
    lines += [f"| {date} | {what} | {result} | `{where}` |" for date, what, result, where in RECORDED]
    lines += ["", "## Against the baseline", ""]
    if baseline is None:
        lines += ["No baseline yet: `python diya_scorecard.py --save-baseline` keeps today's numbers, and `--compare` then says what got worse.", ""]
    else:
        worse = regressions(metrics(live, code), baseline)
        lines += [f"Baseline of {baseline.get('date', '?')}: " + ("nothing is clearly worse." if not worse else "worse: " + "; ".join(worse) + "."), ""]
    return "\n".join(lines)


def load_baseline(path=None):
    try:
        return json.loads(Path(path or BASELINE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    import diya_config
    import diya_health
    from diya_db import Store

    import diya_backup

    config = diya_config.load_config()
    if not diya_backup.guard_migration(config, say=lambda line: print(f"diya_scorecard: {line}", file=sys.stderr)):
        return 2  # a schema change is never made to a database that has data without a checked copy first, whichever program opens it (docs/BACKUP_DESIGN.md)
    store = Store(config.db_path)
    now = datetime.now().astimezone()
    live, code = measure_live(store), measure_code()
    numbers = metrics(live, code)
    if argv == ["--save-baseline"]:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_bytes((json.dumps({**numbers, "date": now.date().isoformat()}, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        print(f"Wrote {BASELINE}")
        return 0
    if argv == ["--compare"]:
        baseline = load_baseline()
        if baseline is None:
            print("There is no baseline yet: run python diya_scorecard.py --save-baseline")
            return 2
        worse = regressions(numbers, baseline)
        print("Nothing is clearly worse than the baseline of " + baseline.get("date", "?") + "." if not worse else "Worse than the baseline of " + baseline.get("date", "?") + ":\n- " + "\n- ".join(worse))
        return 1 if worse else 0
    status_items = diya_health.collect(config, store)["items"]
    text = render(live, code, status_items, now, load_baseline())
    if argv == ["--write"]:
        DOC.write_bytes(text.encode("utf-8"))
        print(f"Wrote {DOC}")
        return 0
    if argv:
        print("usage: python diya_scorecard.py [--write | --save-baseline | --compare]")
        return 2
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
