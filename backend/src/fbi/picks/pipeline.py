"""Forecast -> evaluate captured prices -> settle -> settle again what a corrected result changed.
Database only: no provider request.

One ledger run ('pick_pipeline') wraps the steps, so "what did the
system decide at 11:45?" has an answer in the same place as every capture.
Each step is idempotent: a forecast with unchanged inputs is not written
again, a price already evaluated is not evaluated again, a settled pick is
not settled again - unless the provider corrected the result of its match, in
which case ``fbi.picks.resettlement`` settles it again with a trail (plan F0,
defect 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
import structlog

from fbi.core.env import environment
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.parlays.persist import ParlayReport, build_parlays
from fbi.picks.daily import DailyReport, build_daily_sets
from fbi.picks.engine import PickReport, SettlementReport, evaluate_captures, settle_open_picks
from fbi.picks.fast_settlement import fill_line_value, record_latency
from fbi.picks.product_settlement import ProductSettlementReport, settle_products
from fbi.picks.resettlement import ResettlementReport, resettle
from fbi.predictions.forecast import ForecastReport, forecast_upcoming
from fbi.predictions.match_forecast import MatchForecastReport, write_match_forecasts

log = structlog.get_logger(__name__)

RESETTLE_SWITCH = "FBI_RESETTLE"
"""``FBI_RESETTLE=0`` stops the routine re-settlement without a deploy (the worker needs a restart to read it). The
corrections of results keep being recorded by the database; they are settled again when the switch is back on, or by
hand (``python -m scripts.resettle``)."""


def resettle_enabled() -> bool:
    return environment().get(RESETTLE_SWITCH, "1").strip().lower() not in {"0", "off", "false", "no"}


FORECAST_SWITCH = "FBI_MATCH_FORECAST"
"""``FBI_MATCH_FORECAST=0`` stops the pass from writing PrediGol's forecast of each match (plan F5) without a deploy (the worker needs
a restart to read it). What was written stays, and the page shows the newest set until it is hidden from users
(``FBI_FORECAST_USERS=0``). Nothing else in the pass reads the forecast, so nothing else changes."""


def match_forecast_enabled() -> bool:
    return environment().get(FORECAST_SWITCH, "1").strip().lower() not in {"0", "off", "false", "no"}


@dataclass
class PipelineReport:
    run_id: int | None
    forecast: ForecastReport | None = None
    match_forecasts: MatchForecastReport | None = None
    picks: PickReport | None = None
    settlement: SettlementReport | None = None
    resettlement: ResettlementReport | None = None
    daily: DailyReport | None = None
    parlays: ParlayReport | None = None
    product: ProductSettlementReport | None = None
    line_values: int = 0


def _after_commit(conn: psycopg.Connection, report: PipelineReport, *, at: datetime) -> None:
    """What this pass settled, stamped once it is visible (after the commit), and the line value of the picks
    whose matches have started. Never a reason for the pass to fail: logged and left to the next pass."""
    settled = report.settlement.by_fixture if report.settlement else {}
    items = report.product.by_fixture if report.product else {}
    try:
        for fid in sorted(set(settled) | set(items)):
            record_latency(conn, fid, path="pipeline", picks=settled.get(fid, 0), items=items.get(fid, 0))
        report.line_values = fill_line_value(conn, at=at)
        conn.commit()
    except psycopg.Error as exc:
        conn.rollback()
        log.error("pipeline.after_commit_failed", error=type(exc).__name__, detail=str(exc)[:300])


def run_pipeline(conn: psycopg.Connection, *, at: datetime, code_version: str, apply: bool = True) -> PipelineReport:
    """With ``apply=False`` everything is computed inside a transaction that is rolled back."""
    ledger = RunLedger(conn)
    run_id = ledger.open("pick_pipeline", params={"at": at.isoformat(), "apply": apply}) if apply else None
    report = PipelineReport(run_id)
    counters = RunCounters()
    try:
        report.forecast = forecast_upcoming(conn, at=at, code_version=code_version)
        # What PrediGol thinks will happen, kept apart from what is worth betting (plan F5): read from the forecasts just
        # made, written to a table nothing below reads. In its own savepoint: a defect here is recorded on the run and
        # must not cost the candidates, the settlement or the product records.
        report.match_forecasts = MatchForecastReport(at=at)
        forecasting = match_forecast_enabled()
        if forecasting:
            try:
                with conn.transaction():
                    report.match_forecasts = write_match_forecasts(conn, at=at, code_version=code_version)
            except Exception as exc:  # recorded on the run, and logged; the core pipeline still commits
                counters.errors.append(f"match forecasts: {type(exc).__name__}: {exc}"[:500])
                log.error("pipeline.match_forecasts_failed", error=type(exc).__name__, detail=str(exc)[:300])
                report.match_forecasts = MatchForecastReport(at=at)
        else:
            log.warning("pipeline.match_forecasts_off", hint=f"{FORECAST_SWITCH}=0: PrediGol's forecast of the matches is not written")
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
        report.settlement = settle_open_picks(conn, run_id=temp_run, at=at)
        # What the provider corrected since: the records settled on the old result are settled again, with a trail.
        # In its own savepoint, before the product records (an un-settled parlay is decided again in this same pass):
        # a defect here is recorded on the run and must not cost the forecasts, candidates and settlement.
        report.resettlement = ResettlementReport()
        resettling = resettle_enabled()
        if resettling:
            try:
                with conn.transaction():
                    report.resettlement = resettle(conn, at=at, run_id=temp_run)
            except Exception as exc:  # recorded on the run, and logged; the core pipeline still commits
                counters.errors.append(f"resettlement: {type(exc).__name__}: {exc}"[:500])
                log.error("pipeline.resettlement_failed", error=type(exc).__name__, detail=str(exc)[:300])
                report.resettlement = ResettlementReport()
        else:
            log.warning("pipeline.resettlement_off", hint=f"{RESETTLE_SWITCH}=0: settled records are not re-checked "
                                                           "after the provider corrects a result")
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
            _after_commit(conn, report, at=at)
        else:
            conn.rollback()
        counters.rows_inserted = report.forecast.written + report.picks.candidates
        counters.rows_updated = report.settlement.settled + len(report.resettlement.changes)
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
        rr = report.resettlement
        # (a refused pass has changes: the list that was not written, which is what the note must say)
        again = f"; {rr.summary()}" if rr is not None and (rr.changes or rr.held or rr.conflicts) else ""
        again += "" if resettling else f"; re-settlement OFF ({RESETTLE_SWITCH}=0)"
        mfr = report.match_forecasts
        assert mfr is not None
        shown = mfr.summary() if forecasting else f"match forecasts OFF ({FORECAST_SWITCH}=0)"
        ledger.close(run_id, counters, notes=(
            f"forecasts {f.written} written/{f.unchanged} unchanged for {f.targets} fixtures; {shown}; "
            f"candidates {p.candidates} (selected {p.selected}, qualified {p.qualified}); "
            f"settled {s.settled}, pending {s.still_pending} ({s.needs_review} need review){again}; "
            f"daily items +{d.items_added} {d.by_source}; parlays built {pl.built}; product settled "
            f"items {ps.items}, parlays {ps.parlays}, user picks {ps.user_picks}, user parlays {ps.user_parlays}; "
            f"line values {report.line_values}; 0 requests"))
    log.info("pipeline.done", run_id=run_id, forecasts=report.forecast.written,
             match_forecasts=0 if report.match_forecasts is None else report.match_forecasts.markets_written,
             candidates=report.picks.candidates, selected=report.picks.selected, settled=report.settlement.settled,
             apply=apply)
    return report
