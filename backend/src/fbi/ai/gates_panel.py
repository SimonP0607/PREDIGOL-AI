"""The panel of the gates of the plan and the value per dollar of each component of the AI (IA-050; INT-T03 of the Plan Maestro de PrediGol
Intelligence 2026): ONE read-only place with every gate - its cases, its interval, its threshold, its verdict, the day it can be judged and where
every figure comes from - and what each component of the AI costs, with a value per dollar only where a benefit was measured.

THE RULE: no pending gate is shown as approved. ``PASA`` appears only where a pass is ON FILE (``on_file_pass``):

    a live gate          the newest row of that gate in ``ai.feature_gates`` says it passed (``fbi.ai.gates``: the newest row decides). An
                         evaluator that says PASA over a window nobody recorded is PENDIENTE POR ACCIONES MANUALES here - without the row the
                         system does not treat it as passed (``gates.research_mode``) - and the evaluator's own word is kept beside it
    the AI layer's gate  the newest report of ``ai.shadow_reports`` (``ai-gate-v2``, written every day by the cycle) of ``combined``, the one
                         ``fbi.ai.gating`` reads
    a LAB experiment     its frozen verdict (``LAB``), carried with the fingerprint of its protocol (``fbi.research.protocol``)

A gate whose code does not exist yet is PENDIENTE POR DEPENDENCIAS, and P1 has no evidence of its own: it is never more than pending.
``violations`` checks the rule over a whole panel and ``scripts/ia_gates_panel.py`` exits non-zero if it ever fails.

THE WORDS are the gates' own: PASA, NO PASA, PENDIENTE POR TIEMPO REAL and PENDIENTE POR ACCIONES MANUALES (``fbi.ai.gate_b``); the LAB's
RECHAZA and PENDIENTE POR MUESTRA (the protocols of ``fbi.research.protocol``); and PENDIENTE POR DEPENDENCIAS for a gate whose pieces are not
built.

THE VALUE PER DOLLAR. The cost of each component is ``fbi.ai.cost_paths`` (``cost-paths-v1``) over the window the caller read, the ledger's to the
cent. Its benefit is taken only from a report that measures one: the AI's own prospective test (``fbi.ai.shadow``, ``ai-gate-v2``) says, per
engine, whether what a review rejected did worse than what it kept - ROI(kept) - ROI(rejected) at a flat stake of 1, with its bootstrap standard
error over matches - and G-EVENTOS (IA-045) whether the web's claims came before the price. A value per dollar is computed only where that benefit
is DEMONSTRATED (the engine's ``ai-gate-v2`` says ``pass``): what the review adds, at a flat stake of 1 per kept selection, over a random veto that
rejected the same share - ``(1 - r) * r * (ROI(kept) - ROI(rejected))`` per candidate judged, ``r`` the share rejected - over the cost of judging one
candidate. Everywhere else it says why there is none: ``no demostrado``, ``pendiente por muestra`` or ``sin medir``.

It INFORMS and decides nothing (``"decides": False``): it records nothing, switches nothing and changes no threshold, gate or verdict. Pure: no
database and no clock (the readers are ``fbi.ai.gates_panel_readers``; the cost is read by ``scripts/ia_gates_panel.py``)."""

from __future__ import annotations

import functools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from fbi.ai.calendar import local_day
from fbi.ai.contracts.mcp import family_of
from fbi.ai.cost_paths import LABELS as PATH_LABELS
from fbi.ai.gates import GATES
from fbi.ai.gates import NOT_GATES as RECORDS
from fbi.ai.intervals import Z95, Proportion
from fbi.research import protocol

VERSION: Final = "gates-panel-v1"
Json = dict[str, Any]

PASS: Final = "PASA"
FAIL: Final = "NO PASA"
PENDING_TIME: Final = "PENDIENTE POR TIEMPO REAL"
PENDING_ACTIONS: Final = "PENDIENTE POR ACCIONES MANUALES"
REJECTS: Final = "RECHAZA"
PENDING_SAMPLE: Final = "PENDIENTE POR MUESTRA"
PENDING_DEPENDENCIES: Final = "PENDIENTE POR DEPENDENCIAS"
STATUSES: Final[tuple[str, ...]] = (PASS, FAIL, REJECTS, PENDING_ACTIONS, PENDING_TIME, PENDING_SAMPLE, PENDING_DEPENDENCIES)
"""Every status an entry can show. Only PASA reads as approved."""
PENDING: Final = frozenset({PENDING_TIME, PENDING_ACTIONS, PENDING_SAMPLE, PENDING_DEPENDENCIES})

Kind = Literal["vivo", "registrado", "lab", "muestra", "dependencias"]
"""``vivo``: an evaluator of the code and the rows it records; ``registrado``: a verdict on file only; ``lab``: a frozen LAB verdict;
``muestra``: P1, counts against a threshold; ``dependencias``: its pieces are not built yet."""

NOT_GATES: Final = frozenset(RECORDS)
"""Rows of ``ai.feature_gates`` that are records, not gates (``fbi.ai.gates.NOT_GATES``): listed, never judged."""
SHADOW_REPORT_ENGINES: Final[tuple[str, ...]] = ("combined", "llm", "rules", "ma-v1", "ma-v1-h", "cs-v1")
"""The engines ``ai-gate-v2`` reports on (``fbi.ai.shadow.ENGINES``), in the order the panel shows them. ``combined`` is the one that gates
what users see (``fbi.ai.gating``)."""
GATE_V2_WORDS: Final[dict[str, str]] = {"pass": PASS, "fail": FAIL, "insufficient": PENDING_TIME}
"""``ai-gate-v2``'s verdicts in the gates' words: ``insufficient`` is a sample still too small, which only time brings."""
P1_DAYS: Final = 30
P1_SELECTIONS: Final = 300
"""P1 (plan, section 8): at least 30 days of shadow and 300 selections per family, counted from the configuration under evaluation."""
P1_ENGINES: Final[tuple[str, ...]] = ("ma-v1", "ma-v1-h", "cs-v1")


def _iso(x: date | datetime | None) -> str | None:
    return None if x is None else x.isoformat()


def _dec(x: Any) -> Decimal | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        return Decimal(str(x))
    except InvalidOperation:
        return None


def _day(x: Any) -> date | None:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str) and x:
        try:
            return date.fromisoformat(x[:10])
        except ValueError:
            return None
    return None


def _m(x: Mapping[str, Any] | None, key: str) -> Mapping[str, Any]:
    """``x[key]`` when it is a mapping, else an empty one (a report's nested blocks, read defensively)."""
    v = None if x is None else x.get(key)
    return v if isinstance(v, Mapping) else {}


# ── what the panel shows ───────────────────────────────────────────────────────────────────────────────────────


def figure(label: str, value: str | None, *, source: str, cases: int | None = None, counted: int | None = None,
           ci95: Sequence[str | None] | None = None, ci_method: str | None = None, threshold: str | None = None,
           relation: str | None = None, verdict: str | None = None, note: str | None = None) -> Json:
    """One figure, always with the same keys: what it is, its value, its cases, its interval, the threshold it is read against, the verdict of
    the check it belongs to and where it comes from."""
    return {"label": label, "value": value, "cases": cases, "counted": counted, "ci95": None if ci95 is None else list(ci95),
            "ci_method": ci_method, "threshold": threshold, "interval_vs_threshold": relation, "verdict": verdict, "source": source,
            "note": note}


def interval_figure(label: str, i: Mapping[str, Any], *, source: str, verdict: str | None = None, note: str | None = None) -> Json:
    """A rate as ``fbi.ai.intervals.Proportion.as_json`` gives it: k of n, its 95 % Wilson interval and the threshold of its check."""
    kind = i.get("threshold_kind")
    threshold = None if i.get("threshold_pct") is None else f"{'≤' if kind == 'max' else '≥'} {i['threshold_pct']} %"
    w = i.get("ci95_wilson_pct")
    return figure(label, None if i.get("pct") is None else f"{i['pct']} %", source=source, cases=i.get("cases"), counted=i.get("counted"),
                  ci95=None if not w else (w[0], w[1]), ci_method="Wilson" if w else None, threshold=threshold,
                  relation=i.get("interval_vs_threshold"), verdict=verdict, note=note)


@dataclass(frozen=True, slots=True)
class Spec:
    """A gate of the plan as the plan writes it: its name, its piece, its rule and what it waits for."""

    id: str
    name: str
    piece: str
    kind: Kind
    threshold: str
    rejects_if: str | None = None
    code: str | None = None
    depends_on: tuple[str, ...] = ()
    source: str = ""
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Row:
    """The newest row of a gate in ``ai.feature_gates`` (the newest row decides: ``ORDER BY at DESC, id DESC``)."""

    id: int
    gate: str
    at: datetime
    passed: bool
    decided_by: str | None = None
    evidence_hash: str | None = None
    verdict: str | None = None
    """``evidence.verdict`` when the evidence is a whole report (Gate A, Gate B, research v2)."""
    window: Mapping[str, Any] | None = None
    models: tuple[str, ...] | None = None
    kind: str | None = None

    def as_json(self) -> Json:
        return {"table": "ai.feature_gates", "gate": self.gate, "id": self.id, "at": self.at.isoformat(), "passed": self.passed,
                "decided_by": self.decided_by, "evidence_hash": self.evidence_hash, "verdict": self.verdict,
                "window": None if self.window is None else dict(self.window), "models": None if self.models is None else list(self.models)}


