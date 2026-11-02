"""Read one provider ``value`` / ``odd`` pair of a structured bet (plan F1, the price clock).

The provider's words ("Over 9.5", "Home -1.5", "Home/Draw", 0, "1st Half") become a ``(selection, line)`` pair once, here, and
nowhere else. The vocabulary of ``selection`` is the one ``market.odds_snapshots`` already uses (Home, Draw, Away, Yes, No,
Over, Under, 1X, 12, X2) so a structured price can be compared with the live series word for word; a bet whose values are
not a closed vocabulary (HT/FT Double, Highest Scoring Half) keeps the provider's text as the selection.

The same rule as the live parser: a value that cannot be read is DROPPED and counted, never replaced by a plausible
neighbour. A line is a multiple of 0.25 (no bookmaker quotes anything else, so anything else is a parsing failure), and a
negative line is accepted only where the bet is signed. For the five bets the live pipeline reads the work is delegated to
the pipeline's own function, ``normalize._selection``, so the two series cannot disagree about what a row means.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from fbi.domain.market import NO_LINE
from fbi.odds.quote_taxonomy import BetSpec
from fbi.providers.api_football.normalize import MAX_ODDS, MIN_ODDS, _selection, _to_decimal

__all__ = ["parse_odds", "parse_selection"]

MAX_SELECTION_CHARS = 60
QUARTER = Decimal("0.25")
LINE_LIMIT = Decimal("1000")

_WORD_LINE = re.compile(r"^(?P<word>.*\S)\s+(?P<line>[+-]?\d+(?:\.\d+)?)$")

_HDA = {"home": "Home", "draw": "Draw", "away": "Away", "1": "Home", "x": "Draw", "2": "Away"}
_HA = {"home": "Home", "away": "Away", "1": "Home", "2": "Away"}
_YN = {"yes": "Yes", "no": "No"}
_OE = {"odd": "Odd", "even": "Even"}
_DC = {"home/draw": "1X", "home/away": "12", "draw/away": "X2", "1x": "1X", "12": "12", "x2": "X2"}
_OU = {"over": "Over", "under": "Under"}
_AH = {"home": "Home", "away": "Away", "1": "Home", "2": "Away"}

Parsed = tuple[str, Decimal]


def _text(value: Any, *, numbers: bool = False) -> str | None:
    """The provider's value as text. Only the free-text bets accept a number (the count markets send ``0``, ``1`` as
    integers): in a closed vocabulary an integer ``1`` must not become "Home" by way of the alias "1"."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if numbers and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    return None


def _closed(vocabulary: dict[str, str]) -> Callable[[BetSpec, Any], Parsed | None]:
    def parse(spec: BetSpec, value: Any) -> Parsed | None:
        text = _text(value)
        if text is None:
            return None
        word = vocabulary.get(text.lower())
        return None if word is None else (word, NO_LINE)

    return parse


def _lined(vocabulary: dict[str, str]) -> Callable[[BetSpec, Any], Parsed | None]:
    def parse(spec: BetSpec, value: Any) -> Parsed | None:
        text = _text(value)
        if text is None:
            return None
        match = _WORD_LINE.match(text)
        if match is None:
            return None
        word = vocabulary.get(match.group("word").strip().lower())
        if word is None:
            return None
        line = _to_decimal(match.group("line"))
        if line is None or abs(line) >= LINE_LIMIT or line % QUARTER != 0:
            return None
        if spec.away_line_negated and word == "Away":
            line = -line
        if line < 0 and not spec.line_is_signed:
            return None
        return word, line

    return parse


def _free(spec: BetSpec, value: Any) -> Parsed | None:
    text = _text(value, numbers=True)
    if text is None or len(text) > MAX_SELECTION_CHARS:
        return None
    return text, NO_LINE


def _legacy(spec: BetSpec, value: Any) -> Parsed | None:
    """The live pipeline's own reading, for the five bets it knows."""
    text = _text(value)
    if text is None or spec.market_key is None:
        return None
    selection = _selection(spec.market_key, text)
    if selection is None:
        return None
    return selection.side.value, selection.line_for_storage


SCHEMAS: dict[str, Callable[[BetSpec, Any], Parsed | None]] = {
    "legacy": _legacy,
    "hda": _closed(_HDA),
    "ha": _closed(_HA),
    "yn": _closed(_YN),
    "oe": _closed(_OE),
    "dc": _closed(_DC),
    "ou": _lined(_OU),
    "ah": _lined(_AH),
    "text": _free,
}


def parse_selection(spec: BetSpec, value: Any) -> Parsed | None:
    """``(selection, line)`` of one value of this bet, or None when the value is not a selection of it."""
    parser = SCHEMAS.get(spec.schema)
    if parser is None:
        return None
    return parser(spec, value)


def parse_odds(value: Any) -> Decimal | None:
    """The decimal odds, or None when unreadable or outside the range the pipeline accepts."""
    odds = _to_decimal(value)
    if odds is None or not (MIN_ODDS <= odds <= MAX_ODDS):
        return None
    return odds
