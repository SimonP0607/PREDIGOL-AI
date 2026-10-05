"""Standings lineage from RAW: the payload each table snapshot written without one came from (0 provider requests).

    python -m scripts.repair_standings_lineage            # dry run: what would be traced, nothing written
    python -m scripts.repair_standings_lineage --apply    # write it, one audit.data_repairs row per snapshot

``core.standings.payload_hash`` arrived with revision 0048 (4 Oct 2026). The rows written before it - the v2
migration's replay of RAW (29 Sep) and the context refresh until 4 Oct, 15,385 rows in 840 snapshots on 5 Oct -
name no payload, so those tables could not be traced to what the provider said.

A snapshot is one competition season at one instant (``snapshot_at`` is the fetch instant of the payload that
wrote it). It is matched to the ``/standings`` payload of its league and season fetched at that instant, or the
newest one before it (an identical answer keeps its first index time). The payload is read from RAW, verified
against its indexed hash and parsed with the writer's own parser (``iter_standings``); every row of the snapshot
must equal a row of the payload - team, table, rank, points, played, won, drawn, lost, goals for and against,
form - before the hash is written. The table is compared by the provider's own label: the parser now calls the
n-th table under a repeated label "<label> #n" (E-779), the rows written before kept the bare label.

The pre-0048 writer kept one row per team, so a team in two tables of one snapshot (Apertura and Clausura, a
regular season and a play-off round, a third-place ranking) lost the second: such a snapshot is a strict subset of
its payload. Its rows are still that payload's, value for value, and are traced to it; the rows it lacks are
counted and reported (``incomplete``), not added - the newest snapshot of every tracked season was completed by
``refresh_tables --legacy`` (rule ``standings_dropped_tables``), the older ones are history and stay as written.
A snapshot with a row no payload has keeps NULL and is reported.

Only ``payload_hash`` is written. The columns that came with 0048 (goal difference, zone, description, update
stamp, home/away splits) stay NULL on those rows: filling them would rewrite what the snapshot held, and the
snapshots written since carry them. RAW is only read; nothing is deleted.
"""

from __future__ import annotations

import argparse
import re
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
       s.goals_against, s.form, (s.payload_hash IS NULL) AS untraced
  FROM core.standings s JOIN core.teams t ON t.id = s.team_id
 WHERE s.competition_season_id = %(cs)s AND s.snapshot_at = %(at)s
"""

Key = tuple[Any, ...]
REPEATED_LABEL = re.compile(r" #\d+$")


def _key(team: int, group: str | None, *values: Any) -> Key:
    """A row as compared: the table by the provider's own label (a "#n" the parser adds is dropped)."""
    return (int(team), REPEATED_LABEL.sub("", group or ""), *values)


@dataclass
class Report:
    snapshots: int = 0
    rows: int = 0
    traced: int = 0
    rows_traced: int = 0
    exact_instant: int = 0
    incomplete: int = 0
    """Traced snapshots that lack rows of their payload (dropped by the pre-0048 writer)."""
    rows_missing: int = 0
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
            rows = cur.fetchall()
            keys = [(_key(r["provider_team_id"], r["group"], r["rank"], r["points"], r["played"], r["wins"],
                          r["draws"], r["losses"], r["goals_for"], r["goals_against"], r["form"]), r["untraced"])
                    for r in rows]
            stored = Counter(k for k, untraced in keys if untraced)
            whole = Counter(k for k, _ in keys)
            cur.execute(CANDIDATES_SQL, {"league": str(snap["league"]), "season": str(snap["season"]),
                                         "at": snap["snapshot_at"], "n": CANDIDATES})
            match, lacking = None, 0
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
                if body is None:
                    continue
                said = _payload_rows(body, int(snap["league"]), int(snap["season"]), held)
                if not stored - said:
                    match, lacking = cand, sum((said - whole).values())
                    break
            label = f"season {snap['cs']} ({snap['league']}/{snap['season']}) at {snap['snapshot_at']:%Y-%m-%d %H:%M:%S}"
            if match is None:
                report.untraced.append(f"{label}: {snap['rows']} rows, no payload reproduces them")
                continue
            report.traced += 1
            report.rows_traced += int(snap["rows"])
            report.exact_instant += int(match["fetched_at"] == snap["snapshot_at"])
            report.incomplete += int(lacking > 0)
            report.rows_missing += lacking
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
                     "the payload; traced to the /standings payload whose rows it holds value for value",
                     f"{updated} rows each equal to a row of {match['file_path']} (fetched "
                     f"{match['fetched_at'].isoformat()}, hash verified)"
                     + (f"; the snapshot lacks {lacking} of the payload's rows (dropped by the pre-0048 writer, one "
                        "row per team)" if lacking else "") + f"; code {version}"))
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
          f"{r.exact_instant} at the payload's own instant; {r.incomplete} lack {r.rows_missing} of their payload's "
          f"rows); untraced: {len(r.untraced)}; payloads read: {r.payloads_read}")
    for u in r.untraced[:20]:
        print("  UNTRACED " + u)
    for p in r.problems[:10]:
        print("  PROBLEM " + p)
    print("written" if args.apply else "dry run: re-run with --apply")
    return 1 if r.problems else 0


if __name__ == "__main__":
    sys.exit(main())
