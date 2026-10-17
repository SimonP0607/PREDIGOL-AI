"""The evolution loop's two schedules (``apps/worker/scheduler.py``):

* **daily monitor** - the E0 audit of the shadow picks and the prospective evaluation, read
  from the database in seconds, turned into memory and proposals (``fbi.research.evolution``);
* **weekly research V2** - the full walk-forward run (``scripts/research_v2.py --apply``, about
  five minutes of CPU in its own process, no provider request), stored with its roles and
  learned from, only when ``v2_due``: the code changed since the last run, or that run is four
  weeks old - the historical seasons do not change from week to week, the code does.

Neither changes a threshold, a model or a pick rule; both write results and proposals.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.core.version import model_code_version
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.research.evolution import learn_from_audit, learn_from_prospective
from fbi.research.pick_audit import audit_picks
from fbi.research.prospective import evaluate_prospective

STALE_AFTER = timedelta(days=28)
FREEZE_FILE = Path(__file__).resolve().parents[3] / "data" / "research.frozen"
"""While this file exists (its text says why), no research run trains or stores a model: the
weekly job skips and ``scripts.research_v2 --apply`` refuses. Set during a data-truth audit -
no new models until the data they would learn from is proven."""


def frozen() -> str | None:
    """Why research is frozen right now, or None."""
    env = os.environ.get("FBI_RESEARCH_FROZEN", "").strip()
    if env and env.lower() not in ("0", "false", "no", "off"):
        return f"FBI_RESEARCH_FROZEN={env}"
    if FREEZE_FILE.exists():
        return FREEZE_FILE.read_text().strip() or str(FREEZE_FILE)
    return None


def model_ready(conn: psycopg.Connection[Any], validation: int, test: int) -> list[tuple[int, str]]:
    """The domestic leagues whose validation AND test seasons are MODEL_READY."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT c.id, c.name FROM core.competitions c
              JOIN core.competition_seasons cs ON cs.competition_id = c.id
              JOIN analytics.competition_data_scores s ON s.competition_season_id = cs.id
             WHERE c.competition_type = 'domestic_league' AND s.class = 'MODEL_READY' AND cs.season IN (%s, %s)
             GROUP BY c.id, c.name HAVING count(DISTINCT cs.season) = 2 ORDER BY c.id
            """, (validation, test))
        return [(int(a), str(b)) for a, b in cur.fetchall()]


@dataclass
class MonitorResult:
    settled_picks: int
    prospective_played: int
    prospective_priced: int
    memory: list[int] = field(default_factory=list)
    proposals: list[int] = field(default_factory=list)


def run_monitor(conn: psycopg.Connection[Any], *, at: datetime) -> MonitorResult:
    """Audit + prospective -> memory and proposals, committed together."""
    ledger = RunLedger(conn)
    run_id = ledger.open("research_monitor", params={"at": at.isoformat()})
    counters = RunCounters()
    try:
        audit = audit_picks(conn, at=at)
        prospective = evaluate_prospective(conn, until=at)
        a = learn_from_audit(conn, audit, at=at)
        p = learn_from_prospective(conn, prospective, at=at)
        result = MonitorResult(int(audit.overall.get("n") or 0), prospective.played, prospective.priced,
                               a.memory + p.memory, a.proposals + p.proposals)
        counters.rows_inserted = len(result.memory) + len(result.proposals)
        conn.commit()
    except BaseException:
        conn.rollback()  # nothing half-learned: the ledger close below commits
        raise
    finally:
        ledger.close(run_id, counters, notes="audit + prospective -> memory and proposals, 0 requests")
    return result


def latest_v2(conn: psycopg.Connection[Any]) -> dict[str, Any] | None:
    """The newest stored research-V2 run: its name, commit, model code and dataset version (both null for a run
    stored before 5 Oct 2026, which recorded neither) and when it finished."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT name, code_version, environment->>'model_code' AS model_code, "
                    "environment->>'dataset_version' AS dataset_version, finished_at FROM analytics.experiments "
                    "WHERE run_label = 'RESEARCH_V2' AND kind = 'backtest' AND status = 'completed' "
                    "ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return None if row is None else dict(row)


def _model_ready_dataset(conn: psycopg.Connection[Any]) -> str | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT name FROM audit.dataset_versions WHERE status = 'MODEL_READY' "
                    "ORDER BY promoted_at DESC NULLS LAST LIMIT 1")
        row = cur.fetchone()
    return None if row is None else str(row[0])


@dataclass(frozen=True, slots=True)
class DueReason:
    """Why a research-V2 run is due: a stable code and its values (for a page in the reader's language) and the
    sentence in English (logs, the command line)."""

    code: str
    text: str
    vars: dict[str, str] = field(default_factory=dict)


def v2_due_reason(conn: psycopg.Connection[Any], *, at: datetime, version: str | None = None) -> DueReason | None:
    """Why a research-V2 run is due, or None.

    Judged by the MODEL code (``fbi.core.version.model_code_version``) and the dataset version, not the repository
    commit: a deploy that touched a page or an audit made the weekly run "due" while nothing it learns from had
    changed (5 Oct 2026). A run stored before runs recorded their model code cannot be compared, and says so."""
    last = latest_v2(conn)
    version = version or model_code_version()
    if last is None:
        return DueReason("no_run", "no research-V2 run is stored")
    dataset = _model_ready_dataset(conn)
    if dataset is not None and last.get("dataset_version") != dataset:
        before = last.get("dataset_version") or "none recorded"
        return DueReason("new_dataset", f"a new dataset version is MODEL_READY ({before} -> {dataset})",
                         {"before": last.get("dataset_version") or "", "after": dataset})
    if last.get("model_code") is None:
        return DueReason("unknown_model_code",
                         f"the last run ({last['code_version']}) predates model-code fingerprints: the model code it "
                         f"ran is unknown (now {version})", {"commit": str(last["code_version"]), "now": version})
    if last["model_code"] != version:
        return DueReason("model_code_changed", f"the model code changed ({last['model_code']} -> {version})",
                         {"before": str(last["model_code"]), "after": version})
    if last["finished_at"] is None or last["finished_at"] < at - STALE_AFTER:
        return DueReason("four_weeks", "the last run is four weeks old")
    return None


def v2_due(conn: psycopg.Connection[Any], *, at: datetime, version: str | None = None) -> str | None:
    """Why a research-V2 run is due, in English, or None (``v2_due_reason`` has the code and values)."""
    reason = v2_due_reason(conn, at=at, version=version)
    return None if reason is None else reason.text
