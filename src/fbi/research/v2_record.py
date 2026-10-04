"""Research V2, written down: the session, one experiment per model with its role, the market
baselines (the champion among them), the prospective evaluation and the pick audit - and a
report a person can read. Nothing earlier is overwritten; the runs before the rebuild keep
their ``LEGACY_RESEARCH_RUN`` label (migration 0054)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.backtesting.persist import config_hash, config_json, hgb_hyper, scores_json, store_session
from fbi.backtesting.session import hypers_for
from fbi.features.engine import FEATURE_VERSION
from fbi.research.experiments import environment, record_session
from fbi.research.prospective import MIN_DAYS, MIN_SEGMENT, SegmentResult
from fbi.research.v2 import V2Result

QUESTION = ("Research V2 on the validated history: does any model family - alone, or blended with the market - "
            "forecast 1X2 better than the best de-vigged market price, out of sample and walk-forward?")


def _insert(cur: psycopg.Cursor[Any], *, name: str, kind: str, family: str, question: str, config: dict[str, Any],
            metrics: dict[str, Any], code_version: str, role: str | None, reason: str | None, segment: str | None,
            result: V2Result, session_id: int | None) -> int:
    cur.execute(
        "INSERT INTO analytics.experiments (name, kind, question, model_family, backtest_session_id, feature_version, "
        "config, dataset_hash, code_version, environment, metrics, status, research_status, gate, finished_at, "
        "run_label, role, role_reason, segment, data_as_of) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'completed',"
        "'RESEARCH','{}'::jsonb,now(),'RESEARCH_V2',%s,%s,%s,%s) RETURNING id",
        (name, kind, question, family, session_id, FEATURE_VERSION, Json(config), result.evaluation.dataset_hash,
         code_version, Json(environment()), Json(metrics), role, reason, segment, result.data_as_of))
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def prospective_role(r: SegmentResult) -> tuple[str, str]:
    c = r.comparison
    if c is None or not r.judged:
        return "RESEARCH", (f"{r.n_common} matches with a forecast and a closing price on "
                            f"{0 if c is None else c.n_blocks} days: fewer than {MIN_SEGMENT} matches or "
                            f"{MIN_DAYS} days, not judged")
    d = c.logloss_diff
    w = "no blend weight" if r.w is None else f"blend weight {r.w[0]:+.3f} [{r.w[1]:+.3f}, {r.w[2]:+.3f}]"
    alone = f"log loss vs the close {d.mean:+.4f} [{d.lo:+.4f}, {d.hi:+.4f}] on {c.n_common} matches"
    adds = r.w is not None and r.w[1] > 0
    if d.hi < 0:
        return "CHALLENGER", f"beats the closing consensus prospectively: {alone}; {w}"
    if d.lo > 0 and not adds:
        return "REJECTED", f"worse than the closing consensus and adds nothing to it: {alone}; {w}"
    return "RESEARCH", f"the evidence cannot tell: {alone}; {w}"


def record_v2(conn: psycopg.Connection[Any], result: V2Result, *, name: str, code_version: str,
              report_path: Path | None) -> dict[str, Any]:
    """Store everything; the caller commits. Returns what was written."""
    s = result.session
    cfg = s.cfg
    hypers = hypers_for(s, code_version)
    hypers["hgb"] = hgb_hyper(code_version, with_market=False)
    hypers["hgb_market"] = hgb_hyper(code_version, with_market=True)
    payload = config_json(cfg) | {"competitions": [i for i, _ in s.competitions], "feature_version": FEATURE_VERSION,
                                  "research": "v2"}
    session_id = store_session(conn, name=name, cfg=cfg, data=s.data, evaluation=s.evaluation,
                               selection=s.selection, hypers=hypers, code_version=code_version,
                               cfg_hash=config_hash(payload))
    recorded = record_session(conn, result=s, session_id=session_id, name=name, question=QUESTION,
                              code_version=code_version, hypers=hypers, report_path=report_path,
                              roles=result.roles, extra_metrics=result.model_metrics(), data_as_of=result.data_as_of)
    written: dict[str, Any] = {"session_id": session_id,
                               "models": {r.model: {"id": r.id, "role": result.roles[r.model].role}
                                          for r in recorded}}
    champion = result.champion
    with conn.cursor(row_factory=tuple_row) as cur:
        markets = {}
        best = champion.logloss.get(champion.key, math.inf)
        for key, ll in sorted(champion.logloss.items(), key=lambda kv: kv[1]):
            base = next((b for b in s.evaluation.baselines if b.key == key), None)
            is_champion = key == champion.key
            reason = (f"lowest log loss of the de-vigged market baselines, {ll:.5f} on the {champion.n_common} "
                      "fixtures every one of them priced" if is_champion else
                      f"a market variant: log loss {ll:.5f}, {ll - best:+.5f} against the champion on the same "
                      f"{champion.n_common} fixtures")
            markets[key] = _insert(cur, name=f"{name}:market:{key}", kind="market", family="market",
                                   question="Which de-vigged market price is the best forecast (E1)?",
                                   config={"baseline": key, "session": name},
                                   metrics={"common_logloss": ll, "n_common": champion.n_common,
                                            "own_sample": None if base is None else scores_json(base.scores),
                                            "mean_overround": None if base is None else base.mean_overround},
                                   code_version=code_version, role="CHAMPION" if is_champion else "RESEARCH",
                                   reason=reason, segment=None, result=result, session_id=session_id)
        written["markets"] = markets
        if result.prospective is not None:
            p = result.prospective
            prosp = {}
            for model in sorted({r.model for r in p.rows}):
                rows = [r for r in p.rows if r.model == model]
                overall = next(r for r in rows if r.segment == "all")
                role, reason = prospective_role(overall)
                prosp[model] = _insert(
                    cur, name=f"{name}:prospective:{model}", kind="prospective", family=model,
                    question="Forecasts stored before kick-off since 25 Sep 2026, against the closing consensus, "
                             "per segment: better, worse, or too few matches to tell?",
                    config={"since": p.since.isoformat(), "until": p.until.isoformat(), "min_segment": MIN_SEGMENT},
                    metrics={"played": p.played, "priced": p.priced, "segments": [r.as_json() for r in rows],
                             "segment_roles": {r.segment: prospective_role(r)[0] for r in rows}},
                    code_version=code_version, role=role, reason=reason, segment="all", result=result,
                    session_id=None)
            written["prospective"] = prosp
        if result.audit is not None:
            written["audit"] = _insert(
                cur, name=f"{name}:audit:shadow-picks", kind="audit", family="shadow_picks",
                question="Where did the shadow picks' returns come from: the price, the edge, or luck (E0)?",
                config={"method": "EV at the last Shin consensus before kick-off"},
                metrics=result.audit.as_json(), code_version=code_version, role=None,
                reason=None, segment=None, result=result, session_id=None)
    return written
