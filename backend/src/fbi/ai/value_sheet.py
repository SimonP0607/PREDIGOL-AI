"""One sheet of what each AI process produces per dollar, with the same rules for all (plan RP-12.1, finding H27): ``value-sheet-v1``.

WHY. The cost reports say where the money goes (``capability-costs-v1``, ``cost-paths``); the comparison of the review says what its verdicts
did after the match (``r4-compare-v1``). Nobody had put the two side by side per process, so a decision about what to reduce had to be taken
by looking at the money alone: the production review spent US$ 26.20 of 46.43 in seven days (56 %) and approved 5 of 601, the web search
reached 269 of 692 matches, and neither number says what each dollar bought. This module writes, per process and BEFORE any reading of the
figures, its useful unit (``PROCESSES``), and then fills one line for each window (7 and 30 days in the script):

    cost            the capability keys of the process, added from ``capability-costs-v1`` (so the sheet reconciles with the month's ledger)
    units           what the process produced (a selection reviewed, a match researched, a chronicle written)
    useful          the part of the units that did something checkable (a verdict that changed the rules' decision, a CONFIRMED fact, a valid chronicle)
    per unit        dollars per unit and per useful unit, with the interval of the useful share (Wilson, ``fbi.ai.intervals``) where there is a sample
    review          for the production review only: whether what it REJECTED did worse than what it let through (outcome at a flat stake of 1,
                    from ``r4-compare-v1``), with the cases and the interval; a rate without its cases is never printed

A process whose useful unit cannot be measured today is marked ``sin_unidad_util`` with the reason: it is a result of the sheet, not a gap to
hide. Capabilities no process claims go to ``otros`` so the total always equals the ledger's.

It INFORMS and decides nothing (``"decides": False``): it turns nothing off, moves no budget (the redistribution of decision D1 is taken
afterwards, by the owner, with this sheet in view), changes no route, model, switch or threshold. Pure: no database and no clock (the readers
are ``fbi.ai.value_sheet_readers``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from fbi.ai.intervals import Proportion

VERSION: Final = "value-sheet-v1"
NO_USEFUL_UNIT: Final = "sin_unidad_util"
CENT: Final = Decimal("0.01")
MILLI: Final = Decimal("0.001")


@dataclass(frozen=True, slots=True)
class Process:
    """A process of the AI layer and the unit that says what it produced, written before the figures are read."""

    key: str
    title: str
    capabilities: tuple[str, ...]
    unit: str
    useful: str | None
    why_not_useful: str | None = None


PROCESSES: Final[tuple[Process, ...]] = (
    Process("revision_candidatos", "Revisión de candidatos (review-v2)", ("production.review",),
            "selección revisada por el modelo antes del saque (motor llm)",
            "revisión cuyo veredicto cambió el de las reglas (una rechaza y la otra no)"),
    Process("busqueda_web", "Búsqueda web y extracción", ("research.search", "research.extraction"),
            "partido con al menos un hecho de la web en la ventana", "hecho de la web en estado CONFIRMED"),
    Process("lectura_partido", "Lectura del partido (brief)", ("production.brief",), "partido con lectura escrita", None,
            "su efecto sobre la decisión no se guarda por separado: no hay forma de saber qué decisión cambió"),
    Process("deliberacion_sombra", "Deliberación de la sombra (agentes y consejo)",
            ("deliberation.match_agent", "deliberation.stats_agent", "deliberation.player_agent", "deliberation.council",
             "deliberation.escalation"), "lectura de un agente", None,
            "es una sombra: sus lecturas se comparan con el cierre en RP-12.2 y RP-8.1, no por unidad"),
    Process("cronicas", "Crónicas de usuario", ("chronicles.chronicle", "chronicle_v4"), "crónica escrita por el modelo",
            "crónica válida (estado ok o partial)"),
    Process("aprendizaje_y_postmortem", "Aprendizaje y post-mortem", ("rest.learning", "rest.postmortem"), "nota o post-mortem escrito", None,
            "sin veredicto de qué cambió cada nota hasta el ciclo de aprendizaje de RP-8.1"),
    Process("banco_de_pruebas", "Banco de pruebas (LAB)", ("rest.lab",), "caso del banco", None,
            "es una prueba de los prompts, no produce una decisión"),
)
"""The useful unit of each process. Changing a line is a new version of the sheet (``value-sheet-v2``), never an edit to favour a process."""


@dataclass(frozen=True, slots=True)
class Counts:
    """What the readers counted in one window, from the tables (``fbi.ai.value_sheet_readers``)."""

    fixtures: int = 0
    fixtures_with_web_facts: int = 0
    web_facts: int = 0
    web_facts_confirmed: int = 0
    web_facts_probable: int = 0
    chronicles_written: int = 0
    chronicles_valid: int = 0


def _usd(x: Decimal) -> str:
    return str(x.quantize(CENT, rounding=ROUND_HALF_UP))


def _per(usd: Decimal, n: int) -> str | None:
    return None if n <= 0 else str((usd / n).quantize(MILLI, rounding=ROUND_HALF_UP))


def _dec(x: Any) -> Decimal:
    return Decimal(str(x)) if x not in (None, "") else Decimal(0)


def _caps(cap_report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c["key"]): dict(c) for c in cap_report.get("capabilities", [])}


def _review_units(r4: Mapping[str, Any]) -> tuple[int, int, Proportion]:
    """(selections the model reviewed, selections where it and the rules differ on the REJECT, the rate of the second over the common ones)."""
    llm = (r4.get("engines") or {}).get("llm") or {}
    pair = (r4.get("pairs") or {}).get("rules_vs_llm") or {}
    common = int(pair.get("common") or 0)
    same = pair.get("agree_on_reject_or_not") or {}
    changed = max(0, common - int(same.get("counted") or 0)) if common else 0
    return int(llm.get("selections") or 0), changed, Proportion(changed, common)


def _review_outcome(r4: Mapping[str, Any]) -> dict[str, Any]:
    """Did what the review rejected do worse than what it let through? Cases and intervals as ``r4-compare-v1`` gives them; no verdict here."""
    llm = (r4.get("engines") or {}).get("llm") or {}
    kept, rejected = llm.get("kept") or {}, llm.get("rejected") or {}
    return {"kept": kept, "rejected": rejected,
            "reading": "una muestra pequeña de liquidadas no decide: cada tasa va con sus casos y su intervalo",
            "rejected_settled": int(rejected.get("settled") or 0), "kept_settled": int(kept.get("settled") or 0)}


def _line(p: Process, usd: Decimal, calls: int, units: int, useful: int | None, share: Proportion | None, extra: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": p.key, "title": p.title, "capabilities": list(p.capabilities), "calls": calls, "cost_usd": _usd(usd),
        "unit": p.unit, "units": units, "cost_per_unit_usd": _per(usd, units),
        "useful_unit": p.useful, "useful": useful, "cost_per_useful_usd": None if useful is None else _per(usd, useful),
        "useful_share": None if share is None else share.as_json(),
    }
    if p.useful is None:
        out["state"] = NO_USEFUL_UNIT
        out["why_not_useful"] = p.why_not_useful
    else:
        out["state"] = "medido" if units else "sin_muestra"
    out.update(extra)
    return out


def sheet(cap_report: Mapping[str, Any], r4: Mapping[str, Any], counts: Counts, *, days: int) -> dict[str, Any]:
    """The sheet of one window of ``days`` days from the capability report, the review comparison and the counts of the readers."""
    caps = _caps(cap_report)
    claimed: set[str] = set()
    lines: list[dict[str, Any]] = []
    for p in PROCESSES:
        usd = Decimal(0)
        calls = 0
        for k in p.capabilities:
            c = caps.get(k)
            if c is None:
                continue
            claimed.add(k)
            usd += _dec(c.get("spent_usd"))
            calls += int(c.get("calls") or 0)
        extra: dict[str, Any] = {}
        units: int
        useful: int | None
        share: Proportion | None = None
        if p.key == "revision_candidatos":
            units, useful, share = _review_units(r4)
            extra["rejected_vs_kept"] = _review_outcome(r4)
        elif p.key == "busqueda_web":
            units, useful = counts.fixtures_with_web_facts, counts.web_facts_confirmed
            share = Proportion(counts.web_facts_confirmed, counts.web_facts)
            extra["fixtures_in_window"] = counts.fixtures
            extra["fixtures_covered"] = Proportion(counts.fixtures_with_web_facts, counts.fixtures).as_json()
            extra["web_facts"] = {"all": counts.web_facts, "confirmed": counts.web_facts_confirmed, "probable": counts.web_facts_probable}
        elif p.key == "cronicas":
            units, useful = counts.chronicles_written, counts.chronicles_valid
            share = Proportion(counts.chronicles_valid, counts.chronicles_written)
        else:
            units = int(sum(int((caps.get(k) or {}).get("calls") or 0) for k in p.capabilities))
            useful = None
        lines.append(_line(p, usd, calls, units, useful, share, extra))
    others = [c for k, c in caps.items() if k not in claimed]
    other_usd = sum((_dec(c.get("spent_usd")) for c in others), Decimal(0))
    total = sum((Decimal(x["cost_usd"]) for x in lines), Decimal(0)) + other_usd
    ledger = _dec((cap_report.get("total") or {}).get("ledger_usd"))
    unattributed = _dec((cap_report.get("unattributed") or {}).get("usd"))
    return {
        "version": VERSION, "days": days, "decides": False, "processes": lines,
        "otros": {"capabilities": sorted(others_k for others_k in caps if others_k not in claimed), "cost_usd": _usd(other_usd)},
        "sin_capacidad_usd": _usd(unattributed),
        "total": {"sheet_usd": _usd(total + unattributed), "ledger_usd": _usd(ledger),
                  "reconciles": abs(total + unattributed - ledger) < CENT if ledger else None},
        "without_useful_unit": [x["key"] for x in lines if x["state"] == NO_USEFUL_UNIT],
    }


def lines(doc: Mapping[str, Any]) -> list[str]:
    """The sheet as the lines a person reads (Spanish)."""
    out = [f"Hoja de valor por proceso · {doc['version']} · ventana de {doc['days']} días · no decide nada"]
    for x in doc["processes"]:
        head = f"- {x['title']}: US$ {x['cost_usd']} en {x['calls']} llamadas"
        if x["state"] == NO_USEFUL_UNIT:
            out.append(f"{head}; {x['units']} {x['unit']}; sin unidad útil medible: {x['why_not_useful']}")
            continue
        share = x["useful_share"]
        rate = "sin casos" if not share or not share["cases"] else f"{share['counted']}/{share['cases']} · {share['pct']} % · IC95 {share['ci95_wilson_pct'][0]}-{share['ci95_wilson_pct'][1]} %"
        out.append(f"{head}; {x['units']} {x['unit']}; útiles ({x['useful_unit']}): {x['useful']} ({rate}); "
                   f"US$ {x['cost_per_unit_usd'] or 'n/d'} por unidad y US$ {x['cost_per_useful_usd'] or 'n/d'} por unidad útil")
        rv = x.get("rejected_vs_kept")
        if rv:
            out.append(f"    lo rechazado: {rv['rejected_settled']} liquidadas; lo dejado pasar: {rv['kept_settled']} liquidadas (con su intervalo en el JSON)")
    t = doc["total"]
    out.append(f"Total de la hoja US$ {t['sheet_usd']} frente al libro US$ {t['ledger_usd']} · concilia: {t['reconciles']}")
    return out


__all__ = ["NO_USEFUL_UNIT", "PROCESSES", "VERSION", "Counts", "Process", "lines", "sheet"]
