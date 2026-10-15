import contextlib
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone

from openai import OpenAI

import diya_checks
import diya_config
import diya_db
import diya_intent


SOURCE_JUDGE_CHARS = 600  # how much of the person's message the privacy question is asked about
DREAM_MESSAGE_CHARS = 4000  # how much of one message of the person's Dreaming reads: the rest of a very long one is not looked at
FORGET_MATCH_MIN = 0.6  # the share of the words of a "forget that ..." that a fact must contain, at least, to be taken as what is meant
FORGET_MATCH_MARGIN = 0.2  # and how far the best fact must stand above the next, or it is not clear which is meant and nothing is forgotten
LIVE_POSITION_BASE = 1000  # where the slots of facts read live start: far above any batch's own (a batch is capped well below a thousand facts)

EXTRACTION_PROMPT = (
    "Below are things a user said recently. Extract any genuine NEW facts about their "
    "real life -- preferences, ongoing situations, people/pets/things mentioned, tasks. "
    "IGNORE casual greetings, small talk, test messages, and anything with no real "
    "personal content ('hey', 'quick check', trivia questions, etc.). Return ONLY the "
    "new facts as short bullet points, one per line, nothing else. If a fact is about a "
    "specific person the user named -- not the user themselves -- end that line with the "
    "person's name in square brackets, exactly as the user wrote it, for example "
    "'- sister Maya is visiting in May [Maya]'. Leave the brackets off a fact that is "
    "about the user, or names no particular person. If there are no genuine new facts, "
    "return exactly: NONE\n\n"
)


def first_batch(messages, max_chars):
    """The first of `messages` (oldest first) that Dreaming reads in one pass, as a new list: every message from the start up to the point
    where the person's own messages come to `max_chars` (each counted at most DREAM_MESSAGE_CHARS), and always up to the first message of
    the person's, however long, so a pass always makes progress. What is left waits for the next pass. `max_chars` 0 or less reads everything."""
    if max_chars <= 0:
        return list(messages)
    taken, used, seen_user = [], 0, False
    for message in messages:
        if message["role"] == "user":
            cost = min(len(message["content"]), DREAM_MESSAGE_CHARS)
            if seen_user and used + cost > max_chars:
                break
            used += cost
            seen_user = True
        taken.append(message)
    return taken


def _is_message_id(value):
    return isinstance(value, int) and not isinstance(value, bool)  # True == 1 in Python, but is no id


