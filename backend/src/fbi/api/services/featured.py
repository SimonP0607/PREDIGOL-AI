"""C-12, the analyses Home features (AD-J09, IA-134). Reading only.

The candidates are the matches with at least one selection the owner published (the ``qualified`` daily set, the one C-01 shows a reader
as a pick) that kick off in the next ``WINDOW``. Each is summarised from the match's PUBLIC projection of C-01 (``match_intelligence.build``
then ``to_public``): its ``match`` and its published ``selections``, the same objects the match's tab serves - so a featured analysis can
never carry a selection in the shadow. They are read once for every reader (``shared``, the same 30 s as the rest of ``/home``); the
reader's favourites then only order them (``FBI_PERSONALIZATION``) and each item says why it is there.

With nothing published the list is empty with its reason (``sin_publicados``). With ``FBI_MATCH_INTELLIGENCE`` off ``for_home`` answers
None and ``/home`` does not carry the field at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import structlog

from fbi.api.cache import shared
from fbi.api.contracts.intelligence.base import Freshness, ItemList
from fbi.api.contracts.intelligence.featured import (
    FeaturedAnalyses,
    FeaturedAnalysesPrivate,
    FeaturedAnalysisPrivate,
    FeaturedReason,
    FeaturedRule,
)
from fbi.api.contracts.intelligence.match import MatchInfo, MatchIntelligence, Selection
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services import match_intelligence
from fbi.api.switches import match_intelligence_on
from fbi.core.clock import now as clock_now
from fbi.customer import favorites

log = structlog.get_logger(__name__)

VERSION: Final = "featured-v1"
WINDOW: Final = timedelta(hours=48)
MAX_ITEMS: Final = 4
MAX_CANDIDATES: Final = 8
"""At most this many matches are summarised per answer (each is a C-01 build); the rule keeps MAX_ITEMS of them."""
ORDER: Final[tuple[FeaturedReason, ...]] = ("equipo_favorito", "competicion_seguida", "partido_proximo")
RULE: Final = FeaturedRule(version=VERSION, window_hours=int(WINDOW.total_seconds() // 3600), max_items=MAX_ITEMS, order=list(ORDER))

CANDIDATES_SQL: Final = """
SELECT DISTINCT f.id, f.kickoff_at
  FROM picks.daily_sets s
  JOIN picks.daily_set_items i ON i.set_id = s.id
  JOIN core.fixtures f ON f.id = i.fixture_id
 WHERE s.source = 'qualified' AND i.selected_at <= %(at)s AND f.kickoff_at >= %(at)s AND f.kickoff_at < %(until)s
 ORDER BY f.kickoff_at, f.id
 LIMIT %(limit)s
"""
"""The matches with a selection the owner published that kick off in the window (``qualified`` only: never the owner's preview)."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """A match with what its public C-01 shows."""

    match: MatchInfo
    selections: tuple[Selection, ...]


def summary(answer: MatchIntelligence) -> Candidate:
    """The part of a match's public C-01 Home features. Pure."""
    return Candidate(match=answer.match, selections=tuple(answer.selections.items))


@shared(30)
def candidates(conn: Conn, *, at: datetime | None = None) -> tuple[Candidate, ...]:
    """The published analyses of the window, soonest first, each from the match's public C-01. Reading only."""
    moment = at or clock_now()
    rows = fetch_all(conn, CANDIDATES_SQL, {"at": moment, "until": moment + WINDOW, "limit": MAX_CANDIDATES})
    out: list[Candidate] = []
    for r in rows:
        built = match_intelligence.build(conn, int(r["id"]), at=moment)
        out.append(summary(to_public(built, MatchIntelligence)))
    return tuple(out)


def reasons_of(c: Candidate, *, teams: frozenset[int], leagues: frozenset[int]) -> list[FeaturedReason]:
    out: list[FeaturedReason] = []
    if {c.match.home.id, c.match.away.id} & teams:
        out.append("equipo_favorito")
    if c.match.competition.id in leagues:
        out.append("competicion_seguida")
    out.append("partido_proximo")
    return out


def assemble(found: Sequence[Candidate], *, at: datetime, teams: frozenset[int] = frozenset(),
             leagues: frozenset[int] = frozenset(), personalised: bool = False) -> FeaturedAnalysesPrivate:
    """The rule over the candidates: favourite team, then followed competition, then the soonest; at most ``MAX_ITEMS``. Pure."""
    def key(c: Candidate) -> tuple[bool, bool, datetime, int]:
        why = reasons_of(c, teams=teams, leagues=leagues)
        return "equipo_favorito" not in why, "competicion_seguida" not in why, c.match.kickoff_at, c.match.id

    ranked = sorted(found, key=key)
    items = [FeaturedAnalysisPrivate(match=c.match, selections=list(c.selections), reasons=reasons_of(c, teams=teams, leagues=leagues),
                                     published=True) for c in ranked if c.selections][:MAX_ITEMS]
    return FeaturedAnalysesPrivate(
        freshness=Freshness(generated_at=at, stale=False), rule=RULE, personalised=personalised and bool(teams or leagues),
        items=ItemList[FeaturedAnalysisPrivate](items=items) if items else ItemList[FeaturedAnalysisPrivate](
            items=[], missing_reason="sin_publicados"),
        candidates=len(found))


def public(answer: FeaturedAnalysesPrivate) -> FeaturedAnalyses:
    projected = to_public(answer, FeaturedAnalyses)
    assert isinstance(projected, FeaturedAnalyses)
    return projected


def _favourites(conn: Conn, user_id: int) -> tuple[frozenset[int], frozenset[int], bool]:
    if not favorites.personalization_on():
        return frozenset(), frozenset(), False
    mine = favorites.chosen(conn, user_id)
    if mine is None:
        return frozenset(), frozenset(), False
    return frozenset(mine.teams), frozenset(mine.leagues), True


def for_home(conn: Conn, *, user_id: int, at: datetime | None = None) -> FeaturedAnalyses | None:
    """``featured_analyses`` of ``/home`` for one reader, or None with ``FBI_MATCH_INTELLIGENCE`` off. A failure to build it leaves
    ``/home`` as it was (the field absent) and is logged: the rest of the page must keep answering."""
    if not match_intelligence_on():
        return None
    moment = at or clock_now()
    try:
        found = candidates(conn, at=at)
        teams, leagues, personal = _favourites(conn, user_id)
        return public(assemble(found, at=moment, teams=teams, leagues=leagues, personalised=personal))
    except Exception:  # Home must answer whatever C-12 does
        log.warning("featured.build_failed", exc_info=True)
        return None

