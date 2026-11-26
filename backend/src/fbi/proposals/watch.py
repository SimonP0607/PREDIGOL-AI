"""Reads what is in force in every ledger of the registry and judges it with ``fbi.proposals.surveillance`` (RP-8.4, tranche 2). Reads only: no promotion is written.

For each ``(entity type, key)`` of the registry whose current decision puts a version in force, a READER says what that version did in the last 14 days. A kind
without a reader is listed as NOT watched (the honest figure of the indicator «promotions watched / promotions in force»), never as healthy. The readers that exist:

* ``calibrator``: the prospective evaluation the nightly calibration already stores (``intel.calibrator_evaluations``): loss and calibration error of the calibrated
  probability against the raw model's. The calibration step withdraws a failing calibrator by itself under this same rule, so its findings are marked automatic.

More readers are added one by one with the metric of their kind and its minimum sample, written before they run (``READERS``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import local_day
from fbi.governance import promotions as registry
from fbi.proposals import surveillance as rule

Reader = Callable[[psycopg.Connection[Any], registry.Promotion, datetime], rule.Reading | None]

PROSPECTIVE_SQL: Final = """
SELECT sum(n) AS n, sum(n * logloss_cal) / NULLIF(sum(n), 0) AS ll_cal, sum(n * logloss_raw) / NULLIF(sum(n), 0) AS ll_raw,
       sum(n * ece_cal) / NULLIF(sum(n), 0) AS ece_cal
  FROM intel.calibrator_evaluations WHERE calibrator_id = %(id)s AND day >= %(since)s
"""
"""The same reading the calibration step takes before it retires a calibrator (``fbi.intel.calibration.PROSPECTIVE_SQL``)."""
AUTOMATIC: Final = frozenset({"calibrator"})
"""The kinds whose ledger already withdraws a failing version by itself under this rule."""
WATCHED_KINDS: Final = tuple(sorted(registry.BY_VERSION | registry.NEWEST))


def _num(x: Any) -> float | None:
    return None if x is None else float(x)


def calibrator_reading(conn: psycopg.Connection[Any], promotion: registry.Promotion, at: datetime) -> rule.Reading | None:
    if promotion.version is None or not promotion.version.isdigit():
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PROSPECTIVE_SQL, {"id": int(promotion.version), "since": local_day(at) - timedelta(days=rule.WINDOW_DAYS)})
        row = cur.fetchone() or {}
    return rule.Reading(int(row.get("n") or 0), _num(row.get("ll_cal")), _num(row.get("ll_raw")), _num(row.get("ece_cal")))


READERS: Final[dict[str, Reader]] = {"calibrator": calibrator_reading}


@dataclass(slots=True)
class Report:
    findings: list[rule.Finding] = field(default_factory=list)
    not_watched: list[dict[str, Any]] = field(default_factory=list)

    @property
    def degraded(self) -> list[rule.Finding]:
        return [f for f in self.findings if f.verdict.state == rule.DEGRADES]

    def summary(self) -> dict[str, Any]:
        states = {s: sum(1 for f in self.findings if f.verdict.state == s) for s in (rule.KEEPS, rule.DEGRADES, rule.SHORT)}
        in_force = len(self.findings) + len(self.not_watched)
        return {"rule": rule.VERSION, "in_force": in_force, "watched": len(self.findings), "not_watched": len(self.not_watched), **states}


def _previous(history: list[registry.Promotion], current: registry.Promotion) -> str | None:
    before = [r for r in history if r.in_force is True and r.version is not None and r.version != current.version and r.at <= current.at]
    return before[-1].version if before else None


def scan(conn: psycopg.Connection[Any], *, at: datetime, records: list[registry.Promotion] | None = None,
         readers: Mapping[str, Reader] | None = None) -> Report:
    """Every version in force at ``at`` with its reading and verdict, and the ones no reader covers."""
    records = registry.all_promotions(conn, at=at) if records is None else records
    use = READERS if readers is None else readers
    report = Report()
    for entity_type, key in registry.keys_of(records):
        if entity_type not in WATCHED_KINDS:
            continue
        current = registry.current_of(records, entity_type, key, at=at)
        if current is None or current.in_force is not True or not current.effective:
            continue
        version = current.version or current.decision
        reader = use.get(entity_type)
        if reader is None:
            report.not_watched.append({"entity_type": entity_type, "key": key, "version": version, "since": current.at.isoformat()})
            continue
        reading = reader(conn, current, at)
        previous = _previous(registry.history_of(records, entity_type, key, at=at), current)
        report.findings.append(rule.Finding(entity_type, key, version, current.at, previous, reading, rule.judge(reading),
                                            automatic=entity_type in AUTOMATIC))
    return report


__all__ = ["AUTOMATIC", "READERS", "Report", "calibrator_reading", "scan"]
