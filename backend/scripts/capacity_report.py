"""API-Football consumption, measured, and the room for more leagues, projected.

    python -m scripts.capacity_report                  # 0 provider requests
    python -m scripts.capacity_report --probe 120      # + one /odds?league&season page per top candidate league
                                                       #   (liquidity proxy: bookmakers per priced fixture)

Writes data/capacity/<stamp>/capacity.json and CAPACITY.md.

What is MEASURED: requests per day (raw.provider_quota, the counter the budget bills against), requests per job and
per day (raw.ingestion_runs.api_calls), what each recurring job costs per fixture and per league, the provider's
coverage flags and odds mapping for every league it has (raw.league_coverage, market.odds_mapping_seen), and - with
--probe - how many bookmakers price a candidate league's fixtures.

What is ASSUMED, and said so in the report: the recurring cost of a new league equals the measured cost of a tracked
one per fixture and per league; the pre-match capture costs one request per window (six) plus one final read per
priced fixture, as it does since the re-ask fix of 5 Oct 2026 (before it, an unpriced fixture was asked every tick);
one-off loads (history migration, first fill of the reference feeds, audits) are kept out of the steady state and
reported apart.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.version import code_version

OUT_ROOT = Path("data/capacity")

JOB_CATEGORY: dict[str, str] = {
    "fixtures_sync": "fixtures", "catalogue_refresh": "fixtures", "teams_sync": "teams",
    "team_identity_resolve": "teams", "odds_capture": "odds_prematch", "final_prematch": "odds_prematch",
    "window_probe": "odds_prematch", "live_odds_capture": "odds_live", "results_sync": "results",
    "results_repair": "results", "live_match_capture": "results", "post_match_detail": "lineups_statistics",
    "context_due": "standings_injuries", "context_refresh": "standings_injuries",
    "context_refresh_manual": "standings_injuries", "reference_refresh": "reference",
    "historical_backfill": "migration", "raw_backfill_fixture_facts": "migration", "truth_audit": "audits",
    "research_monitor": "research", "plan_probe": "other", "capacity_probe": "audits",
}
ONE_OFF = {"migration", "audits", "research"}
ONE_OFF_JOBS = {"context_refresh_manual"}
STEADY_REFERENCE_PER_DAY = 3_500
"""fbi.ingestion.reference: once the first fill (~23,500 requests) is done, the reference feeds cost about 3,500 a day
for the 4 Oct 2026 scope. While the first fill runs, the measured figure is higher and is reported as one-off."""
PREMATCH_WINDOWS = 6
"""T-72 h, -48 h, -24 h, -12 h, -6 h, -3 h (settings.odds.prematch_windows)."""

TOP_MARKETS = {"England", "Spain", "Germany", "Italy", "France", "Netherlands", "Portugal", "Belgium", "Turkey",
               "Scotland", "Austria", "Switzerland", "Denmark", "Sweden", "Norway", "Poland", "Czech-Republic",
               "Greece", "Brazil", "Argentina", "USA", "Mexico", "Japan", "South-Korea", "Australia",
               "Saudi-Arabia", "World", "Croatia", "Serbia", "Romania", "Ukraine", "Russia", "Colombia", "Chile",
               "Ireland", "Finland", "Israel", "Hungary", "Slovakia", "Slovenia", "Bulgaria", "Cyprus", "China",
               "Uruguay", "Paraguay", "Peru", "Ecuador", "Egypt", "Morocco", "South-Africa", "Qatar", "UAE"}
"""Football betting markets with depth. A judgement, stated as one: it weighs business interest, nothing else."""
YOUTH_OR_RESERVE = ("u17", "u18", "u19", "u20", "u21", "u23", "youth", "reserve", "primavera", "women", "feminin",
                    "femenin", "frauen", "w-league", "liga mx femenil", "junior", " ii", " b ")


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def percentiles(values: list[float]) -> dict[str, float | None]:
    return {"n_days": len(values), "min": min(values) if values else None, "p25": _pct(values, 0.25),
            "median": _pct(values, 0.5), "p75": _pct(values, 0.75), "p90": _pct(values, 0.9),
            "p95": _pct(values, 0.95), "max": max(values) if values else None}


@dataclass
class Candidate:
    provider_league_id: int
    season: int
    name: str
    country: str | None
    league_type: str | None
    mapped_7d: int
    """Fixtures in the provider's odds mapping within a week either side of now."""
    flags: dict[str, bool | None]
    seasons_with_stats: int
    seasons_with_odds: int
    bookmakers_avg: float | None = None
    bookmakers_max: int | None = None
    probe_fixtures: int | None = None
    score: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    fixtures_per_day: float = 0.0
    requests_per_day: float = 0.0


