"""How much memory each job of the worker takes (Plan Maestro PM, PM-13-05; OPS-010). It measures; since OPS-026 it can also hand memory back after a heavy
run (``fbi.ops.memrelease``, ``FBI_WORKER_MEMTRIM``).

WHY. On 19 Nov 2026 the worker sat at 2.80 of its 3 GiB and touched the limit 4,160 times in ten hours, and nothing said which job
puts it there. This module answers that, by sampling, at the cost of one small file read every ``SAMPLE_SECONDS``:

* a daemon thread reads the process's resident memory (``/proc/self/statm``) and its high-water mark (``VmHWM`` of
  ``/proc/self/status``) every ``SAMPLE_SECONDS`` and keeps, for every open span, the highest resident memory it saw;
* a SPAN is one run of one job: an APScheduler job between its submission and its end (``apps.worker.scheduler`` adds the
  listeners) and a ledger run between ``RunLedger.open`` and ``close``. ``end`` returns what the span did: resident memory at its
  start, at its end and at its highest (MiB), how far the high-water mark of the process rose during it (the run that pushes the
  process to a new peak is the one to move out), how many spans were open at once (the worker is one process with threads: memory
  is the process's, so an overlap makes the figure an upper bound) and how many samples it got.

The worker logs it as ``job.memory`` and the ledger keeps it in ``raw.ingestion_runs.params`` under ``_mem``, so seven days of it
survive the restarts of a deploy. Nothing is sampled outside the worker process: ``start`` is called only by the worker's ``main``,
and without it ``begin`` and ``end`` are no-ops (the API, the messenger and the scripts pay nothing). ``FBI_WORKER_MEMWATCH=0``
turns it off; it never raises into a job. Guide: ``docs/owner/PM_13_05_MEMORIA_DEL_WORKER.md``.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

SAMPLE_SECONDS: Final = 5.0
MAX_SPAN_SECONDS: Final = 12 * 3600.0
"""A span still open after this long belongs to a run that never closed (a crash): the sampler forgets it."""
SWITCH: Final = "FBI_WORKER_MEMWATCH"
MIB: Final = 1024 * 1024
_PAGE: Final = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def enabled(environ: dict[str, str] | None = None) -> bool:
    """On unless the switch says no (``0``, ``off``, ``no``, ``false``): a measurement nobody sees, taken back with one word."""
    value = (os.environ if environ is None else environ).get(SWITCH, "1").strip().lower()
    return value not in {"0", "off", "no", "false"}


def rss_bytes() -> int | None:
    """The process's resident memory now, or None where ``/proc`` is not readable."""
    try:
        with open("/proc/self/statm", encoding="ascii") as fh:
            return int(fh.read().split()[1]) * _PAGE
    except (OSError, ValueError, IndexError):
        return None


def hwm_bytes() -> int | None:
    """The process's resident high-water mark (``VmHWM``), or None."""
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


@dataclass
class _Span:
    name: str
    started: float
    rss_start: int
    hwm_start: int
    rss_max: int
    overlap: int
    samples: int = 0


def _mib(value: int) -> float:
    return round(value / MIB, 1)


class MemWatch:
    """The open spans and the sampler that feeds them. One per process (``WATCH``); thread-safe."""

    def __init__(self, *, rss: Any = rss_bytes, hwm: Any = hwm_bytes, every: float = SAMPLE_SECONDS,
                 release: Any = None) -> None:
        self._rss = rss
        self._hwm = hwm
        self._every = every
        self.release = release
        """PM-13-05 (OPS-026): what hands memory back after a heavy run (``fbi.ops.memrelease.Release.after``), or None: a run's report
        then carries no ``release``. The worker sets it in ``start``."""
        self._lock = threading.Lock()
        self._spans: dict[str, _Span] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start sampling (the worker's ``main``). False when it cannot measure here: no ``/proc``."""
        if self.running:
            return True
        if self._rss() is None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="memwatch", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._every + 1)
        self._thread = None

    def sample(self) -> None:
        """One reading, folded into every open span. Never raises: one bad reading is skipped."""
        try:
            value = self._rss()
        except Exception:
            return
        if value is None:
            return
        horizon = time.monotonic() - MAX_SPAN_SECONDS
        with self._lock:
            for key in [k for k, span in self._spans.items() if span.started < horizon]:
                del self._spans[key]
            for span in self._spans.values():
                span.samples += 1
                span.rss_max = max(span.rss_max, value)

    def _loop(self) -> None:
        while not self._stop.wait(self._every):
            self.sample()

    def begin(self, key: str, name: str) -> None:
        """Open a span (a no-op while the sampler is not running)."""
        if not self.running:
            return
        try:
            rss, hwm = self._rss() or 0, self._hwm() or 0
            with self._lock:
                overlap = len(self._spans) + 1
                for other in self._spans.values():
                    other.overlap = max(other.overlap, overlap)
                self._spans[key] = _Span(name, time.monotonic(), rss, hwm, rss, overlap)
        except Exception:
            return

    def end(self, key: str) -> dict[str, Any] | None:
        """Close a span: what it took, in MiB, or None when it was never opened (or the sampler is off)."""
        try:
            with self._lock:
                span = self._spans.pop(key, None)
            if span is None:
                return None
            rss, hwm = self._rss() or span.rss_start, self._hwm() or span.hwm_start
            top = max(span.rss_max, rss)
            out: dict[str, Any] = {"job": span.name, "seconds": round(time.monotonic() - span.started, 1),
                    "rss_start_mib": _mib(span.rss_start), "rss_end_mib": _mib(rss), "rss_max_mib": _mib(top),
                    "grew_mib": _mib(rss - span.rss_start), "peak_over_start_mib": _mib(top - span.rss_start),
                    "hwm_raised_mib": _mib(max(hwm - span.hwm_start, 0)), "hwm_mib": _mib(hwm),
                    "overlap": span.overlap, "samples": span.samples}
            if self.release is not None:
                freed = self.release(out)  # after the report is made: its figures are those of the run, not of the release
                if freed:
                    out["release"] = freed
            return out
        except Exception:
            return None

    def open_spans(self) -> int:
        with self._lock:
            return len(self._spans)


WATCH: Final = MemWatch()
"""The process's own: started by the worker, read by the scheduler's listeners and by the ledger."""


def start() -> bool:
    """Start the process's sampler when the switch allows it. True when it is sampling. PM-13-05 (OPS-026): with ``FBI_WORKER_MEMTRIM``
    on (the default) it also keeps glibc to two arenas and wires the release after heavy runs (``fbi.ops.memrelease``)."""
    from fbi.ops import memrelease

    if memrelease.enabled():
        memrelease.cap_arenas()
        WATCH.release = memrelease.RELEASE.after
    return enabled() and WATCH.start()
