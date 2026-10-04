"""Saving a pick, building a parlay, and the user's history - USER_PICK_HISTORY_SPEC.

* A saved pick is a SNAPSHOT: the best price we showed for that selection when the user
  saved it (bookmaker, instant, the market's fair probability, and - when it was one of
  PrediGol's picks - the model's numbers). The user may add the price they actually got at
  their own bookmaker; settlement and profit use that price when given, ours otherwise.
  A pick can be removed until its match starts; after that it is history.
* A user's parlay is validated before it is stored: 2 to 10 legs, one leg per match (two
  selections on one match are dependent), no quarter lines (a half-won leg has no clean
  meaning inside a parlay), every match still to start. A team appearing in two legs is
  allowed with a warning: two matches of one team share its news.
* History groups four kinds of record - PrediGol's picks (the daily set), the user's picks,
  PrediGol's parlays, the user's parlays - over today, the last 7 days, the last 30 days or
  everything, by the day the match kicks off in the user's own time zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.picks.settlement import market_outcome

MIN_LEGS, MAX_LEGS = 2, 10
SNAPSHOT_LOOKBACK = timedelta(hours=36)
Period = Literal["today", "7d", "30d", "all"]


class RecordError(ValueError):
    """A request the rules refuse; ``code`` is stable for the API and the UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def valid_selection(market_key: str, selection: str, line: Decimal) -> bool:
    try:
        market_outcome(market_key, selection, line, 0, 0)
    except ValueError:
        return False
    return True


def quarter_line(line: Decimal) -> bool:
    return abs(line * 4) % 2 == 1


FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_group, f.home_team_id, f.away_team_id FROM core.fixtures f WHERE f.id = %s
"""

PRICE_SQL = """
SELECT m.best_odds, b.name AS bookmaker, m.as_of, m.p_fair, m.n_bookmakers
  FROM market.market_consensus m LEFT JOIN market.bookmakers b ON b.id = m.best_bookmaker_id
 WHERE m.fixture_id = %(fixture)s AND m.market_key = %(market)s AND m.selection = %(selection)s
   AND m.line = %(line)s AND m.devig_method = 'shin' AND m.as_of <= %(at)s AND m.as_of >= %(since)s
 ORDER BY m.as_of DESC LIMIT 1
"""

PICK_SQL = """
SELECT p.id, p.status, p.p_calibrated, p.p_calibrated_lo, p.ev, m.name AS model
  FROM picks.picks p JOIN models.model_versions v ON v.id = p.model_version_id
  JOIN models.model_registry m ON m.id = v.model_id
 WHERE p.id = %(pick)s AND p.fixture_id = %(fixture)s AND p.market_key = %(market)s AND p.selection = %(selection)s
   AND p.line = %(line)s