def row_of(r: Mapping[str, Any]) -> Row:
    models = r.get("models")
    window = r.get("evidence_window")
    return Row(int(r["id"]), str(r["gate"]), r["at"], bool(r["passed"]), r.get("decided_by"), r.get("evidence_hash"), r.get("verdict"),
               window if isinstance(window, Mapping) else None,
               tuple(str(m) for m in models) if isinstance(models, list) and models else None, r.get("kind"))


# ── the frozen verdicts of the LAB ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LabRow:
    """One cell of a LAB result, as its result file writes it."""

    segment: str
    n: int
    blocks: int
    estimate: float
    ci95: tuple[float, float]
    mde: float | None = None
    verdict: str | None = None
    """The cell's own verdict where the protocol judges cells (A02 by market, A09 by cell); None where it judges the whole (B09)."""
    why: tuple[str, ...] = ()
    weight: tuple[float, tuple[float, float]] | None = None
    """A09: the challenger's weight against the market in the pool, with its 95 % interval."""
    facts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LabRecord:
    """A closed LAB verdict: a fact, frozen here with the fingerprint of the protocol it was run under and the file it comes from."""

    key: str
    code: str
    title: str
    version: str
    fingerprint: str
    evaluated: str
    evaluated_on: date
    verdict: str
    metric: str
    estimate_unit: str
    n_unit: str
    blocks_unit: str
    rule: str
    result: str
    doc: str
    rows: tuple[LabRow, ...]
    notes: tuple[str, ...] = ()

    @property
    def registered(self) -> bool:
        """The protocol it carries is the one registered in ``fbi.research.protocol``: same version, same fingerprint."""
        p = protocol.PROTOCOLS.get(self.key)
        return p is not None and p.version == self.version and protocol.fingerprint(p) == self.fingerprint

    def as_json(self) -> Json:
        return {"key": self.key, "code": self.code, "title": self.title, "protocol": {"version": self.version, "fingerprint": self.fingerprint,
                                                                                   "framework": protocol.VERSION, "registered": self.registered},
                "evaluated": self.evaluated, "evaluated_on": self.evaluated_on.isoformat(), "verdict": self.verdict, "metric": self.metric,
                "estimate_unit": self.estimate_unit, "rule": self.rule, "result": self.result, "doc": self.doc, "notes": list(self.notes),
                "rows": [{"segment": r.segment, "n": r.n, "n_unit": self.n_unit, "blocks": r.blocks, "blocks_unit": self.blocks_unit,
                          "estimate": r.estimate, "ci95": list(r.ci95), "mde": r.mde, "verdict": r.verdict, "why": list(r.why),
                          "weight": None if r.weight is None else {"w": r.weight[0], "ci95": list(r.weight[1])}, "facts": list(r.facts)}
                         for r in self.rows]}

    def figures(self) -> list[Json]:
        out: list[Json] = []
        digits = 3 if self.estimate_unit == "pp" else 4
        for r in self.rows:
            ci = (f"{r.ci95[0]:+.{digits}f}", f"{r.ci95[1]:+.{digits}f}")
            note = "; ".join([*r.why, *r.facts]) or None
            if r.weight is not None:
                w, (lo, hi) = r.weight
                note = "; ".join(x for x in (f"peso frente al mercado {w:+.3f} [{lo:+.3f}; {hi:+.3f}]", note) if x)
            out.append(figure(f"{self.key} · {r.segment}", f"{r.estimate:+.{digits}f} {self.estimate_unit}", source=self.result, cases=r.n,
                              ci95=ci, ci_method=f"bootstrap de {r.blocks} {self.blocks_unit}", verdict=r.verdict, note=note))
        return out


LAB_A02: Final = LabRecord(
    key="INT-A02", code="IA-036", title="Calibración coherente multiclase", version="proto-int-a02-v1",
    fingerprint="2a1cdb3ec31a6b5075010a989e6205bf60bc699c54891a62ac861ad0fd69ae6d",
    evaluated="2026-11-11T05:52:31+00:00 (una sola evaluación)", evaluated_on=date(2026, 11, 11), verdict=REJECTS,
    metric="diferencia pareada del log loss multiclase, coherente - reescalada (media de los días; negativa = mejor la coherente)",
    estimate_unit="nats", n_unit="partidos-mercado", blocks_unit="días",
    rule="suma 1 en el 100 %; límite superior del IC95 de la diferencia ≤ 0; ningún ECE por resultado peor en más de 0,005",
    result="backend/docs/owner/lab/IA_036/resultado.json", doc="backend/docs/owner/IA_036_CALIBRACION_COHERENTE.md",
    rows=(
        LabRow("1X2", 5796, 31, 0.002497, (-5.8e-05, 0.005325), 0.003921, REJECTS,
               ("límite superior del IC95 de la diferencia = 0.005325 > 0", "ECE de Home empeora 0.0061 > 0,005",
                "ECE de Draw empeora 0.0057 > 0,005"), facts=("suma 1 en 5796 de 5796",)),
        LabRow("OU", 2602, 26, 0.004548, (0.000208, 0.01075), 0.007958, REJECTS, ("límite superior del IC95 de la diferencia = 0.01075 > 0",),
               facts=("suma 1 en 2602 de 2602",)),
        LabRow("BTTS", 2602, 26, 0.004425, (-0.002739, 0.014624), 0.012975, REJECTS,
               ("límite superior del IC95 de la diferencia = 0.014624 > 0",), facts=("suma 1 en 2602 de 2602",)),
    ),
    notes=("Regla de rechazo: la reescalada sigue siendo la cifra coherente y el calibrador coherente queda en el LAB con su motivo.",
           "Contados en partidos distintos, más/menos 2,5 y ambos marcan tendrían 1.308 (< 1.500) y quedarían pendientes por muestra; "
           "la consecuencia es la misma (IA-036)."),
)
LAB_A09: Final = LabRecord(
    key="INT-A09", code="IA-039", title="E4: tiros y xG en los ratings", version="proto-int-a09-v1",
    fingerprint="400778f85de7acdfc59b1d9e265d7f4c4d5fe42abc4abf71cb5785b33604bd36",
    evaluated="2026-11-11 05:32-05:35 UTC (una sola evaluación)", evaluated_on=date(2026, 11, 11), verdict=REJECTS,
    metric="diferencia pareada del log loss, retador - modelo actual (media de los días; negativa = mejor el retador)",
    estimate_unit="nats", n_unit="partidos", blocks_unit="días",
    rule="en al menos un segmento: límite superior del IC95 de la diferencia < 0, límite inferior del IC95 del peso frente al mercado > 0 "
         "y auditoría de fugas limpia",
    result="backend/docs/owner/lab/IA_039/resultado_e4.json", doc="backend/docs/owner/IA_039_E4_TIROS_XG.md",
    rows=(
        LabRow("prioritarias|1X2", 281, 27, -0.002424919229377133, (-0.01848048128460312, 0.014494632945401275), 0.03631605655774285,
               PENDING_SAMPLE, ("281 partidos fuera de muestra < 1500",), (-0.22997402275352224, (-0.845352539846802, 0.2645074655554149))),
        LabRow("prioritarias|OU", 281, 27, -0.012798160828378839, (-0.0289345594096646, 0.0016675627059353885), 0.025949805316697907,
               PENDING_SAMPLE, ("281 partidos fuera de muestra < 1500",), (0.4000393565468295, (-0.5355870928789793, 1.1267027524621862))),
        LabRow("resto|1X2", 2738, 39, 0.006100085697034147, (-0.0006617544827275, 0.012684771161794612), 0.013378822268672416, REJECTS,
               ("el límite superior del IC95 de la diferencia de log loss no es < 0",
                "el límite inferior del IC95 del peso frente al mercado no es > 0"),
               (-0.3779888538309693, (-0.632033041734499, -0.16438600719919774))),
        LabRow("resto|OU", 2738, 39, -0.00941491102413581, (-0.014017248141782762, -0.005309876407141412), 0.01764149885536437, REJECTS,
               ("el límite inferior del IC95 del peso frente al mercado no es > 0",),
               (0.06762012462871907, (-0.19345017720656538, 0.32864455544396426))),
    ),
    notes=("Auditoría de fugas limpia.", "El retador se archiva con su motivo y el modelo activo no cambia (regla de rechazo)."),
)
LAB_B09: Final = LabRecord(
    key="INT-B09", code="IA-045", title="Estudio de eventos: noticia → precio", version="proto-int-b09-v1",
    fingerprint="2b8e49fb115f5cecbcb5e61f52d9ac11d8c8464ce7b3da97af62b3f9382e9232",
    evaluated="2026-11-11 05:19:31-05:19:59 UTC (una sola evaluación)", evaluated_on=date(2026, 11, 11), verdict=REJECTS,
    metric="D: cambio de la probabilidad sin margen del equipo afectado tras el evento menos el de los controles con horas barajadas "
           "(positivo = el precio se movió después de que PrediGol lo supo)",
    estimate_unit="pp", n_unit="eventos", blocks_unit="partidos",
    rule="informe válido con ≥ 200 eventos, intervalo agrupado por partido y controles cerca de 0; se rechaza si en ningún segmento "
         "preregistrado D supera a los controles",
    result="backend/docs/owner/IA_045_ESTUDIO_EVENTOS.md (tabla «Métrica principal y segmentos preregistrados»)",
    doc="backend/docs/owner/IA_045_ESTUDIO_EVENTOS.md",
    rows=(
        LabRow("Global", 3095, 371, 0.000, (-0.035, 0.036), 0.050,
               facts=("cambio tras el evento 0,096 [-0,018; 0,211]", "controles 0,096 [-0,011; 0,203]")),
        LabRow("Fuente: proveedor", 2879, 314, -0.007, (-0.040, 0.027), 0.05),
        LabRow("Fuente: oficial", 12, 5, -0.345, (-1.749, 0.405), 1.5),
        LabRow("Fuente: medio", 71, 30, 0.203, (-0.306, 0.664), 0.7),
        LabRow("Fuente: rumor", 133, 48, 0.073, (-0.251, 0.417), 0.5),
        LabRow("Hecho: baja", 2127, 355, -0.011, (-0.050, 0.027), 0.06),
        LabRow("Hecho: duda", 836, 284, 0.041, (-0.044, 0.131), 0.13),
        LabRow("Hecho: sanción", 132, 100, -0.068, (-0.205, 0.065), 0.19),
        LabRow("Ligas prioritarias", 1316, 145, 0.016, (-0.034, 0.066), 0.07),
        LabRow("Resto de ligas", 1779, 226, -0.011, (-0.060, 0.038), 0.07),
    ),
    notes=("Válido: 3.095 eventos (≥ 200), intervalo agrupado por 371 partidos y controles 0,096 [-0,011; 0,203], que incluye 0.",
           "Ningún segmento tiene el intervalo de D por encima de 0: el mercado ya tenía los hechos y no se propone ninguna fuente nueva.",
           "La diferencia mínima detectable de los segmentos es aproximada (del ancho del intervalo); la global es 0,050 pp."),
)
LAB: Final[dict[str, LabRecord]] = {r.key: r for r in (LAB_A02, LAB_A09, LAB_B09)}
"""The LAB verdicts already closed (ola 1). A new result is a new record here, with its own PR - never an edit of one of these."""
LAB_WEB_SEGMENTS: Final[tuple[str, ...]] = ("Fuente: oficial", "Fuente: medio", "Fuente: rumor")
"""The segments of G-EVENTOS that are claims of Research v2 (the web), as opposed to the provider's absences."""


