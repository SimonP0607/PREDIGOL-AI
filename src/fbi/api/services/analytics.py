"""Models, picks and performance - where 'not yet' is the usual honest answer."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fbi.api.contracts.analytics import (
    BacktestMetrics,
    BacktestSessionSummary,
    BaselineScore,
    CalibrationBucket,
    CandidateRow,
    CompetitionName,
    Coverage,
    HypotheticalBetting,
    Lifecycle,
    MarketBaselineSummary,
    MarketComparison,
    ModelsOverview,
    ModelVersionSummary,
    PerformanceSlice,
    PerformanceSummary,
    PickEvent,
    PickRow,
    PicksOverview,
    ScoreSummary,
    SplitRow,
)
from fbi.api.envelope import DataStatus, Envelope, Section, ok, section, unavailable
from fbi.api.repositories import Conn
from fbi.api.repositories import analytics as repo

MIN_SETTLED_FOR_PERFORMANCE = 30
"""Below this, an ROI is noise with a percentage sign. Reported as insufficient."""


BETTING_NOTE = ("Hypothetical: flat one-unit stakes at the historical source's closing price, by a rule fixed "
                "before the test season. Not a record of bets, not a forecast of returns.")


def _comparison(r: dict[str, Any]) -> MarketComparison:
    return MarketComparison(**{k: v for k, v in r.items() if k != "backtest_run_id"})


def _scores(d: dict[str, Any] | None) -> ScoreSummary | None:
    if not d:
        return None
    return ScoreSummary(n=int(d["n"]), brier=float(d["brier"]), log_loss=float(d["log_loss"]), ece=float(d["ece"]))


def _splits(d: dict[str, dict[str, float]] | None, labels: dict[int, str] | None = None) -> list[SplitRow]:
    out = []
    for key, row in (d or {}).items():
        label = labels.get(int(key), key) if labels is not None and key.isdigit() else key
        out.append(SplitRow(key=key, label=label, n=int(row["n"]), model_logloss=float(row["model_logloss"]),
                            baseline_logloss=float(row["baseline_logloss"]), logloss_diff=float(row["logloss_diff"])))
    return out


def _backtest(b: dict[str, Any], comps: list[dict[str, Any]], primary_key: str | None,
              labels: dict[int, str]) -> BacktestMetrics:
    details: dict[str, Any] = b.get("details") or {}
    vs = [_comparison(c) for c in comps]
    primary = next((c for c in vs if c.baseline_key == primary_key and c.market_key == "1X2"), None)
    bet_meta = details.get("betting") or {}
    betting = None
    if b.get("n_bets") is not None and b.get("odds_source"):
        betting = HypotheticalBetting(
            rule=str(bet_meta.get("rule", "")), odds_source=str(b["odds_source"]),
            fixtures_priced=int(bet_meta.get("fixtures_priced", 0)), n_bets=int(b["n_bets"]),
            staked_units=Decimal(b["total_stake_units"] or 0), profit_units=Decimal(b["total_profit_units"] or 0),
            roi_pct=b["roi_pct"], roi_ci_low=b["roi_ci_low"], roi_ci_high=b["roi_ci_high"],
            max_drawdown_units=b["max_drawdown_units"], mean_probability_edge=bet_meta.get("mean_probability_edge"),
            note=BETTING_NOTE,
        )
    cov = details.get("coverage")
    return BacktestMetrics(
        run_id=b["run_id"], name=b["name"], protocol=b["protocol"], session_id=b["session_id"],
        test_from=b["test_from"], test_to=b["test_to"], n_samples=b["n_samples"], brier=b["brier"],
        logloss=b["logloss"], ece=b["ece"], accuracy_pct=b["accuracy_pct"],
        coverage=Coverage(**cov) if cov else None, primary=primary, vs_market=vs,
        calibration=[CalibrationBucket(**x) for x in details.get("calibration", [])],
        over_under_2_5=_scores(details.get("ou")), btts=_scores(details.get("btts")),
        by_competition=_splits(details.get("by_competition"), labels), by_month=_splits(details.get("by_month")),
        betting=betting, odds_source=b["odds_source"], n_bets=b["n_bets"], roi_pct=b["roi_pct"],
        yield_pct=b["yield_pct"], near_close_lv_mean=b["near_close_lv_mean"], code_version=b["code_version"],
        finished_at=b["finished_at"],
    )


def models(conn: Conn) -> Envelope[ModelsOverview]:
    session = repo.latest_session(conn)
    labels = repo.competition_names(conn, list(session["competition_ids"])) if session else {}
    versions = repo.model_versions(conn)
    backtests = repo.latest_backtests(conn)
    comps: dict[int, list[dict[str, Any]]] = {}
    for c in repo.comparisons(conn, [int(b["run_id"]) for b in backtests.values()]):
        comps.setdefault(int(c["backtest_run_id"]), []).append(c)
    primary_key = str(session["primary_baseline"]) if session else None
    items = [
        ModelVersionSummary(
            **v, latest_backtest=_backtest(backtests[v["version_id"]], comps.get(int(backtests[v["version_id"]]["run_id"]), []),
                                           primary_key, labels)
            if v["version_id"] in backtests else None,
        )
        for v in versions
    ]
    base = repo.market_baseline(conn)
    live_baseline = (
        Section[MarketBaselineSummary | None](
            status=DataStatus.OK,
            data=MarketBaselineSummary(fixtures_with_consensus=base["fixtures_with_consensus"],
                                       methods=list(base["methods"]), last_as_of=base["last_as_of"]))
        if base["fixtures_with_consensus"] else
        Section[MarketBaselineSummary | None](
            status=DataStatus.INSUFFICIENT_DATA, data=None,
            reason="No live de-vigged consensus yet: it is computed from odds WE captured, and none has been captured.")
    )
    if session is None:
        backtest = Section[BacktestSessionSummary | None](
            status=DataStatus.NOT_AVAILABLE, data=None, reason="No walk-forward backtest has been stored yet.")
        historical: Section[list[BaselineScore]] = section(
            [], status=DataStatus.NOT_AVAILABLE,
            reason="Market baselines are scored as part of a backtest session; none exists yet.")
    else:
        backtest = Section[BacktestSessionSummary | None](status=DataStatus.OK, data=BacktestSessionSummary(
            id=session["id"], session_uuid=session["session_uuid"], name=session["name"],
            protocol=session["protocol"],
            competitions=[CompetitionName(id=i, name=labels.get(int(i), str(i))) for i in session["competition_ids"]],
            validation_season=session["validation_season"], test_season=session["test_season"],
            test_from=session["test_from"], test_to=session["test_to"], n_targets=session["n_targets"],
            primary_baseline=session["primary_baseline"], dataset_hash=session["dataset_hash"],
            code_version=session["code_version"], finished_at=session["finished_at"],
            selection=session["selection"], config=session["config"]))
        rows = [BaselineScore(**r, is_primary=(r["baseline_key"] == primary_key and r["market_key"] == "1X2"))
                for r in repo.baseline_evaluations(conn, int(session["id"]))]
        historical = section(rows) if rows else section(
            rows, status=DataStatus.EMPTY, reason="The session priced no fixture with a historical market.")
    listed = (section(items) if items else section(
        items, status=DataStatus.NOT_AVAILABLE, reason="No model has been trained and registered yet."))
    return ok(ModelsOverview(market_baseline=live_baseline, backtest=backtest, historical_baselines=historical,
                             models=listed))


def picks(conn: Conn, *, limit: int, offset: int, public: bool = False) -> Envelope[PicksOverview]:
    """``public`` is the client-facing view: only picks that passed qualification, and none of the
    shadow-mode candidates or rejection detail. Shadow stays an internal instrument."""
    from fbi.picks.rules import CURRENT_RULE

    rows = repo.picks(conn, limit=limit, offset=offset, qualified_only=public)
    events: dict[int, list[PickEvent]] = {}
    for e in repo.pick_events(conn, [int(r["id"]) for r in rows]):
        events.setdefault(int(e["pick_id"]), []).append(PickEvent(**{k: v for k, v in e.items() if k != "pick_id"}))
    items = [PickRow(**r, events=events.get(int(r["id"]), [])) for r in rows]
    candidates = [] if public else [CandidateRow(**c) for c in repo.recent_candidates(conn, limit=50)]
    body = PicksOverview(
        lifecycle=Lifecycle(**{k: int(v) for k, v in repo.lifecycle(conn).items()}),
        rule=CURRENT_RULE.as_dict(),
        rejection_reasons={} if public else repo.rejection_reasons(conn),
        candidates_by_decision=repo.candidate_counts(conn),
        picks_by_mode=repo.pick_counts(conn),
        picks=section(items) if items else section(
            items, status=DataStatus.NOT_AVAILABLE,
            reason="No qualified pick: none has beaten the market in walk-forward testing yet." if public else "No shadow pick yet: one needs a real-time forecast AND a price captured after it that passes "
                   f"{CURRENT_RULE.version}. Publishing is disabled; every pick is shadow."),
        recent_candidates=section(candidates) if candidates else section(
            candidates, status=DataStatus.NOT_AVAILABLE,
            reason="No captured price has been evaluated yet: candidates appear after the first odds capture."),
    )
    if not items:
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
    fixtures = int(s["fixtures"] or 0)
    body = PerformanceSummary(slices=_slices(conn),
        settled=settled, pending=pending, staked_units=staked, profit_units=profit,
        roi_pct=roi.quantize(Decimal("0.01")),
        hit_rate=(Decimal(int(s["wins"])) / settled * 100).quantize(Decimal("0.01")),
        note="Shadow picks at the captured price; not a betting record.",
        roi_ci95_pct=_clustered_ci(fixtures, s["fixture_profit_sd"], staked), fixtures=fixtures,
    )
    return ok(body)


MIN_FIXTURES_FOR_INTERVAL = 20


def _clustered_ci(fixtures: int, fixture_profit_sd: Any, staked: Decimal | None) -> Decimal | None:
    """Half-width of the 95% interval on ROI (%) from the spread of per-match profits: the sum over m matches has
    variance m * var(match profit). Null below MIN_FIXTURES_FOR_INTERVAL matches."""
    if not staked or fixtures < MIN_FIXTURES_FOR_INTERVAL or fixture_profit_sd is None:
        return None
    return (Decimal("1.96") * Decimal(fixture_profit_sd) * Decimal(fixtures).sqrt() / staked * 100).quantize(
        Decimal("0.01"))


def _slices(conn: Conn) -> list[PerformanceSlice]:
    out: list[PerformanceSlice] = []
    q2 = Decimal("0.01")
    for r in repo.performance_slices(conn):
        n = int(r["settled"])
        staked = Decimal(r["staked"]) if r["staked"] is not None else None
        profit = Decimal(r["profit"]) if r["profit"] is not None else None
        roi = ci = None
        if staked:
            roi = ((profit or Decimal(0)) / staked * 100).quantize(q2)
            ci = _clustered_ci(int(r["fixtures"] or 0), r["fixture_profit_sd"], staked)
        out.append(PerformanceSlice(
            dimension=r["dimension"], key=str(r["key"]).split(": ", 1)[-1], settled=n, staked_units=staked,
            profit_units=profit, roi_pct=roi, roi_ci95_pct=ci, fixtures=int(r["fixtures"] or 0),
            hit_rate=(Decimal(int(r["wins"])) / n * 100).quantize(q2) if n else None,
            mean_odds=Decimal(r["mean_odds"]).quantize(q2) if r["mean_odds"] is not None else None,
            expected_profit_units=Decimal(r["expected_profit"]).quantize(q2) if r["expected_profit"] is not None
            else None,
        ))
    return out
