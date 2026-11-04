"""The attribution of the shadow and the Learning Analyst's hypotheses, read for the Admin Console (plan IA, phase 5). Never a model call and never a
write: it reads ``intel.agent_attributions`` (what the server computed), the post-mortems of the selections, the narrative of the Post-Match Reviewer
(``ai.postmortem_narratives``, version ``pmr-v1``) and the hypotheses that name an agent (``analytics.research_hypotheses``).

The figures are counts of rows and shares of counts; the share of Gate B is reported against the plan's bar and never as a verdict.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fbi.ai import prompts
from fbi.ai.agents import analyst, attribution
from fbi.ai.calendar import day_bounds, local_day
from fbi.ai.config import AiSettings
from fbi.api.contracts.ai_attribution import (
    AttributionLine,
    AttributionOverview,
    AttributionSwitches,
    ClassCount,
    Coverage,
    HypothesisCount,
    HypothesisView,
    PostmortemAttribution,
    ScoreRow,
)
from fbi.api.envelope import Envelope, ok
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now

BAR: Final = 0.95
"""Plan section 24, Gate B: «atribución en ≥ 95 %»."""
POSTMORTEMS_MAX: Final = 60
HYPOTHESES_MAX: Final = 100

SELECTIONS_SQL: Final = """
WITH reviewed AS (
    SELECT DISTINCT r.fixture_id, r.market_key, r.selection, r.line
      FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id
     WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND r.mode = 'shadow' AND r.status = 'ok' AND r.reviewed_at < f.kickoff_at
       AND f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s),
settled AS (
    SELECT rv.*, pm.id AS postmortem_id FROM reviewed rv
      JOIN intel.selection_postmortems pm ON pm.fixture_id = rv.fixture_id AND pm.market_key = rv.market_key AND pm.selection = rv.selection AND pm.line = rv.line)
SELECT count(DISTINCT fixture_id) AS matches,
       count(DISTINCT fixture_id) FILTER (WHERE EXISTS (SELECT 1 FROM intel.agent_attributions a WHERE a.fixture_id = settled.fixture_id
                                                         AND a.attribution_version = %(version)s AND a.classified_by = 'code')) AS attributed_matches,
       count(*) AS selections,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM intel.agent_attributions a WHERE a.postmortem_id = settled.postmortem_id
                                       AND a.attribution_version = %(version)s AND a.classified_by = 'code')) AS attributed_selections
  FROM settled
"""

CLASSES_SQL: Final = """
SELECT a.agent, a.agent_version, a.error_class, count(*) AS n,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM intel.agent_attributions r WHERE r.basis_id = a.id)) AS refined
  FROM intel.agent_attributions a
 WHERE a.classified_by = 'code' AND a.signal = 'VERDICT' AND a.outcome = 'MISS' AND a.attribution_version = %(version)s AND a.computed_at >= %(since)s
 GROUP BY a.agent, a.agent_version, a.error_class ORDER BY a.agent, a.agent_version, a.error_class
"""

POSTMORTEMS_SQL: Final = """
SELECT pm.id AS postmortem_id, pm.fixture_id, th.name || ' - ' || ta.name AS match, f.kickoff_at, pm.market_key, pm.selection, pm.line, pm.settled,
       pm.clv, (SELECT a.calibration FROM intel.agent_attributions a WHERE a.postmortem_id = pm.id AND a.classified_by = 'code' LIMIT 1) AS calibration,
       (SELECT n.narrative FROM ai.postmortem_narratives n WHERE n.postmortem_id = pm.id AND n.version = %(pmr)s ORDER BY n.id DESC LIMIT 1) AS narrative
  FROM intel.selection_postmortems pm JOIN core.fixtures f ON f.id = pm.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE EXISTS (SELECT 1 FROM intel.agent_attributions a WHERE a.postmortem_id = pm.id AND a.classified_by = 'code' AND a.attribution_version = %(version)s)
   AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
 ORDER BY (SELECT count(*) FROM intel.agent_attributions a WHERE a.postmortem_id = pm.id AND a.outcome = 'MISS' AND a.signal = 'VERDICT') DESC,
          f.kickoff_at DESC, pm.id
 LIMIT %(limit)s
"""

LINES_SQL: Final = """
SELECT a.postmortem_id, a.engine, a.agent, a.agent_version, a.signal, a.stance, a.outcome, a.error_class, a.toward_close,
       (SELECT r.error_class FROM intel.agent_attributions r WHERE r.basis_id = a.id AND r.classified_by = 'pmr-v1') AS refined_class
  FROM intel.agent_attributions a
 WHERE a.postmortem_id = ANY(%(ids)s) AND a.classified_by = 'code' AND a.attribution_version = %(version)s
 ORDER BY a.postmortem_id, a.engine, a.agent, (a.signal <> 'VERDICT'), a.signal
