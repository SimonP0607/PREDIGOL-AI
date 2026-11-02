"""A small world for the neutral-venue tests, built by hand on the rolled-back ``db`` connection.

A league whose four clubs each play six home matches at their own ground, a cup with a final at a ground that is nobody's,
two national sides meeting in a third country and in one of theirs. Shared by ``test_neutral_venue_db`` (the verdicts, the
switch, what the database refuses) and ``test_neutral_venue_flow`` (the ingestion, the packet, the forecast, the command)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.catalog import neutral_store as ns
from fbi.catalog.neutral import RULE_VERSION
from fbi.features.data import load_matches

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def one(db: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = db.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


@dataclass
class World:
    league_season: int
    cup_season: int
    intl_season: int
    ids: dict[str, int]
    teams: dict[str, int]
    venues: dict[str, int]
    _pid: int = 9_870_000

    def next_pid(self) -> int:
        self._pid += 1
        return self._pid


def add_fixture(db: psycopg.Connection[Any], w: World, season: int, home: str, away: str, kickoff: datetime, *,
                round_: str | None, venue: tuple[str, str, str] | None, score: tuple[int, int] | None) -> int:
    """``venue`` is (key of core.venues, name, city) as the PAYLOAD names the ground; None names no ground."""
    name = city = None
    venue_id = None
    if venue is not None:
        key, name, city = venue
        venue_id = w.venues[key]
    fid = one(db, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                  "venue_id, venue_name, venue_city, kickoff_at, round, status_short, status_group) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
              (w.next_pid(), season, w.teams[home], w.teams[away], venue_id, name, city, kickoff, round_,
               "FT" if score else "NS", "finished" if score else "scheduled"))
    if score is not None:
        db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s,%s,%s)",
                   (fid, score[0], score[1]))
    return int(fid)


def make_world(db: psycopg.Connection[Any]) -> World:
    def competition(pid: int, name: str, kind: str, ctype: str, scope: str, country: str) -> int:
        return int(one(db, "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                           "competition_type) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                       (pid, name, country, kind, scope, ctype)))

    def season(comp: int, year: int) -> int:
        return int(one(db, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s,%s) RETURNING id",
                       (comp, year)))

    league = season(competition(98_701, "Test League", "league", "domestic_league", "club", "England"), 2025)
    cup = season(competition(98_702, "Test Cup", "cup", "domestic_cup", "club", "England"), 2025)
    intl = season(competition(98_703, "Test Qualifiers", "cup", "international", "national_team", "World"), 2026)
    venues: dict[str, int] = {}
    for key, pid, name, city, country in (
            ("blues", 987_201, "Blues Park", "London", "England"), ("reds", 987_202, "Reds Park", "Manchester", "England"),
            ("greens", 987_203, "Greens Park", "Leeds", "England"), ("yellows", 987_204, "Yellows Park", "Bristol", "England"),
            ("arena", 987_205, "Neutral Arena", "Birmingham", "England"),
            ("santiago", 987_206, "Estadio Nacional Test", "Santiago", "Chile"),
            ("rio", 987_207, "Maracana Test", "Rio de Janeiro", "Brazil")):
        venues[key] = int(one(db, "INSERT INTO core.venues (provider_venue_id, name, city, country) "
                                  "VALUES (%s,%s,%s,%s) RETURNING id", (pid, name, city, country)))
    teams: dict[str, int] = {}
    for pid, name, country, national, home in ((987_101, "Blues", "England", False, "blues"),
                                               (987_102, "Reds", "England", False, "reds"),
                                               (987_103, "Greens", "England", False, "greens"),
                                               (987_104, "Yellows", "England", False, "yellows"),
                                               (987_111, "Brazil", "Brazil", True, None),
                                               (987_112, "Argentina", "Argentina", True, None),
                                               # nobody plays them here; they only make "Chile" a label teams carry, which
                                               # the rule demands before it compares a ground's country with a side's
                                               (987_113, "Chile", "Chile", True, None)):
        teams[name] = int(one(db, "INSERT INTO core.teams (provider_team_id, name, country, is_national, venue_id) "
                                  "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                              (pid, name, country, national, None if home is None else venues[home])))
    w = World(league, cup, intl, {}, teams, venues)
    # the history the rule reads: every club's usual ground is its own park (six league home matches each)
    parks = {"Blues": ("blues", "Blues Park", "London"), "Reds": ("reds", "Reds Park", "Manchester"),
             "Greens": ("greens", "Greens Park", "Leeds"), "Yellows": ("yellows", "Yellows Park", "Bristol")}
    names = list(parks)
    for i, home in enumerate(names):
        for k in range(6):
            add_fixture(db, w, league, home, names[(i + 1 + k % 3) % 4], NOW - timedelta(days=400 - 20 * k - i),
                        round_=f"Regular Season - {k + 1}", venue=parks[home], score=(1, 0))
    arena = ("arena", "Neutral Arena", "Birmingham")
    w.ids = {
        "final": add_fixture(db, w, cup, "Blues", "Reds", NOW - timedelta(days=30), round_="Final", venue=arena,
                             score=(2, 1)),
        "quarter_home": add_fixture(db, w, cup, "Greens", "Yellows", NOW - timedelta(days=60),
                                    round_="Quarter-finals", venue=parks["Greens"], score=(0, 0)),
        "r16_arena": add_fixture(db, w, cup, "Blues", "Greens", NOW - timedelta(days=80), round_="Round of 16",
                                 venue=arena, score=(1, 1)),
        "no_venue": add_fixture(db, w, cup, "Reds", "Yellows", NOW - timedelta(days=59), round_="Quarter-finals",
                                venue=None, score=(3, 1)),
        "third": add_fixture(db, w, intl, "Brazil", "Argentina", NOW - timedelta(days=40), round_="Group A - 1",
                             venue=("santiago", "Estadio Nacional Test", "Santiago"), score=(1, 0)),
        "host": add_fixture(db, w, intl, "Brazil", "Argentina", NOW - timedelta(days=20), round_="Group A - 2",
                            venue=("rio", "Maracana Test", "Rio de Janeiro"), score=(2, 2)),
        "ahead": add_fixture(db, w, intl, "Argentina", "Brazil", NOW + timedelta(days=10), round_="Group A - 3",
                             venue=("santiago", "Estadio Nacional Test", "Santiago"), score=None),
    }
    w.ids["league_match"] = int(one(db, "SELECT id FROM core.fixtures WHERE competition_season_id = %s ORDER BY id LIMIT 1",
                                    (league,)))
    return w




def verdicts(db: psycopg.Connection[Any], rule: str = RULE_VERSION) -> dict[int, tuple[bool, str]]:
    rows = db.execute("SELECT fixture_id, neutral, basis FROM core.fixture_venue_class WHERE rule_version = %s",
                      (rule,)).fetchall()
    return {int(f): (bool(n), str(b)) for f, n, b in rows}


def read(db: psycopg.Connection[Any], **kw: Any) -> dict[int, bool]:
    return {m.fixture_id: m.is_neutral for m in load_matches(db, **kw)}


EXPECTED = {
    "final": (True, "decider_ground"),
    "quarter_home": (False, "home_ground"),
    "r16_arena": (False, "no_evidence"),
    "no_venue": (False, "no_venue"),
    "third": (True, "third_country"),
    "host": (False, "home_country"),
    "ahead": (True, "third_country"),
}




NEUTRAL_NAMES = ("final", "third", "ahead")


def neutral_ids(w: World) -> set[int]:
    return {w.ids[n] for n in NEUTRAL_NAMES}




def justified_run(db: psycopg.Connection[Any], *, verdict: str = "justified", through: datetime | None = None,
                  rule: str = RULE_VERSION) -> ns.Run:
    return ns.record_run(db, rule_version=rule, protocol="neutral-ab-v1", verdict=verdict,
                         labels=ns.label_state(db, rule, through=through), params={"margin": 0.005},
                         result={"headline": f"{verdict}: made up for the test"}, code_version="abc123",
                         dataset_hash="d", at=NOW)
