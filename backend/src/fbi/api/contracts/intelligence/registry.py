"""Every Intelligence contract, registered once (AD-J01, IA-057).

A contract enters ``CONTRACTS`` the day its models are merged, with its two classes and its routes. From then on the
generic tests (``tests/unit/test_intelligence_contract_*.py``) go through it on every run: its examples validate, its
public projection leaks nothing, its private routes answer 403 to a reader, and a change of shape without the version it
needs fails. ``CATALOGUE`` is the plan's list of the twelve contracts (coordination with UX, 16-nov-2026); its routes
are the agreed proposals until each contract fixes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fbi.api.contracts.intelligence.alerts import AlertsContract
from fbi.api.contracts.intelligence.availability import Availability, AvailabilityPrivate
from fbi.api.contracts.intelligence.base import IntelligenceContract
from fbi.api.contracts.intelligence.console import ConsoleContract
from fbi.api.contracts.intelligence.featured import FeaturedAnalyses, FeaturedAnalysesPrivate
from fbi.api.contracts.intelligence.market_probs import MarketProbs, MarketProbsPrivate
from fbi.api.contracts.intelligence.match import MatchIntelligence, MatchIntelligencePrivate
from fbi.api.contracts.intelligence.match_v2 import MatchIntelligenceV2, MatchIntelligenceV2Private
from fbi.api.contracts.intelligence.parlays import ParlaySetState, ParlaySetStatePrivate
from fbi.api.contracts.intelligence.post_evaluation import PostMatchEvaluation
from fbi.api.contracts.intelligence.profiles import Profile, ProfilePrivate
from fbi.api.contracts.intelligence.projection import (
    ProjectionError,
    has_private,
    public_counterpart,
    structure_problems,
)
from fbi.api.contracts.intelligence.reference import ConventionsSample, ConventionsSamplePrivate
from fbi.api.contracts.intelligence.search import SearchV2, SearchV2Private
from fbi.api.contracts.intelligence.selection import (
    SelectionIntelligence,
    SelectionIntelligencePrivate,
)
from fbi.api.contracts.intelligence.sources import AnalysisSources, AnalysisSourcesPrivate
from fbi.api.contracts.intelligence.stakes import Stakes, StakesPrivate
from fbi.api.contracts.intelligence.stats_profile import StatsProfile, StatsProfilePrivate
from fbi.api.contracts.intelligence.stories import News, NewsPrivate
from fbi.api.contracts.intelligence.tracking import Tracking
from fbi.api.contracts.intelligence.trends import Trends, TrendsPrivate
from fbi.api.contracts.intelligence.versioning import parse

PROFILE_PUBLIC_ROUTES: Final = ("/api/v1/teams/{team_id}/profile", "/api/v1/players/{player_id}/profile",
                                 "/api/v1/competitions/{competition_id}/profile")
"""C-09 (AD-H07, IA-090): additive routes beside /teams/{id}, /players/{id} and /competitions/{id}, which keep their shape. A
national team is a team: one resource, ``kind`` says which."""
NEWS_PUBLIC_ROUTES: Final = ("/api/v1/news/v2", "/api/v1/news/{item_id}", "/api/v1/matches/{fixture_id}/news/v2")
"""C-06 (AD-G07, IA-121): additive routes beside GET /news, /today/news and /matches/{id}/news of BE-040, which keep their shape and
what they read (``ai.evidence``); ``item_id`` is a story's key. 404 unless FBI_NEWS_FEED and FBI_NEWS_V2 are both on."""
NEWS_PRIVATE_ROUTES: Final = ("/api/v1/admin/intelligence/news", "/api/v1/admin/intelligence/news/{item_id}",
                              "/api/v1/admin/intelligence/matches/{fixture_id}/news")
