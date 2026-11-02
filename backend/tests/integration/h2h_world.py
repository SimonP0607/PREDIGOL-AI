"""A small world for the head-to-head tests (``fbi.intel.h2h``, plan F6): two sides that have met in a league, a cup and a friendly
(a pinned id), a third side, and the helpers to add matches, results and the benches of a match sheet."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.intel import h2h

from .conftest import Seed
from .helpers import scalar

AT = datetime(2033, 3, 10, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(hours=6)


class World:
    """Two sides, a league, a cup and a friendly (a pinned id), and the match to describe."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db = db
        self.cur = db.cursor()
        self.hash = seed.payload_hash
        self.n = 0
        self.comp: dict[str, tuple[int, int, int]] = {}
        for key, league, ctype, scope in (("league", 98931, "domestic_league", "club"),
                                          ("cup", 98932, "domestic_cup", "club"),
                                          ("friendly", 667, "domestic_cup", "club")):
            self.cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                             "competition_type, is_tracked) VALUES (%s, %s, 'Colombia', %s, %s, %s, true) RETURNING id",
                             (league, f"H2H {key}", "league" if ctype == "domestic_league" else "cup", scope, ctype))
            comp = scalar(self.cur)
            self.cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2033) RETURNING id",
                             (comp,))
            self.comp[key] = (int(comp), int(scalar(self.cur)), league)
        self.team: list[int] = []
        for i in range(3):
            self.cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                             (989310 + i, f"H2H Team {i}"))
            self.team.append(int(scalar(self.cur)))

    def fixture(self, comp: str, home: int, away: int, kickoff: datetime, status: str = "FT", *, neutral: bool = False,
                result: tuple[int, int] | None = None, extra: tuple[int, int] | None = None,
                settled: datetime | None = None, pens: tuple[int, int] | None = None) -> int:
        self.n += 1
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                         "kickoff_at, status_short, status_group, is_neutral) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                         "RETURNING id", (9893000 + self.n, self.comp[comp][1], self.team[home], self.team[away], kickoff,
                                          status, "scheduled" if status == "NS" else "finished", neutral))
        fid = int(scalar(self.cur))
        if result is not None:
            self.cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, et_goals_home, "
                             "et_goals_away, pen_home, pen_away, settled_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                             (fid, result[0], result[1], extra[0] if extra else None, extra[1] if extra else None,
                              pens[0] if pens else None, pens[1] if pens else None,
                              settled or kickoff + timedelta(hours=2)))
        return fid

    def bench(self, fid: int, side: str, coach_id: int | None, name: str | None, fetched: datetime) -> None:
        self.cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, provider_coach_id, coach_name, "
                         "payload_hash, fetched_at) VALUES (%s, %s, 'api-football', %s, %s, %s, %s)",
                         (fid, side, coach_id, name, self.hash, fetched))

    def h2h(self, at: datetime = AT, **kw: Any) -> h2h.HeadToHead:
        args: dict[str, Any] = {"home_team_id": self.team[0], "away_team_id": self.team[1], "kickoff": KICKOFF, "at": at,
                                "competition_id": self.comp["league"][0], "competition_kind": "domestic_league",
                                "provider_league_id": self.comp["league"][2]}
        return h2h.head_to_head(self.db, **(args | kw))
