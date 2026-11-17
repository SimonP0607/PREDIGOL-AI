"""Sync fixtures (and the teams they need) for the active competitions.

The capturer only captures fixtures that exist in core.fixtures; this is what
puts them there. Two strategies, because one provider plan refuses the other:

  LEAGUE  ``/fixtures?league=&season=`` - one call per active competition-season,
          the whole season: identities, kick-offs, statuses and scores.
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

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg.errors
import structlog
from psycopg.rows import tuple_row

from fbi.core import match_state
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

STATUS_GROUP: dict[str, str] = match_state.STORED_GROUP
"""The stored group of each short status: one table, in fbi.core.match_state, with the phase every layer reads."""


def status_group(status_short: str, default: str = "scheduled") -> str:
    """The group of a short status, whatever its spelling (see ``canonical_status``)."""
    return match_state.stored_group(status_short, default)


@dataclass(frozen=True)
class ActiveSeason:
    competition_season_id: int
    provider_league_id: int
    season: int
    name: str


FINISHED_GRACE_DAYS = 30
"""How long after its last known fixture a current season is still refreshed.

Not zero: a postponed match can be rescheduled weeks later, and the point of
refreshing is to see that. Not open-ended either - see below."""


def active_seasons(conn: psycopg.Connection, *, at: datetime | None = None) -> list[ActiveSeason]:
    """The seasons the LEAGUE strategy will spend a request on, one each.

    ``is_current`` is the provider's answer and it is reliable - exactly one
    current season per tracked competition, 124 of them. What it does not say is
    whether that season is over. The World Cup qualifying seasons stay current
    for years, and 25 of the 124 had already played their last fixture, 23 of
    them more than a month ago: a quarter of this job's requests, every run,
    asking a finished competition whether anything had changed.

    So a season whose newest known fixture is more than FINISHED_GRACE_DAYS past
    is left alone. A season with no fixtures at all is kept, because "we have
    never fetched this one" is the opposite of "this one is over".

    "Now" is the APPLICATION clock (``at`` or ``fbi.core.clock.now``), not SQL ``now()``. The window used to be
    read from the database's own clock while every other date in the job came from the application's, so a test
    that froze the application clock was still judged by the real day: on 2026-10-15 the seed fixture of the
    integration suite (2026-09-15) crossed the 30-day mark and six tests failed with no code having changed.
    In production the two clocks are the same instant.
    """
    moment = at or now()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT cs.id, c.provider_league_id, cs.season, c.name "
            "FROM core.competition_seasons cs "
            "JOIN core.competitions c ON c.id = cs.competition_id "
            "LEFT JOIN LATERAL ("
            "  SELECT max(f.kickoff_at) AS last_kickoff FROM core.fixtures f "
            "  WHERE f.competition_season_id = cs.id"
            ") k ON true "
            "WHERE c.is_tracked AND cs.is_current "
            "  AND (k.last_kickoff IS NULL "
            "       OR k.last_kickoff > %s::timestamptz - make_interval(days => %s)) "
            "ORDER BY c.provider_league_id",
            (moment, FINISHED_GRACE_DAYS),
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


KEEP_REPAIRED_CITY_SQL = """
SELECT 1 FROM audit.data_repairs d
 WHERE d.entity = 'core.fixtures' AND d.entity_id = core.fixtures.id AND d.field = 'venue_city'
   AND d.rule = 'fixture_venue_city' AND d.before_value = EXCLUDED.venue_city AND d.after_value = core.fixtures.venue_city
"""
"""A city the owner's repair already corrected (``scripts.repair_venue_city``, rule ``fixture_venue_city``, BE-005) is not written
back by the next sync when the provider's payload repeats the very value it replaced (BE-008: Mestalla's «Valdivia» came back
two hours after the repair). Any other city the provider sends - a real change - is taken as before."""


KEEP_REASSIGNED_VENUE_SQL = """
SELECT 1 FROM audit.data_repairs d
 WHERE d.entity = 'core.fixtures' AND d.entity_id = core.fixtures.id AND d.field = 'venue_id'
   AND d.rule = 'fixture_venue_reassigned' AND d.before_value = EXCLUDED.venue_id::text
   AND d.after_value = core.fixtures.venue_id::text
