"""The ``match_knowledge`` job over a real database (``fbi.ingestion.match_knowledge``, plan F7): what a pass of the worker builds, what it
leaves in the ledger and what it leaves alone.

The ledger is replaced by a recorder: the real one commits, and the transaction of a test is rolled back afterwards."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.ingestion import match_knowledge as job
from fbi.knowledge import builder, layers

from .conftest import Seed
from .knowledge_world import KICKOFF, NOW, World

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

    monkeypatch.setattr("fbi.ingestion.match_knowledge.RunLedger", FakeLedger)
    return runs


def stored(db: psycopg.Connection[Any], fid: int) -> int:
    return int(db.execute("SELECT count(*) FROM intel.match_knowledge WHERE fixture_id = %s", (fid,)).fetchone()[0])  # type: ignore[index]


def test_the_job_builds_what_is_due_and_leaves_a_ledger_run_only_when_it_did(db: psycopg.Connection[Any], seed: Seed,
                                                                             ledger_runs: list[dict[str, Any]]) -> None:
    fid = World(db, seed).golden()

    report = job.run_job(db, now=NOW, commit=False)

    assert (report.built, report.failed, report.stopped) == (1, 0, None) and stored(db, fid) == 1
    assert len(ledger_runs) == 1 and ledger_runs[0]["job"] == job.JOB == builder.JOB == "match_knowledge"
    assert ledger_runs[0]["params"] == {"days": 10, "limit": 300, "max_seconds": 240.0, "layers": layers.VERSION, "events": "events-v1",
                                        "sweep": False}
    counters = ledger_runs[0]["counters"]
    assert (counters.rows_inserted, counters.rows_updated, counters.rows_normalized) == (1, report.kinds, report.seen) and report.kinds == 8
    assert counters.errors == [] and counters.stopped_early is None
    assert json.loads(ledger_runs[0]["notes"])["built"] == 1

    quiet = job.run_job(db, now=NOW, commit=False)

    assert (quiet.built, quiet.failed, quiet.due) == (0, 0, 0) and stored(db, fid) == 1
    assert len(ledger_runs) == 1, "a pass that built nothing leaves no row in the ledger"


def test_a_pass_looks_at_the_last_days_and_the_sweep_at_the_whole_window(db: psycopg.Connection[Any], seed: Seed,
                                                                        ledger_runs: list[dict[str, Any]]) -> None:
    w = World(db, seed)
    recent, old = w.golden(), w.golden(KICKOFF - timedelta(days=60))

    ordinary = job.run_job(db, now=NOW, commit=False)

    assert ordinary.seen == 1 and stored(db, recent) == 1 and stored(db, old) == 0, "60 days ago is outside the last ten"
    sweep = job.run_job(db, now=NOW, days=400, limit=None, max_seconds=900.0, commit=False)
    assert sweep.seen == 2 and sweep.built == 1 and stored(db, old) == 1
    assert [r["params"]["sweep"] for r in ledger_runs] == [False, True]
    assert ledger_runs[1]["params"]["days"] == 400


def test_a_match_that_is_not_settled_yet_is_not_built(db: psycopg.Connection[Any], seed: Seed, ledger_runs: list[dict[str, Any]]) -> None:
    fid = World(db, seed).golden()
    too_soon = KICKOFF + builder.SETTLE - timedelta(minutes=1)
    assert job.run_job(db, now=too_soon, commit=False).seen == 0 and stored(db, fid) == 0 and ledger_runs == []
    assert job.run_job(db, now=KICKOFF + builder.SETTLE, commit=False).built == 1


def test_a_pass_cut_short_says_so_in_the_ledger_and_the_next_one_goes_on(db: psycopg.Connection[Any], seed: Seed,
                                                                         ledger_runs: list[dict[str, Any]]) -> None:
    w = World(db, seed)
    ids = [w.golden(KICKOFF + timedelta(hours=i)) for i in range(3)]

    first = job.run_job(db, now=NOW, limit=2, commit=False)

    assert (first.built, first.stopped, first.left) == (2, "limit", 1)
    assert ledger_runs[0]["counters"].stopped_early == "limit: 1 matches left for the next pass"
    second = job.run_job(db, now=NOW, limit=2, commit=False)
    assert (second.built, second.stopped) == (1, None) and sum(stored(db, i) for i in ids) == 3


def test_a_match_that_fails_is_recorded_and_the_others_are_built(db: psycopg.Connection[Any], seed: Seed, ledger_runs: list[dict[str, Any]],
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    bad, good = w.golden(KICKOFF), w.golden(KICKOFF + timedelta(hours=1))
    real = layers.build

    def build(inp: layers.Inputs) -> layers.Knowledge:
        if inp.fixture.id == bad:
            raise RuntimeError("a rule that cannot read this match")
        return real(inp)

    monkeypatch.setattr(layers, "build", build)

    report = job.run_job(db, now=NOW, commit=False)

    assert (report.built, report.failed) == (1, 1) and stored(db, good) == 1 and stored(db, bad) == 0
    counters = ledger_runs[0]["counters"]
    assert len(counters.errors) == 1 and "a rule that cannot read this match" in counters.errors[0]
    assert counters.rows_inserted == 1
