"""The computer's memory and processor, written down as they go (diya_resources.py, migration 28, the Status page's "This computer"; docs/HEALTH_DESIGN.md; DIYA-017), added 2026-10-25.

What this proves, with the real store and a stand-in for the machine: a look is written as numbers only; two looks closer than four minutes are one; a system that cannot be asked writes nothing and does not
fail; the newest 5,000 are kept; the last 24 hours are summarised (lowest and average free memory, how busy the processor was, how often memory was short or the processor over 85%) and too few looks make no trend;
the Status page's sentence for the computer carries it; the recorder thread writes at its own pace, stops when told and survives a machine that raises; and no text of yours is anywhere in what is written.
"""
import dataclasses
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import diya_config
import diya_health
import diya_machine
import diya_resources as res
from diya_db import Store

GB = diya_machine.GB
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def machine(free_gb=4.0, cpu=30.0, rss_mb=900):
    return lambda: {"ram_total": 16 * GB, "ram_free": int(free_gb * GB), "cpu_percent": cpu, "process_rss": rss_mb * 1024 * 1024}


def fill(store, looks):
    """looks: (minutes after T0, free GB, cpu)."""
    for minutes, free, cpu in looks:
        assert res.record(store, machine(free, cpu), T0 + timedelta(minutes=minutes))


def test_a_look_is_written_as_numbers_and_two_close_together_are_one(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    assert res.record(store, machine(3.5, 42.0, 800), T0)
    assert not res.record(store, machine(), T0 + timedelta(minutes=3))  # under four minutes since the last
    assert res.record(store, machine(), T0 + timedelta(minutes=5))
    conn = sqlite3.connect(store.path)
    rows = conn.execute("SELECT at, ram_total, ram_free, cpu_percent, process_rss FROM resource_samples ORDER BY id").fetchall()
    assert len(rows) == 2 and rows[0] == (T0.isoformat(), 16 * GB, int(3.5 * GB), 42.0, 800 * 1024 * 1024)
    assert [c[1] for c in conn.execute("PRAGMA table_info(resource_samples)")] == ["id", "at", "ram_total", "ram_free", "cpu_percent", "process_rss"]  # numbers: not one column that could hold text of yours


def test_a_system_that_cannot_be_asked_writes_nothing_and_a_machine_that_raises_breaks_nothing(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    assert res.record(store, lambda: None, T0) is False

    def boom():
        raise OSError("no")

    assert res.record(store, boom, T0) is False
    assert store.resource_sample_last() is None


def test_only_the_newest_five_thousand_are_kept(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    store.RESOURCE_SAMPLES_KEPT = 5
    for number in range(9):
        store.resource_sample_add((T0 + timedelta(minutes=number)).isoformat(), 1, 2, 3.0, 4)
    kept = [row for row in sqlite3.connect(store.path).execute("SELECT at FROM resource_samples ORDER BY id")]
    assert len(kept) == 5 and kept[0][0] == (T0 + timedelta(minutes=4)).isoformat()


def test_the_last_day_is_summarised_and_older_looks_and_too_few_make_no_trend(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    fill(store, [(0, 4.0, 20.0), (5, 0.6, 95.0), (10, 2.0, 50.0), (15, 6.0, 90.0)])
    found = res.trend(store, T0 + timedelta(minutes=20))
    assert found["samples"] == 4 and found["ram_free_min"] == int(0.6 * GB) and abs(found["cpu_avg"] - 63.75) < 1e-9 and found["cpu_max"] == 95.0
    assert found["busy_share"] == 0.5 and found["low_memory_share"] == 0.25
    assert res.trend(store, T0 + timedelta(hours=30)) is None  # all older than a day: too few to say
    assert res.trend(Store(str(tmp_path / "empty.db")), T0) is None
    sentence = res.describe(found)
    assert "4 looks" in sentence and "lowest at 0.6 GB" in sentence and "under 1 GB in 25% of looks" in sentence and "averaged 64%" in sentence and "over 85% busy in 50% of looks" in sentence
    assert res.describe(None) is None


def test_the_status_pages_sentence_for_the_computer_carries_it(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    config = dataclasses.replace(diya_config.load_config(), db_path=store.path)
    fill(store, [(0, 4.0, 20.0), (5, 3.0, 30.0), (10, 2.0, 40.0)])
    item = diya_health._machine(machine(5.0, 10.0), store, T0 + timedelta(minutes=12))
    assert item["status"] == "ok" and "5.0 of 16.0 GB of memory free" in item["text"] and "Over the last 24 hours (3 looks)" in item["text"]
    plain = diya_health._machine(machine(5.0, 10.0))  # asked the old way, with no store: the same as before
    assert "Over the last" not in plain["text"]
    low = diya_health._machine(machine(0.4, 10.0), store, T0 + timedelta(minutes=12))
    assert low["status"] == "warn"
    report = diya_health.collect(config, store, now=T0.replace(tzinfo=None) + timedelta(minutes=12), ping=lambda c: (False, []), sample=machine())
    assert any(item["name"] == "machine" for item in report["items"])


def test_the_recorder_writes_at_its_own_pace_stops_when_told_and_survives_a_machine_that_raises(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    calls = {"n": 0}

    def sometimes_breaks():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the first look fails")
        return machine()()

    recorder = res.Recorder(store, interval=0.05, sample=sometimes_breaks)
    assert recorder.daemon
    recorder.start()
    deadline = time.time() + 5
    while time.time() < deadline and store.resource_sample_last() is None:
        time.sleep(0.02)
    time.sleep(0.4)  # several more turns of its loop: they come inside the four-minute gap, so they write nothing and do not even look
    assert recorder.is_alive()
    recorder.stop()
    recorder.join(2)
    assert not recorder.is_alive()
    assert calls["n"] == 2  # the first look failed and was survived, the second was written, the rest were held back by the gap
    assert sqlite3.connect(store.path).execute("SELECT COUNT(*) FROM resource_samples").fetchone()[0] == 1
