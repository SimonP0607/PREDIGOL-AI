"""Catalogue and activation of competitions.

    python -m scripts.manage_competitions import-legacy --dry-run
    python -m scripts.manage_competitions import-legacy
    python -m scripts.manage_competitions apply --dry-run
    python -m scripts.manage_competitions apply
    python -m scripts.manage_competitions refresh-seasons --league 39 [--dry-run]
    python -m scripts.manage_competitions probe --league 39 --league 140
    python -m scripts.manage_competitions list

import-legacy writes core.competitions / competition_seasons / market.bookmakers /
market.markets from the audited backups and prints a migration report.
apply reads config/competitions.yaml and is the only thing that ever flips
is_tracked. list shows what is known and what is active.

refresh-seasons and probe are the only commands here that spend provider
requests: exactly ONE /leagues call per league named, and both say so before
they do it. probe is refresh-seasons in --dry-run plus a verdict on whether the
league can host a capture pilot (current season + odds coverage).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row

from fbi.catalog import activation, legacy_import
from fbi.core.config import settings
from fbi.core.errors import FbiError
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.build import build_client
from fbi.providers.base import SeasonRef

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LEGACY = REPO / "data" / "legacy"
DEFAULT_CONFIG = REPO / "config" / "competitions.yaml"


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url)


def cmd_import(args: argparse.Namespace) -> int:
    legacy_dir = Path(args.legacy_dir)
    conn = None if args.dry_run else _connect()
    try:
        report = legacy_import.run(conn, legacy_dir, dry_run=args.dry_run)
    finally:
        if conn is not None:
            conn.close()
    print(f"mode: {'DRY RUN' if args.dry_run else 'WRITE'}\n")
    print(report.summary_table())
    print("\nwritten:", report.written)
    if report.warnings:
        print(f"\n{len(report.warnings)} warning(s):")
        for w in report.warnings:
            print("  -", w)
    rejected = [r for r in report.rows if r.outcome == "rejected"]
    if rejected:
        print(f"\n{len(rejected)} rejected:")
        for r in rejected:
            print(f"  - {r.source} {r.key}: {r.reason}")
    if args.report:
        Path(args.report).write_text(report.to_json(), encoding="utf-8")
        print(f"\nfull report -> {args.report}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    toggles = activation.load_config(Path(args.config))
    with _connect() as conn:
        diff = activation.apply(conn, toggles, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
        active = activation.active_league_ids(conn)
    print(f"mode: {'DRY RUN' if args.dry_run else 'WRITE'}")
    print(f"enable : {diff.enabled or '-'}")
    print(f"disable: {diff.disabled or '-'}")
    print(f"unknown (not in catalogue, ignored): {diff.unknown or '-'}")
    print(f"unchanged: {diff.unchanged}")
    print(f"active after{' (would be)' if args.dry_run else ''}: {active if not args.dry_run else '(run without --dry-run)'}")
    return 0


async def _fetch_seasons(conn: psycopg.Connection, league_ids: list[int]) -> list[SeasonRef]:
    """One /leagues request per league, recorded in the job ledger."""
    ledger = RunLedger(conn)
    run_id = ledger.open("seasons_refresh", params={"leagues": league_ids})
    counters = RunCounters()
    client = build_client()  # persistent daily budget, shared with every other script
    provider = ApiFootballProvider(client)
    refs: list[SeasonRef] = []
    try:
        for league_id in league_ids:
            try:
                seasons, raw = await provider.fetch_league_seasons(league_id=league_id)
            except FbiError as exc:
                counters.errors.append(f"league {league_id}: {exc}")
                print(f"  league {league_id}: FAILED — {exc}")
                continue
            counters.api_calls += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [raw])
            counters.rows_normalized += len(seasons)
            refs.extend(seasons)
        conn.commit()
    finally:
        await provider.aclose()
        ledger.close(run_id, counters)
    return refs


def _league_ids(args: argparse.Namespace, conn: psycopg.Connection) -> list[int]:
    if args.league:
        return sorted({int(x) for x in args.league})
    ids = activation.active_league_ids(conn)
    if not ids:
        print("no --league given and no competition is tracked: nothing to do.")
    return ids


def _print_season_table(updates: list[activation.SeasonUpdate], *, dry_run: bool) -> None:
    print(f"\nmode: {'DRY RUN' if dry_run else 'WRITE'}")
    print(f"{'league':>7}  {'name':<24} {'was':>5} {'now':>5} {'odds':>5}  window")
    for u in updates:
        window = f"{u.start_date or '?'} .. {u.end_date or '?'}"
        was = str(u.was_current) if u.was_current is not None else "-"
        now = str(u.now_current) if u.now_current is not None else "NONE"
        flag = "yes" if u.has_odds else "NO"
        marker = "" if u.was_current == u.now_current else "   <- changed"
        print(f"{u.provider_league_id:>7}  {u.name[:24]:<24} {was:>5} {now:>5} {flag:>5}  {window}{marker}")
        if u.now_current is None:
            print(f"           ^ the provider exposes {u.seasons_seen} season(s) for this league and none is current")


def cmd_refresh_seasons(args: argparse.Namespace) -> int:
    with _connect() as conn:
        league_ids = _league_ids(args, conn)
        if not league_ids:
            return 0
        print(f"this will spend exactly {len(league_ids)} provider request(s) on /leagues.")
        refs = asyncio.run(_fetch_seasons(conn, league_ids))
        if not refs:
            print("the provider returned no season at all for those leagues.")
            return 1
        updates = activation.refresh_seasons(conn, refs, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
        _print_season_table(updates, dry_run=args.dry_run)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Can this league host a capture pilot? Reads only; writes nothing."""
    with _connect() as conn:
        league_ids = _league_ids(args, conn)
        if not league_ids:
            return 0
        print(f"this will spend exactly {len(league_ids)} provider request(s) on /leagues.")
        refs = asyncio.run(_fetch_seasons(conn, league_ids))
        updates = activation.refresh_seasons(conn, refs, dry_run=True)
        _print_season_table(updates, dry_run=True)
        print("\nverdict")
        viable = []
        for u in updates:
            if u.now_current is None:
                print(f"  {u.provider_league_id:>5} {u.name[:24]:<24} NOT VIABLE — no current season on this plan")
            elif not u.has_odds:
                print(f"  {u.provider_league_id:>5} {u.name[:24]:<24} NOT VIABLE — season {u.now_current} has no odds coverage")
            else:
                print(f"  {u.provider_league_id:>5} {u.name[:24]:<24} viable      — season {u.now_current}, odds covered")
                viable.append(u.provider_league_id)
        print(f"\nviable: {viable or 'none'}")
        print("next: enable one or two of them in config/competitions.yaml, then `apply`, then `refresh-seasons`.")
    return 0 if viable else 1


