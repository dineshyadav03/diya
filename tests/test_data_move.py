"""`python diya_data.py move`: copy Diya's data out of the code folder, check the copy, delete nothing (audit F3).

What this proves: every file the data folder holds is copied, byte for byte, and the database as a faithful copy (same rows in every table, both
integrity checks pass); the originals are never changed or removed; nothing is copied if anything would be refused; a file that differs is never
overwritten, but a database with no data in it (what a scheduled task makes if it runs first) is replaced and a second run changes nothing; a
cloud-sync folder is refused; a copy that does not check out is reported and no setting is offered; the printed settings, applied, point Diya at
the copy; and what is printed never contains what is in a file.
"""
import hashlib
import io
import os
import pathlib
import sqlite3

import pytest

import diya_config
import diya_data
import diya_db
import diya_memory

SECRET = "MY-PRIVATE-FACT-TEXT"


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


@pytest.fixture
def home(tmp_path):
    """A code folder with data in it, as it is in real life (the harness has already made the working directory this folder)."""
    store = diya_db.Store("diya.db")
    thread = store.create_thread()
    store.add_message(thread, "user", "hello there")
    store.add_message(thread, "assistant", "hi")
    store.add_reminder("call mum")
    diya_memory.Memory(store).add_manual(SECRET, "api")
    pathlib.Path("diya_token.hash").write_text("a" * 64 + "\n")
    pathlib.Path("dream_state.json").write_text('{"last_message_id": 2}')
    pathlib.Path("dream_pending.jsonl").write_text('{"facts": []}\n')
    pathlib.Path("dream_log.txt").write_text("--- dream cycle ---\n")
    pathlib.Path("user_profile.txt").write_text("- likes tea\n")
    (tmp_path / "connector_tokens").mkdir()
    (tmp_path / "connector_tokens" / "notion.token").write_text("a-token-value\n")
    pathlib.Path("connectors_log.txt").write_text("log\n")
    pathlib.Path("localhost+2.pem").write_text("CERT-BODY-7731")
    pathlib.Path("localhost+2-key.pem").write_text("KEY-BODY-7731")
    return tmp_path


@pytest.fixture
def config(home, monkeypatch):
    monkeypatch.delenv("DIYA_DB_PATH")  # the harness points it at a temp file; the data here is at the defaults
    monkeypatch.delenv("DIYA_PROFILE_PATH")
    return diya_config.load_config()


def run(config, *argv):
    out = io.StringIO()
    code = diya_data.main(list(argv), config=config, out=lambda line="": out.write(line + "\n"))
    return code, out.getvalue()


@pytest.fixture
def destination(tmp_path_factory):
    return tmp_path_factory.mktemp("elsewhere") / "diya-data"


FILES = ["diya_token.hash", "dream_state.json", "dream_pending.jsonl", "dream_log.txt", "user_profile.txt", "connectors_log.txt"]


def test_everything_is_copied_and_checked(home, config, destination):
    code, out = run(config, "move", "--to", str(destination))
    assert code == 0, out
    for name in FILES:
        assert digest(destination / name) == digest(home / name), name
    assert digest(destination / "connector_tokens" / "notion.token") == digest(home / "connector_tokens" / "notion.token")
    old, new = sqlite3.connect(home / "diya.db"), sqlite3.connect(destination / "diya.db")
    for table in ("threads", "messages", "reminders", "facts", "fact_events", "migrations"):
        assert old.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == new.execute(f"SELECT COUNT(*) FROM {table}").fetchone() != (0,), table
    assert diya_memory.Memory(diya_db.Store(str(destination / "diya.db"))).accepted_texts() == [SECRET]
    assert out.count("checked ") == 8 and "CHECK FAILED" not in out


def test_the_originals_are_not_changed_or_removed(home, config, destination):
    before = {name: digest(home / name) for name in FILES + ["diya.db", "connector_tokens/notion.token"]}
    run(config, "move", "--to", str(destination))
    assert {name: digest(home / name) for name in before} == before


def test_what_does_not_exist_is_not_made_up(home, config, destination):
    (home / "user_profile.txt").unlink()
    code, out = run(config, "move", "--to", str(destination))
    assert code == 0 and not (destination / "user_profile.txt").exists() and not (destination / "notify_log.txt").exists()


def test_a_dry_run_says_what_it_would_do_and_does_nothing(home, config, destination):
    code, out = run(config, "move", "--to", str(destination), "--dry-run")
    assert code == 0 and not destination.exists() and "Dry run: nothing was copied." in out and "would copy" in out and "diya.db" in out


