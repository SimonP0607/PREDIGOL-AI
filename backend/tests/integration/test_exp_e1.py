"""RP-9.1 on a real database: the sample of EXP-E1 counts only the matches AFTER the signature with a real close of two books or more and the raw forecasts of
at least two models stored before the kick-off; the raw figure is read (not the calibrated one) and the verdict is written only through the launcher's path."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from scripts import exp_run

from fbi.research import exp_conditions, exp_e1, verdicts

from .conftest import Seed
from .helpers import scalar

pytestmark = pytest.mark.integration

SIGNED = date(2026, 11, 26)
AFTER = datetime(2026, 12, 3, 19, tzinfo=UTC)
BEFORE = datetime(2026, 11, 20, 19, tzinfo=UTC)


def fixture(db: psycopg.Connection[Any], seed: Seed, provider_id: int, kickoff: datetime) -> int:
    fid = int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_short, status_group) "
        "VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id", (provider_id, seed.season_id, seed.home_team_id, seed.away_team_id, kickoff))))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 1)", (fid,))
    return fid


def model_version(db: psycopg.Connection[Any], name: str) -> int:
    mid = scalar(db.execute("INSERT INTO models.model_registry (name, family, description) VALUES (%s, 'goals', 'test') RETURNING id", (name,)))
    return int(scalar(db.execute("INSERT INTO models.model_versions (model_id, version, train_from, train_to, n_train, code_version) "
                                 "VALUES (%s, 'v1', '2020-01-01', '2024-06-30', 5000, 'abc') RETURNING id", (mid,))))


def forecast(db: psycopg.Connection[Any], fid: int, version: int, kickoff: datetime, raw: tuple[str, str, str], *, calibrated: tuple[str, str, str]) -> None:
    for sel, p, c in zip(("Home", "Draw", "Away"), raw, calibrated, strict=True):
        db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, p_lo, p_hi, "
                   "feature_set_hash, data_cutoff_ts, created_at) VALUES (%s, %s, '1X2', %s, 0, %s, %s, %s, %s, 'h', %s, %s)",
                   (fid, version, sel, p, c, c, c, kickoff - timedelta(hours=4), kickoff - timedelta(hours=4)))


def real_close(db: psycopg.Connection[Any], fid: int, books: int) -> None:
    for sel, p in (("Home", "0.48"), ("Draw", "0.27"), ("Away", "0.25")):
        db.execute("INSERT INTO market.near_close_consensus (fixture_id, market_key, selection, line, devig_method, p_fair, n_bookmakers, minutes_to_ko, "
                   "newest_minutes_to_ko, version, computed_at) VALUES (%s, '1X2', %s, 0, 'shin', %s, %s, 40, 20, 'test', now())", (fid, sel, p, books))


def test_the_sample_counts_only_what_the_protocol_says(db: psycopg.Connection[Any], seed: Seed) -> None:
    v1, v2 = model_version(db, "poisson"), seed.model_version_id
    good = fixture(db, seed, 9_100_001, AFTER)
    old = fixture(db, seed, 9_100_002, BEFORE)
    two_books = fixture(db, seed, 9_100_003, AFTER + timedelta(hours=2))
    one_model = fixture(db, seed, 9_100_004, AFTER + timedelta(hours=4))
    for fid, kick in ((good, AFTER), (old, BEFORE), (two_books, AFTER + timedelta(hours=2)), (one_model, AFTER + timedelta(hours=4))):
        forecast(db, fid, v1, kick, ("0.50", "0.25", "0.25"), calibrated=("0.40", "0.30", "0.30"))
        if fid != one_model:
            forecast(db, fid, v2, kick, ("0.46", "0.28", "0.26"), calibrated=("0.40", "0.30", "0.30"))
        real_close(db, fid, 1 if fid == two_books else 4)
    far = datetime(2100, 1, 1, tzinfo=UTC)
    loaded = exp_e1.load(db, after=exp_e1.after_signature(SIGNED), until=far)
    assert [m.fixture for m in loaded] == [good], "after the signature, two books or more, two models or more"
    m = loaded[0]
    assert m.forecasts["poisson"] == pytest.approx((0.50, 0.25, 0.25)), "the raw figure, not the calibrated one"
    assert m.close == pytest.approx((0.48, 0.27, 0.25)) and m.outcome == 0 and m.day == AFTER.date()
    assert exp_e1.load(db, after=datetime(2026, 11, 1, tzinfo=UTC), until=far)[0].fixture in {old, good}, "the matches already looked at can be read, never counted"
    assert exp_e1.count(db, SIGNED) == 1


def test_the_experiment_is_registered_by_the_launcher_script_and_is_not_due_before_its_sample(db: psycopg.Connection[Any]) -> None:
    exp_conditions.unregister("EXP-E1")
    try:
        exp_run.load_plugins()
        assert "EXP-E1" in exp_conditions.registered()
        state = exp_conditions.check(db, "EXP-E1", at=AFTER, model_code="code")
        assert (state.due, state.code, state.required) == (False, "sample", 1000)
        assert verdicts.latest(db) == []
    finally:
        for key in ("EXP-E1", "EXP-E3", "EXP-E7"):
            exp_conditions.unregister(key)
