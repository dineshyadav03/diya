"""How the computer is doing, as numbers: memory free, how busy the processor is, and how much memory Diya's own process holds (docs/HEALTH_DESIGN.md, task DIYA-017), added 2026-10-20.

Local models are the heavy part of Diya on a 16 GB laptop with no graphics card, and "answers are slow" is often "the computer is out of memory". The Status page shows these three numbers so that a slow answer
can be told from a broken one. Nothing is stored and nothing leaves the computer: a sample is taken when the page asks and shown at once. No library is needed (Windows through the system's own calls, Linux
through /proc); on any other system it says it cannot tell, and the Status page says so.

Importing this module has no side effects.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

GB = 1024 ** 3


def _windows(sleep):
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                    ("page_free", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong), ("virtual_free", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    class ProcessMemory(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("page_faults", ctypes.c_ulong), ("peak_working", ctypes.c_size_t), ("working", ctypes.c_size_t), ("peak_paged", ctypes.c_size_t),
                    ("paged", ctypes.c_size_t), ("peak_nonpaged", ctypes.c_size_t), ("nonpaged", ctypes.c_size_t), ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t)]

    kernel = ctypes.windll.kernel32
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None

    def times():
        idle, system, user = FileTime(), FileTime(), FileTime()
        if not kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(system), ctypes.byref(user)):
            return None
        return tuple((t.high << 32) | t.low for t in (idle, system, user))

    first = times()
    sleep(0.25)
    second = times()
    cpu = None
    if first and second:
        idle, busy = second[0] - first[0], (second[1] - first[1]) + (second[2] - first[2])  # (kernel time includes the idle time)
        cpu = max(0.0, min(100.0, 100.0 * (1 - idle / busy))) if busy > 0 else None
    process = ProcessMemory()
    process.cb = ctypes.sizeof(ProcessMemory)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    handle = kernel.GetCurrentProcess()
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle), ctypes.byref(process), process.cb)
    return {"ram_total": int(status.total), "ram_free": int(status.free), "cpu_percent": cpu, "process_rss": int(process.working) if ok else None}


def _linux(sleep):
    info = {}
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024
    if "MemTotal" not in info or "MemAvailable" not in info:
        return None

    def busy():
        with open("/proc/stat", encoding="ascii") as handle:
            numbers = [int(x) for x in handle.readline().split()[1:]]
        return sum(numbers), numbers[3] + (numbers[4] if len(numbers) > 4 else 0)

    total1, idle1 = busy()
    sleep(0.25)
    total2, idle2 = busy()
    cpu = max(0.0, min(100.0, 100.0 * (1 - (idle2 - idle1) / (total2 - total1)))) if total2 > total1 else None
    with open("/proc/self/statm", encoding="ascii") as handle:
        rss = int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    return {"ram_total": info["MemTotal"], "ram_free": info["MemAvailable"], "cpu_percent": cpu, "process_rss": rss}


def sample(sleep=time.sleep):
    """{ram_total, ram_free, cpu_percent, process_rss} in bytes and percent (a value is None when it could not be had), or None when this system cannot be asked. Never raises. Takes about a quarter of a second
    (the processor's busy time is the difference between two looks)."""
    try:
        if sys.platform == "win32":
            return _windows(sleep)
        if sys.platform.startswith("linux"):
            return _linux(sleep)
    except Exception:  # noqa: BLE001 -- a number that cannot be had is not worth failing the Status page for
        return None
    return None


def describe(found):
    """The sample as a sentence for the Status page."""
    if not found:
        return None
    parts = [f"{found['ram_free'] / GB:.1f} of {found['ram_total'] / GB:.1f} GB of memory free"]
    if found.get("cpu_percent") is not None:
        parts.append(f"processor {found['cpu_percent']:.0f}% busy")
    if found.get("process_rss") is not None:
        parts.append(f"Diya's API holds {found['process_rss'] / GB * 1024:.0f} MB")
    return ", ".join(parts) + "."
