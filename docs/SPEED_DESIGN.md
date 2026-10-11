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
