"""Talking to Diya from Telegram (docs/TELEGRAM_DESIGN.md, unit P4): diya_telegram.py, against a scripted stand-in for Telegram. Nothing here contacts Telegram.

What this proves: only the one paired owner, in a private chat, in plain text, is answered, and everything else is dropped without an answer (and an unpaired sender can do one thing,
send the code); the one-time code is random, kept only as a hash, expires, is single use and is voided by wrong guesses; forwards, replies to other people, bots, groups, files, commands and
over-long messages get a fixed line or nothing; the hourly limit holds; a failure in the model gives a fixed line and no text of the failure; the number of an update is saved before it is
handled; a failure to reach Telegram backs off and is said without the token or any address; the token is kept in its own file and never printed; the module cannot approve anything; and
importing it does nothing.
"""
import dataclasses
import io
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone

import pytest

import diya
import diya_config
import diya_telegram as tg
from diya_db import Store
from fakes import FakeClient, text_reply

NOW = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
TOKEN = "123456789:" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"[:35]
OWNER, STRANGER, BOT_ID = 1001, 2002, 999
SECRET_WORDS = "my private words about my health"


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


@pytest.fixture
def state(store):
    return tg.State(store)


class Telegram:
    """The other end: a queue of updates, and a record of every request."""

    def __init__(self, token=TOKEN):
        self.token = token
        self.updates, self.requests = [], []
        self.fail = {}  # method -> status (None: no answer)

    def post(self, url, payload, timeout):
        method = url.rsplit("/", 1)[1]
        self.requests.append((url, method, payload, timeout))
        if method in self.fail:
            return self.fail[method], None
        if f"/bot{self.token}/" not in url:
            return 401, {"ok": False, "error_code": 401, "description": "Unauthorized"}
        if method == "getMe":
            return 200, {"ok": True, "result": {"id": BOT_ID, "is_bot": True, "username": "a_test_bot"}}
        if method == "getUpdates":
            # Telegram sends what is at or after the offset; the odd entries the tests add on purpose (no number, not even a dict) are always sent
            return 200, {"ok": True, "result": [u for u in self.updates if not (isinstance(u, dict) and isinstance(u.get("update_id"), int)) or u["update_id"] >= payload["offset"]]}
        if method == "sendMessage":
            return 200, {"ok": True, "result": {"message_id": 1}}
        return 404, {"ok": False}

    @property
    def sent(self):
        return [payload for _, method, payload, _ in self.requests if method == "sendMessage"]

    def api(self):
        return tg.TelegramApi(self.token, post=self.post)


def message(update_id, sender=OWNER, text="hello", chat_type="private", **extra):
    body = {"message_id": update_id, "from": {"id": sender, "is_bot": False, "first_name": "x"}, "chat": {"id": sender, "type": chat_type}, "date": 1_800_000_000}
    if text is not None:
        body["text"] = text
    body.update(extra)
    return {"update_id": update_id, "message": body}


class Brain:
    """The model: records what it was asked and answers as told."""

    def __init__(self, answer="an answer", fails=None):
        self.asked, self.answer, self.fails = [], answer, fails

    def __call__(self, text):
        self.asked.append(text)
        if self.fails:
            raise self.fails
        return self.answer


def make_bridge(state, telegram=None, brain=None, now=None, bot_id=BOT_ID):
    telegram = telegram or Telegram()
    brain = brain or Brain()
    said = []
    clock = {"now": now or NOW}
    bridge = tg.Bridge(state, telegram.api(), brain, clock=lambda: clock["now"], say=said.append, bot_id=bot_id)
    return bridge, telegram, brain, said, clock


def pair(state, owner=OWNER, now=NOW):
    state.set("owner_id", owner)


# ---- the code ---------------------------------------------------------------------------------------------------------------------

def test_the_constants_are_what_the_design_says():
    assert (tg.CODE_LENGTH, tg.MAX_ATTEMPTS, tg.MAX_PER_HOUR, tg.MAX_CHARS_IN, tg.MAX_CHARS_OUT, tg.POLL_SECONDS) == (12, 5, 30, 2000, 4000, 30)
    assert tg.CODE_LIFETIME == timedelta(minutes=10) and (tg.BACKOFF_FIRST, tg.BACKOFF_MAX) == (5, 60)
    assert not set("0O1I") & set(tg.CODE_ALPHABET) and len(set(tg.CODE_ALPHABET)) == len(tg.CODE_ALPHABET) == 32


def test_a_code_is_twelve_characters_in_three_groups_from_the_alphabet():
    for _ in range(50):
        code = tg.make_code()
        assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", code)


def test_codes_are_not_repeated_and_use_the_whole_alphabet():
    codes = {tg.make_code() for _ in range(300)}
    assert len(codes) == 300 and set("".join(codes).replace("-", "")) == set(tg.CODE_ALPHABET)


def test_a_code_is_made_from_the_choosers_choices():
    picks = iter("ABCDEFGHJKLM")
    assert tg.make_code(choose=lambda alphabet: next(picks)) == "ABCD-EFGH-JKLM"


@pytest.mark.parametrize("typed", ["abcd-efgh-jklm", "ABCD EFGH JKLM", " abcdefghjklm ", "ABCD-EFGH-JKLM\n", "a b c d - e f g h - j k l m"])
def test_what_is_typed_is_compared_without_capitals_spaces_or_dashes(typed):
    assert tg.hash_code(typed) == tg.hash_code("ABCD-EFGH-JKLM")


def test_a_different_code_has_a_different_hash():
    assert tg.hash_code("ABCD-EFGH-JKLM") != tg.hash_code("ABCD-EFGH-JKLN") and re.fullmatch(r"[0-9a-f]{64}", tg.hash_code("x"))


# ---- pairing ----------------------------------------------------------------------------------------------------------------------

def test_starting_keeps_only_the_hash_and_the_time_it_runs_out(state):
    pairing = tg.Pairing(state)
    code = pairing.start(NOW, code="ABCD-EFGH-JKLM")
    assert code == "ABCD-EFGH-JKLM" and state.get("pair_hash") == tg.hash_code(code) and state.get("pair_expires") == "2026-10-12T04:10:00Z" and state.get("pair_attempts") == "0"
    conn = state.store.connect()
    try:
        assert "ABCD" not in json.dumps(conn.execute("SELECT key, value FROM telegram_state").fetchall())
    finally:
        conn.close()


