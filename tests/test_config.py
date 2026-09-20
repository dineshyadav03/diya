import os
import pathlib
import re

import pytest

import diya_config
from diya_config import Config, ConfigError, load_config, tls_files

ROOT = pathlib.Path(__file__).resolve().parent.parent


# --- defaults must be exactly what used to be hard-coded --------------------

def test_defaults_are_the_previously_hardcoded_values():
    assert load_config({}) == Config(
        db_path="diya.db",
        model="qwen2.5:3b",
        embed_model="nomic-embed-text",
        ollama_url="http://localhost:11434/v1",
        notes_dir="sample_notes",
        profile_path="user_profile.txt",
        dream_log_path="dream_log.txt",
        dream_state_path="dream_state.json",
        dream_pending_path="dream_pending.jsonl",
        dream_profile_mode="staged",
        whisper_model="base",
        host="0.0.0.0",
        port=8080,
        ssl_certfile=None,
        ssl_keyfile=None,
    )


def test_every_setting_can_be_overridden():
    env = {
        "DIYA_DB_PATH": "x.db", "DIYA_MODEL": "m", "DIYA_EMBED_MODEL": "e",
        "DIYA_OLLAMA_URL": "http://o:1/v1", "DIYA_NOTES_DIR": "n", "DIYA_PROFILE_PATH": "p.txt",
        "DIYA_DREAM_LOG_PATH": "d.log", "DIYA_DREAM_STATE_PATH": "d.json",
        "DIYA_DREAM_PENDING_PATH": "q.jsonl", "DIYA_DREAM_PROFILE_MODE": "direct",
        "DIYA_WHISPER_MODEL": "small", "DIYA_HOST": "127.0.0.1", "DIYA_PORT": "9000",
        "DIYA_SSL_CERT": "c.pem", "DIYA_SSL_KEY": "k.pem",
    }
    cfg = load_config(env)
    assert (cfg.db_path, cfg.model, cfg.embed_model, cfg.ollama_url) == ("x.db", "m", "e", "http://o:1/v1")
    assert (cfg.notes_dir, cfg.profile_path, cfg.whisper_model) == ("n", "p.txt", "small")
    assert (cfg.host, cfg.port, cfg.ssl_certfile, cfg.ssl_keyfile) == ("127.0.0.1", 9000, "c.pem", "k.pem")
    assert (cfg.dream_log_path, cfg.dream_state_path) == ("d.log", "d.json")
    assert (cfg.dream_pending_path, cfg.dream_profile_mode) == ("q.jsonl", "direct")


def test_blank_values_count_as_unset():
    assert load_config({"DIYA_MODEL": "", "DIYA_PORT": "  ", "DIYA_DB_PATH": " "}) == Config()


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("DIYA_MODEL", "from-environ")
    assert load_config().model == "from-environ"


def test_is_evaluated_per_call_not_cached(monkeypatch):
    monkeypatch.setenv("DIYA_MODEL", "first")
    assert load_config().model == "first"
    monkeypatch.setenv("DIYA_MODEL", "second")
    assert load_config().model == "second"


@pytest.mark.parametrize("bad", ["abc", "80.5", "0", "70000", "-1"])
def test_bad_port_is_rejected_with_a_clear_message(bad):
    with pytest.raises(ConfigError, match="DIYA_PORT"):
        load_config({"DIYA_PORT": bad})


def test_dreaming_is_staged_by_default():
    assert load_config({}).dream_profile_mode == "staged"


@pytest.mark.parametrize("value, expected", [("staged", "staged"), ("direct", "direct"), (" Direct ", "direct"), ("STAGED", "staged")])
def test_dream_profile_mode_accepts_the_two_known_modes(value, expected):
    assert load_config({"DIYA_DREAM_PROFILE_MODE": value}).dream_profile_mode == expected


@pytest.mark.parametrize("bad", ["auto", "append", "off", "true"])
def test_an_unknown_dream_profile_mode_is_rejected_not_guessed(bad):
    with pytest.raises(ConfigError, match="DIYA_DREAM_PROFILE_MODE"):
        load_config({"DIYA_DREAM_PROFILE_MODE": bad})


def test_ssl_cert_and_key_must_come_as_a_pair():
    with pytest.raises(ConfigError, match="together"):
        load_config({"DIYA_SSL_CERT": "c.pem"})
    with pytest.raises(ConfigError, match="together"):
        load_config({"DIYA_SSL_KEY": "k.pem"})


def test_load_config_touches_no_files(tmp_path):
    load_config({"DIYA_DB_PATH": str(tmp_path / "nope" / "x.db"), "DIYA_NOTES_DIR": str(tmp_path / "nope")})
    assert list(tmp_path.iterdir()) == []


def test_module_source_contains_no_hardcoded_lan_address():
    source = (ROOT / "diya_config.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", source)


# --- TLS file resolution -----------------------------------------------------

def _touch(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_text("x")


def test_tls_none_when_nothing_configured_or_found(tmp_path):
    assert tls_files(Config(), str(tmp_path)) is None


def test_tls_discovers_a_single_mkcert_pair_without_knowing_the_address(tmp_path):
    _touch(tmp_path, "10.1.2.3+2.pem", "10.1.2.3+2-key.pem")
    cert, key = tls_files(Config(), str(tmp_path))
    assert os.path.basename(cert) == "10.1.2.3+2.pem" and os.path.basename(key) == "10.1.2.3+2-key.pem"


def test_tls_ignores_a_key_with_no_matching_cert(tmp_path):
    _touch(tmp_path, "lonely+1-key.pem")
    assert tls_files(Config(), str(tmp_path)) is None


def test_tls_refuses_to_guess_between_several_pairs(tmp_path):
    _touch(tmp_path, "a+1.pem", "a+1-key.pem", "b+2.pem", "b+2-key.pem")
    with pytest.raises(ConfigError, match="More than one"):
        tls_files(Config(), str(tmp_path))


def test_tls_explicit_settings_win_over_discovery(tmp_path):
    _touch(tmp_path, "a+1.pem", "a+1-key.pem", "mine.pem", "mine-key.pem")
    cfg = Config(ssl_certfile=str(tmp_path / "mine.pem"), ssl_keyfile=str(tmp_path / "mine-key.pem"))
    assert tls_files(cfg, str(tmp_path)) == (cfg.ssl_certfile, cfg.ssl_keyfile)


def test_tls_explicit_but_missing_file_is_an_error(tmp_path):
    cfg = Config(ssl_certfile=str(tmp_path / "gone.pem"), ssl_keyfile=str(tmp_path / "gone-key.pem"))
    with pytest.raises(ConfigError, match="not found"):
        tls_files(cfg, str(tmp_path))


# --- the isolation guard for the whole suite --------------------------------

def test_suite_can_never_resolve_to_the_live_database(isolated_environment):
    tmp = isolated_environment
    live = (ROOT / "diya.db").resolve()
    assert pathlib.Path(load_config().db_path).resolve().parent == tmp.resolve()
    assert pathlib.Path(load_config().db_path).resolve() != live
    # and even with DIYA_DB_PATH unset, the relative default lands in the temp cwd
    os.environ.pop("DIYA_DB_PATH")
    assert pathlib.Path(load_config().db_path).resolve() == (tmp / "diya.db").resolve()
    assert pathlib.Path.cwd().resolve() == tmp.resolve()
