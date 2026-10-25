"""Today, for Home (plan UX, A9; section 24 of the plan): the matches around today with PrediGol's forecast labelled and one line
of the reading, the leagues suggested until the reader picks theirs (favourites arrive with A13), and why there is no pick today.

One board for every reader, kept a minute (``shared``): picks, probabilities and states are the same for everyone; what a reader
follows will filter it on top (A13). Reading only: nothing here computes a probability, prices a selection or chooses a pick.

**Why there is no pick today** is said from the published set's own funnel (``fbi.picks.funnel``, the one the Admin Console
reads, run on the ``qualified`` source only): the furthest stage the day's selections reached and the commonest reason there.
The plan named ``intel.decisions`` as the source; that table is PrediGol Intelligence's own decision layer, in shadow, not the
rule that publishes the day's picks - a reason taken from it would describe another pipeline. Evaluation picks are never read
here, never counted and never named.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

from fbi.api.cache import shared
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.reading import ReadingFact
from fbi.api.contracts.today import NoPick, Today, TodayForecast, TodayMatch
from fbi.api.envelope import DataStatus, Envelope, Section, ok, section
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services import center, reading
from fbi.api.services import forecast as forecast_service
from fbi.core.clock import now
from fbi.picks import funnel
from fbi.picks.daily import (
    DAY_TZ,
    HORIZON,
    READY_BY,
    ai_view,
    load_candidates,
    passing,
    product_day,
)

WINDOW_BEFORE: Final = timedelta(hours=48)
"""Results: the last 48 hours (plan section 24, block 6)."""
WINDOW_AFTER: Final = timedelta(hours=36)
"""Enough for the reader's own today in any time zone."""
MAX_MATCHES: Final = 300
SUGGESTED_LEAGUES: Final = (239, 13, 2, 39, 140, 135, 78, 61)
"""The leagues suggested for a reader in Colombia until they pick theirs (plan section 24, «arranque en frío»): the Liga BetPlay
(Primera A), the Libertadores, the Champions League and the five big European leagues - by the provider's league id."""
SUGGESTED_TEAM: Final = "Colombia"
"""And the national team (the senior side: ``is_national`` and this exact name)."""
Outcome = Literal["home", "draw", "away"]
OUTCOME: Final[dict[str, Outcome]] = {"Home": "home", "Draw": "draw", "Away": "away"}
STAGE_ORDER: Final = ("selection", "context", "risk", "value", "calibration", "model", "market", "data")
"""The funnel's stages, deepest first: the reason of an empty day is told from the furthest stage its selections reached."""

MATCHES_SQL = """
SELECT f.id AS fixture_id, f.kickoff_at, f.status_group, f.status_short, r.goals_home AS final_home,
       r.goals_away AS final_away, c.provider_league_id, c.tier,
       f.home_team_id, th.name AS home_name, th.logo_url AS home_logo, th.is_national AS home_national,
       f.away_team_id, ta.name AS away_name, ta.logo_url AS away_logo, ta.is_national AS away_national,
       c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE c.is_tracked AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
 ORDER BY f.kickoff_at, c.tier NULLS LAST, f.id
 LIMIT %(limit)s
"""

SUGGESTED_SQL = """
SELECT c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag
  FROM core.competitions c
 WHERE c.is_tracked AND c.provider_league_id = ANY(%(leagues)s)
 ORDER BY array_position(%(leagues)s, c.provider_league_id), c.id
"""

DAY_MATCHES_SQL = """
SELECT count(*)::int AS n
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
"""

DAY_SET_SQL = """
SELECT count(i.rank)::int AS items
  FROM picks.daily_sets s LEFT JOIN picks.daily_set_items i ON i.set_id = s.id
 WHERE s.day = %(day)s AND s.source = 'qualified'
"""


def _competition(r: dict[str, Any]) -> CompetitionBadge:
    return CompetitionBadge(id=int(r["competition_id"]), name=r["competition_name"], country=r["competition_country"],
                            logo_url=r["competition_logo"], flag_url=r["competition_flag"])


def _suggested(r: dict[str, Any]) -> bool:
    if r["provider_league_id"] is not None and int(r["provider_league_id"]) in SUGGESTED_LEAGUES:
        return True
    return any(r[f"{side}_national"] is True and r[f"{side}_name"] == SUGGESTED_TEAM for side in ("home", "away"))


def _forecast(found: tuple[str, Decimal, str] | None) -> TodayForecast | None:
    if found is None or found[0] not in OUTCOME:
        return None
    selection, p, calibration = found
    return TodayForecast(outcome=OUTCOME[selection], probability=p.quantize(Decimal("0.001")),
                         calibrated=calibration == "CALIBRATED")