DAILY_SQL = """
SELECT quota_date, spent, budget FROM raw.provider_quota
 WHERE provider = 'api_football' AND budget >= 1000 ORDER BY quota_date
"""

JOBS_SQL = """
SELECT (started_at AT TIME ZONE 'UTC')::date AS day, job_type, count(*) AS runs, sum(api_calls) AS calls
  FROM raw.ingestion_runs WHERE started_at >= %(since)s AND api_calls > 0 GROUP BY 1, 2
"""

ENDPOINTS_SQL = """
SELECT r.job_type, p.endpoint, count(*) AS n FROM raw.ingestion_payloads p JOIN raw.ingestion_runs r ON r.id = p.run_id
 WHERE r.started_at >= %(since)s AND r.job_type = ANY(%(jobs)s) GROUP BY 1, 2
"""

FIXTURES_PER_DAY_SQL = """
SELECT (f.kickoff_at AT TIME ZONE 'UTC')::date AS day, count(*) AS n
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at BETWEEN %(since)s AND %(until)s GROUP BY 1
"""

PRICED_SHARE_SQL = """
SELECT count(*) AS fixtures,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM market.odds_mapping_seen m
                                       WHERE m.provider_fixture_id = f.provider_fixture_id)
                           OR EXISTS (SELECT 1 FROM market.odds_snapshots o WHERE o.fixture_id = f.id)) AS priced
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at BETWEEN %(since)s AND %(until)s
"""

TRACKED_SQL = "SELECT count(*) FROM core.competitions WHERE is_tracked"

CANDIDATES_SQL = """
WITH cur AS (
    SELECT DISTINCT ON (lc.provider_league_id) lc.*
      FROM raw.league_coverage lc
     WHERE lc.is_current
     ORDER BY lc.provider_league_id, lc.season DESC, lc.observed_at DESC
), hist AS (
    SELECT provider_league_id, count(DISTINCT season) FILTER (WHERE statistics_fixtures) AS stats_seasons,
           count(DISTINCT season) FILTER (WHERE odds) AS odds_seasons
      FROM raw.league_coverage GROUP BY 1
), mapped AS (
    SELECT provider_league_id, count(*) AS n FROM market.odds_mapping_seen
     WHERE fixture_date BETWEEN %(since)s AND %(until)s GROUP BY 1
)
SELECT cur.provider_league_id, cur.season, cur.league_name, cur.country, cur.league_type, cur.events, cur.lineups,
       cur.statistics_fixtures, cur.statistics_players, cur.standings, cur.players, cur.injuries, cur.predictions,
       cur.odds, coalesce(hist.stats_seasons, 0) AS stats_seasons, coalesce(hist.odds_seasons, 0) AS odds_seasons,
       coalesce(mapped.n, 0) AS mapped
  FROM cur
  LEFT JOIN hist ON hist.provider_league_id = cur.provider_league_id
  LEFT JOIN mapped ON mapped.provider_league_id = cur.provider_league_id
 WHERE NOT EXISTS (SELECT 1 FROM core.competitions c WHERE c.provider_league_id = cur.provider_league_id
                    AND c.is_tracked)
   AND coalesce(mapped.n, 0) > 0
"""

