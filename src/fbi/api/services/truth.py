"""Data truth for the Admin Console.

The audit runs are read back from ``audit.truth_runs``; freshness and the model gate
are measured live (a few seconds on the full database, so the answer is kept for two
minutes and the statement timeout is raised for this request only).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.api.contracts.truth import (
    CompetitionScoreRow,
    CoverageBookmaker,
    CoverageCompetition,
    CoverageCountry,
    CoverageLocal,
    CoverageMarket,
    DataRepair,
    FreshnessDataset,
    FreshnessReport,
    GateFixture,
    GateModel,
    GateReport,
    OddsCoverageReport,
    OddsSource,
    QuarantinedFixture,
    StandingsAuditRow,
    TruthFinding,
    TruthMatrixRow,
    TruthRun,
    TruthSummary,
    ValidationSummary,
)
from fbi.api.envelope import DataStatus, Envelope, listing, ok, unavailable
from fbi.catalog.segments import CompetitionFacts, segment_of
from fbi.core.clock import now
from fbi.market.coverage import build_report, is_critical
from fbi.providers.odds_sources import ODDS_SOURCES
from fbi.truth.freshness import measure, table_reason, table_state
from fbi.truth.gate import MODEL_NEEDS, evaluate

CACHE_SECONDS = 120.0
_cache: dict[str, tuple[float, Any]] = {}


def _cached[T](key: str, compute: Callable[[], T]) -> T:
    hit = _cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]  # type: ignore[no-any-return]
    value = compute()
    _cache[key] = (time.monotonic(), value)
    return value


def _rows(conn: psycopg.Connection[Any], sql: str, params: Any = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _slow(conn: psycopg.Connection[Any]) -> None:
    """This request may take longer than the API's ten-second default; only this one."""
    conn.execute("SET LOCAL statement_timeout = '90s'")


RUNS_SQL = """
SELECT r.id, r.started_at, r.finished_at, r.status, r.requests, r.seed, r.report_dir,
       COALESCE((SELECT jsonb_object_agg(severity, n) FROM (
           SELECT severity, count(*) AS n FROM audit.truth_findings f WHERE f.run_id = r.id GROUP BY severity) x),
           '{}'::jsonb) AS by_severity
  FROM audit.truth_runs r
"""


def _run(r: dict[str, Any]) -> TruthRun:
    by = {str(k): int(v) for k, v in (r.get("by_severity") or {}).items()}
    return TruthRun(id=r["id"], started_at=r["started_at"], finished_at=r["finished_at"], status=r["status"],
                    requests=r["requests"], seed=r["seed"], findings=sum(by.values()), by_severity=by,
                    report_dir=r["report_dir"])


def runs(conn: psycopg.Connection[Any], *, limit: int) -> Envelope[list[TruthRun]]:
    rows = _rows(conn, RUNS_SQL + " ORDER BY r.id DESC LIMIT %s", (limit,))
    return listing([_run(r) for r in rows], empty_reason="No truth audit has been run yet "
                   "(python -m scripts.truth_audit).")


def summary(conn: psycopg.Connection[Any], run_id: int | None) -> Envelope[TruthSummary | None]:
    where = "WHERE r.id = %s" if run_id is not None else \
        "WHERE r.status IN ('completed', 'partial') ORDER BY r.id DESC LIMIT 1"
    rows = _rows(conn, RUNS_SQL + where, (run_id,) if run_id is not None else None)
    if not rows:
        return unavailable(None, "No truth audit has been run yet (python -m scripts.truth_audit)."
                           if run_id is None else f"Audit {run_id} does not exist.")
    raw = _rows(conn, "SELECT summary FROM audit.truth_runs WHERE id = %s", (rows[0]["id"],))[0]["summary"] or {}
    data = TruthSummary(
        run=_run(rows[0]),
        matrix=[TruthMatrixRow(**m) for m in raw.get("matrix", [])],
        freshness=[FreshnessDataset(**f) for f in raw.get("freshness", [])],
        gate=raw.get("gate") or {},
        datasets=raw.get("datasets") or {},
        failures=list(raw.get("failures") or []),
    )
    return ok(data, data_as_of=rows[0]["finished_at"] or rows[0]["started_at"])


