"""Hypotheses the repository proposes from a measurement (plan F12): written here with their evidence, registered in the database on request.

The loop of the plan is hypothesis -> experiment -> gate -> promotion, and the owner is the only one who moves a hypothesis out of PROPOSED. A
measurement that points somewhere (the comparison of the families with the market, F11.4) used to end in a paragraph of a guide, which is not a
hypothesis anyone can decide on, find in Evolución or link an experiment and a promotion to. This module is the other end: each proposal is a
dataclass with the numbers it rests on, the guide those numbers come from and the row of the guide's table that holds each, and
``tests/unit/test_docs_match_code.py`` fails when the guide and the proposal say different things.

``register`` writes a proposal through ``fbi.research.evolution.propose`` - keyed, so it is made once however many times it runs - as ``system``,
status PROPOSED. It decides nothing, changes no model, forecast or pick, and with ``confirm=False`` it writes nothing. This module sits outside
the fingerprinted packages (it is not model code): adding a proposal does not change the fingerprint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import psycopg

from fbi.research import evolution

MINUS: Final = "\N{MINUS SIGN}"
EN_DASH: Final = "\N{EN DASH}"
GUIDE: Final = "FAMILIAS_VS_MERCADO_F11.md"
SECTION: Final = "## 7. Un sesgo concreto: el nivel de córners"
"""The heading in ``docs/owner/FAMILIAS_VS_MERCADO_F11.md`` of the section where most cited figures live."""
SECTION_REPEAT: Final = "## 9. Cómo se repite"
ANYWHERE: Final = ""
"""``Cited.where`` for a figure that is not in one section: the test looks for it in the whole guide."""
PROPOSED_BY: Final = "system"
MAX_TITLE: Final = 160
MAX_HYPOTHESIS: Final = 600
MAX_RATIONALE: Final = 1000
"""The limits the API puts on a hypothesis the owner writes (``HypothesisIn``) and the column on a title: the same here."""
MAX_CHIP: Final = 90
"""The page shows an evidence value of the card cut at this many characters."""
MAX_CHIPS: Final = 6
"""... and at most this many evidence values besides the three the card shows apart (matches, impact, cost)."""
APART: Final = ("n_matches", "impact", "investigation_cost")


@dataclass(frozen=True, slots=True)
class Cited:
    """A figure as the guide writes it, and where: the heading of its section, and the labels of the row of the table it is in (None: it is in
    the text of the section)."""

    text: str
    row: tuple[str, ...] | None = None
    where: str = SECTION


@dataclass(frozen=True, slots=True)
class Proposal:
    key: str
    title: str
    hypothesis: str
    rationale: str
    target: str
    evidence: dict[str, Any]
    cited: tuple[Cited, ...] = field(default_factory=tuple)
    """Every figure the proposal quotes from the guide, in its text or in its evidence: the test finds each where it says it is."""


def integer(text: str) -> int:
    """A count as the guide writes it (thousands with a point): 1.268 -> 1268."""
    return int(text.replace(".", ""))


# The figures of §7 of the guide, as written there (decimal comma, a typographic minus). Row labels are cells of the table row that holds the figure.
RATIO = Cited("1,045", (f"18 sep {EN_DASH} 16 oct",))
SHORT_BY = Cited("4,5 %")
GAP_BEFORE = Cited(f"{MINUS}0,0040 ± 0,0032")
GAP_CLOSE = Cited(f"{MINUS}0,0006 ± 0,0030", ("total del partido", "último precio", "1.268"))
GAP_24H = Cited(f"{MINUS}0,0006 ± 0,0041", ("total del partido", "24 h antes", "785"))
GAP_HOME = Cited(f"{MINUS}0,0166 ± 0,0044", ("equipo local", "último precio", "1.179"))
MATCHES_CLOSE = Cited("1.268", ("total del partido", "último precio"))
BETS_CLOSE = Cited("672", ("total del partido", "último precio", "+9,7 %"))
RETURN_CLOSE = Cited("+1,1 % ± 3,8 %", ("total del partido", "último precio", "672"))
SIGNAL_CLOSE = Cited("+0,35 ± 0,27", ("total del partido", "último precio", "1.268"))
SIGNAL_24H = Cited("+0,15 ± 0,34", ("total del partido", "24 h antes", "785"))
SIGNAL_HOME = Cited(f"{MINUS}0,25 ± 0,20", ("equipo local", "último precio", "1.179"))
SIGNAL_AWAY = Cited("+0,23 ± 0,19", ("equipo visitante", "último precio", "1.181"))
# The criterion of the plan for a family to decide in shadow (F11.5), as §9 of the guide says it.
CRITERION = Cited("al menos 300 apuestas simuladas y valor de cierre no negativo", where=SECTION_REPEAT)
# The prices the measurement rests on, as the header of the guide says it.
FROM_DAY = Cited("25 de septiembre", where=ANYWHERE)
TO_DAY = Cited("24 de octubre de 2026", where=ANYWHERE)

WINDOW: Final = f"precios del {FROM_DAY.text} al {TO_DAY.text}"
VARIANTS_GUIDE: Final = "VARIANTES_VS_MERCADO_F12.md"
REPEAT_COMMAND: Final = "python -m scripts.families variant"
REPEAT: Final = f"La medición se repite con el comando «{REPEAT_COMMAND}» (guía {VARIANTS_GUIDE}), con una ventana posterior a la aprobación."
"""How the measurement is repeated (F12.5): the permanent tool that stands a variant of a family next to the family and the books. No figure in it."""
COST: Final = "Ninguna petición al proveedor ni IA: solo precios y resultados ya guardados"

RECENT_LEVEL_KEY: Final = "f11:recent_level:v1"
MARKET_BLEND_KEY: Final = "f11:market_blend:v1"

RECENT_LEVEL: Final = Proposal(
    key=RECENT_LEVEL_KEY,
    title="Córners: corregir el nivel con lo observado en las 4 semanas anteriores",
    hypothesis=("Multiplicar las medias de córners de cada lado por lo observado entre pronosticado de las 4 semanas anteriores (solo con partidos ya "
                "conocidos entonces) deja el total de córners del modelo a la par del mercado también hacia delante, con los pronósticos guardados."),
    rationale=(f"Desde mediados de septiembre el modelo se queda un {SHORT_BY.text} corto en córners (observado entre pronosticado {RATIO.text} del "
               f"18-sep al 16-oct). Con la corrección, mercado {MINUS} modelo en el total pasa de {GAP_BEFORE.text} a {GAP_CLOSE.text} al cierre "
               f"({MATCHES_CLOSE.text} partidos), y a 24 horas queda en {GAP_24H.text}: a la par del mercado, no por delante. Por equipo no se "
               f"cierra (local {GAP_HOME.text} al cierre), y las {BETS_CLOSE.text} apuestas simuladas del total rindieron {RETURN_CLOSE.text}: "
               "indistinguible de cero. Es un ajuste de nivel, no información nueva. Se propone medirlo hacia delante con el criterio de cualquier "
               f"modelo (contra el mercado, {CRITERION.text}) antes de tocar el código. {REPEAT}"),
    target="models",
    evidence={
        "n_matches": integer(MATCHES_CLOSE.text),
        "impact": "Totales de córners (después, tarjetas); no toca goles ni 1X2",
        "investigation_cost": COST,
        "guide": f"{GUIDE} §7",
        "window": WINDOW,
        "ratio_obs_over_pred": RATIO.text,
        "gap_before": GAP_BEFORE.text,
        "gap_after": GAP_CLOSE.text,
        "simulated_bets": integer(BETS_CLOSE.text),
    },
    cited=(RATIO, SHORT_BY, GAP_BEFORE, GAP_CLOSE, GAP_24H, GAP_HOME, MATCHES_CLOSE, BETS_CLOSE, RETURN_CLOSE, CRITERION, FROM_DAY, TO_DAY),
)

MARKET_BLEND: Final = Proposal(
    key=MARKET_BLEND_KEY,
    title="Totales de córners: una probabilidad anclada al mercado y movida hacia el modelo",
    hypothesis=("Una probabilidad que parte de la del mercado y se mueve hacia la del modelo con un peso w estimado hacia delante, en logit: "
                f"logit(p) = logit(mercado) + w · (logit(modelo) {MINUS} logit(mercado)), supera al mercado en el total de córners."),
    rationale=(f"La «señal extra» del total (el coeficiente de «modelo {MINUS} mercado») es positiva en los dos momentos, con la corrección de nivel: "
               f"{SIGNAL_CLOSE.text} al cierre ({MATCHES_CLOSE.text} partidos) y {SIGNAL_24H.text} a 24 horas. Es un indicio, no un resultado: con "
               f"esos errores no se distingue de cero. Por equipo no hay nada que mezclar: local {SIGNAL_HOME.text} y visitante {SIGNAL_AWAY.text} "
               "al cierre. Depende de la corrección de nivel (se mide con ella). Hay 4 semanas de precios; con los pronósticos guardados desde F10 se "
               "mide sin la aproximación semanal, y w se estimaría solo con partidos anteriores a cada predicción."),
    target="models",
    evidence={
        "n_matches": integer(MATCHES_CLOSE.text),
        "impact": "Totales de córners; ninguna otra familia ni mercado",
        "investigation_cost": COST,
        "guide": f"{GUIDE} §7",
        "window": WINDOW,
        "signal_close": SIGNAL_CLOSE.text,
        "signal_24h": SIGNAL_24H.text,
        "depends_on": RECENT_LEVEL.title,
    },
    cited=(SIGNAL_CLOSE, SIGNAL_24H, SIGNAL_HOME, SIGNAL_AWAY, MATCHES_CLOSE, FROM_DAY, TO_DAY),
)

REGISTER: Final[tuple[Proposal, ...]] = (RECENT_LEVEL, MARKET_BLEND)
"""Oldest first, and a proposal comes after the one it depends on. To propose another: add it here with the guide it rests on, and a test ties each
figure to that guide."""


def find(key: str) -> Proposal | None:
    return next((p for p in REGISTER if p.key == key), None)


def registered(conn: psycopg.Connection[Any]) -> dict[str, tuple[int, str]]:
    """The proposals of the register that the database already has: key -> (id, status)."""
    with conn.cursor() as cur:
        cur.execute("SELECT dedup_key, id, status FROM analytics.research_hypotheses WHERE dedup_key = ANY(%s)", ([p.key for p in REGISTER],))
        return {str(r[0]): (int(r[1]), str(r[2])) for r in cur.fetchall()}


def register(conn: psycopg.Connection[Any], *, at: datetime, confirm: bool) -> list[str]:
    """Write the proposals the database does not have yet (status PROPOSED, by the system). Without ``confirm`` nothing is written. The caller
    owns the transaction. A proposal that is already there - whatever the owner has decided about it since - is left alone."""
    have = registered(conn)
    lines: list[str] = []
    for p in REGISTER:
        if p.key in have:
            hid, status = have[p.key]
            lines.append(f"already registered: {p.key} as #{hid} ({status})")
            continue
        if not confirm:
            lines.append(f"WOULD REGISTER {p.key} ({p.target}): {p.title}")
            continue
        new_id = evolution.propose(conn, key=p.key, title=p.title, hypothesis=p.hypothesis, rationale=p.rationale, evidence=p.evidence,
                                   proposed_by=PROPOSED_BY, at=at, target=p.target)
        lines.append(f"REGISTERED {p.key} as #{new_id}: {p.title}" if new_id is not None else f"already registered: {p.key}")
    return lines


def render(have: dict[str, tuple[int, str]], *, full: bool = False) -> str:
    """The register against what the database has of it, to read. ``full`` adds the text and the evidence of each proposal."""
    out: list[str] = []
    for p in REGISTER:
        state = f"registered as #{have[p.key][0]} ({have[p.key][1]})" if p.key in have else "not registered"
        out.append(f"{p.key}  [{p.target}]  {state}")
        out.append(f"    {p.title}")
        if full:
            out.append(f"    hypothesis: {p.hypothesis}")
            out.append(f"    rationale:  {p.rationale}")
            out.append(f"    evidence:   {json.dumps(p.evidence, ensure_ascii=False, sort_keys=True)}")
        out.append("")
    pending = sum(1 for p in REGISTER if p.key not in have)
    out.append(f"{len(REGISTER)} proposals in the register, {len(REGISTER) - pending} registered, {pending} not yet." if pending
               else f"{len(REGISTER)} proposals in the register, all registered.")
    return "\n".join(out)
