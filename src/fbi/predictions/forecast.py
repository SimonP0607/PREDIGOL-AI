"""Real-time forecasts for upcoming fixtures, made BEFORE the prices they will be compared with.

Each goal model is refitted on the results known now (kick-off + 3 h before
the forecast instant), for the fixture's competition, with the time decay and
shrinkage its latest backtest chose on the validation season. The Elo ordered
logit is refitted on every domestic league result with an Elo feature, and fed
the fixture's own Elo difference as of now. Nothing here is tuned on what
happens next.

No new information, no new forecast: when a fixture's latest forecast was
computed from exactly the same inputs, nothing is written, so the table is a
record of what changed rather than a heartbeat.

What the forecasts cannot escape is the data the plan allows: on the free
plan a season that could not be read is a gap in the training data, and the
lineage records how old the newest result behind each forecast is.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.backtesting.data import load_backtest_data
from fbi.backtesting.persist import ensure_version, goal_hyper, ologit_hyper
from fbi.backtesting.walkforward import (
    MIN_ELO_HISTORY,
    MIN_GOAL_TRAIN,
    MIN_OLOGIT_TRAIN,
    GoalSpec,
    WalkForwardConfig,
    elo_history_short,
    known_before,
    outcome_index,
    train_hash,
)
from fbi.features.data import MatchRecord, load_team_stats
from fbi.features.elo import EloParams
from fbi.features.engine import FEATURE_VERSION, walk_forward
from fbi.features.store import ensure_registry, write_feature_sets
from fbi.models.elo_ologit import OLogitObs, fit_ologit
from fbi.models.goals import GoalObs, InvalidCorrectionError, fit_goal_model
from fbi.models.quoted import price_quoted_lines, quoted_lines
from fbi.models.scoring import MARKET_ROWS

HORIZON = timedelta(days=4)
MIN_LEAD = timedelta(minutes=15)
"""A forecast needs to exist before the last price we could compare it with (T-12)."""


@dataclass
class ForecastReport:
    at: datetime
    targets: int = 0
    written: int = 0
    unchanged: int = 0
    predicted: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    uncovered: list[tuple[int, str, str]] = field(default_factory=list)
    skipped_models: dict[str, str] = field(default_factory=dict)
    lines_priced: int = 0
    """Rows for lines the market quoted that MARKET_ROWS does not cover: Asian
    Handicap, Double Chance, and every Over/Under line but 2.5. Those prices
    were being captured and stored with no model number opposite them - 8,841
    AH, 1,444 DC, and 9,306 of 10,240 OU."""
    newest_result_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Spec:
    competition_ids: tuple[int, ...]
    cfg: WalkForwardConfig
    goal: dict[str, GoalSpec]
    session_id: int


def current_spec(conn: psycopg.Connection) -> Spec | None:
    """Hyper-parameters from the latest completed backtest session - the only
    place they are chosen, and always on a validation season."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, competition_ids, config, selection FROM analytics.backtest_sessions "
                    "WHERE status = 'completed' ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    config: dict[str, Any] = dict(row["config"])
    cfg = WalkForwardConfig(competition_ids=tuple(int(x) for x in row["competition_ids"]),
                            history_days=int(config.get("history_days", 730)))
    goal = {kind: GoalSpec(kind, float(sel["chosen"]["xi"]), float(sel["chosen"]["penalty"]))
            for kind, sel in dict(row["selection"]).items() if kind in ("poisson", "dixon_coles")}
    return Spec(cfg.competition_ids, cfg, goal, int(row["id"]))


def upcoming(conn: psycopg.Connection, at: datetime, horizon: timedelta) -> list[int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT f.id FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id WHERE c.is_tracked AND f.status_group = 'scheduled' "
            "AND f.kickoff_at > %s AND f.kickoff_at <= %s ORDER BY f.kickoff_at",
            (at + MIN_LEAD, at + horizon),
        )
        return [int(r[0]) for r in cur.fetchall()]


