"""Keep the Elo ratings current: the whole history, recomputed from every stored result.

The ratings were computed once, on 24 Sep 2026, from the 13,500 results that existed
then, and never extended: on 4 Oct the Rankings page still showed PSG last rated in May
2025, and 7,459 of 201,781 finished fixtures carried a rating. Every Elo-based model
input, and the MODEL_DATA_GATE, read that.

Elo is a walk through matches in kick-off order, so a result that arrives late (a match
the provider settled two days after it was played, a season backfilled today) changes
every rating after it. Extending the last run in place would get that wrong; recomputing
the whole history - about 200,000 matches, seconds of arithmetic - cannot. Each refresh
is a new ledger run (``elo_refresh``), so a rating is always traceable to the run that
wrote it, and the previous refresh runs are pruned: only the newest ``keep`` survive.
Runs written by ``feature_build`` are never touched - they are the inputs of stored
feature sets and models.

The parameters are ``EloParams()``, fixed a priori; changing them is a new version.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import tuple_row

from fbi.core.logging import get_logger
from fbi.features.data import load_matches
from fbi.features.elo import EloParams
from fbi.features.engine import walk_forward
from fbi.features.store import write_elo_history
from fbi.ingestion.ledger import RunCounters, RunLedger

log = get_logger(__name__)

JOB = "elo_refresh"


@dataclass(frozen=True, slots=True)
class EloRefresh:
    run_id: int
    rows: int
    matches: int
    pruned_runs: int
    pruned_rows: int


def refresh_elo(conn: psycopg.Connection, *, keep: int = 2, params: EloParams | None = None) -> EloRefresh:
    params = params or EloParams()
    history = load_matches(conn)
    rated = sum(1 for m in history if m.has_result)
    _, elo = walk_forward(history, [], params)
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": params.version, "matches": rated})
    counters = RunCounters()
    pruned_runs = pruned_rows = 0
    try:
        rows = write_elo_history(conn, elo, version=params.version, run_id=run_id)
        counters.rows_inserted = rows
        counters.rows_normalized = rated
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT id FROM raw.ingestion_runs WHERE job_type = %s AND id <> %s ORDER BY id DESC",
                        (JOB, run_id))
            older = [int(r[0]) for r in cur.fetchall()]
            stale = older[max(keep - 1, 0):]
            if stale:
                cur.execute("DELETE FROM features.elo_ratings WHERE run_id = ANY(%s)", (stale,))
                pruned_rows = max(cur.rowcount, 0)
                pruned_runs = len(stale)
        conn.commit()
    finally:
        ledger.close(run_id, counters, notes=f"{params.version}: {rated:,} matches, {counters.rows_inserted:,} rows; "
                                             f"pruned {pruned_runs} older refresh run(s), {pruned_rows:,} rows")
    log.info("elo_refresh.done", run_id=run_id, matches=rated, rows=counters.rows_inserted, pruned_runs=pruned_runs)
    return EloRefresh(run_id, counters.rows_inserted, rated, pruned_runs, pruned_rows)
