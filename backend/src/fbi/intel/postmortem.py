"""THE post-mortem - ``pm-v6``: after a match, every selection PrediGol looked at is asked the same questions, whoever looked at it.

Until now a selection was judged in up to three places that did not agree (``ai.postmortems`` pm-v1.1 by match, ``ai.pick_postmortems``
pm-v2 by selection, this table by decision) and only 20 selections were in two of them. Now ONE row per selection and version, built by rules
from what was stored before kick-off and the result, at no cost (a language model only writes the optional narrative,
``ai.postmortem_narratives``). A selection is studied when ANY of these looked at it:

    decision   the last decision of the decision layer before kick-off, when it reached CAUTELA or better, or is one of the twenty
               best-scored INVESTIGACION selections of a finished Bogotá day (so the layer learns while it approves nothing);
    daily_pick / parlay_leg   a pick of the day or a leg of a parlay (what users saw);
    llm        a selection a language model reviewed;
    reviewed / rejected   every reviewed selection of a match the AI worked on that day (it had a pass).

For each one (the questions are in ``fbi.intel.pm_questions``; the facts it starts from in ``fbi.intel.pm_facts``):

* THE PRICE, from the one closing-line value (``fbi.market.closing_value`` at the reference ``fbi.market.closing_reference``): closing-line
  value above +1 % GOOD, below -1 % BAD, otherwise NEUTRAL; no closing price: UNKNOWN. This is the DECISION QUALITY, never the result.
* VERDICT, quality x outcome: won & good/neutral MERECIDO - won & bad SUERTE - lost & good/neutral VARIANZA - lost & bad ERROR - push / void
  NULO - no closing price SIN_DATOS. The luck against the decision.
* REVIEW VERDICT, beside it and never mixed with it: what the AI's review decided against how the selection ended (approved and won,
  rejected and would have won, ...).
* THE CLASS OF A LOSS, the first that applies: data, execution, context, market, model, normal variance, unknown.
* CAUSES the model could not see, from the match itself (``core.fixture_events``, ``core.fixture_team_stats``): red cards (minute, which side),
  penalties scored or missed (the kicks of a shoot-out are not part of the match), an early goal, early substitutions, cards against what the
  referee usually shows, and what the expected goals say the match deserved.
* THE QUESTIONS, answered only from stored numbers: the ten of the AI (expected, happened, model, information, ignored signal, odds moved, key
  absence, line-up changed, uncertainty, variance) and the eight of the decision layer (probability, price, market, unseen, context, luck or
  decision, learning, change). One result never changes anything: it goes to memory (``fbi.intel.memory``) and only patterns over many
  reach a hypothesis (``fbi.ai.patterns``).

History: pm-v3 .. pm-v5 judged decisions only (pm-v5: the referee is a person, ``fbi.people``; pm-v4: a shoot-out is not the match) and their rows
stay as written; pm-v2 and pm-v1.1 (``ai.pick_postmortems``, ``ai.postmortems``) are frozen behind ``FBI_AI_LEGACY_POSTMORTEMS``. The readers take the
newest post-mortem of a decision (``decision_id``) or of a selection (``intel.selection_postmortems``). ``decision_id`` is set whenever a decision
exists, so everything that read a decision's post-mortem still does.

The match as a whole (the AI's evidence against who started, the model's forecast against the closing market) is ``fbi.intel.match_review``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_start, local_day
from fbi.ai.memory import remember
from fbi.intel.match_review import analyse
from fbi.intel.pm_facts import Candidate, Key, build_facts, resolve
from fbi.intel.pm_questions import Facts, answers, classify, review_verdict_of
from fbi.market import closing_reference, closing_value
from fbi.picks.settlement import market_outcome

VERSION = "pm-v6"
SHOOTOUT = "Penalty Shootout"
"""``comments`` of the events that are kicks of a shoot-out (the provider gives them minute 120 and type Goal)."""
GOOD_CLV = closing_value.GOOD
TOP_INVESTIGATION = 20
LOOKBACK = timedelta(days=7)
SETTLE_DELAY = timedelta(hours=3)
"""A match is studied three hours after kick-off at the earliest: its events, statistics and line-ups arrive after the final whistle, and a
post-mortem is written once (the table is append-only), so it waits until they are there."""
LIMIT = 400
"""Selections a run studies at most (the rest wait for the next run; ``scripts.postmortems build`` loops until none is left)."""

DECISIONS_SQL = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.*
      FROM intel.decisions d
     WHERE d.kickoff_at >= %(since)s AND d.kickoff_at <= %(until)s
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
), ranked AS (
    SELECT l.id, row_number() OVER (PARTITION BY (l.kickoff_at AT TIME ZONE 'America/Bogota')::date
                                    ORDER BY l.score DESC NULLS LAST, l.id) AS rk
      FROM last l WHERE l.state = 'INVESTIGACION'
)
SELECT l.id, l.fixture_id, l.market_key, l.selection, l.line, l.state, l.checkpoint, l.known_at, l.odds, l.bookmaker_id, l.price_at,
       l.p_model, l.p_cal, l.p_market, l.score, l.context_status, l.context, l.review_id,
       o.result_status AS decision_result, o.clv AS decision_clv
  FROM last l
  JOIN core.fixtures f ON f.id = l.fixture_id AND f.status_group = 'finished'
  JOIN core.fixture_results r ON r.fixture_id = f.id AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
  LEFT JOIN intel.decision_outcomes o ON o.decision_id = l.id
 WHERE l.state NOT IN ('RECHAZADO', 'INVESTIGACION')
    OR (l.id IN (SELECT id FROM ranked WHERE rk <= %(top)s)
        AND (l.kickoff_at AT TIME ZONE 'America/Bogota')::date < (%(until)s AT TIME ZONE 'America/Bogota')::date)
"""
"""The last decision of each selection before kick-off that is worth a post-mortem. The twenty best INVESTIGACION selections of a day are
chosen only once the Bogotá day is over (a half day would rank differently every hour)."""

