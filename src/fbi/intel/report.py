"""DAILY LEARNING REPORT - ``learn-report-v1``: what a Bogotá day taught PrediGol Intelligence, from stored data only
(``intel.daily_reports``, append-only revisions; a new revision only when the content changed).

Sections: the decisions (by state and context, the picks of the day and parlays of daily-set-v6 beside v5's), the
results (wins / losses / voids, flat ROI, closing-line value - approved and rejected alike, so the filters themselves
are judged), calibration (log loss, Brier, ECE of the calibrated probability against the raw model and the market),
the post-mortems (verdicts and the causes that recur), whether the AI's context helped, the news (evidence by status
and source level, CONTEXTO EXTERNO LIMITADO), model and market anomalies, teams and players from the memory, the
calibrators and their roles, new hypotheses, the opportunities the market discovery found, and what the AI cost.

Nothing here changes a model, a filter or a pick.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds

VERSION = "learn-report-v1"

LAST_SQL = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.*
      FROM intel.decisions d
     WHERE d.kickoff_at >= %(start)s AND d.kickoff_at < %(end)s
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
)
SELECT l.id, l.state, l.market_key, l.selection, l.context_status, l.score::float8 AS score, l.odds::float8 AS odds,
       l.p_model::float8 AS p_model, l.p_cal::float8 AS p_cal, l.p_market::float8 AS p_market,
       l.ev_cal::float8 AS ev_cal, l.stake_units::float8 AS stake, (l.context->'review'->>'decision') AS review,
       o.result_status, o.profit_flat::float8 AS profit, o.profit_staked::float8 AS profit_staked,
       o.clv::float8 AS clv, pm.verdict, pm.causes
  FROM last l
  LEFT JOIN intel.decision_outcomes o ON o.decision_id = l.id
  LEFT JOIN intel.postmortems pm ON pm.decision_id = l.id
"""


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    return None if not xs else round(sum(xs) / len(xs), 6)


def _group_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [r for r in rows if r["result_status"] in ("win", "loss", "half_win", "half_loss")]
    voids = [r for r in rows if r["result_status"] in ("push", "void")]
    wins = [r for r in settled if r["result_status"] in ("win", "half_win")]
    return {"n": len(rows), "settled": len(settled), "wins": len(wins), "losses": len(settled) - len(wins),
            "voids": len(voids), "pending": sum(1 for r in rows if r["result_status"] is None),
            "roi_flat": _mean([r["profit"] for r in settled]),
            "profit_staked": round(sum(r["profit_staked"] or 0 for r in settled), 4),
            "clv": _mean([r["clv"] for r in rows if r["clv"] is not None])}


def _calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    import numpy as np

    from fbi.intel import stats

    xs = [r for r in rows if r["result_status"] in ("win", "loss") and r["p_cal"] is not None
          and r["p_market"] is not None]
    if len(xs) < 20:
        return {"n": len(xs), "note": "muestra insuficiente"}
    y = np.array([1.0 if r["result_status"] == "win" else 0.0 for r in xs])
    out: dict[str, Any] = {"n": len(xs)}
    for name, key in (("calibrada", "p_cal"), ("modelo", "p_model"), ("mercado", "p_market")):
        p = np.array([float(r[key]) for r in xs])
        out[name] = {"logloss": round(stats.logloss(y, p), 5), "brier": round(stats.brier(y, p), 5),
                     "ece": round(stats.ece(y, p), 5), "mean_p": round(float(p.mean()), 4)}
    out["hit_rate"] = round(float(y.mean()), 4)
    return out


