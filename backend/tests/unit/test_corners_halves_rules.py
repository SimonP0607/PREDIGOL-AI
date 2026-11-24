"""PM-05-03: the corners of a half are graded by a NEW version of the two rules, behind ``FBI_CORNERS_BY_HALF``. A rule is never edited: the
first version of every rule is pinned by a hash, so changing a word of it fails here and has to be a new version. Off, the bets are
linked and explained exactly as before; on, they are liquidable with the columns the view got in migration 0177."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from fbi.market import rules
from fbi.market.rules import (
    RULES,
    RULES_BY_KEY,
    RULES_BY_MEASURE,
    explain,
    rule_for,
    rules_in_force,
)
from fbi.odds.quote_taxonomy import BetSpec
from fbi.picks.count_settlement import settle_numbers
from fbi.picks.settlement import Status
from tests.unit.test_market_catalogue import ALL_SPECS


def digest(selected: list[rules.Rule]) -> str:
    h = hashlib.sha256()
    for r in sorted(selected, key=lambda r: r.key):
        h.update(repr((r.measure, r.version, r.family, r.period, r.convention, r.columns, r.reason, r.note)).encode())
    return h.hexdigest()


def test_the_first_version_of_every_rule_is_never_edited() -> None:
    v1 = [r for r in RULES if r.version == 1]
    assert len(v1) == 20, "a rule is added as a new version, never by changing the first one"
    assert digest(v1) == PINNED_V1


def test_the_new_version_is_born_behind_a_switch_and_the_old_one_stays() -> None:
    for key in ("corners_1h@v2", "corners_2h@v2"):
        r = RULES_BY_KEY[key]
        assert r.liquidable and r.switch == rules.CORNERS_BY_HALF and r.version == 2
    assert RULES_BY_KEY["corners_1h@v2"].columns == ("corners_1h_home", "corners_1h_away")
    assert RULES_BY_KEY["corners_2h@v2"].columns == ("corners_2h_home", "corners_2h_away")
    assert not RULES_BY_KEY["corners_1h@v1"].liquidable and not RULES_BY_KEY["corners_2h@v1"].liquidable


def test_off_the_bets_on_the_corners_of_a_half_are_explained_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(rules.CORNERS_BY_HALF, raising=False)
    assert RULES_BY_MEASURE["corners_1h"].key == "corners_1h@v1" and RULES_BY_MEASURE["corners_2h"].key == "corners_2h@v1"
    assert {r.key for r in rules_in_force()} == {r.key for r in RULES if r.key not in ("corners_1h@v2", "corners_2h@v2")}
    halves = [s for s in ALL_SPECS if s.family == "corners" and s.period in ("1H", "2H")]
    assert len(halves) >= 10
    for s in halves:
        assert explain(s).reason == rules.NO_PERIOD_DATA and rule_for(s) is None, s


def test_on_they_are_graded_by_version_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(rules.CORNERS_BY_HALF, "1")
    assert RULES_BY_MEASURE["corners_1h"].key == "corners_1h@v2" and RULES_BY_MEASURE["corners_2h"].key == "corners_2h@v2"
    assert RULES_BY_MEASURE["corners_ft"].key == "corners_ft@v1", "the other measures keep their only version"
    halves = [s for s in ALL_SPECS if s.family == "corners" and s.period in ("1H", "2H")]
    for s in halves:  # the taxonomy still parks these bets (their selections are not read): the reason is no longer «no period data»
        d = explain(s)
        assert d.reason == rules.NOT_UNDERSTOOD and d.measure == ("corners_1h" if s.period == "1H" else "corners_2h"), s
    first = BetSpec(bet_id=900_000, name="Total Corners (1st Half)", family="corners", period="1H", subject="match", kind="over_under",
                    extract=True)
    second = BetSpec(bet_id=900_001, name="Total Corners (2nd Half)", family="corners", period="2H", subject="match", kind="over_under",
                     extract=True)
    for spec, key in ((first, "corners_1h@v2"), (second, "corners_2h@v2")):
        d = explain(spec)
        assert d.reason == rules.OK and d.liquidable and d.rule is not None and d.rule.key == key
        assert rule_for(spec) == d.rule


@pytest.mark.parametrize(("value", "expected"), [("0", False), ("off", False), ("", False), ("no", False), ("1", True), ("on", True),
                                                  ("TRUE", True), ("yes", True)])
def test_the_switch_reads_like_every_other(value: str, expected: bool) -> None:
    assert rules.switch_on(rules.CORNERS_BY_HALF, {rules.CORNERS_BY_HALF: value}) is expected
    assert rules.switch_on(rules.CORNERS_BY_HALF, {}) is False and rules.switch_on(None, {}) is True


def test_a_half_is_graded_on_its_own_pair_of_counts_and_an_unknown_count_is_never_a_zero() -> None:
    rule = RULES_BY_KEY["corners_1h@v2"]
    line = Decimal("4.5")
    assert settle_numbers(rule, "over_under", "match", "Over", line, {"corners_1h_home": 3, "corners_1h_away": 2}) == Status.WIN
    assert settle_numbers(rule, "over_under", "match", "Under", line, {"corners_1h_home": 3, "corners_1h_away": 2}) == Status.LOSS
    assert settle_numbers(rule, "over_under", "match", "Over", line, {"corners_1h_home": 2, "corners_1h_away": 2}) == Status.LOSS
    assert settle_numbers(rule, "over_under", "match", "Over", line, {"corners_1h_home": 3, "corners_1h_away": None}) is None
    second = RULES_BY_KEY["corners_2h@v2"]
    assert settle_numbers(second, "over_under", "match", "Over", Decimal("3.5"), {"corners_2h_home": 2, "corners_2h_away": 2}) == Status.WIN
    assert settle_numbers(second, "over_under", "match", "Over", Decimal("3.5"), {"corners_1h_home": 9, "corners_1h_away": 9}) is None


PINNED_V1 = "57636615be2183f57bf91e52ac437ee4d882b95b55f9e72c9e82a000c30f2ec1"
