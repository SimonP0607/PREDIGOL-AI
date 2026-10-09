"""MATCH INTELLIGENCE MEMORY: the matches looked at, searchable by team, league, coach, player, market, odds band and
model, before and after (fbi.api.services.match_memory)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg

from fbi.api.services.match_memory import MemoryFilters, search
from fbi.picks.fast_settlement import settle_fixtures

from .conftest import Seed
from .test_daily_records import AT, World

AFTER = AT + timedelta(days=2)


def test_the_memory_finds_a_match_by_what_the_owner_asks(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    f1, f3 = w.fixtures["F1"], w.fixtures["F3"]
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, coach_name, payload_hash, "
               "fetched_at) VALUES (%s, 'home', 'api-football', '4-3-3', 'Coach Uno', 'h1', %s)", (f1, AT))
    db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, "
               "player_name, is_starter) VALUES (%s, 'home', 'api-football', 9901, 'Juan Delantero', true)", (f1,))
    w.result("F1", 2, 0)
    w.result("F3", 0, 0)
    settle_fixtures(db, [f1, f3], path="live_follow", at=AT + timedelta(hours=9))

    def ids(**flt: Any) -> list[int]:
        env = search(db, MemoryFilters(**flt), limit=50, at=AFTER)
        return [m.fixture_id for m in (env.data or [])]

    everything = ids()
    assert f1 in everything and f3 in everything, "matches with picks are in the memory"
    assert ids(team="F1-H") == [f1]
    assert ids(coach="coach uno") == [f1], "case-insensitive"
    assert ids(player="delantero") == [f1]
    assert f1 in ids(competition="Daily League") and f1 not in ids(competition="Daily League B")
    assert set(ids(market="1X2")) >= {f1, f3} and ids(market="AH") == []
    assert f1 in ids(odds_band="2.20-2.99") and f1 not in ids(odds_band="1.50-1.79"), "taken at 2.30"
    assert f1 in ids(model="dixon_coles") and ids(model="poisson") == []
    m = next(x for x in search(db, MemoryFilters(team="F1-H"), limit=5, at=AFTER).data or [])
    assert (m.score_home, m.score_away, m.home_coach, m.won, m.lost) == (2, 0, "Coach Uno", 1, 0)
    assert m.markets == ["1X2"] and m.models == ["dixon_coles"] and m.pnl_units == 1.3