# ── the gates ──────────────────────────────────────────────────────────────────────────────────────────────────

B_SOURCE: Final = "fbi.ai.gate_b (gate-b-v1), vista previa sin registrar; registro: ai.feature_gates, gate gate_b"
R_SOURCE: Final = "fbi.ai.gate_research, vista previa sin registrar; registro: ai.feature_gates, gate research_v2"
SPECS: Final[tuple[Spec, ...]] = (
    Spec("gate_b", "Gate B", "Plan Maestro IA, sección 24 (gate-b-v1)", "vivo",
         "14 días completos de Bogotá en una sola configuración; ≤ 3 % de salidas inválidas por agente y versión; pasadas finales antes de "
         "T-15; atribución ≥ 95 %; auditoría de fugas limpia; batería en verde; LAB en su sobre; gate de Research v2 en PASA",
         "Falla cualquier comprobación: NO PASA, la sombra sigue y se corrige", source=B_SOURCE),
    Spec("research_v2", "Research v2", "Plan Maestro IA, fase 2 (su propio gate de equivalencia)", "vivo",
         "7 días completos con research v2 en sombra en todas las pasadas; ≥ 95 % de las evidencias de v1 (y de las que dicen quién juega) "
         "con menos búsquedas; ninguna revisión ni decisión cita a v2; auditoría evidence_known limpia. El encendido lo firmas tú",
         "Falla cualquier comprobación: research v2 sigue en sombra y la semana de comparación vuelve a empezar", source=R_SOURCE),
    Spec("gate_a", "Gate A", "Plan Maestro IA, sección 24 (fin de la fase 0)", "registrado",
         "Eficiencia y estabilidad: 7 días completos en una sola configuración, coste dentro del sobre, misma cobertura que la línea base, "
         "veredicto final antes de T-15 y acciones manuales hechas",
         source="ai.feature_gates, gate gate_a (escrito por scripts/ia_gate.py; no se vuelve a evaluar aquí)"),
    Spec("ai_gate_v2", "Puerta de la capa IA (ai-gate-v2)", "Plan Maestro IA (fbi.ai.shadow, fbi.ai.gating)", "registrado",
         "≥ 300 selecciones liquidadas en ≥ 30 días y ≥ 50 rechazadas; ROI(guardadas) - ROI(rechazadas) ≥ 2 errores típicos (bootstrap por "
         "partido); CLV de las guardadas no por debajo del de las rechazadas; Brier de las guardadas no peor que el de todas (+0,002)",
         "Sin PASA en combined, la IA no cambia lo que ven los usuarios (FBI_AI_MODE=enforce no basta)",
         source="ai.shadow_reports, informe más reciente por motor (ai-gate-v2, lo escribe el ciclo cada día)"),
    Spec("g_coh", "G-COH", "INT-A04", "dependencias",
         "Cada mercado suma 1 en el 100 % de los casos; 0 diferencias de más de 0,5 pp entre Match Center, Picks y decisión en 72 h; log loss "
         "del calibrador coherente no peor que el actual (límite superior del IC95 de la diferencia pareada por jornada ≤ 0); ECE por clase "
         "no peor; diferencias de decisión explicadas",
         "Falla el log loss o la calibración: queda la reescalada como cifra coherente y se sigue en el LAB",
         depends_on=("INT-A03 (cifra única en sombra)", "INT-A04 (informe y fila del gate)"), source="plan, sección 8; LAB INT-A02 (IA-036)"),
    Spec("g_precio", "G-PRECIO", "INT-A06", "dependencias",
         "Ninguna decisión sin edad de precio; umbral de edad fijado con la distribución medida",
         "El libro no cubre los candidatos: se informa a Cuotas y sigue la captura actual", code="IA-037",
         depends_on=("INT-A06 (IA-037, abierto): la decisión en sombra aún no guarda la edad del precio",), source="plan, sección 8"),
    Spec("g_fuentes_1", "G-FUENTES 1", "INT-B01", "dependencias", "Los ítems de dominios sin nivel bajan del 20 %", code="IA-040",
         depends_on=("filas del registro de INT-B01 en la sombra: IA-040 las clasificó; entran tras el Gate B y la revisión a mano de las "
                     "filas oficiales",), source="plan, sección 8; medida: IA-040, antes del registro nuevo"),
    Spec("g_fuentes_2", "G-FUENTES 2", "INT-B02", "dependencias",
         "Más afirmaciones oficiales o confirmadas por partido al mismo coste o menor por afirmación útil",
         depends_on=("INT-B01", "INT-B03", "INT-B02 (búsqueda dirigida en Research v2, en sombra)"), source="plan, sección 8"),
    Spec("g_fuentes_3", "G-FUENTES 3", "INT-B04", "dependencias",
         "Enlace noticia → jugador con precisión ≥ 95 % y, como propuesta, ≥ 60 % de las afirmaciones de disponibilidad enlazadas",
         "Precisión por debajo del 95 %: el enlace no alimenta el modelo",
         depends_on=("INT-B04 (enlace en mundo cerrado, en sombra)", "gate de Research v2"), source="plan, sección 8"),
    Spec("g_eventos", "G-EVENTOS", "INT-B09", "lab",
         "Protocolo preregistrado; intervalos agrupados por partido; controles con hechos barajados cercanos a cero. Informa la anticipación, "
         "el valor y el contenido nuevo por liga y tipo de fuente",
         "Si el precio ya tenía los hechos en todos los segmentos, no se propone ninguna fuente nueva", code="IA-045",
         source="LAB INT-B09 (IA-045), veredicto congelado"),
    Spec("g_e4", "G-E4", "INT-A09", "lab",
         "Log loss pareado frente al modelo actual con el IC95 por debajo de 0 y peso en el pool frente al mercado con el IC95 por encima de "
         "0 en al menos un segmento preregistrado; auditoría de fugas limpia",
         "Falla cualquiera: se archiva con su motivo", code="IA-039", source="LAB INT-A09 (IA-039), veredicto congelado"),
    Spec("g_e6", "G-E6", "INT-A08", "dependencias",
         "Log loss pareado frente al modelo actual con el IC95 por debajo de 0 y peso en el pool frente al mercado con el IC95 por encima de "
         "0 en al menos un segmento preregistrado; auditoría de fugas limpia",
         "Falla cualquiera: se archiva con su motivo", code="IA-052",
         depends_on=("INT-A08 (IA-052, abierto)", "su protocolo registrado antes de mirar los datos (fbi.research.protocol)"),
         source="plan, sección 8; fbi.research.protocol"),
    Spec("g_delib", "G-DELIB", "INT-C08", "dependencias",
         "1) desacuerdos entre voces sobre la misma selección, explicables; 2) CLV medio de los candidatos bloqueados menor que el de los "
         "confirmados (prueba unilateral, bootstrap por jornada); 3) ningún caso más permisivo que decision-v1 sin explicación; 4) ≤ 3 % de "
         "inválidas por agente y versión; 5) coste por candidato menor que el de review-v2; 6) (propuesta) el mismo estado en ≥ 95 % de las "
         "repeticiones",
         "Falla la condición 2: la deliberación queda como explicación y no como condición para publicar",
         depends_on=("INT-C03", "INT-C04", "INT-C05", "INT-C06", "INT-C07 (en sombra, tras el Gate B)", "la ventana de P1"),
         source="plan, sección 8"),
    Spec("g_cron", "G-CRON", "INT-D04", "dependencias",
         "Cifras sin referencia = 0; rumores presentados como hechos = 0; errores de hecho por cada 100 frases por debajo de los de la v3 en la "
         "misma muestra, con intervalo; falsos rechazos medidos; coste ≤ US$ 1 al día",
         "La v4 sigue en sombra", depends_on=("INT-D02 (crónica v4 en sombra; no ha empezado)",), source="plan, sección 8"),
    Spec("p1", "P1", "Plan Maestro IA (ventana de evaluación de la sombra)", "muestra",
         f"Al menos {P1_DAYS} días de sombra y {P1_SELECTIONS} selecciones por familia, contados desde la configuración que se evalúe",
         source="ai.pick_reviews (motores de la sombra) desde el ancla de la configuración del Gate B",
         note="P1 no guarda evidencia propia: llegar al umbral solo dice que hay muestra para mirar, nunca que algo pasó"),
    Spec("f_player", "F-Player", "fuera de este plan", "dependencias",
         "Mercado validado, regla de liquidación y precio de referencia para los props de jugador",
         depends_on=("fuera del Plan Maestro de Intelligence 2026",), source="plan, sección 8"),
)
SPEC: Final[dict[str, Spec]] = {s.id: s for s in SPECS}
LAB_OF: Final[dict[str, str]] = {"g_eventos": "INT-B09", "g_e4": "INT-A09", "g_coh": "INT-A02"}
"""The LAB verdict each gate carries: G-EVENTOS and G-E4 ARE their experiment's gate; G-COH carries A02 as one of its inputs."""


