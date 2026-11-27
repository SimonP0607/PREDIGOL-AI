"""The acceptance of the joint probability of a parlay, fixed BEFORE the prospective window is measured (plan RP-11.1 and RP-11.3, the owner's decision of 27-nov-2026,
``parlay-acceptance-v1``).

The historical repetition (``fbi.parlays.replay``) showed an optimism of 5.78 points for the joint the shadow says and 2.42 for the one that reads the market (60 days, 10 of them
with settled legs). Nothing here makes that figure acceptable and nothing adjusts the criterion to it: the criterion below was written down after seeing it and is applied to it as it
stands (it does not pass), and the prospective window starts on the day of the signature, so what was seen before never counts for it.

THE CRITERION (the owner's):

* OPTIMISM, the joint said minus the frequency that came in, is at most ``MAX_OPTIMISM`` = 2 percentage points;
* its interval of 95 %, by resampling whole days, is compatible with zero (it holds zero): a joint that is too pessimistic is not calibrated either;
* the window has at least ``MIN_DAYS`` = 30 DISTINCT days with a settled parlay, and at least ``MIN_SETTLED`` = 100 settled parlays (a parlay with a void leg is left out: its
  joint was of other legs);
* the HISTORICAL repetition needs ``MIN_COMBINATIONS`` = 1,500 combinations (the plan's) and the same optimism and interval; it needs no 30 days (it is the history).

THE ESTIMATORS the shadow stores for every parlay (``intel.parlays_v6``) are each judged by the same criterion on the same parlays: ``p_joint`` (the one it says, and the one the door of the
parlays reads), ``p_market_joint`` (the product of the legs' market probabilities), ``p_product`` (the product of the model's, without the correction for dependence) and
``p_joint_low`` (the pessimistic one, secondary). Only ``p_joint`` opens the door. The estimator that is said changes only by a NEW VERSION of the engine, and a new version opens a new
window: the 30 days are counted from the first day it built a parlay. If after a window the market's joint meets the criterion and the model's does not, the joint to say is the market's
(a change of version, not an adjustment of numbers). No probability is shrunk, scaled or shifted to pass.

The verdict is arithmetic: ``cumple``, ``no_cumple`` or ``pendiente`` (a window with fewer days or parlays than the minimum says nothing, and is never stretched). Pure: no database, no clock.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal

from fbi.research.protocol import Protocol

VERSION: Final = "parlay-acceptance-v1"
FROZEN_ON: Final = date(2026, 11, 27)
"""The day the criterion is registered: the prospective window counts the parlays of this day on."""
MAX_OPTIMISM: Final = 0.02
MIN_DAYS: Final = 30
MIN_SETTLED: Final = 100
MIN_COMBINATIONS: Final = 1500
ESTIMATORS: Final = ("p_joint", "p_market_joint", "p_product", "p_joint_low")
"""What the shadow stores for each parlay; the first is the one it says."""
SAID: Final = ESTIMATORS[0]
BOOTSTRAP: Final = 2000
SEED: Final = 20261127

Verdict = Literal["cumple", "no_cumple", "pendiente"]

PROTOCOL: Final = Protocol(
    key="PARLAY-P1",
    version="proto-parlay-p1-v1",
    title="Fiabilidad prospectiva de la conjunta de un parlay",
    question="¿La probabilidad conjunta que el sistema dice de un parlay en sombra se queda a 2 puntos o menos de la frecuencia con que acierta, con un intervalo compatible con cero?",
    null="El optimismo de la conjunta (dicha menos ocurrida) es mayor de 2 puntos, o su intervalo del 95 % por días no contiene el cero.",
    alternative="El optimismo es de 2 puntos o menos y el intervalo contiene el cero.",
    unit="Un parlay en sombra de la regla vigente (hasta tres selecciones de partidos y equipos distintos), liquidado como ganado o perdido.",
    data=(
        "Los parlays que el sistema construye en la sombra (`intel.parlays_v6`) desde el 27-nov-2026, con la conjunta guardada al construirlos y el resultado de sus selecciones. "
        "La repetición histórica anterior (optimismo de 5,78 puntos con 2,52 a 11,10 de intervalo) no cuenta para esta ventana."
    ),
    split="No ajusta nada: se mide lo guardado. La ventana empieza el día de la firma, o el primer día en que un motor nuevo construye un parlay.",
    primary_metric="Optimismo = media de la conjunta dicha menos la proporción de parlays acertados, con intervalo del 95 % por remuestreo de días enteros.",
    pass_rule="Optimismo de 2 puntos o menos, intervalo que contiene el cero, 30 días distintos o más y 100 parlays liquidados o más.",
    reject_rule="Optimismo mayor de 2 puntos o intervalo que no contiene el cero, con la muestra y los días mínimos.",
    secondary=("La misma medida para la conjunta del mercado, la del producto sin corrección y la pesimista.", "El optimismo por banda de la conjunta."),
    min_sample="30 días distintos con un parlay liquidado y 100 parlays liquidados.",
    power_note="Con 100 parlays que aciertan alrededor de un 10 %, dos errores estándar del acierto son unos 6 puntos: el intervalo, no el punto, decide.",
    exclusions=("Parlays con una selección anulada: su conjunta era de otras selecciones.", "Parlays anteriores a la firma.", "Parlays todavía sin liquidar."),
    stopping=(
        "Se mira el veredicto cuando la ventana tiene los días y los parlays mínimos; antes solo se informa el avance. Cambiar el estimador que se dice es una versión nueva del motor y abre "
        "una ventana nueva: no se reparten ni se escalan probabilidades para pasar el criterio."
    ),
    segments=("conjunta dicha", "conjunta del mercado", "producto sin corrección", "pesimista"),
    registered_on=FROZEN_ON.isoformat(),
    seed=SEED,
)


@dataclass(frozen=True, slots=True)
class Reading:
    """The criterion applied to one estimator: how many parlays and days, the optimism with its interval and the verdict."""

    estimator: str
    verdict: Verdict
    settled: int
    days: int
    optimism: float | None
    low: float | None
    high: float | None
    why: str

    def as_json(self) -> dict[str, Any]:
        return {"estimator": self.estimator, "verdict": self.verdict, "settled": self.settled, "days": self.days, "optimism": self.optimism, "low": self.low, "high": self.high,
                "why": self.why}


def _interval(said_minus_won: Mapping[date, Sequence[float]], *, seed: int = SEED, rounds: int = BOOTSTRAP) -> tuple[float, float]:
    keys = sorted(said_minus_won)
    sums = [sum(said_minus_won[k]) for k in keys]
    counts = [len(said_minus_won[k]) for k in keys]
    rng = random.Random(seed)
    n = len(keys)
    means: list[float] = []
    for _ in range(rounds):
        picks = [rng.randrange(n) for _ in range(n)]
        means.append(sum(sums[i] for i in picks) / sum(counts[i] for i in picks))
    means.sort()
    return means[int(0.025 * (rounds - 1))], means[-(int(0.025 * (rounds - 1)) + 1)]


def judge_figures(*, optimism: float, low: float | None, high: float | None) -> bool:
    """The criterion on its own: optimism of ``MAX_OPTIMISM`` or less and an interval that holds zero. An interval that is missing is not compatible with anything."""
    if low is None or high is None:
        return False
    return optimism <= MAX_OPTIMISM and low <= 0.0 <= high


def judge_window(rows: Sequence[Mapping[str, Any]], estimator: str, *, since: date = FROZEN_ON) -> Reading:
    """One estimator over the settled parlays of the window. ``rows`` carry ``day`` (a date or an ISO string), ``status`` (``WON`` or ``LOST``; anything else is left out) and the
    estimator's value; a parlay before ``since`` is left out and so is one with no value for the estimator."""
    if estimator not in ESTIMATORS:
        raise ValueError(f"{estimator} no es un estimador guardado")
    by_day: dict[date, list[float]] = defaultdict(list)
    for r in rows:
        day = r["day"] if isinstance(r["day"], date) else date.fromisoformat(str(r["day"])[:10])
        value = r.get(estimator)
        if r.get("status") not in ("WON", "LOST") or value is None or day < since:
            continue
        by_day[day].append(float(value) - (1.0 if r["status"] == "WON" else 0.0))
    settled = sum(len(v) for v in by_day.values())
    days = len(by_day)
    if settled < MIN_SETTLED or days < MIN_DAYS:
        return Reading(estimator, "pendiente", settled, days, None, None, None, f"{settled} de {MIN_SETTLED} parlays liquidados en {days} de {MIN_DAYS} días: no se juzga antes")
    optimism = sum(sum(v) for v in by_day.values()) / settled
    low, high = _interval(by_day)
    ok = judge_figures(optimism=optimism, low=low, high=high)
    if ok:
        why = f"optimismo {optimism * 100:.2f} puntos (intervalo {low * 100:.2f} a {high * 100:.2f}): dentro de {MAX_OPTIMISM * 100:.0f} puntos y compatible con cero"
    elif optimism > MAX_OPTIMISM:
        why = f"optimismo {optimism * 100:.2f} puntos, por encima de {MAX_OPTIMISM * 100:.0f}"
    else:
        why = f"el intervalo {low * 100:.2f} a {high * 100:.2f} puntos no contiene el cero"
    return Reading(estimator, "cumple" if ok else "no_cumple", settled, days, optimism, low, high, why)


def judge_all(rows: Sequence[Mapping[str, Any]], *, since: date = FROZEN_ON) -> dict[str, Reading]:
    """Every stored estimator over the same parlays."""
    return {e: judge_window(rows, e, since=since) for e in ESTIMATORS}


def historical(*, combinations: int, optimism: float | None, interval: tuple[float, float] | None) -> bool | None:
    """``within_bound`` of the historical repetition: None when it cannot be decided (fewer than ``MIN_COMBINATIONS`` or no figure), otherwise the criterion applied to the figure as it stands."""
    if combinations < MIN_COMBINATIONS or optimism is None:
        return None
    low, high = (None, None) if interval is None else interval
    return judge_figures(optimism=optimism, low=low, high=high)


__all__ = ["BOOTSTRAP", "ESTIMATORS", "FROZEN_ON", "MAX_OPTIMISM", "MIN_COMBINATIONS", "MIN_DAYS", "MIN_SETTLED", "PROTOCOL", "SAID", "SEED", "VERSION", "Reading", "Verdict",
           "historical", "judge_all", "judge_figures", "judge_window"]
