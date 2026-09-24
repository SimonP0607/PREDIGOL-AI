from __future__ import annotations

from datetime import datetime

from pydantic import Field

from fbi.api.contracts.common import Contract


class RatingRow(Contract):
    rank: int
    team_id: int
    team: str
    rating: float
    matches: int = Field(description="Rated matches behind this rating.")
    last_match_at: datetime
    last_competition: str
    change_last5: float | None = Field(description="Rating change over the team's last five rated matches.")
    provisional: bool = Field(description="Fewer than 10 rated matches: still mostly the starting value.")


class Rankings(Contract):
    elo_version: str
    run_id: int
    computed_at: datetime
    parameters: str
    rows: list[RatingRow]
