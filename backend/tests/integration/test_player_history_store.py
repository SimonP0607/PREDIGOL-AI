"""A player's clubs and national team in the database (plan F3): the streaks come from the transfers, the squad sheets of the matches and the
squad lists, the caps from the matches of senior national sides, and a second pass writes nothing."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.people import caps as cp
from fbi.people import player_history as ph
from fbi.people import spells as sp
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

T0 = datetime(2026, 3, 1, 15, 0, tzinfo=UTC)
_team = itertools.count(70_000)
_fixture = itertools.count(7_000_000)
_player = itertools.count(8_000_000)
_league = itertools.count(7_000)


def d(n: int) -> date:
    return (T0 + timedelta(days=n)).date()


@dataclass
class World:
    db: psycopg.Connection
    seed: Seed
    club_season: int
    national_season: int

    def team(self, name: str, national: bool | None) -> int:
        """A team of ours; returns its id (its provider id is ``provider(id)``)."""
        return int(scalar(self.db.execute("INSERT INTO core.teams (provider_team_id, name, is_national) VALUES (%s, %s, %s) RETURNING id",
                                          (next(_team), name, national))))

    def provider(self, team_id: int) -> int:
        return int(scalar(self.db.execute("SELECT provider_team_id FROM core.teams WHERE id = %s", (team_id,))))

    def player(self) -> int:
        return next(_player)

    def fixture(self, home: int, away: int, day: int, *, status: str = "finished", national: bool = False,
                at: datetime | None = None) -> int:
        """A match ``day`` days after T0 (at 15:00 UTC unless ``at`` says when)."""
        return int(scalar(self.db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_group) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (next(_fixture), self.national_season if national else self.club_season, home, away, at or T0 + timedelta(days=day), status))))

    def lineup(self, fixture: int, side: str, players: list[tuple[int, bool]]) -> None:
        """The squad sheet of one side: (player, starter)."""
        self.db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                        "VALUES (%s, %s, 'api-football', %s, now()) ON CONFLICT DO NOTHING", (fixture, side, self.seed.payload_hash))
        for player, starter in players:
            self.db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, is_starter) "
                            "VALUES (%s, %s, 'api-football', %s, %s)", (fixture, side, player, starter))

    def stats(self, fixture: int, side: str, rows: list[tuple[int, int | None, bool]]) -> None:
        """The statistics of one side: (player, minutes, substitute)."""
        for player, minutes, substitute in rows:
            self.db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, "
                            "is_substitute, payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, %s, %s, now())",
                            (fixture, player, side, minutes, substitute, self.seed.payload_hash))

    def transfer(self, player: int, day: int, team_in: int | None, team_out: int | None, kind: str = "Free",
                 names: tuple[str, str] = ("In FC", "Out FC"), *, listed: int = 0) -> None:
        """A transfer the provider lists, by the provider's ids of the clubs; ``listed`` is the day (after T0) the list was read."""
        ordinal = scalar(self.db.execute("SELECT count(*) FROM core.player_transfers WHERE provider_player_id = %s", (player,)))
        self.db.execute("INSERT INTO core.player_transfers (provider_player_id, observed_at, ordinal, transfer_date, type, team_in_id, "
                        "team_in_name, team_out_id, team_out_name, payload_hash, normalizer_version) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'test')",
                        (player, T0 + timedelta(days=listed), ordinal, d(day), kind, team_in, names[0], team_out, names[1],
                         self.seed.payload_hash))

    def squad(self, team_id: int, player: int, first: int, last: int) -> None:
        self.db.execute("INSERT INTO core.squad_members (team_id, provider_player_id, first_seen_at, last_seen_at, payload_hash) "
                        "VALUES (%s, %s, %s, %s, %s)", (team_id, player, T0 + timedelta(days=first), T0 + timedelta(days=last),
                                                        self.seed.payload_hash))

    def one(self, sql: str, *params: object) -> Any:
        return scalar(self.db.execute(sql, params))

    def spells(self, player: int) -> list[tuple[Any, ...]]:
        return self.db.execute("SELECT ordinal, provider_team_id, team_name, valid_from, valid_to, source, matches, last_evidence, via "
                               "FROM core.player_spells WHERE provider_player_id = %s ORDER BY ordinal", (player,)).fetchall()

    def caps(self, fixture: int) -> dict[int, tuple[Any, ...]]:
        rows = self.db.execute("SELECT provider_player_id, team_id, is_starter, appeared, minutes FROM core.player_national_caps "
                               "WHERE fixture_id = %s", (fixture,)).fetchall()
        return {int(r[0]): tuple(r[1:]) for r in rows}


@pytest.fixture()
def world(db: psycopg.Connection, seed: Seed) -> World:
    # the ids of the matches and of the teams come from two sequences that can hold the same number at once: push the matches' far
    # away, so that nothing passes by reading a match id where a team id is meant (sequences are not rolled back: ids only grow)
    db.execute("SELECT setval(pg_get_serial_sequence('core.fixtures', 'id'), nextval(pg_get_serial_sequence('core.fixtures', 'id')) + 4000000)")
    comp = scalar(db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                             "VALUES (%s, 'League', 'league', 'club', 'domestic_league') RETURNING id", (next(_league),)))
    club_season = scalar(db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,)))
    intl = scalar(db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                             "VALUES (%s, 'Nations', 'cup', 'national_team', 'international') RETURNING id", (next(_league),)))
    national_season = scalar(db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (intl,)))
    return World(db, seed, int(club_season), int(national_season))


# ── the streaks ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_streaks_come_from_transfers_matches_and_squad_lists_and_a_second_pass_writes_nothing(world: World) -> None:
    a, b, c = world.team("Alpha FC", False), world.team("Beta FC", False), world.team("Gamma FC", False)
    rival = world.team("Rival FC", False)
    p, q, r = world.player(), world.player(), world.player()
    # p plays for Alpha three times, is transferred to Beta (day 40), plays for Beta twice; Gamma's squad list also carries him later
    for day in (1, 10, 20):
        world.lineup(world.fixture(a, rival, day), "home", [(p, True)])
    for day in (45, 50):
        world.lineup(world.fixture(rival, b, day), "away", [(p, False)])
    world.transfer(p, 40, world.provider(b), world.provider(a), "€ 5M", names=("Beta FC", "Alpha FC"))
    world.squad(c, p, 60, 70)
    # q is only in a squad list
    world.squad(c, q, 5, 30)
    # r has a transfer only, from a club that is not one of ours
    world.transfer(r, 12, world.provider(a), 123456, "Loan", names=("Alpha Football Club", "Far Away United"))

    dry = ph.build(world.db, players=[p, q, r])
    assert not dry.applied and dry.players == 3 and dry.spells == 2 + 1 + 2 and dry.players_changed == 3
    assert world.spells(p) == [], "a dry run writes nothing"

    first = ph.build(world.db, apply=True, players=[p, q, r])
    assert first.applied and first.changed and first.spells_written == 5 and first.spells_deleted == 0 and first.phantoms == 0
    assert world.spells(p) == [
        (0, world.provider(a), "Alpha FC", d(1), d(40), "lineup", 3, d(20), None),
        (1, world.provider(b), "Beta FC", d(40), None, "transfer", 2, d(50), "€ 5M"),
    ], "the squad list of another club does not take him from the one he plays for"
    assert world.spells(q) == [(0, world.provider(c), "Gamma FC", d(5), None, "squad", 0, d(30), None)]
    assert world.spells(r) == [
        (0, 123456, "Far Away United", None, d(12), "transfer", 0, d(12), None),
        (1, world.provider(a), "Alpha FC", d(12), None, "transfer", 0, d(12), "Loan"),
    ], "a club we hold is called as we call it, one we do not keeps the name the transfer gave it, and the start nobody gave stays unknown"
    assert [(s.club, s.valid_from, s.valid_to, s.source, s.matches, s.last_evidence, s.via) for s in ph.spells_of(world.db, [p])[p]] == [
        (world.provider(a), d(1), d(40), "lineup", 3, d(20), None), (world.provider(b), d(40), None, "transfer", 2, d(50), "€ 5M")]

    second = ph.build(world.db, apply=True, players=[p, q, r])
    assert not second.changed and second.players_changed == 0, second.as_dict()


