"""Home, picks, parlays and best prices - what a signed-in user sees.

Every pick here is re-priced at the best price available now and put through the same
value gate the parlay engine uses (``fbi.parlays.engine``). A user sees qualified picks
only; ``include_shadow`` is the Admin Console's preview and is refused to anyone else
by the router.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fbi.api.cache import shared
from fbi.api.contracts.product import (
    BestHighlight,
    BestMarket,
    BestOddsBoard,
    BestOddsFixture,
    BestPrice,
    CompetitionBadge,
    DataFreshness,
    Freshness,
    Home,
    Parlay,
    ParlayLeg,
    PickCard,
    PicksBoard,
    Source,
    TeamBadge,
    UpcomingMatch,
)
from fbi.api.envelope import DataStatus, Envelope, ok, section
from fbi.api.repositories import Conn, Row
from fbi.api.repositories import product as repo
from fbi.api.services import center
from fbi.core.clock import now as clock_now
from fbi.parlays import engine
from fbi.parlays.engine import Candidate, GateConfig, Leg, Reject

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
Q6 = Decimal("0.000001")
CONSENSUS_LOOKBACK = timedelta(hours=36)
"""A consensus older than this is not a current price at all; the gate's own limit is tighter."""
PRICE_FRESH = timedelta(hours=1)
TOP_WINDOW = timedelta(hours=24)
TOP_SIZE = 5
HOME_WINDOW = timedelta(hours=48)
HIGHLIGHT_MIN_BOOKS = 3
HIGHLIGHT_MAX_AGE = timedelta(hours=6)
OUTLIER_EDGE = GateConfig().max_price_edge


def _source(include_shadow: bool) -> Source:
    return "shadow_preview" if include_shadow else "qualified"


def _competition(r: Row) -> CompetitionBadge:
    return CompetitionBadge(id=int(r["competition_id"]), name=r["competition_name"], country=r["competition_country"],
                            logo_url=r["competition_logo"], flag_url=r["competition_flag"])


def _home(r: Row) -> TeamBadge:
    return TeamBadge(id=int(r["home_team_id"]), name=r["home_name"], logo_url=r["home_logo"])


def _away(r: Row) -> TeamBadge:
    return TeamBadge(id=int(r["away_team_id"]), name=r["away_name"], logo_url=r["away_logo"])


def candidate_of(r: Row) -> Candidate:
    return Candidate(
        pick_id=int(r["pick_id"]), fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
        fixture_status=r["fixture_status"], home_team_id=int(r["home_team_id"]),
        away_team_id=int(r["away_team_id"]), market_key=r["market_key"], selection=r["selection"],
        line=Decimal(r["line"]), qualified=r["pick_status"] in ("qualified", "published"),
        model_status=r["model_status"], p_model=Decimal(r["p_model"]),
        p_push=Decimal(r["p_push"]) if r.get("p_push") is not None else None,
        p_market_fair=Decimal(r["p_fair"]) if r.get("p_fair") is not None else None,
        price=Decimal(r["best_odds"]) if r.get("best_odds") is not None else None,
        price_at=r.get("price_at"), n_bookmakers=r.get("n_bookmakers"),
    )


def freshness_of(price_at: datetime | None, moment: datetime, cfg: GateConfig) -> Freshness:
    if price_at is None:
        return "none"
    age = moment - price_at
    if age <= PRICE_FRESH:
        return "fresh"
    if age <= cfg.max_price_age:
        return "aging"
    return "stale"


def card(r: Row, verdict: Leg | Reject, moment: datetime, cfg: GateConfig) -> PickCard:
    c = candidate_of(r)
    p_market = c.p_market_fair
    if isinstance(verdict, Leg):
        ev: Decimal | None = verdict.ev
    elif c.price is not None:
        ev = engine.expected_value(c.p_model, c.p_push, c.price)[0].quantize(Q6, ROUND_HALF_UP)
    else:
        ev = None
    return PickCard(
        pick_id=c.pick_id, fixture_id=c.fixture_id, kickoff_at=c.kickoff_at, competition=_competition(r),
        home=_home(r), away=_away(r), market_key=c.market_key, selection=c.selection, line=c.line,
        status=r["pick_status"], model=r["model"], best_odds=c.price, bookmaker=r.get("bookmaker"),
        price_at=c.price_at, p_model=c.p_model, p_market=p_market,
        fair_odds=(Decimal(1) / p_market).quantize(Q3, ROUND_HALF_UP) if p_market else None,
        edge=(c.p_model - p_market).quantize(Q6, ROUND_HALF_UP) if p_market is not None else None,
        ev=ev, freshness=freshness_of(c.price_at, moment, cfg), value_now=isinstance(verdict, Leg),
        value_reason=None if isinstance(verdict, Leg) else verdict.value,
    )


