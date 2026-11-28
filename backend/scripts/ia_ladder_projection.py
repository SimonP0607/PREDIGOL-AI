"""RP-2.2: what the coherent line ladder would do to the matches that kick off soon (``ladder-projection-v1``). Read-only.

    python -m scripts.ia_ladder_projection --hours 72 [--json] [--mode half|pooled]

Over the single figures of ``forecast-v2`` as of now, it counts the matches the battery refuses before and after the projection, the violations by test, and how far the
figures move (share, mean, median, 90th percentile and largest shift, by market). It changes nothing and publishes nothing: the outcome-based criterion (``LAD-P1``)
needs settled matches. Exit 0 when it ran, 2 when it cannot.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.forecasting import battery, battery_audit, ladder
from fbi.forecasting.market_reader import figures_at
from fbi.intel.calibration import calibration_state
from scripts.ia_single_figure import FIXTURES_SQL, PAGE_VERSION

OK, CANNOT = 0, 2
READ_ONLY: Final = "-c default_transaction_read_only=on -c statement_timeout=95000 -c TimeZone=UTC"


def _tally(sets: list[list[battery.Figure]]) -> dict[str, Any]:
    by_test = dict.fromkeys(battery.NAMES, 0)
    refused = 0
    for s in sets:
        rep = battery.check(s)
        refused += 0 if rep.publishable else 1
        for t, n in rep.by_test().items():
            by_test[t] += n
    return {"not_publishable": refused, "violations_by_test": by_test}


def report(sets: list[list[battery.Figure]], *, mode: ladder.Mode) -> dict[str, Any]:
    projections = [ladder.project(s, mode=mode) for s in sets]
    before = _tally(sets)
    after = _tally([list(p.figures) for p in projections])
    refused_before = [battery.publishable(s) for s in sets]
    refused_after = [battery.publishable(p.figures) for p in projections]
    fixed = sum(1 for b, a in zip(refused_before, refused_after, strict=True) if not b and a)
    kinds: dict[str, int] = {}
    for p in projections:
        for m in p.moves:
            kinds[m.kind] = kinds.get(m.kind, 0) + 1
    return {
        "version": ladder.VERSION,
        "mode": mode,
        "matches": len(sets),
        "before": before,
        "after": after,
        "made_publishable": fixed,
        "moves": kinds,
        "shift": ladder.shifts(projections),
        "shift_by_market": ladder.by_market(projections),
    }


def render(r: dict[str, Any]) -> str:
    s = r["shift"]
    lines = [
        f"Escalera de líneas ({r['version']}, variante {r['mode']}) · {r['matches']} partidos",
        f"  no publicables: {r['before']['not_publishable']} antes, {r['after']['not_publishable']} después ({r['made_publishable']} pasan a publicables)",
    ]
    for t, name in battery.NAMES.items():
        lines.append(
            f"  prueba {t} · {name}: {r['before']['violations_by_test'][t]} antes, {r['after']['violations_by_test'][t]} después"
        )
    lines.append(
        f"  cifras: {int(s['figures'])} · movidas {s['share_moved'] * 100:.1f} % · media {s['mean_shift'] * 100:.2f} pp · mediana {s['median_shift'] * 100:.2f} pp · "
        f"p90 {s['p90_shift'] * 100:.2f} pp · máximo {s['max_shift'] * 100:.2f} pp"
    )
    lines.append(
        "  líneas sin escalera completa (se quedan como están): " + str(r["moves"].get("kept", 0))
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--limit", type=int, default=600)
    ap.add_argument("--mode", choices=ladder.MODES, default="pooled")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn", default=None)
    args = ap.parse_args(argv)
    try:
        if args.dsn:
            dsn = args.dsn
        else:
            from fbi.core.config import settings

            dsn = settings.database.psycopg_url
        at = datetime.now(UTC)
        with psycopg.connect(dsn, options=READ_ONLY) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                ids = [
                    int(r["fixture_id"])
                    for r in cur.execute(
                        FIXTURES_SQL,
                        {
                            "at": at,
                            "until": at + timedelta(hours=args.hours),
                            "page": PAGE_VERSION,
                            "limit": args.limit,
                        },
                    ).fetchall()
                ]
            sets = figures_at(conn, ids, at=at, cal=calibration_state(conn, at=at)) if ids else {}
        out = report(
            [battery_audit.figures_of(fs) for _, fs in sorted(sets.items())], mode=args.mode
        )
    except (psycopg.Error, ValueError) as exc:
        sys.stderr.write(f"cannot run: {type(exc).__name__}: {exc}\n")
        return CANNOT
    sys.stdout.write(
        json.dumps(out, ensure_ascii=False, indent=1, default=str, sort_keys=True) + "\n"
        if args.as_json
        else render(out)
    )
    return OK


if __name__ == "__main__":
    sys.exit(main())
