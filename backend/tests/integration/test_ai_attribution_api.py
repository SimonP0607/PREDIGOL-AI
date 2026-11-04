"""The attribution in the Admin Console (plan IA, phase 5), read from a real database: the coverage of Gate B against the plan's bar, the scoreboard of the
agents, the post-mortems with the lines the server attributed and the narrative of the reviewer, and the hypotheses that name the agent that wrote them.

The match is seeded by hand (``attribution_world``). The service only reads: the test also holds that nothing in the database moves because it ran.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import prompts
from fbi.ai.agents import attribution as at
from fbi.ai.calendar import day_bounds
from fbi.ai.config import AiSettings
from fbi.api.services import ai_attribution, evolution
from tests.integration.attribution_world import AFTER, DAY, complete
from tests.integration.conftest import Seed
from tests.integration.test_agent_attribution import fingerprint

pytestmark = pytest.mark.integration

START, END = day_bounds(DAY)
AT = AFTER + timedelta(hours=1)
OFF = replace(AiSettings.from_env(), pm_reviewer=False, learning_analyst=False)


def settled(db: psycopg.Connection[Any], seed: Seed) -> None:
    complete(db, seed)
    at.compute(db, since=START, until=END, at=AFTER)


def test_with_nothing_to_show_the_shares_are_none_and_not_one_hundred_percent(db: psycopg.Connection[Any]) -> None:
    out = ai_attribution.overview(db, days=1, at=AT, settings=OFF).data
    assert out is not None
    assert (out.coverage.matches, out.coverage.selections) == (0, 0)
    assert (out.coverage.match_share, out.coverage.selection_share) == (None, None)
    assert out.coverage.bar == 0.95
    assert (out.postmortems, out.hypotheses, out.scoreboard, out.classes) == ([], [], [], [])
    assert (out.switches.pm_reviewer, out.switches.learning_analyst) == (False, False)


def test_a_settled_match_that_was_not_attributed_counts_against_the_bar(db: psycopg.Connection[Any], seed: Seed) -> None:
    complete(db, seed)
    out = ai_attribution.overview(db, days=1, at=AT, settings=OFF).data
    assert out is not None
    assert (out.coverage.matches, out.coverage.attributed_matches, out.coverage.match_share) == (1, 0, 0.0)
    assert (out.coverage.selections, out.coverage.attributed_selections, out.coverage.selection_share) == (1, 0, 0.0)
    assert out.postmortems == []


def test_an_attributed_match_is_covered_and_its_lines_are_shown_with_the_narrative(db: psycopg.Connection[Any], seed: Seed) -> None:
    settled(db, seed)
    pm = db.execute("SELECT postmortem_id FROM intel.agent_attributions WHERE postmortem_id IS NOT NULL LIMIT 1").fetchone()
    assert pm is not None
    db.execute("INSERT INTO ai.postmortem_narratives (postmortem_id, created_at, version, narrative, usage_ids) VALUES (%s, %s, %s, %s, %s)",
               (pm[0], AFTER, prompts.PMR_VERSION, "El mercado sabía algo que el modelo no leyó.", []))
    out = ai_attribution.overview(db, days=1, at=AT, settings=OFF).data
    assert out is not None
    assert (out.coverage.match_share, out.coverage.selection_share) == (1.0, 1.0)
    assert len(out.postmortems) == 1
    shown = out.postmortems[0]
    assert shown.narrative == "El mercado sabía algo que el modelo no leyó."
    assert shown.lines and {line.outcome for line in shown.lines} <= {"HIT", "MISS", "VOID"}
    assert any(line.signal == "VERDICT" and line.outcome == "MISS" for line in shown.lines)
    assert sum(c.n for c in out.classes) == sum(1 for line in shown.lines if line.signal == "VERDICT" and line.outcome == "MISS")
    assert out.scoreboard, "the agents that were right and wrong are counted"


def test_a_narrative_of_another_version_is_not_the_reviewers(db: psycopg.Connection[Any], seed: Seed) -> None:
    settled(db, seed)
    pm = db.execute("SELECT postmortem_id FROM intel.agent_attributions WHERE postmortem_id IS NOT NULL LIMIT 1").fetchone()
    assert pm is not None
    db.execute("INSERT INTO ai.postmortem_narratives (postmortem_id, created_at, version, narrative, usage_ids) VALUES (%s, %s, 'pm-narr-v1', 'otra', %s)",
               (pm[0], AFTER, []))
    out = ai_attribution.overview(db, days=1, at=AT, settings=OFF).data
    assert out is not None and out.postmortems[0].narrative is None


def test_hypotheses_that_name_an_agent_are_listed_with_their_version_and_the_evidence_they_cite(db: psycopg.Connection[Any], seed: Seed) -> None:
    settled(db, seed)
    ids = [int(r[0]) for r in db.execute("SELECT id FROM intel.agent_attributions ORDER BY id LIMIT 2").fetchall()]
    db.execute("INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, evidence, created_at, status, agent, agent_version) "
               "VALUES ('ai', 'Una hipótesis de la IA', 'h', 'r', %s, %s, 'PROPOSED', 'council', 'council-v1')",
               (Jsonb({"attribution_ids": ids, "week_from": "2026-09-07", "experiment": {"name": "x"}}), AFTER))
    db.execute("INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, evidence, created_at, status) "
               "VALUES ('owner', 'Del dueño', 'h', 'r', '{}', %s, 'PROPOSED')", (AFTER,))
    out = ai_attribution.overview(db, days=1, at=AT, settings=OFF).data
    assert out is not None
    assert [h.title for h in out.hypotheses] == ["Una hipótesis de la IA"], "the hypotheses nobody attributed to an agent are not this panel's"
    h = out.hypotheses[0]
    assert (h.agent, h.agent_version, h.attribution_ids, h.week_from, h.experiment) == ("council", "council-v1", ids, "2026-09-07", {"name": "x"})
    assert [(c.agent, c.agent_version, c.proposed, c.accepted) for c in out.hypothesis_counts] == [("council", "council-v1", 1, 0)]


def test_reading_it_moves_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    settled(db, seed)
    before = fingerprint(db)
    ai_attribution.overview(db, days=1, at=AT, settings=OFF)
    assert fingerprint(db) == before


def test_the_switches_are_shown_as_they_are(db: psycopg.Connection[Any]) -> None:
    on = replace(OFF, pm_reviewer=True)
    out = ai_attribution.overview(db, days=1, at=AT, settings=on).data
    assert out is not None and (out.switches.pm_reviewer, out.switches.learning_analyst) == (True, False)


def test_the_evolution_page_knows_which_agent_and_version_a_hypothesis_is_about(db: psycopg.Connection[Any]) -> None:
    db.execute("INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, evidence, created_at, status, agent, agent_version) "
               "VALUES ('ai', 'Una hipótesis de la IA', 'h', 'r', '{}', %s, 'PROPOSED', 'match', 'match-v1')", (AFTER,))
    db.execute("INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, evidence, created_at, status) "
               "VALUES ('owner', 'Del dueño sin agente', 'h', 'r', '{}', %s, 'PROPOSED')", (AFTER,))
    overview = evolution.overview(db, at=AT).data
    assert overview is not None
    shown = {h.title: (h.agent, h.agent_version) for h in overview.hypotheses}
    assert shown["Una hipótesis de la IA"] == ("match", "match-v1")
    assert shown["Del dueño sin agente"] == (None, None)
