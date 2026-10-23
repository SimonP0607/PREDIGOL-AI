"""A team's calendar in every competition, in the database (plan F4): what the provider's list writes, what stays out, what a reader may
know at a given moment, and who is asked about how often."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.competitions import team_calendar as tc
from fbi.ingestion import reference as ref
from fbi.ingestion import team_calendar as ing
from fbi.providers.base import RawResponse
from tests.integration.calendar_helpers import (
    T0,
    fixture,
    followed_season,
    known_competition,
    listed,
    next_provider_fixture,
    payload,
    read,
    team,
)
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

# ── what is written ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_calendar_has_its_tables_its_views_and_refuses_nonsense(db: psycopg.Connection, seed: Seed) -> None:
    kinds: dict[str, str] = dict(db.execute(
        "SELECT relname, relkind FROM pg_class WHERE relnamespace = 'core'::regnamespace AND relname IN "
        "('calendar_matches', 'calendar_fetches', 'calendar_matches_latest', 'team_calendar')").fetchall())
    assert kinds == {"calendar_matches": "r", "calendar_fetches": "r", "calendar_matches_latest": "v", "team_calendar": "v"}
    h = payload(db, seed)
    columns = ("provider_fixture_id, observed_at, kickoff_at, status_short, status_group, provider_league_id, league_name, season, "
               "home_provider_team_id, home_name, away_provider_team_id, away_name, payload_hash, normalizer_version")

    def insert(**override: Any) -> None:
        values: dict[str, Any] = {"f": 1, "at": T0, "ko": T0, "ss": "NS", "sg": "scheduled", "pl": 1, "ln": "L", "se": 2026, "h": 10,
                                  "hn": "H", "a": 20, "an": "A", "ph": h, "v": "t"}
        values.update(override)
        with db.transaction():
            db.execute(f"INSERT INTO core.calendar_matches ({columns}) VALUES (%(f)s, %(at)s, %(ko)s, %(ss)s, %(sg)s, %(pl)s, %(ln)s, "
                       "%(se)s, %(h)s, %(hn)s, %(a)s, %(an)s, %(ph)s, %(v)s)", values)

    insert()
    for bad in ({"sg": "unknown"}, {"a": 10}, {"h": 0}, {"hn": "  "}, {"ph": "no such payload"}, {"f": 0}):
        with pytest.raises(psycopg.errors.Error):
            insert(f=bad.get("f", 2), **{k: v for k, v in bad.items() if k != "f"})
    comment = scalar(db.execute("SELECT obj_description('core.calendar_matches'::regclass)"))
    assert "Never a model input and never a pick" in comment


def test_only_the_matches_of_competitions_not_followed_are_written_and_every_reading_is_logged(db: psycopg.Connection, seed: Seed) -> None:
    season, _ = followed_season(db)
    a, pa = team(db, "Alpha FC")
    b, pb = team(db, "Beta FC")
    _, league_match = fixture(db, season, a, b, T0 + timedelta(days=3))
    cup, europe = next_provider_fixture(), next_provider_fixture()
    added = read(db, seed, pa, [
        listed(league_match, home=pa, away=pb, kickoff=T0 + timedelta(days=3), league=1, league_name="League"),
        listed(cup, home=pa, away=555, kickoff=T0 - timedelta(days=3), short="FT", goals=(2, 1), home_name="Alpha FC", away_name="Minnow"),
        listed(europe, home=777, away=pa, kickoff=T0 + timedelta(days=5), league=2, league_name="Champions League",
               home_name="Giants", away_name="Alpha FC"),
    ])
    assert added == 2, "the match PrediGol follows is not written twice"
    rows = db.execute("SELECT provider_fixture_id, status_group, league_name, home_name, away_name, goals_home, goals_away, "
                      "normalizer_version FROM core.calendar_matches ORDER BY kickoff_at").fetchall()
    assert rows == [(cup, "finished", "Copa del Rey", "Alpha FC", "Minnow", 2, 1, ing.NORMALIZER_VERSION),
                    (europe, "scheduled", "Champions League", "Giants", "Alpha FC", None, None, ing.NORMALIZER_VERSION)]
    assert db.execute("SELECT provider_team_id, season, fetched_at, matches, followed, rows_added FROM core.calendar_fetches").fetchall() \
        == [(pa, 2026, T0, 3, 1, 2)]
    # nothing is created for a competition that is not followed: its rival is a name in the calendar row and no more
    assert scalar(db.execute("SELECT count(*) FROM core.teams WHERE name IN ('Minnow', 'Giants')")) == 0
    assert scalar(db.execute("SELECT count(*) FROM core.competitions WHERE name IN ('Copa del Rey', 'Champions League')")) == 0
    assert scalar(db.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id IN (%s, %s)", (cup, europe))) == 0


def test_a_reading_that_says_nothing_new_adds_no_match_row_but_is_logged(db: psycopg.Connection, seed: Seed) -> None:
    _, pa = team(db, "Alpha FC")
    cup = next_provider_fixture()
    entry = listed(cup, home=pa, away=555, kickoff=T0 + timedelta(days=3))
    assert read(db, seed, pa, [entry], T0) == 1
    assert read(db, seed, pa, [entry], T0 + timedelta(days=1)) == 0
    assert read(db, seed, pa, [], T0 + timedelta(days=2)) == 0, "an empty answer erases nothing"
    assert scalar(db.execute("SELECT count(*) FROM core.calendar_matches")) == 1
    assert db.execute("SELECT fetched_at, matches, rows_added FROM core.calendar_fetches ORDER BY fetched_at").fetchall() \
        == [(T0, 1, 1), (T0 + timedelta(days=1), 1, 0), (T0 + timedelta(days=2), 0, 0)], "asked and empty is not 'never asked'"
    assert read(db, seed, pa, [entry], T0 + timedelta(days=1)) == 0, "the same reading twice is the same reading"
    assert scalar(db.execute("SELECT count(*) FROM core.calendar_fetches")) == 3


def test_a_match_that_moves_or_is_played_is_a_new_row_and_the_first_sighting_is_kept(db: psycopg.Connection, seed: Seed) -> None:
    _, pa = team(db, "Alpha FC")
    cup = next_provider_fixture()
    first = T0 + timedelta(days=6)
    assert read(db, seed, pa, [listed(cup, home=pa, away=555, kickoff=first)], T0) == 1
    moved = first + timedelta(days=1)
    assert read(db, seed, pa, [listed(cup, home=pa, away=555, kickoff=moved)], T0 + timedelta(days=1)) == 1
    assert read(db, seed, pa, [listed(cup, home=pa, away=555, kickoff=moved, short="FT", goals=(0, 3))], T0 + timedelta(days=9)) == 1
    states = db.execute("SELECT observed_at, kickoff_at, status_group, goals_home, goals_away FROM core.calendar_matches "
                        "WHERE provider_fixture_id = %s ORDER BY observed_at", (cup,)).fetchall()
    assert states == [(T0, first, "scheduled", None, None), (T0 + timedelta(days=1), moved, "scheduled", None, None),
                      (T0 + timedelta(days=9), moved, "finished", 0, 3)]
    latest = db.execute("SELECT observed_at, first_seen_at, kickoff_at, status_group FROM core.calendar_matches_latest "
                        "WHERE provider_fixture_id = %s", (cup,)).fetchall()
    assert latest == [(T0 + timedelta(days=9), T0, moved, "finished")]
    assert read(db, seed, pa, [listed(cup, home=pa, away=555, kickoff=first)], T0 - timedelta(days=1)) == 0, \
        "a reading older than the newest row cannot undo it"


def test_the_view_shows_each_match_once_from_the_teams_side(db: psycopg.Connection, seed: Seed) -> None:
    season, _ = followed_season(db)
    cup_league = known_competition(db, "Known Cup")
    a, pa = team(db, "Alpha FC")
    b, pb = team(db, "Beta FC")
    _, league_match = fixture(db, season, a, b, T0 - timedelta(days=7), status="finished", goals=(3, 1))
    away_match_id, away_match = fixture(db, season, b, a, T0 + timedelta(days=4))
    cup, cup_unknown = next_provider_fixture(), next_provider_fixture()
    read(db, seed, pa, [
        listed(league_match, home=pa, away=pb, kickoff=T0 - timedelta(days=7)),
        listed(cup, home=pa, away=555, kickoff=T0 - timedelta(days=3), short="FT", goals=(2, 0), league=cup_league, league_name="Known Cup",
               home_name="Alpha FC", away_name="Minnow"),
        listed(cup_unknown, home=999, away=pa, kickoff=T0 + timedelta(days=1), league=8_888, league_name="Unknown Trophy",
               home_name="Stranger", away_name="Alpha FC"),
    ])
    rows = db.execute("SELECT source, provider_fixture_id, is_home, opponent_name, opponent_provider_team_id, competition_name, "
                      "competition_type, status_group, goals_for, goals_against FROM core.team_calendar WHERE team_id = %s "
                      "ORDER BY kickoff_at", (a,)).fetchall()
    assert rows == [("followed", league_match, True, "Beta FC", pb, "League", "domestic_league", "finished", 3, 1),
                    ("calendar", cup, True, "Minnow", 555, "Known Cup", "domestic_cup", "finished", 2, 0),
                    ("calendar", cup_unknown, False, "Stranger", 999, "Unknown Trophy", None, "scheduled", None, None),
                    ("followed", away_match, False, "Beta FC", pb, "League", "domestic_league", "scheduled", None, None)]
    assert away_match_id > 0
    beta = db.execute("SELECT source, is_home, goals_for, goals_against FROM core.team_calendar WHERE team_id = %s ORDER BY kickoff_at",
                      (b,)).fetchall()
    assert beta == [("followed", False, 1, 3), ("followed", True, None, None)], "the other side of the same match, with the score turned"


def test_a_match_that_becomes_followed_later_is_not_shown_twice(db: psycopg.Connection, seed: Seed) -> None:
    season, _ = followed_season(db)
    a, pa = team(db, "Alpha FC")
    b, pb = team(db, "Beta FC")
    provider_fixture = next_provider_fixture()
    read(db, seed, pa, [listed(provider_fixture, home=pa, away=pb, kickoff=T0 + timedelta(days=2))])
    assert scalar(db.execute("SELECT count(*) FROM core.team_calendar WHERE team_id = %s", (a,))) == 1
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
               "VALUES (%s, %s, %s, %s, %s)", (provider_fixture, season, a, b, T0 + timedelta(days=2)))
    assert db.execute("SELECT source FROM core.team_calendar WHERE team_id = %s", (a,)).fetchall() == [("followed",)]


# ── what a reader may know at a moment ───────────────────────────────────────────────────────────────────────────────────


def test_the_reader_knows_only_what_was_known_at_the_moment(db: psycopg.Connection, seed: Seed) -> None:
    season, _ = followed_season(db)
    a, pa = team(db, "Alpha FC")
    b, _pb = team(db, "Beta FC")
    kickoff = T0 + timedelta(days=2)
    moment = T0
    # a followed match played last week, recorded in a backfill AFTER the moment: a fact all the same
    _, backfilled = fixture(db, season, a, b, T0 - timedelta(days=7), status="finished", created=T0 + timedelta(days=100), goals=(1, 1))
    # a followed match to come, recorded before the moment / after it
    _, known_future = fixture(db, season, b, a, T0 + timedelta(days=5), created=T0 - timedelta(days=2))
    _, announced_later = fixture(db, season, b, a, T0 + timedelta(days=6), created=T0 + timedelta(hours=1))
    cup, cup_late, cup_moved = next_provider_fixture(), next_provider_fixture(), next_provider_fixture()
    # a cup tie played three days ago, read by us only after the moment
    read(db, seed, pa, [listed(cup, home=pa, away=555, kickoff=T0 - timedelta(days=3), short="FT", goals=(2, 0))], T0 + timedelta(days=4))
    # a tie to come that the provider announced after the moment
    read(db, seed, pa, [listed(cup_late, home=pa, away=556, kickoff=T0 + timedelta(days=4))], T0 + timedelta(days=1))
    # a tie that was announced for the 5th and then moved to the 9th - and read in between
    read(db, seed, pa, [listed(cup_moved, home=pa, away=557, kickoff=T0 + timedelta(days=5, hours=3))], T0 - timedelta(days=1))
    read(db, seed, pa, [listed(cup_moved, home=pa, away=557, kickoff=T0 + timedelta(days=9))], T0 + timedelta(days=2))

    now = tc.load(db, team_id=a, at=moment, kickoff=kickoff)
    seen = {m.provider_fixture_id: m for m in now.matches}
    assert set(seen) == {backfilled, known_future, cup, cup_moved}, "a match announced later did not exist yet; a played one always did"
    assert seen[cup].kickoff_at == T0 - timedelta(days=3) and seen[cup].played and seen[cup].result() == "2-0"
    assert seen[cup_moved].kickoff_at == T0 + timedelta(days=5, hours=3), "the schedule as it stood: the move came later"
    assert announced_later not in seen and cup_late not in seen
    assert now.rest_days(kickoff) == 5.0, "the cup tie of three days ago, not the league match of a week ago"
    assert now.fetched_at == T0 - timedelta(days=1), "the newest reading at or before the moment (the others came later)"

    later = tc.load(db, team_id=a, at=T0 + timedelta(days=3), kickoff=kickoff)
    assert {m.provider_fixture_id for m in later.matches} >= {announced_later, cup_late, cup_moved}
    assert {m.provider_fixture_id: m.kickoff_at for m in later.matches}[cup_moved] == T0 + timedelta(days=9)
    assert later.fetched_at == T0 + timedelta(days=2)


def test_the_reader_tells_the_two_sources_apart_and_a_team_without_matches_is_empty(db: psycopg.Connection, seed: Seed) -> None:
    season, _ = followed_season(db)
    a, pa = team(db, "Alpha FC")
    b, _pb = team(db, "Beta FC")
    c, _pc = team(db, "Gamma FC")
    fixture(db, season, a, b, T0 - timedelta(days=4), status="finished", goals=(0, 2))
    read(db, seed, pa, [listed(next_provider_fixture(), home=pa, away=555, kickoff=T0 - timedelta(days=2), short="FT", goals=(1, 0))])
    cal = tc.load(db, team_id=a, at=T0, kickoff=T0 + timedelta(days=1))
    assert [(m.followed, m.competition, m.result()) for m in cal.matches] == [(True, "League", "0-2"), (False, "Copa del Rey", "1-0")]
    assert cal.state(T0 + timedelta(days=1)).complete
    empty = tc.load(db, team_id=c, at=T0, kickoff=T0 + timedelta(days=1))
    assert empty.matches == () and empty.fetched_at is None
    assert empty.state(T0 + timedelta(days=1)).reason == "never_fetched"
    nobody = tc.load(db, team_id=2_000_000_000, at=T0, kickoff=T0)
    assert nobody.matches == () and nobody.fetched_at is None


def test_a_list_is_as_fresh_as_its_last_reading_at_the_moment(db: psycopg.Connection, seed: Seed) -> None:
    _, pa = team(db, "Alpha FC")
    a = int(scalar(db.execute("SELECT id FROM core.teams WHERE provider_team_id = %s", (pa,))))
    read(db, seed, pa, [], T0 - timedelta(days=6))
    read(db, seed, pa, [], T0 - timedelta(days=1))
    kickoff = T0 + timedelta(days=1)
    assert tc.load(db, team_id=a, at=T0, kickoff=kickoff).state(kickoff).complete
    fresh = tc.load(db, team_id=a, at=T0 - timedelta(days=3), kickoff=kickoff).state(kickoff)
    assert fresh.complete and fresh.age_hours == 72.0, "three days after the first reading, before the second"
    stale = tc.load(db, team_id=a, at=T0 - timedelta(days=1, hours=12), kickoff=kickoff).state(kickoff)
    assert stale.reason == "stale" and stale.age_hours == 108.0, "four and a half days after it, and the second reading not yet made"
    assert tc.load(db, team_id=a, at=T0 - timedelta(days=7), kickoff=kickoff).state(kickoff).reason == "never_fetched"


# ── who is asked about, and how often ────────────────────────────────────────────────────────────────────────────────────


def test_who_is_asked_about_and_how_often(db: psycopg.Connection) -> None:
    season, _ = followed_season(db)
    other, _ = followed_season(db, tracked=False)
    finished, _ = followed_season(db, current=False)
    teams = {name: team(db, name) for name in ("near", "soon", "week", "far", "untracked", "past season", "twice", "rival")}
    rival = teams["rival"][0]
    for name, days in (("near", 1.0), ("soon", 3.0), ("week", 6.5), ("far", 9.0)):
        fixture(db, season, teams[name][0], rival, T0 + timedelta(days=days))
    fixture(db, other, teams["untracked"][0], rival, T0 + timedelta(days=1))
    fixture(db, finished, teams["past season"][0], rival, T0 + timedelta(days=1))
    fixture(db, season, teams["twice"][0], rival, T0 + timedelta(days=5))
    fixture(db, season, teams["twice"][0], rival, T0 + timedelta(days=1, hours=2))
    fixture(db, season, rival, teams["near"][0], T0 - timedelta(days=1), status="finished")
    by_team = {t.params["team"]: t for t in ing.targets(db, T0)}
    assert set(by_team) == {teams[n][1] for n in ("near", "soon", "week", "twice", "rival")}, \
        "a followed match within seven days, in a followed and current season - nobody else"
    assert by_team[teams["near"][1]].every == ing.EVERY_NEAR
    assert by_team[teams["twice"][1]].every == ing.EVERY_NEAR, "the soonest match decides"
    assert by_team[teams["soon"][1]].every == ing.EVERY_SOON
    assert by_team[teams["week"][1]].every == ing.EVERY_WEEK
    assert by_team[teams["near"][1]].key == f"team:{teams['near'][1]}:2026" and by_team[teams["near"][1]].params["season"] == 2026
    order = [t.params["team"] for t in ing.targets(db, T0)]
    assert order.index(teams["near"][1]) < order.index(teams["soon"][1]) < order.index(teams["week"][1]), "the soonest to play first"
    assert [t.key for t in ing.targets(db, T0 + timedelta(days=20))] == []


def test_the_team_fixtures_feed_is_registered_with_its_limits() -> None:
    [feed] = [f for f in ref.FEEDS if f.name == "team_fixtures"]
    assert (feed.endpoint, feed.max_per_run, feed.batch, feed.paged) == ("/fixtures", 60, 1, False)
    assert feed.apply is ref.apply_team_fixtures and feed.targets is ref.team_fixture_targets
    names = [f.name for f in ref.FEEDS]
    assert names.index("team_fixtures") < names.index("team_statistics"), "time-sensitive: before the aggregates"


# ── the feed, run ────────────────────────────────────────────────────────────────────────────────────────────────────────


class CalendarProvider:
    """Answers each team with one cup tie of its own (the fixture id is made from the team's)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        self.calls.append((endpoint, params))
        h = f"tc9{len(self.calls)}"
        team = int(params["team"])
        entries = [listed(9_700_000 + team, home=team, away=555, kickoff=T0 + timedelta(days=2))]
        return RawResponse(endpoint=endpoint, params=params, fetched_at=T0, http_status=200, results_count=len(entries),
                           payload_hash=h, file_path=h, bytes_written=1, body={"response": entries})


@pytest.fixture()
def committed(db: psycopg.Connection) -> Any:
    """A run commits (it is a worker job): what it wrote is removed after the test."""
    yield db
    db.rollback()
    db.execute("DELETE FROM core.calendar_fetches WHERE payload_hash LIKE 'tc%%'")
    db.execute("DELETE FROM core.calendar_matches WHERE payload_hash LIKE 'tc%%'")
    db.execute("DELETE FROM core.reference_checks WHERE feed = 'team_fixtures'")
    db.execute("DELETE FROM raw.ingestion_payloads WHERE hash LIKE 'tc%%'")
    db.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'reference_refresh'")
    db.commit()


@pytest.mark.asyncio
async def test_a_run_asks_for_the_team_and_the_season_and_records_the_question(
        committed: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db = committed
    import fbi.ingestion.backfill as backfill
    import fbi.providers.quota as quota

    class Usage:
        remaining = 1000

    monkeypatch.setattr(backfill, "live_reserve", lambda *a, **k: 0)
    monkeypatch.setattr(quota, "read_usage", lambda *a, **k: Usage())

    def two(conn: psycopg.Connection, at: datetime) -> list[ref.Target]:
        return [ref.Target("team:91999:2026", {"team": 91_999, "season": 2026}, ing.EVERY_NEAR, {}),
                ref.Target("team:91998:2025", {"team": 91_998, "season": 2025}, ing.EVERY_WEEK, {})]

    feed = ref.Feed("team_fixtures", "/fixtures", two, ref.apply_team_fixtures, max_per_run=60)
    provider = CalendarProvider()
    report = await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0)
    assert provider.calls == [("/fixtures", {"team": 91_999, "season": 2026}), ("/fixtures", {"team": 91_998, "season": 2025})]
    assert report.asked == {"team_fixtures": 2} and report.rows == {"team_fixtures": 2}
    checks = db.execute("SELECT target, results, rows_added, error FROM core.reference_checks WHERE feed = 'team_fixtures' "
                        "ORDER BY target").fetchall()
    assert checks == [("team:91998:2025", 1, 1, None), ("team:91999:2026", 1, 1, None)]
    assert scalar(db.execute("SELECT count(*) FROM core.calendar_fetches")) == 2
    again = await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0 + timedelta(hours=2))
    assert again.deferred_reason == "nothing due" and len(provider.calls) == 2, "fresh for the hours its freshness allows"
    later = await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0 + timedelta(hours=21))
    assert [c[1]["team"] for c in provider.calls[2:]] == [91_999], "the team playing soon is asked again after a day, the other is not"
    assert later.asked == {"team_fixtures": 1}