def test_a_player_who_goes_a_b_a_has_three_streaks_in_the_table_and_is_read_back_as_of_a_day(world: World) -> None:
    a, b, rival = world.team("Alpha FC", False), world.team("Beta FC", False), world.team("Rival FC", False)
    p = world.player()
    for day, home, away, side in ((1, a, rival, "home"), (30, b, rival, "home"), (60, rival, a, "away")):
        world.lineup(world.fixture(home, away, day), side, [(p, True)])
    ph.build(world.db, apply=True, players=[p])
    assert [(row[1], row[3], row[4]) for row in world.spells(p)] == [
        (world.provider(a), d(1), d(30)), (world.provider(b), d(30), d(60)), (world.provider(a), d(60), None)]
    built = ph.spells_of(world.db, [p])[p]
    assert [(s.club, sp.club_at(built, d(n)) is not None) for s, n in zip(built, (1, 30, 60), strict=True)] == [
        (world.provider(a), True), (world.provider(b), True), (world.provider(a), True)]
    got = sp.club_at(built, d(45))
    assert got is not None and got.club == world.provider(b)
    assert sp.club_at(built, d(0)) is None, "nothing says where he was before his first match"
    assert ph.spell_names(world.db, [p]) == {world.provider(a): "Alpha FC", world.provider(b): "Beta FC"}


def test_national_teams_unclassified_sides_and_matches_not_played_are_no_evidence_of_a_club(world: World) -> None:
    club, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    nation, mystery = world.team("Spain", True), world.team("Mystery FC", None)
    p = world.player()
    world.lineup(world.fixture(club, rival, 1), "home", [(p, True)])
    world.lineup(world.fixture(nation, rival, 5, national=True), "home", [(p, True)])          # a national team
    world.lineup(world.fixture(mystery, rival, 6), "home", [(p, True)])                         # nobody has classified it
    world.lineup(world.fixture(rival, club, 7, status="scheduled"), "away", [(p, True)])        # not played yet
    world.lineup(world.fixture(rival, club, 8, status="cancelled"), "away", [(p, True)])        # never played
    world.lineup(world.fixture(rival, club, 9, status="live"), "away", [(p, True)])             # being played
    ph.build(world.db, apply=True, players=[p])
    assert [(row[1], row[3], row[4], row[6]) for row in world.spells(p)] == [(world.provider(club), d(1), None, 2)]
    # a transfer to a national team (the provider lists none, but a team we classify so is not a club either) is ignored too
    q = world.player()
    world.transfer(q, 3, world.provider(nation), world.provider(club))
    world.squad(nation, q, 5, 9)       # nor is the squad list of a national team...
    world.squad(mystery, q, 5, 9)      # ...or of a side nobody has classified
    ph.build(world.db, apply=True, players=[q])
    assert [(row[1], row[3], row[4]) for row in world.spells(q)] == [(world.provider(club), None, d(3))]


def test_the_classification_of_predigol_wins_over_the_providers_flag(world: World) -> None:
    club = world.team("Alpha FC", True)  # the provider says national
    p = world.player()
    world.lineup(world.fixture(club, world.team("Rival FC", False), 1), "home", [(p, True)])
    ph.build(world.db, apply=True, players=[p])
    assert world.spells(p) == [], "a national team is not a club"
    world.db.execute("INSERT INTO core.team_kind (team_id, is_national, basis, competitive_club_matches, national_matches, "
                     "club_friendly_matches, rule_version, refreshed_at) VALUES (%s, false, 'test', 5, 0, 0, 'test', now())", (club,))
    ph.build(world.db, apply=True, players=[p])
    assert [(row[1], row[6]) for row in world.spells(p)] == [(world.provider(club), 1)], "PrediGol's rule says it is a club"


def test_the_statistics_of_a_match_count_too_and_a_match_is_counted_once(world: World) -> None:
    a, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    p, q = world.player(), world.player()
    both = world.fixture(a, rival, 2)
    world.lineup(both, "home", [(p, True)])
    world.stats(both, "home", [(p, 90, False), (q, None, True)])        # q is only in the statistics (an unused substitute)
    ph.build(world.db, apply=True, players=[p, q])
    assert [(row[6]) for row in world.spells(p)] == [1], "the squad sheet and the statistics carry the same match once"
    assert [(row[6]) for row in world.spells(q)] == [1], "a man only the statistics name is in the matchday squad"


def test_the_statistics_of_a_match_not_played_are_no_evidence_but_those_of_one_being_played_are(world: World) -> None:
    a, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    p, q = world.player(), world.player()
    world.stats(world.fixture(a, rival, 2, status="cancelled"), "home", [(p, 0, False)])
    world.stats(world.fixture(a, rival, 3, status="scheduled"), "home", [(p, 0, False)])
    world.stats(world.fixture(a, rival, 4, status="live"), "home", [(q, 10, False)])
    ph.build(world.db, apply=True, players=[p, q])
    assert world.spells(p) == []
    assert [(row[1], row[6]) for row in world.spells(q)] == [(world.provider(a), 1)]


def test_a_changed_fact_rewrites_only_that_player_and_another_version_rewrites_all(world: World) -> None:
    a, b, rival = world.team("Alpha FC", False), world.team("Beta FC", False), world.team("Rival FC", False)
    p, q = world.player(), world.player()
    world.lineup(world.fixture(a, rival, 1), "home", [(p, True), (q, True)])
    ph.build(world.db, apply=True, players=[p, q])
    world.transfer(p, 5, world.provider(b), world.provider(a))
    report = ph.build(world.db, apply=True, players=[p, q])
    assert (report.players_changed, report.spells_deleted, report.spells_written) == (1, 1, 2)
    assert [(row[1], row[3], row[4]) for row in world.spells(p)] == [(world.provider(a), d(1), d(5)), (world.provider(b), d(5), None)]
    world.db.execute("UPDATE core.player_spells SET version = 'spells-v0' WHERE provider_player_id = ANY(%s)", ([p, q],))
    again = ph.build(world.db, apply=True, players=[p, q])
    assert again.players_changed == 2, "rows of another version of the rules are rewritten even when the streaks are the same"
    assert {row[0] for row in world.db.execute("SELECT version FROM core.player_spells WHERE provider_player_id = ANY(%s)", ([p, q],))} == {sp.VERSION}


def test_a_player_whose_facts_are_gone_loses_his_streaks(world: World) -> None:
    a, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    p = world.player()
    fid = world.fixture(a, rival, 1)
    world.lineup(fid, "home", [(p, True)])
    ph.build(world.db, apply=True, players=[p])
    assert len(world.spells(p)) == 1
    world.db.execute("UPDATE core.fixtures SET status_group = 'cancelled' WHERE id = %s", (fid,))
    report = ph.build(world.db, apply=True, players=[p])
    assert (report.spells_deleted, report.spells_written) == (1, 0) and world.spells(p) == []


def test_the_scheduled_pass_looks_at_what_changed_lately_and_the_sweep_at_everyone(world: World) -> None:
    a, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    old, recent, traded, listed = world.player(), world.player(), world.player(), world.player()
    forgotten = {"lineup": world.player(), "list": world.player(), "statistics": world.player(), "squad": world.player()}
    world.lineup(world.fixture(a, rival, -400), "home", [(old, True)])
    world.lineup(world.fixture(a, rival, 0), "home", [(recent, True)])
    world.transfer(traded, -2, world.provider(a), None)               # read at T0 (observed_at), dated two days before
    world.squad(a, listed, 0, 0)
    # what only the sweep knows: each source of facts has a man whose facts are all old
    world.lineup(world.fixture(a, rival, -401), "home", [(forgotten["lineup"], True)])
    world.transfer(forgotten["list"], -500, world.provider(a), None, listed=-300)          # a transfer list read long ago
    world.stats(world.fixture(a, rival, -402), "home", [(forgotten["statistics"], 90, False)])
    world.squad(a, forgotten["squad"], -400, -390)
    now = T0 + timedelta(days=1)
    assert {old, recent, traded, listed} >= set(ph.recent_players(world.db, now=now)) >= {recent, traded, listed}
    assert old not in ph.recent_players(world.db, now=now)
    assert not (set(forgotten.values()) & set(ph.recent_players(world.db, now=now)))
    assert old not in ph.recent_players(world.db, now=T0 + timedelta(days=30)), "and a window passes"
    assert {old, *forgotten.values()} <= set(ph.all_players(world.db))
    scheduled = ph.build(world.db, apply=True, now=now)
    assert scheduled.mode == ph.SCHEDULED and world.spells(old) == [] and world.spells(recent) != []
    assert all(world.spells(x) == [] for x in forgotten.values())
    sweep = ph.build(world.db, apply=True, sweep=True, now=now)
    assert sweep.mode == ph.SWEEP and world.spells(old) != []
    assert all(world.spells(x) != [] for x in forgotten.values()), "the sweep goes through everyone, whatever the fact that names him"