def live_status(verdict: str | None, recorded: Row | None, *, error: str | None = None) -> tuple[str, list[str]]:
    """The status of a live gate from its evaluator's verdict now and its newest recorded row. The recorded row wins (it is what the system
    acts on); without one, an evaluator's PASA is PENDIENTE POR ACCIONES MANUALES - a pass nobody recorded is not a pass on file."""
    why: list[str] = []
    if recorded is not None:
        status = PASS if recorded.passed else FAIL
        why.append(f"registrado el {recorded.at.isoformat()} (ai.feature_gates, fila {recorded.id}): {status}")
        if verdict is not None and verdict != status:
            why.append(f"hoy su evaluador dice {verdict} (vista previa, sin registrar)")
        if error is not None:
            why.append(f"la vista previa de hoy no se pudo calcular: {error}")
        return status, why
    if error is not None:
        return PENDING_ACTIONS, [f"no se pudo evaluar: {error}", "sin fila registrada"]
    if verdict is None:
        return PENDING_ACTIONS, ["no hay evaluación ni fila registrada"]
    if verdict == PASS:
        return PENDING_ACTIONS, ["su evaluador da PASA, pero no está registrado: sin la fila, el sistema no lo da por aprobado (--record)"]
    if verdict not in STATUSES:
        return PENDING_ACTIONS, [f"su evaluador dio una palabra desconocida ({verdict!r})"]
    return verdict, ["sin fila registrada: es el veredicto de hoy de su evaluador (vista previa, sin registrar)"]


def _check_numbers(detail: Mapping[str, Any]) -> Json:
    """The plain figures of a check's detail (numbers, words, flags), not its nested lists: what a person reads first."""
    return {k: v for k, v in detail.items() if v is None or isinstance(v, (bool, int, float, str))}


CHECK_SOURCES: Final[dict[str, str]] = {
    "final_deadline": "ai.match_runs, ai.agent_runs y ai.agent_tasks (pasadas final de la sombra)",
    "invalid_outputs": "ai.agent_runs (sombra)", "duplicate_payments": "ai.agent_runs (idem_key)",
    "lab_envelope": "ai.usage del LAB, ai.cycles y la fila lab_plan del dueño", "attribution": "intel.agent_attributions y core.fixtures",
    "leak_audit": "intel.audit_checks", "battery": "ai.feature_gates (battery) y ai.agent_runs", "research_v2": "ai.feature_gates (research_v2)",
}
"""Where each check of Gate B reads its figures (``fbi.ai.gate_b``)."""


def gate_b_checks(report: Mapping[str, Any]) -> list[Json]:
    out: list[Json] = []
    for c in report.get("checks") or []:
        detail = _m(c, "detail")
        figures: list[Json] = []
        if c.get("id") == "invalid_outputs":
            for a in detail.get("agents") or []:
                if isinstance(a, Mapping) and isinstance(a.get("interval"), Mapping):
                    figures.append(interval_figure(f"inválidas de {a.get('agent')} {a.get('agent_version')}", a["interval"],
                                                   source="ai.agent_runs (sombra)",
                                                   note="sin veredicto propio: el veredicto es el del check, que juzga todas las versiones"))
        elif isinstance(detail.get("interval"), Mapping):
            figures.append(interval_figure(str(c.get("title") or c.get("id")), detail["interval"],
                                           source=CHECK_SOURCES.get(str(c.get("id")), "fbi.ai.gate_b"), verdict=c.get("verdict")))
        out.append({"id": c.get("id"), "title": c.get("title"), "verdict": c.get("verdict"), "reasons": list(c.get("reasons") or []),
                    "numbers": _check_numbers(detail), "figures": figures})
    return out


RESEARCH_WORDS: Final[dict[bool | None, str]] = {True: PASS, False: FAIL, None: PENDING_TIME}
"""A check of the research gate is True, False or None (no data to judge it yet: the research gate's only pending is by time)."""


def research_checks(report: Mapping[str, Any]) -> list[Json]:
    out: list[Json] = []
    for c in report.get("checks") or []:
        detail = _m(c, "detail")
        verdict = RESEARCH_WORDS.get(c.get("ok"), PENDING_TIME)
        figures = ([interval_figure(str(c.get("title")), detail["interval"], source="ai.evidence y ai.fixture_passes", verdict=verdict)]
                   if isinstance(detail.get("interval"), Mapping) else [])
        out.append({"id": c.get("id"), "title": c.get("title"), "verdict": verdict, "reasons": [], "numbers": _check_numbers(detail),
                    "figures": figures})
    return out


def research_preview_figures(report: Mapping[str, Any]) -> list[Json]:
    """What the days gone show while the research gate's window is not complete: NOT evidence of the gate."""
    preview = _m(report, "preview")
    cov = _m(preview, "coverage")
    note = "vista previa sobre los días estables que ya pasaron: no es evidencia del gate"
    out = [interval_figure(f"cobertura de las evidencias de v1{label}", cov[key], source="ai.evidence (vista previa)", note=note)
           for key, label in (("interval", ""), ("interval_players", ", quién puede jugar")) if isinstance(cov.get(key), Mapping)]
    s = _m(preview, "searches")
    if s:
        out.append(figure("búsquedas: v2 sola frente a v1", f"{s.get('searches_v2_alone')} frente a {s.get('searches_v1')}",
                          source="ai.fixture_passes (vista previa)", cases=s.get("passes_compared"), threshold="v2 sola < v1", note=note))
    return out


def _sources(*pairs: tuple[str, str]) -> list[Json]:
    return [{"what": what, "where": where} for what, where in pairs]


