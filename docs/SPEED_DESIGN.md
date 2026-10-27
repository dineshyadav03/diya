# Why "hey" took so long, and what was done about it

> **Status (2026-10-11):** measured, then built (`diya_warm.py`, `diya_intent.is_small_talk`, streamed replies in `docs/STREAMING_DESIGN.md`). The owner said even "hey" took a long time.

## 1. What was measured

On this computer (CPU only, no GPU), sending exactly what Diya's chat sends (the system message with the 7 remembered facts, the eight tools' descriptions, one user message "hey") to Ollama, whose
own reply reports where the time went:

| Model | State of the model | Total | Loading the model | Reading the ~1,200 prompt tokens | Writing the answer |
|---|---|---|---|---|---|
| `diya-chat` (the one the owner uses, a 4B model) | not loaded (idle for over five minutes) | **30.1 s** | 8.0 s | 20.5 s | 1.2 s |
| `diya-chat` | loaded, the system message and tools already read | **1.1 s** | 0 | 0.1 s | 0.9 s |
| `diya-chat` | loaded, tools left out of the request | 1.3 s | 0 | 0.2 s (9 tokens) | 0.9 s |
| `qwen2.5:3b` (the repository default) | not loaded | 20.3 s | 7.2 s | 12.2 s | 0.7 s |
| `qwen2.5:3b` | loaded | 0.8 s | 0 | 0.1 s | 0.7 s |

So the answer is not slow: **everything is in the first message after a pause.** Ollama unloads a model after five idle minutes by default, and a model that has to be loaded again must also read the
whole system message and the tools' descriptions again (about 4,400 characters, eight tools): thirty seconds for a greeting. Once the model is loaded and has read them, Ollama keeps them cached
and the same message takes about a second.

One more thing found while measuring: the API the assistant started for the owner this session was launched from a shell that did not have the owner's `DIYA_MODEL=diya-chat` (it was set after that
shell began), so it was quietly answering with `qwen2.5:3b`. It now starts with the owner's user-level `DIYA_*` settings loaded.

## 2. What was done

- **Keep the model loaded** (`diya_warm.py`, on by default, `DIYA_KEEP_WARM=0` turns it off). When the API starts it loads the chat model and reads the system message and tools a chat sends (a
  one-token request), so the first real message finds them cached; then, every four minutes, it asks Ollama to keep the model for `DIYA_KEEP_ALIVE` (default 30 minutes) more, with a request that
  has no prompt (nothing is read or written: it only moves the unload time). The cost is memory: about 3 GB for the 4B model, held while the API runs.
  - If the computer sleeps, or Ollama is restarted, the model is unloaded and the next message is the slow kind again until the next renewal (within four minutes of waking) re-loads it.
  - The other way to the same end is Ollama's own setting, `OLLAMA_KEEP_ALIVE` in the environment of the Ollama app. That is a setting of the owner's machine and was not changed.
- **A greeting is answered without the tools** (`diya_intent.is_small_talk`): "hey", "hi diya", "good morning", "thanks", "bye", "how are you" and the like, and nothing else (not "yes" or "ok", which
  may answer an offer that needs a tool, and not a greeting followed by anything). Such a message cannot need a tool, and leaving the tools out turns the 20 seconds of reading into 0.2 even when the model
  is cold. Warm, it makes no measurable difference (1.1 s against 1.3 s); it is the cold case it fixes.
- **Replies appear as they are written** (`docs/STREAMING_DESIGN.md`): the time to the first word is the prompt (0.1 s when warm) plus one word, not the whole answer.

## 3. What was not done, and what is still slow

- A question that needs a tool (the weather, a web search) is two model turns plus the tool, and an answer of a hundred words on this CPU is about ten seconds. Streaming shows it as it arrives; it does not
  make it shorter.
- The first message after the API is restarted waits for the priming (the model load, about 30 seconds on this computer), which now happens at start, before the first message, not during it.
- The microphone path (Whisper on the CPU) is its own cost and was not touched.
- A bigger or faster model would be a hardware question (`ROADMAP.md`, later stages, item 1), not this one.

## 4. Greetings are tidied (2026-10-14)

A greeting, thank-you or goodbye has its own turn (no tools, a short prompt, a looser temperature), and the reply used to be shown as the model wrote it. Measured with the real chat model, one greeting
at a time, twelve different ones (hey, hi, good morning, thanks, bye ...):

- **With nothing in memory, 11 of 12 replies addressed the person by a name nobody had given:** "Hi Alex" in seven, and in three the assistant's own name ("Good morning, Diya!" to someone who had said
  "hey diya"). With "Name is Priya" in memory the right name was used **0** times and a wrong one (Alex, Maya, Anna) 11 times: the prompt's "use their name if it is given" was filled in by the model.
