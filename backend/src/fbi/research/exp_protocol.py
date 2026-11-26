"""The common protocol of the plan's eight experiments, ``exp-protocol-v1`` (plan RP-9.0).

An experiment of the restructuring plan (EXP-E1 to EXP-E8: not the evaluation cycle E1-E4 of the pipeline, which has nothing to do with them) says,
BEFORE it computes anything, what it asks, which population it reads, how it measures and when it counts as a success or as abandoned. Without
that, a search that tries enough segments finds by chance what it was looking for. This module is the one place where those rules are written:

* PREREGISTRATION. Each experiment is a frozen ``fbi.research.protocol.Protocol`` registered below under its key; its fingerprint (SHA-256 of
  its canonical JSON) is pinned by ``tests/unit/test_exp_protocol.py`` so that changing a registered protocol is a visible diff and a NEW version
  (git dates the protocol before any result). ``fbi.research.protocol.require`` finds them.
* A VERDICT WITHOUT A PRIOR PROTOCOL IS REFUSED (``admit``): it must name the registered protocol, carry its fingerprint, and have been computed
  after the protocol's signature.
* INTERVALS by resampling whole days of matches (``day_bootstrap_ci``): the matches of a day are not independent.
* MULTIPLE COMPARISONS: the Holm correction over the segments or families tried inside one experiment (``holm``), and the same sign in the two
  halves of the period (``same_sign_in_halves``).
* DATA ALREADY LOOKED AT: ``only_after`` keeps the matches played after the signature. The levels 3 and 4 were pointed out by the audit while
  looking at data; confirming them with the same data would be fooling oneself.
* EQUAL POPULATIONS: model and comparator are scored on the same matches (``equal_population``); what one does not predict does not count.
* THE VERDICT IS ARITHMETIC (``difference_verdict``): success, abandoned or insufficient, from the thresholds of the audit, unchanged.

It decides nothing about a model, a forecast, a pick or a threshold: it is pure (no database, no clock). A success of an experiment alone promotes
nothing: a promotion needs the intact test, the prospective shadow with the sample fixed, the coherence of section 11 and a signed proposal.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, Literal

from fbi.research.protocol import Protocol, fingerprint

VERSION: Final = "exp-protocol-v1"
ALPHA: Final = 0.05
BOOTSTRAP: Final = 2000
MAX_SEGMENTS: Final = 8
SIGNATURE: Final = "2026-11-26"
"""The day the eight protocols are registered (before the first run of any of them)."""


# ── the statistics ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def day_bootstrap_ci(values: Sequence[float], days: Sequence[date], *, seed: int, draws: int = BOOTSTRAP,
                     level: float = 0.95) -> tuple[float, float, float]:
    """(mean, low, high) of ``values`` with the interval of ``level`` by resampling WHOLE DAYS with replacement."""
    if len(values) != len(days):
        raise ValueError("one day per value")
    if not values:
        raise ValueError("no values")
    by_day: dict[date, list[float]] = defaultdict(list)
    for v, d in zip(values, days, strict=True):
        by_day[d].append(float(v))
    sums = [sum(v) for v in by_day.values()]
    counts = [len(v) for v in by_day.values()]
    total = sum(counts)
    mean = sum(sums) / total
    rng = random.Random(seed)
    n = len(sums)
    means: list[float] = []
    for _ in range(draws):
        picks = [rng.randrange(n) for _ in range(n)]
        c = sum(counts[i] for i in picks)
        means.append(sum(sums[i] for i in picks) / c)
    means.sort()
    tail = (1.0 - level) / 2.0
    low = means[max(0, min(draws - 1, math.floor(tail * draws)))]
    high = means[max(0, min(draws - 1, math.ceil((1.0 - tail) * draws) - 1))]
    return mean, low, high


def one_sided_p(values: Sequence[float], days: Sequence[date], *, below: float, seed: int, draws: int = BOOTSTRAP) -> float:
    """P-value of "the mean is NOT below ``below``": the share of day-resamples whose mean is at or above it (never zero: ``1 / (draws + 1)``)."""
    by_day: dict[date, list[float]] = defaultdict(list)
    for v, d in zip(values, days, strict=True):
        by_day[d].append(float(v))
    sums = [sum(v) for v in by_day.values()]
    counts = [len(v) for v in by_day.values()]
    rng = random.Random(seed)
    n = len(sums)
    hits = 0
    for _ in range(draws):
        picks = [rng.randrange(n) for _ in range(n)]
        if sum(sums[i] for i in picks) / sum(counts[i] for i in picks) >= below:
            hits += 1
    return (hits + 1) / (draws + 1)


def holm(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm's step-down adjustment: the adjusted p-values (monotone, capped at 1), in the order the tests were given."""
    order = sorted(p_values, key=lambda k: p_values[k])
    m = len(order)
    out: dict[str, float] = {}
    running = 0.0
    for rank, key in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[key]))
        out[key] = running
    return {k: out[k] for k in p_values}


