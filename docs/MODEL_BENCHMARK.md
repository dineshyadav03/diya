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
