"""Analytics page services. Every figure is a count or a mean over stored rows."""

from __future__ import annotations

import math
from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from fbi.api.contracts.common import TeamRef
from fbi.api.contracts.explorer import (
    LOW_SAMPLE,
    CompetitionProfile,
    CoverageCell,
    EloPoint,
    ExperimentSummary,
    GateCheck,
    MarketAnalytics,
    MarketBucket,
    MarketSeason,
    MigrationProgress,
    ProcessPoint,
    Split,
    TeamAnalytics,
    TeamFeatures,
)
from fbi.api.envelope import DataStatus, Envelope, listing
from fbi.api.repositories import Conn
from fbi.api.repositories import explorer as repo
from fbi.features.engine import FEATURE_VERSION

MARKET_BASELINE = ("pinnacle", "closing", "shin")
CALIBRATION_BINS = 10


def _f(x: Any) -> float | None:
    if x is None:
        return None
    v = float(x) if isinstance(x, Decimal | int | float) else float(str(x))
    return v if math.isfinite(v) else None


def competitions(conn: Conn) -> Envelope[list[CompetitionProfile]]:
    rows = repo.competition_profiles(conn, FEATURE_VERSION)
    items = []
    for r in rows:
        low = int(r["finished"]) < LOW_SAMPLE
        items.append(CompetitionProfile(
            competition_id=r["competition_id"], competition=r["competition"], country=r["country"],
            competition_type=r["competition_type"], season=r["season"], fixtures=r["fixtures"],
            finished=r["finished"], low_sample=low,
            **{k: _f(r[k]) for k in ("home_win", "draw", "away_win", "goals_per_match", "home_goals_per_match",
                                     "away_goals_per_match", "home_goal_difference", "btts", "over_2_5")},
            with_team_stats=r["with_team_stats"], with_historical_odds=r["with_historical_odds"],
            with_odds_snapshots=r["with_odds_snapshots"], with_features=r["with_features"],
            with_predictions=r["with_predictions"]))
    return listing(items, empty_reason="No fixtures have been ingested yet.")


def coverage(conn: Conn) -> Envelope[list[CoverageCell]]:
    items = [CoverageCell(**r) for r in repo.coverage(conn, FEATURE_VERSION)]
    return listing(items, empty_reason="No fixtures have been ingested yet.")


def _split(rows: list[dict[str, Any]]) -> Split:
    won = sum(1 for r in rows if r["gf"] > r["ga"])
    drawn = sum(1 for r in rows if r["gf"] == r["ga"])
    lost = len(rows) - won - drawn
    return Split(played=len(rows), won=won, drawn=drawn, lost=lost, goals_for=sum(int(r["gf"]) for r in rows),
                 goals_against=sum(int(r["ga"]) for r in rows),
                 points_per_match=None if not rows else (3 * won + drawn) / len(rows))


def team(conn: Conn, team_id: int) -> Envelope[TeamAnalytics]:
    t = repo.team(conn, team_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"team {team_id} not found")
    results = repo.team_results(conn, team_id)
    elo = sorted(repo.team_elo(conn, team_id), key=lambda r: r["kickoff_at"])
    process = sorted(repo.team_process(conn, team_id), key=lambda r: r["kickoff_at"])
    feat = repo.team_latest_features(conn, team_id, FEATURE_VERSION)
    features = None
    if feat is not None and feat["vals"]:
        side = str(feat["side"])
        other = "away" if side == "home" else "home"
        values: dict[str, float | None] = {}
        for name, value in dict(feat["vals"]).items():
            if name.startswith(f"{side}_"):
                values[name[len(side) + 1:]] = _f(value)
            elif name.startswith(f"{other}_"):
                continue
            elif name in (f"pi_{side}", "elo_" + side):
                values[name.replace(f"_{side}", "")] = _f(value)
        features = TeamFeatures(fixture_id=feat["fixture_id"], feature_version=feat["feature_version"],
                                data_cutoff=feat["data_cutoff"], side=side, values=values)
    data = TeamAnalytics(
        team=TeamRef(id=t["id"], name=t["name"], provider_team_id=t["provider_team_id"]),
        splits={"all": _split(results), "home": _split([r for r in results if r["at_home"]]),
                "away": _split([r for r in results if not r["at_home"]])},
        elo=[EloPoint(fixture_id=r["fixture_id"], kickoff_at=r["kickoff_at"], competition=r["competition"],
                      opponent=TeamRef(id=r["opponent_id"], name=r["opponent_name"],
                                       provider_team_id=r["opponent_provider_id"]),
                      at_home=r["at_home"], rating_before=float(r["rating_before"]),
                      rating_after=float(r["rating_after"]), expected_score=float(r["expected_score"]),
                      actual_score=float(r["actual_score"])) for r in elo],
        process=[ProcessPoint(**r) for r in process],
        features=features,
    )
    if not results:
        return Envelope[TeamAnalytics](status=DataStatus.INSUFFICIENT_DATA, data=data,
                                       reason="No recorded result for this team yet.")
    return Envelope[TeamAnalytics](status=DataStatus.OK, data=data)


