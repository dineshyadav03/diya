# Task sheet progress

Updated 2026-10-18. The blueprint's task sheet has 298 tasks; the progress is kept in `docs/tracker/progress.csv` and written into the owner's three copies of the sheet by `python scripts/tracker.py apply`.
"Done" means the acceptance test in the sheet was met and there is evidence. Anything that touches Google, a phone or another real thing the tests cannot reach stays "In progress" until the owner has tried it.

| Status | Tasks |
|---|---|
| Not started | 178 |
| Needs verification | 10 |
| Research queue | 63 |
| In progress | 14 |
| Blocked | 0 |
| Done | 33 |
| Deferred | 0 |

## Done (33)

- **DIYA-001** Pin current Git SHA, branch and release state (2026-10-18): docs/BASELINE_2026-10-18.md: SHA 8fbe9d8, branch main, tree clean, date
- **DIYA-003** Rerun backend unit/integration tests with saved output (2026-10-18): docs/BASELINE_2026-10-18.md: python -m pytest tests, 7495 passed, 5 skipped, 0 failed, 8m23s, commit 8fbe9d8. Stand-in models, so this says nothing about model quality.
- **DIYA-004** Run frontend build, type checking and lint (2026-10-18): CI run 39114084541 on 8fbe9d8: pytest, address scan and `npx next build` all succeeded. The UI is plain JavaScript; no separate type check or lint is configured, so there is none to run.
- **DIYA-006** Inventory running Ollama models and checksums (2026-10-18): docs/BASELINE_2026-10-18.md: Ollama 0.40.6, 13 models with ids, sizes, quantization, context
- **DIYA-007** Capture laptop and runtime performance fingerprint (2026-10-18): docs/BASELINE_2026-10-18.md: Windows 11, Core Ultra 7 155H, 15.7 GB RAM, Arc graphics driver, CPU backend, 394 GB free
- **DIYA-014** Implement app health endpoint dashboard (2026-10-18): diya_health.py, the Status page, tests/test_health.py (13), docs/HEALTH_DESIGN.md. Run against a private copy of the real database.
- **DIYA-015** Check encrypted backup and real restore (2026-10-18): tests/test_backup.py (19+); a snapshot of a copy of the real database restored to a disposable file and passed the health check. Not encrypted (see DIYA-005).
- **DIYA-016** Add migration forward/recovery policy (2026-10-18): diya_backup.before_migrating + diya_db.apply_migrations; tests/test_backup.py: older database snapshotted first, migrated, rolled back by restore; a failed step changes nothing. The API refuses to migrate a database it could not first copy (DIYA_BACKUP=0 goes on without).
- **DIYA-018** Design explicit memory store taxonomy (2026-10-18): docs/MEMORY_TAXONOMY.md. Names the kinds and says honestly that skills/procedures and per-fact forget_after do not exist yet.
- **DIYA-019** Make memory capture outbox atomic with message commit (2026-10-18): Store.add_message(capture=True); tests/test_capture_queue.py::test_a_message_and_its_reading_job_are_saved_in_one_transaction
- **DIYA-020** Expose immediately asserted facts on the next turn (2026-10-18): tests/test_hog_regression.py::test_told_once_the_dog_reaches_the_model_on_the_next_turn
- **DIYA-022** Distinguish user-approved facts from provisional claims (2026-10-18): diya_provenance.py, tests/test_provenance.py (32), docs/PROVENANCE_DESIGN.md; the Memory page already shows each fact's source message, history, actor and time. On request ('how do you know that?') and on the Memory page; not appended to every reply.
- **DIYA-023** Implement correction and supersession (2026-10-18): tests/test_hog_regression.py::test_a_correction_replaces_it_and_the_old_one_stays_in_the_trail; tests/test_recall.py vector purge
- **DIYA-025** Implement external-source memory promotion gate (2026-10-18): tests/test_hog_regression.py (mail saying 'your dog is Max' changes nothing); docs/GMAIL_DESIGN.md: mail is read with no tools. Only the person's own words become accepted memory.
- **DIYA-026** Write Hog next-turn/cold-restart/truncated-history test (2026-10-18): tests/test_hog_regression.py: next turn, history cut, cold restart, correction, forgetting, malicious email
- **DIYA-028** Validate existing dreaming staged checkpoint semantics (2026-10-18): tests/test_dreaming.py: a staging failure leaves the checkpoint alone; a crash between staging and checkpoint cannot duplicate the batch
- **DIYA-030** Emit per-Dreaming-run receipts (2026-10-18): dream_runs table (migration 22), dreaming.run_cycle, GET /api/dreaming, Activity page section; tests/test_dream_receipts.py (14); docs/DREAMING_RECEIPTS_DESIGN.md. Run id, message range, staged, remembered/asked/not kept/held/replaced, errors, duration. No merges yet because Dreaming does not merge.
- **DIYA-032** Add cross-session revision/concurrent edit control (2026-10-18): Memory.edit(expected_text) / ChangedUnderYou, status-checked decisions; tests/test_memory_concurrency.py (7 incl. two simultaneous edits); docs/MEMORY_DURABILITY_DESIGN.md. Covers the Memory page and the scheduled pass. Other pages (reminders, tasks) have no edit-in-place that could overwrite.
- **DIYA-036** Define tiered action authority model (2026-10-18): docs/AUTHORITY_MODEL.md (generated from diya_catalog.py): tiers 0 to 4, what each means, and which exist. Tiers 3 (external-facing) and 4 (destructive) are defined but nothing at those tiers is built.
- **DIYA-037** Build central authority broker for every write (2026-10-18): tests/test_catalog.py: the only code that can send data out is named with a reason; Google and Todoist requests are made only inside the execute functions; kind.execute is called in exactly one place (diya_actions.run), which refuses unless approved. A static guarantee about today's code: a new write path fails the test until it is declared. There is no external-facing tier yet to enforce.
- **DIYA-038** Create typed tool schemas and side-effect catalog (2026-10-18): diya_catalog.CATALOG: every tool, proposal and flow with tier, effect, hosts reached, undo, approval and whether its output holds other people's words; tests/test_catalog.py fails for an undeclared or stale entry. Parameter schemas are the tools' own; no tool takes an address, header or credential.
- **DIYA-039** Bind approvals to exact payload digest and target (2026-10-18): diya_actions args_hash; tests/test_google_write.py::test_a_changed_event_is_not_what_was_approved and the Stage 4 tests. Approval is bound to the kind and the exact arguments, including the frozen event time.
- **DIYA-044** Red-team tool use against prompt injection (2026-10-18): tests/test_red_team.py (8): with a model scripted to obey every injected instruction, calendar text, a web page and an email cannot make a proposal, a task, a reminder or a memory fact; the guard was removed once to confirm the test fails. Shows the code does not rely on the model resisting. A real model's behaviour is a separate question.
- **DIYA-045** Add network and file root allowlists (2026-10-18): tests/test_list_files_allowlist.py (dot-dot and symlink escapes refused), tests/test_tool_allowlist.py and tests/test_boundary.py (hosts), tests/test_google_write.py (fixed Google hosts). The symlink case is skipped on this Windows account (no privilege) and runs in CI on Linux.
- **DIYA-046** Keep tokens out of model prompts and audit logs (2026-10-18): tests/test_journal.py (secret-named arguments hidden); tests/test_google_write.py::test_no_tool_lets_the_model_choose_a_host_a_url_or_a_token. No model-facing path carries a token. A program running as the same Windows user could still ask DPAPI.
- **DIYA-047** Add emergency kill switch (2026-10-18): diya_pause.py; Pause/Resume on the Status page; tests/test_pause.py (10); docs/PAUSE_DESIGN.md. Stops approved actions, automations and Diya writing first. Reminders keep firing on purpose.
- **DIYA-048** Create user-visible preview for remote writes (2026-10-18): Actions page: risk level, what it reaches, how far it can be undone, which connection it uses, under the exact arguments; tests/test_google_write.py, docs/PERMISSIONS_DESIGN.md. No recipient is shown because nothing Diya can do reaches another person yet; the Google account's email is not kept (DIYA-066).
- **DIYA-053** Handle unknown write outcomes and duplicate retries (2026-10-18): ActionUncertain -> status unknown, never sent again; tests/test_google_write.py and tests/test_connector_tools.py. The calendar event id is made from the request, so a second try cannot make a second event.
- **DIYA-061** Implement OAuth authorization code + PKCE as appropriate (2026-10-18): diya_google_calendar.pkce_pair; tests/test_secrets.py: challenge sent first, matching verifier sent with the code; state check in tests/test_google_calendar.py. No OpenID nonce: no ID token is requested. Stand-in Google only.
- **DIYA-062** Support incremental per-app read/write scopes (2026-10-18): diya_google_write.GOOGLE_WRITE: one connector, one scope, one Connect per service; tests/test_google_write.py. Stand-in Google only.
- **DIYA-063** Use secure Windows credential vault or encrypted tokens (2026-10-18): diya_secrets.py (DPAPI); tests/test_secrets.py incl. a real Windows round trip; docs/SECRETS_DESIGN.md. Windows only. A program running as the same user can still ask DPAPI.
- **DIYA-068** Fix permitted Google API hosts and safe request bounds (2026-10-18): tests/test_google_write.py: no tool parameter names a host, url or token; every address is a fixed Google host. Calendar, Tasks, Drive, Docs adapters. Stand-in Google only.
- **DIYA-072** Create Google account permissions overview (2026-10-18): GET /api/permissions and the Connections page: what each connection can and cannot do, the permission asked for, what Google said it granted, since when, last used, last approved action; tests/test_permissions.py (12), docs/PERMISSIONS_DESIGN.md. Stand-in Google for the grant record; not yet seen with a real sign-in. Sign-ins from before this show no 'granted' line.

