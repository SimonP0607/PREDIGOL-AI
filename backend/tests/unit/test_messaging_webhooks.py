"""The provider's webhook is believed only when it is signed and fresh (plan UX, A5): Svix's scheme, as Resend uses
it - an HMAC-SHA256 of ``<id>.<timestamp>.<body>`` with the endpoint's secret, five minutes either way."""

from __future__ import annotations

import base64

import pytest

from fbi.messaging.webhooks import TOLERANCE_S, WebhookError, sign, verify

# Svix's own published example (its libraries' test vector): the same secret, id, time and body give this signature.
SVIX_SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # gitleaks:allow - Svix's public test vector, not a secret
SVIX_ID, SVIX_TS, SVIX_BODY = "msg_p5jXN8AQM9LWM0D4loKWxJek", "1614265330", b'{"test": 2432232314}'
SVIX_SIGNATURE = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="

SECRET = "whsec_" + base64.b64encode(b"predigol-test-webhook-secret-32b").decode()  # gitleaks:allow - made up here
BODY = b'{"type":"email.bounced","data":{"email_id":"4ef9a417"}}'
NOW = 1_761_400_000


def headers(secret: str = SECRET, *, msg_id: str = "msg_1", ts: int = NOW, body: bytes = BODY,
            signature: str | None = None) -> dict[str, str]:
    return {"svix-id": msg_id, "svix-timestamp": str(ts),
            "svix-signature": signature or f"v1,{sign(secret, msg_id, str(ts), body)}"}


def test_svix_published_example_verifies() -> None:
    assert f"v1,{sign(SVIX_SECRET, SVIX_ID, SVIX_TS, SVIX_BODY)}" == SVIX_SIGNATURE
    verify(SVIX_SECRET, {"svix-id": SVIX_ID, "svix-timestamp": SVIX_TS, "svix-signature": SVIX_SIGNATURE},
           SVIX_BODY, now=int(SVIX_TS) + 10)


def test_a_signed_fresh_event_is_believed_and_a_list_of_signatures_may_carry_it() -> None:
    verify(SECRET, headers(), BODY, now=NOW)
    good = headers()["svix-signature"]
    verify(SECRET, headers(signature=f"v1,AAAA v2,{good[3:]} {good}"), BODY, now=NOW + TOLERANCE_S)


@pytest.mark.parametrize("change", ["body", "secret", "id", "old", "future", "missing", "version", "garbage"])
def test_anything_else_is_refused(change: str) -> None:
    h, body, now = headers(), BODY, NOW
    if change == "body":
        body = BODY.replace(b"bounced", b"delivered")
    elif change == "secret":
        h = headers("whsec_" + base64.b64encode(b"another-secret-of-thirty-two-by").decode())
    elif change == "id":
        h["svix-id"] = "msg_2"
    elif change == "old":
        now = NOW + TOLERANCE_S + 1
    elif change == "future":
        now = NOW - TOLERANCE_S - 1
    elif change == "missing":
        del h["svix-signature"]
    elif change == "version":
        h["svix-signature"] = h["svix-signature"].replace("v1,", "v2,")
    else:
        h["svix-timestamp"] = "yesterday"
    with pytest.raises(WebhookError):
        verify(SECRET, h, body, now=now)


def test_a_secret_that_is_not_one_is_refused_before_anything() -> None:
    with pytest.raises(WebhookError, match="base64"):
        verify("whsec_not base64!", headers(), BODY, now=NOW)
    with pytest.raises(WebhookError, match="too short"):
        verify("whsec_" + base64.b64encode(b"short").decode(), headers(), BODY, now=NOW)