def entry(spec: Spec, status: str, why: Iterable[str], *, figures: Iterable[Json] = (), checks: Iterable[Json] = (),
          evaluable_on: date | None = None, evaluated_on: date | None = None, when: str | None = None, failing_now: Iterable[str] = (),
          evaluator: Json | None = None, recorded: Json | None = None, lab: Json | None = None, sources: Iterable[Json] = ()) -> Json:
    """One gate of the panel, always with the same keys (the shape the admin view reads)."""
    if status not in STATUSES:
        raise ValueError(f"{spec.id}: {status!r} is not a status of the panel")
    return {"id": spec.id, "name": spec.name, "piece": spec.piece, "code": spec.code, "kind": spec.kind, "status": status,
            "approved": status == PASS, "why": list(why), "threshold": spec.threshold, "rejects_if": spec.rejects_if,
            "evaluable_on": _iso(evaluable_on), "evaluated_on": _iso(evaluated_on), "when": when, "figures": list(figures),
            "checks": list(checks), "failing_now": list(failing_now), "evaluator": evaluator, "recorded": recorded, "lab": lab,
            "depends_on": list(spec.depends_on), "note": spec.note,
            "sources": [*_sources((spec.name, spec.source)), *sources]}


def gate_b_entry(report: Mapping[str, Any] | None, row: Row | None, *, error: str | None = None) -> Json:
    spec = SPEC["gate_b"]
    verdict = None if report is None else str(report.get("verdict"))
    status, why = live_status(verdict, row, error=error)
    if report is None:
        return entry(spec, status, why, recorded=None if row is None else row.as_json())
    w = _m(report, "window")
    eligible = _day(w.get("eligible_on"))
    if w.get("complete"):
        when = f"ventana completa: {w.get('first')} a {w.get('last')}"
    elif w.get("anchor"):
        when = (f"evaluable el {w.get('eligible_on')} si nada cambia antes: configuración estable desde {w.get('anchor')} "
                f"({w.get('anchored_by')}), {w.get('stable_complete_days')} de 14 días completos")
    else:
        when = "el Orchestrator aún no escribió una ejecución de la sombra"
    why += [str(p) for p in report.get("pending") or []]
    if report.get("preview"):
        why.append("las comprobaciones son una vista previa sobre los 14 días que acabaron ayer: no son evidencia del gate")
    evaluator = {"module": "fbi.ai.gate_b", "method": report.get("method"), "verdict": verdict, "at": report.get("at"),
                 "preview": bool(report.get("preview")), "window": dict(w), "recorded_only_if": report.get("recorded_only_if")}
    return entry(spec, status, why, checks=gate_b_checks(report), evaluable_on=eligible, when=when,
                 failing_now=[str(x) for x in report.get("failing_now") or []], evaluator=evaluator,
                 recorded=None if row is None else row.as_json(),
                 sources=_sources(("cómo se repite", "python -m scripts.ia_gate_b evaluate --json")))


def research_entry(report: Mapping[str, Any] | None, row: Row | None, *, error: str | None = None) -> Json:
    spec = SPEC["research_v2"]
    verdict = None if report is None else str(report.get("verdict"))
    status, why = live_status(verdict, row, error=error)
    if report is None:
        return entry(spec, status, why, recorded=None if row is None else row.as_json())
    w = _m(report, "window")
    if w.get("complete"):
        when = f"evaluable ya: ventana {w.get('first')} a {w.get('last')} completa"
    else:
        when = (f"evaluable el {w.get('eligible_on')} si research v2 corre en sombra en todas las pasadas: "
                f"{w.get('stable_complete_days')} de 7 días completos ({w.get('anchored_by')})")
    why += [str(p) for p in report.get("pending") or []]
    if report.get("consequence"):
        why.append(f"consecuencia: {report['consequence']}")
    checks = research_checks(report)
    figures = [] if checks else research_preview_figures(report)
    failing = [str(c["id"]) for c in checks if c["verdict"] == FAIL]
    evaluator = {"module": "fbi.ai.gate_research", "method": None, "verdict": verdict, "at": report.get("at"),
                 "preview": not w.get("complete"), "window": dict(w), "recorded_only_if": report.get("recorded_only_if")}
    return entry(spec, status, why, figures=figures, checks=checks, evaluable_on=_day(w.get("eligible_on")), when=when, failing_now=failing,
                 evaluator=evaluator, recorded=None if row is None else row.as_json(),
                 sources=_sources(("cómo se repite", "python -m scripts.ia_research_gate evaluate --json")))


def gate_a_entry(row: Row | None) -> Json:
    spec = SPEC["gate_a"]
    if row is None:
        return entry(spec, PENDING_ACTIONS, ["ninguna fila registrada en ai.feature_gates (python -m scripts.ia_gate evaluate --record)"])
    status = PASS if row.passed else FAIL
    w = row.window or {}
    figures = [figure("ventana evaluada", f"{w.get('first')} a {w.get('last')}", source=f"ai.feature_gates, fila {row.id} (evidence.window)",
                      cases=w.get("stable_complete_days"), note="días completos con la configuración estable")] if w else []
    return entry(spec, status, [f"registrado el {row.at.isoformat()} (fila {row.id}, {row.decided_by}): {status}",
                                "cierre de la fase 0: su veredicto registrado es el que cuenta y el panel no lo vuelve a evaluar"],
                 figures=figures, evaluated_on=row.at.date(), when=f"evaluado el {row.at.date().isoformat()}", recorded=row.as_json())


def _gate_v2(r: Mapping[str, Any]) -> Json:
    """One newest ``ai-gate-v2`` report as the panel carries it: its verdict, its sample and its rejection quality with a normal 95 % interval."""
    diff, se = _dec(r.get("diff")), _dec(r.get("se"))
    ci = None if diff is None or se is None else [str((diff - Decimal(str(Z95)) * se).quantize(Decimal("0.0001"))),
                                                  str((diff + Decimal(str(Z95)) * se).quantize(Decimal("0.0001")))]
    return {"engine": r.get("engine"), "report_id": r.get("id"), "created_at": _iso(r.get("created_at")),
            "window": [_iso(r.get("window_from")), _iso(r.get("window_to"))], "version": r.get("version"), "verdict": r.get("verdict"),
            "status": GATE_V2_WORDS.get(str(r.get("verdict")), PENDING_ACTIONS), "selections": r.get("selections"), "days": r.get("days"),
            "rejected": r.get("rejected"), "roi_kept": r.get("roi_kept"), "roi_rejected": r.get("roi_rejected"),
            "diff": None if diff is None else str(diff), "se": None if se is None else str(se), "z": r.get("z"), "ci95_normal": ci,
            "clv_kept": r.get("clv_kept"), "clv_rejected": r.get("clv_rejected")}


def ai_gate_v2_entry(reports: Sequence[Mapping[str, Any]]) -> Json:
    spec = SPEC["ai_gate_v2"]
    by = {str(r.get("engine")): _gate_v2(r) for r in reports}
    figures = []
    for engine in [*SHADOW_REPORT_ENGINES, *sorted(set(by) - set(SHADOW_REPORT_ENGINES))]:
        g = by.get(engine)
        if g is None:
            continue
        ci = g["ci95_normal"]
        figures.append(figure(f"{engine}: ROI(guardadas) - ROI(rechazadas)", g["diff"],
                              source=f"ai.shadow_reports, fila {g['report_id']} ({g['created_at']})", cases=g["selections"],
                              counted=g["rejected"], ci95=ci, ci_method="normal con el error típico del bootstrap por partido" if ci else None,
                              threshold="z ≥ 2", verdict=g["status"],
                              note=f"{g['selections']} selecciones liquidadas en {g['days']} días, {g['rejected']} rechazadas; z = {g['z']}; "
                                   f"CLV guardadas {g['clv_kept']} frente a rechazadas {g['clv_rejected']}"))
    combined = by.get("combined")
    if combined is None:
        return entry(spec, PENDING_ACTIONS, ["no hay informe de combined en ai.shadow_reports"], figures=figures)
    status = str(combined["status"])
    why = [f"informe de combined del {combined['created_at']} (fila {combined['report_id']}): {combined['verdict']}",
           "es la puerta que lee fbi.ai.gating: sin PASA, la IA no cambia lo que ven los usuarios"]
    recorded = {"table": "ai.shadow_reports", "engine": "combined", "id": combined["report_id"], "at": combined["created_at"],
                "passed": combined["verdict"] == "pass", "verdict": combined["verdict"], "window": combined["window"]}
    return entry(spec, status, why, figures=figures, evaluated_on=_day(combined["created_at"]),
                 when="se vuelve a calcular cada día (ciclo de la sombra), sobre los 60 días anteriores", recorded=recorded)


def lab_entry(spec: Spec, record: LabRecord) -> Json:
    """A gate that IS its experiment's: its status is the frozen verdict."""
    why = [f"{record.key} ({record.code}): {record.verdict}, evaluado el {record.evaluated}", *record.notes]
    if not record.registered:
        why.append("la huella guardada no es la del protocolo registrado en fbi.research.protocol")
    return entry(spec, record.verdict, why, figures=record.figures(), evaluated_on=record.evaluated_on,
                 when="evaluado una sola vez (regla de parada del protocolo); otro resultado pide un protocolo v2 registrado antes de mirar",
                 lab=record.as_json(), sources=_sources(("resultado", record.result), ("informe", record.doc)))