def cards(rows: Iterable[Row], moment: datetime, cfg: GateConfig) -> list[PickCard]:
    """One card per selection: the pick with value now and the best EV, else the newest pick."""
    groups: dict[tuple[int, str, str, Decimal], list[Row]] = defaultdict(list)
    for r in rows:
        groups[(int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"]))].append(r)
    out: list[PickCard] = []
    for group in groups.values():
        judged: list[tuple[Row, Leg | Reject]] = [(r, engine.assess(candidate_of(r), moment, cfg)) for r in group]
        passing = [(r, v) for r, v in judged if isinstance(v, Leg)]
        chosen: tuple[Row, Leg | Reject]
        if passing:
            best_row, best_leg = max(passing, key=lambda rv: rv[1].ev)
            chosen = (best_row, best_leg)
        else:
            chosen = max(judged, key=lambda rv: (rv[0]["pick_created_at"], rv[0]["pick_id"]))
        out.append(card(chosen[0], chosen[1], moment, cfg))
    out.sort(key=lambda p: (not p.value_now, -(p.ev if p.ev is not None else Decimal(-99)), p.kickoff_at,
                            p.pick_id))
    return out


def _top(all_cards: list[PickCard], moment: datetime) -> list[PickCard]:
    return [p for p in all_cards if p.value_now and p.kickoff_at < moment + TOP_WINDOW][:TOP_SIZE]


@shared(30)
def picks_board(conn: Conn, *, include_shadow: bool, competition_id: int | None, market: str | None,
                min_odds: Decimal | None, max_odds: Decimal | None, hours: int,
                at: datetime | None = None) -> Envelope[PicksBoard]:
    moment = at or clock_now()
    cfg = GateConfig(allow_unqualified=include_shadow)
    rows = repo.pick_candidates(conn, now=moment, until=moment + timedelta(hours=hours),
                                since=moment - CONSENSUS_LOOKBACK, include_shadow=include_shadow)
    competitions = {int(r["competition_id"]): _competition(r) for r in rows}
    markets = sorted({r["market_key"] for r in rows})
    kept = [r for r in rows
            if (competition_id is None or int(r["competition_id"]) == competition_id)
            and (market is None or r["market_key"] == market)
            and (min_odds is None or (r["best_odds"] is not None and Decimal(r["best_odds"]) >= min_odds))
            and (max_odds is None or (r["best_odds"] is not None and Decimal(r["best_odds"]) <= max_odds))]
    all_cards = cards(kept, moment, cfg)
    top = _top(all_cards, moment)
    reason = None
    if not rows:
        reason = "no_shadow_picks" if include_shadow else "no_qualified_picks"
    elif not kept:
        reason = "no_picks_match_filters"
    elif not top:
        reason = "no_value_now"
    board = PicksBoard(source=_source(include_shadow), top=top, picks=all_cards,
                       competitions=sorted(competitions.values(), key=lambda c: c.name), markets=markets,
                       window_hours=hours, reason=reason)
    newest = max((p.price_at for p in all_cards if p.price_at), default=None)
    return ok(board, count=len(all_cards), data_as_of=newest)


def parlay(rows: list[Row], spec: engine.ParlaySpec, *, include_shadow: bool, moment: datetime) -> Parlay:
    cfg = GateConfig(allow_unqualified=include_shadow)
    by_pick = {int(r["pick_id"]): r for r in rows}
    built = engine.build(spec.kind, [candidate_of(r) for r in rows], now=moment, window=spec.window,
                         min_legs=spec.min_legs, max_legs=spec.max_legs, cfg=cfg)
    legs: list[ParlayLeg] = []
    for leg in built.legs:
        c = leg.candidate
        r = by_pick[c.pick_id]
        assert c.price is not None and c.price_at is not None and c.p_market_fair is not None
        legs.append(ParlayLeg(
            pick_id=c.pick_id, fixture_id=c.fixture_id, kickoff_at=c.kickoff_at, competition=_competition(r),
            home=_home(r), away=_away(r), market_key=c.market_key, selection=c.selection, line=c.line,
            odds=c.price, bookmaker=r.get("bookmaker"), price_at=c.price_at, p_model=c.p_model,
            p_market=c.p_market_fair, p_win=leg.p_win, edge=leg.probability_edge, ev=leg.ev,
        ))
    return Parlay(
        kind=built.kind, status=built.status, source=_source(include_shadow), legs=legs,
        required_legs=built.required_legs, max_legs=built.max_legs, eligible_legs=built.eligible_legs,
        window_from=built.window_from, window_to=built.window_to, combined_odds=built.combined_odds,
        probability_all_win=built.probability_all_win, expected_value=built.expected_value, risk=built.risk,
        independence=built.independence, prices_as_of=built.prices_as_of, rejections=built.rejections,
        generated_at=moment,
    )


@shared(30)
def parlay_board(conn: Conn, kind: engine.ParlayKind, *, include_shadow: bool,
                 at: datetime | None = None) -> Envelope[Parlay]:
    moment = at or clock_now()
    spec = engine.SPECS[kind]
    rows = repo.pick_candidates(conn, now=moment, until=moment + spec.window, since=moment - CONSENSUS_LOOKBACK,
                                include_shadow=include_shadow)
    return ok(parlay(rows, spec, include_shadow=include_shadow, moment=moment))


# ── best prices ──────────────────────────────────────────────────────────────────

def _price(r: Row) -> BestPrice:
    p_fair = Decimal(r["p_fair"])
    odds = Decimal(r["best_odds"])
    edge = (odds * p_fair - Decimal(1)).quantize(Q4, ROUND_HALF_UP)
    return BestPrice(selection=r["selection"], best_odds=odds, bookmaker=r.get("bookmaker"), p_fair=p_fair,
                     fair_odds=(Decimal(1) / p_fair).quantize(Q3, ROUND_HALF_UP) if p_fair > 0 else Decimal(0),
                     price_edge=edge, outlier=edge > OUTLIER_EDGE,
                     n_bookmakers=int(r["n_bookmakers"]), as_of=r["as_of"])


def main_line(market_key: str, lines: dict[Decimal, list[Row]]) -> Decimal:
    """The line a board shows for a market with several: Over/Under 2.5 when it is quoted; otherwise
    the most widely quoted line, and among those the most balanced (prices closest to even)."""
    if market_key == "OU" and Decimal("2.5") in lines:
        return Decimal("2.5")

    def key(item: tuple[Decimal, list[Row]]) -> tuple[int, Decimal, Decimal]:
        line, rows = item
        books = max(int(r["n_bookmakers"]) for r in rows)
        imbalance = max(abs(Decimal(r["p_fair"]) - Decimal("0.5")) for r in rows)
        return (-books, imbalance, abs(line))

    return min(lines.items(), key=key)[0]


def best_odds(rows: list[Row], *, moment: datetime) -> tuple[list[BestOddsFixture], list[BestHighlight]]:
    by_fixture: dict[int, list[Row]] = defaultdict(list)
    for r in rows:
        by_fixture[int(r["fixture_id"])].append(r)
    fixtures: list[BestOddsFixture] = []
    highlights: list[BestHighlight] = []
    for fid, frows in by_fixture.items():
        first = frows[0]
        markets: list[BestMarket] = []
        for market_key in repo.POPULAR_MARKETS:
            mrows = [r for r in frows if r["market_key"] == market_key]
            if not mrows:
                continue
            lines: dict[Decimal, list[Row]] = defaultdict(list)
            for r in mrows:
                lines[Decimal(r["line"])].append(r)
            line = main_line(market_key, lines)
            prices = [_price(r) for r in lines[line]]
            markets.append(BestMarket(market_key=market_key, line=line, selections=prices))
            for p in prices:
                if (p.n_bookmakers >= HIGHLIGHT_MIN_BOOKS and p.price_edge > 0 and not p.outlier
                        and moment - p.as_of <= HIGHLIGHT_MAX_AGE):
                    highlights.append(BestHighlight(
                        fixture_id=fid, kickoff_at=first["kickoff_at"], competition=_competition(first),
                        home=_home(first), away=_away(first), market_key=market_key, line=line, price=p))
        if markets:
            fixtures.append(BestOddsFixture(
                fixture_id=fid, kickoff_at=first["kickoff_at"], competition=_competition(first), home=_home(first),
                away=_away(first), markets=markets, as_of=max(r["as_of"] for r in frows)))
    fixtures.sort(key=lambda f: (f.kickoff_at, f.fixture_id))
    # One highlight per fixture: its best price furthest above fair.
    best_per_fixture: dict[int, BestHighlight] = {}
    for h in sorted(highlights, key=lambda h: -h.price.price_edge):
        best_per_fixture.setdefault(h.fixture_id, h)
    return fixtures, sorted(best_per_fixture.values(), key=lambda h: -h.price.price_edge)


@shared(30)
def best_odds_board(conn: Conn, *, hours: int, market: str | None, include_shadow: bool,
                    at: datetime | None = None) -> Envelope[BestOddsBoard]:
    moment = at or clock_now()
    markets = (market,) if market else repo.POPULAR_MARKETS
    rows = repo.best_prices(conn, now=moment, until=moment + timedelta(hours=hours),
                            since=moment - CONSENSUS_LOOKBACK, markets=markets)
    fixtures, highlights = best_odds(rows, moment=moment)
    pick_rows = repo.pick_candidates(conn, now=moment, until=moment + timedelta(hours=hours),
                                     since=moment - CONSENSUS_LOOKBACK, include_shadow=include_shadow)
    value = [p for p in cards(pick_rows, moment, GateConfig(allow_unqualified=include_shadow)) if p.value_now]
    if market:
        value = [p for p in value if p.market_key == market]
    board = BestOddsBoard(window_hours=hours, markets=list(markets), fixtures=fixtures, highlights=highlights[:12],
                          value=value, source=_source(include_shadow))
    newest = max((f.as_of for f in fixtures), default=None)
    return ok(board, count=len(fixtures), data_as_of=newest)


# ── home ─────────────────────────────────────────────────────────────────────────

def _upcoming(r: Row) -> UpcomingMatch:
    return UpcomingMatch(fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"], competition=_competition(r),
                         home=_home(r), away=_away(r), bookmakers=int(r["bookmakers"]))


@shared(30)
def home(conn: Conn, *, include_shadow: bool, at: datetime | None = None) -> Envelope[Home]:
    moment = at or clock_now()
    cfg = GateConfig(allow_unqualified=include_shadow)
    rows = repo.pick_candidates(conn, now=moment, until=moment + HOME_WINDOW, since=moment - CONSENSUS_LOOKBACK,
                                include_shadow=include_shadow)
    top = _top(cards(rows, moment, cfg), moment)
    if top:
        top_section = section(top)
    elif rows:
        top_section = section(top, status=DataStatus.EMPTY, reason="no_value_now")
    else:
        top_section = section(top, status=DataStatus.EMPTY,
                              reason="no_shadow_picks" if include_shadow else "no_qualified_picks")

    live_env = center.live_board(conn, at=moment)
    live = list(live_env.data.matches[:6])
    price_rows = repo.best_prices(conn, now=moment, until=moment + HOME_WINDOW, since=moment - CONSENSUS_LOOKBACK)
    _, highlights = best_odds(price_rows, moment=moment)
    upcoming = [_upcoming(r) for r in repo.upcoming(conn, now=moment, until=moment + HOME_WINDOW, limit=8)]
    odds_at = max((r["as_of"] for r in price_rows), default=None)
    body = Home(
        source=_source(include_shadow),
        data_freshness=DataFreshness(odds_at=odds_at, live_at=repo.live_freshness(conn, now=moment)),
        top_picks=top_section,
        daily_parlay=parlay(rows, engine.DAILY, include_shadow=include_shadow, moment=moment),
        multiday_parlay=parlay(rows, engine.MULTIDAY, include_shadow=include_shadow, moment=moment),
        live=section(live) if live else section(live, status=DataStatus.EMPTY, reason="no_live_matches"),
        best_prices=(section(highlights[:6]) if highlights
                     else section(highlights, status=DataStatus.EMPTY, reason="no_best_prices")),
        upcoming=(section(upcoming) if upcoming
                  else section(upcoming, status=DataStatus.EMPTY, reason="no_upcoming_matches")),
    )
    return ok(body, data_as_of=odds_at)
