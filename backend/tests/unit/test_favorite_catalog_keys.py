"""Which catalogue keys a reader may follow (CUOTAS BE-025): the taxonomy decides, in code, with no database. The user layer
never loads the taxonomy: it is handed the check."""

from __future__ import annotations

import pytest

from fbi.api.services.catalog_keys import catalog_key_ok
from fbi.customer import favorites
from fbi.odds.quote_current import MARKET_CODES, market_key
from fbi.odds.quote_taxonomy import EXTRACTED, known_bet_ids


@pytest.mark.parametrize("spec", EXTRACTED, ids=lambda s: str(s.bet_id))
def test_every_market_the_catalogue_can_show_can_be_followed(spec: object) -> None:
    key = market_key(spec.bet_id, spec.period, spec.subject)  # type: ignore[attr-defined]
    assert catalog_key_ok(key), key


def test_a_bet_without_a_code_reads_as_bet_and_is_followable_only_when_the_taxonomy_knows_it() -> None:
    unnamed = sorted(known_bet_ids() - set(MARKET_CODES))
    assert unnamed, "the taxonomy knows bets the catalogue has no code for"
    assert catalog_key_ok(f"bet_{unnamed[0]}.FT.match") is True
    assert catalog_key_ok("bet_999999999.FT.match") is False


@pytest.mark.parametrize("key", ["", "FOO", "corners_over_under", "corners_over_under.FT", "corners_over_under.FT.match.x",
                                 "corners_over_under.ft.match", "corners_over_under.FT.Match", "Corners.FT.match",
                                 "nonsense.FT.match", "corners_over_under.XX.match", "corners_over_under.FT.coach",
                                 "corners_over_under.FT.match;--", " corners_over_under.FT.match", "a" * 100])
def test_what_is_not_a_key_of_the_catalogue_is_refused(key: str) -> None:
    assert catalog_key_ok(key) is False


def test_the_limits_keep_the_classic_five_apart() -> None:
    assert (favorites.MAX_MARKETS, favorites.MAX_CATALOG) == (5, 10)
    assert favorites.FOLLOWABLE_MARKETS == ("1X2", "OU", "BTTS", "AH", "DC")
