# Phase 1: try the harness in isolation, against the local model (a runbook for the owner; 2026-10-21)

**Why the owner runs it, not Claude.** Building the harness installs several hundred packages written by other people and runs their install steps, and the harness itself can run commands a model writes. Claude does not execute downloaded
third-party code, even when asked (the rule that protects this computer, stated to the owner on 2026-10-21). So this page is what to run, what to look at, and what to send back. **None of the commands below has been run by Claude;
they are written from the harness's README and may need small changes: paste any error and they will be fixed.**

## Safe setup (do not skip)

* Run it **inside a container or a throwaway Windows user**, never in your normal account. No file of yours goes in; the only thing it can see is the empty `work` folder you give it.
* Give it **no credentials**: no Google sign-in, no tokens, no API keys of any kind (the model is local, so none are needed; its README says a route with no key may need a placeholder such as `ollama`).
* Switch **off** every tool that acts on the computer: shell commands, computer control, browser control. Ask it questions only; it must not touch files.
* Close other programs first: the laptop has about 1.4 GB of memory free, and a container plus a model will make everything slow.

## Steps

1. Docker Desktop (you have it): start a Node 22 container with an empty work folder and the harness files mounted read-only, e.g. `docker run --rm -it -v C:\Users\dines\dsh-copy\deepseek-harness:/src:ro -v C:\Users\dines\dsh-work:/work node:22 bash` (create `C:\Users\dines\dsh-work` first, empty). The copy in the project (`harness/`) is the same files.
2. Inside the container: copy `/src` to `/work/h` (so nothing is written to your copy), `cd /work/h`, then follow its README: `pnpm install`, `pnpm run build`, `pnpm dsh web`. (If `pnpm` is missing, `corepack enable` first.)
3. In its settings, add a model route that points at your local Ollama: base address `http://host.docker.internal:11434/v1`, model `diya-chat`, key `ollama`. (If the container cannot reach it, tell Claude the exact error; do **not** open Ollama to the network to fix it.)
4. Turn off the shell, computer-control and browser tools in its settings; leave its approval mode on **ask for everything**.

## What to try and write down (ten questions, one line each)

| # | Ask | Write down: how long the first words took, whether it answered, whether it made up anything, whether it tried a tool |
|---|---|---|
| 1 | "hey" | |
| 2 | "what is 17 times 23?" | |
| 3 | "explain in two lines what a database index is" | |
| 4 | "remind me to call the bank tomorrow" (it has no reminders: does it say so, or pretend?) | |
| 5 | "what's the weather in Pune?" (does it say it cannot, or invent?) | |
| 6 | "summarise this: " plus a paragraph you paste | |
| 7 | "list three things to do on a rainy Sunday" | |
| 8 | a question that needs the previous answer ("make that shorter") | |
| 9 | a long message (about 300 words pasted) then "what did I ask you?" | |
| 10 | "what time is it?" | |

## What decides the next step

* **It cannot drive the model** (no answer, an error at once, only gibberish, or each reply takes several minutes): stop here. The harness is too heavy for this computer and model, and the plan moves to porting single pieces (phase 3) instead. That is a fine result, and it costs nothing more.
* **It works but badly** (answers, but invents things Diya's code would not, or tries tools it should not): note which; the bridge in phase 2 is exactly what fixes that.
* **It works well**: send the ten lines and the time of the first reply, and phase 2 (the bridge to Diya's memory and approvals) starts.

## What to send back

The ten lines, the first-word time for question 1 (cold) and question 2 (warm), the number shown for context use if it shows one, and any error text.
