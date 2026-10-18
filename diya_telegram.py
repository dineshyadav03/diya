"""Talking to Diya from Telegram (docs/TELEGRAM_DESIGN.md, unit P4). OFF unless DIYA_TELEGRAM=1, and it needs a bot token the owner made themselves.

    python diya_telegram.py --set-token   save the bot token (asked for without showing it) in its own file
    python diya_telegram.py --pair        make a one-time code (valid 10 minutes); send it to the bot from your own Telegram account
    python diya_telegram.py --unpair      forget the owner: after this the bot answers nobody
    python diya_telegram.py --status      say whether it is switched on, has a token, and is paired; starts nothing
    python diya_telegram.py               run: ask Telegram for new messages and answer the paired owner's, until Ctrl+C

Only the paired owner, in a private chat, in plain text, is ever answered; everything else is dropped without an answer. The answer comes from the same Agent.ask as the chat page. Nothing here
can approve, reject or change anything: an action Diya proposes is decided in the app. What is typed here and what Diya answers pass through Telegram, which can read both.

Everything that touches the world (the HTTPS request, the clock, the sleep, the model) is passed in, so the whole of it is tested against a scripted stand-in for Telegram, never the real thing.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import diya_config
from diya_db import Store
from diya_memory import printable

API_HOST = "https://api.telegram.org"
POLL_SECONDS = 30
MAX_CHARS_IN = 2000
MAX_CHARS_OUT = 4000
MAX_PER_HOUR = 30
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0, O, 1, I: nothing that can be misread
CODE_LENGTH = 12
CODE_LIFETIME = timedelta(minutes=10)
MAX_ATTEMPTS = 5
BACKOFF_FIRST, BACKOFF_MAX = 5, 60
TOKEN_SHAPE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,50}")
EXIT_OK, EXIT_FAILED, EXIT_UNUSABLE = 0, 1, 2

# What the owner (and only the owner) is told. Fixed words: never an exception's text, never anything a message said.
PAIRED = "Paired. From now on I answer only you, here."
UNSUPPORTED = "I only read plain text that you type here. Photos, files, voice messages and stickers are not read."
FORWARDED = "I don't read forwarded messages, replies to other people's messages or messages from other bots. Type it yourself."
TOO_LONG = f"That message is longer than {MAX_CHARS_IN} characters. Please send a shorter one."
COMMANDS = "Commands don't work here. Approvals, settings and pairing are in the Diya app, or on the computer it runs on."
LIMITED = f"That is more than {MAX_PER_HOUR} messages in an hour. I'll answer again when there is room."
FAILED = "I couldn't answer that just now."
EMPTY = "(no reply)"

# Telegram's own names for "this was not typed by the person in this chat": the old and the new spellings, because they changed.
NOT_TYPED_HERE = ("forward_origin", "forward_from", "forward_from_chat", "forward_date", "forward_sender_name", "forward_signature", "is_automatic_forward", "via_bot",
                  "sender_chat", "external_reply", "quote", "story", "business_connection_id")


class TelegramError(RuntimeError):
    """Telegram could not be reached or refused a request. The text names the kind of failure and nothing else: never the token, an address or a message."""


# ---- the notes this program keeps -----------------------------------------------------------------------------------------------

class State:
    """The `telegram_state` table: a few named values."""

    def __init__(self, store):
        self.store = store

    def get(self, key, default=None):
        conn = self.store.connect()
        try:
            row = conn.execute("SELECT value FROM telegram_state WHERE key = ?", (key,)).fetchone()
        finally:
            conn.close()
        return row[0] if row else default

    def set(self, key, value):
        conn = self.store.connect()
        try:
            conn.execute("INSERT INTO telegram_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
            conn.commit()
        finally:
            conn.close()

    def delete(self, *keys):
        conn = self.store.connect()
        try:
            for key in keys:
                conn.execute("DELETE FROM telegram_state WHERE key = ?", (key,))
            conn.commit()
        finally:
            conn.close()


# ---- pairing ---------------------------------------------------------------------------------------------------------------------

def make_code(choose=secrets.choice):
    """A fresh one-time code: CODE_LENGTH characters from CODE_ALPHABET, shown in groups of four."""
    raw = "".join(choose(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, CODE_LENGTH, 4))


def normalise_code(text):
    """What was typed, as a code would be compared: capitals, no spaces or dashes."""
    return "".join(ch for ch in text.upper() if ch not in " -\t\r\n")


def hash_code(code):
    return hashlib.sha256(normalise_code(code).encode("utf-8")).hexdigest()


class Pairing:
    """Who the owner is, and the one-time code that makes someone the owner. Only a hash of the code is kept."""

    def __init__(self, state):
        self.state = state

    def owner(self):
        value = self.state.get("owner_id")
        return int(value) if value is not None else None

    def start(self, now, code=None):
        """Make a code that is good for CODE_LIFETIME and return it (shown once). Refuses when there is already an owner."""
        if self.owner() is not None:
            raise TelegramError("already paired: run --unpair first")
        code = code or make_code()
        self.state.set("pair_hash", hash_code(code))
        self.state.set("pair_expires", (now + CODE_LIFETIME).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.state.set("pair_attempts", 0)
        return code

    def unpair(self):
        self.state.delete("owner_id", "pair_hash", "pair_expires", "pair_attempts")

    def _clear_code(self):
        self.state.delete("pair_hash", "pair_expires", "pair_attempts")

    def waiting(self, now):
        """Is there a code that has not expired and has not been used up by wrong guesses?"""
        expires = self.state.get("pair_expires")
        return self.state.get("pair_hash") is not None and expires is not None and now.strftime("%Y-%m-%dT%H:%M:%SZ") < expires

    def try_code(self, text, sender_id, now):
        """Is `text` the code? If so the sender becomes the owner and the code is gone: True. A wrong guess is counted, and MAX_ATTEMPTS of them void the code."""
        if self.owner() is not None:
            return False
        if not self.waiting(now):
            if self.state.get("pair_hash") is not None:
                self._clear_code()  # it has expired
            return False
        if hmac.compare_digest(hash_code(text), self.state.get("pair_hash")):
            self.state.set("owner_id", sender_id)
            self._clear_code()
            return True
        attempts = int(self.state.get("pair_attempts", 0)) + 1
        if attempts >= MAX_ATTEMPTS:
            self._clear_code()
        else:
            self.state.set("pair_attempts", attempts)
        return False


# ---- Telegram ----------------------------------------------------------------------------------------------------------------------

def post_json(url, payload, timeout):
    """POST `payload` as JSON and return (status, parsed body), or (None, None) if there was no usable answer. No redirect is followed. Nothing about the request is ever said."""
    import httpx

    try:
        answer = httpx.post(url, json=payload, timeout=timeout, follow_redirects=False)
        try:
            body = answer.json()
        except ValueError:
            body = None
        return answer.status_code, body
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return None, None


def describe_failure(method, status):
    """What went wrong with a request, by its kind. The words are fixed: Telegram's own description, the address (which holds the token) and the request are never repeated."""
    if status is None:
        return f"no answer from Telegram ({method})"
    if status == 401:
        return "Telegram refused the bot token (run --set-token again)"
    if status == 409:
        return "another program is already reading this bot's messages"
    if status == 429:
        return "Telegram asked to slow down"
    return f"Telegram answered {method} with status {status}"


