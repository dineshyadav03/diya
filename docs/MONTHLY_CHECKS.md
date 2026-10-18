# Once a month (decision 235, DIYA-235)

The first is due **2026-11-18**, then the 18th of each month. Twenty minutes. Write the date and anything found at the bottom.

1. **Google's rules.** For each connection in use, look at the current official page and compare with what Diya asks for:
   - Gmail scopes and the restricted-scope rules: <https://developers.google.com/workspace/gmail/api/auth/scopes>
   - Calendar, Tasks, Drive, Docs: scopes, quotas and any deprecation notice in each API's release notes.
   - Google's current rules for unverified OAuth apps (test-user limits, and the rule that sign-ins of an app left in "testing" end after 7 days): search Google's help for "unverified apps" and "OAuth consent screen".
   - Anything that changes what `diya_google_write.py`, `diya_google_mail.py` or `docs/GOOGLE_SETUP.md` say: change them first, then the sheet.
2. **Backups.** `python diya_backup.py list` shows recent snapshots; run `python diya_backup.py verify FILE` on the newest one it lists; copy `backups/` to another disk.
3. **Status page.** Everything working? Any "needs a look"? Is the Dreaming line recent?
4. **Connections page.** Read "what this connection can do" and "last used" for each. Disconnect any you no longer use.
5. **Models.** `ollama list` and the Ollama release notes; a newer model is a measured trial (`docs/MODEL_BENCHMARK.md`), never a swap on faith.
6. **Updates.** `pip list --outdated` and `npm outdated` in `frontend/`; update one thing at a time with the tests running.
7. **Task sheet.** Open the sheet and look at what is "In progress" or "Needs verification": try what can be tried by hand and tell Claude the result.

Diya can remind you: say "remind me on the 18th of every month at 6pm to do the monthly checks in docs/MONTHLY_CHECKS.md".

## Log

| Date | What was found |
|---|---|
| | |
