# design-rig

A small headless-browser rig for Diya's frontend. It drives **Microsoft Edge** over the
DevTools protocol against the running dev server with **fixed stub data** (the network, the
microphone and speech are faked), so runs are comparable and never touch the real backend,
database or microphone.

For every scenario and viewport it:

- saves a PNG screenshot,
- audits the **WCAG contrast** of every visible text run (AA: 4.5:1, or 3:1 for large text),
- records page errors and horizontal overflow,
- evaluates the scenario's `checks` (DOM assertions -- e.g. "a failed message shows an alert with a
  Try again button"), and exits non-zero if any fail.

```
cd frontend
npm run dev                                   # in one terminal
node tools/design-rig/shots.mjs <outDir>      # all scenarios, desktop + phone
node tools/design-rig/shots.mjs <outDir> send-   # only scenarios whose name contains "send-"
```

Needs Node >= 22 (global `WebSocket`) and Edge. Environment variables:

| variable | meaning |
|---|---|
| `BASE_URL` | dev server origin (default `https://127.0.0.1:3000` -- a different origin from `localhost` keeps the rig's storage separate from your own browser session) |
| `EDGE_PATH` | path to `msedge.exe` |
| `VP` | viewports, comma separated: `desktop`, `mobile` (375x812), `narrow` (320x568). Default `desktop,mobile` |
| `SKIP` | comma separated scenario-name fragments to skip |
| `VARIANT=flat` | inject CSS that removes the elevation tokens, to compare against the shipped look |
| `EXPECT_FAIL=1` | don't exit non-zero on failed checks (to capture a "before" that is expected to fail) |

Scenarios live in `shots.mjs` (`SCENARIOS`). The sample data there is fictional. Screenshots can
contain whatever the fixtures show, so keep the output folder out of the repo.
