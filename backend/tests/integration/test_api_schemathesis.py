"""BE-018. Schemathesis contra la API real: ninguna entrada que el esquema OpenAPI permita (ni rozando sus limites) puede devolver un 5xx.

Se piden solo las operaciones GET (leen, nunca escriben) como SUPER_ADMIN, contra la base migrada y con la semilla de las pruebas de integracion.
Un 5xx es un fallo nuestro: un entero que no cabe en la columna, un texto que el SQL no espera, una lista vacia. Un 4xx es la respuesta correcta.
Corrida determinista (`derandomize`) y corta; si la libreria no esta instalada (solo la instala el CI) el archivo se salta."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

schemathesis = pytest.importorskip("schemathesis")

from hypothesis import HealthCheck, settings  # noqa: E402
from schemathesis.checks import not_a_server_error  # noqa: E402

from fbi.api.app import create_app  # noqa: E402
from fbi.core.config import reset_cache  # noqa: E402
from tests.integration.conftest import Seed  # noqa: E402
from tests.integration.signed_in import signed_in  # noqa: E402


def _app_without_the_address_limit() -> Any:
    """The per-address limit (240 a minute) would answer 429 to most generated requests and hide what is behind it; it has its own tests."""
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_API_RATE_LIMIT", "100000000")
    try:
        return signed_in(create_app(), "SUPER_ADMIN")
    finally:
        mp.undo()


APP = _app_without_the_address_limit()
schema = schemathesis.openapi.from_asgi("/openapi.json", APP)


@pytest.fixture(autouse=True)
def _database(migrated_database: str, seed: Seed) -> Iterator[None]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_APIFOOTBALL_KEY", "test-key-never-sent")  # /admin/system reads the provider settings; nothing is sent anywhere
    reset_cache()
    yield
    mp.undo()
    reset_cache()


@schema.include(method="GET").parametrize()  # type: ignore[untyped-decorator]
@settings(max_examples=8, derandomize=True, deadline=None, database=None, suppress_health_check=list(HealthCheck))
def test_no_get_operation_answers_with_a_server_error_whatever_the_schema_lets_through(case: Any) -> None:
    case.call_and_validate(checks=[not_a_server_error])
