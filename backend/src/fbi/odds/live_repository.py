"""The in-play book as it stands NOW. Ephemeral by design, and separate by construction.

This module writes market.live_fixture_current and market.live_odds_current and NOTHING else. It cannot write
market.odds_snapshots, market.final_prematch_odds, market.near_close_snapshots or market.market_consensus, so no
in-play price can reach the pre-match series, a model, a pick or the backtest through here - the separation is a
property of the code, not a convention to remember.

WHY THE PRESENT AND NOT A HISTORY (owner's decision, 6 Oct 2026)
---------------------------------------------------------------
Until revision 0068 every change of every in-play price was appended to market.live_odds_snapshots. Measured over
94 complete matches that was 15,851 rows - 4.86 MB in PostgreSQL - per match, ~125 GB a year at 133 leagues, and
nothing but the live page ever read it: PrediGol publishes pre-match picks only, and no model, feature, pick,
parlay, backtest or settlement reads an in-play price (docs/owner/LIVE_ODDS_STORAGE_2026-10-06.md, and
tests/unit/test_prematch_independence.py, which keeps it so).

So one row per (fixture, provider bet, selection, line) holds the price being quoted NOW, with the one it replaced:

    a key quoted for the first time (or again after being withdrawn)   INSERT, change_kind 'offered'
    its price moved                                                    UPDATE, 'moved', previous_odds kept
    its suspension flipped                                             UPDATE, 'suspended' / 'available'
    quoted exactly as before                                           nothing (most of every tick)
    no longer quoted by a fixture this tick observed                   DELETE (the provider withdrew it)
    its fixture not seen by the odds feed for STALE_AFTER              purged with the fixture

The table is therefore bounded by what is in play at one instant - tens of thousands of rows at the busiest moment
of a Saturday, none on a quiet night - and a match leaves no trace in it once it is over. Score, minute, events,
statistics, line-ups and the result are NOT in-play odds: the fixture feed keeps them permanently
(``fbi.ingestion.live_match``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.catalog.provider_markets import record_observed_bets
from fbi.core.clock import now
from fbi.providers.api_football.live import (
    LiveFixtureState,
    LiveMarketSeen,
    LiveOddsQuote,
)

log = structlog.get_logger(__name__)

STALE_AFTER = timedelta(minutes=10)
"""A fixture the odds feed has not seen for this long has left the live book - full time, or the provider stopped
pricing it - and its rows are purged. Ten minutes rides out a provider hiccup of several 30-second ticks without
keeping a finished match's last prices on the board for long."""

LiveKey = tuple[int, int, str, Decimal]
"""(fixture_id, provider_bet_id, selection, line): the primary key of market.live_odds_current."""


@dataclass(frozen=True, slots=True)
class CurrentQuote:
    """What the book holds now for one key."""

    odds: Decimal
    is_suspended: bool
    market_key: str | None

    @property
    def quoted_as(self) -> tuple[Decimal, bool]:
        """The part a new observation is compared against. market_key is identity, not state."""
        return (self.odds, self.is_suspended)


@dataclass(frozen=True, slots=True)
class LiveChange:
    """The last change of one key still in the book, newest first in ``LiveOddsRepository.changes``."""

    provider_fixture_id: int
    market_key: str | None
    provider_bet_id: int
    selection: str
    line: Decimal
    previous_odds: Decimal | None
    odds: Decimal
    implied_prob_delta: Decimal | None
    """Change in implied probability, the number that means something: 2.00 -> 1.90 is a far bigger move than
    10.0 -> 9.90, and the raw odds delta says the opposite. None when only the suspension flipped."""
    change_kind: str
    changed_at: datetime
    minute: int | None
    score_home: int | None
    score_away: int | None


@dataclass(frozen=True, slots=True)
class LiveWriteResult:
    quotes_offered: int
    quotes_written: int
    """Keys inserted or updated: what changed in the book this tick."""
    quotes_duplicate: int
    """Quotes for a key this same payload had already quoted - the later one is ignored."""
    states_offered: int
    states_written: int
    unknown_fixtures: int
    """Live fixtures we have no core.fixtures row for. Not an error: the provider prices competitions we do not
    track. Counted so the number is visible rather than inferred."""
    unmapped_markets_written: int
    """Keys written with market_key NULL. Expected to be most of them: 140 of the 145 in-play markets seen have no
    market of ours."""
    quotes_unchanged: int = 0
    """Quoted exactly as the book already held them: nothing written. About three quarters of every tick."""
    withdrawals_written: int = 0
    """Keys deleted because a fixture this tick observed no longer quotes them."""
    quotes_untracked: int = 0
    """Quotes dropped because their fixture is not one we track - the only reason a quote is dropped, so
    quotes_offered always equals written + unchanged + duplicate + untracked."""
    quotes_inserted: int = 0
    quotes_updated: int = 0