def test_a_file_that_differs_is_never_overwritten_and_nothing_else_is_copied_either(home, config, destination):
    destination.mkdir(parents=True)
    (destination / "diya_token.hash").write_text("b" * 64 + "\n")
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_REFUSED and "not overwritten" in out and out.startswith("Nothing was copied")
    assert (destination / "diya_token.hash").read_text() == "b" * 64 + "\n"
    assert not (destination / "diya.db").exists() and not (destination / "dream_log.txt").exists()  # the refusal came before any copy


def test_a_database_with_no_data_in_it_is_replaced_because_that_is_what_a_scheduled_task_leaves_behind(home, config, destination):
    destination.mkdir(parents=True)
    diya_db.Store(str(destination / "diya.db")).connect().close()  # migrations only
    assert diya_data.database_is_empty(str(destination / "diya.db"))
    code, out = run(config, "move", "--to", str(destination))
    assert code == 0 and "replace" in out
    assert diya_memory.Memory(diya_db.Store(str(destination / "diya.db"))).accepted_texts() == [SECRET]


def test_a_database_with_anything_in_it_is_never_replaced(home, config, destination):
    destination.mkdir(parents=True)
    other = diya_db.Store(str(destination / "diya.db"))
    other.add_message(other.create_thread(), "user", "a chat that is only here")
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_REFUSED and "not overwritten" in out
    assert other.get_history(1) == [{"role": "user", "content": "a chat that is only here"}]


def test_a_file_that_is_not_a_database_is_not_called_empty(tmp_path):
    (tmp_path / "x.db").write_text("this is not a database")
    assert diya_data.database_is_empty(str(tmp_path / "x.db")) is False