## In progress (14)

- **DIYA-005** Snapshot local database and all configuration before schema changes (2026-10-18). Not encrypted and not offline: a copy of backups/ on another disk is Dinesh's step.
- **DIYA-021** Add outbox leases, retry and unique keys (2026-10-18). No lease column: one drain at a time in one process. Dreaming's separate pass is guarded by memory_captures, not a lease.
- **DIYA-024** Implement forgetting and derived-index purge (2026-10-18). A forgotten fact's TEXT stays in the trail on purpose (so Restore works); only a secret's text is not kept. A hard purge is not built.
- **DIYA-042** Provide approve/deny/revoke controls (2026-10-18). There is no separate 'revoke an approved action': approval runs the action at once. Pausing before approving covers the gap.
- **DIYA-051** Implement append-only normalized tool/event journal (2026-10-18). Tool calls and code-decided flows are recorded. Not yet: model requests, policy decisions and one correlation id across them.
- **DIYA-052** Build independent remote-write verifier (2026-10-18). Google writes only (stand-in). The Todoist task is not read back yet.
- **DIYA-056** Publish activity feed and action receipt detail (2026-10-18). Approved actions' receipts are still on the Actions page; one combined feed is not built.
- **DIYA-060** Build Google account connection wizard (2026-10-18). Accounts are not shown (the email is not kept) and there is one Google account only.
- **DIYA-065** Implement revocation, invalid_grant and reconnect UX (2026-10-18). Disconnect revokes at Google (last card only). Not built: pausing dependent jobs when Google revokes from its side (invalid_grant).
- **DIYA-081** Implement Calendar event create and readback (2026-10-18). Create plus read-back (title, start, end, no guests) against a stand-in. Needs Dinesh's real-account try.
- **DIYA-087** Implement upload/create folder/file/copy (2026-10-18). Folder create and read-back only (stand-in). Upload, file create and copy are not built. Needs Dinesh's real-account try.
- **DIYA-093** Implement new Doc creation and insertion (2026-10-18). Create and a line of text, read back (stand-in). Needs Dinesh's real-account try.
- **DIYA-097** Implement Google Tasks list/task-list read (2026-10-18). Lists open tasks in the default list only (stand-in). Needs Dinesh's real-account try.
- **DIYA-098** Implement Tasks create/complete/update/move/delete (2026-10-18). Create and read-back only (stand-in): complete, update, move, delete are not built.