"""

HYPOTHESES_SQL: Final = """
SELECT h.id, h.agent, h.agent_version, h.title, h.hypothesis, h.rationale, h.status, h.created_at, h.decided_at, h.evidence
  FROM analytics.research_hypotheses h WHERE h.agent IS NOT NULL ORDER BY h.created_at DESC, h.id DESC LIMIT %(limit)s
"""

COUNTS_SQL: Final = """
SELECT agent, agent_version, count(*) AS proposed, count(*) FILTER (WHERE status IN ('ACCEPTED', 'RUNNING', 'SHADOW', 'DONE', 'PROMOTED')) AS accepted,
       count(*) FILTER (WHERE status = 'REJECTED') AS rejected, count(*) FILTER (WHERE status IN ('PROPOSED', 'INVESTIGATING')) AS other
  FROM analytics.research_hypotheses WHERE agent IS NOT NULL GROUP BY agent, agent_version ORDER BY agent, agent_version
"""


def share(done: int, total: int) -> float | None:
    """A share of counts; None when there is nothing to divide: zero of zero is not 100 %."""
    return None if total == 0 else round(done / total, 4)


def number(x: Any) -> float | None:
    return None if x is None else float(Decimal(x))


def ids_of(evidence: Any) -> list[int]:
    found = (evidence or {}).get("attribution_ids") if isinstance(evidence, dict) else None
    return [int(i) for i in found if isinstance(i, int) and not isinstance(i, bool)] if isinstance(found, list) else []


def overview(conn: Conn, *, days: int = 14, at: datetime | None = None, settings: AiSettings | None = None) -> Envelope[AttributionOverview]:
    at = at or now()
    settings = settings or AiSettings.from_env()
    until_day = local_day(at)
    since_day = until_day - timedelta(days=days)
    since, until = day_bounds(since_day)[0], day_bounds(until_day)[1]
    window = {"since": since, "until": until, "version": attribution.VERSION}

    found = fetch_one(conn, SELECTIONS_SQL, window) or {}
    matches, attributed_matches = int(found.get("matches") or 0), int(found.get("attributed_matches") or 0)
    selections, attributed_selections = int(found.get("selections") or 0), int(found.get("attributed_selections") or 0)
    coverage = Coverage(since=since_day, until=until_day, matches=matches, attributed_matches=attributed_matches,
                        match_share=share(attributed_matches, matches), selections=selections, attributed_selections=attributed_selections,
                        selection_share=share(attributed_selections, selections), bar=BAR)

    scoreboard = [ScoreRow.model_validate(r) for r in attribution.scoreboard(conn, since=since)]
    classes = [ClassCount.model_validate(r) for r in fetch_all(conn, CLASSES_SQL, window)]

    rows = fetch_all(conn, POSTMORTEMS_SQL, window | {"pmr": prompts.PMR_VERSION, "limit": POSTMORTEMS_MAX})
    lines: dict[int, list[AttributionLine]] = defaultdict(list)
    if rows:
        for r in fetch_all(conn, LINES_SQL, {"ids": [int(x["postmortem_id"]) for x in rows], "version": attribution.VERSION}):
            lines[int(r["postmortem_id"])].append(AttributionLine.model_validate({k: v for k, v in r.items() if k != "postmortem_id"}))
    postmortems = [PostmortemAttribution(
        postmortem_id=int(r["postmortem_id"]), fixture_id=int(r["fixture_id"]), match=r["match"], kickoff_at=r["kickoff_at"], market_key=r["market_key"],
        selection=r["selection"], line=float(r["line"]), settled=r["settled"], calibration=r["calibration"], clv=number(r["clv"]),
        narrative=r["narrative"], lines=lines[int(r["postmortem_id"])]) for r in rows]

    hypotheses = []
    for r in fetch_all(conn, HYPOTHESES_SQL, {"limit": HYPOTHESES_MAX}):
        evidence = r["evidence"] if isinstance(r["evidence"], dict) else {}
        experiment = evidence.get("experiment")
        hypotheses.append(HypothesisView(
            id=int(r["id"]), agent=r["agent"], agent_version=r["agent_version"], title=r["title"], hypothesis=r["hypothesis"], rationale=r["rationale"],
            status=r["status"], created_at=r["created_at"], decided_at=r["decided_at"], attribution_ids=ids_of(evidence),
            experiment=experiment if isinstance(experiment, dict) else None, week_from=evidence.get("week_from") if isinstance(evidence.get("week_from"), str) else None))
    counts = [HypothesisCount.model_validate(r) for r in fetch_all(conn, COUNTS_SQL)]

    return ok(AttributionOverview(
        switches=AttributionSwitches(pm_reviewer=settings.pm_reviewer, learning_analyst=settings.learning_analyst, reviewer_version=prompts.PMR_VERSION,
                                     analyst_version=analyst.VERSION, attribution_version=attribution.VERSION),
        coverage=coverage, scoreboard=scoreboard, classes=classes, postmortems=postmortems, hypotheses=hypotheses, hypothesis_counts=counts, days=days))


__all__ = ["BAR", "overview", "share"]