def build_report(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> dict[str, Any]:
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LAST_SQL, {"start": start, "end": end})
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT kind, rank, odds::float8 AS odds, p_est::float8 AS p, ev::float8 AS ev, "
                    "stake_units::float8 AS stake, decision_ids, detail FROM intel.day_selections "
                    "WHERE day = %s ORDER BY kind, rank", (day,))
        selections = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT i.status, count(*) AS n, sum(i.profit_units)::float8 AS pnl, avg(i.odds)::float8 AS odds "
                    "FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id "
                    "WHERE s.day = %s AND s.source = 'evaluation' GROUP BY 1", (day,))
        v5 = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT origin, status, source_tier, count(*) AS n FROM ai.evidence e JOIN core.fixtures f "
                    "ON f.id = e.fixture_id WHERE f.kickoff_at >= %s AND f.kickoff_at < %s GROUP BY 1, 2, 3 "
                    "ORDER BY 4 DESC", (start, end))
        evidence = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT purpose, tier, count(*) AS calls, sum(cost_usd)::float8 AS usd FROM ai.usage "
                    "WHERE at >= %s AND at < %s GROUP BY 1, 2 ORDER BY 4 DESC", (start, end))
        costs = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT entity, market_key, model_name, to_role, reason, at FROM intel.promotions "
                    "WHERE at >= %s AND at < %s + interval '1 day' ORDER BY at", (start, end))
        promotions = [dict(r) | {"at": r["at"].isoformat()} for r in cur.fetchall()]
        cur.execute("SELECT entity_type, entity_name, aspect, stats FROM intel.entity_memory WHERE as_of_day = %s "
                    "AND entity_type IN ('team', 'competition') AND (stats->>'decisions')::int >= 5 "
                    "ORDER BY (stats->>'clv_mean')::float8 NULLS LAST LIMIT 12", (day,))
        memory = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT entity_name, stats FROM intel.entity_memory WHERE as_of_day = %s AND entity_type = 'player' "
                    "AND (delta->>'started_anyway')::int > 0 LIMIT 15", (day,))
        players = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT r.id FROM intel.runs r WHERE r.job = 'weekly' AND r.status IN ('ok', 'partial') "
                    "AND r.started_at <= %s ORDER BY r.started_at DESC LIMIT 1", (at,))
        run = cur.fetchone()
        opportunities: list[dict[str, Any]] = []
        if run is not None:
            cur.execute("SELECT provider_bet_id, name, status, proposal, metrics->>'fixtures' AS fixtures "
                        "FROM intel.market_registry WHERE run_id = %s AND status = 'RESEARCH' "
                        "ORDER BY (metrics->>'fixtures')::int DESC NULLS LAST LIMIT 6", (run["id"],))
            opportunities = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id, title, status FROM analytics.research_hypotheses WHERE created_at >= %s "
                    "AND created_at < %s + interval '1 day' ORDER BY id", (start, end))
        hypotheses = [dict(r) for r in cur.fetchall()]
    by_state: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_state.setdefault(r["state"], []).append(r)
    not_rejected = [r for r in rows if r["state"] != "RECHAZADO"]
    reviewed = [r for r in not_rejected if r["review"]]
    flagged = [r for r in reviewed if r["review"] in ("REJECT", "DOWNGRADE")]
    kept = [r for r in reviewed if r["review"] not in ("REJECT", "DOWNGRADE")]
    verdicts: dict[str, int] = {}
    causes: dict[str, int] = {}
    for r in rows:
        if r["verdict"]:
            verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        for c in r["causes"] or []:
            causes[c.get("code", "?")] = causes.get(c.get("code", "?"), 0) + 1
    anomalies = sorted((r for r in not_rejected if r["p_market"] is not None),
                       key=lambda r: -abs(float(r["p_model"]) - float(r["p_market"])))[:5]
    by_market: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_market.setdefault(r["market_key"], []).append(r)
    content: dict[str, Any] = {
        "day": day.isoformat(), "version": VERSION,
        "decisions": {"total": len(rows), "by_state": {k: len(v) for k, v in sorted(by_state.items())},
                      "by_context": _count(rows, "context_status"),
                      "contexto_externo_limitado": sum(1 for r in rows if r["context_status"] == "LIMITED")},
        "selections_v6": selections, "daily_set_v5": v5,
        "results": {state: _group_results(v) for state, v in sorted(by_state.items())},
        "results_by_market": {m: _group_results(v) for m, v in sorted(by_market.items())},
        "calibration": _calibration(rows),
        "postmortems": {"verdicts": verdicts, "causes": dict(sorted(causes.items(), key=lambda kv: -kv[1])[:8])},
        "context": {"reviewed": len(reviewed), "flagged": _group_results(flagged), "kept": _group_results(kept)},
        "news": evidence,
        "anomalies": [{"decision": r["id"], "market": r["market_key"], "selection": r["selection"],
                       "p_model": r["p_model"], "p_market": r["p_market"], "p_cal": r["p_cal"],
                       "gap": round(float(r["p_model"]) - float(r["p_market"]), 4)} for r in anomalies],
        "memory": [{"type": m["entity_type"], "name": m["entity_name"], "aspect": m["aspect"],
                    "decisions": (m["stats"] or {}).get("decisions"), "clv_mean": (m["stats"] or {}).get("clv_mean"),
                    "last10": (m["stats"] or {}).get("last10")} for m in memory],
        "players_started_after_reported_out": [{"name": p["entity_name"],
                                                "rate": (p["stats"] or {}).get("started_anyway_rate")}
                                               for p in players],
        "calibrators": promotions, "hypotheses": hypotheses, "opportunities": opportunities,
        "costs": {"items": costs, "total_usd": round(sum(c["usd"] or 0 for c in costs), 4)},
    }
    return content


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[str(r[key])] = out.get(str(r[key]), 0) + 1
    return dict(sorted(out.items()))


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.1f} %"


