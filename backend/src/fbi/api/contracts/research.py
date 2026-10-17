"""Research V2 in the Admin Console: the roles of the latest run, its evidence, and the runs
kept from before the rebuild."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

Role = Literal["CHAMPION", "CHALLENGER", "RESEARCH", "REJECTED"]


class ResearchEntry(Contract):
    experiment_id: int
    name: str
    kind: str
    model_family: str
    role: Role | None
    role_reason: str | None
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
