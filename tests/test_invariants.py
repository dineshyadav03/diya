"""Six rules that must always hold, tried with thousands of made-up inputs instead of a few chosen ones (docs/INVARIANTS.md), added 2026-10-25.

An ordinary test checks the cases its author thought of. These make up cases (a fixed seed, so a failure can be run again exactly: DIYA_FUZZ_SEEDS=50 runs more) and check a sentence that must be true
of every one of them, written without copying the code under test:

* **Local only.** Whatever model address is set, the configuration either loads with an address whose host is this computer, as two different readers of the address (Python's and httpx's) both see it,
  or is refused with ConfigError and nothing else. It never lets an address through that spells one host to one reader and another to the other.
* **The token.** A request is let in only if it has exactly one Authorization header, the Bearer scheme, and the stored token exactly: not a longer token, a shorter one, one with a letter changed, one with a
  trailing space, another scheme, a second header, or the right value in the wrong header. With no stored token nothing is let in.
* **Printable.** Whatever text is given, what comes out is one line with no control, invisible or direction-changing character, with no stray spaces, that is left alone by a second pass, and that is the
  text itself when the text was already clean.
* **Short results, honest nudges.** A tool result is cut only when it is over the limit, always keeps its beginning and its end, never comes out longer than the cap, and is not cut twice; the "you are
  repeating yourself" reminder comes at exactly the third and fifth identical call in a row, however the arguments are ordered.
* **Approvals.** Whatever order the owner's and the system's moves arrive in (approving the wrong thing, running what was never approved, running twice, letting a day pass, rejecting, resolving), an
  effect runs only for an action that was approved before it expired, at most once; the store's own integrity check is clean after every move; a finished action never changes.
* **What it knew.** Asking "what did you know on that day?" gives exactly the accepted facts as they stood at that moment, whatever sequence of adding, retiring and restoring led there, and asking writes nothing.
"""
import hashlib
import json
import os
import random
import re
import string
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

import diya_actions
import diya_config
import diya_memory
import diya_toolguard
from diya_db import Store
from diya_memory import FactError, Memory
from diya_web import TokenMiddleware

ROOT = Path(__file__).resolve().parent.parent
SEEDS = range(int(os.environ.get("DIYA_FUZZ_SEEDS", "6")))


# ---- local only ---------------------------------------------------------------------------------------------------------------

def _this_computer(host):
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def _made_up_urls(rng, count):
    schemes = ["http://", "http://", "http://", "https://", "", "ftp://", "//", "http:/", "HTTP://"]
    hosts = [
        "localhost", "LocalHost", "127.0.0.1", "[::1]", "ollama.localhost", "localhost.", "localhost.evil.com", "127.0.0.1.evil.com", "evil.com", "10.0.0.5", "192.168.1.20", "[2001:db8::1]",
        "127.1", "2130706433", "0x7f.0.0.1", "[::ffff:127.0.0.1]", "\u217clocalhost", "localhost\u3002evil.com", "%6cocalhost", "localhost%00.evil.com", "0.0.0.0", "",
        "evil.com#@localhost", "localhost?@evil.com", "localhost\u2024evil.com", "[::1", "::1",
    ]
    userinfo = ["", "", "", "", "evil.com@", "user:pass@", "localhost@", "evil.com:80@", "evil.com\\@", "\\@"]
    ports = ["", "", "", ":11434", ":80", ":abc", ":", ":99999", ":-1"]
    paths = ["", "/v1", "/", "/v1?x=1", "/v1#frag", "/ v1", "/\tv1", "/v1\nx", "/\\v1", "/\u202e", "/v1\x00"]
    odd = [" ", "\t", "\n", "\\", "@", "\x00", "\x7f", "\u00a0", "\u3000", "#", "?", "%", "\u202e"]
    for _ in range(count):
        if rng.random() < 0.3:  # a mostly proper address, so the ones that are let through are tried too
            url = "http://" + rng.choice(["localhost", "LocalHost", "127.0.0.1", "[::1]", "ollama.localhost", "evil.com"]) + rng.choice(["", ":11434"]) + rng.choice(["", "/v1", "/v1?x=1"])
        else:
            url = rng.choice(schemes) + rng.choice(userinfo) + rng.choice(hosts) + rng.choice(ports) + rng.choice(paths)
        if rng.random() < 0.25:
            at = rng.randint(0, len(url))
            url = url[:at] + rng.choice(odd) + url[at:]
        yield url