@dataclass(frozen=True, slots=True)
class PurgeResult:
    fixtures: int
    quotes: int


class LiveOddsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def fixture_ids(self, provider_ids: Sequence[int]) -> dict[int, int]:
        if not provider_ids:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT provider_fixture_id, id FROM core.fixtures WHERE provider_fixture_id = ANY(%s)",
                (sorted(set(provider_ids)),),
            )
            return {int(p): int(i) for p, i in cur.fetchall()}

    def current(self, fixture_ids: Sequence[int]) -> dict[LiveKey, CurrentQuote]:
        """What the book holds now for these fixtures - what a new observation is compared against."""
        if not fixture_ids:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT fixture_id, provider_bet_id, selection, line, odds_decimal, is_suspended, market_key "
                "FROM market.live_odds_current WHERE fixture_id = ANY(%s)",
                (sorted(set(fixture_ids)),),
            )
            return {
                (int(f), int(b), str(s), Decimal(line)): CurrentQuote(
                    Decimal(odds), bool(susp), None if mk is None else str(mk))
                for f, b, s, line, odds, susp, mk in cur.fetchall()
            }

    def _known_markets(self) -> set[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT key FROM market.markets")
            return {str(r[0]) for r in cur.fetchall()}

    def write(self, states: Sequence[LiveFixtureState], quotes: Sequence[LiveOddsQuote]) -> LiveWriteResult:
        """Bring the book up to this tick, in the caller's transaction. Writes only what changed."""
        provider_ids = [s.provider_fixture_id for s in states] + [q.provider_fixture_id for q in quotes]
        fixtures = self.fixture_ids(provider_ids)
        markets = self._known_markets()

        state_rows: list[tuple[object, ...]] = []
        unknown: set[int] = set()
        observed: set[int] = set()
        for s in states:
            fid = fixtures.get(s.provider_fixture_id)
            if fid is None:
                unknown.add(s.provider_fixture_id)
                continue
            observed.add(fid)
            state_rows.append((
                fid, s.captured_at, s.captured_at, s.elapsed_minute, s.elapsed_seconds, s.score_home,
                s.score_away, s.status_long, s.is_stopped, s.is_blocked, s.is_finished, s.markets_offered,
                s.values_offered, s.values_suspended, s.provider_updated_at, s.payload_hash,
            ))

        tracked = sorted({fixtures[p] for p in provider_ids if p in fixtures})
        book = self.current(tracked)

        inserts: list[tuple[object, ...]] = []
        updates: list[tuple[object, ...]] = []
        seen: set[LiveKey] = set()
        unmapped = untracked = unchanged = duplicate = 0
        for q in quotes:
            fid = fixtures.get(q.provider_fixture_id)
            if fid is None:
                untracked += 1
                continue
            # An unknown market_key would violate the FK and abort the tick; the provider bet id identifies the
            # market anyway, and the parse log already records that the key was unknown.
            key = q.market_key if q.market_key in markets else None
            identity: LiveKey = (fid, q.provider_bet_id, q.selection, q.line)
            if identity in seen:
                duplicate += 1
                continue
            seen.add(identity)
            before = book.get(identity)
            if before is not None and before.quoted_as == (q.odds_decimal, q.is_suspended):
                unchanged += 1
                continue
            if key is None:
                unmapped += 1
            if before is None:
                inserts.append((
                    fid, q.provider_bet_id, key, q.selection, q.line, q.odds_decimal, q.is_suspended,
                    q.is_main_line, q.captured_at, q.elapsed_minute, q.score_home, q.score_away, q.captured_at,
                ))
                continue
            kind = (("suspended" if q.is_suspended else "available")
                    if before.is_suspended != q.is_suspended else "moved")
            updates.append((
                q.odds_decimal, q.is_suspended, q.is_main_line, key, before.odds, before.is_suspended, kind,
                q.captured_at, q.elapsed_minute, q.score_home, q.score_away,
                fid, q.provider_bet_id, q.selection, q.line,
            ))

        # A key a fixture of this tick no longer quotes has been withdrawn. Only for fixtures this payload
        # observed: one absent from it has not withdrawn its markets, it has left the live book, and its rows go
        # with the purge after STALE_AFTER.
        gone = [k for k in book if k[0] in observed and k not in seen]

        with self._conn.cursor() as cur:
            if state_rows:
                cur.executemany(
                    "INSERT INTO market.live_fixture_current "
                    "(fixture_id, first_seen_at, captured_at, elapsed_minute, elapsed_seconds, score_home, "
                    " score_away, status_long, is_stopped, is_blocked, is_finished, markets_offered, "
                    " values_offered, values_suspended, provider_updated_at, payload_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (fixture_id) DO UPDATE SET captured_at = EXCLUDED.captured_at, "
                    " elapsed_minute = EXCLUDED.elapsed_minute, elapsed_seconds = EXCLUDED.elapsed_seconds, "
                    " score_home = EXCLUDED.score_home, score_away = EXCLUDED.score_away, "
                    " status_long = EXCLUDED.status_long, is_stopped = EXCLUDED.is_stopped, "
                    " is_blocked = EXCLUDED.is_blocked, is_finished = EXCLUDED.is_finished, "
                    " markets_offered = EXCLUDED.markets_offered, values_offered = EXCLUDED.values_offered, "
                    " values_suspended = EXCLUDED.values_suspended, "
                    " provider_updated_at = EXCLUDED.provider_updated_at, payload_hash = EXCLUDED.payload_hash "
                    "WHERE market.live_fixture_current.captured_at <= EXCLUDED.captured_at",
                    state_rows,
                    returning=False,
                )
            if gone:
                cur.execute(
                    "DELETE FROM market.live_odds_current o "
                    "USING unnest(%s::bigint[], %s::int[], %s::text[], %s::numeric[]) AS g(f, b, s, l) "
                    "WHERE o.fixture_id = g.f AND o.provider_bet_id = g.b AND o.selection = g.s AND o.line = g.l",
                    ([k[0] for k in gone], [k[1] for k in gone], [k[2] for k in gone], [k[3] for k in gone]),
                )
            if inserts:
                cur.executemany(
                    "INSERT INTO market.live_odds_current "
                    "(fixture_id, provider_bet_id, market_key, selection, line, odds_decimal, is_suspended, "
                    " is_main_line, change_kind, changed_at, changed_minute, changed_score_home, "
                    " changed_score_away, first_seen_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'offered',%s,%s,%s,%s,%s) "
                    "ON CONFLICT (fixture_id, provider_bet_id, selection, line) DO NOTHING",
                    inserts,
                    returning=False,
                )
            if updates:
                cur.executemany(
                    "UPDATE market.live_odds_current SET odds_decimal = %s, is_suspended = %s, "
                    " is_main_line = %s, market_key = %s, previous_odds = %s, previous_suspended = %s, "
                    " change_kind = %s, changed_at = %s, changed_minute = %s, changed_score_home = %s, "
                    " changed_score_away = %s "
                    "WHERE fixture_id = %s AND provider_bet_id = %s AND selection = %s AND line = %s",
                    updates,
                    returning=False,
                )

        if unknown:
            log.info("live_odds.untracked_fixtures", count=len(unknown))

        return LiveWriteResult(
            quotes_offered=len(quotes),
            quotes_written=len(inserts) + len(updates),
            quotes_duplicate=duplicate,
            states_offered=len(states),
            states_written=len(state_rows),
            unknown_fixtures=len(unknown),
            unmapped_markets_written=unmapped,
            quotes_unchanged=unchanged,
            withdrawals_written=len(gone),
            quotes_untracked=untracked,
            quotes_inserted=len(inserts),
            quotes_updated=len(updates),
        )

    def purge_stale(self, *, at: datetime | None = None, older_than: timedelta = STALE_AFTER) -> PurgeResult:
        """Remove the fixtures the odds feed has not seen for ``older_than``, and every price of theirs.

        Also any price whose fixture row is gone (cannot happen through ``write``; kept so the book can never
        hold a price for a fixture it does not hold). Costs no request; runs every tick, played or not.
        """
        cut = (at or now()) - older_than
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM market.live_fixture_current WHERE captured_at < %s RETURNING fixture_id",
                        (cut,))
            gone = [int(r[0]) for r in cur.fetchall()]
            cur.execute(
                "DELETE FROM market.live_odds_current o WHERE o.fixture_id = ANY(%s) OR NOT EXISTS "
                "(SELECT 1 FROM market.live_fixture_current s WHERE s.fixture_id = o.fixture_id)",
                (gone,),
            )
            quotes = max(0, cur.rowcount or 0)
        if gone or quotes:
            log.info("live_odds.purged", fixtures=len(gone), quotes=quotes)
        return PurgeResult(fixtures=len(gone), quotes=quotes)

    def book_size(self) -> tuple[int, int]:
        """(fixtures, quotes) held right now. Bounded by what is in play at one instant."""
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT (SELECT count(*) FROM market.live_fixture_current), "
                        "(SELECT count(*) FROM market.live_odds_current)")
            row = cur.fetchone()
            return (int(row[0]), int(row[1])) if row else (0, 0)

    def record_live_markets(self, markets: Sequence[LiveMarketSeen]) -> int:
        """Register every in-play bet that was really priced, mapped or not.

        Defers to catalog.provider_markets.record_observed_bets so the catalogue has exactly ONE writer: an
        observation moves last_seen_at and never overwrites a catalogued row's source or its market mapping.
        The catalogue is reference data (one row per bet id, 266 in-play), not a history of prices.
        """
        if not markets:
            return 0
        observed = {(m.provider_bet_id, m.name): m.values for m in markets}
        record_observed_bets(self._conn, observed, scope="inplay")
        return len(observed)

    def changes(
        self, *, provider_fixture_id: int | None = None, mapped_only: bool = True, limit: int = 500
    ) -> list[LiveChange]:
        """The last change of each key still in the book (first quotes excluded), newest first.

        There is no history to read: a key holds only the price it replaced. That is what the Match Center's
        in-play panel shows - which prices moved, by how much, at what minute - while the match is played.
        """
        where = ["o.change_kind <> 'offered'"]
        params: dict[str, object] = {"limit": limit}
        if mapped_only:
            where.append("o.market_key IS NOT NULL")
        if provider_fixture_id is not None:
            where.append("f.provider_fixture_id = %(fx)s")
            params["fx"] = provider_fixture_id
        query = f"""
            SELECT f.provider_fixture_id, o.market_key, o.provider_bet_id, o.selection, o.line,
                   o.previous_odds, o.odds_decimal,
                   CASE WHEN o.change_kind = 'moved'
                        THEN (1.0 / o.odds_decimal - 1.0 / o.previous_odds)::numeric(10,6) END,
                   o.change_kind, o.changed_at, o.changed_minute, o.changed_score_home, o.changed_score_away
            FROM market.live_odds_current o
            JOIN core.fixtures f ON f.id = o.fixture_id
            WHERE {" AND ".join(where)}
            ORDER BY o.changed_at DESC
            LIMIT %(limit)s
        """
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(query, params)
            return [LiveChange(*row) for row in cur.fetchall()]

    def fixtures_in_play(self, *, within_minutes: int) -> int:
        """How many fixtures the odds feed sees in play right now."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM market.live_fixture_current "
                "WHERE captured_at > now() - make_interval(mins => %s) AND COALESCE(is_finished, false) = false",
                (within_minutes,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def market_coverage(self) -> list[tuple[int, str, int, int]]:
        """(bet id, name, fixtures, values) in the book now: which in-play markets the provider is quoting, and
        how widely, without a stored history and without a request."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.provider_bet_id, COALESCE(pm.name, '(uncatalogued)'), count(DISTINCT o.fixture_id), count(*)
                FROM market.live_odds_current o
                LEFT JOIN market.provider_markets pm
                       ON pm.provider = 'api-football' AND pm.scope = 'inplay'
                      AND pm.provider_bet_id = o.provider_bet_id
                GROUP BY 1, 2
                ORDER BY 4 DESC
                """
            )
            return [(int(a), str(b), int(c), int(d)) for a, b, c, d in cur.fetchall()]

    def competition_coverage(self) -> list[tuple[int, str, int]]:
        """(league id, name, fixtures) the odds feed is pricing in play now."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.provider_league_id, c.name, count(*)
                FROM market.live_fixture_current st
                JOIN core.fixtures f ON f.id = st.fixture_id
                JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                JOIN core.competitions c ON c.id = cs.competition_id
                GROUP BY 1, 2
                ORDER BY 3 DESC
                """
            )
            return [(int(a), str(b), int(c)) for a, b, c in cur.fetchall()]
