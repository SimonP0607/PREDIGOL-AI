"""What the panel of the gates reads (IA-050; the panel itself is ``fbi.ai.gates_panel``). Reads only: the caller opens the connection read-only
(``default_transaction_read_only``, a ``statement_timeout``) and in one snapshot (``REPEATABLE READ``). Nothing here records: the evaluators of
Gate B and of research v2 are called the way their scripts call them without ``--record`` (``evaluate`` reads; their ``record`` is never
called).

Three statements and two evaluators:

* ``NEWEST_ROWS_SQL``: the newest row of every gate of ``ai.feature_gates`` - the newest row decides (``fbi.ai.gates``, ``ORDER BY at DESC, id
  DESC``) -, with the verdict, the window and the models its evidence carries;
* ``SHADOW_REPORTS_SQL``: the newest report of each engine in ``ai.shadow_reports`` (``ai-gate-v2``, the rule of ``fbi.ai.shadow.latest``);
* ``P1_SQL``: the selections the engines of the shadow reviewed before the kick-off since the anchor of the configuration Gate B evaluates,
  naming its engines (``tests/unit/test_engine_filter_guard.py``);
* ``gate_b.evaluate`` and ``gate_research.evaluate``, each in its own savepoint: one that fails is reported and the rest of the snapshot is read.

The cost of the components is not read here but by ``scripts/ia_gates_panel.py`` (``fbi.ai.cost_paths_readers``, the only module of the AI that
may name the readers' own ledger, and that nothing of Intelligence imports). Nothing here reads ``ai.evidence``: G-FUENTES 1 carries IA-040's
measure, frozen in the panel (``tests/unit/test_typed_evidence_guard.py`` lists who reads that table, and why)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import gate_b, gate_research
from fbi.ai.calendar import day_start, local_day
from fbi.ai.config import AiSettings
from fbi.ai.gates_panel import P1Counts, PanelInputs, Row, row_of

NEWEST_ROWS_SQL: Final = """
SELECT DISTINCT ON (gate) id, gate, at, passed, decided_by, evidence_hash, evidence ->> 'verdict' AS verdict,
       evidence -> 'window' AS evidence_window, evidence -> 'models' AS models, evidence ->> 'kind' AS kind
  FROM ai.feature_gates
 ORDER BY gate, at DESC, id DESC
"""

SHADOW_REPORTS_SQL: Final = """
SELECT DISTINCT ON (engine) id, engine, created_at, window_from, window_to, version, gate ->> 'verdict' AS verdict,
       gate -> 'checks' -> 'selections' ->> 'value' AS selections, gate -> 'checks' -> 'days' ->> 'value' AS days,
       gate -> 'checks' -> 'rejected' ->> 'value' AS rejected, gate -> 'rejection_quality' ->> 'diff' AS diff,
       gate -> 'rejection_quality' ->> 'se' AS se, gate -> 'rejection_quality' ->> 'z' AS z,
       gate -> 'checks' -> 'clv' -> 'value' ->> 'kept' AS clv_kept, gate -> 'checks' -> 'clv' -> 'value' ->> 'rejected' AS clv_rejected,
       arms -> 'model_ai' ->> 'roi' AS roi_kept, arms -> 'rejected' ->> 'roi' AS roi_rejected
  FROM ai.shadow_reports
 ORDER BY engine, created_at DESC, id DESC
"""

P1_SQL: Final = """
SELECT r.engine, r.market_key, count(DISTINCT (r.fixture_id, r.market_key, r.selection, r.line)) AS reviewed,
       count(DISTINCT (r.fixture_id, r.market_key, r.selection, r.line)) FILTER (WHERE f.status_group = 'finished') AS finished
  FROM ai.pick_reviews r
  JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND r.mode = 'shadow' AND r.status IN ('ok', 'fallback')
   AND r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s AND r.reviewed_at < f.kickoff_at
 GROUP BY r.engine, r.market_key
 ORDER BY r.engine, r.market_key
"""
"""The shadow's own selections (its three engines, named): reviewed before the kick-off and judged (``ok`` or ``fallback``), each once."""

STATEMENTS: Final[tuple[str, ...]] = (NEWEST_ROWS_SQL, SHADOW_REPORTS_SQL, P1_SQL)

def _int(x: Any) -> int | None:
    try:
        return None if x is None else int(x)
    except (TypeError, ValueError):
        return None


def shadow_report_of(r: Mapping[str, Any]) -> dict[str, Any]:
    """A row of ``SHADOW_REPORTS_SQL`` with its counts as numbers (the JSON gives them as text)."""
    return dict(r) | {k: _int(r.get(k)) for k in ("selections", "days", "rejected")}


def _error(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0][:200]}" if text else type(exc).__name__


def guarded[T](conn: psycopg.Connection[Any], fn: Callable[[], T]) -> tuple[T | None, str | None]:
    """``fn()`` in a savepoint: its result, or None and the error in words. A statement that fails (a timeout) rolls back to the savepoint and
    the snapshot stays readable for the rest of the panel."""
    try:
        with conn.transaction():
            return fn(), None
    except (psycopg.Error, ValueError) as exc:
        return None, _error(exc)


def newest_rows(conn: psycopg.Connection[Any]) -> dict[str, Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        return {str(r["gate"]): row_of(r) for r in cur.execute(NEWEST_ROWS_SQL).fetchall()}


def shadow_reports(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return [shadow_report_of(r) for r in cur.execute(SHADOW_REPORTS_SQL).fetchall()]


def p1_counts(conn: psycopg.Connection[Any], gate_b_report: Mapping[str, Any] | None, *, at: datetime) -> P1Counts:
    """P1 from the anchor of the configuration Gate B evaluates (the day after the latest change), up to ``at``."""
    window = gate_b_report.get("window") if gate_b_report is not None else None
    anchor_text = window.get("anchor") if isinstance(window, Mapping) else None
    today = local_day(at)
    if not anchor_text:
        return P1Counts(None, None, today)
    anchor = datetime.fromisoformat(str(anchor_text)).date()
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(P1_SQL, {"since": day_start(anchor), "until": at}).fetchall()
    return P1Counts(anchor, None if not isinstance(window, Mapping) else window.get("anchored_by"), today,
                    tuple((str(r["engine"]), str(r["market_key"]), int(r["reviewed"]), int(r["finished"])) for r in rows))


def read(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime) -> PanelInputs:
    """Everything the panel reads but the cost, in the caller's transaction (one snapshot)."""
    rows = newest_rows(conn)
    reports = shadow_reports(conn)
    b, b_error = guarded(conn, lambda: gate_b.evaluate(conn, settings, at=at).as_json())
    r, r_error = guarded(conn, lambda: gate_research.evaluate(conn, settings, at=at).as_json())
    p1, p1_error = guarded(conn, lambda: p1_counts(conn, b, at=at))
    return PanelInputs(at=at, rows=rows, gate_b=b, gate_b_error=b_error, research=r, research_error=r_error, shadow_reports=reports,
                       p1=p1, p1_error=p1_error)


__all__ = ["NEWEST_ROWS_SQL", "P1_SQL", "SHADOW_REPORTS_SQL", "STATEMENTS", "guarded", "newest_rows", "p1_counts", "read",
           "shadow_report_of", "shadow_reports"]
