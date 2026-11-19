"""Ask the provider what it thinks our plan and usage are.

``GET /status`` returns the account's plan and the day's request counter. It
does not count against the quota on the documented plans, but it IS a call,
so it is issued once per run and the answer is kept as operational metadata
(raw.ingestion_runs.params) rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fbi.core.errors import ProviderError, ProviderPayloadError
from fbi.providers.api_football.client import ApiFootballClient


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    plan: str
    requests_today: int
    requests_limit_day: int
    subscription_active: bool
    subscription_end: str | None
    account_label: str  # first name only, never the email

    @property
    def remaining_today(self) -> int:
        return max(0, self.requests_limit_day - self.requests_today)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "requests_today": self.requests_today,
            "requests_limit_day": self.requests_limit_day,
            "remaining_today": self.remaining_today,
            "subscription_active": self.subscription_active,
            "subscription_end": self.subscription_end,
        }


def parse_status(payload: dict[str, Any]) -> ProviderStatus:
    """The answer of ``GET /status``, read as it is: an inactive subscription is a value here, not an error.

    The alarm of the subscription's end (PM-01-01, ``scripts.provider_subscription``) needs to SEE an inactive or
    expired plan to tell the owner; every other caller wants an active one and goes through :func:`fetch_status`.
    """
    body = payload.get("response")
    if not isinstance(body, dict):
        raise ProviderPayloadError("/status: unexpected shape")
    account = body.get("account") or {}
    sub = body.get("subscription") or {}
    req = body.get("requests") or {}
    if not isinstance(account, dict) or not isinstance(sub, dict) or not isinstance(req, dict):
        raise ProviderPayloadError("/status: unexpected shape")
    return ProviderStatus(
        plan=str(sub.get("plan", "unknown")).lower(),
        requests_today=int(req.get("current", 0)),
        requests_limit_day=int(req.get("limit_day", 0)),
        subscription_active=bool(sub.get("active", False)),
        subscription_end=(str(sub["end"]) if sub.get("end") else None),
        account_label=str(account.get("firstname", "")),
    )


async def fetch_status(client: ApiFootballClient) -> ProviderStatus:
    response = await client.get("/status", {})
    status = parse_status(response.body)
    if not status.subscription_active:
        raise ProviderError("/status: the subscription is not active")
    return status


def subscription_end_at(status: ProviderStatus) -> datetime | None:
    """``subscription.end`` as an aware UTC datetime; None when the provider gives none or one that is not a date."""
    if not status.subscription_end:
        return None
    try:
        end = datetime.fromisoformat(status.subscription_end)
    except ValueError:
        return None
    if end.tzinfo is None:  # the provider writes "+00:00"; a bare date-time is read as UTC
        end = end.replace(tzinfo=UTC)
    return end.astimezone(UTC)


def subscription_snapshot(status: ProviderStatus, now: datetime) -> dict[str, Any]:
    """What the server's alarm keeps of ``/status`` (``state/provider-subscription.json``): plan, active, end and the
    seconds left. Never the account (name, email) and never a key."""
    end = subscription_end_at(status)
    return {
        "checked_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": status.plan,
        "active": status.subscription_active,
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ") if end else None,
        "seconds_left": int((end - now).total_seconds()) if end else None,
    }
