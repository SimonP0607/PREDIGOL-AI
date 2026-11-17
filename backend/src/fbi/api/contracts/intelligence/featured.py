"""C-12, the analyses Home features (AD-J09, IA-134): ``featured_analyses`` in ``GET /api/v1/home``, PUBLIC projection only.

``GET /home`` keeps its shape and gains an optional ``featured_analyses`` field: this contract, only while ``FBI_MATCH_INTELLIGENCE`` is
on. Each item is the summary of a match's public projection of C-01 (``MatchIntelligence``: the same ``match`` and ``selections``
objects, built by the same code), so a featured analysis never says more than the match's own tab. Only an analysis with a selection
the owner published reaches it; a match in the shadow never does - with nothing published the list is empty with its reason
(``sin_publicados``), never quietly empty.

THE RULE (``featured-v1``, in code): the matches with at least one published selection that kick off in the next ``window_hours``;
first those of a reader's favourite team, then those of a competition the reader follows, then the soonest; at most ``max_items``.
Every item says why it is there (``reasons``). The favourites only order (``FBI_PERSONALIZATION``): they never change a selection,
a figure or a state.

There is no private route: the private class is the server's own working answer (the candidates it read), projected here.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    private,
)
from fbi.api.contracts.intelligence.match import MatchInfo, Selection

FeaturedReason = Literal["equipo_favorito", "competicion_seguida", "partido_proximo"]
"""Why an analysis is featured: the reader follows one of its teams, its competition, or it is simply the next one."""


class FeaturedRule(IntelligenceModel):
    """The rule that chose the items, as data: the web receives it, it never fixes it."""

    version: str = Field(pattern=r"^featured-v\d+$")
    window_hours: int = Field(ge=1)
    max_items: int = Field(ge=1)
    order: list[FeaturedReason] = Field(description="The order the reasons rank by, first to last.")


class FeaturedAnalysis(IntelligenceModel):
    """A published analysis: the match and its published selections, as C-01's public projection gives them."""

    match: MatchInfo
    selections: list[Selection] = Field(min_length=1, description="Only what the owner published (C-01's public selections).")
    reasons: list[FeaturedReason] = Field(min_length=1)


class FeaturedAnalysisPrivate(FeaturedAnalysis):
    """The candidate as the server read it."""

    published: bool = private(description="True when C-01's public projection of the match carries a published selection.")

    def shown_in_public(self) -> bool:
        return self.published


class FeaturedAnalyses(IntelligenceContract):
    """C-12, public projection."""

    CONTRACT_ID: ClassVar[str] = "C-12"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    rule: FeaturedRule
    personalised: bool = Field(description="True when the reader's favourites ordered the list.")
    items: ItemList[FeaturedAnalysis]


class FeaturedAnalysesPrivate(FeaturedAnalyses):
    """The server's working answer: every candidate it read (no route serves it)."""

    items: ItemList[FeaturedAnalysisPrivate]  # type: ignore[assignment]
    candidates: int = private(ge=0, description="Matches with a published selection in the window, before the cut.")
