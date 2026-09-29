"""Sync fixtures (and the teams they need) for the active competitions.

The capturer only captures fixtures that exist in core.fixtures; this is what
puts them there. Two strategies, because one provider plan refuses the other:

  LEAGUE  ``/fixtures?league=&season=&from=&to=`` - one call per active
          competition-season. Cheapest for one league over a long horizon.
  DATE    ``/fixtures?date=`` - one call per calendar day, every league at
          once, filtered locally to the competitions we track. The only
          fixtures query a restricted plan serves: league+season comes back
          with "Free plans do not have access to this season", while date
          alone is answered in full.

``auto`` tries LEAGUE and falls back to DATE when the provider refuses on plan
grounds. Two different budgets are involved and they disagree about that
refused request, so be precise: the PROVIDER does not count an errored call
against its daily limit, while OUR ``DailyQuota`` is spent when the request is
issued, before the answer is known. The ledger follows ours - requests issued -
because a budget that under-reports what it sent is a budget that gets
overspent. So the fallback is free against the provider's 100/day and costs one
request against our own cap.

Either way the cost is stated before it is spent, and every call lands in the
job ledger whether it succeeded or not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.odds.horizons import DEFAULT_HORIZON_DAYS
from fbi.providers.base import FixtureRef, FootballDataProvider, RawResponse

if TYPE_CHECKING:
    from fbi.ingestion.apply import PayloadOutcome

log = structlog.get_logger(__name__)

PLAN_REFUSAL = "do not have access"
"""Substring the provider uses when the plan, not the request, is the problem."""


class SyncStrategy(StrEnum):
    AUTO = "auto"
    LEAGUE = "league"
    DATE = "date"

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


def tracked_season_ids(conn: psycopg.Connection) -> dict[tuple[int, int], int]:
    """(provider_league_id, season) -> competition_season_id, tracked only.

    The date strategy gets fixtures for every league on Earth; this is what
    decides which of them are ours. A fixture whose (league, season) is not in
    here is dropped, not guessed at.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT c.provider_league_id, cs.season, cs.id "
            "FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE c.is_tracked"
        )
        return {(int(a), int(b)): int(c) for a, b, c in cur.fetchall()}


@dataclass(frozen=True, slots=True)
class PayloadLineage:
    """Which stored payload a write came from, and when it was fetched.

    ``fetched_at`` orders writes: a row is only ever overwritten by a payload
    fetched at the same instant or later, so re-applying an old response (a
    replay, a late retry) cannot regress a finished match to scheduled.
    """

    payload_hash: str
    fetched_at: datetime


