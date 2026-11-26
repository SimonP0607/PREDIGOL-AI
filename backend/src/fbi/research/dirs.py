"""Where the research writes its files (plan RP-1.5, root cause of the weekly research that stopped on 9 Oct 2026).

The weekly research (``scripts.research_v2 --apply``) and the experiments write a report and the artifacts of each experiment under
``data/reports`` and ``data/experiments``. Since the image of 9 Oct 2026 the worker runs as an unprivileged user and ``/app/data`` belongs to
root: ``mkdir`` failed with ``PermissionError`` before anything was computed or stored, the child process exited, and the parent logged it at
info level - a run that left no row anywhere. The last research on record is 4 Oct.

``writable(kind, default)`` is the folder to use: ``FBI_RESEARCH_DATA_DIR/<kind>`` when the owner names one; the default (``data/<kind>`` of the
checkout) when it can be written; otherwise ``<raw store>/_research/<kind>`` - the raw volume is the one persistent, writable, backed-up place
every container with a worker has - and last the system's temporary folder, which at least lets the run finish. Nothing is created here:
the caller creates the folder, and a caller that fails to is told where it tried.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

ENV = "FBI_RESEARCH_DATA_DIR"
SUBFOLDER = "_research"


def _can_write(folder: Path) -> bool:
    """Can ``folder`` be created, or written if it exists? Looks at the nearest folder that exists; creates nothing."""
    probe = folder
    while not probe.exists():
        if probe.parent == probe:
            return False
        probe = probe.parent
    return probe.is_dir() and os.access(probe, os.W_OK | os.X_OK)


def writable(kind: str, default: Path) -> Path:
    named = os.environ.get(ENV, "").strip()
    if named:
        return Path(named) / kind
    if _can_write(default):
        return default
    from fbi.core.config import settings

    raw = Path(settings.runtime.raw_store_dir)
    raw = raw if raw.is_absolute() else Path.cwd() / raw
    inside_raw = raw / SUBFOLDER / kind
    if _can_write(inside_raw):
        return inside_raw
    return Path(tempfile.gettempdir()) / "fbi-research" / kind
