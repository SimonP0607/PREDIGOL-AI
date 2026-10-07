"""fbi.core.sentry: off without a DSN; with one, nothing personal leaves the server."""

from __future__ import annotations

import pytest

from fbi.core import sentry


def test_off_without_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_SENTRY_DSN", raising=False)
    assert sentry.options("api") is None
    assert sentry.init("api") is False


def test_nothing_personal_and_no_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_SENTRY_DSN", "https://public@o0.ingest.example.invalid/1")
    monkeypatch.setenv("FBI_ENV", "production")
    monkeypatch.setenv("FBI_CODE_VERSION", "abc123")
    opts = sentry.options("worker")
    assert opts is not None
    assert opts["send_default_pii"] is False
    assert opts["include_local_variables"] is False
    assert opts["max_request_body_size"] == "never"
    assert opts["traces_sample_rate"] == 0.0
    assert opts["environment"] == "production"
    assert opts["release"] == "predigol-backend@abc123"
    assert opts["server_name"] == "worker"
