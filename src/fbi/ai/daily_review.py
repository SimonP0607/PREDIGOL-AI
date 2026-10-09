"""CIERRE DEL DÍA (DAILY AI REVIEW): what a Bogotá day was, written down at 23:59 and completed afterwards.

At 23:59 America/Bogota the day is closed: its matches, the picks of the day and how they did, the shadow
selections against the market (hit rate, ROI, line value), what the AI reviewed and how its decisions turned out,
the post-mortems and their classes, what was learned, the patterns under observation, the hypotheses and
experiments, what the AI and API-Football cost. A match not over at 23:59 (a late kick-off, a suspension) or a
post-mortem written the next morning does not belong to another day: the same day gets a new REVISION when its
content changes (``ai.daily_reviews``, append-only), and the day is ``complete`` once nothing of it is left to play
or to settle - a pick waiting for a human (postponed, abandoned, awarded) is counted apart, never forced.

Everything here is read from what is stored: no model, no search, no provider request. Nothing here can change a
pick, a probability, a rule or a model.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds, local_day
from fbi.core import match_state
from fbi.picks import settlement

VERSION = "daily-review-v1"
Kind = Literal["close", "update"]
FOLLOW_DAYS = 7
"""How many closed days keep being revised (a postponed match, a post-mortem the next morning)."""

MATCHES_SQL = """
SELECT f.id, f.status_short, f.kickoff_at,
       EXISTS (SELECT 1 FROM market.market_consensus m WHERE m.fixture_id = f.id AND m.as_of < f.kickoff_at)
           AS with_market
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
"""

ITEMS_SQL = """
SELECT s.source, s.status AS set_status, i.rank, i.fixture_id, th.name || ' - ' || ta.name AS match,
       i.market_key, i.selection, i.line, i.odds, i.status, i.profit_units, i.inputs->>'model' AS model,
       i.selected_at, f.kickoff_at, f.status_short,
       (SELECT r.decision FROM ai.pick_reviews r
         WHERE r.fixture_id = i.fixture_id AND r.market_key = i.market_key AND r.selection = i.selection
           AND r.line = i.line AND r.engine = 'combined' AND r.reviewed_at < f.kickoff_at
         ORDER BY r.reviewed_at DESC, r.id DESC LIMIT 1) AS ai_last,
       COALESCE(
         (SELECT fp.odds_decimal FROM market.final_prematch_odds fp
           WHERE fp.fixture_id = i.fixture_id AND fp.bookmaker_id = i.bookmaker_id AND fp.market_key = i.market_key
             AND fp.selection = i.selection AND fp.line = i.line),
         (SELECT sn.odds_decimal FROM market.odds_snapshots sn
           WHERE sn.fixture_id = i.fixture_id AND sn.bookmaker_id = i.bookmaker_id AND sn.market_key = i.market_key
             AND sn.selection = i.selection AND sn.line = i.line AND sn.source = 'prematch'
             AND sn.captured_at < f.kickoff_at
           ORDER BY sn.captured_at DESC LIMIT 1)) AS near_close_odds
  FROM picks.daily_sets s
  JOIN picks.daily_set_items i ON i.set_id = s.id
  JOIN core.fixtures f ON f.id = i.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE s.day = %(day)s
 ORDER BY s.source, i.rank
"""

SHADOW_SQL = """
WITH last AS (
    SELECT DISTINCT ON (p.fixture_id, p.market_key, p.selection, p.line, p.model_version_id)
           p.id, p.market_key, p.market_odds, p.p_calibrated, p.p_market_fair, p.ev
      FROM picks.picks p JOIN core.fixtures f ON f.id = p.fixture_id
     WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND p.created_at < f.kickoff_at
     ORDER BY p.fixture_id, p.market_key, p.selection, p.line, p.model_version_id, p.created_at DESC
)
SELECT l.market_key, count(*) AS n,
       count(*) FILTER (WHERE pr.result_status IS NOT NULL AND pr.result_status <> 'pending') AS settled,
       count(*) FILTER (WHERE pr.result_status IN ('win', 'half_win')) AS won,
       COALESCE(sum(pr.profit_units) FILTER (WHERE pr.result_status <> 'pending'), 0) AS pnl,
       avg(lv.lv_raw) AS line_value, avg(lv.lv_devigged) AS line_value_devigged, avg(l.ev) AS ev_claimed,
       avg(l.p_calibrated) AS p_model, avg(l.p_market_fair) AS p_market
  FROM last l
  LEFT JOIN picks.pick_results pr ON pr.pick_id = l.id
  LEFT JOIN picks.pick_line_value lv ON lv.pick_id = l.id
 GROUP BY l.market_key ORDER BY l.market_key