## Waiting for the owner (19)

- **DIYA-005** Snapshot local database and all configuration before schema changes (2026-10-18). Not encrypted and not offline: a copy of backups/ on another disk is Dinesh's step.
- **DIYA-012** Check one-command Windows startup (2026-10-18). python diya_run.py starts the API and UI together; starting at login is not set up. Dinesh's step.
- **DIYA-074** Validate current Gmail search/thread/body/metadata reads on live test account (2026-10-18). Gmail read-only is built and tested with a stand-in. Dinesh's step: connect Gmail and try it (docs/GMAIL_DESIGN.md).
- **DIYA-080** Verify Calendar list/search/free-busy/events reading (2026-10-18). Calendar reading exists (upcoming events); search and free/busy do not. Dinesh's step: connect and try.
- **DIYA-081** Implement Calendar event create and readback (2026-10-18). Create plus read-back (title, start, end, no guests) against a stand-in. Needs Dinesh's real-account try.
- **DIYA-087** Implement upload/create folder/file/copy (2026-10-18). Folder create and read-back only (stand-in). Upload, file create and copy are not built. Needs Dinesh's real-account try.
- **DIYA-093** Implement new Doc creation and insertion (2026-10-18). Create and a line of text, read back (stand-in). Needs Dinesh's real-account try.
- **DIYA-097** Implement Google Tasks list/task-list read (2026-10-18). Lists open tasks in the default list only (stand-in). Needs Dinesh's real-account try.
- **DIYA-098** Implement Tasks create/complete/update/move/delete (2026-10-18). Create and read-back only (stand-in): complete, update, move, delete are not built.
- **DIYA-226** Decide single-user personal use vs distributed product (2026-10-18). Owner decision (blueprint Part XII).
- **DIYA-227** Decide personal Google vs Workspace account feature priority (2026-10-18). Owner decision (blueprint Part XII).
- **DIYA-228** Decide exact standing grants and external-approval policy (2026-10-18). Owner decision (blueprint Part XII).
- **DIYA-229** Decide whether Google Tasks or Diya DB is canonical (2026-10-18). Owner decision (blueprint Part XII).
- **DIYA-230** Decide Windows token vault, device encryption and backup (2026-10-18). Owner decision (blueprint Part XII). Windows DPAPI is the current vault; the decision is whether that is enough.
- **DIYA-231** Decide email/Drive indexing retention and memory promotion (2026-10-18). Owner decision (blueprint Part XII).
- **DIYA-232** Decide all-local vs optional cloud inference boundaries (2026-10-18). Owner decision (blueprint Part XII). Today everything is local.
- **DIYA-233** Decide Code-lane sandbox and network policy (2026-10-18). Owner decision (blueprint Part XII).
- **DIYA-234** Decide archive/chat history and category merge undo strategy (2026-10-18). Owner decision (blueprint Part XII).
- **DIYA-235** Decide API/version/scopes refresh cadence (2026-10-18). Owner decision (blueprint Part XII).
