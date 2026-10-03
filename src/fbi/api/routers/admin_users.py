"""Accounts and the sign-in audit trail - SUPER_ADMIN only."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request

from fbi.api.contracts.auth import AdminUser, AdminUserCreate, AdminUserPatch, AuditEvent
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, listing, ok
from fbi.api.security import UsersAdmin, client_ip, same_site_only
from fbi.auth import service

router = APIRouter(tags=["admin: users"], dependencies=[Depends(same_site_only)])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def _user(row: dict[str, Any]) -> AdminUser:
    return AdminUser(
        id=int(row["id"]), email=row["email"], display_name=row["display_name"], role=row["role"],
        status=row["status"], language=row["language"], timezone=row["timezone"], created_at=row["created_at"],
        last_login_at=row["last_login_at"], active_sessions=int(row.get("active_sessions") or 0),
    )


@router.get("/users", response_model=Envelope[list[AdminUser]])
def list_users(conn: Db, _: UsersAdmin) -> Envelope[list[AdminUser]]:
    return listing([_user(r) for r in service.list_users(conn)], empty_reason="No account exists yet.")


@router.post("/users", response_model=Envelope[AdminUser], status_code=201)
def create_user(body: AdminUserCreate, request: Request, actor: UsersAdmin) -> Envelope[AdminUser]:
    row = service.create_user(actor, email=body.email, display_name=body.display_name, role=body.role,
                              password=body.password, language=body.language, timezone=body.timezone,
                              ip=client_ip(request))
    return ok(_user(row))


@router.patch("/users/{user_id}", response_model=Envelope[AdminUser])
def update_user(body: AdminUserPatch, request: Request, actor: UsersAdmin,
                user_id: Annotated[int, Path(ge=1)]) -> Envelope[AdminUser]:
    row = service.update_user(actor, user_id, role=body.role, status=body.status, ip=client_ip(request))
    return ok(_user(row))


@router.get("/audit", response_model=Envelope[list[AuditEvent]])
def audit(
    conn: Db,
    _: UsersAdmin,
    action: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z][a-z_.]+$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[list[AuditEvent]]:
    rows, total = service.audit_events(conn, limit=limit, offset=offset, action=action)
    events = [AuditEvent(**r) for r in rows]
    return listing(events, empty_reason="Nothing has been recorded yet.", total=total, limit=limit, offset=offset)
