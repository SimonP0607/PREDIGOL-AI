"""Is every change of what production forecasts with on record? (plan F12): the model code, measured against its promotions.

The plan's rule is that nothing changes production without hypothesis -> experiment -> gate -> promotion. Three kinds of change already had their
promotion table: the goal spec (``analytics.promoted_forecast_spec``), the calibrators and the market edge (``intel.promotions``), the neutral-venue
rule (``analytics.neutral_rule_promotion``). The model's CODE had none. A model version is keyed by the fingerprint of the model packages, so a
release that touches them opens new versions of every model and production forecasts with them from its next pass.

``trace`` reads, over a window, every fingerprint that production forecast with (``models.predictions`` made by the worker, the stored
``forecast-v1`` forecasts and the decisions), when its versions came into being, and the promotion that covers it:

* ``BASELINE``     the code already in force when the ledger began, recorded after the fact and said so;
* ``PROMOTED``     a decision (``fbi.research.promotions.LEDGER``, written to ``intel.promotions``) dated before the code first ran;
* ``AFTER_USE``    a decision on record, but dated after production first used the code;
* ``PENDING_SYNC`` in the ledger, not yet copied into ``intel.promotions``;
* ``UNTRACED``     no decision anywhere: this is the change the plan says must not happen;
* ``PRE_LEDGER``   it came into being before the ledger began: listed, never counted (the past cannot be decided afterwards).

The criterion of the plan - 100 % of the model changes of the last 30 days with their promotion traced - is ``traced / counted``. Nothing here
changes a model, a forecast or a pick: ``trace`` only reads and ``sync`` writes the ledger's own rows to ``intel.promotions`` on request.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.research import promotions as ledger_module
from fbi.research.promotions import CodePromotion

LEGACY: Final = "legacy"
"""The versions of before 5 Oct 2026, when a version was keyed by the repository commit (``...@ea1d0c8``), not by the code of the models."""
CODE_OF_VERSION: Final = re.compile(r"@(mc[0-9a-f]{10})$")
DEFAULT_DAYS: Final = 30
IN_FORCE_DAYS: Final = 2
"""A fingerprint used in the last two days is 'in force now'."""
TRACED: Final = ("BASELINE", "PROMOTED", "AFTER_USE")

USE_SQL: Final = """
WITH used AS (
  SELECT 'predictions' AS source, model_version_id, min(created_at) AS first_at, max(created_at) AS last_at, count(*) AS n
    FROM models.predictions WHERE backtest_session_id IS NULL AND created_at >= %(since)s GROUP BY model_version_id
  UNION ALL
  SELECT 'forecasts', model_version_id, min(known_at), max(known_at), count(*)
    FROM models.match_forecasts WHERE version = 'forecast-v1' AND known_at >= %(since)s GROUP BY model_version_id
  UNION ALL
  SELECT 'decisions', model_version_id, min(known_at), max(known_at), count(*)
    FROM intel.decisions WHERE model_version_id IS NOT NULL AND known_at >= %(since)s GROUP BY model_version_id)
SELECT mr.name AS model, mv.id AS version_id, mv.version, mv.created_at, u.source, u.first_at, u.last_at, u.n
  FROM used u
  JOIN models.model_versions mv ON mv.id = u.model_version_id
  JOIN models.model_registry mr ON mr.id = mv.model_id
 ORDER BY mv.created_at, mv.id, u.source