def _latest_hashes(conn: psycopg.Connection, fixture_ids: list[int]) -> dict[tuple[int, int], str]:
    """(fixture, model_version) -> input hash of its newest real-time forecast."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT DISTINCT ON (fixture_id, model_version_id) fixture_id, model_version_id, feature_set_hash "
            "FROM models.predictions WHERE backtest_session_id IS NULL AND fixture_id = ANY(%s) "
            "ORDER BY fixture_id, model_version_id, data_cutoff_ts DESC",
            (fixture_ids,),
        )
        return {(int(a), int(b)): str(c) for a, b, c in cur.fetchall()}


def _write(conn: psycopg.Connection, rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, "
            "p_calibrated, p_lo, p_hi, feature_set_hash, data_cutoff_ts, p_push) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING", rows)
        return max(cur.rowcount, 0)


def forecast_upcoming(conn: psycopg.Connection, *, at: datetime, code_version: str,
                      horizon: timedelta = HORIZON) -> ForecastReport:
    report = ForecastReport(at=at)
    target_ids = upcoming(conn, at, horizon)
    report.targets = len(target_ids)
    if not target_ids:
        return report
    spec = current_spec(conn)
    # What the market quoted, read once for every target rather than per model.
    quoted = quoted_lines(conn, target_ids)
    if spec is None:
        report.skipped_models["all"] = "no completed backtest session: no validated hyper-parameters to use"
        return report
    data = load_backtest_data(conn, feature_version=FEATURE_VERSION)
    by_id = {m.fixture_id: m for m in data.matches}
    targets = [by_id[i] for i in target_ids if i in by_id]
    known = [m for m in data.matches if known_before(m, at)]
    report.newest_result_at = max((m.kickoff_at for m in known), default=None)
    latest = _latest_hashes(conn, target_ids)
    rows: list[tuple[Any, ...]] = []

    # --- goal models, per competition --------------------------------------
    by_comp: dict[int, list[MatchRecord]] = defaultdict(list)
    for m in known:
        by_comp[m.competition_id].append(m)
    for kind, gspec in sorted(spec.goal.items()):
        for comp in sorted({t.competition_id for t in targets}):
            comp_targets = [t for t in targets if t.competition_id == comp]
            train = [m for m in by_comp[comp] if m.kickoff_at >= at - timedelta(days=spec.cfg.history_days)]
            if len(train) < MIN_GOAL_TRAIN:
                report.uncovered.extend((t.fixture_id, kind, f"fewer than {MIN_GOAL_TRAIN} results in the last "
                                         f"{spec.cfg.history_days} days") for t in comp_targets)
                continue
            model = fit_goal_model(
                [GoalObs(m.home_team_id, m.away_team_id, m.settle_home or 0, m.settle_away or 0,
                         weight=math.exp(-gspec.xi * (at - m.kickoff_at).total_seconds() / 86400),
                         neutral=m.is_neutral) for m in train],
                kind=kind, xi=gspec.xi, penalty=gspec.penalty, with_covariance=True)
            if not model.converged:
                report.uncovered.extend((t.fixture_id, kind, "model fit did not converge") for t in comp_targets)
                continue
            version_id = ensure_version(
                conn, model=kind, spec=gspec.tag, hyper=goal_hyper(gspec.xi, gspec.penalty, spec.cfg, code_version),
                code_version=code_version, feature_names=[], train_from=min(m.kickoff_at for m in train).date(),
                train_to=max(m.kickoff_at for m in train).date(), n_train=len(train))
            th = train_hash(train)
            for t in comp_targets:
                if not (model.knows(t.home_team_id) and model.knows(t.away_team_id)):
                    report.uncovered.append((t.fixture_id, kind, "a team has no result in this competition's "
                                             "training window (promoted, or a season the plan cannot read)"))
                    continue
                if latest.get((t.fixture_id, version_id)) == th:
                    report.unchanged += 1
                    continue
                try:
                    probs = model.predict(t.home_team_id, t.away_team_id, neutral=t.is_neutral)
                except InvalidCorrectionError:
                    report.uncovered.append((t.fixture_id, kind, "Dixon-Coles correction invalid at these expected goals"))
                    continue
                bounds = model.interval_rows(t.home_team_id, t.away_team_id, neutral=t.is_neutral)
                point = probs.as_rows()
                for k, (mk, sel, line) in enumerate(MARKET_ROWS):
                    rows.append((t.fixture_id, version_id, mk, sel, line, round(point[k], 6), round(point[k], 6),
                                 None if bounds is None else round(float(bounds[0][k]), 6),
                                 None if bounds is None else round(float(bounds[1][k]), 6), th, at, 0))

                # Every other line the market quoted for this fixture, off the
                # same matrix. 8,841 Asian Handicap and 1,444 Double Chance
                # prices were stored with nothing to compare them against, and
                # the model priced 1 of the 26 Over/Under lines we capture.
                triples = quoted.get(t.fixture_id)
                if triples:
                    matrix, _, _ = model.score_matrix(
                        t.home_team_id, t.away_team_id, neutral=t.is_neutral)
                    for lp in price_quoted_lines(matrix, triples):
                        # p_lo/p_hi stay NULL: no interval was computed for these,
                        # and repeating the point estimate as a bound would read
                        # as certainty the model never claimed.
                        rows.append((t.fixture_id, version_id, lp.market_key,
                                     lp.selection, lp.line, round(lp.p_win, 6),
                                     round(lp.p_win, 6), None, None, th, at,
                                     round(lp.p_push, 6)))
                        report.lines_priced += 1
                report.predicted[kind] += 1

    # --- Elo ordered logit ---------------------------------------------------
    vectors, _ = walk_forward(data.matches, [(t, at) for t in targets], EloParams(), load_team_stats(conn))
    ensure_registry(conn)
    write_feature_sets(conn, vectors, version=FEATURE_VERSION, code_version=code_version, run_id=None,
                       lineage={"purpose": "real-time forecast", "cutoff": at.isoformat()})
    elo = {v.fixture_id: v for v in vectors}
    domestic = set(spec.competition_ids)
    labelled = [m for m in known if m.competition_id in domestic
                and data.features.get(m.fixture_id, {}).get("elo_diff") is not None]
    if len(labelled) < MIN_OLOGIT_TRAIN:
        report.skipped_models["elo_ologit"] = f"fewer than {MIN_OLOGIT_TRAIN} labelled domestic results"
    else:
        ol = fit_ologit([OLogitObs(float(data.features[m.fixture_id]["elo_diff"] or 0.0), m.is_neutral,
                                   2 - outcome_index(m)) for m in labelled])
        version_id = ensure_version(
            conn, model="elo_ologit", spec="elo=v2.0,K=20,home=65", hyper=ologit_hyper(code_version),
            code_version=code_version, feature_names=["elo_diff"],
            train_from=min(m.kickoff_at for m in labelled).date(),
            train_to=max(m.kickoff_at for m in labelled).date(), n_train=len(labelled))
        for t in targets:
            v = elo.get(t.fixture_id)
            x = None if v is None else v.values.get("elo_diff")
            if v is None or x is None:
                report.uncovered.append((t.fixture_id, "elo_ologit", "no Elo feature for this fixture"))
                continue
            if elo_history_short(v.values):
                report.uncovered.append((t.fixture_id, "elo_ologit",
                                         f"a team has fewer than {MIN_ELO_HISTORY} rated matches"))
                continue
            if latest.get((t.fixture_id, version_id)) == v.input_hash:
                report.unchanged += 1
                continue
            try:
                p = ol.predict(float(x), neutral=t.is_neutral)
            except ValueError as exc:
                report.uncovered.append((t.fixture_id, "elo_ologit", str(exc)))
                continue
            bounds = ol.interval(float(x), neutral=t.is_neutral)
            for k, sel in enumerate(("Home", "Draw", "Away")):
                rows.append((t.fixture_id, version_id, "1X2", sel, 0.0, round(p[k], 6), round(p[k], 6),
                             None if bounds is None else round(float(np.asarray(bounds[0])[k]), 6),
                             None if bounds is None else round(float(np.asarray(bounds[1])[k]), 6),
                             v.input_hash, at, 0))
            report.predicted["elo_ologit"] += 1
    report.written = _write(conn, rows)
    return report
