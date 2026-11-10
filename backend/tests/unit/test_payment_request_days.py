"""One business day in Colombia (UX-090): the holidays the owner's promise to verify a payment skips."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from fbi.customer import payment_requests as pr


def test_holidays_of_2026_follow_the_emiliani_law_and_easter() -> None:
    days = pr.holidays(2026)
    assert date(2026, 4, 2) in days and date(2026, 4, 3) in days  # Holy Thursday and Good Friday (Easter: 5 April)
    assert date(2026, 11, 2) in days  # All Saints, Sunday 1 November moved to Monday
    assert date(2026, 11, 16) in days  # Independence of Cartagena, Wednesday 11 November moved to Monday
    assert date(2026, 1, 12) in days  # Epiphany, Tuesday 6 January moved to Monday
    assert date(2026, 12, 8) in days and date(2026, 12, 25) in days  # fixed
    assert date(2026, 11, 3) not in days


def test_a_request_is_due_the_first_business_day_after_its_day() -> None:
    bogota = pr.BOGOTA
    friday_night = datetime(2026, 11, 6, 21, 0, tzinfo=bogota)
    assert pr.due_on(friday_night) == date(2026, 11, 9)  # the weekend is skipped
    assert pr.due_on(datetime(2026, 11, 9, 8, 0, tzinfo=bogota)) == date(2026, 11, 10)
    assert pr.due_on(datetime(2026, 11, 13, 10, 0, tzinfo=bogota)) == date(2026, 11, 17)  # Monday 16 is a holiday
    assert pr.due_on(datetime(2026, 12, 24, 10, 0, tzinfo=bogota)) == date(2026, 12, 28)  # the 25th and the weekend


def test_the_day_is_counted_in_bogota_not_in_utc() -> None:
    late = datetime(2026, 11, 10, 3, 30, tzinfo=UTC)  # 22:30 of Monday 9 November in Bogotá
    assert pr.due_on(late) == date(2026, 11, 10)
    assert pr.due_at(late) == datetime(2026, 11, 11, 5, 0, tzinfo=UTC)  # the end of Tuesday 10, Bogotá


@pytest.mark.parametrize("text", ["4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"])
def test_a_card_number_is_not_a_reference(text: str) -> None:
    with pytest.raises(pr.CustomerError) as err:
        pr.clean_reference(text)
    assert err.value.code == "reference_has_number"


def test_a_reference_is_kept_only_as_its_last_four_and_a_mac() -> None:
    last4, mac = pr.clean_reference("m 1234 5678")  # type: ignore[misc]
    assert last4 == "5678" and len(mac) == 64
    assert pr.clean_reference("") is None and pr.clean_reference(None) is None
    again = pr.clean_reference("M12345678")
    assert again == (last4, mac), "the same reference, however it is spaced or capitalised"
    for bad in ("ab", "a" * 41, "<script>"):
        with pytest.raises(pr.CustomerError):
            pr.clean_reference(bad)