# A write with lineage may replace a row with no lineage or with older lineage.
# A write WITHOUT lineage may only replace a row that has none either: it must
# never be able to overwrite something a traced payload established.
MONOTONIC_SQL = """
    (EXCLUDED.source_fetched_at IS NULL AND {t}.source_fetched_at IS NULL)
    OR (EXCLUDED.source_fetched_at IS NOT NULL
        AND ({t}.source_fetched_at IS NULL OR EXCLUDED.source_fetched_at >= {t}.source_fetched_at))
"""


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

    def ensure_venues(self, refs: Sequence[FixtureRef]) -> dict[int, int]:
        """provider_venue_id -> core.venues.id, for the venues these refs name.

        A venue the provider does not identify is not created: a name without
        an id cannot be deduplicated, and a duplicated venue is worse than none.
        """
        venues = {r.provider_venue_id: r for r in refs if r.provider_venue_id is not None and r.venue_name}
        if not venues:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.executemany(
                "INSERT INTO core.venues (provider_venue_id, name, city) VALUES (%s, %s, %s) "
                "ON CONFLICT (provider_venue_id) DO UPDATE SET name = EXCLUDED.name, "
                "city = COALESCE(EXCLUDED.city, core.venues.city)",
                [(vid, r.venue_name, r.venue_city) for vid, r in venues.items()],
            )
            cur.execute(
                "SELECT provider_venue_id, id FROM core.venues WHERE provider_venue_id = ANY(%s)",
                (sorted(venues),),
            )
            return {int(a): int(b) for a, b in cur.fetchall()}

    def upsert_fixtures(
        self,
        refs: Sequence[FixtureRef],
        season_ids: Mapping[tuple[int, int], int],
        team_ids: dict[int, int],
        *,
        lineage: PayloadLineage | None = None,
        venue_ids: Mapping[int, int] | None = None,
    ) -> tuple[int, int]:
        """Returns (inserted, updated). Kick-off, status, round and venue are
        the things that legitimately change; the identity never does.

        ``season_ids`` maps (provider_league_id, season) to the row in
        core.competition_seasons. A ref with no entry is skipped: we do not
        invent a season row for a competition we are not tracking.

        A ref older than what the row already holds is skipped too, and counted
        in neither total - see ``PayloadLineage``.
        """
        inserted = updated = 0
        venue_ids = venue_ids or {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            for r in refs:
                season_id = season_ids.get((r.provider_league_id, r.season))
                if season_id is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO core.fixtures
                      (provider_fixture_id, competition_season_id, home_team_id, away_team_id,
                       kickoff_at, status_short, status_group, round, venue_id,
                       source_payload_hash, source_fetched_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (provider_fixture_id) DO UPDATE SET
                      kickoff_at = EXCLUDED.kickoff_at, status_short = EXCLUDED.status_short,
                      status_group = EXCLUDED.status_group,
                      round = COALESCE(EXCLUDED.round, core.fixtures.round),
                      venue_id = COALESCE(EXCLUDED.venue_id, core.fixtures.venue_id),
                      source_payload_hash = EXCLUDED.source_payload_hash,
                      source_fetched_at = EXCLUDED.source_fetched_at,
                      updated_at = now()
                    WHERE """ + MONOTONIC_SQL.format(t="core.fixtures") + """
                    RETURNING (xmax = 0) AS inserted
                    """,
                    (
                        r.provider_fixture_id, season_id, team_ids[r.provider_home_team_id],
                        team_ids[r.provider_away_team_id], r.kickoff_at, r.status_short,
                        STATUS_GROUP.get(r.status_short, "scheduled"), r.round,
                        venue_ids.get(r.provider_venue_id) if r.provider_venue_id is not None else None,
                        lineage.payload_hash if lineage else None,
                        lineage.fetched_at if lineage else None,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    continue  # an older payload than the one already applied
                if row[0]:
                    inserted += 1
                else:
                    updated += 1
        return inserted, updated


async def sync_fixtures(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    at: datetime | None = None,
    strategy: SyncStrategy = SyncStrategy.AUTO,
) -> RunCounters:
    """Bring core.fixtures up to date for the tracked competitions.

    Cost: LEAGUE = one request per active competition-season.
          DATE   = one request per calendar day in the horizon, all leagues.
    """
    moment = at or now()
    ledger = RunLedger(conn)
    run_id = ledger.open(
        "fixtures_sync",
        params={"horizon_days": horizon_days, "strategy": str(strategy)},
        scheduled_for=moment,
    )
    counters = RunCounters()
    try:
        if strategy in (SyncStrategy.AUTO, SyncStrategy.LEAGUE):
            refused = await _sync_by_league(conn, provider, ledger, run_id, counters, moment, horizon_days)
            if refused and strategy is SyncStrategy.AUTO:
                log.warning("fixtures.plan_refused_league_strategy", falling_back_to="date")
                counters.errors.clear()  # the refusal is understood and handled, not a failure
                await _sync_by_date(conn, provider, ledger, run_id, counters, moment, horizon_days)
        else:
            await _sync_by_date(conn, provider, ledger, run_id, counters, moment, horizon_days)
    finally:
        ledger.close(run_id, counters, notes=str(strategy))
    return counters


async def _sync_by_league(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    ledger: RunLedger,
    run_id: int,
    counters: RunCounters,
    moment: datetime,
    horizon_days: int,
) -> bool:
    """Returns True if the provider refused on PLAN grounds (so a fallback is
    warranted). A transport or parameter error is a real error and is recorded
    as one."""
    seasons = active_seasons(conn)
    season_ids = tracked_season_ids(conn)
    date_from = moment.date().isoformat()
    date_to = (moment + timedelta(days=horizon_days)).date().isoformat()
    plan_refused = False

    for s in seasons:
        try:
            refs, raw = await provider.fetch_fixtures(
                league_id=s.provider_league_id, season=s.season, date_from=date_from, date_to=date_to
            )
        except ProviderError as exc:
            # The request WAS issued, so it is counted even though it failed.
            counters.api_calls += 1
            counters.errors.append(f"league {s.provider_league_id}: {exc}")
            if PLAN_REFUSAL in str(exc):
                plan_refused = True
            log.warning("fixtures.fetch_failed", league=s.provider_league_id, error=str(exc))
            continue
        counters.api_calls += 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw])
        outcome = _apply(conn, provider, raw, season_ids, counters)
        conn.commit()
        log.info("fixtures.synced", strategy="league", league=s.provider_league_id,
                 name=s.name, seen=len(refs), inserted=outcome.fixtures_inserted,
                 updated=outcome.fixtures_updated, results_written=outcome.results_written)
    return plan_refused


async def _sync_by_date(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    ledger: RunLedger,
    run_id: int,
    counters: RunCounters,
    moment: datetime,
    horizon_days: int,
) -> None:
    """One request per day. Every league comes back; only tracked ones are kept."""
    season_ids = tracked_season_ids(conn)
    if not season_ids:
        log.warning("fixtures.no_tracked_seasons")
        return
    for offset in range(horizon_days + 1):
        on: date = (moment + timedelta(days=offset)).date()
        try:
            _, raw = await provider.fetch_fixtures_by_date(on=on)
        except ProviderError as exc:
            counters.api_calls += 1
            counters.errors.append(f"{on.isoformat()}: {exc}")
            log.warning("fixtures.fetch_failed", date=on.isoformat(), error=str(exc))
            continue
        counters.api_calls += 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw])
        outcome = _apply(conn, provider, raw, season_ids, counters)
        conn.commit()
        log.info("fixtures.synced", strategy="date", date=on.isoformat(),
                 seen_all_leagues=outcome.seen, seen_ours=outcome.ours,
                 inserted=outcome.fixtures_inserted, updated=outcome.fixtures_updated,
                 results_written=outcome.results_written)


def _apply(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    raw: RawResponse,
    season_ids: Mapping[tuple[int, int], int],
    counters: RunCounters,
) -> PayloadOutcome:
    """Apply a just-fetched payload and account for it in the run's counters.

    A score is recorded as an update: it changes the state of a fixture we
    already hold, it does not create a new one.
    """
    # Imported here, not at module level: apply imports this module.
    from fbi.ingestion.apply import apply_fixtures_payload

    outcome = apply_fixtures_payload(
        conn, provider, raw.body,
        payload_hash=raw.payload_hash, fetched_at=raw.fetched_at, season_ids=season_ids,
    )
    counters.rows_normalized += outcome.ours
    counters.rows_inserted += outcome.fixtures_inserted
    counters.rows_updated += outcome.fixtures_updated + outcome.results_written
    return outcome


def team_names(body: dict[str, object]) -> dict[int, str]:
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
