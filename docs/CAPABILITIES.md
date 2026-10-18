# What Diya can do, with the evidence (2026-10-18; task rows DIYA-009 and DIYA-222)

One row per capability: the code, the tests that prove it, when those tests last passed, and **what kind of proof it is**. A test in this repository (`tests/test_capabilities_doc.py`) fails if a file or test named
here does not exist, if a row has no date, or if a row has a label that is not one of the four below, so this table cannot quietly go stale.

| Label | Means |
|---|---|
| **Live** | It depends on something outside Diya's code (the local model, Windows, the real database) and has been run against the real one; the note names the document that shows it. |
| **Own code** | It depends on nothing outside Diya; the tests run the real code. |
| **Stand-in** | It depends on something outside (a model's behaviour, a microphone, a service) and has only been run against a scripted or fake one. How well it works in real life is not known. |
| **Untried** | Its real service or device has never been touched, even once. It may well fail on the first real use. |

"Last passed" is the date the whole suite last passed with this row's tests in it. It says the tests passed, not that the feature suits you.

| Capability | Code | Tests | Last passed | Label | Note |
|---|---|---|---|---|---|
| Chat with streamed replies, one continuous chat, search in chats | `diya.py`, `diya_chat.py`, `diya_web.py`, `diya_threads_api.py` | `tests/test_chat_loop.py`, `tests/test_streaming.py`, `tests/test_one_chat.py`, `tests/test_chat_search.py`, `tests/test_web.py` | 2026-10-18 | Live | Real Ollama model on this laptop (`diya_evals.py`, `docs/MODEL_BENCHMARK.md`, `docs/SPEED_DESIGN.md`) |
| Tap-to-talk voice (local Whisper) | `diya_web.py`, `frontend/lib/microphone.mjs` | `tests/test_web.py`, `tests/test_body_limit.py` | 2026-10-18 | Stand-in | Transcriber faked in tests; `docs/VOICE_DESIGN.md` |
| Answering general questions from the web | `diya_chat.py`, `diya_intent.py` | `tests/test_lookup.py` | 2026-10-18 | Stand-in | Search results are scripted in tests; `docs/LOOKUP_DESIGN.md` |
| Reviewed memory: staged facts, checks, review from the page or the command line | `diya_memory.py`, `diya_checks.py`, `diya_review.py`, `diya_memory_api.py`, `dreaming.py` | `tests/test_memory_store.py`, `tests/test_memory_checks.py`, `tests/test_review_cli.py`, `tests/test_memory_api.py` | 2026-10-18 | Own code | The owner's live memory holds a handful of facts (`docs/STAGE2_DESIGN.md`) |
| Automatic memory under written rules, with questions for the doubtful | `diya_autonomy.py` | `tests/test_autonomy.py`, `tests/test_live_capture.py`, `tests/test_hog_regression.py` | 2026-10-18 | Live | Measured with the real model (`docs/AUTO_MEMORY_DESIGN.md`); switched on by the owner 2026-10-13 |
| Corrections, "forget that", and forgetting for good | `diya_forget.py`, `diya_forget_api.py` | `tests/test_forget.py`, `tests/test_corrections.py`, `tests/test_memory_supersede.py` | 2026-10-18 | Own code | Run on test databases and copies only; `docs/FORGET_DESIGN.md` |
| Relevance recall when memory outgrows one message, with the note that the view is partial | `diya_recall.py`, `diya_memory.py` | `tests/test_recall.py` | 2026-10-18 | Stand-in | Meaning is stood in for by topic words in tests; `docs/RECALL_DESIGN.md` |
| Facts that fade unless said again, and Keep | `diya_fade.py`, `diya_memory.py`, `diya_autonomy.py` | `tests/test_fade.py` | 2026-10-18 | Own code | Not yet run on the owner's database; `docs/FADING_DESIGN.md` |
| "How do you know that?" answered from the record | `diya_provenance.py` | `tests/test_provenance.py` | 2026-10-18 | Own code | `docs/PROVENANCE_DESIGN.md` |
| Dreaming (reading chats for facts) and its receipts | `dreaming.py`, `diya_dreaming_api.py` | `tests/test_dreaming.py`, `tests/test_dream_receipts.py` | 2026-10-18 | Stand-in | Scripted model; the schedule is switched off until the owner chooses; `docs/dreaming.md` |
| Markdown copy of memory and restore | `diya_markdown.py`, `diya_review.py` | `tests/test_markdown.py` | 2026-10-18 | Own code | `docs/MARKDOWN_MEMORY_DESIGN.md` |
| Knowledge pages and answers from the owner's notes | `diya_knowledge.py`, `diya_knowledge_api.py` | `tests/test_knowledge.py`, `tests/test_knowledge_api.py`, `tests/test_notes_pages.py` | 2026-10-18 | Stand-in | Demo notes only until `DIYA_NOTES_DIR` points at the owner's folder; `docs/KNOWLEDGE_DESIGN.md` |
| Reminders, repeating reminders, snooze, done | `diya_reminders_api.py`, `diya_schedule.py`, `diya_schedule_api.py`, `diya_repeat.py`, `diya_time.py` | `tests/test_reminders.py`, `tests/test_schedule.py`, `tests/test_repeat.py`, `tests/test_time.py` | 2026-10-18 | Live | Measured with the real model (`docs/SCHEDULE_DESIGN.md`, `docs/PROACTIVITY_DESIGN.md`) |
| To-do list inside Diya | `diya_tasks.py`, `diya_tasks_api.py` | `tests/test_tasks.py`, `tests/test_tasks_api.py`, `tests/test_tasks_agent.py` | 2026-10-18 | Live | Measured with the real model (`docs/TASKS_DESIGN.md`) |
| Today page and Diya writing first | `diya_brief.py`, `diya_brief_api.py`, `diya_proactive.py`, `diya_proactive_api.py`, `diya_notify.py` | `tests/test_brief.py`, `tests/test_brief_api.py`, `tests/test_proactive.py`, `tests/test_notify.py` | 2026-10-18 | Stand-in | The desktop notifier's schedule is switched off until the owner chooses; `docs/PROACTIVE_DESIGN.md` |
| Automations ("every morning tell me the weather") | `diya_automations.py`, `diya_automations_api.py` | `tests/test_automations.py` | 2026-10-18 | Live | Measured with the real model (`docs/AUTOMATIONS_DESIGN.md`); a run can only read |
| Actions that wait for exact approval, with risk and reach shown | `diya_actions.py`, `diya_actions_api.py`, `diya_actions_cli.py`, `diya_catalog.py` | `tests/test_actions.py`, `tests/test_actions_api.py`, `tests/test_actions_agent.py`, `tests/test_catalog.py`, `tests/test_permissions.py` | 2026-10-18 | Live | Proposal behaviour measured with the real model (`docs/ACTIONS_DESIGN.md`); no real account was written to |
| Red-team: a model that obeys every injected instruction still cannot act | `diya_actions.py`, `diya_catalog.py` | `tests/test_red_team.py`, `tests/test_tool_allowlist.py`, `tests/test_boundary.py` | 2026-10-18 | Own code | The model is scripted to obey; this proves the fence, not the model |
| Pause switch | `diya_pause.py` | `tests/test_pause.py` | 2026-10-18 | Own code | `docs/PAUSE_DESIGN.md` |
| Activity journal of every tool use | `diya_journal.py`, `diya_journal_api.py` | `tests/test_journal.py` | 2026-10-18 | Own code | `docs/ACTIVITY_JOURNAL_DESIGN.md` |
| Status page and health checks | `diya_health.py`, `diya_health_api.py` | `tests/test_health.py` | 2026-10-18 | Live | Run against a private copy of the real database (task DIYA-014) |
| Checked backups, restore, and a snapshot before every migration | `diya_backup.py`, `diya_db.py` | `tests/test_backup.py`, `tests/test_migrations.py` | 2026-10-18 | Live | A snapshot of a copy of the real database was restored to a disposable file and passed the health check (task DIYA-015) |
| Sign-ins kept encrypted with Windows (DPAPI) | `diya_secrets.py` | `tests/test_secrets.py` | 2026-10-18 | Live | A real Windows round trip in the tests; `docs/SECRETS_DESIGN.md`; Windows only |
| Access token, UI passcode, local-only listening | `diya_web.py`, `frontend/lib/proxy.mjs` | `tests/test_token.py`, `tests/test_ui_login.py`, `tests/test_frontend_proxy.py` | 2026-10-18 | Own code | `docs/STAGE1_DESIGN.md`, `docs/UI_LOGIN_DESIGN.md` |
| MCP client (read-only tools the owner approves one by one) | `diya_mcp.py` | `tests/test_mcp.py` | 2026-10-18 | Stand-in | A small local server in tests; no third-party server tried; `docs/MCP_DESIGN.md` |
| Study a repository the owner names (read-only) | `diya_repostudy.py` | `tests/test_repostudy.py` | 2026-10-18 | Stand-in | Used on supermemory and REA by hand (`docs/STUDY_SUPERMEMORY.md`); the tests use scripted fetches |
| Google Calendar (read) | `diya_google_calendar.py` | `tests/test_google_calendar.py`, `tests/test_google_setup.py` | 2026-10-18 | Untried | Never against a real Google account; parked (Google project limit); `docs/GOOGLE_SETUP.md` |
| Gmail (read) | `diya_google_mail.py` | `tests/test_google_mail.py` | 2026-10-18 | Untried | Same; `docs/GMAIL_DESIGN.md` |
| Google writes with read-back (Calendar events, Tasks) | `diya_google_write.py` | `tests/test_google_write.py` | 2026-10-18 | Untried | Same; a write counts only when read back; `docs/GOOGLE_WRITE_DESIGN.md` |
| Todoist, Notion, Home Assistant | `diya_connectors.py`, `diya_connector_tools.py` | `tests/test_connectors.py`, `tests/test_connector_tools.py` | 2026-10-18 | Untried | `docs/CONNECTORS_DESIGN.md` |
| Phone: Web Push and the Telegram bot | `diya_push.py`, `diya_push_api.py`, `diya_telegram.py` | `tests/test_push.py`, `tests/test_push_api.py`, `tests/test_telegram.py` | 2026-10-18 | Untried | Never on a real device or bot; `docs/PUSH_DESIGN.md`, `docs/TELEGRAM_DESIGN.md` |
| One-command launcher | `diya_run.py` | `tests/test_run.py` | 2026-10-18 | Stand-in | The install step was never run for real; `docs/ONE_COMMAND_DESIGN.md` |

## What this table does not say
* **Live is not "works well".** A feature measured with the real 3B model was measured on a few dozen cases; `docs/MODEL_BENCHMARK.md` and the design notes give the numbers and the misses.
* **Own code** rows prove the rules hold, not that the rules are the ones the owner wants. The only test of that is use.
* The task sheet (`docs/TRACKER.md`) is the other half: it lists every planned piece, what is done, and what is waiting for the owner.
