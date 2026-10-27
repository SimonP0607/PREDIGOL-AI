"""The product's records, read back: the day's board, a user's picks and parlays, the history.

Reads go through the API's read-only connection; the two writes (save a pick, build a
parlay) go through ``fbi.userdata`` with the signed-in user's id and nothing else.
"""

from __future__ import annotations

import base64
import re
from collections import defaultdict
from collections.abc import Hashable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fbi.api.cache import shared
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.records import (
    AiLatest,
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
    ResultCorrection,
    SetSource,
    UserParlay,
    UserParlayLeg,
    UserPick,
)
from fbi.api.envelope import DataStatus, Envelope, listing, ok, unavailable
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one
from fbi.core import match_state
from fbi.core.clock import now as clock_now
from fbi.picks import user_status
from fbi.picks.daily import DAY_TZ, product_day
from fbi.userdata import records as userdata

MATCH_COLS = """
       f.id AS m_fixture_id, f.kickoff_at AS m_kickoff_at, f.status_group AS m_status_group,
       c.id AS m_competition_id, c.name AS m_competition_name, c.country AS m_competition_country,
       c.logo_url AS m_competition_logo, c.flag_url AS m_competition_flag,
       th.id AS m_home_id, th.name AS m_home_name, th.logo_url AS m_home_logo,
       ta.id AS m_away_id, ta.name AS m_away_name, ta.logo_url AS m_away_logo,
       r.reg_goals_home AS m_score_home, r.reg_goals_away AS m_score_away, f.status_short AS m_status_short,
       ls.elapsed AS m_live_minute, ls.extra AS m_live_extra, ls.goals_home AS m_live_home,
       ls.goals_away AS m_live_away, ls.observed_at AS m_live_at
"""

MATCH_JOINS = """
  JOIN core.fixtures f ON f.id = {alias}.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
  LEFT JOIN LATERAL (
      SELECT s.elapsed, s.extra, s.goals_home, s.goals_away, s.observed_at FROM core.fixture_live_states s
       WHERE s.fixture_id = f.id ORDER BY s.observed_at DESC LIMIT 1) ls ON true
"""


def match_of(r: Row, at: datetime | None = None) -> MatchRef:
    """A record's match: its state as every screen shows it (fbi.core.match_state) and, while it is played, the
    minute and the score of the newest live observation."""
    moment = at or clock_now()
    phase = match_state.phase(r.get("m_status_short"), r["m_kickoff_at"], moment)
    playing = phase is match_state.Phase.LIVE or phase is match_state.Phase.SUSPENDED
    return MatchRef(
        fixture_id=int(r["m_fixture_id"]), kickoff_at=r["m_kickoff_at"], status_group=r["m_status_group"],
        competition=CompetitionBadge(id=int(r["m_competition_id"]), name=r["m_competition_name"],
                                     country=r["m_competition_country"], logo_url=r["m_competition_logo"],
                                     flag_url=r["m_competition_flag"]),
        home=TeamBadge(id=int(r["m_home_id"]), name=r["m_home_name"], logo_url=r["m_home_logo"]),
        away=TeamBadge(id=int(r["m_away_id"]), name=r["m_away_name"], logo_url=r["m_away_logo"]),
        score_home=r["m_score_home"], score_away=r["m_score_away"],
        status_short=r.get("m_status_short"), phase=phase.value,
        live_minute=r.get("m_live_minute") if playing else None, live_extra=r.get("m_live_extra") if playing else None,
        live_home=r.get("m_live_home") if playing else None, live_away=r.get("m_live_away") if playing else None,
        live_at=r.get("m_live_at") if playing else None)


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

LATEST_SQL = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
       r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at, r.decision, r.confidence, r.engine_version,
       r.output->>'summary' AS reason
  FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.engine = 'combined' AND r.fixture_id = ANY(%(fixtures)s) AND r.reviewed_at < f.kickoff_at
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""


