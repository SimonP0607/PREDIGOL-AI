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
from fbi.api.contracts.intelligence.base import IntelligenceContract
from fbi.api.contracts.intelligence.console import ConsoleContract
from fbi.api.contracts.intelligence.match import MatchIntelligence, MatchIntelligencePrivate
from fbi.api.contracts.intelligence.profiles import Profile, ProfilePrivate
from fbi.api.contracts.intelligence.projection import (
    ProjectionError,
    has_private,
    public_counterpart,
    structure_problems,
)
from fbi.api.contracts.intelligence.reference import ConventionsSample, ConventionsSamplePrivate
from fbi.api.contracts.intelligence.search import SearchV2, SearchV2Private

PROFILE_PUBLIC_ROUTES: Final = ("/api/v1/teams/{team_id}/profile", "/api/v1/players/{player_id}/profile",
                                 "/api/v1/competitions/{competition_id}/profile")
"""C-09 (AD-H07, IA-090): additive routes beside /teams/{id}, /players/{id} and /competitions/{id}, which keep their shape. A
national team is a team: one resource, ``kind`` says which."""
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
    "C-01": Planned("Partido", "AD-J02", ("/api/v1/matches/{fixture_id}/intelligence",),
                    ("/api/v1/admin/intelligence/matches/{fixture_id}/intelligence",)),
    "C-02": Planned("Selección", "AD-J03", ("/api/v1/picks/{pick_id}/explanation",),
                    ("/api/v1/admin/intelligence/decisions/{decision_id}",)),
    "C-03": Planned("Seguimiento privado", "AD-J04", (), ("/api/v1/admin/intelligence/tracking",)),
    "C-04": Planned("Parlays con estado", "AD-J05", ("/api/v1/parlays/{kind}",),
                    ("/api/v1/admin/intelligence/parlays",)),
    "C-05": Planned("Alertas por alineación", "AD-J06", (), ("/api/v1/admin/intelligence/alerts",)),
    "C-06": Planned("Noticia", "AD-G07", ("/api/v1/news", "/api/v1/news/{item_id}", "/api/v1/matches/{fixture_id}/news",
                                          "/api/v1/today/news"), ()),
    "C-07": Planned("Fuentes del análisis", "AD-G08", ("/api/v1/matches/{fixture_id}/sources",), ()),
    "C-08": Planned("Evaluación posterior", "AD-J07", (),
                    ("/api/v1/admin/intelligence/evaluations/{fixture_id}",)),
    "C-09": Planned("Perfiles", "AD-H07", PROFILE_PUBLIC_ROUTES, PROFILE_PRIVATE_ROUTES),
    "C-10": Planned("Búsqueda v2", "AD-I02", ("/api/v1/search/v2",), ("/api/v1/admin/search/v2",)),
    "C-11": Planned("Consola", "AD-J08", (), ("/api/v1/admin/intelligence/console",)),
    "C-12": Planned("Inicio", "AD-J09", ("/api/v1/home",), ()),
}
"""The twelve contracts of the plan and the reference one. A private route is always under ``/api/v1/admin/``."""


@dataclass(frozen=True)
class ContractSpec:
    """One registered contract: its private model (always), its public model (None for a private-only contract) and the
    routes that serve each projection (empty until the endpoint is merged)."""

    private: type[IntelligenceContract]
    public: type[IntelligenceContract] | None
    public_routes: tuple[str, ...] = ()
    private_routes: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.private.CONTRACT_ID

    @property
    def version(self) -> str:
        return self.private.CONTRACT_VERSION

    @property
    def piece(self) -> str:
        return CATALOGUE[self.id].piece if self.id in CATALOGUE else "?"


CONTRACTS: Final[tuple[ContractSpec, ...]] = (
    ContractSpec(private=ConventionsSamplePrivate, public=ConventionsSample),
    ContractSpec(private=MatchIntelligencePrivate, public=MatchIntelligence,
                 public_routes=("/api/v1/matches/{fixture_id}/intelligence",),
                 private_routes=("/api/v1/admin/intelligence/matches/{fixture_id}/intelligence",)),
    ContractSpec(private=ConsoleContract, public=None, private_routes=("/api/v1/admin/intelligence/console",)),
    ContractSpec(private=AlertsContract, public=None, private_routes=("/api/v1/admin/intelligence/alerts",)),
    ContractSpec(private=SearchV2Private, public=SearchV2, public_routes=("/api/v1/search/v2",),
                 private_routes=("/api/v1/admin/search/v2",)),
    ContractSpec(private=ProfilePrivate, public=Profile, public_routes=PROFILE_PUBLIC_ROUTES,
                 private_routes=PROFILE_PRIVATE_ROUTES),
)
"""Every Intelligence contract. A new one is added here in the PR that merges its models."""


def by_id() -> dict[str, ContractSpec]:
    return {spec.id: spec for spec in CONTRACTS}


def spec_problems(spec: ContractSpec) -> list[str]:
    """What breaks the conventions in one registered contract (empty: nothing)."""
    problems: list[str] = []
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
