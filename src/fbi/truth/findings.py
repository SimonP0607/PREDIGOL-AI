"""What a truth check can find, and how bad each finding is.

A finding is one disagreement between the provider and our database, or one
contradiction inside the database, stated with both values. Agreement is not a
finding: it is counted, so a dataset's line in the report reads "checked 1,200,
matched 1,193" rather than listing 1,193 non-events.

Severity is about consequences, not about how surprising the finding is:

* CRITICAL - a wrong number reaches settlement, a model or a user: a result, a
  finished match stored as not played, a price we never had.
* HIGH - a wrong fact a page states as true: a status, a kick-off, a fixture we
  do not have.
* MEDIUM - context that is wrong or behind: a stale table, a missing line-up.
* LOW - identity details: a name spelled differently, a logo, a venue.
* INFO - the provider and we agree there is nothing, or a field we never store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    MISMATCH = "mismatch"
    """Both sides hold a value and the values differ."""
    MISSING_IN_DB = "missing_in_db"
    """The provider has it; we do not."""
    MISSING_IN_API = "missing_in_api"
    """We have it; the provider no longer lists it (deleted, re-numbered)."""
    NOT_STORED = "not_stored"
    """The provider sends a field our schema has nowhere to keep."""
    STALE = "stale"
    """We hold an older state than the provider's."""
    PROVIDER_LAG = "provider_lag"
    """The provider itself has not caught up (a match still NS hours after kick-off)."""
    INCONSISTENT = "inconsistent"
    """The database contradicts itself; no provider call was needed to see it."""
    PROVIDER_CONTRADICTION = "provider_contradiction"
    """The provider's answer contradicts itself (a 90-minute or extra-time score above the final one):
    the writer keeps no result rather than a wrong one."""


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_ORDER = {s: i for i, s in enumerate(Severity)}


def _short(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= 300 else text[:297] + "..."


@dataclass(frozen=True, slots=True)
class Finding:
    dataset: str
    entity: str
    """What the finding is about, as a person would name it: ``fixture 1438655``."""
    field: str
    kind: Kind
    severity: Severity
    api: str | None = None
    db: str | None = None
    note: str = ""

    @staticmethod
    def of(dataset: str, entity: str, field: str, kind: Kind, severity: Severity, *,
           api: Any = None, db: Any = None, note: str = "") -> Finding:
        return Finding(dataset, entity, field, kind, severity, _short(api), _short(db), note)

    def as_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "entity": self.entity, "field": self.field, "kind": self.kind.value,
                "severity": self.severity.value, "api": self.api, "db": self.db, "note": self.note}


FINDINGS_KEPT_PER_KIND = 400
"""Each (dataset, field, kind) keeps this many findings verbatim and counts the rest.

The fixture-completeness check alone can disagree on thousands of rows when one
mistake repeats; the report needs the count and enough examples to recognise the
pattern, not ten thousand copies of it."""


@dataclass
class Tally:
    """One dataset's outcome: how much was compared, how much agreed, what did not."""

    dataset: str
    checked: int = 0
    matched: int = 0
    findings: list[Finding] = field(default_factory=list)
    counts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    """(field, kind, severity) -> number of findings, including the ones not kept."""
    notes: list[str] = field(default_factory=list)
    requests: int = 0

    def agree(self, n: int = 1) -> None:
        self.checked += n
        self.matched += n

    def compared(self, n: int = 1) -> None:
        """Counted as checked; the caller records what disagreed with ``add``."""
        self.checked += n

    def add(self, finding: Finding) -> None:
        key = (finding.field, finding.kind.value, finding.severity.value)
        seen = self.counts.get(key, 0)
        self.counts[key] = seen + 1
        if seen < FINDINGS_KEPT_PER_KIND:
            self.findings.append(finding)

    def extend(self, findings: list[Finding]) -> None:
        for f in findings:
            self.add(f)

    @property
    def total_findings(self) -> int:
        return sum(self.counts.values())

    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for (_field, kind, _sev), n in self.counts.items():
            out[kind] = out.get(kind, 0) + n
        return out

    def by_severity(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for (_field, _kind, sev), n in self.counts.items():
            out[sev] = out.get(sev, 0) + n
        return out

    @property
    def worst(self) -> Severity | None:
        sev = [Severity(s) for (_f, _k, s) in self.counts]
        return min(sev, key=lambda s: SEVERITY_ORDER[s]) if sev else None

    def difference(self) -> str:
        """One line for the matrix: what disagreed, by kind, largest first."""
        kinds = sorted(self.by_kind().items(), key=lambda kv: -kv[1])
        if not kinds:
            return "none"
        return ", ".join(f"{n:,} {k.replace('_', ' ')}" for k, n in kinds)

    def summary(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset, "checked": self.checked, "matched": self.matched,
            "findings": self.total_findings, "by_kind": self.by_kind(), "by_severity": self.by_severity(),
            "worst": self.worst.value if self.worst else None, "difference": self.difference(),
            "requests": self.requests, "notes": self.notes,
            "by_field": [{"field": f, "kind": k, "severity": s, "n": n}
                         for (f, k, s), n in sorted(self.counts.items(), key=lambda kv: -kv[1])],
        }
