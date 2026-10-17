"""POST_MATCH_REVIEW of a decision - ``pm-v3``: whether the DECISION was good, apart from whether it WON.

For the last decision before kick-off of every selection that reached CAUTELA or better, and the twenty best-scored
INVESTIGACION selections of each day (so the layer learns while it approves nothing), once its outcome is known:

* DECISION QUALITY from the price, not the result: closing-line value above +1 % GOOD, below -1 % BAD, otherwise
  NEUTRAL; no closing price: UNKNOWN.
* VERDICT, quality x outcome:  won & good/neutral MERECIDO · won & bad SUERTE · lost & good/neutral VARIANZA ·
  lost & bad ERROR · push / void NULO · no closing price SIN_DATOS.
* CAUSES the model could not see, from the match itself (``core.fixture_events``, ``core.fixture_team_stats``): red
  cards (minute, which side), penalties scored or missed, an early goal, early substitutions, cards against what the
  referee usually shows, and what the expected goals say the match deserved.
* THE QUESTIONS answered from stored data: was the probability right, was the price good, how did the market move,
  what happened that the model could not see, did the context help, bad luck or a bad decision, what is learnt, and
  whether anything must change - which is never "yes" because of one match: one result goes to memory
  (``fbi.intel.memory``) and only patterns over many reach a hypothesis.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

VERSION = "pm-v3"
GOOD_CLV = 0.01
TOP_INVESTIGATION = 20
LOOKBACK = timedelta(days=4)

TODO_SQL = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.*
      FROM intel.decisions d
     WHERE d.kickoff_at >= %(since)s AND d.kickoff_at < %(at)s
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
), ranked AS (
    SELECT l.id, row_number() OVER (PARTITION BY (l.kickoff_at AT TIME ZONE 'America/Bogota')::date
                                    ORDER BY l.score DESC NULLS LAST, l.id) AS rk
      FROM last l WHERE l.state = 'INVESTIGACION'
)
SELECT l.id, l.fixture_id, l.kickoff_at, l.market_key, l.selection, l.line, l.state, l.odds::float8 AS odds,
       l.p_model::float8 AS p_model, l.p_cal::float8 AS p_cal, l.p_market::float8 AS p_market, l.score::float8 AS score,
       l.ev_cal::float8 AS ev_cal, l.context_status, l.context, l.checkpoint, l.known_at,
       o.result_status, o.clv::float8 AS clv, o.close_p_fair::float8 AS close_p, o.profit_flat::float8 AS profit,
       f.home_team_id, f.away_team_id
  FROM last l
  JOIN intel.decision_outcomes o ON o.decision_id = l.id
  JOIN core.fixtures f ON f.id = l.fixture_id
  LEFT JOIN intel.postmortems pm ON pm.decision_id = l.id AND pm.version = %(version)s
 WHERE pm.id IS NULL
   AND (l.state NOT IN ('RECHAZADO', 'INVESTIGACION') OR l.id IN (SELECT id FROM ranked WHERE rk <= %(top)s))
"""

EVENTS_SQL = """
SELECT fixture_id, minute, extra_minute, team_side, event_type, detail, comments, player_name
  FROM core.fixture_events WHERE fixture_id = ANY(%(fixtures)s) ORDER BY fixture_id, minute, seq
"""

STATS_SQL = """
SELECT DISTINCT ON (fixture_id, team_side) fixture_id, team_side, yellow_cards, red_cards, fouls, expected_goals::float8
       AS xg, shots, shots_on_target, corners
  FROM core.fixture_team_stats WHERE fixture_id = ANY(%(fixtures)s)
 ORDER BY fixture_id, team_side, (source = 'api-football') DESC, fetched_at DESC
"""

RESULTS_SQL = """
SELECT r.fixture_id, COALESCE(r.reg_goals_home, r.goals_home) AS gh, COALESCE(r.reg_goals_away, r.goals_away) AS ga,
       r.ht_goals_home AS hth, r.ht_goals_away AS hta, ff.referee
  FROM core.fixture_results r LEFT JOIN core.fixture_facts_latest ff ON ff.fixture_id = r.fixture_id
 WHERE r.fixture_id = ANY(%(fixtures)s)
"""

