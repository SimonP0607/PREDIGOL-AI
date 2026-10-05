"""The dataset register: the fourteen datasets, each with its endpoint, service level, last capture, last write,
rows, coverage, errors, blockers and whether a model may use it.

Freshness (``fbi.truth.freshness``) says FRESH / STALE / UNKNOWN / UNAVAILABLE per entity. The register turns
that into one class per dataset, with the evidence beside it:

* FRESH       - every entity we are responsible for is current (the provider's own gaps do not count against us);
* STALE       - the provider has newer data than we hold, and asking was our job;
* INCOMPLETE  - nothing stale, but 5% or more of what we are responsible for was never read;
* INVALID     - an open critical or high finding at PrediGol's fault names this dataset (the evidence ledger);
* UNKNOWN     - nothing to measure right now (no match in play, nothing in scope).

Model eligibility is separate: MODEL_READY only when a model reads the dataset, the dataset is FRESH and the
dataset version the models train on (``fbi.datasets``) is MODEL_READY; NOT_USED for a product-only dataset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.freshness import DatasetFreshness, Freshness
from fbi.truth.gate import Need, dataset_role


@dataclass(frozen=True, slots=True)
class Spec:
    endpoints: tuple[str, ...]
    jobs: tuple[str, ...]
    table: str
    ledger_areas: tuple[str, ...] = ()


SPECS: dict[str, Spec] = {
    "fixtures": Spec(("/fixtures?league&season",), ("fixtures_sync",), "core.fixtures", ("fixtures", "phases")),
    "results": Spec(("/fixtures?ids", "/fixtures?league&season"), ("results_sync", "results_repair",
                                                                   "live_match_capture"),
                    "core.fixture_results", ("fixtures", "golden")),
    "live": Spec(("/fixtures?ids (in play)", "/odds/live"), ("live_match_capture", "live_odds_capture"),
                 "market.live_fixture_states"),
    "standings": Spec(("/standings",), ("context_due", "context_refresh"), "core.standings", ("standings",)),
    "injuries": Spec(("/injuries",), ("context_due", "context_refresh"), "core.player_absences", ("injuries",)),
    "lineups": Spec(("/fixtures?ids (lineups)",), ("post_match_detail", "historical_backfill", "live_match_capture"),
                    "core.fixture_lineups"),
    "match_detail": Spec(("/fixtures?ids (events, statistics, players)",),
                         ("post_match_detail", "historical_backfill", "live_match_capture"), "core.fixture_events",
                         ("player_stats", "team_stats")),
    "odds_prematch": Spec(("/odds",), ("odds_capture", "final_prematch"), "market.odds_snapshots", ("odds",)),
    "elo": Spec(("(PrediGol: from results)",), ("elo_refresh",), "features.elo_ratings"),
    "teams": Spec(("/teams",), ("catalogue_refresh", "historical_backfill"), "core.teams", ("teams", "identity")),
    "players": Spec(("/players/profiles", "/players"), ("historical_backfill",), "core.players", ("players",)),
    "squads": Spec(("/players/squads",), ("historical_backfill",), "core.squad_members", ("squads",)),
    "coaches": Spec(("/coachs",), ("reference_refresh",), "core.coach_profiles", ("coaches",)),
    "coverage": Spec(("/leagues",), ("catalogue_refresh",), "raw.league_coverage", ("leagues",)),
}

ENDPOINT_PREFIX = {"/fixtures?league&season": "/fixtures", "/fixtures?ids": "/fixtures",
                   "/fixtures?ids (in play)": "/fixtures", "/fixtures?ids (lineups)": "/fixtures",
                   "/fixtures?ids (events, statistics, players)": "/fixtures"}

INCOMPLETE_SHARE = 0.05

ISSUE_DATASET = {"fixture": "fixtures", "fixture_result": "results", "lineup": "lineups",
                 "team_statistics": "match_detail", "player_statistics": "match_detail",
                 "match_event": "match_detail", "odds_snapshot": "odds_prematch", "provider_market": "odds_prematch",
                 "bookmaker": "odds_prematch", "team": "teams", "player": "players", "coach": "coaches",
                 "competition": "coverage", "league_season": "coverage"}
"""audit.data_quality_issues entity types -> the dataset they belong to."""

NORMALIZATION_CODES = ("NORMALIZATION_REJECTED", "UNKNOWN_PROVIDER_ENTITY", "RESULT_UNRESOLVED")
"""Issue codes that mean "we hold the provider's answer but could not turn (part of) it into rows"."""

STATES = ("VALID", "STALE", "NOT_REQUESTED", "PROVIDER_HAS_NO_DATA", "REQUEST_FAILED", "NORMALIZATION_FAILED")
"""The six answers the Data Quality page gives per dataset (5 Oct 2026 mandate): valid; we have it but it is stale;
we did not request it; the provider does not have it; we requested it and it failed; we have it but normalization
failed. The first four count entities (``fbi.truth.freshness``); REQUEST_FAILED counts failed or partial runs and
their errors in 24 h; NORMALIZATION_FAILED counts open issues of the codes above."""


@dataclass
class RegisterRow:
    dataset: str
    klass: str
    model: str
    model_reason: str
    role: str
    endpoints: list[str]
    sla: str
    freshness: str
    coverage: float | None
    """Fresh share of what we are responsible for (the provider's own gaps excluded)."""
    provider_gap: float | None
    """Share the provider does not have (its coverage flag or its lag)."""
    last_capture: datetime | None
    last_write: datetime | None
    rows: int
    errors_24h: int
    failed_runs_24h: int
    open_findings: int
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    states: dict[str, int] = field(default_factory=dict)
    """One count per ``STATES`` answer."""


def classify(f: DatasetFreshness, open_findings: int) -> tuple[str, float | None, float | None, list[str]]:
    c = f.counts
    fresh, stale, unknown, unavailable = (c[Freshness.FRESH.value], c[Freshness.STALE.value],
                                          c[Freshness.UNKNOWN.value], c[Freshness.UNAVAILABLE.value])
    ours = fresh + stale + unknown
    blockers: list[str] = []
    coverage = round(fresh / ours, 4) if ours else None
    gap = round(unavailable / f.total, 4) if f.total else None
    if stale:
        blockers.append(f"{stale:,} {f.entity}(s) stale: the provider has newer data")
    if unknown and ours and unknown / ours >= INCOMPLETE_SHARE:
        blockers.append(f"{unknown:,} {f.entity}(s) never read")
    if open_findings:
        blockers.append(f"{open_findings} open critical/high finding(s) at PrediGol's fault (evidence ledger)")
    if f.total == 0 or (ours == 0 and not unavailable):
        return "UNKNOWN", coverage, gap, blockers or ["nothing to measure right now"]
    if open_findings:
        return "INVALID", coverage, gap, blockers
    if stale:
        return "STALE", coverage, gap, blockers
    if ours and unknown / ours >= INCOMPLETE_SHARE:
        return "INCOMPLETE", coverage, gap, blockers
    return "FRESH", coverage, gap, blockers


RUNS_SQL = """
SELECT job_type,
       max(finished_at) FILTER (WHERE status IN ('completed', 'partial', 'aborted') AND rows_written + rows_updated > 0)
           AS last_write,
       count(*) FILTER (WHERE status IN ('failed', 'partial', 'stale') AND started_at > %(since)s) AS bad,
       coalesce(sum(errors) FILTER (WHERE started_at > %(since)s), 0) AS errors
  FROM raw.ingestion_runs WHERE job_type = ANY(%(jobs)s) GROUP BY job_type
"""

CAPTURE_SQL = "SELECT endpoint, max(fetched_at) AS last FROM raw.ingestion_payloads GROUP BY endpoint"

ROWS_SQL = """
SELECT n.nspname || '.' || c.relname AS rel, greatest(c.reltuples, 0)::bigint AS n
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname || '.' || c.relname = ANY(%(rels)s)
"""

FINDINGS_SQL = """
SELECT area, count(*) AS n FROM audit.evidence_ledger
 WHERE status = 'OPEN' AND at_fault = 'predigol' AND severity IN ('critical', 'high') GROUP BY area
"""

DATASET_VERSION_SQL = "SELECT name, status FROM audit.dataset_versions ORDER BY (status = 'MODEL_READY') DESC LIMIT 1"

NORMALIZATION_SQL = """
SELECT entity_type, count(*) AS n FROM audit.data_quality_issues
 WHERE status = 'open' AND code = ANY(%(codes)s) GROUP BY 1
"""


def build(conn: psycopg.Connection[Any], freshness: list[DatasetFreshness], *, at: datetime) -> list[RegisterRow]:
    jobs = sorted({j for s in SPECS.values() for j in s.jobs})
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RUNS_SQL, {"jobs": jobs, "since": at - timedelta(hours=24)})
        runs = {r["job_type"]: r for r in cur.fetchall()}
        cur.execute(CAPTURE_SQL)
        captures = {r["endpoint"]: r["last"] for r in cur.fetchall()}
        cur.execute(ROWS_SQL, {"rels": [s.table for s in SPECS.values()]})
        rows = {r["rel"]: int(r["n"]) for r in cur.fetchall()}
        cur.execute(FINDINGS_SQL)
        findings = {r["area"]: int(r["n"]) for r in cur.fetchall()}
        cur.execute(DATASET_VERSION_SQL)
        version = cur.fetchone()
        cur.execute(NORMALIZATION_SQL, {"codes": list(NORMALIZATION_CODES)})
        normalization: dict[str, int] = {}
        for r in cur.fetchall():
            ds = ISSUE_DATASET.get(str(r["entity_type"]))
            if ds is not None:
                normalization[ds] = normalization.get(ds, 0) + int(r["n"])
    version_ready = bool(version and version["status"] == "MODEL_READY")
    out: list[RegisterRow] = []
    by_name = {f.dataset: f for f in freshness}
    for name, spec in SPECS.items():
        f = by_name.get(name) or DatasetFreshness(name, "", "entity")
        open_findings = sum(findings.get(a, 0) for a in spec.ledger_areas)
        klass, coverage, gap, blockers = classify(f, open_findings)
        role = dataset_role(name)
        if role in (Need.NOT_USED, Need.UNAVAILABLE_BY_PROVIDER):
            model, reason = "NOT_USED", "no model reads it (product and reference only)"
        elif not version_ready:
            model, reason = "NOT_MODEL_READY", (f"the dataset version models train on ({version['name'] if version else '-'}"
                                                f") is {version['status'] if version else 'missing'}, not MODEL_READY")
        elif klass != "FRESH":
            model, reason = "NOT_MODEL_READY", f"the dataset is {klass}"
        else:
            model, reason = "MODEL_READY", f"{role.value.lower()} input, fresh, in a MODEL_READY dataset version"
        last_capture = max((captures[ENDPOINT_PREFIX.get(e, e.split('?')[0])] for e in spec.endpoints
                            if captures.get(ENDPOINT_PREFIX.get(e, e.split('?')[0])) is not None), default=None)
        job_rows = [runs[j] for j in spec.jobs if j in runs]
        notes = [f"the provider has no data for {gap:.0%} of the {f.entity}s (its coverage flag or its lag)"] \
            if gap else []
        c = f.counts
        failed_runs = sum(int(r["bad"]) for r in job_rows)
        states = {"VALID": c[Freshness.FRESH.value], "STALE": c[Freshness.STALE.value],
                  "NOT_REQUESTED": c[Freshness.UNKNOWN.value], "PROVIDER_HAS_NO_DATA": c[Freshness.UNAVAILABLE.value],
                  "REQUEST_FAILED": failed_runs, "NORMALIZATION_FAILED": normalization.get(name, 0)}
        out.append(RegisterRow(
            dataset=name, klass=klass, model=model, model_reason=reason, role=role.value,
            endpoints=list(spec.endpoints), sla=f.sla, freshness=f.label(), coverage=coverage, provider_gap=gap,
            last_capture=last_capture,
            last_write=max((r["last_write"] for r in job_rows if r["last_write"] is not None), default=None),
            rows=rows.get(spec.table, 0), errors_24h=sum(int(r["errors"]) for r in job_rows),
            failed_runs_24h=failed_runs, open_findings=open_findings, blockers=blockers,
            notes=notes, states=states))
    return out
