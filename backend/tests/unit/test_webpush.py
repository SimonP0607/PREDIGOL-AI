"""Web Push as the messenger speaks it (plan UX, B7; section 34), without a network: the encryption reproduces RFC 8291's
own example byte for byte and a device reads back what was sent; the VAPID header is a JWT over the push service's origin
that PrediGol's public key verifies; only the known push services are called; a push service's answers say what to do."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from fbi.messaging import push, push_jobs

b64 = push.b64url_decode

# RFC 8291, Appendix A
PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"  # gitleaks:allow - RFC 8291's published example (Appendix A), not a secret
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
HEADER = "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
CIPHERTEXT = "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"


def key(text: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64(text), "big"), ec.SECP256R1())


def device() -> tuple[ec.EllipticCurvePrivateKey, str, str]:
    """A browser's keys, as PushSubscription.toJSON() gives them."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return private, push.b64url_encode(public), push.b64url_encode(b"0123456789abcdef")


def test_the_encryption_is_rfc_8291s_own_example_byte_for_byte() -> None:
    body = push.encrypt(PLAINTEXT, UA_PUBLIC, AUTH, salt=b64(SALT), server_key=key(AS_PRIVATE))
    assert body == b64(HEADER) + b64(CIPHERTEXT)
    assert push.decrypt(body, key(UA_PRIVATE), AUTH) == PLAINTEXT


def test_every_message_is_fresh_and_only_its_device_reads_it() -> None:
    private, public, auth = device()
    one, two = push.encrypt(b'{"title":"x"}', public, auth), push.encrypt(b'{"title":"x"}', public, auth)
    assert one != two, "a new salt and a new server key every time"
    assert push.decrypt(one, private, auth) == push.decrypt(two, private, auth) == b'{"title":"x"}'
    other, _, _ = device()
    with pytest.raises(InvalidTag):
        push.decrypt(one, other, auth)


@pytest.mark.parametrize(("device_key", "auth"), [
    ("not-a-key", AUTH), (UA_PUBLIC[:-4], AUTH), (UA_PUBLIC, "c2hvcnQ"), ("A" * 87, AUTH)])
def test_keys_that_cannot_encrypt_are_refused(device_key: str, auth: str) -> None:
    with pytest.raises((push.PushError, ValueError)):
        push.encrypt(b"x", device_key, auth)


def test_a_notice_stays_inside_the_4_kb_a_push_service_takes() -> None:
    _, public, auth = device()
    assert len(push.encrypt(b"x" * push.MAX_PAYLOAD, public, auth)) <= 4096
    with pytest.raises(push.PushError):
        push.encrypt(b"x" * (push.MAX_PAYLOAD + 1), public, auth)


def test_the_vapid_header_is_a_jwt_over_the_push_services_origin_signed_with_predigols_key() -> None:
    vapid = push.Vapid(private=push.private_key_from(push.new_private_key()), subject="mailto:soporte@predigol.com")
    header = push.vapid_authorization("https://fcm.googleapis.com/fcm/send/abc:123", vapid, now=1_800_000_000)
    t, k = header.removeprefix("vapid t=").split(", k=")
    assert k == vapid.public and len(b64(k)) == 65
    head, claims, signature = t.split(".")
    assert json.loads(b64(head)) == {"typ": "JWT", "alg": "ES256"}
    assert json.loads(b64(claims)) == {"aud": "https://fcm.googleapis.com", "exp": 1_800_000_000 + 12 * 3600,
                                       "sub": "mailto:soporte@predigol.com"}
    raw = b64(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64(k))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        public.verify(der, f"{head}.{claims}x".encode(), ec.ECDSA(hashes.SHA256()))


def test_the_key_comes_from_the_owners_environment_and_the_public_one_is_derived() -> None:
    assert push.vapid_from_env({}) is None, "no key: push is off"
    private = push.new_private_key()
    vapid = push.vapid_from_env({push.KEY_ENV: private, "FBI_WEB_BASE_URL": "https://predigol.example"})
    assert vapid is not None and vapid.subject == "https://predigol.example"
    assert vapid.public == push.Vapid(private=push.private_key_from(private), subject="x").public
    assert push.vapid_from_env({push.KEY_ENV: private, push.SUBJECT_ENV: "mailto:a@b.co"}).subject == "mailto:a@b.co"  # type: ignore[union-attr]
    with pytest.raises(push.PushError):
        push.vapid_from_env({push.KEY_ENV: "c2hvcnQ"})