"""
"""A match a person pointed at the ground it was played at (``scripts.reassign_fixture_venue``, rule
``fixture_venue_reassigned``, BE-037) keeps that venue while the provider's payload repeats the very id it was moved away
from: the provider files two grounds under one id (143 is the Linz arena and the LASK's old ground at Pasching), so the id
of every refresh points at the wrong one. Any other venue the provider sends - a real change - is taken as before."""


UPSERT_SQL = """
    INSERT INTO core.fixtures
      (provider_fixture_id, competition_season_id, home_team_id, away_team_id,
       kickoff_at, status_short, status_group, round, venue_id, venue_name, venue_city,
       source_payload_hash, source_fetched_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (provider_fixture_id) DO UPDATE SET
      competition_season_id = EXCLUDED.competition_season_id,
      home_team_id = EXCLUDED.home_team_id, away_team_id = EXCLUDED.away_team_id,
      kickoff_at = EXCLUDED.kickoff_at, status_short = EXCLUDED.status_short,
      status_group = EXCLUDED.status_group,
      round = COALESCE(EXCLUDED.round, core.fixtures.round),
      venue_id = CASE WHEN EXISTS (""" + KEEP_REASSIGNED_VENUE_SQL + """) THEN core.fixtures.venue_id
                      ELSE COALESCE(EXCLUDED.venue_id, core.fixtures.venue_id) END,
      venue_name = COALESCE(EXCLUDED.venue_name, core.fixtures.venue_name),
      venue_city = CASE WHEN EXISTS (""" + KEEP_REPAIRED_CITY_SQL + """) THEN core.fixtures.venue_city
                        ELSE COALESCE(EXCLUDED.venue_city, core.fixtures.venue_city) END,
      source_payload_hash = EXCLUDED.source_payload_hash,
      source_fetched_at = EXCLUDED.source_fetched_at,
      updated_at = now()
    WHERE """ + MONOTONIC_SQL.format(t="core.fixtures") + """
    RETURNING (xmax = 0) AS inserted
"""
"""One fixture, inserted or brought up to date (monotonic on the fetch time, ``MONOTONIC_SQL``)."""


LINEAGE_ONLY_SQL = """
    UPDATE core.fixtures f
       SET source_payload_hash = %(h)s, source_fetched_at = %(at)s, updated_at = now()
      FROM unnest(%(ids)s::bigint[], %(versions)s::text[]) AS u(id, version)
     WHERE f.id = u.id AND f.xmin::text = u.version
       AND ((%(at)s::timestamptz IS NULL AND f.source_fetched_at IS NULL)
            OR (%(at)s::timestamptz IS NOT NULL
                AND (f.source_fetched_at IS NULL OR %(at)s::timestamptz >= f.source_fetched_at)))
    RETURNING f.id
"""
"""The fixtures a payload confirmed without changing anything (OPS-006): the same final row the upsert leaves - its
content already equal, its lineage and ``updated_at`` moved - in one statement. ``xmin`` is the row version read
before deciding "equal": a row another session wrote in between is not touched here and goes through ``UPSERT_SQL``.
The same monotonic rule as ``MONOTONIC_SQL``: an older payload changes nothing."""


@dataclass(frozen=True, slots=True)
class HeldFixture:
    """A fixture row as read before a payload is applied to it."""

    id: int
    home_team_id: int
    away_team_id: int
    kickoff_at: datetime
    competition_season_id: int
    status_short: str
    status_group: str
    round: str | None
    venue_id: int | None
    venue_name: str | None
    venue_city: str | None
    version: str
    """``xmin``: which version of the row this is."""

    def same_as(self, r: FixtureRef, season_id: int, team_ids: Mapping[int, int], venue_id: int | None) -> bool:
        """Would ``UPSERT_SQL`` leave every column of the row as it is, lineage apart? Only a sure yes counts: a
        value the upsert keeps (an absent round, venue or city: ``COALESCE``) is equal; anything else that differs,
        even a venue or a city a repair keeps (``KEEP_*_SQL``), is left to the upsert, which knows those rules."""
        return (self.competition_season_id == season_id
                and self.home_team_id == team_ids[r.provider_home_team_id]
                and self.away_team_id == team_ids[r.provider_away_team_id]
                and self.kickoff_at == r.kickoff_at
                and self.status_short == r.status_short
                and self.status_group == status_group(r.status_short)
                and (r.round is None or r.round == self.round)
                and (venue_id is None or venue_id == self.venue_id)
                and (r.venue_name is None or r.venue_name == self.venue_name)
                and (r.venue_city is None or r.venue_city == self.venue_city))


def _repeated(ids: Iterable[int]) -> set[int]:
    """Ids that appear more than once (a payload that lists a fixture twice is applied in order, row by row)."""
    seen: set[int] = set()
    twice: set[int] = set()
    for i in ids:
        (twice if i in seen else seen).add(i)
    return twice


class FixtureRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self.unchanged = 0
        """Fixtures whose payload said exactly what the row held: only their lineage moved (OPS-006)."""

    def ensure_teams(self, refs: Sequence[FixtureRef], names: dict[int, str]) -> dict[int, int]:
        ids = sorted({r.provider_home_team_id for r in refs} | {r.provider_away_team_id for r in refs})
        if not ids:
            return {}
        # A team we hold is written only when the payload names it differently. Every payload used to rewrite
        # every team in it - a new row version each time, locked until the payload's transaction ended - so the
        # in-play capture waited on the fixtures sync: on the server, 9 Oct 2026, three waits of seven minutes.
        # Nor is a known name replaced by the "team <id>" placeholder any more when a payload does not carry one.
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT provider_team_id, id, name FROM core.teams WHERE provider_team_id = ANY(%s)", (ids,))
            held = {int(p): (int(i), n) for p, i, n in cur.fetchall()}
            renamed = [(names[t], t) for t in ids if t in held and t in names and names[t] != held[t][1]]
            if renamed:
                cur.executemany("UPDATE core.teams SET name = %s, updated_at = now() WHERE provider_team_id = %s",
                                renamed)
            new = [t for t in ids if t not in held]
            if new:
                cur.executemany("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) "
                                "ON CONFLICT (provider_team_id) DO NOTHING",
                                [(t, names.get(t, f"team {t}")) for t in new])
                cur.execute("SELECT provider_team_id, id FROM core.teams WHERE provider_team_id = ANY(%s)", (new,))
                held.update({int(p): (int(i), "") for p, i in cur.fetchall()})
            return {t: held[t][0] for t in ids if t in held}

    def ensure_venues(self, refs: Sequence[FixtureRef]) -> dict[int, int]:
        """provider_venue_id -> core.venues.id, for the venues these refs name.

        A venue the provider does not identify is not created: a name without
        an id cannot be deduplicated, and a duplicated venue is worse than none.
        Neither is one with id 0, the provider's "no id" (until 5 Oct 2026 it made
        one venue of 154 stadiums).

        A fixture's venue block names a new venue; it never changes a known one.
        It is what the provider called the ground for that match - a Milan home
        match played in Perth keeps San Siro's id and says "Optus Stadium" - and
        the fixture keeps that name itself (venue_name). The venue's own name comes
        from /venues or /teams.
        """
        venues = {r.provider_venue_id: r for r in refs
                  if r.provider_venue_id is not None and r.provider_venue_id > 0 and r.venue_name}
        if not venues:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.executemany(
                "INSERT INTO core.venues (provider_venue_id, name, city) VALUES (%s, %s, %s) "
                "ON CONFLICT (provider_venue_id) DO NOTHING",
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
        the things that legitimately change; the provider's fixture id is the
        identity and never does.

        ``season_ids`` maps (provider_league_id, season) to the row in
        core.competition_seasons. A ref with no entry is skipped: we do not
        invent a season row for a competition we are not tracking (a fixture we
        hold that the provider moved out of the tracked set is flagged by
        ``note_left_tracked`` instead).

        The competition season follows the provider like the sides do: a fixture
        it moves to another tracked competition or season goes with it, and the
        move is one ``audit.data_repairs`` row (rule ``fixture_competition``).
        Until 5 Oct 2026 the update never touched it, so a moved fixture stayed
        listed under the competition it had left.

        A ref older than what the row already holds is skipped too, and counted
        in neither total - see ``PayloadLineage``.

        A ref that says exactly what the row already holds (OPS-006) is not
        written again field by field: only its lineage moves forward - which
        payload last confirmed the row and when (``source_payload_hash``,
        ``source_fetched_at``, ``updated_at``), the values every reader of "when
        did the provider last say this" reads - in one statement for all of them
        (``LINEAGE_ONLY_SQL``). The final rows are the ones the upsert would have
        left; what goes is the per-row statement, its two audit subqueries and its
        rewrite of every column. On the server, 16 Nov 2026, the 15:41 sync applied
        the club friendlies' payload of 10:17 a second time - the same body, byte
        for byte - and rewrote all 8,397 of its fixtures. A row that changed
        between the read here and the write (another session wrote it) goes
        through the full upsert, as every changed row does.
        """
        inserted = updated = 0
        venue_ids = venue_ids or {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            known = {r.provider_fixture_id for r in refs}
            cur.execute("SELECT provider_fixture_id, id, home_team_id, away_team_id, kickoff_at, "
                        "competition_season_id, status_short, status_group, round, venue_id, venue_name, venue_city, "
                        "xmin::text FROM core.fixtures WHERE provider_fixture_id = ANY(%s)",
                        (sorted(known),))
            held = {int(x[0]): HeldFixture(*x[1:]) for x in cur.fetchall()}
            seen_twice = _repeated(r.provider_fixture_id for r in refs)
            full: list[tuple[FixtureRef, int]] = []
            same: dict[int, tuple[FixtureRef, int, str]] = {}
            for r in refs:
                season_id = season_ids.get((r.provider_league_id, r.season))
                if season_id is None:
                    continue
                h = held.get(r.provider_fixture_id)
                vid = venue_ids.get(r.provider_venue_id) if r.provider_venue_id is not None else None
                if (h is not None and r.provider_fixture_id not in seen_twice
                        and h.same_as(r, season_id, team_ids, vid)):
                    same[h.id] = (r, season_id, h.version)
                else:
                    full.append((r, season_id))
            for r, season_id in full:
                outcome = self._upsert_one(cur, r, season_id, team_ids, held, lineage=lineage, venue_ids=venue_ids)
                inserted += outcome == "inserted"
                updated += outcome == "updated"
            if same:
                ids = sorted(same)
                cur.execute(LINEAGE_ONLY_SQL, {"ids": ids, "versions": [same[i][2] for i in ids],
                                               "h": lineage.payload_hash if lineage else None,
                                               "at": lineage.fetched_at if lineage else None})
                refreshed = {int(x[0]) for x in cur.fetchall()}
                updated += len(refreshed)
                # Not refreshed: an older payload than the row's (skipped, as the upsert would), or a row another
                # session wrote since it was read - that one gets the full upsert, which decides as it always did.
                for fid in ids:
                    if fid in refreshed:
                        continue
                    r, season_id, _ = same[fid]
                    outcome = self._upsert_one(cur, r, season_id, team_ids, held, lineage=lineage,
                                               venue_ids=venue_ids)
                    inserted += outcome == "inserted"
                    updated += outcome == "updated"
            self.unchanged += len(same)
        return inserted, updated

    def _upsert_one(
        self,
        cur: psycopg.Cursor[tuple[Any, ...]],
        r: FixtureRef,
        season_id: int,
        team_ids: dict[int, int],
        held: Mapping[int, HeldFixture],
        *,
        lineage: PayloadLineage | None,
        venue_ids: Mapping[int, int],
    ) -> str | None:
        """The upsert of one fixture and the trail of what it changed. Returns "inserted", "updated" or None (an
        older payload than the one already applied)."""
        cur.execute(
            UPSERT_SQL,
            (
                r.provider_fixture_id, season_id, team_ids[r.provider_home_team_id],
                team_ids[r.provider_away_team_id], r.kickoff_at, r.status_short,
                status_group(r.status_short), r.round,
                venue_ids.get(r.provider_venue_id) if r.provider_venue_id is not None else None,
                r.venue_name, r.venue_city,
                lineage.payload_hash if lineage else None,
                lineage.fetched_at if lineage else None,
            ),
        )
        row = cur.fetchone()
        if row is None:
            return None  # an older payload than the one already applied
        if row[0]:
            return "inserted"
        h = held.get(r.provider_fixture_id)
        moved_from = h.kickoff_at if h is not None else None
        if moved_from is not None and moved_from != r.kickoff_at:
            # Kept so a capture planned on the old time can be explained later.
            cur.execute(
                "INSERT INTO core.fixture_kickoff_changes (fixture_id, observed_at, before_kickoff, "
                "after_kickoff, payload_hash) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (h.id if h is not None else None, lineage.fetched_at if lineage else now(), moved_from,
                 r.kickoff_at, lineage.payload_hash if lineage else None),
            )
        was_in = h.competition_season_id if h is not None else None
        if h is not None and was_in is not None and was_in != season_id:
            # The provider moved the fixture to another competition season we track.
            cur.execute(
                "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, "
                "before_value, after_value, reason, evidence) VALUES ('fixture_competition', "
                "'core.fixtures', %s, %s, 'competition_season_id', %s, %s, %s, %s)",
                (h.id, r.provider_fixture_id, str(was_in), str(season_id),
                 f"the provider moved this fixture to league {r.provider_league_id} season {r.season}",
                 lineage.payload_hash if lineage else None),
            )
        after = (team_ids[r.provider_home_team_id], team_ids[r.provider_away_team_id])
        if h is not None and (h.home_team_id, h.away_team_id) != after:
            # The provider corrected who plays whom. The row follows it - the
            # provider's fixture id is the identity - and the change is kept.
            cur.execute(
                "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, "
                "before_value, after_value, reason, evidence) VALUES ('fixture_sides', 'core.fixtures', "
                "%s, %s, 'home_team_id/away_team_id', %s, %s, %s, %s)",
                (h.id, r.provider_fixture_id, f"{h.home_team_id} v {h.away_team_id}", f"{after[0]} v {after[1]}",
                 "the provider changed the sides of this fixture", lineage.payload_hash if lineage else None),
            )
        return "updated"

    def note_left_tracked(self, refs: Sequence[FixtureRef], season_ids: Mapping[tuple[int, int], int], *,
                          payload_hash: str | None = None) -> int:
        """Flag the fixtures we hold that the provider now lists under a competition we do not track.

        The row is not moved - that would mean inventing a season row - and not deleted: it stays
        where it was, and one quality issue (``STALE_DATA`` on the field ``competition``, provider's
        league and season against ours) says so until the destination is tracked or the move is
        accepted. Seen on 4 Oct 2026: Panama v New Zealand (1632353), moved from Friendlies to the
        Kirin Cup semi-finals. Returns how many were flagged.
        """
        others = {r.provider_fixture_id: r for r in refs if (r.provider_league_id, r.season) not in season_ids}
        if not others:
            return 0
        # Imported here: the quality registry is not needed on the common path.
        from fbi.quality.issues import EntityType, IssueCode, IssueRegistry, QualityIssue

        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT f.provider_fixture_id, f.id, c.provider_league_id, cs.season FROM core.fixtures f "
                "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                "JOIN core.competitions c ON c.id = cs.competition_id WHERE f.provider_fixture_id = ANY(%s)",
                (sorted(others),),
            )
            held = cur.fetchall()
        registry = IssueRegistry(self._conn)
        flagged = 0
        for pfid, fid, league, season in held:
            r = others[int(pfid)]
            if (int(league), int(season)) == (r.provider_league_id, r.season):
                continue  # held in a competition we stopped tracking: not a move
            flagged += 1
            registry.record(QualityIssue(
                code=IssueCode.STALE_DATA, entity_type=EntityType.FIXTURE, entity_id=int(fid),
                provider_entity_id=int(pfid), payload_hash=payload_hash, field="competition",
                observed=f"league {r.provider_league_id} season {r.season}",
                expected=f"league {league} season {season}",
                detail="the provider moved this fixture to a competition we do not track; the row stays "
                       "where it was (no season row is invented) until that competition is tracked or the "
                       "move is accepted"))
            log.warning("fixtures.left_tracked", fixture=int(pfid), held_in=f"{league}/{season}",
                        provider_now=f"{r.provider_league_id}/{r.season}")
        return flagged


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
    seasons = active_seasons(conn, at=moment)
    season_ids = tracked_season_ids(conn)
    plan_refused = False

    # The WHOLE season, not today..today+horizon. Same one request per season, and it is
    # the only way a season stays complete: the window left every match before the day a
    # season was first synced unknown (the 2026-27 J1 League had 40 of its 380 fixtures,
    # 80 of them already played; club friendlies 177 of 8,327), and a match rescheduled
    # beyond the window kept its old kick-off until it came back into it. Statuses and
    # scores of the past arrive in the same payload.
    for s in seasons:
        try:
            refs, raw = await provider.fetch_fixtures(league_id=s.provider_league_id, season=s.season)
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
        outcome = await _apply(conn, provider, raw, season_ids, counters, what=f"league {s.provider_league_id}")
        log.info("fixtures.synced", strategy="league", league=s.provider_league_id,
                 name=s.name, seen=len(refs), inserted=outcome.fixtures_inserted,
                 updated=outcome.fixtures_updated, unchanged=outcome.fixtures_unchanged,
                 results_written=outcome.results_written, left_tracked=outcome.left_tracked)
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
        outcome = await _apply(conn, provider, raw, season_ids, counters, what=f"date {on.isoformat()}")
        log.info("fixtures.synced", strategy="date", date=on.isoformat(),
                 seen_all_leagues=outcome.seen, seen_ours=outcome.ours,
                 inserted=outcome.fixtures_inserted, updated=outcome.fixtures_updated,
                 unchanged=outcome.fixtures_unchanged, results_written=outcome.results_written,
                 left_tracked=outcome.left_tracked)


