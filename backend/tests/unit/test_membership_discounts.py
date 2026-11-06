"""The discounts of the membership (UX-005) without a database: the arithmetic, the owner's settings, the code's form and
which discount wins - the rules the owner decided on 5-nov-2026."""

from __future__ import annotations

import pytest

from fbi.customer import discounts
from fbi.customer.db import CustomerError


@pytest.mark.parametrize(("amount", "percent", "said"), [
    ("150000", 20, "120000"),
    ("50", 20, "40"),
    ("50", 15, "42.5"),
    ("150000", 33, "100500"),
    ("19.99", 10, "17.99"),
    ("100", 100, "0"),
    ("100", 1, "99"),
])
def test_the_discount_is_taken_off_and_said_without_trailing_zeros(amount: str, percent: int, said: str) -> None:
    assert discounts.discounted(amount, percent) == said


def test_the_loyalty_discount_is_twenty_percent_after_two_months_unless_the_owner_says(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FBI_LOYALTY_PERCENT", "FBI_LOYALTY_AFTER_MONTHS"):
        monkeypatch.delenv(name, raising=False)
    assert (discounts.loyalty_percent(), discounts.loyalty_after_months()) == (20, 2)
    monkeypatch.setenv("FBI_LOYALTY_PERCENT", "15")
    monkeypatch.setenv("FBI_LOYALTY_AFTER_MONTHS", "3")
    assert (discounts.loyalty_percent(), discounts.loyalty_after_months()) == (15, 3)
    for off in ("0", "off", "OFF", "false", "no"):
        monkeypatch.setenv("FBI_LOYALTY_PERCENT", off)
        assert discounts.loyalty_percent() == 0, off
    for wrong in ("abc", "101", "-5", "12.5"):
        monkeypatch.setenv("FBI_LOYALTY_PERCENT", wrong)
        assert discounts.loyalty_percent() == 20, f"{wrong}: a wrong value never changes the rule"
    for wrong in ("abc", "0", "25", "-1"):
        monkeypatch.setenv("FBI_LOYALTY_AFTER_MONTHS", wrong)
        assert discounts.loyalty_after_months() == 2, wrong


def test_a_code_is_kept_in_capitals_and_never_with_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    assert discounts.clean_code("  bienvenida-20 ") == "BIENVENIDA-20"
    assert discounts.clean_code("a_b") == "A_B"
    for bad in ("", "ab", "x" * 33, "con espacio", "ñandú", "a;b", "<script>"):
        with pytest.raises(CustomerError) as caught:
            discounts.clean_code(bad)
        assert caught.value.code == "invalid_coupon_code", bad


def held(*percents: int) -> list[dict[str, object]]:
    return [{"id": i + 1, "code": f"C{i}", "percent": p} for i, p in enumerate(sorted(percents, reverse=True))]


def test_the_larger_discount_wins_and_they_never_add_up(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FBI_LOYALTY_PERCENT", "FBI_LOYALTY_AFTER_MONTHS"):
        monkeypatch.delenv(name, raising=False)
    assert discounts._best(0, []) is None
    assert discounts._best(1, []) is None, "one month paid is not past the two"
    assert discounts._best(2, []) == discounts.Offer("loyalty", 20)
    assert discounts._best(5, held(10)) == discounts.Offer("loyalty", 20), "a smaller coupon never beats loyalty"
    assert discounts._best(5, held(20)) == discounts.Offer("loyalty", 20), "equal: loyalty, the coupon stays for later"
    assert discounts._best(5, held(50, 30)) == discounts.Offer("coupon", 50, "C0", 1)
    assert discounts._best(0, held(15)) == discounts.Offer("coupon", 15, "C0", 1), "a coupon needs no months"
    monkeypatch.setenv("FBI_LOYALTY_PERCENT", "0")
    assert discounts._best(12, []) is None, "with loyalty off, nothing for months alone"
    assert discounts._best(12, held(10)) == discounts.Offer("coupon", 10, "C0", 1)
