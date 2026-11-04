"""E-mail through Resend's HTTP API (plan UX, A5): one request per message, with an idempotency key.

The provider is told the address, the subject and the body of one message, and nothing else about the reader. The
answer becomes a provider id (accepted) or a ``ProviderError`` whose ``kind`` decides what the queue does:

    retry        the network, a timeout, 5xx, 429 rate limit, 409 in progress     -> again after a delay
    quota_day    429 daily_quota_exceeded (resets at midnight UTC)               -> after midnight, no attempt spent
    quota_month  429 monthly_quota_exceeded                                       -> in 12 h, no attempt spent
    config       401 / 403: the key or the sending domain                         -> again after a delay; the cycle
                                                                                     stops (every message would fail)
    permanent    400 / 404 / 405 / 422 / 409 invalid_idempotent_request           -> failed

Errors are reported by status and Resend's error name only: the provider's message can quote the address.
"""

from __future__ import annotations

import os

import httpx

from fbi.messaging.provider import Outgoing, ProviderError

RESEND_URL = "https://api.resend.com"
TIMEOUT_S = 10.0


def _error_name(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name.replace("_", "").isalnum() and len(name) <= 60 else ""


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return max(0.0, min(float(value), 3600.0)) if value is not None else None
    except ValueError:
        return None


def classify(response: httpx.Response) -> ProviderError:
    status, name = response.status_code, _error_name(response)
    code = f"resend {status}" + (f" {name}" if name else "")
    if status == 429:
        if name == "daily_quota_exceeded":
            return ProviderError("quota_day", code)
        if name == "monthly_quota_exceeded":
            return ProviderError("quota_month", code)
        return ProviderError("retry", code, retry_after_s=_retry_after(response))
    if status == 409:
        if name in ("concurrent_idempotent_requests", "resource_locked"):
            return ProviderError("retry", code)
        return ProviderError("permanent", code)
    if status in (401, 403):
        return ProviderError("config", code)
    if status >= 500:
        return ProviderError("retry", code, retry_after_s=_retry_after(response))
    return ProviderError("permanent", code)


class ResendClient:
    name = "resend"

    def __init__(self, api_key: str, sender: str, *, reply_to: str | None = None,
                 transport: httpx.BaseTransport | None = None, base_url: str = RESEND_URL) -> None:
        if not api_key or not sender:
            raise ValueError("Resend needs an API key and a sender")
        self._sender = sender
        self._reply_to = reply_to
        self._http = httpx.Client(base_url=base_url, timeout=TIMEOUT_S, transport=transport,
                                  headers={"authorization": f"Bearer {api_key}", "user-agent": "predigol-messenger"})

    def send(self, message: Outgoing) -> str:
        body: dict[str, object] = {
            "from": message.sender or self._sender, "to": [message.to], "subject": message.subject,
            "text": message.text, "html": message.html,
            "tags": [{"name": k, "value": v} for k, v in sorted(message.tags.items())],
        }
        if self._reply_to:
            body["reply_to"] = self._reply_to
        if message.headers:
            body["headers"] = dict(message.headers)
        try:
            response = self._http.post("/emails", json=body,
                                       headers={"idempotency-key": message.idempotency_key[:256]})
        except httpx.HTTPError as exc:
            raise ProviderError("retry", f"resend unreachable ({type(exc).__name__})") from None
        if 200 <= response.status_code < 300:
            try:
                data = response.json()
            except ValueError:
                data = None
            provider_id = data.get("id") if isinstance(data, dict) else None
            if isinstance(provider_id, str) and 0 < len(provider_id) <= 100:
                return provider_id
            raise ProviderError("retry", f"resend {response.status_code} without an id")
        raise classify(response)

    def close(self) -> None:
        self._http.close()


def client_from_env(transport: httpx.BaseTransport | None = None) -> ResendClient | None:
    """The provider when both the key and the sender are set; None otherwise (the queue waits)."""
    key, sender = os.environ.get("FBI_RESEND_API_KEY", ""), os.environ.get("FBI_EMAIL_FROM", "")
    if not key or not sender:
        return None
    return ResendClient(key, sender, reply_to=os.environ.get("FBI_EMAIL_REPLY_TO") or None, transport=transport)