def same_sign_in_halves(values: Sequence[float], days: Sequence[date], *, centre: float = 0.0) -> bool:
    """Do the first and the second half of the period (split by DAY, at the median day) lie on the same side of ``centre``?"""
    if len(values) != len(days):
        raise ValueError("one day per value")
    distinct = sorted(set(days))
    if len(distinct) < 2:
        return False
    cut = distinct[len(distinct) // 2]
    first = [v for v, d in zip(values, days, strict=True) if d < cut]
    second = [v for v, d in zip(values, days, strict=True) if d >= cut]
    if not first or not second:
        return False
    a, b = sum(first) / len(first) - centre, sum(second) / len(second) - centre
    return (a < 0) == (b < 0) and a != 0 and b != 0


def equal_population(*scored: Iterable[Hashable]) -> list[Hashable]:
    """The matches EVERY scorer predicted (model and comparator): what one of them does not predict does not enter. Order of the first scorer."""
    lists = [list(s) for s in scored]
    if not lists:
        return []
    common = set(lists[0]).intersection(*map(set, lists[1:]))
    return [k for k in dict.fromkeys(lists[0]) if k in common]


def only_after(items: Iterable[tuple[datetime, Hashable]], signed_at: datetime) -> list[Hashable]:
    """Keep what happened AFTER the protocol's signature (``(played_at, key)`` pairs): the data already looked at only validates."""
    return [k for at, k in items if at > signed_at]


# ── the verdict ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

Verdict = Literal["exito", "abandono", "insuficiente"]


@dataclass(frozen=True, slots=True)
class Judgement:
    verdict: Verdict
    reason: str
    mean: float
    low: float
    high: float
    n: int
    adjusted_p: float | None = None


def difference_verdict(values: Sequence[float], days: Sequence[date], *, success_below: float, n_required: int, seed: int,
                       adjusted_p: float | None = None, abandon_at_or_above: float | None = None) -> Judgement:
    """Judge a difference of loss (model minus comparator, per match) against the thresholds fixed in advance.

    * ``insuficiente``: fewer matches than ``n_required``. Nothing else is said, and the sample is not stretched.
    * ``exito``: the mean is below ``success_below`` AND its interval by days stays below it (when ``adjusted_p`` is given, it is the Holm-adjusted
      p-value of the segment and must be under ``ALPHA``), AND both halves of the period lie below it.
    * ``abandono``: the interval by days lies entirely at or above ``abandon_at_or_above`` (default: ``success_below``): no evidence of getting there.
    * otherwise ``insuficiente``: the sample is there but the interval still holds both answers - the experiment continues, nothing is declared.
    """
    n = len(values)
    if n < n_required:
        return Judgement("insuficiente", f"muestra {n} de {n_required}", float("nan"), float("nan"), float("nan"), n, adjusted_p)
    mean, low, high = day_bootstrap_ci(values, days, seed=seed)
    ceiling = success_below if abandon_at_or_above is None else abandon_at_or_above
    if low >= ceiling:
        return Judgement("abandono", "el intervalo queda entero por encima del umbral", mean, low, high, n, adjusted_p)
    p_ok = adjusted_p is None or adjusted_p < ALPHA
    if mean < success_below and high < success_below and p_ok and same_sign_in_halves(values, days, centre=success_below):
        return Judgement("exito", "por debajo del umbral, con intervalo, corrección de Holm y mismo signo en las dos mitades",
                         mean, low, high, n, adjusted_p)
    return Judgement("insuficiente", "con la muestra fijada el intervalo aún admite las dos respuestas", mean, low, high, n, adjusted_p)


class ProtocolRefusedError(Exception):
    """A verdict that does not rest on a protocol registered before it."""


def admit(key: str, *, claimed_fingerprint: str, computed_at: datetime, registry: Mapping[str, Protocol] | None = None) -> Protocol:
    """The registered protocol a verdict stands on, or ``ProtocolRefusedError``: it must exist, match the fingerprint the result carries, and the
    result must have been computed after the protocol's signature."""
    table = EXPERIMENTS if registry is None else registry
    p = table.get(key)
    if p is None:
        raise ProtocolRefusedError(f"no hay protocolo registrado para {key}: un veredicto sin protocolo previo se rechaza")
    if fingerprint(p) != claimed_fingerprint:
        raise ProtocolRefusedError(f"{key}: la huella del resultado no es la del protocolo registrado (¿se cambió el protocolo? es una versión nueva)")
    if computed_at.date().isoformat() < p.registered_on:
        raise ProtocolRefusedError(f"{key}: el resultado es anterior a la firma del protocolo ({p.registered_on})")
    return p


# ── the eight protocols ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

_COMMON_EXCLUSIONS: Final = (
    "Partidos sin predicción guardada antes del saque o sin el comparador: no entran (poblaciones iguales).",
    "Partidos anteriores a la firma del protocolo: solo validan, no cuentan para el veredicto.",
)
_STOPPING: Final = ("Se mira el veredicto UNA vez, al llegar a la muestra fijada; antes solo se informa el avance, sin declarar éxito ni abandono. "
                    "No se añaden modelos, variables ni segmentos después de la firma.")


def _p(key: str, title: str, question: str, null: str, alternative: str, unit: str, data: str, split: str, metric: str, passes: str,
       rejects: str, sample: str, power: str, segments: tuple[str, ...], secondary: tuple[str, ...] = (), seed: int = 20261126) -> Protocol:
    return Protocol(key=key, version=f"proto-{key.lower()}-v1", title=title, question=question, null=null, alternative=alternative, unit=unit,
                    data=data, split=split, primary_metric=metric, pass_rule=passes, reject_rule=rejects, secondary=secondary, min_sample=sample,
                    power_note=power, exclusions=_COMMON_EXCLUSIONS, stopping=_STOPPING, segments=segments, registered_on=SIGNATURE, seed=seed)


E1: Final = _p(
    "EXP-E1", "Segmentos donde el modelo en bruto iguala al mercado",
    "¿En algún segmento (nivel y tipo de competición, hasta ocho) el modelo en bruto, sin leer el mercado, queda a menos de +0,005 de pérdida "
    "logarítmica del consenso de cierre sin margen?",
    "En todo segmento, la diferencia de pérdida logarítmica (modelo menos cierre) es de +0,005 o más.",
    "En al menos un segmento la diferencia es menor de +0,005.",
    "Un partido de un segmento, con la probabilidad del modelo en bruto y la del consenso de cierre sin margen para los tres resultados del 1X2.",
    "Pronósticos guardados antes del saque y cierre real (RP-1.4, consenso con cuotas de la última hora); solo partidos posteriores a la firma. "
    "Los partidos ya mirados (23-oct a 25-nov) solo validan.",
    "Entrenamiento y validación hasta la firma; prueba intacta: partidos posteriores a la firma.",
    "Diferencia de pérdida logarítmica por segmento (modelo menos cierre real), con intervalo del 95 % por días y corrección de Holm entre segmentos.",
    "Diferencia menor de +0,005 con 1.000 partidos en un segmento, mismo signo en las dos mitades.",
    "Ningún segmento baja de +0,005.",
    "1.000 partidos por segmento (hoy entran unos 36, 9 y 16 al día en los niveles 2, 3 y 4).",
    "Con desviación por partido cercana a 0,10 de pérdida, 1.000 partidos ven una diferencia de unos 0,006; por eso el umbral se juzga con el intervalo.",
    ("nivel 1", "nivel 2", "nivel 3", "nivel 4", "nivel 5", "ligas nacionales", "copas nacionales", "competiciones de selecciones"),
    ("Los cuatro modelos sencillos y el conjunto, cada uno frente al cierre.",))
E2: Final = _p(
    "EXP-E2", "Información de la alineación oficial",
    "¿Una baja clave confirmada en la alineación oficial mueve el resultado más de lo que ya movió el precio previo?",
    "El residuo (resultado menos probabilidad de mercado previa a la alineación) tras una baja clave está dentro de dos errores estándar de cero.",
    "El residuo queda fuera de dos errores estándar.",
    "Un partido con una baja clave confirmada en la alineación oficial.",
    "Alineaciones (87 % de los partidos), bajas confirmadas y precios antes y después de la alineación; solo partidos posteriores a la firma.",
    "Sin ajuste de nada: se mide el residuo. Todo lo posterior a la firma es prueba.",
    "Residuo: resultado menos probabilidad de mercado previa a la alineación.",
    "Residuo fuera de dos errores estándar con 500 casos.",
    "Residuo dentro del error.",
    "500 casos con baja clave confirmada.",
    "Con 500 casos, dos errores estándar del residuo de un resultado binario son unos 4,5 puntos.",
    ("baja clave de un portero", "baja clave de un delantero", "baja clave de un defensa", "baja clave de un centrocampista"))
E3: Final = _p(
    "EXP-E3", "Córneres y tarjetas tras calibrar",
    "¿Los córneres y tarjetas calibrados sin leer el mercado quedan a menos de +0,005 de pérdida logarítmica del mercado de la misma línea?",
    "La diferencia (modelo calibrado menos mercado) es de +0,005 o más en cada familia.",
    "En alguna familia la diferencia es menor de +0,005.",
    "Una selección de córneres o de tarjetas con su línea, ya liquidada.",
    "Selecciones liquidadas (1.688 de córneres y 149 de tarjetas a la firma) y las que se acumulen, contra el mercado de la misma línea.",
    "Hacia delante, día a día: cada día se calibra solo con selecciones liquidadas antes de ese día.",
    "Diferencia de pérdida logarítmica por familia, con intervalo por días y Holm entre familias.",
    "A menos de +0,005 del mercado sin leerlo, con 1.500 selecciones por familia.",
    "Solo iguala al mercado leyéndolo.",
    "1.500 selecciones por familia.",
    "El tamaño es el fijado por la auditoría; no se alarga.",
    ("córneres", "tarjetas"))
E4: Final = _p(
    "EXP-E4", "Modelo jerárquico de tarjetas",
    "¿El modelo jerárquico de tarjetas mejora fuera de muestra al modelo de tarjetas actual?",
    "La pérdida logarítmica fuera de muestra del jerárquico no es menor que la del actual.",
    "El jerárquico mejora fuera de muestra en la mayoría de las competiciones.",
    "Un partido de una competición con 200 partidos o más con estadísticas.",
    "51.796 partidos con estadísticas; 81 competiciones con 200 o más.",
    "Temporada 2024-25 para ajustar; segunda mitad de 2025 para elegir; prueba intacta: partidos de 2026 hasta la firma, nunca usados para elegir.",
    "Pérdida logarítmica fuera de muestra por competición, jerárquico frente al actual.",
    "Mejora fuera de muestra en la mayoría de competiciones, con la mejora mayor que su error.",
    "Mejora menor que el error.",
    "No requiere muestra prospectiva para el veredicto histórico.",
    "81 competiciones: la mayoría exige 41 con la misma señal; Holm entre competiciones.",
    ("competiciones con 200 partidos o más",))
E5: Final = _p(
    "EXP-E5", "Segunda mitad condicionada al descanso",
    "¿Condicionar la 2.ª mitad al marcador del descanso corrige el error del modelo y se acerca al mercado de 1X2 de la 2.ª mitad?",
    "La pérdida del modelo condicionado no queda a menos de +0,010 del mercado.",
    "La pérdida queda a menos de +0,010 del mercado.",
    "Una selección de 1X2 de la 2.ª mitad.",
    "Marcador al descanso (98 % de los partidos) y estadísticas por mitad; frente al mercado, solo partidos posteriores a la firma.",
    "Igual que EXP-E4 para ajustar y elegir; frente al mercado, solo posteriores a la firma.",
    "Diferencia de pérdida logarítmica frente al mercado de 1X2 de la 2.ª mitad y frente al modelo actual.",
    "Pérdida a menos de +0,010 del mercado con 900 selecciones.",
    "Sigue por encima de +0,020.",
    "900 selecciones de 1X2 de 2.ª mitad.",
    "Dos umbrales (+0,010 y +0,020) dejan una zona intermedia que se declara insuficiente.",
    ("1X2 de la 2.ª mitad",))
E6: Final = _p(
    "EXP-E6", "Rachas frente al mercado",
    "¿Tras una racha de 10 partidos el mercado de más/menos se equivoca de forma sistemática?",
    "El residuo tras una racha está dentro del error.",
    "El residuo tras una racha es distinto de cero.",
    "Un partido que sigue a una racha de 10 partidos de un equipo.",
    "Rachas de 10 partidos y todo el consenso de más/menos guardado.",
    "No ajusta nada: se mide el residuo.",
    "Residuo tras racha respecto de la probabilidad de mercado, con intervalo por días y Holm entre tipos de racha.",
    "Residuo distinto de cero tras la racha, con intervalo y mismo signo en las dos mitades.",
    "Residuo dentro del error.",
    "No requiere muestra prospectiva: usa todo el consenso guardado.",
    "Se mide con lo guardado.",
    ("racha de victorias", "racha de derrotas", "racha de partidos con muchos goles", "racha de partidos con pocos goles"))
E7: Final = _p(
    "EXP-E7", "Dependencia entre sucesos del mismo partido",
    "¿Los sucesos de un mismo partido (goles, córneres, tarjetas) dependen entre sí de forma medible?",
    "La razón entre la frecuencia conjunta y el producto de las marginales es 1 en cada estrato.",
    "La razón se aparta de 1 con intervalo.",
    "Un partido, con un par de sucesos y su estrato (competición).",
    "Histórico con goles, córneres y tarjetas.",
    "No ajusta nada: la mitad del histórico estima, la otra mitad comprueba la estabilidad.",
    "Razón entre la frecuencia conjunta y el producto (independencia) por estrato, con intervalo.",
    "Descriptivo: tabla de pares con intervalo por competición.",
    "No aplica.",
    "No requiere muestra prospectiva.",
    "Descriptivo.",
    ("goles-córneres", "goles-tarjetas", "córneres-tarjetas"))
E8: Final = _p(
    "EXP-E8", "Hechos confirmados por dólar",
    "¿Algún criterio de reparto de la investigación da más hechos confirmados por partido y por dólar que el reparto actual?",
    "Ningún criterio supera al reparto actual en hechos confirmados por dólar.",
    "Algún criterio da más hechos confirmados por dólar.",
    "Un partido investigado en una pasada.",
    "Contadores por pasada de 30 días y el coste de cada pasada.",
    "No ajusta nada: 30 días de contadores; después, criterios en paralelo por sorteo estable de partidos.",
    "Hechos confirmados por partido y por dólar, con el coste.",
    "Descriptivo: comparación con coste.",
    "No aplica.",
    "300 partidos por criterio.",
    "Descriptivo, dentro del tope de gasto de la propia investigación.",
    ("reparto actual", "por incertidumbre", "por importancia"))

EXPERIMENTS: Final[dict[str, Protocol]] = {p.key: p for p in (E1, E2, E3, E4, E5, E6, E7, E8)}
"""The eight experiments of the plan, registered with their fingerprint before their first run."""

THRESHOLDS: Final[dict[str, dict[str, Any]]] = {
    "EXP-E1": {"success_below": 0.005, "n_required": 1000},
    "EXP-E3": {"success_below": 0.005, "n_required": 1500},
    "EXP-E5": {"success_below": 0.010, "abandon_at_or_above": 0.020, "n_required": 900},
}
"""The numeric thresholds of the audit (unchanged) that ``difference_verdict`` takes, by experiment."""