ITEMS_SQL = """
SELECT 'daily_pick' AS role, i.fixture_id, i.market_key, i.selection, i.line, i.odds, i.bookmaker_id, i.p_model,
       i.p_low, i.p_market, i.price_at, i.selected_at
  FROM picks.daily_set_items i JOIN core.fixtures f ON f.id = i.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND f.status_group = 'finished'
UNION ALL
SELECT 'parlay_leg', l.fixture_id, l.market_key, l.selection, l.line, l.odds, l.bookmaker_id, l.p_model, l.p_low,
       l.p_market, l.price_at, l.added_at
  FROM picks.parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND f.status_group = 'finished'
"""

LLM_SQL = """
SELECT DISTINCT r.fixture_id, r.market_key, r.selection, r.line FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.engine = 'llm' AND r.status = 'ok' AND r.reviewed_at < f.kickoff_at
   AND f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s
"""

PASSED_SQL = """
SELECT DISTINCT p.fixture_id FROM ai.fixture_passes p JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s
"""

REVIEW_COLUMNS = """
       r.fixture_id, r.market_key, r.selection, r.line, r.id AS review_id, r.decision, r.odds, r.bookmaker_id, r.p_model, r.p_low,
       r.p_market, r.reviewed_at, r.packet_id, r.pick_id,
       jsonb_build_object('negative_evidence', r.output->'negative_evidence', 'uncertainties', r.output->'uncertainties',
                          'contradictions', r.output->'contradictions', 'lineups_seen', r.output->'lineups_seen') AS output"""

REVIEWS_SQL = f"""
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line) {REVIEW_COLUMNS}
  FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.engine = 'combined' AND r.reviewed_at < f.kickoff_at AND r.fixture_id = ANY(%(fixtures)s)
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""
"""The newest combined review of each selection before kick-off, of the matches the AI worked on (only what a post-mortem reads of its output)."""

REVIEWS_BY_ID_SQL = f"SELECT {REVIEW_COLUMNS} FROM ai.pick_reviews r WHERE r.id = ANY(%(ids)s)"
"""The review a decision says it used (``intel.decisions.review_id``), for a selection the AI's own universe does not contain."""

DONE_SQL = """
SELECT fixture_id, market_key, selection, line FROM intel.postmortems
 WHERE version = %(version)s AND market_key IS NOT NULL AND fixture_id = ANY(%(fixtures)s)
"""