def test_a_code_made_by_start_is_a_fresh_random_one(state):
    pairing = tg.Pairing(state)
    assert pairing.start(NOW) != pairing.start(NOW)


def test_the_right_code_makes_the_sender_the_owner_and_is_used_up(state):
    pairing = tg.Pairing(state)
    code = pairing.start(NOW)
    assert pairing.try_code(code.lower(), OWNER, NOW + timedelta(minutes=1)) is True
    assert pairing.owner() == OWNER and state.get("pair_hash") is None and state.get("pair_expires") is None and state.get("pair_attempts") is None
    assert pairing.try_code(code, STRANGER, NOW + timedelta(minutes=2)) is False and pairing.owner() == OWNER


def test_a_code_is_good_for_exactly_ten_minutes(state):
    pairing = tg.Pairing(state)
    code = pairing.start(NOW)
    assert pairing.waiting(NOW + timedelta(minutes=9, seconds=59)) is True
    assert pairing.waiting(NOW + timedelta(minutes=10)) is False
    assert pairing.try_code(code, OWNER, NOW + timedelta(minutes=10)) is False and pairing.owner() is None and state.get("pair_hash") is None


def test_a_wrong_guess_is_counted_and_five_void_the_code_even_for_the_right_one(state):
    pairing = tg.Pairing(state)
    code = pairing.start(NOW)
    for expected in (1, 2, 3, 4):
        assert pairing.try_code("WRONG-WRONG-XXXX", STRANGER, NOW) is False and state.get("pair_attempts") == str(expected)
    assert pairing.try_code("WRONG-WRONG-XXXX", STRANGER, NOW) is False and state.get("pair_hash") is None
    assert pairing.try_code(code, OWNER, NOW) is False and pairing.owner() is None


def test_the_right_code_on_the_fifth_try_still_works(state):
    pairing = tg.Pairing(state)
    code = pairing.start(NOW)
    for _ in range(4):
        pairing.try_code("WRONG", STRANGER, NOW)
    assert pairing.try_code(code, OWNER, NOW) is True


def test_there_is_nothing_to_guess_when_no_code_was_made(state):
    assert tg.Pairing(state).try_code("ANYTHING", OWNER, NOW) is False and tg.Pairing(state).owner() is None


def test_starting_again_replaces_the_code_and_the_count(state):
    pairing = tg.Pairing(state)
    old = pairing.start(NOW)
    pairing.try_code("WRONG", STRANGER, NOW)
    new = pairing.start(NOW + timedelta(minutes=5))
    assert state.get("pair_attempts") == "0" and pairing.try_code(old, OWNER, NOW + timedelta(minutes=6)) is False and pairing.try_code(new, OWNER, NOW + timedelta(minutes=6)) is True


def test_there_is_no_second_pairing_while_there_is_an_owner_and_unpairing_forgets_everything(state):
    pairing = tg.Pairing(state)
    pair(state)
    with pytest.raises(tg.TelegramError, match="already paired"):
        pairing.start(NOW)
    state.set("pair_hash", "x")
    pairing.unpair()
    assert pairing.owner() is None and state.get("pair_hash") is None


# ---- the notes --------------------------------------------------------------------------------------------------------------------

def test_the_notes_are_a_small_key_value_store(state):
    assert state.get("a") is None and state.get("a", "d") == "d"
    state.set("a", 5)
    state.set("a", 6)
    assert state.get("a") == "6"
    state.set("b", "x")
    state.delete("a", "b", "missing")
    assert state.get("a") is None and state.get("b") is None


# ---- the bridge: who is answered --------------------------------------------------------------------------------------------------

def test_nobody_is_answered_before_pairing_and_nothing_is_asked(state):
    bridge, telegram, brain, said, _ = make_bridge(state)
    for sender in (OWNER, STRANGER):
        assert bridge.handle(message(1, sender, "hello")) == "dropped:not paired"
    assert telegram.sent == [] and brain.asked == []


def test_the_code_from_a_private_chat_pairs_and_the_reply_goes_to_that_sender_only(state):
    bridge, telegram, brain, said, _ = make_bridge(state)
    code = tg.Pairing(state).start(NOW)
    assert bridge.handle(message(1, OWNER, code)) == "paired"
    assert telegram.sent == [{"chat_id": OWNER, "text": tg.PAIRED, "disable_web_page_preview": True, "link_preview_options": {"is_disabled": True}}]
    assert tg.Pairing(state).owner() == OWNER and brain.asked == []


def test_a_wrong_code_gets_no_answer_at_all(state):
    bridge, telegram, brain, said, _ = make_bridge(state)
    tg.Pairing(state).start(NOW)
    assert bridge.handle(message(1, STRANGER, "not the code")) == "dropped:not paired" and telegram.sent == [] and brain.asked == []


@pytest.mark.parametrize("extra", [{"forward_origin": {"type": "user"}}, {"forward_from": {"id": 1}}, {"forward_date": 1}, {"via_bot": {"id": 5}}, {"sender_chat": {"id": 5}},
                                   {"external_reply": {"x": 1}}, {"quote": {"text": "x"}}])
def test_the_code_does_not_pair_when_it_was_forwarded_or_came_through_a_bot(state, extra):
    bridge, telegram, _, _, _ = make_bridge(state)
    code = tg.Pairing(state).start(NOW)
    assert bridge.handle(message(1, STRANGER, code, **extra)) == "dropped:not paired" and tg.Pairing(state).owner() is None


def test_the_code_does_not_pair_in_a_group(state):
    bridge, telegram, _, _, _ = make_bridge(state)
    code = tg.Pairing(state).start(NOW)
    assert bridge.handle(message(1, STRANGER, code, chat_type="group")) == "dropped:not a private chat" and tg.Pairing(state).owner() is None


def test_after_pairing_a_stranger_gets_nothing_and_is_never_asked_about(state):
    pair(state)
    bridge, telegram, brain, said, _ = make_bridge(state)
    assert bridge.handle(message(1, STRANGER, "hello")) == "dropped:not the owner" and telegram.sent == [] and brain.asked == []


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel", "sender", "", None])
def test_nothing_in_any_kind_of_chat_but_a_private_one_is_read_even_from_the_owner(state, chat_type):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(message(1, OWNER, "hello", chat_type=chat_type)).startswith("dropped") and telegram.sent == [] and brain.asked == []