def cmd_list(_args: argparse.Namespace) -> int:
    with _connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT c.provider_league_id, c.name, c.country, c.type, c.competition_type, c.elo_weight, "
            "       c.is_tracked, count(s.id) AS seasons "
            "FROM core.competitions c LEFT JOIN core.competition_seasons s ON s.competition_id = c.id "
            "GROUP BY c.id ORDER BY c.is_tracked DESC, c.provider_league_id"
        )
        rows = cur.fetchall()
    print(f"{'id':>5}  {'name':<26} {'country':<12} {'fmt':<6} {'kind':<16} {'elo':>4}  tracked seasons")
    for lid, name, country, fmt, kind, elo, tracked, seasons in rows:
        print(f"{lid:>5}  {name[:26]:<26} {(country or '-')[:12]:<12} {fmt:<6} {kind:<16} {float(elo):>4.1f}  {'YES' if tracked else '.':<7} {seasons}")
    print(f"\n{len(rows)} known · {sum(1 for r in rows if r[6])} active")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manage_competitions", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-legacy")
    p.add_argument("--legacy-dir", default=str(DEFAULT_LEGACY))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--report", default=None, help="write the full JSON report here")
    p = sub.add_parser("apply")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("refresh-seasons")
    p.add_argument("--league", action="append", default=[], help="provider league id; repeatable. Default: every tracked competition.")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("probe")
    p.add_argument("--league", action="append", default=[], help="provider league id; repeatable.")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    configure_logging(settings.runtime.log_level)
    handlers = {
        "import-legacy": cmd_import,
        "apply": cmd_apply,
        "refresh-seasons": cmd_refresh_seasons,
        "probe": cmd_probe,
        "list": cmd_list,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
