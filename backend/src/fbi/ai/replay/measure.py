"""How much a replay reproduces what was stored (IA-047, plan piece ``INT-C02``): the rule of the gate «reproducibilidad
suficiente para comparar variantes», written before any data. Pure: no database, no clock, no model.

THE UNIT. One answer of a stored run, word by word: the stance of each candidate (``aa-v1``, ``pa-v1``: SUPPORT, NEUTRAL,
CONCERN, REJECT_SIGNAL), the verdict of each candidate (``cd-v1``: APPROVE, DOWNGRADE, REJECT, ABSTAIN - one to one with
the word of ``ctx-adj-v1`` and with the effect it has in ``decision-v2``, the contract of IA-046) or, for the Match Agent's
context, the set of its signals (``code:direction``). Each unit has three readings: ``S`` the stored one, ``R1`` and ``R2``
the two replays of the same request. None is a reading that does not exist (an answer that did not stand).

THE RULE, per scope (an agent's task or an arm of the Council), the form of the equivalence of Gate A with the stored run in
the place of the variant (``fbi.ai.lab.assess``):

* CHANGE: over the units whose three readings exist, the number where ``S`` differs from ``R1`` is not larger than the
  number where ``R2`` differs from ``R1`` - «el cambio respecto de lo guardado ≤ el de repetir la misma llamada»;
* VALIDITY: the replays that did not stand are at most 3 % of those that came back and at most one point above the
  stored runs that did not stand (Gate B's 3 %);
* SIZE: at least ``MIN_UNITS`` such units over at least ``MIN_MATCHES`` matches. Fewer is INSUFICIENTE, never a pass.

Reported, not decided on: the share of units that change, the stored against BOTH replays, the difference with its 95 %
interval by a bootstrap of the matches (units of one match are not independent), which words moved where, the moves toward
APPROVE or SUPPORT and toward a restriction, and the confidence of the Council's verdicts. With a perfect reproduction the
CHANGE rule passes a little more than half the time (the two counts have the same expectation): a NO PASA whose interval
covers 0 says the sample cannot tell, and the protocol says what follows from it.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

METHOD: Final = "replay-measure-v1"
"""The rule of this module. A change of a threshold, of the unit or of the interval is a new version, never an edit."""
MIN_UNITS: Final = 200
"""Units with their three readings, per scope (the 200 stored inputs of the equivalence of Gate A)."""
MIN_MATCHES: Final = 30
"""Distinct matches behind them: the units of one match move together."""
MAX_INVALID: Final = 0.03
INVALID_MARGIN: Final = 0.01
BOOTSTRAP: Final = 2000
SEED: Final = 20261111
PASS: Final = "PASA"
FAIL: Final = "NO PASA"
INSUFFICIENT: Final = "INSUFICIENTE"
RESTRICTING: Final = frozenset({"DOWNGRADE", "REJECT", "ABSTAIN", "CONCERN", "REJECT_SIGNAL"})
FAVOURING: Final = frozenset({"APPROVE", "SUPPORT"})


@dataclass(frozen=True, slots=True)
class Unit:
    """One word of one stored answer, with its two replays."""

    item: int
    """The stored run (``ai.agent_runs.id``)."""
    fixture: int
    key: str
    """The candidate (``c1``...) or ``signals``."""
    stored: str | None
    first: str | None
    second: str | None

    @property
    def complete(self) -> bool:
        return self.stored is not None and self.first is not None and self.second is not None


@dataclass(frozen=True, slots=True)
class Answers:
    """How the asks of a scope came back: the stored runs that stood or not, and the replays that stood or not."""

    stored: int
    stored_invalid: int
    replays: int
    replays_invalid: int
    open: int = 0
    """Asks still on their way: nothing is decided about a scope while one is open."""


def units_of(item: int, fixture: int, stored: Mapping[str, str] | None, first: Mapping[str, str] | None,
             second: Mapping[str, str] | None) -> list[Unit]:
    """The units of one stored run from the words of its three answers (``bank.units_of``; None = the answer did not
    stand or did not come back). The keys are the stored answer's when it stood, else those of the replays: a candidate
    a replay names and the stored answer does not is no unit (``read`` of each agent refuses an answer about a candidate
    that was not asked, so this happens only when one of them did not stand)."""
    keys = sorted(stored) if stored else sorted(set(first or {}) | set(second or {}))
    return [Unit(item, fixture, k, None if stored is None else stored.get(k), None if first is None else first.get(k),
                 None if second is None else second.get(k)) for k in keys]


def _rate(k: int, n: int) -> float | None:
    return None if n == 0 else round(k / n, 4)


def _moves(pairs: Iterable[tuple[str | None, str | None]]) -> dict[str, int]:
    return dict(sorted(Counter(f"{a}>{b}" for a, b in pairs if a != b).items()))


def bootstrap_difference(units: Sequence[Unit], *, draws: int = BOOTSTRAP, seed: int = SEED) -> tuple[float, float] | None:
    """The 95 % interval (percentiles 2.5 and 97.5) of the difference ``share(S != R1) - share(R2 != R1)`` when the
    MATCHES are drawn again with replacement (all the units of a match go together). None with fewer than two matches.
    Deterministic: the seed is the protocol's."""
    by_match: dict[int, list[tuple[int, int]]] = {}
    for u in units:
        by_match.setdefault(u.fixture, []).append((int(u.stored != u.first), int(u.second != u.first)))
    matches = sorted(by_match)
    if len(matches) < 2:
        return None
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(draws):
        drawn = [matches[rng.randrange(len(matches))] for _ in matches]
        pairs = [p for m in drawn for p in by_match[m]]
        n = len(pairs)
        stats.append((sum(a for a, _ in pairs) - sum(b for _, b in pairs)) / n)
    stats.sort()
    low = stats[int(0.025 * (draws - 1))]
    high = stats[int(0.975 * (draws - 1))]
    return round(low, 4), round(high, 4)


