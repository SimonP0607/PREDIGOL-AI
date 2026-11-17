"""The page as the unified research reads it (IA-087, plan piece AD-C05): clean text, windows chosen by code, a fingerprint per page.

WHY. Research v2 shows its extractor the first 700 characters of six pages in one call (``extract_v2.PAGE_CHARS``, ``MAX_PAGES``); since
8 Nov the search returns 2,000, and 46 % of the facts v1 found sit after the cut (RV2b, 15 Nov 2026). In 92 % of the pages those 700 start by
repeating the title. And a page read for one match is read again for the next if the key of the reading names the match. This module is
the code half of the answer - nothing here calls a model:

* ``clean``: the text only (never the search API's summary), at most ``PAGE_CHARS`` (12,000), without the title it repeats as its own first
  lines and without the lines the same domain repeats on every page (menus, «Read also», cookie notices: ``common_lines``, generated from
  the pages of the same domain the pass has in front of it).
* ``choose``: windows of at most ``WINDOW_CHARS`` (the 2,100 characters ``extract-v4`` was tested with, ``fbi.ai.quarantine.WINDOW_CHARS``),
  at most ``MAX_WINDOWS`` (4) a page, around the paragraphs that NAME a candidate of the match (``fbi.ai.mentions``, aliases included: the
  prefilter) - most mentions and most words of a type of fact first, then in the order of the page. A paragraph that names nobody is never
  sent: a claim from it could not stand.
* ``fingerprint`` (``fp-v1`` of ``fbi.core.fingerprint``, the same the news store deduplicates on) of the clean text: one page is extracted once
  per fingerprint, whatever match or address asks (``fbi.ai.unified_research``). ``simhash`` and ``near_duplicate``: two pages that are the
  same wire story with a different first line are one origin for the ladder (``fbi.ai.assertions``).

Pure: nothing is read or written. The door (``fbi.ai.untrusted``) and the check for orders are applied after, window by window, by the road.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from fbi.ai import quarantine
from fbi.ai.mentions import Catalogue, Mention, mentions_in, words
from fbi.core import fingerprint as fp_v1

VERSION: Final = "windows-v1"
PAGE_CHARS: Final = 12_000
WINDOW_CHARS: Final = quarantine.WINDOW_CHARS
MAX_WINDOWS: Final = 4
COMMON_MIN_PAGES: Final = 2
"""A line is the domain's (not the article's) when at least this many OTHER pages of the same domain have it too."""
COMMON_MIN_CHARS: Final = 12
SIMHASH_BITS: Final = 64
NEAR_DISTANCE: Final = 6
"""Hamming distance of two simhashes under which two texts are the same story (a wire copy with a new first line or a different footer)."""
SHINGLE: Final = 3

_PARAGRAPH: Final = re.compile(r"\n\s*\n|\n(?=\s*[#*\-•]\s)|\n")
_SENTENCE: Final = re.compile(r"(?<=[.!?…])\s+")


def _line_key(line: str) -> str:
    return " ".join(words(line))


def _drop_title(title: str, text: str) -> str:
    """The text without the title it repeats on lines of its own at its start («title\\n\\n# title\\n\\n»)."""
    t = text
    title = (title or "").strip()
    if not title:
        return t
    line = re.compile(r"^\s*#*\s*" + re.escape(title) + r"\s*(?:\n|$)", re.I)
    for _ in range(3):
        m = line.match(t)
        if m is None:
            break
        t = t[m.end():]
    return t


def common_lines(pages: Iterable[tuple[str, str]]) -> dict[str, frozenset[str]]:
    """Domain -> the (folded) lines that at least ``COMMON_MIN_PAGES`` + 1 distinct pages of that domain have: what the site prints on every
    page. ``pages`` is (domain, raw text)."""
    per: dict[str, list[set[str]]] = {}
    for domain, text in pages:
        keys = {k for k in (_line_key(x) for x in (text or "").splitlines()) if len(k) >= COMMON_MIN_CHARS}
        per.setdefault(domain, []).append(keys)
    out: dict[str, frozenset[str]] = {}
    for domain, sets in per.items():
        counts = Counter(k for s in sets for k in s)
        out[domain] = frozenset(k for k, n in counts.items() if n >= COMMON_MIN_PAGES + 1)
    return out


def clean(title: str, text: str, *, common: frozenset[str] = frozenset()) -> str:
    """The body of a page as the model may see it: without the repeated title and the domain's common lines, at most ``PAGE_CHARS``."""
    body = _drop_title(title or "", text or "")
    kept = [line for line in body.splitlines() if _line_key(line) not in common or not _line_key(line)]
    out = "\n".join(kept).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out[:PAGE_CHARS]


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int


def paragraphs(text: str) -> list[Span]:
    """The paragraphs of a text (blank lines, list items, lines), a paragraph longer than a window cut at sentences, and a sentence longer
    than a window cut at the window."""
    out: list[Span] = []
    start = 0
    bounds = [m.span() for m in _PARAGRAPH.finditer(text)] + [(len(text), len(text))]
    for a, b in bounds:
        if a > start:
            out.extend(_fit(text, start, a))
        start = b
    return [s for s in out if text[s.start:s.end].strip()]


def _fit(text: str, start: int, end: int) -> list[Span]:
    if end - start <= WINDOW_CHARS:
        return [Span(start, end)]
    cuts = [m.end() for m in _SENTENCE.finditer(text, start, end)] + [end]
    out: list[Span] = []
    cur = start
    last = start  # the end of the last sentence that still fits in the piece that starts at ``cur``
    for cut in cuts:
        if cut - cur <= WINDOW_CHARS:
            last = cut
            continue
        if last > cur:
            out.append(Span(cur, last))
            cur = last
        while cut - cur > WINDOW_CHARS:  # one sentence longer than a window: cut at the window
            out.append(Span(cur, cur + WINDOW_CHARS))
            cur += WINDOW_CHARS
        last = cut
    if end > cur:
        out.append(Span(cur, end))
    return out


@dataclass(frozen=True, slots=True)
class Window:
    """A piece of a page the server would send: where it is, what it says and who it names."""

    index: int
    start: int
    end: int
    text: str
    mentions: tuple[Mention, ...]

    @property
    def subjects(self) -> frozenset[tuple[str, int]]:
        return frozenset((m.who.kind, m.who.id) for m in self.mentions)


def _cues(text: str) -> int:
    folded = " ".join(words(text))
    return sum(1 for p in quarantine.CUE_PATTERNS.values() if p.search(folded))


def choose(text: str, catalogue: Catalogue, *, max_windows: int = MAX_WINDOWS) -> list[Window]:
    """The windows of a clean text the server would send, in the order of the page: grown around the paragraphs that name a candidate (the
    ones with most players named and most words of a type of fact first), each one at most ``WINDOW_CHARS``, at most ``max_windows``. None
    when the page names nobody of the match (the prefilter: no call)."""
    paras = paragraphs(text)
    named = [(i, p, mentions_in(text[p.start:p.end], catalogue)) for i, p in enumerate(paras)]
    scored = sorted(((sum(2 if m.who.kind == "PLAYER" else 1 for m in ms) + _cues(text[p.start:p.end]), -i, i)
                     for i, p, ms in named if ms), reverse=True)
    taken: list[tuple[int, int]] = []
    used: set[int] = set()
    for _, _, i in scored:
        if len(taken) >= max_windows:
            break
        if i in used:
            continue
        lo = hi = i
        used.add(i)
        while True:  # grow towards the neighbours that still fit, the next one first (a list of absentees follows its heading)
            grown = False
            for j in (hi + 1, lo - 1):
                if 0 <= j < len(paras) and j not in used:
                    a, b = paras[min(lo, j)].start, paras[max(hi, j)].end
                    if b - a <= WINDOW_CHARS:
                        used.add(j)
                        lo, hi = min(lo, j), max(hi, j)
                        grown = True
                        break
            if not grown:
                break
        taken.append((lo, hi))
    out: list[Window] = []
    for n, (lo, hi) in enumerate(sorted(taken)):
        a, b = paras[lo].start, paras[hi].end
        piece = text[a:b].strip()
        out.append(Window(n, a, b, piece, tuple(mentions_in(piece, catalogue))))
    return out


def fingerprint(text: str) -> str | None:
    """The fingerprint of a clean text (``fp-v1``), or None for a text with nothing in it."""
    try:
        return fp_v1.fingerprint(text)
    except ValueError:
        return None


def simhash(text: str) -> int:
    """A 64-bit simhash of the word shingles of a text: close texts have close hashes."""
    toks = words(text)
    grams = [" ".join(toks[i:i + SHINGLE]) for i in range(max(1, len(toks) - SHINGLE + 1))] if toks else []
    acc = [0] * SIMHASH_BITS
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
        for bit in range(SIMHASH_BITS):
            acc[bit] += 1 if h >> bit & 1 else -1
    return sum(1 << bit for bit in range(SIMHASH_BITS) if acc[bit] > 0)


def near_duplicate(a: int, b: int, *, distance: int = NEAR_DISTANCE) -> bool:
    return (a ^ b).bit_count() <= distance


def window_counts(windows: Sequence[Window]) -> Mapping[str, int]:
    return {"windows": len(windows), "chars": sum(len(w.text) for w in windows),
            "subjects": len({s for w in windows for s in w.subjects})}


__all__ = ["MAX_WINDOWS", "PAGE_CHARS", "VERSION", "WINDOW_CHARS", "Window", "choose", "clean", "common_lines", "fingerprint",
           "near_duplicate", "paragraphs", "simhash"]
