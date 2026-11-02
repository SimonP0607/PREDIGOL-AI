"""A Sentry client for tests: the options production uses, a transport that keeps every envelope instead of sending
it, and the global client put back to "off" afterwards (other tests must see Sentry off)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from fbi.core import sentry

DSN = "https://public@o0.ingest.example.invalid/1"


class Capture(Transport):
    def __init__(self, options: Any = None) -> None:
        super().__init__(options)
        self.envelopes: list[Any] = []

    def capture_envelope(self, envelope: Any) -> None:
        self.envelopes.append(envelope)

    def events(self) -> list[dict[str, Any]]:
        return [item.payload.json for env in self.envelopes for item in env.items if item.type == "event"]

    def raw(self) -> str:
        return json.dumps(self.events(), ensure_ascii=False)


@contextmanager
def capturing_sentry(monkeypatch: pytest.MonkeyPatch, component: str = "api") -> Iterator[Capture]:
    monkeypatch.setenv("FBI_SENTRY_DSN", DSN)
    monkeypatch.setattr(sentry, "BACKEND_EVENTS", sentry.EventBudget())  # each test starts with the whole budget
    opts = sentry.options(component)
    assert opts is not None
    sentry_sdk.init(**{**opts, "transport": Capture, "default_integrations": False})
    transport = sentry_sdk.get_client().transport
    assert isinstance(transport, Capture)
    try:
        yield transport
    finally:
        sentry_sdk.get_client().close()
        for scope in (sentry_sdk.get_isolation_scope(), sentry_sdk.get_current_scope()):
            scope.clear()
        sentry_sdk.get_global_scope().set_client(None)
        assert not sentry_sdk.is_initialized()
