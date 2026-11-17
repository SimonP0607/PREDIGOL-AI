"""The score matrix of each match beside what each market states today (``matrix-v1``, AD-B04, IA-074), in shadow and read-only.

    python -m scripts.ia_score_matrix check --hours 72
    python -m scripts.ia_score_matrix check --hours 72 --json

For every match that kicks off in the next ``--hours`` and has a page forecast (``forecast-v1``): each goal model in force
(``models.predictions``: the newest real-time forecast of Poisson and Dixon-Coles) gives back its expected goals from its own seven fixed
rows (``fbi.simulator.consistency.invert``: the model's arithmetic solved on its own numbers, nothing fitted), the matrix is built
(``fbi.forecasting.score_matrix``) and every market of the menu is derived from it. Then, market by market:

    stored ...... the model's own stored rows (1X2, every over/under and Asian line, double chance, BTTS) against the matrix: they
                  are the same arithmetic, so this is the regression (largest difference, the rounding of six decimals)
    page ........ what the page states (``forecast-v1``: 1X2, over/under 2.5, BTTS, each calibrated on its own) against the matrix of
                  the same model, and the page's markets checked TOGETHER (a set coherent by construction obeys the bounds between
                  the 1X2, BTTS and over 2.5; markets calibrated one by one need not)
    decisions ... the calibrated probability of each selection the decision layer judged (``decision-v1``, ``p_cal``) against the
                  matrix of the same model, and the decisions of one match checked together (double chance against the 1X2, etc.)

Read-only: the connection refuses writes; nothing is asked of a provider or of a model; nothing here is read by a decision, a pick, a
forecast or a page. Exit 0 with a report, 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.forecasting import score_matrix as sm
from fbi.simulator import consistency

OK, CANNOT = 0, 2
PAGE_VERSION: Final = "forecast-v1"
"""``fbi.forecasting.market_view.VERSION`` (a test holds the two equal)."""
DECISION_VERSION: Final = "decision-v1"
"""``fbi.core.decision_versions.DECISION_CORE`` (a test holds the two equal)."""
STORED_TOLERANCE: Final = 2e-6
"""A stored probability is rounded to six decimals: a sum of three of them can be off by 1.5e-6 without being incoherent."""
EXAMPLES: Final = 5

FIXTURES_SQL: Final = """
SELECT f.id AS fixture_id, f.kickoff_at
  FROM core.fixtures f
 WHERE f.kickoff_at > %(at)s AND f.kickoff_at <= %(until)s
   AND EXISTS (SELECT 1 FROM models.match_forecasts x WHERE x.fixture_id = f.id AND x.version = %(page)s AND x.known_at <= %(at)s)
 ORDER BY f.kickoff_at, f.id
 LIMIT %(limit)s
"""

PAGE_SQL: Final = """
WITH last AS (
    SELECT market_key, line, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = %(f)s AND version = %(page)s AND known_at <= %(at)s
     GROUP BY 1, 2
)
SELECT x.market_key, x.line, x.selection, x.p::float8 AS p, x.model_name, x.calibration
  FROM models.match_forecasts x JOIN last l ON l.market_key = x.market_key AND l.line = x.line AND l.k = x.known_at
 WHERE x.fixture_id = %(f)s AND x.version = %(page)s
