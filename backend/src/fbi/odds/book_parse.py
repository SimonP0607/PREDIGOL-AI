"""Read one provider ``value`` of a bet type for the current-price book: the readers of ``tax-v3`` (plan Cuotas, phase 2).

``fbi.odds.quote_parse`` reads the 55 bets ``tax-v2`` extracts; this module reads the 128 visible types of ``tax-v3``
(``fbi.odds.book_taxonomy``), the same way where the two meet: the shared words become the tokens ``market.odds_quotes``
already stores (Home, Draw, Away, Yes, No, Over, Under, 1X, 12, X2, Odd, Even), a line is a multiple of 0.25, and an Asian
handicap's away row is negated (the provider prints the HOME handicap on both rows). For the 42 extracted types that arrived in the
samples the two readings agree value for value (``tests/unit/test_book_taxonomy.py``).

The same rule as every parser of the platform: a value that cannot be read is never replaced by a plausible neighbour. Here it
is stricter still - ``read_value`` returns None and the book HIDES the whole type for that match (``fbi.odds.book``): a reading
that failed once in an answer is not trusted for the rest of it. ``check_book`` adds what one value cannot tell: the values of one
bookmaker for one type must make sense together (no selection twice at two prices, bands that do not overlap, a two-way line
that is not a three-way line with its "Exactly" missing).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from fbi.odds.book_taxonomy import BookSpec

__all__ = ["Read", "band", "check_book", "format_number", "group_outcomes", "partition_complete", "read_value", "ways_of"]

QUARTER = Decimal("0.25")
LINE_LIMIT = Decimal("1000")
MAX_COUNT = 99
MAX_NAME_CHARS = 60

_WORD_LINE = re.compile(r"^(?P<word>.*\S)\s+(?P<line>[+-]?\d+(?:\.\d+)?)$")
_SCORE = re.compile(r"^(\d{1,2})\s*:\s*(\d{1,2})$")
_HT_FT = re.compile(r"^(home|draw|away)\s*/\s*(home|draw|away)$")
_RESULT_TOTAL = re.compile(r"^(home|draw|away)\s*/\s*(over|under)\s+(\d+(?:\.\d+)?)$")
_TOTAL_BTTS = re.compile(r"^(o|u|over|under)\s*/\s*(yes|no)\s+(\d+(?:\.\d+)?)$")
_MORE = re.compile(r"^more\s+(\d{1,2})$")
_UNDER_BAND = re.compile(r"^under\s+(\d{1,3})$")
_OVER_BAND = re.compile(r"^over\s+(\d{1,3})$")
_BAND = re.compile(r"^(\d{1,3})\s*(?:-|or|to)\s*(\d{1,3})$")
_GOALS_SUFFIX = re.compile(r"\s+goals?$")
_PLAYER_COUNT = re.compile(r"^(?P<name>.+?)\s+-\s+(?P<n>\d{1,3})$")
_NAME = re.compile("^[^\\W\\d_](?:[^\\W\\d_]|[ '\u2019.\\-])*$")
_HDA_WORDS = {"home": "Home", "draw": "Draw", "away": "Away"}


@dataclass(frozen=True, slots=True)
class Read:
    """One value read: the selection, its own line, and the line its group is shown under."""

    selection: str
    line: Decimal | None
    """The line that applies to this selection (an Asian handicap's away row: the negated printed number). None: no line."""
    group: Decimal | None
    """The line the selection is grouped under: the line itself, except an Asian handicap's pair, grouped by the HOME
    handicap (Home h with Away -h). None: the market has no line."""


def _text(value: Any) -> str | None:
    """The provider's value as text with its spaces collapsed. Only strings: in a closed vocabulary an integer ``1`` must not
    become "Home" through the alias "1"."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _number(text: str) -> Decimal | None:
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or abs(number) >= LINE_LIMIT or number % QUARTER != 0:
        return None
    return Decimal(0) if number == 0 else number


def _plain(spec: BookSpec, value: Any) -> Read | None:
    text = _text(value)
    token = spec.vocabulary.get(text.casefold()) if text else None
    return None if token is None else Read(token, None, None)


def _line(spec: BookSpec, value: Any) -> Read | None:
    text = _text(value)
    match = _WORD_LINE.match(text) if text else None
    if match is None:
        return None
    word = spec.vocabulary.get(match.group("word").casefold())
    line = _number(match.group("line"))
    if word is None or line is None or line < 0:
        return None
    if (spec.integer_lines or word == "Exactly") and line % 1 != 0:
        return None
    return Read(word, line, line)


def _signed_line(spec: BookSpec, value: Any) -> Read | None:
    """Asian handicap: the printed number is the HOME handicap on both rows; the away row's own line is its negation."""
    text = _text(value)
    match = _WORD_LINE.match(text) if text else None
    if match is None:
        return None
    word = spec.vocabulary.get(match.group("word").casefold())
    home = _number(match.group("line"))
    if word not in ("Home", "Away") or home is None:
        return None
    own = home if word == "Home" else (Decimal(0) if home == 0 else -home)
    return Read(word, own, home)


def _signed_line_3way(spec: BookSpec, value: Any) -> Read | None:
    """European handicap: three rows with the same printed number, the HOME handicap of a three-way market."""
    text = _text(value)
    match = _WORD_LINE.match(text) if text else None
    if match is None:
        return None
    word = spec.vocabulary.get(match.group("word").casefold())
    home = _number(match.group("line"))
    if word is None or home is None or home % 1 != 0:
        return None
    return Read(word, home, home)


def _exact_score(spec: BookSpec, value: Any) -> Read | None:
    text = _text(value)
    match = _SCORE.match(text) if text else None
    return None if match is None else Read(f"{int(match.group(1))}:{int(match.group(2))}", None, None)


def _ht_ft(spec: BookSpec, value: Any) -> Read | None:
    text = _text(value)
    match = _HT_FT.match(text.casefold()) if text else None
    if match is None:
        return None
    return Read(f"{_HDA_WORDS[match.group(1)]}/{_HDA_WORDS[match.group(2)]}", None, None)


def _result_total(spec: BookSpec, value: Any) -> Read | None:
    text = _text(value)
    match = _RESULT_TOTAL.match(text.casefold()) if text else None
    line = _number(match.group(3)) if match else None
    if match is None or line is None:
        return None
    return Read(f"{_HDA_WORDS[match.group(1)]}/{match.group(2).title()}", line, line)


def _total_btts(spec: BookSpec, value: Any) -> Read | None:
    text = _text(value)
    match = _TOTAL_BTTS.match(text.casefold()) if text else None
    line = _number(match.group(3)) if match else None
    if match is None or line is None:
        return None
    total = "Over" if match.group(1).startswith("o") else "Under"
    return Read(f"{total}/{match.group(2).title()}", line, line)


def _count(spec: BookSpec, value: Any) -> Read | None:
    """An exact count: the provider sends the numbers as integers and the last one as "more N", which is N OR MORE (every
    bookmaker of the samples lists 0 .. N-1 and then "more N"; ``check_book`` refuses a book where N appears twice)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return Read(str(value), None, None) if 0 <= value <= MAX_COUNT else None
    text = _text(value)
    if text is None:
        return None
    if text.isdigit():
        number = int(text)
        return Read(str(number), None, None) if number <= MAX_COUNT else None
    match = _MORE.match(text.casefold())
    return None if match is None else Read(f"{int(match.group(1))}+", None, None)


def _range(spec: BookSpec, value: Any) -> Read | None:
    """Bands of a count: "Under 6" is 0-5, "6 - 8" is 6-8, "Over 14" is 15+; "Under 2 goals", "2 or 3 goals", "Over 3 goals"
    are 0-1, 2-3 and 4+. ``check_book`` refuses bands that overlap, so a band read the wrong way cannot be shown."""
    text = _text(value)
    if text is None:
        return None
    text = _GOALS_SUFFIX.sub("", text.casefold())
    if match := _UNDER_BAND.match(text):
        top = int(match.group(1)) - 1
        return None if top < 0 else Read(f"0-{top}", None, None)
    if match := _OVER_BAND.match(text):
        return Read(f"{int(match.group(1)) + 1}+", None, None)
    if match := _BAND.match(text):
        low, high = int(match.group(1)), int(match.group(2))
        return None if low > high else Read(f"{low}-{high}", None, None)
    return None


def _name(text: str) -> bool:
    return len(text) <= MAX_NAME_CHARS and sum(c.isalpha() for c in text) >= 2 and _NAME.match(text) is not None


def _player(spec: BookSpec, value: Any) -> Read | None:
    text = _text(value)
    if text is None:
        return None
    outcome = spec.vocabulary.get(text.casefold())
    if outcome is not None:
        return Read(outcome, None, None)
    return Read(text, None, None) if _name(text) else None


def _player_count(spec: BookSpec, value: Any) -> Read | None:
    """ "Mohamed Salah - 2": the player reaches at least 2 (the prices rise with N in every sample). The line is N."""
    text = _text(value)
    match = _PLAYER_COUNT.match(text) if text else None
    if match is None or not _name(match.group("name")):
        return None
    count = Decimal(int(match.group("n")))
    return Read(match.group("name"), count, count)


READERS: dict[str, Callable[[BookSpec, Any], Read | None]] = {
    "plain": _plain,
    "line": _line,
    "signed_line": _signed_line,
    "signed_line_3way": _signed_line_3way,
    "exact_score": _exact_score,
    "ht_ft": _ht_ft,
    "result_total": _result_total,
    "total_btts": _total_btts,
    "count": _count,
    "range": _range,
    "player": _player,
    "player_count": _player_count,
}


def read_value(spec: BookSpec, value: Any) -> Read | None:
    """The selection and line of one value of this type, or None when the value is not one of its selections."""
    reader = READERS.get(spec.reader)
    return None if reader is None else reader(spec, value)


# ── what one bookmaker's values must say together ─────────────────────────────────────────────────────────────────


def band(token: str) -> tuple[int, int | None] | None:
    """The interval of a ``count`` or ``range`` token: "3" -> (3, 3), "6+" -> (6, None), "6-8" -> (6, 8)."""
    if token.endswith("+") and token[:-1].isdigit():
        return int(token[:-1]), None
    if token.isdigit():
        return int(token), int(token)
    low, sep, high = token.partition("-")
    if sep and low.isdigit() and high.isdigit():
        return int(low), int(high)
    return None


def _overlap(tokens: Sequence[str]) -> bool:
    bands = sorted((b for b in map(band, tokens) if b is not None), key=lambda b: b[0])
    return any(high is None or low <= high for (_, high), (low, _) in pairwise(bands))


def partition_complete(tokens: Sequence[str]) -> bool:
    """Whether the bands cover 0, 1, 2 ... with no gap and an open last band: every outcome, each once."""
    bands = sorted((b for b in map(band, tokens) if b is not None), key=lambda b: b[0])
    if len(bands) != len(tokens) or not bands or bands[0][0] != 0:
        return False
    for (_, high), (low, _) in pairwise(bands):
        if high is None or low != high + 1:
            return False
    return bands[-1][1] is None


def ways_of(spec: BookSpec, reads: Sequence[Read]) -> dict[Decimal | None, int]:
    """How many ways each group of one bookmaker's values is: 3 for a three-way line (Over / Exactly / Under, a race, a European
    handicap), 2 otherwise. ``when_exactly``: a line is three-way where this bookmaker quotes "Exactly" at it."""
    groups = {r.group for r in reads}
    if spec.reader == "line":
        if spec.three_way == "always":
            return dict.fromkeys(groups, 3)
        if spec.three_way == "when_exactly":
            exact = {r.group for r in reads if r.selection == "Exactly"}
            return {g: 3 if g in exact else 2 for g in groups}
        return dict.fromkeys(groups, 2)
    if spec.reader == "signed_line_3way":
        return dict.fromkeys(groups, 3)
    return dict.fromkeys(groups, 2 if spec.reader == "signed_line" else 0)


def group_outcomes(spec: BookSpec, ways: int) -> tuple[str, ...]:
    """The tokens a complete book of one group quotes, in the order they are shown; empty where the set is open (scores,
    players) or checked as bands (``partition_complete``)."""
    if spec.reader == "line":
        if ways == 3:
            return spec.outcomes if len(spec.outcomes) == 3 else ("Over", "Exactly", "Under")
        return ("Over", "Under")
    return spec.outcomes


def check_book(spec: BookSpec, priced: Sequence[tuple[Read, Decimal]]) -> str | None:
    """What is wrong with one bookmaker's values of one type taken together, or None. ``priced``: every value read, with its
    odds (a value whose odds were not a price is not in it)."""
    seen: dict[tuple[str, Decimal | None], Decimal] = {}
    for read, odds in priced:
        key = (read.selection, read.line)
        held = seen.get(key)
        if held is not None and held != odds:
            return f"{read.selection} {read.line} quoted twice at two prices"
        seen[key] = odds
    if spec.reader in ("count", "range") and _overlap(list(dict.fromkeys(r.selection for r, _ in priced))):
        return "bands that overlap: the values are not read the way they are written"
    if spec.reader == "line" and spec.three_way == "when_exactly":
        ways = ways_of(spec, [r for r, _ in priced])
        for group, n in ways.items():
            if n != 2 or group is None or group % 1 != 0:
                continue
            pair = {r.selection: o for r, o in priced if r.group == group}
            if {"Over", "Under"} <= set(pair) and 1 / pair["Over"] + 1 / pair["Under"] <= 1:
                return f"a two-way line {group} with no margin: a three-way line whose 'Exactly' is missing?"
    return None


def format_number(number: Decimal) -> str:
    """A line or a price as the shortest exact text: 2.5, -0.25, 10, 1.83."""
    text = format(number.normalize(), "f")
    return "0" if text in ("-0", "0") else text