"""
"""What production forecast with: the live predictions (a backtest's carry its session), the stored forecasts of the page and the decisions."""

ROWS_SQL: Final = """
SELECT id, at, to_role, decided_by, reason, criteria
  FROM intel.promotions WHERE entity = 'model' ORDER BY at, id
"""
OTHER_SQL: Final = {
    "goal_spec": "SELECT count(*) FROM analytics.promoted_forecast_spec WHERE promoted_at >= %(since)s",
    "calibrator": "SELECT count(*) FROM intel.promotions WHERE entity = 'calibrator' AND at >= %(since)s",
    "market_edge": "SELECT count(*) FROM intel.promotions WHERE entity = 'market_edge' AND at >= %(since)s",
    "neutral_rule": "SELECT count(*) FROM analytics.neutral_rule_promotion WHERE promoted_at >= %(since)s",
}
"""The promotions of the other kinds of change in the same window, for context: they are traced by construction (the table is the only way in)."""


@dataclass(frozen=True, slots=True)
class Use:
    """One source's use of one model version."""

    model: str
    version_id: int
    version: str
    created_at: datetime
    source: str
    first_at: datetime
    last_at: datetime
    rows: int


@dataclass(frozen=True, slots=True)
class Recorded:
    """A CHAMPION row of the model code in ``intel.promotions``."""

    row_id: int
    at: datetime
    decided_by: str
    reason: str
    decided_at: datetime
    baseline: bool
    evidence: Mapping[str, Any]


def fingerprint_of(version: str) -> str:
    """The code a model version string names: ``2.0.0/xi=0.002,penalty=1@mc9a7bec97ca`` -> ``mc9a7bec97ca``; the commit-keyed ones -> ``legacy``."""
    found = CODE_OF_VERSION.search(version)
    return found.group(1) if found else LEGACY


def classify(fingerprint: str, appeared_at: datetime, *, ledger: Sequence[CodePromotion], recorded: Mapping[str, Recorded]) -> str:
    """The status of one fingerprint (see the module): what covers it, judged against the moment its code first ran."""
    if fingerprint == LEGACY or (ledger and appeared_at < ledger[0].decided_at):
        return "PRE_LEDGER"
    row = recorded.get(fingerprint)
    if row is None:
        return "PENDING_SYNC" if any(p.fingerprint == fingerprint for p in ledger) else "UNTRACED"
    if row.baseline:
        return "BASELINE"
    return "PROMOTED" if row.decided_at <= appeared_at else "AFTER_USE"


def load_use(conn: psycopg.Connection[Any], *, since: datetime) -> list[Use]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(USE_SQL, {"since": since})
        return [Use(str(r["model"]), int(r["version_id"]), str(r["version"]), r["created_at"], str(r["source"]), r["first_at"], r["last_at"],
                    int(r["n"])) for r in cur.fetchall()]


def load_recorded(conn: psycopg.Connection[Any]) -> dict[str, Recorded]:
    """The newest CHAMPION row of each fingerprint (a RETIRED row later does not make the decision unrecorded)."""
    out: dict[str, Recorded] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROWS_SQL)
        for r in cur.fetchall():
            criteria = r["criteria"] or {}
            code = criteria.get("model_code")
            if r["to_role"] != "CHAMPION" or not isinstance(code, str):
                continue
            decided = criteria.get("decided_at")
            out[code] = Recorded(int(r["id"]), r["at"], str(r["decided_by"]), str(r["reason"]),
                                 datetime.fromisoformat(decided) if isinstance(decided, str) else r["at"],
                                 bool(criteria.get("baseline")), criteria.get("evidence") or {})
    return out


def trace(conn: psycopg.Connection[Any], *, now: datetime, days: int = DEFAULT_DAYS, ledger: Sequence[CodePromotion] | None = None) -> dict[str, Any]:
    """Every fingerprint that forecast in the last ``days`` days, with its status, and the count the plan's criterion is made of."""
    ledger = ledger_module.LEDGER if ledger is None else ledger
    since = now - timedelta(days=days)
    recorded = load_recorded(conn)
    grouped: dict[str, list[Use]] = defaultdict(list)
    for use in load_use(conn, since=since):
        grouped[fingerprint_of(use.version)].append(use)
    fingerprints: list[dict[str, Any]] = []
    for code, uses in grouped.items():
        appeared = min(u.created_at for u in uses)
        status = classify(code, appeared, ledger=ledger, recorded=recorded)
        row = recorded.get(code)
        sources: dict[str, int] = defaultdict(int)
        for u in uses:
            sources[u.source] += u.rows
        fingerprints.append({
            "fingerprint": code, "status": status, "appeared_at": appeared, "last_use": max(u.last_at for u in uses),
            "versions": len({u.version_id for u in uses}), "models": sorted({u.model for u in uses}), "rows": dict(sources),
            "in_force_now": max(u.last_at for u in uses) >= now - timedelta(days=IN_FORCE_DAYS),
            "promotion": None if row is None else {"id": row.row_id, "decided_by": row.decided_by, "decided_at": row.decided_at,
                                                   "reason": row.reason, "evidence": dict(row.evidence)},
        })
    fingerprints.sort(key=lambda f: (f["appeared_at"], f["fingerprint"]))
    counted = [f for f in fingerprints if f["status"] != "PRE_LEDGER"]
    traced = [f for f in counted if f["status"] in TRACED]
    other: dict[str, int] = {}
    with conn.cursor() as cur:
        for name, sql in OTHER_SQL.items():
            cur.execute(sql, {"since": since})
            found = cur.fetchone()
            other[name] = int(found[0]) if found else 0
    return {
        "now": now, "since": since, "days": days, "ledger_since": ledger[0].decided_at if ledger else None,
        "ledger_in_force": ledger[-1].fingerprint if ledger else None, "fingerprints": fingerprints,
        "counts": {"fingerprints": len(fingerprints), "counted": len(counted), "traced": len(traced),
                   "untraced": sum(1 for f in counted if f["status"] == "UNTRACED"),
                   "pending_sync": sum(1 for f in counted if f["status"] == "PENDING_SYNC"),
                   "after_use": sum(1 for f in counted if f["status"] == "AFTER_USE"),
                   "pre_ledger": len(fingerprints) - len(counted)},
        "coverage": len(traced) / len(counted) if counted else None, "other": other,
    }