"""


def _snapshot(conn: psycopg.Connection[Any], *, fixture_id: int, market_key: str, selection: str, line: Decimal,
              at: datetime) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PRICE_SQL, {"fixture": fixture_id, "market": market_key, "selection": selection, "line": line,
                                "at": at, "since": at - SNAPSHOT_LOOKBACK})
        return cur.fetchone()


def _fixture(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURE_SQL, (fixture_id,))
        f = cur.fetchone()
    if f is None:
        raise RecordError("unknown_fixture", f"fixture {fixture_id} does not exist")
    if f["kickoff_at"] <= at or f["status_group"] != "scheduled":
        raise RecordError("started", "the match has started: only a match still to be played can be saved")
    return f


def save_pick(conn: psycopg.Connection[Any], *, user_id: int, fixture_id: int, market_key: str, selection: str,
              line: Decimal, at: datetime, pick_id: int | None = None, user_odds: Decimal | None = None,
              allow_shadow: bool = False) -> dict[str, Any]:
    if not valid_selection(market_key, selection, line):
        raise RecordError("invalid_selection", f"{market_key} {selection} {line} is not a selection we settle")
    _fixture(conn, fixture_id, at)
    price = _snapshot(conn, fixture_id=fixture_id, market_key=market_key, selection=selection, line=line, at=at)
    pick = None
    if pick_id is not None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(PICK_SQL, {"pick": pick_id, "fixture": fixture_id, "market": market_key,
                                   "selection": selection, "line": line})
            pick = cur.fetchone()
        if pick is None or (pick["status"] not in ("qualified", "published") and not allow_shadow):
            raise RecordError("unknown_pick", "that PrediGol pick is not one this account can see")
    snapshot: dict[str, Any] = {
        "saved_at": at.isoformat(),
        "price": None if price is None else {"odds": str(price["best_odds"]), "bookmaker": price["bookmaker"],
                                             "as_of": price["as_of"].isoformat(), "p_fair": str(price["p_fair"]),
                                             "n_bookmakers": price["n_bookmakers"]},
        "pick": None if pick is None else {"id": pick["id"], "status": pick["status"], "model": pick["model"],
                                           "p_model": str(pick["p_calibrated"]), "p_low": str(pick["p_calibrated_lo"]),
                                           "ev": str(pick["ev"])},
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, pick_id, odds, "
            "bookmaker, price_at, user_odds, snapshot, saved_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s) ON CONFLICT (user_id, fixture_id, market_key, selection, line) DO NOTHING RETURNING id",
            (user_id, fixture_id, market_key, selection, line, "predigol_pick" if pick else "market",
             pick["id"] if pick else None, price["best_odds"] if price else None,
             price["bookmaker"] if price else None, price["as_of"] if price else None, user_odds, Jsonb(snapshot),
             at))
        row = cur.fetchone()
    if row is None:
        raise RecordError("already_saved", "this selection is already in your picks")
    return {"id": int(row["id"]), "snapshot": snapshot}


def remove_pick(conn: psycopg.Connection[Any], *, user_id: int, record_id: int, at: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM picks.user_picks u USING core.fixtures f WHERE u.id = %s AND u.user_id = %s "
                    "AND f.id = u.fixture_id AND f.kickoff_at > %s AND u.status = 'PENDING'", (record_id, user_id, at))
        if cur.rowcount == 0:
            raise RecordError("not_removable", "only your own pick, before its match starts, can be removed")


def set_user_odds(conn: psycopg.Connection[Any], *, user_id: int, record_id: int, user_odds: Decimal | None,
                  at: datetime) -> None:
    """The price the user says they got at their own bookmaker - until the match starts; after
    that the record is history and its price is what it settles at."""
    with conn.cursor() as cur:
        cur.execute("UPDATE picks.user_picks u SET user_odds = %s FROM core.fixtures f WHERE u.id = %s "
                    "AND u.user_id = %s AND f.id = u.fixture_id AND f.kickoff_at > %s AND u.status = 'PENDING'",
                    (user_odds, record_id, user_id, at))
        if cur.rowcount == 0:
            raise RecordError("not_editable", "only your own pick, before its match starts, can be changed")


def remove_parlay(conn: psycopg.Connection[Any], *, user_id: int, record_id: int, at: datetime) -> None:
    """Only before its first match starts: after that a parlay is history."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM picks.user_parlays p WHERE p.id = %s AND p.user_id = %s AND p.status = 'READY' "
                    "AND NOT EXISTS (SELECT 1 FROM picks.user_parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id "
                    "WHERE l.user_parlay_id = p.id AND f.kickoff_at <= %s)", (record_id, user_id, at))
        if cur.rowcount == 0:
            raise RecordError("not_removable", "only your own parlay, before its first match starts, can be removed")


@dataclass
class LegIn:
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal | None = None


@dataclass
class Validation:
    ok: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    legs: list[dict[str, Any]] = field(default_factory=list)
    combined_odds: Decimal | None = None


