"""Forecast -> evaluate captured prices -> settle. Database only: no provider request.

One ledger run ('pick_pipeline') wraps the three steps, so "what did the
system decide at 11:45?" has an answer in the same place as every capture.
Each step is idempotent: a forecast with unchanged inputs is not written
again, a price already evaluated is not evaluated again, a settled pick is
not settled again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
import structlog

from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.parlays.persist import ParlayReport, build_parlays
from fbi.picks.daily import DailyReport, build_daily_sets
from fbi.picks.engine import PickReport, SettlementReport, evaluate_captures, settle_open_picks
from fbi.picks.product_settlement import ProductSettlementReport, settle_products
from fbi.predictions.forecast import ForecastReport, forecast_upcoming

log = structlog.get_logger(__name__)


@dataclass
class PipelineReport:
    run_id: int | None
    forecast: ForecastReport | None = None
    picks: PickReport | None = None
    settlement: SettlementReport | None = None
    daily: DailyReport | None = None
    parlays: ParlayReport | None = None
    product: ProductSettlementReport | None = None


def run_pipeline(conn: psycopg.Connection, *, at: datetime, code_version: str, apply: bool = True) -> PipelineReport:
    """With ``apply=False`` everything is computed inside a transaction that is rolled back."""
    ledger = RunLedger(conn)
    run_id = ledger.open("pick_pipeline", params={"at": at.isoformat(), "apply": apply}) if apply else None
    report = PipelineReport(run_id)
    counters = RunCounters()
    try:
        report.forecast = forecast_upcoming(conn, at=at, code_version=code_version)
        if run_id is None:
            with conn.cursor() as cur:  # a throwaway run row for the FK, rolled back below
                cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type) VALUES ('pick_pipeline', "
                            "'pick_pipeline') RETURNING id")
                row = cur.fetchone()
                assert row is not None
                temp_run = int(row[0])
        else:
            temp_run = run_id
        report.picks = evaluate_captures(conn, run_id=temp_run, code_version=code_version)
        report.settlement = settle_open_picks(conn, run_id=temp_run)
        # What the product shows, as records: the day's picks and parlays, frozen when chosen,
        # and everything already shown (PrediGol's and the users' own) settled. In a savepoint:
        # a defect here is recorded and must not cost the forecasts, candidates and settlement.
        try:
            with conn.transaction():
                report.daily = build_daily_sets(conn, at=at)
                report.parlays = build_parlays(conn, at=at)
                report.product = settle_products(conn, at=at)
        except Exception as exc:  # recorded on the run, and logged; the core pipeline still commits
            counters.errors.append(f"product records: {type(exc).__name__}: {exc}"[:500])
            log.error("pipeline.product_records_failed", error=type(exc).__name__, detail=str(exc)[:300])
            report.daily, report.parlays, report.product = DailyReport(), ParlayReport(), ProductSettlementReport()
        if apply:
            conn.commit()
        else:
            conn.rollback()
        counters.rows_inserted = report.forecast.written + report.picks.candidates
        counters.rows_updated = report.settlement.settled
        counters.rows_normalized = report.picks.selected
    except Exception as exc:
        conn.rollback()
        counters.errors.append(f"{type(exc).__name__}: {exc}"[:500])
        if run_id is not None:
            ledger.close(run_id, counters, notes="failed; nothing from this run was kept")
        raise
    if run_id is not None:
        f, p, s = report.forecast, report.picks, report.settlement
        d, pl, ps = report.daily, report.parlays, report.product
        assert d is not None and pl is not None and ps is not None
        ledger.close(run_id, counters, notes=(
            f"forecasts {f.written} written/{f.unchanged} unchanged for {f.targets} fixtures; "
            f"candidates {p.candidates} (selected {p.selected}, qualified {p.qualified}); "
            f"settled {s.settled}, pending {s.still_pending} ({s.needs_review} need review); "
            f"daily items +{d.items_added} {d.by_source}; parlays built {pl.built}; product settled "
            f"items {ps.items}, parlays {ps.parlays}, user picks {ps.user_picks}, user parlays {ps.user_parlays}; "
            "0 requests"))
    log.info("pipeline.done", run_id=run_id, forecasts=report.forecast.written, candidates=report.picks.candidates,
             selected=report.picks.selected, settled=report.settlement.settled, apply=apply)
    return report