"""

DECISIONS_SQL: Final = """
SELECT DISTINCT ON (market_key, selection, line) market_key, selection, line, model_name, p_cal::float8 AS p_cal,
       COALESCE(p_push, 0)::float8 AS p_push
  FROM intel.decisions
 WHERE fixture_id = %(f)s AND decision_version = %(decision)s AND known_at <= %(at)s AND p_cal IS NOT NULL
 ORDER BY market_key, selection, line, known_at DESC, id DESC
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_score_matrix", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("check",))
    ap.add_argument("--hours", type=int, default=72, help="matches kicking off in the next HOURS (default 72)")
    ap.add_argument("--limit", type=int, default=400, help="at most this many matches (default 400)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    xs = sorted(values)
    return {"n": len(xs), "median": round(statistics.median(xs), 6), "p90": round(xs[min(len(xs) - 1, int(0.9 * len(xs)))], 6),
            "max": round(xs[-1], 6), "over_0_5pp": sum(1 for x in xs if x > 0.005)}


class Tally:
    """Differences per (source, market) and coherence violations per (source, rule), with a few examples."""

    def __init__(self) -> None:
        self.diffs: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self.rules: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.sets: dict[str, int] = defaultdict(int)
        self.incoherent_sets: dict[str, int] = defaultdict(int)
        self.examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.missing: dict[str, int] = defaultdict(int)

    def add_diffs(self, source: str, diffs: Iterable[sm.Diff]) -> None:
        for d in diffs:
            self.diffs[source][d.market_key].append(d.abs_diff)

    def add_set(self, source: str, fixture_id: int, found: list[sm.Violation]) -> None:
        self.sets[source] += 1
        if found:
            self.incoherent_sets[source] += 1
        for v in found:
            self.rules[source][v.rule] += 1
            if len(self.examples[source]) < EXAMPLES:
                self.examples[source].append({"fixture_id": fixture_id, "rule": v.rule, "detail": v.detail})

    def report(self) -> dict[str, Any]:
        return {
            "differences": {s: {m: _stats(v) for m, v in sorted(by.items())} for s, by in sorted(self.diffs.items())},
            "coherence": {s: {"sets": self.sets[s], "incoherent_sets": self.incoherent_sets[s],
                              "rules": dict(sorted(self.rules[s].items())), "examples": self.examples[s]}
                          for s in sorted(self.sets)},
            "not_in_menu": dict(self.missing),
        }


def _published(rows: Iterable[dict[str, Any]], p: str = "p", push: str | None = None) -> list[sm.Published]:
    return [sm.Published(str(r["market_key"]), str(r["selection"]), Decimal(r["line"]), float(r[p]),
                         float(r[push]) if push else 0.0) for r in rows]


def check(conn: psycopg.Connection[Any], *, at: datetime, hours: int, limit: int) -> dict[str, Any]:
    tally = Tally()
    inversions: list[float] = []
    status: dict[str, int] = defaultdict(int)
    with conn.cursor(row_factory=dict_row) as cur:
        fixtures = cur.execute(FIXTURES_SQL, {"at": at, "until": at + timedelta(hours=hours), "page": PAGE_VERSION,
                                              "limit": limit}).fetchall()
    for f in fixtures:
        fid = int(f["fixture_id"])
        prices: dict[str, sm.Prices] = {}
        for mf in consistency.in_force(conn, fid, at):
            if mf.model not in sm.GOAL_MODELS:
                continue
            inv = consistency.invert(mf.rows, mf.model)
            if inv is None:
                status["not_invertible"] += 1
                continue
            inversions.append(inv.residual)
            if inv.residual > consistency.INVERSION_TOLERANCE:
                status["incoherent_fixed_rows"] += 1
                continue
            try:
                matrix = sm.build(sm.Params(inv.lam_home, inv.lam_away, inv.rho, mf.model, mf.version_id))
            except ValueError:  # InvalidCorrectionError included: refused, never clipped
                status["invalid_correction"] += 1
                continue
            stored = [sm.Published(r.market_key, r.selection, Decimal(str(r.line)), r.p, r.p_push) for r in mf.rows]
            lines: dict[str, set[Decimal]] = defaultdict(set)
            for x in stored:
                lines[x.market_key].add(x.line if x.market_key != "AH" or x.selection == "Home" else -x.line + 0)
            derived = sm.derive(matrix, ou_lines=set(sm.OU_LINES) | lines["OU"], ah_lines=set(sm.AH_LINES) | lines["AH"])
            prices[mf.model] = derived
            status["matrices"] += 1
            tally.add_set("matrix", fid, sm.coherence(derived))
            diffs, missing = sm.compare(derived, stored)
            tally.missing["stored"] += missing
            tally.add_diffs(f"stored:{mf.model}", diffs)
            tally.add_set("stored", fid, sm.published_coherence(stored, tol=STORED_TOLERANCE))
        with conn.cursor(row_factory=dict_row) as cur:
            page = cur.execute(PAGE_SQL, {"f": fid, "at": at, "page": PAGE_VERSION}).fetchall()
            decisions = cur.execute(DECISIONS_SQL, {"f": fid, "at": at, "decision": DECISION_VERSION}).fetchall()
        tally.add_set("page", fid, sm.published_coherence(_published(page), tol=STORED_TOLERANCE))
        for r in page:
            model = str(r["model_name"])
            if model in prices:
                d, _ = sm.compare(prices[model], _published([r]))
                tally.add_diffs(f"page:{r['calibration']}", d)
        if decisions:
            tally.add_set("decisions", fid, sm.published_coherence(_published(decisions, "p_cal", "p_push"),
                                                                   tol=STORED_TOLERANCE))
        for r in decisions:
            model = str(r["model_name"])
            if model in prices:
                d, missing = sm.compare(prices[model], _published([r], "p_cal"))
                tally.missing["decisions"] += missing
                tally.add_diffs("decisions", d)
    return {"version": sm.VERSION, "shadow": True, "at": at.isoformat(), "hours": hours, "fixtures": len(fixtures),
            "status": dict(status), "inversion_residual": _stats(inversions), **tally.report()}


def render(doc: dict[str, Any]) -> str:
    lines = [f"{doc['version']} (shadow) at {doc['at']}: {doc['fixtures']} matches in the next {doc['hours']} h; {doc['status']}"]
    for source, by in doc["differences"].items():
        lines.append(f"  {source}")
        lines += [f"    {m:<8} {s}" for m, s in by.items()]
    for source, c in doc["coherence"].items():
        lines.append(f"  coherence {source}: {c['incoherent_sets']} of {c['sets']} sets incoherent {c['rules']}")
        lines += [f"    {e}" for e in c["examples"]]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.hours <= 0 or args.limit <= 0:
        ap.error("--hours and --limit must be positive")
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000") as conn:
        doc = check(conn, at=datetime.now(UTC), hours=args.hours, limit=args.limit)
    sys.stdout.write((json.dumps(doc, indent=1, default=str, ensure_ascii=False) if args.as_json else render(doc)) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