def coh_entry(record: LabRecord = LAB_A02) -> Json:
    spec = SPEC["g_coh"]
    why = ["INT-A03 e INT-A04 aún no existen en el código: no hay cifra única en sombra ni paridad de 72 h que medir",
           f"su experimento del LAB, {record.key} ({record.code}), {record.verdict} en los tres mercados: según la regla de rechazo, queda la "
           "reescalada como cifra coherente y se sigue en el LAB"]
    return entry(spec, PENDING_DEPENDENCIES, why, figures=record.figures(), when="cuando existan INT-A03 e INT-A04 y 72 h de producción",
                 lab=record.as_json(), sources=_sources(("experimento del LAB", record.result), ("informe", record.doc)))


FUENTES_1_ITEMS: Final = 6074
FUENTES_1_MEASURE: Final[tuple[tuple[str, int, str], ...]] = (
    ("nivel guardado al escribir", 3560, "lo que guardó cada ítem al escribirse"),
    ("listas y registro de hoy", 3398, "repetición de IA-040 con lo que hay hoy"),
    ("con las filas propuestas del registro", 284, "repetición de IA-040 con su propuesta, que aún no está en la sombra"),
)
"""IA-040's table 2: the web items of 30 days from domains without a tier, read three ways (the same 6.074 items each time)."""
FUENTES_1_SOURCE: Final = ("IA-040, tabla 2 (backend/docs/owner/IA_040_REGISTRO_FUENTES.md): ai.evidence, origin = 'web', del 2026-10-12 04:30 "
                           "al 2026-11-11 04:30 UTC; 6.074 ítems, 5.175 de v1 y 899 de Research v2")


@functools.cache
def _fuentes_1_shares() -> tuple[Mapping[str, Any], ...]:
    """IA-040's three shares with their intervals, computed once: an exact interval over 6.074 items is slow."""
    return tuple(Proportion(k, FUENTES_1_ITEMS, Decimal("0.20"), "max").as_json() for _, k, _ in FUENTES_1_MEASURE)


def fuentes_1_entry() -> Json:
    """G-FUENTES 1 waits for INT-B01's registry in the shadow. Beside it, IA-040's measure, frozen with its source: made before the new registry,
    it is never the gate's verdict. The panel reads nothing of ``ai.evidence`` itself (``tests/unit/test_typed_evidence_guard.py``)."""
    spec = SPEC["g_fuentes_1"]
    why = ["el registro depurado de INT-B01 aún no está en la sombra: el gate no se puede evaluar",
           "las cifras son la medida de IA-040 (11-nov-2026), antes del registro nuevo: ninguna es el veredicto del gate"]
    figures = [interval_figure(f"ítems web de dominios sin nivel: {label}", share, source=FUENTES_1_SOURCE,
                               note=f"{note}; NO es el veredicto del gate")
               for (label, _, note), share in zip(FUENTES_1_MEASURE, _fuentes_1_shares(), strict=True)]
    return entry(spec, PENDING_DEPENDENCIES, why, figures=figures, when="cuando el registro depurado corra en la sombra (tras el Gate B)",
                 sources=_sources(("medida de IA-040", FUENTES_1_SOURCE)))


def e6_entry() -> Json:
    spec = SPEC["g_e6"]
    p = protocol.PROTOCOLS.get("INT-A08")
    if p is None:
        why = ["INT-A08 no tiene protocolo registrado en fbi.research.protocol: el experimento no puede correr (protocol.require lo impide)"]
    else:
        why = [f"protocolo {p.version} registrado ({protocol.fingerprint(p)[:12]}…), sin resultado congelado todavía"]
    return entry(spec, PENDING_DEPENDENCIES, why, when="después de INT-A08 en el LAB, con su protocolo")


def pending_entry(spec: Spec) -> Json:
    why = [f"espera: {'; '.join(spec.depends_on)}"] if spec.depends_on else ["sus piezas aún no existen"]
    return entry(spec, PENDING_DEPENDENCIES, why, when="cuando existan sus piezas")


# ── P1 ─────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class P1Counts:
    """What P1 can count: the days since the configuration under evaluation and the shadow's selections per family since then."""

    anchor: date | None
    anchored_by: str | None
    today: date
    rows: tuple[tuple[str, str, int, int], ...] = ()
    """(engine, market key, selections reviewed before the kick-off, of them with the match finished)."""

    @property
    def days(self) -> int:
        """Complete Bogotá days from the anchor to yesterday."""
        return 0 if self.anchor is None else max(0, (self.today - self.anchor).days)

    def families(self) -> dict[str, dict[str, dict[str, int]]]:
        out: dict[str, dict[str, dict[str, int]]] = {}
        for engine, market, reviewed, finished in self.rows:
            fam = family_of(market) or "otras"
            cell = out.setdefault(engine, {}).setdefault(fam, {"reviewed": 0, "finished": 0})
            cell["reviewed"] += reviewed
            cell["finished"] += finished
        return out


def p1_entry(p: P1Counts | None, *, error: str | None = None) -> Json:
    spec = SPEC["p1"]
    if error is not None:
        return entry(spec, PENDING_ACTIONS, [f"no se pudo contar: {error}"])
    if p is None or p.anchor is None:
        return entry(spec, PENDING_TIME, ["no hay ancla de configuración (el Gate B no pudo calcularla): nada que contar todavía"])
    fams = p.families()
    reached = sorted(f"{e} {f}" for e, fs in fams.items() for f, c in fs.items() if c["reviewed"] >= P1_SELECTIONS)
    figures = [figure("días completos de sombra desde el ancla", str(p.days), source=f"ancla del Gate B: {p.anchor} ({p.anchored_by})",
                      threshold=f"≥ {P1_DAYS}")]
    for engine in P1_ENGINES:
        for fam, c in sorted(fams.get(engine, {}).items()):
            figures.append(figure(f"{engine} · {fam}: selecciones revisadas antes del saque", str(c["reviewed"]),
                                  source="ai.pick_reviews (motores de la sombra, ok o fallback)", cases=c["reviewed"],
                                  counted=c["finished"], threshold=f"≥ {P1_SELECTIONS}", note=f"{c['finished']} con el partido terminado"))
    if p.days >= P1_DAYS and reached:
        status = PENDING_ACTIONS
        why = [f"muestra alcanzada en {', '.join(reached)}: P1 no guarda evidencia propia; la evalúa el informe de G-DELIB (INT-C08)"]
    else:
        status = PENDING_TIME
        why = [f"{p.days} de {P1_DAYS} días completos desde {p.anchor}",
               "ninguna familia llega a 300 selecciones" if not reached else f"llegan a 300: {', '.join(reached)}"]
    return entry(spec, status, why, figures=figures, evaluable_on=p.anchor + timedelta(days=P1_DAYS),
                 when=f"no antes del {(p.anchor + timedelta(days=P1_DAYS)).isoformat()} (30 días completos desde el ancla)")


# ── the value per dollar ───────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Component:
    """A component of the AI as the cost by path splits it (``fbi.ai.cost_paths``) and the engines whose ``ai-gate-v2`` measures its benefit."""

    id: str
    name: str
    path: str
    parts: tuple[str, ...] = ()
    """The parts of the path; empty: the whole path."""
    engines: tuple[str, ...] = ()
    events: bool = False
    """Its benefit as an information lead over the price is what G-EVENTOS measured (the web's claims, IA-045)."""
    user_ledger: bool = False
    note: str | None = None


COMPONENTS: Final[tuple[Component, ...]] = (
    Component("review-v2", "Revisión de producción (review-v2)", "production", ("review",), ("llm",)),
    Component("brief-v8", "Lectura del partido (brief-v8)", "production", ("brief",),
              note="insumo de review-v2: ningún informe mide su valor por separado"),
    Component("deliberation", "Deliberación en sombra (agentes, Council y escaladas)", "deliberation", (), ("ma-v1", "ma-v1-h", "cs-v1"),
              note="los brazos ma-v1 y ma-v1-h comparten las llamadas de los agentes: el coste es el del camino entero"),
    Component("research-search", "Research: búsquedas de Exa", "research", ("search",), events=True),
    Component("research-extraction", "Research: extracción de lo encontrado", "research", ("extraction",), events=True),
    Component("chronicles", "Crónica de lectores", "chronicles", (), user_ledger=True,
              note="escribe en su propio libro, el de la IA de los lectores (plan UX, A11), que va al lado del total de ai.usage y nunca dentro"),
    Component("learning", "Aprendizaje y patrones", "rest", ("learning",)),
    Component("postmortem", "Post-mortems", "rest", ("postmortem",)),
    Component("lab", "LAB: batería, sondas y equivalencia", "rest", ("lab",)),
    Component("other", "Otros", "rest", ("other",)),
)


