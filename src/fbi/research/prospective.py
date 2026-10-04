"""Forecasts made BEFORE kick-off, judged after it: the only test no backtest can fake.

Since 25 Sep 2026 every pipeline run has stored each model's forecast for the upcoming
matches (``models.predictions``, outside any backtest session) and captured the market's
prices. For every match played since, this takes:

  * per model family, the newest 1X2 forecast stored before kick-off;
  * the market's last de-vigged (Shin) 1X2 consensus captured before kick-off;
  * the 90-minute result of a match the historical validation did not quarantine;

and compares them per segment of football - the only evaluation against a market that
covers more than the five big leagues, because those are the only seasons with
historical prices. The samples are small (days, not seasons) and every number carries its
interval: a segment that cannot tell is reported as such.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import psycopg
from numpy.typing import NDArray
from psycopg.rows import dict_row

from fbi.backtesting.evaluate import Comparison, compare
from fbi.catalog.segments import CompetitionFacts, segment_of
from fbi.research.blend import weight_interval

SINCE = datetime.fromisoformat("2026-09-25T00:00:00+00:00")
MIN_SEGMENT = 50
"""Fewer matches than this in a segment: reported, not judged."""
MIN_DAYS = 5
"""Fewer match days than this: the day-block interval has nothing to resample - not judged."""

PROSPECTIVE_SQL = """
WITH played AS (
    SELECT f.id, f.kickoff_at, r.reg_goals_home AS h, r.reg_goals_away AS a, c.name AS competition,
           c.competition_type, c.entity_scope, c.tier
      FROM core.fixtures f
      JOIN core.fixture_results r ON r.fixture_id = f.id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
       AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM analytics.fixture_validation v WHERE v.fixture_id = f.id
                        AND v.state IN ('QUARANTINED', 'INGESTED'))
), forecast AS (
    SELECT DISTINCT ON (p.fixture_id, m.name) p.fixture_id, m.name AS model, p.model_version_id, p.data_cutoff_ts
      FROM models.predictions p
      JOIN played ON played.id = p.fixture_id
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry m ON m.id = v.model_id
     WHERE p.backtest_session_id IS NULL AND p.market_key = '1X2' AND p.data_cutoff_ts < played.kickoff_at
       AND p.created_at < played.kickoff_at
     ORDER BY p.fixture_id, m.name, p.data_cutoff_ts DESC
), forecast_rows AS (
    SELECT fc.fixture_id, fc.model,
           max(p.p_calibrated) FILTER (WHERE p.selection = 'Home') AS ph,
           max(p.p_calibrated) FILTER (WHERE p.selection = 'Draw') AS pd,
           max(p.p_calibrated) FILTER (WHERE p.selection = 'Away') AS pa
      FROM forecast fc
      JOIN models.predictions p ON p.fixture_id = fc.fixture_id AND p.model_version_id = fc.model_version_id
                               AND p.data_cutoff_ts = fc.data_cutoff_ts AND p.market_key = '1X2'
                               AND p.backtest_session_id IS NULL
     GROUP BY fc.fixture_id, fc.model
), close_at AS (
    SELECT mc.fixture_id, max(mc.as_of) AS as_of
      FROM market.market_consensus mc JOIN played ON played.id = mc.fixture_id
     WHERE mc.market_key = '1X2' AND mc.devig_method = 'shin' AND mc.as_of < played.kickoff_at
     GROUP BY mc.fixture_id
), market AS (
    SELECT mc.fixture_id,
           max(mc.p_fair) FILTER (WHERE mc.selection = 'Home') AS qh,
           max(mc.p_fair) FILTER (WHERE mc.selection = 'Draw') AS qd,
           max(mc.p_fair) FILTER (WHERE mc.selection = 'Away') AS qa,
           min(mc.n_bookmakers) AS books
      FROM market.market_consensus mc JOIN close_at ca ON ca.fixture_id = mc.fixture_id AND ca.as_of = mc.as_of
     WHERE mc.market_key = '1X2' AND mc.devig_method = 'shin'
     GROUP BY mc.fixture_id
)
SELECT played.*, fr.model, fr.ph, fr.pd, fr.pa, mk.qh, mk.qd, mk.qa, mk.books
  FROM played
  LEFT JOIN forecast_rows fr ON fr.fixture_id = played.id
  LEFT JOIN market mk ON mk.fixture_id = played.id
 ORDER BY played.kickoff_at, played.id