def render(report: Mapping[str, Any]) -> str:
    """The trace as text: one line per fingerprint, then the count of the plan's criterion."""
    c = report["counts"]
    lines = [f"model code that forecast in production in the last {report['days']} days: {c['fingerprints']} fingerprint(s); "
             f"the ledger in force is {report['ledger_in_force'] or 'empty'}"
             + (f", begun {report['ledger_since']:%Y-%m-%d %H:%M} UTC" if report["ledger_since"] else "")]
    for f in report["fingerprints"]:
        rows = ", ".join(f"{k} {v:,}".replace(",", " ") for k, v in sorted(f["rows"].items()))
        lines.append(f"  {f['fingerprint']:<13} {f['status']:<12} appeared {f['appeared_at']:%Y-%m-%d %H:%M}  last used {f['last_use']:%Y-%m-%d %H:%M}  "
                     f"{f['versions']} versions of {', '.join(f['models'])}  [{rows}]{'  IN FORCE NOW' if f['in_force_now'] else ''}")
        if f["promotion"]:
            p = f["promotion"]
            lines.append(f"      promotion #{p['id']} by {p['decided_by']}, decided {p['decided_at']:%Y-%m-%d %H:%M}: {p['reason'][:110]}")
    if c["counted"]:
        lines.append(f"criterion of the plan (changes since the ledger began, with their promotion on record): {c['traced']} of {c['counted']} "
                     f"= {report['coverage'] * 100:.0f} %"
                     + (f"; untraced {c['untraced']}" if c["untraced"] else "") + (f"; pending sync {c['pending_sync']}" if c["pending_sync"] else "")
                     + (f"; decided after the code ran {c['after_use']}" if c["after_use"] else ""))
    else:
        lines.append("criterion of the plan: no change since the ledger began")
    if c["pre_ledger"]:
        lines.append(f"  ({c['pre_ledger']} fingerprint(s) older than the ledger are listed, not counted: the past cannot be decided afterwards)")
    lines.append("other promotions in the window: " + ", ".join(f"{k} {v}" for k, v in sorted(report["other"].items())))
    return "\n".join(lines)


def check_evidence(conn: psycopg.Connection[Any], entry: CodePromotion) -> None:
    """A promotion that cites a hypothesis or an experiment that does not exist is refused: the link has to be real."""
    hypothesis = entry.evidence.get("hypothesis_id")
    experiments = [int(x) for x in entry.evidence.get("experiment_ids", [])]
    with conn.cursor() as cur:
        if hypothesis is not None:
            cur.execute("SELECT 1 FROM analytics.research_hypotheses WHERE id = %s", (int(hypothesis),))
            if cur.fetchone() is None:
                raise LookupError(f"{entry.fingerprint}: hypothesis {hypothesis} does not exist")
        if experiments:
            cur.execute("SELECT id FROM analytics.experiments WHERE id = ANY(%s)", (experiments,))
            missing = sorted(set(experiments) - {int(r[0]) for r in cur.fetchall()})
            if missing:
                raise LookupError(f"{entry.fingerprint}: experiment(s) {missing} do not exist")


def sync(conn: psycopg.Connection[Any], *, now: datetime, confirm: bool, ledger: Sequence[CodePromotion] | None = None) -> list[str]:
    """Copy the entries of the ledger that ``intel.promotions`` does not have yet. Without ``confirm`` nothing is written. The caller owns the
    transaction. The entry before a new one is retired in the same pass (history only: the table stays append-only)."""
    ledger = ledger_module.LEDGER if ledger is None else ledger
    recorded = load_recorded(conn)
    lines: list[str] = []
    previous: CodePromotion | None = None
    for entry in ledger:
        if entry.fingerprint in recorded:
            previous = entry
            continue
        check_evidence(conn, entry)
        lines.append(f"{'WRITE' if confirm else 'WOULD WRITE'} {entry.fingerprint} ({entry.phase}, {entry.decided_by}"
                     f"{', baseline' if entry.baseline else ''}): {entry.reason[:100]}")
        if confirm:
            criteria = {"model_code": entry.fingerprint, "decided_at": entry.decided_at.isoformat(), "phase": entry.phase,
                        "baseline": entry.baseline, "evidence": entry.evidence, "source": "fbi.research.promotions"}
            with conn.cursor() as cur:
                if previous is not None and previous.fingerprint in recorded:
                    cur.execute("INSERT INTO intel.promotions (at, entity, to_role, from_role, gate_version, criteria, reason, decided_by) "
                                "VALUES (%s, 'model', 'RETIRED', 'CHAMPION', %s, %s, %s, %s)",
                                (now, ledger_module.GATE_VERSION, Jsonb({"model_code": previous.fingerprint, "replaced_by": entry.fingerprint}),
                                 f"replaced by {entry.fingerprint}", entry.decided_by))
                cur.execute("INSERT INTO intel.promotions (at, entity, to_role, from_role, gate_version, criteria, reason, decided_by) "
                            "VALUES (%s, 'model', 'CHAMPION', %s, %s, %s, %s, %s)",
                            (now, "CHAMPION" if previous is not None and previous.fingerprint in recorded else None,
                             ledger_module.GATE_VERSION, Jsonb(criteria), entry.reason[:500], entry.decided_by))
        previous = entry
        recorded[entry.fingerprint] = Recorded(0, now, entry.decided_by, entry.reason, entry.decided_at, entry.baseline, entry.evidence)
    return lines or ["nothing to write: every entry of the ledger is already in intel.promotions"]
