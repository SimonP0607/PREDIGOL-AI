"""The PRIVATE queue of moderation of the news (IA-102, plan piece AD-G05). SUPER_ADMIN only: the router is mounted under
``/api/v1/admin`` behind ``require_admin`` (``fbi.api.app``), and nothing here is a reader's view - ``FBI_NEWS_V2`` stays off.

* ``GET  /admin/news/moderation`` - the stories in the queue (``en_moderacion``) or withdrawn (``status=retirada``), newest first, each
  with its register. The rule or the request that sent it there, its type, category, level and PrediGol's own text if it has one.
* ``GET  /admin/news/stories/{story_key}`` - one story as the owner sees it: every article (outlet, date, link, what its source allows
  now), the attempts of its own text and the register.
* ``POST /admin/news/stories/{story_key}/request``  - record a request of withdrawal (who asked: a kind, and a reference - never a
  person's contact) and hide the story until the owner decides.
* ``POST /admin/news/stories/{story_key}/withdraw`` - withdraw it (a new version ``retirada``; the register says why and at whose request).
* ``POST /admin/news/stories/{story_key}/restore``  - put a withdrawn story back.
* ``POST /admin/news/stories/{story_key}/approve``  - take a story out of the queue as it is.
* ``POST /admin/news/stories/{story_key}/dismiss``  - turn a request of withdrawal down (recorded) and take the story out of the queue.

Every act is a new version of the story and a line of ``news.moderation_log``: nothing is edited or deleted. The articles' own titles are
private metadata and are NOT returned (an admin view does not need a third party's words to moderate: the link opens the article)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from fbi.ai import source_policy
from fbi.api.deps import get_db
from fbi.api.problem import ApiError
from fbi.api.security import Admin
from fbi.customer.db import write_connection
from fbi.newsroom import moderation

router = APIRouter(tags=["admin: news moderation"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
StoryKey = Annotated[str, Path(pattern=r"^st-[a-z0-9][a-z0-9-]{3,62}$")]
Requester = Literal["titular_derechos", "persona_mencionada", "club", "medio", "dueno", "otro"]


class ActOut(BaseModel):
    at: datetime
    action: str
    rule: str | None
    reason: str
    requested_by: str
    reference: str | None
    decided_by: str


class QueuedStory(BaseModel):
    story_key: str
    version: int
    at: datetime
    status: str
    status_reason: str | None
    claim_type: str | None
    category: str | None
    level: str | None
    lang: str | None
    country: str | None
    headline_es: str | None
    summary_es: str | None
    log: list[ActOut]


class ModerationQueue(BaseModel):
    status: str
    since: datetime
    stories: list[QueuedStory]


class ItemOut(BaseModel):
    source_name: str
    source_domain: str
    source_state: str
    publish_level: str
    """What may ever be shown of it: the stricter of the copy and the policy in force."""
    url: str
    published_at: datetime | None
    seen_at: datetime


class TextAttempt(BaseModel):
    at: datetime
    outcome: str
    problems: list[str]
    metrics: dict[str, Any]
    cost_usd: str


class StoryAdmin(BaseModel):
    story: QueuedStory
    items: list[ItemOut]
    texts: list[TextAttempt]


class ActIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    requested_by: Requester = "dueno"
    reference: str | None = Field(default=None, max_length=200)


class Done(BaseModel):
    story_key: str
    action: str
    log_id: int
    status: str


def _act(a: moderation.Act) -> ActOut:
    return ActOut(at=a.at, action=a.action, rule=a.rule, reason=a.reason, requested_by=a.requested_by, reference=a.reference,
                  decided_by=a.decided_by)


def _queued(r: dict[str, Any], log: list[moderation.Act]) -> QueuedStory:
    return QueuedStory(story_key=r["story_key"], version=int(r["version"]), at=r["at"], status=r["status"], status_reason=r["status_reason"],
                       claim_type=r["claim_type"], category=r["category"], level=r["level"], lang=r["lang"], country=r["country"],
                       headline_es=r["headline_es"], summary_es=r["summary_es"], log=[_act(a) for a in log])


@router.get("/news/moderation", response_model=ModerationQueue)
def get_queue(conn: Db, status: Literal["en_moderacion", "retirada"] = "en_moderacion",
              days: Annotated[int, Query(ge=1, le=365)] = 30) -> ModerationQueue:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = moderation.queue(conn, since=since, statuses=(status,))
    return ModerationQueue(status=status, since=since, stories=[_queued(r, r["log"]) for r in rows])


@router.get("/news/stories/{story_key}", response_model=StoryAdmin)
def get_story(conn: Db, story_key: StoryKey) -> StoryAdmin:
    found = moderation.story_for_owner(conn, story_key)
    if found is None:
        raise ApiError(404, "not_found", "No existe esa historia.")
    policy = source_policy.load(conn)

    def publish(r: dict[str, Any]) -> str:
        """The stricter of the copy written when the article was seen and the policy in force (as ``fbi.news.readers``)."""
        order = {"none": 0, "link": 1, "summary": 2}
        now = "none" if policy is None else source_policy.can_publish(policy.standing(r["canonical_url"])).level
        return min(str(r["publish_level"]), now, key=lambda w: order[w])

    return StoryAdmin(story=_queued(found, found["log"]),
                      items=[ItemOut(source_name=r["source_name"], source_domain=r["source_domain"], source_state=r["source_state"],
                                     publish_level=publish(r), url=r["canonical_url"], published_at=r["published_at"], seen_at=r["seen_at"])
                             for r in found["items"]],
                      texts=[TextAttempt(at=r["at"], outcome=r["outcome"], problems=list(r["problems"] or []),
                                         metrics=dict(r["metrics"] or {}), cost_usd=str(r["cost_usd"])) for r in found["texts"]])


def _do(story_key: str, action: str, body: ActIn, actor_id: int) -> Done:
    at = datetime.now(UTC)
    try:
        with write_connection() as conn:
            if action == "request":
                log_id = moderation.request(conn, story_key, at=at, reason=body.reason, requested_by=body.requested_by,
                                            reference=body.reference, actor_user_id=actor_id)
            elif action == "withdraw":
                log_id = moderation.withdraw(conn, story_key, at=at, reason=body.reason, requested_by=body.requested_by,
                                             reference=body.reference, actor_user_id=actor_id)
            elif action == "restore":
                log_id = moderation.restore(conn, story_key, at=at, reason=body.reason, actor_user_id=actor_id)
            elif action == "dismiss":
                log_id = moderation.dismiss(conn, story_key, at=at, reason=body.reason, requested_by=body.requested_by,
                                            reference=body.reference, actor_user_id=actor_id)
            else:
                log_id = moderation.approve(conn, story_key, at=at, reason=body.reason, actor_user_id=actor_id)
            now_story = moderation.current(conn, story_key)
    except moderation.ModerationError as exc:
        code = 404 if str(exc) == "no_such_story" else 409
        raise ApiError(code, "not_found" if code == 404 else "conflict", str(exc)) from exc
    return Done(story_key=story_key, action=action, log_id=log_id, status=now_story.status if now_story else "unknown")


@router.post("/news/stories/{story_key}/request", response_model=Done)
def post_request(story_key: StoryKey, body: ActIn, actor: Admin) -> Done:
    return _do(story_key, "request", body, actor.user_id)


@router.post("/news/stories/{story_key}/withdraw", response_model=Done)
def post_withdraw(story_key: StoryKey, body: ActIn, actor: Admin) -> Done:
    return _do(story_key, "withdraw", body, actor.user_id)


@router.post("/news/stories/{story_key}/restore", response_model=Done)
def post_restore(story_key: StoryKey, body: ActIn, actor: Admin) -> Done:
    return _do(story_key, "restore", body, actor.user_id)


@router.post("/news/stories/{story_key}/dismiss", response_model=Done)
def post_dismiss(story_key: StoryKey, body: ActIn, actor: Admin) -> Done:
    return _do(story_key, "dismiss", body, actor.user_id)


@router.post("/news/stories/{story_key}/approve", response_model=Done)
def post_approve(story_key: StoryKey, body: ActIn, actor: Admin) -> Done:
    return _do(story_key, "approve", body, actor.user_id)
