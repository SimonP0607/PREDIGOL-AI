"""Give back to the system the memory a heavy job of the worker no longer needs (Plan Maestro PM, PM-13-05; OPS-026).

WHY. ``fbi.ops.memwatch`` measured the worker for seven days (20-26 Nov 2026, 39,000 runs of 73 jobs). What it found: the process does
not get to 2.9 of its 3 GiB in one blow, it climbs by hundreds of MiB an hour and almost never goes down - the floor between two runs
of the same job was 1.7 GiB at 17:00 and 3.0 GiB at 21:00 on 25 Nov - and the job that adds to that floor, run after run, is the pick
pipeline (15 to 67 MiB left behind by each pass, 850 passes). The process holds 24 threads and, with glibc's default of eight arenas
a core (48 on the server), seven 64 MiB arenas where freed memory stays reserved (231 MiB resident and 159 MiB swapped at 23:19 UTC
on 26 Nov, an hour after a restart). Python gives its own small blocks back when an arena empties; the memory of ``malloc`` it keeps
until someone asks.

WHAT. Two things, behind one switch (``FBI_WORKER_MEMTRIM``, on unless it says ``0``/``off``/``no``/``false``; restart the worker
to apply it):

* ``cap_arenas`` - at start, before the scheduler creates its threads, glibc is told to keep two arenas (``mallopt(M_ARENA_MAX)``),
  which is what the matrix's own process already runs with (BE-094, ``MALLOC_ARENA_MAX=2``): a thread that frees memory frees it into
  an arena the next thread reuses, instead of into one nobody asks for again.
* ``Release.after`` - when a run of a job ends (``MemWatch.end``) and it was heavy (it grew the process by 50 MiB or more, or went 150
  MiB over its start), at most once every five minutes: ``gc.collect()`` and ``malloc_trim(0)``, which hands every free page of every
  arena back to the kernel. What it did is written into the run's ``params._mem.release``: resident memory before and after,
  what ``malloc_trim`` freed, how many live Python blocks there were before and after (``sys.getallocatedblocks``: if the blocks do
  not fall and the resident memory does, what was held was fragmentation; if neither falls, the job keeps real data), the objects
  the collector found and how long it all took.

Nothing is computed from it and nothing reads it but a person. It never raises into a job, it never runs outside the worker, and a
platform without glibc (a developer's machine) does nothing. Guide: ``docs/owner/PM_13_05_MEMORIA_DEL_WORKER.md``.
"""

from __future__ import annotations

import ctypes
import gc
import os
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

SWITCH: Final = "FBI_WORKER_MEMTRIM"
MIB: Final = 1024 * 1024
M_ARENA_MAX: Final = -8
"""``mallopt`` parameter number of the arena cap (glibc ``malloc.h``)."""
ARENAS: Final = 2
HEAVY_GREW_MIB: Final = 50.0
HEAVY_PEAK_MIB: Final = 150.0
MIN_GAP_SECONDS: Final = 300.0


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """On unless the switch says no (``0``, ``off``, ``no``, ``false``): nothing a reader sees, taken back with one word."""
    value = (os.environ if environ is None else environ).get(SWITCH, "1").strip().lower()
    return value not in {"0", "off", "no", "false"}


def _libc() -> Any | None:
    try:
        return ctypes.CDLL("libc.so.6", use_errno=True)
    except (OSError, AttributeError):
        return None


def cap_arenas(arenas: int = ARENAS, *, libc: Any | None = None) -> bool:
    """Keep at most ``arenas`` malloc arenas from now on. True when glibc took it; False where there is no glibc."""
    lib = libc if libc is not None else _libc()
    if lib is None:
        return False
    try:
        return bool(lib.mallopt(M_ARENA_MAX, int(arenas)) == 1)
    except (AttributeError, OSError, ValueError):
        return False


def malloc_trim(*, libc: Any | None = None) -> bool:
    """``malloc_trim(0)``: every free page of every arena goes back to the kernel. True when it ran."""
    lib = libc if libc is not None else _libc()
    if lib is None:
        return False
    try:
        lib.malloc_trim(0)
        return True
    except (AttributeError, OSError, ValueError):
        return False


def _rss() -> int | None:
    from fbi.ops import memwatch

    return memwatch.rss_bytes()


def is_heavy(mem: Mapping[str, Any]) -> bool:
    """A run that left the process bigger (``grew_mib``) or that went high over where it started (``peak_over_start_mib``)."""
    try:
        return float(mem.get("grew_mib") or 0) >= HEAVY_GREW_MIB or float(mem.get("peak_over_start_mib") or 0) >= HEAVY_PEAK_MIB
    except (TypeError, ValueError):
        return False


class Release:
    """What the worker hands back after a heavy run. One per process; thread-safe enough: two ends at once do it once (the second finds
    the gap not elapsed)."""

    def __init__(self, *, rss: Callable[[], int | None] = _rss, collect: Callable[[], int] = gc.collect,
                 trim: Callable[[], bool] = malloc_trim, blocks: Callable[[], int] = sys.getallocatedblocks,
                 clock: Callable[[], float] = time.monotonic, gap: float = MIN_GAP_SECONDS) -> None:
        self._rss = rss
        self._collect = collect
        self._trim = trim
        self._blocks = blocks
        self._clock = clock
        self._gap = gap
        self._last = float("-inf")

    def after(self, mem: Mapping[str, Any]) -> dict[str, Any] | None:
        """``mem`` is what ``MemWatch.end`` reports for a run that just ended. None when the run was light or the last release is
        recent; otherwise what the release did (MiB). Never raises."""
        try:
            if not is_heavy(mem):
                return None
            started = self._clock()
            if started - self._last < self._gap:
                return None
            self._last = started
            before, blocks_before = self._rss(), self._blocks()
            collected = self._collect()
            mid = self._rss()
            trimmed = self._trim()
            after, blocks_after = self._rss(), self._blocks()
            out: dict[str, Any] = {"trimmed": trimmed, "collected": int(collected), "blocks_before": int(blocks_before),
                                   "blocks_after": int(blocks_after), "seconds": round(self._clock() - started, 3)}
            if before is not None and after is not None:
                out["rss_before_mib"] = round(before / MIB, 1)
                out["rss_after_mib"] = round(after / MIB, 1)
                out["freed_mib"] = round((before - after) / MIB, 1)
                if mid is not None:
                    out["freed_by_trim_mib"] = round((mid - after) / MIB, 1)
            return out
        except Exception:
            return None


RELEASE: Final = Release()
"""The process's own, wired to ``fbi.ops.memwatch.WATCH`` by the worker's ``start``."""
