"""What readers think of PrediGol (plan UX, B6 and section 40): the monthly survey, «¿Te sirvió?» and Novedades read.

    survey      «¿Qué tan útil te resultó PrediGol este mes?», 1 to 5, and optionally «¿Qué faltó?» (1-3) or «¿Qué fue lo
                más útil?» (4-5). At most once every 30 days, counted from the reader's last answer or skip: closing it
                (``csat_skipped``) keeps it away for those 30 days too; and never in the account's first week («este
                mes» asks about a PrediGol the reader has used). When to offer it is the page's - after a useful moment
                (a match's analysis opened, a result seen), never at sign-in and never after an error -; whether it is
                owed, and refusing an answer that is not, is here.
    helpful     «¿Te sirvió?» yes or no at the end of a reading, a narrative, an explanation or an «Explícame» answer: one
                answer per reader and thing read, the last one counts.
    updates     Novedades: the page says what changed thanks to the readers' comments; which of its entries the reader
                has seen is a mark in ``customer.preferences.hints_seen`` (``updates:<id>``, only the newest kept).

The opinion improves the product and never enters the models: nothing of PrediGol Intelligence reads it. A comment does
not ask for personal data, and an address or a long number (a phone, a document) is removed before it is stored. Never a
prize for answering, never a nag: everything can be skipped. ``FBI_FEEDBACK`` (on while the line is absent) turns the
survey and the votes off without a deploy; the answers stay. A survey of 2 or less marks the reader EN RIESGO for the
customer's life cycle (B11) so that support looks after them - ``at_risk`` is that signal.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.core.env import environment
from fbi.customer.db import CustomerError, write_connection

log = structlog.get_logger("customer.feedback")

SWITCH: Final = "FBI_FEEDBACK"
SURVEY_EVERY: Final = timedelta(days=30)
FIRST_AFTER: Final = timedelta(days=7)
"""The first survey waits for the account's first week: «¿Qué tan útil te resultó PrediGol este mes?» is not a question
for someone who arrived ten minutes ago."""
COMMENT_MAX: Final = 1000
SUBJECTS: Final = ("reading", "narrative", "explanation", "explain")
TRIGGERS: Final = ("analysis_opened", "result_seen")
"""The useful moments after which the page may offer the survey (plan section 40)."""
VOTES_PER_DAY: Final = 300
"""More «¿Te sirvió?» answers than any reading of a day needs: past this a reader's votes are refused until tomorrow."""
RETENTION: Final = timedelta(days=730)
"""24 months (plan, section 40 and the customer data's table)."""
AT_RISK_SCORE: Final = 2
AT_RISK_WINDOW: Final = timedelta(days=30)
UPDATES_MARK: Final = "updates:"
UPDATE_ID: Final = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]{1,40}")
"""An entry of Novedades: its date and a slug (``2026-10-27-mis-picks``)."""
ROUTE_MAX: Final = 80
_ON: Final = frozenset({"1", "on", "true", "yes"})

Subject = Literal["reading", "narrative", "explanation", "explain"]
Trigger = Literal["analysis_opened", "result_seen"]

# what a comment must not keep: an e-mail address, a web address, a run of 7 or more digits (a phone, a document) -
# spaces, dots and dashes between the digits included
_EMAIL: Final = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_URL: Final = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_DIGITS: Final = re.compile(r"\+?\d(?:[\s.\-]?\d){6,}")
REMOVED: Final = "[dato quitado]"


def enabled() -> bool:
    """``FBI_FEEDBACK``: on while the line is absent or empty (the owner approved the plan; =0 turns the survey and the
    votes off without a deploy), off for a value it cannot read."""
    raw = environment().get(SWITCH)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in _ON


def scrub(comment: str | None) -> str | None:
    """The comment as stored: trimmed, at most COMMENT_MAX characters, with an address or a long number replaced. None for
    nothing left to keep."""
    if comment is None:
        return None
    text = " ".join(comment.split())
    text = _EMAIL.sub(REMOVED, text)
    text = _URL.sub(REMOVED, text)
    text = _DIGITS.sub(REMOVED, text)
    text = text.strip()[:COMMENT_MAX].strip()
    return text or None


