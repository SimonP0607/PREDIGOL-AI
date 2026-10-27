"""The readers' notices on their devices over HTTP (plan UX, B7 and section 34).

* ``GET /me/push`` - whether notices can be offered (FBI_PUSH and PrediGol's VAPID key, P12), the key the browser subscribes
  with, the reader's devices and categories, the quiet hours and the daily ceiling.
* ``POST /me/push/devices`` - a browser the reader allowed (a known push service only): 201.
* ``POST /me/push/devices/stop`` - this browser (its address, in the body: never in an address a log keeps) or another of
  the list (its id) stops: 204.
* ``PUT /me/push/categories`` - categories on or off.
* ``POST /me/push/test`` - «Así se verán tus avisos» on the reader's devices, now (3 a day).
* ``GET`` / ``PUT`` / ``DELETE /me/match-alerts/{fixture_id}`` - the bell of a match: «avísame N minutos antes».
* ``GET /admin/product/push`` - the owner's view: live devices and a week of notices, counts only.

The devices and categories are the reader's own settings: never behind the gates (a limited reader is still told their
membership ends). The bell is on a match's page: the product's gates.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Response

from fbi.api.contracts.push import (
    MatchAlert,
    MatchAlertIn,
    PushCategories,
    PushCategoriesIn,
    PushCategoryCount,
    PushDevice,
    PushFamilyCount,
    PushOverview,
    PushState,
    PushSubscribeIn,
    PushTestOut,
    PushUnsubscribeIn,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, same_site_only
from fbi.core.clock import now
from fbi.customer import push
from fbi.customer.db import CustomerError
from fbi.messaging import push_texts

router = APIRouter(prefix="/me/push", tags=["push"], dependencies=[Depends(same_site_only)])
alerts_router = APIRouter(prefix="/me/match-alerts", tags=["push"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/product", tags=["push"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _device(d: push.Device) -> PushDevice:
    return PushDevice(id=d.id, family=d.family, system=d.system, installed=d.installed,  # type: ignore[arg-type]
                      created_at=d.created_at, last_ok_at=d.last_ok_at)


@router.get("", response_model=PushState)
def get_push(conn: Db, principal: App) -> PushState:
    s = push.state(conn, principal.user_id)
    return PushState(available=s.available, public_key=s.public_key, devices=[_device(d) for d in s.devices],
                     categories=PushCategories(**s.categories), quiet_start=push.QUIET_START.strftime("%H:%M"),
                     quiet_end=push.QUIET_END.strftime("%H:%M"), daily_cap=push.DAILY_CAP)


@router.post("/devices", response_model=PushDevice, status_code=201)
def subscribe(body: PushSubscribeIn, principal: App) -> PushDevice:
    """422 ``unknown_push_service`` or ``bad_key``; 404 ``push_off``."""
    try:
        d = push.subscribe(principal.user_id, endpoint=body.endpoint, device_key=body.keys.p256dh,
                           auth_secret=body.keys.auth, family=body.family, system=body.system, installed=body.installed,
                           at=now())
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _device(d)


@router.post("/devices/stop", status_code=204, response_class=Response)
def unsubscribe(body: PushUnsubscribeIn, principal: App) -> Response:
    try:
        push.unsubscribe(principal.user_id, at=now(), endpoint=body.endpoint, device_id=body.device_id)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@router.put("/categories", response_model=PushCategories)
def put_categories(body: PushCategoriesIn, principal: App) -> PushCategories:
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return PushCategories(**push.set_categories(principal.user_id, values))
    except CustomerError as exc:
        raise _refused(exc) from exc


@router.post("/test", response_model=PushTestOut, status_code=201)
def send_test(principal: App) -> PushTestOut:
    """409 ``no_device``, 429 ``too_many_tests``, 404 ``push_off``."""
    w = push_texts.test_notice(push_texts.locale_of(principal.language))
    try:
        return PushTestOut(id=push.send_test(principal.user_id, title=w.title, body=w.body, at=now()))
    except CustomerError as exc:
        raise _refused(exc) from exc


def _alert(a: push.Alert) -> MatchAlert:
    return MatchAlert(fixture_id=a.fixture_id, on=a.on, minutes_before=a.minutes_before, kickoff_at=a.kickoff_at)


@alerts_router.get("/{fixture_id}", response_model=MatchAlert)
def get_alert(fixture_id: int, conn: Db, principal: App) -> MatchAlert:
    try:
        return _alert(push.alert(conn, principal.user_id, fixture_id))
    except CustomerError as exc:
        raise _refused(exc) from exc


@alerts_router.put("/{fixture_id}", response_model=MatchAlert)
def put_alert(fixture_id: int, body: MatchAlertIn, principal: App) -> MatchAlert:
    """404 ``not_found`` or ``push_off``; 422 ``match_started``, ``too_far``, ``too_many_alerts``."""
    try:
        return _alert(push.set_alert(principal.user_id, fixture_id, minutes_before=body.minutes_before, at=now()))
    except CustomerError as exc:
        raise _refused(exc) from exc


@alerts_router.delete("/{fixture_id}", status_code=204, response_class=Response)
def delete_alert(fixture_id: int, principal: App) -> Response:
    push.clear_alert(principal.user_id, fixture_id)
    return Response(status_code=204)


OVERVIEW_SQL = """
SELECT family, system, count(*) AS devices FROM customer.push_subscriptions WHERE revoked_at IS NULL
 GROUP BY family, system ORDER BY count(*) DESC, family, system
"""
NOTICES_SQL = """
SELECT category, count(*) FILTER (WHERE status = 'sent') AS sent, count(*) FILTER (WHERE status = 'dropped') AS dropped
  FROM customer.push_notices WHERE created_at > now() - interval '7 days' GROUP BY category ORDER BY category
"""


@admin_router.get("/push", response_model=PushOverview)
def get_overview(conn: Db) -> PushOverview:
    families = conn.execute(OVERVIEW_SQL).fetchall()
    notices = conn.execute(NOTICES_SQL).fetchall()
    readers = conn.execute("SELECT count(DISTINCT user_id) FROM customer.push_subscriptions WHERE revoked_at IS NULL"
                           ).fetchone()
    gone = conn.execute("SELECT count(*) FROM customer.push_subscriptions WHERE revoked_reason = 'gone' "
                        "AND revoked_at > now() - interval '7 days'").fetchone()
    return PushOverview(
        available=push.available(), readers=int(readers[0]) if readers else 0,
        devices=[PushFamilyCount(family=f, system=s, devices=int(n)) for f, s, n in families],
        notices=[PushCategoryCount(category=c, sent=int(s), dropped=int(d)) for c, s, d in notices],
        gone=int(gone[0]) if gone else 0)