BACKFILL_SQL = """
SELECT kind, count(*) AS tasks, sum(requests_spent) AS requests,
       count(DISTINCT (provider_league_id, season)) AS league_seasons
  FROM raw.backfill_tasks WHERE status = 'done' GROUP BY 1
"""


def category_of(job: str, endpoint_shares: dict[str, dict[str, float]]) -> dict[str, float]:
    """A job's calls by category; a job that reads several endpoints is split by its payloads' endpoints."""
    if job.startswith("truth_"):
        return {"audits": 1.0}
    if job in ("reference_refresh", "context_due", "context_refresh") and endpoint_shares.get(job):
        out: dict[str, float] = defaultdict(float)
        for endpoint, share in endpoint_shares[job].items():
            out[_endpoint_category(endpoint)] += share
        return dict(out)
    return {JOB_CATEGORY.get(job, "other"): 1.0}


def _endpoint_category(endpoint: str) -> str:
    if endpoint == "/standings":
        return "standings"
    if endpoint in ("/injuries", "/sidelined"):
        return "injuries"
    if endpoint.startswith("/players") or endpoint in ("/transfers", "/trophies"):
        return "players"
    if endpoint.startswith("/teams") or endpoint in ("/coachs", "/venues"):
        return "teams"
    if endpoint.startswith("/odds"):
        return "odds_prematch"
    if endpoint.startswith("/fixtures") or endpoint in ("/leagues", "/predictions"):
        return "fixtures"
    return "other"


def measure(conn: psycopg.Connection[Any], at: datetime) -> dict[str, Any]:
    today = at.date()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DAILY_SQL)
        daily = list(cur.fetchall())
        first = daily[0]["quota_date"] if daily else today
        since = datetime.combine(first, datetime.min.time(), tzinfo=UTC)
        cur.execute(JOBS_SQL, {"since": since})
        jobs = cur.fetchall()
        cur.execute(ENDPOINTS_SQL, {"since": since,
                                    "jobs": ["reference_refresh", "context_due", "context_refresh"]})
        ep_rows = cur.fetchall()
        cur.execute(FIXTURES_PER_DAY_SQL, {"since": since, "until": at + timedelta(days=7)})
        fixtures_per_day = {r["day"]: int(r["n"]) for r in cur.fetchall()}
        cur.execute(PRICED_SHARE_SQL, {"since": at - timedelta(days=7), "until": at + timedelta(days=7)})
        priced = cur.fetchone() or {"fixtures": 0, "priced": 0}
        cur.execute(TRACKED_SQL)
        tracked = int((cur.fetchone() or {"count": 0})["count"])
        cur.execute(BACKFILL_SQL)
        backfill = cur.fetchall()
    shares: dict[str, dict[str, float]] = {}
    totals: dict[str, int] = defaultdict(int)
    for r in ep_rows:
        totals[r["job_type"]] += int(r["n"])
    for r in ep_rows:
        shares.setdefault(r["job_type"], {})[r["endpoint"]] = int(r["n"]) / totals[r["job_type"]]

    by_day: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_day_job: dict[date, dict[str, int]] = defaultdict(dict)
    for r in jobs:
        calls = int(r["calls"] or 0)
        by_day_job[r["day"]][r["job_type"]] = calls
        for cat, share in category_of(r["job_type"], shares).items():
            key = cat if r["job_type"] not in ONE_OFF_JOBS else "migration"
            by_day[r["day"]][key] += calls * share
    days = []
    for r in daily:
        d = r["quota_date"]
        cats = {k: round(v) for k, v in sorted(by_day.get(d, {}).items())}
        recurring = sum(v for k, v in cats.items() if k not in ONE_OFF and k != "reference")
        days.append({"day": d.isoformat(), "total": int(r["spent"]), "complete": d < today, "categories": cats,
                     "jobs": dict(sorted(by_day_job.get(d, {}).items(), key=lambda kv: -kv[1])),
                     "recurring_without_reference": round(recurring),
                     "tracked_fixtures_kicked_off": fixtures_per_day.get(d, 0)})
    complete = [d for d in days if d["complete"] and d["total"] > 0]
    return {"daily": days, "tracked_competitions": tracked, "fixtures_per_day": {
        k.isoformat(): v for k, v in sorted(fixtures_per_day.items())},
        "priced_share": (int(priced["priced"]) / int(priced["fixtures"])) if priced["fixtures"] else None,
        "totals_percentiles": percentiles([float(d["total"]) for d in complete]),
        "recurring_percentiles": percentiles([float(d["recurring_without_reference"]) for d in complete]),
        "backfill": [dict(r) for r in backfill], "endpoint_shares": shares}


