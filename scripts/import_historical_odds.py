"""Import historical 1X2 and O/U 2.5 odds from Football-Data.co.uk, then compute the market baseline.

    python -m scripts.import_historical_odds                   # dry run: download, match, report - write nothing
    python -m scripts.import_historical_odds --apply
    python -m scripts.import_historical_odds --apply --leagues 39 --seasons 2024
    python -m scripts.import_historical_odds --apply --from-raw   # re-read the CSVs already stored: no download

One small CSV per league-season (free, no login). Every file is kept in the raw
store under its hash. Rows are attached to stored fixtures only when date,
both teams and the score agree - see fbi.ingestion.historical_odds. Spends
nothing from the API-Football budget.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

import httpx
import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.historical_odds import (
    SOURCE,
    load_aliases,
    load_our_fixtures,
    match_rows,
    write_matched,
    write_matched_stats,
)
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.ingestion.payload_store import PayloadStore, StoredPayload
from fbi.market.baseline import compute_from_historical, write_baseline
from fbi.providers.football_data.parse import DIVISIONS, csv_url, decode, parse_csv, season_code

USER_AGENT = "football-intelligence-v2 (private research; contact: repository owner)"
POLITE_DELAY_S = 2.0


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="import_historical_odds", description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--leagues", type=str, default="39,140,78,135,61")
    parser.add_argument("--seasons", type=str, default="2024,2023,2022")
    parser.add_argument("--from-raw", action="store_true",
                        help="use the CSVs already in the raw store (their payload rows must exist)")
    args = parser.parse_args()
    leagues = [int(x) for x in args.leagues.split(",") if x.strip()]
    seasons = [int(x) for x in args.seasons.split(",") if x.strip()]
    store = PayloadStore(settings.runtime.raw_store_dir, provider="football-data")

    with psycopg.connect(settings.database.psycopg_url) as conn, httpx.Client(
        timeout=30, headers={"user-agent": USER_AGENT}, follow_redirects=True
    ) as http:
        ledger = RunLedger(conn) if args.apply else None
        run_id = ledger.open("historical_odds_import", params={"source": SOURCE, "leagues": leagues,
                                                              "seasons": seasons}) if ledger else None
        counters = RunCounters()
        known = load_aliases(conn)
        downloads = 0
        try:
            for league in leagues:
                div = DIVISIONS.get(league)
                if div is None:
                    print(f"league {league}: no Football-Data division known - skipped")
                    continue
                with conn.cursor(row_factory=tuple_row) as cur:
                    cur.execute("SELECT id FROM core.competitions WHERE provider_league_id = %s", (league,))
                    comp = cur.fetchone()
                if comp is None:
                    print(f"league {league}: not in the catalogue - skipped")
                    continue
                for season in seasons:
                    endpoint = f"/mmz4281/{season_code(season)}/{div}.csv"
                    if args.from_raw:
                        with conn.cursor(row_factory=tuple_row) as cur:
                            cur.execute("SELECT hash, file_path, fetched_at FROM raw.ingestion_payloads "
                                        "WHERE provider = 'football_data' AND endpoint = %s "
                                        "ORDER BY fetched_at DESC LIMIT 1", (endpoint,))
                            got = cur.fetchone()
                        if got is None:
                            print(f"{div} {season}: not in the raw store - skipped")
                            continue
                        envelope = store.load(str(got[1]))
                        text = str(envelope["body"]["text"])
                        fetched_at = got[2]
                        stored = StoredPayload(str(got[0]), str(got[1]), 0, True)
                    else:
                        url = csv_url(div, season)
                        if downloads:
                            time.sleep(POLITE_DELAY_S)
                        res = http.get(url)
                        downloads += 1
                        if res.status_code != 200:
                            counters.errors.append(f"{url}: HTTP {res.status_code}")
                            print(f"{div} {season}: HTTP {res.status_code} - skipped")
                            continue
                        text = decode(res.content)
                        fetched_at = datetime.now(UTC)
                        stored = store.store(endpoint=endpoint, params={"division": div, "season": str(season)},
                                             fetched_at=fetched_at, http_status=200,
                                             body={"format": "csv", "text": text})
                    rows, skipped = parse_csv(text)
                    ours = load_our_fixtures(conn, int(comp[0]), season)
                    report = match_rows(rows, ours, known)
                    n_prices = sum(len(r.prices) for r, _ in report.matched)
                    print(f"{div} {season}: {len(rows)} rows, {len(ours)} stored fixtures -> "
                          f"{len(report.matched)} matched, {len(report.unmatched)} unmatched, "
                          f"{len(skipped)} unparsable; {n_prices} prices")
                    for row, why in report.unmatched[:5]:
                        print(f"    unmatched {row.match_date} {row.home} v {row.away} "
                              f"{row.goals_home}-{row.goals_away}: {why}")
                    if not args.apply:
                        continue
                    if not args.from_raw:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, "
                                "fetched_at, http_status, results_count, file_path, bytes) "
                                "VALUES (%s,%s,'football_data',%s,%s,%s,200,%s,%s,%s) ON CONFLICT (hash) DO NOTHING",
                                (stored.hash, run_id, endpoint, Json({"division": div, "season": str(season)}),
                                 fetched_at, len(rows), stored.file_path, stored.bytes_written),
                            )
                        counters.payloads_stored += 1
                    counters.rows_normalized += len(report.matched)
                    counters.rows_inserted += write_matched(conn, report, payload_hash=stored.hash)
                    n_stats = write_matched_stats(conn, report, payload_hash=stored.hash, fetched_at=fetched_at)
                    counters.rows_inserted += n_stats
                    print(f"    team statistics rows written: {n_stats}")
                    known.update({a: t for a, (t, _) in report.aliases.items()})
                    conn.commit()
            if args.apply:
                base = compute_from_historical(conn, source=SOURCE, bookmakers=("pinnacle", "AVG", "bet365"))
                n = write_baseline(conn, base)
                conn.commit()
                counters.rows_updated += n
                print(f"market baseline rows written: {n}")
            else:
                print("dry run - nothing written (use --apply)")
        finally:
            if ledger is not None and run_id is not None:
                # api_calls stays 0: these are not API-Football requests and must
                # not be reconciled against its budget.
                ledger.close(run_id, counters, notes=f"{downloads} CSV download(s) from {SOURCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
