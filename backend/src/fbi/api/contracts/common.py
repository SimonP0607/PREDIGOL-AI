from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StatusGroup = Literal["scheduled", "live", "finished", "cancelled", "postponed"]
MatchPhase = Literal["scheduled", "live", "suspended", "finished", "postponed", "cancelled", "abandoned",
                   "not_played", "awaiting", "unknown"]
"""What a reader sees: the provider's code with the time guard of fbi.core.match_state."""
ResultWaitCode = Literal["provider_pending", "provider_silent", "jobs_stalled", "provider_conflict", "result_missing"]
"""Why a match that should be over has no result (fbi.core.match_state.ResultWait)."""
UserStatus = Literal["RECOMMENDED", "CAUTION", "NOT_RECOMMENDED", "EVALUATION"]
"""The visible state of a pick (plan UX, B3): the states of fbi/picks/user_status.py, the one table that decides them."""
StatusReason = Literal["approved", "value", "not_reviewed", "downgraded", "rejected", "no_value_now", "evaluation"]
"""Why a pick's visible state is the one it is (StatusReason of fbi/picks/user_status.py)."""
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
    priority_group: int = Field(
        default=4, ge=1, le=4,
        description=("The owner's priority group of the competition (comp-priority-v1, fbi.intel.day_priority): 1 the "
                     "Champions League and the top leagues, 2 continental and intercontinental club cups, 3 national-team "
                     "tournaments and World Cup qualifiers, 4 everything else. An ordering hint for lists; it decides "
                     "nothing else."))


class VenueRef(Contract):
    """Where a match is played or a team plays. ``id`` is null when the provider named the stadium without
    identifying it (the fixture payload's name and city, as sent); the details come from /venues or /teams."""

    id: int | None = None
    name: str
    city: str | None = None
    country: str | None = None
    capacity: int | None = None
    surface: str | None = Field(default=None, description="The provider's text: 'grass', 'artificial turf'...")
    address: str | None = None
    image_url: str | None = None


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
    status: Literal["running", "completed", "partial", "failed", "aborted", "interrupted", "stale"]
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
    owner: str | None = Field(None, description="host:pid of the process that opened the run (since 0062).")
    heartbeat_at: datetime | None = Field(None, description="Last sign of life: a payload indexed, a beat.")
    deadline_at: datetime | None = Field(None, description="Past it, the run watchdog closes a still-open run as "
                                                           "stale.")
