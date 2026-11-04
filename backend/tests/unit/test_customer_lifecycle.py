"""Each customer's state of the day (plan UX, B11): the precedence and the reasons, proved with synthetic stories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.customer import lifecycle
from fbi.customer.lifecycle import Inputs, judge

AT = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)


def inputs(**kw: object) -> Inputs:
    base: dict[str, object] = {"account_status": "active", "created_at": AT - timedelta(days=40), "membership": "active",
                               "active_days_7": 1, "active_days_14": 2, "low_survey": False, "ticket_waiting": False}
    return Inputs(**(base | kw))  # type: ignore[arg-type]


def state(**kw: object) -> tuple[str, tuple[str, ...]]:
    found = judge(inputs(**kw), AT)
    assert found is not None
    return found.state, found.reasons


def test_invited_until_activated() -> None:
    assert state(account_status="invited", active_days_7=0, active_days_14=0) == ("invited", ("account_invited",))


def test_activated_then_habitual() -> None:
    assert state(active_days_7=1)[0] == "activated"
    assert state(active_days_7=2)[0] == "activated"
    assert state(active_days_7=3) == ("habitual", ("used_3_of_7_days",))
    assert state(active_days_7=0, active_days_14=0, created_at=AT - timedelta(days=3)) == (
        "activated", ("account_activated", "never_used"))


def test_at_risk_has_its_reasons_and_never_before_a_week_of_age() -> None:
    assert state(active_days_7=0, active_days_14=1) == ("at_risk", ("silent_7d",))
    assert state(low_survey=True) == ("at_risk", ("low_survey",))
    assert state(ticket_waiting=True, active_days_7=4) == ("at_risk", ("ticket_waiting_72h",))
    assert state(active_days_7=0, low_survey=True, ticket_waiting=True)[1] == (
        "silent_7d", "low_survey", "ticket_waiting_72h")
    # a two-day-old account that has not come back is not silent yet
    assert state(created_at=AT - timedelta(days=2), active_days_7=0, active_days_14=0)[0] == "activated"


@pytest.mark.parametrize(("membership", "expected", "reason"), [
    ("expired", "expired", "membership_expired"),
    ("expiring", "expiring", "membership_expiring"),
    ("grace", "expiring", "membership_grace"),
    ("renewed", "renewed", "membership_renewed"),
])
def test_the_membership_comes_before_the_use(membership: str, expected: str, reason: str) -> None:
    # even a risky, silent or habitual reader is told by their membership first
    for kw in ({"low_survey": True}, {"active_days_7": 0}, {"active_days_7": 6}):
        assert state(membership=membership, **kw) == (expected, (reason,))


def test_precedence_expired_over_everything() -> None:
    assert state(membership="expired", account_status="invited")[0] == "expired"


@pytest.mark.parametrize(("kw"), [
    {"membership": "exempt"}, {"membership": "suspended"}, {"account_status": "disabled"},
    {"account_status": "deleted"},
])
def test_no_state_for_the_owner_a_suspended_a_disabled_or_a_deleted_account(kw: dict[str, str]) -> None:
    assert judge(inputs(**kw), AT) is None


def test_every_reason_is_in_the_closed_list_and_fits_the_column() -> None:
    import re

    seen: set[str] = set()
    for membership in ("trial", "active", "expiring", "grace", "expired", "renewed", "none"):
        for status in ("active", "invited"):
            for d7, d14 in ((0, 0), (0, 2), (1, 1), (3, 5)):
                for low in (False, True):
                    for waiting in (False, True):
                        found = judge(inputs(membership=membership, account_status=status, active_days_7=d7,
                                             active_days_14=d14, low_survey=low, ticket_waiting=waiting), AT)
                        assert found is not None
                        assert found.state in lifecycle.STATES
                        assert 1 <= len(found.reasons) <= 8
                        joined = ",".join(found.reasons)
                        assert re.fullmatch(r"[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*", joined) and len(joined) <= 200
                        seen.update(found.reasons)
    assert seen <= lifecycle.REASONS


def test_rates_are_hidden_under_thirty_readers() -> None:
    assert lifecycle.rate(5, 29).value is None
    assert lifecycle.rate(15, 30).value == 0.5
    assert lifecycle.rate(0, 0).value is None


def test_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_LIFECYCLE", raising=False)
    assert lifecycle.enabled()
    for value in ("0", "off", "false"):
        monkeypatch.setenv("FBI_LIFECYCLE", value)
        assert not lifecycle.enabled()
