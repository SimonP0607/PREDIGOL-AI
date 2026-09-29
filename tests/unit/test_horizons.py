"""The fixtures horizon has to outreach the measured price horizon, or windows are lost.

Four days was the Free-plan figure and it survived the upgrade by oversight. With prices
measured at T-18.2 days, a fixture ten days out was not in core.fixtures at all, so the
odds capture planner never saw it as a candidate and the earliest part of its price
series - the part no later request can recover - was never captured. That is the one
failure the priority order calls irreversible, so it gets a test rather than a comment.
"""

from __future__ import annotations

from fbi.ingestion.fixtures import sync_fixtures
from fbi.odds.horizons import (
    DEFAULT_HORIZON_DAYS,
    MEASURED_FIRST_PRICE_DAYS,
    SYNC_INTERVAL_HOURS,
)


def test_the_horizon_reaches_past_the_first_observed_price() -> None:
    assert DEFAULT_HORIZON_DAYS > MEASURED_FIRST_PRICE_DAYS, (
        "a fixture must be a row before its first prices exist, or the opening of its "
        "series is unobservable"
    )


def test_the_margin_covers_a_whole_sync_interval() -> None:
    """A fixture can enter the provider's horizon just after a sync ran, so the margin
    has to be at least one interval - otherwise it is first seen already inside the
    price window."""
    margin_days = DEFAULT_HORIZON_DAYS - MEASURED_FIRST_PRICE_DAYS
    assert margin_days * 24 >= SYNC_INTERVAL_HOURS


def test_sync_fixtures_defaults_to_that_horizon_rather_than_its_own_number() -> None:
    """The regression was two copies of the number, not a wrong number."""
    import inspect

    default = inspect.signature(sync_fixtures).parameters["horizon_days"].default
    assert default == DEFAULT_HORIZON_DAYS


def test_the_worker_defaults_to_that_horizon_too() -> None:
    from apps.worker import scheduler

    assert scheduler.FIXTURES_HORIZON_DAYS >= DEFAULT_HORIZON_DAYS or not scheduler.PAID_PLAN
