"""Sync fixtures (and the teams they need) for the active competitions.

The capturer only captures fixtures that exist in core.fixtures; this is what
puts them there. One /fixtures call per active competition-season and window,
so the cost is known before it is spent: N active leagues = N calls.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.base import FixtureRef, FootballDataProvider

log = structlog.get_logger(__name__)

STATUS_GROUP: dict[str, str] = {
    "TBD": "scheduled", "NS": "scheduled",
    "1H": "live", "HT": "live", "2H": "live", "ET": "live", "BT": "live", "P": "live", "LIVE": "live", "INT": "live",
    "FT": "finished", "AET": "finished", "PEN": "finished",
    "SUSP": "postponed", "PST": "postponed",
    "CANC": "cancelled", "ABD": "cancelled", "AWD": "cancelled", "WO": "cancelled",
}


@dataclass(frozen=True)
class ActiveSeason:
    competition_season_id: int
    provider_league_id: int
    season: int
    name: str


def active_seasons(conn: psycopg.Connection) -> list[ActiveSeason]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT cs.id, c.provider_league_id, cs.season, c.name "
            "FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE c.is_tracked AND cs.is_current ORDER BY c.provider_league_id"
        )
        return [ActiveSeason(int(a), int(b), int(c), str(d)) for a, b, c, d in cur.fetchall()]


class FixtureRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def ensure_teams(self, refs: Sequence[FixtureRef], names: dict[int, str]) -> dict[int, int]:
        ids = sorted({r.provider_home_team_id for r in refs} | {r.provider_away_team_id for r in refs})
        if not ids:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.executemany(
                "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) "
                "ON CONFLICT (provider_team_id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()",
                [(tid, names.get(tid, f"team {tid}")) for tid in ids],
            )
            cur.execute("SELECT provider_team_id, id FROM core.teams WHERE provider_team_id = ANY(%s)", (ids,))
            return {int(a): int(b) for a, b in cur.fetchall()}

    def upsert_fixtures(self, refs: Sequence[FixtureRef], season_id: int, team_ids: dict[int, int]) -> tuple[int, int]:
        """Returns (inserted, updated). Kick-off and status are the only
        things that legitimately change; the identity never does."""
        inserted = updated = 0
        with self._conn.cursor(row_factory=tuple_row) as cur:
            for r in refs:
                cur.execute(
                    """
                    INSERT INTO core.fixtures
                      (provider_fixture_id, competition_season_id, home_team_id, away_team_id,
                       kickoff_at, status_short, status_group)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (provider_fixture_id) DO UPDATE SET
                      kickoff_at = EXCLUDED.kickoff_at, status_short = EXCLUDED.status_short,
                      status_group = EXCLUDED.status_group, updated_at = now()
                    RETURNING (xmax = 0) AS inserted
                    """,
                    (
                        r.provider_fixture_id, season_id, team_ids[r.provider_home_team_id],
                        team_ids[r.provider_away_team_id], r.kickoff_at, r.status_short,
                        STATUS_GROUP.get(r.status_short, "scheduled"),
                    ),
                )
                row = cur.fetchone()
                if row is not None and row[0]:
                    inserted += 1
                else:
                    updated += 1
        return inserted, updated


async def sync_fixtures(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    *,
    horizon_days: int = 7,
    at: datetime | None = None,
) -> RunCounters:
    """One provider call per active season. Fixtures within [today, today+horizon]."""
    moment = at or now()
    seasons = active_seasons(conn)
    ledger = RunLedger(conn)
    repo = FixtureRepository(conn)
    run_id = ledger.open("fixtures_sync", params={"seasons": len(seasons), "horizon_days": horizon_days})
    counters = RunCounters()
    date_from = moment.date().isoformat()
    date_to = (moment + timedelta(days=horizon_days)).date().isoformat()

    for s in seasons:
        try:
            refs, raw = await provider.fetch_fixtures(
                league_id=s.provider_league_id, season=s.season, date_from=date_from, date_to=date_to
            )
        except ProviderError as exc:
            counters.errors.append(f"league {s.provider_league_id}: {exc}")
            log.warning("fixtures.fetch_failed", league=s.provider_league_id, error=str(exc))
            continue
        counters.api_calls += 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw])
        counters.rows_normalized += len(refs)
        names = _team_names(raw.body)
        team_ids = repo.ensure_teams(refs, names)
        ins, upd = repo.upsert_fixtures(refs, s.competition_season_id, team_ids)
        counters.rows_inserted += ins
        counters.rows_updated += upd
        conn.commit()
        log.info("fixtures.synced", league=s.provider_league_id, name=s.name, fixtures=len(refs), inserted=ins, updated=upd)

    ledger.close(run_id, counters, notes=f"{date_from}..{date_to}")
    return counters


def _team_names(body: dict[str, object]) -> dict[int, str]:
    names: dict[int, str] = {}
    response = body.get("response")
    if not isinstance(response, list):
        return names
    for entry in response:
        if not isinstance(entry, dict):
            continue
        teams = entry.get("teams")
        if not isinstance(teams, dict):
            continue
        for side in ("home", "away"):
            t = teams.get(side)
            if isinstance(t, dict) and isinstance(t.get("id"), int) and isinstance(t.get("name"), str):
                names[int(t["id"])] = str(t["name"])
    return names
