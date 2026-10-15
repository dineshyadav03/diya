# Look it up instead of giving up: answering general questions

> **Status (2026-10-13):** built (`diya.Agent._ask`, `diya_intent.wants_lookup` / `is_lookup_question` / `gave_up`, `DIYA_LOOKUP`). The owner wanted "something which can answer for everything". Diya answered
> "I don't know what it is or how it works. But I'm built to help you with things like your tasks, exam prep, or daily routines" and, asked who the current CEO of OpenAI is, said she had no real-time access.

## What was wrong

Two things, both measured with the real model (`diya-chat`, a 4B model) on a throwaway database:
1. **The voice was narrow.** It told the model it was a personal assistant that knows the person; with facts about an exam and a dog in front of it, "what can you do?" came back as exam prep. It also did not know
   what it is, so "how are you different from Claude Opus?" got "I don't have a big brother named Claude".
2. **A small model does not reach for the web.** "Who is the current CEO of OpenAI?" was answered "I don't have real-time access" in 3 of 4 tries (the web search tool was available and was not used);
   "what's the latest news about Ollama?" once the same. Changing the voice alone did not fix that (0 of 2 searched with the broader voice).

## What changed

- **A broader voice** (`diya.PERSONA`): a general assistant, running as a small open-source model on the person's computer, much smaller than cloud models like Claude Opus or GPT, honest about that, and never
  "built only for tasks, reminders or exams". Measured: it now describes itself correctly and still answers general questions.
- **Code decides when to look, the way it decides other things** (`docs/GATE_BENCHMARK.md`: the model was worse at such gates):
  - A *general question* (about the world, not about the person, Diya, or Diya's own lists such as tasks, reminders, notes, weather) that needs *today's facts* ("current", "latest", "news", "price of",
    "who won", ...) is **searched on the web first**, and the model answers from the results.
  - A short **"what is X" / "who is X"** (a name or term of one to three words, not "what is the time" or "what is the capital of Australia") is searched first too: asked "what is Opus", the model answered
    confidently and wrongly ("a large language model developed by OpenAI") and never gave up, so only searching first helps. An ambiguous word gets the web's most common meaning (for Opus, the audio format).
  - Any other general question that the model **gave up on** ("I don't know", "I can't confirm", "no real-time access", "check their website") is **thrown away** (the page is told to reset what it showed) and
    **answered again from a search**. A question about the person ("did I call the bank?") is never searched: "I have no record" is the true answer there.
- **The second pass offers no tools.** What a web page says is read, never obeyed: the model is told so, and cannot call a tool that could save or send anything. A search that finds nothing or fails leaves the
  model's own answer. `DIYA_LOOKUP=0` turns all of it off; unattended runs (automations) never do it.

## Measured (real model, real web search, throwaway database)

"Who is the current CEO of OpenAI?", "what's the latest news about Ollama?" and "who won the last cricket world cup" were searched and answered with a source; "what is Tailscale?" and "who is Sam Altman" were
searched and answered; "what is the capital of Australia" was answered at once with no search; "did I call the bank?" and "what can you do" were never searched. Not measured: how often the first-pass
"giving up" check fires on real chats; it is a short list of phrases and a miss only means the model answers as it did before.

### A regression the real-model evals found (2026-10-14)

`diya_evals.py` had passed 9 of 9 and then gave 6 of 9: "What's 9 times 7?" and "What files are in the current folder?" were sent to the web. Two gate bugs, both in `diya_intent`: "9 times 7" fitted the
"what is <a short name>" rule, and the word "current" in "current folder" fitted the "today's facts" rule. Arithmetic (`_ARITHMETIC`) and questions about this computer's folders and files (`_OWN_THINGS`)
are now never web questions, in either pass; "what is 5G", "what is GPT-4" and "what is Python 3.12" are still looked up. After the fix the evals were 9 of 9 again (real `diya-chat`). The unit tests did not
catch it because they only held examples written when the gate was written; the evals are what is for that, and they were not being run after each change. Disclosed: that is a lapse in how I (the AI)
worked on this repo, not a one-off.

## Cost and limits

An extra search (a few seconds) and a second answer for the questions that need it, nothing for the rest. The results are three DuckDuckGo snippets, so an answer is as good as those and a 4B model's summary of
them; it is told to say when they do not answer. It does not make a 4B model a cloud model: hard reasoning and long writing stay what they were.
