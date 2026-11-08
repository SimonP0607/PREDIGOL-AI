"""Home, picks, parlays and best prices - what a signed-in user sees.

Every pick of a match not yet started is re-priced at the best price available now and put
through the same value gate the parlay engine uses (``fbi.parlays.engine``). Once its match
kicks off a pick is never re-priced again: it stays on the board as it was taken (``started``),
beside the match's state and its result. A user sees qualified picks
only; ``include_shadow`` is the Admin Console's preview and is refused to anyone else
by the router.

Every card carries the state a reader is shown (plan UX, B3: ``fbi/picks/user_status.py``, the one table). A reader is shown
the RECOMMENDED ones only - in a list, on one match (``fixture_id``) and as the legs of a parlay (UX-002, «solo verde») - and the
rest are counted (``withheld``). The owner's preview shows every card, labelled.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fbi.api.cache import shared
from fbi.api.contracts.builder import (
    BuilderFilters,
    BuilderFunnel,
    BuilderLeg,
    BuilderOption,
    BuiltParlay,
)
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
    StartedPick,
    TeamBadge,
)
from fbi.api.contracts.records import ItemAi
from fbi.api.envelope import DataStatus, Envelope, listing, ok, section
from fbi.api.repositories import Conn, Row
from fbi.api.repositories import product as repo
from fbi.api.services import center, home_board, pick_status
from fbi.api.services.pick_status import Applied
from fbi.api.services.records import ai_items
from fbi.core import match_state
from fbi.core.clock import now as clock_now
from fbi.market.consensus import OPPOSITE_LINE
from fbi.parlays import builder, engine
from fbi.parlays import correlation as corr
from fbi.parlays.engine import Candidate, GateConfig, Leg, Reject
from fbi.parlays.persist import RULE_VERSION as PARLAY_RULE
from fbi.parlays.persist import leg_pool
from fbi.picks import user_status
from fbi.picks.daily import DAY_TZ, RISK, Ranked, load_candidates, passing, product_day
from fbi.picks.daily import Source as DailySource

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
Q6 = Decimal("0.000001")
STARTED_AT_LEAST = timedelta(hours=6)
CONSENSUS_LOOKBACK = timedelta(hours=36)
"""A consensus older than this is not a current price at all; the gate's own limit is tighter."""
PRICE_FRESH = timedelta(hours=1)
TOP_WINDOW = timedelta(hours=24)
TOP_SIZE = 5
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


def card(r: Row, verdict: Leg | Reject, moment: datetime, cfg: GateConfig, *, applied: Applied) -> PickCard:
    c = candidate_of(r)
    p_market = c.p_market_fair
    if isinstance(verdict, Leg):
        ev: Decimal | None = verdict.ev
    elif c.price is not None:
        ev = engine.expected_value(c.p_model, c.p_push, c.price)[0].quantize(Q6, ROUND_HALF_UP)
    else:
        ev = None
    state = applied.shown(pick_status=r["pick_status"], value=isinstance(verdict, Leg), fixture_id=c.fixture_id,
                          market_key=c.market_key, selection=c.selection, line=c.line)
    return PickCard(
        pick_id=c.pick_id, fixture_id=c.fixture_id, kickoff_at=c.kickoff_at, competition=_competition(r),
        home=_home(r), away=_away(r), market_key=c.market_key, selection=c.selection, line=c.line,
        status=r["pick_status"], model=r["model"], best_odds=c.price, bookmaker=r.get("bookmaker"),
        price_at=c.price_at, p_model=c.p_model, p_market=p_market,
        fair_odds=(Decimal(1) / p_market).quantize(Q3, ROUND_HALF_UP) if p_market else None,
        edge=(c.p_model - p_market).quantize(Q6, ROUND_HALF_UP) if p_market is not None else None,
        ev=ev, freshness=freshness_of(c.price_at, moment, cfg), value_now=isinstance(verdict, Leg),
        value_reason=None if isinstance(verdict, Leg) else verdict.value,
        user_status=state.status, status_reason=state.reason, context_pending=state.context_pending,
    )


