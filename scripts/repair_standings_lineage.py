"""Standings lineage from RAW: the payload each table snapshot written without one came from (0 provider requests).

    python -m scripts.repair_standings_lineage            # dry run: what would be traced, nothing written
    python -m scripts.repair_standings_lineage --apply    # write it, one audit.data_repairs row per snapshot

``core.standings.payload_hash`` arrived with revision 0048 (4 Oct 2026). The rows written before it - the v2
migration's replay of RAW (29 Sep) and the context refresh until 4 Oct, 15,385 rows in 840 snapshots on 5 Oct -
name no payload, so a table a model reads could not be traced to what the provider said.

A snapshot is one competition season at one instant (``snapshot_at`` is the fetch instant of the payload that
wrote it). It is matched to the ``/standings`` payload of its league and season fetched at that instant, or the
newest one before it (an identical answer keeps its first index time). The payload is read from RAW, verified
against its indexed hash, parsed with the writer's own parser (``iter_standings``), and every row of the snapshot
must equal a row of the payload - team, table label, rank, points, played, won, drawn, lost, goals for and
against, form - with as many rows as the payload has for teams we hold. Only then is the hash written. A snapshot
no payload reproduces keeps NULL and is reported (for instance a table written before the label fix of E-779,
whose repeated labels were merged).

Only ``payload_hash`` is written. The columns that came with 0048 (goal difference, zone, description, update
stamp, home/away splits) stay NULL on those rows: filling them would rewrite what the snapshot held, and the
snapshots written since carry them. RAW is only read; nothing is deleted.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.ingestion.payload_store import PayloadStore, body_hash
from fbi.providers.api_football.details import iter_standings

RULE = "standings_lineage"
REPO = Path(__file__).resolve().parents[1]
CANDIDATES = 3
"""Payloads tried per snapshot, newest first: the one fetched at the snapshot's instant is the first."""

SNAPSHOTS_SQL = """
SELECT s.competition_season_id AS cs, s.snapshot_at, c.provider_league_id AS league, cs.season, count(*) AS rows
  FROM core.standings s JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE s.payload_hash IS NULL
 GROUP BY 1, 2, 3, 4
 ORDER BY 1, 2
"""

CANDIDATES_SQL = """
SELECT hash, file_path, fetched_at FROM raw.ingestion_payloads
 WHERE endpoint = '/standings' AND params->>'league' = %(league)s AND params->>'season' = %(season)s
   AND fetched_at <= %(at)s
 ORDER BY fetched_at DESC
 LIMIT %(n)s
"""

ROWS_SQL = """
SELECT t.provider_team_id, s."group", s.rank, s.points, s.played, s.wins, s.draws, s.losses, s.goals_for,
       s.goals_against, s.form
  FROM core.standings s JOIN core.teams t ON t.id = s.team_id
 WHERE s.competition_season_id = %(cs)s AND s.snapshot_at = %(at)s AND s.payload_hash IS NULL
"""

Key = tuple[Any, ...]


def _key(team: int, group: str | None, *values: Any) -> Key:
    return (int(team), group or "", *values)


@dataclass
class Report:
    snapshots: int = 0
    rows: int = 0
    traced: int = 0
    rows_traced: int = 0
    exact_instant: int = 0
    payloads_read: int = 0
    untraced: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _payload_rows(body: dict[str, Any], league: int, season: int, held: set[int]) -> Counter[Key]:
    return Counter(_key(r.provider_team_id, r.group, r.rank, r.points, r.played, r.wins, r.draws, r.losses,
                        r.goals_for, r.goals_against, r.form)
                   for r in iter_standings(body)
                   if (r.provider_league_id, r.season) == (league, season) and r.provider_team_id in held)