def clean_context(context: Mapping[str, Any] | None) -> dict[str, str]:
    """Where it was asked, and nothing else: the trigger (one of TRIGGERS) and the page's path (no query, no fragment,
    at most ROUTE_MAX characters). Anything else is dropped."""
    out: dict[str, str] = {}
    if not context:
        return out
    trigger = context.get("trigger")
    if isinstance(trigger, str) and trigger in TRIGGERS:
        out["trigger"] = trigger
    route = context.get("route")
    if isinstance(route, str):
        path = route.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/") and re.fullmatch(r"[A-Za-z0-9/_\-.]+", path):
            out["route"] = path[:ROUTE_MAX]
    return out


# ── the survey ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SurveyState:
    enabled: bool
    due: bool
    last_at: datetime | None
    """The reader's last answer or skip."""
    next_at: datetime | None
    """From when it is owed (None while it is owed, or off): the end of the account's first week, or 30 days after the
    last answer or skip."""


LAST_SURVEY_SQL = """
SELECT created_at FROM customer.feedback
 WHERE user_id = %s AND kind IN ('csat', 'csat_skipped')
 ORDER BY created_at DESC LIMIT 1
"""
ACCOUNT_SINCE_SQL = "SELECT created_at FROM auth.users WHERE id = %s"


def survey_state(conn: psycopg.Connection[Any], user_id: int, *, at: datetime) -> SurveyState:
    """Whether the survey is owed: on, the account past its first week, and no answer or skip in the last 30 days."""
    row = conn.execute(LAST_SURVEY_SQL, (user_id,)).fetchone()
    last = row[0] if row else None
    if not enabled():
        return SurveyState(enabled=False, due=False, last_at=last, next_at=None)
    since = conn.execute(ACCOUNT_SINCE_SQL, (user_id,)).fetchone()
    owed_from = [since[0] + FIRST_AFTER] if since and since[0] is not None else []
    if last is not None:
        owed_from.append(last + SURVEY_EVERY)
    next_at = max(owed_from, default=None)
    if next_at is None or next_at <= at:
        return SurveyState(enabled=True, due=True, last_at=last, next_at=None)
    return SurveyState(enabled=True, due=False, last_at=last, next_at=next_at)


def _lock(conn: psycopg.Connection[Any], user_id: int) -> None:
    """One survey write at a time per reader: two tabs answering at once write one answer."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('customer.feedback'), %s)", (user_id % 2**31,))


def _owed(conn: psycopg.Connection[Any], user_id: int, at: datetime) -> bool:
    state = survey_state(conn, user_id, at=at)
    return state.due


def answer_survey(user_id: int, score: int, comment: str | None, context: Mapping[str, Any] | None, *,
                  at: datetime) -> int:
    """The survey answered: one row, or 409 ``survey_not_due`` when it is not owed - answered or skipped in the last 30
    days, or the account in its first week - (or 404 ``feedback_off``). 422 ``invalid_score`` outside 1-5."""
    if not enabled():
        raise CustomerError(404, "feedback_off", "the survey is off")
    if not 1 <= score <= 5:
        raise CustomerError(422, "invalid_score", "the score goes from 1 to 5")
    with write_connection() as conn:
        _lock(conn, user_id)
        if not _owed(conn, user_id, at):
            raise CustomerError(409, "survey_not_due", "the survey is not owed: answered or closed in the last 30 days, "
                                "or the account's first week")
        row = conn.execute(
            "INSERT INTO customer.feedback (user_id, kind, score, comment, context, created_at, updated_at) "
            "VALUES (%s, 'csat', %s, %s, %s, %s, %s) RETURNING id",
            (user_id, score, scrub(comment), Jsonb(clean_context(context)), at, at)).fetchone()
    assert row is not None
    log.info("feedback.survey_answered", user_id=user_id, score=score)
    return int(row[0])


def skip_survey(user_id: int, context: Mapping[str, Any] | None, *, at: datetime) -> bool:
    """The survey closed without an answer: it does not come back for 30 days. Idempotent - a skip when it is not owed
    writes nothing (False)."""
    if not enabled():
        return False
    with write_connection() as conn:
        _lock(conn, user_id)
        if not _owed(conn, user_id, at):
            return False
        conn.execute("INSERT INTO customer.feedback (user_id, kind, context, created_at, updated_at) "
                     "VALUES (%s, 'csat_skipped', %s, %s, %s)", (user_id, Jsonb(clean_context(context)), at, at))
    return True


# ── «¿Te sirvió?» ─────────────────────────────────────────────────────────────────────

VOTE_SQL = """
SELECT helpful FROM customer.feedback WHERE user_id = %s AND kind = 'helpful' AND subject = %s AND subject_id = %s
"""


def my_vote(conn: psycopg.Connection[Any], user_id: int, subject: str, subject_id: int) -> bool | None:
    row = conn.execute(VOTE_SQL, (user_id, subject, subject_id)).fetchone()
    return None if row is None else bool(row[0])


def vote(user_id: int, subject: str, subject_id: int, helpful: bool, context: Mapping[str, Any] | None, *,
         at: datetime) -> bool:
    """«¿Te sirvió?» answered: one row per reader and thing read, the last answer counts. 422 ``unknown_subject``,
    429 ``too_many_votes`` past VOTES_PER_DAY in the reader's last 24 hours, 404 ``feedback_off``."""
    if not enabled():
        raise CustomerError(404, "feedback_off", "the votes are off")
    if subject not in SUBJECTS:
        raise CustomerError(422, "unknown_subject", f"«¿Te sirvió?» is asked of {', '.join(SUBJECTS)}")
    if subject_id < 1:
        raise CustomerError(422, "unknown_subject", "the thing read has no id")
    with write_connection() as conn:
        _lock(conn, user_id)
        recent = conn.execute("SELECT count(*) FROM customer.feedback WHERE user_id = %s AND kind = 'helpful' "
                              "AND updated_at > %s", (user_id, at - timedelta(days=1))).fetchone()
        if recent is not None and int(recent[0]) >= VOTES_PER_DAY:
            raise CustomerError(429, "too_many_votes", "too many answers today")
        conn.execute(
            "INSERT INTO customer.feedback (user_id, kind, subject, subject_id, helpful, context, created_at, updated_at) "
            "VALUES (%s, 'helpful', %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, subject, subject_id) WHERE kind = 'helpful' "
            "DO UPDATE SET helpful = EXCLUDED.helpful, context = EXCLUDED.context, updated_at = EXCLUDED.updated_at",
            (user_id, subject, subject_id, helpful, Jsonb(clean_context(context)), at, at))
    return helpful


