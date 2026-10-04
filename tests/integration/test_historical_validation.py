"""Historical validation on a built world: every finished match gets one state, every
competition-season a data score and a class; the transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.validation.historical import RULE_VERSION, classify, validate_history

from .conftest import Seed
from .helpers import scalar

AT = datetime(2034, 1, 10, 12, tzinfo=UTC)


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.cur, self.seed = db.cursor(), seed
        self.pid = 7340000

    def season(self, league: int, name: str) -> int:
        self.cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                         "is_tracked) VALUES (%s, %s, 'league', 'club', 'domestic_league', true) RETURNING id",
                         (league, name))
        comp = scalar(self.cur)
        self.cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2033) "
                         "RETURNING id", (comp,))
        return int(scalar(self.cur))

    def match(self, cs: int, kickoff: datetime, *, status: str = "FT", score: tuple[int, int] | None = (1, 0),
              ht: tuple[int, int] | None = None, ft: tuple[int, int] | None = None, rated: bool = True,
              priced: bool = False, swap: bool = False) -> int:
        self.pid += 1
        home, away = self.seed.home_team_id, self.seed.away_team_id
        if swap:
            home, away = away, home
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                         "away_team_id, kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, "
                         "'finished') RETURNING id", (self.pid, cs, home, away, kickoff, status))
        fid = int(scalar(self.cur))
        if score is not None:
            self.cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, "
                             "ht_goals_away, ft_goals_home, ft_goals_away) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                             (fid, score[0], score[1], *(ht or (None, None)), *(ft or (None, None))))
        if rated:
            for team, before in ((home, 1500.0), (away, 1490.0)):
                self.cur.execute("INSERT INTO features.elo_ratings (elo_version, run_id, team_id, fixture_id, kickoff_at, "
                                 "rating_before, rating_after, expected_score, actual_score, k_factor, margin_multiplier) "
                                 "VALUES ('test', %s, %s, %s, %s, %s, %s, 0.5, 0.5, 20, 1)",
                                 (self.seed.run_id, team, fid, kickoff, before, before))
        if priced:
            self.cur.execute("INSERT INTO market.historical_odds (fixture_id, source, bookmaker_code, market_key, "
                             "selection, price_kind, odds_decimal, source_payload_hash) VALUES "
                             "(%s, 'test', 'B365', '1X2', 'Home', 'closing', 2.10, %s)", (fid, self.seed.payload_hash))
        return fid


def test_classes_follow_the_thresholds() -> None:
    full = {"results": 1.0, "integrity": 1.0, "stats": 0.5, "lineups": 0.5, "odds": 0.7, "elo": 1.0}
    assert classify(60, full) == ("MODEL_READY", ())
    klass, reasons = classify(60, {**full, "odds": 0.2})
    assert klass == "PARTIAL" and "prices 20%" in reasons[0]
    assert classify(40, full)[0] == "PARTIAL", "fewer than 50 matches: not enough to judge against the market"
    assert classify(60, {**full, "results": 0.9})[0] == "PRODUCT_ONLY"
    assert classify(60, {**full, "integrity": 0.95})[0] == "PRODUCT_ONLY"
    assert classify(8, full)[0] == "INSUFFICIENT"
    assert classify(60, {**full, "results": 0.7})[0] == "INSUFFICIENT"


def test_every_finished_match_gets_one_state_and_the_reasons(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    ready = w.season(97301, "Ready League")
    start = AT - timedelta(days=400)
    ready_ids = [w.match(ready, start + timedelta(days=3 * i), swap=bool(i % 2), priced=i < 42) for i in range(60)]
    thin = w.season(97302, "Thin League")
    # two days after each Ready League match: never the same pairing within 36 hours
    thin_ids = [w.match(thin, start + timedelta(days=3 * i + 2), swap=bool(i % 2)) for i in range(12)]
    dup_a = w.match(thin, AT - timedelta(days=20))
    dup_b = w.match(thin, AT - timedelta(days=20) + timedelta(hours=5))
    no_result = w.match(thin, AT - timedelta(days=1), score=None)
    halftime = w.match(thin, AT - timedelta(days=4), score=(1, 0), ht=(2, 0))
    pens = w.match(thin, AT - timedelta(days=7), status="PEN", score=(2, 1), ft=(1, 1))
    aet = w.match(thin, AT - timedelta(days=10), status="AET", score=(2, 1))
    future = w.match(thin, AT + timedelta(days=2))

    report = validate_history(db, at=AT)
    assert report.fixtures >= 79
    rows = {int(f): (s, set(failed)) for f, s, failed in db.execute(
        "SELECT fixture_id, state, failed FROM analytics.fixture_validation WHERE rule_version = %s AND fixture_id = "
        "ANY(%s)", (RULE_VERSION, [*ready_ids, dup_a, dup_b, *thin_ids, no_result, halftime, pens, aet, future]))}
    assert {rows[f][0] for f in ready_ids} == {"HISTORICAL_APPROVED"}
    assert rows[dup_a][0] == "QUARANTINED" and "provider_duplicate" in rows[dup_a][1]
    assert rows[dup_b][0] == "QUARANTINED"
    assert rows[no_result][0] == "INGESTED" and "no_result" in rows[no_result][1]
    assert rows[halftime][0] == "QUARANTINED" and "halftime_exceeds_score" in rows[halftime][1]
    assert rows[pens][0] == "QUARANTINED" and "penalties_without_level" in rows[pens][1]
    assert rows[aet][0] == "QUARANTINED" and "no_regulation_score" in rows[aet][1]
    assert rows[future][0] == "QUARANTINED" and "finished_in_future" in rows[future][1]
    assert {rows[f][0] for f in thin_ids} == {"VALIDATED"}, "valid, but the season is not fit for modelling"
    assert all("competition_not_fit" in rows[f][1] for f in thin_ids)

    scores = {int(cs): (k, comp, n, a, q) for cs, k, comp, n, a, q in db.execute(
        "SELECT competition_season_id, class, components, finished, approved, quarantined "
        "FROM analytics.competition_data_scores WHERE competition_season_id = ANY(%s)", ([ready, thin],))}
    klass, comp, n, approved, quarantined = scores[ready]
    assert (klass, n, approved, quarantined) == ("MODEL_READY", 60, 60, 0)
    assert comp["odds"] == 0.7
    assert scores[thin][0] == "PRODUCT_ONLY", "19 matches, 1 without a result and 6 quarantined"
    assert scores[thin][4] == 6
    ready_view = db.execute("SELECT count(*) FROM analytics.model_ready_fixtures WHERE competition_season_id = %s",
                            (ready,)).fetchone()
    assert ready_view == (60,)


def test_the_admin_console_reads_validation_and_a_user_cannot(migrated_database: str) -> None:
    import pytest
    from fastapi.testclient import TestClient

    from fbi.api.app import create_app
    from fbi.api.services import truth as truth_service
    from fbi.core.config import reset_cache
    from tests.integration.signed_in import SAME_SITE, admin_app, signed_in

    truth_service._cache.clear()
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    try:
        admin = TestClient(admin_app(), headers=SAME_SITE)
        for path in ("/api/v1/admin/data/validation", "/api/v1/admin/data/validation/competitions",
                     "/api/v1/admin/data/validation/quarantine"):
            res = admin.get(path)
            assert res.status_code == 200, path
            assert res.json()["status"] in ("ok", "empty"), path
        assert admin.get("/api/v1/admin/data/validation/competitions", params={"class": "NOPE"}).status_code == 422
        user = TestClient(signed_in(create_app(), "USER"), headers=SAME_SITE)
        assert user.get("/api/v1/admin/data/validation").status_code == 403
    finally:
        mp.undo()
        reset_cache()
        truth_service._cache.clear()