def cost_model(m: dict[str, Any]) -> dict[str, Any]:
    """Steady-state requests per day = fixed + per league x leagues + per fixture x fixtures, from the measured
    days with the pre-match capture at its post-fix cost."""
    complete = [d for d in m["daily"] if d["complete"]]
    recent = complete[-3:] if complete else []

    def per_day(job: str) -> float:
        xs = [d["jobs"].get(job, 0) for d in recent]
        return statistics.mean(xs) if xs else 0.0

    fixtures = statistics.mean([d["tracked_fixtures_kicked_off"] for d in recent]) if recent else 0.0
    per_fixture_live = (per_day("live_match_capture") + per_day("post_match_detail") + per_day("results_sync")
                        + per_day("results_repair")) / fixtures if fixtures else 0.0
    priced = m["priced_share"] or 0.0
    per_fixture_odds = PREMATCH_WINDOWS + priced * 1.0  # one ask per window + the final read of a priced fixture
    leagues = max(m["tracked_competitions"], 1)
    per_league = (per_day("fixtures_sync") + per_day("context_due") + per_day("context_refresh")
                  + STEADY_REFERENCE_PER_DAY) / leagues
    fixed = per_day("live_odds_capture") + per_day("catalogue_refresh")
    return {"basis_days": [d["day"] for d in recent], "fixtures_per_day_basis": round(fixtures, 1),
            "fixed_per_day": round(fixed), "per_league_per_day": round(per_league, 1),
            "per_fixture": round(per_fixture_odds + per_fixture_live, 2),
            "per_fixture_odds": round(per_fixture_odds, 2), "per_fixture_live_and_results": round(per_fixture_live, 2),
            "priced_share": priced,
            "measured_odds_capture_per_day_before_fix": round(per_day("odds_capture"))}


def score(c: Candidate, max_mapped: int) -> None:
    f = c.flags
    name = f" {c.name.lower()} "
    market = math.log1p(c.mapped_7d) / math.log1p(max_mapped) if max_mapped else 0.0
    liquidity = min((c.bookmakers_avg or 0) / 12.0, 1.0) if c.bookmakers_avg is not None else market * 0.8
    data = sum(1.0 for k in ("events", "lineups", "statistics_fixtures", "statistics_players") if f.get(k)) / 4
    depth = min(c.seasons_with_stats, 8) / 8
    interest = (1.0 if (c.country or "") in TOP_MARKETS else 0.5) * (
        0.3 if any(t in name for t in YOUTH_OR_RESERVE) else 1.0)
    usefulness = (1.0 if c.league_type == "League" else 0.6) * (1.0 if f.get("standings") else 0.7)
    c.components = {"market": round(market, 3), "liquidity": round(liquidity, 3), "data": round(data, 3),
                    "depth": round(depth, 3), "interest": round(interest, 3), "usefulness": round(usefulness, 3)}
    c.score = round(0.20 * market + 0.20 * liquidity + 0.20 * data + 0.10 * depth + 0.20 * interest
                    + 0.10 * usefulness, 4)


def candidates(conn: psycopg.Connection[Any], at: datetime) -> list[Candidate]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CANDIDATES_SQL, {"since": at - timedelta(days=7), "until": at + timedelta(days=7)})
        rows = cur.fetchall()
    out = []
    for r in rows:
        if r["odds"] is False:
            continue
        out.append(Candidate(
            int(r["provider_league_id"]), int(r["season"]), str(r["league_name"]), r["country"], r["league_type"],
            int(r["mapped"]), {k: r[k] for k in ("events", "lineups", "statistics_fixtures", "statistics_players",
                                                 "standings", "players", "injuries", "predictions", "odds")},
            int(r["stats_seasons"]), int(r["odds_seasons"])))
    top = max((c.mapped_7d for c in out), default=0)
    for c in out:
        score(c, top)
    return sorted(out, key=lambda c: -c.score)


