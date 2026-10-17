"""Internal identity versus provider identity.

API-Football's ids are how we *find* things at the provider. They are not who
things *are* to us. Every entity carries its own internal id and, separately,
the reference(s) that locate it at each provider. A second provider can be
added without renumbering anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

from fbi.core.errors import DomainError


class Provider(StrEnum):
    API_FOOTBALL = "api_football"


CompetitionId = NewType("CompetitionId", int)
SeasonId = NewType("SeasonId", int)
TeamId = NewType("TeamId", int)
VenueId = NewType("VenueId", int)
FixtureId = NewType("FixtureId", int)
BookmakerId = NewType("BookmakerId", int)
ModelVersionId = NewType("ModelVersionId", int)
CalibratorId = NewType("CalibratorId", int)
PredictionId = NewType("PredictionId", int)
CandidateId = NewType("CandidateId", int)
PickId = NewType("PickId", int)
RunId = NewType("RunId", int)


@dataclass(frozen=True, slots=True)
class ProviderRef:
    """Where an entity lives at a given provider."""

    provider: Provider
    external_id: int

    def __post_init__(self) -> None:
        if isinstance(self.external_id, bool) or self.external_id <= 0:
            raise DomainError(f"provider ids are positive integers; got {self.external_id!r}")