def market(conn: Conn) -> Envelope[MarketAnalytics]:
    bm, kind, method = MARKET_BASELINE
    rows = repo.market_probabilities(conn, bm, kind, method)
    index = {"Home": 0, "Draw": 1, "Away": 2}
    sums = [[0, 0.0, 0.0] for _ in range(CALIBRATION_BINS)]  # n, sum p, hits
    for r in rows:
        y = index.get(str(r["outcome_1x2"]))
        if y is None:
            continue
        for k, p in enumerate((r["p_home"], r["p_draw"], r["p_away"])):
            pv = float(p)
            b = min(int(pv * CALIBRATION_BINS), CALIBRATION_BINS - 1)
            sums[b][0] += 1
            sums[b][1] += pv
            sums[b][2] += 1.0 if k == y else 0.0
    buckets = [MarketBucket(lower=i / CALIBRATION_BINS, upper=(i + 1) / CALIBRATION_BINS, n=int(n),
                            mean_probability=None if n == 0 else sp / n, observed_rate=None if n == 0 else h / n)
               for i, (n, sp, h) in enumerate(sums)]
    seasons = []
    for r in repo.market_by_season(conn, bm, method):
        closing, pre = _f(r["closing_logloss"]), _f(r["pre_closing_logloss"])
        seasons.append(MarketSeason(
            competition_id=r["competition_id"], competition=r["competition"], season=r["season"], n=r["n"],
            closing_logloss=closing, pre_closing_logloss=pre,
            closing_improvement=None if closing is None or pre is None else pre - closing,
            mean_overround_closing=_f(r["mean_overround_closing"])))
    data = MarketAnalytics(baseline="/".join(MARKET_BASELINE), n_fixtures=len(rows), calibration=buckets,
                           by_season=seasons, source="football-data.co.uk closing and pre-closing prices")
    if not rows:
        return Envelope[MarketAnalytics](status=DataStatus.NOT_AVAILABLE, data=data,
                                         reason="No historical market baseline has been imported yet.")
    return Envelope[MarketAnalytics](status=DataStatus.OK, data=data)


def experiments(conn: Conn) -> Envelope[list[ExperimentSummary]]:
    reproduced = repo.reproductions(conn)
    items = []
    for r in repo.experiments(conn):
        m: dict[str, Any] = dict(r["metrics"] or {})
        own = m.get("own_sample") or {}
        vs = m.get("vs_primary") or {}
        diff = vs.get("logloss_diff") or {}
        details = vs.get("details") or {}
        gate: dict[str, Any] = dict(r["gate"] or {})
        checks = [GateCheck(name=k, passed=bool(v.get("passed")), evidence=str(v.get("evidence", "")))
                  for k, v in (gate.get("checks") or {}).items()]
        by_comp: list[dict[str, float | str]] = [
            {"competition_id": str(cid), "n": float(row.get("n", 0)), "logloss_diff": float(row.get("logloss_diff", 0.0))}
            for cid, row in sorted((m.get("by_competition") or {}).items())]
        items.append(ExperimentSummary(
            id=r["id"], uuid=r["uuid"], name=r["name"], model_family=r["model_family"],
            research_status=r["research_status"], gate_passed=bool(gate.get("passed")), gate=checks,
            reproduced=r["id"] in reproduced, reproduced_by=reproduced.get(r["id"]),
            reproduction_of=r["reproduced_from"],
            backtest_session_id=r["backtest_session_id"], code_version=r["code_version"],
            dataset_hash=r["dataset_hash"], feature_version=r["feature_version"], test_from=r["test_from"],
            test_to=r["test_to"], own_n=own.get("n"), own_logloss=_f(own.get("log_loss")),
            own_brier=_f(own.get("brier")), own_ece=_f(own.get("ece")),
            market_logloss_diff=_f(diff.get("mean")), market_diff_low=_f(diff.get("lo")),
            market_diff_high=_f(diff.get("hi")), verdict=vs.get("verdict"), evidence=vs.get("evidence"),
            dm_p=_f(details.get("dm_p")), by_competition=by_comp, finished_at=r["finished_at"]))
    return listing(items, empty_reason="No experiment has been recorded yet (python -m scripts.run_backtest --apply).")


def migration(conn: Conn) -> Envelope[MigrationProgress]:
    plan = repo.migration_plan(conn)
    rows = repo.migration_units(conn)
    units: dict[str, dict[str, int]] = defaultdict(dict)
    tiers: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        units[str(r["kind"])][str(r["status"])] = units[str(r["kind"])].get(str(r["status"]), 0) + int(r["units"])
        tier = f"tier {r['tier']}" if r["tier"] else "untiered"
        tiers[tier][str(r["status"])] = tiers[tier].get(str(r["status"]), 0) + int(r["units"])
    summary: dict[str, Any] = dict(plan["summary"]) if plan and plan["summary"] else {}
    data = MigrationProgress(
        plan_id=None if plan is None else plan["id"], plan_name=None if plan is None else plan["name"],
        plan_created_at=None if plan is None else plan["created_at"],
        planned_requests=summary.get("requests"), units=dict(units),
        requests_spent=sum(int(r["spent"]) for r in rows), rows_written=sum(int(r["rows"]) for r in rows),
        by_tier=dict(tiers), last_activity_at=max((r["last_at"] for r in rows if r["last_at"]), default=None))
    if not rows:
        return Envelope[MigrationProgress](status=DataStatus.NOT_AVAILABLE, data=data,
                                           reason="No migration unit has been seeded yet.")
    return Envelope[MigrationProgress](status=DataStatus.OK, data=data)