@pytest.mark.parametrize(("endpoint", "allowed"), [
    ("https://fcm.googleapis.com/fcm/send/abc:APA91b", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/gAAAA", True),
    ("https://web.push.apple.com/QGuQyavXutnMH8", True),
    ("https://wns2-bn3p.notify.windows.com/w/?token=BQYAAA", True),
    ("http://fcm.googleapis.com/fcm/send/abc", False),
    ("https://fcm.googleapis.com:8443/fcm/send/abc", False),
    ("https://evil.example/fcm.googleapis.com", False),
    ("https://fcm.googleapis.com.evil.example/x", False),
    ("https://user:pw@fcm.googleapis.com/x", False),
    ("https://notify.windows.com.evil.example/x", False),
    ("http://127.0.0.1:9996/push/1", False),
    ("https://fcm.googleapis.com/x y", False),
])
def test_only_the_known_push_services_are_called(endpoint: str, allowed: bool) -> None:
    assert push.allowed_endpoint(endpoint, extra="") is allowed


def test_qas_stand_in_is_called_only_when_its_origin_is_listed() -> None:
    assert push.allowed_endpoint("http://127.0.0.1:9996/push/1", extra="http://127.0.0.1:9996")
    assert not push.allowed_endpoint("http://127.0.0.1:9997/push/1", extra="http://127.0.0.1:9996")
    assert not push.allowed_endpoint("http://127.0.0.1:9996/push/1", extra="")


def answer(status: int, headers: dict[str, str] | None = None) -> httpx.Client:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, headers=headers or {})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen = seen  # type: ignore[attr-defined]
    return client


VAPID = push.Vapid(private=push.private_key_from(push.new_private_key()), subject="https://predigol.example")


def test_a_notice_goes_encrypted_with_its_headers_and_the_device_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(push.HOSTS_ENV, raising=False)
    private, public, auth = device()
    client = answer(201)
    result = push_jobs.send(client, endpoint="https://fcm.googleapis.com/fcm/send/x", device_key=public, auth_secret=auth,
                            payload={"title": "Ganado: tu pick", "url": "/my-picks"}, vapid=VAPID, ttl=3600,
                            urgency="high", topic="result-pick-1")
    assert result == push_jobs.Delivery("sent", 201)
    request = client.seen[0]  # type: ignore[attr-defined]
    assert request.headers["content-encoding"] == "aes128gcm" and request.headers["ttl"] == "3600"
    assert request.headers["urgency"] == "high" and request.headers["topic"] == "result-pick-1"
    assert request.headers["authorization"].startswith("vapid t=") and f"k={VAPID.public}" in request.headers["authorization"]
    assert json.loads(push.decrypt(request.content, private, auth)) == {"title": "Ganado: tu pick", "url": "/my-picks"}


@pytest.mark.parametrize(("status", "headers", "outcome"), [
    (404, {}, "gone"), (410, {}, "gone"), (413, {}, "too_large"), (429, {"retry-after": "30"}, "later"),
    (500, {}, "later"), (503, {}, "later"), (400, {}, "refused"), (403, {}, "refused")])
def test_the_push_services_answers_say_what_to_do(monkeypatch: pytest.MonkeyPatch, status: int, headers: dict[str, str],
                                                  outcome: str) -> None:
    monkeypatch.delenv(push.HOSTS_ENV, raising=False)
    _, public, auth = device()
    result = push_jobs.send(answer(status, headers), endpoint="https://web.push.apple.com/x", device_key=public,
                            auth_secret=auth, payload={"title": "x"}, vapid=VAPID, ttl=60)
    assert (result.outcome, result.status) == (outcome, status)
    if status == 429:
        assert result.retry_after == 30


def test_an_address_that_is_no_push_service_is_never_called_and_a_network_failure_is_tried_later(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(push.HOSTS_ENV, raising=False)
    _, public, auth = device()
    client = answer(201)
    refused = push_jobs.send(client, endpoint="https://evil.example/x", device_key=public, auth_secret=auth,
                             payload={"title": "x"}, vapid=VAPID, ttl=60)
    assert refused.outcome == "refused" and client.seen == []  # type: ignore[attr-defined]

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)
    later = push_jobs.send(httpx.Client(transport=httpx.MockTransport(broken)), endpoint="https://fcm.googleapis.com/x",
                           device_key=public, auth_secret=auth, payload={"title": "x"}, vapid=VAPID, ttl=60)
    assert later.outcome == "later"


def test_base64url_without_padding_both_ways() -> None:
    raw = bytes(range(40))
    assert push.b64url_decode(push.b64url_encode(raw)) == raw
    assert "=" not in push.b64url_encode(raw)
    assert push.b64url_decode(base64.urlsafe_b64encode(raw).decode()) == raw


def test_the_key_script_prints_a_key_the_messenger_can_use(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import vapid_keys
    vapid_keys.main()
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"{push.KEY_ENV}=")
    assert push.vapid_from_env({push.KEY_ENV: out[0].split("=", 1)[1]}) is not None
