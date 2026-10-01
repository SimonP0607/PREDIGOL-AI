"""Read /odds/live payloads. A separate namespace from pre-match, on purpose.

WHAT THE PROVIDER ACTUALLY SENDS, MEASURED 2026-10-01
-----------------------------------------------------
One unfiltered /odds/live call, 8 fixtures, 7 competitions, 72 distinct bet ids,
1,933 values. Per fixture::

    {"fixture": {"id": 1490500, "status": {"long": "Second Half",
                                           "elapsed": 77, "seconds": "77:00"}},
     "league":  {"id": 253, "season": 2026},
     "teams":   {"home": {"id": 1602, "goals": 0}, "away": {...}},
     "status":  {"stopped": false, "blocked": false, "finished": false},
     "update":  "2026-10-01T01:14:30+00:00",
     "odds":    [{"id": 59, "name": "Fulltime Result", "values": [...]}, ...]}

There is NO bookmaker dimension - no fixture carried a ``bookmakers`` key. A
live price is the provider's single aggregated number, which is why these rows
live in market.live_odds_snapshots and not in market.odds_snapshots.

THE HANDICAP IS SIGNED PER SELECTION HERE. PRE-MATCH IT IS NOT.
---------------------------------------------------------------
Pre-match repeats the home team's handicap on both rows of an Asian Handicap
pair, so normalize._selection() negates the away row. Live sends the handicap
that applies to the selection named::

    {"value": "Home", "handicap": "-0.75", "odd": "1.90"}
    {"value": "Away", "handicap":  "0.75", "odd": "1.98"}

Settled by measurement, the same way the pre-match sign was settled - pair the
rows each way and devig:

    away handicap already negated   40 pairs, overround 1.0528 .. 1.0827
    away handicap repeats the home   7 pairs, overround 0.8413 .. 1.2937

Only the first reading produces a plausible book on every pair; the second
forms barely any pairs and yields overrounds below 1.0, which would be free
money. So live rows are stored AS SENT and the pre-match negation is NOT
applied here. Reusing normalize._selection() for live would have flipped the
sign on every away line in the series.

VALUES THAT ARE NOT PRICES
--------------------------
57 of the 1,933 values were at or below 1.0: 56 of them ``"odd": "0"`` and
``suspended: true``, plus one Double Chance leg at exactly 1.00 and not
suspended. Zero is not a price - it is the provider declining to quote - and
market.live_odds_snapshots CHECKs odds_decimal > 1.0. Those values are refused
into the parse log and counted in the fixture state's ``values_suspended``,
never stored as a quote and never coerced to a number we invented.

A suspended value that still carries a real price (210 of the 1,933) IS stored,
with is_suspended = true: that is how the series shows a market freezing and
what it reopened at.

Of the 72 bet ids seen, 5 map to markets we model. The other 67 are in-play
only (Match Corners, Race to the 9th Corner, Last Team to Score, Anytime Goal
Scorer) and are stored with market_key NULL and the provider's own selection
text. /odds/live keeps no history, so a value not stored at capture time is
gone for good - dropping an unmapped market would be an unrecoverable loss.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from fbi.domain.market import MarketLine, MarketType, Selection, Side
from fbi.providers.api_football.normalize import (
    INPLAY_BETS,
    MAX_ODDS,
    MIN_ODDS,
    _same_name,
    _to_decimal,
)
from fbi.providers.base import OddsParseLog

__all__ = [
    "LIVE_SELECTION_ALIASES",
    "LiveFixtureState",
    "LiveMarketSeen",
    "LiveOddsQuote",
    "iter_live_odds",
    "live_market_of",
    "normalise_live_selection",
]

log = structlog.get_logger(__name__)

LIVE_LINED_MARKETS = frozenset({"AH", "OU"})

LIVE_SELECTION_ALIASES: dict[str, dict[str, Side]] = {
    "1X2": {"home": Side.HOME, "draw": Side.DRAW, "away": Side.AWAY},
    "BTTS": {"yes": Side.YES, "no": Side.NO},
    "DC": {
        # The live vocabulary differs from pre-match's "Home/Draw". Both spellings
        # are accepted so neither catalogue can starve the other, but the live
        # wording is what was measured.
        "home or draw": Side.HOME_OR_DRAW,
        "away or draw": Side.DRAW_OR_AWAY,
        "home or away": Side.HOME_OR_AWAY,
        "draw or away": Side.DRAW_OR_AWAY,
        "home/draw": Side.HOME_OR_DRAW,
        "draw/away": Side.DRAW_OR_AWAY,
        "home/away": Side.HOME_OR_AWAY,
    },
    "OU": {"over": Side.OVER, "under": Side.UNDER},
    "AH": {"home": Side.HOME, "away": Side.AWAY},
}

MAX_SELECTION_TEXT = 120
"""Unmapped selections keep the provider's words. Long enough for the longest
observed ("Race To 9th Corner - Away"), short enough that a payload change
cannot write unbounded text into the primary key."""


@dataclass(frozen=True, slots=True)
class LiveOddsQuote:
    """One in-play price, as observed. Append-only: never updated in place."""

    provider_fixture_id: int
    provider_bet_id: int
    market_key: str | None
    selection: str
    line: Decimal
    odds_decimal: Decimal
    is_suspended: bool
    is_main_line: bool | None
    elapsed_minute: int | None
    elapsed_seconds: str | None
    score_home: int | None
    score_away: int | None
    status_long: str | None
    is_stopped: bool | None
    is_blocked: bool | None
    provider_updated_at: datetime | None
    captured_at: datetime
    payload_hash: str


@dataclass(slots=True)
class LiveFixtureState:
    """What the capture saw happening, kept apart from the prices."""

    provider_fixture_id: int
    captured_at: datetime
    payload_hash: str
    provider_league_id: int | None = None
    season: int | None = None
    elapsed_minute: int | None = None
    elapsed_seconds: str | None = None
    score_home: int | None = None
    score_away: int | None = None
    status_long: str | None = None
    is_stopped: bool | None = None
    is_blocked: bool | None = None
    is_finished: bool | None = None
    markets_offered: int = 0
    values_offered: int = 0
    values_suspended: int = 0
    provider_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LiveMarketSeen:
    """A bet id the provider actually priced live, for the LIVE_MARKETS catalogue.

    The in-play catalogue at /odds/live/bets lists 266 entries; 72 were seen
    carrying real prices. Recording what was observed - not what was listed -
    is what tells an available market from a theoretical one.
    """

    provider_bet_id: int
    name: str
    fixtures: int
    values: int


def live_market_of(bet_id: int) -> str | None:
    """Our market key for an in-play bet id, or None when we do not model it.

    Deliberately consults INPLAY_BETS only. Pre-match bet 4 is Asian Handicap;
    in-play bet 4 is "Extra Time Total Corners (3 Ways) (1st Half)". One shared
    id map would file corner prices as our handicap series.
    """
    for key, bet in INPLAY_BETS.items():
        if bet.bet_id == bet_id:
            return key
    return None


def normalise_live_selection(
    market_key: str, raw_value: str, handicap: Any
) -> Selection | None:
    """The provider's live words turned into a domain Selection.

    The handicap arrives in its own field, already signed for the selection
    named (measured; see the module docstring), so it is used as sent.
    """
    try:
        market = MarketType(market_key)
    except ValueError:
        return None
    side = LIVE_SELECTION_ALIASES.get(market_key, {}).get(raw_value.strip().lower())
    if side is None:
        return None

    if market_key not in LIVE_LINED_MARKETS:
        if handicap is not None:
            return None  # a lineless market that grew a line is a catalogue change
        return Selection(market, side)

    line = _to_decimal(handicap)
    if line is None:
        return None
    try:
        return Selection(market, side, MarketLine(line))
    except Exception:
        return None


def iter_live_odds(
    body: dict[str, Any],
    *,
    captured_at: datetime,
    payload_hash: str,
    parse_log: OddsParseLog | None = None,
) -> tuple[list[LiveFixtureState], list[LiveOddsQuote], list[LiveMarketSeen]]:
    """Read one /odds/live payload into states, quotes and observed markets.

    Returns every fixture seen in play - including one priced with no readable
    value at all, so "was it live?" can be answered without the prices.
    """
    states: list[LiveFixtureState] = []
    quotes: list[LiveOddsQuote] = []
    seen_markets: dict[int, _MarketTally] = {}

    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        state = _state_of(entry, captured_at=captured_at, payload_hash=payload_hash)
        if state is None:
            continue
        bets = entry.get("odds")
        bets = bets if isinstance(bets, list) else []
        state.markets_offered = len(bets)

        for bet in bets:
            if not isinstance(bet, dict):
                continue
            bet_id = bet.get("id")
            if not isinstance(bet_id, int):
                continue
            bet_name = _text(bet.get("name"))
            market_key = live_market_of(bet_id)
            if market_key is not None:
                expected = INPLAY_BETS[market_key].name
                if bet_name and not _same_name(bet_name, expected):
                    # The id moved under us. Refuse rather than relabel: the whole
                    # point of two catalogues is that ids are not interchangeable.
                    log.warning(
                        "live_odds.bet_renamed",
                        bet_id=bet_id,
                        expected=expected,
                        got=bet_name,
                    )
                    if parse_log is not None:
                        parse_log.renamed_bets.append((bet_id, expected, bet_name))
                    market_key = None

            values = bet.get("values")
            values = values if isinstance(values, list) else []
            tally = seen_markets.setdefault(bet_id, _MarketTally(bet_name))
            tally.fixtures.add(state.provider_fixture_id)

            for value in values:
                if not isinstance(value, dict):
                    continue
                state.values_offered += 1
                tally.values += 1
                suspended = value.get("suspended") is True
                if suspended:
                    state.values_suspended += 1
                quote = _quote(
                    value=value,
                    bet_id=bet_id,
                    bet_name=bet_name,
                    market_key=market_key,
                    state=state,
                    suspended=suspended,
                    captured_at=captured_at,
                    payload_hash=payload_hash,
                    parse_log=parse_log,
                )
                if quote is not None:
                    quotes.append(quote)

        states.append(state)

    markets = [
        LiveMarketSeen(bet_id, t.name, len(t.fixtures), t.values)
        for bet_id, t in sorted(seen_markets.items())
    ]
    return states, quotes, markets


@dataclass(slots=True)
class _MarketTally:
    name: str
    fixtures: set[int] = field(default_factory=set)
    values: int = 0


def _state_of(
    entry: dict[str, Any], *, captured_at: datetime, payload_hash: str
) -> LiveFixtureState | None:
    fixture = _dict(entry.get("fixture"))
    if not isinstance(fixture.get("id"), int):
        return None
    status = _dict(fixture.get("status"))
    flags = _dict(entry.get("status"))
    teams = _dict(entry.get("teams"))
    league = _dict(entry.get("league"))

    return LiveFixtureState(
        provider_fixture_id=int(fixture["id"]),
        captured_at=captured_at,
        payload_hash=payload_hash,
        provider_league_id=_int_or_none(league.get("id")),
        season=_int_or_none(league.get("season")),
        elapsed_minute=_non_negative(status.get("elapsed")),
        elapsed_seconds=_text(status.get("seconds")) or None,
        score_home=_non_negative(_goals(teams.get("home"))),
        score_away=_non_negative(_goals(teams.get("away"))),
        status_long=_text(status.get("long")) or None,
        is_stopped=_bool_or_none(flags.get("stopped")),
        is_blocked=_bool_or_none(flags.get("blocked")),
        is_finished=_bool_or_none(flags.get("finished")),
        provider_updated_at=_timestamp(entry.get("update")),
    )


def _quote(
    *,
    value: dict[str, Any],
    bet_id: int,
    bet_name: str,
    market_key: str | None,
    state: LiveFixtureState,
    suspended: bool,
    captured_at: datetime,
    payload_hash: str,
    parse_log: OddsParseLog | None,
) -> LiveOddsQuote | None:
    raw_value = value.get("value")
    if not isinstance(raw_value, str) or not raw_value.strip():
        if parse_log is not None:
            parse_log.refuse(market_key or f"bet:{bet_id}", repr(raw_value), "no selection")
        return None
    handicap = value.get("handicap")

    selection_text: str
    line: Decimal
    if market_key is not None:
        selection = normalise_live_selection(market_key, raw_value, handicap)
        if selection is None:
            if parse_log is not None:
                parse_log.refuse(
                    market_key,
                    f"{raw_value} @ handicap={handicap!r}",
                    "not a selection of this market",
                )
            return None
        selection_text = selection.side.value
        line = selection.line_for_storage
    else:
        # Unmapped: the provider's own words, so the series stays readable and
        # can be normalised later from what we stored.
        if parse_log is not None:
            parse_log.unmapped_bets[(bet_id, bet_name)] += 1
        selection_text = raw_value.strip()[:MAX_SELECTION_TEXT]
        parsed = _to_decimal(handicap)
        line = parsed if parsed is not None else Decimal(0)

    odds = _to_decimal(value.get("odd"))
    if odds is None or not (MIN_ODDS <= odds <= MAX_ODDS):
        # "odd": "0" on a suspended value means the provider is not quoting.
        # It is counted in the state, never stored as if it were a price.
        if parse_log is not None:
            parse_log.refuse(
                market_key or f"bet:{bet_id}",
                f"{raw_value} @ {value.get('odd')!r}",
                "suspended with no price" if suspended else "odds out of range",
            )
        return None

    return LiveOddsQuote(
        provider_fixture_id=state.provider_fixture_id,
        provider_bet_id=bet_id,
        market_key=market_key,
        selection=selection_text,
        line=line,
        odds_decimal=odds,
        is_suspended=suspended,
        is_main_line=_bool_or_none(value.get("main")),
        elapsed_minute=state.elapsed_minute,
        elapsed_seconds=state.elapsed_seconds,
        score_home=state.score_home,
        score_away=state.score_away,
        status_long=state.status_long,
        is_stopped=state.is_stopped,
        is_blocked=state.is_blocked,
        provider_updated_at=state.provider_updated_at,
        captured_at=captured_at,
        payload_hash=payload_hash,
    )


def _dict(value: Any) -> dict[str, Any]:
    """A payload sub-object, or an empty one. Missing keys then read as absent
    rather than raising, which is how a payload that loses a block degrades to
    NULLs instead of losing the whole fixture."""
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _goals(team: Any) -> Any:
    return _dict(team).get("goals")


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _non_negative(value: Any) -> int | None:
    n = _int_or_none(value)
    return n if n is not None and n >= 0 else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def mapped_quotes(quotes: Iterable[LiveOddsQuote]) -> list[LiveOddsQuote]:
    """The subset carrying a market we model. Live intelligence reads these;
    the rest are kept because /odds/live has no history to go back to."""
    return [q for q in quotes if q.market_key is not None]