async def probe(conn: psycopg.Connection[Any], cands: list[Candidate], limit: int) -> int:
    """One /odds?league&season (page 1) per candidate: bookmakers per priced fixture. Stored as RAW, ledgered."""
    from fbi.ingestion.ledger import RunCounters, RunLedger
    from fbi.providers.api_football.build import build_client
    from fbi.providers.api_football.provider import _raw

    ledger = RunLedger(conn)
    run_id = ledger.open("capacity_probe", params={"leagues": min(limit, len(cands))})
    counters = RunCounters()
    client = build_client(max_requests=limit)
    try:
        for c in cands[:limit]:
            try:
                resp = await client.get("/odds", {"league": c.provider_league_id, "season": c.season})
            except Exception as exc:  # a probe failure is a finding, not a crash
                counters.errors.append(f"{c.provider_league_id}: {type(exc).__name__}: {exc}"[:300])
                continue
            counters.api_calls += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [_raw(resp)])
            entries = [e for e in (resp.body.get("response") or []) if isinstance(e, dict)]
            books = [len(e.get("bookmakers") or []) for e in entries]
            c.probe_fixtures = len(entries)
            c.bookmakers_avg = round(statistics.mean(books), 2) if books else 0.0
            c.bookmakers_max = max(books) if books else 0
            conn.commit()
    finally:
        await client.aclose()
        ledger.close(run_id, counters, notes=f"capacity probe: {counters.api_calls} requests")
    return run_id


def scenarios(model: dict[str, Any], m: dict[str, Any], cands: list[Candidate], days: int = 14
              ) -> list[dict[str, Any]]:
    """Requests per day for 0, 25, 50 and 75 added leagues, on a normal, busy (P90), P95 and worst day.

    Day types come from the tracked fixtures per day (measured); an added league's fixtures follow the same shape:
    its mean per day (the provider's odds mapping, a week either side of now) times the day type's ratio to the
    tracked mean."""
    fixtures = [float(v) for v in m["fixtures_per_day"].values() if v > 0]
    mean_fx = statistics.mean(fixtures) if fixtures else 0.0
    day_types = {"normal": _pct(fixtures, 0.5) or 0.0, "busy": _pct(fixtures, 0.9) or 0.0,
                 "p95": _pct(fixtures, 0.95) or 0.0, "worst": max(fixtures) if fixtures else 0.0}
    out = []
    for added in (0, 25, 50, 75):
        extra_mean = sum(c.mapped_7d for c in cands[:added]) / days
        rows: dict[str, Any] = {}
        for label, base in day_types.items():
            fx = base + (extra_mean * base / mean_fx if mean_fx else extra_mean)
            req = (model["fixed_per_day"] * (1 + 0.3 * added / 50)
                   + model["per_league_per_day"] * (m["tracked_competitions"] + added)
                   + model["per_fixture"] * fx)
            rows[label] = {"fixtures": round(fx), "requests": round(req)}
        out.append({"added_leagues": added, "added_fixtures_per_day_mean": round(extra_mean, 1), **rows})
    return out


