"""A privacy request's legal deadline (plan UX, A4; Ley 1581 de 2012, arts. 14 and 15): counted in Colombian business
days from the day after it arrives - arriving being a date in Bogotá, not in UTC."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fbi.customer import privacy, workdays


def test_each_request_has_its_legal_term_and_its_one_extension() -> None:
    assert privacy.DEADLINES == {"privacy_query": (10, 5), "privacy_claim": (15, 8), "privacy_deletion": (15, 8)}
    # Friday 23 Oct 2026: a query is due 10 business days later, past the holidays of 2 and 16 November
    assert privacy.deadline_for("privacy_query", date(2026, 10, 23)) == date(2026, 11, 9)
    assert privacy.deadline_for("privacy_claim", date(2026, 10, 23)) == date(2026, 11, 17)
    assert privacy.deadline_for("privacy_deletion", date(2026, 10, 23)) == date(2026, 11, 17)
    # the extension counts from the deadline
    assert workdays.add_business_days(date(2026, 11, 9), 5) == date(2026, 11, 17)


def test_the_day_a_request_arrives_is_bogotas() -> None:
    # 03:30 UTC on Saturday 24 Oct is still Friday 23 Oct in Bogotá (UTC-5)
    assert privacy.bogota_today(datetime(2026, 10, 24, 3, 30, tzinfo=UTC)) == date(2026, 10, 23)
    assert privacy.bogota_today(datetime(2026, 10, 24, 5, 0, tzinfo=UTC)) == date(2026, 10, 24)


def test_a_request_on_a_holiday_counts_from_the_next_business_day() -> None:
    # Monday 2 Nov 2026 is All Saints' (moved): a query sent that day is due 10 business days from Tuesday
    assert privacy.deadline_for("privacy_query", date(2026, 11, 2)) == date(2026, 11, 17)
