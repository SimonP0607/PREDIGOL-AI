"""Build walk-forward feature sets (and the Elo history) from stored results.

    python -m scripts.build_features                 # dry run: what would be written, null rates
    python -m scripts.build_features --apply         # write
    python -m scripts.build_features --apply --competitions 39 --offset-min 60

Targets: every stored fixture of the chosen competitions. A finished fixture
gets its features as of ``offset`` minutes before kick-off - what a
pre-match model could have known - and a scheduled one as of now (never later
than that same offset before its kick-off). History for Elo and form is every
stored result, all competitions. Zero provider requests.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import timedelta

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.features.data import load_matches, load_team_stats
from fbi.features.elo import EloParams
from fbi.features.engine import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    FORM_N,
    LEAGUE_N,
    RESULT_AVAILABLE_AFTER,
    STRENGTH_N,
    walk_forward,
)
from fbi.features.store import ensure_registry, write_elo_history, write_feature_sets
from fbi.ingestion.ledger import RunCounters, RunLedger


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="build_features", description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--competitions", type=str, default="", help="comma-separated competition ids (core.competitions.id)")
    parser.add_argument("--offset-min", type=int, default=60)
    args = parser.parse_args()

    moment = now()
    offset = timedelta(minutes=args.offset_min)
    params = EloParams()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        history = load_matches(conn)
        wanted = {int(x) for x in args.competitions.split(",") if x.strip()}
        targets = []
        for m in history:
            if wanted and m.competition_id not in wanted:
                continue
            if m.status_group == "finished" and m.has_result:
                targets.append((m, m.kickoff_at - offset))
            elif m.status_group == "scheduled":
                targets.append((m, min(moment, m.kickoff_at - offset)))
        stats = load_team_stats(conn)
        vectors, elo = walk_forward(history, targets, params, stats)

        # A scheduled fixture recomputed with no new information is not a new vector.
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT DISTINCT ON (fixture_id) fixture_id, input_hash FROM features.feature_sets "
                "WHERE feature_version = %s ORDER BY fixture_id, n_inputs DESC, generated_at DESC",
                (FEATURE_VERSION,),
            )
            latest = {int(a): str(b) for a, b in cur.fetchall()}
        fresh = [v for v in vectors if latest.get(v.fixture_id) != v.input_hash]

        nulls = Counter(name for v in vectors for name, value in v.values.items() if value is None)
        print(f"history: {len(history)} fixtures, {sum(1 for m in history if m.has_result)} with results, "
              f"{len(stats)} with shot statistics")
        print(f"targets: {len(targets)} -> vectors: {len(vectors)}, new information: {len(fresh)}")
        print(f"elo history rows: {len(elo)} ({params.version})")
        if vectors:
            print("null rate per feature (share of vectors with no value):")
            for name in FEATURE_NAMES:
                rate = nulls[name] / len(vectors)
                if rate:
                    print(f"  {name:24s} {rate:6.1%}")
        if not args.apply:
            print("dry run - nothing written (use --apply)")
            return 0

        ensure_registry(conn)
        ledger = RunLedger(conn)
        run_id = ledger.open("feature_build", params={"version": FEATURE_VERSION, "offset_min": args.offset_min})
        lineage = {
            "feature_version": FEATURE_VERSION,
            "elo": params.as_dict(),
            "availability_model": f"result known {int(RESULT_AVAILABLE_AFTER.total_seconds() // 3600)} h after kick-off",
            "windows": {"form": FORM_N, "strength": STRENGTH_N, "league": LEAGUE_N},
            "cutoff": f"kick-off minus {args.offset_min} min; now for scheduled fixtures",
            "history_fixtures": len(history),
            "code_version": code_version(),
        }
        counters = RunCounters()
        try:
            inserted, present = write_feature_sets(conn, fresh, version=FEATURE_VERSION,
                                                   code_version=code_version(), run_id=run_id, lineage=lineage)
            elo_rows = write_elo_history(conn, elo, version=params.version, run_id=run_id)
            conn.commit()
            counters.rows_inserted = inserted + elo_rows
            counters.rows_normalized = len(vectors)
            print(f"written: {inserted} feature sets ({present} already present), {elo_rows} Elo rows, run {run_id}")
        finally:
            ledger.close(run_id, counters, notes=f"{FEATURE_VERSION}, 0 requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
