"""The attribution of the shadow and the Learning Analyst's hypotheses, for the Admin Console (plan IA, phase 5). Reading only: nothing here calls a
model, creates a task or changes a pick, a rule or a hypothesis.

What these shapes carry is what the server computed (``intel.agent_attributions``: the outcome of each agent's stance, the class of a miss, the closing
line, the calibration) and the codes of the agents. The only prose is the Post-Match Reviewer's narrative and the Learning Analyst's text: the AI wrote
them, they are shown and never measured, and a hypothesis carries the ids of the attributions it cites."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

Outcome = Literal["HIT", "MISS", "VOID"]


class AttributionSwitches(Contract):
    pm_reviewer: bool = Field(description="FBI_AI_PM_REVIEWER: the daily attribution and the Post-Match Reviewer. Off unless the owner switched it on.")
    learning_analyst: bool = Field(description="FBI_AI_LEARNING_ANALYST: the Learning Analyst, on Mondays. Off unless the owner switched it on.")
    reviewer_version: str
    analyst_version: str
    attribution_version: str


class Coverage(Contract):
    """Gate B's «atribución en ≥ 95 %»: of the matches that finished in the window and that a shadow engine reviewed, the ones with attributions. It is
    a count and a share, not a verdict: the gate decides, not this page."""

    since: date
    until: date
    matches: int
    attributed_matches: int
    match_share: float | None = Field(description="None when there is no match to judge: zero of zero is not 100 %.")
    selections: int = Field(description="Post-mortems of the selections the shadow reviewed.")
    attributed_selections: int
    selection_share: float | None
    bar: float = Field(description="The plan's bar for Gate B.")


class ScoreRow(Contract):
    agent: str
    agent_version: str
    engine: str
    hits: int
    misses: int
    voids: int
    hit_rate: float | None = Field(description="Hits over hits plus misses; None when the agent took no side.")


class ClassCount(Contract):
    agent: str
    agent_version: str
    error_class: str
    n: int
    refined: int = Field(description="How many of them carry the class the Post-Match Reviewer added to a miss the code left UNKNOWN.")


class AttributionLine(Contract):
    engine: str
    agent: str
    agent_version: str
    signal: str
    stance: str
    outcome: Outcome
    error_class: str = Field(description="The class of the code (NONE for a hit and a void).")
    refined_class: str | None = Field(description="The class the Post-Match Reviewer added to an UNKNOWN miss, as a second row; None otherwise.")
    toward_close: bool | None


class PostmortemAttribution(Contract):
    """One settled selection of the shadow with what each agent did about it."""

    postmortem_id: int
    fixture_id: int
    match: str
    kickoff_at: datetime
    market_key: str
    selection: str
    line: float
    settled: str
    calibration: str | None
    clv: float | None
    narrative: str | None = Field(default=None, description="The Post-Match Reviewer's, in words: the AI's, shown and never measured.")
    lines: list[AttributionLine]


class HypothesisView(Contract):
    id: int
    agent: str
    agent_version: str
    title: str
    hypothesis: str
    rationale: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    attribution_ids: list[int] = Field(description="The rows of intel.agent_attributions the hypothesis cites.")
    experiment: dict[str, Any] | None = Field(description="The experiment the analyst drafted: design, metric, family, what varies, sample.")
    week_from: str | None


class HypothesisCount(Contract):
    agent: str
    agent_version: str
    proposed: int
    accepted: int
    rejected: int
    other: int


class AttributionOverview(Contract):
    switches: AttributionSwitches
    coverage: Coverage
    scoreboard: list[ScoreRow]
    classes: list[ClassCount]
    postmortems: list[PostmortemAttribution]
    hypotheses: list[HypothesisView]
    hypothesis_counts: list[HypothesisCount]
    days: int
