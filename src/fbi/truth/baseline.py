"""The data-truth baseline: what every table holds before an audit touches anything.

For each table: exact rows, the span of football it covers (the earliest and latest match
or capture it describes), the latest moment the PROVIDER stated or served it, and the latest
moment PrediGol wrote it. Plus, per provider endpoint, when we last asked and how often.
Read only (``python -m scripts.audit_data_truth baseline``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class TableSpec:
    table: str
    label: str
    span: str | None
    """SQL expression (over alias x, with f = core.fixtures joined when ``via_fixture``) for the
    football date the row describes."""
    provider: str | None
    """Expression for the latest time the provider stated or served the row."""
    written: str | None
    """Expression for the latest time PrediGol wrote the row."""
    via_fixture: bool = False
    endpoints: tuple[str, ...] = ()


TABLES: tuple[TableSpec, ...] = (
    TableSpec("core.competitions", "competitions", None, None, "x.updated_at", endpoints=("/leagues",)),
    TableSpec("core.competition_seasons", "seasons", "x.start_date", "x.listed_at", None, endpoints=("/leagues",)),
    TableSpec("core.fixtures", "fixtures", "x.kickoff_at", "x.source_fetched_at", "x.updated_at",
              endpoints=("/fixtures",)),
    TableSpec("core.fixture_results", "results", "f.kickoff_at", "x.source_fetched_at", "x.settled_at",
              via_fixture=True, endpoints=("/fixtures",)),
    TableSpec("core.teams", "teams", None, "x.source_fetched_at", "x.updated_at", endpoints=("/teams",)),
    TableSpec("core.venues", "venues", None, "x.source_fetched_at", None, endpoints=("/venues", "/teams")),
    TableSpec("core.players", "players", None, "x.profile_fetched_at", "x.updated_at",
              endpoints=("/players/profiles", "/players")),
    TableSpec("core.squad_members", "squads", "x.first_seen_at", "x.last_seen_at", "x.last_seen_at",
              endpoints=("/players/squads",)),
    TableSpec("core.coaches", "coaches", None, "x.source_fetched_at", "x.updated_at", endpoints=("/coachs",)),
    TableSpec("core.standings", "standings", "x.snapshot_at", "x.provider_updated_at", "x.snapshot_at",
              endpoints=("/standings",)),
    TableSpec("core.team_season_stats", "team season stats (legacy)", "x.snapshot_at", None, "x.snapshot_at",
              endpoints=("/teams/statistics",)),
    TableSpec("core.fixture_team_stats", "team match stats", "f.kickoff_at", "x.fetched_at", "x.fetched_at",
              via_fixture=True, endpoints=("/fixtures/statistics",)),
    TableSpec("core.fixture_player_stats", "player match stats", "f.kickoff_at", "x.fetched_at", "x.fetched_at",
              via_fixture=True, endpoints=("/fixtures/players",)),
    TableSpec("core.fixture_events", "events", "f.kickoff_at", "x.fetched_at", "x.fetched_at", via_fixture=True,
              endpoints=("/fixtures/events",)),
    TableSpec("core.fixture_lineups", "line-ups", "f.kickoff_at", "x.fetched_at", "x.fetched_at", via_fixture=True,
              endpoints=("/fixtures/lineups",)),
    TableSpec("core.fixture_lineup_players", "line-up players", "f.kickoff_at", None, None, via_fixture=True),
    TableSpec("core.player_absences", "injuries / suspensions", "f.kickoff_at", "x.fetched_at", "x.fetched_at",
              via_fixture=True, endpoints=("/injuries",)),
    TableSpec("market.odds_snapshots", "pre-match odds", "x.captured_at", "x.captured_at", "x.captured_at",
              endpoints=("/odds",)),
    TableSpec("market.final_prematch_odds", "final pre-match odds", "x.provider_update_at", "x.provider_update_at",
              "x.fetched_at", endpoints=("/odds",)),
    TableSpec("market.live_odds_snapshots", "in-play odds", "x.captured_at", "x.provider_updated_at",
              "x.captured_at", endpoints=("/odds/live",)),
    TableSpec("market.market_consensus", "de-vigged consensus", "x.as_of", None, "x.as_of"),
    TableSpec("market.historical_odds", "historical odds (football-data)", "f.kickoff_at", None, None,
              via_fixture=True),
    TableSpec("raw.ingestion_payloads", "raw payloads", None, "x.fetched_at", "x.fetched_at"),
)


def _one(conn: psycopg.Connection[Any], sql: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return dict(row) if row else {}


def table_baseline(conn: psycopg.Connection[Any], spec: TableSpec) -> dict[str, Any]:
    join = " JOIN core.fixtures f ON f.id = x.fixture_id" if spec.via_fixture else ""
    parts = ["count(*) AS rows"]
    if spec.span:
        parts += [f"min({spec.span}) AS span_from", f"max({spec.span}) AS span_to"]
    if spec.provider:
        parts.append(f"max({spec.provider}) AS provider_latest")
    if spec.written:
        parts.append(f"max({spec.written}) AS written_latest")
    row = _one(conn, f"SELECT {', '.join(parts)} FROM {spec.table} x{join}")
    return {"table": spec.table, "label": spec.label, "endpoints": list(spec.endpoints), **row}


ENDPOINTS_SQL = """
SELECT endpoint, count(*) AS payloads, min(fetched_at) AS first_fetch, max(fetched_at) AS last_fetch,
       count(*) FILTER (WHERE fetched_at > now() - interval '24 hours') AS last_24h
  FROM raw.ingestion_payloads GROUP BY endpoint ORDER BY endpoint
