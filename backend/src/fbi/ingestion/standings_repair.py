"""League-table snapshots whose tables collided on a repeated group label - found and rebuilt.

The provider can give two tables of one season the same label (Colombia's Primera A 2023 and 2024:
the Apertura and the Clausura play-off groups are both "Group A" and "Group B"). Until 4 Oct 2026 the
writer keyed a row by (season, team, snapshot, label): the second table merged into the first and a
team present in both kept only its first row (``ON CONFLICT DO NOTHING``). The parser now gives the
n-th table with a label "<label> #n" (``labelled_rows``).

A damaged snapshot is never edited: its rows are a mix of two tables under one label, and the honest
correction is a NEW snapshot built from the very payload the damaged one was written from, with the
fixed parser. The old snapshot stays as it was; each rebuild is a row in ``audit.data_repairs`` (rule
``standings_group_label_collision``: rows before and after, the payload hash). The new snapshot's time is
when it was rebuilt; its ``payload_hash`` names the payload, whose ``fetched_at`` is when the provider
said it. No request is made.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.ingestion.details import apply_standings_outcome
from fbi.providers.api_football.details import iter_standings
from fbi.storage.payload_store import PayloadStore
from fbi.truth.v2.standings import repeated_labels

RULE = "standings_group_label_collision"
log = structlog.get_logger(__name__)

NEWEST_SNAPSHOTS_SQL = """
SELECT cs.id AS cs_id, c.provider_league_id AS league, cs.season, c.name, s.snapshot_at,
       count(*) AS rows, max(s.payload_hash) AS payload_hash,
       array_agg(t.provider_team_id::text || '|' || s.group_key) AS keys
  FROM core.standings s
  JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id = s.team_id
 WHERE s.snapshot_at = (SELECT max(snapshot_at) FROM core.standings x WHERE x.competition_season_id = cs.id)
 GROUP BY cs.id, c.provider_league_id, cs.season, c.name, s.snapshot_at
"""

PAYLOADS_SQL = """
SELECT hash, params->>'league' AS league, params->>'season' AS season, fetched_at, file_path
  FROM raw.ingestion_payloads WHERE endpoint = '/standings'
"""


@dataclass
class LabelCase:
    cs_id: int
    league: int
    season: int
    name: str
    snapshot_at: datetime
    payload_hash: str
    file_path: str
    labels: dict[str, int]
    rows_before: int
    rows_expected: int
    missing: list[str] = field(default_factory=list)
    """team|group keys the payload holds that the snapshot lacks (the merged tables' rows)."""


def _payload_for(snap: dict[str, Any], payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The payload a snapshot was written from: by the hash on its rows, else the season's newest
    payload seen at or before the snapshot (a snapshot is filed at the time its payload was first seen)."""
    mine = [p for p in payloads if (p["league"], p["season"]) == (str(snap["league"]), str(snap["season"]))]
    if snap["payload_hash"]:
        for p in mine:
            if p["hash"] == snap["payload_hash"]:
                return p
    earlier = [p for p in mine if p["fetched_at"] <= snap["snapshot_at"]]
    return max(earlier, key=lambda p: p["fetched_at"]) if earlier else None


def find_collisions(conn: psycopg.Connection[Any], store: PayloadStore,
                    seasons: Sequence[int] | None = None) -> list[LabelCase]:
    """Every season (or those of ``seasons``, competition-season ids) whose newest snapshot was written
    from a payload with a repeated table label and lacks rows that payload holds. A payload whose file
    cannot be read is skipped and logged."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(NEWEST_SNAPSHOTS_SQL)
        snaps = [s for s in cur.fetchall() if seasons is None or int(s["cs_id"]) in seasons]
        cur.execute(PAYLOADS_SQL)
        payloads = cur.fetchall()
    out = []
    for snap in snaps:
        p = _payload_for(snap, payloads)
        if p is None:
            continue
        try:
            body = store.load(str(p["file_path"]))["body"]
        except OSError as exc:
            log.warning("standings_repair.unreadable", payload=str(p["hash"])[:12], error=str(exc)[:120])
            continue
        labels = repeated_labels(body)
        if not labels:
            continue
        expected = {f"{r.provider_team_id}|{r.group or ''}" for r in iter_standings(body)}
        have = set(snap["keys"] or [])
        missing = sorted(expected - have)
        if not missing:
            continue
        out.append(LabelCase(int(snap["cs_id"]), int(snap["league"]), int(snap["season"]), str(snap["name"]),
                             snap["snapshot_at"], str(p["hash"]), str(p["file_path"]), labels, int(snap["rows"]),
                             len(expected), missing))
    return out


def rebuild(conn: psycopg.Connection[Any], case: LabelCase, store: PayloadStore, *, at: datetime) -> int:
    """A new snapshot at ``at`` from the case's payload, and its ``audit.data_repairs`` row. Returns rows written."""
    body = store.load(case.file_path)["body"]
    refs = [r for r in iter_standings(body) if (r.provider_league_id, r.season) == (case.league, case.season)]
    outcome = apply_standings_outcome(conn, refs, fetched_at=at, payload_hash=case.payload_hash)
    groups = Counter(r.group or "" for r in refs)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, after_value, "
            "reason, evidence) VALUES (%s, 'core.standings', %s, %s, 'rows in newest snapshot', %s, %s, %s, %s)",
            (RULE, case.cs_id, case.league, f"{case.rows_before} rows at {case.snapshot_at.isoformat()}",
             f"{outcome.written} rows at {at.isoformat()} ({', '.join(f'{g} {n}' for g, n in sorted(groups.items()))})",
             f"the provider labels {len(case.labels)} table label(s) twice in {case.name} {case.season} "
             f"({', '.join(sorted(case.labels))}); the old writer merged those tables and dropped "
             f"{len(case.missing)} row(s). New snapshot from the same payload with the fixed parser; the old "
             "snapshot is kept unchanged",
             f"/standings league={case.league} season={case.season} payload {case.payload_hash}"),
        )
    conn.commit()
    return outcome.written
