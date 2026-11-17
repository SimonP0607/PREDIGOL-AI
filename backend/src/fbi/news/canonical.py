"""The canonical URL and the fingerprint of an article (IA-080, AD-G01): what the store deduplicates on.

* ``canonical_url`` (``canon-v1``): one address per article - https, the host in lower case without ``www.``, ``m.``, ``amp.`` or
  ``mobile.``, no default port, no fragment, no tracking parameters (``utm_*``, ``fbclid``, ``gclid`` ...), no AMP version (a final
  ``/amp`` segment, ``?amp``, ``outputType=amp``), the other parameters sorted, no final slash. The path keeps its case (it is the
  site's). ``url_sha256`` is the sha256 of it - the identity of an item, and the database checks it (migration 0146).
* ``fingerprint`` (``fp-v1``): the sha256 of a text folded (Unicode NFKC, lower case, no accents, only letters and digits, single
  spaces) - the same article reprinted by five media gives the same fingerprint. The text is NOT kept: only its hash is.

Both are versioned: a change of the rules is a new version (``canon-v2``), written in every row, never a silent change of this one.
AD-G02 adds the near-duplicate fingerprint (``simhash``)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Final
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

CANON_VERSION: Final = "canon-v1"
FINGERPRINT_VERSION: Final = "fp-v1"

MOBILE_PREFIXES: Final = ("www.", "m.", "amp.", "mobile.")
TRACKING: Final = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid", "_ga", "_gl", "ref", "ref_src",
    "ref_url", "cmpid", "ito", "spm", "amp", "__twitter_impression",
})
AMP_SWITCHES: Final = frozenset({"outputtype", "output", "format"})
"""Parameters that ask for the AMP version when their value is ``amp`` (any other value is kept)."""
TRACKING_PREFIXES: Final = ("utm_", "ns_", "pk_", "mtm_", "hsa_")
_SLASHES = re.compile(r"/{2,}")
_NOT_WORD = re.compile(r"[^0-9a-z]+")


class NotAnArticleUrlError(ValueError):
    """The address is not an http(s) URL with a host."""


def _host(raw: str | None) -> str:
    host = (raw or "").strip().rstrip(".").lower()
    for prefix in MOBILE_PREFIXES:
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix):]
            break
    return host


def _tracking(key: str, value: str) -> bool:
    k = key.lower()
    return k in TRACKING or k.startswith(TRACKING_PREFIXES) or (k in AMP_SWITCHES and value.strip().lower() == "amp")


def canonical_url(url: str) -> str:
    """The one address of an article (``canon-v1``)."""
    raw = (url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise NotAnArticleUrlError(raw[:200])
    host = _host(parts.hostname)
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = _SLASHES.sub("/", parts.path or "/")
    if path.lower().endswith("/amp") or path.lower().endswith("/amp/"):
        path = path[: path.lower().rfind("/amp")] or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    path = quote(path, safe="/%:@!$&'()*+,;=-._~")
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _tracking(k, v))
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def url_sha256(url: str) -> str:
    """The identity of an item: the sha256 of its canonical URL (what migration 0146 checks)."""
    return sha256_hex(canonical_url(url))


def folded(text: str) -> str:
    """The text as the fingerprint reads it: NFKC, lower case, accents removed, only letters and digits, single spaces."""
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text or "").casefold())
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NOT_WORD.sub(" ", bare).strip()


def fingerprint(text: str) -> str:
    """The content fingerprint (``fp-v1``). The text is what the caller read (the body of a source that allows extraction, or else the
    title and date); only the hash is stored."""
    words = folded(text)
    if not words:
        raise ValueError("nothing to fingerprint")
    return sha256_hex(words)


__all__ = ["CANON_VERSION", "FINGERPRINT_VERSION", "NotAnArticleUrlError", "canonical_url", "fingerprint", "folded", "sha256_hex",
           "url_sha256"]
