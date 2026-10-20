"""How the computer is doing (diya_machine.py and the Status page's "This computer" line; task DIYA-017; docs/HEALTH_DESIGN.md), added 2026-10-20.

What this proves: on the machine the tests run on, a real sample comes back with believable numbers (free memory no more than the total, a processor percentage between 0 and 100, a process that holds some
memory) and takes well under a second; a system that cannot be asked, or a call that fails, gives None and never raises; the sentence says what it measured; and the Status page's line is ok with plenty of free
memory, a warning under a gigabyte (with the reason it matters), and says "off" rather than guessing when it cannot be asked. It does not say the numbers are right on every machine: only that they came from the
system's own calls.
"""
import sys
import time

import pytest

import diya_health as health
import diya_machine as machine

GB = machine.GB


def test_a_real_sample_has_believable_numbers_and_is_quick():
    import importlib

    real = importlib.reload(machine)  # (conftest replaces sample() with a stand-in so that other tests do not wait for the processor)
    started = time.monotonic()
    found = real.sample()
    assert time.monotonic() - started < 2
    if found is None:
        pytest.skip(f"this system ({sys.platform}) cannot be asked")
    assert 0 < found["ram_free"] <= found["ram_total"] and found["ram_total"] > GB
    assert found["cpu_percent"] is None or 0 <= found["cpu_percent"] <= 100
    assert found["process_rss"] is None or 10 * 1024 * 1024 < found["process_rss"] < found["ram_total"]


def test_a_system_that_cannot_be_asked_gives_none_and_a_failing_call_raises_nothing(monkeypatch):
    import importlib

    real = importlib.reload(machine)
    monkeypatch.setattr(real.sys, "platform", "plan9")
    assert real.sample() is None
    monkeypatch.setattr(real.sys, "platform", "win32")
    monkeypatch.setattr(real, "_windows", lambda sleep: (_ for _ in ()).throw(OSError("no such call")))
    assert real.sample() is None


def test_the_sentence_says_what_was_measured():
    text = machine.describe({"ram_total": 16 * GB, "ram_free": 5 * GB, "cpu_percent": 12.4, "process_rss": 300 * 1024 * 1024})
    assert text == "5.0 of 16.0 GB of memory free, processor 12% busy, Diya's API holds 300 MB."
    assert machine.describe({"ram_total": 8 * GB, "ram_free": 1 * GB, "cpu_percent": None, "process_rss": None}) == "1.0 of 8.0 GB of memory free."
    assert machine.describe(None) is None


def test_the_status_line_is_ok_with_room_a_warning_without_it_and_off_when_it_cannot_tell():
    plenty = {"ram_total": 16 * GB, "ram_free": 6 * GB, "cpu_percent": 5.0, "process_rss": 200 * 1024 * 1024}
    assert health._machine(lambda: plenty)["status"] == "ok"
    tight = dict(plenty, ram_free=int(0.4 * GB))
    item = health._machine(lambda: tight)
    assert item["status"] == "warn" and "Memory is nearly full" in item["text"] and "0.4 of 16.0 GB" in item["text"]
    off = health._machine(lambda: None)
    assert off["status"] == "off" and "cannot be asked" in off["text"]


def test_a_sample_that_blows_up_is_reported_as_the_part_that_could_not_be_checked(tmp_path):
    import dataclasses

    import diya_config
    from diya_db import Store

    def boom():
        raise RuntimeError("no")

    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "m.db"))
    report = health.collect(config, Store(config.db_path), sample=boom, ping=lambda c: (True, [config.model]))
    item = next(i for i in report["items"] if i["name"] == "machine")
    assert item["status"] == "bad" and "Could not be checked" in item["text"]
