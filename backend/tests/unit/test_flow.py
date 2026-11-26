"""RP-1.2: the state of the stages of «El camino de un pick», computed in the server - the five cases the panel got wrong, the single rule of
the counter, and the map of job types held equal to the web's."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fbi.ops import flow

AT = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
WEB_MAP = Path(__file__).resolve().parents[3] / "web" / "src" / "live" / "flowStages.ts"


def job(t: str, **kw: object) -> flow.JobRow:
    base: dict[str, object] = {"runs": 4, "completed": 4, "last_status": "completed", "last_started_at": AT - timedelta(hours=1)}
    return flow.JobRow(job_type=t, **{**base, **kw})  # type: ignore[arg-type]


def stage(name: flow.Stage, *rows: flow.JobRow) -> flow.StageFlow:
    return flow.stage_flow(name, rows, AT)


def test_a_stage_with_no_run_in_the_book_says_none_and_why() -> None:
    got = stage("value")
    assert (got.state, got.reason, got.jobs, got.errors) == ("none", "sin_ejecuciones_registradas", 0, 0)


def test_case_one_a_run_that_aborted_is_an_error_and_the_counter_says_so() -> None:
    """Today's «Ingesta · Con error · 0 con error»: the last run of period_backfill ended ``aborted`` and the counter summed ``failed`` only."""
    got = stage("ingest", job("period_backfill", runs=3, completed=1, aborted=2, last_status="aborted"), job("stats_documents"))
    assert (got.state, got.reason, got.worst_job) == ("error", "ultima_abortada", "period_backfill")
    assert got.errors == 2 and got.aborted == 2 and got.failed == 0, "the counter explains the colour"


def test_case_two_every_status_that_can_put_a_stage_in_error_counts() -> None:
    got = stage("ingest", job("a", runs=8, completed=1, failed=1, aborted=2, interrupted=3, stale=1, last_status="interrupted"))
    assert got.errors == got.failed + got.aborted + got.interrupted + got.stale == 7
    for status, reason in (("failed", "ultima_fallida"), ("aborted", "ultima_abortada"), ("interrupted", "ultima_interrumpida"),
                           ("stale", "ultima_obsoleta")):
        assert stage("models", job("elo_refresh", last_status=status)).reason == reason


def test_case_three_a_job_that_failed_in_the_day_but_ended_well_is_late_not_error() -> None:
    got = stage("models", job("elo_refresh", runs=5, completed=4, failed=1))
    assert (got.state, got.reason, got.errors) == ("late", "fallos_en_24h", 1)
    assert stage("models", job("elo_refresh", runs=5, completed=4, partial=1)).reason == "parciales_en_24h"


def test_case_four_a_job_overdue_is_late_then_error() -> None:
    nxt = AT - timedelta(minutes=16)
    assert stage("value", job("decision_v2_shadow", next_run_at=nxt)).reason == "atrasada_mas_de_15_min"
    assert stage("value", job("decision_v2_shadow", next_run_at=AT - timedelta(minutes=15))).state == "ok"
    late = stage("value", job("decision_v2_shadow", next_run_at=AT - timedelta(minutes=61)))
    assert (late.state, late.reason) == ("error", "atrasada_mas_de_60_min")


def test_case_five_the_worst_job_decides_the_stage_and_a_clean_stage_is_ok() -> None:
    got = stage("models", job("feature_build"), job("elo_refresh", failed=1, runs=5, completed=4), job("family_forecasts", last_status="failed"))
    assert (got.state, got.worst_job) == ("error", "family_forecasts")
    clean = stage("models", job("feature_build"), job("elo_refresh"))
    assert (clean.state, clean.reason, clean.worst_job, clean.errors) == ("ok", "al_dia", None, 0)
    assert clean.last_run_at == AT - timedelta(hours=1) and clean.runs == 8 and clean.completed == 8


def test_publication_is_closed_by_the_owners_decision_whatever_the_book_says() -> None:
    got = flow.stage_flow("publication", [job("anything")], AT)
    assert (got.state, got.reason, got.runs) == ("closed", "cerrada_por_decision", 0)


def test_the_eleven_stages_come_in_order_and_a_job_no_stage_claims_is_counted_apart() -> None:
    rows = [job("elo_refresh"), job("a_new_job_nobody_mapped"), job("a_quiet_one", runs=0, completed=0)]
    out, unmapped = flow.flows(rows, AT)
    assert [x.stage for x in out] == list(flow.STAGES) and len(out) == 11
    assert unmapped == ["a_new_job_nobody_mapped"], "a type with no run in the day is not reported as unmapped"


def test_the_error_counter_is_the_sum_for_every_combination() -> None:
    for failed in range(3):
        for aborted in range(3):
            for stale in range(2):
                row = job("x", runs=10, completed=1, failed=failed, aborted=aborted, stale=stale, last_status="completed")
                assert row.errors == failed + aborted + stale
                assert stage("sources", row).errors == row.errors


def test_every_reason_the_code_gives_is_in_the_closed_list() -> None:
    seen = {stage("ingest", job("a", last_status=s)).reason for s in flow.BAD_STATUSES}
    seen |= {stage("ingest", job("a", failed=1)).reason, stage("ingest", job("a", partial=1)).reason, stage("ingest", job("a")).reason,
             stage("ingest", job("a", next_run_at=AT - timedelta(minutes=30))).reason,
             stage("ingest", job("a", next_run_at=AT - timedelta(minutes=90))).reason, stage("ingest").reason,
             flow.stage_flow("publication", [], AT).reason}
    assert seen <= set(flow.REASONS) and len(seen) == len(flow.REASONS)


def test_the_map_of_job_types_is_the_webs_plus_the_two_additions_of_the_plan() -> None:
    text = WEB_MAP.read_text(encoding="utf-8")
    block = text[text.index("export const STAGE_JOBS"):text.index("/** Where a tap on each node leads")]
    web: dict[str, set[str]] = {}
    for name, body in re.findall(r"^  (\w+): \[(.*?)\],?$", block, flags=re.M | re.S):
        web[name] = set(re.findall(r'"(\w+)"', body))
    assert set(web) == set(flow.STAGES), "the same eleven stages"
    for name in flow.STAGES:
        added = set(flow.PLAN_ADDITIONS.get(name, ()))
        assert set(flow.STAGE_JOBS[name]) == web[name] | added, name
        assert not (web[name] & added), f"{name}: an addition is not already in the web's map"


def test_the_heartbeats_next_run_of_a_sweep_or_a_retry_belongs_to_its_type() -> None:
    got = flow._next_runs({"results_sync": "2026-11-26T12:30:00+00:00", "results_sync_sweep": "2026-11-26T12:10:00+00:00", "bad": "no date"})
    assert got == {"results_sync": datetime(2026, 11, 26, 12, 10, tzinfo=UTC)}, "an id with no readable date is left out, not guessed"


@pytest.mark.parametrize("stage_name", flow.STAGES)
def test_every_stage_has_a_job_list(stage_name: flow.Stage) -> None:
    assert (stage_name == "publication") == (flow.STAGE_JOBS[stage_name] == ())