def cards(rows: Iterable[Row], moment: datetime, cfg: GateConfig, *, applied: Applied) -> list[PickCard]:
    """One card per selection: the pick with value now and the best EV, else the newest pick - each with the state a reader
    is shown (plan UX, B3), the downgraded ones after the rest."""
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
        out.append(card(chosen[0], chosen[1], moment, cfg, applied=applied))
    out.sort(key=lambda p: (not p.value_now, user_status.ORDER[p.user_status],
                            -(p.ev if p.ev is not None else Decimal(-99)), p.kickoff_at, p.pick_id))
    return out


def listed(all_cards: list[PickCard], *, include_shadow: bool) -> list[PickCard]:
    """What a reader is shown of these picks (plan UX, B3; UX-002, «solo verde»): the RECOMMENDED ones only - a pick downgraded
    or rejected by the applied AI review, or without value at the best price now, is counted, never shown, in a list and on its
    match alike. The owner's preview shows every card, labelled."""
    return all_cards if include_shadow else [p for p in all_cards if user_status.for_readers(p.user_status)]


def _top(all_cards: list[PickCard], moment: datetime) -> list[PickCard]:
    return [p for p in all_cards if p.value_now and p.kickoff_at < moment + TOP_WINDOW][:TOP_SIZE]


def started_since(moment: datetime) -> datetime:
    """How far back the board keeps the picks of matches that already kicked off: the whole product day
    (America/Bogota), and never less than the last six hours - a match still being played at midnight stays."""
    day_start = datetime.combine(product_day(moment), time.min, tzinfo=DAY_TZ)
    return min(day_start, moment - STARTED_AT_LEAST)


def started_pick(r: Row, moment: datetime) -> StartedPick:
    phase = match_state.phase(r["status_short"], r["kickoff_at"], moment)
    playing = phase in (match_state.Phase.LIVE, match_state.Phase.SUSPENDED)
    return StartedPick(
        pick_id=int(r["pick_id"]), fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
        competition=_competition(r), home=_home(r), away=_away(r), market_key=r["market_key"],
        selection=r["selection"], line=Decimal(r["line"]), status=r["pick_status"], model=r["model"],
        created_at=r["created_at"], taken_at=r["taken_at"], odds_taken=Decimal(r["odds_taken"]),
        bookmaker=r.get("bookmaker"), p_model=Decimal(r["p_model"]), p_market=Decimal(r["p_market"]),
        fair_odds=Decimal(r["fair_odds"]), edge=Decimal(r["edge"]), ev=Decimal(r["ev"]),
        evaluations=int(r["evaluations"]), phase=phase.value, status_short=r["status_short"],
        live_minute=r["live_minute"] if playing else None, live_extra=r["live_extra"] if playing else None,
        live_home=r["live_home"] if playing else None, live_away=r["live_away"] if playing else None,
        score_home=r["score_home"], score_away=r["score_away"], result_status=r["result_status"],
        profit_units=r["profit_units"], settled_at=r["settled_at"], review_reason=r["review_reason"],
        near_close_odds=r["near_close_odds"], line_value=r["line_value"],
    )


