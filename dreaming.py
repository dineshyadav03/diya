import contextlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone

from openai import OpenAI

import diya_config
import diya_db


def _is_message_id(value):
    return isinstance(value, int) and not isinstance(value, bool)  # True == 1 in Python, but is no id


class Dreamer:
    """One memory-consolidation pass, bound to one config (database, profile, state file).

    Nothing is opened or connected until it's used, so importing this module -- or building
    a Dreamer -- has no side effects. The profile, state and log locations come from
    DIYA_* settings, defaulting to the same relative files as before.

    By default (DIYA_DREAM_PROFILE_MODE=staged) Dreaming never writes the trusted profile:
    what it extracts is queued in a JSONL file for review, one record per extraction. The
    original behaviour -- appending straight to the profile -- remains only as the explicit
    "direct" compatibility mode.
    """

    def __init__(self, config=None, client=None, store=None):
        self.config = config or diya_config.load_config()
        self.store = store or diya_db.Store(self.config.db_path)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(base_url=self.config.ollama_url, api_key="ollama")
        return self._client

    def load_profile(self):
        if os.path.exists(self.config.profile_path):
            with open(self.config.profile_path) as f:
                return f.read().strip()
        return "(no profile yet -- this is the first dream cycle)"

    def save_profile(self, text):
        with open(self.config.profile_path, "w") as f:
            f.write(text.strip() + "\n")

    def load_last_dreamed_id(self):
        if os.path.exists(self.config.dream_state_path):
            with open(self.config.dream_state_path) as f:
                return json.load(f)["last_message_id"]
        return 0

    def save_last_dreamed_id(self, message_id):
        with open(self.config.dream_state_path, "w") as f:
            json.dump({"last_message_id": message_id}, f)

    # ---- the review queue (staged mode) ----
    def staged_batches(self):
        """Every well-formed record in the pending file, oldest first. A torn or corrupt line
        (e.g. a crash mid-write) is skipped: it is not a staged batch."""
        try:
            with open(self.config.dream_pending_path, encoding="utf-8") as f:
                lines = f.read().split("\n")
        except FileNotFoundError:
            return []
        records = []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(record, dict)
                and _is_message_id(record.get("first_message_id"))
                and _is_message_id(record.get("last_message_id"))
                and record["last_message_id"] >= record["first_message_id"]
            ):
                records.append(record)
        return records

    def _find_staged(self, first_message_id):
        for record in self.staged_batches():
            if record["first_message_id"] == first_message_id:
                return record
        return None

    def _append_pending(self, record):
        """Append one record as one line and force it to disk before returning."""
        # \u2028/\u2029 are legal inside JSON strings but split lines in some readers.
        line = json.dumps(record, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        path = self.config.dream_pending_path
        prefix = ""
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        prefix = "\n"  # an earlier write was torn: end that fragment so this record has its own line
        except FileNotFoundError:
            pass
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(prefix + line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def dream_cycle(self):
        """One consolidation pass. Meant to be run periodically (Task Scheduler, later) --
        same 'never loop itself' pattern as milestone4_watcher.py, same lesson applied from
        the start this time: don't crash or lose progress if Ollama isn't reachable."""
        last_id = self.load_last_dreamed_id()
        new_messages = self.store.get_messages_since(last_id)

        # Only the user's own statements teach us real facts -- assistant replies don't.
        user_messages = [m for m in new_messages if m["role"] == "user"]

        if not user_messages:
            print("Nothing new to dream about.")
            return

        staged = self.config.dream_profile_mode == "staged"
        first_message_id, last_message_id = new_messages[0]["id"], new_messages[-1]["id"]

        if staged:
            # A batch always starts at the first message after the checkpoint, and batches never
            # overlap, so a record with this first id means the batch was staged but the process
            # died before the checkpoint moved. Finish that step instead of extracting again --
            # this is what makes a retry idempotent.
            try:
                already = self._find_staged(first_message_id)
            except OSError as exc:
                # Can't tell whether this batch was staged already, so stage nothing this cycle.
                print(f"[error] Could not read the review queue ({exc}). Checkpoint left unchanged; will retry next cycle.")
                return
            if already is not None:
                self.save_last_dreamed_id(already["last_message_id"])
                print(
                    f"Messages {already['first_message_id']}-{already['last_message_id']} were already "
                    "staged; checkpoint advanced, nothing staged again."
                )
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
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            print(f"[error] Could not reach the model ({exc}). Will retry next cycle.")
            return

        new_facts = response.choices[0].message.content.strip()

        if staged:
            self._finish_staged(new_facts, first_message_id, last_message_id)
        else:
            self._finish_direct(new_facts, last_message_id)

    def _finish_staged(self, new_facts, first_message_id, last_message_id):
        if not new_facts or new_facts.upper().startswith("NONE"):
            self.save_last_dreamed_id(last_message_id)
            print("No genuine new facts found.")
            return

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "first_message_id": first_message_id,
            "last_message_id": last_message_id,
            "model": self.config.model,
            "facts": [line.strip() for line in new_facts.split("\n") if line.strip()],
        }
        # Stage first, checkpoint second: if staging fails the checkpoint stays put and the same
        # batch is simply tried again next cycle; if we die between the two, _find_staged()
        # notices the record on the next cycle and only moves the checkpoint.
        try:
            self._append_pending(record)
        except Exception as exc:
            print(f"[error] Could not stage the new facts ({exc}). Checkpoint left unchanged; will retry next cycle.")
            return
        self.save_last_dreamed_id(last_message_id)

        print("New facts staged for review (not added to profile):")
        print(new_facts)

    def _finish_direct(self, new_facts, last_message_id):
        """The original behaviour, unchanged: checkpoint first, then append to the profile."""
        self.save_last_dreamed_id(last_message_id)

        if not new_facts or new_facts.upper().startswith("NONE"):
            print("No genuine new facts found.")
            return

        with open(self.config.profile_path, "a", encoding="utf-8") as f:
            f.write(new_facts + "\n")

        print("New facts appended:")
        print(new_facts)


def main():
    """The scheduled entry point: one cycle, with all output going to the log file.

    Same lesson as milestone4_watcher.py, applied up front: running headless via Task Scheduler
    (pythonw.exe, no console) means print() has nowhere to write and would crash. So stdout and
    stderr are redirected to a real, persistent log file for the duration of the run -- this is
    also how anyone checks what Dreaming has actually been doing, day to day. Failures (a bad
    setting, a crash mid-cycle) are written to that same log, since there's nowhere else for
    them to go.
    """
    try:
        config, config_error = diya_config.load_config(), None
    except diya_config.ConfigError as exc:
        # Still record the problem, in the default log location.
        config, config_error = diya_config.Config(), exc

    with open(config.dream_log_path, "a", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            print(f"\n--- dream cycle at {datetime.now(timezone.utc).isoformat()} ---")
            if config_error is not None:
                print(f"[error] {config_error}")
                return 1
            try:
                Dreamer(config).dream_cycle()
            except Exception:
                traceback.print_exc()
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
