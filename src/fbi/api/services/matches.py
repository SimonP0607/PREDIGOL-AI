"""Match list and Match Center."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException

from fbi.api.contracts.common import CompetitionRef, Lineage, Score, TeamRef, VenueRef
from fbi.api.contracts.matches import (
    MarketQuote,
    MatchDetail,
    MatchSummary,
    MatchView,
    OddsSummary,
    PredictionRow,
    TimelineEvent,
)
from fbi.api.envelope import DataStatus, Envelope, listing, section
from fbi.api.repositories import Conn, Row
from fbi.api.repositories import fixtures as repo
from fbi.core.clock import now
from fbi.core.config import settings

NO_MARKET_DATA = "No captured market data yet."
NO_PREDICTION = "No model has produced a prediction for this match yet."
FREE_PLAN_HORIZON_MIN = 1440
"""On the free plan a fixture is visible only about a day ahead, so a window
further out than this cannot be captured - it is not missed, it is unreachable."""


STILL_SCHEDULED_AFTER = timedelta(minutes=15)
STILL_LIVE_AFTER = timedelta(hours=3, minutes=30)


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


def summary(row: Row, at: datetime | None = None) -> MatchSummary:
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
    )


def list_matches(
    conn: Conn, flt: repo.FixtureFilter, *, limit: int, offset: int, order: Literal["asc", "desc"]
) -> Envelope[list[MatchSummary]]:
    rows, total = repo.list_fixtures(conn, flt, limit=limit, offset=offset, order=order)
    moment = now()
    items = [summary(r, moment) for r in rows]
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


def timeline(row: Row, captures: list[Row], at: datetime | None = None) -> list[TimelineEvent]:
    """What happened to this fixture, in order, as far as the system observed it.

    A capture window is 'done' only if a snapshot actually fell inside it. A
    window that passed without one is 'skipped' and says so; a window the plan
    could never reach is 'skipped' with that reason instead - it was not
    missed. Nothing here is inferred from a timestamp alone.
    """
    moment = at or now()
    kickoff: datetime = row["kickoff_at"]
    tolerance = settings.odds.odds_window_tolerance
    free_plan = settings.provider_plan.plan == "free"
    events = [TimelineEvent(
        key="discovered", label="Fixture discovered", at=row["created_at"], state="done",
        detail=f"first ingested from the provider (fixture {row['provider_fixture_id']})",
    )]
    prematch = [c for c in captures if c["source"] == "prematch"]
    for window in settings.odds.prematch_windows:
        window_at = kickoff - timedelta(minutes=window)
        hits = [c for c in prematch if window - tolerance <= c["minutes_to_ko"] <= window]
        label = f"Odds T-{window // 60}h" if window % 60 == 0 else f"Odds T-{window}m"
        if hits:
            first = hits[0]
            events.append(TimelineEvent(
                key=f"odds_{window}", label=label, at=first["captured_at"], state="done",
                detail=f"{sum(int(h['quotes']) for h in hits)} quotes captured at T-{first['minutes_to_ko']} min",
            ))
        elif free_plan and window > FREE_PLAN_HORIZON_MIN:
            events.append(TimelineEvent(
                key=f"odds_{window}", label=label, at=None, state="skipped",
                detail="not reachable on the free plan: fixtures are visible only about a day ahead",
            ))
        elif window_at > moment:
            events.append(TimelineEvent(
                key=f"odds_{window}", label=label, at=window_at, state="pending", detail="scheduled",
            ))
        else:
            events.append(TimelineEvent(
                key=f"odds_{window}", label=label, at=window_at, state="skipped",
                detail="window passed without a capture",
            ))
    live = [c for c in captures if c["source"] == "live"]
    near_at = kickoff - timedelta(minutes=settings.odds.odds_nearclose_window)
    if live:
        events.append(TimelineEvent(key="near_close", label="Near-close capture", at=live[-1]["captured_at"],
                                    state="done", detail=f"captured at T-{live[-1]['minutes_to_ko']} min (not a validated closing line)"))
    else:
        events.append(TimelineEvent(
            key="near_close", label="Near-close capture", at=near_at,
            state="pending" if near_at > moment else "skipped",
            detail="scheduled" if near_at > moment else "no near-close capture was made",
        ))
    status_group = row["status_group"]
    if status_group in ("postponed", "cancelled"):
        events.append(TimelineEvent(key="kickoff", label="Kick-off", at=kickoff, state="skipped",
                                    detail=f"{status_group} ({row['status_short']})"))
    else:
        events.append(TimelineEvent(key="kickoff", label="Kick-off", at=kickoff,
                                    state="done" if kickoff <= moment else "pending",
                                    detail="kicked off" if kickoff <= moment else "scheduled"))
    if row.get("goals_home") is not None:
        events.append(TimelineEvent(
            key="result", label="Result recorded", at=row["result_fetched_at"], state="done",
            detail=f"{row['goals_home']}-{row['goals_away']} ({row['status_short']})",
        ))
    elif status_group in ("postponed", "cancelled"):
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="skipped",
                                    detail="no result: the match was not played"))
    elif kickoff <= moment:
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="failed",
                                    detail="kicked off, but no result has been recorded"))
    else:
        events.append(TimelineEvent(key="result", label="Result recorded", at=None, state="pending",
                                    detail="after full time"))
    return events


def match_detail(conn: Conn, fixture_id: int) -> Envelope[MatchDetail]:
    row = repo.get_fixture(conn, fixture_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    moment = now()
    quotes = [quote(q) for q in repo.latest_quotes(conn, fixture_id)]
    predictions = [PredictionRow(**p) for p in repo.predictions_for(conn, fixture_id)]
    venue_row = repo.get_venue(conn, row["venue_id"]) if row["venue_id"] else None
    detail = MatchDetail(
        match=summary(row, moment),
        venue=VenueRef(**venue_row) if venue_row else None,
        lineage=_lineage(conn, row),
        markets=section(quotes) if quotes else section(quotes, status=DataStatus.EMPTY, reason=NO_MARKET_DATA),
        predictions=(
            section(predictions) if predictions
            else section(predictions, status=DataStatus.NOT_AVAILABLE, reason=NO_PREDICTION)
        ),
        timeline=timeline(row, repo.capture_instants(conn, fixture_id), moment),
    )
    return Envelope[MatchDetail](status=DataStatus.OK, data=detail)


def match_view(conn: Conn, fixture_id: int) -> Envelope[MatchView]:
    row = repo.get_fixture(conn, fixture_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    quotes = [quote(q) for q in repo.latest_quotes(conn, fixture_id)]
    venue_row = repo.get_venue(conn, row["venue_id"]) if row["venue_id"] else None
    view = MatchView(
        match=summary(row, now()),
        venue=VenueRef(**venue_row) if venue_row else None,
        markets=section(quotes) if quotes else section(quotes, status=DataStatus.EMPTY, reason=NO_MARKET_DATA),
    )
    return Envelope[MatchView](status=DataStatus.OK, data=view)
