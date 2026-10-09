# Model benchmark, first pass (Windows laptop, CPU)

Roadmap, Later stages 1: "Hardware and model benchmark". This is the **model half, measured on the machine Diya runs on
today**. The hardware half (the Mac mini) is not done: it cannot be until the Mac is here.

## What was run

Measured 2026-09-26 and 2026-09-27 on a laptop with an Intel Core Ultra 7 155H (16 cores), 15.7 GB of RAM and no dedicated
GPU (Ollama ran on the CPU as far as anything here shows; the integrated Arc graphics were not checked). Three models that
were already installed, each run through the same two things, one after the other, with the model loaded first:

1. `python diya_evals.py`: the nine cases in `diya_evals.py` (no tool for arithmetic, notes retrieval, weather, file
   listing, add and list reminders, two fact-shares that must get one short sentence, one question that must get a full
   answer).
2. The reminder measurement from [PROACTIVITY_DESIGN.md](PROACTIVITY_DESIGN.md), one run per message: 19 messages that ask
   for no reminder (the tool must save nothing) and 12 that do (the time must be read right, or refused).

| Model | Evals passed | Time for the 9 evals | Unasked reminders saved (of 19) | Tried anyway | Requests (12): right time / wrong time / other | Time for the reminder run |
|---|---|---|---|---|---|---|
| `qwen2.5:3b` (Diya's model) | 8 of 9 | 91 s | 0 | 4 | 8 / 0 / 4 | 190 s |
| `llama3.2:3b` | 7 of 9 | 96 s | 0 | 2 | 7 / 0 / 5 | 200 s |
| `qwen3:8b` | **9 of 9** | 551 s | 0 | 2 | 8 / 0 / 4 | 1,935 s (32 min) |

"Other" is every request that was neither saved at the right time nor at a wrong one: refused, no tool call, or the one
request that should be saved with no time at all. "Tried anyway" is how often the model called `add_reminder` on a message that did not ask for one; the guard
refused every time, which is why none were saved.

## What it says

- **A bigger model fixes the routing, at a price this laptop cannot pay.** `qwen3:8b` is the only one that passes all nine:
  both 3B models run a web search for "9 times 7", and `llama3.2:3b` searched the web for the explanation question too.
  It needed no tool where none was wanted. But it took about 6 times as long: 61 seconds per eval case against about 10. An answer that takes a minute is not a usable chat on this
  hardware.
- **It did not do better at the thing reminders need.** With the guard and the words check in place, the three models
  saved the same number of correct times (7 or 8 of 12) and none saved a wrong one. The refusals were the same kinds
  ("next Friday", a bare "at 5", "after lunch" are refused by design). So for reminders the code, not the model size, is
  what carries the safety, which is the point of having put it in code.
- **`qwen2.5:3b` is a reasonable default here**, not a good one: it is the fastest and the guard makes its worst habit
  (saving reminders nobody asked for) harmless, but it still misroutes plain arithmetic to a web search.
- **The Mac question this leaves open:** whether a Mac mini with 16 GB can run an 8B model fast enough to use. The 8B
  model's quality here is real; its speed on this CPU is not the answer for Apple silicon, which has a GPU sharing memory.
  That needs the machine.

## How far to trust it

Not far, and this is why:

- **One run per message.** Sampling is on (Ollama's default), so a second run would differ. The earlier measurement of
  `qwen2.5:3b` at 2 to 3 runs per message gave the same picture, but these counts are small enough that a difference of one
  or two is noise, including the 8 / 8 / 7 above.
- **One machine, one moment,** with other programs running. Timings are wall-clock, not a controlled speed test, and the
  weather case makes a real network call.
- **The cases are the author's.** Nine evals and 31 reminder messages, written by the person who wrote the code they test.
  They show that a model can or cannot do these things, not how it does on the way the owner actually talks.
- **`qwen3:8b` has a thinking mode** whose effect on the answers and the time was not separated out.
- **Three models only,** the ones that were installed. `medgemma` (installed) was left out: it is not a general chat model.
  A larger or different model may do better, and nothing here says which.

## What would settle it

The same two runs on the Mac mini once it arrives, and on `qwen3:8b` there in particular; then several runs per message.
The commands are `DIYA_MODEL=<model> python diya_evals.py` and the reminder measurement described in
[PROACTIVITY_DESIGN.md](PROACTIVITY_DESIGN.md) (the script is not in the repository: it needs a running Ollama and was run
from a scratch folder).

## Second pass (2026-10-09): can a small newer model beat `qwen2.5:3b`?

The question came from `RESEARCH.md` entry 19: 2026 roundups name Qwen3-4B and Gemma 4 E4B as the best small models for tool
calling, and `qwen2.5:3b` reaches for a task tool on messages that did not ask for one. Same laptop as above (Core Ultra 7 155H,
15.7 GB, CPU only), Ollama 0.35.1, today's code (eight tools, the guards from `docs/TASKS_DESIGN.md`). Candidates:
`qwen3:4b` (2.5 GB), `qwen3:4b-instruct` (2.5 GB) and `gemma4:e4b` (6.6 GB, 7.5B parameters in all), pulled from the Ollama
library on the owner's yes. Each was run through `python diya_evals.py` (three runs for the two that ran properly) and
`python diya_actions_bench.py` (three runs of 82 messages each: 25 that ask for a task, 51 that do not, 6 ambiguous; Todoist not
connected). Per-call times are from Ollama's own server log.

### Two things stopped candidates before any quality could be measured

1. **A huge default context does not fit this machine.** Ollama loads a model at its full context window (`qwen2.5:3b` at 32,768).
   `qwen3:4b` advertises 262,144 tokens, whose cache is 38.7 GB (2 x 36 layers x 8 heads x 128 x 2 bytes x 262,144); on 15.7 GB it
   fails at load with an out-of-memory error, so all nine evals crashed (0 of 9) before the model said a word. Diya cannot pass
   `num_ctx` through Ollama's OpenAI-style endpoint, so the fix is a two-line alias that caps it, which shares the weights and
   downloads nothing: a Modelfile with `FROM qwen3:4b-instruct` and `PARAMETER num_ctx 16384`, then `ollama create <name> -f Modelfile`
   (16,384 tokens is a 2.4 GB cache; it was the tested value). Everything below used such an alias. Note the cap is half the
   default 3B's window: a very long chat thread is cut off sooner.
2. **`qwen3:4b` (the plain tag) thinks before every reply.** One spot check, not a measurement: "Say hi in three words" took 279 s
   and 2,306 generated tokens (8,428 characters of reasoning) at about 8 tokens a second. Sending `reasoning_effort: "none"`
   did not return in over ten minutes and was stopped. The non-thinking build is the separate tag `qwen3:4b-instruct`, and that is
   what was measured. (`gemma4:e4b` is also listed as thinking by default, but on the same trivial prompt it answered in 2 s with
   no reasoning text; harder prompts were not tested.)

### Results

Three runs each, the same 76 labelled messages per run plus the six ambiguous ones (82 asks).

| | `qwen2.5:3b` (today's default) | `qwen3:4b-instruct` |
|---|---|---|
| evals passed (9 cases), three runs | 7, 8, 8 | **9, 9, 9** |
| which eval fails | "9 times 7": a tool is called (every run); "add a reminder": once | none |
| asked for a task for the list: saved on it | 60 of 60 | 57 of 60 |
| asked for a task in Todoist while it is not connected: nothing saved | 15 of 15 | 15 of 15 |
| not asked: the model reached for a task tool | 20 of 153 (13%) | **3 of 153 (2%)** |
| not asked: a task saved (the guards refuse every one) | 0 of 153 | 0 of 153 |
| due dates the model gave that the person did not say | 16 of 37 (43%) | **0 of 18** |
| answers saying a task was added when none was (rough pattern match) | 7 of 246 (3%) | **0 of 246** |
| asked what is on the list: read it with `list_tasks` | 14 of 18 | **18 of 18** |
| `add_reminder` reached for on a message that did not ask | 13 of 153 (8%) | 12 of 153 (8%) |
| eval run time | 69-81 s | 86-144 s |
| benchmark run time / per message | 482 s / 5.9 s | 677 s / 8.3 s |
| median server time per model call | 2.3 s | 3.2 s |

`gemma4:e4b`: 7 of 9 evals in 326 s (the plain question "what is a mortgage" was sent to a web search, and one fact-share reply left
out the expected name); median 12.5 s per call, up to 125 s. Its benchmark was stopped after about 28 minutes with no results kept (at about three calls a minute it
needed well over an hour, past what a background task is allowed, and the script only writes at the end), so it has no benchmark numbers.
At five times the 3B's time per call it is not a candidate on this CPU. For reference, the 2026-09-27 table above has `qwen3:8b` at
9 of 9 in 551 s: the 4B-instruct matches that score in a fifth to a quarter of the time.

### What it says

- **`qwen3:4b-instruct` is a real improvement for Diya's routing, not a different failure.** It does not send plain arithmetic to a
  tool, almost never reaches for the task tool unasked, invents no due dates and never told the person it had added a task when it
  had not. The guards in code are unchanged and still refused everything that was unasked: what changed is that they have far less to
  refuse. The price is about 1.4 times the time per message (8 s against 6 s) and about 1.7 GB more memory in use (5.1 GB loaded with the 16K cache, against 3.4 GB).
- **It is not better at everything.** It never acts on "Could you put finish the report on my task list?" (no tool call, all three
  runs), which the 3B did every time: a model that calls fewer tools unasked also calls fewer when asked in an indirect phrasing.
  And it is no better on `add_reminder` (8% either way), which the reminder guard already makes harmless.
- **The Mac mini question is smaller than it looked.** A 4B model that is good at routing runs at a usable speed on this CPU; the
  case for new hardware rested on needing an 8B model.

### How far to trust it

- Three runs per model and one machine; a gap of one or two in a count is noise, and the gaps that matter here (13% against 2%, 43%
  against 0%) are not that small but are still from 153 and 37 events.
- The labelled messages were written by the author of the guards. They show what each model does with these phrasings, not how it
  does on the owner's own words; the way to settle that is to run it for a week and watch what the guards refuse.
- The benchmark replaces `add_reminder` with a stub that always succeeds, so reminder-time reading was not measured here (the table
  above still stands for it, and a change of model should repeat it); the "said it was added" count is a rough pattern match.
- `reasoning_effort` and the 2-second Gemma 4 call are single probes. Gemma 4 was not benchmarked, only run through the evals.
- Timings are wall-clock with other programs open, and the Gemma 4 download was still finishing during the first `qwen3:4b-instruct` run.

### To use it (nothing was switched)

The repository default is still `qwen2.5:3b`. To try the 4B-instruct model: `ollama pull qwen3:4b-instruct`; write a file named
`Modelfile` containing the two lines in the first problem above; `ollama create diya-qwen3-4b -f Modelfile`; start Diya with
`DIYA_MODEL=diya-qwen3-4b`. If long chats matter, the cap can be raised to 32768 (a 4.8 GB cache, untested here). Left on this machine
by the bake-off: `qwen3:4b-instruct` (2.5 GB, the useful one), `qwen3:4b` (2.5 GB, the thinking build, not usable), `gemma4:e4b`
(6.6 GB, not viable here) and three aliases named `bakeoff-*` (a few KB each); `ollama rm <name>` removes any of them.
