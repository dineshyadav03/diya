"""Measure a supermemory server YOU run, against Diya's own invented test set (docs/SUPERMEMORY_LOCAL_TRIAL.md), added 2026-10-20.

    python scripts/probe_supermemory.py --url http://127.0.0.1:6767 --key <the key the server made>

What it does: sends the 40 invented messages of tests/labelled_episodic.py to the server as 40 documents in a namespace of its own, waits until they are searchable, asks the 20 questions that one of them
answers (both in `hybrid` mode, memories and source chunks, and in `memories` mode, only what supermemory extracted) and the 10 that none does, and prints how often the answer was in the top 1, 3 and 5
results, how fast the searches were, and how many unrelated questions still got results. The same lists are what `python diya_episodic_bench.py` measures Diya's own episodic recall with, so the two sets of
numbers can be read side by side (they are not identical tests: supermemory also rewrites messages into short memories, and Diya's recall returns the message itself; read the script's notes).

What it will not do, in code:
* talk to anything but this computer: the address must be localhost, 127.0.0.1 or [::1];
* send any text but the invented messages and questions in tests/labelled_episodic.py. It reads no database, no note and no file of yours, and the key goes only in the Authorization header and is never printed;
* run, install or download the server. YOU start it (docs/SUPERMEMORY_LOCAL_TRIAL.md says how, contained, with a throwaway volume).

It was written from supermemory's published API pages (`POST /ns/{namespace}/document`, `POST /ns/{namespace}/search`) and tested only against a stand-in server that behaves as those pages say. It has never been run
against the real one: if the real server answers differently, the script says which call failed and what it received, and nothing else is guessed.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import labelled_episodic as L  # noqa: E402

LOCAL = ("localhost", "127.0.0.1", "[::1]")
# for each of the 20 questions of L.ASKED: words any of which, in a result, shows it holds the answer (supermemory may turn "5th of November" into "5 November", so each has alternatives)
ANSWER = [("5th", "5 nov", "november 5", "b12"), ("zed",), ("maya",), ("40 rupees", "40"), ("legs", "push", "pull"), ("8 pm", "8:00", "20:00"), ("14 nov", "november 14"), ("yamaha", "f310"),
          ("thursday", "4:30", "dr. rao"), ("21st", "21"), ("peanut",), ("income certificate", "passport"), ("february", "wedding"), ("upper limb", "brachial"), ("10:30", "curfew"), ("goa",),
          ("rohan", "badminton"), ("hour", "battery"), ("iris", "logistic"), ("12th", "viva")]
TOPS = (1, 3, 5)


class ProbeError(Exception):
    """A call to the server failed, and what it said."""


def call(base, key, method, path, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            raw = reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise ProbeError(f"{method} {path} answered {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ProbeError(f"{method} {path} could not be reached: {exc}") from exc
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError as exc:
        raise ProbeError(f"{method} {path} answered something that is not JSON: {raw[:200]!r}") from exc


def texts_of(result):
    return [str(item.get("memory") or item.get("chunk") or "") for item in (result.get("results") or []) if isinstance(item, dict)]


def holds(text, words):
    return any(w in text.lower() for w in words)


def search(base, key, namespace, query, mode, limit=5):
    started = time.perf_counter()
    result = call(base, key, "POST", f"/ns/{namespace}/search", {"query": query, "searchMode": mode, "limit": limit})
    return texts_of(result), (time.perf_counter() - started) * 1000


def wait_until_searchable(base, key, namespace, wait=300, poll=5, sleep=time.sleep):
    """The server queues documents: wait until a search for the last message finds it (or give up after `wait` seconds)."""
    probe = L.MESSAGES[-1]
    deadline = time.monotonic() + wait
    while True:
        try:
            if any("badminton" in t.lower() for t in search(base, key, namespace, probe, "hybrid")[0]):
                return True
        except ProbeError:
            pass
        if time.monotonic() >= deadline:
            return False
        sleep(poll)


def run(base, key, out=print, wait=300, poll=5, sleep=time.sleep):
    host = base.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0] if "://" in base else ""
    if host not in LOCAL:
        raise SystemExit("probe: the address must be on this computer (localhost, 127.0.0.1 or [::1])")
    namespace = f"diya-probe-{int(time.time())}"
    started = time.perf_counter()
    ids = []
    for number, message in enumerate(L.MESSAGES):
        reply = call(base, key, "POST", f"/ns/{namespace}/document", {"content": message, "id": f"probe-{number}", "dreaming": "instant"})
        ids.append(reply.get("id", f"probe-{number}"))
    out(f"sent {len(ids)} invented messages in {time.perf_counter() - started:.1f}s to namespace {namespace}")
    if not wait_until_searchable(base, key, namespace, wait=wait, poll=poll, sleep=sleep):
        out(f"the messages were not searchable after {wait}s; the numbers below would be of an unfinished index")
    report = {"namespace": namespace}
    for mode in ("hybrid", "memories"):
        hits = {k: 0 for k in TOPS}
        times = []
        for (question, _), words in zip(L.ASKED, ANSWER):
            texts, ms = search(base, key, namespace, question, mode)
            times.append(ms)
            for k in TOPS:
                hits[k] += any(holds(t, words) for t in texts[:k])
        unrelated = 0
        for question in L.UNRELATED:
            texts, ms = search(base, key, namespace, question, mode)
            times.append(ms)
            unrelated += bool(texts)
        p95 = sorted(times)[max(0, int(len(times) * 0.95) - 1)]
        report[mode] = {"top1": hits[1], "top3": hits[3], "top5": hits[5], "asked": len(L.ASKED), "unrelated_with_results": unrelated, "unrelated": len(L.UNRELATED),
                        "search_ms_median": round(statistics.median(times)), "search_ms_p95": round(p95)}
        r = report[mode]
        out(f"{mode:9} answer in top 1: {r['top1']}/{r['asked']}  top 3: {r['top3']}/{r['asked']}  top 5: {r['top5']}/{r['asked']}  | unrelated questions that still got results: "
            f"{r['unrelated_with_results']}/{r['unrelated']}  | search {r['search_ms_median']} ms median, {r['search_ms_p95']} ms p95")
    cleaned = 0
    for document in ids:
        try:
            call(base, key, "DELETE", f"/ns/{namespace}/document/{document}")
            cleaned += 1
        except ProbeError:
            break
    out(f"removed {cleaned}/{len(ids)} of the probe's documents" + ("" if cleaned == len(ids) else "; the rest are in namespace " + namespace + " (a throwaway volume removes them all: docs/SUPERMEMORY_LOCAL_TRIAL.md)"))
    out("Diya's own numbers on the same lists: python diya_episodic_bench.py (top 1: 20/20, unrelated let through: 0/10 at its threshold). supermemory's default similarity cutoff is 0.3, "
        "so 'unrelated questions that still got results' is not comparable to Diya's 0.55 until the cutoff is matched.")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="probe_supermemory.py", description="Measure a supermemory server you run, with invented messages only.")
    parser.add_argument("--url", default="http://127.0.0.1:6767")
    parser.add_argument("--key", default=os.environ.get("SUPERMEMORY_API_KEY", ""))
    parser.add_argument("--wait", type=int, default=300, help="seconds to wait for the server to index the messages")
    args = parser.parse_args(argv)
    if not args.key:
        print("probe: give the server's key with --key or SUPERMEMORY_API_KEY", file=sys.stderr)
        return 2
    try:
        run(args.url, args.key, wait=args.wait)
    except ProbeError as exc:
        print(f"probe: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