def ai_latest(conn: Conn, rows: list[Row], *, reveal: bool) -> dict[int, AiLatest]:
    """Each row's newest pre-kick-off combined review (fbi.ai), in one query; the decision only when ``reveal``
    (the owner's preview) - in shadow a user sees only that the selection was reviewed."""
    fixtures = sorted({int(r["fixture_id"]) for r in rows})
    if not fixtures:
        return {}
    found = {(int(x["fixture_id"]), x["market_key"], x["selection"], Decimal(x["line"])): x
             for x in fetch_all(conn, LATEST_SQL, {"fixtures": fixtures})}
    out: dict[int, AiLatest] = {}
    for i, r in enumerate(rows):
        x = found.get((int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"])))
        if x is None:
            continue
        version = str(x.get("engine_version") or "")
        by_llm = bool(version) and not version.endswith("+none")
        if not reveal:
            out[i] = AiLatest(reviewed_at=x["reviewed_at"], by_llm=by_llm)
            continue
        out[i] = AiLatest(reviewed_at=x["reviewed_at"], decision=x["decision"], confidence=x["confidence"],
                          reason=x.get("reason"), by_llm=by_llm)
    return out
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


CORRECTIONS_SQL = """
SELECT r.id, r.record_kind, r.record_key, r.at, r.from_status, r.to_status, r.from_profit, r.to_profit,
       CASE WHEN v.id IS NULL THEN 'audit' WHEN v.kind = 'status' THEN 'status_changed'
            ELSE 'result_corrected' END AS cause
  FROM unnest(%(kinds)s::text[], %(keys)s::text[]) AS w(kind, key)
  JOIN picks.resettlements r ON r.record_kind = w.kind AND r.record_key = w.key
  LEFT JOIN core.fixture_result_revisions v ON v.id = r.revision_id
"""
LEG_KINDS = frozenset({"parlay_leg", "user_parlay_leg"})


def corrections(conn: Conn, shown: Mapping[Hashable, Sequence[tuple[str, str]]]
                ) -> dict[Hashable, list[ResultCorrection]]:
    """What each record being shown had been before its match was corrected (fbi.picks.resettlement), oldest first,
    in one query. ``shown`` maps whatever the caller shows (any key) to the (record kind, record key) of the trail
    rows that belong to it - a parlay's own and its legs'. Only records the caller is already showing are asked for,
    so a person's own corrections are never looked up by anything but their own records. Records never corrected
    have no entry."""
    wanted = sorted({pair for pairs in shown.values() for pair in pairs})
    if not wanted:
        return {}
    by_record: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in fetch_all(conn, CORRECTIONS_SQL, {"kinds": [k for k, _ in wanted], "keys": [key for _, key in wanted]}):
        by_record[(r["record_kind"], r["record_key"])].append(r)
    out: dict[Hashable, list[ResultCorrection]] = {}
    for ident, pairs in shown.items():
        rows = sorted((r for pair in pairs for r in by_record.get(pair, ())), key=lambda r: (r["at"], r["id"]))
        if rows:
            out[ident] = [ResultCorrection(
                at=r["at"], leg_no=int(r["record_key"].rsplit("/", 1)[1]) if r["record_kind"] in LEG_KINDS else None,
                from_status=r["from_status"], to_status=r["to_status"], from_profit=r["from_profit"],
                to_profit=r["to_profit"], cause=r["cause"]) for r in rows]
    return out


def parlay_trail(kind: str, parlay_id: int, leg_nos: Sequence[int]) -> list[tuple[str, str]]:
    """The trail rows of a parlay and of its legs: ``kind`` is 'parlay' or 'user_parlay'."""
    return [(kind, str(parlay_id)), *((f"{kind}_leg", f"{parlay_id}/{n}") for n in leg_nos)]


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
    latest = ai_latest(conn, rows, reveal=source == "evaluation")
    trail = corrections(conn, {0: parlay_trail("parlay", int(p["id"]), [int(r["leg_no"]) for r in rows])})
    legs = [ParlayRecordLeg(
        leg_no=r["leg_no"], pick_id=r["pick_id"], match=match_of(r), market_key=r["market_key"],
        selection=r["selection"], line=r["line"], odds=r["odds"], bookmaker=r["bookmaker"], p_model=r["p_model"],
        p_low=r["p_low"], p_market=r["p_market"], ev=r["ev"], status=r["status"], ai=ai.get(i),
        ai_latest=latest.get(i))
        for i, r in enumerate(rows)]
    statuses = [str(r["status"]) for r in rows]
    return ParlayRecord(
        id=p["id"], kind=p["kind"], day=p["day"], source=p["source"], rule_version=p["rule_version"],
        status=p["status"], min_legs=p["min_legs"], max_legs=p["max_legs"], window_from=p["window_from"],
        window_to=p["window_to"], combined_odds=p["combined_odds"], p_all_low=p["p_all_low"],
        expected_log_growth=p["expected_log_growth"], ready_at=p["ready_at"], settled_at=p["settled_at"],
        profit_units=p["profit_units"], legs=legs, progress=progress_of(str(p["status"]), statuses),
        legs_pending=sum(1 for x in statuses if x == "PENDING"), corrections=trail.get(0, []))


def item_state(r: Row, source: SetSource) -> user_status.Shown:
    """A pick of the day's state as it stood when it entered the set (plan UX, B3): its price then passed the value rule, and the
    AI review frozen with it (``inputs.ai``) counts only if it was applied then. The evaluation set is EVALUATION."""
    frozen = (r.get("inputs") or {}).get("ai") or {}
    return user_status.shown(published=source == "qualified", value=True, review=frozen.get("decision"),
                             applied=bool(frozen.get("enforced")))


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
        latest = ai_latest(conn, rows, reveal=include_shadow)
        trail = corrections(conn, {r["rank"]: [("daily_item", f"{s['id']}/{r['rank']}")] for r in rows})
        states = [item_state(r, source) for r in rows]
        items = [DailyItem(
            rank=r["rank"], pick_id=r["pick_id"], match=match_of(r, moment), market_key=r["market_key"],
            selection=r["selection"], line=r["line"], stage=r["stage"], selected_at=r["selected_at"], odds=r["odds"],
            bookmaker=r["bookmaker"], price_at=r["price_at"], p_model=r["p_model"], p_low=r["p_low"],
            p_market=r["p_market"], ev=r["ev"], model=r["model"], status=r["status"],
            profit_units=r["profit_units"], settled_at=r["settled_at"], ai=ai.get(i), ai_latest=latest.get(i),
            corrections=trail.get(r["rank"], []), user_status=states[i].status, status_reason=states[i].reason,
            context_pending=states[i].context_pending)
            for i, r in enumerate(rows)]
        daily_set = DailySet(id=s["id"], day=s["day"], timezone=s["timezone"], source=s["source"],
                             rule_version=s["rule_version"], status=s["status"], items=items)
    board = DailyBoard(
        day=the_day, timezone=str(DAY_TZ), source=source, evaluation_mode=include_shadow, set=daily_set,
        daily_parlay=_parlay(conn, "daily", the_day, source), multiday_parlay=_parlay(conn, "multiday", the_day, source),
        reason=None if daily_set and daily_set.items else (
            "no_shadow_picks" if include_shadow else "no_qualified_picks"))
    return ok(board)


# A user's own lists are read page by page (plan UX, A1: "Todo" was cut at 500 picks and 200 parlays and called
# everything). The cursor is the position of the last record of a page in the list's order - picks by kick-off, parlays
# by creation, the id breaking ties, newest first - so a page never repeats or skips a record, whatever is saved in
# between. It is opaque to the client: base64url of "c1|<list>|<timestamp>|<id>".
CURSOR_RE = re.compile(r"^c1\|(?P<kind>[pl])\|(?P<at>\d{4}-\d\d-\d\dT[0-9:.+\-]+)\|(?P<id>\d{1,18})$")


class CursorError(ValueError):
    """A cursor this API did not write."""


def encode_cursor(kind: str, at: datetime, record_id: int) -> str:
    raw = f"c1|{kind}|{at.isoformat()}|{record_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(kind: str, cursor: str | None) -> tuple[datetime | None, int | None]:
    if cursor is None:
        return None, None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise CursorError("not a cursor of this list") from exc
    found = CURSOR_RE.match(raw)
    if found is None or found["kind"] != kind:
        raise CursorError("not a cursor of this list")
    try:
        at = datetime.fromisoformat(found["at"])
    except ValueError as exc:
        raise CursorError("not a cursor of this list") from exc
    if at.tzinfo is None:
        raise CursorError("not a cursor of this list")
    return at, int(found["id"])


USER_PICKS_FILTER = """
 WHERE u.user_id = %(user)s AND (%(status)s::text IS NULL OR (%(status)s = 'open' AND u.status = 'PENDING')
                                  OR (%(status)s = 'settled' AND u.status <> 'PENDING'))
"""

USER_PICKS_SQL = """
SELECT u.*, """ + MATCH_COLS + """
  FROM picks.user_picks u
""" + MATCH_JOINS.format(alias="u") + USER_PICKS_FILTER + """
   AND (%(after_at)s::timestamptz IS NULL OR (f.kickoff_at, u.id) < (%(after_at)s::timestamptz, %(after_id)s::bigint))
 ORDER BY f.kickoff_at DESC, u.id DESC
 LIMIT %(limit)s
"""

USER_PICKS_TOTAL_SQL = "SELECT count(*) AS n FROM picks.user_picks u" + USER_PICKS_FILTER


USER_PICKS_OF_FIXTURE_SQL = """
SELECT u.*, """ + MATCH_COLS + """
  FROM picks.user_picks u
""" + MATCH_JOINS.format(alias="u") + """
 WHERE u.user_id = %(user)s AND u.fixture_id = %(fixture)s
 ORDER BY u.saved_at, u.id
"""
"""What one reader saved on one match (plan UX, B4: the Postpartido says how each ended)."""


def _user_picks_of(conn: Conn, rows: list[Row]) -> list[UserPick]:
    trail = corrections(conn, {r["id"]: [("user_pick", str(r["id"]))] for r in rows})
    return [UserPick(
        id=r["id"], match=match_of(r), market_key=r["market_key"], selection=r["selection"], line=r["line"],
        origin=r["origin"], pick_id=r["pick_id"], odds=r["odds"], bookmaker=r["bookmaker"], price_at=r["price_at"],
        user_odds=r["user_odds"], saved_at=r["saved_at"], status=r["status"], profit_units=r["profit_units"],
        settled_at=r["settled_at"], snapshot=r["snapshot"], corrections=trail.get(r["id"], [])) for r in rows]


def user_picks_of_fixture(conn: Conn, *, user_id: int, fixture_id: int) -> list[UserPick]:
    """Every pick one reader saved on one match, oldest first, with its result and corrections (the same as Mis picks shows)."""
    return _user_picks_of(conn, fetch_all(conn, USER_PICKS_OF_FIXTURE_SQL, {"user": user_id, "fixture": fixture_id}))


def user_picks(conn: Conn, *, user_id: int, status: str | None, limit: int,
               cursor: str | None = None) -> Envelope[list[UserPick]]:
    after_at, after_id = decode_cursor("p", cursor)
    rows = fetch_all(conn, USER_PICKS_SQL, {"user": user_id, "status": status, "limit": limit + 1,
                                            "after_at": after_at, "after_id": after_id})
    more = len(rows) > limit
    rows = rows[:limit]
    total = fetch_one(conn, USER_PICKS_TOTAL_SQL, {"user": user_id, "status": status})
    out = _user_picks_of(conn, rows)
    next_cursor = encode_cursor("p", rows[-1]["m_kickoff_at"], int(rows[-1]["id"])) if more else None
    n = int(total["n"]) if total else 0
    # An empty page past the last one is not an empty list (review of A1): it says so.
    return listing(out, empty_reason="You have not saved a pick yet." if n == 0 else "No more picks after this one.",
                   total=n, limit=limit, offset=0 if cursor is None else None, next_cursor=next_cursor)


USER_PARLAYS_SQL = """
SELECT p.* FROM picks.user_parlays p
 WHERE p.user_id = %(user)s
   AND (%(after_at)s::timestamptz IS NULL OR (p.created_at, p.id) < (%(after_at)s::timestamptz, %(after_id)s::bigint))
 ORDER BY p.created_at DESC, p.id DESC LIMIT %(limit)s
"""

USER_PARLAYS_TOTAL_SQL = "SELECT count(*) AS n FROM picks.user_parlays p WHERE p.user_id = %(user)s"

USER_LEGS_SQL = """
SELECT l.*, """ + MATCH_COLS + """
  FROM picks.user_parlay_legs l
""" + MATCH_JOINS.format(alias="l") + """
 WHERE l.user_parlay_id = ANY(%(ids)s) ORDER BY l.user_parlay_id, l.leg_no
"""


def user_parlays(conn: Conn, *, user_id: int, limit: int, cursor: str | None = None) -> Envelope[list[UserParlay]]:
    after_at, after_id = decode_cursor("l", cursor)
    parlays = fetch_all(conn, USER_PARLAYS_SQL, {"user": user_id, "limit": limit + 1, "after_at": after_at,
                                                 "after_id": after_id})
    more = len(parlays) > limit
    parlays = parlays[:limit]
    total = fetch_one(conn, USER_PARLAYS_TOTAL_SQL, {"user": user_id})
    legs: dict[int, list[UserParlayLeg]] = defaultdict(list)
    if parlays:
        for r in fetch_all(conn, USER_LEGS_SQL, {"ids": [p["id"] for p in parlays]}):
            legs[int(r["user_parlay_id"])].append(UserParlayLeg(
                leg_no=r["leg_no"], match=match_of(r), market_key=r["market_key"], selection=r["selection"],
                line=r["line"], odds=r["odds"], status=r["status"]))
    trail = corrections(conn, {p["id"]: parlay_trail("user_parlay", int(p["id"]), [x.leg_no for x in legs[int(p["id"])]])
                               for p in parlays})
    out = [UserParlay(
        id=p["id"], name=p["name"], created_at=p["created_at"], combined_odds=p["combined_odds"], status=p["status"],
        profit_units=p["profit_units"], settled_at=p["settled_at"],
        warnings=list((p["validation"] or {}).get("warnings", [])), legs=legs[int(p["id"])],
        corrections=trail.get(p["id"], [])) for p in parlays]
    next_cursor = encode_cursor("l", parlays[-1]["created_at"], int(parlays[-1]["id"])) if more else None
    n = int(total["n"]) if total else 0
    return listing(out, empty_reason="You have not built a parlay yet." if n == 0 else "No more parlays after this one.",
                   total=n, limit=limit, offset=0 if cursor is None else None, next_cursor=next_cursor)


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
