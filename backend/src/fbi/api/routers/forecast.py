"""PrediGol's forecast of a match over HTTP (plan F5). Reading only.

* ``GET /matches/{fixture_id}/forecast`` (product) - what PrediGol expects of the match: per core market the probability of each
  outcome, the interval the model measured and whether it was calibrated. No odds, no edge, no pick. Shown to users only once the
  owner decides (``FBI_FORECAST_USERS``); until then it answers ``not_available``.
  ``preview=shadow`` (SUPER_ADMIN only) adds the fair odds and, beside the forecast, the decision layer's value and the frozen
  picks of the match - three answers that are not one.

No route here computes a probability, calls a model or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.forecast import MatchForecast
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.errors import ApiError
from fbi.api.security import App
from fbi.api.services import forecast
from fbi.auth.roles import Permission
from fbi.auth.service import Principal

router = APIRouter(tags=["forecast"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
Preview = Annotated[Literal["shadow"] | None, Query(
    description="SUPER_ADMIN only: the forecast with its fair odds, beside the value and the picks of the match and, in a section of its own, "
                "what the families forecast (research, uncalibrated). Never a user's view.")]


def _preview(preview: str | None, principal: Principal) -> bool:
    if preview is None:
        return False
    if not principal.can(Permission.SHADOW_PREVIEW):
        raise ApiError(403, "forbidden", "the shadow preview is for the Admin Console only")
    return True


@router.get("/matches/{fixture_id}/forecast", response_model=Envelope[MatchForecast | None])
def get_match_forecast(conn: Db, principal: App, fixture_id: FixtureId,
                       preview: Preview = None) -> Envelope[MatchForecast | None]:
    """PRONÓSTICO PREDIGOL: per market (1X2, total goals at 2.5, both teams to score) the probability of each outcome with
    its interval, the model that made it and CALIBRATED or UNCALIBRATED. A forecast is not a recommendation: it carries no
    price, and what is worth betting is the decision layer's, not this. The Admin Console's preview adds the value, the picks and the
    forecasts of the families, each in a section of its own."""
    return forecast.match_forecast(conn, fixture_id, preview=_preview(preview, principal))
