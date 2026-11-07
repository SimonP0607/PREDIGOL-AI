"""One selection of the day as the portfolio sees it: the newest decision-v1 row of a selection (the row
``fbi.intel.decision.select_day`` reads, ``LATEST_DAY_SQL``) with its state-v2 (``fbi.intel.state_v2.classify``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fbi.intel import state_v2


def _num(x: Any) -> float | None:
    return None if x is None else float(x)


def _int(x: Any) -> int | None:
    return None if x is None else int(x)


@dataclass(frozen=True, slots=True)
class Selection:
    decision_id: int
    fixture_id: int
    kickoff_at: datetime
    known_at: datetime
    competition_id: int
    provider_league_id: int | None
    home_team_id: int
    away_team_id: int
    market_key: str
    selection: str
    line: Decimal
    odds: float | None
    p_cal: float | None
    """The CALIBRATED probability (conditional on the bet settling): what stake-v1 stakes on."""
    p_push: float
    p_low: float | None
    p_high: float | None
    p_market: float | None
    n_bookmakers: int | None
    price_at: datetime | None
    score: float | None
    premium: bool
    parlay_eligible: bool
    state_v1: str
    state_v2: state_v2.StateV2
    reason: str
    label: str | None
    pick_id: int | None = None
    fixture_status: str = "scheduled"
    model_status: str | None = None

    @property
    def teams(self) -> frozenset[int]:
        return frozenset((self.home_team_id, self.away_team_id))

    @classmethod
    def of(cls, row: Mapping[str, Any]) -> Selection:
        """From a row of ``intel.decisions`` joined to its fixture and competition (``build.ROWS_SQL``)."""
        state, reason = state_v2.classify(row)
        return cls(
            decision_id=int(row["id"]), fixture_id=int(row["fixture_id"]), kickoff_at=row["kickoff_at"],
            known_at=row["known_at"], competition_id=int(row["competition_id"]),
            provider_league_id=_int(row.get("provider_league_id")), home_team_id=int(row["home_team_id"]),
            away_team_id=int(row["away_team_id"]), market_key=str(row["market_key"]),
            selection=str(row["selection"]), line=Decimal(str(row.get("line") or 0)), odds=_num(row.get("odds")),
            p_cal=_num(row.get("p_cal")), p_push=_num(row.get("p_push")) or 0.0, p_low=_num(row.get("p_low")),
            p_high=_num(row.get("p_high")), p_market=_num(row.get("p_market")),
            n_bookmakers=_int(row.get("n_bookmakers")), price_at=row.get("price_at"), score=_num(row.get("score")),
            premium=bool(row.get("premium")), parlay_eligible=bool(row.get("parlay_eligible")),
            state_v1=str(row["state"]), state_v2=state, reason=reason, label=state_v2.label_of(row),
            pick_id=_int(row.get("pick_id")), fixture_status=str(row.get("fixture_status") or "scheduled"),
            model_status=None if row.get("model_status") is None else str(row["model_status"]))

    def brief(self) -> dict[str, Any]:
        return {"decision_id": self.decision_id, "fixture_id": self.fixture_id, "competition_id": self.competition_id,
                "provider_league_id": self.provider_league_id, "kickoff_at": self.kickoff_at.isoformat(),
                "known_at": self.known_at.isoformat(), "market_key": self.market_key, "selection": self.selection,
                "line": str(self.line), "odds": self.odds, "p_cal": self.p_cal, "score": self.score,
                "state_v1": self.state_v1, "state_v2": self.state_v2, "reason": self.reason, "label": self.label}