@pytest.mark.parametrize("update", [
    None, [], "text", 5, {}, {"update_id": 1}, {"update_id": 1, "edited_message": {"text": "x"}}, {"update_id": 1, "channel_post": {"text": "x"}}, {"update_id": 1, "message": "text"},
    {"update_id": 1, "message": {"text": "x"}}, {"update_id": 1, "message": {"chat": {"type": "private", "id": OWNER}, "text": "x"}},
])
def test_an_update_that_is_not_a_new_message_in_a_chat_is_dropped(state, update):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(update).startswith("dropped") and telegram.sent == [] and brain.asked == []


@pytest.mark.parametrize("sender", [None, "text", {"id": OWNER, "is_bot": True}, {"id": True, "is_bot": False}, {"id": "1001", "is_bot": False}, {"is_bot": False}])
def test_a_sender_that_is_not_a_person_is_dropped_even_when_the_id_looks_like_the_owners(state, sender):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    update = message(1, OWNER, "hello")
    update["message"]["from"] = sender
    assert bridge.handle(update).startswith("dropped") and telegram.sent == [] and brain.asked == []


def test_a_message_whose_chat_is_not_the_senders_own_is_dropped(state):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    update = message(1, OWNER, "hello")
    update["message"]["chat"]["id"] = STRANGER
    assert bridge.handle(update).startswith("dropped") and brain.asked == []


# ---- the bridge: what the owner says ----------------------------------------------------------------------------------------------

def test_the_owner_is_answered_with_what_the_model_said_as_plain_text(state):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state, brain=Brain("  Done.\n"))
    assert bridge.handle(message(1, OWNER, "remind me to call mum")) == "answered"
    assert brain.asked == ["remind me to call mum"] and telegram.sent == [{"chat_id": OWNER, "text": "Done.", "disable_web_page_preview": True, "link_preview_options": {"is_disabled": True}}]
    assert "parse_mode" not in telegram.sent[0]


def test_an_answer_is_cut_at_four_thousand_characters_and_an_empty_one_is_said(state):
    pair(state)
    bridge, telegram, _, _, _ = make_bridge(state, brain=Brain("x" * 5000))
    bridge.handle(message(1))
    assert len(telegram.sent[0]["text"]) == 4000
    for answer in ("", "   ", None, 5):
        bridge, telegram, _, _, _ = make_bridge(state, brain=Brain(answer))
        bridge.handle(message(2))
        assert telegram.sent[0]["text"] == tg.EMPTY


def test_two_thousand_characters_are_read_and_one_more_is_not(state):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(message(1, text="a" * 2000)) == "answered"
    assert bridge.handle(message(2, text="a" * 2001)) == "replied:too long" and telegram.sent[-1]["text"] == tg.TOO_LONG and len(brain.asked) == 1


@pytest.mark.parametrize("extra", [{"forward_origin": {"type": "user"}}, {"forward_from": {"id": 1}}, {"forward_from_chat": {"id": 1}}, {"forward_date": 1}, {"forward_sender_name": "x"},
                                   {"forward_signature": "x"}, {"is_automatic_forward": True}, {"via_bot": {"id": 5}}, {"sender_chat": {"id": 5}}, {"external_reply": {}},
                                   {"quote": {"text": "x"}}, {"story": {}}, {"business_connection_id": "x"}])
def test_a_message_that_was_not_typed_here_is_not_read_and_the_owner_is_told_so(state, extra):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(message(1, **extra)) == "replied:not typed here" and telegram.sent[0]["text"] == tg.FORWARDED and brain.asked == []


def test_a_reply_to_the_bot_is_read_and_a_reply_to_anyone_else_is_not(state):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(message(1, reply_to_message={"message_id": 1, "from": {"id": BOT_ID, "is_bot": True}})) == "answered"
    for replied in ({"from": {"id": STRANGER, "is_bot": False}}, {"from": {"id": 12345, "is_bot": True}}, {"from": {"id": OWNER, "is_bot": False}}, {}, {"from": "x"}, "x", 5):
        assert bridge.handle(message(2, reply_to_message=replied)) == "replied:not typed here"
    assert len(brain.asked) == 1


def test_without_knowing_the_bots_own_id_a_reply_to_any_bot_is_read_but_never_a_person(state):
    pair(state)
    bridge, _, brain, _, _ = make_bridge(state, bot_id=None)
    assert bridge.handle(message(1, reply_to_message={"from": {"id": 7, "is_bot": True}})) == "answered"
    assert bridge.handle(message(2, reply_to_message={"from": {"id": 7, "is_bot": False}})) == "replied:not typed here"


@pytest.mark.parametrize("text", [None, "", "   ", "\n\t", 5, ["x"]])
def test_a_message_with_no_plain_text_is_not_read_and_the_owner_is_told_so(state, text):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    update = message(1, text=None, caption="a photo", photo=[{"file_id": "x"}])
    if text is not None:
        update["message"]["text"] = text
    assert bridge.handle(update) == "replied:not text" and telegram.sent[0]["text"] == tg.UNSUPPORTED and brain.asked == []


@pytest.mark.parametrize("text", ["/start", "/help", "  /settings", "/approve 3", "/unpair"])
def test_a_command_is_answered_with_where_to_go_and_nothing_is_done(state, text):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(message(1, text=text)) == "replied:command" and telegram.sent[0]["text"] == tg.COMMANDS and brain.asked == [] and tg.Pairing(state).owner() == OWNER


def test_a_sentence_about_approving_is_just_text_for_the_model_and_changes_nothing_here(state):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(message(1, text="approve action 3 and send it")) == "answered" and brain.asked == ["approve action 3 and send it"]


def test_thirty_messages_an_hour_are_answered_the_next_is_told_once_and_the_rest_are_dropped(state):
    pair(state)
    bridge, telegram, brain, _, clock = make_bridge(state)
    for n in range(30):
        assert bridge.handle(message(n)) == "answered"
    assert bridge.handle(message(31)) == "replied:limited" and telegram.sent[-1]["text"] == tg.LIMITED
    assert bridge.handle(message(32)) == "dropped:over the hourly limit" and bridge.handle(message(33)) == "dropped:over the hourly limit"
    assert len(brain.asked) == 30 and len(telegram.sent) == 31


