"""Read the research registry for the Admin Console (``GET /admin/research/v2``)."""

from __future__ import annotations

from typing import Any

from fbi.api.contracts.research import LegacyRun, ResearchEntry, ResearchOverview
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.repositories import Conn, fetch_all, fetch_one

LATEST_SQL = """
SELECT split_part(name, ':', 1) AS run, max(finished_at) AS finished_at
  FROM analytics.experiments
 WHERE run_label = 'RESEARCH_V2' AND status = 'completed' AND name LIKE 'research-v2-%%'
 GROUP BY 1 ORDER BY 2 DESC LIMIT 1
"""

ROWS_SQL = """
SELECT id, name, kind, model_family, role, role_reason, segment, finished_at, data_as_of, feature_version, metrics
  FROM analytics.experiments
 WHERE run_label = 'RESEARCH_V2' AND status = 'completed' AND split_part(name, ':', 1) = %(run)s
 ORDER BY kind, id
"""

LEGACY_SQL = """
SELECT id, name, model_family, research_status, finished_at, metrics->'vs_primary'->'logloss_diff' AS diff
  FROM analytics.experiments WHERE run_label = 'LEGACY_RESEARCH_RUN' ORDER BY id
"""

PROMOTED_SQL = "SELECT count(*) AS n FROM analytics.experiments WHERE research_status = 'PRODUCTION'"


def _summary(kind: str, m: dict[str, Any]) -> dict[str, Any]:
    if kind == "backtest":
        v2 = m.get("research_v2") or {}
        own = m.get("own_sample") or {}
        blends = v2.get("blends") or {}
        champion = v2.get("champion")
        return {"n": own.get("n"), "logloss": own.get("log_loss"), "ece": own.get("ece"),
                "vs_champion": v2.get("vs_champion"), "blend": blends.get(champion) if champion else None,
                "blend_pre_closing": blends.get("AVG/pre_closing/shin"),
                "coverage": (m.get("coverage") or {}).get("predicted")}
    if kind == "market":
        return {"logloss": m.get("common_logloss"), "n": m.get("n_common"),
                "own_sample": m.get("own_sample"), "mean_overround": m.get("mean_overround")}
    if kind == "prospective":
        return {"played": m.get("played"), "priced": m.get("priced"), "segments": m.get("segments"),
                "segment_roles": m.get("segment_roles")}
    if kind == "audit":
        return {k: m.get(k) for k in ("overall", "by_odds", "by_market", "by_segment", "by_model",
                                      "median_close_minutes_before_kickoff", "method")}
    return {}


def _entry(r: dict[str, Any]) -> ResearchEntry:
    return ResearchEntry(experiment_id=int(r["id"]), name=r["name"], kind=r["kind"], model_family=r["model_family"],
                         role=r["role"], role_reason=r["role_reason"], segment=r["segment"],
                         finished_at=r["finished_at"], data_as_of=r["data_as_of"],
                         metrics=_summary(r["kind"], dict(r["metrics"] or {})))


def overview(conn: Conn) -> Envelope[ResearchOverview]:
    legacy = [LegacyRun(experiment_id=int(r["id"]), name=r["name"], model_family=r["model_family"],
                        research_status=r["research_status"], finished_at=r["finished_at"],
                        vs_primary=None if r["diff"] is None else [float(r["diff"]["mean"]), float(r["diff"]["lo"]),
                                                                   float(r["diff"]["hi"])])
              for r in fetch_all(conn, LEGACY_SQL)]
    promoted = fetch_one(conn, PROMOTED_SQL)
    latest = fetch_one(conn, LATEST_SQL)
    if latest is None:
        body = ResearchOverview(run=None, finished_at=None, data_as_of=None, feature_version=None, champion=None,
                                qualified_models=int(promoted["n"]) if promoted else 0, challengers=0, models=[],
                                markets=[], prospective=[], audit=None, legacy=legacy)
        return unavailable(body, "no research-V2 run has been stored yet (python -m scripts.research_v2 --apply)",
                           status=DataStatus.NOT_AVAILABLE)
    rows = fetch_all(conn, ROWS_SQL, {"run": latest["run"]})
    entries = [_entry(r) for r in rows]
    models = [e for e in entries if e.kind == "backtest"]
    markets = sorted((e for e in entries if e.kind == "market"),
                     key=lambda e: (e.role != "CHAMPION", e.metrics.get("logloss") or 9))
    champion = next((e.name.split(":market:", 1)[-1] for e in markets if e.role == "CHAMPION"), None)
    first = rows[0] if rows else {}
    return ok(ResearchOverview(
        run=str(latest["run"]), finished_at=latest["finished_at"],
        data_as_of=max((e.data_as_of for e in entries if e.data_as_of), default=None),
        feature_version=first.get("feature_version"), champion=champion,
        qualified_models=int(promoted["n"]) if promoted else 0,
        challengers=sum(1 for e in models if e.role == "CHALLENGER"),
        models=sorted(models, key=lambda e: (["CHALLENGER", "RESEARCH", "REJECTED"].index(e.role)
                                             if e.role in ("CHALLENGER", "RESEARCH", "REJECTED") else 3,
                                             e.metrics.get("logloss") or 9)),
        markets=markets, prospective=[e for e in entries if e.kind == "prospective"],
        audit=next((e for e in entries if e.kind == "audit"), None), legacy=legacy))
