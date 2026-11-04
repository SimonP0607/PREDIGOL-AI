"""``python -m scripts.ia_attribution`` against a database: the figure of Gate B, the scoreboard and the recomputation of earlier days (plan IA, phase 5)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest
from scripts import ia_attribution as script

from tests.integration.attribution_world import AFTER, DAY, attributions, complete, savepoints
from tests.integration.conftest import Seed
from tests.integration.test_agent_attribution import codes

pytestmark = pytest.mark.integration

TODAY = AFTER + dt.timedelta(days=3)


def test_coverage_is_pending_when_there_is_nothing_to_judge(db: psycopg.Connection[Any]) -> None:
    doc, code = script.run("coverage", savepoints(db), at=TODAY, since=DAY, until=DAY)
    assert (doc["share"], doc["settled_with_runs"], code) == (None, 0, script.PENDING), "zero of zero is not 100 %"


def test_coverage_passes_the_bar_of_gate_b_only_when_the_matches_have_their_attributions(db: psycopg.Connection[Any], seed: Seed) -> None:
    complete(db, seed)
    doc, code = script.run("coverage", savepoints(db), at=TODAY, since=DAY, until=DAY)
    assert (doc["share"], doc["attributed"], doc["settled_with_runs"], code) == (0.0, 0, 1, script.NO)
    script.run("recompute", savepoints(db), at=TODAY, first=DAY, last=DAY)
    doc, code = script.run("coverage", savepoints(db), at=TODAY, since=DAY, until=DAY)
    assert (doc["share"], doc["gate_b_share"], code) == (1.0, 0.95, script.OK)


def test_the_window_of_coverage_is_the_one_asked_for(db: psycopg.Connection[Any], seed: Seed) -> None:
    complete(db, seed)
    doc, _ = script.run("coverage", savepoints(db), at=TODAY, since=DAY + dt.timedelta(days=1), until=DAY + dt.timedelta(days=2))
    assert doc["settled_with_runs"] == 0 and doc["from"] == (DAY + dt.timedelta(days=1)).isoformat()
    doc, _ = script.run("coverage", savepoints(db), at=TODAY)
    assert doc["to"] == (TODAY.date() - dt.timedelta(days=1)).isoformat() and doc["from"] == (TODAY.date() - dt.timedelta(days=15)).isoformat()


def test_recompute_writes_the_rows_of_the_rule_marks_them_batch_and_can_be_run_twice(db: psycopg.Connection[Any], seed: Seed) -> None:
    complete(db, seed)
    doc, code = script.run("recompute", savepoints(db), at=TODAY, first=DAY - dt.timedelta(days=3), last=DAY + dt.timedelta(days=1))
    assert (doc["selections"], doc["rows"], doc["written"], code) == (1, 4, 4, script.OK)
    assert {r[0] for r in attributions(db, columns="source")} == {"batch"}
    again, _ = script.run("recompute", savepoints(db), at=TODAY + dt.timedelta(days=1), first=DAY, last=DAY)
    assert (again["rows"], again["written"]) == (4, 0)


def test_a_dry_run_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    complete(db, seed)
    doc, _ = script.run("recompute", savepoints(db), at=TODAY, first=DAY, last=DAY, dry_run=True)
    assert (doc["written"], doc["dry_run"]) == (4, True)
    assert attributions(db) == []


def test_the_recomputation_equals_the_daily_step_on_the_same_data(db: psycopg.Connection[Any], seed: Seed) -> None:
    from fbi.ai.agents import attribution

    complete(db, seed)
    with db.transaction(force_rollback=True):
        attribution.attribute_day(db, day=DAY, at=AFTER)
        live = codes(db)
    script.run("recompute", savepoints(db), at=TODAY, first=DAY, last=DAY)
    assert codes(db) == live != []


@pytest.mark.parametrize(("kwargs", "words"), [
    ({"first": None, "last": None}, "needs --from and --to"),
    ({"first": DAY, "last": DAY - dt.timedelta(days=1)}, "after --to"),
    ({"first": DAY, "last": TODAY.date()}, "has not finished"),
])
def test_a_recomputation_that_cannot_run_says_why(db: psycopg.Connection[Any], kwargs: dict[str, Any], words: str) -> None:
    doc, code = script.run("recompute", savepoints(db), at=TODAY, **kwargs)
    assert code == script.CANNOT and words in doc["error"]


def test_the_scoreboard_counts_hits_and_misses_per_agent_and_version(db: psycopg.Connection[Any], seed: Seed) -> None:
    sp = savepoints(db)
    assert script.run("scoreboard", sp, at=TODAY, since=DAY)[0]["rows"] == []
    complete(db, seed)
    script.run("recompute", sp, at=TODAY, first=DAY, last=DAY)
    doc, code = script.run("scoreboard", sp, at=TODAY, since=DAY)
    assert code == script.OK and doc["version"] == "attr-v1"
    assert [(r["agent"], r["agent_version"], r["engine"], r["hits"], r["misses"], r["hit_rate"]) for r in doc["rows"]] == [
        ("council", "council-v1", "ma-v1", 0, 1, 0.0), ("match", "match-v1", "ma-v1", 0, 1, 0.0)]


def test_a_bad_day_is_a_usage_error() -> None:
    with pytest.raises(ValueError, match="not a day"):
        script.parse_day("tomorrow")
    assert script.build_parser().parse_args(["coverage", "--json"]).as_json is True
