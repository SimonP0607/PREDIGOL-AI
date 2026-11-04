"""The customer views as pure functions of a card's numbers (plan UX, B10): synthetic readers, a fixed moment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.api.services.customers import VIEWS, Facts, in_view
from fbi.customer.db import CustomerError

AT = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)


def facts(**over: object) -> Facts:
    base: dict[str, object] = {
        "status": "active", "created_at": AT - timedelta(days=60), "last_seen_at": AT - timedelta(days=1),
        "ends_at": AT + timedelta(days=30), "grace_until": AT + timedelta(days=33), "suspended": False,
        "open_tickets": 0, "errors_24h": 0}
    return Facts(**{**base, **over})  # type: ignore[arg-type]


def views(f: Facts) -> set[str]:
    return {v for v in VIEWS if v != "all" and in_view(v, f, AT)}


def test_a_reader_with_nothing_to_watch_is_in_no_view_but_all() -> None:
    assert in_view("all", facts(), AT) and views(facts()) == set()


def test_expiring_means_seven_days_or_the_grace_still_running() -> None:
    assert views(facts(ends_at=AT + timedelta(days=7))) == {"expiring"}
    assert views(facts(ends_at=AT + timedelta(days=7, seconds=1))) == set()
    ended = facts(ends_at=AT - timedelta(days=1), grace_until=AT + timedelta(days=2))
    assert views(ended) == {"expiring"}, "ended, within its grace: still to renew"
    gone = facts(ends_at=AT - timedelta(days=5), grace_until=AT - timedelta(days=2))
    assert views(gone) == set(), "past the grace it is no longer expiring - it is expired"
    assert views(facts(ends_at=AT + timedelta(days=2), suspended=True)) == set()
    assert views(facts(ends_at=None, grace_until=None)) == set(), "no period, nothing ends"


def test_inactive_means_fourteen_days_unseen_for_an_activated_account() -> None:
    assert views(facts(last_seen_at=AT - timedelta(days=14, seconds=1))) == {"inactive"}
    assert views(facts(last_seen_at=AT - timedelta(days=14))) == set()
    never = facts(last_seen_at=None, created_at=AT - timedelta(days=20))
    assert views(never) == {"inactive"}, "never seen: counted from the account's creation"
    assert views(facts(last_seen_at=None, created_at=AT - timedelta(days=3))) == set()
    assert views(facts(status="invited", last_seen_at=None, created_at=AT - timedelta(days=30))) == set()
    assert views(facts(status="disabled", last_seen_at=AT - timedelta(days=90))) == set()


def test_tickets_and_errors() -> None:
    assert views(facts(open_tickets=2)) == {"tickets"}
    assert views(facts(errors_24h=1)) == {"errors"}
    assert views(facts(open_tickets=1, errors_24h=3, last_seen_at=AT - timedelta(days=30))) == {
        "tickets", "errors", "inactive"}


def test_an_unknown_view_is_refused() -> None:
    with pytest.raises(CustomerError) as raised:
        in_view("nope", facts(), AT)
    assert raised.value.status == 422
