"""The welcome tour and the guides of each screen (plan UX-032; PLAN_BIENVENIDA_RECORRIDO).

* ``PUT /me/guides/{guide}`` - what the reader did with a guide: ``{version, status, step}``. Idempotent; within a version the
  status never goes down; a lower version than the recorded one changes nothing; 422 for a guide, version, status or step the
  closed lists do not have; 409 ``guide_mandatory`` for skipping the first guide of Perfil before it is done.

The state reaches the page in ``GET /auth/me`` (``guides``, ``guides_on``, ``guides_auto``). Not behind the consent or the
membership gates: it is the reader's own state, like a dismissed hint. It never changes a pick, a probability or a price.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from fbi.api.contracts.guides import GuideIn, GuideState
from fbi.api.errors import ApiError
from fbi.api.security import App, same_site_only
from fbi.core.clock import now
from fbi.customer import guides
from fbi.customer.db import CustomerError

router = APIRouter(prefix="/me", tags=["guides"], dependencies=[Depends(same_site_only)])


def view(p: guides.Progress) -> GuideState:
    return GuideState(**{f: getattr(p, f) for f in GuideState.model_fields})


@router.put("/guides/{guide}", response_model=GuideState)
def put_guide(guide: Annotated[str, Path(max_length=20)], body: GuideIn, principal: App) -> GuideState:
    """What the reader did with a guide, recorded once and answered with its state."""
    try:
        return view(guides.record(principal.user_id, guide, version=body.version, status=body.status, step=body.step,
                                  at=now()))
    except CustomerError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