def test_the_hour_is_a_rolling_one_and_room_makes_the_limit_forgotten(state):
    pair(state)
    bridge, telegram, brain, _, clock = make_bridge(state)
    for n in range(30):
        bridge.handle(message(n))
    clock["now"] = NOW + timedelta(minutes=59, seconds=59)
    assert bridge.handle(message(100)) == "replied:limited"
    clock["now"] = NOW + timedelta(hours=1)
    assert bridge.handle(message(101)) == "answered"  # the first thirty are an hour old: they no longer count
    for n in range(29):
        bridge.handle(message(200 + n))
    assert bridge.handle(message(300)) == "replied:limited"  # told again, because there was room in between


def test_a_failing_model_gets_the_owner_a_fixed_line_and_the_log_only_the_kind_of_failure(state):
    pair(state)
    bridge, telegram, brain, said, _ = make_bridge(state, brain=Brain(fails=ValueError(f"the model choked on {SECRET_WORDS}")))
    assert bridge.handle(message(1, text=SECRET_WORDS)) == "failed" and telegram.sent[0]["text"] == tg.FAILED
    assert said == ["telegram: could not answer (ValueError)"] and SECRET_WORDS not in json.dumps(telegram.sent)


def test_a_reply_that_cannot_be_sent_is_said_by_its_kind_and_not_counted_as_answered(state):
    pair(state)
    telegram = Telegram()
    telegram.fail["sendMessage"] = 403
    bridge, _, brain, said, _ = make_bridge(state, telegram=telegram)
    assert bridge.handle(message(1)) == "unsent" and said == ["telegram: could not send (Telegram answered sendMessage with status 403)"]


def test_nothing_that_is_said_holds_a_message_an_id_or_the_token(state):
    pair(state)
    bridge, telegram, brain, said, _ = make_bridge(state, brain=Brain(f"re: {SECRET_WORDS}"))
    bridge.handle(message(1, text=SECRET_WORDS))
    bridge.handle(message(2, STRANGER, text=SECRET_WORDS))
    bridge.handle(message(3, text=SECRET_WORDS, forward_date=1))
    bridge.handle(message(4, text="/x"))
    bridge.handle(message(5, text=SECRET_WORDS, chat_type="group"))
    text = "\n".join(said)
    assert said and SECRET_WORDS not in text and TOKEN not in text and str(OWNER) not in text and str(STRANGER) not in text


# ---- the real turn ----------------------------------------------------------------------------------------------------------------

def make_agent(tmp_path, replies):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "a.db"), profile_path=str(tmp_path / "profile.txt"))
    return diya.Agent(config, client=FakeClient([text_reply(r) for r in replies]))


def test_the_turn_is_the_chats_own_in_one_thread_that_is_kept(tmp_path):
    agent = make_agent(tmp_path, ["first answer", "second answer"])
    state = tg.State(agent.store)
    asker = tg.AgentAsker(agent, state)
    assert asker("one") == "first answer" and asker("two") == "second answer"
    thread = agent.store.main_thread()  # the phone is the one chat the page shows (docs/ONE_CHAT_DESIGN.md)
    assert [(m["role"], m["content"]) for m in agent.store.get_messages(thread)] == [("user", "one"), ("assistant", "first answer"), ("user", "two"), ("assistant", "second answer")]
    assert len(agent.store.list_threads()) == 1


def test_a_message_from_the_phone_goes_into_the_chat_the_page_already_has(tmp_path):
    agent = make_agent(tmp_path, ["phone answer"])
    earlier = agent.store.create_thread()
    agent.store.add_message(earlier, "user", "typed on the laptop")
    agent.store.add_message(earlier, "assistant", "laptop answer")
    assert tg.AgentAsker(agent, tg.State(agent.store))("typed on the phone") == "phone answer"
    assert [m["content"] for m in agent.store.get_messages(earlier)] == ["typed on the laptop", "laptop answer", "typed on the phone", "phone answer"]
    assert len(agent.store.list_threads()) == 1


def test_a_failed_turn_leaves_the_question_saved_and_raises(tmp_path):
    agent = make_agent(tmp_path, [])  # the model has nothing to say: the fake raises
    asker = tg.AgentAsker(agent, tg.State(agent.store))
    with pytest.raises(Exception):
        asker("hello")
    assert [m["content"] for m in agent.store.get_messages(agent.store.main_thread())] == ["hello"]


# ---- the loop ---------------------------------------------------------------------------------------------------------------------

def test_an_updates_number_is_saved_before_it_is_handled_so_a_crash_never_handles_it_twice(state):
    telegram = Telegram()
    telegram.updates = [message(10), message(11)]
    handled = []

    class Crashing:
        def handle(self, update):
            handled.append(update["update_id"])
            raise RuntimeError("the machine fell over")

    with pytest.raises(RuntimeError):
        tg.run(state, telegram.api(), Crashing(), polls=1, say=lambda line: None)
    assert handled == [10] and state.get("offset") == "11"
    with pytest.raises(RuntimeError):
        tg.run(state, telegram.api(), Crashing(), polls=1, say=lambda line: None)
    assert handled == [10, 11]  # the one that crashed is not handled again; the next one is


def test_it_asks_from_the_saved_offset_and_with_the_poll_time_and_only_messages(state):
    telegram = Telegram()
    state.set("offset", 42)
    tg.run(state, telegram.api(), type("B", (), {"handle": lambda self, u: None})(), polls=1, say=lambda line: None)
    (_, method, payload, timeout) = telegram.requests[0]
    assert method == "getUpdates" and payload == {"offset": 42, "timeout": 30, "allowed_updates": ["message"]} and timeout == 40


