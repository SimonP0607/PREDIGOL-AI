"""Match list and Match Center."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException

from fbi.api.cache import shared
from fbi.api.contracts.common import (
    CompetitionRef,
    Lineage,
    ResultWaitCode,
    Score,
    TeamRef,
    VenueRef,
)
from fbi.api.contracts.matches import (
    MarketPriceStatus,
    MarketQuote,
    MatchDetail,
    MatchSummary,
    MatchView,
    ModelNoPriceView,
    OddsSummary,
    PredictionRow,
    TimelineEvent,
)
from fbi.api.envelope import DataStatus, Envelope, listing, section
from fbi.api.repositories import Conn, Row
from fbi.api.repositories import fixtures as repo
from fbi.core import match_state
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.market.price_status import market_prices
from fbi.ops.heartbeat import latest_heartbeat
from fbi.picks import no_price

NO_MARKET_DATA = "No captured market data yet."
NO_PREDICTION = "No model has produced a prediction for this match yet."
FREE_PLAN_HORIZON_MIN = 1440
"""On the free plan a fixture is visible only about a day ahead, so a window
further out than this cannot be captured - it is not missed, it is unreachable."""


STILL_SCHEDULED_AFTER = match_state.START_GRACE
STILL_LIVE_AFTER = match_state.LIVE_STALE_AFTER


def awaiting_result(kickoff_at: datetime, status_group: str, moment: datetime) -> bool:
    """Kicked off and the row has not moved on as it should have.

    A match being played is NOT awaiting its result - it is live, and the live
    follower updates it every minute. What is suspicious is a row still
    'scheduled' a quarter of an hour after kick-off, or still 'live' longer than
    any match with extra time and penalties lasts.
    """
    if status_group == "scheduled":
        return kickoff_at < moment - STILL_SCHEDULED_AFTER
    if status_group == "live":
        return kickoff_at < moment - STILL_LIVE_AFTER
    return False


def jobs_healthy(conn: Conn, at: datetime) -> bool:
    """The worker that follows matches and repairs results is alive: without it a silent provider is our fault."""
    beat = latest_heartbeat(conn)
    return beat is not None and beat.is_alive(at)


def summary(row: Row, at: datetime | None = None, *, healthy: bool = True) -> MatchSummary:
    moment = at or now()
    score = None
    if row.get("goals_home") is not None:
        score = Score(
            home=row["goals_home"], away=row["goals_away"],
            ht_home=row["ht_goals_home"], ht_away=row["ht_goals_away"],
            et_home=row["et_goals_home"], et_away=row["et_goals_away"],
            pen_home=row["pen_home"], pen_away=row["pen_away"],
            outcome_1x2=row["outcome_1x2"], total_goals=row["total_goals"], btts=row["btts"],
            source_payload_hash=row["result_payload_hash"], source_fetched_at=row["result_fetched_at"],
        )
    return MatchSummary(
        id=row["id"], provider_fixture_id=row["provider_fixture_id"], kickoff_at=row["kickoff_at"],
        status_short=row["status_short"], status_group=row["status_group"], round=row["round"],
        competition=CompetitionRef(
            id=row["competition_id"], name=row["competition_name"], country=row["competition_country"],
            provider_league_id=row["provider_league_id"], season=row["season"],
            competition_type=row["competition_type"], is_tracked=row["is_tracked"],
            logo_url=row.get("competition_logo"), flag_url=row.get("competition_flag"),
            country_code=row.get("competition_country_code"),
        ),
        home=TeamRef(id=row["home_id"], name=row["home_name"], provider_team_id=row["home_provider_id"],
                     logo_url=row.get("home_logo")),
        away=TeamRef(id=row["away_id"], name=row["away_name"], provider_team_id=row["away_provider_id"],
                     logo_url=row.get("away_logo")),
        score=score,
        odds=OddsSummary(
            snapshots=row["odds_snapshots"], bookmakers=row["odds_bookmakers"], markets=row["odds_markets"],
            first_captured_at=row["odds_first_at"], last_captured_at=row["odds_last_at"],
            near_close_snapshots=row["near_close_snapshots"],
        ),
        predictions=row["predictions"],
        awaiting_result=awaiting_result(row["kickoff_at"], row["status_group"], moment),
        phase=match_state.phase(row["status_short"], row["kickoff_at"], moment).value,
        result_wait=_wait(row, moment, healthy),
        provider_read_at=row.get("source_fetched_at"),
    )


def _wait(row: Row, moment: datetime, healthy: bool) -> ResultWaitCode | None:
    wait = match_state.result_wait(row["status_short"], row["kickoff_at"], provider_read_at=row.get("source_fetched_at"),
                                   has_result=row.get("goals_home") is not None, at=moment, jobs_healthy=healthy)
    return wait.value if wait is not None else None


@shared(15)
def list_matches(
    conn: Conn, flt: repo.FixtureFilter, *, limit: int, offset: int, order: Literal["asc", "desc"]
) -> Envelope[list[MatchSummary]]:
    rows, total = repo.list_fixtures(conn, flt, limit=limit, offset=offset, order=order)
    moment = now()
    healthy = jobs_healthy(conn, moment)
    items = [summary(r, moment, healthy=healthy) for r in rows]
    filtered = any(v is not None for v in flt.params().values())
    reason = "No fixtures match these filters." if filtered else "No fixtures have been ingested yet."
    newest = max((r["updated_at"] for r in rows), default=None)
    return listing(items, empty_reason=reason, total=total, limit=limit, offset=offset, data_as_of=newest)


def quote(row: Row) -> MarketQuote:
    odds = Decimal(row["odds_decimal"])
    return MarketQuote(
        bookmaker_id=row["bookmaker_id"], bookmaker=row["bookmaker"], market_key=row["market_key"],
        selection=row["selection"], line=row["line"], odds_decimal=odds,
        implied_probability=(Decimal(1) / odds).quantize(Decimal("0.000001")),
        captured_at=row["captured_at"], minutes_to_ko=row["minutes_to_ko"], source=row["source"],
        payload_hash=row["payload_hash"],
    )


def _lineage(conn: Conn, row: Row) -> Lineage:
    payload_hash = row["source_payload_hash"]
    src = repo.get_lineage(conn, payload_hash) if payload_hash else None
    params: dict[str, Any] | None = src["params"] if src else None
    return Lineage(
        provider="api_football",
        provider_fixture_id=row["provider_fixture_id"],
        first_seen_at=row["created_at"],
        updated_at=row["updated_at"],
        recorded=payload_hash is not None,
        source_payload_hash=payload_hash,
        source_fetched_at=row["source_fetched_at"],
        source_endpoint=src["endpoint"] if src else None,
        source_params={str(k): str(v) for k, v in params.items()} if params else None,
        source_run_id=src["run_id"] if src else None,
        source_job_type=src["job_type"] if src else None,
        note=None if payload_hash else (
            "This row was last written before lineage was recorded (revision 0015); "
            "the payload that wrote it is not linked."
        ),
    )


def timeline(row: Row, captures: list[Row], at: datetime | None = None, *, asks: Sequence[Row] = (),
             final: Row | None = None, first_live: datetime | None = None,
             wait: str | None = None) -> list[TimelineEvent]:
    """What happened to this fixture, in order, as far as the system observed it.

    A capture window is 'done' only if a snapshot actually fell inside it. A window that passed without one says
    why: the provider was asked and had no prices (``market.odds_asks``), or nobody asked. Captures outside the
    windows (catch-ups) are listed too, so every quote a page shows has its line here (REVIEW 11 Oct 2026, point
    10). Near-close capture is off by design: the closing reference is the provider's last pre-match price, read
    after the match (``market.final_prematch_checks``). Kick-off is 'done' on evidence - the match seen in play, or
    a result - not on the clock. A missing result names its owner (fbi.core.match_state.ResultWait).
    Every event carries a ``code`` and ``vars`` so the page can say it in its reader's language.
    """
    moment = at or now()
    kickoff: datetime = row["kickoff_at"]
    tolerance = settings.odds.odds_window_tolerance
    free_plan = settings.provider_plan.plan == "free"
    events = [TimelineEvent(
        key="discovered", label="Fixture discovered", at=row["created_at"], state="done",
        detail=f"first ingested from the provider (fixture {row['provider_fixture_id']})",
        code="discovered", vars={"provider_fixture_id": str(row["provider_fixture_id"])},
    )]
    prematch = [c for c in captures if c["source"] == "prematch"]
    in_window: set[datetime] = set()
    for window in settings.odds.prematch_windows:
        window_at = kickoff - timedelta(minutes=window)
        hits = [c for c in prematch if window - tolerance <= c["minutes_to_ko"] <= window]
        in_window.update(c["captured_at"] for c in hits)
        label = f"Odds T-{window // 60}h" if window % 60 == 0 else f"Odds T-{window}m"
        wvars = {"window": str(window)}
        if hits:
            first = hits[0]
            quotes = sum(int(h["quotes"]) for h in hits)
            events.append(TimelineEvent(
                key=f"odds_{window}", label=label, at=first["captured_at"], state="done",
                detail=f"{quotes} quotes captured at T-{first['minutes_to_ko']} min", code="window_done",
                vars={**wvars, "quotes": str(quotes), "minutes": str(first["minutes_to_ko"])},
            ))
            continue
        if free_plan and window > FREE_PLAN_HORIZON_MIN:
            events.append(TimelineEvent(
                key=f"odds_{window}", label=label, at=None, state="skipped",
                detail="not reachable on the free plan: fixtures are visible only about a day ahead",
                code="window_free_plan", vars=wvars,
            ))
            continue
        if window_at > moment:
            events.append(TimelineEvent(key=f"odds_{window}", label=label, at=window_at, state="pending",
                                        detail="scheduled", code="window_scheduled", vars=wvars))
            continue
        asked = [a for a in asks if a["minutes_to_ko"] is not None and window - tolerance <= a["minutes_to_ko"] <= window]
        if asked:
            events.append(TimelineEvent(
                key=f"odds_{window}", label=label, at=asked[0]["asked_at"], state="skipped",
                detail=f"asked at T-{asked[0]['minutes_to_ko']} min: the provider had no prices for this match",
                code="window_provider_empty", vars={**wvars, "minutes": str(asked[0]["minutes_to_ko"])},
            ))
        else:
            events.append(TimelineEvent(key=f"odds_{window}", label=label, at=window_at, state="skipped",
                                        detail="window passed without a capture", code="window_missed", vars=wvars))
    extra = [c for c in prematch if c["captured_at"] not in in_window]
    for c in extra[:12]:
        events.append(TimelineEvent(
            key=f"extra_{c['minutes_to_ko']}", label="Odds capture", at=c["captured_at"], state="done",
            detail=f"{c['quotes']} quotes captured at T-{c['minutes_to_ko']} min (outside the planned windows)",
            code="extra_capture", vars={"quotes": str(c["quotes"]), "minutes": str(c["minutes_to_ko"])},
        ))
    if len(extra) > 12:
        events.append(TimelineEvent(
            key="extra_more", label="Odds captures", at=extra[-1]["captured_at"], state="done",
            detail=f"{len(extra) - 12} more captures outside the planned windows", code="extra_more",
            vars={"count": str(len(extra) - 12)}))
    live = [c for c in captures if c["source"] == "live"]
    near_at = kickoff - timedelta(minutes=settings.odds.odds_nearclose_window)
    if live:
        events.append(TimelineEvent(key="near_close", label="Near-close capture", at=live[-1]["captured_at"],
                                    state="done", detail=f"captured at T-{live[-1]['minutes_to_ko']} min (not a validated closing line)",
                                    code="near_close_done", vars={"minutes": str(live[-1]["minutes_to_ko"])}))
    elif not settings.odds.odds_capture_near_close:
        events.append(TimelineEvent(
            key="near_close", label="Near-close capture", at=None, state="skipped",
            detail="off by design: the closing reference is the provider's last pre-match price, read after the match",
            code="near_close_off"))
    else:
        events.append(TimelineEvent(
            key="near_close", label="Near-close capture", at=near_at,
            state="pending" if near_at > moment else "skipped",
            detail="scheduled" if near_at > moment else "no near-close capture was made",
            code="near_close_scheduled" if near_at > moment else "near_close_missed",
        ))
    phase = match_state.phase(row["status_short"], kickoff, moment)
    not_played = phase in (match_state.Phase.POSTPONED, match_state.Phase.CANCELLED, match_state.Phase.NOT_PLAYED)
    status_vars = {"status": str(row["status_short"])}
    if not_played:
        events.append(TimelineEvent(key="kickoff", label="Kick-off", at=kickoff, state="skipped",
                                    detail=f"{row['status_group']} ({row['status_short']})", code="kickoff_not_played",
                                    vars=status_vars))
    elif first_live is not None:
        events.append(TimelineEvent(key="kickoff", label="Kick-off", at=first_live, state="done",
                                    detail="seen in play", code="kickoff_seen"))
    elif row.get("goals_home") is not None:
        events.append(TimelineEvent(key="kickoff", label="Kick-off", at=kickoff, state="done",
                                    detail="played: the provider recorded a result", code="kickoff_by_result"))
    elif kickoff <= moment:
        events.append(TimelineEvent(key="kickoff", label="Kick-off", at=kickoff, state="pending",
                                    detail="kick-off time passed; the provider has not confirmed the start",
                                    code="kickoff_unconfirmed"))
    else:
        events.append(TimelineEvent(key="kickoff", label="Kick-off", at=kickoff, state="pending", detail="scheduled",
                                    code="kickoff_scheduled"))
    if final is not None:
        quotes = int(final["quotes"] or 0)
        events.append(TimelineEvent(
            key="final_prematch", label="Final pre-match prices", at=final["checked_at"],
            state="done" if quotes else "skipped",
            detail=(f"{quotes} last pre-match quotes from {final['bookmakers']} bookmakers (the closing reference)"
                    if quotes else f"read after the match: {final['outcome']}"),
            code="final_prematch" if quotes else "final_prematch_empty",
            vars={"quotes": str(quotes), "bookmakers": str(final["bookmakers"] or 0), "outcome": str(final["outcome"])},
        ))
    if row.get("goals_home") is not None:
        events.append(TimelineEvent(
            key="result", label="Result recorded", at=row["result_fetched_at"], state="done",
            detail=f"{row['goals_home']}-{row['goals_away']} ({row['status_short']})", code="result_recorded",
            vars={**status_vars, "score": f"{row['goals_home']}-{row['goals_away']}"},
        ))
    elif not_played:
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="skipped",
                                    detail="no result: the match was not played", code="result_not_played",
                                    vars=status_vars))
    elif phase is match_state.Phase.ABANDONED:
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="skipped",
                                    detail="no result: the match was abandoned", code="result_abandoned",
                                    vars=status_vars))
    elif phase is match_state.Phase.SUSPENDED:
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="pending",
                                    detail="suspended: waiting for the provider to resume or close it",
                                    code="result_suspended", vars=status_vars))
    elif wait in ("provider_pending", "provider_silent"):
        events.append(TimelineEvent(
            key="result", label="Result recorded", at=row.get("source_fetched_at"), state="pending",
            detail=(f"the provider still reports {row['status_short']}: waiting for it, asking again"
                    if wait == "provider_pending" else "no word from the provider since the match should have ended"),
            code=f"result_{wait}", vars=status_vars))
    elif wait is not None:
        events.append(TimelineEvent(
            key="result", label="Result recorded", at=None, state="failed",
            detail={"jobs_stalled": "our result jobs are not running",
                    "result_missing": "finished, but no score is stored",
                    "provider_conflict": "the provider contradicts itself (finished, with a kick-off ahead)"}.get(
                        wait, wait),
            code=f"result_{wait}", vars=status_vars))
    elif kickoff <= moment:
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="pending",
                                    detail="after full time", code="result_after_full_time"))
    else:
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="pending",
                                    detail="after full time", code="result_scheduled"))
    return events


def match_detail(conn: Conn, fixture_id: int) -> Envelope[MatchDetail]:
    row = repo.get_fixture(conn, fixture_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    moment = now()
    quotes = [quote(q) for q in repo.latest_quotes(conn, fixture_id)]
    predictions = [PredictionRow(**p) for p in repo.predictions_for(conn, fixture_id)]
    venue_row = repo.fixture_venue(conn, row)
    match = summary(row, moment, healthy=jobs_healthy(conn, moment))
    detail = MatchDetail(
        match=match,
        venue=VenueRef(**venue_row) if venue_row else None,
        lineage=_lineage(conn, row),
        markets=section(quotes) if quotes else section(quotes, status=DataStatus.EMPTY, reason=NO_MARKET_DATA,
                                                          code="no_market_data"),
        predictions=(
            section(predictions) if predictions
            else section(predictions, status=DataStatus.NOT_AVAILABLE, reason=NO_PREDICTION)
        ),
        timeline=timeline(row, repo.capture_instants(conn, fixture_id), moment,
                          asks=repo.odds_asks(conn, row["provider_fixture_id"]),
                          final=repo.final_prematch_check(conn, fixture_id),
                          first_live=repo.first_live_state(conn, fixture_id), wait=match.result_wait),
    )
    return Envelope[MatchDetail](status=DataStatus.OK, data=detail)


def match_view(conn: Conn, fixture_id: int) -> Envelope[MatchView]:
    row = repo.get_fixture(conn, fixture_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    quotes = [quote(q) for q in repo.latest_quotes(conn, fixture_id)]
    venue_row = repo.fixture_venue(conn, row)
    moment = now()
    view = MatchView(
        match=summary(row, moment, healthy=jobs_healthy(conn, moment)),
        venue=VenueRef(**venue_row) if venue_row else None,
        markets=section(quotes) if quotes else section(quotes, status=DataStatus.EMPTY, reason=NO_MARKET_DATA,
                                                          code="no_market_data"),
        price_status=price_status(conn, fixture_id, moment) if row["kickoff_at"] > moment else [],
    )
    return Envelope[MatchView](status=DataStatus.OK, data=view)


def price_status(conn: Conn, fixture_id: int, moment: datetime) -> list[MarketPriceStatus]:
    """Each core market's price status before kick-off, and the model's view where nothing is priced."""
    prices = market_prices(conn, [fixture_id], at=moment)
    views = {(v.market_key, v.line): v for v in no_price.watch(conn, [fixture_id], at=moment, prices=prices)}
    out = []
    for p in prices:
        v = views.get((p.market_key, p.line))
        out.append(MarketPriceStatus(
            market_key=p.market_key, line=p.line, status=p.status.value, bookmakers=p.bookmakers,
            last_capture=p.last_capture,
            model_view=None if v is None else ModelNoPriceView(
                status=v.status.value, selection=v.selection, probability=v.probability, fair_odds=v.fair_odds,
                min_odds=v.min_odds, model=v.model, rule_version=v.rule_version, evaluation_mode=v.evaluation_mode,
                data_cutoff_ts=v.data_cutoff_ts)))
    return out