REFEREE_SQL = """
SELECT ff.referee, count(*) AS n, avg(COALESCE(s.y, 0) + COALESCE(s.r, 0))::float8 AS cards
  FROM core.fixture_facts_latest ff
  JOIN core.fixtures f ON f.id = ff.fixture_id
  JOIN LATERAL (SELECT sum(yellow_cards) AS y, sum(red_cards) AS r FROM core.fixture_team_stats t
                 WHERE t.fixture_id = f.id AND t.source = 'api-football') s ON true
 WHERE ff.referee = ANY(%(refs)s) AND f.kickoff_at < %(before)s AND f.kickoff_at >= %(before)s - interval '400 days'
   AND f.status_group = 'finished' AND s.y IS NOT NULL
 GROUP BY 1
"""


def side_of(market: str, selection: str) -> str:
    if market in ("1X2", "AH"):
        return "home" if selection == "Home" else "away" if selection == "Away" else "draw"
    if market == "DC":
        return "home" if selection == "1X" else "away" if selection == "X2" else "draw"
    return "total"


def quality_of(clv: float | None) -> str:
    if clv is None or (isinstance(clv, float) and math.isnan(clv)):
        return "UNKNOWN"
    return "GOOD" if clv > GOOD_CLV else "BAD" if clv < -GOOD_CLV else "NEUTRAL"


def verdict_of(result: str, quality: str) -> str:
    if result in ("push", "void"):
        return "NULO"
    if quality == "UNKNOWN":
        return "SIN_DATOS"
    won = result in ("win", "half_win")
    if won:
        return "SUERTE" if quality == "BAD" else "MERECIDO"
    return "ERROR" if quality == "BAD" else "VARIANZA"


OUTCOME = {"win": "won", "loss": "lost", "push": "push", "void": "void", "half_win": "half_won",
           "half_loss": "half_lost"}