SOURCES_PUBLIC_ROUTES: Final = ("/api/v1/matches/{fixture_id}/sources",)
"""C-07 (AD-G08, IA-122): 404 while FBI_MATCH_INTELLIGENCE is off or the match's analysis is not published."""
SOURCES_PRIVATE_ROUTES: Final = ("/api/v1/admin/intelligence/matches/{fixture_id}/sources",)
MATCH_V1_ROUTES: Final = ("/api/v1/matches/{fixture_id}/intelligence",)
MATCH_V1_PRIVATE_ROUTES: Final = ("/api/v1/admin/intelligence/matches/{fixture_id}/intelligence",)
MATCH_PUBLIC_ROUTES: Final = ("/api/v1/matches/{fixture_id}/intelligence/v2",)
"""C-01 2.0.0 (AD-J02 delivery 2, IA-131): additive routes beside the 1.x ones, which keep their shape. 404 while
FBI_MATCH_INTELLIGENCE is off."""
MATCH_PRIVATE_ROUTES: Final = ("/api/v1/admin/intelligence/matches/{fixture_id}/intelligence/v2",)
STATS_PUBLIC_ROUTES: Final = ("/api/v1/teams/{team_id}/stats", "/api/v1/players/{player_id}/stats", "/api/v1/stats/compare/teams",
                               "/api/v1/stats/compare/players", "/api/v1/matches/{fixture_id}/stats-preview")
"""C-13 (plan EA, EA-001/EA-007): 404 while FBI_STATS_V2 is off. Additive: no route of C-09 changes."""
STATS_PRIVATE_ROUTES: Final = ("/api/v1/admin/intelligence/teams/{team_id}/stats", "/api/v1/admin/intelligence/players/{player_id}/stats")
PROBS_PUBLIC_ROUTES: Final = ("/api/v1/matches/{fixture_id}/market-probs",)
"""C-14 (plan EA, EA-002/EA-201): 404 while FBI_MARKET_PROBS is off."""
PROBS_PRIVATE_ROUTES: Final = ("/api/v1/admin/intelligence/matches/{fixture_id}/market-probs",)
AVAILABILITY_PUBLIC_ROUTES: Final = ("/api/v1/availability/competitions", "/api/v1/availability/competitions/{competition_id}",
                                     "/api/v1/matches/{fixture_id}/availability")
"""C-16 (plan PM, PM-02-05): 404 while FBI_AVAILABILITY is off. Additive: no existing route changes."""
AVAILABILITY_PRIVATE_ROUTES: Final = ("/api/v1/admin/availability/matrix", "/api/v1/admin/availability/changes")
PROFILE_PRIVATE_ROUTES: Final = ("/api/v1/admin/intelligence/teams/{team_id}/profile",
                                 "/api/v1/admin/intelligence/players/{player_id}/profile",
                                 "/api/v1/admin/intelligence/competitions/{competition_id}/profile")


@dataclass(frozen=True)
class Planned:
    title: str
    piece: str
    public: tuple[str, ...]
    private: tuple[str, ...]


CATALOGUE: Final[dict[str, Planned]] = {
    "C-00": Planned("Muestra de convenciones (sin ruta)", "AD-J01", (), ()),
    "C-01": Planned("Partido", "AD-J02", MATCH_PUBLIC_ROUTES + MATCH_V1_ROUTES, MATCH_PRIVATE_ROUTES + MATCH_V1_PRIVATE_ROUTES),
    "C-02": Planned("Selección", "AD-J03", ("/api/v1/picks/{pick_id}/explanation",),
                    ("/api/v1/admin/intelligence/decisions/{decision_id}",)),
    "C-03": Planned("Seguimiento privado", "AD-J04", (), ("/api/v1/admin/intelligence/tracking",)),
    "C-04": Planned("Parlays con estado", "AD-J05", ("/api/v1/parlays/{kind}",),
                    ("/api/v1/admin/intelligence/parlays",)),
    "C-05": Planned("Alertas por alineación", "AD-J06", (), ("/api/v1/admin/intelligence/alerts",)),
    "C-06": Planned("Noticia", "AD-G07", NEWS_PUBLIC_ROUTES, NEWS_PRIVATE_ROUTES),
    "C-07": Planned("Fuentes del análisis", "AD-G08", SOURCES_PUBLIC_ROUTES, SOURCES_PRIVATE_ROUTES),
    "C-08": Planned("Evaluación posterior", "AD-J07", (),
                    ("/api/v1/admin/intelligence/evaluations/{fixture_id}",)),
    "C-09": Planned("Perfiles", "AD-H07", PROFILE_PUBLIC_ROUTES, PROFILE_PRIVATE_ROUTES),
    "C-10": Planned("Búsqueda v2", "AD-I02", ("/api/v1/search/v2",), ("/api/v1/admin/search/v2",)),
    "C-11": Planned("Consola", "AD-J08", (), ("/api/v1/admin/intelligence/console",)),
    "C-12": Planned("Inicio", "AD-J09", ("/api/v1/home",), ()),
    "C-13": Planned("Perfil estadístico", "EA-001", STATS_PUBLIC_ROUTES, STATS_PRIVATE_ROUTES),
    "C-14": Planned("Probabilidades por mercado", "EA-002", PROBS_PUBLIC_ROUTES, PROBS_PRIVATE_ROUTES),
    "C-16": Planned("Disponibilidad", "PM-02-05", AVAILABILITY_PUBLIC_ROUTES, AVAILABILITY_PRIVATE_ROUTES),
    "C-17": Planned("Unidades (sin ruta: FBI_STAKES apagado)", "AP-K07", (), ()),
    "C-18": Planned("Tendencias (sin ruta: FBI_TREND_BUILDER apagado)", "AP-L02", (), ()),
}
"""The twelve contracts of the plan and the reference one, C-13 and C-14 of plan EA, C-16 of plan PM (C-15 is reserved by plan EA), and
C-17 and C-18 of the plan of corrections UX/UI (contract and example only, no route until their switches).
A private route is always under ``/api/v1/admin/``."""