def markdown(report: dict[str, Any]) -> str:
    lines = [f"# API-Football capacity - {report['at'][:16]}Z", "",
             f"Plan: **{report['plan']['name']}**, provider limit {report['plan']['per_day']:,}/day, "
             f"{report['plan']['per_minute']}/min; internal budget {report['plan']['internal_budget']:,}/day. "
             f"Code {report['code_version']}.", "", "## Measured days", "",
             "| Day | Total | Recurring (no reference) | Fixtures | Biggest jobs |", "|---|---:|---:|---:|---|"]
    for d in report["measured"]["daily"]:
        top = ", ".join(f"{k} {v:,}" for k, v in list(d["jobs"].items())[:4])
        lines.append(f"| {d['day']}{'' if d['complete'] else ' (partial)'} | {d['total']:,} | "
                     f"{d['recurring_without_reference']:,} | {d['tracked_fixtures_kicked_off']} | {top} |")
    tp, rp = report["measured"]["totals_percentiles"], report["measured"]["recurring_percentiles"]
    lines += ["", f"Complete days: {tp['n_days']}. Totals: min {tp['min']}, P25 {tp['p25']}, median {tp['median']}, "
              f"P75 {tp['p75']}, P90 {tp['p90']}, P95 {tp['p95']}, max {tp['max']}.",
              f"Recurring without the reference feeds: median {rp['median']}, P95 {rp['p95']}, max {rp['max']}.", "",
              "## Steady-state cost model", "", "```", json.dumps(report["model"], indent=2), "```", "",
              "## Scenarios (steady state, requests/day)", "",
              "| Added leagues | Normal | Busy | P95 | Worst | Headroom at P95 (internal / provider) |",
              "|---:|---:|---:|---:|---:|---|"]
    for s in report["scenarios"]:
        p95 = s["p95"]["requests"]
        lines.append(f"| {s['added_leagues']} | {s['normal']['requests']:,} | {s['busy']['requests']:,} | "
                     f"{p95:,} | {s['worst']['requests']:,} | {report['plan']['internal_budget'] - p95:,} / "
                     f"{report['plan']['per_day'] - p95:,} |")
    lines += ["", "## Top 50 candidate leagues", "",
              "| # | League | Country | Type | Fixtures priced (±7 d) | Bookmakers avg | Data | Score |",
              "|---:|---|---|---|---:|---:|---:|---:|"]
    for i, c in enumerate(report["candidates"][:50], 1):
        lines.append(f"| {i} | {c['name']} ({c['provider_league_id']}) | {c['country']} | {c['league_type']} | "
                     f"{c['mapped_7d']} | {c['bookmakers_avg'] if c['bookmakers_avg'] is not None else '-'} | "
                     f"{c['components'].get('data')} | {c['score']} |")
    lines += ["", "Assumptions: " + report["assumptions"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(prog="capacity_report", description=__doc__)
    parser.add_argument("--probe", type=int, default=0, help="request /odds?league&season for the top N candidates")
    args = parser.parse_args()
    at = now()
    cfg = settings.api_football
    with psycopg.connect(settings.database.psycopg_url) as conn:
        m = measure(conn, at)
        model = cost_model(m)
        cands = candidates(conn, at)
        probe_run = None
        if args.probe:
            probe_run = asyncio.run(probe(conn, cands, args.probe))
            top = max((c.mapped_7d for c in cands), default=0)
            for c in cands:
                score(c, top)
            cands.sort(key=lambda c: -c.score)
    report = {
        "at": at.isoformat(), "code_version": code_version(), "probe_run_id": probe_run,
        "plan": {"name": cfg.plan, "per_day": cfg.per_day_limit, "per_minute": cfg.per_minute_limit,
                 "internal_budget": cfg.daily_budget},
        "measured": m, "model": model, "scenarios": scenarios(model, m, cands),
        "candidates": [asdict(c) for c in cands[:120]], "candidates_total": len(cands),
        "assumptions": ("a new league costs what a tracked one costs per league and per fixture; the pre-match "
                        "capture asks once per window (6) plus one final read per priced fixture (post-fix); "
                        "live odds grow 30% per 50 leagues (more hours in play, one request a tick regardless); "
                        "busy/P95/worst days scale the added leagues' fixtures by the measured weekend factor; "
                        "one-off loads (history migration, the reference first fill, audits) are not steady state"),
    }
    folder = OUT_ROOT / at.strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "capacity.json").write_text(json.dumps(report, indent=2, default=str))
    (folder / "CAPACITY.md").write_text(markdown(report))
    print(folder / "CAPACITY.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
