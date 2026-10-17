"""Fill new tables from stored RAW payloads - no provider request, nothing existing changed.

    python -m scripts.backfill_from_raw --fixture-facts            # core.fixture_facts + core.fixture_player_extras
    python -m scripts.backfill_from_raw --fixture-facts --dry-run  # count the rows the history holds, write nothing
    python -m scripts.backfill_from_raw --season-stats             # /players and /teams/statistics payloads ->
                                                                   # core.player_season_stats / core.team_season_stats

Every stored /fixtures payload is replayed in the order it was fetched (``raw.ingestion_payloads.fetched_at``,
then hash) through the value functions the live writers use (``facts_values`` / ``extras_values``): a
fixture's - or a player's match - first observation that says anything, and every later one that says
something different, becomes a row stamped with that payload's time and hash. So:

* the result is the history the live writers would have kept had they existed when the payloads came in;
* a second run adds nothing: the same payloads give the same rows, and a row whose key is held is skipped
  (``INSERT ... ON CONFLICT DO NOTHING``);
* rows the live writers added since migration 0058 stay as they are. Where one repeats the state of the RAW
  row just before it (the live writer met an empty table), the history keeps that one repeat: nothing is
  updated or deleted to hide it.

The change-only state is held in memory. A fixture's players are dropped from it once the last payload
that names the fixture (its ``ids`` parameter) has been read, so memory follows the fixtures in flight,
not the 5 million player rows. Rows go in by COPY into a temporary table, then one INSERT per batch.
Payload files are read, never modified. The run is recorded in raw.ingestion_runs (job
raw_backfill_fixture_facts); SIGTERM closes it as aborted.
"""

from __future__ import annotations

import argparse
import gzip
import json
import signal
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.ingestion.fixture_facts import (
    NORMALIZER_VERSION,
    ExtrasValues,
    FactsValues,
    extras_values,
    facts_values,
)
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.details import iter_fixture_details, iter_fixture_facts

REPO = Path(__file__).resolve().parents[1]
BATCH = 50_000

PAYLOADS_SQL = """
SELECT hash, file_path, fetched_at, params FROM raw.ingestion_payloads
 WHERE endpoint = '/fixtures' AND http_status = 200
 ORDER BY fetched_at, hash
"""

FIXTURES_SQL = """
SELECT f.provider_fixture_id, f.id, th.provider_team_id, ta.provider_team_id FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
"""

FACTS_COLUMNS = ("fixture_id", "observed_at", "referee", "referee_country", "home_winner", "away_winner",
                 "first_half_at", "second_half_at", "payload_hash", "normalizer_version")
EXTRAS_COLUMNS = ("fixture_id", "provider_player_id", "observed_at", "team_side", "position_played", "offsides",
                  "dribbled_past", "penalties_won", "penalties_committed", "penalties_saved", "payload_hash",
                  "normalizer_version")


def detail_ids(params: Any) -> tuple[int, ...]:
    """The fixtures a /fixtures?ids= (or ?id=) payload was asked for; () for a list request."""
    if not isinstance(params, Mapping):
        return ()
    raw = params.get("ids", params.get("id"))
    if raw is None:
        return ()
    out = []
    for part in str(raw).split("-"):
        if part.strip().isdigit():
            out.append(int(part))
    return tuple(out)


@dataclass
class Replay:
    """The change-only state of a chronological replay, and the rows it adds."""

    fixtures: Mapping[int, tuple[int, int, int]]
    """provider fixture id -> (fixture id, home provider team id, away provider team id)."""
    last_naming: Mapping[int, int] = field(default_factory=dict)
    """provider fixture id -> index of the last payload whose ``ids`` names it."""
    facts_state: dict[int, tuple[datetime, FactsValues]] = field(default_factory=dict)
    extras_state: dict[int, dict[int, tuple[datetime, ExtrasValues]]] = field(default_factory=dict)
    """The newest row's time and state per key. A payload no newer than that row adds nothing, as in the
    live writers (two payloads stamped with the same instant: the first in hash order is kept)."""
    facts_rows: list[tuple[Any, ...]] = field(default_factory=list)
    extras_rows: list[tuple[Any, ...]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(
        ("payloads", "detail_payloads", "facts_rows", "extras_rows", "unknown_fixtures"), 0))

    def feed(self, index: int, payload_hash: str, at: datetime, body: dict[str, Any],
             ids: Iterable[int]) -> None:
        self.counts["payloads"] += 1
        for r in iter_fixture_facts(body):
            v = facts_values(r)
            if v is None:
                continue
            known = self.fixtures.get(r.provider_fixture_id)
            if known is None:
                self.counts["unknown_fixtures"] += 1
                continue
            held = self.facts_state.get(r.provider_fixture_id)
            if held is not None and (held[0] >= at or held[1] == v):
                continue
            self.facts_state[r.provider_fixture_id] = (at, v)
            self.facts_rows.append((known[0], at, *v, payload_hash, NORMALIZER_VERSION))
            self.counts["facts_rows"] += 1
        ids = tuple(ids)
        if not ids:
            return
        self.counts["detail_payloads"] += 1
        for d in iter_fixture_details(body):
            known = self.fixtures.get(d.provider_fixture_id)
            if known is None or "players" not in d.blocks_present:
                continue
            fixture_id, home, away = known
            sides = {home: "home", away: "away"}
            state = self.extras_state.setdefault(d.provider_fixture_id, {})
            for ps in d.players:
                v2 = extras_values(ps, sides)
                if v2 is None:
                    continue
                kept = state.get(ps.provider_player_id)
                if kept is not None and (kept[0] >= at or kept[1] == v2):
                    continue
                state[ps.provider_player_id] = (at, v2)
                self.extras_rows.append((fixture_id, ps.provider_player_id, at, *v2, payload_hash,
                                         NORMALIZER_VERSION))
                self.counts["extras_rows"] += 1
        for pf in ids:
            if self.last_naming.get(pf, -1) <= index:
                self.extras_state.pop(pf, None)


