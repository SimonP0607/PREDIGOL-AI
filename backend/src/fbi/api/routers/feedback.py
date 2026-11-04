"""What readers think of PrediGol over HTTP (plan UX, B6 and section 40).

* ``GET /me/feedback/survey`` - whether the monthly survey is owed (once every 30 days from the last answer or skip,
  never in the account's first week).
* ``POST /me/feedback/survey`` - the survey answered (1 to 5 and an optional comment): 201, or 409 ``survey_not_due``.
* ``POST /me/feedback/survey/skip`` - the survey closed: it does not come back for 30 days (204, idempotent).
* ``GET`` / ``PUT /me/feedback/helpful`` - «¿Te sirvió?» on a reading, a narrative, an explanation or an «Explícame»
  answer: the reader's answer, and the answer given (the last one counts).
* ``GET`` / ``POST /me/updates/seen`` - the newest entry of Novedades the reader has seen.
* ``GET /admin/product/feedback`` - the owner's view: the survey with its n, «¿Te sirvió?» per kind, the newest comments
  (never who wrote them) and the readers at risk by the survey.

The survey and the votes are product measurement: behind the consent gate (a reader who has not accepted the processing
is not asked), never behind the membership's (a limited reader's opinion counts too). Novedades read is the reader's
own state, like a dismissed hint. ``FBI_FEEDBACK=0`` turns the survey and the votes off; the answers stay.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query, Response

from fbi.api.contracts.feedback import (
    FeedbackComment,
    FeedbackOverview,
    HelpfulIn,
    HelpfulVote,
    Subject,
    SurveyAnswered,
    SurveyFigures,
    SurveyIn,
    SurveySkipIn,
    SurveyState,
    UpdatesSeen,
    UpdatesSeenIn,
    VoteFigures,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, same_site_only
from fbi.core.clock import now
from fbi.customer import feedback
from fbi.customer.db import CustomerError

router = APIRouter(prefix="/me/feedback", tags=["feedback"], dependencies=[Depends(same_site_only)])
updates_router = APIRouter(prefix="/me/updates", tags=["feedback"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/product", tags=["feedback"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _state(conn: psycopg.Connection[Any], user_id: int) -> SurveyState:
    s = feedback.survey_state(conn, user_id, at=now())
    return SurveyState(enabled=s.enabled, due=s.due, last_at=s.last_at, next_at=s.next_at)


@router.get("/survey", response_model=SurveyState)
def get_survey(conn: Db, principal: App) -> SurveyState:
    """Whether the monthly survey is owed to this reader now."""
    return _state(conn, principal.user_id)


@router.post("/survey", response_model=SurveyAnswered, status_code=201)
def answer_survey(body: SurveyIn, principal: App) -> SurveyAnswered:
    """The survey answered: 409 ``survey_not_due`` when it was answered or closed in the last 30 days, 404
    ``feedback_off`` while the owner keeps it off."""
    try:
        record = feedback.answer_survey(principal.user_id, body.score, body.comment, body.context.model_dump(), at=now())
    except CustomerError as exc:
        raise _refused(exc) from exc
    return SurveyAnswered(id=record)


@router.post("/survey/skip", status_code=204, response_class=Response)
def skip_survey(body: SurveySkipIn, principal: App) -> Response:
    """The survey closed without an answer: not again for 30 days. Idempotent."""
    feedback.skip_survey(principal.user_id, body.context.model_dump(), at=now())
    return Response(status_code=204)


@router.get("/helpful", response_model=HelpfulVote)
def get_vote(conn: Db, principal: App, subject: Annotated[Subject, Query()],
             subject_id: Annotated[int, Query(ge=1)]) -> HelpfulVote:
    """The reader's «¿Te sirvió?» on this thing read (null while they have given none)."""
    return HelpfulVote(subject=subject, subject_id=subject_id,
                       helpful=feedback.my_vote(conn, principal.user_id, subject, subject_id))


@router.put("/helpful", response_model=HelpfulVote)
def put_vote(body: HelpfulIn, principal: App) -> HelpfulVote:
    """«¿Te sirvió?» answered (the last answer counts): 429 ``too_many_votes`` past 300 in a day, 404 ``feedback_off``."""
    try:
        helpful = feedback.vote(principal.user_id, body.subject, body.subject_id, body.helpful, body.context.model_dump(),
                                at=now())
    except CustomerError as exc:
        raise _refused(exc) from exc
    return HelpfulVote(subject=body.subject, subject_id=body.subject_id, helpful=helpful)


@updates_router.get("/seen", response_model=UpdatesSeen)
def get_updates_seen(conn: Db, principal: App) -> UpdatesSeen:
    """The newest entry of Novedades the reader has seen: the page marks «Más» while a newer one exists."""
    return UpdatesSeen(last_seen=feedback.updates_seen(conn, principal.user_id))


@updates_router.post("/seen", response_model=UpdatesSeen)
def post_updates_seen(body: UpdatesSeenIn, principal: App) -> UpdatesSeen:
    """Novedades opened with ``id`` as its newest entry: 422 ``unknown_update`` for an id that is not one."""
    try:
        seen = feedback.mark_updates_seen(principal.user_id, body.id, at=now())
    except CustomerError as exc:
        raise _refused(exc) from exc
    return UpdatesSeen(last_seen=seen)


@admin_router.get("/feedback", response_model=FeedbackOverview)
def get_feedback_overview(conn: Db, days: Annotated[int, Query(ge=7, le=365)] = 90) -> FeedbackOverview:
    """The survey with its n, «¿Te sirvió?» per kind of thing read and the newest comments over the last ``days``, and the
    readers at risk by the survey (B11). Never who wrote a comment."""
    o = feedback.overview(conn, at=now(), days=days)
    s = o.survey
    return FeedbackOverview(
        enabled=o.enabled, since=o.since,
        survey=SurveyFigures(n=s.n, mean=s.mean, scores={str(k): v for k, v in s.scores.items()}, low=s.low,
                             skipped=s.skipped),
        votes=[VoteFigures(subject=v.subject, yes=v.yes, no=v.no) for v in o.votes],  # type: ignore[arg-type]
        comments=[FeedbackComment(at=c.at, score=c.score, comment=c.comment, trigger=c.trigger)  # type: ignore[arg-type]
                  for c in o.comments],
        at_risk=o.at_risk)
