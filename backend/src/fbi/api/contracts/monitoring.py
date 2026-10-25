"""What the browser needs to report its errors (plan UX, A2), and what the API answers when it forwards them."""

from __future__ import annotations

from pydantic import Field

from fbi.api.contracts.common import Contract


class MonitoringClient(Contract):
    """The browser reports its errors through this API (``tunnel``), never to Sentry itself: the server filters each
    event again and the reader's address never reaches a third party."""

    enabled: bool = Field(description="False while the web project has no DSN: the browser then reports nothing.")
    dsn: str | None = Field(description="The web project's public DSN, checked on every event the browser sends.")
    environment: str
    tunnel: str = Field(description="Where the browser sends its events.")


class EnvelopeForwarded(Contract):
    status: str = "ok"
    events: int = Field(description="Events forwarded after the filter (attachments, replays and sessions never).")
