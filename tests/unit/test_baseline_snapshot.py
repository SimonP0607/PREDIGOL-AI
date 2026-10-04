"""Which endpoints a baseline snapshot freezes."""

from __future__ import annotations

from typing import Any

from fbi.ops.baseline import readable_paths


def test_only_parameterless_reads_outside_auth_are_snapshotted() -> None:
    spec: dict[str, Any] = {"paths": {
        "/api/v1/home": {"get": {}},
        "/api/v1/admin/models": {"get": {}},
        "/api/v1/matches/{fixture_id}": {"get": {}},
        "/api/v1/auth/me": {"get": {}},
        "/api/v1/admin/users": {"get": {}, "post": {}},
        "/api/v1/admin/analyst/ask": {"post": {}},
        "/api/v1/search": {"get": {}},
    }}
    assert readable_paths(spec) == ["/api/v1/admin/models", "/api/v1/admin/users", "/api/v1/home"]
