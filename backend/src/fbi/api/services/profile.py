"""The two teams before a match: results, goals, shots, corners, cards and penalties over their newest finished
matches, in every competition and in this one (REVIEW PREDIGOL, 11 Oct 2026, point 5).

Coverage first: each figure counts only the matches that carry its data and says how many (``n``). A season
without corner data gives "corners: no data", not "0 corners"; a first goal that was an own goal, or a match
without events, is left out of "scored first" rather than guessed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException

from fbi.api.cache import shared
from fbi.api.contracts.profile import (
    BookQuote,
    CaptureSummary,
    MatchMarkets,
    MatchProfile,
    ProfileMetric,
    ProfileScope,
    ProfileScopeName,
    ProfileValue,
    SelectionQuotes,
)
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one
from fbi.api.repositories import profile as repo

WINDOW = 10
"""The newest finished matches of each team before kick-off."""

Pred = Callable[[Row], bool | None]
"""Whether it happened in a match; None when the match does not carry the data."""

Num = Callable[[Row], Decimal | int | float | None]


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def count_value(rows: Sequence[Row], pred: Pred) -> ProfileValue:
    seen = [v for v in (pred(r) for r in rows) if v is not None]
    k = sum(1 for v in seen if v)
    return ProfileValue(value=_q(Decimal(k) / len(seen)) if seen else None, count=k, n=len(seen))


def average_value(rows: Sequence[Row], num: Num) -> ProfileValue:
    seen = [Decimal(str(v)) for v in (num(r) for r in rows) if v is not None]
    return ProfileValue(value=_q(sum(seen, Decimal(0)) / len(seen)) if seen else None, n=len(seen))


def _first(r: Row) -> str | None:
    """'own' / 'opp' / 'none' (0-0); None when unknown: an own goal first, or goals but no events."""
    if r["first_goal"] in ("own", "opp"):
        return str(r["first_goal"])
    if r["first_goal"] is None and r["gf"] == 0 and r["ga"] == 0:
        return "none"
    return None


def _ht(r: Row) -> bool | None:
    return None if r["ht_gf"] is None or r["ht_ga"] is None else r["ht_gf"] > r["ht_ga"]


def _cards(r: Row) -> int | None:
    if r["yellow_cards"] is None and r["red_cards"] is None:
        return None
    return int(r["yellow_cards"] or 0) + int(r["red_cards"] or 0)


def _scored_first(r: Row) -> bool | None:
    first = _first(r)
    return None if first is None else first == "own"


def _conceded_first(r: Row) -> bool | None:
    first = _first(r)
    return None if first is None else first == "opp"


COUNTS: tuple[tuple[str, Pred], ...] = (
    ("wins", lambda r: r["gf"] > r["ga"]),
    ("draws", lambda r: r["gf"] == r["ga"]),
    ("losses", lambda r: r["gf"] < r["ga"]),
    ("win_or_draw", lambda r: r["gf"] >= r["ga"]),
    ("btts", lambda r: r["gf"] > 0 and r["ga"] > 0),
    ("over_2_5", lambda r: r["gf"] + r["ga"] > 2),
    ("clean_sheets", lambda r: r["ga"] == 0),
    ("failed_to_score", lambda r: r["gf"] == 0),
    ("ht_lead", _ht),
    ("scored_first", _scored_first),
    ("conceded_first", _conceded_first),
)

AVERAGES: tuple[tuple[str, Num], ...] = (
    ("goals_for", lambda r: r["gf"]),
    ("goals_against", lambda r: r["ga"]),
    ("xg_for", lambda r: r["xg_for"]),
    ("xg_against", lambda r: r["xg_against"]),
    ("shots", lambda r: r["shots"]),
    ("shots_on_target", lambda r: r["shots_on_target"]),
    ("shots_against", lambda r: r["shots_against"]),
    ("corners", lambda r: r["corners"]),
    ("corners_against", lambda r: r["corners_against"]),
    ("cards", _cards),
    ("fouls", lambda r: r["fouls"]),
    ("possession", lambda r: r["possession_pct"]),
)


def penalties_value(rows: Sequence[Row]) -> ProfileValue:
    """Scored of taken, over the matches whose events we have (a match without events says nothing about them)."""
    with_events = [r for r in rows if r["has_events"]]
    scored = sum(int(r["pens_scored"]) for r in with_events)
    taken = scored + sum(int(r["pens_missed"]) for r in with_events)
    return ProfileValue(value=None, count=scored, total=taken, n=len(with_events))


def metrics(home: Sequence[Row], away: Sequence[Row]) -> list[ProfileMetric]:
    out = [ProfileMetric(key=key, kind="count", home=count_value(home, pred), away=count_value(away, pred))
           for key, pred in COUNTS]
    out += [ProfileMetric(key=key, kind="average", home=average_value(home, num), away=average_value(away, num))
            for key, num in AVERAGES]
    out.append(ProfileMetric(key="penalties", kind="ratio", home=penalties_value(home), away=penalties_value(away)))
    return out


def _team(conn: Conn, team: int, fx: Row, competition: int | None) -> list[Row]:
    params: dict[str, Any] = {"team": team, "ko": fx["kickoff_at"], "competition": competition, "n": WINDOW}
    return fetch_all(conn, repo.TEAM_MATCHES, params)


@shared(300)
def match_profile(conn: Conn, fixture_id: int) -> Envelope[MatchProfile | None]:
    fx = fetch_one(conn, repo.FIXTURE, {"f": fixture_id})
    if fx is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    scopes: list[ProfileScope] = []
    wanted: tuple[tuple[ProfileScopeName, int | None], ...] = (("all", None), ("competition", fx["competition_id"]))
    for scope, competition in wanted:
        home = _team(conn, fx["home_team_id"], fx, competition)
        away = _team(conn, fx["away_team_id"], fx, competition)
        scopes.append(ProfileScope(scope=scope, home_matches=len(home), away_matches=len(away),
                                   metrics=metrics(home, away)))
    profile = MatchProfile(fixture_id=fixture_id, window=WINDOW, scopes=scopes)
    if scopes[0].home_matches == 0 and scopes[0].away_matches == 0:
        return unavailable(profile, "Neither team has a finished match stored before this one.",
                           status=DataStatus.EMPTY)
    return ok(profile)


@shared(60)
def match_markets(conn: Conn, fixture_id: int) -> Envelope[MatchMarkets | None]:
    """Every price captured for the match, as the Cronología counts them (REVIEW point 10): the captures with their
    numbers per market, and each pre-match selection with every bookmaker's newest and first price. Not filtered
    by any pick rule - a price is shown whether or not it ever passed one."""
    if fetch_one(conn, repo.FIXTURE, {"f": fixture_id}) is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    per_market: dict[tuple[Any, str], dict[str, int]] = {}
    for r in fetch_all(conn, repo.CAPTURES_BY_MARKET, {"f": fixture_id}):
        per_market.setdefault((r["captured_at"], r["source"]), {})[r["market_key"]] = int(r["quotes"])
    captures = [CaptureSummary(captured_at=r["captured_at"], minutes_to_ko=int(r["minutes_to_ko"]), source=r["source"],
                               quotes=int(r["quotes"]), bookmakers=int(r["bookmakers"]),
                               by_market=per_market.get((r["captured_at"], r["source"]), {}))
                for r in fetch_all(conn, repo.CAPTURES, {"f": fixture_id})]
    grouped: dict[tuple[str, str, Decimal], list[BookQuote]] = {}
    for r in fetch_all(conn, repo.MARKET_BOOKS, {"f": fixture_id}):
        grouped.setdefault((r["market_key"], r["selection"], Decimal(r["line"])), []).append(BookQuote(
            bookmaker_id=r["bookmaker_id"], bookmaker=r["bookmaker"], odds=r["odds"], captured_at=r["captured_at"],
            opening_odds=r["opening_odds"], opening_at=r["opening_at"], captures=int(r["captures"])))
    selections = [SelectionQuotes(market_key=k[0], selection=k[1], line=k[2],
                                  books=sorted(v, key=lambda b: (-b.odds, b.bookmaker)))
                  for k, v in grouped.items()]
    view = MatchMarkets(fixture_id=fixture_id, quotes=sum(c.quotes for c in captures), captures=captures,
                        selections=selections)
    if not captures:
        return unavailable(view, "No price has been captured for this match yet.", status=DataStatus.EMPTY)
    return ok(view)