FIXTURE_BLOCK = 250
"""Fixtures of one payload applied and committed together (OPS-006). A season used to be one transaction: the club
friendlies' 8,400 fixtures stayed locked for about 30 minutes (server, 16 Nov 2026, 16:13-16:44 UTC), and the in-play
capture of any of them waited that long. A block holds its rows for seconds."""

CLASSIFY_BLOCK = 500
"""Fixtures whose neutral-venue verdicts are written per transaction, once every block of the payload is in."""

LOCK_TIMEOUT = "5s"
"""How long a statement of the sync waits for a row another session holds (the in-play capture, a repair) before its
block is rolled back and tried again. The server's default is 0: wait for ever."""

LOCK_RETRY_PAUSES_S: tuple[float, ...] = (2.0, 5.0, 15.0)
"""Pauses before each new attempt of a block that waited too long; after the last one the block is given up (an error
of the run: the next sync applies the same fixtures, and the payload stays in the RAW store)."""

_LOCK_ERRORS: tuple[type[BaseException], ...] = (psycopg.errors.LockNotAvailable, psycopg.errors.DeadlockDetected)


async def _in_block[T](conn: psycopg.Connection, what: str, step: Callable[[], T], counters: RunCounters) -> T | None:
    """Run ``step`` as one transaction with ``LOCK_TIMEOUT`` and commit it. A lock wait past the timeout (or a deadlock)
    rolls the block back and tries it again after a pause; the block's writes are monotonic, so a retry writes what the
    first attempt would have. Returns None when the block is given up."""
    for attempt, pause in enumerate((*LOCK_RETRY_PAUSES_S, None), start=1):
        try:
            conn.execute("SELECT set_config('lock_timeout', %s, true)", (LOCK_TIMEOUT,))
            out = step()
            conn.commit()
            return out
        except _LOCK_ERRORS as exc:
            conn.rollback()
            if pause is None:
                counters.errors.append(f"{what}: gave up after {attempt} lock waits ({type(exc).__name__})")
                log.warning("fixtures.block_gave_up", block=what, attempts=attempt, error=type(exc).__name__)
                return None
            log.info("fixtures.block_lock_wait", block=what, attempt=attempt, retry_in_s=pause,
                     error=type(exc).__name__)
            await asyncio.sleep(pause)
    return None


