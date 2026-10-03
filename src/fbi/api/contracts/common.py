from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StatusGroup = Literal["scheduled", "live", "finished", "cancelled", "postponed"]
Outcome1x2 = Literal["Home", "Draw", "Away"]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True)


class TeamRef(Contract):
    id: int
    name: str
    provider_team_id: int
    logo_url: str | None = Field(default=None, description="The provider's crest URL, as stored. Null: not told.")


class CompetitionRef(Contract):
    id: int
    name: str
    country: str | None
    provider_league_id: int
    season: int
    competition_type: str
    is_tracked: bool
    logo_url: str | None = Field(default=None, description="The provider's league logo URL. Null: not stored.")
    flag_url: str | None = Field(default=None, description="The country's flag as the provider published it.")
    country_code: str | None = None


class VenueRef(Contract):
    id: int
    name: str
    city: str | None


class Score(Contract):
    """The 90-minute score markets settle on, with extra time and penalties apart."""

    home: int
    away: int
    ht_home: int | None
    ht_away: int | None
    et_home: int | None
    et_away: int | None
    pen_home: int | None
    pen_away: int | None
    outcome_1x2: Outcome1x2
    total_goals: int
    btts: bool
    source_payload_hash: str | None = Field(description="Payload the score was read from; null before revision 0015.")
    source_fetched_at: datetime | None


class Lineage(Contract):
    """Where a fixture row came from, as far as it was recorded."""

    provider: str
    provider_fixture_id: int
    first_seen_at: datetime
    updated_at: datetime
    recorded: bool = Field(description="False for rows last written before lineage existed (revision 0015).")
    source_payload_hash: str | None
    source_fetched_at: datetime | None
    source_endpoint: str | None
    source_params: dict[str, str] | None
    source_run_id: int | None
    source_job_type: str | None
    note: str | None


class RunSummary(Contract):
    id: int
    job_type: str
    job_name: str
    status: Literal["running", "completed", "partial", "failed", "aborted", "interrupted"]
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    api_calls: int
    payloads_stored: int
    rows_written: int
    rows_updated: int
    errors: int
    last_error: str | None
    notes: str | None