@shared(30)
def picks_board(conn: Conn, *, include_shadow: bool, competition_id: int | None, market: str | None,
                min_odds: Decimal | None, max_odds: Decimal | None, hours: int,
                at: datetime | None = None, fixture_id: int | None = None) -> Envelope[PicksBoard]:
    moment = at or clock_now()
    cfg = GateConfig(allow_unqualified=include_shadow)
    rows = repo.pick_candidates(conn, now=moment, until=moment + timedelta(hours=hours),
                                since=moment - CONSENSUS_LOOKBACK, include_shadow=include_shadow,
                                fixture_id=fixture_id)
    started = [started_pick(r, moment) for r in repo.started_picks(
        conn, now=moment, since=started_since(moment), include_shadow=include_shadow, fixture_id=fixture_id)
        if (competition_id is None or int(r["competition_id"]) == competition_id)
        and (market is None or r["market_key"] == market)]
    competitions = {int(r["competition_id"]): _competition(r) for r in rows}
    markets = sorted({r["market_key"] for r in rows})
    kept = [r for r in rows
            if (competition_id is None or int(r["competition_id"]) == competition_id)
            and (market is None or r["market_key"] == market)
            and (min_odds is None or (r["best_odds"] is not None and Decimal(r["best_odds"]) >= min_odds))
            and (max_odds is None or (r["best_odds"] is not None and Decimal(r["best_odds"]) <= max_odds))]
    applied = pick_status.applied_now(conn, (int(r["fixture_id"]) for r in kept), at=moment)
    all_cards = cards(kept, moment, cfg, applied=applied)
    # A list and one match (its Picks tab) alike show a reader the RECOMMENDED picks only (UX-002, «solo verde»), and the Top 5
    # is always such a list; the owner's preview shows every pick with its state.
    shown = listed(all_cards, include_shadow=include_shadow)
    top = _top(shown, moment)
    reason = None
    if not rows:
        reason = "no_shadow_picks" if include_shadow else "no_qualified_picks"
    elif not kept:
        reason = "no_picks_match_filters"
    elif not shown:
        # No pick of the window is recommended now (plan UX, B3; UX-002): say why truthfully - none has value at the best price
        # now, or some were downgraded or rejected by the applied review.
        reason = "no_value_now" if all(c.status_reason == "no_value_now" for c in all_cards) else "none_recommended"
    elif not top:
        reason = "no_value_now"
    board = PicksBoard(source=_source(include_shadow), top=top, picks=shown,
                       competitions=sorted(competitions.values(), key=lambda c: c.name), markets=markets,
                       window_hours=hours, reason=reason, withheld=len(all_cards) - len(shown), started=started)
    newest = max((p.price_at for p in shown if p.price_at), default=None)
    return ok(board, count=len(shown), data_as_of=newest)


def started_board(conn: Conn, *, include_shadow: bool, at: datetime | None = None) -> Envelope[list[StartedPick]]:
    """Today's pre-match picks whose match already kicked off, unfiltered: the Picks page filters and pages them
    itself, apart from the list of the matches still to come (REVIEW 11 Oct 2026, point 14)."""
    moment = at or clock_now()
    rows = repo.started_picks(conn, now=moment, since=started_since(moment), include_shadow=include_shadow)
    return listing([started_pick(r, moment) for r in rows],
                   empty_reason="no_shadow_picks" if include_shadow else "no_started_picks")


NOT_RECOMMENDED_LEG = "not_recommended"
"""A parlay's rejection code (``Parlay.rejections``) for the selections a reader may not be shown as a leg: the applied AI review
downgrades or rejects them (UX-002, «solo verde»)."""


def recommendable_rows(rows: list[Row], *, applied: Applied) -> tuple[list[Row], int]:
    """The candidates a reader's parlay may hold as legs (UX-002, «solo verde»): every leg passes the value gate (the engine's own
    rule) and must be RECOMMENDED there - so a selection the AI's review downgrades or rejects (applied or in shadow, D1) is left out
    before the engine chooses, never shown as a leg. Returns (the rows kept, how many were left out). Free when the review has
    decided nothing on these rows: nothing is left out."""
    if not applied.decisions:
        return rows, 0
    kept = [r for r in rows if user_status.for_readers(applied.shown(
        pick_status=r["pick_status"], value=True, fixture_id=int(r["fixture_id"]), market_key=r["market_key"],
        selection=r["selection"], line=Decimal(r["line"])).status)]
    return kept, len(rows) - len(kept)


def parlay(rows: list[Row], spec: engine.ParlaySpec, *, include_shadow: bool, moment: datetime,
           applied: Applied = pick_status.NOT_APPLIED) -> Parlay:
    """The parlay of a kind, built now with the engine's rule. A reader's holds RECOMMENDED legs only (``recommendable_rows``);
    the owner's preview builds from every candidate, as before."""
    cfg = GateConfig(allow_unqualified=include_shadow)
    left_out = 0
    if not include_shadow:
        rows, left_out = recommendable_rows(rows, applied=applied)
    by_pick = {int(r["pick_id"]): r for r in rows}
    built = engine.build(spec.kind, [candidate_of(r) for r in rows], now=moment, window=spec.window,
                         min_legs=spec.min_legs, max_legs=spec.max_legs, cfg=cfg)
    rejections = dict(built.rejections)
    if left_out:
        rejections = dict(sorted((rejections | {NOT_RECOMMENDED_LEG: left_out}).items()))
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
        independence=built.independence, prices_as_of=built.prices_as_of, rejections=rejections,
        generated_at=moment,
    )