def test_updates_are_handled_in_order_and_old_or_odd_ones_are_skipped(state):
    telegram = Telegram()
    state.set("offset", 5)
    telegram.updates = [message(5), message(6), message(7), message(6)]  # the last is a repeat of one already handled
    telegram.updates += [{"update_id": "x", "message": {}}, {"no_id": True}, "text", None]
    seen = []
    handler = type("B", (), {"handle": lambda self, u: seen.append(u["update_id"])})()
    original = telegram.post

    def with_old(url, payload, timeout):
        status, body = original(url, payload, timeout)
        if body and isinstance(body.get("result"), list):
            body["result"] = body["result"] + [message(2)]  # an old one that Telegram should not send
        return status, body

    api = tg.TelegramApi(TOKEN, post=with_old)
    tg.run(state, api, handler, polls=1, say=lambda line: None)
    assert seen == [5, 6, 7] and state.get("offset") == "8"  # in the order given; the old one, the repeat and the odd entries are skipped


def test_a_failure_to_reach_telegram_backs_off_five_ten_twenty_forty_sixty_and_starts_again_after_a_success(state):
    telegram = Telegram()
    telegram.fail["getUpdates"] = None
    waits, said = [], []
    tg.run(state, telegram.api(), type("B", (), {"handle": lambda self, u: None})(), sleep=waits.append, say=said.append, polls=7)
    assert waits == [5, 10, 20, 40, 60, 60, 60] and said[0] == "telegram: no answer from Telegram (getUpdates); trying again in 5 seconds"
    del telegram.fail["getUpdates"]
    telegram.fail["getUpdates"] = None
    waits.clear()
    calls = {"n": 0}
    original = telegram.post

    def flaky(url, payload, timeout):
        calls["n"] += 1
        if calls["n"] == 3:
            return 200, {"ok": True, "result": []}
        return original(url, payload, timeout)

    tg.run(state, tg.TelegramApi(TOKEN, post=flaky), type("B", (), {"handle": lambda self, u: None})(), sleep=waits.append, say=lambda line: None, polls=5)
    assert waits == [5, 10, 5, 10]


def test_what_is_said_about_a_failure_never_holds_the_token_or_the_address(state):
    telegram = Telegram()
    for status in (None, 401, 409, 429, 500, 502):
        telegram.fail["getUpdates"] = status
        said = []
        tg.run(state, telegram.api(), None, sleep=lambda s: None, say=said.append, polls=1)
        assert said and TOKEN not in said[0] and "api.telegram.org" not in said[0] and "/bot" not in said[0]


def test_a_stop_after_polls_asks_exactly_that_many_times(state):
    telegram = Telegram()
    tg.run(state, telegram.api(), type("B", (), {"handle": lambda self, u: None})(), polls=3, say=lambda line: None)
    assert [m for _, m, _, _ in telegram.requests] == ["getUpdates"] * 3


# ---- Telegram's side ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status, text", [
    (None, "no answer from Telegram (getMe)"), (401, "Telegram refused the bot token (run --set-token again)"), (409, "another program is already reading this bot's messages"),
    (429, "Telegram asked to slow down"), (400, "Telegram answered getMe with status 400"), (500, "Telegram answered getMe with status 500"),
])
def test_each_failure_is_named_by_its_kind(status, text):
    assert tg.describe_failure("getMe", status) == text


def test_a_refusal_raises_an_error_that_holds_neither_the_token_nor_the_address():
    telegram = Telegram()
    telegram.fail["getMe"] = 401
    with pytest.raises(tg.TelegramError) as caught:
        telegram.api().get_me()
    assert TOKEN not in str(caught.value) and "telegram.org" not in str(caught.value)


def test_a_wrong_token_is_a_401_from_the_stand_in_and_an_ok_false_body_is_an_error_too():
    with pytest.raises(tg.TelegramError, match="refused the bot token"):
        tg.TelegramApi("1:" + "x" * 35, post=Telegram().post).get_me()
    with pytest.raises(tg.TelegramError):
        tg.TelegramApi(TOKEN, post=lambda url, payload, timeout: (200, {"ok": False})).get_me()
    with pytest.raises(tg.TelegramError):
        tg.TelegramApi(TOKEN, post=lambda url, payload, timeout: (200, "not a dict")).get_me()
    with pytest.raises(tg.TelegramError):
        tg.TelegramApi(TOKEN, post=lambda url, payload, timeout: (201, {"ok": True, "result": {}})).get_me()


def test_get_me_and_get_updates_check_the_shape_of_what_they_get():
    with pytest.raises(tg.TelegramError):
        tg.TelegramApi(TOKEN, post=lambda url, payload, timeout: (200, {"ok": True, "result": {"id": "x"}})).get_me()
    with pytest.raises(tg.TelegramError):
        tg.TelegramApi(TOKEN, post=lambda url, payload, timeout: (200, {"ok": True, "result": {"no": "list"}})).get_updates(0, 1)


def test_the_token_is_in_the_address_only_and_the_host_is_telegrams():
    telegram = Telegram()
    api = telegram.api()
    api.get_me()
    api.send_message(5, "hi")
    for url, method, payload, timeout in telegram.requests:
        assert url == f"https://api.telegram.org/bot{TOKEN}/{method}" and TOKEN not in json.dumps(payload) and timeout == 15


def test_the_real_post_returns_the_status_and_body_or_nothing_and_follows_no_redirect(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, json=None, timeout=None, follow_redirects=None):
        seen.update(url=url, json=json, timeout=timeout, follow_redirects=follow_redirects)
        return httpx.Response(200, json={"ok": True, "result": 1})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert tg.post_json("https://api.telegram.org/botX/getMe", {"a": 1}, 7.0) == (200, {"ok": True, "result": 1})
    assert seen == {"url": "https://api.telegram.org/botX/getMe", "json": {"a": 1}, "timeout": 7.0, "follow_redirects": False}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(502, content=b"<html>"))
    assert tg.post_json("u", {}, 1) == (502, None)

    def broken(*a, **k):
        raise httpx.ConnectError("down: https://api.telegram.org/bot" + TOKEN)

    monkeypatch.setattr(httpx, "post", broken)
    assert tg.post_json("u", {}, 1) == (None, None)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.InvalidURL("bad")))
    assert tg.post_json("u", {}, 1) == (None, None)


# ---- the token file -----------------------------------------------------------------------------------------------------------------

def test_the_token_is_saved_in_its_own_file_and_read_back(tmp_path):
    path = str(tmp_path / "data" / "telegram.token")
    tg.save_token(path, f"  {TOKEN}\n")
    assert open(path, encoding="utf-8").read() == TOKEN + "\n" and tg.read_token(path) == TOKEN and os.listdir(tmp_path / "data") == ["telegram.token"]


