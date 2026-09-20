import json
import os
import sys
from datetime import datetime, timezone

from openai import OpenAI

NOTES_DIR = "sample_notes"
STATE_FILE = "watcher_state.json"
CONTEXT_FILE = "proactive_context.txt"
LOG_FILE = "watcher_log.txt"

# Running headless via Task Scheduler (pythonw.exe -- no console at all) means print()
# has no real stdout to write to and would crash. Redirect to a real file explicitly,
# before anything else runs, so this works the same whether there's a console or not --
# and as a bonus, this is now a persistent log instead of output that just vanishes.
_log = open(LOG_FILE, "a", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log
print(f"\n--- run at {datetime.now(timezone.utc).isoformat()} ---")

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def load_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(seen), f)


def summarize(text):
    response = client.chat.completions.create(
        model="qwen2.5:3b",
        messages=[
            {
                "role": "user",
                "content": (
                    "Below, in quotes, is a personal note written by the user. Summarize what "
                    "THE USER wrote, in one short sentence, from the user's own perspective. "
                    "Do not mention yourself or any model name. Start with exactly: New note:\n\n"
                    f'Note: "{text.strip()}"'
                ),
            }
        ],
    )
    return response.choices[0].message.content


def run_cycle():
    """One check. A real scheduler calls this repeatedly -- this script never loops itself."""
    seen = load_seen()
    current = set(os.listdir(NOTES_DIR))
    new_files = current - seen

    if not new_files:
        print("Nothing new.")
        return

    summaries = []
    for filename in sorted(new_files):
        with open(os.path.join(NOTES_DIR, filename)) as f:
            text = f.read()
        try:
            summary = summarize(text)
        except Exception as exc:
            # Ollama might not be up yet (e.g. right after a reboot) -- don't crash the
            # scheduled task and don't mark anything "seen." Leave it all for the next
            # cycle, 15 minutes later, instead of silently losing it.
            print(f"[error] Could not reach the model ({exc}). Will retry next cycle.")
            return
        print(f"[new] {filename}: {summary}")
        summaries.append(summary)

    with open(CONTEXT_FILE, "a") as ctx:
        for summary in summaries:
            ctx.write(summary + "\n")

    save_seen(current)


if __name__ == "__main__":
    run_cycle()