async def _apply(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    raw: RawResponse,
    season_ids: Mapping[tuple[int, int], int],
    counters: RunCounters,
    *,
    what: str,
) -> PayloadOutcome:
    """Apply a just-fetched payload in blocks and account for it in the run's counters.

    The payload is the provider's list of fixtures; ``apply_fixtures_payload`` reads every entry on its own, so a
    block of ``FIXTURE_BLOCK`` entries is applied exactly as the whole list was - fixture, score and facts of a match
    in the same transaction - and committed (OPS-006). The neutral-venue verdicts follow once every block is in, as
    ``apply_fixtures_payload`` does at its end, in blocks of ``CLASSIFY_BLOCK``. Every block runs with
    ``LOCK_TIMEOUT`` and is retried on a lock wait (``_in_block``).

    A score is recorded as an update: it changes the state of a fixture we
    already hold, it does not create a new one.
    """
    # Imported here, not at module level: apply imports this module.
    from fbi.catalog.neutral_store import Reference, reference_for
    from fbi.ingestion.apply import PayloadOutcome, _classify_venues, apply_fixtures_payload

    conn.commit()  # the payload's index row stands on its own, whatever a block does
    body = raw.body
    entries = body.get("response")
    blocks: list[dict[str, object]] = (
        [{**body, "response": entries[i:i + FIXTURE_BLOCK]} for i in range(0, len(entries), FIXTURE_BLOCK)]
        if isinstance(entries, list) and len(entries) > FIXTURE_BLOCK else [body])
    parts: list[PayloadOutcome] = []
    for n, block in enumerate(blocks, start=1):
        def step(block: dict[str, object] = block) -> PayloadOutcome:
            return apply_fixtures_payload(conn, provider, block, payload_hash=raw.payload_hash,
                                          fetched_at=raw.fetched_at, season_ids=season_ids, classify=False)
        out = await _in_block(conn, f"{what} block {n}/{len(blocks)}", step, counters)
        if out is not None:
            parts.append(out)
    ours = [i for p in parts for i in p.ours_ids]
    ref: list[Reference | None] = []
    verdicts = 0
    for start in range(0, len(ours), CLASSIFY_BLOCK):
        ids = ours[start:start + CLASSIFY_BLOCK]

        def classify(ids: list[int] = ids) -> int:
            if not ref:
                ref.append(reference_for(conn, ours))  # once per payload, and not at all for league matches alone
            return _classify_venues(conn, ids, payload_hash=raw.payload_hash, ref=ref[0], reraise=_LOCK_ERRORS)
        verdicts += await _in_block(conn, f"{what} verdicts {start // CLASSIFY_BLOCK + 1}", classify, counters) or 0
    outcome = PayloadOutcome(
        seen=sum(p.seen for p in parts), ours=sum(p.ours for p in parts),
        fixtures_inserted=sum(p.fixtures_inserted for p in parts),
        fixtures_updated=sum(p.fixtures_updated for p in parts),
        finished_seen=sum(p.finished_seen for p in parts), results_written=sum(p.results_written for p in parts),
        facts_written=sum(p.facts_written for p in parts), left_tracked=sum(p.left_tracked for p in parts),
        venue_verdicts_written=verdicts, fixtures_unchanged=sum(p.fixtures_unchanged for p in parts),
        ours_ids=tuple(ours), premature_ids=frozenset(i for p in parts for i in p.premature_ids),
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
