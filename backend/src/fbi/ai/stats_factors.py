"""The DESCRIPTIVE factors of the Statistics Agent (Plan Maestro IA, phase 4; architecture, section 10): what it may MENTION and may never give as a reason.

Two kinds of thing are DESCRIPTIVE for this agent:

* the context factors of the packet that its slice carries (``fbi.intel.factors.CATALOGUE``): the observable tactics and rest and congestion (and the
  weighted head-to-head and the scenarios, should a later slice carry them). Their status is the registry's (``shared.factors.<key>.status`` of the
  package); one that is not VALIDATED is DESCRIPTIVE, and ``descriptive_blocks`` says which paths and which driver codes it blocks;
* the RELATIONS the plan names - pressure -> shots -> corners and intensity -> fouls -> cards (``RELATIONS``). They are recorded in
  ``intel.context_factors`` as DESCRIPTIVE with the experiment that would test them (``register_relations``), idempotently and without a migration
  (the table is the registry of ``fbi.intel.factors`` and already takes any factor key). They are NOT in ``fbi.intel.factors.CATALOGUE`` on purpose:
  the catalogue builds the block ``factors`` of EVERY packet (``packet-v8``), and adding to it would change what every reviewer reads. F11.6 measured
  that the totals of goals, corners and cards barely depend on each other (-0.021 to -0.028 over 59,252 matches), so nobody has shown these relations.

Only a person validates a factor, with an experiment and its result (``python -m scripts.context_factors``); the system writes DESCRIPTIVE rows and nothing
else, and a database constraint refuses a VALIDATED row that is not a person's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from fbi.intel import factors

VERSION: Final = "stats-relations-v1"
"""The version of the code that states these relations. A change to what a relation says is a new version, and a validation never carries over to it."""


@dataclass(frozen=True, slots=True)
class Relation:
    """A relation between counts that PrediGol can mention and has not tested: its key in the registry, what it says and the experiment that would test it."""

    key: str
    label: str
    claim: str
    experiment: str


RELATIONS: Final[tuple[Relation, ...]] = (
    Relation("pressure_shots_corners", "Presión -> tiros -> córners",
             "que la presión que un equipo ejerce (tiros, posesión en campo rival) anticipa los córners del partido mejor que sus tasas de córners y que el mercado",
             "backtest de córners con el factor de presión contra family-v1 y contra el mercado, sobre partidos liquidados con 3 casas o más"),
    Relation("intensity_fouls_cards", "Intensidad -> faltas -> tarjetas",
             "que la intensidad del partido (faltas, duelos) anticipa las tarjetas mejor que las tasas de tarjetas, el árbitro y el mercado",
             "backtest de tarjetas con el factor de intensidad contra family-v1 con el multiplicador del árbitro y contra el mercado, con la regla cards_lines_ft@v1"),
)
"""Every relation is DESCRIPTIVE. The Statistics Agent may mention one as a signal ``RATE`` (direction NEUTRAL, strength LOW) and a stance never rests on it."""

BLOCKED_DRIVERS: Final[dict[str, str]] = {"h2h_weighted": "H2H", "tactics_profile": "TACTICS", "rest_congestion": "SCHEDULE"}
"""The signal code of each context factor of the packet whose code is the factor's own: a stance never rests on it while the factor is not VALIDATED. The
scenarios have no code of their own (STAKES also comes from the standings, which are data), so for them only the path is blocked."""

REASON: Final = "Registrado como DESCRIPTIVO por el Agente de Estadísticas (stats-v1): nadie ha probado la relación, no puede ser razón de un veredicto."


def package_path(factor: factors.Factor) -> str:
    """Where the package carries the block of a factor of the catalogue: ``shared.<name>`` (``dossier.tactics`` is ``shared.tactics``)."""
    parts = [p for p in factor.block if p != "dossier"]
    return ".".join(["shared", *parts])


def descriptive_blocks(document: Mapping[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    """``(paths, drivers)`` that a stance may not rest on, from the statuses a package states (``shared.factors.<key>.status``): every factor of the
    catalogue that the package does not list as VALIDATED is DESCRIPTIVE - born so, and the safe side of every doubt, including a package that says nothing."""
    shared = document.get("shared")
    states = shared.get("factors") if isinstance(shared, Mapping) else None
    paths: set[str] = set()
    drivers: set[str] = set()
    for factor in factors.CATALOGUE:
        entry = states.get(factor.key) if isinstance(states, Mapping) else None
        status = entry.get("status") if isinstance(entry, Mapping) else None
        if status == factors.VALIDATED:
            continue
        paths.add(package_path(factor))
        if factor.key in BLOCKED_DRIVERS:
            drivers.add(BLOCKED_DRIVERS[factor.key])
    return frozenset(paths), frozenset(drivers)


def under(path: str, blocked: frozenset[str]) -> bool:
    """Whether a path of the package is a blocked block or anything inside it (``shared.tactics.home`` is inside ``shared.tactics``)."""
    return any(path == b or path.startswith(b + ".") for b in blocked)


def register_relations(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """Record every relation in ``intel.context_factors`` as DESCRIPTIVE (``decided_by`` system, no person) unless the registry already has a decision about
    it at this version. Idempotent: the second call writes nothing. Returns the rows written. The caller commits."""
    written = 0
    with conn.cursor() as cur:
        for r in RELATIONS:
            evidence = {"factor": r.key, "version": VERSION, "claim": r.claim, "experiment_planned": r.experiment, "registered_by": "stats-v1"}
            cur.execute(
                "INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence, previous_id) "
                "VALUES (%s, %s, 'DESCRIPTIVE', %s, 'system', NULL, %s, %s, NULL) ON CONFLICT (factor, version) WHERE previous_id IS NULL DO NOTHING",
                (r.key, VERSION, at, REASON, Jsonb(evidence)),
            )
            written += max(0, cur.rowcount)
    return written


__all__ = ["BLOCKED_DRIVERS", "RELATIONS", "VERSION", "Relation", "descriptive_blocks", "package_path", "register_relations", "under"]
