"""PM-01-01: the line of ``GET /status`` the server's alarm keeps (``scripts.provider_subscription``).

The alarm itself (``check_provider_subscription``, 10 days of margin) is tested in ``tests/vps_shell/test_alerts_checks.sh``; here, what the worker
prints: plan, active, end and seconds left, an inactive plan as an answer and not an error, and never the account.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from scripts import provider_subscription

from fbi.core.errors import ProviderError, ProviderPayloadError
from fbi.providers.api_football import status as status_mod
from fbi.providers.api_football.status import (
    fetch_status,
    parse_status,
    subscription_end_at,
    subscription_snapshot,
)

NOW = datetime(2026, 11, 19, 22, 0, tzinfo=UTC)


def payload(
    active: bool = True, end: str | None = "2026-11-29T21:45:57+00:00", plan: str = "Ultra"
) -> dict[str, Any]:
    return {
        "response": {
            "account": {"firstname": "Ana", "lastname": "X", "email": "someone@example.test"},
            "subscription": {"plan": plan, "end": end, "active": active},
            "requests": {"current": 13679, "limit_day": 75000},
        }
    }


def test_the_snapshot_holds_the_end_and_the_seconds_left_and_no_account() -> None:
    snap = subscription_snapshot(parse_status(payload()), NOW)
    assert snap == {
        "checked_at": "2026-11-19T22:00:00Z",
        "plan": "ultra",
        "active": True,
        "end": "2026-11-29T21:45:57Z",
        "seconds_left": 9 * 86400 + 23 * 3600 + 45 * 60 + 57,
    }
    text = json.dumps(snap)
    assert "Ana" not in text and "example.test" not in text and "account" not in text


def test_inactive_is_an_answer_for_the_alarm_and_an_error_for_the_rest() -> None:
    st = parse_status(payload(active=False))
    assert st.subscription_active is False
    assert subscription_snapshot(st, NOW)["active"] is False

    class FakeResponse:
        body = payload(active=False)

    class FakeClient:
        async def get(self, endpoint: str, params: dict[str, Any]) -> FakeResponse:
            return FakeResponse()

    import asyncio

    with pytest.raises(ProviderError, match="not active"):
        asyncio.run(fetch_status(FakeClient()))  # type: ignore[arg-type]


def test_an_end_that_is_missing_or_not_a_date_gives_no_count() -> None:
    for end in (None, "", "next month"):
        snap = subscription_snapshot(parse_status(payload(end=end)), NOW)
        assert snap["end"] is None and snap["seconds_left"] is None


def test_a_bare_date_time_is_read_as_utc_and_an_offset_is_converted() -> None:
    assert subscription_end_at(parse_status(payload(end="2026-11-29T21:45:57"))) == datetime(
        2026, 11, 29, 21, 45, 57, tzinfo=UTC
    )
    assert subscription_end_at(parse_status(payload(end="2026-11-29T16:45:57-05:00"))) == datetime(
        2026, 11, 29, 21, 45, 57, tzinfo=UTC
    )


def test_a_body_that_is_not_a_status_is_refused() -> None:
    with pytest.raises(ProviderPayloadError):
        parse_status({"response": []})
    with pytest.raises(ProviderPayloadError):
        parse_status({"response": {"subscription": "ultra"}})


def test_the_script_prints_one_json_line_and_does_not_persist_the_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    class FakeResponse:
        body = payload()

    class FakeClient:
        async def get(
            self, endpoint: str, params: dict[str, Any], *, persist: bool = True
        ) -> FakeResponse:
            seen.update(endpoint=endpoint, persist=persist)
            return FakeResponse()

        async def aclose(self) -> None:
            seen["closed"] = True

    monkeypatch.setattr(provider_subscription, "build_client", lambda: FakeClient())
    monkeypatch.setattr(provider_subscription, "now", lambda: NOW)
    assert provider_subscription.main([]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert json.loads(out[0])["end"] == "2026-11-29T21:45:57Z"
    assert seen == {"endpoint": "/status", "persist": False, "closed": True}


def test_the_script_exits_1_when_the_provider_does_not_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeClient:
        async def get(self, endpoint: str, params: dict[str, Any], *, persist: bool = True) -> None:
            raise ProviderError("down")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(provider_subscription, "build_client", lambda: FakeClient())
    assert provider_subscription.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "down" in captured.err


def test_the_module_keeps_its_public_names() -> None:
    assert {"parse_status", "fetch_status", "subscription_snapshot", "subscription_end_at"} <= set(
        dir(status_mod)
    )