def validate_parlay(conn: psycopg.Connection[Any], legs: list[LegIn], *, at: datetime) -> Validation:
    v = Validation(ok=True)
    if not MIN_LEGS <= len(legs) <= MAX_LEGS:
        v.errors.append({"code": "leg_count", "min": MIN_LEGS, "max": MAX_LEGS, "got": len(legs)})
    fixtures: dict[int, int] = {}
    teams: dict[int, int] = {}
    odds_product = Decimal(1)
    all_priced = True
    for n, leg in enumerate(legs, start=1):
        entry: dict[str, Any] = {"leg": n, "fixture_id": leg.fixture_id, "market_key": leg.market_key,
                                 "selection": leg.selection, "line": str(leg.line)}
        if not valid_selection(leg.market_key, leg.selection, leg.line):
            v.errors.append({"code": "invalid_selection", "leg": n})
        if quarter_line(leg.line):
            v.errors.append({"code": "quarter_line", "leg": n})
        try:
            f = _fixture(conn, leg.fixture_id, at)
        except RecordError as exc:
            v.errors.append({"code": exc.code, "leg": n})
            v.legs.append(entry)
            continue
        if leg.fixture_id in fixtures:
            v.errors.append({"code": "same_fixture", "leg": n, "with": fixtures[leg.fixture_id]})
        fixtures.setdefault(leg.fixture_id, n)
        for team in (f["home_team_id"], f["away_team_id"]):
            if team in teams and teams[team] != n:
                v.warnings.append({"code": "shared_team", "leg": n, "with": teams[team]})
            teams.setdefault(team, n)
        price = _snapshot(conn, fixture_id=leg.fixture_id, market_key=leg.market_key, selection=leg.selection,
                          line=leg.line, at=at)
        odds = leg.odds if leg.odds is not None else (Decimal(price["best_odds"]) if price else None)
        entry.update({"odds": None if odds is None else str(odds), "kickoff_at": f["kickoff_at"].isoformat(),
                      "price": None if price is None else {"odds": str(price["best_odds"]),
                                                           "bookmaker": price["bookmaker"],
                                                           "as_of": price["as_of"].isoformat()}})
        if odds is None:
            all_priced = False
            v.warnings.append({"code": "no_price", "leg": n})
        else:
            odds_product *= odds
        v.legs.append(entry)
    v.ok = not v.errors
    v.combined_odds = odds_product.quantize(Decimal("0.001")) if all_priced and legs else None
    return v


def create_parlay(conn: psycopg.Connection[Any], *, user_id: int, name: str | None, legs: list[LegIn],
                  at: datetime) -> dict[str, Any]:
    v = validate_parlay(conn, legs, at=at)
    if not v.ok:
        raise RecordError("invalid_parlay", "the parlay breaks a rule: " + ", ".join(e["code"] for e in v.errors))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("INSERT INTO picks.user_parlays (user_id, name, created_at, combined_odds, validation, status) "
                    "VALUES (%s, %s, %s, %s, %s, 'READY') RETURNING id",
                    (user_id, name, at, v.combined_odds, Jsonb({"warnings": v.warnings})))
        row = cur.fetchone()
        assert row is not None
        parlay_id = int(row["id"])
        for n, (leg, entry) in enumerate(zip(legs, v.legs, strict=True), start=1):
            cur.execute("INSERT INTO picks.user_parlay_legs (user_parlay_id, leg_no, fixture_id, market_key, selection, "
                        "line, odds, snapshot) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (parlay_id, n, leg.fixture_id, leg.market_key, leg.selection, leg.line,
                         Decimal(entry["odds"]) if entry.get("odds") else None, Jsonb(entry)))
    return {"id": parlay_id, "combined_odds": v.combined_odds, "warnings": v.warnings}


# ── history ──────────────────────────────────────────────────────────────────

