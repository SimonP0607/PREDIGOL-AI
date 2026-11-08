"""The kind of a table zone in a first division (plan Inicio, step 1.2, UX-031; rule stakes-v3).

The tables of 7 Nov 2026 reached PrediGol with these provider descriptions: Serie A put "Play-offs" on the 6th and the
Bundesliga "Qualifying", the first four places of both read "Champions League league stage", and LaLiga words the same
places "Promotion - Champions League (League phase)". stakes-v2 turned "Play-offs" into a promotion ("Frosinone, 6th, is in
the promotion zone"), lost "Qualifying" and made the 2nd place a title ("Dortmund, 2nd, is in the title zone"). In a first
division no zone is a promotion, the title is the first place only, and the same places read the same whatever the wording."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from fbi.ai.context import STAKES_RULE, TableRow, is_top_flight, league_of, stakes, zone_kind
from fbi.intel.scenarios import table_effect

SERIE_A = {**dict.fromkeys(range(1, 5), "Champions League league stage"), 5: "Europa League league stage",
           6: "Play-offs", **dict.fromkeys(range(7, 18)), **dict.fromkeys(range(18, 21), "Relegation")}
BUNDESLIGA = {**dict.fromkeys(range(1, 5), "Champions League league stage"), 5: "Europa League league stage",
              6: "Qualifying", **dict.fromkeys(range(7, 16)), 16: "Relegation Playoffs",
              **dict.fromkeys(range(17, 19), "Relegation")}
LALIGA = {**dict.fromkeys(range(1, 5), "Promotion - Champions League (League phase)"),
          5: "Promotion - Europa League (League phase)", 6: "Promotion - Conference League (Qualification)",
          **dict.fromkeys(range(7, 18)), **dict.fromkeys(range(18, 21), "Relegation - LaLiga2")}
SERIE_B = {**dict.fromkeys(range(1, 3), "Promotion - Serie A"), **dict.fromkeys(range(3, 9), "Promotion - Serie A (Play-offs)"),
           **dict.fromkeys(range(9, 17)), **dict.fromkeys(range(17, 21), "Relegation - Serie C")}
CHAMPIONS_LEAGUE = {**dict.fromkeys(range(1, 9), "Promotion - Champions League (Round of 16)"),
                    **dict.fromkeys(range(9, 25), "Promotion - Champions League (Knockout Phase Play-offs)"),
                    **dict.fromkeys(range(25, 37))}


def table(zones: Mapping[int, str | None]) -> list[TableRow]:
    """One row per rank, 3 points apart, 10 played of 38."""
    return [TableRow(team_id=rank, rank=rank, points=40 - rank * 3 + 60, played=10, description=d)
            for rank, d in zones.items()]


def kinds(zones: Mapping[int, str | None]) -> dict[int, str | None]:
    top = is_top_flight(zones.values())
    return {rank: zone_kind(d, rank, top_flight=top) for rank, d in zones.items()}


@pytest.mark.parametrize("zones", [SERIE_A, BUNDESLIGA, LALIGA], ids=["Serie A", "Bundesliga", "LaLiga"])
def test_the_same_places_read_the_same_in_every_first_division(zones: Mapping[int, str | None]) -> None:
    got = kinds(zones)
    assert got[1] == "title"
    assert [got[r] for r in (2, 3, 4, 5, 6)] == ["europe"] * 5, "places 2 to 6 are international places, never a title or a promotion"
    assert "promotion" not in got.values(), "a first division has no promotion zone"
    assert got[max(zones)] == "relegation"


def test_the_relegation_playoffs_of_the_bundesliga_are_relegation() -> None:
    assert kinds(BUNDESLIGA)[16] == "relegation"


def test_serie_a_no_longer_puts_the_sixth_in_a_promotion_zone() -> None:
    sixth = stakes(table(SERIE_A), 6, 28)
    assert sixth is not None and sixth.zone == "europe"
    assert sixth.zone_above == "europe" and sixth.zone_below != "promotion"


def test_dortmund_second_is_in_international_places_not_the_title_zone() -> None:
    second = stakes(table(BUNDESLIGA), 2, 24)
    assert second is not None and second.zone == "europe"
    leader = stakes(table(BUNDESLIGA), 1, 24)
    assert leader is not None and leader.zone == "title"


def test_the_rule_version_says_the_reading_changed() -> None:
    assert STAKES_RULE == "stakes-v4"
    first = stakes(table(SERIE_A), 3, 28)
    assert first is not None and first.as_json()["rule"] == "stakes-v4"


def test_a_second_division_keeps_its_promotion_zones() -> None:
    assert not is_top_flight(SERIE_B.values())
    got = kinds(SERIE_B)
    assert got[1] == got[2] == "promotion"
    assert got[5] == "promotion", "the promotion play-offs of a second division are a promotion"
    assert got[20] == "relegation"


def test_a_cup_table_is_not_read_as_a_first_division() -> None:
    assert not is_top_flight(CHAMPIONS_LEAGUE.values()), "it sends nobody down"
    got = kinds(CHAMPIONS_LEAGUE)
    assert got[1] == "europe", "the Champions League's own phases keep the stakes-v2 reading"


def test_without_the_table_the_reading_is_the_one_of_stakes_v2() -> None:
    assert zone_kind("Champions League league stage") == "title"
    assert zone_kind("Play-offs") == "promotion"
    assert zone_kind("Promotion - Champions League (League phase)") == "europe"
    assert zone_kind(None) is None


def test_a_table_without_zones_is_not_a_first_division() -> None:
    assert not is_top_flight([None, None, ""])


@pytest.mark.parametrize("zones", [SERIE_A, BUNDESLIGA], ids=["Serie A", "Bundesliga"])
def test_the_scenarios_name_the_same_zones(zones: Mapping[int, str | None]) -> None:
    rows: Sequence[TableRow] = table(zones)
    effect = table_effect(rows, 6, 7)
    assert effect is not None
    seen = {z["kind"] for res in effect["after"].values() for side in ("home", "away")
            for z in res[side]["zones"] if z["kind"]}
    assert "promotion" not in seen


# The Liga MX table of 7 Nov 2026 (stakes-v4, UX-065): the provider words the first eight places
# "Promotion - Liga MX (Apertura - Play Offs: Quarter-finals)" - the liguilla of the same league, not a promotion.
LIGA_MX_ZONE = "Promotion - Liga MX (Apertura - Play Offs: Quarter-finals)"
LIGA_MX = {**dict.fromkeys(range(1, 9), LIGA_MX_ZONE), **dict.fromkeys(range(9, 19))}


def test_the_liguilla_of_the_liga_mx_is_a_playoff_never_a_promotion() -> None:
    assert zone_kind(LIGA_MX_ZONE, 3, league="Liga MX") == "playoff"
    assert zone_kind(LIGA_MX_ZONE, 3) == "promotion", "without the league the reading is the one of before"
    assert zone_kind("Promotion - Liga MX (Apertura - Play Offs: Quarter-finals)", 3, league="Serie A") == "promotion"


def test_pumas_eleventh_do_not_fight_for_promotion() -> None:
    pumas = stakes(table(LIGA_MX), 11, 4, league="Liga MX")
    assert pumas is not None
    assert pumas.zone is None and pumas.zone_above == "playoff"
    assert pumas.pressure != "promotion"
    leader = stakes(table(LIGA_MX), 1, 4, league="Liga MX")
    assert leader is not None and leader.zone == "playoff" and leader.pressure in ("playoff", "settled")


def test_the_league_is_the_name_of_the_group_before_the_colon() -> None:
    assert league_of("Liga MX: Apertura") == "Liga MX"
    assert league_of("Serie A") == "Serie A"
    assert league_of(None) is None and league_of("") is None


def test_a_second_division_still_promotes_when_it_names_another_league() -> None:
    assert zone_kind("Promotion - Serie A (Play-offs)", 5, league="Serie B") == "promotion"
