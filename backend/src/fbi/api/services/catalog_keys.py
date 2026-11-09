"""Which catalogue keys a reader may follow (CUOTAS, BE-025): the taxonomy decides, in code, with no database.

A key is ``code.period.subject`` (``corners_over_under.FT.match``): a code of the taxonomy (or ``bet_<id>`` of a bet it knows), a
period and a subject it has. The code decides, not the database: a key the taxonomy stops producing simply never shows a
«Seguir». It lives in the API's layer because the user layer (``fbi.customer``) never loads the taxonomy: the route passes this
check into the save."""

from __future__ import annotations

import re
from typing import Final

from fbi.odds.quote_current import MARKET_CODES
from fbi.odds.quote_taxonomy import PERIODS, SUBJECTS, known_bet_ids

_CODES: Final = frozenset(MARKET_CODES.values())
_KEY: Final = re.compile(r"^([a-z0-9_]+)\.([A-Z0-9]+)\.([a-z]+)$")
MAX_LENGTH: Final = 80


def catalog_key_ok(key: str) -> bool:
    """Whether ``key`` is the key of a market the catalogue can show."""
    if len(key) > MAX_LENGTH or (m := _KEY.match(key)) is None:
        return False
    code, period, subject = m.groups()
    known = code in _CODES or (code.startswith("bet_") and code[4:].isdigit() and int(code[4:]) in known_bet_ids())
    return known and period in PERIODS and subject in SUBJECTS