@pytest.mark.parametrize("seed", SEEDS)
def test_a_model_address_is_this_computer_as_every_reader_sees_it_or_it_is_refused_and_nothing_else_happens(seed):
    rng = random.Random(seed)
    accepted = refused = 0
    for url in _made_up_urls(rng, 600):
        try:
            config = diya_config.load_config({"DIYA_OLLAMA_URL": url})
        except diya_config.ConfigError:
            refused += 1
            continue
        accepted += 1
        shown = url.strip()
        assert config.ollama_url == shown, url
        assert not any(char.isspace() or ord(char) < 32 or char in "\\@\x7f" for char in shown), repr(url)  # no spelling that two readers could take differently
        assert _this_computer((urlsplit(shown).hostname or "").lower()), repr(url)
        try:
            theirs = httpx.URL(shown).host.lower()
        except Exception:  # an address httpx cannot read is one the model client cannot connect to at all
            continue
        assert _this_computer(theirs), (repr(url), theirs)
    assert accepted >= 10 and refused >= 100, (accepted, refused)  # the made-up addresses really did reach both outcomes


# ---- the token ----------------------------------------------------------------------------------------------------------------

def _near_misses(rng, real):
    other = bytes([rng.choice([c for c in string.ascii_letters.encode() if c != real[0]])]) + real[1:]
    swapped = real.swapcase()
    return [real, real, real, real + b"x", real[:-1], other, swapped if swapped != real else real + b"0", b"", real + b" ", real + b"\t", real + b"\n", real[:len(real) // 2]]


@pytest.mark.parametrize("seed", SEEDS)
def test_only_the_exact_token_in_exactly_one_bearer_header_gets_in(seed):
    rng = random.Random(seed)
    real = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(rng.randint(8, 40))).encode()
    middleware = TokenMiddleware(None, hashlib.sha256(real).hexdigest(), True)
    let_in = turned_away = 0
    for _ in range(400):
        scheme = rng.choice([b"Bearer", b"bearer", b"BEARER", b"BeArEr", b"Basic", b"Bearer:", b"Token", b"", b"Bear", b"Bearers"])
        sep = rng.choice([b" ", b"  ", b"\t", b"", b" \t "])
        token = rng.choice(_near_misses(rng, real))
        headers = [(b"authorization", scheme + sep + token)]
        shape = rng.random()
        if shape < 0.1:
            headers.append((b"authorization", b"Bearer " + real))  # a second credential, even a right one
        elif shape < 0.2:
            headers = [(b"x-authorization", scheme + sep + token)]  # the right words in the wrong header
        elif shape < 0.3:
            headers = []
        elif shape < 0.4:
            headers.append((b"cookie", b"token=" + real))
        only_one = sum(1 for name, _value in headers if name == b"authorization") == 1
        expected = only_one and scheme.lower() == b"bearer" and sep != b"" and token == real
        assert middleware._authorized(headers) is expected, (headers, expected)
        let_in += expected
        turned_away += not expected
    assert let_in >= 20 and turned_away >= 100, (let_in, turned_away)


def test_with_no_stored_token_nothing_gets_in_even_the_right_words():
    for stored in (None, ""):
        assert TokenMiddleware(None, stored, True)._authorized([(b"authorization", b"Bearer anything")]) is False


# ---- printable ----------------------------------------------------------------------------------------------------------------

# Format characters that are part of real writing and are shown as they are: the joiners that emoji and Indic scripts need, and the script-specific marks (Arabic number signs, Syriac, Egyptian
# hieroglyph and musical-notation controls). Every other format character is invisible and must be shown as an escape.
_SHOWN_FORMAT = {0x200C, 0x200D, 0x6DD, 0x70F, 0x8E2, 0x110BD, 0x110CD} | set(range(0x600, 0x606)) | set(range(0x890, 0x892)) | set(range(0x13430, 0x13440)) | set(range(0x1BCA0, 0x1BCA4)) | set(range(0x1D173, 0x1D17B))
_FORMAT = [cp for cp in range(0x110000) if not 0xD800 <= cp <= 0xDFFF and unicodedata.category(chr(cp)) == "Cf" and cp not in _SHOWN_FORMAT]
_CLEAN_CHARS = string.ascii_letters + string.digits + " .,;:!?-()'\u0928\u092e\u0938\u094d\u0924\u0947\U0001f44d\u200d"
_NASTY_CHARS = (
    [chr(c) for c in range(0, 32)] + [chr(c) for c in range(0x7F, 0xA0)] + ["\u2028", "\u2029", "\u00a0", "\u3000", "\u200b", "\u202e", "\u2066", "\ufeff", "\ud800", "\udfff", "\ue000", "\U000f0000", "\\", "\\u202e"]
)


def _shows_nothing_hidden(out):
    for char in out:
        category = unicodedata.category(char)
        assert category not in ("Cc", "Cs", "Co", "Zl", "Zp"), repr(char)
        assert not (category == "Cf" and ord(char) not in _SHOWN_FORMAT), hex(ord(char))
        assert not char.isspace() or char == " ", repr(char)


@pytest.mark.parametrize("seed", SEEDS)
def test_whatever_text_is_given_what_is_shown_is_one_clean_line_that_a_second_pass_leaves_alone(seed):
    rng = random.Random(seed)
    pool = list(_CLEAN_CHARS) * 3 + _NASTY_CHARS + [chr(cp) for cp in rng.sample(_FORMAT, 60)]
    for _ in range(500):
        text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 60)))
        out = diya_memory.printable(text)
        _shows_nothing_hidden(out)
        assert out == out.strip() and "  " not in out, repr(out)
        assert diya_memory.printable(out) == out, repr(text)
        clean = "".join(rng.choice(_CLEAN_CHARS) for _ in range(rng.randint(0, 60)))
        assert diya_memory.printable(clean) == " ".join(clean.split()), repr(clean)  # clean text is shown as it is, apart from stray spaces
        limit = rng.randint(1, 40)
        assert len(diya_memory.printable(clean, limit)) <= limit + 3, repr(clean)


