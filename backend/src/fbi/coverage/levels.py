"""The rules ``coverage-levels-v1`` (plan PM, section 4; PM-02-01, decision DM-04): the level of a datum, of a market and the
summary of a competition season, from what was measured. Pure: no database, no clock, no environment.

The unit is competition x season x phase x datum (or market). A level is graded on the finished matches of that unit:

* ``A`` (completa): at least ``A_SHARE`` of them carry the datum and there are at least ``A_SAMPLE``;
* ``B`` (intermedia): at least ``B_SHARE``; ``C`` (básica): at least ``C_SHARE``; ``D`` (limitada): less;
* ``MI`` (muestra insuficiente): fewer than ``MIN_SAMPLE`` matches, whatever the share.

A market is graded the same way on the finished matches of the odds window, and the median of houses that price it caps it: ``A``
needs ``A_BOOKS`` or more, fewer than ``MIN_BOOKS`` leaves it at ``C`` at best. A ``B`` below ``A_SAMPLE`` matches is provisional
(with 80 % of 10 the lower end of Wilson's interval is 0.49); a season below ``MIN_SAMPLE`` takes the level of the season before,
provisional. A level goes up as soon as it is met and down only after two recalculations in a row miss it (``step``).

The thresholds are the ones the code already decides with, imported and not copied, so that they cannot drift apart:
``B_SHARE`` and ``MIN_SAMPLE`` settle a market (``fbi.market.settle_coverage``), ``C_SHARE`` and ``A_SAMPLE`` keep a market off the
catalogue or call its settlement verified (``fbi.api.services.market_status``), ``MIN_BOOKS`` is Mi parlay's (``fbi.market
.eligibility``). Only ``A_SHARE`` and ``A_BOOKS`` are new (DM-04). Changing any of them is a new rules version, never an edit.

What a datum counts as present (filled for both teams; an empty value is not a zero), the five editions pooled for one-match
competitions and the provider's flag (used only when it says «no») belong to the measurement (PM-02-03), not to these rules: it
hands over the counts, which ``combine`` adds up across phases or editions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from fbi.api.services.market_status import MIN_SETTLE_SAMPLE, NO_SETTLEMENT
from fbi.market.eligibility import MIN_BOOKS as PARLAY_MIN_BOOKS
from fbi.market.settle_coverage import MIN_MATCHES, MIN_SHARE, Coverage

RULES_VERSION: Final = "coverage-levels-v1"

Level = Literal["A", "B", "C", "D", "MI"]
LEVELS: Final[tuple[Level, ...]] = ("A", "B", "C", "D", "MI")
"""Best first. ``MI`` ranks last: a family with one datum short of sample is short of sample."""
RANK: Final[dict[Level, int]] = {"A": 4, "B": 3, "C": 2, "D": 1, "MI": 0}

# ── thresholds (coverage-levels-v1) ──────────────────────────────────────────────────────────────────────────────────────

A_SHARE: Final = 0.95
"""New (DM-04): with 95 % of 30 matches the lower end of Wilson's interval is 0.81, still above ``B_SHARE``."""
B_SHARE: Final = MIN_SHARE
"""0.80: a statistic is published, a market settled and a league called covered at this share."""
C_SHARE: Final = NO_SETTLEMENT
"""0.50: below it a market is not offered."""
MIN_SAMPLE: Final = MIN_MATCHES
"""10 finished matches: fewer is ``MI``."""
A_SAMPLE: Final = MIN_SETTLE_SAMPLE
"""30 finished matches: needed for ``A``; a ``B`` below it is provisional."""
MIN_BOOKS: Final = PARLAY_MIN_BOOKS
"""3 houses (median): fewer caps a market at ``C``."""
A_BOOKS: Final = 5
"""New (DM-04): houses (median) a market needs for ``A``; with 3 or 4 it is ``B`` at best."""

# ── data, markets and families ───────────────────────────────────────────────────────────────────────────────────────

DATA: Final[tuple[str, ...]] = (
    "events", "lineups", "corners", "yellow_cards", "shots", "shots_on_target", "fouls", "xg", "player_stats", "referee",
)
"""The data graded per match. ``xg`` is the provider's; ``player_stats`` is a player line per match."""
MARKETS: Final[tuple[str, ...]] = ("1X2", "OU", "BTTS", "AH", "goals_half", "corners", "cards", "shots", "players")
"""The markets graded on the odds window: four of Mi parlay's core keys (``fbi.market.eligibility.CORE``) and five families of the
catalogue of prices (``fbi.odds.quote_taxonomy``)."""

DATA_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "base": ("events", "lineups"),
    "team_stats": ("corners", "yellow_cards", "shots"),
    "xg": ("xg",),
    "player_stats": ("player_stats",),
    "referee": ("referee",),
}
MARKET_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "main_odds": ("1X2", "OU", "BTTS"),
    "stat_odds": ("corners", "cards"),
}
FAMILIES: Final[tuple[str, ...]] = (*DATA_FAMILIES, *MARKET_FAMILIES)

# ── grading ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def datum_level(share: float | None, n: int) -> Level:
    """The level of a datum carried by ``share`` (0 to 1) of ``n`` finished matches; ``share`` None when nothing was measured."""
    if n < MIN_SAMPLE or share is None:
        return "MI"
    if share >= A_SHARE and n >= A_SAMPLE:
        return "A"
    if share >= B_SHARE:
        return "B"
    if share >= C_SHARE:
        return "C"
    return "D"


