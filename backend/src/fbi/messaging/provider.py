"""What the queue needs to know about a provider, without the provider's client (plan UX, A5): the message as it
leaves, the answer that is not an id, and the shape of a provider. The API imports the queue (to enqueue, to preview
in the console) and never loads the HTTP client of fbi.messaging.email - only the messenger does."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

ErrorKind = Literal["retry", "quota_day", "quota_month", "config", "permanent"]


@dataclass(frozen=True, slots=True)
class Outgoing:
    to: str
    subject: str
    text: str
    html: str
    idempotency_key: str
    tags: dict[str, str] = field(default_factory=dict)
    """Category and template - what the provider's dashboard groups by. Never the reader's data."""


class ProviderError(Exception):
    """The provider did not accept a message. ``kind`` decides what the queue does (fbi.messaging.email)."""

    def __init__(self, kind: ErrorKind, code: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(f"{kind}: {code}")
        self.kind: ErrorKind = kind
        self.code = code[:120]
        self.retry_after_s = retry_after_s


class Provider(Protocol):
    name: str

    def send(self, message: Outgoing) -> str:
        """The provider's id of the accepted message, or ProviderError."""