def findings(conn: psycopg.Connection[Any], run_id: int, *, dataset: str | None, severity: str | None,
             kind: str | None, limit: int, offset: int) -> Envelope[list[TruthFinding]]:
    clauses = ["run_id = %(run)s"]
    params: dict[str, Any] = {"run": run_id, "limit": limit, "offset": offset}
    for name, value in (("dataset", dataset), ("severity", severity), ("kind", kind)):
        if value:
            clauses.append(f"{name} = %({name})s")
            params[name] = value
    where = " AND ".join(clauses)
    total = _rows(conn, f"SELECT count(*) AS n FROM audit.truth_findings WHERE {where}", params)[0]["n"]
    rows = _rows(conn, f"""
        SELECT id, dataset, entity, field, kind, severity, api_value, db_value, note FROM audit.truth_findings
         WHERE {where}
         ORDER BY array_position(ARRAY['critical','high','medium','low','info'], severity), dataset, id
         LIMIT %(limit)s OFFSET %(offset)s""", params)
    return listing([TruthFinding(**r) for r in rows], empty_reason="No findings match this selection.",
                   total=int(total), limit=limit, offset=offset)


def freshness(conn: psycopg.Connection[Any]) -> Envelope[FreshnessReport]:
    def compute() -> FreshnessReport:
        _slow(conn)
        at = now()
        return FreshnessReport(measured_at=at, datasets=[FreshnessDataset(**d.as_dict()) for d in measure(conn, at=at)])

    report = _cached("freshness", compute)
    return ok(report, data_as_of=report.measured_at)


def gate(conn: psycopg.Connection[Any], *, horizon_hours: int) -> Envelope[GateReport]:
    def compute() -> GateReport:
        _slow(conn)
        at = now()
        s, fixtures = evaluate(conn, at=at, horizon_hours=horizon_hours)
        models = [GateModel(model=m, passing=v["pass"], blocked=v["blocked"], blocked_by=v["blocked_by"],
                            needs={d: n.value for d, n in MODEL_NEEDS[m].items()}) for m, v in s.by_model.items()]
        sample = [GateFixture(provider_fixture_id=g.provider_fixture_id, competition=g.competition,
                              kickoff_at=g.kickoff_at,
                              datasets={d: {"state": str(st), "why": why} for d, (st, why) in g.datasets.items()},
                              models={m: g.passes(m)[0] for m in MODEL_NEEDS})
                  for g in fixtures[:300]]
        return GateReport(measured_at=at, horizon_hours=horizon_hours, fixtures=s.fixtures, models=models,
                          sample=sample)

    report = _cached(f"gate:{horizon_hours}", compute)
    if report.fixtures == 0:
        return unavailable(report, f"No tracked fixture kicks off in the next {horizon_hours} hours.",
                           status=DataStatus.EMPTY)
    return ok(report, data_as_of=report.measured_at)


STANDINGS_SQL = """
WITH snap AS (
    SELECT DISTINCT ON (s.competition_season_id) s.competition_season_id AS cs, s.snapshot_at
      FROM core.standings s ORDER BY s.competition_season_id, s.snapshot_at DESC
), latest AS (
    SELECT s.competition_season_id AS cs, count(*) AS rows, count(DISTINCT s.group_key) AS groups,
           max(s.provider_updated_at) AS provider_updated_at,
           bool_or(s.description IS NOT NULL OR s.home_played IS NOT NULL) AS extended
      FROM core.standings s JOIN snap ON snap.cs = s.competition_season_id AND snap.snapshot_at = s.snapshot_at
     GROUP BY 1
), fin AS (
    SELECT f.competition_season_id AS cs, max(f.kickoff_at) AS last_finished
      FROM core.fixtures f WHERE f.status_group = 'finished' GROUP BY 1
)
SELECT c.id AS competition_id, c.name AS competition, c.country, c.provider_league_id, cs.season,
       snap.snapshot_at, k.checked_at, k.changed_at, latest.provider_updated_at, fin.last_finished,
       COALESCE(latest.rows, 0) AS rows, COALESCE(k.rows_skipped, 0) AS rows_skipped,
       COALESCE(latest.groups, 0) AS groups, COALESCE(latest.extended, false) AS extended, lc.standings AS covered
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN snap ON snap.cs = cs.id
  LEFT JOIN latest ON latest.cs = cs.id
  LEFT JOIN fin ON fin.cs = cs.id
  LEFT JOIN core.context_checks k ON k.competition_season_id = cs.id AND k.dataset = 'standings'
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND cs.is_current AND c.type = 'league'
 ORDER BY c.name, c.country
"""


def standings(conn: psycopg.Connection[Any]) -> Envelope[list[StandingsAuditRow]]:
    out = []
    for r in _rows(conn, STANDINGS_SQL):
        state, why = table_state(r["snapshot_at"], r["last_finished"], r["checked_at"], r["covered"])
        _, code = table_reason(r["snapshot_at"], r["last_finished"], r["checked_at"], r["covered"])
        out.append(StandingsAuditRow(
            competition_id=r["competition_id"], competition=r["competition"], country=r["country"],
            provider_league_id=r["provider_league_id"], season=r["season"], status=state.value, reason_code=code,
            reason=why,
            snapshot_at=r["snapshot_at"], checked_at=r["checked_at"], changed_at=r["changed_at"],
            provider_updated_at=r["provider_updated_at"], last_finished_at=r["last_finished"], rows=r["rows"],
            rows_skipped=r["rows_skipped"], groups=r["groups"], extended=r["extended"]))
    order = {"STALE": 0, "UNKNOWN": 1, "UNAVAILABLE": 2, "FRESH": 3}
    out.sort(key=lambda x: (order[x.status], x.competition))
    return listing(out, empty_reason="No current league season is tracked.")