OWN_LEDGER: Final = "la IA de los lectores, plan UX A11"
"""The readers' AI keeps its own ledger, beside Intelligence's total and never in it; only its own modules and the cost report's readers name its
table (``tests/unit/test_user_layer_isolation.py``)."""


def _cost_of(c: Component, cost: Mapping[str, Any], days: float | None) -> Json:
    path = (cost.get("paths") or {}).get(c.path) or {}
    t = path if not c.parts else (path.get("parts") or {}).get(c.parts[0]) or {}
    usd = _dec(t.get("usd_exact") if t.get("usd_exact") is not None else t.get("usd")) or Decimal(0)
    out: Json = {"usd": t.get("usd", "0.00"), "usd_exact": t.get("usd_exact"), "share_pct": t.get("share_pct"), "calls": t.get("calls", 0),
                 "fixtures": t.get("fixtures", 0), "usd_per_fixture": t.get("usd_per_fixture"), "candidates": t.get("candidates", 0),
                 "usd_per_candidate": t.get("usd_per_candidate"), "models": list(t.get("models") or [])[:3],
                 "pace_30_days_usd": None if not days else str((usd / Decimal(str(days)) * 30).quantize(Decimal("0.01")))}
    if c.user_ledger:
        u = cost.get("chronicles_user_ledger") or {}
        out["own_ledger"] = {"ledger": OWN_LEDGER, "calls": u.get("calls", 0), "usd": u.get("usd", "0.00")}
        own = _dec(u.get("usd")) or Decimal(0)
        out["pace_30_days_usd_own_ledger"] = None if not days else str((own / Decimal(str(days)) * 30).quantize(Decimal("0.01")))
    if c.path == "deliberation":
        out["parts"] = {q: {"usd": p.get("usd"), "calls": p.get("calls")} for q, p in (path.get("parts") or {}).items()}
    return out


BENEFIT_MEASURE: Final = ("ROI(guardadas) - ROI(rechazadas) a stake plano de 1 sobre las selecciones liquidadas que el motor revisó antes "
                          "del saque, con el error típico del bootstrap por partido (ai-gate-v2)")
VALUE_UNIT: Final = "unidades de beneficio a stake plano de 1 por cada US$ de coste"


def value_per_usd(g: Mapping[str, Any], usd_per_candidate: Any) -> Json:
    """The value per dollar of one engine's review: only when its ``ai-gate-v2`` says pass (the benefit is demonstrated)."""
    if g.get("verdict") != "pass":
        why = {"fail": "beneficio no demostrado: su ai-gate-v2 dice NO PASA (lo que rechaza no rinde peor que lo que guarda, z < 2)",
               "insufficient": "beneficio pendiente por muestra: su ai-gate-v2 aún no tiene 300 selecciones, 30 días y 50 rechazadas"}
        return {"value": None, "ci95": None, "unit": VALUE_UNIT,
                "why": why.get(str(g.get("verdict")), f"sin veredicto de ai-gate-v2 ({g.get('verdict')})")}
    n, rej, diff, se, cost = (_dec(g.get("selections")), _dec(g.get("rejected")), _dec(g.get("diff")), _dec(g.get("se")),
                              _dec(usd_per_candidate))
    if not n or rej is None or diff is None or se is None or not cost:
        return {"value": None, "ci95": None, "unit": VALUE_UNIT, "why": "faltan las cifras para calcularlo (selecciones, rechazos o coste)"}
    r = rej / n
    scale = (1 - r) * r / cost
    z = Decimal(str(Z95))
    q = Decimal("0.0001")
    return {"value": str((scale * diff).quantize(q)), "ci95": [str((scale * (diff - z * se)).quantize(q)), str((scale * (diff + z * se)).quantize(q))],
            "unit": VALUE_UNIT, "why": "beneficio demostrado (ai-gate-v2 en PASA): (1 - r)·r·(ROI guardadas - ROI rechazadas) / coste por candidato",
            "inputs": {"r": str(r.quantize(q)), "diff": str(diff), "se": str(se), "usd_per_candidate": str(cost)}}


def _events_benefit(record: LabRecord = LAB_B09) -> Json:
    rows = [r for r in record.rows if r.segment in LAB_WEB_SEGMENTS]
    shown = any(r.ci95[0] > 0 for r in rows)
    return {"status": "demostrado" if shown else "no demostrado", "source": f"G-EVENTOS: {record.key} ({record.code}), {record.result}",
            "measure": "si el precio se mueve, después de que PrediGol conoce una afirmación web, más que en los controles (D, pp)",
            "segments": [{"segment": r.segment, "events": r.n, "matches": r.blocks, "d_pp": r.estimate, "ci95": list(r.ci95)} for r in rows],
            "reading": "ventaja de información frente al precio: ninguna demostrada (una semana de Research v2, MDE ≈ 0,5-1,5 pp); "
                       "su valor como contexto de la revisión no lo mide ningún informe",
            "value_per_usd": {"value": None, "ci95": None, "unit": None,
                              "why": "el beneficio medido no está demostrado y no está en dólares: no hay valor por dólar"}}


def value_section(cost: Mapping[str, Any] | None, reports: Sequence[Mapping[str, Any]], *, cost_days: float | None) -> Json:
    """Each component of the AI with its cost, its measured benefit and its value per dollar (only where the benefit is demonstrated)."""
    by = {str(r.get("engine")): _gate_v2(r) for r in reports}
    components: list[Json] = []
    for c in COMPONENTS:
        item: Json = {"id": c.id, "name": c.name, "path": c.path, "path_label": PATH_LABELS.get(c.path, c.path), "parts": list(c.parts),
                      "note": c.note, "cost": None if cost is None else _cost_of(c, cost, cost_days)}
        per_candidate = None if item["cost"] is None else item["cost"]["usd_per_candidate"]
        if c.engines:
            engines = []
            for e in c.engines:
                g = by.get(e)
                if g is None:
                    engines.append({"engine": e, "status": "sin medir", "why": "ai.shadow_reports no tiene informe de este motor (no corre)",
                                    "value_per_usd": {"value": None, "ci95": None, "unit": VALUE_UNIT, "why": "sin medir"}})
                    continue
                engines.append(g | {"value_per_usd": value_per_usd(g, per_candidate)})
            statuses = {str(g.get("verdict")) for g in engines}
            status = ("demostrado" if "pass" in statuses else "no demostrado" if "fail" in statuses
                      else "pendiente por muestra" if "insufficient" in statuses else "sin medir")
            item["benefit"] = {"status": status, "source": "ai.shadow_reports (ai-gate-v2)", "measure": BENEFIT_MEASURE, "engines": engines}
        elif c.events:
            item["benefit"] = _events_benefit()
        else:
            item["benefit"] = {"status": "sin medir", "source": None, "measure": None,
                               "reading": "ningún informe mide su beneficio", "value_per_usd": {"value": None, "ci95": None, "unit": None,
                                                                                             "why": "sin medir"}}
        components.append(item)
    window: Json | None = None
    if cost is not None:
        t = cost.get("total") or {}
        window = {"version": cost.get("version"), "since": cost.get("since"), "until": cost.get("until"), "days": cost_days,
                  "calls": t.get("calls"), "usd": t.get("usd"), "usd_exact": t.get("usd_exact"), "ledger_usd_exact": t.get("ledger_usd_exact"),
                  "difference_usd": t.get("difference_usd"), "reconciles": t.get("reconciles"),
                  "opus_all_registered": (cost.get("opus") or {}).get("all_registered")}
    return {"decides": False, "cost_window": window, "benefit_sources": ["ai.shadow_reports (ai-gate-v2)", "G-EVENTOS (IA-045)"],
            "value_unit": VALUE_UNIT, "rule": "valor por dólar solo donde el beneficio está demostrado; si no, se dice por qué",
            "components": components}


# ── the panel ──────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PanelInputs:
    """Everything the panel is made of, as the readers (``fbi.ai.gates_panel_readers``) and the script read it."""

    at: datetime
    rows: Mapping[str, Row] = field(default_factory=dict)
    gate_b: Mapping[str, Any] | None = None
    gate_b_error: str | None = None
    research: Mapping[str, Any] | None = None
    research_error: str | None = None
    shadow_reports: Sequence[Mapping[str, Any]] = ()
    p1: P1Counts | None = None
    p1_error: str | None = None
    cost: Mapping[str, Any] | None = None
    cost_days: float | None = None


def evidence_rows(rows: Mapping[str, Row]) -> list[Json]:
    """The newest row of every gate of ``ai.feature_gates``, read as the gates read it - and the two records that are not gates."""
    out = []
    for g in [*GATES, *sorted(set(rows) - set(GATES))]:
        r = rows.get(g)
        if g in NOT_GATES:
            reads = "registro (no es un gate)" if r is not None else "sin fila (registro, no es un gate)"
        elif r is None:
            reads = "sin fila: no pasa (sin evidencia)"
        else:
            reads = PASS if r.passed else FAIL
        out.append({"gate": g, "is_gate": g not in NOT_GATES, "reads_as": reads, "row": None if r is None else r.as_json()})
    return out