def test_a_pass_that_finds_the_lock_taken_gives_way(world: World, migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (ph.LOCK_KEY,))
        report = ph.build(world.db, apply=True, players=[1])
        looked = ph.build(world.db, apply=False, players=[1])
        other.rollback()
    assert report.skipped_locked and not report.applied and not report.changed
    assert not looked.skipped_locked and not looked.applied, "looking takes no lock, so it goes on while another pass writes"


# ── the caps ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_senior_national_match_makes_a_cap_for_every_man_of_the_squad_sheet(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p1, p2, p3, p4, p5, p6, p7 = (world.player() for _ in range(7))
    fid = world.fixture(spain, italy, 3, national=True)
    world.lineup(fid, "home", [(p1, True), (p2, True), (p3, False), (p4, False), (p7, False)])
    world.lineup(fid, "away", [(p5, True), (p6, False)])
    world.stats(fid, "home", [(p1, 90, False), (p2, 60, False), (p3, 30, True), (p4, None, True), (p7, 0, True)])   # p4, p7 never got on
    dry = ph.build(world.db, sweep=True, now=T0 + timedelta(days=10))
    assert dry.caps_written >= 7 and world.caps(fid) == {}, "a dry run says what it would write and writes nothing"
    report = ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert report.caps_written >= 7 and report.caps == report.caps_written and report.fixtures >= 1
    assert world.caps(fid) == {
        p1: (spain, True, True, 90), p2: (spain, True, True, 60), p3: (spain, False, True, 30), p4: (spain, False, False, None),
        p7: (spain, False, False, None),   # on the sheet with a line of statistics that says 0 minutes: no minutes either
        p5: (italy, True, True, None),     # a starter played, whatever the statistics say - and they have not arrived for Italy
        p6: (italy, False, None, None),    # a substitute: nobody can say yet
    }
    assert report.caps_open >= 1
    quiet = ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert quiet.caps_written == 0 and quiet.caps_deleted == 0, "a second pass writes nothing"
    assert ph.caps_of(world.db, [p6])[p6][0].appeared is None
    got = ph.caps_of(world.db, [p3])[p3]
    assert [(c.fixture_id, c.kickoff, c.team_id, c.is_starter, c.appeared, c.minutes) for c in got] == [
        (fid, T0 + timedelta(days=3), spain, False, True, 30)]
    assert ph.build(world.db, apply=True, players=[p1], now=T0 + timedelta(days=10)).fixtures == 0, "a pass for some players leaves the caps alone"


