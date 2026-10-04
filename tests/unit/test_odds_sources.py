"""The price-source interface and registry: API-Football implements it, and nothing that costs
money or needs an account can be read without an owner decision."""

from __future__ import annotations

from typing import Any, cast

from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.odds_sources import ODDS_SOURCES, Access, OddsProvider, enabled_sources


def test_api_football_is_an_odds_provider() -> None:
    provider: OddsProvider = ApiFootballProvider(cast(Any, None))  # checked structurally by mypy
    assert isinstance(provider, OddsProvider)


def test_only_active_sources_are_enabled() -> None:
    enabled = {s.key for s in enabled_sources()}
    assert enabled == {"api_football", "football_data_co_uk"}
    for s in ODDS_SOURCES:
        if s.access in (Access.PAYMENT_REQUIRED, Access.FREE_NEEDS_OWNER, Access.CLOSED, Access.REJECTED):
            assert s.key not in enabled


def test_every_paid_source_says_so_and_every_source_cites_where_it_was_read() -> None:
    for s in ODDS_SOURCES:
        assert s.sources, s.key
        if s.access is Access.PAYMENT_REQUIRED:
            assert "not contracted" in s.decision, s.key