def panel(i: PanelInputs) -> Json:
    """The whole panel, JSON-ready: the gates in the plan's order, the newest evidence rows and the value per dollar."""
    rows = dict(i.rows)
    gates = [
        gate_b_entry(i.gate_b, rows.get("gate_b"), error=i.gate_b_error),
        research_entry(i.research, rows.get("research_v2"), error=i.research_error),
        gate_a_entry(rows.get("gate_a")),
        ai_gate_v2_entry(i.shadow_reports),
        coh_entry(),
        pending_entry(SPEC["g_precio"]),
        fuentes_1_entry(),
        pending_entry(SPEC["g_fuentes_2"]),
        pending_entry(SPEC["g_fuentes_3"]),
        lab_entry(SPEC["g_eventos"], LAB[LAB_OF["g_eventos"]]),
        lab_entry(SPEC["g_e4"], LAB[LAB_OF["g_e4"]]),
        e6_entry(),
        pending_entry(SPEC["g_delib"]),
        pending_entry(SPEC["g_cron"]),
        p1_entry(i.p1, error=i.p1_error),
        pending_entry(SPEC["f_player"]),
    ]
    counts = {s: sum(1 for g in gates if g["status"] == s) for s in STATUSES}
    doc: Json = {"version": VERSION, "decides": False, "at": i.at.isoformat(), "day": local_day(i.at).isoformat(),
                 "rule": "ningún gate pendiente aparece como aprobado: PASA solo con un pase registrado (fila de ai.feature_gates, "
                         "informe de ai.shadow_reports o veredicto congelado del LAB)",
                 "summary": counts, "gates": gates, "evidence_rows": evidence_rows(rows),
                 "value": value_section(i.cost, i.shadow_reports, cost_days=i.cost_days)}
    doc["violations"] = violations(doc)
    doc["rule_holds"] = not doc["violations"]
    return doc


def on_file_pass(e: Mapping[str, Any]) -> bool:
    """A pass is on file: a recorded row (or report) that passed, or a frozen LAB verdict that passed."""
    rec = e.get("recorded")
    lab = e.get("lab")
    return (isinstance(rec, Mapping) and rec.get("passed") is True) or (isinstance(lab, Mapping) and lab.get("verdict") == PASS
                                                                        and e.get("kind") == "lab")


def violations(doc: Mapping[str, Any]) -> list[str]:
    """Every way a panel breaks its rule: an unknown status, ``approved`` that is not ``status == PASA``, a PASA without a pass on file, or
    a PASA on a gate that can only be pending (P1, a gate whose pieces do not exist)."""
    out: list[str] = []
    for e in doc.get("gates") or []:
        status = e.get("status")
        if status not in STATUSES:
            out.append(f"{e.get('id')}: unknown status {status!r}")
        if bool(e.get("approved")) != (status == PASS):
            out.append(f"{e.get('id')}: approved={e.get('approved')} but status={status!r}")
        if status == PASS and not on_file_pass(e):
            out.append(f"{e.get('id')}: PASA without a pass on file")
        if status == PASS and e.get("kind") in ("muestra", "dependencias"):
            out.append(f"{e.get('id')}: a {e.get('kind')} gate cannot be PASA")
    return out


# ── for a person ───────────────────────────────────────────────────────────────────────────────────────────────


def _figure_line(f: Mapping[str, Any]) -> str:
    parts = [f"{f['label']}: {f['value'] if f['value'] is not None else '-'}"]
    if f.get("counted") is not None and f.get("cases") is not None and f.get("ci_method") == "Wilson":
        parts[0] = f"{f['label']}: {f['counted']}/{f['cases']} · {f['value']}"
    elif f.get("cases") is not None:
        parts.append(f"n = {f['cases']}")
    if f.get("ci95"):
        parts.append(f"IC95 [{f['ci95'][0]}; {f['ci95'][1]}] ({f['ci_method']})")
    if f.get("threshold"):
        parts.append(f"umbral {f['threshold']}")
    if f.get("verdict"):
        parts.append(f"veredicto: {f['verdict']}")
    if f.get("note"):
        parts.append(str(f["note"]))
    return " · ".join(parts)


def _figure_lines(shown: Sequence[Mapping[str, Any]], limit: int, *, indent: str) -> list[str]:
    out = [f"{indent}- {_figure_line(f)}" for f in shown[:limit]]
    if len(shown) > limit:
        out.append(f"{indent}- … y {len(shown) - limit} cifra(s) más en --json")
    return out


def _ci(ci: Sequence[Any] | None) -> str:
    return "-" if not ci else f"[{ci[0]}; {ci[1]}]"


def lines(doc: Mapping[str, Any], *, figures: int = 6) -> list[str]:
    """The panel for a person, in Spanish: one block per gate (status, when, why, its first figures and what fails already), the evidence
    rows and the value per dollar."""
    out = [f"PANEL DE GATES · {doc['version']} (solo lectura, no decide) · {doc['at']}",
           f"Regla: ningún gate pendiente aparece como aprobado — {'se cumple' if doc.get('rule_holds') else 'NO SE CUMPLE'}",
           "Resumen: " + ", ".join(f"{s} {n}" for s, n in doc["summary"].items() if n)]
    for e in doc["gates"]:
        out.append(f"[{e['status']}] {e['name']} ({e['piece']}){' · ' + e['when'] if e.get('when') else ''}")
        out += [f"    · {w}" for w in e["why"]]
        out += _figure_lines(e["figures"], figures, indent="    ")
        for c in e["checks"]:
            out.append(f"    [{c['verdict']}] {c['title']}" + (f" — {'; '.join(c['reasons'])[:240]}" if c["reasons"] else ""))
            out += _figure_lines(c["figures"], figures, indent="        ")
        if e["failing_now"]:
            out.append(f"    Falla ya: {', '.join(e['failing_now'])}")
    out.append("Filas más nuevas de ai.feature_gates:")
    for r in doc["evidence_rows"]:
        row = r["row"]
        out.append(f"    {r['gate']}: {r['reads_as']}" + ("" if row is None else f" (fila {row['id']}, {row['at']})"))
    v = doc["value"]
    w = v.get("cost_window")
    if w is None:
        out.append("Valor por dólar · el coste no se leyó")
    else:
        rec = "sí" if w.get("reconciles") else "NO" if w.get("reconciles") is False else "-"
        out.append(f"Valor por dólar · coste {w.get('version')} del {w.get('since')} al {w.get('until')}: US$ {w.get('usd')} en "
                   f"{w.get('calls')} llamadas; cuadra con ai.usage: {rec}; beneficio: {', '.join(v['benefit_sources'])}")
    for c in v["components"]:
        cost = c.get("cost")
        b = c["benefit"]
        if cost is None:
            head = "coste sin leer"
        else:
            head = f"US$ {cost['usd']} ({cost['calls']} llamadas"
            if cost.get("usd_per_candidate"):
                head += f"; {cost['candidates']} candidatos a US$ {cost['usd_per_candidate']}"
            head += f"; ritmo ≈ US$ {cost.get('pace_30_days_usd') or '-'} / 30 días)"
            own = cost.get("own_ledger")
            if own:
                head += f" + su propio libro ({own['ledger']}): US$ {own['usd']} en {own['calls']} llamadas"
        out.append(f"    {c['name']}: {head} · beneficio: {b['status']}")
        for g in b.get("engines") or []:
            vp = g["value_per_usd"]
            if g.get("verdict") is None:
                out.append(f"        {g['engine']}: {g.get('why')}")
                continue
            out.append(f"        {g['engine']}: ai-gate-v2 {g['verdict']} ({g['selections']} selecciones, {g['days']} días, {g['rejected']} "
                       f"rechazadas; ROI guardadas - rechazadas {g['diff']}, IC95 {_ci(g['ci95_normal'])}, z {g['z']}) · valor por dólar: "
                       f"{vp['value'] if vp['value'] is not None else '— (' + vp['why'] + ')'}")
        if b.get("segments"):
            segs = "; ".join(f"{s['segment']} D {s['d_pp']:+.3f} [{s['ci95'][0]:+.3f}; {s['ci95'][1]:+.3f}] pp ({s['events']} eventos)"
                             for s in b["segments"])
            out.append(f"        G-EVENTOS: {segs} · valor por dólar: —")
    return out


__all__ = ["COMPONENTS", "FAIL", "LAB", "LAB_A02", "LAB_A09", "LAB_B09", "PASS", "PENDING", "PENDING_ACTIONS", "PENDING_DEPENDENCIES",
           "PENDING_SAMPLE", "PENDING_TIME", "REJECTS", "SPECS", "STATUSES", "VERSION", "Component", "LabRecord", "LabRow", "P1Counts",
           "PanelInputs", "Row", "Spec", "entry", "figure", "interval_figure", "lines", "live_status", "on_file_pass", "panel", "row_of",
           "value_per_usd", "value_section", "violations"]
