"""The product's records, read back: the day's board, a user's picks and parlays, the history.

Reads go through the API's read-only connection; the two writes (save a pick, build a
parlay) go through ``fbi.userdata`` with the signed-in user's id and nothing else.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fbi.api.cache import shared
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.records import (
    DailyBoard,
    DailyItem,
    DailySet,
    History,
    HistoryGroup,
    ItemAi,
    MatchRef,
    ParlayProgress,
    ParlayRecord,
    ParlayRecordLeg,
    SetSource,
    UserParlay,
    UserParlayLeg,
    UserPick,
)
from fbi.api.envelope import DataStatus, Envelope, listing, ok, unavailable
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one
from fbi.core.clock import now as clock_now
from fbi.picks.daily import DAY_TZ, product_day
from fbi.userdata import records as userdata

MATCH_COLS = """
       f.id AS m_fixture_id, f.kickoff_at AS m_kickoff_at, f.status_group AS m_status_group,
       c.id AS m_competition_id, c.name AS m_competition_name, c.country AS m_competition_country,
       c.logo_url AS m_competition_logo, c.flag_url AS m_competition_flag,
       th.id AS m_home_id, th.name AS m_home_name, th.logo_url AS m_home_logo,
       ta.id AS m_away_id, ta.name AS m_away_name, ta.logo_url AS m_away_logo,
       r.reg_goals_home AS m_score_home, r.reg_goals_away AS m_score_away
"""

MATCH_JOINS = """
  JOIN core.fixtures f ON f.id = {alias}.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
"""


def match_of(r: Row) -> MatchRef:
    return MatchRef(
        fixture_id=int(r["m_fixture_id"]), kickoff_at=r["m_kickoff_at"], status_group=r["m_status_group"],
        competition=CompetitionBadge(id=int(r["m_competition_id"]), name=r["m_competition_name"],
                                     country=r["m_competition_country"], logo_url=r["m_competition_logo"],
                                     flag_url=r["m_competition_flag"]),
        home=TeamBadge(id=int(r["m_home_id"]), name=r["m_home_name"], logo_url=r["m_home_logo"]),
        away=TeamBadge(id=int(r["m_away_id"]), name=r["m_away_name"], logo_url=r["m_away_logo"]),
        score_home=r["m_score_home"], score_away=r["m_score_away"])


SET_SQL = "SELECT * FROM picks.daily_sets WHERE day = %(day)s AND source = %(source)s"

ITEMS_SQL = """
SELECT i.*, b.name AS bookmaker, i.inputs->>'model' AS model, """ + MATCH_COLS + """
  FROM picks.daily_set_items i LEFT JOIN market.bookmakers b ON b.id = i.bookmaker_id
""" + MATCH_JOINS.format(alias="i") + """
 WHERE i.set_id = %(set)s ORDER BY i.rank
"""

PARLAY_SQL = "SELECT * FROM picks.parlays WHERE kind = %(kind)s AND day = %(day)s AND source = %(source)s"

LEGS_SQL = """
SELECT l.*, b.name AS bookmaker, """ + MATCH_COLS + """
  FROM picks.parlay_legs l LEFT JOIN market.bookmakers b ON b.id = l.bookmaker_id
""" + MATCH_JOINS.format(alias="l") + """
 WHERE l.parlay_id = %(parlay)s ORDER BY l.leg_no
