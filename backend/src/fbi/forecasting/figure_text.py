"""The figures of a text, checked against the single figure (plan 2026, AD-B09, G-COH, ``figure-text-v1``).

A text written for a reader (the one chronicle of AD-F02, a brief, a pick's «why») may state a probability only by REPEATING a figure of
``forecast-v2`` (``fbi.forecasting.single_figure``), and only with the citation of the reading it repeats, right after the percentage::

    Más de 2,5 goles: 57 % [cifra forecast-v2 3f9a1c2b7d4e].

``check`` refuses the text - it is not mended, not rounded again, not shown - when any percentage:

    uncited ......... has no citation right after it (a number nobody can trace)
    other_version ... cites a reading of another version than the one the text was written from
    unknown_reading . cites an id that is not a reading of that version for this match at that moment
    mismatch ........ is not the cited figure rounded half up to the decimals it is written with (57 for 0.5703; 57,0 for 0.5703 with
                      one decimal) - a figure moved by a tenth of a point is another figure

and when a citation stands alone, with no percentage before it (``orphan``). A language model never computes, corrects or chooses a number:
it is handed the figures with their citations (``cite``) and may only repeat them.

Pure and self-contained: it takes the figures as plain values (reading id -> probability) so that whichever layer writes a text can check it
without depending on how the figures are made.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

RULE: Final = "figure-text-v1"

CITATION: Final = re.compile(r"\[cifra (?P<version>[a-z0-9][a-z0-9_-]*) (?P<id>[0-9a-f]{12})\]")
PERCENT: Final = re.compile(r"(?<![\d.,])(?P<num>\d{1,3}(?:[.,]\d{1,2})?)\s?%")
"""A percentage as a text writes it: 57 %, 57%, 57,3 %, 57.3 %."""
_GAP: Final = re.compile(r"\s*")

UNCITED: Final = "uncited"
OTHER_VERSION: Final = "other_version"
UNKNOWN_READING: Final = "unknown_reading"
MISMATCH: Final = "mismatch"
ORPHAN: Final = "orphan"


def rounded_pct(p: float, decimals: int = 0) -> Decimal:
    """``p`` as a percentage rounded half up (the contracts' ``base.rounded_pct``; a test holds the two equal)."""
    q = Decimal(1).scaleb(-decimals)
    return (Decimal(str(p)) * 100).quantize(q, rounding=ROUND_HALF_UP)


def cite(reading_id: str, p: float, *, version: str, decimals: int = 0, comma: bool = True) -> str:
    """The one way a figure enters a text: its percentage, as the reader is shown it, and its citation."""
    pct = str(rounded_pct(p, decimals))
    return f"{pct.replace('.', ',') if comma else pct} % [cifra {version} {reading_id}]"


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    at: int
    """Where in the text (a character offset)."""
    detail: str


@dataclass(frozen=True, slots=True)
class Verdict:
    rule: str
    figures: int
    """How many cited percentages the text states."""
    problems: tuple[Problem, ...]

    @property
    def accepted(self) -> bool:
        return not self.problems

    def as_json(self) -> dict[str, object]:
        return {"rule": self.rule, "accepted": self.accepted, "figures": self.figures,
                "problems": [{"code": p.code, "at": p.at, "detail": p.detail} for p in self.problems]}


def check(text: str, readings: Mapping[str, float], *, version: str) -> Verdict:
    """Every percentage of ``text`` against the figures it cites. ``readings``: reading id -> probability, the figures of ``version`` for the
    match as of the moment the text was written from."""
    problems: list[Problem] = []
    used: set[int] = set()
    cited = 0
    for m in PERCENT.finditer(text):
        gap = _GAP.match(text, m.end())
        start = m.end() if gap is None else gap.end()
        c = CITATION.match(text, start)
        written = m.group("num").replace(",", ".")
        if c is None:
            problems.append(Problem(UNCITED, m.start(), f"{m.group(0)} without a citation"))
            continue
        used.add(c.start())
        cited += 1
        rid, v = c.group("id"), c.group("version")
        if v != version:
            problems.append(Problem(OTHER_VERSION, m.start(), f"{m.group(0)} cites {v}, the text is written from {version}"))
            continue
        p = readings.get(rid)
        if p is None:
            problems.append(Problem(UNKNOWN_READING, m.start(), f"{m.group(0)} cites {rid}, not a reading of {version} for this match"))
            continue
        decimals = len(written.split(".")[1]) if "." in written else 0
        expected = rounded_pct(p, decimals)
        if Decimal(written) != expected:
            problems.append(Problem(MISMATCH, m.start(), f"{m.group(0)} but the reading {rid} is {expected} %"))
    for c in CITATION.finditer(text):
        if c.start() not in used:
            problems.append(Problem(ORPHAN, c.start(), f"{c.group(0)} follows no percentage"))
    return Verdict(RULE, cited, tuple(sorted(problems, key=lambda p: p.at)))
