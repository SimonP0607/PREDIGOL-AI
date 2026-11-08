"""The owner's performance console with a real sample (plan PICKS, R1).

Until BE-006 only the «insufficient sample» branch of ``GET /admin/performance`` was ever exercised: below 30
settled picks the endpoint returns before it builds the slices. Production has thousands, and the console answered
HTTP 500. Here 40 settled shadow picks on 40 matches - wins, losses, half results, pushes and voids, two odds bands,
two months - go through the whole path: the totals, the clustered interval and every slice.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in

KICKOFF = datetime(2032, 1, 20, 18, 0, tzinfo=UTC)
PICK_COLS = (
    "candidate_id,fixture_id,market_key,selection,model_version_id,"
    "feature_set_hash,data_cutoff_ts,decision_rule_version,code_version,bookmaker_id,"
    "market_odds,odds_captured_at,p_model,p_calibrated,"
    "p_market_fair,fair_odds,edge,price_edge,ev,ev_adjusted,kelly_fraction,stake_units,"
    "selection_reason"
)
# result, profit at the pick's price (1 unit staked)
OUTCOMES: list[tuple[str, str]] = [
    ("win", "1.3000"), ("loss", "-1.0000"), ("half_win", "0.6500"), ("half_loss", "-0.5000"),
    ("push", "0.0000"), ("void", "0.0000"), ("win", "1.3000"), ("loss", "-1.0000"),
]
N = 40


@pytest.fixture(scope="module")
def settled(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"fixtures": [], "teams": [], "picks": []}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id,name,country,type,entity_scope,"
                    "competition_type,is_tracked) VALUES (77201,'Liga Rendimiento','Spain','league','club',"
                    "'domestic_league',true) RETURNING id")
        ids["competition"] = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id,season,is_current) VALUES (%s,2031,true) "
                    "RETURNING id", (ids["competition"],))
        season = scalar(cur)
        for n in range(N):
            teams = []
            for side in (0, 1):
                cur.execute("INSERT INTO core.teams (provider_team_id,name) VALUES (%s,%s) RETURNING id",
                            (872000 + 2 * n + side, f"Rendimiento {n}-{side}"))
                teams.append(scalar(cur))
            ids["teams"].extend(teams)
            # two months, so the "month" slice has two keys
            ko = KICKOFF + timedelta(days=n)
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id,competition_season_id,home_team_id,"
                        "away_team_id,kickoff_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                        (972000 + n, season, teams[0], teams[1], ko))
            fid = scalar(cur)
            ids["fixtures"].append(fid)
            cutoff = ko - timedelta(days=1)
            # two odds bands, so the "odds_band" slice has two keys
            odds = "2.30" if n % 2 == 0 else "1.60"
            market = "1X2" if n % 4 < 2 else "BTTS"
            selection = "Home" if market == "1X2" else "Yes"
            cur.execute("INSERT INTO models.predictions (fixture_id,model_version_id,market_key,selection,p_raw,"
                        "p_calibrated,feature_set_hash,data_cutoff_ts) VALUES (%s,%s,%s,%s,0.50,0.50,'fh',%s) "
                        "RETURNING id", (fid, seed.model_version_id, market, selection, cutoff))
            prediction = scalar(cur)
            cur.execute("INSERT INTO picks.pick_candidates (run_id,fixture_id,prediction_id,market_key,selection,"
                        "bookmaker_id,market_odds,p_calibrated,p_market_fair,edge,price_edge,ev,ev_adjusted,decision)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,0.50,0.43,0.07,0.08,0.15,0.10,'selected') RETURNING id",
                        (seed.run_id, fid, prediction, market, selection, seed.bookmaker_id, odds))
            candidate = scalar(cur)
            cur.execute(
                f"INSERT INTO picks.picks ({PICK_COLS}) VALUES (%s,%s,%s,%s,%s,'fh',%s,'shadow-rule-v2','abc',%s,"
                "%s,%s,0.50,0.50,0.43,2.0,0.07,0.08,0.15,0.10,0.11,1,'{}') RETURNING id",
                (candidate, fid, market, selection, seed.model_version_id, cutoff, seed.bookmaker_id, odds,
                 cutoff + timedelta(minutes=5)))
            pick = scalar(cur)
            ids["picks"].append(pick)
            status, profit = OUTCOMES[n % len(OUTCOMES)]
            cur.execute("INSERT INTO picks.pick_results (pick_id,result_status,profit_units,settled_at,settled_by,"
                        "settlement_basis,rule_version) VALUES (%s,%s,%s,%s,'test','regulation_90','settle-v4')",
                        (pick, status, Decimal(profit), ko + timedelta(hours=2)))
    yield ids
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM picks.pick_results WHERE pick_id = ANY(%s)", (ids["picks"],))
        cur.execute("DELETE FROM picks.pick_events WHERE pick_id = ANY(%s)", (ids["picks"],))
        cur.execute("DELETE FROM picks.picks WHERE id = ANY(%s)", (ids["picks"],))
        cur.execute("DELETE FROM picks.pick_candidates WHERE fixture_id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM models.predictions WHERE fixture_id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM core.teams WHERE id = ANY(%s)", (ids["teams"],))
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (ids["competition"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["competition"],))


@pytest.fixture()
def owner(settled: dict[str, Any], migrated_database: str) -> Iterator[TestClient]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    from fbi.api.app import create_app

    with TestClient(signed_in(create_app()), headers=SAME_SITE) as c:
        yield c
    mp.undo()
    reset_cache()


def test_the_console_answers_with_a_real_sample(owner: TestClient) -> None:
    r = owner.get("/api/v1/admin/performance")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    d = body["data"]
    assert d["settled"] >= N and d["roi_pct"] is not None and d["hit_rate"] is not None
    assert d["fixtures"] >= N and d["roi_ci95_pct"] is not None, "40 matches: the clustered interval is shown"
    dims = {s["dimension"] for s in d["slices"]}
    assert dims == {"market", "model", "rule", "month", "odds_band"}
    keys = {(s["dimension"], s["key"]) for s in d["slices"]}
    assert {("odds_band", "1.70-2.49"), ("odds_band", "< 1.70")} <= keys, "the sort prefix is not shown"
    assert {("month", "2032-01"), ("month", "2032-02")} <= keys
    for s in d["slices"]:
        assert s["settled"] > 0 and s["key"]


def test_each_slice_counts_its_own_bets(owner: TestClient) -> None:
    """The months are this file's alone (2032): their figures are known to the cent."""
    d = owner.get("/api/v1/admin/performance").json()["data"]
    by_key = {(s["dimension"], s["key"]): s for s in d["slices"]}
    for month, ns in (("2032-01", range(12)), ("2032-02", range(12, N))):
        rows = [OUTCOMES[n % len(OUTCOMES)] for n in ns]
        staked = sum(1 for status, _ in rows if status != "void")
        profit = sum(Decimal(p) for _, p in rows)
        s = by_key[("month", month)]
        assert s["settled"] == len(rows) and s["fixtures"] == len(rows)
        assert Decimal(s["staked_units"]) == staked and Decimal(s["profit_units"]) == profit
        assert Decimal(s["roi_pct"]) == (profit / staked * 100).quantize(Decimal("0.01"))
        wins = sum(1 for status, _ in rows if status in ("win", "half_win"))
        assert Decimal(s["hit_rate"]) == (Decimal(wins) / len(rows) * 100).quantize(Decimal("0.01"))
        odds = [Decimal("2.30") if n % 2 == 0 else Decimal("1.60") for n in ns]
        assert Decimal(s["mean_odds"]) == (sum(odds) / len(odds)).quantize(Decimal("0.01"))
        assert Decimal(s["expected_profit_units"]) == (Decimal("0.15") * staked).quantize(Decimal("0.01"))