def test_a_second_run_changes_nothing_and_says_so(home, config, destination):
    run(config, "move", "--to", str(destination))
    before = {p.name: digest(p) for p in destination.rglob("*") if p.is_file()}
    code, out = run(config, "move", "--to", str(destination))
    assert code == 0 and "same" in out and "checked " not in out
    assert {p.name: digest(p) for p in destination.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("folder", ["OneDrive/Desktop/diya", "Dropbox/diya", "Google Drive/diya", "iCloud/diya", "onedrive - work/x"])
def test_a_cloud_sync_folder_is_refused_unless_it_is_asked_for(home, config, tmp_path, folder):
    target = tmp_path / folder
    code, out = run(config, "move", "--to", str(target))
    assert code == diya_data.EXIT_REFUSED and "--allow-synced" in out and not target.exists()
    code, out = run(config, "move", "--to", str(target), "--allow-synced")
    assert code == 0 and (target / "diya.db").is_file()


def test_other_folders_are_not_mistaken_for_cloud_ones(tmp_path):
    assert diya_data.synced_folder(str(tmp_path / "Diya" / "data")) is None
    assert diya_data.synced_folder(str(tmp_path / "my-drive" / "x")) is None
    assert diya_data.synced_folder(str(tmp_path / "OneDrive" / "x")) == "onedrive"


def test_certificates_are_copied_only_when_asked_and_the_settings_for_them_are_printed(home, config, destination):
    code, out = run(config, "move", "--to", str(destination))
    assert code == 0 and not (destination / "certs").exists() and "DIYA_SSL" not in out
    code, out = run(config, "move", "--to", str(destination), "--certs")
    assert code == 0 and (destination / "certs" / "localhost+2.pem").read_text() == "CERT-BODY-7731" and (destination / "certs" / "localhost+2-key.pem").read_text() == "KEY-BODY-7731"
    assert "SetEnvironmentVariable('DIYA_SSL_CERT'" in out and "SetEnvironmentVariable('DIYA_SSL_KEY'" in out


def test_certificates_that_do_not_exist_are_a_refusal_not_a_silent_skip(home, config, destination):
    (home / "localhost+2.pem").unlink()
    (home / "localhost+2-key.pem").unlink()
    code, out = run(config, "move", "--to", str(destination), "--certs")
    assert code == diya_data.EXIT_REFUSED and "no TLS certificate pair" in out and not destination.exists()


def test_the_settings_it_prints_point_diya_at_the_copy(home, config, destination):
    code, out = run(config, "move", "--to", str(destination), "--certs")
    assert f"SetEnvironmentVariable('DIYA_DATA_DIR', '{destination}', 'User')" in out
    moved = diya_config.load_config({"DIYA_DATA_DIR": str(destination), "DIYA_SSL_CERT": str(destination / "certs" / "localhost+2.pem"),
                                     "DIYA_SSL_KEY": str(destination / "certs" / "localhost+2-key.pem")})
    for field, name in (("db_path", "diya.db"), ("token_path", "diya_token.hash"), ("dream_state_path", "dream_state.json"), ("connector_tokens_dir", "connector_tokens")):
        assert getattr(moved, field) == str(destination / name) and os.path.exists(getattr(moved, field)), field
    assert diya_config.tls_files(moved) == (moved.ssl_certfile, moved.ssl_keyfile)


def test_a_quote_in_the_folder_name_is_made_safe_in_the_printed_command(home, config, tmp_path_factory):
    target = tmp_path_factory.mktemp("elsewhere") / "o'brien data"
    code, out = run(config, "move", "--to", str(target))
    assert code == 0 and f"'{str(target).replace(chr(39), chr(39) * 2)}'" in out


def test_what_is_printed_is_names_and_sizes_never_what_is_inside(home, config, destination):
    code, out = run(config, "move", "--to", str(destination), "--certs")
    for secret in (SECRET, "a-token-value", "a" * 64, "CERT-BODY-7731", "KEY-BODY-7731", "hello there"):
        assert secret not in out, secret


def test_a_copy_that_does_not_check_out_is_reported_and_no_setting_is_offered(home, config, destination, monkeypatch):
    real = diya_data.shutil.copy2

    def truncating(source, target, **kwargs):
        real(source, target, **kwargs)
        pathlib.Path(target).write_bytes(pathlib.Path(target).read_bytes()[:-1])

    monkeypatch.setattr(diya_data.shutil, "copy2", truncating)
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_FAILED and "CHECK FAILED" in out and "not identical" in out
    assert "SetEnvironmentVariable" not in out and "do not apply any setting" in out


def test_a_database_copy_with_missing_rows_is_caught(home, config, destination, monkeypatch):
    real = diya_data._copy_database

    def lossy(source, target):
        real(source, target)
        conn = sqlite3.connect(target)
        conn.execute("DELETE FROM messages")
        conn.commit()
        conn.close()

    monkeypatch.setattr(diya_data, "_copy_database", lossy)
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_FAILED and "table messages has 0 rows in the copy and 2 in the original" in out and "SetEnvironmentVariable" not in out


def test_nothing_to_move_is_said_plainly(tmp_path, destination, monkeypatch):
    monkeypatch.delenv("DIYA_DB_PATH")
    monkeypatch.delenv("DIYA_PROFILE_PATH")
    code, out = run(diya_config.load_config(), "move", "--to", str(destination))
    assert code == 0 and "nothing to move" in out and not destination.exists()


def test_a_destination_that_cannot_be_made_is_said_and_the_originals_are_left_alone(home, config, tmp_path):
    (tmp_path / "file").write_text("in the way")
    code, out = run(config, "move", "--to", str(tmp_path / "file" / "data"))
    assert code in (diya_data.EXIT_FAILED, diya_data.EXIT_REFUSED) and "SetEnvironmentVariable" not in out and (home / "diya.db").is_file()


def test_the_command_line_needs_a_command_and_a_destination(config):
    assert run(config)[0] != 0
    assert run(config, "move")[0] != 0


# --- found by mutation testing -------------------------------------------------------------------------------------------------

def test_the_check_of_the_copy_looks_at_the_database_s_own_integrity_check(home, config, destination, monkeypatch):
    real = diya_data._readonly

    class Damaged:
        """A connection that is the real one except that SQLite's integrity check says the file is damaged."""

        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if "integrity_check" in sql:
                return type("Row", (), {"fetchone": lambda self: ("*** in database main *** page 2 is damaged",)})()
            return self.conn.execute(sql, *args)

        def close(self):
            self.conn.close()

    monkeypatch.setattr(diya_data, "_readonly", lambda path: Damaged(real(path)) if os.path.abspath(path).startswith(str(destination)) else real(path))
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_FAILED and "integrity check of the copy did not say ok" in out and "SetEnvironmentVariable" not in out


def test_a_table_that_is_missing_from_the_copy_is_named(home, config, destination, monkeypatch):
    real = diya_data._copy_database

    def without_a_table(source, target):
        real(source, target)
        conn = sqlite3.connect(target)
        conn.execute("DROP TABLE reminders")
        conn.commit()
        conn.close()

    monkeypatch.setattr(diya_data, "_copy_database", without_a_table)
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_FAILED and "table reminders is missing from the copy" in out and "SetEnvironmentVariable" not in out


def test_the_memory_s_own_integrity_check_is_run_on_the_copy(home, config, destination):
    conn = sqlite3.connect(home / "diya.db")
    conn.execute("UPDATE facts SET status = 'retired'")  # a status no event explains: the trail and the fact disagree
    conn.commit()
    conn.close()
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_FAILED and "memory integrity:" in out and "SetEnvironmentVariable" not in out


def test_a_connectors_folder_with_a_file_missing_or_changed_in_the_copy_is_caught(home, config, destination, monkeypatch):
    (home / "connector_tokens" / "todoist.token").write_text("another-token\n")
    real = diya_data._copy_folder

    def lossy(source, target):
        real(source, target)
        os.remove(os.path.join(target, "todoist.token"))

    monkeypatch.setattr(diya_data, "_copy_folder", lossy)
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_FAILED and "todoist.token is missing or different in the copy" in out

    def altered(source, target):
        real(source, target)
        pathlib.Path(target, "notion.token").write_text("not what it was\n")

    other = destination.parent / "second"
    monkeypatch.setattr(diya_data, "_copy_folder", altered)
    code, out = run(config, "move", "--to", str(other))
    assert code == diya_data.EXIT_FAILED and "notion.token is missing or different in the copy" in out


def test_a_connectors_folder_already_there_with_other_contents_is_not_overwritten(home, config, destination):
    (destination / "connector_tokens").mkdir(parents=True)
    (destination / "connector_tokens" / "notion.token").write_text("a different token\n")
    code, out = run(config, "move", "--to", str(destination))
    assert code == diya_data.EXIT_REFUSED and "not overwritten" in out
    assert (destination / "connector_tokens" / "notion.token").read_text() == "a different token\n"


def test_a_path_that_is_a_folder_where_a_file_belongs_is_not_copied_as_one(home, config, destination):
    (home / "dream_log.txt").unlink()
    (home / "dream_log.txt").mkdir()
    code, out = run(config, "move", "--to", str(destination))
    assert code == 0 and not (destination / "dream_log.txt").exists()


def test_a_file_is_put_under_the_name_diya_looks_for_whatever_it_was_called_here(home, config, destination):
    import dataclasses

    (home / "diya.db").rename(home / "mine.db")
    renamed = dataclasses.replace(config, db_path=str(home / "mine.db"))
    code, out = run(renamed, "move", "--to", str(destination))
    assert code == 0 and (destination / "diya.db").is_file() and not (destination / "mine.db").exists()


def test_the_settings_name_each_certificate_file_for_what_it_is(home, config, destination):
    import re

    code, out = run(config, "move", "--to", str(destination), "--certs")
    cert = re.search(r"'DIYA_SSL_CERT', '([^']+)'", out).group(1)
    key = re.search(r"'DIYA_SSL_KEY', '([^']+)'", out).group(1)
    assert cert.endswith("localhost+2.pem") and key.endswith("localhost+2-key.pem")


def test_a_quote_in_the_folder_name_is_doubled_in_every_printed_setting(home, config, tmp_path_factory):
    target = tmp_path_factory.mktemp("elsewhere") / "o'brien data"
    code, out = run(config, "move", "--to", str(target), "--certs")
    settings = [line for line in out.splitlines() if "SetEnvironmentVariable" in line]
    assert code == 0 and len(settings) == 3
    for line in settings:
        assert "o''brien data" in line and "o'brien data" not in line.replace("o''brien data", "")


def test_a_relative_destination_is_printed_as_a_full_path_because_a_setting_must_not_depend_on_where_it_is_read(home, config):
    code, out = run(config, "move", "--to", "rel/diya-data")
    assert code == 0 and (home / "rel" / "diya-data" / "diya.db").is_file()
    setting = [line for line in out.splitlines() if "'DIYA_DATA_DIR'" in line][0]
    assert str(home / "rel" / "diya-data") in setting


def test_a_database_line_says_what_was_checked(home, config, destination):
    code, out = run(config, "move", "--to", str(destination))
    assert "same rows in every table, integrity checks pass" in out and "identical to the original" in out


def test_a_folder_named_for_a_cloud_service_only_in_part_is_not_one(tmp_path):
    assert diya_data.synced_folder(str(tmp_path / "notonedrive" / "x")) is None
    assert diya_data.synced_folder(str(tmp_path / "the-dropbox-notes" / "x")) is None
    assert diya_data.synced_folder(str(tmp_path / "OneDrive - Work" / "x")) == "onedrive"


def test_importing_the_module_does_nothing(run_python, tmp_path):
    result = run_python("import diya_data, sys; print(sorted(p.name for p in __import__('pathlib').Path('.').iterdir()))")
    assert result.returncode == 0 and result.stdout.strip() == "[]"