@pytest.mark.skipif(os.name == "nt", reason="file modes mean little on Windows")
def test_the_token_file_is_readable_by_its_owner_only(tmp_path):
    path = tmp_path / "telegram.token"
    tg.save_token(str(path), TOKEN)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("token", ["", "abc", "123:short", "abc:" + "x" * 35, "123456789:" + "x" * 29, "123456789:" + "x" * 51, "123456789:" + "x" * 34 + "!", "12345:" + "x" * 35, "1" * 13 + ":" + "x" * 35, "a\n" + TOKEN])
def test_something_that_is_not_shaped_like_a_bot_token_is_not_saved_and_not_repeated(tmp_path, token):
    path = str(tmp_path / "telegram.token")
    with pytest.raises(tg.TelegramError) as caught:
        tg.save_token(path, token)
    assert not os.path.exists(path) and (token not in str(caught.value) or token == "")


def test_a_token_that_is_saved_again_replaces_the_old_one(tmp_path):
    path = str(tmp_path / "telegram.token")
    tg.save_token(path, TOKEN)
    other = "987654321:" + "Z" * 35
    tg.save_token(path, other)
    assert tg.read_token(path) == other


def test_a_missing_or_damaged_token_file_says_what_to_do_without_showing_it(tmp_path):
    with pytest.raises(tg.TelegramError, match="--set-token"):
        tg.read_token(str(tmp_path / "none"))
    (tmp_path / "bad").write_text("garbage but secret\n")
    with pytest.raises(tg.TelegramError) as caught:
        tg.read_token(str(tmp_path / "bad"))
    assert "garbage" not in str(caught.value) and "--set-token" in str(caught.value)


# ---- the command line ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path):
    return dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "c.db"), telegram=True, telegram_token_path=str(tmp_path / "telegram.token"))


def run_main(args, cfg, **kwargs):
    out = io.StringIO()
    code = tg.main(args, config=cfg, out=out, **kwargs)
    return code, out.getvalue()


def test_the_defaults_are_off_and_the_token_file_follows_the_data_folder(tmp_path):
    config = diya_config.load_config({})
    assert config.telegram is False and config.telegram_token_path == "telegram.token"
    assert diya_config.load_config({"DIYA_TELEGRAM": "1"}).telegram is True
    assert diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path / "d")}).telegram_token_path == str(tmp_path / "d" / "telegram.token")
    with pytest.raises(diya_config.ConfigError, match="DIYA_TELEGRAM"):
        diya_config.load_config({"DIYA_TELEGRAM": "perhaps"})


def test_setting_the_token_works_even_while_it_is_off_and_never_shows_it(cfg):
    code, text = run_main(["--set-token"], dataclasses.replace(cfg, telegram=False), secret=lambda: TOKEN)
    assert code == 0 and TOKEN not in text and tg.read_token(cfg.telegram_token_path) == TOKEN


def test_a_token_that_is_wrong_is_refused_with_one_line_that_does_not_repeat_it(cfg):
    code, text = run_main(["--set-token"], cfg, secret=lambda: "not a token at all")
    assert code == 2 and "not a token at all" not in text and "shaped like a bot token" in text and not os.path.exists(cfg.telegram_token_path)


def test_everything_else_refuses_while_it_is_off(cfg):
    for flag in (["--pair"], ["--unpair"], ["--status"], []):
        code, text = run_main(flag, dataclasses.replace(cfg, telegram=False))
        assert code == 2 and "DIYA_TELEGRAM=1" in text


