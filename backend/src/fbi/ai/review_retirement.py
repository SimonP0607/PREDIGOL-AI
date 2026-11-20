"""The conditioned retirement of ``review-v2`` (IA-125, AD-D11 of the plan of the definitive architecture 2026): ``review-retire-v1``. Pure.

``review-v2`` (``fbi.ai.review``, Sonnet and Opus at L3) is the production review of the AI layer: it cost US$ 39,54 from 1 to 15 Nov 2026,
48,7 % of all the spend, and approved 7 of 870 reviews in 14 days. The plan retires it ONLY when the new path - ``decision-v2``, the rules
and the reduced Council - does not do worse against the close on the same selections, by a criterion and a sample fixed before looking.
THIS PIECE RETIRES NOTHING: it leaves the criterion (``PROTOCOL``), the comparison (``compare``), the measure of what removing it would
change in the combined review that decision-v1's filter 6 and rule D1 of the picks' user status (``user-status-v2``) read (``effect_of_removal``) and the
switch with its steps. Every step past ``on`` is the owner's, signed, once the criterion is met; ``on`` restores today's path.

THE SWITCH (``FBI_REVIEW_V2``, ``AiSettings.review_v2``), read by ``fbi.ai.cycle`` where the production review is asked:

    on        today's path, byte for byte (the default; any word not understood is ``on``)
    no_opus   step 1: the review never escalates to the strong model (no L3 tier, no arbitration of a contradiction by Opus); the rest as on
    sample    step 2: as no_opus, and the model reviews only the selections of a fixed random share (``SAMPLE_SHARE``, ``in_sample``):
              the control group the comparison keeps measuring; the others are reviewed by the rules alone
    off       step 3: the rules alone (``rules-review-v1``); no model review is asked and none is carried

Every row of ``ai.pick_reviews`` stays as it is in every step.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final, Literal

import numpy as np

VERSION: Final = "review-retire-v1"
KEY: Final = "AD-D11"
"""Its key in the register of the owner's signatures (IA-145: ``fbi.protosign.records.D11``, ``python -m scripts.ia_protocols show --key
AD-D11``). The record there is ``PROTOCOL`` word for word and the control of step ``sample``; ``tests/unit/test_protocol_signatures.py``
holds them equal."""
Step = Literal["on", "no_opus", "sample", "off"]
STEPS: Final[tuple[Step, ...]] = ("on", "no_opus", "sample", "off")
DEFAULT: Final[Step] = "on"

SAMPLE_SHARE: Final = Decimal("0.20")
"""Step 2: the share of the selections the model still reviews, as the control of the comparison (proposed; the owner signs it)."""
SAMPLE_SALT: Final = "review-v2-control-v1"
BUCKETS: Final = 10_000

PROTOCOL: Final[Mapping[str, Any]] = {
    "version": VERSION,
    "status": "propuesto: lo firma el dueño antes de mirar la ventana",
    "population": "las selecciones que review-v2 revisó con modelo (ai.pick_reviews, engine llm, status ok) y que decision-v2 decidió en "
                  "sombra antes del saque, con su evaluación eval-sel-v1 y un precio de cierre (clv-v1)",
    "reference": "review-v2: la selección se queda cuando la revisión combinada más reciente antes del saque es APPROVE",
    "new_path": "decision-v2 + reglas + Council reducido: la selección se queda cuando decision-v2 la toma (taken de eval-sel-v1)",
    "metric": "diferencia pareada, por selección examinada, del valor frente al cierre de lo que cada camino deja pasar: "
              "clv x (se queda en el camino nuevo - se queda en review-v2)",
    "interval": "IC95 bilateral por remuestreo de días enteros de Bogotá (2.000 réplicas, semilla fija)",
    "margin": "0.005",
    "rule": "NO_INFERIOR si el extremo inferior del IC95 es mayor o igual que -margen; INFERIOR si no; INSUFICIENTE bajo la muestra",
    "min_selections": 300,
    "min_days": 14,
    "seed": 20261117,
    "replicates": 2000,
    "window": "las 4 semanas siguientes a la firma; nada anterior a la firma cuenta",
}
"""The non-inferiority protocol, PRE-REGISTERED here before any window is read. Its figures are proposals of the plan (the margin is half
a point of CLV per selection examined; the sample is the validation board's 300, AD-K02) until the owner signs them."""
MARGIN: Final = Decimal(str(PROTOCOL["margin"]))
MIN_SELECTIONS: Final = int(PROTOCOL["min_selections"])
MIN_DAYS: Final = int(PROTOCOL["min_days"])
SEED: Final = int(PROTOCOL["seed"])
REPLICATES: Final = int(PROTOCOL["replicates"])
LEVEL: Final = 0.95
VERDICTS: Final[tuple[str, ...]] = ("NO_INFERIOR", "INFERIOR", "INSUFICIENTE")


# -- the switch -------------------------------------------------------------------------------------------------------------------------

def step_of(raw: str | None) -> Step:
    """``FBI_REVIEW_V2``: one of ``STEPS``; anything else is ``on``."""
    word = (raw or "").strip().lower()
    for s in STEPS:
        if word == s:
            return s
    return DEFAULT


def escalates(step: str) -> bool:
    """Whether the review may escalate to the strong model (L3, and the arbitration of a contradiction): only ``on``."""
    return step == "on"


def tier_for(step: str, tier: str) -> str:
    """The tier the review is asked at in a step: ``final`` (the strong model) only with ``on``."""
    return tier if escalates(step) or tier != "final" else "analysis"


def bucket(fixture_id: int, market_key: str, selection: str, line: Decimal) -> int:
    """A selection's bucket of the control, 0 to 9999: the first eight bytes of ``sha256("<salt>:<fixture>:<market>:<selection>:<line>")``."""
    text = f"{SAMPLE_SALT}:{int(fixture_id)}:{market_key}:{selection}:{format(Decimal(line).normalize(), 'f')}"
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big") % BUCKETS


def in_sample(fixture_id: int, market_key: str, selection: str, line: Decimal) -> bool:
    """Whether a selection is in the control group the model keeps reviewing in step ``sample``. Stable: no state, no clock."""
    return bucket(fixture_id, market_key, selection, line) < int(SAMPLE_SHARE * BUCKETS)


def model_reviews(step: str, fixture_id: int, market_key: str, selection: str, line: Decimal) -> bool:
    """Whether the model may review this selection in a step (the cycle's own conditions - budget, a material change - still apply)."""
    if step in ("on", "no_opus"):
        return True
    if step == "sample":
        return in_sample(fixture_id, market_key, selection, line)
    return False


def carries(step: str) -> bool:
    """Whether an earlier model review still in force is carried into the combined review (every step but ``off``)."""
    return step != "off"


# -- the comparison ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Pair:
    """One selection both paths judged: its Bogotá day, its value against the close and whether each path lets it through."""

    day: date
    clv: float
    kept_reference: bool
    kept_new: bool

    @property
    def difference(self) -> float:
        return self.clv * (int(self.kept_new) - int(self.kept_reference))


def _by_day_ci(values: Sequence[tuple[date, float]], *, seed: int, replicates: int) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    sums: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for d, v in values:
        sums[d][0] += v
        sums[d][1] += 1
    days = sorted(sums)
    s = np.array([sums[d][0] for d in days])
    n = np.array([sums[d][1] for d in days])
    mean = float(s.sum() / n.sum())
    if len(days) < 2:
        return mean, None, None
    idx = np.random.default_rng(seed).integers(0, len(days), size=(replicates, len(days)))
    stats = np.sort(s[idx].sum(axis=1) / n[idx].sum(axis=1))
    tail = (1 - LEVEL) / 2
    lo = stats[max(0, min(replicates - 1, math.floor(tail * replicates)))]
    hi = stats[max(0, min(replicates - 1, math.ceil((1 - tail) * replicates) - 1))]
    return mean, float(lo), float(hi)


def _mean(xs: Sequence[float]) -> float | None:
    return None if not xs else sum(xs) / len(xs)


def compare(pairs: Iterable[Pair], *, seed: int = SEED, replicates: int = REPLICATES) -> dict[str, Any]:
    """The protocol over a window: the paired difference with its interval and the verdict. A verdict activates nothing."""
    items = [p for p in pairs if math.isfinite(p.clv)]
    days = {p.day for p in items}
    mean, lo, hi = _by_day_ci([(p.day, p.difference) for p in items], seed=seed, replicates=replicates)
    reasons: list[str] = []
    if len(items) < MIN_SELECTIONS:
        reasons.append(f"selections_below_{MIN_SELECTIONS}")
    if len(days) < MIN_DAYS:
        reasons.append(f"days_below_{MIN_DAYS}")
    if reasons or lo is None:
        verdict = "INSUFICIENTE"
    elif lo >= -float(MARGIN):
        verdict = "NO_INFERIOR"
    else:
        verdict = "INFERIOR"
    kept_ref = [p.clv for p in items if p.kept_reference]
    kept_new = [p.clv for p in items if p.kept_new]
    return {"version": VERSION, "protocol": dict(PROTOCOL), "n": len(items), "days": len(days), "verdict": verdict,
            "reasons": reasons or ["criterion_evaluated"],
            "difference": {"mean": mean, "low": lo, "high": hi, "margin": float(MARGIN)},
            "reference": {"kept": len(kept_ref), "mean_clv_kept": _mean(kept_ref)},
            "new_path": {"kept": len(kept_new), "mean_clv_kept": _mean(kept_new)},
            "discordant": {"only_new": sum(1 for p in items if p.kept_new and not p.kept_reference),
                           "only_reference": sum(1 for p in items if p.kept_reference and not p.kept_new)},
            "decides": False}


# -- what removing the model review changes --------------------------------------------------------------------------------------------

ORDER: Final[Mapping[str, int]] = {"REJECT": 0, "DOWNGRADE": 1, "APPROVE": 2}


def combined(decisions: Iterable[str]) -> str:
    """``fbi.ai.review.combine`` on the words: the most conservative opinion; ABSTAIN only when every engine abstained."""
    opinions = [d for d in decisions if d != "ABSTAIN"]
    return "ABSTAIN" if not opinions else min(opinions, key=lambda d: ORDER[d])


@dataclass(frozen=True, slots=True)
class Review:
    """A combined review as stored: the rules' word and, when the model reviewed (or was carried), its word."""

    rules: str
    model: str | None


def effect_of_removal(reviews: Iterable[Review]) -> dict[str, Any]:
    """What the combined review - the input of decision-v1's filter 6 and of rule D1 of the picks' user status (``user-status-v2``) - becomes without the
    model: the rules' word alone. Counts by (with the model -> without it). decision-v1 and the user status change exactly where it moves;
    the owner signs this measure before each step (AD-D11)."""
    moves: Counter[tuple[str, str]] = Counter()
    n = with_model = 0
    for r in reviews:
        n += 1
        if r.model is None:
            continue
        with_model += 1
        before = combined([r.rules, r.model])
        after = combined([r.rules])
        if before != after:
            moves[(before, after)] += 1
    changed = sum(moves.values())
    return {"version": VERSION, "reviews": n, "with_model": with_model, "changed": changed,
            "moves": {f"{a}->{b}": k for (a, b), k in sorted(moves.items())},
            "raised": sum(k for (a, b), k in moves.items() if ORDER.get(b, 3) > ORDER.get(a, 3)),
            "lowered": sum(k for (a, b), k in moves.items() if ORDER.get(b, 3) < ORDER.get(a, 3))}


__all__ = ["BUCKETS", "DEFAULT", "KEY", "MARGIN", "MIN_DAYS", "MIN_SELECTIONS", "PROTOCOL", "SAMPLE_SALT", "SAMPLE_SHARE", "STEPS", "VERDICTS",
           "VERSION", "Pair", "Review", "Step", "bucket", "carries", "combined", "compare", "effect_of_removal", "escalates", "in_sample",
           "model_reviews", "step_of", "tier_for"]
