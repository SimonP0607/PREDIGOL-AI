"""BE-018. A number the column cannot hold is a 422 for the caller, not a 500 for us (found by Schemathesis, tests/integration/test_api_schemathesis.py)."""

from __future__ import annotations

import psycopg.errors
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fbi.api import errors


def app_that_raises(exc: Exception) -> TestClient:
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    def boom() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_a_number_the_database_cannot_hold_is_422_invalid_and_carries_no_sql() -> None:
    r = app_that_raises(psycopg.errors.NumericValueOutOfRange("bigint out of range: SELECT secret FROM t")).get("/boom")
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "error" and body["error"]["code"] == "invalid" and body["request_id"]
    assert "SELECT" not in r.text and "bigint" not in r.text


def test_a_text_with_a_nul_byte_is_422_invalid_too() -> None:
    r = app_that_raises(psycopg.DataError("PostgreSQL text fields cannot contain NUL (0x00) bytes")).get("/boom")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid" and "NUL" not in r.text


def test_any_other_database_error_is_still_a_500_without_details() -> None:
    r = app_that_raises(psycopg.errors.UndefinedTable("relation x does not exist")).get("/boom")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal" and "relation" not in r.text
