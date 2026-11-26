"""The coherence battery over what PrediGol states: one match's single figures in, the violations out, each linked to the figure it came from
(plan RP-2.2, ``coherence-battery-v1``). Pure; ``scripts/ia_coherence_audit.py`` reads the database and keeps the report.

A violation names the selections it compares; the audit gives each of them its seal: the reading id a text would cite, the fingerprint of the
inputs of its market set (``set_hash``, what ``input_hash`` is for a stored forecast), the model and its version, whether it is calibrated, and
where the number came from. A violation changes no figure and publishes none: ``publishable`` is false for the match.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Final

from fbi.forecasting import battery
from fbi.forecasting import single_figure as sf


def figures_of(figure_set: sf.FigureSet) -> list[battery.Figure]:
    """The battery's figures of one match's single-figure set (what it wins, what comes back, and the interval of each selection)."""
    return [battery.Figure(f.market_key, f.selection, f.line, f.p, f.push, f.lo, f.hi) for f in figure_set.figures.values()]


def seal_of(f: sf.Figure) -> dict[str, Any]:
    return {"reading_id": f.reading_id, "set_hash": f.set_hash, "model": f.model, "model_version_id": f.model_version_id,
            "calibration": f.calibration, "basis": f.basis, "source": f.source, "version": f.version, "cutoff": f.cutoff.isoformat()}


def audit_match(figure_set: sf.FigureSet) -> dict[str, Any]:
    """The battery over one match, with every violation linked to the seals of the figures it compares."""
    report = battery.check(figures_of(figure_set))
    violations = []
    for v in report.violations:
        linked = [{"market": m, "selection": s, "line": str(line), **seal_of(figure_set.figures[(m, s, line)])}
                  for m, s, line in v.selections if (m, s, line) in figure_set.figures]
        violations.append({**v.as_json(), "figures": linked})
    return {"fixture_id": figure_set.fixture_id, "figures": len(figure_set.figures), "publishable": report.publishable,
            "ran": report.ran, "violations": violations}


def summary(audits: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The nightly report: how many matches were checked, how many are not publishable, which tests broke and which could not run."""
    items = list(audits)
    by_test: Counter[int] = Counter()
    ran: Counter[int] = Counter()
    for a in items:
        for v in a["violations"]:
            by_test[int(v["test"])] += 1
        for t, n in a["ran"].items():
            ran[int(t)] += int(n)
    return {
        "version": battery.VERSION, "matches": len(items), "figures": sum(int(a["figures"]) for a in items),
        "not_publishable": sum(1 for a in items if not a["publishable"]),
        "tests": {str(t): {"name": battery.NAMES[t], "tolerance": battery.TOLERANCES[t] if battery.TOLERANCES[t] is not None else "strict",
                           "comparisons": ran[t], "violations": by_test[t], "ran": ran[t] > 0} for t in battery.NAMES},
    }


EXAMPLES: Final = 10
"""How many violations the report spells out (the counts are always complete)."""

__all__ = ["EXAMPLES", "audit_match", "figures_of", "seal_of", "summary"]