@dataclass(frozen=True)
class ContractSpec:
    """One registered contract: its private model (always), its public model (None for a private-only contract) and the
    routes that serve each projection (empty until the endpoint is merged).

    ``superseded``: an earlier MAJOR version that keeps serving its own routes beside the current one (AD-J01: versions, not
    rewrites; C-01 1.x beside 2.0.0). Its shape stays frozen in the snapshot under ``<id>@<major>`` (``key``); the current version
    of the contract is the one entry of its id that is not superseded. The examples of a major version N >= 2 live in
    ``<id>/vN/`` (``examples_dir``), those of 1.x in ``<id>/``."""

    private: type[IntelligenceContract]
    public: type[IntelligenceContract] | None
    public_routes: tuple[str, ...] = ()
    private_routes: tuple[str, ...] = ()
    superseded: bool = False

    @property
    def id(self) -> str:
        return self.private.CONTRACT_ID

    @property
    def version(self) -> str:
        return self.private.CONTRACT_VERSION

    @property
    def major(self) -> int:
        return parse(self.version)[0]

    @property
    def key(self) -> str:
        """The contract's key in the snapshot: its id, or ``<id>@<major>`` for a superseded major version."""
        return f"{self.id}@{self.major}" if self.superseded else self.id

    @property
    def examples_dir(self) -> str:
        """Where its examples are, relative to ``tests/fixtures/contracts/intelligence``."""
        return self.id if self.major == 1 else f"{self.id}/v{self.major}"

    @property
    def piece(self) -> str:
        return CATALOGUE[self.id].piece if self.id in CATALOGUE else "?"


