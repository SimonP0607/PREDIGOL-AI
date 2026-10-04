"""Turn API-Football JSON into provider-agnostic DTOs.

Everything here is defensive. The legacy system trusted the payload shape and
paid for it: ``_parse_avg`` fell back to the SEASON TOTAL when the average was
missing, producing expected_goals of 108.0, 94.0, 90.0, 55.0 and 15.0 goals per
match - values that then drove the Over/Under heuristic for months without
anybody noticing.

The rule that follows from that: a value that cannot be parsed is DROPPED and
counted, never substituted with a plausible-looking neighbour.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from fbi.core.errors import InvalidSelectionError
from fbi.domain.market import MarketLine, MarketType, Selection, Side
from fbi.providers.base import (
    FixtureRef,
    FixtureResultRef,
    OddsParseLog,
    OddsQuote,
    OddsSource,
    SeasonRef,
)

__all__ = [
    "BETS_BY_SOURCE",
    "CANONICAL_STATUSES",
    "INPLAY_BETS",
    "PREMATCH_BETS",
    "OddsParseLog",
    "ProviderBet",
    "canonical_status",
    "iter_fixture_results",
    "iter_fixtures",
    "iter_league_seasons",
    "iter_odds",
    "minutes_to_kickoff",
]

log = structlog.get_logger(__name__)

# API-Football bet ids -> our market keys.
#
# PRE-MATCH AND IN-PLAY ARE DIFFERENT NAMESPACES. Measured from the provider's
# own two catalogues: pre-match bet 4 is "Asian Handicap"; IN-PLAY bet 4 is
# "Extra Time Total Corners (3 Ways) (1st Half)". In-play bet 5 is "Extra Time
# Double Result", not "Goals Over/Under". One shared id map would therefore have
# stored extra-time corner prices as our Over/Under series the first time
# /odds/live ran - and /odds/live had never run, so nothing had caught it.
#
# The map is chosen by ``source``, and the provider's own ``name`` in the payload
# is checked against the catalogue name before a bet is accepted. A rename or a
# renumbering on the provider's side therefore refuses the bet and is recorded,
# rather than quietly relabelling prices.


@dataclass(frozen=True, slots=True)
class ProviderBet:
    bet_id: int
    name: str


PREMATCH_BETS: dict[str, ProviderBet] = {
    "1X2": ProviderBet(1, "Match Winner"),
    "AH": ProviderBet(4, "Asian Handicap"),
    "OU": ProviderBet(5, "Goals Over/Under"),
    "BTTS": ProviderBet(8, "Both Teams Score"),
    "DC": ProviderBet(12, "Double Chance"),
}
"""Verified against 22 real /odds payloads in our raw store."""

INPLAY_BETS: dict[str, ProviderBet] = {
    "1X2": ProviderBet(59, "Fulltime Result"),
    "AH": ProviderBet(33, "Asian Handicap"),
    "OU": ProviderBet(36, "Over/Under Line"),
    "BTTS": ProviderBet(69, "Both Teams to Score"),
    "DC": ProviderBet(72, "Double Chance"),
}
"""Taken from /odds/live/bets (266 entries, results=266, no errors).

