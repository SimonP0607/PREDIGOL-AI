"""Web Push from the messenger (plan UX, B7; section 34): PrediGol's own VAPID keys, no intermediate provider.

A notice reaches a reader's device in one HTTP request to the push service the browser chose (Google's for Chrome,
Mozilla's for Firefox, Apple's for Safari, Microsoft's for Edge): the body encrypted for that device alone (RFC 8291,
``aes128gcm``: an ephemeral ECDH key, the device's key and its authentication secret), the request signed with
PrediGol's VAPID key (RFC 8292: a JWT over the push service's origin, ES256). The push service learns nothing of the
text; the browser shows it.

No new dependency: the elliptic curves, HKDF and AES-GCM come from ``cryptography`` (already the second factor's) and
the request from ``httpx``. The encryption reproduces RFC 8291's own example byte for byte (the unit tests).

* Keys (P12, the owner's): ``FBI_VAPID_PRIVATE_KEY`` - the private scalar, base64url, in ``/etc/predigol/app.env``
  (root, 600) - and ``FBI_VAPID_SUBJECT`` (``mailto:`` or ``https:``, default
  ``FBI_WEB_BASE_URL``). The public key is derived from the private one, so they cannot disagree.
  ``python -m scripts.vapid_keys`` prints a new pair, on the server.
* Push services: only the known ones (``SERVICE_HOSTS``) - a browser's subscription names a URL the messenger will
  call, so anything else is refused (no request to an address a client chose). ``FBI_PUSH_SERVICE_HOSTS`` adds
  others, for QA's stand-in only.
The request itself is the messenger's (``fbi.messaging.push_jobs.send``): nothing a reader's request runs imports an
HTTP client.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from fbi.core.env import environment

KEY_ENV: Final = "FBI_VAPID_PRIVATE_KEY"
SUBJECT_ENV: Final = "FBI_VAPID_SUBJECT"
HOSTS_ENV: Final = "FBI_PUSH_SERVICE_HOSTS"

SERVICE_HOSTS: Final = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com",
                        ".push.apple.com", ".notify.windows.com")
"""The push services of the browsers PrediGol supports: Chrome (and Android), Firefox, Safari (macOS and the installed
app on an iPhone), Edge. A leading dot: that domain's hosts."""

RECORD_SIZE: Final = 4096
MAX_PAYLOAD: Final = 3072
"""The text of a notice, at most: inside the 4 KB a push service accepts once encrypted (section 34: «carga de 4 KB»)."""
JWT_TTL: Final = 12 * 3600

class PushError(ValueError):
    """A key, a subscription or a payload the protocol cannot use."""


def b64url_decode(text: str) -> bytes:
    text = "".join(text.split())
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def private_key_from(text: str) -> ec.EllipticCurvePrivateKey:
    raw = b64url_decode(text)
    if len(raw) != 32:
        raise PushError("a VAPID private key is 32 bytes, base64url")
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def public_key_from(text: str) -> ec.EllipticCurvePublicKey:
    raw = b64url_decode(text)
    if len(raw) != 65 or raw[0] != 4:
        raise PushError("a device key is an uncompressed P-256 point: 65 bytes, base64url")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as exc:
        raise PushError("not a point of P-256") from exc


@dataclass(frozen=True)
class Vapid:
    private: ec.EllipticCurvePrivateKey
    subject: str

    @property
    def public(self) -> str:
        """The application server key the browser subscribes with (base64url of the uncompressed point)."""
        return b64url_encode(_point(self.private.public_key()))


def new_private_key() -> str:
    """A new VAPID private key, base64url (``scripts/vapid_keys.py``)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64url_encode(key.private_numbers().private_value.to_bytes(32, "big"))


def vapid_from_env(env: Any = None) -> Vapid | None:
    """PrediGol's VAPID key, or None while the owner has not set one (push is then off, whatever FBI_PUSH says)."""
    values = env if env is not None else environment()
    raw = (values.get(KEY_ENV) or "").strip()
    if not raw:
        return None
    subject = (values.get(SUBJECT_ENV) or values.get("FBI_WEB_BASE_URL") or "").strip()
    if not subject.startswith(("mailto:", "https://")):
        subject = "https://predigol.com"
    return Vapid(private=private_key_from(raw), subject=subject)