@shared(30)
def parlay_board(conn: Conn, kind: engine.ParlayKind, *, include_shadow: bool,
                 at: datetime | None = None) -> Envelope[Parlay]:
    moment = at or clock_now()
    spec = engine.SPECS[kind]
    rows = repo.pick_candidates(conn, now=moment, until=moment + spec.window, since=moment - CONSENSUS_LOOKBACK,
                                include_shadow=include_shadow)
    applied = pick_status.applied_now(conn, (int(r["fixture_id"]) for r in rows), at=moment)
    return ok(parlay(rows, spec, include_shadow=include_shadow, moment=moment, applied=applied))


# ── the automatic parlay builder (REVIEW 11 Oct 2026, point 15) ─────────────────────

def _builder_leg(x: Ranked, ai: dict[int, ItemAi], i: int) -> BuilderLeg:
    c, r = x.leg.candidate, x.row
    assert c.price is not None and c.price_at is not None and c.p_market_fair is not None
    p_market = c.p_market_fair
    return BuilderLeg(
        pick_id=c.pick_id, fixture_id=c.fixture_id, kickoff_at=c.kickoff_at, competition=_competition(r),
        home=_home(r), away=_away(r), market_key=c.market_key, selection=c.selection, line=c.line, odds=c.price,
        bookmaker=r.get("bookmaker"), price_at=c.price_at, n_bookmakers=int(c.n_bookmakers or 0), p_model=c.p_model,
        p_low=x.p_low, p_high=Decimal(r["p_high"]) if r.get("p_high") is not None else None, p_market=p_market,
        fair_odds=(Decimal(1) / p_market).quantize(Q3, ROUND_HALF_UP), edge=x.leg.probability_edge,
        price_edge=(c.price * p_market - Decimal(1)).quantize(Q4, ROUND_HALF_UP), ev=x.leg.ev,
        growth=Decimal(str(round(x.elg, 8))), ai=ai.get(i))


def _options(reviewed: list[Ranked]) -> tuple[list[BuilderOption], list[str]]:
    """What the filters can offer: the competitions and markets with selections a parlay could hold, whatever the
    filters chosen so far (picking one competition does not hide the others)."""
    usable = [x for x in reviewed if builder.combinable(x)]
    counts: dict[int, int] = defaultdict(int)
    badges: dict[int, CompetitionBadge] = {}
    for x in usable:
        comp = int(x.row["competition_id"])
        counts[comp] += 1
        badges.setdefault(comp, _competition(x.row))
    options = [BuilderOption(competition=badges[c], selections=n) for c, n in counts.items()]
    options.sort(key=lambda o: (-o.selections, o.competition.name))
    return options, sorted({x.leg.candidate.market_key for x in usable})