class TelegramApi:
    """The three calls this program makes. `post(url, payload, timeout)` returns (status, body); it is passed in so a test can stand in for Telegram."""

    def __init__(self, token, post=post_json, host=API_HOST):
        self._token, self._post, self._host = token, post, host

    def _call(self, method, payload, timeout=15):
        status, body = self._post(f"{self._host}/bot{self._token}/{method}", payload, timeout)
        if status != 200 or not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramError(describe_failure(method, status))
        return body.get("result")

    def get_me(self):
        result = self._call("getMe", {})
        if not isinstance(result, dict) or not isinstance(result.get("id"), int):
            raise TelegramError("Telegram's answer to getMe was not what a bot's is")
        return result

    def get_updates(self, offset, timeout):
        result = self._call("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]}, timeout=timeout + 10)
        if not isinstance(result, list):
            raise TelegramError("Telegram's answer to getUpdates was not a list")
        return result

    def send_message(self, chat_id, text):
        self._call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "link_preview_options": {"is_disabled": True}})


# ---- the bridge --------------------------------------------------------------------------------------------------------------------

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Bridge:
    """Decides what to do with one update. `ask(text)` returns Diya's answer; `api.send_message` sends one; `clock()` is an aware UTC datetime. `handle` returns a word for what it did
    (never any text), which is also all that is ever said about an update: "dropped (not the owner)" and the like."""

    def __init__(self, state, api, ask, clock=None, say=print, bot_id=None):
        self.state, self.api, self.ask, self.say, self.bot_id = state, api, ask, say, bot_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.pairing = Pairing(state)
        self._recent = deque()
        self._told_limit = False

    def _drop(self, why):
        self.say(f"telegram: dropped ({why})")
        return f"dropped:{why}"

    def _send(self, chat_id, text):
        try:
            self.api.send_message(chat_id, text)
        except TelegramError as exc:
            self.say(f"telegram: could not send ({exc})")
            return False
        return True

    def _reply(self, chat_id, text, outcome):
        return outcome if self._send(chat_id, text) else "unsent"

    def _within_rate(self, now):
        while self._recent and now - self._recent[0] >= timedelta(hours=1):
            self._recent.popleft()
        if len(self._recent) >= MAX_PER_HOUR:
            return False
        self._recent.append(now)
        self._told_limit = False
        return True

    def handle(self, update):
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            return self._drop("not a new message")
        chat, sender = message.get("chat"), message.get("from")
        if not isinstance(chat, dict) or chat.get("type") != "private":
            return self._drop("not a private chat")
        if not isinstance(sender, dict) or sender.get("is_bot") or not _is_int(sender.get("id")) or chat.get("id") != sender["id"]:
            return self._drop("not a person in their own chat")
        sender_id, now, text = sender["id"], self.clock(), message.get("text")
        owner = self.pairing.owner()
        if owner is None:  # the only thing an unpaired sender can do is send the code, as plain text typed by themselves
            if isinstance(text, str) and not any(key in message for key in NOT_TYPED_HERE) and self.pairing.try_code(text, sender_id, now):
                return self._reply(sender_id, PAIRED, "paired")
            return self._drop("not paired")
        if sender_id != owner:
            return self._drop("not the owner")
        # ---- from here on it is the owner, and the answers are fixed words ----
        if any(key in message for key in NOT_TYPED_HERE) or not self._reply_is_to_us(message.get("reply_to_message")):
            return self._reply(sender_id, FORWARDED, "replied:not typed here")
        if not isinstance(text, str) or not text.strip():
            return self._reply(sender_id, UNSUPPORTED, "replied:not text")
        if len(text) > MAX_CHARS_IN:
            return self._reply(sender_id, TOO_LONG, "replied:too long")
        if text.lstrip().startswith("/"):
            return self._reply(sender_id, COMMANDS, "replied:command")
        if not self._within_rate(now):
            if self._told_limit:
                return self._drop("over the hourly limit")
            self._told_limit = True
            return self._reply(sender_id, LIMITED, "replied:limited")
        try:
            answer = self.ask(text)
        except Exception as exc:  # the model, the database, anything: the owner gets a fixed line and the log gets the kind of failure
            self.say(f"telegram: could not answer ({printable(type(exc).__name__)})")
            return self._reply(sender_id, FAILED, "failed")
        answer = answer.strip()[:MAX_CHARS_OUT] if isinstance(answer, str) else ""
        return self._reply(sender_id, answer or EMPTY, "answered")

    def _reply_is_to_us(self, replied_to):
        """No reply is fine; a reply is fine only to a message this bot sent."""
        if replied_to is None:
            return True
        if not isinstance(replied_to, dict) or not isinstance(replied_to.get("from"), dict):
            return False
        author = replied_to["from"]
        return bool(author.get("is_bot")) and (self.bot_id is None or author.get("id") == self.bot_id)