def repair(conn: psycopg.Connection[Any], raw_root: Path, *, apply: bool) -> Report:
    report = Report()
    version = code_version()
    store = PayloadStore(raw_root)
    bodies: dict[str, dict[str, Any] | None] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SNAPSHOTS_SQL)
        snapshots = cur.fetchall()
        cur.execute("SELECT provider_team_id FROM core.teams")
        held = {int(r["provider_team_id"]) for r in cur.fetchall()}
    report.snapshots = len(snapshots)
    report.rows = sum(int(s["rows"]) for s in snapshots)
    with conn.cursor(row_factory=dict_row) as cur:
        for snap in snapshots:
            cur.execute(ROWS_SQL, {"cs": snap["cs"], "at": snap["snapshot_at"]})
            stored = Counter(_key(r["provider_team_id"], r["group"], r["rank"], r["points"], r["played"], r["wins"],
                                  r["draws"], r["losses"], r["goals_for"], r["goals_against"], r["form"])
                             for r in cur.fetchall())
            cur.execute(CANDIDATES_SQL, {"league": str(snap["league"]), "season": str(snap["season"]),
                                         "at": snap["snapshot_at"], "n": CANDIDATES})
            match = None
            for cand in cur.fetchall():
                h = str(cand["hash"])
                if h not in bodies:
                    body: dict[str, Any] | None = None
                    try:
                        raw = store.load(str(cand["file_path"])).get("body")
                        if body_hash(raw) != h:
                            report.problems.append(f"{cand['file_path']}: does not re-hash to {h[:12]} - skipped")
                        elif isinstance(raw, dict):
                            body = raw
                    except FileNotFoundError:
                        report.problems.append(f"{cand['file_path']}: indexed but not in the raw store")
                    bodies[h] = body
                    report.payloads_read += 1
                body = bodies[h]
                if body is not None and _payload_rows(body, int(snap["league"]), int(snap["season"]), held) == stored:
                    match = cand
                    break
            label = f"season {snap['cs']} ({snap['league']}/{snap['season']}) at {snap['snapshot_at']:%Y-%m-%d %H:%M:%S}"
            if match is None:
                report.untraced.append(f"{label}: {snap['rows']} rows, no payload reproduces them")
                continue
            report.traced += 1
            report.rows_traced += int(snap["rows"])
            report.exact_instant += int(match["fetched_at"] == snap["snapshot_at"])
            if apply:
                cur.execute("UPDATE core.standings SET payload_hash = %s WHERE competition_season_id = %s "
                            "AND snapshot_at = %s AND payload_hash IS NULL",
                            (match["hash"], snap["cs"], snap["snapshot_at"]))
                updated = cur.rowcount
                cur.execute(
                    "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, "
                    "after_value, reason, evidence) VALUES (%s, 'core.standings', %s, %s, 'payload_hash', NULL, %s, "
                    "%s, %s)",
                    (RULE, snap["cs"], snap["league"], match["hash"],
                     f"table snapshot of {snap['snapshot_at'].isoformat()} written before revision 0048 recorded "
                     "the payload; traced to the /standings payload that reproduces it value for value",
                     f"{updated} rows equal to {match['file_path']} (fetched {match['fetched_at'].isoformat()}, "
                     f"hash verified); code {version}"))
    if apply:
        conn.commit()
    else:
        conn.rollback()
    return report


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.runtime.log_level)
    ap = argparse.ArgumentParser(prog="repair_standings_lineage", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    root = Path(settings.runtime.raw_store_dir)
    root = root if root.is_absolute() else REPO / root
    with psycopg.connect(settings.database.psycopg_url) as conn:
        r = repair(conn, root, apply=args.apply)
    print(f"snapshots without a payload: {r.snapshots} ({r.rows} rows); traced: {r.traced} ({r.rows_traced} rows, "
          f"{r.exact_instant} at the payload's own instant); untraced: {len(r.untraced)}; "
          f"payloads read: {r.payloads_read}")
    for u in r.untraced[:20]:
        print("  UNTRACED " + u)
    for p in r.problems[:10]:
        print("  PROBLEM " + p)
    print("written" if args.apply else "dry run: re-run with --apply")
    return 1 if r.problems else 0


if __name__ == "__main__":
    sys.exit(main())
