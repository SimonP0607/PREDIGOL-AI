"""``claim-v1``: what the Research Service's extractor (Haiku 5.5) returns about the pages it was shown (one call reads up to six).

The extractor reads untrusted web text (``fbi.ai.untrusted``) and writes typed claims, nothing else: WHO the claim is about (an id the
server listed for this match, never a name), WHAT kind of claim it is (a closed list), which match it applies to, a short quote of the
page that says it, which page (an id the server gave it) and the date the page states. It does not say how far to believe it: the STATUS
of an evidence is decided by the server from the source's class (``fbi.ai.evidence``), and a model cannot raise it.

Checked after the answer (``check``), claim by claim - a claim that fails is dropped and counted, the others stand:

* the subject id is one of the match's, the page id is one of the pages shown;
* the quote has a length (``QUOTE_MIN_CHARS`` characters, ``QUOTE_MIN_WORDS`` words) and is in ONE part of that page - its title or its text,
  the two fields the model was shown apart - after the same normalisation the page went through;
* a claim about a PLAYER quotes a passage that names him (a word of his name, without accents or case) and says something besides his name:
  a page that never names him is not the page that says something of him (independent review of phase 2, 27 Oct 2026, H1).

The limits the wire schema cannot carry (a quote of at most ``QUOTE_MAX`` characters, at most ``CLAIMS_MAX`` claims, a date that is a date)
are checked per claim as well, by ``fbi.ai.extract_v2.read``: one claim over a limit costs that claim and not the answer. An answer that is
not this schema at all - a field the contract does not have, a value outside an enum - is discarded whole, with the pages it covered, and
recorded (``invalid``).

Free text: ``quote`` - copied from the page, so as untrusted as the page. It is shown as a quotation and never read as an instruction.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from pydantic import Field, field_validator

from fbi.ai.contracts.base import Contract

QUOTE_MAX: Final = 300
QUOTE_MIN_CHARS: Final = 10
QUOTE_MIN_WORDS: Final = 2
"""The shortest quote that is a quote: a single word («injured») is in every page that talks of injuries and proves nothing of anyone."""
CLAIMS_MAX: Final = 20
"""Claims in one ANSWER. An answer covers the pages of one call (``fbi.ai.extract_v2.MAX_PAGES``, six): the cap is not per page. The claims
past the twentieth are dropped (``too_many``) by ``fbi.ai.extract_v2.read`` and the answer stands: the cap is a limit of this contract, which
the wire schema cannot carry, and a model that writes one claim more than it is allowed costs that claim and not the other twenty."""

ClaimType = Literal["OUT", "DOUBT", "AVAILABLE", "STARTER", "SUSPENSION", "COACH", "SCHEDULE", "VENUE", "OTHER"]
"""Out, doubtful, back, in the eleven, banned, the coach, the time, the ground, anything else (baja, duda, disponible, titular, sanción,
entrenador, horario, sede, otro)."""
SubjectKind = Literal["TEAM", "PLAYER", "COACH", "REFEREE", "MATCH", "COMPETITION"]
AppliesTo = Literal["THIS_MATCH", "NEXT_MATCH", "OTHER_MATCH", "UNSPECIFIED"]
"""Which match the claim is about: this one, the side's next one (a suspension that starts after it), another or not said."""

LABELS_ES: Final = {"OUT": "baja", "DOUBT": "duda", "AVAILABLE": "disponible", "STARTER": "titular", "SUSPENSION": "sanción",
                    "COACH": "entrenador", "SCHEDULE": "horario", "VENUE": "sede", "OTHER": "otro"}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date(text: str) -> bool:
    """``YYYY-MM-DD`` and a day that exists."""
    if not _DATE.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


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
        if v and not valid_date(v):
            raise ValueError("published_on is a YYYY-MM-DD date or empty")
        return v


class ClaimsOut(Contract):
    contract: Literal["claim-v1"]
    claims: list[Claim] = Field(max_length=CLAIMS_MAX)


@dataclass(frozen=True, slots=True)
class Checked:
    kept: tuple[Claim, ...]
    dropped: tuple[tuple[int, str], ...]
    """(position, reason) of every claim that did not stand."""


PARTICLES: Final = frozenset({"de", "da", "do", "das", "dos", "del", "della", "di", "du", "van", "von", "der", "den", "bin", "ibn", "el", "al", "la",
                              "le", "los", "las", "jr", "sr", "ii", "iii"})
"""Words of a name that a quote can hold without naming anyone («de», «Jr»): they never tie a quote to a player."""
_WORD = re.compile(r"[^\W_]+")


def fold(text: str) -> str:
    """Lower case and without accents: the form in which a name is compared with the words of a quote."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold()


def words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def name_tokens(name: str) -> frozenset[str]:
    """The words of a name that a quote must hold (one of them) to be about the person: without accents or case, without particles, and
    without initials («K. Mbappé» is «mbappe»). Words of three letters or more; a name made of shorter ones («Li Yu») uses those. Empty when
    the name has nothing to look for."""
    parts = [w for w in words(name) if w not in PARTICLES]
    return frozenset([w for w in parts if len(w) >= 3] or [w for w in parts if len(w) >= 2])


def check(out: ClaimsOut, *, subjects: Mapping[str, Collection[int]], pages: Mapping[str, str | Sequence[str]],
          named: Mapping[tuple[str, int], Collection[str]] | None = None) -> Checked:
    """The claims of an answer that stand. ``subjects`` is what the server listed for the match (kind -> ids), ``pages`` the pages shown (id ->
    the parts of the text the model read - title, text - already normalised; a bare string is one part), ``named`` the words a quote about
    a subject must hold one of (``(kind, id)`` -> ``name_tokens``; a subject with no entry is not asked, one with none has no claim).

    In order: a claim about a subject that was not listed, from a page that was not shown, with a quote too short to be one, that is not in
    one part of its page, or that does not name the player it is about (or names him and says nothing more), does not stand."""
    shown = {page: tuple(_squash(p) for p in ((parts,) if isinstance(parts, str) else parts)) for page, parts in pages.items()}
    kept: list[Claim] = []
    dropped: list[tuple[int, str]] = []
    for i, claim in enumerate(out.claims):
        quote = _squash(claim.quote)
        if claim.subject_id not in subjects.get(claim.subject_kind, ()):
            dropped.append((i, "subject_not_listed"))
        elif claim.page_id not in shown:
            dropped.append((i, "page_not_shown"))
        elif len(quote) < QUOTE_MIN_CHARS or len(quote.split()) < QUOTE_MIN_WORDS:
            dropped.append((i, "quote_too_short"))
        elif not any(quote in part for part in shown[claim.page_id]):
            dropped.append((i, "quote_not_in_page"))
        elif (why := _unnamed(claim, named)) is not None:
            dropped.append((i, why))
        else:
            kept.append(claim)
    return Checked(tuple(kept), tuple(dropped))


def _unnamed(claim: Claim, named: Mapping[tuple[str, int], Collection[str]] | None) -> str | None:
    """Why a claim about a player does not stand for what its quote says of him, or None."""
    tokens = None if named is None else named.get((claim.subject_kind, claim.subject_id))
    if tokens is None:
        return None
    said = words(claim.quote)
    if not any(w in tokens for w in said):
        return "quote_without_subject"
    if all(w in tokens or w in PARTICLES for w in said):
        return "quote_too_short"
    return None


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()