def test_a_cap_waits_for_the_statistics_and_the_scheduled_pass_completes_it_long_after_the_match(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    fid = world.fixture(spain, italy, 3, national=True)
    world.lineup(fid, "home", [(p, False)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=4))
    assert world.caps(fid) == {p: (spain, False, None, None)}
    world.stats(fid, "home", [(p, 12, True)])
    far = T0 + timedelta(days=400)  # the match is far outside the window: only the open cap brings it back
    assert fid in ph.recent_cap_fixtures(world.db, [spain, italy], now=far), "a cap that waits for the statistics brings the match back"
    scheduled = ph.build(world.db, apply=True, now=far)
    assert scheduled.caps_written >= 1
    assert world.caps(fid) == {p: (spain, False, True, 12)}


def test_youth_sides_unclassified_teams_clubs_and_matches_not_finished_make_no_caps(world: World) -> None:
    spain, youth = world.team("Spain", True), world.team("Spain U21", True)
    club, rival, mystery = world.team("Alpha FC", False), world.team("Rival FC", False), world.team("Mystery", None)
    ps = [world.player() for _ in range(5)]
    cases = {
        "youth": world.fixture(youth, rival, 1, national=True),
        "club": world.fixture(club, rival, 2),
        "unclassified": world.fixture(mystery, rival, 3, national=True),
        "not finished": world.fixture(spain, rival, 4, status="scheduled", national=True),
        "cancelled": world.fixture(spain, rival, 5, status="cancelled", national=True),
    }
    for p, fid in zip(ps, cases.values(), strict=True):
        world.lineup(fid, "home", [(p, True)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert all(world.caps(fid) == {} for fid in cases.values())


def test_a_match_that_stops_being_a_cap_loses_them(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    fid = world.fixture(spain, italy, 3, national=True)
    world.lineup(fid, "home", [(p, True)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert world.caps(fid) != {}
    world.db.execute("UPDATE core.fixtures SET status_group = 'postponed' WHERE id = %s", (fid,))
    gone = ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert gone.caps_deleted == 1 and world.caps(fid) == {}
    world.db.execute("UPDATE core.fixtures SET status_group = 'finished' WHERE id = %s", (fid,))
    world.db.execute("UPDATE core.teams SET name = 'Spain U19' WHERE id = %s", (spain,))
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert world.caps(fid) == {}, "a side that is a youth one is not a senior one"


def test_a_player_in_the_statistics_but_not_in_the_squad_sheet_has_a_cap(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p, q = world.player(), world.player()
    fid = world.fixture(spain, italy, 3, national=True)
    world.stats(fid, "home", [(p, 90, False), (q, None, True)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert world.caps(fid) == {p: (spain, True, True, 90), q: (spain, False, False, None)}


def test_the_record_of_a_man_before_a_match_is_read_back(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    fids = [world.fixture(spain, italy, day, national=True) for day in (3, 10, 20)]
    for fid, minutes in zip(fids, (90, 45, 70), strict=True):
        world.lineup(fid, "home", [(p, True)])
        world.stats(fid, "home", [(p, minutes, False)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=30))
    caps = ph.caps_of(world.db, [p], before=T0 + timedelta(days=20))[p]
    assert [c.fixture_id for c in caps] == [fids[1], fids[0]], "newest first, and the match itself is not in its own record"
    got = cp.profile(caps, before=T0 + timedelta(days=20))
    assert (got.caps, got.starts, got.minutes) == (2, 2, 135)
    assert [c.fixture_id for c in ph.caps_of(world.db, [p])[p]] == [fids[2], fids[1], fids[0]]


# ── the figures ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_figures_and_the_audit_say_when_all_is_well_and_when_it_is_not(world: World) -> None:
    spain, italy, a, rival = world.team("Spain", True), world.team("Italy", True), world.team("Alpha FC", False), world.team("Rival FC", False)
    p, mover = world.player(), world.player()
    world.lineup(world.fixture(a, rival, 1), "home", [(p, True)])
    world.transfer(mover, 5, world.provider(rival), world.provider(a))   # two streaks, the second beginning the day the first ends
    # a month before the day the test runs, whenever that is: inside the year the figures about recent caps look at
    fid = world.fixture(spain, italy, (datetime.now(UTC) - T0).days - 30, national=True)
    world.lineup(fid, "home", [(p, True)])
    ph.build(world.db, apply=True, sweep=True)
    figures = ph.audit(world.db)
    assert ph.broken_invariants(figures) == []
    assert not any(figures["pass_would_write"].values()), figures["pass_would_write"]
    assert figures["spells"] >= 3 and figures["caps"] >= 1 and figures["spells_by_source"]["lineup"] >= 1
    assert figures["spells_of_another_version"] == 0 and figures["caps_of_another_version"] == 0
    assert figures["recent_caps"] >= 1 and 0.0 <= figures["recent_club_known_share"] <= 1.0

    # break two invariants the tables cannot refuse: a streak that begins before the previous one ended, and a cap of a match not played
    overlapping, open_before_another = world.player(), world.player()
    for stray, first_end in ((overlapping, "'2026-03-01'"), (open_before_another, "NULL")):
        world.db.execute("INSERT INTO core.player_spells (provider_player_id, ordinal, provider_team_id, valid_from, valid_to, source, "
                         f"last_evidence, version) VALUES (%(p)s, 0, 1, '2026-01-01', {first_end}, 'lineup', '2026-01-01', 'spells-v1'), "
                         "(%(p)s, 1, 2, '2026-02-01', NULL, 'lineup', '2026-02-01', 'spells-v1')", {"p": stray})
    world.db.execute("UPDATE core.fixtures SET status_group = 'postponed' WHERE id = %s", (fid,))
    world.db.execute("UPDATE core.player_spells SET version = 'spells-v0' WHERE provider_player_id = %s", (overlapping,))
    world.db.execute("UPDATE core.player_national_caps SET version = 'caps-v0' WHERE fixture_id = %s", (fid,))
    broken = ph.counts(world.db)
    assert ph.broken_invariants(broken) == ["spells_out_of_order", "caps_of_unfinished_matches"]
    assert broken["spells_out_of_order"] == 2 and broken["caps_of_unfinished_matches"] == 1
    assert broken["spells_of_another_version"] == 2 and broken["caps_of_another_version"] == 1


def test_the_caps_can_be_read_as_of_a_moment(world: World) -> None:
    spain, italy, p = world.team("Spain", True), world.team("Italy", True), world.player()
    early, late = world.fixture(spain, italy, 5, national=True), world.fixture(spain, italy, 9, national=True)
    for fixture, settled in ((early, T0 + timedelta(days=5, hours=3)), (late, T0 + timedelta(days=12))):
        world.lineup(fixture, "home", [(p, True)])
        world.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 1, 0, %s)", (fixture, settled))
    ph.build(world.db, apply=True, sweep=True)
    assert [c.fixture_id for c in ph.caps_of(world.db, [p])[p]] == [late, early]
    assert [c.fixture_id for c in ph.caps_of(world.db, [p], settled_by=T0 + timedelta(days=10))[p]] == [early], "the result of the late one came after"
    assert [c.fixture_id for c in ph.caps_of(world.db, [p], settled_by=T0 + timedelta(days=12))[p]] == [late, early], "and at the very moment it is known"
    assert [c.fixture_id for c in ph.caps_of(world.db, [p], before=T0 + timedelta(days=9), settled_by=T0 + timedelta(days=30))[p]] == [early]


def test_the_audit_names_the_caps_of_youth_sides_and_of_teams_that_are_not_national_ones(world: World) -> None:
    italy, u21, club, rival = world.team("Italy", True), world.team("Spain U21", True), world.team("Alpha FC", False), world.team("Rival FC", False)
    mystery = world.team("Mystery", None)
    p = world.player()
    youth_match = world.fixture(u21, italy, 5, national=True)
    club_match = world.fixture(club, rival, 6)
    unclassified_match = world.fixture(mystery, rival, 7, national=True)
    assert ph.broken_invariants(ph.counts(world.db)) == []
    for fixture, team in ((youth_match, u21), (club_match, club), (unclassified_match, mystery)):
        world.db.execute("INSERT INTO core.player_national_caps (provider_player_id, fixture_id, team_id, is_starter, appeared, minutes, version) "
                         "VALUES (%s, %s, %s, true, true, 90, %s)", (p, fixture, team, cp.VERSION))
    figures = ph.counts(world.db)
    assert (figures["caps_of_youth_sides"], figures["caps_of_other_sides"]) == (1, 2)
    assert ph.broken_invariants(figures) == ["caps_of_youth_sides", "caps_of_other_sides"]


def test_the_counts_of_recent_caps_say_how_many_have_a_club_and_the_audit_only_looks(world: World) -> None:
    spain, italy, a, rival = world.team("Spain", True), world.team("Italy", True), world.team("Alpha FC", False), world.team("Rival FC", False)
    with_club, without, leaver, twice, joiner = (world.player() for _ in range(5))
    w, x, y = world.team("W FC", False), world.team("X FC", False), world.team("Y FC", False)
    before = ph.counts(world.db)
    assert before["recent_club_known_share"] == (1.0 if not before["recent_caps"] else round(before["recent_caps_with_a_club"] / before["recent_caps"], 4))
    world.lineup(world.fixture(a, rival, 1), "home", [(with_club, True), (leaver, True)])
    month_ago = (datetime.now(UTC) - T0).days - 30
    recent = world.fixture(spain, italy, month_ago, national=True)
    world.lineup(recent, "home", [(with_club, True), (without, False), (leaver, False)])
    world.lineup(world.fixture(spain, italy, month_ago - 700, national=True), "home", [(with_club, True)])  # long ago: not "recent"
    world.transfer(leaver, month_ago, world.provider(spain), world.provider(a))   # leaves Alpha the day of the match: no club that day
    morning = (T0 + timedelta(days=month_ago)).replace(hour=1, minute=30)
    world.lineup(world.fixture(spain, italy, month_ago, national=True, at=morning), "home", [(joiner, True)])
    world.transfer(joiner, month_ago, world.provider(a), None)                    # joins Alpha the day of a 01:30 UTC match: a day at the club
    world.transfer(twice, 10, world.provider(x), world.provider(w))               # two moves from one club on one day: a streak of no days
    world.transfer(twice, 10, world.provider(y), world.provider(w))
    ph.build(world.db, apply=True, sweep=True)
    after = ph.counts(world.db)
    assert after["caps"] - before["caps"] == 5
    assert after["recent_caps"] - before["recent_caps"] == 4
    assert after["recent_caps_with_a_club"] - before["recent_caps_with_a_club"] == 2
    assert after["spells_by_source"]["lineup"] - before["spells_by_source"].get("lineup", 0) == 2
    assert after["spells_open"] - before["spells_open"] == 3 and after["players_with_spells"] - before["players_with_spells"] == 4
    assert after["caps_players"] - before["caps_players"] == 4 and after["caps_fixtures"] - before["caps_fixtures"] == 3
    assert after["caps_open"] - before["caps_open"] == 2, "the substitutes without statistics wait for them"
    assert after["recent_club_known_share"] == round(after["recent_caps_with_a_club"] / after["recent_caps"], 4) > 0.0

    world.db.execute("DELETE FROM core.player_spells WHERE provider_player_id = %s", (with_club,))
    found = ph.audit(world.db)
    assert found["pass_would_write"] == {"spells": 1, "spells_deleted": 0, "caps": 0, "caps_deleted": 0} and found["phantoms"] == 1
    assert world.spells(with_club) == [], "the audit only looks"


# ── what a transfer list cannot say, who wins when the sources disagree, how a pass is cut ─────────────────────────────


def test_what_a_transfer_list_cannot_say_is_left_out_and_only_the_newest_list_counts(world: World) -> None:
    club, other, mystery = world.team("Alpha FC", False), world.team("Beta FC", False), world.team("Mystery FC", None)
    undated, no_club, unclassified, relisted, wordy, blank = (world.player() for _ in range(6))
    world.transfer(undated, 3, world.provider(club), None)
    world.db.execute("UPDATE core.player_transfers SET transfer_date = NULL WHERE provider_player_id = %s", (undated,))   # cannot be placed in time
    world.transfer(no_club, 3, 0, world.provider(club))                                   # the provider's 0 is "no club"
    world.transfer(unclassified, 3, world.provider(mystery), world.provider(club))        # a team nobody has classified is not known to be a club
    world.transfer(relisted, 5, world.provider(club), None, listed=0)                     # the list read first...
    world.transfer(relisted, 9, world.provider(other), world.provider(club), listed=1)    # ...and the one read after, which no longer has it
    world.transfer(wordy, 3, world.provider(club), None, "Loan " + "x" * 100)
    world.transfer(blank, 3, world.provider(club), None, "   ")
    report = ph.build(world.db, apply=True, players=[undated, no_club, unclassified, relisted, wordy, blank, wordy])
    assert world.spells(undated) == [] and report.phantoms == 0, "a transfer with no date is not looked at"
    assert [(row[1], row[3], row[4]) for row in world.spells(no_club)] == [(world.provider(club), None, d(3))]
    assert [(row[1], row[3], row[4]) for row in world.spells(unclassified)] == [(world.provider(club), None, d(3))]
    assert [(row[1], row[3], row[4]) for row in world.spells(relisted)] == [(world.provider(club), None, d(9)), (world.provider(other), d(9), None)]
    assert world.spells(wordy)[0][8] == ("Loan " + "x" * 100)[:60], "the wording of the move is cut"
    assert world.spells(blank)[0][8] is None


def test_the_day_of_a_match_or_a_sighting_is_its_utc_day(world: World) -> None:
    a, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    early, late, stats_early, stats_late, sighted = (world.player() for _ in range(5))
    day = T0 + timedelta(days=5)
    # 01:30 UTC is still the day before in the Americas and 23:30 UTC is already the day after in Asia
    morning, night = day.replace(hour=1, minute=30), day.replace(hour=23, minute=30)
    world.lineup(world.fixture(a, rival, 0, at=morning), "home", [(early, True)])
    world.lineup(world.fixture(a, rival, 0, at=night), "home", [(late, True)])
    world.stats(world.fixture(a, rival, 0, at=morning), "home", [(stats_early, 90, False)])
    world.stats(world.fixture(a, rival, 0, at=night), "home", [(stats_late, 90, False)])
    world.db.execute("INSERT INTO core.squad_members (team_id, provider_player_id, first_seen_at, last_seen_at, payload_hash) "
                     "VALUES (%s, %s, %s, %s, %s)", (a, sighted, morning, night, world.seed.payload_hash))
    ph.build(world.db, apply=True, players=[early, late, stats_early, stats_late, sighted])
    assert [world.spells(x)[0][3] for x in (early, late, stats_early, stats_late)] == [d(5)] * 4
    assert [(row[3], row[7]) for row in world.spells(sighted)] == [(d(5), d(5))], "first and last sighting, as UTC days"


def test_when_the_squad_sheet_and_the_statistics_disagree_about_the_side_the_statistics_win(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    p = world.player()
    fid = world.fixture(a, b, 2)
    world.lineup(fid, "home", [(p, True)])
    world.stats(fid, "away", [(p, 90, False)])
    report = ph.build(world.db, apply=True, players=[p, p])
    assert [(row[1], row[6]) for row in world.spells(p)] == [(world.provider(b), 1)], "(measured: they are right in 97.7 % of the disagreements)"
    assert report.players == 1, "a player asked for twice is looked at once"
    assert (report.sheets_crossed, report.sheets_doubtful) == (0, 1), "one man apart in a sheet of one man: in doubt, not crossed"


def test_two_moves_to_different_clubs_on_one_day_leave_a_streak_of_no_days_that_is_counted_and_not_written(world: World) -> None:
    w, x, y = world.team("W FC", False), world.team("X FC", False), world.team("Y FC", False)
    p = world.player()
    world.transfer(p, 10, world.provider(x), world.provider(w))
    world.transfer(p, 10, world.provider(y), world.provider(w))
    report = ph.build(world.db, apply=True, players=[p])
    assert report.phantoms == 1 and report.spells == 2
    assert [(row[1], row[3], row[4]) for row in world.spells(p)] == [(world.provider(w), None, d(10)), (world.provider(y), d(10), None)]


def test_a_transfer_list_read_again_is_news_only_when_it_lists_a_recent_transfer(world: World) -> None:
    """Regression (23 Oct 2026, the first scheduled pass in production): the provider reads its transfer lists again about once a week,
    a new snapshot for each of 130,000 men, and nearly all say what they said before. The pass took every man whose list had been read
    in the window - 132,692 men and eleven minutes to write nothing. A list is news when it lists a transfer that has just happened;
    an old one listed late is the daily sweep's."""
    assert ph.WINDOW.days == 4 and ph.TRANSFER_LOOKBACK.days == 30, "(the dates below are written for these two)"
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    fresh, reread, at_the_edge, past_the_edge, late, read_before = (world.player() for _ in range(6))
    now = T0 + timedelta(days=10)
    # the window starts 4 days before now (day 6); a transfer counts if it is dated no earlier than 30 days before that (day -24)
    for man, day in ((fresh, 8), (at_the_edge, -24), (past_the_edge, -25)):
        world.transfer(man, day, world.provider(b), world.provider(a), listed=9)
    world.transfer(reread, -300, world.provider(b), world.provider(a), listed=9)       # the whole list read again, nothing new in it
    world.transfer(late, -120, world.provider(b), world.provider(a), listed=9)         # an old transfer that the provider lists late
    world.transfer(read_before, 5, world.provider(b), world.provider(a), listed=2)     # recent, but the list was read before the window
    got = set(ph.recent_players(world.db, now=now))
    assert {fresh, at_the_edge} <= got and not ({reread, past_the_edge, late, read_before} & got)
    assert not ({reread, late} & set(ph.recent_players(world.db, now=T0 + timedelta(days=11)))), "and the day after"
    assert {reread, late} <= set(ph.all_players(world.db)), "but the sweep looks at them"
    scheduled = ph.build(world.db, apply=True, now=now)
    assert scheduled.mode == ph.SCHEDULED and world.spells(fresh) != [] and world.spells(reread) == [] == world.spells(late)
    swept = ph.build(world.db, apply=True, sweep=True, now=now)
    assert swept.mode == ph.SWEEP and world.spells(reread) != [] and world.spells(late) != []


def test_the_scheduled_pass_reads_a_window_of_days_around_now_and_the_statistics_too(world: World) -> None:
    a, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    inside, today, too_old, future, stats_only, stats_old, stats_future = (world.player() for _ in range(7))
    now = T0 + timedelta(days=10)
    world.lineup(world.fixture(a, rival, 8), "home", [(inside, True)])
    world.lineup(world.fixture(a, rival, 10), "home", [(today, True)])
    world.lineup(world.fixture(a, rival, 4), "home", [(too_old, True)])
    world.lineup(world.fixture(a, rival, 14), "home", [(future, True)])
    world.stats(world.fixture(a, rival, 9), "home", [(stats_only, 90, False)])
    world.stats(world.fixture(a, rival, 1), "home", [(stats_old, 90, False)])
    world.stats(world.fixture(a, rival, 14), "home", [(stats_future, 90, False)])
    got = set(ph.recent_players(world.db, now=now))
    assert {inside, today, stats_only} <= got and not ({too_old, future, stats_old, stats_future} & got)
    assert too_old in ph.recent_players(world.db, now=now, window=timedelta(days=7))


def test_the_scheduled_pass_finds_the_matches_of_a_senior_side_on_either_side(world: World) -> None:
    spain, club, rival = world.team("Spain", True), world.team("Alpha FC", False), world.team("Rival FC", False)
    p_home, p_away, p_none = world.player(), world.player(), world.player()
    at_home = world.fixture(spain, club, 8, national=True)
    away = world.fixture(club, spain, 9, national=True)
    neither = world.fixture(club, rival, 9)
    old, ahead = world.fixture(spain, club, 2, national=True), world.fixture(club, spain, 14, national=True)
    world.lineup(at_home, "home", [(p_home, True)])
    world.lineup(away, "away", [(p_away, True)])
    world.lineup(neither, "home", [(p_none, True)])
    now = T0 + timedelta(days=10)
    found = ph.recent_cap_fixtures(world.db, [spain], now=now)
    assert at_home in found and away in found and not ({neither, old, ahead} & set(found))
    everywhere = ph.all_cap_fixtures(world.db, [spain])
    assert {at_home, away, old} <= set(everywhere) and neither not in everywhere, "the sweep goes through all the finished matches of the side"
    ph.build(world.db, apply=True, now=now)
    assert (set(world.caps(at_home)), set(world.caps(away)), world.caps(neither)) == ({p_home}, {p_away}, {})


def test_a_cap_follows_the_facts_it_was_built_from(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    fid = world.fixture(spain, italy, 3, national=True)
    world.lineup(fid, "home", [(p, False)])
    world.stats(fid, "home", [(p, 20, True)])
    now = T0 + timedelta(days=10)
    ph.build(world.db, apply=True, sweep=True, now=now)
    assert world.caps(fid) == {p: (spain, False, True, 20)}
    # the sheet is corrected (he started), the minutes too, and the home side turns out to be the other team
    world.db.execute("UPDATE core.fixture_lineup_players SET is_starter = true WHERE fixture_id = %s", (fid,))
    world.db.execute("UPDATE core.fixture_player_stats SET minutes = 75 WHERE fixture_id = %s", (fid,))
    world.db.execute("UPDATE core.fixtures SET home_team_id = %s, away_team_id = %s WHERE id = %s", (italy, spain, fid))
    ph.build(world.db, apply=True, sweep=True, now=now)
    assert world.caps(fid) == {p: (italy, True, True, 75)}
    world.db.execute("UPDATE core.player_national_caps SET version = 'caps-v0' WHERE fixture_id = %s", (fid,))
    again = ph.build(world.db, apply=True, sweep=True, now=now)
    assert again.caps_written == 1 and again.caps_deleted == 0
    assert world.one("SELECT version FROM core.player_national_caps WHERE fixture_id = %s", fid) == cp.VERSION


def test_a_big_pass_is_cut_into_batches_and_nobody_is_lost(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ph, "BATCH", 2)
    monkeypatch.setattr(ph, "CAP_BATCH", 1)
    a, rival, spain, italy = world.team("Alpha FC", False), world.team("Rival FC", False), world.team("Spain", True), world.team("Italy", True)
    players = [world.player() for _ in range(5)]
    world.lineup(world.fixture(a, rival, 1), "home", [(x, True) for x in players])
    fids = [world.fixture(spain, italy, day, national=True) for day in (2, 3, 4)]
    for fid in fids:
        world.lineup(fid, "home", [(players[0], True)])
    report = ph.build(world.db, apply=True, players=players)
    assert report.players == 5 and report.spells_written == 5 and all(len(world.spells(x)) == 1 for x in players)
    sweep = ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert sweep.fixtures >= 3 and all(set(world.caps(fid)) == {players[0]} for fid in fids)


def test_a_person_at_the_console_waits_for_the_lock_and_gives_up_after_a_while(
        world: World, migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ph, "MANUAL_LOCK_WAIT", "200ms")
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (ph.LOCK_KEY,))
        with pytest.raises(psycopg.errors.LockNotAvailable):
            ph.build(world.db, apply=True, wait=True, players=[1])
        other.rollback()
    # (the lock of a pass is held to the end of the transaction, so this one comes after: the other connection would wait for it)
    assert not ph.build(world.db, apply=True, wait=True, players=[1]).skipped_locked, "nobody holds it any more"


# ── which side a man was on: the statistics win, and a pair of squad sheets the provider crossed is turned round ───────────


def crossed_match(world: World, home: int, away: int, day: int, *, home_men: list[int], away_men: list[int], home_bench: int | None = None,
                  away_bench: int | None = None, national: bool = False) -> int:
    """A match whose squad sheets the provider gave to the wrong team: the sheet of ``home`` lists the men of ``away`` and the other way
    round, while the statistics are right. The benches (never on the pitch) are in the sheets only."""
    fid = world.fixture(home, away, day, national=national)
    world.lineup(fid, "home", [(p, True) for p in away_men] + ([(away_bench, False)] if away_bench else []))
    world.lineup(fid, "away", [(p, True) for p in home_men] + ([(home_bench, False)] if home_bench else []))
    world.stats(fid, "home", [(p, 90, False) for p in home_men])
    world.stats(fid, "away", [(p, 90, False) for p in away_men])
    return fid


def test_a_match_whose_squad_sheets_the_provider_crossed_is_read_the_right_way_round(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    ours, theirs = [world.player() for _ in range(6)], [world.player() for _ in range(6)]
    our_bench, their_bench = world.player(), world.player()
    for day in (1, 30):   # ordinary matches around it, sheets and statistics agree: a mistake would show as a stint at the other club
        fid = world.fixture(a, b, day)
        world.lineup(fid, "home", [(p, True) for p in ours] + [(our_bench, False)])
        world.lineup(fid, "away", [(p, True) for p in theirs] + [(their_bench, False)])
        world.stats(fid, "home", [(p, 90, False) for p in ours])
        world.stats(fid, "away", [(p, 90, False) for p in theirs])
    crossed_match(world, a, b, 15, home_men=ours, away_men=theirs, home_bench=our_bench, away_bench=their_bench)
    everyone = [*ours, *theirs, our_bench, their_bench]

    dry = ph.build(world.db, players=everyone)
    assert (dry.sheets_crossed, dry.sheets_doubtful, dry.men_nowhere) == (2, 0, 0), "both sheets of the match, and only those"
    report = ph.build(world.db, apply=True, players=everyone)
    assert report.sheets_crossed == 2 and report.spells_written == len(everyone)
    for p in ours:
        assert [(row[1], row[3], row[4], row[6]) for row in world.spells(p)] == [(world.provider(a), d(1), None, 3)]
    for p in theirs:
        assert [(row[1], row[3], row[4], row[6]) for row in world.spells(p)] == [(world.provider(b), d(1), None, 3)]
    assert [(row[1], row[6]) for row in world.spells(our_bench)] == [(world.provider(a), 3)], "a bench the statistics never name follows its sheet"
    assert [(row[1], row[6]) for row in world.spells(their_bench)] == [(world.provider(b), 3)]
    quiet = ph.build(world.db, apply=True, players=everyone)
    assert not quiet.changed and quiet.sheets_crossed == 2, "a second pass writes nothing"
    assert ph.build(world.db, apply=True, players=[ours[0]]).sheets_crossed == 2, "the matches of the players asked for are looked at whole"


def test_a_sheet_with_too_few_men_in_the_statistics_is_not_turned_round_on_so_little(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    ours, theirs = [world.player() for _ in range(4)], [world.player() for _ in range(4)]
    our_bench, their_bench = world.player(), world.player()
    crossed_match(world, a, b, 5, home_men=ours, away_men=theirs, home_bench=our_bench, away_bench=their_bench)
    report = ph.build(world.db, apply=True, players=[*ours, *theirs, our_bench, their_bench])
    assert (report.sheets_crossed, report.sheets_doubtful) == (0, 2), "four men are too few: both sheets are in doubt"
    # the men the statistics name are where the statistics say; the benches, of whom nothing else is known, follow their sheets
    assert all([(row[1], row[6]) for row in world.spells(p)] == [(world.provider(a), 1)] for p in ours)
    assert all([(row[1], row[6]) for row in world.spells(p)] == [(world.provider(b), 1)] for p in theirs)
    assert [(row[1], row[6]) for row in world.spells(our_bench)] == [(world.provider(b), 1)], "(the residue the rule cannot reach)"
    assert [(row[1], row[6]) for row in world.spells(their_bench)] == [(world.provider(a), 1)]


def test_a_sheet_that_half_agrees_with_the_statistics_is_not_turned_round(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    men = [world.player() for _ in range(10)]
    fid = world.fixture(a, b, 5)
    world.lineup(fid, "home", [(p, True) for p in men])
    world.stats(fid, "home", [(p, 90, False) for p in men[:5]])
    world.stats(fid, "away", [(p, 90, False) for p in men[5:]])   # half of the sheet is apart: no rule says which half is wrong
    bench = world.player()
    world.lineup(fid, "home", [(bench, False)])
    report = ph.build(world.db, apply=True, players=[*men, bench])
    assert (report.sheets_crossed, report.sheets_doubtful) == (0, 1)
    assert [(row[1]) for row in world.spells(men[0])] == [world.provider(a)] and [(row[1]) for row in world.spells(men[9])] == [world.provider(b)]
    assert [(row[1]) for row in world.spells(bench)] == [world.provider(a)], "a sheet in doubt is left as the provider gave it"


def test_a_match_with_no_statistics_keeps_its_squad_sheets_as_they_are(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    ours, theirs = [world.player() for _ in range(7)], [world.player() for _ in range(7)]
    fid = world.fixture(a, b, 3)
    world.lineup(fid, "home", [(p, True) for p in ours])
    world.lineup(fid, "away", [(p, True) for p in theirs])
    report = ph.build(world.db, apply=True, players=[*ours, *theirs])
    assert (report.sheets_crossed, report.sheets_doubtful) == (0, 0)
    assert all(world.spells(p)[0][1] == world.provider(a) for p in ours) and all(world.spells(p)[0][1] == world.provider(b) for p in theirs)


def test_a_man_in_both_squad_sheets_is_where_the_statistics_say_and_nowhere_if_they_do_not(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    named, unnamed, plain = world.player(), world.player(), world.player()
    fid = world.fixture(a, b, 3)
    world.lineup(fid, "home", [(named, True), (unnamed, True), (plain, True)])
    world.lineup(fid, "away", [(named, True), (unnamed, True)])
    world.stats(fid, "away", [(named, 90, False)])
    report = ph.build(world.db, apply=True, players=[named, unnamed, plain])
    assert [(row[1], row[6]) for row in world.spells(named)] == [(world.provider(b), 1)]
    assert world.spells(unnamed) == [], "nothing says which club he was playing for"
    assert [(row[1], row[6]) for row in world.spells(plain)] == [(world.provider(a), 1)]
    assert report.men_nowhere == 1
    assert (report.sheets_crossed, report.sheets_doubtful) == (0, 1), "the sheet that carries the man on the wrong side is in doubt, not turned"


def test_the_sheets_the_statistics_cross_are_read_for_a_scope_and_a_scope_is_one_thing(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    ours, theirs, bystander = [world.player() for _ in range(6)], [world.player() for _ in range(6)], world.player()
    fid = crossed_match(world, a, b, 4, home_men=ours, away_men=theirs)
    fine = world.fixture(a, b, 9)
    world.lineup(fine, "home", [(bystander, True)])
    world.stats(fine, "home", [(bystander, 90, False)])
    want = {(fid, "home"), (fid, "away")}
    everywhere = ph.read_sheets(world.db)
    assert want <= everywhere.crossed and (fine, "home") not in everywhere.crossed
    assert ph.read_sheets(world.db, players=[ours[0]]).crossed == want, "the matches of the players asked for"
    assert ph.read_sheets(world.db, players=[bystander]).crossed == set()
    assert ph.read_sheets(world.db, fixtures=[fid, fine]).crossed == want
    assert ph.read_sheets(world.db, fixtures=[fine]).crossed == set()
    assert ph.read_sheets(world.db, players=[]).crossed == set() and ph.read_sheets(world.db, fixtures=[]).crossed == set()
    with pytest.raises(ValueError, match="not both"):
        ph.read_sheets(world.db, players=[1], fixtures=[2])


def test_the_pass_of_everyone_and_the_pass_of_a_few_read_the_crossed_matches_alike(world: World) -> None:
    a, b = world.team("Alpha FC", False), world.team("Beta FC", False)
    ours, theirs = [world.player() for _ in range(6)], [world.player() for _ in range(6)]
    crossed_match(world, a, b, 4, home_men=ours, away_men=theirs)
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    swept = {p: world.spells(p) for p in (*ours, *theirs)}
    world.db.execute("DELETE FROM core.player_spells WHERE provider_player_id = ANY(%s)", ([*ours, *theirs],))
    ph.build(world.db, apply=True, players=[*ours, *theirs])
    assert {p: world.spells(p) for p in (*ours, *theirs)} == swept


# ── the same for a national team: the cap goes to the nation he plays for ──────────────────────────────────────────────────


def test_the_caps_of_a_match_whose_squad_sheets_were_crossed_go_to_the_right_nation(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    spaniards, italians = [world.player() for _ in range(6)], [world.player() for _ in range(6)]
    spanish_bench, italian_bench = world.player(), world.player()
    fid = crossed_match(world, spain, italy, 3, home_men=spaniards, away_men=italians, home_bench=spanish_bench, away_bench=italian_bench,
                        national=True)
    report = ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert report.sheets_crossed >= 2
    expected: dict[int, tuple[int, bool, bool | None, int | None]] = {
        **dict.fromkeys(spaniards, (spain, True, True, 90)), **dict.fromkeys(italians, (italy, True, True, 90)),
        spanish_bench: (spain, False, False, None), italian_bench: (italy, False, False, None)}
    assert world.caps(fid) == expected
    quiet = ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert quiet.caps_written == 0 and quiet.caps_deleted == 0
    assert [c.team_id for c in ph.caps_of(world.db, [italians[0]])[italians[0]]] == [italy]


def test_a_cap_goes_to_the_side_the_statistics_say_even_when_a_sheet_disagrees_about_one_man(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p, q = world.player(), world.player()
    fid = world.fixture(spain, italy, 3, national=True)
    world.lineup(fid, "home", [(p, True), (q, True)])
    world.stats(fid, "home", [(q, 90, False)])
    world.stats(fid, "away", [(p, 80, False)])     # a lone disagreement: the sheet is not crossed, the man is where the statistics say
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert world.caps(fid) == {p: (italy, True, True, 80), q: (spain, True, True, 90)}


def test_a_man_in_both_squad_sheets_of_a_national_match_has_a_cap_only_if_the_statistics_place_him(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    named, unnamed = world.player(), world.player()
    fid = world.fixture(spain, italy, 3, national=True)
    for side in ("home", "away"):
        world.lineup(fid, side, [(named, False), (unnamed, True)])
    world.stats(fid, "away", [(named, 25, True)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=10))
    assert world.caps(fid) == {named: (italy, False, True, 25)}


def test_a_direct_call_for_caps_reads_the_crossed_sheets_of_its_own_matches_unless_it_is_given_them(world: World) -> None:
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    spaniards, italians = [world.player() for _ in range(5)], [world.player() for _ in range(5)]
    spanish_bench = world.player()
    fid = crossed_match(world, spain, italy, 3, home_men=spaniards, away_men=italians, home_bench=spanish_bench, national=True)
    senior = {spain, italy}
    reads_its_own = {r[0]: r[2] for r in ph.wanted_caps(world.db, [fid], senior)}
    assert reads_its_own == {**dict.fromkeys(spaniards, spain), **dict.fromkeys(italians, italy), spanish_bench: spain}
    told_none = {r[0]: r[2] for r in ph.wanted_caps(world.db, [fid], senior, frozenset())}
    assert told_none == {**dict.fromkeys(spaniards, spain), **dict.fromkeys(italians, italy), spanish_bench: italy}, \
        "told that no sheet is crossed, the statistics still place the men they name, and only the bench follows its sheet"
    assert ph.wanted_caps(world.db, [], senior) == []


# ── the figures of the audit about the sides ─────────────────────────────────────────────────────────────────────────────


def test_the_audit_counts_the_crossed_sheets_the_matches_with_no_statistics_and_the_lone_stints(world: World) -> None:
    a, b, c = world.team("Alpha FC", False), world.team("Beta FC", False), world.team("Gamma FC", False)
    before = ph.audit(world.db)
    ours, theirs = [world.player() for _ in range(6)], [world.player() for _ in range(6)]
    crossed_match(world, a, b, 4, home_men=ours, away_men=theirs)
    lone = world.player()
    # A, B for a single match, A again: three squad sheets (no statistics), nothing else known of him
    world.lineup(world.fixture(a, c, 20), "home", [(lone, True)])
    world.lineup(world.fixture(b, c, 25), "home", [(lone, True)])
    world.lineup(world.fixture(a, c, 30), "home", [(lone, True)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=40))
    after = ph.audit(world.db)
    assert after["sheets_crossed"] - before["sheets_crossed"] == 2
    assert after["fixtures_with_sheets_only"] - before["fixtures_with_sheets_only"] == 3
    assert after["lone_stints"] - before["lone_stints"] == 1
    assert after["men_nowhere"] == before["men_nowhere"] and ph.broken_invariants(after) == []
    assert not any(after["pass_would_write"].values())


# ── what the provider writes where a man has no identity ─────────────────────────────────────────────────────────────────


def test_the_providers_player_zero_makes_no_streak_and_no_cap_and_does_not_stop_the_pass(world: World) -> None:
    """Regression (22 Oct 2026, the first scheduled pass in production): the statistics of 4,820 matches carry one line of a "player 0"
    (the provider's placeholder for a man it cannot name). The pass folded him like anybody else and the table refused the row
    (``player_spells_player_check``: an identifier above zero), so the whole transaction failed - and would fail at every pass."""
    a, rival, spain, italy = world.team("Alpha FC", False), world.team("Rival FC", False), world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    club_match = world.fixture(a, rival, 2)
    world.lineup(club_match, "home", [(p, True), (0, False)])
    world.stats(club_match, "home", [(p, 90, False), (0, 0, True)])
    national_match = world.fixture(spain, italy, 3, national=True)
    world.lineup(national_match, "home", [(p, True), (0, False)])
    world.stats(national_match, "home", [(p, 90, False), (0, None, True)])
    world.transfer(0, 1, world.provider(a), None)   # (a squad list cannot carry him: its table refuses an identifier of zero)
    now = T0 + timedelta(days=4)
    assert 0 not in ph.all_players(world.db) and 0 not in ph.recent_players(world.db, now=now)
    report = ph.build(world.db, apply=True, sweep=True, now=now)
    assert report.applied and world.spells(0) == []
    assert world.caps(national_match) == {p: (spain, True, True, 90)}
    assert [(row[1], row[6]) for row in world.spells(p)] == [(world.provider(a), 1)]
    asked = ph.build(world.db, apply=True, players=[0, p, -3])
    assert asked.players == 1, "a man without an identity is not asked for either"
    assert ph.audit(world.db)["pass_would_write"] == {"spells": 0, "spells_deleted": 0, "caps": 0, "caps_deleted": 0}


# ── a database that is written to while the pass runs ────────────────────────────────────────────────────────────────────

NOTHING = {"spells": 0, "spells_deleted": 0, "caps": 0, "caps_deleted": 0}
NO_NEWS = {"players": 0, "spells": 0}


def a_man_with_three_matches(world: World) -> tuple[int, int, int]:
    """(club, rival, player): the man played for the club on days 1, 10 and 20, and a sweep has put that into the table."""
    club, rival, man = world.team("Alpha FC", False), world.team("Rival FC", False), world.player()
    for day in (1, 10, 20):
        world.lineup(world.fixture(club, rival, day), "home", [(man, True)])
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=21))
    return club, rival, man


def test_a_match_played_while_the_sweep_ran_is_news_for_the_audit_and_not_a_pass_that_still_writes(world: World) -> None:
    """Regression (23 Oct 2026, the first full build in production): the audit that follows a sweep found 46 players for whom "a pass
    would still write", and every one differed from the stored streak by one match more and a last day of evidence of that very night -
    matches played while the sweep (and the audit's own simulation, nine minutes later) were running. That is the database being written
    to, not a pass that is not idempotent: it is counted apart (``pass_would_write_news``), and the next pass folds it in."""
    club, rival, man = a_man_with_three_matches(world)
    quiet = ph.audit(world.db, now=T0 + timedelta(days=21))
    assert quiet["pass_would_write"] == NOTHING and quiet["pass_would_write_news"] == NO_NEWS

    world.lineup(world.fixture(club, rival, 21), "home", [(man, True)])    # played after the sweep had read him
    evening = T0 + timedelta(days=21, hours=6)
    found = ph.audit(world.db, now=evening)
    assert found["pass_would_write"] == NOTHING, "not a defect"
    assert found["pass_would_write_news"] == {"players": 1, "spells": 1}
    assert ph.broken_invariants(found) == []
    seen = ph.build(world.db, sweep=True, now=evening)
    assert (seen.players_changed, seen.spells_written, seen.spells_deleted) == (1, 1, 1), "the pass itself still counts what it would write"
    assert (seen.news_players, seen.news_spells_written, seen.news_spells_deleted) == (1, 1, 1)
    assert world.spells(man) == [(0, world.provider(club), "Alpha FC", d(1), None, "lineup", 3, d(20), None)], "(and a dry run writes nothing)"

    folded = ph.build(world.db, apply=True, sweep=True, now=evening)
    assert folded.applied and folded.news_players == 1
    assert world.spells(man) == [(0, world.provider(club), "Alpha FC", d(1), None, "lineup", 4, d(21), None)]
    after = ph.audit(world.db, now=evening)
    assert after["pass_would_write"] == NOTHING and after["pass_would_write_news"] == NO_NEWS


def test_a_match_that_arrives_late_is_still_a_pass_that_would_write(world: World) -> None:
    """The case the sweep is there for - the sheet of an old match downloaded now - is NOT news: the man's last day of evidence is old."""
    club, rival, man = a_man_with_three_matches(world)
    world.lineup(world.fixture(club, rival, 5), "home", [(man, True)])
    found = ph.audit(world.db, now=T0 + timedelta(days=30))
    assert found["pass_would_write"] == {"spells": 1, "spells_deleted": 1, "caps": 0, "caps_deleted": 0}
    assert found["pass_would_write_news"] == NO_NEWS


def test_a_move_to_another_club_is_not_news_even_when_it_happened_today(world: World) -> None:
    club, rival, man = a_man_with_three_matches(world)
    new_club = world.team("Beta FC", False)
    world.transfer(man, 27, world.provider(new_club), world.provider(club), "€ 5M", names=("Beta FC", "Alpha FC"), listed=28)
    world.lineup(world.fixture(rival, new_club, 28), "away", [(man, True)])
    found = ph.audit(world.db, now=T0 + timedelta(days=28, hours=6))
    assert found["pass_would_write"] == {"spells": 2, "spells_deleted": 1, "caps": 0, "caps_deleted": 0}
    assert found["pass_would_write_news"] == NO_NEWS


def test_a_squad_list_read_again_is_news_for_the_audit(world: World) -> None:
    """Only the last day of evidence of a squad streak moves when the list that carried the man is read again."""
    club, man = world.team("Gamma FC", False), world.player()
    world.squad(club, man, 5, 30)
    ph.build(world.db, apply=True, sweep=True, now=T0 + timedelta(days=31))
    quiet = ph.audit(world.db, now=T0 + timedelta(days=31))
    assert quiet["pass_would_write"] == NOTHING and quiet["pass_would_write_news"] == NO_NEWS

    world.db.execute("UPDATE core.squad_members SET last_seen_at = %s WHERE provider_player_id = %s", (T0 + timedelta(days=31), man))
    found = ph.audit(world.db, now=T0 + timedelta(days=31, hours=6))
    assert found["pass_would_write"] == NOTHING and found["pass_would_write_news"] == {"players": 1, "spells": 1}
    # ... and the same list read again a week earlier than the audit is no longer news of the day
    stale = ph.audit(world.db, now=T0 + timedelta(days=38))
    assert stale["pass_would_write"] == {"spells": 1, "spells_deleted": 1, "caps": 0, "caps_deleted": 0}
    assert stale["pass_would_write_news"] == NO_NEWS


def test_the_audit_counts_the_sheets_that_look_crossed_by_the_history_month_by_month(world: World) -> None:
    """Plan F8.11 (decision 9): five men of one sheet whose only match for the club they are listed at was this one, against the club they
    come back to, is the signature of a sheet filed under the wrong side - a figure, never a correction."""
    a, b, c = world.team("Alpha FC", False), world.team("Beta FC", False), world.team("Gamma FC", False)
    five, four = [world.player() for _ in range(5)], [world.player() for _ in range(4)]
    for men in (five, four):
        # A, then B for one match - against A - then A again: the lone stint of each man is in the middle sheet
        world.lineup(world.fixture(a, c, 20), "home", [(m, True) for m in men])
    world.lineup(world.fixture(b, a, 25), "home", [(m, True) for m in five])
    world.lineup(world.fixture(b, a, 26), "home", [(m, True) for m in four])  # one man short: not enough to say anything
    for men in (five, four):
        world.lineup(world.fixture(a, c, 30), "home", [(m, True) for m in men])
    now = T0 + timedelta(days=40)
    ph.build(world.db, apply=True, sweep=True, now=now)
    figure = ph.sheets_that_look_crossed(world.db, now=now)
    month = (T0 + timedelta(days=25)).strftime("%Y-%m")
    assert figure["min_men"] == 5 and figure["sheets"] == 1 and figure["matches"] == 1
    assert figure["by_month"] == {month: {"sheets": 1, "matches": 1, "men": 5}}
    assert ph.audit(world.db, now=now)["sheets_look_crossed"]["sheets"] == 1, "the audit carries the figure"
    assert ph.broken_invariants(ph.audit(world.db, now=now)) == [], "and a figure is news, not a broken invariant"
    assert ph.sheets_that_look_crossed(world.db, now=T0 + timedelta(days=300), days=30)["sheets"] == 0, "only the last days are looked at"
