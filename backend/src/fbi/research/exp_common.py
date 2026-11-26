"""What the experiments of the plan that compare a model with a market SEGMENT BY SEGMENT have in common (RP-9.1, RP-9.3): the verdict over the segments.

Each segment (a level of competition, a family of markets) has its series of differences of loss (model minus comparator, one per match or selection, with its
day). The rules are those of ``fbi.research.exp_protocol`` and are not repeated here: a segment is judged only when it has the sample fixed in the protocol, its
interval is by days, its p-value is corrected by Holm over the segments judged, and both halves of the period must lie on the same side of the threshold. This
module only turns the verdicts of the segments into the verdict of the experiment:

* SUCCESS if any segment succeeds (the question is "in which segment, if any"): the segment with the smallest mean gives its numbers;
* ABANDONMENT only when EVERY segment the protocol names has its sample and every one abandons: while one segment has not reached its sample the experiment
  has not shown that no segment gets there;
* INSUFFICIENT otherwise: nothing is declared, and no segment is added or dropped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Final

from fbi.research import exp_protocol
from fbi.research.exp_protocol import Judgement

NAN: Final = float("nan")


def judge_segments(series: Mapping[str, tuple[Sequence[float], Sequence[date]]], *, names: Sequence[str], required: int, thresholds: Mapping[str, Any], seed: int,
                   abandon_reason: str) -> tuple[Judgement, dict[str, Any]]:
    """The verdict of an experiment over its segments, and the figures of each segment (``names`` are all the segments the protocol names, in its order)."""
    success_below = float(thresholds["success_below"])
    abandon_at = thresholds.get("abandon_at_or_above")
    ready = {s: v for s, v in series.items() if len(v[0]) >= required}
    p_values = {s: exp_protocol.one_sided_p(v, d, below=success_below, seed=seed) for s, (v, d) in ready.items()}
    adjusted = exp_protocol.holm(p_values) if p_values else {}
    judged = {s: exp_protocol.difference_verdict(v, d, success_below=success_below, n_required=required, seed=seed, adjusted_p=adjusted[s],
                                                 abandon_at_or_above=None if abandon_at is None else float(abandon_at)) for s, (v, d) in ready.items()}
    figures: dict[str, Any] = {}
    for s in names:
        j = judged.get(s)
        figures[s] = {"n": len(series[s][0]) if s in series else 0, "verdict": None if j is None else j.verdict, "mean": None if j is None else j.mean,
                      "low": None if j is None else j.low, "high": None if j is None else j.high, "adjusted_p": None if j is None else j.adjusted_p}
    wins = {s: j for s, j in judged.items() if j.verdict == "exito"}
    if wins:
        best = min(wins, key=lambda s: wins[s].mean)
        j = wins[best]
        return Judgement("exito", f"{best}: {j.reason}", j.mean, j.low, j.high, j.n, j.adjusted_p), figures
    if judged and all(s in judged for s in names) and all(j.verdict == "abandono" for j in judged.values()):
        j = min(judged.values(), key=lambda x: x.mean)
        return Judgement("abandono", abandon_reason, j.mean, j.low, j.high, j.n, j.adjusted_p), figures
    if judged:
        j = min(judged.values(), key=lambda x: x.mean)
        return Judgement("insuficiente", "con la muestra fijada el intervalo aún admite las dos respuestas, o faltan segmentos con su muestra",
                         j.mean, j.low, j.high, j.n, j.adjusted_p), figures
    top = max((len(v[0]) for v in series.values()), default=0)
    return Judgement("insuficiente", f"muestra {top} de {required}", NAN, NAN, NAN, top), figures


__all__ = ["judge_segments"]
