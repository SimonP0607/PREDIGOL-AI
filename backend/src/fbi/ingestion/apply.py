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
import structlog

from fbi.catalog.neutral_store import classify_provider_fixtures
from fbi.core import match_state
from fbi.ingestion.fixture_facts import apply_fixture_facts
from fbi.ingestion.fixtures import FixtureRepository, PayloadLineage, team_names
from fbi.ingestion.results import ResultRepository
from fbi.providers.api_football.details import iter_fixture_facts
from fbi.providers.base import FootballDataProvider

log = structlog.get_logger(__name__)


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
    venue_verdicts_written: int = 0
    """Neutral-venue verdicts written or changed for the fixtures of the payload (``fbi.catalog.neutral``)."""
    premature_ids: frozenset[int] = frozenset()
    """Provider ids of the fixtures the payload called finished sooner after kick-off than a match can last: nothing of
    them was stored from this payload, and a caller that writes more from the same payload (the live follow's states and
    details) leaves them out too (``fbi.core.match_state.final_is_plausible``)."""

    @property
    def premature_finals(self) -> int:
        return len(self.premature_ids)


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
    premature = {r.provider_fixture_id for r in refs
                 if not match_state.final_is_plausible(r.status_short, r.kickoff_at, fetched_at)}
    if premature:
        # Declined, loudly: the stored state stays what it was and the next read of the match says what is true.
        log.warning("fixture.premature_final", payload_hash=payload_hash, fetched_at=fetched_at.isoformat(),
                    fixtures=[{"provider_fixture_id": r.provider_fixture_id, "status": r.status_short,
                               "minutes_after_kickoff": round(match_state.minutes_after_kickoff(r.kickoff_at, fetched_at), 1)}
                              for r in refs if r.provider_fixture_id in premature])
    ours = [r for r in refs if (r.provider_league_id, r.season) in season_ids
            and r.provider_fixture_id not in premature]
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
    _, written = ResultRepository(conn).apply(
        [x for x in results if x.provider_fixture_id not in premature], lineage=lineage)
    facts = apply_fixture_facts(conn, (f for f in iter_fixture_facts(body) if f.provider_fixture_id not in premature),
                                payload_hash=payload_hash, observed_at=fetched_at)
    verdicts = _classify_venues(conn, [r.provider_fixture_id for r in ours], payload_hash=payload_hash)
    return PayloadOutcome(
        seen=len(refs),
        ours=len(ours),
        fixtures_inserted=inserted,
        fixtures_updated=updated,
        finished_seen=len(results),
        results_written=written,
        facts_written=facts,
        left_tracked=left,
        venue_verdicts_written=verdicts,
        premature_ids=frozenset(premature),
    )


def _classify_venues(conn: psycopg.Connection, provider_fixture_ids: list[int], *, payload_hash: str) -> int:
    """Decide whether the fixtures just written are at a neutral venue (``fbi.catalog.neutral``, rule neutral-v1) and
    keep the verdict. It is derived data and must never cost a payload its fixtures, so it runs in a savepoint: if it
    fails the failure is logged as an error - not swallowed, not turned into a number - and the payload's own writes
    stand; ``python -m scripts.neutral_rule classify`` fills in what is missing."""
    if not provider_fixture_ids:
        return 0
    try:
        with conn.transaction():
            return classify_provider_fixtures(conn, provider_fixture_ids).written
    except Exception:
        log.exception("neutral.classify_failed", fixtures=len(provider_fixture_ids), payload_hash=payload_hash)
        return 0
