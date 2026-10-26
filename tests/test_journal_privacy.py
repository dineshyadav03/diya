"""The activity record can say less, and can forget (diya_journal, diya_db migration 29, diya_forget; DIYA-215; docs/ACTIVITY_JOURNAL_DESIGN.md), added 2026-10-26.

Until now every preview of what a tool was asked ("query=garden") was kept for ever, and 'Forget for good' said it could not reach it. What this proves, on a record seeded the way a real week looks (searches, a weather
question, a mail look, approved actions, secrets in odd places): a value that looks like a credential, an email address or a card or phone number is hidden wherever it is, not only when its name says so;
with DIYA_JOURNAL_PREVIEWS=0 nothing that says what a tool was asked is kept at all (only that it happened, when, how it came out and how long it took); 'Forget for good' blanks the previews and notes of the rows that
came from the forgotten messages and nothing else, and says how many; rows older than DIYA_JOURNAL_KEEP_DAYS are removed and no newer one is, with a receipt each time; the database still refuses an
ordinary UPDATE or DELETE of the record, and the switch the two functions use is never left on, also when one fails half way; the receipts cannot be changed or deleted either; and the setting is read from the environment.
"""
import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import diya
import diya_config
import diya_db
import diya_forget
import diya_journal
import diya_memory
from fakes import FakeClient

SECRETS = [
    "sk-live_abcdefghijklmnopqrstuvwx", "ya29.a0AfH6SMBx-abcdefghijklmnop", "1//0gAbCdEfGhIjKlMnOpQrStUvWxYz", "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4fw",
    "ghp_abcdefghijklmnopqrstuvwxyz1234", "dinesh.yadav+bank@example.com", "4111 1111 1111 1111", "+91 98765 43210", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
]


@pytest.fixture
def store(tmp_path):
    return diya_db.Store(str(tmp_path / "j.db"))


@pytest.mark.parametrize("secret", SECRETS)
def test_a_value_that_looks_like_a_credential_an_email_or_a_number_is_hidden_wherever_it_is(secret):
    said = diya_journal.preview({"query": f"look up {secret} please", "location": secret})
    assert secret not in said and "[hidden]" in said


def test_ordinary_words_numbers_and_times_are_still_shown():
    said = diya_journal.preview({"query": "garden", "due_at": "2026-10-27T11:30:00Z", "content": "call mum at 5", "n": 25})
    assert "query=garden" in said and "2026-10-27T11:30:00Z" in said and "call mum at 5" in said and "[hidden]" not in said


def test_a_secret_in_a_note_is_hidden_too(store):
    diya_journal.record(store, "read_mail", {"question": "check"}, "error", kind="flow", note="Google answered with token ya29.a0AfH6SMBx-abcdefghijklmnop")
    assert "ya29" not in (store.journal_recent(limit=1)[0]["note"] or "")


def seeded(store, *, previews=True):
    store.journal_previews = previews
    for message_id, (tool, args) in enumerate([("search_notes", {"query": "garden"}), ("get_weather", {"location": "Pune"}), ("web_search", {"query": "dentist near me"}), ("add_task", {"content": "buy milk"})], start=1):
        diya_journal.record(store, tool, args, "ok", message_id=message_id, result="x" * 40, seconds=0.1, note="looked it up")
    return store


def test_with_previews_off_nothing_that_says_what_a_tool_was_asked_is_kept(store):
    seeded(store, previews=False)
    rows = store.journal_recent(limit=10)
    assert len(rows) == 4 and all(r["args_preview"] is None and r["note"] is None for r in rows)
    assert all(r["args_digest"] and r["status"] == "ok" and r["result_chars"] == 40 and r["duration_ms"] == 100 for r in rows)  # that it happened, when, how it came out, how long, and a fingerprint


def test_the_agent_hands_the_setting_to_its_store(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "a.db"), journal_previews=False)
    agent = diya.Agent(config, client=FakeClient([]))
    assert agent.store.journal_previews is False
    agent2 = diya.Agent(dataclasses.replace(config, db_path=str(tmp_path / "b.db"), journal_previews=True), client=FakeClient([]))
    assert agent2.store.journal_previews is True


