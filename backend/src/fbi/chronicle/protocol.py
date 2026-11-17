"""The protocol of the factual evaluation of the single chronicle (IA-118, plan piece AD-F06): ``chronicle-protocol-v1``. PREREGISTERED, UNSIGNED.

What a person reviews, how many, how two reviewers are compared, and which thresholds the chronicle is held to - written BEFORE any of it is
measured, so that no figure is chosen after seeing the data. The owner signs it (``SIGNED`` stays False in the code until a commit records the
owner's words in ``SIGNATURE``); until then every threshold below is a PROPOSAL, and nothing reads it to switch, publish or promote anything.

    the sample       ``SAMPLE`` chronicles reviewed by ``chronicle-review-v2`` (``ai.chronicle_reviews``), drawn by a hash of ``SEED`` and
                     their id (deterministic: the same rows give the same sample); ``DOUBLE`` of them read blind by a second person
    the label        each sentence: SUPPORTED / NOT_IN_SOURCES / CONTRADICTED_BY_SOURCES / UNCLEAR (``fbi.ai.label_bank.SUPPORT_LABELS``:
                     the words of the labelled bank, IA-030) - does the sentence say only what its cited facts say?
    the criterion    0 sentences not supported in the ``SAMPLE`` chronicles. With n = 50 and 0 failures the one-sided 95 % upper bound of the
                     real rate is 5.8 % (``upper_bound``): «below 6 %» is all that n = 50 can say, and the report says it so
    the agreement    the two reviewers agree on at least ``AGREEMENT_MIN`` of the double sentences; a disagreement is listed, never resolved
                     by the code
    the stock rule   the thresholds of ``repeat-check-v1`` (AD-F04): ``repetition.SHARE_MAX``, ``GENERIC_RATE_MAX``, ``REPEAT_RATE_MAX``

The human labels are kept apart (a sheet, then the owner's folder): they train nothing and tune nothing (AD-K07). Pure: no database, no clock."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from fbi.ai.label_bank import SUPPORT_LABELS, UNDECIDED
from fbi.chronicle import repetition

VERSION: Final = "chronicle-protocol-v1"
SIGNED: Final = False
SIGNATURE: Final[str | None] = None
"""The owner's words when they sign (a commit that records them). None: the protocol is a proposal."""
SEED: Final = "chronicle-protocol-v1"
SAMPLE: Final = 50
DOUBLE: Final = 10
"""A fifth of the sample, read blind by a second person."""
UNSUPPORTED_MAX: Final = 0
AGREEMENT_MIN: Final = 0.90
CONFIDENCE: Final = 0.95

THRESHOLDS: Final[dict[str, Any]] = {
    "unsupported_sentences_max": UNSUPPORTED_MAX, "sample": SAMPLE, "double": DOUBLE, "agreement_min": AGREEMENT_MIN,
    "stock_share_max": repetition.SHARE_MAX, "generic_rate_max": repetition.GENERIC_RATE_MAX,
    "repeat_rate_max": repetition.REPEAT_RATE_MAX, "min_corpus": repetition.MIN_CORPUS,
}


def status() -> dict[str, Any]:
    """What the protocol is, for the owner's guide and the script: its version, whether it is signed, its thresholds."""
    return {"version": VERSION, "signed": SIGNED, "signature": SIGNATURE, "thresholds": dict(THRESHOLDS),
            "note": "propuesto y preregistrado; sin firma del dueño ningún umbral es definitivo y nada lo lee para encender algo"}


def upper_bound(failures: int, n: int, confidence: float = CONFIDENCE) -> float | None:
    """The one-sided upper bound of a rate with ``failures`` of ``n`` (exact, Clopper-Pearson one-sided). 0 of 50 -> 0.0582."""
    if n <= 0:
        return None
    if failures == 0:
        return float(1 - (1 - confidence) ** (1 / n))
    if failures >= n:
        return 1.0
    lo, hi = failures / n, 1.0
    for _ in range(80):  # the p whose lower tail P(X <= failures) is 1 - confidence
        mid = (lo + hi) / 2
        tail = sum(math.comb(n, i) * mid**i * (1 - mid) ** (n - i) for i in range(failures + 1))
        lo, hi = (mid, hi) if tail > 1 - confidence else (lo, mid)
    return hi