GROUP_SQL: dict[str, str] = {
    "predigol_picks": """
        SELECT i.status, i.profit_units AS profit, i.odds, f.kickoff_at
          FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id
          JOIN core.fixtures f ON f.id = i.fixture_id
         WHERE s.source = ANY(%(sources)s) AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s""",
    "my_picks": """
        SELECT u.status, u.profit_units AS profit, COALESCE(u.user_odds, u.odds) AS odds, f.kickoff_at
          FROM picks.user_picks u JOIN core.fixtures f ON f.id = u.fixture_id
         WHERE u.user_id = %(user)s AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s""",
    "predigol_parlays": """
        SELECT CASE p.status WHEN 'WON' THEN 'WIN' WHEN 'LOST' THEN 'LOSS' WHEN 'PARTIAL_VOID' THEN 'WIN'
                    WHEN 'VOID' THEN 'VOID' ELSE 'PENDING' END AS status,
               p.profit_units AS profit, p.combined_odds AS odds, p.window_from AS kickoff_at
          FROM picks.parlays p
         WHERE p.source = ANY(%(sources)s) AND p.status NOT IN ('BUILDING')
           AND EXISTS (SELECT 1 FROM picks.parlay_legs l WHERE l.parlay_id = p.id)
           AND (SELECT min(f.kickoff_at) FROM picks.parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
                 WHERE l.parlay_id = p.id) >= %(since)s
           AND (SELECT min(f.kickoff_at) FROM picks.parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
                 WHERE l.parlay_id = p.id) < %(until)s""",
    "my_parlays": """
        SELECT CASE p.status WHEN 'WON' THEN 'WIN' WHEN 'LOST' THEN 'LOSS' WHEN 'PARTIAL_VOID' THEN 'WIN'
                    WHEN 'VOID' THEN 'VOID' ELSE 'PENDING' END AS status,
               p.profit_units AS profit, p.combined_odds AS odds, p.created_at AS kickoff_at
          FROM picks.user_parlays p
         WHERE p.user_id = %(user)s
           AND (SELECT min(f.kickoff_at) FROM picks.user_parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
                 WHERE l.user_parlay_id = p.id) >= %(since)s
           AND (SELECT min(f.kickoff_at) FROM picks.user_parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
                 WHERE l.user_parlay_id = p.id) < %(until)s""",
}


@dataclass
class GroupStats:
    total: int = 0
    pending: int = 0
    won: int = 0
    lost: int = 0
    push: int = 0
    void: int = 0
    staked: Decimal = Decimal(0)
    profit: Decimal = Decimal(0)
    priced: int = 0
    """Settled records with a price, the ones profit is counted over."""

    @property
    def hit_rate(self) -> float | None:
        decided = self.won + self.lost
        return self.won / decided if decided else None

    @property
    def roi(self) -> float | None:
        return float(self.profit / self.staked) if self.staked else None


def period_bounds(period: Period, *, at: datetime, tz: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tz)
    local_midnight = at.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    until = local_midnight + timedelta(days=1)
    days = {"today": 1, "7d": 7, "30d": 30}.get(period)
    since = local_midnight - timedelta(days=days - 1) if days else datetime(2000, 1, 1, tzinfo=zone)
    return since, until


def history(conn: psycopg.Connection[Any], *, user_id: int, period: Period, tz: str, at: datetime,
            include_evaluation: bool) -> dict[str, GroupStats]:
    since, until = period_bounds(period, at=at, tz=tz)
    # The evaluation records are their own superset view (qualified picks are in it too): the
    # preview shows them alone, as the board does, never added to the qualified ones.
    sources = ["evaluation"] if include_evaluation else ["qualified"]
    out: dict[str, GroupStats] = {}
    for group, sql in GROUP_SQL.items():
        stats = GroupStats()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, {"user": user_id, "since": since, "until": until, "sources": sources})
            rows = cur.fetchall()
        for r in rows:
            stats.total += 1
            status = str(r["status"])
            if status == "PENDING":
                stats.pending += 1
                continue
            if status in ("WIN", "HALF_WIN"):
                stats.won += 1
            elif status in ("LOSS", "HALF_LOSS"):
                stats.lost += 1
            elif status == "PUSH":
                stats.push += 1
            else:
                stats.void += 1
            if r["profit"] is not None:
                stats.priced += 1
                stats.profit += Decimal(r["profit"])
                if status != "VOID":
                    stats.staked += Decimal(1)
        out[group] = stats
    return out