def render(c: dict[str, Any]) -> str:
    d = c["decisions"]
    lines = [f"# DAILY LEARNING REPORT · {c['day']}", "",
             f"**Decisiones:** {d['total']} selecciones evaluadas — " + ", ".join(f"{k} {v}" for k, v in
                                                                                d["by_state"].items()) + ".",
             "**Contexto:** " + ", ".join(f"{k} {v}" for k, v in d["by_context"].items())
             + f"; CONTEXTO EXTERNO LIMITADO en {d['contexto_externo_limitado']}.", ""]
    picks = [s for s in c["selections_v6"] if s["kind"] == "pick"]
    parlays = [s for s in c["selections_v6"] if s["kind"] == "parlay"]
    lines.append(f"**Picks del día (v6, shadow):** {len(picks)}; parlays {len(parlays)}. "
                 + ("Ningún mercado tiene edge validado: 0 picks es la respuesta honesta." if not picks else ""))
    lines.append("")
    lines.append("## Resultados por estado")
    for state, g in c["results"].items():
        lines.append(f"- {state}: {g['settled']} liquidadas ({g['wins']} G / {g['losses']} P / {g['voids']} N, "
                     f"{g['pending']} pendientes), ROI plano {_pct(g['roi_flat'])}, CLV {_pct(g['clv'])}")
    cal = c["calibration"]
    lines.append("")
    lines.append("## Calibración")
    if "calibrada" in cal:
        lines.append(f"- n={cal['n']}, acierto {cal['hit_rate']:.1%}: log loss calibrada {cal['calibrada']['logloss']}"
                     f" · modelo {cal['modelo']['logloss']} · mercado {cal['mercado']['logloss']}; ECE calibrada "
                     f"{cal['calibrada']['ece']} · modelo {cal['modelo']['ece']}")
    else:
        lines.append(f"- {cal.get('note')} (n={cal.get('n')})")
    pm = c["postmortems"]
    lines.append("")
    lines.append("## Post-mortems (pm-v3)")
    lines.append("- Veredictos: " + (", ".join(f"{k} {v}" for k, v in pm["verdicts"].items()) or "ninguno"))
    lines.append("- Causas: " + (", ".join(f"{k} {v}" for k, v in pm["causes"].items()) or "ninguna registrada"))
    ctx = c["context"]
    lines.append("")
    lines.append("## ¿Ayudó el contexto?")
    lines.append(f"- Revisadas {ctx['reviewed']}: marcadas por la IA {ctx['flagged']['settled']} (ROI "
                 f"{_pct(ctx['flagged']['roi_flat'])}), no marcadas {ctx['kept']['settled']} (ROI "
                 f"{_pct(ctx['kept']['roi_flat'])}). Una diferencia de un día no prueba nada.")
    lines.append("")
    lines.append("## Anomalías modelo / mercado")
    for a in c["anomalies"]:
        lines.append(f"- {a['market']} {a['selection']}: modelo {a['p_model']:.3f} vs mercado {a['p_market']:.3f} "
                     f"(calibrada {a['p_cal'] if a['p_cal'] is None else round(a['p_cal'], 3)})")
    if c["calibrators"]:
        lines.append("")
        lines.append("## Calibradores y edge")
        for p in c["calibrators"]:
            lines.append(f"- {p['entity']} {p['market_key']}/{p['model_name']} → {p['to_role']}: {p['reason']}")
    if c["opportunities"]:
        lines.append("")
        lines.append("## Oportunidades (Market Discovery)")
        for o in c["opportunities"]:
            lines.append(f"- {o['name']} (#{o['provider_bet_id']}): {o['proposal']}")
    lines.append("")
    lines.append(f"**Coste IA del día:** US${c['costs']['total_usd']:.2f}.")
    return "\n".join(lines)


def write_report(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> int | None:
    content = build_report(conn, day=day, at=at)
    body = json.dumps(content, sort_keys=True, default=str)
    h = hashlib.sha256(body.encode()).hexdigest()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT revision, content_hash FROM intel.daily_reports WHERE day = %s ORDER BY revision DESC "
                    "LIMIT 1", (day,))
        last = cur.fetchone()
        if last is not None and last["content_hash"] == h:
            return None
        rev = 1 if last is None else int(last["revision"]) + 1
        cur.execute("INSERT INTO intel.daily_reports (day, revision, built_at, version, content, text, content_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (day, revision) DO NOTHING RETURNING id",
                    (day, rev, at, VERSION, Jsonb(json.loads(body)), render(content), h))
        row = cur.fetchone()
    return None if row is None else int(row["id"])


def days_to_report(at: datetime) -> list[date]:
    """Yesterday (and the day before, whose late matches may have settled since)."""
    from fbi.ai.calendar import local_day

    today = local_day(at)
    return [today - timedelta(days=2), today - timedelta(days=1)]
