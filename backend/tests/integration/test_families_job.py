"""The scheduled pass of the family forecasts (plan F10): a ledger run when it wrote or failed, none when it had nothing to say, and a
family that fails costs the others nothing.

The ledger is replaced by a recorder: the real one commits, and the transaction of a test is rolled back afterwards."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.families import forecast, job

from .test_families_forecast import AT, catalogue, played, small_window, stored, upcoming, w  # noqa: F401  (the world and its fixtures)

pytestmark = pytest.mark.integration


@pytest.fixture
def ledger_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []

    class FakeLedger:
        def __init__(self, conn: Any) -> None:
            self.conn = conn

        def open(self, job_type: str, *, params: dict[str, object] | None = None, **_: Any) -> int:
            runs.append({"job": job_type, "params": params, "counters": None, "notes": None})
            return len(runs)

        def close(self, run_id: int, counters: Any, *, notes: str | None = None) -> None:
            runs[run_id - 1].update(counters=counters, notes=notes)

    monkeypatch.setattr("fbi.families.job.RunLedger", FakeLedger)
    return runs


def test_a_pass_that_writes_leaves_a_run_and_a_quiet_one_leaves_none(db: psycopg.Connection[Any], w: Any,  # noqa: F811
                                                                      ledger_runs: list[dict[str, Any]]) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    report = job.run_job(db, now=AT, code_version="test", commit=False)
    assert len(ledger_runs) == 1 and ledger_runs[0]["job"] == "family_forecasts", "one run in the ledger: what was written"
    counters = ledger_runs[0]["counters"]
    assert counters.rows_inserted == len(stored(db, fid)) > 0 and counters.rows_normalized == report.targets and counters.status == "completed"
    assert "family forecasts" in ledger_runs[0]["notes"] and ledger_runs[0]["params"]["version"] == "family-v1"
    again = job.run_job(db, now=AT + timedelta(hours=1), code_version="test", commit=False)
    assert all(r.rows_written == 0 for r in again.specs.values())
    assert len(ledger_runs) == 1, "a pass with nothing to say is not a row"


def test_a_family_that_fails_costs_the_others_nothing(db: psycopg.Connection[Any], w: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
                                                      ledger_runs: list[dict[str, Any]]) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    real = forecast._run_spec

    def flaky(conn: psycopg.Connection[Any], spec: forecast.Spec, *args: Any, **kwargs: Any) -> None:
        if spec.key == "corners_ft":
            raise RuntimeError("the corners of this competition are broken")
        real(conn, spec, *args, **kwargs)

    monkeypatch.setattr(forecast, "_run_spec", flaky)
    report = job.run_job(db, now=AT, code_version="test", commit=False)
    assert "broken" in report.specs["corners_ft"].error and report.specs["corners_ft"].rows_written == 0
    assert all(report.specs[k].rows_written > 0 for k in ("goals_halves", "cards_lines_ft", "yellow_ft")), report.summary()
    assert {r[5] for r in stored(db, fid)} == {"GOALS_HALF", "CARDS", "YELLOW"}, "the families that worked are written"
    (run,) = ledger_runs
    assert run["counters"].status == "partial" and "corners_ft" in run["counters"].errors[0] and "FAILED" in run["notes"]


def test_a_family_that_fails_after_writing_leaves_nothing_of_itself(db: psycopg.Connection[Any], w: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    catalogue(db)
    played(w)
    fid = upcoming(w)
    real_store = forecast.store
    calls = {"n": 0}

    def store_then_fail(*args: Any, **kwargs: Any) -> int:
        calls["n"] += 1
        written = real_store(*args, **kwargs)
        if kwargs.get("family") == "YELLOW" and calls["n"] > 0:
            raise RuntimeError("after the first rows")
        return written

    monkeypatch.setattr(forecast, "store", store_then_fail)
    report = forecast.write_family_forecasts(db, at=AT, code_version="test", fixture_ids=[fid])
    assert report.specs["yellow_ft"].error and report.specs["yellow_ft"].rows_written == 0, "the report does not claim what was rolled back"
    assert "YELLOW" not in {r[5] for r in stored(db, fid)}, "a family is written whole or not at all"
    assert {"GOALS_HALF", "CARDS", "CORNERS"} <= {r[5] for r in stored(db, fid)}
