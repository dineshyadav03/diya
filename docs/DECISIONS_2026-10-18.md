# The owner's decisions, 2026-10-18 (blueprint Part XII, tasks DIYA-226 to DIYA-235)

Recorded from the owner's own words in the working session. Where the words left room, the reading is stated so it can be corrected. Nothing here changes by itself: a decision changes only when the owner says so.

| Task | Question | The owner's answer | What it means for the code |
|---|---|---|---|
| 226 | Only for the owner, or for others later? | "For now Diya is only for me. Later similar might go out and they can name it their own: all the architecture but personalised to them." | Single user, one install, no accounts, no sharing. The things that are personal (name, voice, categories, memory, connections, data folder) stay settings and data, not code, so a copy can be made personal to someone else later. Nothing is built for distribution now, and nothing here assumes Google's app-verification route for other people. |
| 227 | Which Google account? | "Personal Google account." | A personal Gmail account, not a school or Workspace one. Unverified-app warnings are expected and accepted (`docs/GOOGLE_SETUP.md`); Workspace-only products (Chat, Meet recordings, Classroom, Admin) are out of scope. |
| 228 | What may Diya do without asking? | "Yes, ask every time until I myself say to override." | The current rule stays: every change to an account waits for an exact, per-action approval. **No standing grants will be built or switched on unless the owner says so, in those words.** (DIYA-041 stays closed until then.) |
| 229 | Which is the master list, Diya's or Google Tasks'? | "Yes, Diya is the master." | Diya's own database is the truth. Google Tasks only ever receives what the owner approves; there is no two-way sync, so there are no sync loops or conflicts to resolve (DIYA-099 and DIYA-145 shrink accordingly). |
| 230 | Is Windows encryption of saved sign-ins enough? | "Yes." | DPAPI stays the vault (`docs/SECRETS_DESIGN.md`). Still advised, not done by Diya: turn on Windows device encryption (Settings, Privacy & security, Device encryption) and copy `backups/` to another disk now and then. |
| 231 | Should Diya use email and Drive for memory? | "Yes." (**read as:** yes in principle, per source, only when the owner switches a source on) | **Needs the owner's confirmation:** the suggestion in the question was *no*, and "yes" may have meant either. It is recorded as the careful reading: allowed only as an opt-in per source (mail, Drive), with retention and purge when a source is switched off; nothing read from mail or a file becomes a remembered fact on its own (it can be offered as a question, as today); the owner's own words stay the only thing that is accepted automatically. Nothing is built or switched on by this; no Google connector is connected yet. Say "no, as suggested" and it closes the other way. |
| 232 | Local AI or cloud sometimes? | "Local." | Everything runs on this computer with Ollama. No cloud model is called. The only network use is what a task needs (the weather, a web search, a repository, a service the owner connected). |
| 233 | Code lane sandbox and network policy | "Giving you free hand to decide, and if it helps in improving Diya anyhow go for it." | **Decided by Claude under that delegation, below.** |
| 234 | Chat history and category merges | "OK, but also give a feature to delete or forget something." | Keep everything by default; merges are recorded and undoable; **and** a way to delete or forget for good (below). |
| 235 | How often to recheck Google's rules? | "Every month." | `docs/MONTHLY_CHECKS.md` is the monthly list; the first is due 2026-11-18. |

## The code lane policy (DIYA-233), decided

The code lane is where Diya reads other people's code and may propose changes to her own. The rule is that **reading is free and running is rare and fenced.**

1. **Other people's code is read, never run.** A repository the owner names is fetched read-only, studied, and quoted with the file it came from (`diya_repostudy.py`). Nothing from it is installed, imported, built or executed, on any machine account, ever. No dependency of it is installed.
2. **The only code that is ever run is Diya's own repository,** and only in a throwaway copy (a git worktree or a temporary folder), never in the live folder.
3. **The run is fenced:** a clean environment with no `DIYA_*` setting, token or secret in it; the copy's own folder as the working directory, never the data folder; a time limit; a cap on output; only the offline test suite (nothing that needs the network). On Windows the network cannot be switched off for one process without firewall changes, so the fence is "run only what does not need it"; when the lane is built its tests must show that the suite it runs does not need the network.
4. **The result is a proposal:** a patch and the test results, shown to the owner on a page. It is never applied by itself. Accepting applies it on a new git branch, never on `main`, and never pushes; reverting is one step. The owner pushes, or tells Claude to.
5. **Out of bounds for self-improvement:** settings, tokens, the data folder, scheduled tasks, the approval system's rules, and this policy. A change to any of those is made by the owner or with them, in the open.
6. **Everything is journalled** (a flow in the activity journal) and the pause switch stops it.

What "if it helps improving Diya, go for it" authorises: building this lane as described, and proposing improvements to Diya's code and tests through it. It does not authorise Diya changing herself unseen, which the policy above rules out.
