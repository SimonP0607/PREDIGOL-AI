"""value-v2 and corr-v2 (IA-097 / IA-098) against the real schema: the score matrix of a match rebuilt from its model's stored rows, the shadow
portfolio with corr-v2 beside portfolio-corr-v1 (which still stakes: no stake moves), and the production measurement - all read-only."""

# ruff: noqa: F811  (pytest fixtures imported from other test modules are used by name as parameters)
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from scripts import ia_value_correlation as measure

from fbi.models.scoring import dc_tau, poisson_matrix
from fbi.portfolio import build
from fbi.valuation import dependence as dep
from tests.integration.test_match_forecast import AT as FORECAST_AT
from tests.integration.test_match_forecast import World, world  # noqa: F401

from .test_portfolio import AT, DAY, PortfolioWorld, w, writes  # noqa: F401
from .test_single_figure_parity import LA, LH, RHO, predict_from_matrix

pytestmark = pytest.mark.integration


def test_the_score_matrix_of_a_match_is_rebuilt_from_its_models_stored_rows(world: World) -> None:
    fid = world.fixture()
    predict_from_matrix(world, fid)
    before = writes(world.db)
    mats, basis = dep.read_matrices(world.db, [fid], at=FORECAST_AT)
    assert writes(world.db) == before, "read-only"
    want = dc_tau(poisson_matrix(LH, LA), LH, LA, RHO)
    want = want / want.sum()
    assert fid in mats and np.abs(mats[fid] - want).max() < 1e-4 and basis[fid].startswith("dixon_coles")
    assert dep.read_matrices(world.db, [fid], at=FORECAST_AT - timedelta(days=2)) == ({}, {}), "nothing stored before its cut-off"


def test_the_portfolio_reads_corr_v2_beside_portfolio_corr_v1_and_no_stake_moves(w: PortfolioWorld) -> None:
    season = w.competition(97711, "Corr v2 League")
    f1, f2 = w.fixture(season, AT + timedelta(hours=4)), w.fixture(season, AT + timedelta(hours=4, minutes=30))
    d1, d2 = w.decision(f1, "APROBADO", score=60.0), w.decision(f2, "APROBADO", score=58.0)
    w.decision(f1, "APROBADO", score=50.0, market="OU", selection="Over", line="2.5")
    before = writes(w.db)
    plain = build.build_day(w.db, DAY, at=AT)
    doc = build.build_day(w.db, DAY, at=AT, corr_v2=True)
    assert writes(w.db) == before, "read-only"
    v2 = doc.pop("correlation_v2")
    assert doc == plain, "portfolio-corr-v1 still stakes: corr-v2 is a block beside it"
    pair = next(p for p in v2["pairs"] if {p["a"], p["b"]} == {d1, d2})
    assert (pair["relation"], pair["source"], pair["budget_rho"]) == ("same_competition_day", "unmeasured", 0.15)
    same = [p for p in v2["pairs"] if p["relation"] == "same_match"]
    assert len(same) == 1 and same[0]["source"] == "unmeasured" and same[0]["combinable"] is False and v2["matrices"] == 0
    assert v2["budget_differs_from_v1"] == [] and v2["version"] == "corr-v2"


def test_the_measurement_is_read_only_and_counts_what_it_read(w: PortfolioWorld) -> None:
    season = w.competition(97712, "Corr v2 Measure League")
    f1, f2 = w.fixture(season, AT + timedelta(hours=4)), w.fixture(season, AT + timedelta(hours=5))
    w.decision(f1, "CAUTELA", reasons=("risk",), known=AT - timedelta(hours=10))
    w.decision(f1, "CAUTELA", reasons=("correlated_same_match",), market="OU", selection="Over", line="2.5", known=AT - timedelta(hours=10))
    w.decision(f2, "APROBADO", known=AT - timedelta(hours=10))
    before = writes(w.db)
    value = measure.value(w.db, since=DAY - timedelta(days=1), until=DAY + timedelta(days=1))
    corr = measure.correlation(w.db, since=DAY, until=DAY + timedelta(days=1))
    assert writes(w.db) == before, "read-only"
    assert value["rows"] >= 3 and value["with_interval"] >= 3 and value["confirmed_single_book"] == 0
    assert corr["days"] == 1 and corr["selections"] == 3
    assert corr["decision_v1_filter_8"]["same_match_pair"] == 1 and corr["decision_v1_filter_8"]["a_side_is_correlated_same_match"] == 1
    assert corr["parlay_v5"]["refused_by_guard"] == 1 and corr["pairs_by_relation"]["same_competition_day"] == 2


def test_the_command_parses() -> None:
    ap = measure.build_parser()
    args = ap.parse_args(["value", "--since", "2026-11-03", "--until", "2026-11-17", "--json"])
    assert args.command == "value" and date.fromisoformat(args.since) < date.fromisoformat(args.until)