def test_forgetting_for_good_blanks_the_previews_of_those_messages_and_nothing_else_and_leaves_a_receipt(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "f.db"), profile_path=str(tmp_path / "p.txt"))
    store = diya_db.Store(config.db_path)
    thread = store.create_thread()
    first = store.add_message(thread, "user", "what did i write about my dentist")
    second = store.add_message(thread, "user", "how hot is it in pune")
    for message_id, args in ((first, {"query": "dentist"}), (second, {"location": "Pune"})):
        diya_journal.record(store, "search_notes", args, "ok", message_id=message_id, note="a note")
    report = diya_forget.forget_message(store, diya_memory.open_memory(store, config), config, first)
    rows = {r["message_id"]: r for r in store.journal_recent(limit=10) if r["tool"] == "search_notes"}
    assert report.get("journal_blanked") == 1
    assert rows[first]["args_preview"] is None and rows[first]["note"] is None and rows[first]["status"] == "ok" and rows[first]["args_digest"]  # the row stays
    assert rows[second]["args_preview"] == "location=Pune" and rows[second]["note"] == "a note"  # another message's is untouched
    receipt = store.journal_receipts(limit=5)[0]
    assert receipt["what"] == "blanked" and receipt["rows_changed"] == 1 and "dentist" not in str(receipt)  # counts only, never the words


def test_rows_older_than_the_limit_are_removed_and_newer_ones_are_not_with_a_receipt(store):
    seeded(store)
    now = datetime.now(timezone.utc)
    conn = store.connect()
    conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('journal_edit_allowed', '1')")
    conn.execute("UPDATE tool_journal SET at = ? WHERE id IN (1, 2)", ((now - timedelta(days=200)).isoformat(),))  # two rows made old, the way a real record ages
    conn.execute("DELETE FROM app_state WHERE key = 'journal_edit_allowed'")
    conn.commit()
    conn.close()
    assert diya_journal.prune(store, 90) == 2
    assert sorted(r["id"] for r in store.journal_recent(limit=10)) == [3, 4]
    receipt = store.journal_receipts(limit=1)[0]
    assert receipt["what"] == "pruned" and receipt["rows_changed"] == 2
    assert diya_journal.prune(store, 90) == 0 and len(store.journal_receipts(limit=10)) == 1  # nothing more to remove: no empty receipt


@pytest.mark.parametrize("days", [0, -5, None, True, "90", 1.5])
def test_a_limit_of_nothing_or_that_is_not_a_number_of_days_removes_nothing(store, days):
    seeded(store)
    assert diya_journal.prune(store, days) == 0 and len(store.journal_recent(limit=10)) == 4


def test_the_database_still_refuses_an_ordinary_change_to_the_record_and_to_its_receipts(store):
    seeded(store)
    store.journal_prune("1999-01-01T00:00:00+00:00")  # makes the receipts table exist and the switch be used once
    conn = store.connect()
    for statement in ("UPDATE tool_journal SET status = 'error' WHERE id = 1", "DELETE FROM tool_journal WHERE id = 1"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(statement)
    conn.execute("INSERT INTO journal_receipts (at, what, rows_changed, detail) VALUES ('x', 'pruned', 1, 'x')")
    for statement in ("UPDATE journal_receipts SET rows_changed = 9", "DELETE FROM journal_receipts"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(statement)
    conn.close()


def test_the_switch_is_never_left_on_also_when_a_removal_fails_half_way(store, monkeypatch):
    seeded(store)

    real = store.connect

    def broken():
        conn = real()
        original = conn.execute

        class Wrapper:
            def __getattr__(self, name):
                return getattr(conn, name)

            def execute(self, sql, *args):
                if sql.startswith("INSERT INTO journal_receipts"):
                    raise sqlite3.OperationalError("disk full")
                return original(sql, *args)

        return Wrapper()

    monkeypatch.setattr(store, "connect", broken)
    with pytest.raises(sqlite3.OperationalError):
        store.journal_prune("2999-01-01T00:00:00+00:00")  # would remove every row, then fails writing the receipt
    monkeypatch.undo()
    conn = store.connect()
    assert conn.execute("SELECT COUNT(*) FROM app_state WHERE key = 'journal_edit_allowed'").fetchone()[0] == 0  # rolled back: the switch is off
    assert conn.execute("SELECT COUNT(*) FROM tool_journal").fetchone()[0] == 4  # and nothing was removed
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM tool_journal WHERE id = 1")
    conn.close()


def test_the_two_settings_are_read_from_the_environment():
    assert diya_config.load_config({}).journal_previews is True and diya_config.load_config({}).journal_keep_days == 0
    config = diya_config.load_config({"DIYA_JOURNAL_PREVIEWS": "0", "DIYA_JOURNAL_KEEP_DAYS": "90"})
    assert config.journal_previews is False and config.journal_keep_days == 90
    for bad in ("-1", "ninety"):
        with pytest.raises(diya_config.ConfigError):
            diya_config.load_config({"DIYA_JOURNAL_KEEP_DAYS": bad})
