"""Where the outputs disagree with the single figure today (``forecast-v2``, AD-B05/AD-B09, IA-083/IA-084), surface by surface. Read-only.

    python -m scripts.ia_single_figure check --hours 24
    python -m scripts.ia_single_figure check --hours 72 --json

For the matches that kick off in the next ``--hours`` and have a page forecast (``forecast-v1``), the single figure is computed as of now
(``fbi.forecasting.market_reader.figures_at``) and set beside what each output states for the same selection:

    replay ........ the page's stored sets (``forecast-v1``) and the stable seal's (``forecast-v1-seal``), each recomputed by the single
                    figure AT ITS OWN MOMENT with its own price window: the regression in production (it must be 0 differences)
    page .......... what the Match Center states now (the newest ``forecast-v1`` set) against the single figure now, and why they differ
    decisions ..... decision-v1's calibrated probability (``intel.decisions.p_cal``, the newest of each selection) against the single
                    figure at the decision's own moment; and which of its selections the single figure covers (or ``not_in_view``)
    board ......... what the Picks board shows (``picks.picks``'s raw number, and the card's number with ``FBI_PICKS_SOURCE``) against the
                    single figure now
    coherence ..... the single figure's own sets checked together (``score_matrix.coherence``): where calibrating market by market breaks a
                    rule between markets
    texts ......... no text cites a reading yet (the one chronicle, AD-F02, is the first that will): said, not measured

Each difference is in percentage points; the criterion of AD-B05 is 0 differences above 0.05 points between outputs of the same version.
The connection is READ ONLY with a 95-second statement timeout; nothing is asked of a provider or a model and nothing is written. Exit 0
with a report, 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.forecasting import score_matrix as sm
from fbi.forecasting import single_figure as sf
from fbi.forecasting.market_reader import figures_at
from fbi.forecasting.market_view import MAX_MARKET_AGE
from fbi.intel.calibration import CalibrationState, calibration_state

OK, CANNOT = 0, 2
READ_ONLY: Final = "-c default_transaction_read_only=on -c statement_timeout=95000 -c TimeZone=UTC"
TOLERANCE_PP: Final = 0.05
"""AD-B05's closing criterion: no difference above 0.05 percentage points between outputs."""
PAGE_VERSION: Final = "forecast-v1"
SEAL_VERSION: Final = "forecast-v1-seal"
DECISION_VERSION: Final = "decision-v1"
EXAMPLES: Final = 5
COHERENCE_TOLERANCE: Final = 2e-6
"""A stored probability is rounded to six decimals: a set of the model's own rows can miss one by 1.5e-6 without being incoherent
(``scripts.ia_score_matrix.STORED_TOLERANCE``)."""
CORE_DECIDED: Final = ("1X2", "OU", "BTTS", "AH", "DC")

FIXTURES_SQL: Final = """
SELECT f.id AS fixture_id FROM core.fixtures f
 WHERE f.kickoff_at > %(at)s AND f.kickoff_at <= %(until)s
   AND EXISTS (SELECT 1 FROM models.match_forecasts x WHERE x.fixture_id = f.id AND x.version = %(page)s AND x.known_at <= %(at)s)
 ORDER BY f.kickoff_at, f.id LIMIT %(limit)s
"""

STORED_SQL: Final = """
WITH last AS (
    SELECT fixture_id, market_key, line, max(known_at) AS k
      FROM models.match_forecasts
     WHERE fixture_id = ANY(%(ids)s) AND version = %(version)s AND known_at <= %(at)s
     GROUP BY 1, 2, 3
)
SELECT x.fixture_id, x.market_key, x.selection, x.line, x.p::float8 AS p, x.model_name, x.calibration, x.basis, x.calibrator_id, x.known_at
  FROM models.match_forecasts x JOIN last l ON l.fixture_id = x.fixture_id AND l.market_key = x.market_key AND l.line = x.line
       AND l.k = x.known_at
 WHERE x.version = %(version)s
"""

