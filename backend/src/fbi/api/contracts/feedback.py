"""What readers think of PrediGol (plan UX, B6): the monthly survey, «¿Te sirvió?», Novedades read, and the owner's view of
them in /admin/product. The opinion improves the product and never enters the models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

Subject = Literal["reading", "narrative", "explanation", "explain"]
Trigger = Literal["analysis_opened", "result_seen"]


class FeedbackContext(BaseModel):
    """Where it was asked, and nothing else: never a form's content."""

    model_config = ConfigDict(extra="forbid")

    trigger: Trigger | None = Field(default=None, description="The useful moment after which the survey was offered.")
    route: str | None = Field(default=None, max_length=200, description="The page's path (no query): kept up to 80 "
                                                                        "characters.")


class SurveyState(Contract):
    enabled: bool = Field(description="FBI_FEEDBACK: false while the owner keeps the survey and the votes off.")
    due: bool = Field(description="Owed: on, the account past its first week, and no answer or skip in the last 30 "
                                  "days. The page offers it after a useful moment, never at sign-in and never after an "
                                  "error.")
    last_at: datetime | None
    next_at: datetime | None = Field(description="From when it is owed (null while it is owed, or off): the end of the "
                                                 "account's first week, or 30 days after the last answer or skip.")


class SurveyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=1, le=5, description="«¿Qué tan útil te resultó PrediGol este mes?», 1 to 5.")
    comment: str | None = Field(default=None, max_length=2000,
                                description="«¿Qué faltó?» (1-3) or «¿Qué fue lo más útil?» (4-5): optional; kept up to "
                                            "1,000 characters, without addresses or long numbers.")
    context: FeedbackContext = Field(default_factory=FeedbackContext)


class SurveySkipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: FeedbackContext = Field(default_factory=FeedbackContext)


class SurveyAnswered(Contract):
    id: int


class HelpfulIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: Subject
    subject_id: int = Field(ge=1, description="The thing read: the match of a reading or a narrative, the pick of an "
                                              "explanation.")
    helpful: bool
    context: FeedbackContext = Field(default_factory=FeedbackContext)


class HelpfulVote(Contract):
    subject: Subject
    subject_id: int
    helpful: bool | None = Field(description="The reader's answer; null while they have given none.")


class UpdatesSeen(Contract):
    last_seen: str | None = Field(description="The newest entry of Novedades the reader has seen (its id); null: none.")


class UpdatesSeenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=12, max_length=60, description="The newest entry shown: «2026-10-27-mis-picks».")


class SurveyFigures(Contract):
    n: int = Field(description="Answers in the period.")
    mean: float | None = Field(description="Their mean, 1 to 5; null without answers. Read it with its n.")
    scores: dict[str, int] = Field(description="Answers per score, \"1\" to \"5\".")
    low: int = Field(description="Answers of 2 or less.")
    skipped: int = Field(description="Surveys closed without an answer.")


class VoteFigures(Contract):
    subject: Subject
    yes: int
    no: int


class FeedbackComment(Contract):
    at: datetime
    score: int
    comment: str
    trigger: Trigger | None


class FeedbackOverview(Contract):
    enabled: bool
    since: datetime
    survey: SurveyFigures
    votes: list[VoteFigures] = Field(description="«¿Te sirvió?» per kind of thing read, in the period.")
    comments: list[FeedbackComment] = Field(description="The newest comments with their score and date - never who wrote "
                                                        "them (the reader's card is B10's).")
    at_risk: int = Field(description="Readers whose last survey of the last 30 days was 2 or less (EN RIESGO, B11).")
