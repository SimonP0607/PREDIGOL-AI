"""The history of who was reported missing, and when we learned it (plan F0, defect 8).

``core.player_absences`` holds the LAST thing the provider said about each (match, player): every /injuries answer
overwrites it. That table cannot say what was known at an earlier moment (a row refreshed after the moment is dropped by
``fetched_at <= at``), and it cannot say that a player was taken OFF the list: one the newest answer no longer names keeps
his old row, and the AI packet read it as an absence that still stood.

``core.player_availability_obs`` (migration 0078) is the history. An /injuries answer is the provider's complete list for
one season at one moment; it is recorded as the CHANGES it makes against what was known just before it:

    LISTED   the answer names the player for the match, with the type and reason it gives. Written when he was not
             listed, or was listed with a different type, reason or team. An unchanged answer writes nothing.
    CLEARED  the previous state listed him, and this answer - for a match not yet played - no longer names him. Written
             once; type and reason are those of the last listing, so the row says what was cleared.

A match already played keeps its record: nobody is cleared from it, because who was missing is what happened. The state at
``at`` is read by ``fbi.ai.absences.absences_as_of``: per player, the newest row with ``observed_at <= at``, the LISTED ones.

An answer is trusted as the provider's complete list for the season, the same assumption the Match Center made on
11 Oct 2026 when it stopped showing players the newest answer no longer names. An answer older than one already recorded
for the season (it arrived late) changes nothing: the newest wins, as at every other level of ingestion.

``observed_at`` is when WE asked (``RawResponse.fetched_at``), not the payload's index time: the raw store keeps identical
bodies once, at the first fetch, so an answer that went back to an earlier content would be dated in the past and could
never win. Replays of stored payloads (``migration.dryrun``) do not call this module - they know only the index time -
and the history is not rebuilt from RAW: it is written when the answer arrives.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.providers.api_football.details import AbsenceRef

SOURCE = "api-football"
VERSION = "availability-v1"
LOCK_PREFIX = "availability:"
"""``pg_advisory_xact_lock(hashtextextended(LOCK_PREFIX + season id, 0))``: one writer of a season's history at a time."""

STALE_SQL = """
SELECT EXISTS (SELECT 1 FROM core.context_checks
                WHERE competition_season_id = %(season)s AND dataset = 'injuries' AND checked_at > %(at)s)
    OR EXISTS (SELECT 1 FROM core.player_availability_obs o JOIN core.fixtures f ON f.id = o.fixture_id
                WHERE f.competition_season_id = %(season)s AND o.origin = 'answer' AND o.observed_at > %(at)s)
"""
"""A newer answer for this season is already recorded: by the context checks (the live path writes the check right
after the rows) or by the history itself (the backfill path writes no check)."""

FIXTURES_SQL = "SELECT provider_fixture_id, id FROM core.fixtures WHERE provider_fixture_id = ANY(%(ids)s)"

LISTED_SQL = """
WITH answer AS (
    SELECT * FROM jsonb_to_recordset(%(answer)s::jsonb)
      AS a(fixture_id bigint, provider_fixture_id int, provider_player_id int, provider_team_id int, player_name text,
           absence_type text, reason text)
), latest AS (
    SELECT DISTINCT ON (o.fixture_id, o.provider_player_id)
           o.fixture_id, o.provider_player_id, o.status, o.provider_team_id, o.absence_type, o.reason
      FROM core.player_availability_obs o
      JOIN answer a ON a.fixture_id = o.fixture_id AND a.provider_player_id = o.provider_player_id
     WHERE o.source = %(source)s AND o.observed_at <= %(at)s
     ORDER BY o.fixture_id, o.provider_player_id, o.observed_at DESC
)
INSERT INTO core.player_availability_obs
       (fixture_id, source, provider_fixture_id, provider_player_id, observed_at, status, provider_team_id,
        player_name, absence_type, reason, payload_hash, origin, normalizer_version)
SELECT a.fixture_id, %(source)s, a.provider_fixture_id, a.provider_player_id, %(at)s, 'LISTED', a.provider_team_id,
       a.player_name, a.absence_type, a.reason, %(hash)s, 'answer', %(version)s
  FROM answer a
  LEFT JOIN latest l ON l.fixture_id = a.fixture_id AND l.provider_player_id = a.provider_player_id
 WHERE l.status IS DISTINCT FROM 'LISTED'
    OR (l.provider_team_id, l.absence_type, l.reason) IS DISTINCT FROM (a.provider_team_id, a.absence_type, a.reason)
ON CONFLICT DO NOTHING
"""

