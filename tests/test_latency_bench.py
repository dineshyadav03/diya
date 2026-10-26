"""The speed benchmark (diya_latency_bench.py; docs/HELDOUT_BENCH.md; DIYA-194), added 2026-10-26.

What this proves, with a made-up clock and made-up streamed lines (no model, no network): the percentile is the nearest-rank one and says nothing for no numbers; the first word is timed from the call to the first
piece with something in it (an empty piece does not count), the whole answer to the end, and the speed is Ollama's own token count over its own generation time; the load is not counted as an answer (one
throwaway question comes first); each prompt is asked every trial; the load keeps its workers running only while open and stops them after; the report names the condition and says the slow end is not a promise; and
the command asks with temperature 0 and a seed, with the model kept loaded, and writes the file. It does not say how fast any real model is: that is what running it is for.
"""
import json

import diya_latency_bench as lb


def lines(*pieces, done_tokens=20, done_ns=2_000_000_000):
    out = [json.dumps({"message": {"content": text}, "done": False}) for text in pieces]
    out.append(json.dumps({"message": {"content": ""}, "done": True, "eval_count": done_tokens, "eval_duration": done_ns}))
    return out


class Clock:
    def __init__(self, *times):
        self.times = list(times)

    def __call__(self):
        return self.times.pop(0)


def test_the_percentile_is_the_nearest_rank_one_and_says_nothing_for_no_numbers():
    assert lb.percentile([], 0.5) is None
    assert lb.percentile([5], 0.95) == 5
    assert lb.percentile([1, 2, 3, 4, 5], 0.5) == 3 and lb.percentile([1, 2, 3, 4, 5], 0.95) == 5
    assert lb.percentile(list(range(1, 101)), 0.5) == 50 and lb.percentile(list(range(1, 101)), 0.95) == 95
    assert lb.percentile([9, 1, 5], 0.5) == 5  # sorted first


def test_the_first_word_is_timed_to_the_first_piece_with_something_in_it_and_the_speed_is_ollamas_own():
    # clock: start 100; one read per non-empty line (the first non-empty piece), then the end
    streamed = [json.dumps({"message": {"content": ""}, "done": False})] + lines("Hello", " there", done_tokens=30, done_ns=3_000_000_000)
    result = lb.read_stream(streamed, Clock(100.0, 101.5, 104.0))
    assert result["first"] == 1.5 and result["total"] == 4.0 and result["words"] == 2 and result["tokens"] == 30 and result["tokens_per_second"] == 10.0


def test_a_stream_with_no_text_has_no_first_word_and_a_stream_with_no_counts_has_no_speed():
    result = lb.read_stream([json.dumps({"message": {"content": ""}, "done": True})], Clock(0.0, 2.0))
    assert result["first"] is None and result["words"] == 0 and result["tokens_per_second"] is None


def test_the_model_is_loaded_by_a_throwaway_question_and_every_prompt_is_asked_every_trial():
    asked = []

    def opener(base, body):
        asked.append(body["messages"][0]["content"])
        return lines("ok ok")

    ticks = iter(range(10_000))
    records = lb.measure("http://x", "m", 2, opener=opener, clock=lambda: float(next(ticks)), say=lambda *_: None)
    assert asked[0] == "Reply with just the word yes."  # the load, not an answer
    assert len(records) == 2 * len(lb.PROMPTS) and [r["trial"] for r in records] == [1] * 4 + [2] * 4 and {r["prompt"] for r in records} == {name for name, _ in lb.PROMPTS}
    assert len(asked) == 1 + 2 * len(lb.PROMPTS)


def test_the_report_names_the_condition_and_says_the_slow_end_is_not_a_promise():
    conditions = {"quiet": [{"first": 1.0, "total": 4.0, "tokens_per_second": 8.0}, {"first": 2.0, "total": 10.0, "tokens_per_second": 6.0}], "loaded": [{"first": 5.0, "total": 30.0, "tokens_per_second": 2.0}]}
    report = lb.render("qwen3", conditions, "9 of 16 GB free")
    assert "qwen3" in report and "quiet" in report and "loaded" in report and "9 of 16 GB free" in report and "not as a promise" in report
    assert lb.summarize(conditions["quiet"]) == {"n": 2, "first_p50": 1.0, "first_p95": 2.0, "total_p50": 4.0, "total_p95": 10.0, "tokens_per_second_p50": 6.0}


def test_the_load_runs_its_workers_only_while_open_and_stops_them():
    with lb.Load(cores=1) as load:
        assert all(proc.is_alive() for proc in load.procs) and len(load.procs) == 1
    assert not any(proc.is_alive() for proc in load.procs)


def test_the_command_asks_at_temperature_zero_with_a_seed_keeps_the_model_loaded_and_writes_the_file(tmp_path):
    bodies = []

    def opener(base, body):
        bodies.append(body)
        return lines("fine")

    out = tmp_path / "latency.json"
    said = []
    assert lb.main(["--trials", "1", "--model", "m1", "--out", str(out)], opener=opener, say=said.append) == 0
    assert all(b["options"] == {"temperature": 0, "seed": 7} and b["keep_alive"] == "10m" and b["stream"] is True and b["model"] == "m1" for b in bodies)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["m1"]["conditions"]["quiet"] and "Latency: m1" in "\n".join(said)
