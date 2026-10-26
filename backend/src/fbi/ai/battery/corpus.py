"""The corpus as a whole: the targets, their bases and cases, the request every ask makes, and the fingerprints that say whether a measurement
is of THIS corpus and of the prompts in force.

* ``corpus_hash``: the cases and the bases - what is attacked and how. A change to either is a new ``VERSION`` (a test pins the hash).
* ``requests_hash``: the bytes of every request of a target - the corpus AND the prompts, the schemas and the layout it is asked with. A
  prompt or a schema that changes changes it, and a measurement made with another one is stale (``fbi.ai.battery.run.status``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Final

from fbi.ai.battery import (
    MIN_CASES,
    TARGETS,
    VERSION,
    attacks_extract,
    attacks_review,
    extractor,
    reviewer,
)
from fbi.ai.battery.model import Base, Case, make_case
from fbi.ai.config import Tier
from fbi.ai.prompts import EXTRACT_VERSION, REVIEW_VERSION
from fbi.ai.providers.base import JsonRequest

Builder = Callable[[str, Case | None, bool], JsonRequest]


@dataclass(frozen=True, slots=True)
class Target:
    """A prompt of PrediGol that reads text someone else wrote."""

    name: str
    prompt: str
    """The version of the prompt under test (``review-v2``)."""
    tier: Tier
    """The tier production asks it with: the battery asks the same."""
    typical_output: int
    """Tokens an answer is expected to write: the reservation of the cost of an ask."""
    bases: dict[str, Base]
    build: Builder


TARGET_SPECS: Final[dict[str, Target]] = {
    "review": Target("review", REVIEW_VERSION, "analysis", 1000, reviewer.BASES,
                     lambda base, case, native: reviewer.request(base, case, native=native)),
    "extract": Target("extract", EXTRACT_VERSION, "bulk", 400, extractor.BASES,
                      lambda base, case, native: extractor.request(base, case, native=native)),
}

CASES: Final[tuple[Case, ...]] = (tuple(make_case("review", a) for a in attacks_review.ATTACKS)
                                  + tuple(make_case("extract", a) for a in attacks_extract.ATTACKS))
BY_ID: Final[dict[str, Case]] = {c.id: c for c in CASES}


def target(name: str) -> Target:
    try:
        return TARGET_SPECS[name]
    except KeyError:
        raise ValueError(f"unknown target {name!r} (the targets are {', '.join(TARGETS)})") from None


def cases_of(name: str) -> tuple[Case, ...]:
    target(name)
    return tuple(c for c in CASES if c.target == name)


def case_of(case_id: str) -> Case:
    try:
        return BY_ID[case_id]
    except KeyError:
        raise ValueError(f"unknown case {case_id!r}") from None


def request_for(name: str, base: str, case: Case | None = None, *, native: bool = False) -> JsonRequest:
    """The request of an ask: the base clean (a control) or with the case's text in its place."""
    spec = target(name)
    if base not in spec.bases:
        raise ValueError(f"unknown base {base!r} of the target {name!r}")
    if case is not None and (case.target != name or case.base != base):
        raise ValueError(f"the case {case.id} is not an attack on the base {base!r} of {name!r}")
    return spec.build(base, case, native)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def fingerprint(request: JsonRequest) -> str:
    """sha256 of everything that defines a request: what the model is told, the schema, how it is asked."""
    return hashlib.sha256(_canonical(asdict(request)).encode()).hexdigest()


def requests_hash(name: str, *, native: bool = False) -> str:
    """sha256 of the fingerprints of every request of a target: its bases clean and each of its cases."""
    spec = target(name)
    parts = [[f"base:{b}", fingerprint(request_for(name, b, native=native))] for b in sorted(spec.bases)]
    parts += [[f"case:{c.id}", fingerprint(request_for(name, c.base, c, native=native))] for c in sorted(cases_of(name), key=lambda c: c.id)]
    return hashlib.sha256(_canonical([VERSION, spec.prompt, parts]).encode()).hexdigest()


def corpus_hash() -> str:
    """sha256 of the corpus: every base and every case, with what the deterministic layer and the evaluator expect of it."""
    bases = [[t, b.id, b.note] for t in TARGETS for b in sorted(target(t).bases.values(), key=lambda b: b.id)]
    cases = [[c.id, c.canary, asdict(c.attack)] for c in sorted(CASES, key=lambda c: c.id)]
    return hashlib.sha256(_canonical([VERSION, bases, cases]).encode()).hexdigest()


def check_sizes() -> list[str]:
    """What is wrong with the size of the corpus - the plan's «≥ 40 casos» of each target - or nothing."""
    return [f"{t}: {n} cases, {MIN_CASES} needed" for t in TARGETS if (n := len(cases_of(t))) < MIN_CASES]
