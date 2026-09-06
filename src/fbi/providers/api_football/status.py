"""Ask the provider what it thinks our plan and usage are.

``GET /status`` returns the account's plan and the day's request counter. It
does not count against the quota on the documented plans, but it IS a call,
so it is issued once per run and the answer is kept as operational metadata
(raw.ingestion_runs.params) rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
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


async def fetch_status(client: ApiFootballClient) -> ProviderStatus:
    response = await client.get("/status", {})
    body = response.body.get("response")
    if not isinstance(body, dict):
        raise ProviderPayloadError("/status: unexpected shape")
    account = body.get("account") or {}
    sub = body.get("subscription") or {}
    req = body.get("requests") or {}
    if not isinstance(account, dict) or not isinstance(sub, dict) or not isinstance(req, dict):
        raise ProviderPayloadError("/status: unexpected shape")
    if not sub.get("active", False):
        raise ProviderError("/status: the subscription is not active")
    return ProviderStatus(
        plan=str(sub.get("plan", "unknown")).lower(),
        requests_today=int(req.get("current", 0)),
        requests_limit_day=int(req.get("limit_day", 0)),
        subscription_active=bool(sub.get("active", False)),
        subscription_end=(str(sub["end"]) if sub.get("end") else None),
        account_label=str(account.get("firstname", "")),
    )