"""


def _triplet(a: Any, b: Any, c: Any) -> NDArray[np.float64] | None:
    if a is None or b is None or c is None:
        return None
    x = np.array([float(a), float(b), float(c)])
    s = x.sum()
    return None if s <= 0 else x / s


@dataclass
class SegmentResult:
    segment: str
    model: str
    n_played: int
    n_forecast: int
    n_common: int
    comparison: Comparison | None
    w: tuple[float, float, float] | None

    @property
    def judged(self) -> bool:
        c = self.comparison
        return c is not None and self.n_common >= MIN_SEGMENT and (c.n_blocks or 0) >= MIN_DAYS

    def as_json(self) -> dict[str, Any]:
        c = self.comparison
        return {"segment": self.segment, "model": self.model, "played": self.n_played,
                "forecast": self.n_forecast, "with_market": self.n_common,
                "days": None if c is None else c.n_blocks, "judged": self.judged,
                "model_logloss": None if c is None else c.model.log_loss,
                "market_logloss": None if c is None else c.baseline.log_loss,
                "diff": None if c is None else [c.logloss_diff.mean, c.logloss_diff.lo, c.logloss_diff.hi],
                "verdict": None if c is None else c.verdict, "evidence": None if c is None else c.evidence,
                "model_ece": None if c is None else c.model.ece, "market_ece": None if c is None else c.baseline.ece,
                "blend_w": None if self.w is None else list(self.w)}


@dataclass
class ProspectiveResult:
    since: datetime
    until: datetime
    played: int
    priced: int
    rows: list[SegmentResult]

    def as_json(self) -> dict[str, Any]:
        return {"since": self.since.isoformat(), "until": self.until.isoformat(), "played": self.played,
                "priced": self.priced, "min_segment": MIN_SEGMENT, "rows": [r.as_json() for r in self.rows]}


def evaluate_prospective(conn: psycopg.Connection[Any], *, until: datetime, since: datetime = SINCE
                         ) -> ProspectiveResult:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PROSPECTIVE_SQL, {"since": since, "until": until})
        rows = list(cur.fetchall())
    y: dict[int, int] = {}
    seg: dict[int, str] = {}
    day: dict[int, object] = {}
    moment: dict[int, object] = {}
    market: dict[int, NDArray[np.float64]] = {}
    forecasts: dict[str, dict[int, NDArray[np.float64]]] = defaultdict(dict)
    for r in rows:
        fid = int(r["id"])
        if fid not in y:
            h, a = int(r["h"]), int(r["a"])
            y[fid] = 0 if h > a else 1 if h == a else 2
            seg[fid] = segment_of(CompetitionFacts(str(r["competition"]), r["competition_type"], r["entity_scope"],
                                                   None if r["tier"] is None else int(r["tier"]))).value
            day[fid] = r["kickoff_at"].date().isoformat()
            moment[fid] = r["kickoff_at"].isoformat()
            q = _triplet(r["qh"], r["qd"], r["qa"])
            if q is not None and (r["books"] or 0) >= 2:
                market[fid] = q
        if r["model"] is not None:
            p = _triplet(r["ph"], r["pd"], r["pa"])
            if p is not None:
                forecasts[str(r["model"])][fid] = p
    out: list[SegmentResult] = []
    segments = sorted(set(seg.values()))
    for model, preds in sorted(forecasts.items()):
        for s in [*segments, "all"]:
            ids = {f for f in y if s == "all" or seg[f] == s}
            mine = {f: p for f, p in preds.items() if f in ids}
            common = sorted(set(mine) & set(market) & ids)
            c = compare(mine, market, y, baseline_key="market/close/shin", market_key="1X2", line=0.0,
                        only=set(common), blocks=day, order=moment) if common else None
            w = None
            if len(common) >= MIN_SEGMENT:
                w = weight_interval(np.array([market[f] for f in common]), np.array([mine[f] for f in common]),
                                    np.array([y[f] for f in common], dtype=np.int64), [day[f] for f in common],
                                    draws=300)
            out.append(SegmentResult(s, model, len(ids), len(mine), len(common), c, w))
    return ProspectiveResult(since, until, len(y), len(market), out)