def _body(raw_root: Path, file_path: str) -> tuple[dict[str, Any] | None, str | None]:
    """The stored body, or (None, why) for a file that is missing, empty, truncated or not JSON. The file is
    reported, never repaired: RAW is evidence."""
    f = Path(file_path) if Path(file_path).is_absolute() else raw_root / file_path
    try:
        data = f.read_bytes()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        doc = json.loads(data)
    except (OSError, EOFError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"[:160]
    body = doc.get("body", doc) if isinstance(doc, dict) else None
    return (body, None) if isinstance(body, dict) else (None, "no body object")


def flush(conn: psycopg.Connection[Any], replay: Replay, *, commit: bool = True) -> tuple[int, int]:
    """Write the pending rows; rows whose key is held already are skipped. Returns (facts, extras) added."""
    added = []
    for table, columns, rows in (("fixture_facts", FACTS_COLUMNS, replay.facts_rows),
                                 ("fixture_player_extras", EXTRAS_COLUMNS, replay.extras_rows)):
        if not rows:
            added.append(0)
            continue
        cols = ", ".join(columns)
        with conn.cursor() as cur:
            cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS stage_{table} "
                        f"(LIKE core.{table} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS")
            cur.execute(f"TRUNCATE stage_{table}")
            with cur.copy(f"COPY stage_{table} ({cols}) FROM STDIN") as cp:
                for row in rows:
                    cp.write_row(row)
            cur.execute(f"INSERT INTO core.{table} ({cols}) SELECT {cols} FROM stage_{table} ON CONFLICT DO NOTHING")
            added.append(max(cur.rowcount, 0))
        rows.clear()
    if commit:
        conn.commit()
    return added[0], added[1]


def fixture_facts(conn: psycopg.Connection[Any], *, dry_run: bool, progress_every: int = 1000) -> dict[str, Any]:
    raw_root = Path(settings.runtime.raw_store_dir)
    raw_root = raw_root if raw_root.is_absolute() else REPO / raw_root
    with conn.cursor() as cur:
        cur.execute(FIXTURES_SQL)
        fixtures = {int(a): (int(b), int(c), int(d)) for a, b, c, d in cur.fetchall()}
        cur.execute(PAYLOADS_SQL)
        payloads = cur.fetchall()
    conn.rollback()
    named = [detail_ids(p[3]) for p in payloads]
    last: dict[int, int] = {}
    for i, ids in enumerate(named):
        for pf in ids:
            last[pf] = i
    replay = Replay(fixtures=fixtures, last_naming=last)
    out: dict[str, Any] = {"unreadable": 0, "facts_added": 0, "extras_added": 0, "unreadable_files": []}
    for i, (h, path, fetched_at, _params) in enumerate(payloads):
        body, why = _body(raw_root, str(path))
        if body is None:
            out["unreadable"] += 1
            out["unreadable_files"].append({"hash": str(h), "file": str(path), "fetched_at": str(fetched_at),
                                            "why": why})
            continue
        replay.feed(i, str(h), fetched_at, body, named[i])
        if len(replay.facts_rows) + len(replay.extras_rows) >= BATCH:
            if dry_run:
                replay.facts_rows.clear()
                replay.extras_rows.clear()
            else:
                a, b = flush(conn, replay)
                out["facts_added"] += a
                out["extras_added"] += b
        if (i + 1) % progress_every == 0:
            print(json.dumps({"progress": i + 1, "of": len(payloads), "in_flight_fixtures": len(replay.extras_state),
                              **replay.counts, **{k: v for k, v in out.items() if k != "unreadable_files"}}),
                  flush=True)
    if not dry_run:
        a, b = flush(conn, replay)
        out["facts_added"] += a
        out["extras_added"] += b
    return {**replay.counts, **out}