def test_every_invisible_format_character_there_is_is_shown_as_an_escape():
    """The whole Unicode table, not a sample: the 'tag' block that can hide a message (U+E0020 and on), the soft hyphen, invisible operators and the rest."""
    for cp in _FORMAT:
        escape = "\\u" + format(cp, "04x") if cp <= 0xFFFF else "\\U" + format(cp, "08x")
        assert diya_memory.printable("a" + chr(cp) + "b") == "a" + escape + "b", hex(cp)


def test_a_fact_cannot_carry_an_invisible_character_into_the_store():
    for cp in _FORMAT:
        with pytest.raises(diya_memory.InvalidFact):
            diya_memory.check_text("likes tea" + chr(cp))


# ---- short results, honest nudges ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_a_long_result_is_cut_only_when_over_the_limit_keeps_both_ends_and_is_not_cut_twice(seed):
    rng = random.Random(seed)
    limit, cap = diya_toolguard.THRESHOLD_CHARS, diya_toolguard.HEAD_CHARS + len(diya_toolguard.MARKER) + diya_toolguard.TAIL_CHARS
    for _ in range(150):
        length = rng.choice([0, 1, 100, limit - 1, limit, limit + 1, limit + 2, rng.randint(0, 3 * limit), 40_000])
        text = "".join(rng.choice(string.printable + "\u0928\U0001f44d") for _ in range(min(length, 300)))
        text = (text * (length // max(len(text), 1) + 1))[:length]
        out = diya_toolguard.prune(text)
        if len(text) <= limit:
            assert out is text
            continue
        assert len(out) <= cap < limit
        assert out.startswith(text[:diya_toolguard.HEAD_CHARS]) and out.endswith(text[-diya_toolguard.TAIL_CHARS:]) and diya_toolguard.MARKER in out
        assert diya_toolguard.prune(out) == out
    for other in (None, 5, 2.5, b"x" * 20_000, ["x"] * 20_000, {"a": "x" * 20_000}):
        assert diya_toolguard.prune(other) is other  # what is not text is not touched


@pytest.mark.parametrize("seed", SEEDS)
def test_the_repeating_reminder_comes_at_the_third_and_fifth_identical_call_in_a_row_and_only_then(seed):
    rng = random.Random(seed)
    calls = [("search", {"q": "a", "n": 1}), ("search", {"n": 1, "q": "a"}), ("search", {"q": "b", "n": 1}), ("read", {"q": "a", "n": 1}), ("read", "plain text")]
    for _ in range(60):
        guard = diya_toolguard.RepeatGuard()
        run, last = 0, None
        for _ in range(rng.randint(1, 25)):
            name, arguments = rng.choice(calls) if rng.random() < 0.6 or last is None else last_call
            last_call = (name, arguments)
            key = (name, json.dumps(arguments, sort_keys=True))
            run = run + 1 if key == last else 1
            last = key
            note = guard.after(name, arguments if rng.random() < 0.5 or not isinstance(arguments, dict) else json.dumps(arguments))  # the arguments as data or as the text the model wrote
            assert (note is not None) == (run in (3, 5)), (run, note)
            if run == 5:
                assert "Calls in a row: 5" in note


# ---- approvals ----------------------------------------------------------------------------------------------------------------

TERMINAL = ("succeeded", "failed", "rejected", "expired")


@pytest.mark.parametrize("seed", SEEDS)
def test_an_effect_runs_only_for_an_action_approved_before_it_expired_and_at_most_once_whatever_the_order_of_moves(seed, tmp_path):
    rng = random.Random(seed)
    clock = {"now": datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)}
    effects = []

    def validate(args):
        if not isinstance(args.get("title"), str):
            raise diya_actions.InvalidArgs("a task needs a title")

    def execute(config, args):
        effects.append(args["title"])
        if args["title"].endswith("x"):
            raise diya_actions.ActionFailed("it did not work")
        if args["title"].endswith("u"):
            raise diya_actions.ActionUncertain("no answer came")
        return "done"

    kind = diya_actions.ActionKind("add_task", "Add a task", None, validate, lambda args: f"Add the task {args['title']!r}", execute)
    actions = diya_actions.Actions(Store(str(tmp_path / "a.db")), diya_config.load_config({}), (kind,), clock=lambda: clock["now"])
    titles, last_status = [], {}

    def some_id():
        known = [a["id"] for a in actions.actions()]
        return rng.choice(known + [999]) if known else 999

    for step in range(rng.randint(40, 70)):
        move = rng.choice(["propose", "propose", "approve", "approve", "reject", "run", "run", "run", "wait", "expire", "reconcile", "resolve"])
        before = len(effects)
        try:
            if move == "propose":
                title = rng.choice(titles) if titles and rng.random() < 0.4 else f"t{step}{rng.choice(['', '', 'x', 'u'])}"
                action = actions.propose("add_task", {"title": title})
                titles.append(title)
                assert action["status"] == "pending" and len(effects) == before  # proposing never does anything
            elif move == "approve":
                target = some_id()
                shown = actions.get(target)["args_hash"] if target != 999 and rng.random() < 0.8 else "not-what-was-shown"
                actions.approve(target, shown, "ui")
            elif move == "reject":
                actions.reject(some_id(), "cli")
            elif move == "run":
                actions.run(some_id())
            elif move == "wait":
                clock["now"] += timedelta(minutes=rng.randint(1, 1800))
            elif move == "expire":
                actions.expire()
            elif move == "reconcile":
                actions.reconcile(older_than=timedelta(0))
            elif move == "resolve":
                actions.resolve(some_id(), rng.random() < 0.5, "ui")
        except diya_actions.ActionError:
            pass
        assert actions.verify_integrity() == [], (step, move)
        if move not in ("run",):
            assert len(effects) == before, (step, move)  # only `run` can ever do the thing
        for action in actions.actions():
            if last_status.get(action["id"]) in TERMINAL:
                assert action["status"] == last_status[action["id"]], (action["id"], last_status[action["id"]], action["status"])  # a finished action never changes
            last_status[action["id"]] = action["status"]
    ran = Counter()
    for action in actions.actions():
        names = [event[0] for event in actions.events(action["id"])]
        assert names.count("executing") <= 1, names
        if "executing" in names:
            index = names.index("executing")
            assert "approved" in names[:index] and not {"rejected", "expired"} & set(names[:index]), names
            moment = [event[2] for event in actions.events(action["id"]) if event[0] == "executing"][0]
            assert moment < action["expires_at"], (moment, action["expires_at"])  # not after its time was up
            ran[action["args"]["title"]] += 1
    assert Counter(effects) == ran, (Counter(effects), ran)  # every effect that happened was one action's one run, and every run did its effect


# ---- what it knew -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_what_it_knew_on_any_moment_is_exactly_the_accepted_facts_as_they_stood_then(seed, tmp_path, monkeypatch):
    rng = random.Random(seed)
    clock = {"now": datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(diya_memory, "_now", lambda: clock["now"].isoformat())
    store = Store(str(tmp_path / "m.db"))
    memory = Memory(store)
    start, snapshots = clock["now"], []
    for step in range(rng.randint(12, 24)):
        clock["now"] += timedelta(minutes=rng.randint(5, 3000))
        move = rng.choice(["add", "add", "retire", "restore"])
        try:
            if move == "add":
                memory.add_manual(f"likes {rng.choice(['tea', 'rain', 'chess', 'maths'])} number {step}", "api")
            else:
                wanted = "accepted" if move == "retire" else "retired"
                found = [fact["id"] for fact in memory.facts(wanted)]
                if found:
                    memory.decide(rng.choice(found), move, "api")
        except FactError:
            pass
        snapshots.append((clock["now"], memory.accepted_texts()))

    def events():
        conn = store.connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM fact_events").fetchone()[0]
        finally:
            conn.close()

    written = events()
    assert [fact["text"] for fact in memory.as_of(start - timedelta(days=1))] == []
    for index, (moment, texts) in enumerate(snapshots):
        assert [fact["text"] for fact in memory.as_of(moment)] == texts, (index, moment)
        if index + 1 < len(snapshots):
            between = moment + (snapshots[index + 1][0] - moment) / 2
            assert [fact["text"] for fact in memory.as_of(between)] == texts, (index, "between")
    assert events() == written  # asking writes nothing


# ---- the list ----------------------------------------------------------------------------------------------------------------

def test_the_invariants_page_names_every_test_here_and_only_tests_that_exist():
    page = (ROOT / "docs" / "INVARIANTS.md").read_text(encoding="utf-8")
    here = set(re.findall(r"^def (test_\w+)", Path(__file__).read_text(encoding="utf-8"), re.MULTILINE)) - {"test_the_invariants_page_names_every_test_here_and_only_tests_that_exist"}
    named = set(re.findall(r"tests/test_invariants\.py::(test_\w+)", page))
    assert named == here, (sorted(named - here), sorted(here - named))
