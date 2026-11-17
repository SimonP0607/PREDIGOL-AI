"""The replay bank as a regression test with a preregistered tolerance (IA-136, AD-K04): ``replay-regression-v1`` under the protocol
``AD-K04``. Pure: no database, no clock, no model.

WHAT IT ADDS TO THE BANK. ``fbi.ai.replay.measure`` (``replay-measure-v1``, INT-C02) asks whether the stored answer differs from a replay
no more than two replays differ from each other - a POINT rule that a perfect reproduction passes only a little more than half of the
time. A regression test needs a tolerance fixed before looking: a scope PASSES when the UPPER end of the 95 % interval of that
difference is at most ``TOLERANCE`` (5 points, PROPOSED - the owner signs it), with the validity, the sample and the «nothing on its way»
of INT-C02 unchanged. The interval is the one ``measure`` already reports (bootstrap of the matches, the seed of INT-C02).

BEFORE A VERDICT, THE CAUSE (``diag-v1``). Every NO PASA carries a written cause from a closed list (``CAUSES``), found by splitting the
units of the scope two ways and measuring each part with the same rule:

    route    the stored run was asked in real time or through Batch (the replays always go through Batch)
    model    each replay was answered by the model the stored run had, or by another one (``same_model``)

``via_tiempo_real`` when the real-time part fails the tolerance and the Batch part passes it; ``modelo_distinto`` when the part answered
by another model fails and the part answered by the same model passes; ``validez`` when only the invalid replays fail; ``no_explicada``
when no part explains it; ``muestra_insuficiente_para_explicar`` when the parts are below the protocol's minimum.

THE PROTOCOL'S RULE THAT A TEST HOLDS: no repeating to change a verdict. A measurement over stored runs that an earlier measurement of the
same scope and variant already used is refused (``admissible``); a new measurement uses stored runs that were in none of the earlier ones.

WHEN IT RUNS. Before each change of version of a reader or of the Council's judge (AD-D10): ``due`` names the scopes whose agent version
in force is not the one the last regression measured.

It decides nothing: a verdict switches nothing, and the tolerance is the owner's to sign (a ``umbral`` proposal, IA-139).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fbi.ai.replay import measure

METHOD: Final = "replay-regression-v1"
DIAGNOSIS: Final = "diag-v1"
PROTOCOL_KEY: Final = "AD-K04"
TOLERANCE: Final = 0.05
"""The upper end of the 95 % interval of the difference may be at most 5 points. PROPOSED in the plan (AD-K04); the owner signs it."""
TOLERANCE_STATUS: Final = "propuesta: la firma el dueño"
TARGET: Final = "threshold:fbi.ai.replay.regression.TOLERANCE"
"""What the owner signs, as a ``umbral`` proposal of the registry of IA-139 (``scripts/ia_replay_regression.py propose``)."""
PASS: Final = measure.PASS
FAIL: Final = measure.FAIL
INSUFFICIENT: Final = measure.INSUFFICIENT
CAUSES: Final[tuple[str, ...]] = ("via_tiempo_real", "modelo_distinto", "validez", "no_explicada", "muestra_insuficiente_para_explicar")
CAUSE_ES: Final[Mapping[str, str]] = {
    "via_tiempo_real": "las ejecuciones guardadas en tiempo real no se reproducen y las guardadas por Batch sí: la diferencia es de la vía",
    "modelo_distinto": "las repeticiones que respondió un modelo distinto del guardado no se reproducen y las del mismo sí: cambió el modelo",
    "validez": "las repeticiones que no se sostienen superan su límite, aunque las palabras sí se reproduzcan",
    "no_explicada": "ninguna partición (vía ni modelo) explica la diferencia: el proveedor no repite su respuesta",
    "muestra_insuficiente_para_explicar": "las particiones no alcanzan 200 unidades de 30 partidos: no se puede decir por qué",
}
ROUTES: Final[tuple[str, ...]] = ("batch", "tiempo_real")


def same_model(stored: str | None, replay: str | None) -> bool | None:
    """Whether a replay was answered by the stored run's model: equal, or one is the other with a dated suffix (``claude-x`` and
    ``claude-x-20261001``). None when either is unknown."""
    if not stored or not replay:
        return None
    a, b = stored.strip().lower(), replay.strip().lower()
    return a == b or a.startswith(b + "-") or b.startswith(a + "-")


def upper(assessment: Mapping[str, Any]) -> float | None:
    ci = assessment.get("difference_ci95")
    return None if not ci else float(ci[1])


def within(assessment: Mapping[str, Any], *, tolerance: float = TOLERANCE) -> bool | None:
    """The tolerance alone: None without an interval."""
    hi = upper(assessment)
    return None if hi is None else hi <= tolerance


def invalid_fails(assessment: Mapping[str, Any]) -> bool:
    replay = assessment.get("invalid_replay")
    stored = assessment.get("invalid_stored") or 0.0
    return replay is not None and (replay > measure.MAX_INVALID or replay > stored + measure.INVALID_MARGIN)


def _sized(assessment: Mapping[str, Any], *, min_units: int, min_matches: int) -> bool:
    return int(assessment.get("complete_units") or 0) >= min_units and int(assessment.get("matches") or 0) >= min_matches


def judge(assessment: Mapping[str, Any], *, tolerance: float = TOLERANCE, min_units: int = measure.MIN_UNITS,
          min_matches: int = measure.MIN_MATCHES) -> dict[str, Any]:
    """The regression verdict of one scope from its ``measure.assess``: INSUFICIENTE below the sample or with asks on their way; PASA
    when the upper end of the interval is within the tolerance and the replays stand as INT-C02 asks; NO PASA otherwise, with why."""
    reasons: list[str] = []
    if not _sized(assessment, min_units=min_units, min_matches=min_matches):
        reasons.append(f"insufficient: {assessment.get('complete_units', 0)} complete units of {assessment.get('matches', 0)} matches; "
                       f"{min_units} of {min_matches} needed")
    if assessment.get("open"):
        reasons.append(f"{assessment['open']} ask(s) still on their way")
    hi = upper(assessment)
    tolerated = within(assessment, tolerance=tolerance)
    if tolerated is False:
        reasons.append(f"the upper end of the 95 % interval ({hi:+.4f}) is above the tolerance ({tolerance:.2f})")
    if invalid_fails(assessment):
        reasons.append("the replays do not stand more often than INT-C02 allows")
    if reasons and (reasons[0].startswith("insufficient") or assessment.get("open")):
        verdict = INSUFFICIENT
    elif tolerated is None:
        verdict = INSUFFICIENT
        reasons.append("no interval: fewer than two matches")
    else:
        verdict = PASS if not reasons else FAIL
    return {"method": METHOD, "verdict": verdict, "tolerance": tolerance, "tolerance_status": TOLERANCE_STATUS, "upper": hi,
            "within_tolerance": tolerated, "point_rule": assessment.get("verdict"), "reasons": reasons, "decides": False}


@dataclass(frozen=True, slots=True)
class Strata:
    """How the stored runs of one scope were asked and answered: its route (``batch`` or ``tiempo_real``) and, per repetition, whether
    the model that answered is the stored one (None: unknown)."""

    route: Mapping[int, str]
    model: Mapping[int, tuple[bool | None, bool | None]]


def _part(units: Sequence[measure.Unit], answers: measure.Answers, *, draws: int) -> dict[str, Any]:
    a = measure.assess(units, answers, draws=draws)
    return {k: a.get(k) for k in ("complete_units", "matches", "difference", "difference_ci95", "change_stored", "change_repeat")}


def _subset(units: Sequence[measure.Unit], items: set[int]) -> list[measure.Unit]:
    return [u for u in units if u.item in items]


def diagnose(units: Sequence[measure.Unit], strata: Strata, *, tolerance: float = TOLERANCE, min_units: int = measure.MIN_UNITS,
             min_matches: int = measure.MIN_MATCHES, replays_invalid: bool = False, draws: int = measure.BOOTSTRAP) -> dict[str, Any]:
    """``diag-v1``: the two partitions of a scope, each measured with the same interval, and the cause they point to. The validity of
    the replays is not split (an invalid replay has no units): ``replays_invalid`` says whether the scope failed it."""
    empty = measure.Answers(0, 0, 0, 0)
    items = {u.item for u in units}
    by_route = {r: {i for i in items if strata.route.get(i) == r} for r in ROUTES}
    same = {i for i in items if all(x is True for x in strata.model.get(i, (None, None)))}
    other = {i for i in items if any(x is False for x in strata.model.get(i, (None, None)))}
    parts = {"route": {r: _part(_subset(units, s), empty, draws=draws) for r, s in by_route.items()},
             "model": {"mismo": _part(_subset(units, same), empty, draws=draws),
                       "distinto": _part(_subset(units, other), empty, draws=draws)}}

    def ok(p: Mapping[str, Any]) -> bool | None:
        if not _sized(p, min_units=min_units, min_matches=min_matches) or not p.get("difference_ci95"):
            return None
        return float(p["difference_ci95"][1]) <= tolerance

    batch, live = ok(parts["route"]["batch"]), ok(parts["route"]["tiempo_real"])
    mine, theirs = ok(parts["model"]["mismo"]), ok(parts["model"]["distinto"])
    whole = measure.assess(units, empty, draws=draws)
    words_fail = within(whole, tolerance=tolerance) is False
    if not words_fail and replays_invalid:
        cause = "validez"
    elif live is False and batch is True:
        cause = "via_tiempo_real"
    elif theirs is False and mine is True:
        cause = "modelo_distinto"
    elif None in (batch, live) and None in (mine, theirs):
        cause = "muestra_insuficiente_para_explicar"
    else:
        cause = "no_explicada"
    return {"method": DIAGNOSIS, "cause": cause, "cause_es": CAUSE_ES[cause], "parts": parts,
            "items": {"batch": len(by_route["batch"]), "tiempo_real": len(by_route["tiempo_real"]), "mismo_modelo": len(same),
                      "otro_modelo": len(other)}}


def admissible(items: Iterable[int], earlier: Iterable[Iterable[int]]) -> tuple[bool, list[int]]:
    """The protocol's rule: a regression measurement may not reuse a stored run that an earlier measurement of the same scope and
    variant already used - repeating over the same runs could only change a verdict by chance. (allowed, the reused runs)."""
    mine = set(items)
    reused = sorted(mine & {i for e in earlier for i in e})
    return (bool(mine) and not reused), reused


def due(measured: Mapping[str, str], in_force: Mapping[str, str]) -> list[dict[str, str | None]]:
    """The scopes a regression has to be run for again: those whose agent version in force (a reader, or the Council that judges) is
    not the version the last regression measured, or that were never measured."""
    return [{"scope": s, "measured": measured.get(s), "in_force": v} for s, v in sorted(in_force.items()) if measured.get(s) != v]


def run_ids(units: Iterable[measure.Unit]) -> list[int]:
    return sorted({u.item for u in units})


__all__ = ["CAUSES", "CAUSE_ES", "DIAGNOSIS", "FAIL", "INSUFFICIENT", "METHOD", "PASS", "PROTOCOL_KEY", "ROUTES", "TARGET", "TOLERANCE",
           "TOLERANCE_STATUS", "Strata", "admissible", "diagnose", "due", "invalid_fails", "judge", "run_ids", "same_model", "upper", "within"]