# ── Novedades ─────────────────────────────────────────────────────────────────────────

def updates_seen(conn: psycopg.Connection[Any], user_id: int) -> str | None:
    """The newest entry of Novedades the reader has seen (None: none yet)."""
    row = conn.execute("SELECT hints_seen FROM customer.preferences WHERE user_id = %s", (user_id,)).fetchone()
    marks = [str(h) for h in (row[0] if row and row[0] else []) if str(h).startswith(UPDATES_MARK)]
    return marks[-1][len(UPDATES_MARK):] if marks else None


def mark_updates_seen(user_id: int, update_id: str, *, at: datetime) -> str:
    """The reader opened Novedades with ``update_id`` as its newest entry: the one mark ``updates:<id>`` replaces the
    previous one (one statement, idempotent). 422 ``unknown_update`` for an id that is not one."""
    if not UPDATE_ID.fullmatch(update_id):
        raise CustomerError(422, "unknown_update", "not an entry of Novedades")
    mark = UPDATES_MARK + update_id
    with write_connection() as conn:
        conn.execute(
            "INSERT INTO customer.preferences (user_id, hints_seen, updated_at) VALUES (%s, ARRAY[%s]::text[], %s) "
            "ON CONFLICT (user_id) DO UPDATE SET hints_seen = array_append(ARRAY(SELECT h FROM "
            "unnest(customer.preferences.hints_seen) AS h WHERE h NOT LIKE 'updates:%%'), %s), "
            "updated_at = EXCLUDED.updated_at",
            (user_id, mark, at, mark))
    return update_id


# ── the owner's view (/admin/product) ─────────────────────────────────────────────────

@dataclass
class SurveyFigures:
    n: int = 0
    mean: float | None = None
    scores: dict[int, int] = field(default_factory=lambda: dict.fromkeys(range(1, 6), 0))
    low: int = 0
    """Answers of AT_RISK_SCORE or less."""
    skipped: int = 0


@dataclass
class VoteFigures:
    subject: str
    yes: int
    no: int


@dataclass
class Comment:
    at: datetime
    score: int
    comment: str
    trigger: str | None


@dataclass
class Overview:
    enabled: bool
    since: datetime
    survey: SurveyFigures
    votes: list[VoteFigures]
    comments: list[Comment]
    at_risk: int
    """Readers whose last survey in the last 30 days was AT_RISK_SCORE or less (B11's EN RIESGO)."""


