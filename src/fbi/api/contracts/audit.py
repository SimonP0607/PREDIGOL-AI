"""Match Center -> Audit: the chain behind every number shown for a fixture.

Provider -> raw payload -> normalised rows -> feature set -> model version ->
prediction -> market snapshot -> pick candidate / pick -> settlement. Each step
lists the records that exist and how they link to the step before; a step
with nothing to show says why ('missing' when something should be there,
'not_applicable' when nothing is expected - no pick is a valid outcome).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

Scalar = str | int | float | bool | None
StepKey = Literal["provider", "raw", "normalized", "features", "models", "predictions", "market", "picks",
                  "settlement"]
StepState = Literal["recorded", "partial", "missing", "not_applicable"]


class AuditItem(Contract):
    kind: str = Field(description="payload | fixture | result | team_stats | events | lineups | player_stats | "
                                  "feature_set | model_version | experiment | prediction | odds_snapshots | "
                                  "near_close | historical_odds | market_baseline | consensus | pick_candidate | "
                                  "pick | settlement")
    ref: str = Field(description="Identifier within its kind: a hash, an id, or a composite key.")
    at: datetime | None = None
    source: str | None = None
    facts: dict[str, Scalar] = Field(default_factory=dict)
    links: list[str] = Field(default_factory=list,
                             description="'kind:ref' of the records this one was computed from.")


class AuditStep(Contract):
    key: StepKey
    label: str
    state: StepState
    detail: str
    items: list[AuditItem]


class MatchAudit(Contract):
    fixture_id: int
    provider_fixture_id: int
    kickoff_at: datetime
    status_group: str
    steps: list[AuditStep]
    complete: bool = Field(description="Every step is recorded or not applicable: nothing expected is missing.")
