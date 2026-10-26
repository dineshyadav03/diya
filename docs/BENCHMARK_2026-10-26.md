# Where Diya stands: every benchmark, run on 2026-10-26 (and the failures read)

Run on the real local model (`diya-chat`, which is qwen3:4b-instruct, 16,384 tokens of context) on this laptop (Core Ultra 7 155H, 15.7 GB of memory with about 1 GB free at the time, no usable GPU), one after another,
each on a throwaway database. Prompted by Hamel Husain's post (`RESEARCH.md` entry 38): run a benchmark and read the cases it failed. Raw outputs were kept outside the repository.

## The numbers

| Benchmark | What it measures | Result |
|---|---|---|
| `diya_evals.py` | Nine tool-routing checks (the ones the guards were built around) | **9 of 9** |
| `diya_heldout_bench.py` (new) | 45 messages written before any model saw them: right tool or none, and the answer | first run **35 of 45**, routing **43 of 45**; after fixing three faults it found and replacing those cases, **37 of 45**, routing **44 of 45**; after correcting three doubtful labels (below), **40 of 45** |
| `diya_schedule_bench.py` | A repeating reminder: saved right, or refused, never wrong | repeats asked for: **19 of 20** saved with the right rule, 0 wrong, 0 lost; unreadable repeats (9): 0 saved, all told; single reminders (12): 10 saved, 0 wrongly repeating; not asked (12): **0 saved** |
| `diya_actions_bench.py` | A task added when asked, never when not | asked for the to-do list: **19 of 20** recorded; named Todoist (not connected): 5 of 5 handled; not asked (51): **0 recorded**; invented due phrases 0; claimed an add that did not happen 0 of 57 |
| `diya_autonomy_bench.py` | Is automatic memory safe to leave on? (the must-be-zero lines) | **clean**: no secret kept, no order taken as a fact, no sensitive fact accepted, no wrongly replaced fact. Plain facts: 15 of 24 remembered on their own, 4 asked about, 1 recorded wrong, 4 lost. Sensitive 18 of 18 asked. Secrets 9 of 10 not kept (the tenth waits as a question). Orders 8 of 8 not extracted |
| `diya_memory_qa_bench.py` | Told things over a chat, then asked: does the answer use them? | **31 of 33 (93%)**; every kind 100% except corrections, 5 of 7 |
| `diya_episodic_bench.py` | Finding an earlier message by meaning | top 1 **20 of 20**; at the chosen cut-off 0.55, 0 of 10 unrelated questions let through, but the margin is thin (weakest correct match 0.56, strongest unrelated 0.51) |
| `diya_gate_bench.py` | Who should decide the capture gates: the code or the model | fact-sharing: code 47 of 47, model 42 of 47. "Is this a reminder request?": code 61 of 71 (4 false yes, 6 false no), model 65 of 71 (6 false yes, 0 false no) |
| `diya_latency_bench.py` (new) | How fast it answers | quiet: first word **0.7 s**, short answer **2.5 s**, a full paragraph up to **14 s**, **about 11 words a second**; with half the processor busy: first word 1.3 s, typical answer 4.3 s, slow end 20 s, 7.8 words a second; cold start **18 s** |

## What the failures said

- **The must-be-zero lines are zero**, every benchmark: nothing unasked saved as a reminder or a task, no secret kept, no instruction from a message obeyed. That does not depend on how well the model behaves: code enforces it.
- **The model's routing on messages nobody tuned for is good (96 to 98%).** Where it slips is the *length* of a reply to a plain statement: told "i switched from physics to computer science", it writes a paragraph instead of one sentence.
  The code that makes the reply short only recognises a statement it is sure of (it scored 47 of 47 on the cases it was written for and 3 of 6 on the held-out ones). That is the clearest case of the post's point in this project.
- **Two real bugs, both fixed and kept as tests (`tests/test_found_by_the_heldout_bench.py`):** "put 'email professor sharma' on my to-do list" was answered "Gmail is not connected" (the mail check saw "email" and "list"); and phone-style statements ("btw my exam got moved...", "ive been using...") were not read as statements.
- **A real weakness, not fixed (a decision): corrections.** "I just bought an iPhone" and "I switched to tea" were held back as questions to the owner (flagged "ungrounded" for being worded differently from the message), so the old fact still answered. Holding back is by design; flagging a plain paraphrase is too strict.
- **A real hole, small, not fixed:** the code that decides "is this a reminder request?" allows a negated request ("Please don't set a reminder for that") and a question about the phrase ("What does 'remind me' mean in Spanish?"). Four of 71.
- **Labels I got wrong, said openly (`docs/HELDOUT_BENCH.md`):** three held-out cases asked for a one-sentence reply to something that is a need or a plan ("i need to finish chapter 5 before friday"); the design allows a full reply there, so the label asked for the wrong thing. And one case
  allows a read-only look at the calendar. With those corrected the same saved answers score 40 of 45; the 37 is what it scored under the labels as first written.
- **The model, not the label, was wrong on:** a list of "my notes folder" (it invented a folder called `notes`), and "also my roommate moved out on the 2nd..." (a statement, answered with a paragraph), and two plain statements ("i switched...", "my favourite subject is...").

## What this does not say

- It is Diya's own cases, written by the same person and run through the same guards, except the held-out set, which has 45 messages written in one sitting. A real person's messages are the missing benchmark: the owner's own, labelled by the owner, kept outside the repository.
- One run each (a seed and temperature 0 for the held-out and speed runs; the older benchmarks use the model's usual settings), so a difference of one or two cases is noise.
- Speed is for this laptop today with 1 GB of memory free; a Mac mini with 16 GB or more would be a different measurement.
- The weather answers come from a live service and were graded on the call alone.
- During the held-out run the owner's real Google Calendar was connected and read once (read-only, by the local model); no message, event or answer left the computer.