def overview(conn: psycopg.Connection[Any], *, at: datetime, days: int = 90, comments: int = 50) -> Overview:
    """The last ``days``: the survey's answers with their n and distribution, the skips, «¿Te sirvió?» per kind of thing
    read, the newest comments (with their score and date, never who wrote them: the reader's card is B10's) and the
    readers at risk by the survey."""
    since = at - timedelta(days=days)
    figures = SurveyFigures()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT kind, score, count(*) AS n FROM customer.feedback "
                    "WHERE kind IN ('csat', 'csat_skipped') AND created_at >= %s GROUP BY kind, score", (since,))
        for r in cur.fetchall():
            if r["kind"] == "csat_skipped":
                figures.skipped += int(r["n"])
            else:
                figures.scores[int(r["score"])] = int(r["n"])
        figures.n = sum(figures.scores.values())
        if figures.n:
            figures.mean = round(sum(s * c for s, c in figures.scores.items()) / figures.n, 2)
        figures.low = sum(c for s, c in figures.scores.items() if s <= AT_RISK_SCORE)
        cur.execute("SELECT subject, count(*) FILTER (WHERE helpful) AS yes, count(*) FILTER (WHERE NOT helpful) AS no "
                    "FROM customer.feedback WHERE kind = 'helpful' AND updated_at >= %s GROUP BY subject", (since,))
        found = {r["subject"]: VoteFigures(r["subject"], int(r["yes"]), int(r["no"])) for r in cur.fetchall()}
        votes = [found.get(s, VoteFigures(s, 0, 0)) for s in SUBJECTS]
        cur.execute("SELECT created_at, score, comment, context->>'trigger' AS trigger FROM customer.feedback "
                    "WHERE kind = 'csat' AND comment IS NOT NULL AND created_at >= %s "
                    "ORDER BY created_at DESC, id DESC LIMIT %s", (since, comments))
        notes = [Comment(r["created_at"], int(r["score"]), r["comment"], r["trigger"]) for r in cur.fetchall()]
    return Overview(enabled=enabled(), since=since, survey=figures, votes=votes, comments=notes,
                    at_risk=len(at_risk(conn, at=at)))


AT_RISK_SQL = """
SELECT user_id FROM (
    SELECT DISTINCT ON (user_id) user_id, score FROM customer.feedback
     WHERE kind = 'csat' AND created_at >= %s ORDER BY user_id, created_at DESC, id DESC
) last WHERE score <= %s ORDER BY user_id
"""


def at_risk(conn: psycopg.Connection[Any], *, at: datetime) -> list[int]:
    """The readers whose last survey of the last 30 days was 2 or less: B11 marks them EN RIESGO (never a message: the
    signal orders support's attention)."""
    return [int(r[0]) for r in conn.execute(AT_RISK_SQL, (at - AT_RISK_WINDOW, AT_RISK_SCORE)).fetchall()]


# ── the reader's own copy ─────────────────────────────────────────────────────────────

def export_rows(conn: psycopg.Connection[Any], user_id: int) -> list[dict[str, Any]]:
    """The reader's answers in the copy of their data (A4): each survey, closed survey and «¿Te sirvió?» with where it
    was asked, newest first. Novedades read travels with the other hints (``welcome.hints_seen``)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return list(cur.execute(
            "SELECT kind, score, comment, subject, subject_id, helpful, context, created_at, updated_at "
            "FROM customer.feedback WHERE user_id = %s ORDER BY created_at DESC, id DESC", (user_id,)).fetchall())


# ── retention ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PurgeReport:
    mode: Literal["off", "dry", "on"]
    rows: int


def purge(conn: psycopg.Connection[Any], *, at: datetime, mode: Literal["off", "dry", "on"]) -> PurgeReport:
    """Answers older than 24 months: counted (``dry``) or deleted (``on``) - the same switch as the product analytics'
    retention (FBI_EVENTS_PURGE, the owner's decision). The caller commits."""
    before = at - RETENTION
    if mode == "off":
        return PurgeReport("off", 0)
    if mode == "dry":
        row = conn.execute("SELECT count(*) FROM customer.feedback WHERE updated_at < %s", (before,)).fetchone()
        return PurgeReport("dry", int(row[0]) if row else 0)
    n = conn.execute("DELETE FROM customer.feedback WHERE updated_at < %s", (before,)).rowcount
    if n:
        log.info("feedback.purged", rows=n)
    return PurgeReport("on", max(n, 0))