"""


CLAIMS_SQL = "SELECT id, output FROM ai.pick_reviews WHERE id = ANY(%(ids)s)"
CLAIM_GROUPS = {"positives": ("positive_evidence",), "risks": ("negative_evidence", "contradictions", "uncertainties")}


def ai_items(conn: Conn, rows: list[Row], *, reveal: bool) -> dict[int, ItemAi]:
    """Each row's frozen AI review (``inputs.ai``) with the review's own claims, read in one query. Unless
    ``reveal`` (the owner's preview) or the review was enforced, only that a review happened is said: in shadow
    a user sees nothing the AI decided."""
    frozen = {i: (r.get("inputs") or {}).get("ai") for i, r in enumerate(rows)}
    ids = sorted({int(a["review_id"]) for a in frozen.values() if a and a.get("review_id")})
    claims: dict[int, dict[str, Any]] = {}
    if ids:
        claims = {int(c["id"]): dict(c["output"] or {}) for c in fetch_all(conn, CLAIMS_SQL, {"ids": ids})}
    out = {}
    for i, a in frozen.items():
        if not a:
            continue
        review = claims.get(int(a.get("review_id") or 0), {})
        texts = {k: [str(c.get("text")) for g in groups for c in review.get(g, []) if c.get("text")][:4]
                 for k, groups in CLAIM_GROUPS.items()}
        version = str(a.get("engine_version") or "")
        by_llm = bool(version) and not version.endswith("+none")
        enforced = bool(a.get("enforced"))
        if not reveal and not enforced:
            out[i] = ItemAi(decision=None, mode=a.get("mode") or "off", enforced=False, by_llm=by_llm)
            continue
        out[i] = ItemAi(decision=a.get("decision"), mode=a.get("mode") or "off", enforced=enforced,
                        review_id=a.get("review_id"), confidence=a.get("confidence"), reason=a.get("reason"),
                        by_llm=by_llm, positives=texts["positives"], risks=texts["risks"])
    return out


WON, LOST, VOIDED = frozenset({"WIN", "HALF_WIN"}), frozenset({"LOSS", "HALF_LOSS"}), frozenset({"VOID", "PUSH"})


def progress_of(status: str, legs: list[str]) -> ParlayProgress:
    """The parlay as the legs stand: a lost leg makes it lost at once, but it stays on the board, PARTIAL_LOST,
    until the other legs are played."""
    pending = sum(1 for s in legs if s == "PENDING")
    if status == "VOID" or (legs and all(s in VOIDED for s in legs)):
        return "VOID"
    if status == "LOST" or any(s in LOST for s in legs):
        return "PARTIAL_LOST" if pending else "LOST"
    if pending == 0 and legs:
        return "WON"
    if any(s in WON for s in legs):
        return "PARTIAL_WON"
    return "OPEN"


def _parlay(conn: Conn, kind: str, day: date, source: SetSource) -> ParlayRecord | None:
    p = fetch_one(conn, PARLAY_SQL, {"kind": kind, "day": day, "source": source})
    if p is None:
        return None
    rows = fetch_all(conn, LEGS_SQL, {"parlay": p["id"]})
    ai = ai_items(conn, rows, reveal=source == "evaluation")
    legs = [ParlayRecordLeg(
        leg_no=r["leg_no"], pick_id=r["pick_id"], match=match_of(r), market_key=r["market_key"],
        selection=r["selection"], line=r["line"], odds=r["odds"], bookmaker=r["bookmaker"], p_model=r["p_model"],
        p_low=r["p_low"], p_market=r["p_market"], ev=r["ev"], status=r["status"], ai=ai.get(i))
        for i, r in enumerate(rows)]
    statuses = [str(r["status"]) for r in rows]
    return ParlayRecord(
        id=p["id"], kind=p["kind"], day=p["day"], source=p["source"], rule_version=p["rule_version"],
        status=p["status"], min_legs=p["min_legs"], max_legs=p["max_legs"], window_from=p["window_from"],
        window_to=p["window_to"], combined_odds=p["combined_odds"], p_all_low=p["p_all_low"],
        expected_log_growth=p["expected_log_growth"], ready_at=p["ready_at"], settled_at=p["settled_at"],
        profit_units=p["profit_units"], legs=legs, progress=progress_of(str(p["status"]), statuses),
        legs_pending=sum(1 for x in statuses if x == "PENDING"))


@shared(30)
def daily_board(conn: Conn, *, day: date | None, include_shadow: bool, at: datetime | None = None
                ) -> Envelope[DailyBoard]:
    moment = at or clock_now()
    the_day = day or product_day(moment)
    source: SetSource = "evaluation" if include_shadow else "qualified"
    s = fetch_one(conn, SET_SQL, {"day": the_day, "source": source})
    daily_set = None
    if s is not None:
        rows = fetch_all(conn, ITEMS_SQL, {"set": s["id"]})
        ai = ai_items(conn, rows, reveal=include_shadow)
        items = [DailyItem(
            rank=r["rank"], pick_id=r["pick_id"], match=match_of(r), market_key=r["market_key"],
            selection=r["selection"], line=r["line"], stage=r["stage"], selected_at=r["selected_at"], odds=r["odds"],
            bookmaker=r["bookmaker"], price_at=r["price_at"], p_model=r["p_model"], p_low=r["p_low"],
            p_market=r["p_market"], ev=r["ev"], model=r["model"], status=r["status"],
            profit_units=r["profit_units"], settled_at=r["settled_at"], ai=ai.get(i))
            for i, r in enumerate(rows)]
        daily_set = DailySet(id=s["id"], day=s["day"], timezone=s["timezone"], source=s["source"],
                             rule_version=s["rule_version"], status=s["status"], items=items)
    board = DailyBoard(
        day=the_day, timezone=str(DAY_TZ), source=source, evaluation_mode=include_shadow, set=daily_set,
        daily_parlay=_parlay(conn, "daily", the_day, source), multiday_parlay=_parlay(conn, "multiday", the_day, source),
        reason=None if daily_set and daily_set.items else (
            "no_shadow_picks" if include_shadow else "no_qualified_picks"))
    return ok(board)


USER_PICKS_SQL = """
SELECT u.*, """ + MATCH_COLS + """
  FROM picks.user_picks u
""" + MATCH_JOINS.format(alias="u") + """
 WHERE u.user_id = %(user)s AND (%(status)s::text IS NULL OR (%(status)s = 'open' AND u.status = 'PENDING')
                                  OR (%(status)s = 'settled' AND u.status <> 'PENDING'))
 ORDER BY f.kickoff_at DESC, u.id DESC
 LIMIT %(limit)s
"""


def user_picks(conn: Conn, *, user_id: int, status: str | None, limit: int) -> Envelope[list[UserPick]]:
    rows = fetch_all(conn, USER_PICKS_SQL, {"user": user_id, "status": status, "limit": limit})
    out = [UserPick(
        id=r["id"], match=match_of(r), market_key=r["market_key"], selection=r["selection"], line=r["line"],
        origin=r["origin"], pick_id=r["pick_id"], odds=r["odds"], bookmaker=r["bookmaker"], price_at=r["price_at"],
        user_odds=r["user_odds"], saved_at=r["saved_at"], status=r["status"], profit_units=r["profit_units"],
        settled_at=r["settled_at"], snapshot=r["snapshot"]) for r in rows]
    return listing(out, empty_reason="You have not saved a pick yet.", total=len(out), limit=limit, offset=0)


USER_PARLAYS_SQL = """
SELECT p.* FROM picks.user_parlays p WHERE p.user_id = %(user)s ORDER BY p.created_at DESC LIMIT %(limit)s
"""

USER_LEGS_SQL = """
SELECT l.*, """ + MATCH_COLS + """
  FROM picks.user_parlay_legs l
""" + MATCH_JOINS.format(alias="l") + """
 WHERE l.user_parlay_id = ANY(%(ids)s) ORDER BY l.user_parlay_id, l.leg_no
"""


def user_parlays(conn: Conn, *, user_id: int, limit: int) -> Envelope[list[UserParlay]]:
    parlays = fetch_all(conn, USER_PARLAYS_SQL, {"user": user_id, "limit": limit})
    legs: dict[int, list[UserParlayLeg]] = defaultdict(list)
    if parlays:
        for r in fetch_all(conn, USER_LEGS_SQL, {"ids": [p["id"] for p in parlays]}):
            legs[int(r["user_parlay_id"])].append(UserParlayLeg(
                leg_no=r["leg_no"], match=match_of(r), market_key=r["market_key"], selection=r["selection"],
                line=r["line"], odds=r["odds"], status=r["status"]))
    out = [UserParlay(
        id=p["id"], name=p["name"], created_at=p["created_at"], combined_odds=p["combined_odds"], status=p["status"],
        profit_units=p["profit_units"], settled_at=p["settled_at"],
        warnings=list((p["validation"] or {}).get("warnings", [])), legs=legs[int(p["id"])]) for p in parlays]
    return listing(out, empty_reason="You have not built a parlay yet.", total=len(out), limit=limit, offset=0)


def history(conn: Conn, *, user_id: int, period: userdata.Period, tz: str, include_shadow: bool,
            at: datetime | None = None) -> Envelope[History]:
    moment = at or clock_now()
    since, until = userdata.period_bounds(period, at=moment, tz=tz)
    groups = userdata.history(conn, user_id=user_id, period=period, tz=tz, at=moment,
                              include_evaluation=include_shadow)
    body = History(period=period, timezone=tz, since=since, until=until, evaluation_mode=include_shadow, groups={
        name: HistoryGroup(total=g.total, pending=g.pending, won=g.won, lost=g.lost, push=g.push, void=g.void,
                           hit_rate=g.hit_rate, staked_units=g.staked, profit_units=g.profit.quantize(Decimal("0.01")),
                           roi=g.roi) for name, g in groups.items()})
    if sum(g.total for g in groups.values()) == 0:
        return unavailable(body, "nothing_in_period", status=DataStatus.EMPTY)
    return ok(body)
