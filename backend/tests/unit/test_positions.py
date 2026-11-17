"""AD-H09 (IA-071): one vocabulary of positions, for every spelling seen in production."""

from __future__ import annotations

import pytest

from fbi.players.positions import (
    GROUPS,
    NOT_A_POSITION,
    normalize_position,
    position_group,
    sql_case,
)

SEEN_IN_PRODUCTION: dict[str | None, str | None] = {
    # core.players, core.squad_members, core.player_season_stats, core.fixture_lineup_players (16-nov-2026)
    "Midfielder": "midfielder", "Defender": "defender", "Attacker": "forward", "Goalkeeper": "goalkeeper",
    "Forward": "forward", "M": "midfielder", "D": "defender", "F": "forward", "G": "goalkeeper",
    "SUB": None, "U": None, "Substitute": None, None: None,
}


@pytest.mark.parametrize(("raw", "group"), [(k, SEEN_IN_PRODUCTION[k]) for k in sorted(SEEN_IN_PRODUCTION, key=str)])
def test_every_spelling_seen_in_production_has_its_group(raw: str | None, group: str | None) -> None:
    assert position_group(raw) == group


def test_the_two_vocabularies_meet() -> None:
    for long, short in (("Goalkeeper", "G"), ("Defender", "D"), ("Midfielder", "M"), ("Attacker", "F")):
        assert position_group(long) == position_group(short)


def test_the_list_is_closed() -> None:
    values = {position_group(v) for v in ("Midfielder", "D", "Centre-Back", "Left Winger", "delantero", "x", "")}
    assert values <= {*GROUPS, None}
    assert normalize_position("Centre-Back").detail == "centre_back"
    assert normalize_position("Centre-Back").group == "defender"
    assert normalize_position("Wizard").group is None
    assert "sub" in NOT_A_POSITION


def test_the_sql_table_is_built_from_the_same_map() -> None:
    sql = sql_case("position")
    assert "WHEN 'm' THEN 'midfielder'" in sql
    assert "WHEN 'attacker' THEN 'forward'" in sql
    assert sql.startswith("CASE ") and sql.endswith(" ELSE NULL END")