def causes_of(d: dict[str, Any], events: list[dict[str, Any]], stats: dict[str, dict[str, Any]],
              result: dict[str, Any] | None, referee_avg: float | None) -> list[dict[str, Any]]:
    """What happened in the match that a pre-match model could not see. Pure."""
    side = side_of(str(d["market_key"]), str(d["selection"]))
    out: list[dict[str, Any]] = []

    def whose(ev_side: str | None) -> str:
        if side not in ("home", "away") or ev_side not in ("home", "away"):
            return "neutral"
        return "for" if ev_side == side else "against"

    for e in events:
        minute = int(e["minute"] or 0)
        kind, detail = str(e["event_type"] or ""), str(e["detail"] or "")
        if kind == "Card" and detail.lower().startswith(("red", "second yellow")):
            # a man sent off hurts his own side: against the selection when it backed that side
            w = {"for": "against", "against": "for"}.get(whose(e["team_side"]), "neutral")
            out.append({"code": "red_card", "minute": minute, "side": e["team_side"], "effect": w,
                        "text": f"Roja al {'local' if e['team_side'] == 'home' else 'visitante'} en el {minute}'"
                                + {"against": " (en contra de la selección)", "for": " (a favor de la selección)"}
                                .get(w, "")})
        elif kind == "Goal" and detail == "Penalty":
            out.append({"code": "penalty_scored", "minute": minute, "side": e["team_side"],
                        "effect": whose(e["team_side"]) if side in ("home", "away") else "neutral",
                        "text": f"Penalti convertido ({e['team_side']}) en el {minute}'"})
        elif kind == "Goal" and detail == "Missed Penalty":
            out.append({"code": "penalty_missed", "minute": minute, "side": e["team_side"], "effect": "neutral",
                        "text": f"Penalti fallado ({e['team_side']}) en el {minute}'"})
    goals = [e for e in events if e["event_type"] == "Goal" and e["detail"] != "Missed Penalty"]
    if goals and int(goals[0]["minute"] or 99) <= 15:
        g = goals[0]
        out.append({"code": "early_goal", "minute": int(g["minute"]), "side": g["team_side"],
                    "effect": whose(g["team_side"]), "text": f"Gol temprano ({g['team_side']}) en el {g['minute']}'"})
    early_subs = [e for e in events if str(e["event_type"]).lower() == "subst" and int(e["minute"] or 99) < 30]
    if early_subs:
        out.append({"code": "early_substitution", "n": len(early_subs), "effect": "neutral",
                    "text": f"{len(early_subs)} cambio(s) antes del 30' (posible lesión)"})
    h, a = stats.get("home") or {}, stats.get("away") or {}
    cards = sum(int(x or 0) for x in (h.get("yellow_cards"), a.get("yellow_cards"), h.get("red_cards"),
                                      a.get("red_cards")))
    if referee_avg is not None and (h or a):
        if cards >= referee_avg + 2.5:
            out.append({"code": "cards_above_referee", "cards": cards, "referee_avg": round(referee_avg, 2),
                        "effect": "neutral", "text": f"{cards} tarjetas frente a {referee_avg:.1f} de media del árbitro"})
        elif cards <= referee_avg - 2.5:
            out.append({"code": "cards_below_referee", "cards": cards, "referee_avg": round(referee_avg, 2),
                        "effect": "neutral", "text": f"{cards} tarjetas frente a {referee_avg:.1f} de media del árbitro"})
    xh, xa = h.get("xg"), a.get("xg")
    if xh is not None and xa is not None and result is not None:
        gh, ga = int(result["gh"]), int(result["ga"])
        market, sel = str(d["market_key"]), str(d["selection"])
        deserved: bool | None = None
        if market == "1X2":
            deserved = (xh - xa > 0.5) if sel == "Home" else (xa - xh > 0.5) if sel == "Away" else abs(xh - xa) <= 0.3
        elif market == "OU":
            line = float(d["line"])
            deserved = (xh + xa > line + 0.3) if sel == "Over" else (xh + xa < line - 0.3)
        elif market == "BTTS":
            deserved = (xh >= 0.9 and xa >= 0.9) if sel == "Yes" else (xh < 0.6 or xa < 0.6)
        if deserved is not None:
            out.append({"code": "xg_supported" if deserved else "xg_against", "xg_home": round(xh, 2),
                        "xg_away": round(xa, 2), "score": f"{gh}-{ga}", "effect": "for" if deserved else "against",
                        "text": f"xG {xh:.2f}-{xa:.2f} (marcador {gh}-{ga}): "
                                + ("el juego respaldaba la selección" if deserved else "el juego no la respaldaba")})
    return out


