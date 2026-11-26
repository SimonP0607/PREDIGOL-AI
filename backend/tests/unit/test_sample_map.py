"""RP-3.1: the rule of level of the sample map and its exact pooling."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fbi.stats import sample_map as sm

AT = datetime(2026, 11, 26, tzinfo=UTC)


@pytest.mark.parametrize(("own", "type_", "level"), [
    (200, 5000, sm.COMPETITION), (250, 0, sm.COMPETITION),      # 200 is enough: "200 matches or more"
    (199, 5000, sm.TYPE), (0, 200, sm.TYPE),                    # one short: it inherits from its type
    (199, 199, sm.GLOBAL), (0, 0, sm.GLOBAL),                   # not even the type has sample: global
])
def test_the_rule_of_level(own: int, type_: int, level: str) -> None:
    assert sm.level_of(own, type_) == level


def cell_of(values: list[int]) -> sm.Cell:
    return sm.Cell(len(values), float(sum(values)), float(sum(v * v for v in values)))


def test_a_cell_pools_exactly_not_as_an_average_of_averages() -> None:
    a, b = [2, 3, 4], [10, 0]
    pooled = cell_of(a) + cell_of(b)
    allv = a + b
    mean = sum(allv) / len(allv)
    var = sum((v - mean) ** 2 for v in allv) / (len(allv) - 1)
    assert pooled.n == 5 and pooled.mean == pytest.approx(mean) and pooled.variance == pytest.approx(var)
    assert pooled.dispersion == pytest.approx(var / mean)


def test_what_cannot_be_computed_is_none_not_zero() -> None:
    empty, one = sm.Cell(), cell_of([3])
    assert empty.mean is None and empty.variance is None and empty.dispersion is None
    assert one.mean == 3 and one.variance is None and one.dispersion is None
    assert cell_of([0, 0, 0]).dispersion is None, "a count that is always zero has no dispersion to speak of"


def test_a_matrix_gives_every_competition_a_level_for_every_family() -> None:
    comps = [{"id": 1, "name": "Big League", "country": "X", "type": "domestic_league"},
             {"id": 2, "name": "Small League", "country": "Y", "type": "domestic_league"},
             {"id": 3, "name": "Lonely Cup", "country": "Z", "type": "domestic_cup"}]
    big = cell_of([2, 3] * 100)         # 200 matches
    small = cell_of([1, 4] * 50)        # 100 matches
    cup = cell_of([2, 2, 3])            # 3 matches
    cells = {(1, "goals"): big, (2, "goals"): small, (3, "goals"): cup, (1, "corners"): cell_of([9, 10] * 10)}
    doc = sm.build(comps, cells, at=AT)
    by_id = {c["competition_id"]: c["families"] for c in doc["competitions"]}
    assert by_id[1]["goals"]["level"] == sm.COMPETITION and by_id[1]["goals"]["n"] == 200
    # the small league has 100, but its type (domestic_league) pools 300: it inherits from the type
    assert by_id[2]["goals"]["level"] == sm.TYPE
    # the cup has 3 and its type has 3: only the global figure
    assert by_id[3]["goals"]["level"] == sm.GLOBAL
    # a family with no data anywhere is global, with n = 0
    assert by_id[1]["shots"] == {"n": 0, "mean": None, "dispersion": None, "level": sm.GLOBAL}
    assert doc["summary"]["levels"]["goals"] == {sm.COMPETITION: 1, sm.TYPE: 1, sm.GLOBAL: 1}
    assert doc["summary"]["with_a_level"] == doc["summary"]["competitions"] == 3
    assert doc["types"]["domestic_league"]["goals"]["n"] == 300
    assert doc["global"]["goals"]["n"] == 303
    assert set(doc["families"]) == {"goals", "goals_half", "corners", "cards", "shots", "fouls"}


def test_the_six_families_of_the_plan() -> None:
    assert list(sm.FAMILIES) == ["goals", "goals_half", "corners", "cards", "shots", "fouls"]
