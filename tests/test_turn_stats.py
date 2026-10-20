"""How fast answers come (Store.turn_stat_add, the chat routes, diya_health._answers, the oldest waiting job; task DIYA-017; docs/HEALTH_DESIGN.md), added 2026-10-20.

What this proves: every chat turn, plain or streamed, leaves one row of numbers (how long, whether it worked, how many tools) and NO words of anyone; the table cannot hold text; old rows are pruned;
a record that cannot be written never fails a chat; the Status page line tells the middle and the slow end of the last 7 days and the failures, is a warning when three of the last ten failed and bad when the last five
did, and says plainly when nothing has been timed; and the reading line says how long the oldest message has waited. It does not log CPU or memory (the sheet wishes for them; that part is not met).
"""
import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_health as health
import diya_web
from diya_db import Store
from fakes import ByQuestionClient, FakeClient, text_reply

LOCAL = "https://localhost"
NOW = datetime.now()


class Quiet:
    def transcribe(self, path):
        return ""


def build(tmp_path, client, **changes):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "t.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False, **{"auto_memory": False, **changes},
    )
    agent = diya.Agent(config, client=client)
    return config, agent, TestClient(diya_web.create_app(config, agent, Quiet()), base_url=LOCAL)


def rows(store):
    conn = sqlite3.connect(store.path)
    try:
        return conn.execute("SELECT route, ms, ok, tools FROM turn_stats ORDER BY id").fetchall()
    finally:
        conn.close()


def test_the_table_has_numbers_and_a_time_and_no_place_for_words(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.turn_stat_add("chat", 1234, True, 2)
    conn = sqlite3.connect(store.path)
    try:
        columns = [(r[1], r[2]) for r in conn.execute("PRAGMA table_info(turn_stats)")]
    finally:
        conn.close()
    assert columns == [("id", "INTEGER"), ("at", "TEXT"), ("route", "TEXT"), ("ms", "INTEGER"), ("ok", "INTEGER"), ("tools", "INTEGER")]


def test_the_newest_rows_are_kept_and_the_rest_pruned(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.TURN_STATS_KEPT = 5
    for n in range(9):
        store.turn_stat_add("chat", n, True)
    assert [r[1] for r in rows(store)] == [4, 5, 6, 7, 8]


def test_a_record_that_cannot_be_written_raises_nothing(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "s.db"))

    def broken():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(store, "connect", broken)
    store.turn_stat_add("chat", 10, True)  # (no exception)


def test_a_plain_turn_a_streamed_turn_and_a_failed_turn_each_leave_one_row_of_numbers(tmp_path):
    client = FakeClient([text_reply("Hello."), text_reply("Hello again.")])
    config, agent, http = build(tmp_path, client)
    http.post("/api/chat", json={"message": "a secret phrase the log must not hold"})
    with http.stream("POST", "/api/chat/stream", json={"message": "another private sentence"}) as reply:
        list(reply.iter_lines())
    client.replies = []  # the model has nothing more to say: the next turn fails
    http.post("/api/chat", json={"message": "this one fails"})
    got = rows(agent.store)
    assert [(route, ok) for route, _, ok, _ in got] == [("chat", 1), ("stream", 1), ("chat", 0)] and all(ms >= 0 for _, ms, _, _ in got)
    conn = sqlite3.connect(agent.store.path)
    try:
        everything = str(conn.execute("SELECT * FROM turn_stats").fetchall())
    finally:
        conn.close()
    assert "secret" not in everything and "private" not in everything and "fails" not in everything and "Hello" not in everything


# ---- the Status line ---------------------------------------------------------------------------------------------------


def add(store, *turns, days_ago=0):
    conn = store.connect()  # (through the Store, so that the schema exists)
    try:
        for n, (ms, ok) in enumerate(turns):
            at = (datetime.now(timezone.utc) - timedelta(days=days_ago, seconds=len(turns) - n)).isoformat()
            conn.execute("INSERT INTO turn_stats (at, route, ms, ok, tools) VALUES (?, 'chat', ?, ?, 0)", (at, ms, 1 if ok else 0))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "h.db"))


def test_with_nothing_timed_it_says_so_and_is_ok(store):
    item = health._answers(store, NOW)
    assert item["status"] == "ok" and "No answers have been timed" in item["text"]


def test_it_tells_the_middle_and_the_slow_end_and_the_failures(store):
    add(store, *[(ms, True) for ms in (3000, 5000, 8000, 12000, 15000, 20000, 25000, 30000, 41000, 90000)], (500, False))
    item = health._answers(store, NOW)
    assert item["status"] == "ok"
    assert "11 answers" in item["text"] and "half took 20 s or less" in item["text"] and "19 in 20 took 90 s or less" in item["text"] and "1 failed" in item["text"]


def test_what_is_older_than_a_week_is_not_counted(store):
    add(store, *[(60000, True)] * 5, days_ago=9)
    add(store, (2000, True))
    assert "1 answer;" in health._answers(store, NOW)["text"]


def test_three_failures_in_the_last_ten_is_a_warning_and_five_in_a_row_is_bad(store):
    add(store, *[(5000, True)] * 7, (0, False), (0, False), (0, False))
    assert health._answers(store, NOW)["status"] == "warn"
    add(store, *[(0, False)] * 5)
    bad = health._answers(store, NOW)
    assert bad["status"] == "bad" and "last five did not work" in bad["text"]


def test_a_few_failures_among_many_successes_are_ok(store):
    add(store, (0, False), *[(5000, True)] * 12)
    assert health._answers(store, NOW)["status"] == "ok"


def test_the_status_report_has_the_line(tmp_path):
    config, agent, http = build(tmp_path, FakeClient([text_reply("Hi.")]))
    http.post("/api/chat", json={"message": "hello there"})
    items = {i["name"]: i for i in http.get("/api/health").json()["items"]}
    assert items["answers"]["label"] == "How fast answers come" and "1 answer" in items["answers"]["text"]


def test_the_reading_line_says_how_long_the_oldest_message_has_waited(tmp_path):
    config, agent, http = build(tmp_path, ByQuestionClient(), auto_memory=True)
    store = agent.store
    store.add_message(store.main_thread(), "user", "I have a dog named Hog", capture=True)
    conn = sqlite3.connect(store.path)
    try:
        conn.execute("UPDATE capture_queue SET created_at = ?", ((datetime.now(timezone.utc) - timedelta(minutes=17)).isoformat(),))
        conn.commit()
    finally:
        conn.close()
    text = health._reading(config, store)["text"]
    assert "1 message(s) are waiting" in text and "The oldest has waited 17 minutes." in text