def assess(units: Sequence[Unit], answers: Answers, *, min_units: int = MIN_UNITS, min_matches: int = MIN_MATCHES,
           confidence: Mapping[str, tuple[str | None, str | None, str | None]] | None = None, draws: int = BOOTSTRAP) -> dict[str, Any]:
    """The verdict of one scope by the rule of this module's docstring, with what it rests on. ``confidence`` (the
    Council) maps ``<item>:<candidate>`` to the confidence of the three readings, reported only. ``draws`` is the
    protocol's (only a test of the rule's own properties lowers it: the interval decides nothing)."""
    complete = [u for u in units if u.complete]
    n = len(complete)
    matches = len({u.fixture for u in complete})
    changed_stored = sum(1 for u in complete if u.stored != u.first)
    changed_repeat = sum(1 for u in complete if u.second != u.first)
    changed_second = sum(1 for u in complete if u.stored != u.second)
    stored_invalid = _rate(answers.stored_invalid, answers.stored)
    replay_invalid = _rate(answers.replays_invalid, answers.replays)
    out: dict[str, Any] = {
        "method": METHOD, "units": len(units), "complete_units": n, "matches": matches, "stored_runs": answers.stored,
        "replays": answers.replays, "open": answers.open,
        "changed_stored": changed_stored, "changed_repeat": changed_repeat, "changed_stored_second": changed_second,
        "change_stored": _rate(changed_stored, n), "change_repeat": _rate(changed_repeat, n),
        "change_stored_both": _rate(changed_stored + changed_second, 2 * n),
        "invalid_stored": stored_invalid, "invalid_replay": replay_invalid,
        "all_three_agree": _rate(sum(1 for u in complete if u.stored == u.first == u.second), n),
        "moves": {"stored_to_first": _moves((u.stored, u.first) for u in complete),
                  "first_to_second": _moves((u.first, u.second) for u in complete)},
        "toward_favouring": {"stored": sum(1 for u in complete if u.stored not in FAVOURING and u.first in FAVOURING),
                             "repeat": sum(1 for u in complete if u.first not in FAVOURING and u.second in FAVOURING)},
        "toward_restriction": {"stored": sum(1 for u in complete if u.stored in FAVOURING and u.first in RESTRICTING),
                               "repeat": sum(1 for u in complete if u.first in FAVOURING and u.second in RESTRICTING)},
        "rule": f"changed(S vs R1) <= changed(R2 vs R1) over >= {min_units} complete units of >= {min_matches} matches; "
                f"invalid replays <= {MAX_INVALID:.0%} and <= stored + {INVALID_MARGIN:.0%}"}
    if n:
        out["difference"] = round((changed_stored - changed_repeat) / n, 4)
        interval = bootstrap_difference(complete, draws=draws)
        if interval is not None:
            out["difference_ci95"] = list(interval)
    if confidence:
        agree = [c for c in confidence.values() if all(x is not None for x in c)]
        out["confidence_agree_stored"] = _rate(sum(1 for s, f, _ in agree if s == f), len(agree))
        out["confidence_agree_repeat"] = _rate(sum(1 for _, f, s in agree if s == f), len(agree))
    reasons: list[str] = []
    insufficient = n < min_units or matches < min_matches
    if insufficient:
        reasons.append(f"insufficient: {n} complete units of {matches} matches; {min_units} units of {min_matches} matches needed")
    if changed_stored > changed_repeat:
        reasons.append(f"the replay changes more of what was stored ({changed_stored}) than repeating the same call changes "
                       f"({changed_repeat})")
    if replay_invalid is not None and (replay_invalid > MAX_INVALID or replay_invalid > (stored_invalid or 0.0) + INVALID_MARGIN):
        reasons.append("the replays do not stand more often than allowed")
    if answers.open:
        reasons.append(f"{answers.open} ask(s) still on their way")
    out["reasons"] = reasons
    out["verdict"] = INSUFFICIENT if insufficient or answers.open else PASS if not reasons else FAIL
    out["passed"] = out["verdict"] == PASS
    return out


def letters(units: Sequence[Unit]) -> dict[str, str]:
    """The evidence a row keeps so that anyone can recompute the verdict: per unit, its three readings (``-`` for one
    that does not exist), by ``<item>:<key>``."""
    return {f"{u.item}:{u.key}": "|".join(x if x is not None else "-" for x in (u.stored, u.first, u.second))
            for u in sorted(units, key=lambda u: (u.item, u.key))}


def evidence_hash(evidence: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


__all__ = ["BOOTSTRAP", "FAIL", "INSUFFICIENT", "MAX_INVALID", "METHOD", "MIN_MATCHES", "MIN_UNITS", "PASS", "SEED", "Answers",
           "Unit", "assess", "bootstrap_difference", "evidence_hash", "letters", "units_of"]