CLEARED_SQL = """
WITH answer AS (
    SELECT * FROM jsonb_to_recordset(%(answer)s::jsonb) AS a(fixture_id bigint, provider_player_id int)
), standing AS (
    SELECT DISTINCT ON (o.fixture_id, o.provider_player_id) o.*
      FROM core.player_availability_obs o
      JOIN core.fixtures f ON f.id = o.fixture_id
     WHERE f.competition_season_id = %(season)s AND f.status_group = 'scheduled' AND f.kickoff_at > %(at)s
       AND o.source = %(source)s AND o.observed_at <= %(at)s
     ORDER BY o.fixture_id, o.provider_player_id, o.observed_at DESC
)
INSERT INTO core.player_availability_obs
       (fixture_id, source, provider_fixture_id, provider_player_id, observed_at, status, provider_team_id,
        player_name, absence_type, reason, payload_hash, origin, normalizer_version)
SELECT s.fixture_id, s.source, s.provider_fixture_id, s.provider_player_id, %(at)s, 'CLEARED', s.provider_team_id,
       s.player_name, s.absence_type, s.reason, %(hash)s, 'answer', %(version)s
  FROM standing s
 WHERE s.status = 'LISTED'
   AND NOT EXISTS (SELECT 1 FROM answer a WHERE a.fixture_id = s.fixture_id AND a.provider_player_id = s.provider_player_id)
ON CONFLICT DO NOTHING
"""
"""Only matches still to be played: the answer that no longer names a player for a match that has started is the
provider tidying up, not the player recovering."""


@dataclass
class AnswerReport:
    """What recording one answer did."""

    listed: int = 0
    """LISTED rows added: players newly named, or named with something different."""
    cleared: int = 0
    """CLEARED rows added: players the previous state listed and this answer no longer names."""
    unchanged: int = 0
    """Players the answer names exactly as the previous state already had them."""
    unknown_fixture: int = 0
    """Entries for a match the catalogue does not hold: not recorded (the next answer will see the match)."""
    stale: bool = False
    """A newer answer for the season was already recorded: nothing written."""

    @property
    def changes(self) -> int:
        return self.listed + self.cleared


def _last_per_key(entries: Iterable[AbsenceRef]) -> dict[tuple[int, int], AbsenceRef]:
    """One entry per (match, player), the last one the answer carries: what ``core.player_absences`` keeps too."""
    out: dict[tuple[int, int], AbsenceRef] = {}
    for e in entries:
        out[(e.provider_fixture_id, e.provider_player_id)] = e
    return out


def record_answer(conn: psycopg.Connection[Any], entries: Iterable[AbsenceRef], *, payload_hash: str,
                  competition_season_id: int, requested_at: datetime) -> AnswerReport:
    """Record one /injuries answer for one season as its changes. Idempotent: the same answer twice writes nothing.

    ``requested_at`` is the moment the answer was asked for (``RawResponse.fetched_at``). The payload must already be
    indexed (``raw.ingestion_payloads``): every row names it."""
    report = AnswerReport()
    wanted = _last_per_key(entries)
    with conn.cursor(row_factory=tuple_row) as cur:
        # The check and the writes that follow are one unit: two writers on a season (the worker and a backfill) take
        # turns instead of each judging against a state the other is about to change.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{LOCK_PREFIX}{competition_season_id}",))
        cur.execute(STALE_SQL, {"season": competition_season_id, "at": requested_at})
        row = cur.fetchone()
        if row is not None and row[0]:
            report.stale = True
            return report
        fixtures: dict[int, int] = {}
        if wanted:
            cur.execute(FIXTURES_SQL, {"ids": sorted({k[0] for k in wanted})})
            fixtures = {int(a): int(b) for a, b in cur.fetchall()}
        answer = [
            {"fixture_id": fixtures[key[0]], "provider_fixture_id": e.provider_fixture_id,
             "provider_player_id": e.provider_player_id, "provider_team_id": e.provider_team_id,
             "player_name": e.player_name, "absence_type": e.absence_type, "reason": e.reason}
            for key, e in wanted.items() if key[0] in fixtures
        ]
        report.unknown_fixture = len(wanted) - len(answer)
        params = {"answer": Jsonb(answer), "season": competition_season_id, "at": requested_at, "source": SOURCE,
                  "hash": payload_hash, "version": VERSION}
        if answer:
            cur.execute(LISTED_SQL, params)
            report.listed = max(cur.rowcount, 0)
        report.unchanged = len(answer) - report.listed
        cur.execute(CLEARED_SQL, params)
        report.cleared = max(cur.rowcount, 0)
    return report
