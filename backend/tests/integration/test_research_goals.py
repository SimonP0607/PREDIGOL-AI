"""F2's goals diagnosis reads what it says it reads (plan PICKS, Q2): each model's last real-time forecast BEFORE kick-off,
the last de-vigged consensus BEFORE kick-off with the engine's method, what the match did, and whether a team is new in
its competition this season. A forecast or a price after kick-off, another line and another de-vig method are left
out."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from scripts.research_picks_calibration import load_goals

from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

KICKOFF = datetime(2033, 3, 6, 18, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def world(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"teams": [], "fixtures": {}}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id,name,type,entity_scope,competition_type) "
                    "VALUES (77301,'Liga Goles','league','club','domestic_league') RETURNING id")
        ids["competition"] = comp = scalar(cur)
        seasons = {}
        for year in (2032, 2033):
            cur.execute("INSERT INTO core.competition_seasons (competition_id,season) VALUES (%s,%s) RETURNING id",
                        (comp, year))
            seasons[year] = scalar(cur)
        teams = {}
        for n, name in enumerate(("A", "B", "C")):
            cur.execute("INSERT INTO core.teams (provider_team_id,name) VALUES (%s,%s) RETURNING id",
                        (873001 + n, f"Goles {name}"))
            teams[name] = scalar(cur)
            ids["teams"].append(teams[name])
        plan = [  # name, season, home, away, kick-off, goals
            ("last_year", 2032, "A", "B", KICKOFF - timedelta(days=200), (0, 0)),
            ("known", 2033, "A", "B", KICKOFF, (1, 0)),
            ("newcomer", 2033, "A", "C", KICKOFF + timedelta(days=7), (2, 2)),
        ]
        for n, (name, year, home, away, ko, (gh, ga)) in enumerate(plan):
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id,competition_season_id,home_team_id,away_team_id,"
                        "kickoff_at,status_short) VALUES (%s,%s,%s,%s,%s,'FT') RETURNING id",
                        (973001 + n, seasons[year], teams[home], teams[away], ko))
            fid = scalar(cur)
            ids["fixtures"][name] = fid
            cur.execute("INSERT INTO core.fixture_results (fixture_id,goals_home,goals_away) VALUES (%s,%s,%s)",
                        (fid, gh, ga))

        def forecast(fid: int, market: str, selection: str, line: str, p: str, at: datetime) -> None:
            cur.execute("INSERT INTO models.predictions (fixture_id,model_version_id,market_key,selection,line,p_raw,"
                        "p_calibrated,feature_set_hash,data_cutoff_ts,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,'fh',%s,%s)",
                        (fid, seed.model_version_id, market, selection, line, p, p, at, at))

        def price(fid: int, market: str, selection: str, line: str, p: str, at: datetime,
                  method: str = "shin") -> None:
            cur.execute("INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,devig_method,"
                        "p_fair,n_bookmakers,overround,best_odds,best_bookmaker_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,5,0.05,2.0,%s)",
                        (fid, market, selection, line, at, method, p, seed.bookmaker_id))

        known = ids["fixtures"]["known"]
        forecast(known, "OU", "Under", "2.5", "0.50", KICKOFF - timedelta(days=2))
        forecast(known, "OU", "Under", "2.5", "0.62", KICKOFF - timedelta(hours=1))   # the last before kick-off
        forecast(known, "OU", "Under", "2.5", "0.90", KICKOFF + timedelta(hours=1))   # after kick-off: out
        forecast(known, "OU", "Under", "3.5", "0.80", KICKOFF - timedelta(hours=1))   # another line: out
        forecast(known, "BTTS", "No", "0", "0.58", KICKOFF - timedelta(hours=3))
        price(known, "OU", "Under", "2.5", "0.48", KICKOFF - timedelta(hours=3))
        price(known, "OU", "Under", "2.5", "0.52", KICKOFF - timedelta(minutes=10))    # the last before kick-off
        price(known, "OU", "Under", "2.5", "0.99", KICKOFF + timedelta(minutes=5))     # after kick-off: out
        price(known, "OU", "Under", "2.5", "0.30", KICKOFF - timedelta(minutes=5), "proportional")  # other method
        price(known, "BTTS", "No", "0", "0.47", KICKOFF - timedelta(minutes=20))
        new = ids["fixtures"]["newcomer"]
        new_ko = KICKOFF + timedelta(days=7)
        forecast(new, "OU", "Under", "2.5", "0.55", new_ko - timedelta(hours=2))
        price(new, "OU", "Under", "2.5", "0.45", new_ko - timedelta(minutes=30))
        forecast(new, "BTTS", "No", "0", "0.40", new_ko - timedelta(hours=2))          # no price for it: out
    yield ids
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        fids = list(ids["fixtures"].values())
        cur.execute("DELETE FROM market.market_consensus WHERE fixture_id = ANY(%s)", (fids,))
        cur.execute("DELETE FROM models.predictions WHERE fixture_id = ANY(%s)", (fids,))
        cur.execute("DELETE FROM core.fixture_results WHERE fixture_id = ANY(%s)", (fids,))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (fids,))
        cur.execute("DELETE FROM core.teams WHERE id = ANY(%s)", (ids["teams"],))
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (ids["competition"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["competition"],))


def test_the_goals_diagnosis_reads_the_last_forecast_and_price_before_kick_off(
    world: dict[str, Any], migrated_database: str,
) -> None:
    with psycopg.connect(migrated_database, row_factory=dict_row) as conn:
        rows = load_goals(conn, since=KICKOFF - timedelta(days=1), cutoff=KICKOFF + timedelta(days=30))
    mine = {(r["fixture_id"], r["market_key"]): r for r in rows if r["fixture_id"] in world["fixtures"].values()}
    known, new = world["fixtures"]["known"], world["fixtures"]["newcomer"]
    assert set(mine) == {(known, "OU"), (known, "BTTS"), (new, "OU")}, "a forecast without a price is left out"
    ou = mine[(known, "OU")]
    assert (ou["p_model"], ou["p_market"]) == (0.62, 0.52), "the last of each before kick-off, the engine's method"
    assert ou["low"] is True and ou["newcomer"] is False and ou["competition"] == "Liga Goles"
    btts = mine[(known, "BTTS")]
    assert (btts["p_model"], btts["p_market"], btts["low"]) == (0.58, 0.47, True), "1-0: both teams did not score"
    nc = mine[(new, "OU")]
    assert nc["low"] is False, "2-2 went over 2.5"
    assert nc["newcomer"] is True, "C did not play the season before"
