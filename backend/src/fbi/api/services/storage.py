"""THE STORAGE of PrediGol for the Admin Console («Almacenamiento»): where the server's disk goes, how fast it grows, the copies and where
they are, the last cleanup and the retention policy in force. Reading only.

What it reads was measured on the host by ``deploy/vps/bin/storage-report.sh`` (four times a day; sizes, counts, names and dates, never a
file's content or a secret) and reaches the API through a read-only mount (``FBI_STORAGE_REPORT_DIR``, ``/storage`` in production): the API
container cannot see the host's disk, Docker or the backup folder's neighbours, and must not. This module only reads that report and its
daily history, checks their shape, and adds what is computed from them: the projection at 30, 90 and 365 days and the days left to 80 % and
90 %, at the pace of the median day (a deploy week's jumps do not drag the forecast the way a mean would). Nothing here deletes anything:
the page has no button that removes data (see ``POLITICA_ALMACENAMIENTO.md``, the policy this module's ``RETENTION`` mirrors)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any, Final

from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.core.clock import now

VERSION: Final = "storage-report-v1"
STALE_AFTER: Final = timedelta(hours=8)
"""The report is written four times a day (02:41, 08:41, 14:41 and 20:41 UTC): older than eight hours means a run was missed."""
HISTORY_DAYS: Final = 28
"""The daily lines the projection looks at."""
PACE_DAYS: Final = 14
"""The pace is the median of the last fourteen daily deltas."""
MIN_DAYS: Final = 7
"""Fewer days than this and there is no projection: one week, so that a deploy day is not the whole picture."""
HORIZONS: Final = (30, 90, 365)
LEVELS: Final = ((90, "critical"), (80, "high"), (70, "warning"))

RETENTION: Final[tuple[dict[str, str], ...]] = (
    {"tier": "permanent", "what": "matches_results", "where": "postgres", "keep": "forever"},
    {"tier": "permanent", "what": "prematch_odds", "where": "postgres", "keep": "forever"},
    {"tier": "permanent", "what": "forecasts_predictions_models", "where": "postgres", "keep": "forever"},
    {"tier": "permanent", "what": "picks_parlays_settlements", "where": "postgres", "keep": "forever"},
    {"tier": "permanent", "what": "ai_decisions_postmortems_memory", "where": "postgres", "keep": "forever"},
    {"tier": "permanent", "what": "experiments_promotions_lineage_audits", "where": "postgres", "keep": "forever"},
    {"tier": "long", "what": "raw_provider_files", "where": "vps+r2", "keep": "r2_forever_locked"},
    {"tier": "long", "what": "monthly_dumps", "where": "r2", "keep": "12_months_locked"},
    {"tier": "long", "what": "audit_exports", "where": "r2", "keep": "12_months_locked"},
    {"tier": "medium", "what": "weekly_dumps", "where": "vps+r2", "keep": "8_weeks_r2_locked"},
    {"tier": "medium", "what": "daily_dumps", "where": "vps+r2", "keep": "14_days_r2_locked"},
    {"tier": "medium", "what": "pitr_wal", "where": "r2", "keep": "pitr_full_backups"},
    {"tier": "short", "what": "docker_images", "where": "vps", "keep": "running_plus_previous"},
    {"tier": "short", "what": "build_cache", "where": "vps", "keep": "7_days"},
    {"tier": "short", "what": "logs", "where": "vps", "keep": "rotated"},
    {"tier": "short", "what": "release_packages", "where": "vps", "keep": "30_days"},
    {"tier": "none", "what": "orphan_volumes_test_restores", "where": "vps", "keep": "delete_after_review"},
)
"""The policy in force, one row per kind of thing: the page shows it in words (``web/src/locales/*/storage.json``) and
``POLITICA_ALMACENAMIENTO.md`` explains each row. A test holds every key of this table translated in both languages."""


def report_dir() -> Path | None:
    raw = os.environ.get("FBI_STORAGE_REPORT_DIR", "").strip()
    return Path(raw) if raw else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_history(path: Path, *, days: int = HISTORY_DAYS) -> list[dict[str, Any]]:
    """The daily lines, oldest first, one per date (the last line of a date wins), only the well-formed ones."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    by_date: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("date"), str) and isinstance(row.get("used_bytes"), int):
            by_date[row["date"]] = row
    return [by_date[d] for d in sorted(by_date)][-days:]


def pace(history: list[dict[str, Any]], key: str = "used_bytes") -> float | None:
    """Bytes a day: the median of the last ``PACE_DAYS`` deltas between consecutive days (a gap of several days is spread over
    them). None with fewer than ``MIN_DAYS`` deltas."""
    deltas: list[float] = []
    for a, b in pairwise(history):
        if not isinstance(a.get(key), int) or not isinstance(b.get(key), int):
            continue
        gap = (datetime.fromisoformat(b["date"]) - datetime.fromisoformat(a["date"])).days
        if gap > 0:
            deltas.append((b[key] - a[key]) / gap)
    if len(deltas) < MIN_DAYS:
        return None
    return float(median(deltas[-PACE_DAYS:]))


def projection(used: int, size: int, per_day: float | None) -> dict[str, Any]:
    if per_day is None:
        return {"per_day_bytes": None, "at": [], "days_to": {"80": None, "90": None}}
    at = [{"days": d, "used_bytes": max(0, round(used + per_day * d)),
           "pct": round(100 * max(0.0, used + per_day * d) / size, 1)} for d in HORIZONS]
    days_to: dict[str, int | None] = {}
    for pct in (80, 90):
        room = size * pct / 100 - used
        if room <= 0:
            days_to[str(pct)] = 0
        elif per_day <= 0:
            days_to[str(pct)] = None
        else:
            days_to[str(pct)] = int(room // per_day)
    return {"per_day_bytes": round(per_day), "at": at, "days_to": days_to}


def level_of(pct: float) -> str:
    return next((name for floor, name in LEVELS if pct >= floor), "ok")


def overview(*, directory: Path | None = None) -> Envelope[dict[str, Any]]:
    folder = directory if directory is not None else report_dir()
    policy = {"retention": list(RETENTION)}
    if folder is None:
        return unavailable({"report": None, **policy},
                           "The storage report is not configured here (FBI_STORAGE_REPORT_DIR is not set).")
    report = _read_json(folder / "report.json")
    if not isinstance(report, dict) or report.get("version") != VERSION or not isinstance(report.get("disk"), dict):
        return unavailable({"report": None, **policy},
                           "No storage report has been written yet (bin/storage-report.sh runs four times a day on the server).")
    disk = report["disk"]
    size, used = disk.get("size_bytes"), disk.get("used_bytes")
    if not isinstance(size, int) or not isinstance(used, int) or size <= 0:
        return unavailable({"report": None, **policy}, "The storage report has no readable disk size.")
    measured = report.get("measured_at")
    try:
        measured_at = datetime.fromisoformat(str(measured).replace("Z", "+00:00"))
    except ValueError:
        measured_at = None
    moment = now()
    stale = measured_at is None or moment - measured_at.astimezone(UTC) > STALE_AFTER
    history = read_history(folder / "history.jsonl")
    per_day = pace(history)
    body: dict[str, Any] = {
        "report": report,
        "level": level_of(100 * used / size),
        "stale": stale,
        "projection": projection(used, size, per_day),
        "parts_pace": {k: pace(history, k) for k in ("db_bytes", "raw_bytes", "docker_bytes", "backups_bytes")},
        "history": history,
        **policy,
    }
    if stale:
        return unavailable(body, "The last storage report is older than eight hours: a run of bin/storage-report.sh was missed.",
                           status=DataStatus.INSUFFICIENT_DATA, data_as_of=measured_at)
    return ok(body, data_as_of=measured_at)