"""

AI_SQL = """
WITH last AS (
    SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
           r.fixture_id, r.market_key, r.selection, r.line, r.decision
      FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
     WHERE r.engine = 'combined' AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
       AND r.reviewed_at < f.kickoff_at
     ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
)
SELECT l.*, f.status_short, res.reg_goals_home, res.reg_goals_away, res.et_goals_home, res.et_goals_away,
       res.ft_goals_home, res.ft_goals_away
  FROM last l JOIN core.fixtures f ON f.id = l.fixture_id
  LEFT JOIN core.fixture_results res ON res.fixture_id = l.fixture_id
"""

POSTMORTEMS_SQL = """
SELECT pm.verdict, pm.classification, pm.settled
  FROM ai.pick_postmortems pm JOIN core.fixtures f ON f.id = pm.fixture_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND pm.version = 'pm-v2'
"""

NOTES_SQL = "SELECT kind, title, n FROM ai.learning_notes WHERE day = %(day)s ORDER BY id"

PATTERNS_SQL = """
SELECT kind, entity_type, hypothesis FROM ai.memory_events
 WHERE created_at >= %(start)s AND created_at < %(end)s
   AND kind IN ('league_pattern', 'team_pattern', 'player_pattern', 'market_signal', 'model_failure',
                'model_success', 'context_error')
 ORDER BY id DESC LIMIT 40
"""

HYPOTHESES_SQL = """
SELECT id, title, status, created_at, decided_at, outcome, stage_history FROM analytics.research_hypotheses
 WHERE created_at < %(end)s
"""

EXPERIMENTS_SQL = """
SELECT count(*) FILTER (WHERE started_at >= %(start)s AND started_at < %(end)s) AS started,
       count(*) FILTER (WHERE finished_at >= %(start)s AND finished_at < %(end)s) AS finished,
       count(*) FILTER (WHERE started_at < %(end)s AND (finished_at IS NULL OR finished_at >= %(end)s))
           AS running_at_end
  FROM analytics.experiments
"""

COSTS_SQL = """
SELECT purpose, COALESCE(sum(cost_usd), 0) AS usd, count(*) AS calls
  FROM ai.usage WHERE at >= %(start)s AND at < %(end)s GROUP BY purpose ORDER BY 2 DESC
"""

API_SQL = """
SELECT COALESCE(sum(api_calls), 0) AS requests FROM raw.ingestion_runs WHERE started_at >= %(start)s
   AND started_at < %(end)s
"""

SETTLEMENT_SQL = """
SELECT DISTINCT ON (l.fixture_id) l.fixture_id, l.delay_seconds, l.path
  FROM picks.settlement_latency l JOIN core.fixtures f ON f.id = l.fixture_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
 ORDER BY l.fixture_id, l.settled_at
"""

OPEN_SQL = """
SELECT f.id, f.status_short,
       (SELECT count(*) FROM picks.picks p WHERE p.fixture_id = f.id AND p.status <> 'settled') AS open_picks,
       (SELECT count(*) FROM picks.daily_set_items i WHERE i.fixture_id = f.id AND i.status = 'PENDING') AS open_items
  FROM core.fixtures f
 WHERE f.id = ANY(%(fixtures)s)
"""


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _f(x: Any, digits: int = 4) -> float | None:
    return None if x is None else round(float(x), digits)


def _won(status: str) -> bool:
    return status in ("WIN", "HALF_WIN")


def _lost(status: str) -> bool:
    return status in ("LOSS", "HALF_LOSS")


def _daily(items: list[dict[str, Any]], source: str, at: datetime) -> dict[str, Any]:
    mine = [r for r in items if r["source"] == source]
    settled = [r for r in mine if r["status"] != "PENDING"]
    pnl = sum((Decimal(r["profit_units"]) for r in settled if r["profit_units"] is not None), Decimal(0))
    values = [float(r["odds"]) / float(r["near_close_odds"]) - 1 for r in mine
              if r["near_close_odds"] and r["odds"]]
    return {
        "source": source,
        "set_status": mine[0]["set_status"] if mine else None,
        "n": len(mine),
        "won": sum(1 for r in mine if _won(r["status"])),
        "lost": sum(1 for r in mine if _lost(r["status"])),
        "void": sum(1 for r in mine if r["status"] in ("VOID", "PUSH")),
        "pending": len(mine) - len(settled),
        "pnl_units": float(pnl),
        "staked_units": len(settled),
        "roi": round(float(pnl) / len(settled), 4) if settled else None,
        "line_value": round(statistics.fmean(values), 4) if values else None,
        "items": [{
            "rank": r["rank"], "fixture_id": r["fixture_id"], "match": r["match"], "market": r["market_key"],
            "selection": r["selection"], "line": float(r["line"]), "odds": float(r["odds"]), "model": r["model"],
            "status": r["status"], "profit_units": _f(r["profit_units"]), "ai_last": r["ai_last"],
            "near_close_odds": _f(r["near_close_odds"], 3),
            "phase": match_state.phase(r["status_short"], r["kickoff_at"], at).value,
        } for r in mine],
    }


def _ai(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The AI's last pre-match decision on each reviewed selection, against what happened."""
    out: Counter[str] = Counter()
    for r in rows:
        decision = str(r["decision"]).lower()
        out[decision] += 1
        state = settlement.MatchState(r["status_short"], r["reg_goals_home"], r["reg_goals_away"],
                                      r["et_goals_home"], r["et_goals_away"], r["ft_goals_home"], r["ft_goals_away"])
        result = settlement.settle(r["market_key"], r["selection"], Decimal(r["line"]), Decimal(2), Decimal(1), state)
        if result.status in (settlement.Status.WIN, settlement.Status.HALF_WIN):
            out[f"{decision}_won"] += 1
        elif result.status in (settlement.Status.LOSS, settlement.Status.HALF_LOSS):
            out[f"{decision}_lost"] += 1
    return {"reviewed": len(rows), **dict(sorted(out.items()))}


