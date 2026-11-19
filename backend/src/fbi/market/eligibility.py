"""Which selections Mi parlay takes (plan EA, EA-501): one rule, read by the server when a leg is added and by C-14 when it marks a
price as selectable, so that the page never offers what the server would refuse. Pure.

The five markets of today (1X2, OU, BTTS, AH, DC of the match, full time) keep exactly their behaviour: settled on the score, no
quarter line. With ``FBI_PARLAY_MARKETS_V2`` on, a selection of any other market is taken when its market has a settlement rule of
IA-070 (``fbi.market.rules.rule_for``), the catalogue does not hold it ``no_ofrecer``, the match's competition season records what
the rule settles on (``fbi.market.settle_coverage``, 80 % of its finished matches), at least ``MIN_BOOKS`` houses price it now, and
its line is not a quarter. Nothing here changes Mi parlay's other rules (two to ten legs, one per match, the outlier price).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Final

from fbi.market.rules import Rule, rule_for
from fbi.odds.quote_current import market_key
from fbi.odds.quote_taxonomy import BetSpec, extracted_specs

CORE: Final = frozenset({"1X2", "OU", "BTTS", "AH", "DC"})
MIN_BOOKS: Final = 3


def quarter_line(line: Decimal) -> bool:
    return abs(line * 4) % 2 == 1


@dataclass(frozen=True, slots=True)
class Verdict:
    allowed: bool
    reason: str
    rule: Rule | None = None


def core_market(spec: BetSpec) -> bool:
    return spec.market_key in CORE and spec.period == "FT" and spec.subject == "match"


def verdict(spec: BetSpec, *, line: Decimal, books: int, state: str, started: bool, switch_on: bool,
            covered: Callable[[Rule], bool] | None = None) -> Verdict:
    """Whether Mi parlay takes a selection of ``spec`` at ``line`` priced now by ``books`` houses, its market in catalogue ``state``.
    ``covered``: whether the match's competition season records what the rule settles on (``fbi.market.settle_coverage``); a
    market of the catalogue is refused ``sin_cobertura`` where it does not (decision of 19-nov-2026)."""
    if started:
        return Verdict(False, "empezado")
    if core_market(spec):
        return Verdict(False, "linea_de_cuarto") if quarter_line(line) else Verdict(True, "ok")
    if not switch_on:
        return Verdict(False, "interruptor_apagado")
    rule = rule_for(spec)
    if rule is None:
        return Verdict(False, "sin_regla")
    if state == "no_ofrecer":
        return Verdict(False, "no_ofrecer", rule)
    if covered is not None and not covered(rule):
        return Verdict(False, "sin_cobertura", rule)
    if books < MIN_BOOKS:
        return Verdict(False, "menos_de_3_casas", rule)
    if quarter_line(line):
        return Verdict(False, "linea_de_cuarto", rule)
    return Verdict(True, "ok", rule)


@cache
def _by_key() -> dict[str, BetSpec]:
    out: dict[str, BetSpec] = {}
    for spec in sorted(extracted_specs(), key=lambda s: s.bet_id):
        out.setdefault(market_key(spec.bet_id, spec.period, spec.subject), spec)
    return out


def spec_for_key(key: str) -> BetSpec | None:
    """The bet a leg's market key names: one of the five (``1X2`` ...) or the stable key of the catalogue of prices
    (``corners_over_under.FT.match``); None for anything else. Two provider ids of one market (307 and 339) read as the lower."""
    if key in CORE:
        return next((s for s in extracted_specs() if s.market_key == key), None)
    return _by_key().get(key)