class AgentAsker:
    """The chat page's turn, for one thread called by number and kept in the notes: the history, the new message saved, the answer saved."""

    def __init__(self, agent, state):
        self.agent, self.state = agent, state

    def __call__(self, text):
        store = self.agent.store
        thread_id = store.main_thread()  # the phone and the page are one conversation (docs/ONE_CHAT_DESIGN.md)
        saved = store.get_messages(thread_id)
        history = self.agent.with_profile([{"role": m["role"], "content": m["content"]} for m in saved])
        message_id = store.add_message(thread_id, "user", text)
        history.append({"role": "user", "content": text})
        answer, _ = self.agent.ask(history, thread_id=thread_id, message_id=message_id)
        store.add_message(thread_id, "assistant", answer)
        return answer


# ---- running -----------------------------------------------------------------------------------------------------------------------

def run(state, api, bridge, *, sleep=time.sleep, say=print, polls=None):
    """Ask Telegram for new messages, again and again. The update's number is saved BEFORE it is handled, so a crash loses that one message and never handles it twice.
    A failure to reach Telegram waits BACKOFF_FIRST seconds, then longer each time up to BACKOFF_MAX. `polls` stops it after that many asks (tests)."""
    backoff, asked = BACKOFF_FIRST, 0
    while polls is None or asked < polls:
        asked += 1
        try:
            updates = api.get_updates(int(state.get("offset", 0)), POLL_SECONDS)
            backoff = BACKOFF_FIRST
        except TelegramError as exc:
            say(f"telegram: {exc}; trying again in {backoff} seconds")
            sleep(backoff)
            backoff = min(BACKOFF_MAX, backoff * 2)
            continue
        for update in updates:
            number = update.get("update_id") if isinstance(update, dict) else None
            if not _is_int(number) or number < int(state.get("offset", 0)):
                continue
            state.set("offset", number + 1)
            bridge.handle(update)


