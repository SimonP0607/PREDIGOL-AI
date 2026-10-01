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

ONLY CHANGES ARE WRITTEN
------------------------
The provider sweeps its whole live book about every 31 s and only ~27% of prices
move per sweep. Measured over 36,952 rows written the old way, 26,934 of them
(72.9%) were a second copy of a number already held. At 293 bytes a row that is
140 GB a year of repetition.

So a row is written when (price, suspended, offered) differs from the last row
for that key, and not otherwise. Three transition kinds, with their measured
counts over those same 36,952 rows:

    a price moved, or its suspension flipped   8,786
    a selection was quoted for the first time    772
    a selection stopped being quoted           1,000   -> odds_decimal NULL
    a selection returned after being withdrawn   482
    --------------------------------------------------
    rows a change-only writer keeps            11,040   (3.35x fewer)

The withdrawal rows are what make it lossless. Carrying a value forward is only
correct while the provider is still quoting it, and markets vanish between
sweeps - one measured cycle dropped 325 values. Without recording that,
reconstruction would report a price for a market that had gone, which is
inventing data.

market.live_odds_at_instant rebuilds the full-fidelity series from these rows
and market.live_fixture_states, which records every instant observed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.catalog.provider_markets import record_observed_bets
from fbi.providers.api_football.live import (
    LiveFixtureState,
    LiveMarketSeen,
    LiveOddsQuote,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LiveMovement:
    """One observed in-play price change, with the match state around it.

    Field order matches the SELECT in ``LiveOddsRepository.movements``.
    """

    provider_fixture_id: int
    market_key: str | None
    provider_bet_id: int
    selection: str
    line: Decimal
    previous_odds: Decimal
    odds: Decimal
    implied_prob_delta: Decimal
    """Change in implied probability, which is the number that means something:
    2.00 -> 1.90 is a far bigger move than 10.0 -> 9.90, and the raw odds delta
    says the opposite."""
    seconds_elapsed: Decimal
    previous_at: datetime
    captured_at: datetime
    elapsed_minute: int | None
    score_home: int | None
    score_away: int | None
    score_changed: bool
    """A goal fell between the two observations - the explanation for most large
    moves, and the reason the score rides on every snapshot row."""
    became_suspended: bool
    became_available: bool


LiveKey = tuple[int, int, str, Decimal]
"""(provider_bet_id, ... ) is not enough on its own: the key is
(fixture_id, provider_bet_id, selection, line), which is the primary key of the
series minus its instant."""

@dataclass(frozen=True, slots=True)
class LastState:
    """What was last recorded for one key of the live series."""

    odds: Decimal | None
    """None means the last thing recorded for this key was a withdrawal."""
    is_suspended: bool
    market_key: str | None
    """Carried so a withdrawal row can still say which market was withdrawn.
    Without it the movement view cannot filter withdrawals by market, and a
    reader asking "what happened to the handicap" gets a row with a NULL
    market_key and no way to tell."""

    @property
    def quoted_as(self) -> tuple[Decimal | None, bool]:
        """The part a new observation is compared against. Deliberately not the
        whole object: market_key is identity, not state, and a change in it
        would be a catalogue change rather than a price movement."""
        return (self.odds, self.is_suspended)


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
    quotes_unchanged: int = 0
    """Quotes whose price and suspension matched the last row for their key, so
    no row was written. Expected to be about three quarters of them - that is
    the whole point - and counted so the saving is visible rather than assumed."""
    withdrawals_written: int = 0
    """Keys that stopped being quoted. Recorded with odds_decimal NULL, because
    carrying a withdrawn price forward would invent a quote."""
    quotes_untracked: int = 0
    """Quotes dropped because their fixture is not one we track. The provider
    prices competitions outside our 122, and this is the only reason a quote is
    dropped here - so quotes_offered always equals written + duplicate +
    untracked, and a gap in the series can never be left unexplained."""


def _withdrawal_rows(
    states: Sequence[LiveFixtureState],
    fixtures: dict[int, int],
    last: dict[LiveKey, LastState],
    seen: set[LiveKey],
) -> list[tuple[object, ...]]:
    """A row with a NULL price for every key that was quoted and no longer is.

    Only for fixtures this capture actually observed. A fixture absent from the
    payload has not withdrawn its markets - it has simply finished, or dropped
    out of the live book - and inventing withdrawal rows for it would put a
    timestamp on an event that was never seen. The last price stands as the last
    thing known, which is the truth.

    1,000 of these were needed across 36,952 measured rows: 2.7% of the volume,
    and the difference between a series that can be replayed and one that lies
    about markets that had gone.
    """
    rows: list[tuple[object, ...]] = []
    for s in states:
        fid = fixtures.get(s.provider_fixture_id)
        if fid is None:
            continue
        for identity, before in last.items():
            if identity[0] != fid or identity in seen or before.odds is None:
                continue
            _f, bet_id, selection, line = identity
            rows.append(
                (
                    fid, bet_id, before.market_key, selection, line,
                    None,                      # the withdrawal itself
                    False, None,
                    s.elapsed_minute, s.elapsed_seconds, s.score_home,
                    s.score_away, s.status_long, s.is_stopped, s.is_blocked,
                    s.provider_updated_at, s.captured_at, s.payload_hash,
                )
            )
    return rows


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

    def last_known(
        self, fixture_ids: Sequence[int], *, within_hours: int = 4
    ) -> dict[LiveKey, LastState]:
        """The most recent (price, suspended) recorded for every key of these
        fixtures, which is what a new observation has to be compared against.

        Served by the primary key index - (fixture_id, provider_bet_id,
        selection, line, captured_at) is exactly the DISTINCT ON order - so one
        query per tick costs a few milliseconds even with fifty fixtures live.

        ``within_hours`` bounds the scan to the current match. Reading past it
        is safe in the only direction that matters: a key whose last state is
        older than the window is treated as new and gets a row written, which is
        a repetition, never a wrong answer.
        """
        if not fixture_ids:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (fixture_id, provider_bet_id, selection, line)
                       fixture_id, provider_bet_id, selection, line,
                       odds_decimal, is_suspended, market_key
                FROM market.live_odds_snapshots
                WHERE fixture_id = ANY(%s)
                  AND captured_at > now() - make_interval(hours => %s)
                ORDER BY fixture_id, provider_bet_id, selection, line,
                         captured_at DESC
                """,
                (sorted(set(fixture_ids)), within_hours),
            )
            return {
                (int(f), int(b), str(s), Decimal(line)): LastState(
                    None if odds is None else Decimal(odds),
                    bool(susp),
                    None if mk is None else str(mk),
                )
                for f, b, s, line, odds, susp, mk in cur.fetchall()
            }

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

        # What is already on record for these fixtures, so only changes are kept.
        tracked = [fixtures[p] for p in set(provider_ids) if p in fixtures]
        last = self.last_known(tracked)

        quote_rows: list[tuple[object, ...]] = []
        unmapped = untracked = unchanged = 0
        seen: set[LiveKey] = set()
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

            identity: LiveKey = (fid, q.provider_bet_id, q.selection, q.line)
            seen.add(identity)
            before = last.get(identity)
            if before is not None and before.quoted_as == (
                q.odds_decimal, q.is_suspended
            ):
                unchanged += 1
                continue

            quote_rows.append(
                (
                    fid, q.provider_bet_id, key, q.selection, q.line,
                    q.odds_decimal, q.is_suspended, q.is_main_line,
                    q.elapsed_minute, q.elapsed_seconds, q.score_home,
                    q.score_away, q.status_long, q.is_stopped, q.is_blocked,
                    q.provider_updated_at, q.captured_at, q.payload_hash,
                )
            )

        # A key that was being quoted and is not in this payload has been
        # withdrawn. Recording it is what lets a reader carry the other prices
        # forward without inventing a quote for this one.
        withdrawals = _withdrawal_rows(states, fixtures, last, seen)
        quote_rows.extend(withdrawals)

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
            quotes_unchanged=unchanged,
            withdrawals_written=len(withdrawals),
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

    def movements(
        self,
        *,
        provider_fixture_id: int | None = None,
        mapped_only: bool = True,
        since_minutes: int = 180,
        limit: int = 500,
    ) -> list[LiveMovement]:
        """Observed in-play price changes, newest first.

        Reads market.live_market_movement, which is a VIEW over the snapshot
        series: movement is the difference between two rows of an append-only
        table, so it is derived on demand rather than stored. A stored copy
        would have to agree with the series it came from, and every defect this
        project has repaired was two copies of a fact with nothing forcing them
        to agree.
        """
        where = ["m.captured_at > now() - make_interval(mins => %(mins)s)"]
        params: dict[str, object] = {"mins": since_minutes, "limit": limit}
        if mapped_only:
            where.append("m.market_key IS NOT NULL")
        if provider_fixture_id is not None:
            where.append("f.provider_fixture_id = %(fx)s")
            params["fx"] = provider_fixture_id
        sql = f"""
            SELECT f.provider_fixture_id, m.market_key, m.provider_bet_id,
                   m.selection, m.line, m.previous_odds, m.odds,
                   m.implied_prob_delta, m.seconds_elapsed,
                   m.previous_at, m.captured_at,
                   m.elapsed_minute, m.score_home, m.score_away,
                   m.score_changed, m.became_suspended, m.became_available
            FROM market.live_market_movement m
            JOIN core.fixtures f ON f.id = m.fixture_id
            WHERE {" AND ".join(where)}
            ORDER BY m.captured_at DESC, abs(m.implied_prob_delta) DESC
            LIMIT %(limit)s
        """
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(sql, params)
            return [LiveMovement(*row) for row in cur.fetchall()]

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
                SELECT c.provider_league_id, c.name, count(DISTINCT st.fixture_id)
                FROM market.live_fixture_states st
                JOIN core.fixtures f ON f.id = st.fixture_id
                JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                JOIN core.competitions c ON c.id = cs.competition_id
                WHERE st.captured_at > now() - make_interval(hours => %s)
                GROUP BY 1, 2
                ORDER BY 3 DESC
                """,
                (since_hours,),
            )
            return [(int(a), str(b), int(c)) for a, b, c in cur.fetchall()]
