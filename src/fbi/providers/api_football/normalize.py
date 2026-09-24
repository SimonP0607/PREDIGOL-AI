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
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from fbi.providers.base import FixtureRef, FixtureResultRef, OddsQuote, OddsSource, SeasonRef

log = structlog.get_logger(__name__)

# API-Football bet ids -> our market keys. Only what we actually model.
BET_ID_TO_MARKET: dict[int, str] = {
    1: "1X2",
    5: "OU",
    8: "BTTS",
    12: "DC",
    4: "AH",
}

SELECTION_ALIASES: dict[str, dict[str, str]] = {
    "1X2": {"home": "Home", "draw": "Draw", "away": "Away", "1": "Home", "x": "Draw", "2": "Away"},
    "BTTS": {"yes": "Yes", "no": "No"},
    "DC": {"home/draw": "1X", "home/away": "12", "draw/away": "X2", "1x": "1X", "12": "12", "x2": "X2"},
}

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


def _parse_line(market_key: str, raw_value: str) -> tuple[str, Decimal] | None:
    """Split 'Over 2.5' into ('Over', 2.5). Returns None if the line is
    unreadable - never a default of 0, which would silently merge every
    Over/Under line into one."""
    text = raw_value.strip()
    if market_key not in {"OU", "AH"}:
        return text, Decimal("0")
    parts = text.rsplit(" ", 1)
    if len(parts) != 2:
        return None
    side, line_text = parts[0].strip(), parts[1].strip()
    line = _to_decimal(line_text)
    if line is None or not side:
        return None
    return side.title(), line


def _canonical_selection(market_key: str, raw_value: str) -> str | None:
    aliases = SELECTION_ALIASES.get(market_key)
    if aliases is None:
        return raw_value.strip() or None
    return aliases.get(raw_value.strip().lower())


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
) -> Iterator[OddsQuote]:
    """Yield one OddsQuote per (bookmaker, market, selection, line).

    Anything malformed is skipped and logged with its reason. The caller compares
    yielded count against the payload's own counts to detect silent loss.
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
                market_key = BET_ID_TO_MARKET.get(bet.get("id"))  # type: ignore[arg-type]
                if market_key is None:
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
) -> OddsQuote | None:
    if not isinstance(value, dict):
        return None
    raw_selection = value.get("value")
    if not isinstance(raw_selection, str):
        return None

    parsed = _parse_line(market_key, raw_selection)
    if parsed is None:
        log.debug("odds.unparsable_line", market=market_key, value=raw_selection)
        return None
    side, line = parsed

    selection = _canonical_selection(market_key, side) if market_key not in {"OU", "AH"} else side
    if selection is None:
        log.debug("odds.unknown_selection", market=market_key, value=raw_selection)
        return None

    odds = _to_decimal(value.get("odd"))
    if odds is None or not (MIN_ODDS <= odds <= MAX_ODDS):
        log.debug("odds.out_of_range", market=market_key, selection=selection, odd=value.get("odd"))
        return None

    return OddsQuote(
        provider_fixture_id=fixture_id,
        provider_bookmaker_id=book_id,
        bookmaker_name=book_name,
        market_key=market_key,
        selection=selection,
        line=line,
        odds_decimal=odds,
        captured_at=captured_at,
        minutes_to_ko=minutes,
        source=source,
        payload_hash=payload_hash,
    )


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
                status_short=str((fixture.get("status") or {}).get("short") or "NS"),
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


def iter_fixture_results(body: dict[str, Any]) -> Iterator[FixtureResultRef]:
    """Scores, from the SAME /fixtures payload the fixture sync already reads.

    This costs no extra request: the provider returns goals and score blocks
    alongside every fixture, and the previous code simply discarded them. That
    matters more than it sounds - on a restricted plan a result unclaimed
    within the plan's date window is unreachable forever.

    A fixture the provider does not report as finished yields nothing, so a
    postponed match never acquires a score.
    """
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        fixture = entry.get("fixture")
        if not isinstance(fixture, dict):
            continue
        status = str((fixture.get("status") or {}).get("short") or "")
        if status not in FINISHED_STATUSES:
            continue
        goals_home, goals_away = _pair(entry.get("goals"))
        if goals_home is None or goals_away is None:
            log.debug("result.no_goals", fixture=fixture.get("id"), status=status)
            continue
        raw_score = entry.get("score")
        score: dict[str, Any] = raw_score if isinstance(raw_score, dict) else {}
        ht_h, ht_a = _pair(score.get("halftime"))
        et_h, et_a = _pair(score.get("extratime"))
        pk_h, pk_a = _pair(score.get("penalty"))
        if status in EXTRA_TIME_STATUSES and (et_h is None or et_a is None):
            # `goals` includes extra time; without the extra-time breakdown the
            # 90-minute score that markets settle on cannot be derived. Better
            # an awaited result than a wrong one.
            log.warning("result.extra_time_without_breakdown", fixture=fixture.get("id"), status=status)
            continue
        if (et_h is not None and et_h > goals_home) or (et_a is not None and et_a > goals_away):
            log.warning("result.extra_time_exceeds_final", fixture=fixture.get("id"))
            continue
        try:
            yield FixtureResultRef(
                provider_fixture_id=int(fixture["id"]),
                status_short=status,
                goals_home=goals_home,
                goals_away=goals_away,
                ht_goals_home=ht_h,
                ht_goals_away=ht_a,
                et_goals_home=et_h,
                et_goals_away=et_a,
                pen_home=pk_h,
                pen_away=pk_a,
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("result.unparsable", error=str(exc))
            continue
