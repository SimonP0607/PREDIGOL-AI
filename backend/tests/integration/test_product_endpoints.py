"""Home, picks, parlays and best prices over HTTP, on a dataset where every number is known.

NOW is far from every other test's dates and the dataset is removed afterwards, so no
other test sees it. Nine fixtures, each with a pick on the home win:

    F1-F6   +2h .. +12h   qualified, fresh price 2.30 vs model 0.50  -> value (EV 0.15)
    F7      +30h          qualified, fresh price 2.30                -> value, multi-day only
    F8      +5h           qualified, price captured 5h ago           -> stale_price
    F9      +6h           qualified, price 1.70                      -> non_positive_ev
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in

NOW = datetime(2031, 3, 10, 12, 0, tzinfo=UTC)
PICK_COLS = (
    "candidate_id,fixture_id,market_key,selection,model_version_id,calibrator_id,"
    "feature_set_hash,data_cutoff_ts,decision_rule_version,code_version,bookmaker_id,"
    "market_odds,odds_captured_at,p_model,p_calibrated,p_calibrated_lo,p_calibrated_hi,"
    "p_market_fair,fair_odds,edge,price_edge,ev,ev_adjusted,kelly_fraction,stake_units,"
    "selection_reason"
)
PLAN: list[tuple[str, float, str, float]] = [
    # name, kickoff hours from NOW, best price now, price age in hours
    ("F1", 2, "2.30", 0.5), ("F2", 4, "2.30", 0.5), ("F3", 6, "2.30", 0.5), ("F4", 8, "2.30", 0.5),
    ("F5", 10, "2.30", 0.5), ("F6", 12, "2.30", 0.5), ("F7", 30, "2.30", 0.5),
    ("F8", 5, "2.30", 5.0), ("F9", 6.5, "1.70", 0.5),
]


@pytest.fixture(scope="module")
def dataset(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"fixtures": {}, "teams": [], "picks": {}}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id,name,country,type,entity_scope,"
                    "competition_type,is_tracked,logo_url,flag_url,country_code) VALUES (77001,'Liga Test',"
                    "'Spain','league','club','domestic_league',true,'https://media.api-sports.io/football/leagues/"
                    "140.png','https://media.api-sports.io/flags/es.svg','ES') RETURNING id")
        ids["competition"] = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id,season,is_current) VALUES (%s,2030,true) "
                    "RETURNING id", (ids["competition"],))
        season = scalar(cur)
        cur.execute(
            "INSERT INTO models.calibrators (model_version_id,market_key,scope,method,params,n_train,train_from,"
            "train_to,n_val,val_from,val_to,val_ece,val_mce,val_brier,val_logloss,reliability_weight) VALUES "
            "(%s,'1X2','global','isotonic','{}',1000,'2020-01-01','2024-06-30',500,'2024-07-01','2025-06-30',"
            "0.018,0.04,0.19,0.58,0.82) RETURNING id", (seed.model_version_id,))
        ids["calibrator"] = calibrator = scalar(cur)
        for n, (name, hours, price, age) in enumerate(PLAN):
            teams = []
            for side in ("H", "A"):
                cur.execute("INSERT INTO core.teams (provider_team_id,name,logo_url) VALUES (%s,%s,%s) RETURNING id",
                            (880000 + 2 * n + (side == "A"), f"{name}-{side}",
                             f"https://media.api-sports.io/football/teams/{880000 + 2 * n}.png"))
                teams.append(scalar(cur))
            ids["teams"].extend(teams)
            ko = NOW + timedelta(hours=hours)
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id,competition_season_id,home_team_id,"
                        "away_team_id,kickoff_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                        (990000 + n, season, teams[0], teams[1], ko))
            fid = scalar(cur)
            ids["fixtures"][name] = fid
            cutoff = NOW - timedelta(days=1)
            cur.execute("INSERT INTO models.predictions (fixture_id,model_version_id,calibrator_id,market_key,"
                        "selection,p_raw,p_calibrated,p_lo,p_hi,feature_set_hash,data_cutoff_ts) VALUES "
                        "(%s,%s,%s,'1X2','Home',0.50,0.50,0.45,0.55,'fh',%s) RETURNING id",
                        (fid, seed.model_version_id, calibrator, cutoff))
            prediction = scalar(cur)
            cur.execute("INSERT INTO picks.pick_candidates (run_id,fixture_id,prediction_id,market_key,selection,"
                        "bookmaker_id,market_odds,p_calibrated,p_market_fair,edge,price_edge,ev,ev_adjusted,decision)"
                        " VALUES (%s,%s,%s,'1X2','Home',%s,2.30,0.50,0.43,0.07,0.08,0.15,0.10,'selected') "
                        "RETURNING id", (seed.run_id, fid, prediction, seed.bookmaker_id))
            candidate = scalar(cur)
            cur.execute(
                f"INSERT INTO picks.picks ({PICK_COLS}) VALUES (%s,%s,'1X2','Home',%s,%s,'fh',%s,'shadow-rule-v2',"
                "'abc',%s,2.30,%s,0.50,0.50,0.45,0.55,0.43,2.0,0.07,0.08,0.15,0.10,0.11,1,'{}') RETURNING id",
                (candidate, fid, seed.model_version_id, calibrator, cutoff, seed.bookmaker_id,
                 cutoff + timedelta(minutes=5)))
            pick = scalar(cur)
            ids["picks"][name] = pick
            cur.execute("UPDATE picks.picks SET status = 'qualified', qualification = "
                        "'{\"qualified\": true}'::jsonb WHERE id = %s", (pick,))
            as_of = NOW - timedelta(hours=age)
            for sel, p_fair, odds in (("Home", "0.43", price), ("Draw", "0.28", "3.40"), ("Away", "0.29", "3.30")):
                cur.execute("INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,"
                            "devig_method,p_fair,n_bookmakers,overround,best_odds,best_bookmaker_id) VALUES "
                            "(%s,'1X2',%s,0,%s,'shin',%s,5,0.05,%s,%s)",
                            (fid, sel, as_of, p_fair, odds, seed.bookmaker_id))
    yield ids
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        fids = list(ids["fixtures"].values())
        picks = list(ids["picks"].values())
        cur.execute("DELETE FROM picks.pick_events WHERE pick_id = ANY(%s)", (picks,))
        cur.execute("DELETE FROM picks.picks WHERE id = ANY(%s)", (picks,))
        cur.execute("DELETE FROM picks.pick_candidates WHERE fixture_id = ANY(%s)", (fids,))
        cur.execute("DELETE FROM models.predictions WHERE fixture_id = ANY(%s)", (fids,))
        cur.execute("DELETE FROM models.calibrators WHERE id = %s", (ids["calibrator"],))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (fids,))
        cur.execute("DELETE FROM core.teams WHERE id = ANY(%s)", (ids["teams"],))
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (ids["competition"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["competition"],))


@pytest.fixture()
def as_role(dataset: dict[str, Any], migrated_database: str) -> Iterator[Any]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    set_clock(FrozenClock(NOW))
    from fbi.api.app import create_app

    clients: list[TestClient] = []

    def make(role: str) -> TestClient:
        c = TestClient(signed_in(create_app(), role), headers=SAME_SITE)
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()
    set_clock(SystemClock())
    mp.undo()
    reset_cache()


def data(c: TestClient, path: str) -> dict[str, Any]:
    r = c.get(path)
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    body: dict[str, Any] = r.json()["data"]
    return body


def test_the_daily_parlay_takes_the_five_best_legs_that_pass(as_role: Any, dataset: dict[str, Any]) -> None:
    p = data(as_role("USER"), "/api/v1/parlays/daily")
    assert p["status"] == "ok" and p["source"] == "qualified" and len(p["legs"]) == 5
    assert {leg["fixture_id"] for leg in p["legs"]} <= {dataset["fixtures"][f] for f in ("F1", "F2", "F3", "F4",
                                                                                         "F5", "F6")}
    assert p["eligible_legs"] == 6
    assert p["rejections"]["stale_price"] == 1 and p["rejections"]["non_positive_ev"] == 1
    assert Decimal(p["combined_odds"]) == (Decimal("2.30") ** 5).quantize(Decimal("0.01"))
    assert Decimal(p["probability_all_win"]) == (Decimal("0.5") ** 5).quantize(Decimal("0.000001"))
    assert p["independence"] == "distinct_fixtures_and_teams" and p["risk"] == "very_high"
    leg = p["legs"][0]
    assert leg["home"]["logo_url"].startswith("https://") and leg["competition"]["flag_url"].endswith("es.svg")
    assert Decimal(leg["ev"]) == Decimal("0.15")


def test_the_multiday_parlay_reaches_two_days(as_role: Any, dataset: dict[str, Any]) -> None:
    p = data(as_role("USER"), "/api/v1/parlays/multiday")
    assert p["status"] == "ok" and len(p["legs"]) == 7
    assert dataset["fixtures"]["F7"] in {leg["fixture_id"] for leg in p["legs"]}


def test_picks_are_re_priced_and_say_when_they_have_no_value_now(as_role: Any, dataset: dict[str, Any]) -> None:
    board = data(as_role("USER"), "/api/v1/picks")
    assert board["source"] == "qualified" and len(board["top"]) == 5 and board["reason"] is None
    by_fixture = {p["fixture_id"]: p for p in board["picks"]}
    assert len(by_fixture) == 9
    stale = by_fixture[dataset["fixtures"]["F8"]]
    assert stale["value_now"] is False and stale["value_reason"] == "stale_price" and stale["freshness"] == "stale"
    poor = by_fixture[dataset["fixtures"]["F9"]]
    assert poor["value_now"] is False and poor["value_reason"] == "non_positive_ev" and Decimal(poor["ev"]) < 0
    good = by_fixture[dataset["fixtures"]["F1"]]
    assert good["value_now"] and good["freshness"] == "fresh" and Decimal(good["fair_odds"]) == Decimal("2.326")
    only_9 = data(as_role("USER"), "/api/v1/picks?max_odds=1.80")
    assert [p["fixture_id"] for p in only_9["picks"]] == [dataset["fixtures"]["F9"]]
    assert only_9["reason"] == "no_value_now"
    none = data(as_role("USER"), "/api/v1/picks?market=BTTS")
    assert none["picks"] == [] and none["reason"] == "no_picks_match_filters"


def test_without_enough_qualified_picks_there_is_no_parlay(as_role: Any, dataset: dict[str, Any],
                                                           migrated_database: str) -> None:
    demoted = [dataset["picks"][f] for f in ("F1", "F2", "F3")]
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("UPDATE picks.picks SET status = 'shadow' WHERE id = ANY(%s)", (demoted,))
    try:
        p = data(as_role("USER"), "/api/v1/parlays/daily")
        assert p["status"] == "no_valid_parlay" and p["legs"] == [] and p["combined_odds"] is None
        assert p["eligible_legs"] == 3
        # the owner's shadow preview shows what the layout would look like - and says so
        preview = data(as_role("SUPER_ADMIN"), "/api/v1/parlays/daily?preview=shadow")
        assert preview["status"] == "ok" and preview["source"] == "shadow_preview"
    finally:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("UPDATE picks.picks SET status = 'qualified' WHERE id = ANY(%s)", (demoted,))


def test_home_puts_it_all_on_one_page(as_role: Any, dataset: dict[str, Any]) -> None:
    home = data(as_role("USER"), "/api/v1/home")
    assert home["source"] == "qualified"
    assert home["top_picks"]["status"] == "ok" and len(home["top_picks"]["data"]) == 5
    assert home["daily_parlay"]["status"] == "ok" and home["multiday_parlay"]["status"] == "ok"
    assert home["live"]["status"] == "empty" and home["live"]["reason"] == "no_live_matches"
    assert home["upcoming"]["status"] == "ok"
    assert home["data_freshness"]["odds_at"] is not None


def test_the_best_odds_board_sets_each_price_against_the_fair_one(as_role: Any, dataset: dict[str, Any]) -> None:
    board = data(as_role("USER"), "/api/v1/odds/best?market=1X2")
    fixtures = {f["fixture_id"]: f for f in board["fixtures"]}
    f1 = fixtures[dataset["fixtures"]["F1"]]
    home = next(s for s in f1["markets"][0]["selections"] if s["selection"] == "Home")
    assert Decimal(home["best_odds"]) == Decimal("2.30") and Decimal(home["fair_odds"]) == Decimal("2.326")
    assert Decimal(home["price_edge"]) == Decimal("2.30") * Decimal("0.43") - 1
    assert board["value"] and all(p["value_now"] for p in board["value"])
    prices = data(as_role("USER"), "/api/v1/odds/best?market=1X2&picks=false")
    assert prices["value"] == [], "the Cuotas page: prices only, whatever the picks (REVIEW point 17)"
    assert [f["fixture_id"] for f in prices["fixtures"]] == [f["fixture_id"] for f in board["fixtures"]]
