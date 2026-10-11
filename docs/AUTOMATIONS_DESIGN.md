# Automations: say it once, Diya does it on a schedule and writes you the answer

> **Status (2026-10-11):** built (`diya_automations.py`, `diya_automations_api.py`, the agent's read-only run, the notifier's pass, the **Automations** page). The owner had shared three open-source
> personal-agent projects (Khoj, OpenClaw, Hermes; `RESEARCH.md` entries 16 and 18) and asked for one of their features to be built, not installed. The feature those projects are used for
> most is this one: a request that runs on a clock, with live tools, and arrives as a message. No code was taken from them; this is built from what Diya already had.

## What happens

```
"every morning at 8am tell me the weather in Pune"        (in the chat, or typed on the Automations page)
  -> Diya: "Okay. Every day at 08:00 I will: tell me the weather in Pune. The first one is Monday 12 Oct 2026, 08:00. ..."
  -> every day at 08:00 the notifier (the task that already runs every five minutes) finds it due,
     asks the model the instruction with the read-only tools, writes the answer in the chat ("Automation: tell me the weather in Pune"
     and then what it found) and puts its first line on the desktop.
```

Other examples that were tried on the real model: "check my reminders and tasks and tell me what is open", "search the web for the latest news about Ollama and sum it up in three lines".

## Why it is safe to leave alone

An automation reads the web, which is text anybody can write, and it can read private things (notes, reminders, tasks). The one thing that must then never be possible is the third leg: **acting or
sending** (`RESEARCH.md` entry 17, "the Rule of Two"). So:

- A run is offered **only** the tools that read: `search_notes`, `web_search`, `get_weather`, `list_reminders`, `list_tasks`, `list_files`. This is checked twice: the model is not shown the others, and
  `_run_tool_call(..., strict=True)` refuses a call to any tool that was not shown, however real it is (a test makes the model ask for `add_reminder`, `add_task` and an action proposal, and nothing is saved).
- What it finds goes to one place, the owner's own chat. It cannot send anything anywhere else, save a reminder, a task or an action, or change a setting.
- **Making one is done by code reading the owner's own words** (`parse_request`), never by the model, so a web page cannot make an automation. A sentence is an automation only when it has a repeat
  ("every morning at 8am", "every Friday at 5pm", read by the same reader as repeating reminders) and something to be told or looked up. A reminder ("remind me every Monday to ..."), a task, a question
  and a greeting are not. An hour with no am or pm ("every morning at 8 ...") is asked about, not guessed.
- At most ten. Each can be paused, resumed (from the next time it falls, never a backlog of the ones missed) and deleted; **Run now** runs one by hand.

## How a run goes (and what it costs)

The notifier runs **at most one** automation a pass (it has five minutes, and a model with tools can take 10 to 35 seconds measured here). The automation is **claimed before it runs**: its next time moves
on first, so a run that is cut off is lost once and not repeated for ever. The agent (the slow part to start) is made only if something is due. A failed run writes a plain line in the chat
("I could not do this one just now (ConnectionError)") so it is never mistaken for "nothing to report"; the log line says only counts. What was asked for is posted at any hour and does not use up the
six unasked messages a day.

Measured on the real local model, on a throwaway database: weather in Pune 34 s the first time (model load and the lookup), 10 s for reminders and tasks, 20 s for a web search and a three-line summary;
nothing in the reminders, tasks or actions changed.

## Settings and what is not verified

`DIYA_AUTOMATIONS=0` makes none from the chat or the page and runs none. The page and routes (`GET /api/automations`, `POST /api/automations`, `POST /api/automations/{id}/pause|resume|run|delete`) are
behind the access token like the rest. Not verified: a real week of scheduled runs (the first one tonight is whatever the owner sets up); the weather and web lookups need the internet, as they do in chat.