DECISIONS_SQL: Final = """
SELECT DISTINCT ON (fixture_id, market_key, selection, line) fixture_id, market_key, selection, line, model_name, known_at,
       p_cal::float8 AS p_cal, p_model::float8 AS p_model, calibrator_id
  FROM intel.decisions
 WHERE fixture_id = ANY(%(ids)s) AND decision_version = %(version)s AND known_at <= %(at)s
 ORDER BY fixture_id, market_key, selection, line, known_at DESC, id DESC
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_single_figure", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("check",))
    ap.add_argument("--hours", type=int, default=24, help="matches kicking off in the next HOURS (default 24)")
    ap.add_argument("--limit", type=int, default=400, help="at most this many matches (default 400)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def stats(values: Sequence[float], tolerance: float = TOLERANCE_PP) -> dict[str, Any]:
    """Differences in points: how many, the median, the 90th percentile, the largest and how many above the tolerance."""
    if not values:
        return {"n": 0}
    xs = sorted(values)
    return {"n": len(xs), "median_pp": round(statistics.median(xs), 4), "p90_pp": round(xs[min(len(xs) - 1, int(0.9 * len(xs)))], 4),
            "max_pp": round(xs[-1], 4), "over_tolerance": sum(1 for x in xs if x > tolerance)}


def _key(r: Mapping[str, Any]) -> tuple[int, sf.PriceKey]:
    return int(r["fixture_id"]), sf.key_of(str(r["market_key"]), str(r["selection"]), r["line"])


def _pp(a: float, b: float) -> float:
    return abs(a - b) * 100


class Surface:
    """The differences of one output with the single figure, by market and by cause, with a few examples."""

    def __init__(self) -> None:
        self.by_market: dict[str, list[float]] = defaultdict(list)
        self.causes: Counter[str] = Counter()
        self.missing: Counter[str] = Counter()
        self.examples: list[dict[str, Any]] = []

    def add(self, fid: int, key: sf.PriceKey, stated: float, f: sf.Figure, cause: str) -> None:
        gap = _pp(stated, f.p)
        self.by_market[key[0]].append(gap)
        if gap > TOLERANCE_PP:
            self.causes[cause] += 1
            if len(self.examples) < EXAMPLES:
                self.examples.append({"fixture_id": fid, "market": key[0], "selection": key[1], "line": float(key[2]),
                                      "stated": round(stated, 6), "single_figure": round(f.p, 6), "gap_pp": round(gap, 3), "cause": cause,
                                      "figure_seal": f.label, "figure_basis": f.basis, "figure_model": f.model})

    def report(self) -> dict[str, Any]:
        every = [x for v in self.by_market.values() for x in v]
        return {"all": stats(every), "by_market": {m: stats(v) for m, v in sorted(self.by_market.items())},
                "causes_over_tolerance": dict(self.causes.most_common()), "without_figure": dict(self.missing.most_common()),
                "examples": self.examples}


def cause_of(stated_model: str | None, stated_calibrated: bool | None, f: sf.Figure) -> str:
    """The first reason that explains a gap: another model; another seal (one calibrated, the other not); else the calibration or the
    moment of the numbers."""
    if stated_model is not None and stated_model != f.model:
        return "different_model"
    if stated_calibrated is not None and stated_calibrated != (f.label == "calibrada"):
        return "different_seal"
    return "same_seal_other_number"


def _by_moment(rows: Iterable[Mapping[str, Any]]) -> dict[datetime, list[Mapping[str, Any]]]:
    out: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        out[r["known_at"]].append(r)
    return out


def replay(conn: psycopg.Connection[Any], rows: Sequence[Mapping[str, Any]], *, window: timedelta,
           cals: dict[datetime, CalibrationState]) -> dict[str, Any]:
    """Each stored set recomputed by the single figure at its own moment, with the window it was written with."""
    surface = Surface()
    for at, group in sorted(_by_moment(rows).items()):
        cal = cals.setdefault(at, calibration_state(conn, at=at))
        sets = figures_at(conn, sorted({int(r["fixture_id"]) for r in group}), at=at, cal=cal, max_age=window)
        for r in group:
            fid, key = _key(r)
            f = sets[fid].figures.get(key)
            if f is None:
                surface.missing["no_figure"] += 1
                continue
            surface.add(fid, key, float(r["p"]), f, cause_of(str(r["model_name"]), r["calibration"] == "CALIBRATED", f))
    return surface.report()


def check(conn: psycopg.Connection[Any], *, at: datetime, hours: int, limit: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        ids = [int(r["fixture_id"]) for r in cur.execute(FIXTURES_SQL, {"at": at, "until": at + timedelta(hours=hours), "page": PAGE_VERSION,
                                                                          "limit": limit}).fetchall()]
        page = cur.execute(STORED_SQL, {"ids": ids or [0], "version": PAGE_VERSION, "at": at}).fetchall()
        shadow = cur.execute(STORED_SQL, {"ids": ids or [0], "version": SEAL_VERSION, "at": at}).fetchall()
        decided = [r for r in cur.execute(DECISIONS_SQL, {"ids": ids or [0], "version": DECISION_VERSION, "at": at}).fetchall()
                   if str(r["market_key"]) in CORE_DECIDED]
    cals: dict[datetime, CalibrationState] = {}
    cal = cals.setdefault(at, calibration_state(conn, at=at))
    now = figures_at(conn, ids, at=at, cal=cal) if ids else {}

    page_now = Surface()
    for r in page:
        fid, key = _key(r)
        f = now[fid].figures.get(key)
        if f is None:
            page_now.missing["no_figure"] += 1
            continue
        page_now.add(fid, key, float(r["p"]), f, cause_of(str(r["model_name"]), r["calibration"] == "CALIBRATED", f))

    decisions = Surface()
    coverage: Counter[str] = Counter()
    for when, group in sorted(_by_moment(decided).items()):
        c = cals.setdefault(when, calibration_state(conn, at=when))
        by_fixture = figures_at(conn, sorted({int(d["fixture_id"]) for d in group}), at=when, cal=c)
        for d in group:
            fid, key = _key(d)
            fs = by_fixture.get(fid)
            f = None if fs is None else fs.figures.get(key)
            if f is None:
                coverage[sf.NO_READING if key[0] in sf.MENU else sf.NOT_IN_VIEW] += 1
                continue
            coverage["with_figure"] += 1
            if d["p_cal"] is not None:
                decisions.add(fid, key, float(d["p_cal"]), f, cause_of(str(d["model_name"]), d["calibrator_id"] is not None, f))

    coherence: Counter[str] = Counter()
    incoherent = 0
    examples: list[dict[str, Any]] = []
    for fid, fs in now.items():
        broken = sm.coherence(fs.prices(), tol=COHERENCE_TOLERANCE)
        if broken:
            incoherent += 1
        for v in broken:
            coherence[v.rule] += 1
            if len(examples) < EXAMPLES:
                examples.append({"fixture_id": fid, "rule": v.rule, "detail": v.detail})

    return {
        "at": at.isoformat(), "hours": hours, "fixtures": len(ids), "version": sf.VERSION, "tolerance_pp": TOLERANCE_PP,
        "figures": {"sets": len(now), "figures": sum(len(fs.figures) for fs in now.values()),
                    "seal": dict(Counter(f"{f.label} ({f.basis})" for fs in now.values() for f in fs.figures.values()).most_common()),
                    "source": dict(Counter(f.source for fs in now.values() for f in fs.figures.values()).most_common()),
                    "matrices": {"inverted": sum(1 for fs in now.values() for v in fs.matrices.values() if v is not None),
                                 "refused": sum(1 for fs in now.values() for v in fs.matrices.values() if v is None),
                                 "max_residual": max((v.residual for fs in now.values() for v in fs.matrices.values() if v is not None),
                                                     default=None)}},
        "replay": {"forecast-v1 (6 h)": replay(conn, page, window=MAX_MARKET_AGE, cals=cals),
                   "forecast-v1-seal (4 d)": replay(conn, shadow, window=sf.MARKET_AGE, cals=cals)},
        "page": page_now.report(),
        "decisions": decisions.report() | {"coverage": dict(coverage.most_common()), "rows": len(decided)},
        "board": board(conn, at=at, hours=hours, sets=now),
        "coherence": {"sets": len(now), "incoherent_sets": incoherent, "rules": dict(coherence.most_common()), "examples": examples},
        "texts": {"measured": False, "why": "ningún texto cita aún una lectura de forecast-v2 (la crónica única, AD-F02, será el primero)"},
    }


def board(conn: psycopg.Connection[Any], *, at: datetime, hours: int, sets: Mapping[int, sf.FigureSet]) -> dict[str, Any]:
    """The Picks board: the engine's raw number and the card's number with ``FBI_PICKS_SOURCE`` (as ``compare_probabilities`` reads them)."""
    from fbi.api.repositories import product as repo
    from fbi.api.services import picks_decision
    from fbi.api.services.product import CONSENSUS_LOOKBACK

    rows = repo.pick_candidates(conn, now=at, until=at + timedelta(hours=hours), since=at - CONSENSUS_LOOKBACK, include_shadow=True)
    fixtures = sorted({int(r["fixture_id"]) for r in rows})
    attached = picks_decision.attach(list(rows), list(repo.intel_decisions(conn, fixture_ids=fixtures, now=at)))
    raw, card = Surface(), Surface()
    seen: set[tuple[int, sf.PriceKey]] = set()
    for r in attached:
        fid, key = _key(r)
        if (fid, key) in seen:
            continue
        seen.add((fid, key))
        fs = sets.get(fid)
        f = None if fs is None else fs.figures.get(key)
        if f is None:
            why = "match_outside_window" if fs is None else (sf.NO_READING if key[0] in sf.MENU else sf.NOT_IN_VIEW)
            raw.missing[why] += 1
            continue
        raw.add(fid, key, float(r[picks_decision.RAW_MARK]), f, cause_of(None, False, f))
        card.add(fid, key, float(r["p_model"]), f, cause_of(None, None, f))
    return {"selections": len(seen), "raw (picks.picks)": raw.report(), "card (FBI_PICKS_SOURCE)": card.report()}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.dsn:
            dsn = args.dsn
        else:
            from fbi.core.config import settings
            dsn = settings.database.psycopg_url
        with psycopg.connect(dsn, options=READ_ONLY) as conn:
            report = check(conn, at=datetime.now(UTC), hours=args.hours, limit=args.limit)
    except (psycopg.Error, ValueError) as exc:
        sys.stderr.write(f"cannot run: {type(exc).__name__}: {exc}\n")
        return CANNOT
    if args.as_json:
        sys.stdout.write(json.dumps(report, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render(report))
    return OK


def render(r: Mapping[str, Any]) -> str:
    def line(name: str, s: Mapping[str, Any]) -> str:
        a = s["all"]
        if not a["n"]:
            return f"  {name}: sin selecciones comparables {s.get('without_figure') or ''}\n"
        return (f"  {name}: {a['n']} selecciones · mediana {a['median_pp']} pp · p90 {a['p90_pp']} · máximo {a['max_pp']} · "
                f"> {TOLERANCE_PP} pp: {a['over_tolerance']} {s['causes_over_tolerance'] or ''}\n")

    out = [f"Cifra única ({r['version']}) frente a cada salida · {r['at']} · {r['fixtures']} partidos en {r['hours']} h\n",
           f"  cifras: {r['figures']['figures']} en {r['figures']['sets']} partidos · sellos {r['figures']['seal']}\n"]
    for name, s in r["replay"].items():
        out.append(line(f"repetición {name}", s))
    out.append(line("Match Center ahora", r["page"]))
    out.append(line("decision-v1 (p_cal)", r["decisions"]))
    out.append(f"  cobertura de decision-v1: {r['decisions']['coverage']}\n")
    for name in ("raw (picks.picks)", "card (FBI_PICKS_SOURCE)"):
        out.append(line(f"Picks {name}", r["board"][name]))
    c = r["coherence"]
    out.append(f"  coherencia de la cifra única: {c['incoherent_sets']}/{c['sets']} partidos con alguna regla rota {c['rules']}\n")
    return "".join(out)


if __name__ == "__main__":
    raise SystemExit(main())