@shared(30)
def built_parlay(conn: Conn, filters: builder.Filters, *, include_shadow: bool,
                 at: datetime | None = None) -> Envelope[BuiltParlay]:
    """The parlay PrediGol builds for the user's filters with the rule of its own parlays (``fbi.parlays.builder``):
    from qualified picks only - the owner's preview alone builds from shadow picks, labelled. Nothing is stored."""
    moment = at or clock_now()
    rows = load_candidates(conn, at=moment, until=moment + timedelta(hours=filters.hours),
                           include_shadow=include_shadow)
    source: DailySource = "evaluation" if include_shadow else "qualified"
    gated = passing(rows, at=moment, source=source)
    ranked, reviewed, view = leg_pool(conn, gated, at=moment)
    built = builder.build(ranked, reviewed, filters, at=moment, correlations=corr.latest(conn), gated=len(gated))
    reviews = ai_items(conn, [{"inputs": {"ai": view.record(x)}} for x in built.legs], reveal=include_shadow)
    legs = [_builder_leg(x, reviews, i) for i, x in enumerate(built.legs)]
    competitions, markets = _options(reviewed)
    p_all = Decimal(str(round(built.p_all_low, 8))) if built.p_all_low is not None else None
    p_market = None
    if legs:
        p_market = Decimal(1)
        for leg in legs:
            p_market *= leg.p_market
        p_market = p_market.quantize(Q6, ROUND_HALF_UP)
    body = BuiltParlay(
        status="ok" if legs else "no_valid_parlay", reason=built.reason, source=_source(include_shadow),
        rule_version=builder.RULE_VERSION, parlay_rule=PARLAY_RULE,
        filters=BuilderFilters(hours=filters.hours, min_legs=filters.min_legs, max_legs=filters.max_legs,
                               markets=list(filters.markets), competition_ids=list(filters.competitions),
                               min_odds=filters.min_odds, max_odds=filters.max_odds,
                               max_total_odds=filters.max_total_odds),
        legs=legs,
        combined_odds=built.combined_odds.quantize(Q2, ROUND_HALF_UP) if built.combined_odds is not None else None,
        p_all_low=p_all, p_all_market=p_market,
        expected_log_growth=(Decimal(str(round(built.expected_log_growth, 8)))
                             if built.expected_log_growth is not None else None),
        risk=engine.risk_of(p_all) if p_all is not None else None, correlated_pairs=built.correlated_pairs,
        funnel=BuilderFunnel(passing=built.funnel.gated, risk=built.funnel.passing, reviewed=built.funnel.reviewed,
                             matching=built.funnel.matching, combinable=built.funnel.combinable,
                             matches=built.funnel.matches, max_odds=RISK.max_odds),
        competitions=competitions, markets=markets,
        prices_as_of=min((leg.price_at for leg in legs), default=None), generated_at=moment)
    return ok(body, count=len(legs), data_as_of=body.prices_as_of)


# ── best prices ──────────────────────────────────────────────────────────────────

def _price(r: Row) -> BestPrice:
    p_fair = Decimal(r["p_fair"])
    odds = Decimal(r["best_odds"])
    edge = (odds * p_fair - Decimal(1)).quantize(Q4, ROUND_HALF_UP)
    return BestPrice(selection=r["selection"], best_odds=odds, bookmaker=r.get("bookmaker"), p_fair=p_fair,
                     fair_odds=(Decimal(1) / p_fair).quantize(Q3, ROUND_HALF_UP) if p_fair > 0 else Decimal(0),
                     price_edge=edge, outlier=edge > OUTLIER_EDGE,
                     n_bookmakers=int(r["n_bookmakers"]), as_of=r["as_of"])


HANDICAP_HOME, HANDICAP_AWAY = OPPOSITE_LINE["AH"]
"""An Asian handicap's two sides (``fbi.market.consensus``): one bet is (Home, h) with (Away, -h), and the consensus stores each
side at the line it is quoted at."""


def pair_line(market_key: str, selection: str, line: Decimal) -> Decimal:
    """The line a board groups a price under: its own, except an Asian handicap's away side, quoted at -h for the bet whose home
    side is at h - it goes under h, beside its true counterpart. Grouped by the stored line, Home -0.25 at 1.67 sat beside
    Away -0.25 at 3.48 (fixture 7819, plan Cuotas E1): the away side of the other bet, two prices that make no book together."""
    if market_key == "AH" and selection == HANDICAP_AWAY and line:
        return -line
    return line