SEASON_PAYLOADS_SQL = """
SELECT p.hash, p.file_path, p.fetched_at, p.endpoint, p.params FROM raw.ingestion_payloads p
 WHERE p.endpoint IN ('/players', '/teams/statistics') AND p.http_status = 200
 ORDER BY p.fetched_at, p.hash
"""

TEAM_SEASON_SQL = """
SELECT cs.id, t.id FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id,
       core.teams t
 WHERE c.provider_league_id = %(league)s AND cs.season = %(season)s AND t.provider_team_id = %(team)s
"""


def season_stats(conn: psycopg.Connection[Any], *, dry_run: bool) -> dict[str, Any]:
    """Replay every stored /players and /teams/statistics payload, in fetch order, through the season-stats
    writers (change-only; a payload no newer than the newest row adds nothing)."""
    from fbi.ingestion.season_stats import apply_player_season_stats, apply_team_statistics

    raw_root = Path(settings.runtime.raw_store_dir)
    raw_root = raw_root if raw_root.is_absolute() else REPO / raw_root
    with conn.cursor() as cur:
        cur.execute(SEASON_PAYLOADS_SQL)
        payloads = cur.fetchall()
    out: dict[str, Any] = {"payloads": 0, "unreadable": 0, "player_rows": 0, "team_rows": 0,
                           "team_unknown": 0, "unreadable_files": []}
    for h, path, fetched_at, endpoint, params in payloads:
        body, why = _body(raw_root, str(path))
        if body is None:
            out["unreadable"] += 1
            out["unreadable_files"].append({"hash": str(h), "file": str(path), "why": why})
            continue
        out["payloads"] += 1
        if endpoint == "/players":
            out["player_rows"] += apply_player_season_stats(conn, body, payload_hash=str(h), observed_at=fetched_at)
            continue
        args = {k: int(str(params.get(k))) for k in ("league", "season", "team")
                if isinstance(params, dict) and str(params.get(k, "")).isdigit()}
        row = None
        if len(args) == 3:
            with conn.cursor() as cur:
                cur.execute(TEAM_SEASON_SQL, args)
                row = cur.fetchone()
        if row is None:
            out["team_unknown"] += 1
            continue
        out["team_rows"] += apply_team_statistics(conn, int(row[0]), int(row[1]), body, payload_hash=str(h),
                                                  observed_at=fetched_at)
    conn.rollback() if dry_run else conn.commit()
    out["facts_added"] = out["extras_added"] = 0
    return out


def _terminate(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture-facts", action="store_true", help="core.fixture_facts and core.fixture_player_extras")
    ap.add_argument("--season-stats", action="store_true", help="core.player_season_stats and core.team_season_stats")
    ap.add_argument("--dry-run", action="store_true", help="replay and count, write nothing")
    args = ap.parse_args(argv)
    if not (args.fixture_facts or args.season_stats):
        ap.error("nothing to do: give --fixture-facts or --season-stats")
    if args.season_stats:
        signal.signal(signal.SIGTERM, _terminate)
        with psycopg.connect(settings.database.psycopg_url) as conn:
            ledger = RunLedger(conn)
            run_id = None if args.dry_run else ledger.open("raw_backfill_season_stats", params={"mode": "replay"})
            counters = RunCounters()
            try:
                stats = season_stats(conn, dry_run=args.dry_run)
                counters.rows_normalized = stats["payloads"]
                counters.rows_inserted = stats["player_rows"] + stats["team_rows"]
            finally:
                if run_id is not None:
                    ledger.close(run_id, counters, notes="RAW -> core.player_season_stats / core.team_season_stats, "
                                                         "change-only replay, 0 requests")
        print(json.dumps({"dry_run": args.dry_run, **stats}, indent=1, default=str))
        if not args.fixture_facts:
            return 0
    signal.signal(signal.SIGTERM, _terminate)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        ledger = RunLedger(conn)
        run_id = None if args.dry_run else ledger.open(
            "raw_backfill_fixture_facts", params={"normalizer_version": NORMALIZER_VERSION, "mode": "replay"})
        counters = RunCounters()
        try:
            result = fixture_facts(conn, dry_run=args.dry_run)
            counters.rows_normalized = result["payloads"]
            counters.rows_inserted = result["facts_added"] + result["extras_added"]
            counters.errors += [f"unreadable RAW payload {u['hash']} ({u['file']}): {u['why']}"
                                for u in result["unreadable_files"][:20]]
        finally:
            if run_id is not None:
                ledger.close(run_id, counters, notes="RAW -> core.fixture_facts / core.fixture_player_extras, "
                                                     "chronological change-only replay, 0 requests")
    print(json.dumps({"dry_run": args.dry_run, "normalizer_version": NORMALIZER_VERSION, **result}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
