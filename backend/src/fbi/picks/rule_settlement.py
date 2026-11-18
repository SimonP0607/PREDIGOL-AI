"""Settling a leg of Mi parlay on a market of the catalogue that is not one of the five (plan EA, EA-502).

A leg on ``corners_over_under.FT.match`` (any market the catalogue can settle) settles exactly like a pick on the five as far as the
MATCH is concerned - cancelled is void, unfinished waits, no official result 72 h after the kick-off it was taken for is void
(``fbi.picks.settlement.settle``) - and, once the match is final, by the settlement rule of IA-070 its bet has
(``fbi.market.rules.rule_for``), on the numbers that rule reads in ``market.fixture_outcomes`` (``count_settlement.settle_numbers``):
the same grader the families are scored with. A count that is unknown is never a loss: the leg waits, and if the count is still unknown
72 h after the kick-off it is void (``sin_datos_para_liquidar``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from fbi.market.rules import rule_for
from fbi.picks import settlement
from fbi.picks.count_settlement import settle_numbers
from fbi.userdata.eligibility import spec_for_key

NO_DATA_BASIS: Final = "sin_datos_para_liquidar"
RULE_BASIS: Final = "regla_ia070"


def settle_by_rule(market_key: str, selection: str, line: Decimal, odds: Decimal, stake: Decimal, state: settlement.MatchState,
                   outcome: Mapping[str, Any] | None, *, at: datetime | None = None) -> settlement.Settlement:
    spec = spec_for_key(market_key)
    rule = rule_for(spec) if spec is not None else None
    if spec is None or rule is None:
        return settlement.Settlement(settlement.Status.PENDING, None, f"{market_key}: no settlement rule")
    match = settlement.settle("1X2", "Home", Decimal(0), odds, stake, state, at=at)
    if not match.is_final or match.status is settlement.Status.VOID:
        return match
    status = None
    if outcome is not None:
        try:
            status = settle_numbers(rule, spec.kind, spec.subject, selection, line, outcome)
        except ValueError as exc:
            return settlement.Settlement(settlement.Status.PENDING, None, str(exc))
    if status is None:
        if at is not None and state.kickoff_at is not None and at >= state.kickoff_at + settlement.VOID_AFTER:
            return settlement.Settlement(settlement.Status.VOID, Decimal(0), basis=NO_DATA_BASIS)
        return settlement.Settlement(settlement.Status.PENDING, None, f"{rule.key}: the numbers it reads are not known yet")
    return settlement.Settlement(status, settlement.profit(status, odds, stake), basis=RULE_BASIS)
