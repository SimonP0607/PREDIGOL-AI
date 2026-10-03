"""Run the API as a given role without a database session - for tests of what the
routes answer, not of how sign-in works (that is test_auth_rbac.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI

from fbi.api.security import optional_principal
from fbi.auth.roles import permissions_for
from fbi.auth.service import Principal

SAME_SITE = {"x-requested-with": "predigol"}


def principal(role: str = "SUPER_ADMIN", user_id: int = 1) -> Principal:
    return Principal(user_id=user_id, email=f"{role.lower()}@test.local", display_name=role.title(), role=role,
                     language="en", timezone="UTC", session_id="0" * 64,
                     session_expires_at=datetime.now(UTC) + timedelta(hours=1), permissions=permissions_for(role))


def signed_in(app: FastAPI, role: str = "SUPER_ADMIN") -> FastAPI:
    app.dependency_overrides[optional_principal] = lambda: principal(role)
    return app


def admin_app() -> FastAPI:
    from fbi.api.app import create_app

    return signed_in(create_app(), "SUPER_ADMIN")
