"""Resolve the teams whose national flag nobody has told us, from /teams.

One request per team. Cheap, authoritative, and it also gives the row the
payload lineage it was missing - so the team stops being a name with no
provenance and starts being a team the provider described.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import psycopg
from psycopg.rows import tuple_row

from fbi.core.config import settings
from fbi.ingestion.identity import apply_teams
from fbi.ingestion.ledger import RunLedger
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.details import iter_teams
from scripts.capture_odds import _client


async def main() -> int:
    with psycopg.connect(settings.database.psycopg_url) as conn:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT provider_team_id, name FROM core.teams "
                "WHERE is_national IS NULL ORDER BY provider_team_id"
            )
            unknown = [(int(a), str(b)) for a, b in cur.fetchall()]
        if not unknown:
            print("no team has an unknown national flag")
            return 0
        print(f"{len(unknown)} team(s) to resolve: "
              + ", ".join(f"{i} {n}" for i, n in unknown))

        ledger = RunLedger(conn)
        run_id = ledger.open("team_identity_resolve",
                             params={"teams": [i for i, _ in unknown]})
        client = _client()
        provider = ApiFootballProvider(client)
        from fbi.providers.api_football.provider import _raw
        stored = 0
        calls = 0
        resolved = 0
        try:
            for provider_team_id, name in unknown:
                response = await client.get("/teams", {"id": provider_team_id})
                calls += 1
                teams = list(iter_teams(response.body))
                # The payload is indexed BEFORE anything references it: a row
                # cannot exist without the bytes it came from, and the venue a
                # team names has a foreign key onto this index.
                stored += ledger.record_payloads(run_id, [_raw(response)])
                if not teams:
                    print(f"  {provider_team_id} {name}: /teams returned nothing - "
                          "left unknown, which is the honest answer")
                    continue
                observed_at = (
                    ledger.indexed_at(response.stored.hash) or response.fetched_at
                )
                apply_teams(conn, teams, payload_hash=response.stored.hash,
                            fetched_at=observed_at)
                t = teams[0]
                print(f"  {provider_team_id} {t.name}: national={t.is_national} "
                      f"country={t.country}")
                resolved += 1
        finally:
            await provider.aclose()

        conn.commit()
        from fbi.ingestion.ledger import RunCounters
        ledger.close(run_id, RunCounters(api_calls=calls, payloads_stored=stored,
                                         rows_updated=resolved))

        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT count(*) FILTER (WHERE is_national), "
                "       count(*) FILTER (WHERE NOT is_national), "
                "       count(*) FILTER (WHERE is_national IS NULL) FROM core.teams"
            )
            row = cur.fetchone()
            assert row is not None
            print(f"\nteams: national {row[0]}, club {row[1]}, still unknown {row[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
