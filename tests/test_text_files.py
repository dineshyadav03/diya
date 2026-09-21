"""Line endings and encodings: every text file Diya writes is UTF-8, the profile is LF-only,
and everything that reads them uses the same rules (no platform-default codec, no CRLF drift)."""
import dataclasses
import pathlib
import shutil
import subprocess

import pytest

import diya
import diya_config
from dreaming import Dreamer
from fakes import FakeClient, text_reply
from diya_db import Store

ROOT = pathlib.Path(__file__).resolve().parent.parent
BINARY_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".zip"}
CRLF_OK_EXT = {".bat", ".cmd"}  # Windows batch files genuinely need CRLF (see .gitattributes)
UTF8_BOM = b"\xef\xbb\xbf"


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(tmp_path / "t.db"),
        profile_path=str(tmp_path / "profile.txt"),
        dream_state_path=str(tmp_path / "state.json"),
        dream_pending_path=str(tmp_path / "pending.jsonl"),
        notes_dir=str(tmp_path / "notes"),
        dream_profile_mode="direct",
    )


def agent_for(config):
    return diya.Agent(config, client=FakeClient())


# --- the agent reads the profile as UTF-8, whatever the line endings ----------------------------

def test_a_non_ascii_profile_is_read_as_utf8_not_the_platform_codec(config):
    pathlib.Path(config.profile_path).write_bytes("- Loves café and naïve art\n".encode("utf-8"))
    system = agent_for(config).with_profile([])[0]["content"]
    assert "café" in system and "naïve" in system  # cp1252 would give 'cafÃ©'


def test_crlf_and_mixed_profiles_read_identically_to_lf(config):
    body = {b"- a\n- b\n": None, b"- a\r\n- b\r\n": None, b"- a\r\n- b\n": None}
    seen = set()
    for raw in body:
        pathlib.Path(config.profile_path).write_bytes(raw)
        seen.add(agent_for(config).with_profile([])[0]["content"])
    assert seen == {"What you know about the user so far:\n- a\n- b"}  # no stray \r in any case


def test_a_stray_invalid_byte_does_not_take_chat_down(config):
    pathlib.Path(config.profile_path).write_bytes(b"- fine fact\n- bad \xff byte\n")
    system = agent_for(config).with_profile([])[0]["content"]
    assert "fine fact" in system


def test_notes_are_read_as_utf8(config):
    notes = pathlib.Path(config.notes_dir)
    notes.mkdir()
    (notes / "dentist.txt").write_bytes("Dentist appointment at the café on Tuesday.".encode("utf-8"))
    assert agent_for(config).search_notes("dentist") == "Dentist appointment at the café on Tuesday."


# --- Dreaming writes UTF-8 and LF only -------------------------------------------------------------

def test_direct_mode_appends_utf8_with_lf_only(config):
    Store(config.db_path)  # (lazy) -- the message below creates it
    store = Store(config.db_path)
    store.add_message(store.create_thread(), "user", "I love the café")
    profile = pathlib.Path(config.profile_path)
    profile.write_bytes(b"- likes tea\n")  # an LF profile, as it is now
    Dreamer(config, client=FakeClient([text_reply("- loves the café")])).dream_cycle()
    assert profile.read_bytes() == b"- likes tea\n- loves the caf\xc3\xa9\n"  # UTF-8, and no CR anywhere


def test_dreaming_and_the_agent_agree_on_a_non_ascii_fact(config):
    """The original mismatch, end to end: Dreaming appended UTF-8, the agent read cp1252."""
    store = Store(config.db_path)
    store.add_message(store.create_thread(), "user", "My cat is called Zoë")
    Dreamer(config, client=FakeClient([text_reply("- cat is called Zoë")])).dream_cycle()
    assert "- cat is called Zoë" in agent_for(config).with_profile([])[0]["content"]


def test_save_profile_writes_utf8_and_lf(config):
    Dreamer(config, client=FakeClient()).save_profile("  - café  \n\n")
    assert pathlib.Path(config.profile_path).read_bytes() == b"- caf\xc3\xa9\n"


def test_load_profile_reads_utf8(config):
    pathlib.Path(config.profile_path).write_bytes("- café\n".encode("utf-8"))
    assert Dreamer(config, client=FakeClient()).load_profile() == "- café"


def test_the_checkpoint_file_is_lf_only_ascii_json(config):
    Dreamer(config, client=FakeClient()).save_last_dreamed_id(7)
    assert pathlib.Path(config.dream_state_path).read_bytes() == b'{"last_message_id": 7}'


# --- the repository itself: .gitattributes pins LF, and the files honour it ---------------------------

def _git(*args):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return result.stdout


def test_gitattributes_pins_lf_and_leaves_binaries_alone():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in text
    for path, expected in (("diya.py", {"eol": "lf", "text": "auto"}), ("Truffle_Research_Dossier.pdf", {"text": "unset"})):
        attrs = {}
        for line in _git("check-attr", "eol", "text", "--", path).splitlines():
            _, name, value = line.split(": ")
            attrs[name] = value
        assert {k: attrs[k] for k in expected} == expected, path


def test_every_tracked_text_file_is_utf8_without_a_bom_and_has_no_cr():
    problems = []
    for name in _git("ls-files").splitlines():
        path = ROOT / name
        ext = path.suffix.lower()
        if ext in BINARY_EXT or not path.is_file():
            continue
        raw = path.read_bytes()
        if raw.startswith(UTF8_BOM):
            problems.append(f"{name}: has a UTF-8 BOM")
        if b"\r" in raw and ext not in CRLF_OK_EXT:
            problems.append(f"{name}: contains CR (CRLF or lone CR) -- line endings are LF only")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{name}: not valid UTF-8 ({exc})")
    assert not problems, "\n".join(problems)
