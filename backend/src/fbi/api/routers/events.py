"""Product analytics (plan UX, A6): the browser's events - behind the consent gate, a session's own, limited per
minute - and the owner's view in the console. Nothing a client sends here reaches a model or a decision."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from fbi.api.contracts.events import EventsIn, EventsRecorded, FunnelStep, ProductOverview, UsageRow
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.limits import SlidingWindow
from fbi.api.security import App, same_site_only
from fbi.customer import events
from fbi.customer.db import CustomerError

router = APIRouter(prefix="/events", tags=["analytics"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/product", tags=["admin"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
EVENT_LIMIT = SlidingWindow(per_window=int(os.environ.get("FBI_EVENTS_RATE_LIMIT", "120")), window_s=60.0)
"""Events per account per minute (per API process): a page sends a few; a loop is stopped here."""


@router.post("", response_model=EventsRecorded)
def record_events(body: EventsIn, principal: App) -> EventsRecorded:
    """A batch of the reader's product events (at most 20). An event or a property outside the catalog refuses the
    batch (422); the switch, the owner's and the robot's accounts and consent make it record nothing (0)."""
    for _ in body.events:
        if not EVENT_LIMIT.allow(str(principal.user_id)):
            raise ApiError(429, "rate_limited", "too many events for this account", headers={"retry-after": "30"})
    try:
        n = events.record(principal.user_id, principal.email, [(e.name, e.props) for e in body.events],
                          super_admin=principal.is_super_admin)
    except CustomerError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    return EventsRecorded(recorded=n)


@admin_router.get("", response_model=ProductOverview)
def product_overview(conn: Db) -> ProductOverview:
    """Activation, habit, usage by function, devices and errors - global figures only with enough readers."""
    o = events.overview(conn, at=datetime.now(UTC))
    return ProductOverview(mode=o.mode, purge=o.purge, min_subjects=o.min_subjects, status=o.status,
                           active_30d=o.active_30d, active=o.active,
                           usage=[UsageRow.model_validate(u) for u in o.usage],
                           funnel=[FunnelStep.model_validate(f) for f in o.funnel], devices=o.devices,
                           days_active_per_week=o.days_active_per_week, errors_per_active=o.errors_per_active,
                           dau_mau=o.dau_mau)
