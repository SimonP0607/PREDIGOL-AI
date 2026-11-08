"""The zones of the league tables PrediGol held on 8 Nov 2026, read with stakes-v5 (UX-066).

Every description below is the provider's own, read from production (GET /competitions/{id}/standings, the 41 league
tables of that day, and the cup tables), with the kind each zone has. stakes-v4 (UX-064) read the Liga MX's liguilla right
and made a "playoff" of the Championship's, Serie B's and League One's promotion play-offs, the Eredivisie's Conference
League play-offs and the title groups of Greece, Austria and Egypt; stakes-v3 read League One's "Promotion - Championship"
and the Championship's play-offs as international places ("Champions" inside "Championship"), and Colombia's "Post season
qualification" and Denmark's "Play-offs" as a promotion. A new wording of the provider belongs here first."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from fbi.ai.context import STAKES_RULE, TableRow, stakes, table_zones, zone_kind

P = "Promotion - "
CL_LP, CL_Q = P + "Champions League (League phase)", P + "Champions League (Qualification)"
EL_LP, EL_Q = P + "Europa League (League phase)", P + "Europa League (Qualification)"
ECL_Q = P + "Conference League (Qualification)"
# (competition, group key, teams, [(from, to, description, expected kind)])
TABLES = [
    ("Premier League ENG", "Premier League", 20, [(1, 1, CL_LP, "title"), (2, 4, CL_LP, "europe"), (5, 5, EL_LP, "europe"),
                                                  (18, 20, "Relegation - Championship", "relegation")]),
    ("Ligue 1", "Ligue 1", 18, [(1, 1, "Champions League league stage", "title"), (2, 3, "Champions League league stage", "europe"),
                                (4, 4, "Qualifying", "europe"), (5, 5, "Europa League league stage", "europe"), (6, 6, "Play-offs", "europe"),
                                (16, 16, "Relegation Playoffs", "relegation"), (17, 18, "Relegation", "relegation")]),
    ("League One SCO", "Division2", 10, [(1, 1, P + "Championship", "promotion"), (2, 4, P + "League One (Promotion - Play Offs)", "promotion"),
                                         (9, 9, "League One (Promotion - Play Offs)", "promotion"), (10, 10, "Relegation - League Two", "relegation")]),
    ("Bundesliga GER", "Bundesliga", 18, [(1, 1, "Champions League league stage", "title"), (2, 4, "Champions League league stage", "europe"),
                                          (5, 5, "Europa League league stage", "europe"), (6, 6, "Qualifying", "europe"),
                                          (16, 16, "Relegation Playoffs", "relegation"), (17, 18, "Relegation", "relegation")]),
    ("LaLiga", "Primera División", 20, [(1, 1, CL_LP, "title"), (2, 4, CL_LP, "europe"), (5, 5, EL_LP, "europe"), (6, 6, ECL_Q, "europe"),
                                        (18, 20, "Relegation - LaLiga2", "relegation")]),
    ("Superliga DEN", "Superliga", 12, [(1, 6, "Play-offs", "playoff"), (7, 12, "Relegation Playoffs", "relegation")]),
    ("J2 League", "J2 League", 20, [(1, 2, "Promotion", "promotion"), (3, 6, "Promotion Play-offs", "promotion"), (18, 20, "Relegation", "relegation")]),
    ("Serie A ITA", "Serie A", 20, [(1, 1, "Champions League league stage", "title"), (2, 4, "Champions League league stage", "europe"),
                                    (5, 5, "Europa League league stage", "europe"), (6, 6, "Play-offs", "europe"), (18, 20, "Relegation", "relegation")]),
    ("Premier League UKR", "Premier League", 16, [(1, 1, CL_LP, "title"), (2, 3, ECL_Q, "europe"), (13, 14, "Persha Liga (Relegation)", "relegation"),
                                                  (15, 16, "Relegation - Persha Liga", "relegation")]),
    ("Segunda ESP", "Segunda", 22, [(1, 2, P + "LaLiga", "promotion"), (3, 6, P + "LaLiga2 (Promotion - Play Offs: Semi-finals)", "promotion"),
                                    (19, 22, "Relegation", "relegation")]),
    ("Premiership SCO", "Premier League", 12, [(1, 1, P + "Premiership (Championship Group)", "title"),
                                               (2, 6, P + "Premiership (Championship Group)", "europe"),
                                               (7, 12, "Premiership (Relegation Group)", "relegation")]),
    ("MLS East", "Eastern Conference", 15, [(1, 7, P + "MLS (Play Offs: 1/8-finals)", "playoff"), (8, 9, P + "MLS (Play Offs: 1/16-finals)", "playoff")]),
    ("MLS West", "Western Conference", 15, [(1, 7, P + "MLS (Play Offs: 1/8-finals)", "playoff"), (8, 9, P + "MLS (Play Offs: 1/16-finals)", "playoff")]),
    ("Ligue 2", "Ligue 2", 18, [(1, 2, P + "Ligue 1", "promotion"), (3, 3, P + "Ligue 1 (Promotion - Play Offs: Final)", "promotion"),
                                (4, 5, P + "Ligue 1 (Promotion - Play Offs: Semi-finals)", "promotion"), (16, 16, "Ligue 2 (Relegation)", "relegation"),
                                (17, 18, "Relegation - Ligue 3", "relegation")]),
    ("Premier League RUS", "Premier League", 16, [(13, 14, "Premier League (Relegation)", "relegation"), (15, 16, "Relegation - FNL", "relegation")]),
    ("Premier League EGY", "Premier League", 20, [(1, 1, P + "Premier League (Championship Group)", "title"),
                                                  (2, 6, P + "Premier League (Championship Group)", "europe"),
                                                  (7, 20, P + "Premier League (Relegation Group)", "relegation")]),
    ("NWSL", "Nwsl Women", 16, [(1, 8, P + "NWSL Women (Play Offs: Quarter-finals)", "playoff")]),
    ("Primeira Liga", "Primeira Liga", 18, [(1, 1, CL_LP, "title"), (2, 2, CL_LP, "europe"), (3, 3, CL_Q, "europe"), (4, 4, EL_Q, "europe"),
                                            (5, 5, ECL_Q, "europe"), (16, 16, "Liga Portugal (Relegation)", "relegation"),
                                            (17, 18, "Relegation - Liga Portugal 2", "relegation")]),
    ("Eredivisie", "Eredivisie", 18, [(1, 1, CL_LP, "title"), (2, 2, CL_Q, "europe"), (3, 3, EL_Q, "europe"),
                                      (4, 7, P + "Eredivisie (Conference League - Play Offs)", "europe"), (16, 16, "Eredivisie (Relegation)", "relegation"),
                                      (17, 18, "Relegation - Eerste Divisie", "relegation")]),
    ("Allsvenskan", "Allsvenskan", 16, [(1, 3, "Qualifying", "other"), (14, 14, "Relegation Playoffs", "relegation"), (15, 16, "Relegation", "relegation")]),
    ("Serie B ITA", "Serie B", 20, [(1, 2, P + "Serie A", "promotion"), (3, 4, P + "Serie B (Play Offs: Semi-finals)", "promotion"),
                                    (5, 8, P + "Serie B (Play Offs: Quarter-finals)", "promotion"), (16, 17, "Serie B (Play Out)", "other"),
                                    (18, 20, "Relegation", "relegation")]),
    ("Liga MX", "Liga MX: Apertura", 18, [(1, 8, P + "Liga MX (Apertura - Play Offs: Quarter-finals)", "playoff")]),
    ("Super Lig", "Süper Lig", 18, [(1, 1, CL_LP, "title"), (2, 2, CL_Q, "europe"), (3, 3, EL_Q, "europe"), (4, 4, ECL_Q, "europe"),
                                    (16, 18, "Relegation - 1. Lig", "relegation")]),
    ("Eliteserien", "Eliteserien", 16, [(1, 1, CL_Q, "title"), (2, 2, CL_Q, "europe"), (3, 4, ECL_Q, "europe"), (14, 14, "Eliteserien (Relegation)", "relegation"),
                                        (15, 16, "Relegation - OBOS-ligaen", "relegation")]),
    ("J1 League", "J-League", 20, [(1, 1, P + "AFC Champions League (League phase)", "title"), (2, 3, P + "AFC Champions League (League phase)", "europe"),
                                   (18, 20, "Relegation - J2 League", "relegation")]),
    ("Pro League BEL", "Pro League", 18, [(1, 1, CL_LP, "title"), (2, 2, CL_Q, "europe"), (3, 3, EL_Q, "europe"), (4, 4, ECL_Q, "europe"),
                                          (17, 18, "Relegation - Challenger Pro League", "relegation")]),
    ("League Two ENG", "League Two", 24, [(1, 3, P + "League One", "promotion"), (4, 7, P + "League Two (Play Offs: Semi-finals)", "promotion"),
                                          (23, 24, "Relegation - National League", "relegation")]),
    ("Super League GRE", "Super League", 14, [(1, 1, P + "Super League (Championship Group)", "title"), (2, 4, P + "Super League (Championship Group)", "europe"),
                                              (5, 8, P + "Super League (Conference League Group)", "europe"), (9, 14, "Super League (Relegation Group)", "relegation")]),
    ("2. Bundesliga", "2. Bundesliga", 18, [(1, 2, "Promotion", "promotion"), (3, 3, "Promotion Play-offs", "promotion"),
                                            (16, 16, "Relegation Playoffs", "relegation"), (17, 18, "Relegation", "relegation")]),
    ("League One ENG", "League One", 24, [(1, 2, P + "Championship", "promotion"), (3, 6, P + "League One (Play Offs)", "promotion"),
                                          (21, 24, "Relegation - League Two", "relegation")]),
    ("Serie B BRA", "Serie B", 20, [(1, 2, "Promotion", "promotion"), (3, 6, "Promotion Play-offs", "promotion"), (17, 20, "Relegation", "relegation")]),
    ("A-League", "A-League", 12, [(1, 2, P + "A-League (Play Offs: Semi-finals)", "playoff"), (3, 6, P + "A-League (Play Offs: Quarter-finals)", "playoff")]),
    ("Championship ENG", "Championship", 24, [(1, 2, P + "Premier League", "promotion"), (3, 4, P + "Championship (Play Offs: Semi-finals)", "promotion"),
                                              (5, 8, P + "Championship (Play Offs: Quarter-finals)", "promotion"), (22, 24, "Relegation - League One", "relegation")]),
    ("Serie A BRA", "Serie A", 20, [(1, 1, P + "Copa Libertadores (Group Stage)", "title"), (2, 4, P + "Copa Libertadores (Group Stage)", "europe"),
                                    (5, 5, P + "Copa Libertadores (Qualification)", "europe"), (6, 11, P + "Copa Sudamericana (Group Stage)", "europe"),
                                    (17, 20, "Relegation - Serie B", "relegation")]),
    ("Primera A COL", "Clausura", 20, [(1, 8, "Post season qualification", "playoff")]),
    ("Championship SCO", "Division1", 10, [(1, 1, P + "Premiership", "promotion"), (2, 2, P + "Premiership (Promotion: Semi-finals)", "promotion"),
                                           (3, 4, P + "Premiership (Promotion: Quarter-finals)", "promotion"), (9, 9, "Championship (Relegation)", "relegation"),
                                           (10, 10, "Relegation - League One", "relegation")]),
    ("Liga Profesional ARG A", "Clausura - Group A", 15, [(1, 8, "Knockout Phase", "playoff")]),
    ("Liga Profesional ARG B", "Clausura - Group B", 15, [(1, 8, "Knockout Phase", "playoff")]),
    ("J3 League", "J3 League", 20, [(1, 2, P + "J2 League", "promotion"), (3, 6, P + "J3 League (Promotion - Play Offs)", "promotion"),
                                    (19, 19, "J3 League (Relegation)", "relegation"), (20, 20, "Relegation", "relegation")]),
    ("Bundesliga AUT", "Bundesliga", 12, [(1, 1, P + "Bundesliga (Championship Group)", "title"), (2, 6, P + "Bundesliga (Championship Group)", "europe"),
                                          (7, 12, "Bundesliga (Relegation Group)", "relegation")]),
]



def descriptions(table: tuple[str, str, int, list[tuple[int, int, str, str]]]) -> list[str | None]:
    """The description of every rank of the table: ranks outside the listed runs have none."""
    _, _, n, runs = table
    at = {rank: d for lo, hi, d, _ in runs for rank in range(lo, hi + 1)}
    return [at.get(rank) for rank in range(1, n + 1)]


def rows(table: tuple[str, str, int, list[tuple[int, int, str, str]]], points: Sequence[int] | None = None) -> list[TableRow]:
    """The table as rows: 2 points apart unless ``points`` says otherwise, 30 played."""
    descs = descriptions(table)
    pts = list(points) if points is not None else [2 * (len(descs) - i) for i in range(len(descs))]
    return [TableRow(team_id=rank, rank=rank, points=pts[rank - 1], played=30, description=d)
            for rank, d in enumerate(descs, start=1)]


@pytest.mark.parametrize("table", TABLES, ids=[t[0] for t in TABLES])
def test_every_zone_of_the_real_tables_reads_as_what_it_is(table: tuple[str, str, int, list[tuple[int, int, str, str]]]) -> None:
    zones = table_zones(descriptions(table))
    for lo, hi, d, want in table[3]:
        for rank in range(lo, hi + 1):
            expected = "europe" if want == "title" and rank != 1 else want
            assert zone_kind(d, rank, table=zones) == expected, f"{table[0]}, {rank}.º: {d}"


SENDS_UP = ("Championship ENG", "Serie B ITA", "League One ENG", "League Two ENG", "J3 League", "Segunda ESP", "Ligue 2")
SENDS_NOBODY_UP = ("Liga MX", "MLS East", "A-League", "NWSL", "Primera A COL", "Superliga DEN", "Super League GRE", "Bundesliga AUT")


def by_name(name: str) -> tuple[str, str, int, list[tuple[int, int, str, str]]]:
    return next(t for t in TABLES if t[0] == name)


@pytest.mark.parametrize("name", SENDS_UP)
def test_the_own_play_offs_of_a_division_that_sends_teams_up_are_a_promotion(name: str) -> None:
    assert table_zones(descriptions(by_name(name))).sends_up


@pytest.mark.parametrize("name", SENDS_NOBODY_UP)
def test_a_league_that_sends_nobody_up_is_seen_as_one(name: str) -> None:
    assert not table_zones(descriptions(by_name(name))).sends_up


def test_championship_is_not_champions() -> None:
    zones = table_zones(descriptions(by_name("League One ENG")))
    assert not zones.top_flight, "League One sends nobody abroad: «Promotion - Championship» is not the Champions League"
    assert zone_kind(P + "Championship", 1, table=zones) == "promotion"


CUPS = {
    "Champions League": [P + "Champions League (Play Offs: 1/8-finals)"] * 8 + [P + "Champions League (Play Offs: 1/16-finals)"] * 16 + [None] * 12,
    "Europa League": [P + "Europa League (Play Offs: 1/8-finals)"] * 8 + [P + "Europa League (Play Offs: 1/16-finals)"] * 16 + [None] * 12,
    "Champions League Women": [P + "UEFA Champions League Women (Play Offs: Quarter-finals)", P + "UEFA Champions League Women (Play Offs: 1/8-finals)", None],
    "Turkish Cup": [P + "Turkish Cup (Play Offs)"] * 2 + [None] * 2,
    "Africa Cup of Nations": [P + "Africa Cup of Nations (Play Offs)"] * 2 + [None] * 2,
    "World Cup": ["Round of 32"] * 2 + [None] * 2,
}


@pytest.mark.parametrize("name", list(CUPS), ids=list(CUPS))
def test_the_knock_out_round_of_a_competitions_own_league_phase_is_a_playoff(name: str) -> None:
    descs = CUPS[name]
    zones = table_zones(descs)
    assert {zone_kind(d, rank, table=zones) for rank, d in enumerate(descs, start=1) if d} == {"playoff"}


def test_the_nations_league_still_promotes() -> None:
    descs = ["Promotion", "Promotion Play-offs", None, "Relegation"]
    zones = table_zones(descs)
    assert [zone_kind(d, rank, table=zones) for rank, d in enumerate(descs, start=1)] == ["promotion", "promotion", None, "relegation"]


def test_pumas_eleventh_fight_for_the_liguilla_not_for_promotion() -> None:
    # Liga MX, Apertura 2026 after 16 of 17 rounds: the 8th has 22 points, Pumas (11th) 21.
    points = [36, 33, 31, 29, 27, 25, 23, 22, 22, 21, 21, 20, 18, 17, 15, 14, 12, 10]
    pumas = stakes(rows(by_name("Liga MX"), points), 11, 1)
    assert pumas is not None
    assert (pumas.zone, pumas.zone_above, pumas.gap_up, pumas.pressure) == (None, "playoff", 1, "playoff")


def test_the_championships_play_off_places_are_fought_for_as_a_promotion() -> None:
    ninth = stakes(rows(by_name("Championship ENG")), 9, 10)
    assert ninth is not None and ninth.zone_above == "promotion" and ninth.pressure == "promotion"
    fifth = stakes(rows(by_name("Championship ENG")), 5, 10)
    assert fifth is not None and fifth.zone == "promotion" and fifth.pressure == "promotion"


def test_the_eredivisies_conference_play_offs_are_international_places() -> None:
    eighth = stakes(rows(by_name("Eredivisie")), 8, 10)
    assert eighth is not None and eighth.zone_above == "europe" and eighth.pressure == "europe"


def test_colombias_post_season_is_a_playoff_never_a_promotion() -> None:
    ninth = stakes(rows(by_name("Primera A COL")), 9, 4)
    assert ninth is not None and ninth.zone_above == "playoff" and ninth.pressure == "playoff"


def test_the_title_group_reads_as_before() -> None:
    zones = table_zones(descriptions(by_name("Super League GRE")))
    assert zone_kind(P + "Super League (Championship Group)", 1, table=zones) == "title"
    assert zone_kind(P + "Super League (Championship Group)", 3, table=zones) == "europe"


def test_the_rule_version() -> None:
    assert STAKES_RULE == "stakes-v5"
