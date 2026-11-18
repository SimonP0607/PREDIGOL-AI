"""The documents of plan EA as plain JSON (``dict``): built here, written by the job, validated by the API against C-13.

``fbi.stats`` is domain code: it does not import the layer that serves it (``tests/unit/test_architecture.py``). So each node of a
document is a ``dict`` with exactly the fields of its C-13 class - the constructors below carry the class's name to make the mapping
plain - and ``tests/unit/test_stats_documents.py`` validates every document the tests build against the contract.
"""

from __future__ import annotations

from typing import Any

Doc = dict[str, Any]


def missing(reason: str, **extra: int) -> Doc:
    """A field without value and why (``Missing`` of the contracts)."""
    return {"missing_reason": reason, **extra}


def is_missing(value: object) -> bool:
    return isinstance(value, dict) and "missing_reason" in value


def _node(**fields: Any) -> Doc:
    return dict(fields)


ItemList = _node
Ref = _node
Quantiles = _node
StatFigure = _node
Record = _node
MatchPoint = _node
HalfSplit = _node
GameStates = _node
PulseBin = _node
Pulse = _node
GoalRef = _node
IntervalBin = _node
GoalIntervals = _node
SurvivalPoint = _node
Survival = _node
TrendRow = _node
TrendColumn = _node
RadarAxis = _node
TeamBody = _node
StripValue = _node
StripItem = _node
MinutesItem = _node
PlayerBody = _node
