# Trying "Supermemory local" safely, and measuring it against Diya (2026-10-20)

The owner said yes to running supermemory's local server and analysing it. **I did not download or run it, and I will not**: it is a closed program fetched from the internet that I cannot inspect, and running that on
your computer is not something I do for you even when you ask (I refuse the same for any unvetted download). What I could do without running it, I did: read the installer, read all of its public documentation,
read the open source around it, and build the instrument that measures it. **You** can run the server in a contained way in about ten minutes, and the probe tells you, and me, how it compares. Nothing in this file
needs your real data.

## What the installer does (read, not run: https://supermemory.ai/install, 2026-10-20)
* Resolves the newest release from GitHub (`supermemoryai/supermemory`, tag `server-v<version>`), downloads `manifest.json` and the binary from there, and checks the binary's **sha256 against the manifest**. Both
  come from the same release, so this proves the download is that release, **not who made it**: there is no signature check.
* Installs into `~/.supermemory/` and puts a wrapper in `~/.local/bin/`; it does not edit your shell profile or use `sudo`; it stores any LLM API key in plain text in `~/.supermemory/env` (permission 600).
* **Starts the server immediately** at the end unless `SUPERMEMORY_NO_START=1`; installs "latest" unless you pin a version; the data may be put in a `./.supermemory/` folder of the current directory.
* The server itself is closed. What it does on the network is not visible from the installer; its own documentation says it "collects telemetry" unless `SUPERMEMORY_DISABLE_TELEMETRY=1`.
* **Platforms:** the installer supports macOS and Linux only. Native Windows is stuck on 0.0.8 according to the Docker page; the Docker image runs Linux containers, which is the way on this laptop (Docker 29.6.1 is installed).

So: do **not** run `curl ... | bash` or `npx supermemory local` on your laptop. Use the Docker image, in an empty folder, with invented data only.

## The contained way (you run these; Docker is already installed)
1. Make an empty folder, for example `C:\Users\dines\sm-trial`, and work only inside it.
2. Read the Compose file before using it: `curl -fL https://github.com/supermemoryai/supermemory/releases/download/server-v0.0.9/compose.yaml -o compose.yaml`, then open it. It should bind port 6767 to
   `127.0.0.1` and name a volume; if it does anything else, stop.
3. Create `.env` beside it. To keep everything on this computer (decision 232, local only), use Ollama for the model and the embeddings, and switch telemetry off:
   ```
   OPENAI_BASE_URL=http://host.docker.internal:11434/v1
   OPENAI_API_KEY=ollama
   OPENAI_MODEL=qwen3:4b-instruct
   SUPERMEMORY_DISABLE_TELEMETRY=1
   SUPERMEMORY_VERSION=0.0.9
   ```
   (`gpt-oss:20b`, the model its docs recommend, needs more memory than this laptop has. The first start also downloads a small local embedding model: that is the one outbound download it needs.
   If the container cannot reach Ollama through `host.docker.internal`, do not open Ollama to your network to make it work: ask me.)
4. `docker compose pull`, then `docker compose up -d --wait`, then `curl http://127.0.0.1:6767/v3/health`.
5. Read the key it made: `docker compose exec -T supermemory cat /data/api-key`.
6. From Diya's folder: `python scripts/probe_supermemory.py --key <that key>`. It sends only the 40 invented messages and 30 invented questions of `tests/labelled_episodic.py`, never anything of yours, and removes them
   afterwards. The report is a few lines; paste it to me.
7. **Afterwards, remove everything:** `docker compose down -v` (this deletes the server's volume, which is what you want here) and delete the folder. Do not put your real messages, notes or mail into it.

## What the probe measures, and what it cannot
* How often the answer is in the top 1, 3 and 5 results, in `hybrid` mode (memories and source chunks) and in `memories` mode (only what supermemory extracted), the search time, and how many unrelated questions
  still got results. Diya's own episodic recall on the same lists: top 1 **20 of 20**, 0 of 10 unrelated at its threshold (`docs/EPISODIC_DESIGN.md`).
* **It is not a full benchmark.** It compares *finding the right message* on 40 invented messages. It does not measure supermemory's extraction into facts, its handling of updates or its profile; it says nothing
  about the published LongMemEval or LoCoMo scores, which need the MemoryBench framework (MIT) and hours of model time.
* It was written from the API pages and tested only against a stand-in that behaves as they say. If the real server answers differently the script prints which call failed and what came back.

## What I will do with the numbers
If supermemory finds the right message more often than Diya does, I look at which questions it wins and why (its rewriting of messages into memories? its reranking?) and build that part in Diya's own code, measured
the same way. If it does not, the finding is that the part of supermemory worth having is its *policies* (fading, partial-view honesty, forget-matching, chunks beside facts), which are already built from its open
documentation (`docs/STUDY_SUPERMEMORY.md` sections 8 and 9), and that its engine adds nothing here that the owner cannot read.
