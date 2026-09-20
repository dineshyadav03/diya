import json
import os
import sys
from datetime import datetime, timezone

from openai import OpenAI

import diya_db

PROFILE_FILE = "user_profile.txt"
STATE_FILE = "dream_state.json"
LOG_FILE = "dream_log.txt"
MODEL = "qwen2.5:3b"

# Same lesson as milestone4_watcher.py, applied up front this time: running headless via
# Task Scheduler (pythonw.exe, no console) means print() has nowhere to write and would
# crash. Redirect to a real, persistent log file instead -- this is also how anyone checks
# what Dreaming has actually been doing, day to day.
_log = open(LOG_FILE, "a", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log
print(f"\n--- dream cycle at {datetime.now(timezone.utc).isoformat()} ---")

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def load_profile():
    if os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE) as f:
            return f.read().strip()
    return "(no profile yet -- this is the first dream cycle)"


def save_profile(text):
    with open(PROFILE_FILE, "w") as f:
        f.write(text.strip() + "\n")


def load_last_dreamed_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)["last_message_id"]
    return 0


def save_last_dreamed_id(message_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_message_id": message_id}, f)


def dream_cycle():
    """One consolidation pass. Meant to be run periodically (Task Scheduler, later) --
    same 'never loop itself' pattern as milestone4_watcher.py, same lesson applied from
    the start this time: don't crash or lose progress if Ollama isn't reachable."""
    last_id = load_last_dreamed_id()
    new_messages = diya_db.get_messages_since(last_id)

    # Only the user's own statements teach us real facts -- assistant replies don't.
    user_messages = [m for m in new_messages if m["role"] == "user"]

    if not user_messages:
        print("Nothing new to dream about.")
        return

    # Extraction-only, deliberately: the model never sees or has to reproduce the existing
    # profile. Two real, measured attempts at "rewrite the whole profile, keep what's still
    # valid" both silently dropped real facts in different ways -- a genuine small-model
    # reliability limit, not a wording problem. Code, not the model, is what reliably
    # preserves existing content: we only ever append, never ask for a full rewrite.
    conversation_text = "\n".join(f"- {m['content']}" for m in user_messages)

    prompt = (
        "Below are things a user said recently. Extract any genuine NEW facts about their "
        "real life -- preferences, ongoing situations, people/pets/things mentioned, tasks. "
        "IGNORE casual greetings, small talk, test messages, and anything with no real "
        "personal content ('hey', 'quick check', trivia questions, etc.). Return ONLY the "
        "new facts as short bullet points, one per line, nothing else. If there are no "
        "genuine new facts, return exactly: NONE\n\n"
        f"{conversation_text}"
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        print(f"[error] Could not reach the model ({exc}). Will retry next cycle.")
        return

    new_facts = response.choices[0].message.content.strip()
    save_last_dreamed_id(new_messages[-1]["id"])

    if not new_facts or new_facts.upper().startswith("NONE"):
        print("No genuine new facts found.")
        return

    with open(PROFILE_FILE, "a", encoding="utf-8") as f:
        f.write(new_facts + "\n")

    print("New facts appended:")
    print(new_facts)


if __name__ == "__main__":
    dream_cycle()