def _rank(seed: str, ident: int) -> str:
    return hashlib.sha256(f"{seed}:{ident}".encode()).hexdigest()


def sample(review_ids: Iterable[int], *, n: int = SAMPLE, double: int = DOUBLE, seed: str = SEED) -> tuple[list[int], list[int]]:
    """The reviews to label and, among them, those a second person reads blind. Deterministic."""
    ordered = sorted(set(review_ids), key=lambda i: _rank(seed, i))[:n]
    return ordered, ordered[:double]


def sheet(reviews: Sequence[Mapping[str, Any]], *, double: Iterable[int]) -> list[dict[str, Any]]:
    """The rows a person fills in: one per sentence of each sampled review, with the facts it cites (never the verdict of the code, so the
    person is not led). ``reviews``: rows of ``ai.chronicle_reviews`` (``id``, ``chronicle_id``, ``fixture_id``, ``items``) and, beside each,
    ``facts`` - the plan's facts by id (kind, params)."""
    twice = set(double)
    out: list[dict[str, Any]] = []
    for r in reviews:
        facts = r.get("facts") or {}
        for item in r.get("items") or []:
            cited = [{"id": f, **({k: facts[f].get(k) for k in ("kind", "params")} if f in facts else {})} for f in item.get("facts") or []]
            out.append({"review_id": int(r["id"]), "chronicle_id": r.get("chronicle_id"), "fixture_id": r.get("fixture_id"),
                        "part": item.get("part"), "section": item.get("section"), "index": item.get("index"), "text": item.get("text"),
                        "cited": cited, "double": int(r["id"]) in twice, "label": "", "label_second": "", "note": ""})
    return out


def score(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The filled sheet read back: unsupported sentences against the criterion, the upper bound, the agreement of the double reading."""
    labels = list(SUPPORT_LABELS)
    unknown = [r for r in rows if r.get("label") and r["label"] not in labels]
    judged = [r for r in rows if r.get("label") in labels and r["label"] not in UNDECIDED]
    failures = [r for r in judged if r["label"] != "SUPPORTED"]
    chronicles = {r["review_id"] for r in judged}
    twice = [r for r in rows if r.get("double") in (True, "True", "true", "1") and r.get("label") in labels
             and r.get("label_second") in labels]
    agree = sum(1 for r in twice if r["label"] == r["label_second"])
    agreement = None if not twice else round(agree / len(twice), 4)
    bound = upper_bound(len(failures), len(judged))
    return {
        "version": VERSION, "signed": SIGNED, "chronicles": len(chronicles), "sentences": len(rows), "judged": len(judged),
        "undecided": sum(1 for r in rows if r.get("label") in UNDECIDED), "unlabelled": sum(1 for r in rows if not r.get("label")),
        "unknown_labels": len(unknown), "by_label": dict(sorted(Counter(str(r["label"]) for r in judged).items())),
        "unsupported": len(failures), "upper_bound_95": None if bound is None else round(bound, 4),
        "double_sentences": len(twice), "agreement": agreement,
        "disagreements": [{"review_id": r["review_id"], "where": f"{r.get('section')}[{r.get('index')}]", "first": r["label"],
                           "second": r["label_second"]} for r in twice if r["label"] != r["label_second"]][:50],
        "meets": {"sample": len(chronicles) >= SAMPLE, "unsupported": len(failures) <= UNSUPPORTED_MAX,
                  "agreement": agreement is not None and agreement >= AGREEMENT_MIN},
        "note": "informa y no decide; las etiquetas humanas no entrenan ni ajustan nada",
    }


__all__ = ["AGREEMENT_MIN", "DOUBLE", "SAMPLE", "SEED", "SIGNATURE", "SIGNED", "THRESHOLDS", "VERSION", "sample", "score", "sheet", "status",
           "upper_bound"]
