# One command that starts Diya: design spec (nothing here is built; it needs the owner's yes)

> **Status (2026-10-11):** designed only. It is point 4 of the daily-driver list (`ROADMAP.md`, item 6; `docs/SCHEDULE_DESIGN.md` D9). Today a day
> with Diya starts with three things done by hand: `python diya_web.py` in one terminal, `npm run dev` (with `DIYA_TOKEN` in the environment or in
> `frontend/.env.local`) in another, and, once, registering the notifier and Dreaming as scheduled tasks. This document says what one command
> would do, what it must not do, what is hard about it on this machine, and what the owner has to decide.

## 1. The problem, concretely

- **Three things, three places.** The API (`diya_web.py`, port 8080, HTTPS), the UI (`frontend`, port 3000), and the scheduled tasks
  (`Diya_Dreaming` every 30 minutes, `Diya_Notify` every 5). The first two are long-running; the last are not running at all between their
  turns, which is why "start the notifier" really means "make sure the task exists".
- **The token.** The API prints its access token **once**, when it makes one, and keeps only a hash. The UI needs the token in `DIYA_TOKEN`. A new
  terminal that forgets it gets the 401 explanations the UI already has, so the failure is clear, but it is still an annoyance every day.
- **HTTPS.** The microphone needs a secure origin, and `next start` cannot serve TLS (`frontend/tools/next-tls.mjs`). So the only HTTPS UI today is
  the development server. It works, but it is slower, rebuilds on every edit and was never meant for daily use.
- **The owner's own servers.** The owner runs the API and UI on 8080 and 3000 as they like. A launcher that starts a second copy, or kills theirs,
  is worse than none.

## 2. What the command does

`python diya_run.py` (one file, standard library only, the same on Windows and on the Mac later):

1. **Checks before it starts anything.** Ollama answers on its port; the configured models exist (`ollama list`); the certificate pair is found;
   the two ports are free, or are already Diya's (see 3). Each failure is one sentence and a next step, and nothing was started.
2. **Starts the API** as a child process with the owner's environment, and waits for it to answer on its health route (a route that needs no token
   and says nothing about the person; it would be added with this unit). Its output goes to a log in the data folder, not the terminal.
3. **Starts the UI** the way `npm run dev` does (same script, same certificate rule), with `DIYA_TOKEN` read from `frontend/.env.local` or the
   environment, **never printed, never put on a command line** (a command line is visible to every program on the machine).
4. **Says where it is**: one line with the address to open, and one saying whether the notifier and Dreaming are registered.
5. **Keeps them up.** If a child exits it is started again, waiting a little longer each time (1, 2, 4... up to 60 seconds), and gives up with a
   clear message after five quick failures in a row. Ctrl+C stops both children, API last, and leaves the scheduled tasks alone.
6. **`--status`** says what is running and what is not, without starting anything. **`--stop`** stops what this command started.

## 3. What it must not do

- **Start a second copy.** If something already answers on the API or UI port and it is Diya's, it says so and exits, or attaches in `--status`
  mode. It never stops a process it did not start.
- **Print, log or pass on a command line** the access token, the UI passcode or anything in `.env.local`.
- **Register scheduled tasks or change autostart on its own.** `--install` does that, once, only when asked, and says exactly what it will register
  first (the same two tasks, the same commands that `docs/PROACTIVITY_DESIGN.md` documents), and `--uninstall` removes only those.
- **Write outside the project and the data folder** (`DIYA_DATA_DIR`). Logs rotate (at 1 MB, three kept).
- **Hide a failure.** A missing certificate, a busy port, a model that is not pulled and a token that does not verify are each named.

## 4. The three hard parts, and what to decide

1. **Which UI server.** The choices:
   - *Development server* (what runs today): HTTPS works; slow to first load; reloads on edits; the same code path that has been tested in a
     browser for weeks. Recommended for the first version, because it is the only one that gives the microphone a secure origin without more code.
   - *Production build + `next start`*: fast, but plain HTTP, so no microphone and no secure cookie; it would need a small TLS-terminating proxy
     in front (about 60 lines in the launcher) and a rebuild when the frontend changes (a hash of the sources decides). A second unit, if the
     development server proves too slow.
2. **Autostart at logon.** Options: a **Task Scheduler "at log on" task** that runs the launcher (recommended: it is what Dreaming and the notifier
   already are, it needs no new mechanism, it can be inspected and removed in one place); a Startup-folder shortcut (simple, runs only at an
   interactive logon, invisible to Task Scheduler); a Windows service (a separate process model, a service account, and the files would be read
   under another user: the wrong shape for a program that reads one person's data).
3. **The token on first run.** The API makes it and shows it once. The launcher must not capture and store it silently: it would put a secret in a
   second place without being asked. On the first run it says "the API made a new token; it is shown once above; save it into
   `frontend/.env.local` or tell me to" and does nothing else; with the owner's yes (`--save-token`), it writes it to `frontend/.env.local`
   (gitignored) and nowhere else, and says so.

## 5. What would be built, in order

| Unit | What | Verified by |
|---|---|---|
| O1 | `diya_run.py`: the checks, start, wait, supervise, stop and `--status`, with the rules of section 3, and an unauthenticated health route `GET /api/health` on the API (`{"ok": true}`, nothing else) | tests with fake child processes and a fake clock for the restart rules; a test that no output or log contains the token; a mutation run; tried by hand against throwaway ports (3100 and 8097), never the owner's |
| O2 | `--install` and `--uninstall` for the logon task (and, since it is the same place, the notifier and Dreaming tasks, which `docs/PROACTIVITY_DESIGN.md` leaves to the owner) | tests that the registered command lines are exactly the documented ones and never contain a secret; run for real only with the owner present, then `--uninstall` checked |
| O3 (only if the dev server is too slow) | production build behind a small TLS proxy | measured against the dev server on load time and on the microphone |

## 6. What needs the owner's yes

- **Whether to build it at all**, and O1 before O2: starting by hand is not a bug, and O2 changes what runs at logon.
- **The UI server for the first version** (the development server is recommended).
- **Autostart:** a Task Scheduler task at logon is recommended; say if not.
- **Whether `--save-token` may write the token to `frontend/.env.local`** (it is the same file the owner already uses by hand).
- **Whether the launcher may also register the notifier and Dreaming**, which today the owner does themselves.

## 7. What this does not do

It does not make Diya reachable from anywhere else (`docs/PHONE_CHANNEL_DESIGN.md` is that), does not restart the computer's other programs, does not
keep running if the person logs out, and does not replace the scheduled tasks: Dreaming and the notifier stay separate short jobs, because that
is what lets one fail without taking the API with it.
