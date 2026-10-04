"""E0: where did the shadow picks' returns come from? Price, edge or luck.

Every settled shadow pick is set against the market's own view of it just before kick-off:
the de-vigged consensus (Shin) for the same selection and line, the last one captured before
the match. With the price the pick took (o), its push probability (u) and that closing
probability (p, conditional on the bet settling):

    EV at the close   = p (1 - u) o + u - 1     what the bet was worth by the market's view
    claimed EV        = the model's own EV when the pick was made
    luck              = realised return - EV at the close

A realised return well below zero with an EV at the close near zero is bad luck; with the
EV at the close itself well below zero, the picks were bets the market priced correctly and
the model did not - adverse selection, the "finding value on longshots" pattern
(``docs/research/MODEL_RESEARCH_V2_2026.md`` section 2). Standard errors are of the mean
per pick (flat one-unit stakes), so the reading carries its uncertainty.

Read only. No threshold is changed here: this is a diagnosis of the inputs, not a fix.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.catalog.segments import CompetitionFacts, segment_of

ODDS_BUCKETS: tuple[tuple[float, float], ...] = ((1.0, 1.6), (1.6, 2.2), (2.2, 3.0), (3.0, 5.0), (5.0, math.inf))

AUDIT_SQL = """
WITH settled AS (
    SELECT p.id, p.fixture_id, p.market_key, p.selection, p.line, p.market_odds, p.p_calibrated, p.p_push, p.ev,
           p.p_market_fair, p.created_at, r.result_status, r.profit_units, f.kickoff_at, c.name AS competition,
           c.competition_type, c.entity_scope, c.tier, m.name AS model
      FROM picks.picks p
      JOIN picks.pick_results r ON r.pick_id = p.id AND r.result_status <> 'pending'
      JOIN core.fixtures f ON f.id = p.fixture_id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry m ON m.id = v.model_id
     WHERE r.profit_units IS NOT NULL
), close AS (
    SELECT DISTINCT ON (s.id) s.id, mc.p_fair AS p_close, mc.as_of AS close_at, mc.n_bookmakers
      FROM settled s
      JOIN market.market_consensus mc ON mc.fixture_id = s.fixture_id AND mc.market_key = s.market_key
                                     AND mc.selection = s.selection AND mc.line = s.line
     WHERE mc.devig_method = 'shin' AND mc.as_of < s.kickoff_at
     ORDER BY s.id, mc.as_of DESC
)
SELECT s.*, c.p_close, c.close_at, c.n_bookmakers FROM settled s LEFT JOIN close c ON c.id = s.id ORDER BY s.id
"""


@dataclass(frozen=True, slots=True)
class AuditedPick:
    pick_id: int
    market_key: str
    model: str
    segment: str
    odds: float
    push: float
    profit: float
    claimed_ev: float
    ev_close: float | None
    clv: float | None
    minutes_before: float | None


@dataclass
class Group:
    n: int = 0
    profits: list[float] = field(default_factory=list)
    odds: list[float] = field(default_factory=list)
    claimed: list[float] = field(default_factory=list)
    ev_close: list[float] = field(default_factory=list)
    luck: list[float] = field(default_factory=list)
    clv: list[float] = field(default_factory=list)

    def add(self, p: AuditedPick) -> None:
        self.n += 1
        self.profits.append(p.profit)
        self.odds.append(p.odds)
        self.claimed.append(p.claimed_ev)
        if p.ev_close is not None:
            self.ev_close.append(p.ev_close)
            self.luck.append(p.profit - p.ev_close)
        if p.clv is not None:
            self.clv.append(p.clv)

    @staticmethod
    def _mean_se(xs: list[float]) -> tuple[float | None, float | None]:
        if not xs:
            return None, None
        mean = sum(xs) / len(xs)
        if len(xs) < 2:
            return mean, None
        var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
        return mean, math.sqrt(var / len(xs))

    def summary(self) -> dict[str, Any]:
        roi, roi_se = self._mean_se(self.profits)
        evc, evc_se = self._mean_se(self.ev_close)
        luck, luck_se = self._mean_se(self.luck)
        clv, clv_se = self._mean_se(self.clv)
        claimed, _ = self._mean_se(self.claimed)
        return {"n": self.n, "mean_odds": None if not self.odds else round(sum(self.odds) / len(self.odds), 3),
                "profit_units": round(sum(self.profits), 2), "roi": roi, "roi_se": roi_se,
                "claimed_ev": claimed, "n_with_close": len(self.ev_close), "ev_at_close": evc,
                "ev_at_close_se": evc_se, "luck": luck, "luck_se": luck_se, "clv": clv, "clv_se": clv_se}


def bucket_of(odds: float) -> str:
    for lo, hi in ODDS_BUCKETS:
        if lo <= odds < hi:
            return f"{lo:.1f}-{hi:.1f}" if math.isfinite(hi) else f"{lo:.1f}+"
    return "other"


def audited(rows: list[dict[str, Any]]) -> list[AuditedPick]:
    out = []
    for r in rows:
        o = float(r["market_odds"])
        u = float(r["p_push"] or 0)
        p_close = None if r["p_close"] is None else float(r["p_close"])
        ev_close = None if p_close is None else p_close * (1 - u) * o + u - 1
        clv = None if p_close is None else o * p_close - 1
        minutes = None if r["close_at"] is None else (r["kickoff_at"] - r["close_at"]).total_seconds() / 60
        seg = segment_of(CompetitionFacts(str(r["competition"]), r["competition_type"], r["entity_scope"],
                                          None if r["tier"] is None else int(r["tier"]))).value
        out.append(AuditedPick(int(r["id"]), str(r["market_key"]), str(r["model"]), seg, o, u,
                               float(r["profit_units"]), float(r["ev"]), ev_close, clv, minutes))
    return out


@dataclass
class AuditResult:
    at: datetime
    picks: list[AuditedPick]
    overall: dict[str, Any]
    by_odds: dict[str, dict[str, Any]]
    by_market: dict[str, dict[str, Any]]
    by_segment: dict[str, dict[str, Any]]
    by_model: dict[str, dict[str, Any]]
    median_minutes_before: float | None

    def as_json(self) -> dict[str, Any]:
        return {"at": self.at.isoformat(), "overall": self.overall, "by_odds": self.by_odds,
                "by_market": self.by_market, "by_segment": self.by_segment, "by_model": self.by_model,
                "median_close_minutes_before_kickoff": self.median_minutes_before,
                "method": "EV at the close = p_close*(1-push)*odds + push - 1, p_close the last Shin consensus "
                          "before kick-off; luck = realised - EV at the close; SE of the mean per pick"}


def audit_picks(conn: psycopg.Connection[Any], *, at: datetime) -> AuditResult:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(AUDIT_SQL)
        rows = list(cur.fetchall())
    picks = audited(rows)
    overall = Group()
    groups: dict[str, dict[str, Group]] = {k: defaultdict(Group) for k in ("odds", "market", "segment", "model")}
    for p in picks:
        overall.add(p)
        groups["odds"][bucket_of(p.odds)].add(p)
        groups["market"][p.market_key].add(p)
        groups["segment"][p.segment].add(p)
        groups["model"][p.model].add(p)
    minutes = sorted(p.minutes_before for p in picks if p.minutes_before is not None)
    median = minutes[len(minutes) // 2] if minutes else None
    order = [bucket_of((lo + min(hi, lo + 1)) / 2) for lo, hi in ODDS_BUCKETS]
    return AuditResult(
        at, picks, overall.summary(),
        {k: groups["odds"][k].summary() for k in order if k in groups["odds"]},
        {k: g.summary() for k, g in sorted(groups["market"].items())},
        {k: g.summary() for k, g in sorted(groups["segment"].items())},
        {k: g.summary() for k, g in sorted(groups["model"].items())}, median)