def read_token(path):
    """The bot token from its file, or a TelegramError that says what to do."""
    try:
        with open(path, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        raise TelegramError("there is no bot token yet: run python diya_telegram.py --set-token") from None
    if not TOKEN_SHAPE.fullmatch(token):
        raise TelegramError("the bot token file does not hold a token (run --set-token again)")
    return token


def save_token(path, token):
    """Keep the token in its own file, readable by its owner only. Raises TelegramError if it is not shaped like a bot token."""
    token = token.strip()
    if not TOKEN_SHAPE.fullmatch(token):
        raise TelegramError("that is not shaped like a bot token (digits, a colon, then letters and digits)")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.new"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(token + "\n")
    os.replace(temporary, path)


# ---- the command line --------------------------------------------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="diya_telegram.py", description="Talk to Diya from Telegram (off unless DIYA_TELEGRAM=1).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--set-token", action="store_true", help="save the bot token, asked for without showing it")
    group.add_argument("--pair", action="store_true", help="make a one-time code to send to the bot from your own account")
    group.add_argument("--unpair", action="store_true", help="forget the owner; the bot then answers nobody")
    group.add_argument("--status", action="store_true", help="say whether it is on, has a token and is paired")
    return parser


def main(argv=None, config=None, out=None, secret=None, post=post_json, clock=None, make_asker=None, sleep=time.sleep, polls=None):
    out = sys.stdout if out is None else out

    def say(line):
        print(line, file=out)

    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_UNUSABLE
    try:
        config = config or diya_config.load_config()
        diya_config.ensure_data_dir(config)
    except (diya_config.ConfigError, OSError) as exc:
        say(f"diya_telegram: {exc}")
        return EXIT_UNUSABLE
    import diya_backup

    if not diya_backup.guard_migration(config, say=lambda line: say(f"diya_telegram: {line}")):
        return EXIT_UNUSABLE
    clock = clock or (lambda: datetime.now(timezone.utc))
    if args.set_token:
        try:
            save_token(config.telegram_token_path, secret() if secret else getpass.getpass("Bot token (not shown): "))
        except (TelegramError, OSError) as exc:
            say(f"diya_telegram: {printable(exc, 200)}")
            return EXIT_UNUSABLE
        say("Saved the bot token. It is not shown or logged anywhere.")
        return EXIT_OK
    if not config.telegram:
        say("diya_telegram: Telegram is off (DIYA_TELEGRAM=1 turns it on)")
        return EXIT_UNUSABLE
    try:
        store = Store(config.db_path)
        state = State(store)
        pairing = Pairing(state)
        if args.pair:
            code = pairing.start(clock())
            say(f"Send this code to your bot from your own Telegram account within {int(CODE_LIFETIME.total_seconds() // 60)} minutes (once; it is not kept):")
            say(f"    {code}")
            return EXIT_OK
        if args.unpair:
            pairing.unpair()
            say("Unpaired. The bot now answers nobody.")
            return EXIT_OK
        if args.status:
            try:
                read_token(config.telegram_token_path)
                token = "saved"
            except TelegramError:
                token = "missing"
            say(f"Telegram is on. Bot token: {token}. Paired: {'yes' if pairing.owner() is not None else 'no'}"
                f"{'; a pairing code is waiting' if pairing.waiting(clock()) else ''}.")
            return EXIT_OK
        token = read_token(config.telegram_token_path)
        api = TelegramApi(token, post=post)
        bot_id = api.get_me()["id"]
        if pairing.owner() is None and not pairing.waiting(clock()):
            say("Not paired yet: run python diya_telegram.py --pair in another window to get a code.")
        asker = make_asker(config, state) if make_asker else _real_asker(config, state)
        bridge = Bridge(state, api, asker, clock=clock, say=say, bot_id=bot_id)
        say("Listening for the paired owner's messages. Ctrl+C stops.")
        run(state, api, bridge, sleep=sleep, say=say, polls=polls)
        return EXIT_OK
    except KeyboardInterrupt:
        say("Stopped.")
        return EXIT_OK
    except (TelegramError, sqlite3.Error) as exc:
        say(f"diya_telegram: {printable(exc, 200)}")
        return EXIT_FAILED


def _real_asker(config, state):
    import diya

    return AgentAsker(diya.Agent(config), state)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
