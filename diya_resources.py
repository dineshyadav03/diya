"""The computer's memory and processor, written down as they go (DIYA-017; docs/HEALTH_DESIGN.md), added 2026-10-25.

The Status page already showed memory and processor use, but only for the moment you opened it: when an answer had been slow an hour ago there was nothing to look back at. While the API runs, a small thread
takes one look every five minutes (diya_machine.sample: memory free, how busy the processor was, what Diya's API holds) and writes the numbers to the database; the Status page then says what the last 24 hours
were like. Numbers only: no text of yours is read, kept or logged here, and nothing leaves the computer. The newest 5,000 looks are kept (about two weeks). A system that cannot be asked writes nothing and says
so on the Status page, as before.

Importing this module has no side effects; nothing starts a thread but Recorder.start().
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import diya_machine

INTERVAL_SECONDS = 300  # a look every five minutes
MIN_GAP_SECONDS = 240  # a second look closer than this to the last is not written (two programs, or a restart, must not double the numbers)
BUSY_PERCENT = 85  # "the processor was busy" means over this
MIN_TREND_SAMPLES = 3  # fewer than this is too few to call a trend


def record(store, sample=None, now=None):
    """Write one look unless one was written less than MIN_GAP_SECONDS ago. Returns True if it wrote. Never raises: a look that cannot be written must not be what breaks anything."""
    try:
        now = now or datetime.now(timezone.utc)
        last = store.resource_sample_last()
        if last is not None and (now - datetime.fromisoformat(last)).total_seconds() < MIN_GAP_SECONDS:
            return False
        found = (sample or diya_machine.sample)()
        if not found:
            return False
        store.resource_sample_add(now.isoformat(), found.get("ram_total"), found.get("ram_free"), found.get("cpu_percent"), found.get("process_rss"))
        return True
    except Exception:  # noqa: BLE001
        return False


def trend(store, now=None, hours=24):
    """What the last `hours` hours were like, from the written numbers: {samples, ram_free_min, ram_free_avg (bytes), cpu_avg, cpu_max, busy_share, low_memory_share}, or None when there are too few looks."""
    now = now or datetime.now(timezone.utc)
    rows = store.resource_samples_since((now - timedelta(hours=hours)).isoformat())
    if len(rows) < MIN_TREND_SAMPLES:
        return None
    free = [row[1] for row in rows if row[1] is not None]
    cpu = [row[2] for row in rows if row[2] is not None]
    found = {"samples": len(rows), "hours": hours}
    if free:
        found.update(ram_free_min=min(free), ram_free_avg=sum(free) / len(free), low_memory_share=sum(1 for f in free if f < diya_machine.GB) / len(free))
    if cpu:
        found.update(cpu_avg=sum(cpu) / len(cpu), cpu_max=max(cpu), busy_share=sum(1 for c in cpu if c > BUSY_PERCENT) / len(cpu))
    return found


def describe(found):
    """The trend as a sentence for the Status page, or None when there is none."""
    if not found:
        return None
    parts = []
    if "ram_free_min" in found:
        parts.append(f"free memory was lowest at {found['ram_free_min'] / diya_machine.GB:.1f} GB and {found['ram_free_avg'] / diya_machine.GB:.1f} GB on average"
                     + (f" (under 1 GB in {found['low_memory_share']:.0%} of looks)" if found["low_memory_share"] > 0 else ""))
    if "cpu_avg" in found:
        parts.append(f"the processor averaged {found['cpu_avg']:.0f}% and was over {BUSY_PERCENT}% busy in {found['busy_share']:.0%} of looks")
    if not parts:
        return None
    return f"Over the last {found['hours']} hours ({found['samples']} looks): " + "; ".join(parts) + "."


class Recorder(threading.Thread):
    """Takes a look now and then every `interval` seconds until stopped. A daemon thread: it never keeps the program alive."""

    def __init__(self, store, interval=INTERVAL_SECONDS, sample=None):
        super().__init__(name="resource-recorder", daemon=True)
        self.store, self.interval, self.sample = store, interval, sample
        self._stop_now = threading.Event()

    def run(self):
        while not self._stop_now.is_set():
            record(self.store, self.sample)
            self._stop_now.wait(self.interval)

    def stop(self):
        self._stop_now.set()
