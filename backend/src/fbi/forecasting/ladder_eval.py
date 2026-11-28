"""RP-2.2: the criterion of the coherent ladder, registered before any window is measured (``ladder-acceptance-v1``, protocol ``LAD-P1``). Pure.

``fbi.forecasting.ladder`` says what the figures of a market would be if its lines were one distribution. This module says when that answer may replace the
stored figures: when it is not worse at predicting what happened, and it makes the matches publishable. The comparison is on the same figures, the same
matches and the same outcomes: the unit is a figure of a line with a settled outcome (it won, it was returned, or it lost), scored by the log of the
probability the figure gave to what happened. The difference is projected minus stored, so negative is better. The interval is by whole days.

The variant that is judged is ``pooled`` (named here, before the data); ``half`` is reported next to it and decides nothing. Nothing is scaled, shrunk or
shifted to pass: a failing window is a result, and a different rule is a new version with a new window.

The verdict is arithmetic: ``cumple``, ``no_cumple`` or ``pendiente`` (a window with fewer days or figures than the minimum says nothing and is never
stretched).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal

from fbi.research.protocol import Protocol

VERSION: Final = "ladder-acceptance-v1"
FROZEN_ON: Final = date(2026, 11, 27)
VARIANT: Final = "pooled"
"""The variant the criterion judges; ``half`` is reported and decides nothing."""
MARGIN: Final = 0.001
"""Non-inferiority margin, in nats: the projected figures may lose up to this much log loss per figure and still pass."""
MIN_DAYS: Final = 30
MIN_FIGURES: Final = 5000
MIN_PUBLISHABLE_GAIN: Final = 0.5
"""Of the matches that the battery refuses on lines (tests 3 and 7), at least this share must be publishable after the projection."""
BOOTSTRAP: Final = 2000
SEED: Final = 20261127
FLOOR: Final = 1e-9
"""A figure never gives less than this to what happened, so one certain-and-wrong figure cannot make the mean infinite."""

Verdict = Literal["cumple", "no_cumple", "pendiente"]
STATES: Final = ("win", "push", "lose")

PROTOCOL: Final = Protocol(
    key="LAD-P1",
    version="proto-lad-p1-v1",
    title="Escalera de líneas coherente",
    question="¿Cifras de líneas de goles y hándicap leídas de una sola escalera coherente pronostican igual de bien que las cifras guardadas, línea por línea, y hacen publicables los partidos que hoy la batería rechaza por contradecirse entre líneas?",
    null="La pérdida logarítmica de las cifras proyectadas es peor que la de las guardadas en más de 0,001 nats por cifra (límite superior del intervalo del 95 % por días), o la proyección deja sin publicar a más de la mitad de los partidos que la batería rechaza por las pruebas 3 y 7.",
    alternative="La pérdida de las cifras proyectadas no es peor que la de las guardadas en más de 0,001 nats por cifra, y al menos la mitad de los partidos rechazados por las pruebas 3 y 7 quedan publicables.",
    unit="Una cifra de una línea de más/menos (total, equipo o mitad) o de hándicap de un partido liquidado, con tres estados posibles: gana, se devuelve o pierde.",
    data=(
        "Las cifras de pronóstico `forecast-v2` guardadas en la sombra de la escalera desde el 27-nov-2026 (la cifra guardada y la proyectada de cada línea, calculadas con los mismos datos en el mismo instante), "
        "con el resultado liquidado del partido. La medición con partidos ya jugados no existe: el modelo y el mercado de entonces no se reconstruyen."
    ),
    split="No ajusta nada: la proyección no tiene parámetros que aprender; se compara lo guardado con lo proyectado en los mismos partidos.",
    primary_metric="Diferencia media de la pérdida logarítmica por cifra (proyectada menos guardada, variante `pooled`), con intervalo del 95 % por remuestreo de días enteros; y la proporción de partidos rechazados por las pruebas 3 y 7 que quedan publicables.",
    pass_rule="Límite superior del intervalo de la diferencia ≤ 0,001 nats, 30 días distintos o más, 5.000 cifras liquidadas o más, y al menos la mitad de los partidos rechazados por las pruebas 3 y 7 publicables tras la proyección.",
    reject_rule="Límite superior del intervalo > 0,001 nats, o menos de la mitad de los partidos rechazados quedan publicables, con los días y las cifras mínimas.",
    secondary=(
        "La misma medida para la variante `half`.",
        "La diferencia por mercado y por tipo de línea (media, entera, cuarto).",
        "El desplazamiento de las cifras (mediana, percentil 90, máximo).",
    ),
    min_sample="30 días distintos con partidos liquidados y 5.000 cifras liquidadas.",
    power_note="Con una desviación de la diferencia por cifra de unos 0,05 nats y 5.000 cifras, el error estándar es de unos 0,0007 nats: el intervalo, no el punto, decide.",
    exclusions=(
        "Cifras de líneas cuyo resultado es una anulación del partido.",
        "Líneas sin la escalera completa (se informan como `kept` y no entran en la pérdida).",
        "Partidos anteriores a la firma.",
    ),
    stopping=(
        "El veredicto se mira cuando la ventana tiene los días y las cifras mínimas; antes solo se informa el avance. No se publica ninguna cifra proyectada antes de que cumpla, y cambiar la regla de la escalera "
        "es una versión nueva con ventana nueva: no se escalan probabilidades para pasar el criterio."
    ),
    segments=("OU", "OU_HOME", "OU_AWAY", "OU_1H", "OU_2H", "AH"),
    registered_on=FROZEN_ON.isoformat(),
    seed=SEED,
)


def log_loss(win: float, push: float, state: str) -> float:
    """-log of the probability a figure gave to what happened (``win``, ``push`` or ``lose``)."""
    if state not in STATES:
        raise ValueError(f"{state} no es un resultado de línea")
    p = win if state == "win" else push if state == "push" else 1.0 - win - push
    return -math.log(max(p, FLOOR))


@dataclass(frozen=True, slots=True)
class Reading:
    """The criterion applied to one variant."""

    variant: str
    verdict: Verdict
    figures: int
    days: int
    difference: float | None
    low: float | None
    high: float | None
    publishable_share: float | None
    why: str

    def as_json(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "verdict": self.verdict,
            "figures": self.figures,
            "days": self.days,
            "difference": self.difference,
            "low": self.low,
            "high": self.high,
            "publishable_share": self.publishable_share,
            "why": self.why,
        }


def _interval(
    by_day: Mapping[date, Sequence[float]], *, seed: int = SEED, rounds: int = BOOTSTRAP
) -> tuple[float, float]:
    keys = sorted(by_day)
    sums = [sum(by_day[k]) for k in keys]
    counts = [len(by_day[k]) for k in keys]
    rng = random.Random(seed)
    n = len(keys)
    means: list[float] = []
    for _ in range(rounds):
        picks = [rng.randrange(n) for _ in range(n)]
        means.append(sum(sums[i] for i in picks) / sum(counts[i] for i in picks))
    means.sort()
    cut = int(0.025 * (rounds - 1))
    return means[cut], means[-(cut + 1)]


def judge_figures(*, high: float | None, publishable_share: float | None) -> bool:
    """The criterion on its own. A missing interval or share is not compatible with anything."""
    if high is None or publishable_share is None:
        return False
    return high <= MARGIN and publishable_share >= MIN_PUBLISHABLE_GAIN


def judge_window(
    rows: Sequence[Mapping[str, Any]],
    *,
    publishable_share: float | None,
    variant: str = VARIANT,
    since: date = FROZEN_ON,
) -> Reading:
    """One variant over the settled figures of the window. ``rows`` carry ``day``, ``state`` (``win``, ``push`` or ``lose``; anything else is left out), the stored figure (``win``, ``push``)
    and the projected one (``p_win``, ``p_push``); a row before ``since`` is left out. ``publishable_share`` is measured apart (matches refused by tests 3 and 7 that the projection makes publishable)."""
    by_day: dict[date, list[float]] = defaultdict(list)
    for r in rows:
        day = r["day"] if isinstance(r["day"], date) else date.fromisoformat(str(r["day"])[:10])
        if r.get("state") not in STATES or day < since:
            continue
        by_day[day].append(
            log_loss(float(r["p_win"]), float(r["p_push"]), r["state"])
            - log_loss(float(r["win"]), float(r["push"]), r["state"])
        )
    figures = sum(len(v) for v in by_day.values())
    days = len(by_day)
    if figures < MIN_FIGURES or days < MIN_DAYS:
        return Reading(
            variant,
            "pendiente",
            figures,
            days,
            None,
            None,
            None,
            publishable_share,
            f"{figures} de {MIN_FIGURES} cifras liquidadas en {days} de {MIN_DAYS} días: no se juzga antes",
        )
    diff = sum(sum(v) for v in by_day.values()) / figures
    low, high = _interval(by_day)
    ok = judge_figures(high=high, publishable_share=publishable_share)
    share = 0.0 if publishable_share is None else publishable_share
    if ok:
        why = f"diferencia {diff:.5f} nats por cifra (intervalo {low:.5f} a {high:.5f}) dentro del margen de {MARGIN} y {share * 100:.0f} % de los rechazados quedan publicables"
    elif high > MARGIN:
        why = f"el intervalo {low:.5f} a {high:.5f} pasa del margen de {MARGIN} nats"
    else:
        why = f"solo {share * 100:.0f} % de los rechazados quedan publicables (se pide {MIN_PUBLISHABLE_GAIN * 100:.0f} %)"
    return Reading(
        variant,
        "cumple" if ok else "no_cumple",
        figures,
        days,
        diff,
        low,
        high,
        publishable_share,
        why,
    )


def publishable_share(
    before_publishable: Sequence[bool], after_publishable: Sequence[bool]
) -> float | None:
    """Of the matches that were not publishable before, the share that are after. None when none was refused (nothing to fix)."""
    refused = [a for b, a in zip(before_publishable, after_publishable, strict=True) if not b]
    return sum(refused) / len(refused) if refused else None


__all__ = [
    "BOOTSTRAP",
    "FLOOR",
    "FROZEN_ON",
    "MARGIN",
    "MIN_DAYS",
    "MIN_FIGURES",
    "MIN_PUBLISHABLE_GAIN",
    "PROTOCOL",
    "SEED",
    "VARIANT",
    "VERSION",
    "Reading",
    "judge_figures",
    "judge_window",
    "log_loss",
    "publishable_share",
]