def test_pairing_shows_the_code_once_and_keeps_only_its_hash(cfg):
    code, text = run_main(["--pair"], cfg, clock=lambda: NOW)
    shown = re.search(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", text).group(0)
    state = tg.State(Store(cfg.db_path))
    assert code == 0 and "10 minutes" in text and state.get("pair_hash") == tg.hash_code(shown) and shown not in json.dumps([state.get(k) for k in ("pair_hash", "pair_expires", "pair_attempts")])


def test_pairing_while_paired_is_refused_and_unpairing_works(cfg):
    pair(tg.State(Store(cfg.db_path)))
    code, text = run_main(["--pair"], cfg, clock=lambda: NOW)
    assert code == 1 and "already paired" in text
    code, text = run_main(["--unpair"], cfg)
    assert code == 0 and "answers nobody" in text and tg.Pairing(tg.State(Store(cfg.db_path))).owner() is None


def test_status_says_what_there_is_and_never_who_or_what_token(cfg):
    code, text = run_main(["--status"], cfg, clock=lambda: NOW)
    assert code == 0 and text.strip() == "Telegram is on. Bot token: missing. Paired: no."
    tg.save_token(cfg.telegram_token_path, TOKEN)
    run_main(["--pair"], cfg, clock=lambda: NOW)
    code, text = run_main(["--status"], cfg, clock=lambda: NOW + timedelta(minutes=1))
    assert text.strip() == "Telegram is on. Bot token: saved. Paired: no; a pairing code is waiting." and TOKEN not in text
    pair(tg.State(Store(cfg.db_path)))
    assert run_main(["--status"], cfg, clock=lambda: NOW + timedelta(hours=1))[1].strip() == "Telegram is on. Bot token: saved. Paired: yes."


def test_running_needs_a_token_and_says_how_to_get_one(cfg):
    code, text = run_main([], cfg)
    assert code == 1 and "--set-token" in text


def test_a_refused_token_stops_a_run_with_one_line(cfg):
    tg.save_token(cfg.telegram_token_path, TOKEN)
    telegram = Telegram(token="999999999:" + "Q" * 35)  # a different bot: this token is refused
    code, text = run_main([], cfg, post=telegram.post)
    assert code == 1 and "refused the bot token" in text and TOKEN not in text


def test_a_run_asks_who_the_bot_is_says_it_is_not_paired_and_listens(cfg):
    tg.save_token(cfg.telegram_token_path, TOKEN)
    telegram = Telegram()
    code, text = run_main([], cfg, post=telegram.post, make_asker=lambda config, state: Brain(), polls=2)
    assert code == 0 and "Not paired yet" in text and "Listening for the paired owner" in text and TOKEN not in text
    assert [m for _, m, _, _ in telegram.requests] == ["getMe", "getUpdates", "getUpdates"]


def test_a_run_does_not_say_not_paired_when_a_code_is_waiting_or_there_is_an_owner(cfg):
    tg.save_token(cfg.telegram_token_path, TOKEN)
    run_main(["--pair"], cfg, clock=lambda: NOW)
    assert "Not paired yet" not in run_main([], cfg, post=Telegram().post, make_asker=lambda c, s: Brain(), polls=1, clock=lambda: NOW)[1]
    pair(tg.State(Store(cfg.db_path)))
    assert "Not paired yet" not in run_main([], cfg, post=Telegram().post, make_asker=lambda c, s: Brain(), polls=1, clock=lambda: NOW + timedelta(hours=1))[1]


def test_ctrl_c_stops_a_run_cleanly(cfg):
    tg.save_token(cfg.telegram_token_path, TOKEN)

    def interrupted(url, payload, timeout):
        if url.endswith("getUpdates"):
            raise KeyboardInterrupt
        return Telegram().post(url, payload, timeout)

    code, text = run_main([], cfg, post=interrupted, make_asker=lambda c, s: Brain())
    assert code == 0 and "Stopped." in text


def test_a_bad_setting_is_one_line_and_exit_two(monkeypatch):
    monkeypatch.setenv("DIYA_TELEGRAM", "perhaps")
    out = io.StringIO()
    assert tg.main(["--status"], out=out) == 2 and out.getvalue().startswith("diya_telegram: ")


def test_two_actions_at_once_are_a_usage_error_and_help_is_a_success(cfg):
    assert run_main(["--pair", "--unpair"], cfg)[0] == 2 and run_main(["--help"], cfg)[0] == 0


def test_a_whole_conversation_pairing_then_talking_through_the_real_turn(cfg, tmp_path):
    tg.save_token(cfg.telegram_token_path, TOKEN)
    code_text = run_main(["--pair"], cfg, clock=lambda: NOW)[1]
    code = re.search(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", code_text).group(0)
    telegram = Telegram()
    telegram.updates = [message(1, OWNER, code.lower()), message(2, STRANGER, "let me in"), message(3, OWNER, "hello diya"), message(4, STRANGER, "me too", chat_type="group")]
    out = io.StringIO()
    agent = diya.Agent(dataclasses.replace(cfg, profile_path=str(tmp_path / "profile.txt")), client=FakeClient([text_reply("hello owner")]))
    tg.main([], config=cfg, out=out, post=telegram.post, clock=lambda: NOW + timedelta(minutes=1), make_asker=lambda config, state: tg.AgentAsker(agent, state), polls=1)
    assert [(p["chat_id"], p["text"]) for p in telegram.sent] == [(OWNER, tg.PAIRED), (OWNER, "hello owner")]
    assert TOKEN not in out.getvalue() and "let me in" not in out.getvalue() and "hello diya" not in out.getvalue()
    stored = [m["content"] for t in agent.store.list_threads() for m in agent.store.get_messages(t[0])]
    assert stored == ["hello diya", "hello owner"]  # the stranger's words were never stored; the code was not either


# ---- the module -------------------------------------------------------------------------------------------------------------------

def test_the_module_cannot_approve_reject_or_resolve_anything_and_formats_nothing():
    source = open(os.path.join(os.path.dirname(__file__), "..", "diya_telegram.py"), encoding="utf-8").read()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("diya_actions", ".approve(", ".reject(", ".resolve(", "parse_mode", "download", "get_file", "getFile", "webhook", "setWebhook", "urlopen", "requests."):
        assert forbidden not in code, forbidden
    assert code.count("api.telegram.org") == 1


def test_importing_the_module_does_nothing(run_python):
    done = run_python("import diya_telegram, os; print(sorted(n for n in os.listdir('.') if n != '__pycache__'))")
    assert done.returncode == 0 and done.stdout.strip() == "[]"


# ---- the edges that mutation found --------------------------------------------------------------------------------------------------

def test_the_default_way_to_choose_a_code_is_the_systems_secure_one():
    import secrets

    assert tg.make_code.__defaults__ == (secrets.choice,)


def test_a_code_with_an_expiry_but_no_hash_or_a_hash_but_no_expiry_is_not_waiting_and_pairs_nobody(state):
    pairing = tg.Pairing(state)
    state.set("pair_expires", "2999-01-01T00:00:00Z")
    assert pairing.waiting(NOW) is False and pairing.try_code("ANYTHING", OWNER, NOW) is False and pairing.owner() is None
    state.delete("pair_expires")
    state.set("pair_hash", tg.hash_code("ABCD-EFGH-JKLM"))
    assert pairing.waiting(NOW) is False and pairing.try_code("ABCD-EFGH-JKLM", OWNER, NOW) is False and pairing.owner() is None


def test_a_second_person_with_the_right_code_does_not_take_over_an_existing_pairing(state):
    pairing = tg.Pairing(state)
    pair(state)
    state.set("pair_hash", tg.hash_code("ABCD-EFGH-JKLM"))  # a left-over code beside an owner: it must still pair nobody
    state.set("pair_expires", "2999-01-01T00:00:00Z")
    assert pairing.try_code("ABCD-EFGH-JKLM", STRANGER, NOW) is False and pairing.owner() == OWNER


def test_the_code_is_compared_with_the_constant_time_comparison(state, monkeypatch):
    calls = []
    real = tg.hmac.compare_digest
    monkeypatch.setattr(tg.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b))
    pairing = tg.Pairing(state)
    code = pairing.start(NOW)
    pairing.try_code(code, OWNER, NOW)
    assert calls == [(tg.hash_code(code), tg.hash_code(code))]


def test_a_reply_with_the_wrong_status_or_a_not_true_ok_is_an_error_even_when_the_result_looks_fine():
    good_result = {"id": 5}
    for status, body in ((201, {"ok": True, "result": good_result}), (500, {"ok": True, "result": good_result}), (200, {"ok": False, "result": good_result}),
                         (200, {"ok": 1, "result": good_result}), (200, {"ok": "true", "result": good_result}), (200, {"result": good_result})):
        with pytest.raises(tg.TelegramError):
            tg.TelegramApi(TOKEN, post=lambda url, payload, timeout, s=status, b=body: (s, b)).get_me()
    assert tg.TelegramApi(TOKEN, post=lambda url, payload, timeout: (200, {"ok": True, "result": good_result})).get_me() == good_result


def test_a_true_or_a_numeric_string_is_not_a_person(state):
    pair(state, owner=1)
    bridge, telegram, brain, _, _ = make_bridge(state)
    for sender_id in (True, "1"):
        update = message(1, OWNER, "hello")
        update["message"]["from"]["id"] = sender_id
        update["message"]["chat"]["id"] = sender_id
        assert bridge.handle(update).startswith("dropped")
    assert telegram.sent == [] and brain.asked == []


def test_messages_that_are_not_text_do_not_use_up_a_strangers_guesses_at_the_code(state):
    bridge, telegram, _, _, _ = make_bridge(state)
    code = tg.Pairing(state).start(NOW)
    for n in range(12):
        bridge.handle(message(n, STRANGER, text=None, photo=[{"file_id": "x"}]))
    assert state.get("pair_attempts") == "0" and bridge.handle(message(100, OWNER, code)) == "paired"


@pytest.mark.parametrize("text", ["and/or", "1/2 cup of flour", "see c:/notes/today.txt", "what is 6/3?", "a / b"])
def test_a_slash_inside_a_message_is_not_a_command(state, text):
    pair(state)
    bridge, telegram, brain, _, _ = make_bridge(state)
    assert bridge.handle(message(1, text=text)) == "answered" and brain.asked == [text]


def test_the_model_is_given_the_whole_conversation_so_far_and_the_new_question_last(tmp_path):
    agent = make_agent(tmp_path, ["first answer", "second answer"])
    asker = tg.AgentAsker(agent, tg.State(agent.store))
    asker("one")
    asker("two")
    second = agent.client.chat_calls[1]["messages"]
    texts = [(m["role"], m["content"]) for m in second if m["role"] in ("user", "assistant")]
    assert texts == [("user", "one"), ("assistant", "first answer"), ("user", "two")]


def test_the_turn_tells_the_agent_which_thread_and_message_it_belongs_to(tmp_path):
    seen = {}

    class Agent:
        store = Store(str(tmp_path / "s.db"))

        def with_profile(self, history):
            return list(history)

        def ask(self, history, *, thread_id=None, message_id=None):
            seen.update(history=history, thread_id=thread_id, message_id=message_id)
            return "answer", []

    state = tg.State(Agent.store)
    assert tg.AgentAsker(Agent(), state)("hello") == "answer"
    assert seen["thread_id"] == Agent.store.main_thread() and seen["message_id"] == Agent.store.get_messages(seen["thread_id"])[0]["id"] and seen["history"][-1] == {"role": "user", "content": "hello"}


def test_a_token_file_with_anything_after_the_token_is_not_a_token(tmp_path):
    path = tmp_path / "telegram.token"
    for tail in (" extra", "\nsecond line", "x" * 40, "\n\njunk"):
        path.write_text(TOKEN + tail)
        with pytest.raises(tg.TelegramError):
            tg.read_token(str(path))


def test_the_token_is_asked_for_without_showing_it_and_is_not_repeated(cfg, monkeypatch):
    import builtins

    monkeypatch.setattr(tg.getpass, "getpass", lambda prompt: TOKEN)
    monkeypatch.setattr(builtins, "input", lambda *a: pytest.fail("the token was asked for with input(), which shows it"))
    code, text = run_main(["--set-token"], cfg)
    assert code == 0 and text.strip() == "Saved the bot token. It is not shown or logged anywhere." and tg.read_token(cfg.telegram_token_path) == TOKEN


def test_a_data_folder_that_cannot_be_made_is_one_line_and_exit_two(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("DIYA_DATA_DIR", str(blocker / "inside"))
    out = io.StringIO()
    assert tg.main(["--status"], out=out) == 2 and out.getvalue().startswith("diya_telegram: ")


def test_a_reply_to_some_other_bot_is_refused_in_a_whole_run_because_the_bot_knows_its_own_id(cfg):
    tg.save_token(cfg.telegram_token_path, TOKEN)
    pair(tg.State(Store(cfg.db_path)))
    telegram = Telegram()
    telegram.updates = [message(1, OWNER, "from a stranger bot's thread", reply_to_message={"from": {"id": 4242, "is_bot": True}}),
                        message(2, OWNER, "a reply to us", reply_to_message={"from": {"id": BOT_ID, "is_bot": True}})]
    brain = Brain("ok")
    run_main([], cfg, post=telegram.post, make_asker=lambda config, state: brain, polls=1, clock=lambda: NOW)
    assert brain.asked == ["a reply to us"] and [p["text"] for p in telegram.sent] == [tg.FORWARDED, "ok"]


def test_a_run_uses_the_clock_it_was_given_so_an_expired_code_does_not_pair(cfg):
    tg.save_token(cfg.telegram_token_path, TOKEN)
    code_text = run_main(["--pair"], cfg, clock=lambda: NOW)[1]
    code = re.search(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", code_text).group(0)
    telegram = Telegram()
    telegram.updates = [message(1, OWNER, code)]
    run_main([], cfg, post=telegram.post, make_asker=lambda config, state: Brain(), polls=1, clock=lambda: NOW + timedelta(minutes=11))
    assert telegram.sent == [] and tg.Pairing(tg.State(Store(cfg.db_path))).owner() is None


def test_a_run_with_no_asker_given_makes_the_real_one_without_calling_the_model(cfg, tmp_path):
    tg.save_token(cfg.telegram_token_path, TOKEN)
    cfg = dataclasses.replace(cfg, profile_path=str(tmp_path / "profile.txt"))
    out = io.StringIO()
    assert tg.main([], config=cfg, out=out, post=Telegram().post, polls=1, clock=lambda: NOW) == 0 and "Listening" in out.getvalue()


def test_the_token_path_setting_is_read_and_wins_over_the_data_folder(tmp_path):
    assert diya_config.load_config({"DIYA_TELEGRAM_TOKEN_PATH": "mine.token"}).telegram_token_path == "mine.token"
    assert diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path), "DIYA_TELEGRAM_TOKEN_PATH": "own.token"}).telegram_token_path == "own.token"