class Dreamer:
    """One memory-consolidation pass, bound to one config (database, state file, review queue).

    Nothing is opened or connected until it's used, so importing this module -- or building
    a Dreamer -- has no side effects. The state, queue and log locations come from DIYA_*
    settings, defaulting to the same relative files as before.

    Dreaming only ever stages: what it extracts is queued in a JSONL file for review, one
    record per extraction, and nothing it writes is read by the model. Reviewing the queue
    is diya_review.py's job (docs/STAGE2_DESIGN.md). It used to have a "direct" mode that
    appended straight to the profile; that was retired in Stage 2 unit 5.
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

    # Every file Dreaming writes is UTF-8 with LF line endings: text-mode writes on Windows
    # translate "\n" to CRLF, which once left a file with mixed endings.
    def load_last_dreamed_id(self):
        if os.path.exists(self.config.dream_state_path):
            with open(self.config.dream_state_path, encoding="utf-8") as f:
                return json.load(f)["last_message_id"]
        return 0

    def save_last_dreamed_id(self, message_id):
        with open(self.config.dream_state_path, "w", encoding="utf-8", newline="\n") as f:
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
        new_messages = first_batch(self.store.get_messages_since(last_id), self.config.dream_batch_chars)

        # Only the user's own statements teach us real facts -- assistant replies don't.
        user_messages = [m for m in new_messages if m["role"] == "user"]

        if not user_messages:
            print("Nothing new to dream about.")
            return

        # What memory already read the moment it was said (unit A4) is not read a second time; and with automatic memory on, a message that only
        # asks Diya something is not read at all (diya_intent.only_asks: handed only such messages the model invents facts from them). If that was
        # everything, the pass is over and the checkpoint moves on, or one such message at the start of a batch would hold up all that follows it.
        left_out = self.store.captured_message_ids([m["id"] for m in user_messages])
        if self.config.auto_memory:
            left_out |= {m["id"] for m in user_messages if diya_intent.only_asks(m["content"])}
        if left_out:
            user_messages = [m for m in user_messages if m["id"] not in left_out]
            if not user_messages:
                self.save_last_dreamed_id(new_messages[-1]["id"])
                print("Everything new was already read live, or only asks something.")
                return

        first_message_id, last_message_id = new_messages[0]["id"], new_messages[-1]["id"]

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
        try:
            response = self._ask_for_facts([m["content"] for m in user_messages])
        except Exception as exc:
            print(f"[error] Could not reach the model ({exc}). Will retry next cycle.")
            return

        new_facts = response.choices[0].message.content.strip()
        self._finish_staged(new_facts, first_message_id, last_message_id)

    def _ask_for_facts(self, texts):
        """The model's answer to "what new facts are in these messages of the person's?" (`texts`, oldest first, each read only to
        DREAM_MESSAGE_CHARS). Raises what the client raises."""
        conversation_text = "\n".join(f"- {text[:DREAM_MESSAGE_CHARS]}" for text in texts)
        return self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "user", "content": EXTRACTION_PROMPT + conversation_text}],
        )

    def capture_message(self, message_id):
        """Read ONE message of the person's for facts the moment it is said and put what it finds in its lanes, without waiting for the scheduled
        pass (docs/AUTO_MEMORY_DESIGN.md, D7 and unit A4). Only with DIYA_AUTO_MEMORY on, only for a message worth reading live
        (diya_intent.is_worth_capturing), and only once: the message is marked, so the scheduled pass does not read it again. If the model cannot be
        asked the message is NOT marked and the scheduled pass reads it as it always would. Returns how many candidates it made, or None if it
        did nothing. Never raises: a failure is written where the API's console can show it."""
        if not self.config.auto_memory:
            return None
        try:
            import diya_memory

            if self.store.captured_message_ids([message_id]):
                return None
            found = [m for m in self.store.get_messages_between(message_id, message_id) if m["role"] == "user"]
            if not found:
                return None
            target = diya_intent.forget_target(found[0]["content"])
            if target is not None:
                return self._forget(message_id, target)
            if not diya_intent.is_worth_capturing(found[0]["content"]):
                return None
            try:
                answer = (self._ask_for_facts([found[0]["content"]]).choices[0].message.content or "").strip()
            except Exception as exc:  # noqa: BLE001 -- the model is down or busy: leave the message to the scheduled pass
                print(f"[capture] could not ask the model ({exc}); the scheduled pass will read message {message_id}.", file=sys.stderr)
                return None
            lines = [] if not answer or answer.upper().startswith("NONE") else [line.strip() for line in answer.split("\n") if line.strip()]
            memory = diya_memory.open_memory(self.store, self.config)
            new, _, _ = diya_memory.ingest_lines(
                memory, lines, first_message_id=message_id, last_message_id=message_id, model=self.config.model,
                staged_at=datetime.now(timezone.utc).isoformat(), actor="system", position_base=LIVE_POSITION_BASE,
            )
            self.store.mark_captured(message_id, new)
            if new:
                self._put_in_lanes(memory)
                self._refill_questions(memory)
            return new
        except Exception:  # noqa: BLE001 -- memory failing must never be what breaks a chat
            print(f"[capture] reading message {message_id} for facts failed:", file=sys.stderr)
            traceback.print_exc()
            return None

    def _forget(self, message_id, target):
        """The person asked Diya to forget ("forget that I like tea", "forget everything about Maya"): retire the accepted facts that match, which is
        what forgetting is here (nothing is deleted: the trail stays and a retired fact can be remembered again). A person is matched by name, anywhere in
        what was said; a fact by the words it shares with what was said, and only when one fact stands clearly above the rest, so that "forget that" never
        retires the wrong thing. Marks the message read. Returns how many facts were retired (0 when nothing matched)."""
        import diya_memory

        memory = diya_memory.open_memory(self.store, self.config)
        kind, what = target
        accepted = memory.facts("accepted")
        if kind == "person":
            names = {fact["person"] for fact in accepted if fact["person"]}
            named = {name for name in names if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", what, re.IGNORECASE)}
            chosen = [fact for fact in accepted if fact["person"] in named]
        else:
            wanted = diya_checks.content_words(what)
            ranked = sorted(((len(wanted & diya_checks.content_words(fact["text"])) / len(wanted) if wanted else 0.0, fact) for fact in accepted),
                            key=lambda pair: pair[0], reverse=True)
            clear = ranked and ranked[0][0] >= FORGET_MATCH_MIN and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= FORGET_MATCH_MARGIN)
            chosen = [ranked[0][1]] if clear else []
        forgotten = 0
        for fact in chosen:
            try:
                memory.decide(fact["id"], "retire", "auto", {"lane": "forget", "reasons": [f"asked_to_forget:{kind}"], "message": message_id})
                forgotten += 1
            except diya_memory.FactError:
                pass  # it was retired a moment ago by someone else: nothing to do
        self.store.mark_captured(message_id, 0)
        return forgotten

    def _refill_questions(self, memory):
        """Let the questions Diya raises herself (diya_questions, unit A5) be made from what is waiting, what has gone stale and what is coming, at their pace.
        Returns how many were made."""
        import diya_questions
        from datetime import datetime

        questions = diya_questions.Questions(self.store)
        gone = questions.retire_gone(memory, datetime.now())  # facts whose day has passed: retired by themselves (with Undo), not asked about
        if gone:
            print(f"Retired {gone} fact(s) whose day has passed (the Memory page can bring one back).")
        return questions.refill(memory, datetime.now())  # the quiet hours are about showing a question, not about making one

    def _put_in_lanes(self, memory):
        """Every candidate in its lane (diya_autonomy.apply), asking the models the policy asks. What it did, as diya_autonomy.Report."""
        import diya_autonomy

        return diya_autonomy.apply(memory, private=self._privacy_judge(), replaces=self._replace_judge(memory), corrects=self._correction_judge())

    def look_for_categories(self, now=None, max_sorted=200):
        """Each cycle, if categories are on (DIYA_CATEGORIES): sort the person's messages that are in no category yet (up to `max_sorted` a cycle, so the earlier chats are done over a few), and at most
        once a day look for a new category to suggest (diya_category_ideas), unless one is already waiting. Never stops Dreaming: a failure is written to the log and the next cycle tries again."""
        if not self.config.categories:
            return
        try:
            import threading

            import diya_categories
            import diya_category_ideas

            book = diya_categories.Book(self.store)
            todo = book.unsorted(max_sorted)
            done = 0
            for message_id, text in todo:
                with diya_categories.SORT_LOCK:
                    try:
                        diya_categories.sort(book, self.client, self.config.model, message_id, text, ())
                        done += 1
                    except diya_categories.CategoryError:
                        pass
            if done:
                print(f"Categories: sorted {done} message(s) that were in none.")
            today = (now or datetime.now()).strftime("%Y-%m-%d")
            if book.state("category_ideas_on") != today and not book.open_suggestions():
                book.set_state("category_ideas_on", today)  # one look a day, whatever it finds
                made = diya_category_ideas.suggest(book, self.client, self.config.model)
                print("Categories: I have a new category to suggest to you." if made else "Categories: nothing stood out that the categories do not cover.")
        except Exception as exc:  # noqa: BLE001 -- the log is where a headless run says what went wrong
            print(f"[error] Sorting into categories failed ({type(exc).__name__}: {exc}). What was sorted is kept; will retry next cycle.")

    def remember_on_its_own(self):
        """When DIYA_AUTO_MEMORY is on, carry what is staged into the store and put every candidate in its lane (diya_autonomy.apply):
        remembered, asked about, or not kept. Off, this does nothing, and what was staged waits for a person as it always did. It never
        stops Dreaming: a failure is written to the log and the next cycle tries again."""
        if not self.config.auto_memory:
            return
        try:
            import diya_memory

            memory = diya_memory.open_memory(self.store, self.config)
            ingested = diya_memory.ingest_queue(memory, self.config, actor="system")
            done = self._put_in_lanes(memory)
            questions = self._refill_questions(memory)
            print(
                f"Memory on its own: {done.remembered} remembered, {done.asked} to ask about, {done.never} not kept, "
                f"{done.held} held (profile full); {ingested.new} newly taken in from the staged queue"
                + (f"; {done.replaced} replaced as corrections" if done.replaced else "")
                + (f"; {questions} new questions to put to you." if questions else ".")
            )
        except Exception as exc:  # noqa: BLE001 -- the log is where a headless run says what went wrong
            print(f"[error] Memory on its own failed ({exc}). Nothing was changed past what is above; will retry next cycle.")

    def _privacy_judge(self):
        """`private(fact)` for the memory policy: the model's most cautious answer to "is this private?" about the fact and about the message of the
        person's it was taken from (what the checks recorded as its source), each message asked about once however many facts came from it."""
        import diya_autonomy  # here and not at the top: it needs diya_memory, which reaches this module

        strict, main = self.config.privacy_model or self.config.model, self.config.model
        two = strict != main and not self.config.privacy_unsure_asks  # a second, suspicious judge keeps its veto, but its "unsure" does not block (docs/AUTO_MEMORY_DESIGN.md, 8.5)
        asked = {}

        def verdict(text):
            if two:
                return diya_autonomy.privacy_of_two(self.client, strict, main, [text])
            return diya_autonomy.privacy_of(self.client, strict, [text])

        def private(fact):
            verdicts = [verdict(fact["text"])]
            for text in self._source_texts(fact):
                if text not in asked:
                    asked[text] = verdict(text)
                verdicts.append(asked[text])
            return min(verdicts, key=diya_autonomy._CAUTIOUS_FIRST.index)

        return private

    def _source_texts(self, fact):
        """The person's own messages `fact` was taken from (what the checks recorded as its source), each cut to SOURCE_JUDGE_CHARS."""
        texts = []
        for flag in fact["flags"]:
            name, _, value = flag.partition(":")
            if name == "source_message" and value.isdigit():
                texts += [m["content"][:SOURCE_JUDGE_CHARS] for m in self.store.get_messages_between(int(value), int(value)) if m["role"] == "user"]
        return texts

    def _correction_judge(self):
        """`corrects(fact)` for the memory policy: did the person's own message that the fact came from read as a correction (diya_intent.is_correction)?
        Words only, no model; the policy needs this AND the model's answer to which known fact the new one replaces."""
        return lambda fact: any(diya_intent.is_correction(text) for text in self._source_texts(fact))

    def _replace_judge(self, memory):
        """`replaces(fact)` for the memory policy: the chat model's answer to "does this replace one of the facts already known?". The known facts
        are read afresh for each question, so a fact accepted a moment ago in this same pass is one a later fact may replace."""
        import diya_autonomy

        def replaces(fact):
            if diya_autonomy.says_it_adds(self._source_texts(fact)):  # "another dog": it adds, whatever the rewritten fact looks like (see diya_autonomy._ADDS)
                return diya_autonomy.Replacement("none", None)
            return diya_autonomy.replacement_of(self.client, self.config.model, memory.facts("accepted"), fact["text"])

        return replaces

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
        diya_config.ensure_data_dir(config)
    except (diya_config.ConfigError, OSError) as exc:
        # Still record the problem, in the default log location.
        config, config_error = diya_config.Config(), exc

    with open(config.dream_log_path, "a", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            print(f"\n--- dream cycle at {datetime.now(timezone.utc).isoformat()} ---")
            if config_error is not None:
                print(f"[error] {config_error}")
                return 1
            try:
                dreamer = Dreamer(config)
                dreamer.dream_cycle()
                dreamer.remember_on_its_own()
                dreamer.look_for_categories()
            except Exception:
                traceback.print_exc()
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