FIXTURES_SQL = """
SELECT f.id, f.kickoff_at, th.name AS home, ta.name AS away, c.name AS competition, r.reg_goals_home AS gh, r.reg_goals_away AS ga,
       COALESCE(rf.name, ff.referee) AS referee, fr.referee_id
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.fixture_facts_latest ff ON ff.fixture_id = f.id
  LEFT JOIN core.fixture_referees fr ON fr.fixture_id = f.id
  LEFT JOIN core.referees rf ON rf.id = fr.referee_id
 WHERE f.id = ANY(%(fixtures)s) AND f.status_group = 'finished' AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
"""
"""The score at 90 minutes (the one every market settles on), who played, the competition and the referee (his name and id when the
identity has placed the match, else the string of the facts)."""

PACKETS_SQL = "SELECT id, content->'quality' AS quality, content->'absences' AS absences FROM ai.match_packets WHERE id = ANY(%(ids)s)"
"""What a post-mortem reads of the packet the review used: the quality of the competition and the key absences."""

FIRST_LINEUP_SQL = """
SELECT fixture_id, min(fetched_at) AS first_at FROM core.fixture_lineups WHERE fixture_id = ANY(%(fixtures)s) GROUP BY fixture_id
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

REFEREE_BY_ID_SQL = """
SELECT fr.referee_id, count(*) AS n, avg(COALESCE(s.y, 0) + COALESCE(s.r, 0))::float8 AS cards
  FROM core.fixture_referees fr
  JOIN core.fixtures f ON f.id = fr.fixture_id
  JOIN LATERAL (SELECT sum(yellow_cards) AS y, sum(red_cards) AS r FROM core.fixture_team_stats t
                 WHERE t.fixture_id = f.id AND t.source = 'api-football') s ON true
 WHERE fr.referee_id = ANY(%(ids)s) AND f.kickoff_at < %(before)s AND f.kickoff_at >= %(before)s - interval '400 days'
   AND f.status_group = 'finished' AND s.y IS NOT NULL
 GROUP BY 1
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
"""The same average by the string, only for the matches the identity has not placed yet."""


def side_of(market: str, selection: str) -> str:
    if market in ("1X2", "AH"):
        return "home" if selection == "Home" else "away" if selection == "Away" else "draw"
    if market == "DC":
        return "home" if selection == "1X" else "away" if selection == "X2" else "draw"
    return "total"


def quality_of(clv: float | None) -> str:
    """GOOD / NEUTRAL / BAD from the CLV of the decision's price (``fbi.market.closing_value``), UNKNOWN without one."""
    return closing_value.quality(clv)


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
    events = [e for e in events if str(e.get("comments") or "") != SHOOTOUT]
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


