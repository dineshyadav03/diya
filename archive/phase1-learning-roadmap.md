# Phase 1 learning roadmap (archived)

Kept as a record of how the mechanisms behind Diya were first built and proven, one small
milestone at a time. It is no longer updated; the current roadmap is [`../ROADMAP.md`](../ROADMAP.md)
and the project overview is [`../README.md`](../README.md).

## Status (final)
- **Milestones 1-5:** complete (2026-09-16). The one open item is the learner's own written
  explanation of the whole system (the last checkbox of Milestone 5).
- **Environment:** the milestones were built and run on Windows. Ollama, Python and MCP behave the
  same on macOS; the differences are the scheduler (`launchd` instead of Task Scheduler) and the
  amount of memory available for larger models.
- **What came next:** the same pieces became Diya itself (a web client, persistent threads, the
  Dreaming memory job, tests). See the README.

---

## Milestone 0 -- Hardware
Deferred. Nothing in these milestones depends on particular hardware.

---

## Milestone 1 -- Talk to a model through code, not a chat window
**(Built on Windows; it works the same on macOS.)**

**Goal:** prove to yourself that "an AI chat app" is just a program calling a web address and
reading the reply -- the exact thing Truffle's own `/if2/v1/chat/completions` endpoint does
(dossier Section 6.2).

- [x] Download a small model through Ollama -- already had `llama3.2:3b` (2GB) installed.
- [x] Call it with `curl` from the terminal and read the raw JSON reply -- done 2026-09-16.
- [x] Call it again from a tiny Python script instead of curl, using the OpenAI Python library
      pointed at your own machine instead of OpenAI's servers -- `milestone1_python_call.py`, done 2026-09-16.
- [x] Turn on streaming and watch the answer arrive word-by-word instead of all at once --
      `milestone1_streaming.py`, done 2026-09-16. **Milestone 1 complete.**

**What you'll understand by the end:** what an API actually is (a web address that takes a
request and returns an answer); what a "model" is from the outside (something that turns text in
into text out); why "streaming" exists.

---

## Milestone 2 -- Give the model a tool it can call
**Goal:** the model doesn't just talk -- it can decide to *do* something. This is the same idea
as Truffle's `ForegroundApp` / `ToolSpec` system (dossier Section 6.4), at a much smaller scale.

- [x] Build the raw tool-calling loop by hand first, no MCP yet -- `milestone2_raw_tool_call.py`,
      done 2026-09-16. A `list_files` tool, called successfully by `qwen2.5:3b`.
- [x] Wrap the same tool as a real MCP server using the `mcp` Python SDK (v1.29.0, Anthropic's
      official SDK) -- `milestone2_mcp_server.py`, done 2026-09-16.
- [x] Connect a client and watch it discover + call the tool -- `milestone2_mcp_client_test.py`,
      confirmed working end-to-end (server discovered, `list_files` called, real result returned).
      **Milestone 2 complete.**
- [ ] Optional bonus, not required: if Claude Desktop or LM Studio ever gets installed, point it at
      `milestone2_mcp_server.py` (run it, then add `http://127.0.0.1:8000/mcp` as a custom/remote
      MCP server in that app's settings) and watch a real chat UI trigger the same tool.

**What you'll understand by the end:** what "tool calling" / "function calling" actually means
under the hood (it's not magic -- the model outputs a structured request, your code runs it, and
feeds the result back in); what MCP is and why it's become a shared standard.

---

## Milestone 3 -- Give the model a memory
**Goal:** the model remembers things about *your* notes/files, not just general knowledge -- a
tiny version of Truffle's local-embeddings memory layer (dossier Section 6.3).

- [x] Add a local embeddings model -- `nomic-embed-text` via Ollama, done 2026-09-16.
- [x] Add a simple local vector store -- Chroma, done 2026-09-16.
- [x] Prove semantic retrieval works with example notes -- `milestone3_rag_demo.py`: asked "When's
      my tooth checkup?" (shares almost no words with the note) against 4 unrelated example notes
      in `sample_notes/`, correctly retrieved the dentist one and answered "Thursday at 3PM."
      **Milestone 3 core mechanic proven.**
- [ ] Swap `sample_notes/` for a real folder of your own notes when you have one you want to use.

**What you'll understand by the end:** what an "embedding" is (turning text into a list of numbers
that captures its meaning); what "RAG" (retrieval-augmented generation) means in practice, not just
as a buzzword.