- "Good morning" was said in the afternoon; the prompt's "no emoji" and "never offer to assist" were not kept ("How can I assist you today? 😊").

A prompt did not hold a model of this size to any of it (it is the same finding as `docs/GATE_BENCHMARK.md`: code decides what must be true), so **what the person sees is made right in code after the model has
written it** (`diya_intent.tidy_small_talk`): a name that is not the one a fact gives ("name is X", "my name is X") is taken out, the part of the day is the real one unless the person named one, pictures are
taken out, and a sentence that offers to assist is dropped. The model still writes the greeting; code only removes what it had no way of knowing. The prompt now says to use no name unless a fact gives one
and that Diya is Diya, not the person. Because the reply is changed after it is written, it is told whole when it is done (as a fact-share's already was), not word by word; it is a few words.
A bare "morning", "afternoon" or "evening" is a greeting now (it was sent to the full turn with every tool, and answered "How can I assist you today? 😊").

**Measured after,** the same twelve greetings, with empty memory and with the name Priya: **0 of 12 in both runs** had a name, a picture or an offer to assist. (An earlier try of the same
code still let through a bare "morning", which went down the full turn and was answered "How can I assist you today?" with a picture, and "Hello again, Diya."; those are the last two rules
above.) **Not fixed, because it is the model's voice and not a fact:** the replies are often only "Good morning." (right for the hour, but said even to "thanks"), and the model does not use
the name it is given (it never said "Priya"). A reply with no name is safe, so the name is only ever *kept*, never added. Twelve greetings, two runs: a measurement of this fix, not a benchmark.

## 5. Why every reply took five to fifteen minutes, and the two things that fixed it (2026-10-27)

The owner's replies had slowed to **5-7 minutes each, and 15 for the last** (`turn_stats` in the database; a greeting, which sends no tools, still took 12 seconds). Measured on this computer, calling Ollama directly with
the model Diya uses and a prompt the size of one chat turn (`scratchpad/speed_probe.py`, a 9,117-token prompt):

| | Reading the prompt | Where it ran |
|---|---|---|
| Before | 9,117 tokens in 288 s = **32 tokens a second** | `ollama ps`: 100% CPU (the Intel Arc graphics was found but dropped: "dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1") |
| After `OLLAMA_IGPU_ENABLE=1` | 9,117 tokens in 146 s = **62 tokens a second** | `ollama ps`: 100% GPU |

And what a turn sent: **49 tools, 34,100 characters, about 9,000 tokens, on every message that was not a greeting.** 39 of the 49 are *proposal* tools (one per kind of Google action, added 2026-10-25 to 27); the
other ten are the older read tools. At 32 tokens a second, nine thousand tokens is the five minutes. Memory made it worse: free memory was 0.3-0.5 GB of 16 GB with 8,450 pages a second going to the paging file
(Claude's own window, three browsers, Dropbox and Discord hold about 6 GB; Diya's old Python and node processes are under 100 MB and were not the cause).

**What was done.**
1. *The graphics card.* The user-level variable `OLLAMA_IGPU_ENABLE=1` is set and Ollama was restarted with it (a process started from an older shell does not see a variable set after that shell began; the
   server log's "inference compute ... library=Vulkan ... type=iGPU" line says it is on). It is shared memory, not a card of its own, so it is about twice as fast, not ten times.
2. *Only the tools a message asks for.* `Agent._tools_asked_for`: a proposal tool is offered only when its kind's `asked` test says the message asks for that action, which is the same test `_propose` already used to
   refuse it ("NOT_ASKED_TEXT"). So no answer can change, and a message that asks for nothing sends **10 tools (about 1,800 tokens) instead of 49 (about 11,000 by the same count)**; "make a Drive folder called X" sends 11.

**What was not done.** The model is still on a machine with 16 GB shared with a lot else; the memory the model itself holds (about 5 GB with its 16,384-token window) is unchanged. Closing the browsers is the owner's
to do, and the biggest remaining lever once the above is in.

### And the dog (2026-10-27)

"What am I doing next Tuesday?" ended "...and your dog Hog will be proud." The persona and `PROFILE_REMINDER` ask the model not to bring up pets or hobbies; a 4B model does it anyway (STYLE_BENCH: 9 of 24 replies before
the reminder). `diya_background.drop_unasked` is the rule in code: on the finished reply, a sentence (or the clause after a dash) that mentions a pet or an instrument the person's *accepted facts* cover is taken out,
unless the person's own message touched that topic ("what is my dog's name?"). Nothing else is changed, and a reply that would be left empty is kept as it was. Tests: `tests/test_background_and_tools.py`.
