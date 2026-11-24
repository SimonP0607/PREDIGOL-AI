"""Research V2 in the Admin Console: the roles of the latest run, its evidence, and the runs
kept from before the rebuild."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.research.reason_codes import ReasonCode

Role = Literal["CHAMPION", "CHALLENGER", "RESEARCH", "REJECTED"]
RoleReasonCode = ReasonCode
"""C-11 1.1 (AP-A04, AP-A05): why a model has its role, as a code the console translates
(``fbi.research.reason_codes``)."""


class ResearchEntry(Contract):
    experiment_id: int
    name: str
    kind: str
    model_family: str
    role: Role | None
    role_reason: str | None
    role_reason_code: RoleReasonCode | None = Field(
        default=None, description="C-11 1.1: role_reason as a code (rechazado_peor_que_mercado, aporta_informacion...); "
                                  "its figures are in metrics (vs_champion, blend, segments). None for a reason the "
                                  "list does not know; absent from an older API.")
    segment: str | None
    finished_at: datetime | None
    data_as_of: datetime | None
    metrics: dict[str, Any] = Field(description="The summary the Admin Console shows; the full metrics stay in "
                                                "analytics.experiments.")


class LegacyRun(Contract):
    experiment_id: int
    name: str
    model_family: str
    research_status: str
    finished_at: datetime | None
    vs_primary: list[float] | None = Field(description="Log-loss difference to the primary baseline [mean, lo, hi].")


class ResearchOverview(Contract):
    run: str | None = Field(description="The latest research-V2 run, by name.")
    finished_at: datetime | None
    data_as_of: datetime | None
    feature_version: str | None
    champion: str | None
    qualified_models: int = Field(description="Models whose gate passed AND were promoted: 0 while none beats the "
                                              "market.")
    challengers: int
    models: list[ResearchEntry]
    markets: list[ResearchEntry]
    prospective: list[ResearchEntry]
    audit: ResearchEntry | None
    legacy: list[LegacyRun]
    label: Literal["RESEARCH_V2"] = "RESEARCH_V2"