"""

EXTRA_SQL = {
    "fixtures_by_status": "SELECT status_group, count(*) AS n FROM core.fixtures GROUP BY 1 ORDER BY 1",
    "competitions": "SELECT count(*) FILTER (WHERE is_tracked) AS tracked, count(*) AS total, "
                    "count(*) FILTER (WHERE is_tracked AND type = 'league') AS tracked_leagues FROM core.competitions",
    "current_seasons": "SELECT count(*) AS n FROM core.competition_seasons WHERE is_current",
    "teams_national": "SELECT count(*) FILTER (WHERE is_national) AS national, count(*) AS total FROM core.teams",
    "repairs": "SELECT rule, count(*) AS n, max(repaired_at) AS last FROM audit.data_repairs GROUP BY 1 ORDER BY 2 DESC",
    "validation": "SELECT state, count(*) AS n FROM analytics.fixture_validation GROUP BY 1 ORDER BY 1",
}


def baseline(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    tables = [table_baseline(conn, s) for s in TABLES]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ENDPOINTS_SQL)
        endpoints = [dict(r) for r in cur.fetchall()]
        extra: dict[str, Any] = {}
        for key, sql in EXTRA_SQL.items():
            cur.execute(sql)
            extra[key] = [dict(r) for r in cur.fetchall()]
    return {"at": at.isoformat(), "tables": tables, "endpoints": endpoints, "extra": extra}


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def markdown(b: dict[str, Any]) -> str:
    lines = ["| Table | Rows | From | To | Latest provider stamp | Latest PrediGol write |",
             "|---|---:|---|---|---|---|"]
    for t in b["tables"]:
        lines.append(f"| `{t['table']}` ({t['label']}) | {_fmt(t.get('rows'))} | {_fmt(t.get('span_from'))} | "
                     f"{_fmt(t.get('span_to'))} | {_fmt(t.get('provider_latest'))} | {_fmt(t.get('written_latest'))} |")
    lines += ["", "| Endpoint | Payloads | First | Last | Last 24 h |", "|---|---:|---|---|---:|"]
    for e in b["endpoints"]:
        lines.append(f"| `{e['endpoint']}` | {_fmt(e['payloads'])} | {_fmt(e['first_fetch'])} | "
                     f"{_fmt(e['last_fetch'])} | {_fmt(e['last_24h'])} |")
    return "\n".join(lines) + "\n"