def _headline(fact: reading.Fact | None) -> ReadingFact | None:
    return None if fact is None else ReadingFact(code=fact.code, params=fact.params, ref=fact.ref)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=DAY_TZ)
    return start, start + timedelta(days=1)


def deepest(stages: Sequence[funnel.Stage]) -> tuple[str | None, str | None]:
    """The furthest stage the selections reached and its commonest reason (pure): a stage counts when something entered it.
    The first-come order of ``Counter.most_common`` breaks a tie, as the Admin Console's funnel shows them."""
    by_key = {s.key: s for s in stages}
    for key in STAGE_ORDER:
        stage = by_key.get(key)
        if stage is not None and stage.entered > 0:
            common = stage.reasons.most_common(1)
            return key, (common[0][0] if common else None)
    return None, None


@shared(300)
def no_pick(conn: Conn, *, at: datetime | None = None) -> Section[NoPick]:
    """Why the day has no published pick - or that it has some. Kept five minutes: it reruns the published set's funnel."""
    moment = at or now()
    day = product_day(moment)
    start, end = _day_bounds(day)
    matches = int((fetch_one(conn, DAY_MATCHES_SQL, {"start": start, "end": end}) or {}).get("n") or 0)
    items = int((fetch_one(conn, DAY_SET_SQL, {"day": day}) or {}).get("items") or 0)
    if items > 0:
        return section(NoPick(day=day, state="picks", stage=None, reason=None, matches=matches))
    if matches == 0:
        return section(NoPick(day=day, state="none", stage=None, reason="no_matches", matches=0))
    rows = [r for r in load_candidates(conn, at=moment, until=moment + HORIZON, include_shadow=False)
            if product_day(r["kickoff_at"]) == day]
    if not rows:
        return section(NoPick(day=day, state="none", stage=None, reason="no_qualified_candidates", matches=matches))
    ai = ai_view(conn, passing(rows, at=moment, source="qualified"), at=moment)
    if day not in ai.days_ready and moment.astimezone(DAY_TZ).time() < READY_BY:
        return section(NoPick(day=day, state="reviewing", stage=None, reason=None, matches=matches))
    report = funnel.report(rows, at=moment, source="qualified", ai=ai, taken={day: set()})
    stage, reason = deepest(report.stages)
    return section(NoPick(day=day, state="none", stage=stage, reason=reason, matches=matches))


@shared(60)
def today(conn: Conn, *, at: datetime | None = None) -> Envelope[Today]:
    moment = at or now()
    rows = fetch_all(conn, MATCHES_SQL, {"since": moment - WINDOW_BEFORE, "until": moment + WINDOW_AFTER,
                                         "limit": MAX_MATCHES})
    ids = [int(r["fixture_id"]) for r in rows]
    likely = forecast_service.likely_results(conn, ids, at=at)
    lines = reading.headlines(conn, ids, at=at)
    live = {m.fixture_id: m for m in center.live_board(conn, at=at).data.matches} if any(
        r["status_group"] == "live" for r in rows) else {}
    matches: list[TodayMatch] = []
    for r in rows:
        fid = int(r["fixture_id"])
        state = live.get(fid)
        finished = r["status_group"] == "finished" and r["final_home"] is not None
        matches.append(TodayMatch(
            fixture_id=fid, kickoff_at=r["kickoff_at"], status_group=str(r["status_group"]),
            status=state.status if state is not None else r["status_short"],
            elapsed=state.elapsed if state is not None else None,
            goals_home=state.goals_home if state is not None else (int(r["final_home"]) if finished else None),
            goals_away=state.goals_away if state is not None else (int(r["final_away"]) if finished else None),
            competition=_competition(r),
            home=TeamBadge(id=int(r["home_team_id"]), name=r["home_name"], logo_url=r["home_logo"]),
            away=TeamBadge(id=int(r["away_team_id"]), name=r["away_name"], logo_url=r["away_logo"]),
            suggested=_suggested(r), forecast=_forecast(likely.get(fid)), headline=_headline(lines.get(fid)),
            has_reading=fid in lines))
    suggested = [_competition(r) for r in fetch_all(conn, SUGGESTED_SQL, {"leagues": list(SUGGESTED_LEAGUES)})]
    body = Today(
        day=product_day(moment), suggested=suggested, suggested_team=SUGGESTED_TEAM,
        matches=(section(matches) if matches else section(
            matches, status=DataStatus.EMPTY, code="no_matches",
            reason="No match of the followed competitions in the last 48 hours or the next 36.")),
        no_pick=no_pick(conn, at=at))
    return ok(body, count=len(matches))
