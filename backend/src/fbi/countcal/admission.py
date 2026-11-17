"""Which corners or cards selection may enter the private evaluation (IA-096, plan piece AD-E03). Pure: no database, no clock.

A selection of a family of counts (``CORNERS_OU``, ``CORNERS_OU_HOME``, ``CORNERS_OU_AWAY``, ``CARDS_OU``, ``CARDS_OU_HOME``,
``CARDS_OU_AWAY``) enters the private evaluation - the cycle of states of ``fbi.lifecycle``, under the writer ``count-eval-v1`` - only
when ALL of these hold, checked in this order (the first that fails is the reason, in the cycle's own words):

    1. a settlement rule that can be verified: the family's rule (``corners_ft@v1``, ``cards_lines_ft@v1`` in ``fbi.market.rules``)
       exists and reads columns, and the line is a half line (no push: the calibrated probability and the settlement are the same
       question)                                                                                        else ``datos_insuficientes``
    2. a calibrator of the family with the verdict VALIDADO of the protocol AD-B07 AND the owner's CHAMPION signature
       (``fbi.countcal.store.champions``)                                                                else ``sin_calibrar``
    3. a price: at least one complete book at that line                                                  else ``sin_precio``
    4. at least ``MIN_BOOKS`` (3) complete books behind the price                                         else ``mercado_estrecho``

The cards are settled in ONE convention, the one the catalogue links ``Cards Over/Under`` to (every card one: ``cards_lines_ft@v1``);
the provider does not say which convention each house uses, so the rule applied travels with the admission (``rule``) and the LAB
measures how often the other reading (yellow cards only) would settle the same line differently. A count that is missing after the
match (the 16 % of priced matches without corners) settles as ``None`` (``fbi.picks.count_settlement.settle_numbers``), never as a loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from fbi.countcal import calibrator as cc
from fbi.market.rules import RULES_BY_MEASURE

WRITER: Final = "count-eval-v1"
MIN_BOOKS: Final = 3
ADMITTED: Final = "admitida"
NO_RULE: Final = "datos_insuficientes"
NOT_CALIBRATED: Final = "sin_calibrar"
NO_PRICE: Final = "sin_precio"
THIN: Final = "mercado_estrecho"
REASONS: Final = (ADMITTED, NO_RULE, NOT_CALIBRATED, NO_PRICE, THIN)
"""``admitida`` and four blockers of the cycle (``fbi.lifecycle.machine.BLOCKERS``)."""


@dataclass(frozen=True, slots=True)
class Facts:
    """What the admission reads of one selection."""

    market_key: str
    line: Decimal
    books: int
    """Complete books quoting the selection's line at the moment (0: none)."""
    validated: bool
    """The family has a calibrator with the verdict VALIDADO."""
    signed: bool
    """... and the owner signed it CHAMPION."""


@dataclass(frozen=True, slots=True)
class Admission:
    admitted: bool
    reason: str
    detail: str
    family: str
    rule: str | None


def family_of(market_key: str) -> str | None:
    found = cc.FAMILY_OF_KEY.get(market_key)
    return None if found is None else found[0]


def rule_of(family: str) -> str | None:
    """The key of the settlement rule of a family, when it reads columns (``corners_ft@v1``, ``cards_lines_ft@v1``)."""
    rule = RULES_BY_MEASURE.get(cc.MEASURE_OF[family])
    return rule.key if rule is not None and rule.liquidable else None


def admit(f: Facts) -> Admission:
    family = family_of(f.market_key)
    if family is None:
        raise ValueError(f"{f.market_key!r} is not a market of a family of counts")
    rule = rule_of(family)
    if rule is None:
        return Admission(False, NO_RULE, "sin regla de liquidación que lea el conteo", family, None)
    if f.line % 1 != Decimal("0.5"):
        return Admission(False, NO_RULE, f"línea {f.line} con devolución posible: solo medias líneas", family, rule)
    if not f.validated:
        return Admission(False, NOT_CALIBRATED, "sin calibrador con veredicto VALIDADO (protocolo AD-B07)", family, rule)
    if not f.signed:
        return Admission(False, NOT_CALIBRATED, "calibrador VALIDADO sin la firma del dueño", family, rule)
    if f.books <= 0:
        return Admission(False, NO_PRICE, "ninguna casa completa cotiza la línea", family, rule)
    if f.books < MIN_BOOKS:
        return Admission(False, THIN, f"{f.books} casa(s): se piden {MIN_BOOKS}", family, rule)
    return Admission(True, ADMITTED, f"{f.books} casas, regla {rule}, calibrador firmado", family, rule)
