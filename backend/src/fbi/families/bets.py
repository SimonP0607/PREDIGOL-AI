"""The plan's criterion for a family to decide in shadow, measured every time the scoreboard runs (plan F11).

The plan lets a family move from research to deciding in shadow when it has at least ``MIN_BETS`` simulated bets and the closing-line value of those
bets is not negative. Nothing here decides, prices or picks, and what it prints promotes nothing: a family that meets the criterion is only one the
owner may now ask shadow decisions of. This module counts.

A simulated bet is what the pipeline would have done with a stored forecast, using nothing it could not have known by then:

* the forecast is the last one stored at least ``PICK_LEAD`` (a day) before the kick-off - not the last one before it, which knows more;
* the price is the best any complete book quoted for that selection at that moment (``versus.best_prices``), on a line that cannot push and with
  ``MIN_BOOKS`` or more books behind it, so that there is a market to be measured against;
* the bet is taken when the value the model sees at that price (``p_model x odds - 1``) is at least ``MIN_EV``, and only the best of each market of
  each match (the lines of a market are one view of the same question): one unit, one bet per model, match and market key;
* it is graded with the arithmetic of the scoreboard (``Graded.won``): a win returns ``odds - 1``, a loss ``-1``.

Four numbers say what the bets were worth, each on the same bets - those that also have a consensus at the last price before the kick-off, which
is what the closing-line value needs; the ones that have not are counted apart -:

    believed    the mean value the model saw at the price (at least ``MIN_EV`` by construction)
    at pick     the same price at the books' own probability that day (the consensus of the complete books, margin removed): what shopping for the
                best price is worth, less the margin
    CLV         the same price at the books' probability at the last price before the kick-off (``fbi.market.closing_value.clv``, the one
                definition of the system): a price the market later agreed with is positive
    return      what the bets returned per unit staked

The plan names the CLV. The return is shown beside it because it is what a bettor would have lived, and at these sizes it is luck: its standard error is
4 to 6 points at 300 bets, and the value the model believes is mostly its own bias (``FAMILIAS_VS_MERCADO_F11.md``). Standard errors are clustered by
match: the bets of one match are one observation of how its prices moved, not several.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from fbi.families import versus
from fbi.families.versus import FairKey
from fbi.market import closing_value

if TYPE_CHECKING:
    from fbi.families.score import Graded

MIN_BETS: Final = 300
"""The bets a family needs before its closing-line value is read as evidence (the plan's criterion)."""
MIN_EV: Final = 0.03
"""The value the model has to see at the price to take the bet: the floor of the simulated bets of ``FAMILIAS_VS_MERCADO_F11.md``."""
PICK_REF: Final = "h24"
CLOSE_REF: Final = "close"
PICK_LEAD: Final = dict(versus.REFERENCES)[PICK_REF]
"""How long before the kick-off the bet is taken: the last forecast stored by then, the best price quoted by then."""

TOO_FEW: Final = "TOO_FEW"
CLV_NEGATIVE: Final = "CLV_NEGATIVE"
MEETS: Final = "MEETS"
VERDICTS: Final = (TOO_FEW, CLV_NEGATIVE, MEETS)
WORDS: Final = {TOO_FEW: "too few bets", CLV_NEGATIVE: "closing-line value negative", MEETS: "meets the criterion"}


@dataclass(frozen=True, slots=True)
class Bet:
    """One simulated bet of one unit: what the model said, the price it was taken at, what the books thought of it, and what happened."""

    model: str
    key: str
    fixture_id: int
    line: Decimal
    selection: str
    p_model: float
    odds: float
    p_pick: float
    p_close: float | None
    won: int
    books: int

    @property
    def believed(self) -> float:
        """The value of the price at the model's probability."""
        return self.odds * self.p_model - 1.0

    @property
    def at_pick(self) -> float:
        """The value of the price at the books' probability the day of the bet."""
        return self.odds * self.p_pick - 1.0

    @property
    def clv(self) -> float | None:
        """The closing-line value (``clv-v1``), or None when no consensus of books stood at the last price before the kick-off."""
        return None if self.p_close is None else closing_value.clv(self.odds, self.p_close)

    @property
    def profit(self) -> float:
        return self.odds - 1.0 if self.won else -1.0


def simulate(graded: Iterable[Graded], fair: Mapping[FairKey, tuple[float, int]], best: Mapping[FairKey, tuple[float, int]], *,
             min_ev: float = MIN_EV, min_books: int = versus.MIN_BOOKS) -> list[Bet]:
    """The bets the stored forecasts ``graded`` (the last one at least ``PICK_LEAD`` before each kick-off) would have placed at the prices
    of the books: ``fair`` is their consensus and ``best`` their best price (``versus.consensus`` and ``versus.best_prices``, at the moments of
    ``versus.REFERENCES``). The best of each market of each match, per model."""
    chosen: dict[tuple[str, int, str], tuple[tuple[float, str, Decimal], Bet]] = {}
    for g in graded:
        row = g.row
        if not versus.comparable(row.line):
            continue
        priced = best.get((PICK_REF, row.fixture_id, row.key, row.line, row.selection))
        pick = fair.get((PICK_REF, row.fixture_id, row.key, row.line, row.selection))
        if priced is None or pick is None or pick[1] < min_books:
            continue
        odds = priced[0]
        believed = odds * row.p - 1.0
        if believed < min_ev:
            continue
        close = fair.get((CLOSE_REF, row.fixture_id, row.key, row.line, row.selection))
        p_close = close[0] if close is not None and close[1] >= min_books else None
        bet = Bet(row.model, row.key, row.fixture_id, row.line, row.selection, row.p, odds, pick[0], p_close, g.won, pick[1])
        rank = (believed, row.selection, row.line)  # the best value; a tie falls to the same selection whatever the order of the rows
        slot = (row.model, row.fixture_id, row.key)
        if slot not in chosen or rank > chosen[slot][0]:
            chosen[slot] = (rank, bet)
    return [bet for _, bet in sorted(chosen.values(), key=lambda x: (x[1].model, x[1].fixture_id, x[1].key))]


def verdict(n: int, clv: float | None, *, min_bets: int = MIN_BETS) -> str:
    """The plan's criterion: ``MIN_BETS`` bets, and a closing-line value that is not negative (zero passes)."""
    if n < min_bets:
        return TOO_FEW
    return MEETS if clv is not None and clv >= 0.0 else CLV_NEGATIVE


def _mean_se(items: Sequence[tuple[int, float]]) -> tuple[float, float]:
    """The mean of the values and its standard error, clustered by match (the first element of each pair)."""
    n = len(items)
    mean = sum(v for _, v in items) / n
    by_match: dict[int, float] = defaultdict(float)
    for fixture_id, v in items:
        by_match[fixture_id] += v - mean
    return mean, math.sqrt(sum(s * s for s in by_match.values())) / n


def _block(bets: Sequence[Bet]) -> dict[str, Any]:
    """The numbers of bets that all have a closing consensus."""
    n = len(bets)
    if n == 0:
        return {"n": 0, "fixtures": 0, "mean_odds": None, "hit_rate": None, "believed": None, "at_pick": None, "clv": None, "clv_se": None,
                "return": None, "return_se": None}
    clv, clv_se = _mean_se([(b.fixture_id, v) for b in bets if (v := b.clv) is not None])
    profit, profit_se = _mean_se([(b.fixture_id, b.profit) for b in bets])
    return {"n": n, "fixtures": len({b.fixture_id for b in bets}), "mean_odds": sum(b.odds for b in bets) / n,
            "hit_rate": sum(b.won for b in bets) / n, "believed": sum(b.believed for b in bets) / n,
            "at_pick": sum(b.at_pick for b in bets) / n, "clv": clv, "clv_se": clv_se, "return": profit, "return_se": profit_se}


def report(graded: Iterable[Graded], fair: Mapping[FairKey, tuple[float, int]], best: Mapping[FairKey, tuple[float, int]], *,
           min_ev: float = MIN_EV, min_books: int = versus.MIN_BOOKS, min_bets: int = MIN_BETS) -> dict[str, Any]:
    """The simulated bets of every model that has a graded forecast, summed up and set against the criterion."""
    rows = list(graded)
    taken: dict[str, list[Bet]] = {model: [] for model in sorted({g.row.model for g in rows})}
    for bet in simulate(rows, fair, best, min_ev=min_ev, min_books=min_books):
        taken[bet.model].append(bet)
    models: dict[str, Any] = {}
    for model, members in taken.items():
        priced = [b for b in members if b.p_close is not None]
        block = _block(priced)
        by_key = [{"key": key, **_block([b for b in priced if b.key == key])} for key in sorted({b.key for b in priced})]
        models[model] = {**block, "taken": len(members), "no_closing_line": len(members) - len(priced), "needed": max(0, min_bets - len(priced)),
                         "verdict": verdict(len(priced), block["clv"], min_bets=min_bets), "by_key": by_key}
    return {"criterion": {"min_bets": min_bets, "min_ev": min_ev, "min_books": min_books, "pick": PICK_REF, "close": CLOSE_REF}, "models": models}


def _pct(value: float) -> str:
    return f"{value * 100:+.1f} %"


def _plus_minus(value: float, se: float) -> str:
    return f"{value * 100:+.1f} % ± {se * 100:.1f}"


def render(report: Mapping[str, Any], *, min_rows: int = 50) -> str:
    """The criterion as text, model by model: where each stands on the bets it needs and on its closing-line value."""
    c = report["criterion"]
    if not report["models"]:
        return (f"  the plan's criterion for a family to decide in shadow: no forecast stored {PICK_LEAD.total_seconds() / 3600:g} hours or more "
                "before a kick-off has been graded yet")
    lines = [f"the plan's criterion for a family to decide in shadow: {c['min_bets']}+ simulated bets (1 unit at the best price {PICK_LEAD.total_seconds() / 3600:g} h "
             f"before the kick-off, when the model saw a value of {c['min_ev'] * 100:g} % or more; the best of each market of a match) and a closing-line "
             f"value that is not negative (it promotes nothing; the owner decides):"]
    for model, m in report["models"].items():
        short = f" ({m['needed']} short of {c['min_bets']})" if m["needed"] else ""
        left = f"; {m['no_closing_line']} more with no closing consensus" if m["no_closing_line"] else ""
        if m["n"] == 0:
            lines.append(f"  {model}: no bet{left} -> {WORDS[m['verdict']]}")
            continue
        noise = ""
        if m["verdict"] == MEETS and m["clv"] < 2 * m["clv_se"]:
            noise = ", but the closing-line value is within 2 standard errors of zero"
        lines.append(f"  {model}: {m['n']} bets in {m['fixtures']} matches{short}{left} - the model believed {_pct(m['believed'])}, the books' "
                     f"probability that day {_pct(m['at_pick'])}, closing line {_plus_minus(m['clv'], m['clv_se'])}, return "
                     f"{_plus_minus(m['return'], m['return_se'])} -> {WORDS[m['verdict']]}{noise}")
        for x in m["by_key"]:
            if x["n"] >= min_rows:
                lines.append(f"      {x['key']:<16} n {x['n']:>5}  believed {_pct(x['believed'])}  that day {_pct(x['at_pick'])}  closing line "
                             f"{_plus_minus(x['clv'], x['clv_se'])}  return {_plus_minus(x['return'], x['return_se'])}")
    return "\n".join(lines)