def main_line(market_key: str, lines: dict[Decimal, list[Row]]) -> Decimal:
    """The line a board shows for a market with several: Over/Under 2.5 when it is quoted; otherwise
    the most widely quoted line, and among those the most balanced (prices closest to even).

    ``lines`` holds the rows by ``pair_line``, so an Asian handicap's line is a pair - Home at h and Away at -h, the two
    sides of one bet, their fair probabilities summing to 1 - and its balance is the balance of that bet."""
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
            # An Asian handicap's row is a pair, under its home line: Home at h beside Away at -h (pair_line).
            lines: dict[Decimal, list[Row]] = defaultdict(list)
            for r in mrows:
                lines[pair_line(market_key, r["selection"], Decimal(r["line"]))].append(r)
            line = main_line(market_key, lines)
            shown = lines[line]
            prices = [_price(r) for r in shown]
            markets.append(BestMarket(market_key=market_key, line=line, selections=prices))
            for r, p in zip(shown, prices, strict=True):
                if (p.n_bookmakers >= HIGHLIGHT_MIN_BOOKS and p.price_edge > 0 and not p.outlier
                        and moment - p.as_of <= HIGHLIGHT_MAX_AGE):
                    # The highlight names one selection: at its own line (an Asian handicap's away side at -h).
                    highlights.append(BestHighlight(
                        fixture_id=fid, kickoff_at=first["kickoff_at"], competition=_competition(first),
                        home=_home(first), away=_away(first), market_key=market_key, line=Decimal(r["line"]),
                        price=p))
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
                    at: datetime | None = None, with_picks: bool = True) -> Envelope[BestOddsBoard]:
    """``with_picks=False``: the prices alone - no picks are read (the Cuotas page, REVIEW point 17)."""
    moment = at or clock_now()
    markets = (market,) if market else repo.POPULAR_MARKETS
    rows = repo.best_prices(conn, now=moment, until=moment + timedelta(hours=hours),
                            since=moment - CONSENSUS_LOOKBACK, markets=markets)
    fixtures, highlights = best_odds(rows, moment=moment)
    value: list[PickCard] = []
    if with_picks:
        pick_rows = repo.pick_candidates(conn, now=moment, until=moment + timedelta(hours=hours),
                                         since=moment - CONSENSUS_LOOKBACK, include_shadow=include_shadow)
        applied = pick_status.applied_now(conn, (int(r["fixture_id"]) for r in pick_rows), at=moment)
        value = [p for p in listed(cards(pick_rows, moment, GateConfig(allow_unqualified=include_shadow), applied=applied),
                                   include_shadow=include_shadow) if p.value_now]
        if market:
            value = [p for p in value if p.market_key == market]
    board = BestOddsBoard(window_hours=hours, markets=list(markets), fixtures=fixtures, highlights=highlights[:12],
                          value=value, source=_source(include_shadow))
    newest = max((f.as_of for f in fixtures), default=None)
    return ok(board, count=len(fixtures), data_as_of=newest)


# ── home ─────────────────────────────────────────────────────────────────────────

@shared(30)
def home(conn: Conn, *, include_shadow: bool, at: datetime | None = None) -> Envelope[Home]:
    """What is in play, what ended in the last 24 hours, and how fresh that is (plan Inicio, 2.1 and 3.1). The day's picks
    and parlays come from ``/daily``; the best prices live on the Cuotas page and in each pick - none of them is computed here
    any more."""
    moment = at or clock_now()
    live_env = center.live_board(conn, at=moment)
    in_play = home_board.by_priority(conn, list(live_env.data.matches))
    flagged = home_board.relevant(conn, in_play, at=moment)
    shown = {x.match.fixture_id for x in flagged}
    live = [m for m in in_play if m.fixture_id not in shown][:6]
    stakes = home_board.at_stake(conn, at=moment)
    done = home_board.results(conn, at=moment)
    body = Home(
        source=_source(include_shadow),
        data_freshness=DataFreshness(live_at=repo.live_freshness(conn, now=moment)),
        relevant=section(flagged) if flagged else section(flagged, status=DataStatus.EMPTY, reason="no_relevant_matches"),
        at_stake=section(stakes) if stakes else section(stakes, status=DataStatus.EMPTY, reason="nothing_at_stake"),
        live=section(live) if live else section(live, status=DataStatus.EMPTY, reason="no_live_matches"),
        results=section(done) if done else section(done, status=DataStatus.EMPTY, reason="no_recent_results"),
    )
    return ok(body, data_as_of=body.data_freshness.live_at)
