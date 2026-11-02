"""The Admin Console's «Almacenamiento» page: the host's storage report read, checked and projected; nothing deleted."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fbi.api.envelope import DataStatus
from fbi.api.services import storage

GIB = 1024**3
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "now", lambda: NOW)


def write(folder: Path, *, measured: datetime = NOW - timedelta(hours=1), used: int = 120 * GIB, size: int = 200 * GIB,
          history: list[dict[str, Any]] | None = None, version: str = storage.VERSION) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps({
        "version": version, "measured_at": measured.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "disk": {"size_bytes": size, "used_bytes": used, "avail_bytes": size - used, "pct": used * 100 // size, "level": "ok"},
        "parts": {}, "docker": {}, "database": {"bytes": 23 * GIB, "top_tables": []}, "backups": {}, "cleanup": None,
        "growth": {}}))
    if history is not None:
        (folder / "history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in history))
    return folder


def days(deltas: list[int], *, start: int = 100 * GIB, first: date = date(2026, 10, 1), key: str = "used_bytes") -> list[dict[str, Any]]:
    rows, used = [], start
    for i in range(len(deltas) + 1):
        if i:
            used += deltas[i - 1]
        rows.append({"date": (first + timedelta(days=i)).isoformat(), "used_bytes": used, key: used})
    return rows


def test_not_configured_and_not_written_yet_say_so_and_still_show_the_policy(tmp_path: Path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_STORAGE_REPORT_DIR", raising=False)
    env = storage.overview()
    assert env.status == DataStatus.NOT_AVAILABLE and "FBI_STORAGE_REPORT_DIR" in (env.reason or "")
    assert env.data["retention"] == list(storage.RETENTION)
    env = storage.overview(directory=tmp_path)
    assert env.status == DataStatus.NOT_AVAILABLE and env.data["report"] is None
    write(tmp_path, version="something-else")
    assert storage.overview(directory=tmp_path).status == DataStatus.NOT_AVAILABLE, "a report of another shape is not read"


def test_a_fresh_report_with_a_week_of_history_is_projected(tmp_path: Path) -> None:
    history = days([1 * GIB] * 10, start=110 * GIB)  # 110 -> 120 GiB, 1 GiB a day
    env = storage.overview(directory=write(tmp_path, used=120 * GIB, size=200 * GIB, history=history))
    assert env.status == DataStatus.OK
    body = env.data
    assert body["level"] == "ok" and body["stale"] is False
    p = body["projection"]
    assert p["per_day_bytes"] == GIB
    assert [a["days"] for a in p["at"]] == [30, 90, 365]
    assert p["at"][0]["used_bytes"] == 150 * GIB and p["at"][0]["pct"] == 75.0
    assert p["days_to"] == {"80": 40, "90": 60}


def test_the_pace_is_the_median_day_so_a_deploy_week_does_not_drag_it(tmp_path: Path) -> None:
    history = days([300 * 1024**2] * 10 + [6 * GIB, 5 * GIB])
    assert storage.pace(history) == 300 * 1024**2


def test_too_little_history_gives_no_projection(tmp_path: Path) -> None:
    env = storage.overview(directory=write(tmp_path, history=days([GIB] * 3)))
    assert env.data["projection"] == {"per_day_bytes": None, "at": [], "days_to": {"80": None, "90": None}}


def test_a_gap_of_days_is_spread_over_them() -> None:
    rows = [{"date": f"2026-10-{d:02d}", "used_bytes": 100 * GIB + (d - 1) * GIB} for d in range(1, 9)]
    rows.append({"date": "2026-10-12", "used_bytes": 100 * GIB + 11 * GIB})  # four days later, +4 GiB
    assert storage.pace(rows) == GIB


def test_a_stale_report_is_shown_but_flagged(tmp_path: Path) -> None:
    env = storage.overview(directory=write(tmp_path, measured=NOW - timedelta(hours=9)))
    assert env.status == DataStatus.INSUFFICIENT_DATA and env.data["stale"] is True
    assert env.data["report"] is not None


@pytest.mark.parametrize(("pct", "level"), [(69.9, "ok"), (70, "warning"), (80, "high"), (90, "critical")])
def test_levels(pct: float, level: str) -> None:
    assert storage.level_of(pct) == level


def test_full_or_shrinking_disk() -> None:
    assert storage.projection(95, 100, 1.0)["days_to"] == {"80": 0, "90": 0}
    assert storage.projection(50, 100, -1.0)["days_to"] == {"80": None, "90": None}


def test_broken_history_lines_are_skipped_and_the_last_of_a_day_wins(tmp_path: Path) -> None:
    (tmp_path / "history.jsonl").write_text('not json\n{"date":"2026-10-01","used_bytes":1}\n{"date":"2026-10-01","used_bytes":2}\n'
                                            '{"date":"2026-10-02"}\n')
    assert storage.read_history(tmp_path / "history.jsonl") == [{"date": "2026-10-01", "used_bytes": 2}]


def test_every_retention_row_is_translated_in_both_languages() -> None:
    web = Path(__file__).resolve().parents[3] / "web" / "src" / "locales"
    for lang in ("es", "en"):
        catalog = json.loads((web / lang / "storage.json").read_text(encoding="utf-8"))
        for row in storage.RETENTION:
            for field in ("tier", "what", "where", "keep"):
                assert row[field] in catalog["retention"][field], f"{lang}: retention.{field}.{row[field]}"


def test_the_route_only_reads() -> None:
    source = Path(storage.__file__).read_text(encoding="utf-8")
    for verb in ("unlink(", "rmtree", "remove(", "write_text", "open(", "subprocess", "os.system"):
        assert verb not in source