No real /odds/live PRICE payload has been observed yet, so these ids are
corroborated by the catalogue name alone. Two gates stand behind them: the name
check below, and the selection parser, which only accepts "Over 2.5"-shaped
values for OU and "Home -0.25"-shaped ones for AH. A mislabelled bet therefore
produces refusals in the parse log, never rows in the odds series."""

BETS_BY_SOURCE: dict[str, dict[str, ProviderBet]] = {
    "prematch": PREMATCH_BETS,
    "live": INPLAY_BETS,
}


def _bet_index(source: str) -> dict[int, ProviderBet]:
    bets = BETS_BY_SOURCE[source]
    return {bet.bet_id: bet for bet in bets.values()}


def _market_of(source: str, bet_id: int) -> str | None:
    for key, bet in BETS_BY_SOURCE[source].items():
        if bet.bet_id == bet_id:
            return key
    return None


def _same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


SELECTION_ALIASES: dict[str, dict[str, Side]] = {
    "1X2": {"home": Side.HOME, "draw": Side.DRAW, "away": Side.AWAY,
            "1": Side.HOME, "x": Side.DRAW, "2": Side.AWAY},
    "BTTS": {"yes": Side.YES, "no": Side.NO},
    "DC": {"home/draw": Side.HOME_OR_DRAW, "home/away": Side.HOME_OR_AWAY,
           "draw/away": Side.DRAW_OR_AWAY, "1x": Side.HOME_OR_DRAW,
           "12": Side.HOME_OR_AWAY, "x2": Side.DRAW_OR_AWAY},
    "OU": {"over": Side.OVER, "under": Side.UNDER},
    "AH": {"home": Side.HOME, "away": Side.AWAY, "1": Side.HOME, "2": Side.AWAY},
}

LINED_MARKETS = frozenset({"OU", "AH"})

MIN_ODDS = Decimal("1.001")
MAX_ODDS = Decimal("999.999")

def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return d


def _split_line(raw_value: str) -> tuple[str, Decimal] | None:
    """Split 'Over 2.5' into ('Over', 2.5) and 'Home -0.25' into ('Home', -0.25).

    Returns None when the line is unreadable - never a default of 0, which
    would silently merge every line of the market into one.
    """
    parts = raw_value.strip().rsplit(" ", 1)
    if len(parts) != 2:
        return None
    side, line = parts[0].strip(), _to_decimal(parts[1])
    if not side or line is None:
        return None
    return side, line


def _selection(market_key: str, raw_value: str) -> Selection | None:
    """The provider's words turned into a domain Selection, once, here.

    Asian Handicap is the case that needs explaining. API-Football repeats the
    SAME number on both rows of a pair::

        {"value": "Home -0.25", "odd": "1.92"}
        {"value": "Away -0.25", "odd": "1.88"}

    The number is the handicap on the HOME team; the word says which side you
    back. Measured, not assumed: read that way, every pair in our raw store
    devigs to 1.090; read as a per-side signed handicap, the same pairs devig to
    0.47, which is impossible. So the away row is NEGATED here, and the stored
    line is always the handicap that applies to the stored selection.
    """
    try:
        market = MarketType(market_key)
    except ValueError:
        return None
    aliases = SELECTION_ALIASES.get(market_key, {})

    if market_key not in LINED_MARKETS:
        side = aliases.get(raw_value.strip().lower())
        return None if side is None else Selection(market, side)

    split = _split_line(raw_value)
    if split is None:
        return None
    side_word, number = split
    side = aliases.get(side_word.lower())
    if side is None:
        return None
    line = -number if (market is MarketType.ASIAN_HANDICAP and side is Side.AWAY) else number
    try:
        return Selection(market, side, MarketLine(line))
    except InvalidSelectionError:
        return None


def minutes_to_kickoff(kickoff_at: datetime, captured_at: datetime) -> int:
    """Positive before kick-off, floored at 0. Never negative for a prematch
    price: that would assert we saw a pre-match quote after the match began."""
    delta = (kickoff_at - captured_at).total_seconds() / 60.0
    return max(0, math.floor(delta))


def iter_odds(
    body: dict[str, Any],
    *,
    kickoff_at: datetime,
    captured_at: datetime,
    payload_hash: str,
    source: OddsSource,
    market_filter: set[str] | None = None,
    parse_log: OddsParseLog | None = None,
) -> Iterator[OddsQuote]:
    """Yield one OddsQuote per (bookmaker, market, selection, line).

    Anything malformed is skipped, logged with its reason, and recorded in
    ``parse_log`` when one is given. The caller compares yielded count against
    the payload's own counts to detect silent loss.
    """
    mtk = minutes_to_kickoff(kickoff_at, captured_at)
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        fixture_id = _fixture_id(entry)
        if fixture_id is None:
            continue
        for book in entry.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            book_id, book_name = book.get("id"), book.get("name")
            if not isinstance(book_id, int) or not isinstance(book_name, str):
                continue
            for bet in book.get("bets") or []:
                if not isinstance(bet, dict):
                    continue
                bet_id = bet.get("id")
                if not isinstance(bet_id, int):
                    continue
                bet_name = bet.get("name")
                bet_name = str(bet_name) if isinstance(bet_name, str) else ""
                market_key = _market_of(source, bet_id)
                if market_key is None:
                    if parse_log is not None:
                        parse_log.unmapped_bets[(bet_id, bet_name)] += 1
                    continue
                expected = BETS_BY_SOURCE[source][market_key]
                if bet_name and not _same_name(bet_name, expected.name):
                    log.warning("odds.bet_renamed", source=source, bet_id=bet_id,
                                expected=expected.name, got=bet_name)
                    if parse_log is not None:
                        parse_log.renamed_bets.append((bet_id, expected.name, bet_name))
                    continue
                if market_filter and market_key not in market_filter:
                    continue
                for value in bet.get("values") or []:
                    quote = _quote(
                        value=value,
                        market_key=market_key,
                        fixture_id=fixture_id,
                        book_id=book_id,
                        book_name=book_name,
                        captured_at=captured_at,
                        minutes=mtk,
                        source=source,
                        payload_hash=payload_hash,
                        parse_log=parse_log,
                    )
                    if quote is not None:
                        yield quote


def _fixture_id(entry: dict[str, Any]) -> int | None:
    fixture = entry.get("fixture")
    if isinstance(fixture, dict) and isinstance(fixture.get("id"), int):
        return int(fixture["id"])
    if isinstance(entry.get("fixture"), int):
        return int(entry["fixture"])
    return None


def _quote(
    *,
    value: Any,
    market_key: str,
    fixture_id: int,
    book_id: int,
    book_name: str,
    captured_at: datetime,
    minutes: int,
    source: OddsSource,
    payload_hash: str,
    parse_log: OddsParseLog | None = None,
) -> OddsQuote | None:
    if not isinstance(value, dict):
        return None
    raw_selection = value.get("value")
    if not isinstance(raw_selection, str):
        return None

    selection = _selection(market_key, raw_selection)
    if selection is None:
        log.debug("odds.unreadable_selection", market=market_key, value=raw_selection)
        if parse_log is not None:
            parse_log.refuse(market_key, raw_selection, "not a selection of this market")
        return None

    odds = _to_decimal(value.get("odd"))
    if odds is None or not (MIN_ODDS <= odds <= MAX_ODDS):
        log.debug("odds.out_of_range", market=market_key, selection=str(selection), odd=value.get("odd"))
        if parse_log is not None:
            parse_log.refuse(market_key, f"{raw_selection} @ {value.get('odd')!r}", "odds out of range")
        return None

    return OddsQuote(
        provider_fixture_id=fixture_id,
        provider_bookmaker_id=book_id,
        bookmaker_name=book_name,
        market_key=selection.market.value,
        selection=selection.side.value,
        line=selection.line_for_storage,
        odds_decimal=odds,
        captured_at=captured_at,
        minutes_to_ko=minutes,
        source=source,
        payload_hash=payload_hash,
    )


CANONICAL_STATUSES = frozenset({
    "TBD", "NS", "1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "FT", "AET", "PEN",
    "PST", "CANC", "ABD", "AWD", "WO", "LIVE",
})
"""Every short status the v3 documentation lists, spelled the way it lists them."""


def canonical_status(value: Any, default: str = "NS") -> str:
    """The provider's short status, spelled one way.

    It is not spelled one way at the source. Fixture 1438655 (AFC Champions League
    Two 2025) arrives as ``"Canc"``, most cancelled fixtures as ``"CANC"``; ``"Abd"``
    and ``"ABD"`` likewise. Every map downstream (status group, settlement, the live
    follower) is keyed on the documented upper-case codes, so a mixed-case code fell
    through to each map's default: 78 cancelled fixtures and one abandoned one sat
    as *scheduled*, past kick-off, waiting for a result that was never coming.

    Upper-casing here, once, is what keeps that from depending on every reader
    remembering to do it.
    """
    text = value.strip().upper() if isinstance(value, str) else ""
    return text or default


def _text(value: Any) -> str | None:
    """A non-empty string, or None. The provider sends "" and null interchangeably."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def iter_fixtures(body: dict[str, Any]) -> Iterator[FixtureRef]:
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        fixture, league, teams = entry.get("fixture"), entry.get("league"), entry.get("teams")
        if not all(isinstance(x, dict) for x in (fixture, league, teams)):
            continue
        assert isinstance(fixture, dict) and isinstance(league, dict) and isinstance(teams, dict)
        try:
            kickoff = datetime.fromisoformat(str(fixture["date"]))
            home, away = teams["home"], teams["away"]
            venue = fixture.get("venue") if isinstance(fixture.get("venue"), dict) else {}
            assert isinstance(venue, dict)
            venue_id = venue.get("id")
            round_name = league.get("round")
            yield FixtureRef(
                provider_fixture_id=int(fixture["id"]),
                provider_league_id=int(league["id"]),
                season=int(league["season"]),
                kickoff_at=kickoff,
                provider_home_team_id=int(home["id"]),
                provider_away_team_id=int(away["id"]),
                status_short=canonical_status((fixture.get("status") or {}).get("short")),
                round=str(round_name) if isinstance(round_name, str) and round_name else None,
                provider_venue_id=int(venue_id) if isinstance(venue_id, int) else None,
                venue_name=_text(venue.get("name")),
                venue_city=_text(venue.get("city")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("fixture.unparsable", error=str(exc))
            continue


def iter_league_seasons(body: dict[str, Any]) -> Iterator[SeasonRef]:
    """Parse /leagues. One SeasonRef per season the provider exposes for us.

    On a restricted plan the provider returns only the seasons that plan can
    see, so an empty result is information: this league is not usable, rather
    than a parsing failure.
    """
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        league, seasons = entry.get("league"), entry.get("seasons")
        if not isinstance(league, dict) or not isinstance(seasons, list):
            continue
        league_id = league.get("id")
        if not isinstance(league_id, int):
            continue
        for season in seasons:
            if not isinstance(season, dict) or not isinstance(season.get("year"), int):
                continue
            raw_coverage = season.get("coverage")
            coverage: dict[str, Any] = raw_coverage if isinstance(raw_coverage, dict) else {}
            raw_fixtures = coverage.get("fixtures")
            fixtures: dict[str, Any] = raw_fixtures if isinstance(raw_fixtures, dict) else {}
            yield SeasonRef(
                provider_league_id=int(league_id),
                season=int(season["year"]),
                is_current=bool(season.get("current", False)),
                start_date=(str(season["start"]) if season.get("start") else None),
                end_date=(str(season["end"]) if season.get("end") else None),
                has_odds=bool(coverage.get("odds", False)),
                has_fixtures=bool(fixtures.get("events", False)) or bool(fixtures),
            )

FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})
"""Only these mean "this match was played to a conclusion".

Deliberately narrow. A postponed, abandoned or awarded fixture has no score we
are willing to settle on, and the provider happily reports 0-0 for several of
them.
"""


