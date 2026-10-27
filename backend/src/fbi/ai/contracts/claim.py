"""``claim-v1``: what the Research Service's extractor (Haiku 5.5) returns about ONE page it was shown.

The extractor reads untrusted web text (``fbi.ai.untrusted``) and writes typed claims, nothing else: WHO the claim is about (an id the
server listed for this match, never a name), WHAT kind of claim it is (a closed list), which match it applies to, a short quote of the
page that says it, which page (an id the server gave it) and the date the page states. It does not say how far to believe it: the STATUS
of an evidence is decided by the server from the source's class (``fbi.ai.evidence``), and a model cannot raise it.

Checked after the answer (``check``): the subject id is one of the match's, the page id is one of the pages shown, the quote is in that
page (after the same normalisation the page went through) and no longer than ``QUOTE_MAX``, the date is a date. A claim that fails any of
these is dropped and counted; the others stand. A page whose answer is not this schema at all is discarded and recorded (``invalid``).

Free text: ``quote`` - copied from the page, so as untrusted as the page. It is shown as a quotation and never read as an instruction.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from pydantic import Field, field_validator

from fbi.ai.contracts.base import Contract

QUOTE_MAX: Final = 300
CLAIMS_MAX: Final = 20
"""Claims from one page."""

ClaimType = Literal["OUT", "DOUBT", "AVAILABLE", "STARTER", "SUSPENSION", "COACH", "SCHEDULE", "VENUE", "OTHER"]
"""Out, doubtful, back, in the eleven, banned, the coach, the time, the ground, anything else (baja, duda, disponible, titular, sanción,
entrenador, horario, sede, otro)."""
SubjectKind = Literal["TEAM", "PLAYER", "COACH", "REFEREE", "MATCH", "COMPETITION"]
AppliesTo = Literal["THIS_MATCH", "NEXT_MATCH", "OTHER_MATCH", "UNSPECIFIED"]
"""Which match the claim is about: this one, the side's next one (a suspension that starts after it), another or not said."""

LABELS_ES: Final = {"OUT": "baja", "DOUBT": "duda", "AVAILABLE": "disponible", "STARTER": "titular", "SUSPENSION": "sanción",
                    "COACH": "entrenador", "SCHEDULE": "horario", "VENUE": "sede", "OTHER": "otro"}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Claim(Contract):
    subject_kind: SubjectKind
    subject_id: int
    claim_type: ClaimType
    applies_to: AppliesTo
    quote: str = Field(max_length=QUOTE_MAX)
    page_id: str
    published_on: str
    """``YYYY-MM-DD`` as the page states it, or the empty string when it does not say."""

    @field_validator("published_on")
    @classmethod
    def _a_date_or_nothing(cls, v: str) -> str:
        if v and not _DATE.match(v):
            raise ValueError("published_on is a YYYY-MM-DD date or empty")
        if v:
            date.fromisoformat(v)
        return v


class ClaimsOut(Contract):
    contract: Literal["claim-v1"]
    claims: list[Claim] = Field(max_length=CLAIMS_MAX)


@dataclass(frozen=True, slots=True)
class Checked:
    kept: tuple[Claim, ...]
    dropped: tuple[tuple[int, str], ...]
    """(position, reason) of every claim that did not stand."""


def check(out: ClaimsOut, *, subjects: dict[str, Collection[int]], pages: dict[str, str]) -> Checked:
    """The claims of a page that stand. ``subjects`` is what the server listed for the match (kind -> ids), ``pages`` the pages shown
    (id -> the text the model read, already normalised): a claim about a subject that was not listed, from a page that was not shown, or
    quoting what the page does not say, does not stand."""
    kept: list[Claim] = []
    dropped: list[tuple[int, str]] = []
    for i, claim in enumerate(out.claims):
        if claim.subject_id not in subjects.get(claim.subject_kind, ()):
            dropped.append((i, "subject_not_listed"))
        elif claim.page_id not in pages:
            dropped.append((i, "page_not_shown"))
        elif _squash(claim.quote) not in _squash(pages[claim.page_id]):
            dropped.append((i, "quote_not_in_page"))
        else:
            kept.append(claim)
    return Checked(tuple(kept), tuple(dropped))


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()
