"""The people of a national-team match in the packet (plan F3, ``dossier.national``): where each player of the side plays and since when,
how he has been playing there, what he has done for his country - everything as of the packet's moment, and nothing of the match
itself or of what came after it."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from psycopg.rows import dict_row

from fbi.ai.packet import PacketBuilder
from fbi.intel import national
from fbi.people import player_history as ph
from fbi.providers.api_football.details import AbsenceRef
from tests.integration.conftest import Seed
from tests.integration.test_availability_history import DOUBT, KNEE, _answer
from tests.integration.test_player_history_store import T0, World, d, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

KICKOFF = T0 + timedelta(days=31, hours=5)   # 20:00
AT = KICKOFF - timedelta(minutes=30)         # the sheet was fetched an hour before the match: it is known by then


def settle(w: World, fixture: int, when: datetime | None = None) -> None:
    """The result of a match, recorded 3 hours after it began unless ``when`` says."""
    kickoff = w.one("SELECT kickoff_at FROM core.fixtures WHERE id = %s", fixture)
    w.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 1, 0, %s)",
                 (fixture, when or kickoff + timedelta(hours=3)))


def sheet(w: World, fixture: int, side: str, starters: dict[int, str], *, fetched: datetime | None = None) -> None:
    """A squad sheet with named starters, fetched an hour before the match unless ``fetched`` says."""
    w.lineup(fixture, side, [(p, True) for p in starters])
    for player, name in starters.items():
        w.db.execute("UPDATE core.fixture_lineup_players SET player_name = %s WHERE fixture_id = %s AND provider_player_id = %s",
                     (name, fixture, player))
    kickoff = w.one("SELECT kickoff_at FROM core.fixtures WHERE id = %s", fixture)
    w.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (fetched or kickoff - timedelta(hours=1), fixture))


def played(w: World, fixture: int, side: str, player: int, minutes: int, *, goals: int = 0, assists: int = 0, rating: float | None = None,
           substitute: bool = False, fetched: datetime | None = None) -> None:
    """The statistics of one player in one match, fetched 4 hours after it began unless ``fetched`` says."""
    w.stats(fixture, side, [(player, minutes, substitute)])
    kickoff = w.one("SELECT kickoff_at FROM core.fixtures WHERE id = %s", fixture)
    w.db.execute("UPDATE core.fixture_player_stats SET goals = %s, assists = %s, rating = %s, fetched_at = %s "
                 "WHERE fixture_id = %s AND provider_player_id = %s", (goals, assists, rating, fetched or kickoff + timedelta(hours=4),
                                                                      fixture, player))


def fx_of(w: World, fixture: int) -> dict[str, Any]:
    with w.db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, kickoff_at, home_team_id, away_team_id FROM core.fixtures WHERE id = %s", (fixture,))
        row = cur.fetchone()
    assert row is not None
    return row


class Squad:
    """Spain, three players and what they did before the match: two matches for their country, six for their clubs."""

    def __init__(self, w: World) -> None:
        self.w = w
        self.spain, self.italy = w.team("Spain", True), w.team("Italy", True)
        self.alpha, self.beta, self.rival = w.team("Alpha FC", False), w.team("Beta FC", False), w.team("Rival FC", False)
        self.p3, self.p2, self.p1 = w.player(), w.player(), w.player()      # (the ids grow against the minutes for the country)
        self.p4 = w.player()
        self.club_matches: dict[int, int] = {}
        w.transfer(self.p1, -100, w.provider(self.alpha), None, names=("Alpha FC", "Old FC"))
        w.transfer(self.p2, -60, w.provider(self.beta), None, names=("Beta FC", "Old FC"))
        # for their country: day 6 (all three start), day 21 (p1 and p2 start; p2 is taken off after 20 minutes)
        self.m1 = w.fixture(self.spain, self.italy, 6, national=True)
        sheet(w, self.m1, "home", {self.p1: "Pedro Uno", self.p2: "Pablo Dos", self.p3: "Paco Tres"})
        for p, minutes in ((self.p1, 90), (self.p2, 90), (self.p3, 60)):
            played(w, self.m1, "home", p, minutes)
        settle(w, self.m1)
        # day 9: the statistics of the players are not in yet, p2 is on the bench (we cannot say whether he played)
        self.m4 = w.fixture(self.spain, self.rival, 9, national=True)
        w.lineup(self.m4, "home", [(self.p2, False)])
        w.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (T0 + timedelta(days=9, hours=14), self.m4))
        settle(w, self.m4)
        # day 12: p3 starts and is taken off at once (0 minutes), p1 comes on for 25 minutes
        self.m3 = w.fixture(self.italy, self.spain, 12, national=True)
        w.lineup(self.m3, "away", [(self.p3, True), (self.p1, False)])
        w.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (T0 + timedelta(days=12, hours=14), self.m3))
        played(w, self.m3, "away", self.p3, 0)
        played(w, self.m3, "away", self.p1, 25, substitute=True)
        settle(w, self.m3)
        self.m2 = w.fixture(self.italy, self.spain, 21, national=True)
        sheet(w, self.m2, "away", {self.p1: "Pedro Uno", self.p2: "Pablo Dos"})
        played(w, self.m2, "away", self.p1, 90)
        played(w, self.m2, "away", self.p2, 20)
        settle(w, self.m2)
        # for the club: p1 plays six matches for Alpha (and one more of which he sat out), p2 one for Beta
        form = [(8, 90, 0, 0, 6.0), (12, 90, 1, 0, 7.0), (16, 80, 0, 1, 6.5), (20, 90, 0, 0, None), (24, 70, 2, 0, 8.0), (27, 90, 0, 0, 7.5)]
        for day, minutes, goals, assists, rating in form:
            club_match = self.club_matches[day] = w.fixture(self.alpha, self.rival, day)
            sheet(w, club_match, "home", {self.p1: "Pedro Uno"})
            played(w, club_match, "home", self.p1, minutes, goals=goals, assists=assists, rating=rating)
            settle(w, club_match)
        bench = w.fixture(self.alpha, self.rival, 29)
        sheet(w, bench, "home", {self.p1: "Pedro Uno"})
        played(w, bench, "home", self.p1, 0, substitute=True)
        settle(w, bench)
        beta_match = w.fixture(self.beta, self.rival, 15)
        sheet(w, beta_match, "home", {self.p2: "Pablo Dos"})
        played(w, beta_match, "home", self.p2, 45, goals=1, rating=6.8)
        settle(w, beta_match)
        # a club match of p2 so long ago that it says nothing about how he plays now
        old = w.fixture(self.beta, self.rival, -130)
        sheet(w, old, "home", {self.p2: "Pablo Dos"})
        played(w, old, "home", self.p2, 90, goals=4)
        settle(w, old)
        # the match itself, in the evening, with its sheet an hour before (and a man on the bench, who is not one of the eleven)
        self.target = w.fixture(self.spain, self.italy, 0, status="scheduled", national=True, at=KICKOFF)
        sheet(w, self.target, "home", {self.p1: "Pedro Uno", self.p2: "Pablo Dos", self.p3: "Paco Tres"})
        w.db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, is_starter, player_name) "
                     "VALUES (%s, 'home', 'api-football', %s, false, 'Pepe Cuatro')", (self.target, self.p4))

    def build(self) -> None:
        ph.build(self.w.db, apply=True, sweep=True)

    def block(self, *, at: datetime = AT, absent: dict[int, str] | None = None) -> dict[str, Any]:
        out = national.block(self.w.db, fx_of(self.w, self.target), at=at, absent=absent or {})
        assert out is not None
        return out


def test_a_club_match_has_no_national_block(world: World) -> None:  # noqa: F811
    club, rival, u21, italy = world.team("Alpha FC", False), world.team("Rival FC", False), world.team("Spain U21", True), world.team("Italy", True)
    unclassified = world.team("Mystery", None)
    for home, away in ((club, rival), (u21, rival), (unclassified, rival), (club, unclassified)):
        assert national.block(world.db, fx_of(world, world.fixture(home, away, 1)), at=AT, absent={}) is None
    block = national.block(world.db, fx_of(world, world.fixture(italy, u21, 2, national=True)), at=AT, absent={})
    assert block is not None and block["version"] == national.VERSION == "national-v1"
    assert block["away"] == {"team": "Spain U21", "senior": False}, "a youth side is named and nothing more"
    assert block["home"]["senior"] is True and block["home"]["squad"] == "none" and block["home"]["players"] == []


def test_the_eleven_of_the_match_with_their_club_their_form_and_their_record(world: World) -> None:  # noqa: F811
    s = Squad(world)
    s.build()
    block = s.block(absent={s.p2: "Knee Injury"})
    assert block["away"] == {"team": "Italy", "senior": True, "squad": "none", "squad_fixture": None, "squad_date": None, "n": 0,
                             "club_known": 0, "form_known": 0, "players": []}
    home = block["home"]
    assert (home["team"], home["senior"], home["squad"], home["squad_fixture"], home["squad_date"]) == ("Spain", True, "lineup", None, None)
    assert (home["n"], home["club_known"], home["form_known"]) == (3, 2, 2)
    assert [p["id"] for p in home["players"]] == [s.p1, s.p2, s.p3], "the ones with most minutes for the country first"
    p1, p2, p3 = home["players"]

    assert p1["name"] == "Pedro Uno" and p1["reported_out"] is None
    assert p1["club"] == {"id": world.provider(s.alpha), "name": "Alpha FC", "since": d(-100).isoformat(), "source": "transfer",
                          "last_seen": d(29).isoformat(), "last_seen_days_ago": 2}
    assert (p1["form"]["n"], p1["form"]["minutes"], p1["form"]["goals"], p1["form"]["assists"], p1["form"]["rating"]) == (5, 420, 3, 1, 7.25), \
        "the five newest he played (a match he sat out, with no minutes, is not one), the ratings that exist averaged"
    assert (p1["form"]["last_match"], p1["form"]["last_days_ago"], p1["form"]["last_fixture"]) == (d(27).isoformat(), 4, s.club_matches[27])
    assert p1["caps"] == {"squads": 3, "caps": 3, "starts": 2, "minutes": 205, "unknown": 0, "last_squad": d(21).isoformat(),
                          "last_squad_fixture": s.m2, "last_cap": d(21).isoformat(), "last_cap_fixture": s.m2, "last_cap_days_ago": 10}

    assert p2["reported_out"] == "Knee Injury" and p2["club"]["name"] == "Beta FC"
    assert (p2["form"]["n"], p2["form"]["minutes"], p2["form"]["goals"], p2["form"]["rating"]) == (1, 45, 1, 6.8)
    assert (p2["caps"]["squads"], p2["caps"]["caps"], p2["caps"]["starts"], p2["caps"]["minutes"], p2["caps"]["unknown"]) == (3, 2, 2, 110, 1)

    assert p3["club"] is None and p3["form"] is None, "nothing says where he plays: nothing is guessed"
    assert (p3["caps"]["squads"], p3["caps"]["caps"], p3["caps"]["starts"], p3["caps"]["minutes"], p3["caps"]["unknown"]) == (2, 1, 1, 60, 0)
    assert (p3["caps"]["last_squad_fixture"], p3["caps"]["last_cap_fixture"]) == (s.m3, s.m1), "his last squad is one he did not play"
    assert (p3["caps"]["last_squad"], p3["caps"]["last_cap"], p3["caps"]["last_cap_days_ago"]) == (d(12).isoformat(), d(6).isoformat(), 25)


def test_without_the_sheet_of_the_match_the_one_of_the_previous_match_stands_in_and_says_so(world: World) -> None:  # noqa: F811
    s = Squad(world)
    s.build()
    world.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (AT + timedelta(minutes=1), s.target))
    home = s.block()["home"]
    assert (home["squad"], home["squad_fixture"], home["squad_date"]) == ("last_match", s.m2, d(21).isoformat())
    assert [p["id"] for p in home["players"]] == [s.p1, s.p2], "the eleven of the match before: p3 did not start it"
    at_the_moment = s.block(at=AT + timedelta(minutes=1))["home"]
    assert at_the_moment["squad"] == "lineup" and at_the_moment["n"] == 3, "a sheet fetched at the very moment is known"


def test_the_previous_match_must_be_over_by_the_moment_and_have_a_sheet(world: World) -> None:  # noqa: F811
    s = Squad(world)
    world.db.execute("DELETE FROM core.fixture_lineups WHERE fixture_id = %s", (s.target,))
    world.db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s", (AT + timedelta(hours=1), s.m2))
    home = s.block()["home"]
    assert (home["squad"], home["squad_fixture"]) == ("last_match", s.m3), "the match whose result was not recorded yet is not 'the previous'"
    assert [p["id"] for p in home["players"]] == [s.p3], "(only the starters of that match)"
    world.db.execute("DELETE FROM core.fixture_lineups WHERE fixture_id = %s", (s.m3,))
    assert s.block()["home"]["squad"] == "none" and s.block()["home"]["players"] == []
    later = world.fixture(s.spain, s.rival, 40, national=True)     # after the match: never 'the previous'
    sheet(world, later, "home", {s.p1: "Pedro Uno"})
    settle(world, later)
    assert s.block()["home"]["squad"] == "none"


def test_nothing_that_came_after_the_moment_is_read(world: World) -> None:  # noqa: F811
    s = Squad(world)
    # a club match he played before the moment whose result was recorded after it, and the statistics of another fetched after it
    unsettled = world.fixture(s.alpha, s.rival, 30)
    sheet(world, unsettled, "home", {s.p1: "Pedro Uno"})
    played(world, unsettled, "home", s.p1, 90, goals=5)
    settle(world, unsettled, AT + timedelta(minutes=10))
    world.db.execute("UPDATE core.fixture_player_stats SET fetched_at = %s WHERE provider_player_id = %s AND minutes = 70",
                     (AT + timedelta(minutes=5), s.p1))
    # a match for the country that began before the moment and was settled after it, and one that came after the match
    unsettled_cap = world.fixture(s.spain, s.rival, 30, national=True)
    sheet(world, unsettled_cap, "home", {s.p1: "Pedro Uno"})
    played(world, unsettled_cap, "home", s.p1, 90)
    settle(world, unsettled_cap, AT + timedelta(minutes=10))
    after = world.fixture(s.spain, s.rival, 40, national=True)
    sheet(world, after, "home", {s.p1: "Pedro Uno"})
    played(world, after, "home", s.p1, 90)
    settle(world, after, AT - timedelta(hours=3))    # (a result before the match was played: only its kick-off keeps it out)
    # a move after the moment: the streak at the club he is at goes on being the one of the day, and its last sign is cut at that day
    world.transfer(s.p1, 40, world.provider(s.beta), world.provider(s.alpha), names=("Beta FC", "Alpha FC"))
    later_club_match = world.fixture(s.alpha, s.rival, 35)
    sheet(world, later_club_match, "home", {s.p1: "Pedro Uno"})
    played(world, later_club_match, "home", s.p1, 90, goals=3, fetched=AT - timedelta(hours=2))
    settle(world, later_club_match, AT - timedelta(hours=3))    # (a result before the match was played: only its kick-off keeps it out)
    s.build()

    p1 = s.block()["home"]["players"][0]
    assert p1["id"] == s.p1
    assert p1["club"]["name"] == "Alpha FC" and p1["club"]["last_seen"] == d(31).isoformat() and p1["club"]["last_seen_days_ago"] == 0
    assert (p1["form"]["n"], p1["form"]["goals"], p1["form"]["minutes"]) == (5, 1, 90 + 90 + 80 + 90 + 90), \
        "one match settled after the moment, one with statistics fetched after it and one after the match itself: all out"
    assert (p1["caps"]["squads"], p1["caps"]["minutes"], p1["caps"]["last_squad_fixture"]) == (3, 205, s.m2)
    # the same man, looked at from a later moment, does see them
    seen_later = national.block(world.db, fx_of(world, s.target), at=KICKOFF - timedelta(minutes=1), absent={})
    assert seen_later is not None
    assert seen_later["home"]["players"][0]["caps"]["squads"] == 4 and seen_later["home"]["players"][0]["form"]["goals"] == 7


def test_only_matches_for_a_club_make_the_form(world: World) -> None:  # noqa: F811
    s = Squad(world)
    mystery = world.team("Mystery", None)
    for home, away, national_match in ((mystery, s.rival, False), (s.spain, s.italy, True)):
        match = world.fixture(home, away, 26, national=national_match)
        sheet(world, match, "home", {s.p1: "Pedro Uno"})
        played(world, match, "home", s.p1, 90, goals=9)
        settle(world, match)
    s.build()
    p1 = s.block()["home"]["players"][0]
    assert p1["form"]["goals"] == 3, "the matches of a national side and of a team nobody has classified are not 'club' matches"


def test_a_club_with_no_name_in_the_streak_is_named_from_the_catalogue(world: World) -> None:  # noqa: F811
    s = Squad(world)
    s.build()
    world.db.execute("UPDATE core.player_spells SET team_name = NULL WHERE provider_team_id = %s", (world.provider(s.beta),))
    home = s.block()["home"]
    assert [p["club"]["name"] for p in home["players"] if p["club"]] == ["Alpha FC", "Beta FC"]
    world.db.execute("UPDATE core.player_spells SET team_name = NULL")
    assert [p["club"]["name"] for p in s.block()["home"]["players"] if p["club"]] == ["Alpha FC", "Beta FC"]


def test_the_packet_carries_the_block_and_a_club_match_carries_none(world: World) -> None:  # noqa: F811
    s = Squad(world)
    s.build()
    packet = PacketBuilder(world.db).build(s.target, at=AT)
    assert packet is not None
    block = packet.content["dossier"]["national"]
    assert packet.content["dossier"]["version"] == "dossier-v3" and block["version"] == "national-v1"
    assert block["home"]["n"] == 3 and [p["id"] for p in block["home"]["players"]] == [s.p1, s.p2, s.p3]
    club_match = PacketBuilder(world.db).build(world.fixture(s.alpha, s.rival, 44, status="scheduled"), at=AT)
    assert club_match is not None and club_match.content["dossier"]["national"] is None


def test_the_match_itself_is_never_the_previous_match_not_even_when_it_has_been_played(world: World) -> None:  # noqa: F811
    s = Squad(world)
    world.db.execute("DELETE FROM core.fixture_lineups WHERE fixture_id = %s", (s.target,))
    settle(world, s.target)
    home = s.block(at=KICKOFF + timedelta(hours=4))["home"]       # looked at afterwards (a replay of the packet)
    assert (home["squad"], home["squad_fixture"]) == ("last_match", s.m2)


def test_a_result_recorded_at_the_very_moment_is_known(world: World) -> None:  # noqa: F811
    s = Squad(world)
    world.db.execute("DELETE FROM core.fixture_lineups WHERE fixture_id = %s", (s.target,))
    world.db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s", (AT, s.m2))
    s.build()
    assert s.block()["home"]["squad_fixture"] == s.m2
    assert s.block()["home"]["players"][0]["caps"]["last_squad_fixture"] == s.m2
    world.db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s", (AT + timedelta(microseconds=1), s.m2))
    assert s.block()["home"]["squad_fixture"] == s.m3
    assert s.block()["home"]["players"][0]["caps"]["last_squad_fixture"] == s.m3


def test_a_previous_match_more_than_400_days_old_is_too_old_to_stand_in(world: World) -> None:  # noqa: F811
    spain, italy, p = world.team("Spain", True), world.team("Italy", True), world.player()
    old = world.fixture(spain, italy, 31 - 410, national=True)
    sheet(world, old, "home", {p: "Pedro Uno"})
    settle(world, old)
    target = world.fixture(spain, italy, 0, status="scheduled", national=True, at=KICKOFF)
    far = national.block(world.db, fx_of(world, target), at=AT, absent={})
    assert far is not None and far["home"]["squad"] == "none"
    recent = world.fixture(spain, italy, 31 - 390, national=True)
    sheet(world, recent, "home", {p: "Pedro Uno"})
    settle(world, recent)
    block = national.block(world.db, fx_of(world, target), at=AT, absent={})
    assert block is not None and (block["home"]["squad"], block["home"]["squad_fixture"]) == ("last_match", recent)


def test_the_classification_of_predigol_wins_over_the_providers_flag(world: World) -> None:  # noqa: F811
    country = world.team("Odd Land", False)         # the provider says it is a club; PrediGol decided it is a national side
    club = world.team("Odd FC", True)               # the provider says national; PrediGol decided it is a club
    rival, italy, p = world.team("Rival FC", False), world.team("Italy", True), world.player()
    for team, national_side in ((country, True), (club, False)):
        world.db.execute("INSERT INTO core.team_kind (team_id, is_national, basis, competitive_club_matches, national_matches, "
                         "club_friendly_matches, rule_version, refreshed_at) VALUES (%s, %s, 'test', 5, 0, 0, 'test', now())",
                         (team, national_side))
    made = world.fixture(club, rival, 20)
    sheet(world, made, "home", {p: "Pedro Uno"})
    played(world, made, "home", p, 90, goals=2)
    settle(world, made)
    target = world.fixture(country, italy, 0, status="scheduled", national=True, at=KICKOFF)
    sheet(world, target, "home", {p: "Pedro Uno"})
    ph.build(world.db, apply=True, sweep=True)
    block = national.block(world.db, fx_of(world, target), at=AT, absent={})
    assert block is not None and block["home"]["senior"] is True, "classified as a national side"
    assert block["home"]["players"][0]["form"]["goals"] == 2, "and the match of 'Odd FC' is a match for a club"
    assert block["home"]["players"][0]["club"]["name"] == "Odd FC"


def test_the_day_is_the_day_of_the_moment_and_not_the_day_of_the_match(world: World) -> None:  # noqa: F811
    s = Squad(world)
    s.build()
    yesterday = KICKOFF - timedelta(days=1)       # (the sheet of the match is not known yet: the previous match stands in)
    home = s.block(at=yesterday)["home"]
    assert home["squad"] == "last_match"
    p1 = home["players"][0]
    assert p1["id"] == s.p1
    assert (p1["club"]["last_seen"], p1["club"]["last_seen_days_ago"]) == (d(29).isoformat(), 1)
    assert (p1["form"]["last_match"], p1["form"]["last_days_ago"]) == (d(27).isoformat(), 3)
    assert p1["caps"]["last_cap_days_ago"] == 9


def test_the_players_reported_out_are_the_latest_answer_as_of_the_moment(world: World, seed: Seed) -> None:  # noqa: F811
    """Plan F3, no stale absence in the packet: the block marks whom the provider's newest answer by the packet's moment names - a man a
    later answer cleared is back - and the packet of an earlier moment still says what was known then."""
    s = Squad(world)
    s.build()
    row = world.db.execute("SELECT provider_fixture_id, competition_season_id FROM core.fixtures WHERE id = %s", (s.target,)).fetchone()
    assert row is not None
    provider_fixture, season = row
    spain = world.provider(s.spain)
    t1, t2 = KICKOFF - timedelta(hours=10), KICKOFF - timedelta(hours=5)

    def ref(player: int, what: tuple[str, str]) -> AbsenceRef:
        return AbsenceRef(provider_fixture, player, spain, f"Player {player}", what[0], what[1])

    league: Any = SimpleNamespace(season=season)      # (all the answer helper of the availability tests needs of its world)
    _answer(world.db, seed, league, t1, [ref(s.p1, KNEE), ref(s.p2, DOUBT)])
    _answer(world.db, seed, league, t2, [ref(s.p2, DOUBT)])                       # p1 has recovered

    def reported(at: datetime) -> dict[int, str | None]:
        built = PacketBuilder(world.db).build(s.target, at=at)
        assert built is not None
        return {p["id"]: p["reported_out"] for p in built.content["dossier"]["national"]["home"]["players"]}

    assert reported(AT) == {s.p1: None, s.p2: DOUBT[0], s.p3: None}, "p1 is not out any more; p3 was never named"
    assert reported(t1 + timedelta(hours=1)) == {s.p1: KNEE[0], s.p2: DOUBT[0]}, "built for an hour after the first answer: what was known then"