def repairs(conn: psycopg.Connection[Any], *, limit: int) -> Envelope[list[DataRepair]]:
    rows = _rows(conn, "SELECT id, repaired_at, rule, entity, entity_id, provider_ref, field, before_value, "
                       "after_value, reason FROM audit.data_repairs ORDER BY id DESC LIMIT %s", (limit,))
    return listing([DataRepair(**r) for r in rows], empty_reason="No stored value has been repaired.")


def odds_coverage(conn: psycopg.Connection[Any], *, days: int) -> Envelope[OddsCoverageReport]:
    """BOOKMAKER_COVERAGE_REPORT measured now (kept for two minutes)."""
    def compute() -> OddsCoverageReport:
        _slow(conn)
        r = build_report(conn, at=now(), days=days)
        return OddsCoverageReport(
            measured_at=r.measured_at, since=r.since, until=r.until, days=r.days, first_capture=r.first_capture,
            fixtures=r.fixtures, asked=r.asked, priced=r.priced, captured=r.captured, recovered=r.recovered,
            misses=r.misses, worker_down_hours=round(r.worker_down_hours, 1), critical=is_critical(r),
            competitions=[CoverageCompetition(
                competition_id=c.competition_id, competition=c.competition, country=c.country, season=c.season,
                provider_league_id=c.provider_league_id, flag_odds=c.flag_odds, fixtures=c.fixtures, asked=c.asked,
                priced=c.priced, captured=c.captured, recovered=c.recovered, priced_two_plus=c.priced_two_plus,
                median_bookmakers=c.median_bookmakers, provider_share=round(c.provider_share, 4),
                capture_share=round(c.capture_share, 4), bookmakers=c.bookmakers, markets=c.markets,
                misses=c.misses, upcoming=c.upcoming, state=c.state.value, reason=c.reason)
                for c in r.competitions],
            bookmakers=[CoverageBookmaker(
                provider_bookmaker_id=b.provider_bookmaker_id, name=b.name, state=b.state.value, fixtures=b.fixtures,
                share=b.share, competitions=b.competitions, countries=b.countries, markets=b.markets,
                first_seen=b.first_seen, last_seen=b.last_seen, name_missing=b.name_missing) for b in r.bookmakers],
            markets=[CoverageMarket(market_key=m.market_key, fixtures=m.fixtures, share=m.share,
                                    bookmakers=m.bookmakers, median_bookmakers=m.median_bookmakers)
                     for m in r.markets],
            countries=[CoverageCountry(country=c.country, competitions=c.competitions, fixtures=c.fixtures,
                                       priced=c.priced, captured=c.captured, bookmakers=c.bookmakers)
                       for c in r.countries],
            local=[CoverageLocal(brand=x.brand, domain=x.domain, company=x.company, state=x.state.value,
                                 provider_names=x.provider_names, priced_fixtures=x.priced_fixtures,
                                 colombian_edition_confirmed=x.colombian_edition_confirmed, note=x.note)
                   for x in r.local],
            local_source=r.local_source,
            sources=[OddsSource(key=s.key, name=s.name, kind=s.kind.value, access=s.access.value,
                                bookmakers=s.bookmakers, colombian_books=list(s.colombian_books),
                                closing_line=s.closing_line, cost=s.cost, decision=s.decision,
                                sources=list(s.sources)) for s in ODDS_SOURCES])

    report = _cached(f"odds_coverage:{days}", compute)
    if report.fixtures == 0:
        return unavailable(report, "No played match of a tracked competition in the window yet.",
                           status=DataStatus.EMPTY)
    return ok(report, data_as_of=report.measured_at)


VALIDATION_SUMMARY_SQL = """
SELECT max(v.rule_version) AS rule_version, max(v.validated_at) AS computed_at,
       count(*) AS fixtures FROM analytics.fixture_validation v
"""

