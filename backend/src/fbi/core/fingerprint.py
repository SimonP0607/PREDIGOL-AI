"""The content fingerprint of a text (``fp-v1``, IA-080, AD-G01): the sha256 of the text folded (Unicode NFKC, lower case, no accents, only
letters and digits, single spaces) - the same article reprinted by five media gives the same fingerprint. The text is NOT kept: only its hash.

Written in ``fbi.news.canonical`` (which re-exports it under the same names) and kept here, unchanged, because two packages read it: the news
store deduplicates on it, and the unified research (IA-087, ``fbi.ai.deep_pages``) extracts a page once per fingerprint. A leaf of ``fbi.core``
imports nothing of ours, so ``fbi.ai`` reads it without importing ``fbi.news`` (``tests/unit/test_architecture.py``). A change of the rule is a
new version (``fp-v2``), never a silent change of this one."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Final

FINGERPRINT_VERSION: Final = "fp-v1"
_NOT_WORD = re.compile(r"[^0-9a-z]+")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


__all__ = ["FINGERPRINT_VERSION", "fingerprint", "folded", "sha256_hex"]