CONTRACTS: Final[tuple[ContractSpec, ...]] = (
    ContractSpec(private=ConventionsSamplePrivate, public=ConventionsSample),
    ContractSpec(private=MatchIntelligenceV2Private, public=MatchIntelligenceV2, public_routes=MATCH_PUBLIC_ROUTES,
                 private_routes=MATCH_PRIVATE_ROUTES),
    ContractSpec(private=MatchIntelligencePrivate, public=MatchIntelligence, public_routes=MATCH_V1_ROUTES,
                 private_routes=MATCH_V1_PRIVATE_ROUTES, superseded=True),
    ContractSpec(private=SelectionIntelligencePrivate, public=SelectionIntelligence,
                 public_routes=("/api/v1/picks/{pick_id}/explanation",),
                 private_routes=("/api/v1/admin/intelligence/decisions/{decision_id}",)),
    ContractSpec(private=Tracking, public=None, private_routes=("/api/v1/admin/intelligence/tracking",)),
    ContractSpec(private=ConsoleContract, public=None, private_routes=("/api/v1/admin/intelligence/console",)),
    ContractSpec(private=AlertsContract, public=None, private_routes=("/api/v1/admin/intelligence/alerts",)),
    ContractSpec(private=SearchV2Private, public=SearchV2, public_routes=("/api/v1/search/v2",),
                 private_routes=("/api/v1/admin/search/v2",)),
    ContractSpec(private=ProfilePrivate, public=Profile, public_routes=PROFILE_PUBLIC_ROUTES,
                 private_routes=PROFILE_PRIVATE_ROUTES),
    ContractSpec(private=NewsPrivate, public=News, public_routes=NEWS_PUBLIC_ROUTES, private_routes=NEWS_PRIVATE_ROUTES),
    ContractSpec(private=AnalysisSourcesPrivate, public=AnalysisSources, public_routes=SOURCES_PUBLIC_ROUTES,
                 private_routes=SOURCES_PRIVATE_ROUTES),
    ContractSpec(private=ParlaySetStatePrivate, public=ParlaySetState, public_routes=("/api/v1/parlays/{kind}",),
                 private_routes=("/api/v1/admin/intelligence/parlays",)),
    ContractSpec(private=PostMatchEvaluation, public=None,
                 private_routes=("/api/v1/admin/intelligence/evaluations/{fixture_id}",)),
    ContractSpec(private=FeaturedAnalysesPrivate, public=FeaturedAnalyses, public_routes=("/api/v1/home",)),
    ContractSpec(private=StatsProfilePrivate, public=StatsProfile, public_routes=STATS_PUBLIC_ROUTES,
                 private_routes=STATS_PRIVATE_ROUTES),
    ContractSpec(private=MarketProbsPrivate, public=MarketProbs, public_routes=PROBS_PUBLIC_ROUTES,
                 private_routes=PROBS_PRIVATE_ROUTES),
    ContractSpec(private=AvailabilityPrivate, public=Availability, public_routes=AVAILABILITY_PUBLIC_ROUTES,
                 private_routes=AVAILABILITY_PRIVATE_ROUTES),
    ContractSpec(private=StakesPrivate, public=Stakes),
    ContractSpec(private=TrendsPrivate, public=Trends),
)
"""Every Intelligence contract. A new one is added here in the PR that merges its models."""


def by_id() -> dict[str, ContractSpec]:
    """The current version of every contract by its id (a superseded major version is reached by ``by_key``)."""
    return {spec.id: spec for spec in CONTRACTS if not spec.superseded}


def by_key() -> dict[str, ContractSpec]:
    return {spec.key: spec for spec in CONTRACTS}


def spec_problems(spec: ContractSpec) -> list[str]:
    """What breaks the conventions in one registered contract (empty: nothing)."""
    problems: list[str] = []
    if spec.superseded and not any(s.id == spec.id and not s.superseded and s.major > spec.major for s in CONTRACTS):
        problems.append(f"{spec.key} is superseded but no newer major version of {spec.id} is registered")
    if spec.id not in CATALOGUE:
        problems.append(f"{spec.id} is not a contract of the plan's catalogue")
    if spec.public is None:
        if not spec.private.PRIVATE_ONLY:
            problems.append(f"{spec.id} has no public projection and does not say PRIVATE_ONLY")
        if spec.public_routes:
            problems.append(f"{spec.id} is private only and lists public routes")
    else:
        if not issubclass(spec.private, spec.public):
            problems.append(f"{spec.private.__name__} does not inherit from {spec.public.__name__}")
        if has_private(spec.public):
            problems.append(f"{spec.public.__name__} reaches a private field: it cannot be the public projection")
        if not has_private(spec.private):
            problems.append(f"{spec.private.__name__} adds nothing private: the private projection would equal the public")
        elif spec.private is not spec.public:
            try:
                base = public_counterpart(spec.private)
            except ProjectionError as exc:
                problems.append(str(exc))
            else:
                if base is not spec.public:
                    problems.append(f"{spec.private.__name__} derives from {base.__name__}, not from {spec.public.__name__}")
        problems += structure_problems(spec.public)
    problems += structure_problems(spec.private)
    for route in spec.public_routes:
        if not route.startswith("/api/v1/") or route.startswith("/api/v1/admin/"):
            problems.append(f"{route}: a public route lives under /api/v1/ and outside /api/v1/admin/")
    for route in spec.private_routes:
        if not route.startswith("/api/v1/admin/"):
            problems.append(f"{route}: a private route lives under /api/v1/admin/ (require_admin)")
    return problems
