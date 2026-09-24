"""Which evaluated prices become shadow picks, and which shadow picks would qualify.

The rule is fixed and versioned before it sees a result; changing a threshold
is a new rule version, never an edit. Every rejection names the first rule
that failed.

Qualification is a separate question with a separate answer: a shadow pick
qualifies only when the exact model version that produced it has beaten the
de-vigged market in its own walk-forward backtest, for that market, on a
sample large enough to mean something. Publishing is disabled in the schema
whatever this module says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from fbi.picks.value import ValueAssessment

RULE_VERSION = "shadow-rule-v1"


@dataclass(frozen=True, slots=True)
class DecisionRule:
    version: str = RULE_VERSION
    markets: frozenset[str] = frozenset({"1X2", "OU", "BTTS"})
    min_odds: Decimal = Decimal("1.50")
    max_odds: Decimal = Decimal("5.00")
    min_ev: Decimal = Decimal("0.05")
    min_probability_edge: Decimal = Decimal("0.02")
    require_market_consensus: bool = True

    def as_dict(self) -> dict[str, object]:
        return {"version": self.version, "markets": sorted(self.markets), "odds": [str(self.min_odds),
                str(self.max_odds)], "min_ev": str(self.min_ev), "min_probability_edge":
                str(self.min_probability_edge), "require_market_consensus": self.require_market_consensus}


RULE_V1 = DecisionRule()


def decide(a: ValueAssessment, market_key: str, rule: DecisionRule = RULE_V1) -> str | None:
    """None when the candidate is selected; otherwise the first rule it failed."""
    if market_key not in rule.markets:
        return f"market {market_key} is not covered by {rule.version}"
    if rule.require_market_consensus and (a.fair is None or a.probability_edge is None):
        return "no de-vigged market consensus at this capture"
    if not (rule.min_odds <= a.odds.value <= rule.max_odds):
        return f"odds {a.odds.value} outside [{rule.min_odds}, {rule.max_odds}]"
    if a.expected_value.per_unit < rule.min_ev:
        return f"expected value {a.expected_value.per_unit:+.4f} below {rule.min_ev}"
    if a.probability_edge is not None and a.probability_edge.value < rule.min_probability_edge:
        return f"probability edge {a.probability_edge.value:+.4f} below {rule.min_probability_edge}"
    return None


MIN_VALIDATION_SAMPLE = 1000


@dataclass(frozen=True, slots=True)
class VersionEvidence:
    """What the backtest of ONE model version says about ONE market."""

    backtest_run_id: int | None
    market_key: str
    verdict: str | None
    n_common: int | None
    baseline_key: str | None


@dataclass(frozen=True, slots=True)
class Qualification:
    qualified: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self, evidence: VersionEvidence) -> dict[str, object]:
        return {"qualified": self.qualified, "reasons": list(self.reasons),
                "evidence": {"backtest_run_id": evidence.backtest_run_id, "market": evidence.market_key,
                             "verdict": evidence.verdict, "n_common": evidence.n_common,
                             "baseline": evidence.baseline_key}}


def qualify(evidence: VersionEvidence) -> Qualification:
    reasons: list[str] = []
    if evidence.backtest_run_id is None:
        reasons.append("this model version has no stored walk-forward backtest")
    elif evidence.verdict is None:
        reasons.append(f"its backtest has no comparison with the market for {evidence.market_key}")
    else:
        if evidence.verdict != "better":
            reasons.append(f"its backtest is '{evidence.verdict}' against {evidence.baseline_key}, not better")
        if (evidence.n_common or 0) < MIN_VALIDATION_SAMPLE:
            reasons.append(f"validated on {evidence.n_common or 0} fixtures, fewer than {MIN_VALIDATION_SAMPLE}")
    return Qualification(not reasons, tuple(reasons))
