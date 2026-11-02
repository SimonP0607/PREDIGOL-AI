"""The small world the tests of the team calendar (plan F4) are written in: teams, a followed competition, a match of it, a list the
provider gives for a team and the reading of it by the feed's normalizer. Shared by the store, the packet, the audit and the page tests."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ingestion import reference as ref
from fbi.ingestion import team_calendar as ing
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

T0 = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
_team = itertools.count(91_000)
_fixture = itertools.count(9_100_000)
_league = itertools.count(9_100)
_hash = itertools.count(1)


def payload(db: psycopg.Connection, seed: Seed, at: datetime = T0) -> str:
    """A RAW payload row for a reading to name (every row of the calendar names the payload that said it)."""
    h = f"tc{next(_hash)}"
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, bytes) "
               "VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1)", (h, seed.run_id, at, h))
    return h


def team(db: psycopg.Connection, name: str) -> tuple[int, int]:
    """A team of ours: (id, provider id)."""
    provider = next(_team)
    return int(scalar(db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                 (provider, name)))), provider


def followed_season(db: psycopg.Connection, *, tracked: bool = True, current: bool = True, name: str = "League") -> tuple[int, int]:
    """A competition PrediGol follows and its season: (season id, provider league id)."""
    league = next(_league)
    comp = scalar(db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                             "VALUES (%s, %s, 'league', 'club', 'domestic_league', %s) RETURNING id", (league, name, tracked)))
    season = scalar(db.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, %s) RETURNING id",
                               (comp, current)))
    return int(season), league


def known_competition(db: psycopg.Connection, name: str, kind: str = "domestic_cup") -> int:
    """A competition PrediGol knows but does not follow (not tracked): its provider league id."""
    league = next(_league)
    db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
               "VALUES (%s, %s, 'cup', 'club', %s, false)", (league, name, kind))
    return league


def fixture(db: psycopg.Connection, season_id: int, home: int, away: int, kickoff: datetime, *, status: str = "scheduled",
            created: datetime | None = None, goals: tuple[int, int] | None = None) -> tuple[int, int]:
    """A followed match: (id, provider fixture id)."""
    provider = next(_fixture)
    fid = int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_group, "
        "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (provider, season_id, home, away, kickoff, status, created or kickoff - timedelta(days=30)))))
    if goals is not None:
        db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)", (fid, *goals))
    return fid, provider


def next_provider_fixture() -> int:
    """A provider fixture id no followed match of the test has."""
    return next(_fixture)


def listed(provider_fixture: int, *, home: int, away: int, kickoff: datetime, short: str = "NS", league: int = 9_999,
           league_name: str = "Copa del Rey", goals: tuple[int | None, int | None] = (None, None),
           home_name: str = "Home FC", away_name: str = "Away FC") -> dict[str, Any]:
    """One element of the provider's list for a team."""
    return {"fixture": {"id": provider_fixture, "date": kickoff.isoformat(), "status": {"short": short}},
            "league": {"id": league, "name": league_name, "country": "Spain", "season": 2026, "round": "Round of 16"},
            "teams": {"home": {"id": home, "name": home_name}, "away": {"id": away, "name": away_name}},
            "goals": {"home": goals[0], "away": goals[1]}}


def read(db: psycopg.Connection, seed: Seed, team_provider: int, entries: list[dict[str, Any]], at: datetime = T0,
         season: int = 2026) -> int:
    """The list of a team read at ``at``: what the feed's normalizer writes."""
    target = ref.Target(f"team:{team_provider}:{season}", {"team": team_provider, "season": season}, timedelta(days=1), {})
    return ing.apply(db, target, {"response": entries}, payload(db, seed, at), at)


# ── a match between two teams, each with a last match in the league PrediGol follows ──────────────────────────────────────

AT = datetime(2032, 10, 5, 12, tzinfo=UTC)
"""The moment a packet is built in these tests."""
KICKOFF = AT + timedelta(hours=6)
FRESH = AT - timedelta(hours=20)
"""A team's list read yesterday: whole by the packet's moment."""


@dataclass
class World:
    fixture_id: int
    league: int
    home: int
    away: int
    other: int
    """The provider ids of the teams (the ones the provider's list names)."""
    home_followed: int
    away_followed: int
    """The provider ids of each side's last match in the league PrediGol follows."""


def world(db: psycopg.Connection[Any], *, home_last: float, away_last: float) -> World:
    """The match, and each side's last match in the league PrediGol follows ``home_last`` / ``away_last`` days before it."""
    season, league = followed_season(db, name="Calendar League")
    (home_id, home), (away_id, away), (other_id, other) = team(db, "Home FC"), team(db, "Away FC"), team(db, "Other FC")
    _, home_followed = fixture(db, season, home_id, other_id, KICKOFF - timedelta(days=home_last), status="finished", goals=(1, 0))
    _, away_followed = fixture(db, season, other_id, away_id, KICKOFF - timedelta(days=away_last), status="finished", goals=(0, 2))
    target, _ = fixture(db, season, home_id, away_id, KICKOFF)
    return World(target, league, home, away, other, home_followed, away_followed)


def cup_tie(w: World, side: str, *, days_before: float | None = None, days_after: float | None = None, league: int = 9_999,
            name: str = "Copa del Rey", short: str | None = None) -> dict[str, Any]:
    """A match of the team's in a competition PrediGol does not follow, as the provider lists it."""
    me, rival = (w.home, w.other) if side == "home" else (w.away, w.other)
    kickoff = KICKOFF - timedelta(days=days_before) if days_before is not None else KICKOFF + timedelta(days=days_after or 0)
    done = days_before is not None
    return listed(next_provider_fixture(), home=me, away=rival, kickoff=kickoff, short=short or ("FT" if done else "NS"),
                  league=league, league_name=name, goals=(2, 1) if done else (None, None),
                  home_name="Home FC" if side == "home" else "Away FC", away_name="Other FC")


def own_followed(w: World, side: str, days_before: float) -> dict[str, Any]:
    """The team's league match, as the provider's list also gives it (the list is the whole of the season)."""
    me = w.home if side == "home" else w.away
    followed = w.home_followed if side == "home" else w.away_followed
    return listed(followed, home=me, away=w.other, kickoff=KICKOFF - timedelta(days=days_before), short="FT", league=w.league,
                  league_name="Calendar League", goals=(1, 0))


def read_both(db: psycopg.Connection[Any], seed: Seed, w: World, at: datetime = FRESH) -> dict[str, dict[str, Any]]:
    """Each team's list read at ``at``: the home side has played a cup tie two days ago and has a continental tie in three days."""
    played, coming = cup_tie(w, "home", days_before=2.0), cup_tie(w, "home", days_after=3.0, league=2, name="Champions League")
    read(db, seed, w.home, [own_followed(w, "home", 8.0), played, coming], at)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], at)
    return {"played": played, "coming": coming}