def _jws_part(obj: dict[str, Any]) -> str:
    return b64url_encode(json.dumps(obj, separators=(",", ":")).encode())


def vapid_authorization(endpoint: str, vapid: Vapid, *, now: float | None = None) -> str:
    """The ``Authorization`` header of a push request: ``vapid t=<JWT>, k=<public key>`` (RFC 8292). The JWT names the
    push service's origin and expires in 12 hours."""
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + JWT_TTL),
              "sub": vapid.subject}
    signing_input = f"{_jws_part({'typ': 'JWT', 'alg': 'ES256'})}.{_jws_part(claims)}"
    der = vapid.private.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={signing_input}.{signature}, k={vapid.public}"


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, device_key: str, auth_secret: str, *, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """The body of a push request: ``payload`` encrypted for one device (RFC 8291, a single ``aes128gcm`` record).
    ``salt`` and ``server_key`` are fresh for every message; a test passes RFC 8291's own to compare the bytes."""
    if len(payload) > MAX_PAYLOAD:
        raise PushError(f"a notice is at most {MAX_PAYLOAD} bytes, not {len(payload)}")
    ua_public = public_key_from(device_key)
    auth = b64url_decode(auth_secret)
    if len(auth) != 16:
        raise PushError("a device's authentication secret is 16 bytes, base64url")
    as_private = server_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt if salt is not None else os.urandom(16)
    if len(salt) != 16:
        raise PushError("the salt is 16 bytes")
    ua_point, as_point = _point(ua_public), _point(as_private.public_key())
    shared = as_private.exchange(ec.ECDH(), ua_public)
    # RFC 8291, 3.4: the device's authentication secret and both keys into the input keying material ...
    prk_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth, info=b"WebPush: info\x00" + ua_point + as_point)
    ikm = prk_key.derive(shared)
    # ... RFC 8188: the content-encryption key and the nonce from it and the salt
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # 0x02: the last (and only) record
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_point)) + as_point
    return header + ciphertext


def decrypt(body: bytes, device_private: ec.EllipticCurvePrivateKey, auth_secret: str) -> bytes:
    """A push request's body read the way the device reads it - for the tests and QA's stand-in push service."""
    salt, (rs, idlen) = body[:16], struct.unpack("!IB", body[16:21])
    as_point = body[21:21 + idlen]
    ciphertext = body[21 + idlen:]
    if rs < 18 or len(ciphertext) > rs:
        raise PushError("not a single aes128gcm record")
    as_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_point)
    shared = device_private.exchange(ec.ECDH(), as_public)
    ua_point = _point(device_private.public_key())
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=b64url_decode(auth_secret),
               info=b"WebPush: info\x00" + ua_point + as_point).derive(shared)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    end = plain.rstrip(b"\x00")
    if not end.endswith(b"\x02"):
        raise PushError("the record does not end as the last one")
    return end[:-1]


def allowed_endpoint(endpoint: str, extra: str | None = None) -> bool:
    """Whether a subscription's endpoint is a push service PrediGol will call: HTTPS to one of SERVICE_HOSTS, or an
    origin listed in ``FBI_PUSH_SERVICE_HOSTS`` (QA's stand-in)."""
    if len(endpoint) > 1024 or any(c.isspace() for c in endpoint):
        return False
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    if parts.username or parts.password or not parts.hostname:
        return False
    host = parts.hostname.lower()
    listed = [h.strip().rstrip("/") for h in (extra if extra is not None else environment().get(HOSTS_ENV, "")).split(",")
              if h.strip()]
    if f"{parts.scheme}://{parts.netloc}".lower() in (h.lower() for h in listed):
        return True
    if parts.scheme != "https" or parts.port not in (None, 443):
        return False
    return any(host == h or (h.startswith(".") and host.endswith(h)) for h in SERVICE_HOSTS)
