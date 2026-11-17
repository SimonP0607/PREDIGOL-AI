"""The prices of a player's shots and shots on target, read from one stored ``/odds`` answer (IA-130, AD-E04). Pure.

WHICH BETS. ``tax-v3`` (``fbi.odds.book_taxonomy``, validated value by value on 8 Nov 2026) reads three player counts that this
evaluation covers: 240 «Home Player Shots» and 241 «Away Player Shots» (``player.shots.ft.<side>``) and 269 «Home Player Shots On Target
Total» (``player.shots_on_target.ft.home``). Their values are ``"<name> - N"``: the player reaches at least N. Three more are HIDDEN by the
taxonomy with its evidence, and stay out: 275 «Away Player Shots On Target Total» (its values are the header-goal markets), 276 «Away
Player Shots Total» (a team-sized line) and 215 «Player Singles» (a duplicate of 240/241 under an opaque name). So the shots on target of
an away player have no readable price today: that gap is counted, not filled.

THE READING is ``fbi.odds.book.read_answer`` itself (the explorer's): a renamed bet, a bookmaker sending a type twice or a value that
cannot be read hides the type for that answer. Then each (family, side, name, N) keeps the odds of every house; ``books`` is how many
houses quote it. ``una_sola_casa``: one house - the norm today (the market registry of 16-nov-2026 found 240 and 241 in 58 matches and
269 in 13, each from one house at the median) - and below ``MIN_BOOKS`` (3, the catalogue's threshold) no price confirms anything.

THE NAME is matched to the men of the match's sheet of THAT side (``core.fixture_lineup_players``): the same key of IA-071
(``fbi.people.identity.names.alias_key``) first, else names that could be the same person (``names_compatible``: a surname, or an
initial and a surname), and only when exactly one man fits. Otherwise the price is ``sin_resolver`` and is counted, never guessed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from fbi.odds.book import read_answer
from fbi.people.identity.names import alias_key, names_compatible

MIN_BOOKS: Final = 3
"""Houses below which a price confirms nothing (``market-states-v1``: fewer than three is «una sola casa» in TESIS §E)."""
PRICED: Final[Mapping[int, tuple[str, str]]] = {240: ("player_shots", "home"), 241: ("player_shots", "away"),
                                                269: ("player_shots_on", "home")}
"""bet id -> (family of ``fbi.players.families``, side)."""
GAPS: Final[Mapping[int, tuple[str, str]]] = {275: ("player_shots_on", "away"), 276: ("player_shots", "away"),
                                              215: ("player_shots", "both")}
"""The player-shot bets the taxonomy hides (its reason travels with the count)."""
FAMILIES: Final = ("player_shots", "player_shots_on")
UNRESOLVED: Final = "sin_resolver"


@dataclass(frozen=True, slots=True)
class Quote:
    """One selection of one player at one line, with every house's odds."""

    family: str
    side: str
    name: str
    at_least: int
    odds: Mapping[int, Decimal]
    """provider bookmaker id -> decimal odds."""
    bet_ids: tuple[int, ...]

    @property
    def line(self) -> Decimal:
        """The family's line: «at least N» is «over N - 0.5»."""
        return Decimal(self.at_least) - Decimal("0.5")

    @property
    def books(self) -> int:
        return len(self.odds)

    @property
    def single_house(self) -> bool:
        return self.books == 1

    @property
    def best(self) -> Decimal:
        return max(self.odds.values())


@dataclass(frozen=True, slots=True)
class Reading:
    quotes: tuple[Quote, ...]
    hidden: Mapping[int, str]
    """bet id -> why it was not read (the taxonomy's reason, or the answer's problem)."""
    bookmakers: int


def read(entry: Mapping[str, Any]) -> Reading:
    """The player-shot prices of one ``response`` entry of an ``/odds`` answer. Pure."""
    got = read_answer(entry)
    hidden: dict[int, str] = {}
    for bet_id in GAPS:
        if bet_id in got.hidden_by_taxonomy:
            hidden[bet_id] = got.hidden_by_taxonomy[bet_id]
    cells: dict[tuple[str, str, str, int], dict[int, Decimal]] = defaultdict(dict)
    bets: dict[tuple[str, str, str, int], set[int]] = defaultdict(set)
    for bet_id, (family, side) in PRICED.items():
        held = got.types.get(bet_id)
        if held is None:
            continue
        if held.hidden is not None:
            hidden[bet_id] = held.hidden
            continue
        for book, r, odds in held.prices:
            if r.line is None:
                continue
            key = (family, side, r.selection, int(r.line))
            cells[key][book] = odds
            bets[key].add(bet_id)
    quotes = tuple(Quote(f, s, n, k, dict(sorted(o.items())), tuple(sorted(bets[(f, s, n, k)])))
                   for (f, s, n, k), o in sorted(cells.items()))
    return Reading(quotes, hidden, got.bookmakers)


def resolve(name: str, sheet: Sequence[tuple[int, str | None]]) -> int | None:
    """The provider player id of the one man of the side's sheet the name fits, else None. Pure."""
    key = alias_key(name)
    exact = sorted({pid for pid, n in sheet if n and alias_key(n) == key})
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    loose = sorted({pid for pid, n in sheet if n and names_compatible([name], [n])})
    return loose[0] if len(loose) == 1 else None


def resolved(quotes: Iterable[Quote], sheets: Mapping[str, Sequence[tuple[int, str | None]]]) -> list[tuple[Quote, int | None]]:
    """Each quote with the player it is about on its side's sheet (None: not resolved). Pure."""
    return [(q, resolve(q.name, sheets.get(q.side, ()))) for q in quotes]
