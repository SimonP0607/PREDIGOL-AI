"""The line of why of a parlay leg (plan de Inicio, 2.4b): one fact of the match's reading that stands behind the side the leg
backs, or nothing. Pure rules: no database."""

from __future__ import annotations

from typing import Any

from fbi.api.services import reading

NAMES = {"fixture": {"home": {"name": "Blues"}, "away": {"name": "Reds"}}}


def content(*, home_unbeaten: int = 0, away_winless: int = 0, away_key_out: list[str] | None = None,
            home_pressure: str | None = None) -> dict[str, Any]:
    teams: dict[str, Any] = {"home": {"streaks": {"unbeaten": home_unbeaten}},
                             "away": {"streaks": {"winless": away_winless}}}
    absences = {"away": {"players": [{"name": n, "key": True} for n in away_key_out or []]}, "home": {"players": []}}
    stakes = {"home": {"pressure": home_pressure} if home_pressure else {}, "away": {}}
    return {**NAMES, "dossier": {"teams": teams}, "absences": absences, "stakes": stakes}


def why(c: dict[str, Any], market: str = "1X2", selection: str = "Home") -> reading.Fact | None:
    return reading.leg_reason(c, market, selection)


def test_a_side_backed_with_a_run_without_defeat() -> None:
    fact = why(content(home_unbeaten=6))
    assert fact is not None and fact.code == "streak_unbeaten"
    assert fact.params["team"] == "Blues" and fact.params["n"] == 6 and fact.ref.startswith("packet:")


def test_a_short_run_is_not_a_fact_of_the_reading() -> None:
    assert why(content(home_unbeaten=3)) is None


def test_the_other_sides_key_players_out_back_the_side_chosen() -> None:
    fact = why(content(away_key_out=["Ana Pérez"]))
    assert fact is not None and fact.code == "key_absences" and fact.params["team"] == "Reds"


def test_the_other_side_without_a_win() -> None:
    fact = why(content(away_winless=5))
    assert fact is not None and fact.code == "streak_winless" and fact.params["team"] == "Reds"


def test_what_the_side_plays_for_is_the_last_resort() -> None:
    fact = why(content(home_pressure="europe"))
    assert fact is not None and fact.code == "stakes_pressure" and fact.params["pressure"] == "europe"
    assert why(content(home_pressure="settled")) is None


def test_the_order_of_the_facts() -> None:
    c = content(home_unbeaten=5, away_winless=6, away_key_out=["Ana Pérez"], home_pressure="title")
    assert why(c).code == "streak_unbeaten"  # type: ignore[union-attr]
    c = content(away_winless=6, away_key_out=["Ana Pérez"], home_pressure="title")
    assert why(c).code == "key_absences"  # type: ignore[union-attr]


def test_the_away_win_reads_the_away_sides_facts() -> None:
    c = content(home_unbeaten=7, away_winless=5)
    c["dossier"]["teams"]["away"]["streaks"] = {"unbeaten": 4}
    fact = why(c, selection="Away")
    assert fact is not None and fact.code == "streak_unbeaten" and fact.params["team"] == "Reds"


def test_double_chance_backs_the_side_it_holds_with_the_draw() -> None:
    assert why(content(home_unbeaten=6), "DC", "1X").code == "streak_unbeaten"  # type: ignore[union-attr]
    assert why(content(home_unbeaten=6), "DC", "X2") is None, "X2 backs the away side: the home run is not its fact"
    assert why(content(home_unbeaten=6), "DC", "12") is None


def test_a_selection_that_backs_no_side_says_nothing() -> None:
    c = content(home_unbeaten=9, away_winless=9, away_key_out=["Ana Pérez"], home_pressure="title")
    for market, selection in (("1X2", "Draw"), ("OU", "Over"), ("OU", "Under"), ("BTTS", "Yes")):
        assert why(c, market, selection) is None


def test_a_match_without_a_packet_block_says_nothing() -> None:
    assert why({}) is None
    assert why(NAMES) is None
