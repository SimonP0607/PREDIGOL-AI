"""The membership's seven states, from dates alone (plan UX, A8; section 22): a simulated clock walks a trial, its
first payment, a renewal, the grace and the limit - nothing here touches a database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.customer import membership as ms
from fbi.customer.db import CustomerError
from fbi.customer.membership import Event, Period, add_months, compute, due_notices

T0 = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def period(pid: int, kind: str, start: datetime, end: datetime, created: datetime | None = None) -> Period:
    return Period(id=pid, kind=kind, starts_at=start, ends_at=end, created_at=created or start,  # type: ignore[arg-type]
                  payment_id=pid if kind == "paid" else None)


def event(eid: int, kind: str, at: datetime, reason: str | None = None) -> Event:
    return Event(id=eid, kind=kind, at=at, reason=reason)


TRIAL = period(1, "trial", T0, T0 + 14 * DAY)


def state(periods: list[Period], at: datetime, events: list[Event] | None = None, *, enforce: bool = True) -> str:
    return compute(periods, events or [], at, enforce=enforce).state


def test_a_trial_walks_its_days_then_the_grace_then_the_limit() -> None:
    assert state([TRIAL], T0 + DAY) == "trial"
    assert state([TRIAL], T0 + 11 * DAY - timedelta(minutes=1)) == "trial"
    assert state([TRIAL], T0 + 11 * DAY) == "expiring", "3 days left in a trial"
    assert state([TRIAL], T0 + 14 * DAY) == "grace", "the end: 3 days of grace with everything"
    m = compute([TRIAL], [], T0 + 17 * DAY - timedelta(seconds=1), enforce=True)
    assert (m.state, m.limited) == ("grace", False)
    m = compute([TRIAL], [], T0 + 17 * DAY, enforce=True)
    assert (m.state, m.limited, m.grace_until) == ("expired", True, T0 + 17 * DAY)
    assert not compute([TRIAL], [], T0 + 30 * DAY, enforce=False).limited, "the switch off limits nobody"


def test_the_first_payment_after_the_trial_is_active_whenever_it_comes() -> None:
    for paid_at in (T0 + 12 * DAY, T0 + 15 * DAY, T0 + 20 * DAY):
        start = max(paid_at, TRIAL.ends_at)
        paid = period(2, "paid", start, add_months(start, 1), created=paid_at)
        m = compute([TRIAL, paid], [], paid_at + timedelta(minutes=1), enforce=True)
        assert (m.state, m.kind, m.limited) == ("active", "paid", False), paid_at
    early = period(2, "paid", TRIAL.ends_at, add_months(TRIAL.ends_at, 1), created=T0 + 12 * DAY)
    assert compute([TRIAL, early], [], T0 + 12 * DAY, enforce=True).ends_at == datetime(2026, 12, 7, 15, 0,
                                                                                         tzinfo=UTC)


def test_a_paid_period_after_a_paid_one_is_renewed_for_seven_days() -> None:
    first = period(2, "paid", T0, add_months(T0, 1))
    renewal_at = first.ends_at - 3 * DAY
    second = period(3, "paid", first.ends_at, add_months(first.ends_at, 1), created=renewal_at)
    assert state([first], renewal_at) == "expiring"
    assert state([first, second], renewal_at) == "renewed"
    assert state([first, second], renewal_at + 7 * DAY - timedelta(seconds=1)) == "renewed"
    assert state([first, second], renewal_at + 7 * DAY) == "active"
    # paid in the grace or after the limit: renewed too, from now
    late_at = first.ends_at + 5 * DAY
    late = period(3, "paid", late_at, add_months(late_at, 1), created=late_at)
    assert state([first, late], late_at) == "renewed"


def test_seven_days_before_a_paid_end_it_is_expiring() -> None:
    paid = period(2, "paid", T0, T0 + 30 * DAY)
    assert state([paid], T0 + 23 * DAY - timedelta(seconds=1)) == "active"
    assert state([paid], T0 + 23 * DAY) == "expiring"
    courtesy = period(3, "courtesy", paid.ends_at, paid.ends_at + 10 * DAY, created=T0 + 25 * DAY)
    m = compute([paid, courtesy], [], T0 + 25 * DAY, enforce=True)
    assert (m.state, m.kind) == ("active", "courtesy")


def test_a_suspension_limits_until_it_is_lifted_and_will_not_renew_is_remembered() -> None:
    paid = period(2, "paid", T0, T0 + 30 * DAY)
    suspended = [event(1, "suspended", T0 + DAY, "impago anterior")]
    m = compute([paid], suspended, T0 + 2 * DAY, enforce=True)
    assert (m.state, m.limited, m.suspended_reason) == ("suspended", True, "impago anterior")
    lifted = [*suspended, event(2, "suspension_lifted", T0 + 3 * DAY)]
    assert state([paid], T0 + 4 * DAY, lifted) == "active"
    intent = [event(3, "will_not_renew", T0 + DAY, "se muda"), event(4, "will_renew", T0 + 2 * DAY)]
    assert compute([paid], intent[:1], T0 + DAY, enforce=True).will_not_renew
    assert not compute([paid], intent, T0 + 3 * DAY, enforce=True).will_not_renew


def test_without_a_period_nothing_is_limited() -> None:
    m = compute([], [], T0, enforce=True)
    assert (m.state, m.limited, m.ends_at, m.days_left(T0)) == ("none", False, None, None)


def test_days_left_round_up_and_end_at_zero() -> None:
    m = compute([TRIAL], [], T0, enforce=False)
    assert m.days_left(T0) == 14
    assert m.days_left(T0 + 13 * DAY + timedelta(hours=23)) == 1
    assert m.days_left(T0 + 20 * DAY) == 0


@pytest.mark.parametrize(("start", "months", "end"), [
    (datetime(2027, 1, 31, 12, tzinfo=UTC), 1, datetime(2027, 2, 28, 12, tzinfo=UTC)),
    (datetime(2028, 1, 31, 12, tzinfo=UTC), 1, datetime(2028, 2, 29, 12, tzinfo=UTC)),
    (datetime(2026, 12, 7, 9, tzinfo=UTC), 1, datetime(2027, 1, 7, 9, tzinfo=UTC)),
    (datetime(2026, 11, 7, 15, tzinfo=UTC), 12, datetime(2027, 11, 7, 15, tzinfo=UTC)),
    (datetime(2026, 8, 31, 0, tzinfo=UTC), 3, datetime(2026, 11, 30, 0, tzinfo=UTC)),
])
def test_months_are_calendar_months(start: datetime, months: int, end: datetime) -> None:
    assert add_months(start, months) == end


def test_a_reference_never_holds_an_account_or_a_card_number() -> None:
    assert ms.check_reference("  Nequi,   25 oct ") == "Nequi, 25 oct"
    assert ms.check_reference("transferencia, últimos 4: 1234") == "transferencia, últimos 4: 1234"
    for bad in ("4111 1111 1111 1111", "cuenta 123-456-7890", "1234.5678.90", "ref 0123456789"):
        with pytest.raises(CustomerError) as caught:
            ms.check_reference(bad)
        assert caught.value.code == "reference_has_number", bad
    with pytest.raises(CustomerError):
        ms.check_reference("x" * 121)


def test_the_notices_of_an_end() -> None:
    def notices(at: datetime, events: list[Event] | None = None) -> list[tuple[str, bool]]:
        return [(n.milestone, n.email) for n in due_notices(compute([TRIAL], events or [], at, enforce=True), 7)]

    assert notices(T0 + 5 * DAY) == []
    assert notices(T0 + 12 * DAY) == [("before", True)]
    assert notices(T0 + 15 * DAY) == [("due", True)]
    assert notices(T0 + 18 * DAY) == [("grace_end", False)], "the end of the grace: the app only"
    said = [event(1, "will_not_renew", T0 + DAY, "no le interesa")]
    assert notices(T0 + 12 * DAY, said) == [("before", False)], "«will not renew»: no e-mails"
    assert notices(T0 + 12 * DAY, [event(2, "suspended", T0 + DAY, "revisión")]) == []
    assert due_notices(ms.EXEMPT, 7) == []


def test_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw, days in (("", 20), ("10", 10), ("3", 7), ("40", 20), ("x", 20), ("14", 14), ("20", 20)):
        monkeypatch.setenv("FBI_TRIAL_DAYS", raw)
        assert ms.trial_days() == days, raw
    monkeypatch.delenv("FBI_MEMBERSHIP_CURRENCY", raising=False)
    assert ms.currency() == "COP"
    monkeypatch.setenv("FBI_MEMBERSHIP_CURRENCY", "usd")
    assert ms.currency() == "USD"
    monkeypatch.setenv("FBI_SUPPORT_WHATSAPP", "+57 300 123 4567")
    assert ms.whatsapp() == "573001234567"
    monkeypatch.setenv("FBI_SUPPORT_WHATSAPP", "123")
    assert ms.whatsapp() is None
    monkeypatch.setenv("FBI_EMAIL_REPLY_TO", "PrediGol <hola@correo.example.com>")
    assert ms.reply_address() == "hola@correo.example.com"
    monkeypatch.delenv(ms.SWITCH, raising=False)
    assert not ms.enforced()
    monkeypatch.setenv(ms.SWITCH, "1")
    assert ms.enforced()


def test_the_monthly_price_is_the_owners_decision_and_each_currency_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """150,000 COP or 50 USD by default (5-nov-2026); a currency is off with 0, and a price nobody can read is never shown."""
    for name in ("FBI_MEMBERSHIP_PRICE_COP", "FBI_MEMBERSHIP_PRICE_USD"):
        monkeypatch.delenv(name, raising=False)
    assert ms.prices() == [
        {"currency": "COP", "amount": "150000"},
        {"currency": "USD", "amount": "50"},
    ]
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_COP", "180000")
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_USD", "off")
    assert ms.prices() == [{"currency": "COP", "amount": "180000"}]
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_USD", "49.90")
    assert ms.prices()[1] == {"currency": "USD", "amount": "49.9"}
    for unreadable in ("-5", "abc", "NaN", "Infinity", "99999999999999"):
        monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_COP", unreadable)
        assert [p["currency"] for p in ms.prices()] == ["USD"], unreadable
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_COP", "0")
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_USD", "no")
    assert ms.prices() == []
