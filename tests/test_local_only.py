"""What you say stays on this computer unless you say otherwise (diya_config._check_model_stays_here; docs/LOCAL_ONLY.md; task DIYA-202), added 2026-10-21.

What this proves: with no setting, or a model address that is this computer (localhost, 127.0.0.1, ::1, a name ending in .localhost), the configuration loads; a model address that is any other computer
(a LAN address, a company host, a cloud API) is refused with words that say where the words would have gone and how to allow it on purpose; DIYA_ALLOW_REMOTE_MODEL=1 (or true, yes, on) allows it, and a
typo of it does not; and no program of Diya's takes a model address from anywhere but the configuration (so the one check covers them all). It does not prove the model server (Ollama) itself sends
nothing out: that is Ollama's own behaviour, and Diya's outbound hosts are listed in docs/AUTHORITY_MODEL.md.
"""
import re
from pathlib import Path

import pytest

import diya_config

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("url", [
    "http://localhost:11434/v1", "http://127.0.0.1:11434/v1", "http://[::1]:11434/v1", "http://ollama.localhost:11434/v1", "http://LOCALHOST:1/v1",
])
def test_this_computer_is_accepted(url):
    assert diya_config.load_config({"DIYA_OLLAMA_URL": url}).ollama_url == url


def test_no_setting_means_this_computer():
    assert diya_config.load_config({}).ollama_url.startswith("http://localhost")


@pytest.mark.parametrize("url", [
    "http://192.168.1.20:11434/v1", "https://api.openai.com/v1", "http://example.com/v1", "http://localhost.evil.com/v1", "http://10.0.0.5/v1", "http://[2001:db8::1]/v1",
])
def test_any_other_computer_is_refused_in_words_that_say_where_the_words_would_go(url):
    with pytest.raises(diya_config.ConfigError) as caught:
        diya_config.load_config({"DIYA_OLLAMA_URL": url})
    message = str(caught.value)
    assert "not this computer" in message and "DIYA_ALLOW_REMOTE_MODEL=1" in message


@pytest.mark.parametrize("flag, allowed", [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("no", False), ("", False), ("sure", False)])
def test_only_the_explicit_word_allows_it(flag, allowed):
    env = {"DIYA_OLLAMA_URL": "http://192.168.1.20:11434/v1", "DIYA_ALLOW_REMOTE_MODEL": flag}
    if allowed:
        assert diya_config.load_config(env).ollama_url == "http://192.168.1.20:11434/v1"
    else:
        with pytest.raises(diya_config.ConfigError):
            diya_config.load_config(env)


def test_every_program_that_talks_to_the_model_takes_the_address_from_the_configuration():
    """A hard-coded model address anywhere but the archived Phase 1 learning scripts would sidestep the check."""
    offenders = []
    for path in ROOT.glob("*.py"):
        if path.name.startswith("milestone") or path.name in ("diya_chat.py", "dossier_content.py"):  # the archived learning scripts and the research dossier's text, not the app
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hard_coded = re.search(r"OpenAI\(\s*base_url\s*=\s*[\"']", line) or ("11434" in line and path.name not in ("diya_config.py", "diya_warm.py", "diya_run.py"))
            if hard_coded:
                offenders.append((path.name, number))
    assert offenders == []


def test_the_policy_page_says_the_rule_and_how_to_break_it_on_purpose():
    text = (ROOT / "docs" / "LOCAL_ONLY.md").read_text(encoding="utf-8")
    assert "DIYA_ALLOW_REMOTE_MODEL=1" in text and "not this computer" in text