SCORES_SQL = """
SELECT s.competition_season_id, cs.competition_id, c.name AS competition, c.country, cs.season, cs.is_current,
       c.is_tracked, c.competition_type, c.entity_scope, c.tier, s.class AS data_class, s.score, s.finished,
       s.approved, s.quarantined, s.components, s.reasons, s.computed_at
  FROM analytics.competition_data_scores s
  JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (%(klass)s::text IS NULL OR s.class = %(klass)s)
   AND (%(country)s::text IS NULL OR c.country = %(country)s)
   AND (%(q)s::text IS NULL OR c.name ILIKE '%%' || %(q)s || '%%')
   AND (NOT %(current)s OR cs.is_current)
   AND (NOT %(tracked)s OR c.is_tracked)
 ORDER BY c.is_tracked DESC, cs.is_current DESC, s.score DESC, c.name, cs.season DESC
 LIMIT %(limit)s OFFSET %(offset)s
"""


def _segment(r: dict[str, Any]) -> str:
    return segment_of(CompetitionFacts(str(r["competition"]), r["competition_type"], r["entity_scope"],
                                       r["tier"])).value


def validation_summary(conn: psycopg.Connection[Any]) -> Envelope[ValidationSummary]:
    def compute() -> ValidationSummary:
        _slow(conn)
        head = _rows(conn, VALIDATION_SUMMARY_SQL)[0]
        states = {str(r["state"]): int(r["n"]) for r in _rows(
            conn, "SELECT state, count(*) AS n FROM analytics.fixture_validation GROUP BY 1")}
        failed = {str(r["rule"]): int(r["n"]) for r in _rows(
            conn, "SELECT f.rule, count(*) AS n FROM analytics.fixture_validation v, "
                  "jsonb_array_elements_text(v.failed) AS f(rule) GROUP BY 1")}
        classes = {str(r["class"]): int(r["n"]) for r in _rows(
            conn, "SELECT class, count(*) AS n FROM analytics.competition_data_scores GROUP BY 1")}
        by_segment: dict[str, int] = {}
        for r in _rows(conn, "SELECT c.name AS competition, c.competition_type, c.entity_scope, c.tier, "
                             "count(*) AS n FROM analytics.model_ready_fixtures m "
                             "JOIN core.competitions c ON c.id = m.competition_id GROUP BY 1, 2, 3, 4"):
            seg = _segment(r)
            by_segment[seg] = by_segment.get(seg, 0) + int(r["n"])
        return ValidationSummary(rule_version=head["rule_version"], computed_at=head["computed_at"],
                                 fixtures=int(head["fixtures"]), states=states, failed=failed, classes=classes,
                                 approved_by_segment=by_segment)

    report = _cached("validation", compute)
    if report.fixtures == 0:
        return unavailable(report, "Historical validation has not run yet (python -m scripts.validate_history).",
                           status=DataStatus.EMPTY)
    return ok(report, data_as_of=report.computed_at)


def competition_scores(conn: psycopg.Connection[Any], *, klass: str | None, country: str | None, q: str | None,
                       current: bool, tracked: bool, limit: int, offset: int) -> Envelope[list[CompetitionScoreRow]]:
    _slow(conn)
    params: dict[str, Any] = {"klass": klass, "country": country, "q": q, "current": current, "tracked": tracked,
                              "limit": limit, "offset": offset}
    rows = _rows(conn, SCORES_SQL, params)
    total = _rows(conn, "SELECT count(*) AS n FROM (" + SCORES_SQL.replace(
        "LIMIT %(limit)s OFFSET %(offset)s", "") + ") x", params)[0]["n"]
    out = [CompetitionScoreRow(
        competition_season_id=r["competition_season_id"], competition_id=r["competition_id"],
        competition=r["competition"], country=r["country"], season=r["season"], is_current=r["is_current"],
        is_tracked=r["is_tracked"], segment=_segment(r), data_class=r["data_class"], score=float(r["score"]),
        finished=r["finished"], approved=r["approved"], quarantined=r["quarantined"], components=r["components"],
        reasons=list(r["reasons"] or []), computed_at=r["computed_at"]) for r in rows]
    return listing(out, empty_reason="No competition-season matches this selection.", total=int(total), limit=limit,
                   offset=offset)


QUARANTINE_SQL = """
SELECT v.fixture_id, f.provider_fixture_id, c.name AS competition, cs.season, f.kickoff_at, h.name AS home,
       a.name AS away, f.status_short, v.failed
  FROM analytics.fixture_validation v
  JOIN core.fixtures f ON f.id = v.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams h ON h.id = f.home_team_id JOIN core.teams a ON a.id = f.away_team_id
 WHERE v.state = 'QUARANTINED'
 ORDER BY f.kickoff_at DESC
 LIMIT %(limit)s
"""


def quarantined(conn: psycopg.Connection[Any], *, limit: int) -> Envelope[list[QuarantinedFixture]]:
    _slow(conn)
    rows = _rows(conn, QUARANTINE_SQL, {"limit": limit})
    return listing([QuarantinedFixture(**{**r, "failed": list(r["failed"] or [])}) for r in rows],
                   empty_reason="No quarantined match.", total=len(rows), limit=limit, offset=0)
