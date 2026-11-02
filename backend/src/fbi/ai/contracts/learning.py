"""``la-v1``: what the Learning Analyst (Sonnet 5.5, Batch, Mondays) proposes - at most five hypotheses a week, each with the experiment
that would test it.

It only PROPOSES. PrediGol experiments, the gates validate and the owner promotes (section 13 of the plan): a hypothesis goes to
``analytics.research_hypotheses`` as ``PROPOSED`` (``proposed_by = 'ai'``), an experiment draft to ``analytics.experiments`` as a draft,
and nothing of either changes a prompt, a threshold, a model or the router. The analyst has no database of its own - the backend
writes what it answers - and the worker's role, which runs that job, cannot sign a promotion of an agent in ``intel.promotions`` (a row
policy, ``migrations`` 0111): only the owner's signed order can, and the automatic roll-back through a role of its own. The database
enforces it, not the prompt.

Each hypothesis cites the attributions it rests on (``attribution_ids``: rows of ``intel.agent_attributions``) and says, BEFORE
anything runs, the metric, the family, the design and the sample the experiment needs: a hypothesis is tested forward, on data later
than the data that inspired it, and with its power declared. The text of a hypothesis is the analyst's own prose: untrusted, shown to
the owner, never an instruction.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, field_validator

from fbi.ai.contracts.base import Contract, Family

HYPOTHESES_MAX: Final = 5
"""A week's."""
ATTRIBUTIONS_MAX: Final = 20
TITLE_MIN: Final = 5
TITLE_MAX: Final = 160
TEXT_MAX: Final = 600

Metric = Literal["CLV", "BRIER", "LOG_LOSS", "INVALID_RATE", "COST_PER_SELECTION", "STABILITY"]
Design = Literal["SHADOW_ARM", "REPLAY", "RULE_VARIANT"]
Varies = Literal["PROMPT", "SCHEMA", "MODEL", "RULE", "ROUTER"]
"""What the experiment's arm would change: the analyst says it, and the owner decides whether it runs."""
Subject = Literal["match", "stats", "council", "reviewer"]


class ExperimentDraft(Contract):
    design: Design
    metric: Metric
    family: Family
    varies: Varies
    required_sample: int


class Hypothesis(Contract):
    title: str = Field(max_length=TITLE_MAX)
    hypothesis: str = Field(max_length=TEXT_MAX)
    rationale: str = Field(max_length=TEXT_MAX)
    agent: Subject
    agent_version: str = Field(max_length=40)
    attribution_ids: list[int] = Field(max_length=ATTRIBUTIONS_MAX)
    experiment: ExperimentDraft

    @field_validator("title")
    @classmethod
    def _a_title_a_person_can_read(cls, v: str) -> str:
        if len(v.strip()) < TITLE_MIN:
            raise ValueError("a title has at least five characters")
        return v

    @field_validator("attribution_ids")
    @classmethod
    def _cites_something(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("a hypothesis cites the attributions it rests on")
        if len(set(v)) != len(v) or any(i < 1 for i in v):
            raise ValueError("attribution ids are positive and cited once")
        return v

    @field_validator("experiment")
    @classmethod
    def _a_sample_to_plan_with(cls, v: ExperimentDraft) -> ExperimentDraft:
        if v.required_sample < 1:
            raise ValueError("the experiment declares the sample it needs")
        return v


class LearningOut(Contract):
    contract: Literal["la-v1"]
    hypotheses: list[Hypothesis] = Field(max_length=HYPOTHESES_MAX)
