"""Models, picks and performance - where 'not yet' is the usual honest answer."""

from __future__ import annotations

from decimal import Decimal

from fbi.api.contracts.analytics import (
    BacktestMetrics,
    MarketBaselineSummary,
    ModelsOverview,
    ModelVersionSummary,
    PerformanceSummary,
    PickRow,
    PicksOverview,
)
from fbi.api.envelope import DataStatus, Envelope, Section, ok, section, unavailable
from fbi.api.repositories import Conn
from fbi.api.repositories import analytics as repo

MIN_SETTLED_FOR_PERFORMANCE = 30
"""Below this, an ROI is noise with a percentage sign. Reported as insufficient."""


def models(conn: Conn) -> Envelope[ModelsOverview]:
    versions = repo.model_versions(conn)
    backtests = repo.latest_backtests(conn)
    items = [
        ModelVersionSummary(
            **v, latest_backtest=BacktestMetrics(**{k: val for k, val in backtests[v["version_id"]].items()
                                                   if k != "model_version_id"})
            if v["version_id"] in backtests else None,
        )
        for v in versions
    ]
    base = repo.market_baseline(conn)
    baseline = (
        Section[MarketBaselineSummary | None](
            status=DataStatus.OK,
            data=MarketBaselineSummary(fixtures_with_consensus=base["fixtures_with_consensus"],
                                       methods=list(base["methods"]), last_as_of=base["last_as_of"]))
        if base["fixtures_with_consensus"] else
        Section[MarketBaselineSummary | None](
            status=DataStatus.INSUFFICIENT_DATA, data=None,
            reason="No de-vigged market consensus exists yet: the baseline needs captured odds.")
    )
    listed = (section(items) if items else section(
        items, status=DataStatus.NOT_AVAILABLE, reason="No model has been trained and registered yet."))
    return ok(ModelsOverview(market_baseline=baseline, models=listed))


def picks(conn: Conn, *, limit: int, offset: int) -> Envelope[PicksOverview]:
    rows = [PickRow(**r) for r in repo.picks(conn, limit=limit, offset=offset)]
    body = PicksOverview(
        candidates_by_decision=repo.candidate_counts(conn),
        picks_by_mode=repo.pick_counts(conn),
        picks=section(rows) if rows else section(
            rows, status=DataStatus.NOT_AVAILABLE,
            reason="The pick engine has not produced any pick yet. Publishing is disabled; every pick is shadow."),
    )
    if not rows:
        return unavailable(body, "No pick exists yet.", limit=limit, offset=offset)
    return ok(body, limit=limit, offset=offset)


def performance(conn: Conn) -> Envelope[PerformanceSummary]:
    s = repo.settled_summary(conn)
    settled, pending = int(s["settled"] or 0), int(s["pending"] or 0)
    staked = Decimal(s["staked"]) if s["staked"] is not None else None
    profit = Decimal(s["profit"]) if s["profit"] is not None else None
    if settled < MIN_SETTLED_FOR_PERFORMANCE or not staked:
        body = PerformanceSummary(
            settled=settled, pending=pending, staked_units=None, profit_units=None, roi_pct=None, hit_rate=None,
            note=f"Economic metrics are withheld below {MIN_SETTLED_FOR_PERFORMANCE} settled picks with prices.",
        )
        return unavailable(body, f"Insufficient sample: {settled} settled pick(s).",
                           status=DataStatus.INSUFFICIENT_DATA)
    roi = (profit or Decimal(0)) / staked * 100
    body = PerformanceSummary(
        settled=settled, pending=pending, staked_units=staked, profit_units=profit,
        roi_pct=roi.quantize(Decimal("0.01")),
        hit_rate=(Decimal(int(s["wins"])) / settled * 100).quantize(Decimal("0.01")),
        note="Shadow picks at the captured price; not a betting record.",
    )
    return ok(body)
