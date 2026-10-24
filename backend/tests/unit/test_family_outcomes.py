"""Plan F11 - what became of a family's decision (``fbi.intel.family_outcomes``): the pure parts, checked against numbers worked by hand.

The settlement against a real database is in tests/integration/test_family_outcomes.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.intel import family_decision as fd
from fbi.intel import family_outcomes as fo
from fbi.intel import outcomes
from fbi.picks.settlement import Status

D = Decimal
KICKOFF = datetime(2035, 3, 2, 12, tzinfo=UTC)


def row(*, key: str = "CORNERS_OU", selection: str = "Over", line: str = "10.5", odds: str = "2.100", stake: str = "0.00", fixture: int = 1,
        id: int = 1) -> fo.Open:
    return fo.Open(id, fixture, key, selection, D(line), D(odds), D(stake), KICKOFF)


def closed(p_fair: float = 0.50, best: float = 2.00, *, books: int = 3, newest: datetime = KICKOFF - timedelta(minutes=20)) -> fd.Priced:
    return fd.Priced(p_fair, best, 4, books, 1.05, newest)


# ── the profit ───────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("status", "flat"), [(Status.WIN, "1.1000"), (Status.LOSS, "-1.0000"), (Status.PUSH, "0.0000"), (Status.VOID, "0.0000"),
                                              (Status.HALF_WIN, "0.5500"), (Status.HALF_LOSS, "-0.5000")])
def test_the_profit_of_a_flat_unit_is_the_pipelines_own_arithmetic(status: Status, flat: str) -> None:
    o = fo.outcome(row(), status, None, None)
    assert o.result_status == status.value and o.profit_flat == D(flat)
    assert o.profit_flat == outcomes.profit_per_unit(status.value, D("2.100")).quantize(D("0.0001")), "the same function the pipeline's decisions use"


def test_a_family_that_is_not_staked_earns_nothing_staked_and_a_stake_scales_the_unit() -> None:
    assert fo.outcome(row(stake="0.00"), Status.WIN, None, None).profit_staked == D("0.0000"), "a family's stake is zero"
    assert fo.outcome(row(stake="0.50"), Status.WIN, None, None).profit_staked == D("0.5500")
    assert fo.outcome(row(stake="0.50"), Status.LOSS, None, None).profit_staked == D("-0.5000")


# ── the closing line ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_value_against_the_close_is_the_price_taken_at_the_closing_fair_probability() -> None:
    o = fo.outcome(row(odds="2.100"), Status.WIN, closed(p_fair=0.50, best=2.00), KICKOFF - timedelta(minutes=12))
    assert o.clv == D("0.050000"), "2.10 x 0.50 - 1"
    assert (o.close_p_fair, o.close_odds) == (D("0.500000"), D("2.000"))
    assert o.close_as_of == KICKOFF - timedelta(minutes=12) and o.close_minutes_to_ko == 12, "the last time the odds were read, not the quote's age"
    assert o.clv == fo.closing_value.clv(D("2.100"), D("0.500000")).quantize(D("0.000001")), "clv-v1, the one definition"
    worse = fo.outcome(row(odds="1.900"), Status.LOSS, closed(p_fair=0.50), KICKOFF - timedelta(minutes=12))
    assert worse.clv == D("-0.050000") and worse.profit_flat == D("-1.0000"), "1.90 against a fair 2.00: the price was worse than the close, and lost"


def test_without_a_reading_of_the_odds_the_age_of_the_close_is_the_age_of_its_newest_quote() -> None:
    o = fo.outcome(row(), Status.WIN, closed(newest=KICKOFF - timedelta(minutes=90)), None)
    assert o.close_as_of == KICKOFF - timedelta(minutes=90) and o.close_minutes_to_ko == 90


def test_the_probability_is_stored_to_the_six_places_the_table_keeps_and_the_value_is_worked_from_that_number() -> None:
    o = fo.outcome(row(odds="1.950"), Status.WIN, closed(p_fair=0.5123456789), KICKOFF - timedelta(minutes=5))
    assert o.close_p_fair == D("0.512346")
    assert o.clv == (D("1.950") * D("0.512346") - 1).quantize(D("0.000001")), "so the stored numbers reproduce one another"


def test_a_close_of_fewer_than_three_complete_books_is_no_close() -> None:
    for books in (1, 2):
        o = fo.outcome(row(), Status.WIN, closed(books=books), KICKOFF - timedelta(minutes=5))
        assert (o.clv, o.close_p_fair, o.close_odds, o.close_as_of, o.close_minutes_to_ko) == (None, None, None, None, None)
        assert o.profit_flat == D("1.1000"), "the result and the profit do not wait for a price"
    assert fo.outcome(row(), Status.WIN, None, None).clv is None
    assert fo.outcome(row(), Status.WIN, closed(books=3), KICKOFF - timedelta(minutes=5)).clv is not None


# ── the counts ───────────────────────────────────────────────────────────────────────────────────────────────────

def counts(fixture: int = 1, **values: int | None) -> dict[int, dict[str, int | None]]:
    return {fixture: dict(values)}


def test_a_decision_is_graded_on_the_counts_of_its_match_by_the_rule_of_its_market() -> None:
    rows = [row(id=1, selection="Over", line="10.5"), row(id=2, selection="Under", line="10.5"), row(id=3, selection="Over", line="11.5"),
            row(id=4, key="CORNERS_OU_HOME", selection="Over", line="6.5"), row(id=5, key="CORNERS_1X2", selection="Home", line="0")]
    graded, ungradable, unreadable = fo.grade(rows, counts(corners_ft_home=7, corners_ft_away=4))  # 11 corners, 7 for the home side
    assert graded == {1: Status.WIN, 2: Status.LOSS, 3: Status.LOSS, 4: Status.WIN, 5: Status.WIN}
    assert (ungradable, unreadable) == (0, 0)


def test_the_goals_of_the_halves_read_both_halves() -> None:
    rows = [row(id=1, key="HTFT", selection="Home/Home", line="0"), row(id=2, key="HTFT", selection="Draw/Home", line="0"),
            row(id=3, key="HSH", selection="Draw", line="0"), row(id=4, key="HSH", selection="1st Half", line="0"),
            row(id=5, key="OU_1H", selection="Over", line="1.5"), row(id=6, key="OU_1H", selection="Over", line="2.5"),
            row(id=7, key="1X2_1H", selection="Home", line="0")]
    graded, ungradable, unreadable = fo.grade(rows, counts(goals_1h_home=2, goals_1h_away=0, goals_2h_home=1, goals_2h_away=1))
    # 2-0 at the break and 1-1 after it: 3-1 at the end, with two goals in each half
    assert graded == {1: Status.WIN, 2: Status.LOSS, 3: Status.WIN, 4: Status.LOSS, 5: Status.WIN, 6: Status.LOSS, 7: Status.WIN}
    assert (ungradable, unreadable) == (0, 0)


def test_a_count_that_is_unknown_leaves_the_decision_unsettled_and_is_never_a_loss() -> None:
    rows = [row(id=1), row(id=2, fixture=2)]
    graded, ungradable, unreadable = fo.grade(rows, counts(corners_ft_home=7, corners_ft_away=None))
    assert graded == {} and (ungradable, unreadable) == (2, 0), "an unknown count, and a match with no counts at all"


def test_a_market_the_rules_cannot_read_is_counted_and_costs_nothing() -> None:
    rows = [row(id=1, key="NOT_A_MARKET"), row(id=2, key="CORNERS_OU", selection="Sideways"), row(id=3)]
    graded, ungradable, unreadable = fo.grade(rows, counts(corners_ft_home=7, corners_ft_away=4))
    assert graded == {3: Status.WIN} and (ungradable, unreadable) == (0, 2)


# ── the constants and the switch ─────────────────────────────────────────────────────────────────────────────────

def test_the_outcomes_of_the_families_have_a_version_of_their_own_and_wait_for_the_statistics_of_the_cards() -> None:
    assert fo.VERSION == "outcome-fam-v1" != outcomes.VERSION
    assert fo.DECISION_VERSION == fd.VERSION == "decision-fam-v1" and fo.DECISION_VERSION != fd.CORE_VERSION
    assert timedelta(hours=26) <= fo.WAIT, "the cards settle some 26 hours after the match"
    assert fo.LOOKBACK > fo.WAIT and fo.CLOSE_MIN_BOOKS == 3


class Untouchable:
    """A connection nothing may use: the step of a family that is off must not read the database."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the step touched the connection ({name})")


def test_with_the_switch_off_the_step_does_nothing_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fd.SWITCH, raising=False)
    monkeypatch.setattr(fo.fd, "mode", lambda: "off")
    assert fo.run_step(Untouchable(), at=KICKOFF) == {"mode": "off"}  # type: ignore[arg-type]


def test_in_shadow_the_step_reports_what_the_settlement_did(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(conn: Any, *, at: datetime, **_: Any) -> fo.SettleReport:
        seen["at"] = at
        return fo.SettleReport(open=3, settled=2, ungradable=1, by_result={"win": 1, "loss": 1}, errors=[f"e{i}" for i in range(9)])

    monkeypatch.setattr(fo.fd, "mode", lambda: "shadow")
    monkeypatch.setattr(fo, "settle", fake)
    out = fo.run_step(Untouchable(), at=KICKOFF)  # type: ignore[arg-type]
    assert seen["at"] == KICKOFF and out["mode"] == "shadow"
    assert (out["open"], out["settled"], out["ungradable"], out["by_result"]) == (3, 2, 1, {"win": 1, "loss": 1})
    assert out["errors"] == ["e0", "e1", "e2", "e3", "e4"], "the count says how many there were, the report carries the first few"