def market_level(share: float | None, n: int, books: float | None) -> Level:
    """The level of a market priced in ``share`` of the ``n`` finished matches of the odds window, by a median of ``books`` houses
    (None when the window does not say): the datum's level, at most ``C`` below ``MIN_BOOKS`` and at most ``B`` below ``A_BOOKS``."""
    base = datum_level(share, n)
    if base in ("MI", "D"):
        return base
    if books is None or books < MIN_BOOKS:
        return "C"
    if base == "A" and books < A_BOOKS:
        return "B"
    return base


@dataclass(frozen=True, slots=True)
class Grade:
    """A graded cell. ``reason`` uses the vocabulary of the code: ``muestra_insuficiente`` (``MI``), ``heredado`` (the season
    before, short of sample now), ``menos_de_3_casas`` / ``menos_de_5_casas`` (a market capped by its houses); None otherwise."""

    level: Level
    provisional: bool
    reason: str | None = None


def _grade(level: Level, n: int, previous: Level | None, capped: str | None) -> Grade:
    if level == "MI":
        if previous is not None and previous != "MI":
            return Grade(previous, True, "heredado")
        return Grade("MI", False, "muestra_insuficiente")
    return Grade(level, level == "B" and n < A_SAMPLE, capped)


def grade_datum(coverage: Coverage, *, previous: Level | None = None) -> Grade:
    """The grade of a datum of one unit from its counts. ``previous``: the level of the same cell in the season before, which a
    season short of sample takes, provisional."""
    share = coverage.share if coverage.finished else None
    return _grade(datum_level(share, coverage.finished), coverage.finished, previous, None)


def grade_market(coverage: Coverage, books: float | None, *, previous: Level | None = None) -> Grade:
    """The grade of a market of one unit: ``coverage`` counts the finished matches of the odds window and those priced."""
    share = coverage.share if coverage.finished else None
    level = market_level(share, coverage.finished, books)
    unbounded = datum_level(share, coverage.finished)
    capped = None
    if level != unbounded:
        capped = "menos_de_5_casas" if level == "B" else "menos_de_3_casas"
    return _grade(level, coverage.finished, previous, capped)


def combine(parts: Iterable[Coverage]) -> Coverage:
    """The counts of several units added up: the phases of a season, or the editions of a one-match competition. A level is
    always graded on summed counts, never averaged from the levels of the parts."""
    finished = with_data = 0
    for p in parts:
        finished += p.finished
        with_data += p.with_data
    return Coverage(finished, with_data)


def worst(levels: Iterable[Level]) -> Level:
    """The lowest of ``levels`` (``MI`` lowest of all). Raises ``ValueError`` when there is none."""
    found = list(levels)
    if not found:
        raise ValueError("no level to compare")
    return min(found, key=RANK.__getitem__)


def at_least(level: Level, floor: Level) -> bool:
    return RANK[level] >= RANK[floor]


def family_levels(data: Mapping[str, Level], markets: Mapping[str, Level]) -> dict[str, Level]:
    """The level of each family: the worst of its data or markets. A market without odds window is passed as ``MI``."""
    out = {name: worst(data[d] for d in keys) for name, keys in DATA_FAMILIES.items()}
    out.update({name: worst(markets[m] for m in keys) for name, keys in MARKET_FAMILIES.items()})
    return out


@dataclass(frozen=True, slots=True)
class Summary:
    """The summary of a competition season, for the directory only (I08): no page decides with it. ``without_odds``: the main
    odds are short of sample (no window, or 1 to 9 matches in it) and the summary was made with the match data alone."""

    level: Level
    without_odds: bool = False

    @property
    def label(self) -> str:
        return f"{self.level}*" if self.without_odds else self.level


def summary_level(data: Mapping[str, Level], markets: Mapping[str, Level]) -> Summary:
    """The summary from the levels of every datum and market (``DATA`` and ``MARKETS``):

    * ``A``: base A, team stats A, player stats B or more, main odds A and corner odds B or more;
    * ``B``: base, team stats and main odds B or more; ``C``: base B or more and main odds C or more;
    * without main odds: ``B*`` with base and team stats B or more, ``C*`` with base B or more;
    * ``MI`` when base (or the main odds) and the team stats are short of sample; ``D`` the rest.
    """
    fam = family_levels(data, markets)
    base, team, player, odds = fam["base"], fam["team_stats"], fam["player_stats"], fam["main_odds"]
    if "MI" in (base, odds) and team == "MI":
        return Summary("MI")
    if (base == "A" and team == "A" and at_least(player, "B") and odds == "A"
            and at_least(markets["corners"], "B")):
        return Summary("A")
    if at_least(base, "B") and at_least(team, "B") and at_least(odds, "B"):
        return Summary("B")
    if at_least(base, "B") and at_least(odds, "C"):
        return Summary("C")
    if base == "MI" or odds == "MI":
        if at_least(base, "B") and at_least(team, "B"):
            return Summary("B", without_odds=True)
        if at_least(base, "B"):
            return Summary("C", without_odds=True)
        return Summary("MI" if base == "MI" else "D")
    return Summary("D")


# ── recalculation ────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Step:
    """What a recalculation publishes. ``missed``: it measured less than the published level and kept it; the next one that
    misses it too lowers it."""

    level: Level
    missed: bool = False


def step(published: Level | None, measured: Level, *, missed_before: bool) -> Step:
    """Rule 4: a level goes up (or stays) as soon as it is measured; it goes down only when two recalculations in a row measure
    less than it. ``published``: None for a cell never graded. ``missed_before``: the previous recalculation missed it."""
    if published is None or RANK[measured] >= RANK[published]:
        return Step(measured)
    if missed_before:
        return Step(measured)
    return Step(published, missed=True)
