"""API-Football provider. Nothing outside this package may import it directly;
the rest of the platform depends on ``fbi.providers.base.FootballDataProvider``.
"""

from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider

__all__ = ["ApiFootballClient", "ApiFootballProvider"]
