"""A parlay pays by what each leg does to the stake (plan F0, defect 4).

Until settle-v4 a half win was paid at the full odds and a half loss lost the whole parlay. A leg now multiplies the
stake: a win by its odds, a half win by (odds + 1) / 2, a void or a push by 1, a half loss by 1/2, a loss by 0.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.picks.product_settlement import FINAL_LEG, leg_factor, parlay_outcome

D = Decimal


@pytest.mark.parametrize(("status", "odds", "factor"), [
    ("WIN", D("2.00"), D("2.00")),
    ("HALF_WIN", D("1.90"), D("1.45")),       # half the stake wins at 1.90, half comes back: 0.5 * 1.90 + 0.5
    ("HALF_WIN", D("2.50"), D("1.75")),
    ("VOID", D("1.80"), D(1)),
    ("PUSH", D("1.80"), D(1)),
    ("HALF_LOSS", D("1.90"), D("0.5")),       # half the stake is lost, half comes back
    ("LOSS", D("1.90"), D(0)),
    ("VOID", None, D(1)),                     # a leg that returns the stake needs no price
    ("HALF_LOSS", None, D("0.5")),
    ("LOSS", None, D(0)),
    ("WIN", None, None),                      # a leg that pays without a price: unknown, never guessed
    ("HALF_WIN", None, None),
])
def test_what_one_settled_leg_does_to_the_stake(status: str, odds: Decimal | None, factor: Decimal | None) -> None:
    assert leg_factor(status, odds) == factor


def test_a_status_that_is_not_a_settled_leg_is_an_error_not_a_guess() -> None:
    with pytest.raises(ValueError, match="PENDING"):
        leg_factor("PENDING", D("2"))


@pytest.mark.parametrize(("legs", "expected"), [
    # ── unchanged: whole lines ──────────────────────────────────────────────────────────────────────────────
    ([("WIN", D("2")), ("WIN", D("1.5"))], ("WON", D("2.0000"))),
    ([("WIN", D("2")), ("VOID", D("1.5"))], ("PARTIAL_VOID", D("1.0000"))),
    ([("WIN", D("2")), ("PUSH", D("1.5"))], ("PARTIAL_VOID", D("1.0000"))),
    ([("PUSH", D("2")), ("VOID", D("1.5"))], ("VOID", D(0))),
    ([("LOSS", D("2")), ("PENDING", D("2"))], ("LOST", D(-1))),
    ([("WIN", D("2")), ("PENDING", D("2"))], None),
    ([("WIN", D("2")), ("LOSS", D("1.5"))], ("LOST", D(-1))),
    # ── a half win pays half of its odds ────────────────────────────────────────────────────────────────────
    ([("WIN", D("2")), ("HALF_WIN", D("1.90"))], ("PARTIAL_VOID", D("1.9000"))),         # 2 * 1.45 = 2.9 (was 3.8)
    ([("HALF_WIN", D("1.90")), ("HALF_WIN", D("1.90"))], ("PARTIAL_VOID", D("1.1025"))),  # 1.45 ** 2 = 2.1025
    ([("HALF_WIN", D("1.90")), ("VOID", D("1.5"))], ("PARTIAL_VOID", D("0.4500"))),
    # ── a half loss returns half the stake: it does not lose the parlay ────────────────────────────────────────
    ([("WIN", D("2")), ("HALF_LOSS", D("1.90"))], ("VOID", D(0))),               # 2 * 0.5 = 1: the stake comes back
    ([("WIN", D("1.5")), ("HALF_LOSS", D("1.90"))], ("LOST", D("-0.2500"))),     # 1.5 * 0.5 = 0.75: a quarter is lost
    ([("WIN", D("3")), ("HALF_LOSS", D("1.90"))], ("PARTIAL_VOID", D("0.5000"))),
    ([("HALF_LOSS", D("1.90")), ("HALF_LOSS", D("1.90"))], ("LOST", D("-0.7500"))),
    ([("HALF_LOSS", D("1.90")), ("VOID", D("1.9"))], ("LOST", D("-0.5000"))),
    # ── a half loss waits for the other legs; a full loss does not ──────────────────────────────────────────
    ([("HALF_LOSS", D("1.90")), ("PENDING", D("2"))], None),
    ([("HALF_LOSS", D("1.90")), ("LOSS", D("2"))], ("LOST", D(-1))),
    ([("HALF_LOSS", D("1.90")), ("WIN", D("2")), ("PENDING", D("2"))], None),
    # ── a price that is missing is never invented ──────────────────────────────────────────────────────────
    ([("WIN", None), ("VOID", D("1.5"))], ("PARTIAL_VOID", None)),
    ([("WIN", None), ("WIN", D("1.5"))], ("WON", None)),
    ([("WIN", None), ("HALF_LOSS", D("1.5"))], None),
    # ── a status the rules do not know decides nothing ─────────────────────────────────────────────────────
    ([("WIN", D("2")), ("WHAT", D("2"))], None),
])
def test_the_parlay_outcome_follows_the_factor_of_every_leg(legs: list[tuple[str, Decimal | None]],
                                                            expected: tuple[str, Decimal | None] | None) -> None:
    assert parlay_outcome(legs) == expected


def test_the_status_agrees_with_the_sign_of_the_profit() -> None:
    """The history reads PARTIAL_VOID as a win and LOST as a loss: a parlay that returns less than its stake cannot be
    one of the first, and one that returns more cannot be the second."""
    legs_pool = [("WIN", D("1.4")), ("WIN", D("2.2")), ("HALF_WIN", D("1.8")), ("HALF_LOSS", D("1.9")),
                 ("VOID", D("1.7")), ("PUSH", D("1.6"))]
    for a in legs_pool:
        for b in legs_pool:
            for c in legs_pool:
                outcome = parlay_outcome([a, b, c])
                assert outcome is not None
                status, profit = outcome
                assert profit is not None
                if status in ("WON", "PARTIAL_VOID"):
                    assert profit > 0, (a, b, c, outcome)
                elif status == "LOST":
                    assert profit < 0, (a, b, c, outcome)
                else:
                    assert status == "VOID" and profit == 0, (a, b, c, outcome)


def test_every_final_leg_status_has_a_factor() -> None:
    for status in FINAL_LEG:
        assert leg_factor(status, D("2")) is not None
