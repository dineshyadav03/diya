"""DIYA_DATA_DIR: one folder for everything Diya writes about the person (audit F3, docs/AUDIT_2026-10-10.md).

By default each of those files sits beside the code, in the working directory, which for this project is inside a folder a cloud-sync
program may be copying. With DIYA_DATA_DIR set they all default to the same names inside that folder instead, and each file's own
DIYA_* setting still wins. Reading the settings touches no disk; the programs that start Diya make the folder.
"""
import io
import os

import pytest

import diya_config
import diya_db
import diya_notify
import dreaming

# field -> the file name it has by default; with a data folder, the same name inside it
FILES = {
    "db_path": "diya.db", "profile_path": "user_profile.txt", "dream_log_path": "dream_log.txt", "dream_state_path": "dream_state.json",
    "dream_pending_path": "dream_pending.jsonl", "notify_log_path": "notify_log.txt", "token_path": "diya_token.hash",
    "connector_tokens_dir": "connector_tokens", "connectors_log_path": "connectors_log.txt",
}


def test_without_a_data_folder_nothing_changes():
    config = diya_config.load_config({})
    assert config.data_dir == ""
    assert {field: getattr(config, field) for field in FILES} == FILES


def test_the_files_follow_the_default_names_in_the_config():
    """The mapping is built from the defaults themselves, so a default renamed in Config moves with it."""
    assert {field: diya_config.Config.__dataclass_fields__[field].default for field in FILES} == FILES
    assert diya_config._DATA_FILES == tuple(FILES)


def test_with_a_data_folder_every_one_of_them_lives_in_it(tmp_path):
    config = diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path / "data")})
    assert config.data_dir == str(tmp_path / "data")
    assert {field: getattr(config, field) for field in FILES} == {field: os.path.join(str(tmp_path / "data"), name) for field, name in FILES.items()}


@pytest.mark.parametrize("field, variable", [("db_path", "DIYA_DB_PATH"), ("token_path", "DIYA_TOKEN_PATH"), ("dream_log_path", "DIYA_DREAM_LOG_PATH"),
                                             ("connector_tokens_dir", "DIYA_CONNECTOR_TOKENS_DIR"), ("profile_path", "DIYA_PROFILE_PATH")])
def test_a_files_own_setting_wins_and_the_others_still_move(tmp_path, field, variable):
    config = diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path / "data"), variable: str(tmp_path / "elsewhere")})
    assert getattr(config, field) == str(tmp_path / "elsewhere")
    assert all(getattr(config, other).startswith(str(tmp_path / "data")) for other in FILES if other != field)


def test_what_is_not_about_the_person_stays_where_it_was(tmp_path):
    config = diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path / "data")})
    assert (config.notes_dir, config.whisper_model, config.model) == ("sample_notes", "base", "qwen2.5:3b")


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_data_folder_is_no_data_folder(value):
    assert diya_config.load_config({"DIYA_DATA_DIR": value}).db_path == "diya.db"


def test_reading_the_settings_does_not_make_the_folder(tmp_path):
    diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path / "data")})
    assert not (tmp_path / "data").exists()


def test_the_folder_is_made_with_its_parents_and_making_it_twice_is_fine(tmp_path):
    config = diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path / "a" / "b")})
    diya_config.ensure_data_dir(config)
    diya_config.ensure_data_dir(config)
    assert (tmp_path / "a" / "b").is_dir()


def test_with_no_data_folder_making_it_does_nothing(tmp_path):
    diya_config.ensure_data_dir(diya_config.load_config({}))
    assert list(tmp_path.iterdir()) == []


def test_a_database_in_a_folder_that_does_not_exist_yet_is_made_there(tmp_path):
    store = diya_db.Store(str(tmp_path / "x" / "y" / "d.db"))
    assert store.create_thread() == 1
    assert (tmp_path / "x" / "y" / "d.db").is_file()


def test_a_database_in_the_working_directory_still_needs_no_folder(tmp_path):
    assert diya_db.Store("plain.db").create_thread() == 1
    assert (tmp_path / "plain.db").is_file()


def test_dreaming_writes_its_log_state_and_database_in_the_data_folder_and_nothing_beside_the_code(tmp_path, monkeypatch):
    monkeypatch.delenv("DIYA_DB_PATH")  # the test harness points it at a temp file; this test is about the folder
    monkeypatch.setenv("DIYA_DATA_DIR", str(tmp_path / "data"))
    assert dreaming.main() == 0
    assert (tmp_path / "data" / "dream_log.txt").is_file() and (tmp_path / "data" / "diya.db").is_file()
    assert [p.name for p in tmp_path.iterdir()] == ["data"]  # beside the code (the working directory): nothing


def test_the_notifier_makes_the_folder_before_it_looks_for_anything(tmp_path, monkeypatch):
    monkeypatch.delenv("DIYA_DB_PATH")
    monkeypatch.setenv("DIYA_DATA_DIR", str(tmp_path / "data"))
    out = io.StringIO()
    assert diya_notify.main(["--dry-run"], out=out, notify=lambda title, body: None) == 0
    assert (tmp_path / "data").is_dir() and (tmp_path / "data" / "diya.db").is_file()


def test_a_folder_that_cannot_be_made_is_said_not_raised(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("in the way")
    monkeypatch.setenv("DIYA_DATA_DIR", str(tmp_path / "file" / "data"))  # a folder cannot be made inside a file
    assert dreaming.main() == 1
    assert "[error]" in (tmp_path / "dream_log.txt").read_text(encoding="utf-8")


def test_the_notifier_logs_in_the_data_folder_even_when_the_database_is_elsewhere(tmp_path, monkeypatch):
    """The test harness already points the database at a temp file; the log must still land in the data folder, which the notifier makes."""
    from datetime import datetime

    import diya_time

    store = diya_db.Store(str(tmp_path / "test.db"))
    store.add_reminder("call mum", "yesterday", diya_time.iso_of_local(datetime(2026, 9, 22, 10, 0)))
    monkeypatch.setenv("DIYA_DATA_DIR", str(tmp_path / "data"))
    shown = []
    out = io.StringIO()
    assert diya_notify.main([], out=out, notify=lambda title, body: shown.append(title), now=datetime(2026, 9, 23, 10, 0)) == 0
    assert shown and (tmp_path / "data" / "notify_log.txt").is_file()
    assert "1 due, 1 told" in (tmp_path / "data" / "notify_log.txt").read_text(encoding="utf-8")


def test_the_notifier_says_when_the_data_folder_cannot_be_made_and_does_nothing_else(tmp_path, monkeypatch):
    (tmp_path / "file").write_text("in the way")
    monkeypatch.setenv("DIYA_DATA_DIR", str(tmp_path / "file" / "data"))
    out = io.StringIO()
    shown = []
    assert diya_notify.main([], out=out, notify=lambda title, body: shown.append(title)) == diya_notify.EXIT_UNUSABLE
    assert out.getvalue().startswith("diya_notify: ") and shown == []