---

## Milestone 4 -- Make it proactive
**Goal:** something that acts on a schedule without being asked -- the idea behind Truffle's
`BackgroundWorkerApp.submit_text()` (dossier Section 6.3).

- [x] Write a small script that checks something on a schedule -- `milestone4_watcher.py` watches
      `sample_notes/` for new files (substituted for GitHub PRs/email -- same idea, no external
      accounts needed). Designed as a single `run_cycle()`, meant to be invoked repeatedly by a
      real scheduler, not to loop itself -- matches Truffle's own background-app design (§6.3).
- [x] Have it write a short note to a file whenever something changes -- `proactive_context.txt`,
      confirmed it only reports genuinely new files, not ones already seen.
- [x] Have your chat setup read that file and mention it unprompted -- `milestone4_proactive_chat.py`.
      **Milestone 4 core mechanic proven**, after fixing 3 real small-model bugs along the way:
      (1) model referred to itself instead of the user when summarizing -- fixed with a clearer
      prompt; (2) vague "if it seems worth it, mention it" produced a non-answer -- fixed with a
      directive instruction; (3) model couldn't reliably identify "the most recent item" among
      several -- fixed by moving that selection into plain Python instead of asking the model.
- [x] Optional bonus: registered as a real Windows Task Scheduler job, `MacMiniAIEngineer_NotesWatcher`,
      every 15 minutes, done 2026-09-16. Manually triggered once to confirm it runs correctly through
      Task Scheduler itself (not just via manual `python file.py`) -- `LastTaskResult: 0` (success).
      To pause/remove later: `Disable-ScheduledTask` / `Unregister-ScheduledTask -TaskName
      "MacMiniAIEngineer_NotesWatcher"`. **Milestone 4 fully complete, including the bonus.**

**What you'll understand by the end:** the difference between a chatbot (waits for you) and an
agent (can act on its own); how scheduling actually works (Windows Task Scheduler here; `launchd`/
cron on macOS -- same idea, different tool).

---

## Milestone 5 -- Capstone: put it all together
**Goal:** one small system that has 2-3 tools, a memory, and a scheduled check-in -- a deliberate,
honest miniature of everything the dossier described Truffle shipping.

- [x] Wire milestones 1-4 into one loop -- `milestone5_capstone.py`: memory (M3) built at startup,
      two real tools (M2: `list_files`, `search_notes`), proactive context (M4) primed at the start
      of the conversation, all through one general tool-calling loop (a generalization of M2's
      one-shot version that handles as many tool round-trips as needed).
- [x] The model picks which tool to use on its own, done 2026-09-16, verified across 4 different
      questions in one real conversation: proactively mentioned recent context unprompted, correctly
      called `list_files` for a files question, correctly called `search_notes` for a personal-notes
      question (only after fixing the tool description to say *when* to use it, not just what it
      does), and correctly called *no* tool for a plain arithmetic question. Along the way, fixed a
      crash from an untrusted/hallucinated tool argument by catching the error and handing it back
      to the model instead of letting the program die -- the single most important lesson of the
      capstone: never trust model-provided tool arguments blindly.
- [ ] **Your turn, not mine:** write down, in your own words, what each piece does and why. That
      write-up is the actual proof of understanding -- not the code. Whenever it's written, bring
      it here and I'll read it and tell you honestly what's solid and what's fuzzy.

---

## Notes / open questions
*(add anything here as it comes up -- things to revisit, terms to look up again, ideas for later)*
