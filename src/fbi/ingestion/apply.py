"""One path from a stored /fixtures payload to the database.

Three callers used to each do their own version of this - the fixtures sync,
the results sync, and nobody at all for stored payloads - and each read a
different subset of the same response. The fixtures sync kept identities and
threw the scores away; the results sync kept scores and ignored postponements.
Every /fixtures response carries both, so every caller now applies both, the
same way:

    parse fixtures  -> upsert the tracked ones (teams, venue, round, status)
    parse results   -> write the score of every finished fixture we hold

and every row written records which payload wrote it (``PayloadLineage``).

The function is pure with respect to the network: it takes a payload that has
already been fetched and stored. That is what lets ``scripts.replay_raw``
re-normalise a response from last week without spending a request - and,
because writes are monotonic on the fetch time, without undoing anything a
newer response established.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import psycopg

from fbi.ingestion.fixture_facts import apply_fixture_facts
from fbi.ingestion.fixtures import FixtureRepository, PayloadLineage, team_names
from fbi.ingestion.results import ResultRepository
from fbi.providers.api_football.details import iter_fixture_facts
from fbi.providers.base import FootballDataProvider


@dataclass(frozen=True, slots=True)
class PayloadOutcome:
    seen: int
    """Fixtures in the payload, every league."""
    ours: int
    """Of those, fixtures of a tracked competition-season."""
    fixtures_inserted: int
    fixtures_updated: int
    finished_seen: int
    """Finished fixtures in the payload, every league."""
    results_written: int
    """Scores written or refreshed for fixtures we hold."""
    facts_written: int = 0
    """Rows added to core.fixture_facts (referee, winner flags, half starts; change-only)."""
    left_tracked: int = 0
    """Fixtures we hold that the payload lists under a competition we do not track (flagged, not moved)."""


def apply_fixtures_payload(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    body: dict[str, object],
    *,
    payload_hash: str,
    fetched_at: datetime,
    season_ids: Mapping[tuple[int, int], int],
) -> PayloadOutcome:
    """Apply one /fixtures response. The caller owns the transaction."""
    lineage = PayloadLineage(payload_hash=payload_hash, fetched_at=fetched_at)
    refs = provider.parse_fixtures(body)
    ours = [r for r in refs if (r.provider_league_id, r.season) in season_ids]
    inserted = updated = 0
    repo = FixtureRepository(conn)
    if ours:
        team_ids = repo.ensure_teams(ours, team_names(body))
        venue_ids = repo.ensure_venues(ours)
        inserted, updated = repo.upsert_fixtures(
            ours, season_ids, team_ids, lineage=lineage, venue_ids=venue_ids
        )
    left = repo.note_left_tracked(refs, season_ids, payload_hash=payload_hash) if len(ours) < len(refs) else 0
    results = provider.parse_results(body)
    _, written = ResultRepository(conn).apply(results, lineage=lineage)
    facts = apply_fixture_facts(conn, iter_fixture_facts(body), payload_hash=payload_hash, observed_at=fetched_at)
    return PayloadOutcome(
        seen=len(refs),
        ours=len(ours),
        fixtures_inserted=inserted,
        fixtures_updated=updated,
        finished_seen=len(results),
        results_written=written,
        facts_written=facts,
        left_tracked=left,
    )
