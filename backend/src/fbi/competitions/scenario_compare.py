"""What ``stakes-v5`` says about a side, against what the scenarios engine proves (plan 2026, AD-B02, IA-082), in SHADOW and read-only.

``stakes-v5`` (``fbi.ai.context.stakes``) is the block ``stakes`` of the AI packet: the zone the provider's description gives the side's
row, the distance to the zones above and below, ``settled`` and a ``pressure`` (title, europe, relegation, promotion, playoff, mid_table,
settled, unknown) that the chronicles turn into words ("no tiene nada en juego en la tabla"). This module says, for one side, which of
those words the engine's reading contradicts:

* ``cerrado_pero_abierto`` - stakes-v5 says nothing is at stake (``settled``) and the engine shows an objective of a coded zone that is
  still mathematically open for the team: the sentence is false, and provably so.
* ``cerrado_pero_condicional`` - the same, but what is open is only a zone the regulation makes conditional (a continental place that
  depends on a cup): the sentence is not proved and may be false.
* ``cerrado_no_demostrable`` - every coded objective is decided, but ``SIN_OBJETIVO_DEMOSTRADO`` cannot be proved (a gap in the coded
  regulation, a table not computed): the sentence has no backing.
* ``presion_sobre_decidido`` - stakes-v5 says the side fights for a zone (title, international places, relegation, promotion,
  play-off) whose every objective in the coded rules is already decided for it.
* ``zona_inexistente`` - stakes-v5 names a kind of zone the coded regulation of the side's tables does not have (a "promotion" in a
  league that sends nobody up). When the regulation leaves that kind out on purpose (a gap: the UEFA places of a league), it is
  ``no_verificable`` instead.

Pure: two documents in, a list out. Nothing here reaches a reader.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

VERSION: Final = "stakes-compare-v1"

KINDS: Final[dict[str, frozenset[str]]] = {
    "title": frozenset({"champion", "title_playoff"}),
    "europe": frozenset({"continental"}),
    "relegation": frozenset({"relegation", "relegation_playoff"}),
    "promotion": frozenset({"promotion"}),
    "playoff": frozenset({"next_phase", "playoff_place"}),
}
"""stakes-v5's kinds of zone, and the coded zone kinds each one means."""

GAP_OF: Final[dict[str, str]] = {"title": "format", "europe": "continental", "relegation": "relegation", "promotion": "promotion",
                                 "playoff": "playoff"}
"""The topic of a regulation's ``gaps`` that leaves each kind uncoded: a kind the rules do not code because of a gap is not
"inexistent", it is not verifiable."""

STRONG: Final = frozenset({"cerrado_pero_abierto", "presion_sobre_decidido", "zona_inexistente"})
"""The contradictions the engine proves (the others say the sentence is not proved)."""


def _objectives(reading: Mapping[str, Any], team: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in reading.get("tables", []):
        for row in t["teams"]:
            if row["team"] == team:
                out.extend(row["objetivos"])
    return out


def compare_side(stakes: Mapping[str, Any] | None, reading: Mapping[str, Any], team: int) -> dict[str, Any]:
    """The contradictions between a side's stakes-v5 block and the engine's reading of its competition (see the module)."""
    if not stakes:
        return {"team": team, "status": "sin_stakes", "contradicciones": []}
    if reading.get("status") != "ok":
        return {"team": team, "status": str(reading.get("status")), "contradicciones": []}
    objectives = _objectives(reading, team)
    if not objectives:
        return {"team": team, "status": "sin_tabla", "contradicciones": []}
    pressure = stakes.get("pressure")
    settled = pressure == "settled" or stakes.get("settled") is True
    present = {o["zona"] for o in objectives}
    gaps = {g.get("topic") for g in (reading.get("rules") or {}).get("gaps") or []}
    found: list[dict[str, Any]] = []
    if settled:
        open_firm = [o for o in objectives if o["estado"] == "abierto" and not o["condicional"]]
        open_conditional = [o for o in objectives if o["estado"] == "abierto" and o["condicional"]]
        fact = (reading.get("teams") or {}).get(str(team)) or {}
        if open_firm:
            found.append({"tipo": "cerrado_pero_abierto", "objetivos": [o["objetivo"] for o in open_firm],
                          "probabilidad": [o["probabilidad"] for o in open_firm]})
        elif open_conditional:
            found.append({"tipo": "cerrado_pero_condicional", "objetivos": [o["objetivo"] for o in open_conditional]})
        elif not fact.get("demostrado"):
            found.append({"tipo": "cerrado_no_demostrable", "motivos": list(fact.get("motivos") or [])[:6]})
    if pressure in KINDS:
        mine = [o for o in objectives if o["zona"] in KINDS[str(pressure)]]
        if not mine:
            kind = "no_verificable" if GAP_OF[str(pressure)] in gaps else "zona_inexistente"
            found.append({"tipo": kind, "dice": pressure, "zonas_codificadas": sorted(present)})
        elif all(o["decidido"]["demostrado"] for o in mine):
            found.append({"tipo": "presion_sobre_decidido", "dice": pressure,
                          "estados": [f"{o['objetivo']}:{o['estado']}" for o in mine]})
    zone = stakes.get("zone")
    if zone in KINDS and zone != pressure and not any(o["zona"] in KINDS[str(zone)] for o in objectives):
        kind = "no_verificable" if GAP_OF[str(zone)] in gaps else "zona_inexistente"
        found.append({"tipo": kind, "dice": zone, "zonas_codificadas": sorted(present)})
    return {"team": team, "status": "ok", "pressure": pressure, "settled": settled, "contradicciones": found,
            "contradice": any(f["tipo"] in STRONG for f in found)}
