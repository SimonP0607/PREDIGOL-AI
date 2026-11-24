"""C-11 1.1 (AP-A04, AP-A05): the example of ``GET /api/v1/admin/research/v2`` with the reason of each role as a code, and
the same answer as the API gave it before (without ``role_reason_code``), which still reads. The route is private
(``require_admin``): it has no public projection, so no field of it reaches a reader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fbi.api.contracts.research import ResearchOverview
from fbi.research.reason_codes import reason_code

FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence" / "C-11" / "research_v2"


def read(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FOLDER / name).read_text(encoding="utf-8"))
    return data


def entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [*data["models"], *data["markets"], *data["prospective"], *([data["audit"]] if data["audit"] else [])]


def test_the_example_validates_and_each_code_is_its_reasons() -> None:
    data = read("con_codigo.json")
    assert ResearchOverview.model_validate(data).model_dump(mode="json") == data
    for e in entries(data):
        assert e["role_reason_code"] == reason_code(e["role_reason"]), e["name"]
    assert [e["role_reason_code"] for e in entries(data)] == ["rechazado_peor_que_mercado", "evidencia_insuficiente",
                                                              "campeon_mercado", "muestra_insuficiente"]


def test_the_answer_before_the_code_still_reads_and_only_lacks_it() -> None:
    old, new = read("anterior_sin_codigo.json"), read("con_codigo.json")
    assert all("role_reason_code" not in e for e in entries(old))
    read_back = ResearchOverview.model_validate(old).model_dump(mode="json")
    for e in entries(read_back):
        assert e.pop("role_reason_code") is None
    for e in entries(new):
        e.pop("role_reason_code")
    assert read_back == new == old


def test_the_route_is_private() -> None:
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from fbi.api.app import create_app
    from fbi.api.deps import get_db
    from fbi.api.security import current_principal
    from fbi.auth.roles import Permission, Role
    from fbi.auth.service import Principal

    reader = Principal(user_id=7, email="lector@ejemplo.invalid", display_name="Lector", role=Role.USER, language="es",
                       timezone="America/Bogota", session_id="s", session_expires_at=datetime(2026, 11, 24, tzinfo=UTC),
                       permissions=frozenset({Permission.APP}))
    app = create_app()
    app.dependency_overrides[current_principal] = lambda: reader
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as client:
        answer = client.get("/api/v1/admin/research/v2")
    assert answer.status_code == 403 and answer.json()["error"]["code"] == "forbidden"