def answers_for(f: Facts, quality: str, verdict: str, causes: list[dict[str, Any]], *, context_status: str | None = None) -> dict[str, Any]:
    """The POST_MATCH_REVIEW questions of the decision layer, answered only from stored numbers (the ten of the AI are in
    ``fbi.intel.pm_questions.answers``; both sets live in the same row)."""
    p, close, clv = f.p_model, f.p_close, f.clv
    ll = None
    if p is not None and f.settled in ("win", "loss"):
        pp = min(max(float(p), 1e-4), 1 - 1e-4)
        ll = -math.log(pp if f.won else 1 - pp)
    unseen = [c["text"] for c in causes if c["code"] not in ("xg_supported", "xg_against")]
    return {
        "probabilidad": {"p_cal": p, "p_cierre": close, "log_loss": None if ll is None else round(ll, 4),
                         "texto": ("sin probabilidad de cierre" if close is None or p is None else
                                   f"p calibrada {float(p):.3f} frente a {float(close):.3f} del cierre")},
        "precio": {"clv": clv, "calidad": quality,
                   "texto": "sin cierre" if clv is None else f"CLV {float(clv):+.1%}: "
                            + {"GOOD": "precio mejor que el cierre", "BAD": "precio peor que el cierre",
                               "NEUTRAL": "precio en línea con el cierre"}.get(quality, "")},
        "mercado": {"p_mercado_decision": f.p_market, "p_cierre": close,
                    "movimiento": None if close is None or f.p_market is None else round(float(close) - float(f.p_market), 4)},
        "no_visto": unseen or ["nada fuera de lo normal en los eventos registrados"],
        "contexto": {"estado": context_status, "revision": f.decision,
                     "ayudo": None if f.decision is None else (f.decision in ("REJECT", "DOWNGRADE")) != f.won},
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


REVIEW_DECISIONS = frozenset({"APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"})


@dataclass
class StudyReport:
    candidates: int = 0
    """Selections the universe holds in the window."""
    done: int = 0
    """Of those, already written under this version."""
    studied: int = 0
    wins: int = 0
    losses: int = 0
    memory_events: int = 0
    left: int = 0
    """Selections still to study after this run's limit."""
    by_class: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    """Written rows by who looked at the selection: ``decision`` (the decision layer only), ``ai`` (the AI only), ``both``."""
    skipped: dict[str, int] = field(default_factory=dict)
    outcome_disagreements: int = 0
    """Rows whose result computed from the regulation score differs from the one the decision's settlement stored."""
    errors: list[str] = field(default_factory=list)


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _key(r: dict[str, Any]) -> Key:
    return int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"])


def universe(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> dict[Key, Candidate]:
    """Every selection that finished in the window and that the decision layer or the AI looked at, merged into one candidate each."""
    window = {"since": since, "until": until, "top": TOP_INVESTIGATION}
    decisions = {_key(r): r for r in _rows(conn, DECISIONS_SQL, window)}
    roles: dict[Key, set[str]] = {}
    items: dict[Key, dict[str, Any]] = {}
    for r in _rows(conn, ITEMS_SQL, window):
        roles.setdefault(_key(r), set()).add(str(r["role"]))
        items.setdefault(_key(r), r)
    for r in _rows(conn, LLM_SQL, window):
        roles.setdefault(_key(r), set()).add("llm")
    passed = {int(r["fixture_id"]) for r in _rows(conn, PASSED_SQL, window)}
    ai_fixtures = sorted({k[0] for k in roles} | passed)
    reviews = {_key(r): r for r in _rows(conn, REVIEWS_SQL, {"fixtures": ai_fixtures})} if ai_fixtures else {}
    # the AI's own universe (pm-v2): reviewed selections that were a pick, a leg or LLM-reviewed, or of a match it had a pass for,
    # and every item that was a pick or a leg
    ai_keys = {k for k in reviews if k in roles or k[0] in passed} | set(items)
    wanted = {int(d["review_id"]) for k, d in decisions.items() if k not in ai_keys and d.get("review_id") is not None
              and k not in reviews}
    own = {int(r["review_id"]): r for r in _rows(conn, REVIEWS_BY_ID_SQL, {"ids": sorted(wanted)})} if wanted else {}
    out: dict[Key, Candidate] = {}
    for key in set(decisions) | ai_keys:
        d = decisions.get(key)
        review = reviews.get(key)
        if review is None and d is not None and d.get("review_id") is not None:
            review = own.get(int(d["review_id"]))
        out[key] = resolve(key, item=items.get(key), review=review, decision=d, roles=roles.get(key, set()), ai_studied=key in ai_keys)
    return out


def study(conn: psycopg.Connection[Any], *, at: datetime, lookback: timedelta = LOOKBACK, limit: int = LIMIT,
          until: datetime | None = None, since: datetime | None = None) -> StudyReport:
    """Write the post-mortem of every selection that finished and has none under this version. Idempotent: a selection has one row per
    version (a unique index), and a run that finds everything written writes nothing."""
    report = StudyReport()
    until = until or at - SETTLE_DELAY
    since = since or day_start(local_day(at - lookback))
    candidates = universe(conn, since=since, until=until)
    report.candidates = len(candidates)
    if not candidates:
        return report
    done = {_key(r) for r in _rows(conn, DONE_SQL, {"version": VERSION, "fixtures": sorted({k[0] for k in candidates})})}
    report.done = len(done & set(candidates))
    pending = sorted((k for k in candidates if k not in done), key=lambda k: (k[0], k[1], k[2], k[3]))
    played = {int(r["id"]): r for r in _rows(conn, FIXTURES_SQL, {"fixtures": sorted({k[0] for k in pending})})} if pending else {}
    # a selection nobody can judge yet (the match has no regulation score, the market no settlement rule) must not take the place of one
    # that can be judged: the limit is counted over the ones that can
    settled_by: dict[Key, str] = {}
    for key in pending:
        match = played.get(key[0])
        if match is None:
            report.skipped["no_regulation_score"] = report.skipped.get("no_regulation_score", 0) + 1
            continue
        try:
            settled_by[key] = str(market_outcome(key[1], key[2], key[3], int(match["gh"]), int(match["ga"])).value)
        except ValueError:
            report.skipped["no_settlement_rule"] = report.skipped.get("no_settlement_rule", 0) + 1
    todo = [k for k in pending if k in settled_by]
    report.left = max(0, len(todo) - limit)
    todo = todo[:limit]
    if not todo:
        return report
    fixtures = sorted({k[0] for k in todo})
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    stats: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in _rows(conn, EVENTS_SQL, {"fixtures": fixtures}):
        events[int(r["fixture_id"])].append(r)
    for r in _rows(conn, STATS_SQL, {"fixtures": fixtures}):
        stats[int(r["fixture_id"])][str(r["team_side"])] = r
    first_lineup = {int(r["fixture_id"]): r["first_at"] for r in _rows(conn, FIRST_LINEUP_SQL, {"fixtures": fixtures})}
    packet_ids = sorted({int(pid) for pid in (candidates[k].packet_id for k in todo) if pid is not None})
    packets = {int(r["id"]): r for r in _rows(conn, PACKETS_SQL, {"ids": packet_ids})} if packet_ids else {}
    closes = closing_reference.closing_probabilities(conn, todo)
    book_keys = [(k[0], int(book), k[1], k[2], k[3]) for k, book in ((k, candidates[k].bookmaker_id) for k in todo) if book is not None]
    book_closes = closing_reference.same_book_closes(conn, book_keys)
    studying = [played[f] for f in fixtures]
    before = min(r["kickoff_at"] for r in studying)
    ids = sorted({int(r["referee_id"]) for r in studying if r.get("referee_id") is not None})
    names = sorted({str(r["referee"]) for r in studying if r.get("referee") and r.get("referee_id") is None})
    usual_by_id: dict[int, float] = {}
    usual_by_name: dict[str, float] = {}
    if ids:
        usual_by_id = {int(r["referee_id"]): float(r["cards"]) for r in _rows(conn, REFEREE_BY_ID_SQL, {"ids": ids, "before": before})
                       if int(r["n"]) >= 5}
    if names:
        usual_by_name = {str(r["referee"]): float(r["cards"]) for r in _rows(conn, REFEREE_SQL, {"refs": names, "before": before})
                         if int(r["n"]) >= 5}
    findings: dict[int, dict[str, Any] | None] = {}
    for fid in fixtures:
        try:
            with conn.transaction():
                got = analyse(conn, fid)
            findings[fid] = None if got is None else got[2]
        except Exception as exc:  # the match's own findings are an enrichment: a failure there must not lose the selections
            findings[fid] = None
            report.errors.append(f"{fid}: findings: {type(exc).__name__}: {exc}"[:200])
    for key in todo:
        fid = key[0]
        c = candidates[key]
        match = played[fid]
        gh, ga = int(match["gh"]), int(match["ga"])
        settled = settled_by[key]
        try:
            close = closes.get(key)
            book = None if c.bookmaker_id is None else book_closes.get((fid, int(c.bookmaker_id), key[1], key[2], key[3]))
            facts = build_facts(c, settled=settled, kickoff=match["kickoff_at"], findings=findings.get(fid),
                                packet=packets.get(int(c.packet_id)) if c.packet_id is not None else None,
                                p_close=None if close is None else close.p_fair, close_odds=None if book is None else book.odds,
                                first_lineup=first_lineup.get(fid))
            cls = classify(facts)
            review_verdict = review_verdict_of(facts)
            quality = quality_of(facts.clv)
            verdict = verdict_of(settled, quality)
            referee, referee_id = match.get("referee"), match.get("referee_id")
            usual = (None if referee is None else usual_by_id.get(int(referee_id)) if referee_id is not None
                     else usual_by_name.get(str(referee)))
            causes = causes_of({"market_key": key[1], "selection": key[2], "line": float(key[3])}, events.get(fid, []),
                               stats.get(fid, {}), {"gh": gh, "ga": ga}, usual)
            label = f"{match['home']} - {match['away']} · {key[1]} {key[2]}" + (f" {key[3]}" if key[3] else "")
            ans = answers(facts, cls, score=(gh, ga), label=label) | answers_for(facts, quality, verdict, causes,
                                                                                    context_status=c.context_status)
            disagrees = c.decision_result is not None and c.decision_result != settled
            evidence = {
                "decision": c.decision_id, "state": c.state, "checkpoint": c.checkpoint,
                "known_at": None if c.known_at is None else c.known_at.isoformat(), "odds": facts.odds, "score": c.score,
                "result": f"{gh}-{ga}", "referee": referee, "referee_id": referee_id, "events": len(events.get(fid, [])),
                "stats": bool(stats.get(fid)), "review_id": c.review_id, "packet_id": c.packet_id,
                "findings": (findings.get(fid) or {}).get("match_forecast"), "roles": sorted(c.roles),
                "competition": match["competition"], "kickoff_at": match["kickoff_at"].isoformat(),
                "prices": c.prices, "price_from": c.price_from, "close": None if close is None else close.evidence(),
                "same_book_close": None if book is None else {"odds": book.odds, "minutes_to_ko": book.minutes_to_ko},
                "decision_outcome": None if c.decision_id is None else {"result": c.decision_result, "clv": c.decision_clv,
                                                                       "agrees": not disagrees},
            }
            review_decision = c.review_decision if c.review_decision in REVIEW_DECISIONS else None
            with conn.transaction():  # a savepoint: one selection failing loses that selection, never the ones before it
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, "
                        "verdict, causes, answers, evidence, market_key, selection, line, roles, review_id, review_decision, "
                        "review_verdict, loss_class, odds, close_odds, p_model, p_market, p_close, price_move, clv) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING RETURNING id",
                        (c.decision_id, fid, at, VERSION, OUTCOME[settled], quality, verdict, Jsonb(causes), Jsonb(ans),
                         Jsonb(evidence), key[1], key[2], key[3], sorted(c.roles), c.review_id, review_decision, review_verdict,
                         cls, facts.odds, facts.close_odds, facts.p_model, facts.p_market, facts.p_close, facts.price_move,
                         facts.clv))
                    row = cur.fetchone()
                if row is None:
                    continue
                if c.ai_studied and remember(
                        conn, at=at, kind="pick_postmortem", entity_type="market", entity_id=f"{key[1]}:{key[2]}:{key[3]}",
                        version=VERSION, fixture_id=fid, hypothesis=f"{review_verdict} {label}", result=cls or review_verdict,
                        evidence={"postmortem_id": int(row[0]), "verdict": review_verdict, "class": cls,
                                  "price_move": facts.price_move, "clv_v1": facts.clv, "p_model": facts.p_model,
                                  "p_close": facts.p_close, "roles": sorted(c.roles), "competition": match["competition"],
                                  "signals": facts.ignored, "odds": facts.odds, "result": facts.settled},
                        dedup_key=f"pm2:{fid}:{key[1]}:{key[2]}:{key[3]}"):
                    report.memory_events += 1
            report.studied += 1
            report.wins += int(facts.won)
            report.losses += int(facts.lost)
            report.outcome_disagreements += int(disagrees)
            source = "both" if c.decision_id is not None and c.ai_studied else "decision" if c.decision_id is not None else "ai"
            report.by_source[source] = report.by_source.get(source, 0) + 1
            if cls:
                report.by_class[cls] = report.by_class.get(cls, 0) + 1
        except Exception as exc:
            report.errors.append(f"{fid}: {key[1]} {key[2]} {key[3]}: {type(exc).__name__}: {exc}"[:240])
    return report


def run_postmortems(conn: psycopg.Connection[Any], *, at: datetime, lookback: timedelta = LOOKBACK) -> int:
    """The nightly step: how many selections were studied now (``study`` has the whole report)."""
    return study(conn, at=at, lookback=lookback).studied


__all__ = ["OUTCOME", "REVIEW_DECISIONS", "VERSION", "StudyReport", "answers_for", "causes_of", "quality_of", "run_postmortems",
           "side_of", "study", "universe", "verdict_of"]
