# Gate benchmark: code checks vs. asking the model

RESEARCH.md entry 10 (supermemory) argues a fast decision model should make harness-level routing choices --
whether a tool or a memory lookup applies -- instead of a hook or the main model. Diya already makes two such
choices in code: `diya_intent.is_fact_share` (does this message just share a fact?) and
`diya_intent.is_reminder_request` (does it ask for a reminder?). This measures whether asking the local model
the same yes/no question instead would do better, not just differently: `diya_gate_bench.py` runs both on the
same labelled cases those checks are already tested against.

## What was run

`qwen2.5:3b` via Ollama on this Windows laptop, temperature 0, one fresh single-message question per case (the
same shape as `diya_verifier.ask`), 2026-09-27. The fact-share check was run twice; the result was identical
both times.

| Check | Cases | Code right | Model right | Model false-yes | Model false-no |
|---|---|---|---|---|---|
| fact-share | 47 | **47/47** | 35/47 | 0 | 12 |
| reminder request | 71 | 61/71 | 57/71 | 0 | 14 |

## What it found

**Fact-share: the model said "no" to every single genuine fact-share (all 12), and got every one of the 35
non-fact-shares right.** Checked against the raw, unparsed reply (not just the parsed first word) for two of
them -- both a bare `NO`, so this is not a parsing artifact. Whatever "just sharing a fact, with no question,
request, need or complaint in it" means to this model at temperature 0, with this prompt, it does not include
"I have a dentist appointment next Tuesday at 3pm" or "My flight to Berlin leaves on Friday at 6am". The code
check gets this right 100% of the time, by construction: it is exactly what it was written and measured to
do (`tests/labelled_fact_share.py`).

**Reminder request: the model is worse overall (57/71 vs 61/71), but not worse everywhere.** Of the 14
disagreements: on the 6 cases that `tests/labelled_requests.py` already records as the code check's own known
limits (`LIMIT_ALLOWED`, `LIMIT_REFUSED`), the model got 5 of 6 right where code is documented to be wrong --
correctly refusing "How do I set a reminder on my phone?" (a question about reminders, not a request for one,
which the regex over-matches) and correctly allowing "Alert me when it's 6" (a real request phrased in a way
the regex does not cover). But on the plain, main set of requests the code check gets right, the model
introduced 9 new misses it should not have -- "remind us to leave at 7", "Set an alarm for 7am", "note to self:
renew the licence" and others, all said "no" to.

**In both checks the model never once said yes when it should have said no (0 false-yes across 118 calls).**
It is a consistently conservative model at this task, with this prompt: wrong by omission, not by
overreach. That happens to point the same safe direction the code checks are designed to (D9: a false refusal
is the safe failure), but it is a real cost in how often something the person actually asked for goes
unrecognised.

## Recommendation

**Keep the code checks.** On the evidence measured here, asking the model is not more accurate for either
decision -- clearly worse for fact-share, and worse on balance for reminders despite doing better on a few of
the code's own known edge cases. It would also add, per message, a network/local round trip the code checks
do not need and a new failure mode (nothing today breaks if Ollama is down before the main chat call; a
model-based gate would). This confirms, rather than assumes, the "no new build" conclusion RESEARCH.md entry
10 reached before this was run.

## How far to trust this

- **One prompt each, not iterated.** The fact-share result in particular (0 of 12 right) is stark enough that
  a different prompt might do better; this tested the first reasonable phrasing, not the best achievable one.
- **One model.** `qwen3:8b` was not tried here; `docs/MODEL_BENCHMARK.md` found it about 6 times slower on
  this CPU for a similar-sized task, which would make a per-message gate call slower than is likely usable.
- **The labelled cases are the code checks' own author's,** written to test the code, which the model was not
  tuned against and the code implicitly was (by the ordinary process of writing regexes against examples and
  seeing if they pass). This does not make the comparison unfair -- both sides are measured against the same
  yes/no answer a person would give -- but it is not a foreign, independent test set either.
- **Rerun:** `python diya_gate_bench.py`. Needs Ollama running.