EXTRA_TIME_STATUSES = frozenset({"AET", "PEN"})


def _pair(block: Any) -> tuple[int | None, int | None]:
    """(home, away) from one of the provider's score blocks, or (None, None).

    The provider uses null for periods that did not happen, and the blocks are
    absent entirely on some payloads, so both shapes have to read the same."""
    if not isinstance(block, dict):
        return None, None
    home, away = block.get("home"), block.get("away")
    return (home if isinstance(home, int) else None, away if isinstance(away, int) else None)


@dataclass(frozen=True, slots=True)
class ScoreDisagreement:
    """The provider's own score fields contradicting each other, as a fact to record.

    A string in a log line is not a record: these are the cases where an operator later
    asks why a finished match has no result, and "the provider said fulltime 4-0 with a
    final of 2-0" is the answer. ``dropped`` says whether the fixture was skipped
    entirely or merely had one field ignored.
    """

    provider_fixture_id: int
    field: str
    observed: str
    expected: str
    detail: str
    dropped: bool


def iter_fixture_results(
    body: dict[str, Any], *, disagreements: list[ScoreDisagreement] | None = None
) -> Iterator[FixtureResultRef]:
    """Scores, from the SAME /fixtures payload the fixture sync already reads.

    This costs no extra request: the provider returns goals and score blocks
    alongside every fixture, and the previous code simply discarded them. That
    matters more than it sounds - on a restricted plan a result unclaimed
    within the plan's date window is unreachable forever.

    A fixture the provider does not report as finished yields nothing, so a
    postponed match never acquires a score.

    ``disagreements`` collects the fixtures where the provider's own three numbers do
    not add up - ``fulltime + extratime != goals``, which happens on about 5% of its
    extra-time fixtures because ``extratime`` sometimes carries the running total. The
    stated ``fulltime`` is used regardless; the caller records the disagreement, because
    it is the provider's fact rather than our arithmetic.
    """
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        fixture = entry.get("fixture")
        if not isinstance(fixture, dict):
            continue
        status = canonical_status((fixture.get("status") or {}).get("short"), default="")
        if status not in FINISHED_STATUSES:
            continue
        goals_home, goals_away = _pair(entry.get("goals"))
        if goals_home is None or goals_away is None:
            log.debug("result.no_goals", fixture=fixture.get("id"), status=status)
            continue
        raw_score = entry.get("score")
        score: dict[str, Any] = raw_score if isinstance(raw_score, dict) else {}
        ht_h, ht_a = _pair(score.get("halftime"))
        ft_h, ft_a = _pair(score.get("fulltime"))
        et_h, et_a = _pair(score.get("extratime"))
        pk_h, pk_a = _pair(score.get("penalty"))

        fid = fixture.get("id")
        if ft_h is not None and ft_a is not None and (ft_h > goals_home or ft_a > goals_away):
            # Impossible: `goals` includes extra time, so it can only be greater or equal.
            log.warning("result.fulltime_exceeds_final", fixture=fid,
                        fulltime=(ft_h, ft_a), final=(goals_home, goals_away))
            if disagreements is not None and isinstance(fid, int):
                disagreements.append(ScoreDisagreement(
                    provider_fixture_id=fid, field="ft_goals_home",
                    observed=f"fulltime {ft_h}-{ft_a} with a final of {goals_home}-{goals_away}",
                    expected="a 90-minute score no greater than the final score",
                    detail="goals includes extra time, so fulltime cannot exceed it; the stated "
                           "fulltime is ignored",
                    dropped=False,
                ))
            ft_h = ft_a = None
        if (ft_h is None or ft_a is None) \
                and status in EXTRA_TIME_STATUSES and (et_h is None or et_a is None):
            # Neither the stated 90-minute score nor an extra-time breakdown to derive
            # it from. `goals` includes extra time, so it is not the 90-minute score and
            # there is nothing here to settle a 1X2 on. Better an awaited result than a
            # wrong one.
            log.warning("result.no_ninety_minute_score", fixture=fid, status=status)
            if disagreements is not None and isinstance(fid, int):
                disagreements.append(ScoreDisagreement(
                    provider_fixture_id=fid, field="ft_goals_home",
                    observed=f"status {status} with a final of {goals_home}-{goals_away}",
                    expected="a stated fulltime or an extra-time score",
                    detail="neither the 90-minute score nor a breakdown to derive it from, so no "
                           "result is written rather than a wrong one",
                    dropped=True,
                ))
            continue
        if (et_h is not None and et_h > goals_home) or (et_a is not None and et_a > goals_away):
            log.warning("result.extra_time_exceeds_final", fixture=fid,
                        extratime=(et_h, et_a), final=(goals_home, goals_away))
            if disagreements is not None and isinstance(fid, int):
                disagreements.append(ScoreDisagreement(
                    provider_fixture_id=fid, field="et_goals_home",
                    observed=f"extratime {et_h}-{et_a} with a final of {goals_home}-{goals_away}",
                    expected="an extra-time score no greater than the final score",
                    detail="the provider's own numbers contradict each other and there is no way "
                           "to tell which is wrong, so no result is written",
                    dropped=True,
                ))
            continue
        if ft_h is not None and ft_a is not None and et_h is not None and et_a is not None \
                and (ft_h + et_h, ft_a + et_a) != (goals_home, goals_away):
            # The provider contradicting itself: on about 5% of its extra-time fixtures
            # `extratime` carries the running total rather than the increment, so the
            # three numbers do not add up. `fulltime` is used regardless - which is the
            # point of reading it - and the disagreement is recorded rather than hidden,
            # because it is the provider's fact and not our arithmetic.
            log.info("result.score_parts_disagree", fixture=fid,
                     fulltime=(ft_h, ft_a), extratime=(et_h, et_a), final=(goals_home, goals_away))
            if disagreements is not None and isinstance(fid, int):
                disagreements.append(ScoreDisagreement(
                    provider_fixture_id=fid, field="et_goals_home",
                    observed=f"fulltime {ft_h}-{ft_a} + extratime {et_h}-{et_a} != goals "
                             f"{goals_home}-{goals_away}",
                    expected="the three score blocks to add up",
                    detail="extratime carries the running total rather than the increment on "
                           "about 5% of the provider's extra-time fixtures; the stated fulltime "
                           "is used regardless",
                    dropped=False,
                ))
        try:
            yield FixtureResultRef(
                provider_fixture_id=int(fixture["id"]),
                status_short=status,
                goals_home=goals_home,
                goals_away=goals_away,
                ht_goals_home=ht_h,
                ht_goals_away=ht_a,
                ft_goals_home=ft_h,
                ft_goals_away=ft_a,
                et_goals_home=et_h,
                et_goals_away=et_a,
                pen_home=pk_h,
                pen_away=pk_a,
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("result.unparsable", error=str(exc))
            continue
