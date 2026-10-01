"""Persistence for the in-play series. Append only, and separate by construction.

This module writes market.live_odds_snapshots and market.live_fixture_states and
NOTHING else. It cannot write market.odds_snapshots, market.near_close_snapshots
or market.market_consensus, so no in-play price can reach the pre-match series
or the backtest through here - the separation is a property of the code, not a
convention to remember.

Idempotency comes from the schema: captured_at is in the primary key and writes
are ON CONFLICT DO NOTHING, so a re-run can add rows but can never replace a
price. The series is therefore complete by construction - which matters more
here than anywhere else, because /odds/live keeps no history of its own. A price
not stored at the instant it was quoted does not exist anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg
import structlog

from fbi.catalog.provider_markets import record_observed_bets
from fbi.providers.api_football.live import (
    LiveFixtureState,
    LiveMarketSeen,
    LiveOddsQuote,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LiveWriteResult:
    quotes_offered: int
    quotes_written: int
    quotes_duplicate: int
    states_offered: int
    states_written: int
    unknown_fixtures: int
    """Live fixtures we have no core.fixtures row for. Not an error: the provider
    prices competitions we do not track. Counted so the number is visible rather
    than inferred from a gap in the series."""
    unmapped_markets_written: int
    """Rows stored with market_key NULL. Expected to be most of them."""
    quotes_untracked: int = 0
    """Quotes dropped because their fixture is not one we track. The provider
    prices competitions outside our 122, and this is the only reason a quote is
    dropped here - so quotes_offered always equals written + duplicate +
    untracked, and a gap in the series can never be left unexplained."""


class LiveOddsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def fixture_ids(self, provider_ids: Sequence[int]) -> dict[int, int]:
        if not provider_ids:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT provider_fixture_id, id FROM core.fixtures "
                "WHERE provider_fixture_id = ANY(%s)",
                (sorted(set(provider_ids)),),
            )
            return {int(p): int(i) for p, i in cur.fetchall()}

    def _known_markets(self) -> set[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT key FROM market.markets")
            return {str(r[0]) for r in cur.fetchall()}

    def write(
        self,
        states: Sequence[LiveFixtureState],
        quotes: Sequence[LiveOddsQuote],
    ) -> LiveWriteResult:
        """One capture's states and prices, in the caller's transaction."""
        provider_ids = [s.provider_fixture_id for s in states] + [
            q.provider_fixture_id for q in quotes
        ]
        fixtures = self.fixture_ids(provider_ids)
        markets = self._known_markets()

        state_rows = []
        unknown: set[int] = set()
        for s in states:
            fid = fixtures.get(s.provider_fixture_id)
            if fid is None:
                unknown.add(s.provider_fixture_id)
                continue
            state_rows.append(
                (
                    fid, s.captured_at, s.elapsed_minute, s.elapsed_seconds,
                    s.score_home, s.score_away, s.status_long, s.is_stopped,
                    s.is_blocked, s.is_finished, s.markets_offered,
                    s.values_offered, s.values_suspended, s.provider_updated_at,
                    s.payload_hash,
                )
            )

        quote_rows = []
        unmapped = untracked = 0
        for q in quotes:
            fid = fixtures.get(q.provider_fixture_id)
            if fid is None:
                untracked += 1
                continue
            # An unknown market_key would violate the FK and abort the whole
            # capture. Storing it as NULL keeps the row - the provider bet id is
            # what makes the series usable anyway - and the parse log already
            # records that the key was unknown.
            key = q.market_key if q.market_key in markets else None
            if key is None:
                unmapped += 1
            quote_rows.append(
                (
                    fid, q.provider_bet_id, key, q.selection, q.line,
                    q.odds_decimal, q.is_suspended, q.is_main_line,
                    q.elapsed_minute, q.elapsed_seconds, q.score_home,
                    q.score_away, q.status_long, q.is_stopped, q.is_blocked,
                    q.provider_updated_at, q.captured_at, q.payload_hash,
                )
            )

        states_written = quotes_written = 0
        with self._conn.cursor() as cur:
            if state_rows:
                cur.executemany(
                    "INSERT INTO market.live_fixture_states "
                    "(fixture_id,captured_at,elapsed_minute,elapsed_seconds,"
                    " score_home,score_away,status_long,is_stopped,is_blocked,"
                    " is_finished,markets_offered,values_offered,values_suspended,"
                    " provider_updated_at,payload_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    state_rows,
                    returning=False,
                )
                states_written = max(0, cur.rowcount or 0)
            if quote_rows:
                cur.executemany(
                    "INSERT INTO market.live_odds_snapshots "
                    "(fixture_id,provider_bet_id,market_key,selection,line,"
                    " odds_decimal,is_suspended,is_main_line,elapsed_minute,"
                    " elapsed_seconds,score_home,score_away,status_long,"
                    " is_stopped,is_blocked,provider_updated_at,captured_at,"
                    " payload_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    quote_rows,
                    returning=False,
                )
                quotes_written = max(0, cur.rowcount or 0)

        if unknown:
            log.info("live_odds.untracked_fixtures", count=len(unknown))

        return LiveWriteResult(
            quotes_offered=len(quotes),
            quotes_written=quotes_written,
            quotes_duplicate=max(0, len(quote_rows) - quotes_written),
            states_offered=len(states),
            states_written=states_written,
            unknown_fixtures=len(unknown),
            unmapped_markets_written=unmapped,
            quotes_untracked=untracked,
        )

    def record_live_markets(self, markets: Sequence[LiveMarketSeen]) -> int:
        """Register every in-play bet that was really priced, mapped or not.

        Defers to catalog.provider_markets.record_observed_bets so the
        catalogue has exactly ONE writer. That function's policy is deliberate
        and is kept: an observation moves last_seen_at and never overwrites a
        catalogued row's source or its market mapping, because seeing a bet
        confirms it - it does not unmap it.

        Nothing about HOW MUCH a market was seen is stored here. The catalogues
        are already separate rows - scope 'inplay' holds the 266 in-play bets,
        scope 'prematch' the 338 pre-match ones, so bet 4 is "Asian Handicap"
        in one and "Extra Time Total Corners (3 Ways) (1st Half)" in the other
        and the two can never be read as one. Which of them the provider
        actually quotes, on how many fixtures, is answered by market_coverage()
        straight from the series. A stored count would be a second copy of a
        fact that then has to agree with the first, which is the shape of every
        defect this project has had to repair.
        """
        if not markets:
            return 0
        observed = {(m.provider_bet_id, m.name): m.values for m in markets}
        record_observed_bets(self._conn, observed, scope="inplay")
        return len(observed)

    def fixtures_in_play(self, *, within_minutes: int) -> int:
        """How many fixtures the recent captures saw in play. Feeds the cadence."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT count(DISTINCT fixture_id) FROM market.live_fixture_states "
                "WHERE captured_at > now() - make_interval(mins => %s) "
                "  AND COALESCE(is_finished, false) = false",
                (within_minutes,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def market_coverage(self, *, since_hours: int = 24) -> list[tuple[int, str, int, int]]:
        """(bet id, name, fixtures, values) from the series itself.

        Answers 'which in-play markets does this provider really offer, and how
        widely' without a second stored copy and without spending a request.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.provider_bet_id,
                       COALESCE(pm.name, '(uncatalogued)'),
                       count(DISTINCT s.fixture_id),
                       count(*)
                FROM market.live_odds_snapshots s
                LEFT JOIN market.provider_markets pm
                       ON pm.provider = 'api-football'
                      AND pm.scope = 'inplay'
                      AND pm.provider_bet_id = s.provider_bet_id
                WHERE s.captured_at > now() - make_interval(hours => %s)
                GROUP BY 1, 2
                ORDER BY 4 DESC
                """,
                (since_hours,),
            )
            return [(int(a), str(b), int(c), int(d)) for a, b, c, d in cur.fetchall()]

    def competition_coverage(self, *, since_hours: int = 24) -> list[tuple[int, str, int]]:
        """(league id, name, fixtures seen in play). Coverage by competition,
        measured from what arrived rather than assumed from the plan."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.provider_league_id, l.name, count(DISTINCT st.fixture_id)
                FROM market.live_fixture_states st
                JOIN core.fixtures f ON f.id = st.fixture_id
                JOIN core.seasons se ON se.id = f.season_id
                JOIN core.leagues l ON l.id = se.league_id
                WHERE st.captured_at > now() - make_interval(hours => %s)
                GROUP BY 1, 2
                ORDER BY 3 DESC
                """,
                (since_hours,),
            )
            return [(int(a), str(b), int(c)) for a, b, c in cur.fetchall()]
