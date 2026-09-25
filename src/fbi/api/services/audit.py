"""Match Center -> Audit: reconstruct the chain behind a fixture from the database.

Nothing here is inferred from a timestamp alone: every link is a stored hash
or id (payload hash on a normalised row, feature-set input hash on a
prediction, prediction id on a pick candidate, result payload hash on a
settlement). Whether a payload file is still on disk is checked, not assumed.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from fbi.api.contracts.audit import AuditItem, AuditStep, MatchAudit, Scalar, StepState
from fbi.api.envelope import DataStatus, Envelope
from fbi.api.repositories import Conn, Row
from fbi.api.repositories import audit as repo
from fbi.core.config import settings


def _v(x: Any) -> Scalar:
    if x is None or isinstance(x, bool | int | str):
        return x
    if isinstance(x, float):
        return x
    if isinstance(x, Decimal):
        return float(x)
    return str(x)


def _facts(row: Row, *keys: str) -> dict[str, Scalar]:
    return {k: _v(row.get(k)) for k in keys}


def _on_disk(file_path: str | None) -> bool | None:
    if not file_path:
        return None
    return (Path(settings.runtime.raw_store_dir) / file_path).is_file()


def _step(key: Any, label: str, state: StepState, detail: str, items: list[AuditItem]) -> AuditStep:
    return AuditStep(key=key, label=label, state=state, detail=detail, items=items)


def match_audit(conn: Conn, fixture_id: int) -> Envelope[MatchAudit]:
    fx = repo.fixture(conn, fixture_id)
    if fx is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    finished = fx["status_group"] == "finished"
    steps: list[AuditStep] = []

    # 1. provider ------------------------------------------------------------------
    payload_rows = repo.payloads(conn, fixture_id)
    by_hash = {p["hash"]: p for p in payload_rows}
    src = by_hash.get(fx["source_payload_hash"]) if fx["source_payload_hash"] else None
    provider_items = [AuditItem(kind="fixture", ref=str(fx["id"]), at=fx["created_at"], source="api-football",
                                facts={"provider_fixture_id": fx["provider_fixture_id"], "competition":
                                       fx["competition"], "season": fx["season"]},
                                links=[f"payload:{fx['source_payload_hash']}"] if fx["source_payload_hash"] else [])]
    steps.append(_step(
        "provider", "Provider", "recorded" if src else "partial",
        (f"API-Football fixture {fx['provider_fixture_id']}, last written from {src['endpoint']} "
         f"(run {src['run_id']}, {src['job_type']})") if src else
        "the fixture row predates lineage recording (revision 0015): the payload that wrote it is not linked",
        provider_items))

    # 2. raw payloads ----------------------------------------------------------------
    raw_items = []
    unindexed = missing_files = 0
    for p in payload_rows:
        disk = _on_disk(p["file_path"])
        if p["endpoint"] is None:
            unindexed += 1
        if disk is False:
            missing_files += 1
        raw_items.append(AuditItem(
            kind="payload", ref=p["hash"], at=p["fetched_at"], source=p["provider"],
            facts={"endpoint": p["endpoint"], "roles": ", ".join(p["roles"] or []), "references": p["references"],
                   "http_status": p["http_status"], "bytes": p["bytes"], "file": p["file_path"], "on_disk": disk,
                   "run_id": p["run_id"], "job_type": p["job_type"]},
            links=[f"run:{p['run_id']}"] if p["run_id"] else []))
    if not payload_rows:
        raw_state: StepState = "missing"
        raw_detail = "no stored payload is referenced by any row of this fixture"
    elif unindexed:
        raw_state, raw_detail = "partial", f"{unindexed} referenced hash(es) have no index row"
    else:
        raw_state = "recorded" if missing_files == 0 else "partial"
        raw_detail = (f"{len(payload_rows)} payloads referenced; "
                      + ("every file is on disk" if missing_files == 0 else
                         f"{missing_files} file(s) not in this raw store"))
    steps.append(_step("raw", "Raw payloads", raw_state, raw_detail, raw_items))

    # 3. normalised --------------------------------------------------------------------
    res = repo.result(conn, fixture_id)
    norm_items = [AuditItem(kind="fixture", ref=str(fx["id"]), at=fx["updated_at"], source="api-football",
                            facts=_facts(fx, "status_short", "status_group", "kickoff_at"),
                            links=[f"payload:{fx['source_payload_hash']}"] if fx["source_payload_hash"] else [])]
    if res is not None:
        norm_items.append(AuditItem(
            kind="result", ref=str(fixture_id), at=res["source_fetched_at"], source="api-football",
            facts=_facts(res, "goals_home", "goals_away", "reg_goals_home", "reg_goals_away", "outcome_1x2"),
            links=[f"payload:{res['source_payload_hash']}"] if res["source_payload_hash"] else []))
    for d in repo.detail_counts(conn, fixture_id):
        norm_items.append(AuditItem(kind=d["kind"], ref=f"{fixture_id}/{d['source']}", at=d["at"], source=d["source"],
                                    facts={"rows": d["n"]}, links=[f"payload:{d['payload_hash']}"]))
    if finished and res is None:
        norm_state: StepState = "missing"
        norm_detail = "the match is finished but no result row exists"
    else:
        blocks = len(norm_items) - 1 - (1 if res else 0)
        norm_state = "recorded"
        norm_detail = "fixture row" + (", result" if res else "") + (f", {blocks} detail block(s)" if blocks else "")
    steps.append(_step("normalized", "Normalised rows", norm_state, norm_detail, norm_items))

    # 4. features --------------------------------------------------------------------
    fsets = repo.feature_sets(conn, fixture_id)
    feat_items = []
    for f in fsets:
        facts = _facts(f, "feature_version", "data_cutoff", "input_hash", "n_inputs", "newest_input_at",
                       "code_version", "run_id", "versions_computed")
        facts["cutoff_before_kickoff"] = f["data_cutoff"] < fx["kickoff_at"]
        feat_items.append(AuditItem(kind="feature_set", ref=str(f["id"]), at=f["generated_at"],
                                    source=f["feature_version"], facts=facts,
                                    links=[f"run:{f['run_id']}"] if f["run_id"] else []))
    by_input = {f["input_hash"]: f for f in fsets}
    steps.append(_step(
        "features", "Feature sets", "recorded" if fsets else "missing",
        (f"{len(fsets)} feature version(s); every data cut-off is before kick-off" if fsets and all(
            f["data_cutoff"] < fx["kickoff_at"] for f in fsets) else
         f"{len(fsets)} feature version(s)" if fsets else "no feature set has been computed for this fixture"),
        feat_items))

    # 5-6. models and predictions ---------------------------------------------------
    preds = repo.predictions(conn, fixture_id)
    versions: dict[int, Row] = {}
    for p in preds:
        versions.setdefault(p["model_version_id"], p)
    exps = repo.experiments(conn, list(versions))
    exp_by_version: dict[int, list[Row]] = {}
    for e in exps:
        exp_by_version.setdefault(e["model_version_id"], []).append(e)
    model_items = []
    for vid, p in versions.items():
        links = [f"experiment:{e['id']}" for e in exp_by_version.get(vid, [])]
        model_items.append(AuditItem(kind="model_version", ref=str(vid), at=None, source=p["model"],
                                     facts={"model": p["model"], "family": p["family"], "version": p["version"],
                                            "code_version": p["model_code_version"], "train_from":
                                            _v(p["train_from"]), "train_to": _v(p["train_to"]),
                                            "n_train": p["n_train"], "status": p["version_status"]},
                                     links=links))
    for e in exps:
        model_items.append(AuditItem(kind="experiment", ref=str(e["id"]), at=e["finished_at"], source=e["uuid"],
                                     facts=_facts(e, "research_status", "gate_passed", "backtest_session_id",
                                                  "code_version", "dataset_hash"),
                                     links=[f"model_version:{e['model_version_id']}"]))
    no_model_state: StepState = "missing" if fsets else "not_applicable"
    steps.append(_step(
        "models", "Model versions", "recorded" if versions else no_model_state,
        (f"{len(versions)} model version(s); {len(exps)} registry experiment(s), "
         f"{sum(1 for e in exps if e['research_status'] == 'PRODUCTION')} in PRODUCTION") if versions else
        ("feature sets exist but no model has predicted this fixture" if fsets else
         "this fixture is not modelled (no feature set)"),
        model_items))
    pred_items = []
    for p in preds:
        links = [f"model_version:{p['model_version_id']}"]
        fs = by_input.get(p["feature_set_hash"])
        if fs is not None:
            links.append(f"feature_set:{fs['id']}")
        pred_items.append(AuditItem(
            kind="prediction", ref=str(p["id"]), at=p["created_at"], source=p["model"],
            facts={"market": p["market_key"], "selection": p["selection"], "line": _v(p["line"]),
                   "p": _v(p["p_calibrated"]), "p_lo": _v(p["p_lo"]), "p_hi": _v(p["p_hi"]),
                   "data_cutoff": _v(p["data_cutoff_ts"]), "input": "feature set" if fs is not None else
                   "training-set hash", "input_hash": p["feature_set_hash"],
                   "kind": "backtest" if p["backtest_session_id"] else "forecast",
                   "backtest_session_id": p["backtest_session_id"],
                   "cutoff_before_kickoff": p["data_cutoff_ts"] < fx["kickoff_at"]},
            links=links + ([f"session:{p['backtest_session_id']}"] if p["backtest_session_id"] else [])))
    steps.append(_step(
        "predictions", "Predictions", "recorded" if preds else no_model_state,
        (f"{len(preds)} probability rows from {len(versions)} model version(s); "
         f"{sum(1 for p in preds if p['data_cutoff_ts'] >= fx['kickoff_at'])} with a cut-off at or after kick-off")
        if preds else "no prediction", pred_items))

    # 7. market ----------------------------------------------------------------------
    market_items = []
    for o in repo.odds_summary(conn, fixture_id):
        market_items.append(AuditItem(kind="odds_snapshots", ref=f"{fixture_id}/{o['source']}", at=o["last_at"],
                                      source=o["source"],
                                      facts=_facts(o, "quotes", "bookmakers", "markets", "captures", "payloads",
                                                   "first_at", "closest_minutes_to_ko")))
    for n in repo.near_close(conn, fixture_id):
        market_items.append(AuditItem(kind="near_close", ref=f"{fixture_id}/{n['source']}", at=n["last_at"],
                                      source=n["source"],
                                      facts=_facts(n, "quotes", "bookmakers", "closest_minutes_to_ko",
                                                   "any_validated_close")))
    for h in repo.historical_odds(conn, fixture_id):
        market_items.append(AuditItem(kind="historical_odds", ref=f"{fixture_id}/{h['bookmaker_code']}/{h['price_kind']}",
                                      source=h["source"], facts=_facts(h, "bookmaker_code", "price_kind", "quotes"),
                                      links=[f"payload:{h['payload_hash']}"] if h["payload_hash"] else []))
    for b in repo.baselines(conn, fixture_id):
        market_items.append(AuditItem(
            kind="market_baseline", ref=f"{b['bookmaker_code']}/{b['price_kind']}/{b['devig_method']}",
            at=b["computed_at"], source=b["source"],
            facts=_facts(b, "p_home", "p_draw", "p_away", "overround"),
            links=[f"historical_odds:{fixture_id}/{b['bookmaker_code']}/{b['price_kind']}"]))
    for c in repo.consensus(conn, fixture_id):
        market_items.append(AuditItem(kind="consensus", ref=f"{c['market_key']}/{c['selection']}/{c['line']}",
                                      at=c["as_of"], source=c["devig_method"],
                                      facts=_facts(c, "p_fair", "n_bookmakers", "overround")))
    steps.append(_step(
        "market", "Market", "recorded" if market_items else ("missing" if finished else "not_applicable"),
        f"{len(market_items)} market record group(s)" if market_items else
        ("no market data was captured or imported for this fixture" if finished else "no capture yet"),
        market_items))

    # 8. picks -----------------------------------------------------------------------
    cands = repo.candidates(conn, fixture_id)
    pick_rows = repo.picks(conn, fixture_id)
    pick_items = [AuditItem(kind="pick_candidate", ref=str(c["id"]), at=c["evaluated_at"],
                            source=c["decision_rule_version"],
                            facts=_facts(c, "market_key", "selection", "line", "market_odds", "p_calibrated",
                                         "p_market_fair", "ev", "ev_adjusted", "decision", "rejection_reason",
                                         "data_cutoff_ts"),
                            links=[x for x in (f"prediction:{c['prediction_id']}" if c["prediction_id"] else None,
                                               f"payload:{c['odds_payload_hash']}" if c["odds_payload_hash"] else None)
                                   if x])
                  for c in cands]
    pick_items += [AuditItem(kind="pick", ref=str(p["id"]), at=p["created_at"], source=p["mode"],
                             facts=_facts(p, "market_key", "selection", "line", "market_odds", "p_calibrated",
                                          "p_market_fair", "ev", "stake_units", "status", "decision_rule_version",
                                          "code_version"),
                             links=[x for x in (f"pick_candidate:{p['candidate_id']}" if p["candidate_id"] else None,
                                                f"prediction:{p['prediction_id']}" if p["prediction_id"] else None,
                                                f"model_version:{p['model_version_id']}" if p["model_version_id"]
                                                else None) if x])
                   for p in pick_rows]
    accepted = sum(1 for c in cands if c["decision"] == "accepted")
    steps.append(_step(
        "picks", "Pick engine", "recorded" if cands or pick_rows else "not_applicable",
        (f"{len(cands)} candidate(s) evaluated, {accepted} accepted, {len(pick_rows)} pick(s)"
         + (" - NO VALUE FOUND is a valid outcome" if cands and not pick_rows else "")) if cands or pick_rows else
        "the pick engine did not evaluate this fixture", pick_items))

    # 9. settlement ------------------------------------------------------------------
    settle_items = [AuditItem(kind="settlement", ref=str(p["id"]), at=p["settled_at"], source=p["settled_by"],
                              facts=_facts(p, "result_status", "profit_units", "settlement_basis", "rule_version",
                                           "near_close_odds", "lv_devigged", "is_validated_close"),
                              links=[x for x in (f"pick:{p['id']}", f"payload:{p['result_payload_hash']}"
                                                 if p["result_payload_hash"] else None) if x])
                    for p in pick_rows if p["result_status"] is not None]
    unsettled = [p for p in pick_rows if p["result_status"] is None]
    if not pick_rows:
        s_state: StepState = "not_applicable"
        s_detail = "no pick to settle"
    elif unsettled and finished:
        s_state, s_detail = "missing", f"{len(unsettled)} pick(s) on a finished match are not settled"
    elif unsettled:
        s_state, s_detail = "not_applicable", f"{len(unsettled)} pick(s) wait for full time"
    else:
        s_state, s_detail = "recorded", f"{len(settle_items)} pick(s) settled from the recorded result"
    steps.append(_step("settlement", "Settlement", s_state, s_detail, settle_items))

    audit = MatchAudit(fixture_id=fx["id"], provider_fixture_id=fx["provider_fixture_id"], kickoff_at=fx["kickoff_at"],
                       status_group=fx["status_group"], steps=steps,
                       complete=all(s.state in ("recorded", "not_applicable") for s in steps))
    return Envelope[MatchAudit](status=DataStatus.OK, data=audit)