def answers_for(d: dict[str, Any], quality: str, verdict: str, causes: list[dict[str, Any]]) -> dict[str, Any]:
    """The POST_MATCH_REVIEW questions, answered only from stored numbers."""
    p, close, clv = d.get("p_cal") or d.get("p_model"), d.get("close_p"), d.get("clv")
    won = d["result_status"] in ("win", "half_win")
    ctx = d.get("context") or {}
    review = (ctx.get("review") or {}).get("decision")
    ll = None
    if p is not None and d["result_status"] in ("win", "loss"):
        pp = min(max(float(p), 1e-4), 1 - 1e-4)
        ll = -math.log(pp if won else 1 - pp)
    unseen = [c["text"] for c in causes if c["code"] not in ("xg_supported", "xg_against")]
    return {
        "probabilidad": {"p_cal": p, "p_cierre": close, "log_loss": None if ll is None else round(ll, 4),
                         "texto": ("sin probabilidad de cierre" if close is None or p is None else
                                   f"p calibrada {float(p):.3f} frente a {float(close):.3f} del cierre")},
        "precio": {"clv": clv, "calidad": quality,
                   "texto": "sin cierre" if clv is None else f"CLV {float(clv):+.1%}: "
                            + {"GOOD": "precio mejor que el cierre", "BAD": "precio peor que el cierre",
                               "NEUTRAL": "precio en línea con el cierre"}.get(quality, "")},
        "mercado": {"p_mercado_decision": d.get("p_market"), "p_cierre": close,
                    "movimiento": None if close is None or d.get("p_market") is None
                    else round(float(close) - float(d["p_market"]), 4)},
        "no_visto": unseen or ["nada fuera de lo normal en los eventos registrados"],
        "contexto": {"estado": d.get("context_status"), "revision": review,
                     "ayudo": None if review is None else (review in ("REJECT", "DOWNGRADE")) != won},
        "suerte_o_decision": verdict,
        "aprendizaje": {"MERECIDO": "decisión y resultado alineados: se suma a la memoria, nada que cambiar",
                        "VARIANZA": "buena decisión que perdió: varianza; no se toca el modelo",
                        "SUERTE": "ganó con el precio en contra: no enseña nada a favor del modelo",
                        "ERROR": "precio peor que el cierre y perdió: revisar en el patrón del mercado, no por este "
                                 "partido",
                        "NULO": "sin resultado que juzgar", "SIN_DATOS": "sin cierre para juzgar la decisión"}[verdict],
        "cambiar_algo": "no por un solo partido: queda en la memoria; solo un patrón con muestra suficiente llega a "
                        "hipótesis",
    }


def run_postmortems(conn: psycopg.Connection[Any], *, at: datetime, lookback: timedelta = LOOKBACK) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TODO_SQL, {"since": at - lookback, "at": at, "version": VERSION, "top": TOP_INVESTIGATION})
        todo = [dict(r) for r in cur.fetchall()]
    if not todo:
        return 0
    fixtures = sorted({int(d["fixture_id"]) for d in todo})
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    stats: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EVENTS_SQL, {"fixtures": fixtures})
        for r in cur.fetchall():
            events[int(r["fixture_id"])].append(dict(r))
        cur.execute(STATS_SQL, {"fixtures": fixtures})
        for r in cur.fetchall():
            stats[int(r["fixture_id"])][str(r["team_side"])] = dict(r)
        cur.execute(RESULTS_SQL, {"fixtures": fixtures})
        results = {int(r["fixture_id"]): dict(r) for r in cur.fetchall()}
        refs = sorted({str(r["referee"]) for r in results.values() if r.get("referee")})
        ref_avg: dict[str, float] = {}
        if refs:
            cur.execute(REFEREE_SQL, {"refs": refs, "before": min(d["kickoff_at"] for d in todo)})
            ref_avg = {str(r["referee"]): float(r["cards"]) for r in cur.fetchall() if int(r["n"]) >= 5}
    n = 0
    with conn.cursor() as cur:
        for d in todo:
            fid = int(d["fixture_id"])
            res = results.get(fid)
            referee = None if res is None else res.get("referee")
            causes = causes_of(d, events.get(fid, []), stats.get(fid, {}), res,
                               None if referee is None else ref_avg.get(str(referee)))
            quality = quality_of(d.get("clv"))
            verdict = verdict_of(str(d["result_status"]), quality)
            answers = answers_for(d, quality, verdict, causes)
            cur.execute(
                "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, "
                "verdict, causes, answers, evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (decision_id, version) DO NOTHING",
                (int(d["id"]), fid, at, VERSION, OUTCOME[str(d["result_status"])], quality, verdict, Jsonb(causes),
                 Jsonb(answers),
                 Jsonb({"decision": int(d["id"]), "state": d["state"], "checkpoint": d["checkpoint"],
                        "known_at": d["known_at"].isoformat(), "odds": d["odds"], "score": d["score"],
                        "result": None if res is None else f"{res['gh']}-{res['ga']}", "referee": referee,
                        "events": len(events.get(fid, [])), "stats": bool(stats.get(fid))})))
            n += max(cur.rowcount, 0)
    return n
