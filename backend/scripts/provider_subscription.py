"""When does the API-Football subscription end? One line of JSON for the server's alarm (PM-01-01).

    python -m scripts.provider_subscription

The plan is prepaid and does not renew by itself: when it ends the account falls to the free plan (100 requests a day)
and the ingestion stops, as on 29 Oct 2026. ``bin/healthcheck.sh`` (``check_provider_subscription``) runs this in the
worker at most every few hours, keeps the line in ``state/provider-subscription.json`` and opens the alert
``provider.subscription`` when the end is less than 10 days away.

It prints ``{"checked_at", "plan", "active", "end", "seconds_left"}`` and nothing else: never the account (name, email)
and never a key. ``GET /status`` does not count against the provider's quota; it is one request of our own daily budget
(``build_client``), and its answer is not written to the RAW store (``persist=False``: it carries the account's data).
An inactive or expired subscription is an answer, not an error: the alarm needs to see it. Exit 0 an answer was printed |
1 the provider did not answer, or answered something that is not a ``/status``.
"""

from __future__ import annotations

import asyncio
import json
import sys

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.providers.api_football.build import build_client
from fbi.providers.api_football.status import parse_status, subscription_snapshot


async def _read() -> dict[str, object]:
    client = build_client()
    try:
        response = await client.get("/status", {}, persist=False)
    finally:
        await client.aclose()
    return subscription_snapshot(parse_status(response.body), now())


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        snapshot = asyncio.run(_read())
    except ProviderError as exc:  # ProviderPayloadError is one too
        print(f"provider_subscription: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(snapshot, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
