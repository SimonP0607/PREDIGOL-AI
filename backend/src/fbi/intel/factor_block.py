"""The factors of the structured-context block, each with a status in the registry from the start (plan RP-4.5, finding H18).

The registry (``fbi.intel.factors``) keeps the decision about each context factor; no row means DESCRIPTIVE. The packet's blocks (the head-to-head, the
scenarios, the tactics, rest and congestion) are its ``CATALOGUE``. The facts of the structured-context block (RP-4.1 to RP-4.4) are not a block of the
packet: they are typed facts in ``ai.evidence``, and the registry also needs to say what each of them is, so that no sentence and no decision rests on one
that nobody has tested. ``BLOCK`` lists them and ``register`` gives each its first row, DESCRIPTIVE, written by the system (idempotent), so that
``coverage`` can say that every factor of the block has a status as a row and not only by default.

The versions are the ones of the code that computes each fact (``fbi.competitions.stakes_facts.VERSION``, ``fbi.competitions.calendar_facts.VERSION``); they
are written here as text, not imported, so the registry reads none of the modules that compute (a test holds the text equal to the module's). A fact that a
later piece adds (the availability of a player, the referee, the coach, the usual formation, the minutes of the starters) is added to ``BLOCK`` in that piece,
with its version, and its test says so.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from fbi.intel import factors
from fbi.intel.factors import Factor

STAKES: Final = "stakes_facts"
CALENDAR_FACTS: Final = "calendar_facts"

BLOCK: Final[tuple[Factor, ...]] = (
    Factor(STAKES, "stakes-facts-v1", ("evidence", "stakes"), False, "Qué se juega cada equipo",
           "que lo que cada equipo se juega en la tabla (título, ascenso, copas, descenso, nada) cambia el resultado más allá de lo que ya dicen el modelo "
           "y el mercado"),
    Factor(CALENDAR_FACTS, "calendar-facts-v1", ("evidence", "schedule"), False, "Descanso, carga y próximo partido, dichos como hechos",
           "que los días desde el último partido, los partidos de las dos últimas semanas y la cercanía del siguiente cambian el resultado más allá de lo que "
           "ya dicen el modelo y el mercado"),
)
BY_KEY: Final[dict[str, Factor]] = {f.key: f for f in BLOCK}
REASON: Final = "Registrado como DESCRIPTIVO al cargar el bloque de contexto estructurado (RP-4.5): nadie ha probado el factor, no puede ser razón de nada."


def register(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """Give every factor of ``BLOCK`` its first row - DESCRIPTIVE, ``decided_by`` system, no person - unless the registry already has a decision about it at its
    version. Idempotent: the second call writes nothing. Returns the rows written. The caller commits."""
    written = 0
    with conn.cursor() as cur:
        for f in BLOCK:
            evidence = {"factor": f.key, "version": f.version, "claim": f.claim, "registered_by": "factor-block-v1"}
            cur.execute(
                "INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence, previous_id) "
                "VALUES (%s, %s, 'DESCRIPTIVE', %s, 'system', NULL, %s, %s, NULL) ON CONFLICT (factor, version) WHERE previous_id IS NULL DO NOTHING",
                (f.key, f.version, at, REASON, Jsonb(evidence)))
            written += max(0, cur.rowcount)
    return written


def coverage(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    """The status of every factor of the context (the packet's catalogue and ``BLOCK``) at its version: its row's, or DESCRIPTIVE by default when it has none
    (``has_row`` says which). Every factor has a status; ``without_row`` lists the typed facts that ``register`` has not yet written, which is what a load
    must leave empty. The packet's four blocks are not seeded: a first row would change the decision the packet shows for them."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ON (factor, version) factor, version, status FROM intel.context_factors WHERE decided_at <= %s "
                    "ORDER BY factor, version, id DESC", (at,))
        found = {(str(r[0]), str(r[1])): str(r[2]) for r in cur.fetchall()}
    rows = []
    for f in (*factors.CATALOGUE, *BLOCK):
        status = found.get((f.key, f.version))
        rows.append({"factor": f.key, "version": f.version, "status": status or factors.DESCRIPTIVE, "has_row": status is not None,
                     "usable": factors.usable_as_signal(status)})
    return {"factors": len(rows), "with_status": len(rows),
            "without_row": [r["factor"] for r in rows if not r["has_row"] and r["factor"] in BY_KEY],
            "by_status": {s: sum(1 for r in rows if r["status"] == s) for s in factors.STATUSES}, "rows": rows}


__all__ = ["BLOCK", "BY_KEY", "CALENDAR_FACTS", "REASON", "STAKES", "coverage", "register"]
