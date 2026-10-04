"""Research V2 against the real schema: every completed V2 forecast has a role, the runs before
the rebuild keep their label, and the prospective evaluation reads only forecasts stored before
kick-off. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.research.prospective import evaluate_prospective
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

KO = datetime(2031, 3, 1, 15, tzinfo=UTC)


def _experiment(cur: psycopg.Cursor[Any], *, role: str | None, label: str = "RESEARCH_V2",
                kind: str = "backtest") -> None:
    cur.execute("INSERT INTO analytics.experiments (name, kind, question, model_family, config, code_version, "
                "metrics, status, finished_at, run_label, role) VALUES ('t', %s, 'q', 'm', '{}', 'x', "
                "'{\"a\": 1}', 'completed', now(), %s, %s)", (kind, label, role))


def test_a_v2_forecast_needs_a_role_and_legacy_runs_are_kept(db: psycopg.Connection) -> None:
    with db.cursor() as cur:
        _experiment(cur, role="REJECTED")
        _experiment(cur, role=None, kind="audit")
        _experiment(cur, role=None, label="LEGACY_RESEARCH_RUN")
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            _experiment(cur, role=None)
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            _experiment(cur, role="WINNER")
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            _experiment(cur, role="RESEARCH", label="V3")
    db.rollback()


def test_only_forecasts_stored_before_kickoff_are_judged(db: psycopg.Connection, seed: Seed) -> None:
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                    "away_team_id, kickoff_at, status_short, status_group) VALUES (8810001, %s, %s, %s, %s, 'FT', "
                    "'finished') RETURNING id", (seed.season_id, seed.home_team_id, seed.away_team_id, KO))
        fid = scalar(cur)
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 1)",
                    (fid,))
        for made, ph in ((KO - timedelta(hours=3), "0.50"), (KO + timedelta(hours=1), "0.95")):
            for sel, p in (("Home", ph), ("Draw", "0.25"), ("Away", "0.25" if ph == "0.50" else "0.025")):
                cur.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, "
                            "line, p_raw, p_calibrated, p_lo, p_hi, feature_set_hash, data_cutoff_ts, created_at) "
                            "VALUES (%s, %s, '1X2', %s, 0, %s, %s, %s, %s, 'h', %s, %s)",
                            (fid, seed.model_version_id, sel, p, p, p, p, min(made, KO - timedelta(minutes=5))
                             if made < KO else made, made))
        for sel, p in (("Home", "0.48"), ("Draw", "0.27"), ("Away", "0.25")):
            cur.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, "
                        "devig_method, p_fair, n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES "
                        "(%s, '1X2', %s, 0, %s, 'shin', %s, 4, 0.05, 2.0, %s)",
                        (fid, sel, KO - timedelta(minutes=20), p, seed.bookmaker_id))
    result = evaluate_prospective(db, since=KO - timedelta(days=1), until=KO + timedelta(days=1))
    assert result.played == 1 and result.priced == 1
    overall = [r for r in result.rows if r.segment == "all"]
    assert len(overall) == 1 and overall[0].n_common == 1
    c = overall[0].comparison
    assert c is not None
    assert c.model.log_loss == pytest.approx(-__import__("math").log(0.5), abs=1e-6), \
        "the forecast stored before kick-off (Home 0.50), not the one written after it (0.95)"
    db.rollback()