def _in(value: Any, start: datetime, end: datetime) -> bool:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return False
    return isinstance(value, datetime) and start <= value < end


def _hypotheses(rows: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    """What happened to the hypotheses ON the day - proposed, decided, moved a stage - and how many were still
    waiting for the owner when it ended: facts of the day, so a later decision does not rewrite it."""
    new = [r for r in rows if _in(r["created_at"], start, end)]
    moved: Counter[str] = Counter()  # every decision and every stage is appended to stage_history
    for r in rows:
        for step in r["stage_history"] or []:
            if isinstance(step, dict) and _in(step.get("at"), start, end):
                moved[str(step.get("to"))] += 1
    validated = [r for r in rows if r["status"] in ("DONE", "PROMOTED") and isinstance(r["outcome"], dict)
                 and r["outcome"].get("gate_passed") is True and any(
                     isinstance(st, dict) and st.get("to") == "DONE" and _in(st.get("at"), start, end)
                     for st in r["stage_history"] or [])]
    return {
        "new": len(new),
        "new_titles": [str(r["title"]) for r in new][:10],
        "rejected": moved["REJECTED"],
        "investigating": moved["INVESTIGATING"] + moved["ACCEPTED"] + moved["RUNNING"] + moved["SHADOW"],
        "validated": len(validated),
        "promoted": moved["PROMOTED"],
        "waiting_owner_at_end": sum(1 for r in rows if r["decided_at"] is None or not r["decided_at"] < end),
    }


def content(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> dict[str, Any]:
    """Everything the review says about ``day`` (a Bogotá day), as read at ``at``."""
    start, end = day_bounds(day)
    p = {"day": day, "start": start, "end": end}
    matches = _rows(conn, MATCHES_SQL, p)
    phases = Counter(match_state.phase(m["status_short"], m["kickoff_at"], at).value for m in matches)
    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT fixture_id) FROM ai.fixture_passes WHERE day = %s", (day,))
        row = cur.fetchone()
        analysed = int(row[0]) if row else 0
    items = _rows(conn, ITEMS_SQL, p)
    shadow = _rows(conn, SHADOW_SQL, p)
    n_settled = sum(int(r["settled"]) for r in shadow)
    shadow_pnl = sum(float(r["pnl"]) for r in shadow)
    pms = _rows(conn, POSTMORTEMS_SQL, p)
    hyps = _rows(conn, HYPOTHESES_SQL, p)
    experiments = _rows(conn, EXPERIMENTS_SQL, p)[0]
    costs = _rows(conn, COSTS_SQL, p)
    latency = _rows(conn, SETTLEMENT_SQL, p)
    delays = sorted(int(r["delay_seconds"]) for r in latency if r["delay_seconds"] is not None)
    still = [m for m in matches if match_state.phase(m["status_short"], m["kickoff_at"], at).value in
             ("scheduled", "live", "suspended", "awaiting")]
    opened = _rows(conn, OPEN_SQL, {"fixtures": [m["id"] for m in matches]}) if matches else []
    unsettled = [r for r in opened if (r["open_picks"] or r["open_items"])
                 and match_state.code(r["status_short"]) not in settlement.REVIEW]
    waiting_human = [r for r in opened if (r["open_picks"] or r["open_items"])
                     and match_state.code(r["status_short"]) in settlement.REVIEW]
    pending = sorted({int(m["id"]) for m in still} | {int(r["id"]) for r in unsettled})
    return {
        "day": day.isoformat(),
        "timezone": "America/Bogota",
        "matches": {
            "tracked": len(matches),
            "with_market": sum(1 for m in matches if m["with_market"]),
            "analysed_by_ai": analysed,
            "played": phases["finished"],
            "not_played": phases["postponed"] + phases["cancelled"] + phases["abandoned"] + phases["not_played"],
            "still_to_finish": len(still),
        },
        "daily_picks": _daily(items, "evaluation", at),
        "qualified_picks": _daily(items, "qualified", at),
        "shadow": {
            "selections": sum(int(r["n"]) for r in shadow),
            "settled": n_settled,
            "won": sum(int(r["won"]) for r in shadow),
            "pnl_units": round(shadow_pnl, 4),
            "roi": round(shadow_pnl / n_settled, 4) if n_settled else None,
            "by_market": [{
                "market": r["market_key"], "n": int(r["n"]), "settled": int(r["settled"]), "won": int(r["won"]),
                "roi": round(float(r["pnl"]) / int(r["settled"]), 4) if int(r["settled"]) else None,
                "line_value": _f(r["line_value"]), "line_value_devigged": _f(r["line_value_devigged"]),
                "ev_claimed": _f(r["ev_claimed"]), "p_model": _f(r["p_model"]), "p_market": _f(r["p_market"]),
            } for r in shadow],
        },
        "ai": _ai(_rows(conn, AI_SQL, p)),
        "postmortems": {
            "n": len(pms),
            "by_class": dict(Counter(str(r["classification"]) for r in pms if r["classification"])),
            "by_verdict": dict(Counter(str(r["verdict"]) for r in pms if r["verdict"])),
        },
        "learning": [{"kind": r["kind"], "title": r["title"], "n": r["n"]} for r in _rows(conn, NOTES_SQL, p)],
        "patterns": [{"kind": r["kind"], "about": r["entity_type"], "text": r["hypothesis"]}
                     for r in _rows(conn, PATTERNS_SQL, p)],
        "hypotheses": _hypotheses(hyps, start, end),
        "experiments": {k: int(v or 0) for k, v in experiments.items()},
        "costs": {
            "ai_usd": round(sum(float(r["usd"]) for r in costs), 4),
            "by_purpose": {str(r["purpose"]): round(float(r["usd"]), 4) for r in costs},
            "api_football_requests": int(_rows(conn, API_SQL, p)[0]["requests"]),
        },
        "settlement": {
            "matches": len(latency),
            "median_seconds": float(statistics.median(delays)) if delays else None,
            "max_seconds": delays[-1] if delays else None,
            "by_path": dict(Counter(str(r["path"]) for r in latency)),
        },
        "pending_fixtures": pending,
        "waiting_human": sorted(int(r["id"]) for r in waiting_human),
    }


def _hash(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def store(conn: psycopg.Connection[Any], *, day: date, at: datetime, kind: Kind) -> int | None:
    """Write a revision of ``day`` when its content changed since the last one. Returns its id, or None."""
    body = content(conn, day=day, at=at)
    digest = _hash(body)
    with conn.cursor() as cur:
        cur.execute("SELECT revision, content_hash FROM ai.daily_reviews WHERE day = %s ORDER BY revision DESC "
                    "LIMIT 1", (day,))
        last = cur.fetchone()
        if last is not None and last[1] == digest:
            return None
        if last is None and kind == "update":
            return None  # a day is first written by its close, never by a later pass
        revision = 1 if last is None else int(last[0]) + 1
        cur.execute(
            "INSERT INTO ai.daily_reviews (day, revision, kind, built_at, complete, pending_fixtures, content, "
            "content_hash, version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (day, revision, "close" if last is None else "update", at, not body["pending_fixtures"],
             body["pending_fixtures"], Jsonb(body), digest, VERSION))
        row = cur.fetchone()
    return None if row is None else int(row[0])


def close_day(conn: psycopg.Connection[Any], *, at: datetime) -> int | None:
    """23:59 Bogotá: the day that is ending, written down."""
    return store(conn, day=local_day(at), at=at, kind="close")


def follow_days(conn: psycopg.Connection[Any], *, at: datetime) -> list[int]:
    """The closed days of the last week whose content moved since their last revision (a match settled, a
    post-mortem, the morning's learning): a new revision each, only when something changed. Yesterday, if the
    worker was down at 23:59, is closed now - late, and its ``built_at`` says so."""
    today = local_day(at)
    yesterday = today - timedelta(days=1)
    written: list[int] = []
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM ai.daily_reviews WHERE day = %s LIMIT 1", (yesterday,))
        missing = cur.fetchone() is None
    if missing:
        rid = store(conn, day=yesterday, at=at, kind="close")
        if rid is not None:
            written.append(rid)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT day FROM ai.daily_reviews WHERE day >= %s AND day < %s ORDER BY day",
                    (today - timedelta(days=FOLLOW_DAYS), today))
        days = [r[0] for r in cur.fetchall()]
    for d in days:
        rid = store(conn, day=d, at=at, kind="update")
        if rid is not None:
            written.append(rid)
    return written
