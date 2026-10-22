"""Restore the signed team statistics the detail normaliser dropped (goals prevented), from RAW.

    python -m scripts.repair_signed_team_stats            # dry run: what would change, nothing written
    python -m scripts.repair_signed_team_stats --apply    # write it, one audit.data_repairs row per value

Until 5 Oct 2026 ``fbi.ingestion.details._clean`` dropped every negative team statistic as "not a statistic",
goals prevented included - a difference (expected goals on target faced minus goals conceded) that is negative
whenever a keeper lets in more than expected. The column never had a sign check; the normaliser was wrong. Each drop
left its trace: the row names the dropped column (``dropped_fields``) and the payload it was written from, and the
value is in that RAW payload. This puts it back:

* only into a row still written from the payload it is read from, whose value is NULL and which names the column
  as dropped - a newer payload owns the row otherwise, and that payload's value (or its own drop) stands;
* the RAW file is verified against its indexed hash before it is read; a file that fails is reported and skipped;
* every value written is one ``audit.data_repairs`` row: before NULL, after the value, the payload, the code version;
* the issues that recorded the drops are resolved with the reason; an issue whose row a newer payload now owns is
  marked superseded. Nothing is deleted, RAW is only read, and no provider request is made.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.ingestion.details import SIGNED_COLUMNS
from fbi.providers.api_football.details import iter_fixture_details
from fbi.storage.payload_store import PayloadStore, body_hash

RULE = "team_stats_signed_metric"

ROWS_SQL = """
SELECT s.fixture_id, s.team_side, s.payload_hash, p.file_path, f.provider_fixture_id,
       CASE s.team_side WHEN 'home' THEN th.provider_team_id ELSE ta.provider_team_id END AS team, c.column_name
  FROM core.fixture_team_stats s
  JOIN core.fixtures f ON f.id = s.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN raw.ingestion_payloads p ON p.hash = s.payload_hash
  CROSS JOIN unnest(%(columns)s::text[]) AS c(column_name)
 WHERE s.source = 'api-football' AND c.column_name = ANY(s.dropped_fields)
 ORDER BY s.payload_hash, s.fixture_id, s.team_side
"""


@dataclass
class Report:
    rows: int = 0
    payloads: int = 0
    restored: int = 0
    already_set: int = 0
    not_in_payload: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    positive: list[str] = field(default_factory=list)
    issues_resolved: int = 0
    issues_superseded: int = 0


def _values(store: PayloadStore, file_path: str, payload_hash: str) -> dict[tuple[int, int], dict[str, Any]] | None:
    try:
        envelope = store.load(file_path)
    except (OSError, ValueError):
        return None
    body = envelope.get("body")
    if not isinstance(body, dict) or body_hash(body) != payload_hash:
        return None
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for detail in iter_fixture_details(body):
        for s in detail.stats:
            out[(s.provider_fixture_id, s.provider_team_id)] = dict(s.values)
    return out


def _cell(column: str) -> str:
    assert column in SIGNED_COLUMNS, column  # never interpolate anything else
    return column


def repair(conn: psycopg.Connection[Any], store: PayloadStore) -> Report:
    """Does the work inside the caller's transaction; the caller commits or rolls back."""
    report = Report()
    version = code_version()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROWS_SQL, {"columns": sorted(SIGNED_COLUMNS)})
        rows = cur.fetchall()
    report.rows = len(rows)
    by_payload: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_payload[str(r["payload_hash"])].append(r)
    with conn.cursor() as cur:
        for payload_hash, group in by_payload.items():
            report.payloads += 1
            values = _values(store, str(group[0]["file_path"]), payload_hash)
            if values is None:
                report.unreadable.append(payload_hash[:12])
                continue
            for r in group:
                column = _cell(str(r["column_name"]))
                where = f"fixture {r['provider_fixture_id']} team {r['team']} {column}"
                value = values.get((int(r["provider_fixture_id"]), int(r["team"])), {}).get(column)
                if value is None:
                    report.not_in_payload.append(where)
                    continue
                if not isinstance(value, Decimal | int) or value >= 0:
                    report.positive.append(f"{where} = {value}")  # dropped for another reason: not this repair's
                    continue
                cur.execute(
                    f"UPDATE core.fixture_team_stats SET {column} = %s, "
                    "dropped_fields = array_remove(dropped_fields, %s) "
                    f"WHERE fixture_id = %s AND team_side = %s AND source = 'api-football' AND payload_hash = %s "
                    f"AND {column} IS NULL RETURNING fixture_id",
                    (value, column, r["fixture_id"], r["team_side"], payload_hash))
                if cur.fetchone() is None:
                    report.already_set += 1
                    continue
                report.restored += 1
                cur.execute(
                    "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, "
                    "after_value, reason, evidence) VALUES (%s, 'core.fixture_team_stats', %s, %s, %s, NULL, %s, "
                    "%s, %s)",
                    (RULE, r["fixture_id"], r["team"], column, str(value),
                     f"{column} is a signed metric; the normaliser dropped the negative value as not a statistic "
                     "(fixed 5 Oct 2026); restored from the RAW payload the row was written from",
                     f"payload {payload_hash} side {r['team_side']} code {version}"))
                cur.execute(
                    "UPDATE audit.data_quality_issues SET status = 'resolved', resolved_at = now(), resolution = %s "
                    "WHERE status = 'open' AND code = 'PROVIDER_INCONSISTENCY' AND entity_type = 'team_statistics' "
                    "AND field = %s AND entity_id = %s AND provider_entity_id = %s",
                    (f"not an inconsistency: {column} is signed. Normaliser fixed 5 Oct 2026; the value was restored "
                     f"from RAW payload {payload_hash[:12]} (audit.data_repairs rule {RULE})",
                     column, r["fixture_id"], r["team"]))
                report.issues_resolved += max(cur.rowcount, 0)
        # Drops whose row a newer payload owns now: that payload's value (or its own recorded drop) stands.
        cur.execute(
            "UPDATE audit.data_quality_issues q SET status = 'superseded', resolved_at = now(), resolution = %s "
            "WHERE q.status = 'open' AND q.code = 'PROVIDER_INCONSISTENCY' AND q.entity_type = 'team_statistics' "
            "AND q.field = ANY(%s) AND NOT EXISTS (SELECT 1 FROM core.fixture_team_stats s "
            "  WHERE s.fixture_id = q.entity_id AND s.source = 'api-football' AND q.field = ANY(s.dropped_fields))",
            ("not an inconsistency: the metric is signed (normaliser fixed 5 Oct 2026), and the row is now written "
             "from a payload that did not drop it", sorted(SIGNED_COLUMNS)))
        report.issues_superseded = max(cur.rowcount, 0)
    return report


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="repair_signed_team_stats", description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit (default: dry run)")
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        r = repair(conn, PayloadStore(settings.runtime.raw_store_dir))
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    print(f"rows naming a dropped signed metric={r.rows} payloads={r.payloads} restored={r.restored} "
          f"already_set={r.already_set} issues_resolved={r.issues_resolved} issues_superseded={r.issues_superseded}")
    print(f"unreadable payloads={len(r.unreadable)} not_in_payload={len(r.not_in_payload)} "
          f"non_negative={len(r.positive)}")
    for x in (r.unreadable + r.not_in_payload + r.positive)[:20]:
        print("  ", x)
    print("COMMITTED" if args.apply else "dry run - nothing written (use --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
