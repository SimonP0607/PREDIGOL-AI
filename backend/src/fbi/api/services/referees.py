"""Referees as people in the Admin Console (plan F3): what the queue of doubts and a referee's page read, and the decisions a person
takes (``fbi.people.referees``).

Reads go through the API's read-only connection. A decision runs on a connection of its own - the same shape as the owner's other
decisions (``fbi.api.services.evolution``) - because it writes, waits (up to 20 s) for the hourly pass if that one is writing, and
commits only when the whole action went through. The refusals of the store become the API's: 404 for a referee or an event that does
not exist, 422 for an action that makes no sense, 409 for one that is not allowed now (two men refereeing at the same time, a merge
already undone) or while the pass is writing."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import errors

from fbi.api.contracts.referees import (
    ActionResult,
    MergeIn,
    PairIn,
    RefereeAlias,
    RefereeCandidate,
    RefereeCounts,
    RefereeDetail,
    RefereeEvent,
    RefereeList,
    RefereeMatch,
    RefereePair,
    RefereeQueue,
    RefereeSide,
    RefereeSummary,
    RenameIn,
    SplitIn,
)
from fbi.api.envelope import Envelope, ok
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn
from fbi.core.config import settings
from fbi.people import referees as store
from fbi.people.countries import UNKNOWN_SCOPE, country_name

REFUSALS = {"not_found": 404, "invalid": 422, "collision": 409, "conflict": 409}
"""The status of each refusal the store gives (``store.ActionError.code``)."""
WRITE_TIMEOUT_MS = 30_000
"""A decision may wait 20 s for the pass (``store.MANUAL_LOCK_WAIT``) and then does its work: a bound above both."""


@contextmanager
def write() -> Iterator[psycopg.Connection[Any]]:
    """The connection a decision runs on: commits on a clean exit, rolls back on an exception."""
    conn = psycopg.connect(settings.database.psycopg_url, connect_timeout=3,
                           options=f"-c statement_timeout={WRITE_TIMEOUT_MS} -c TimeZone=UTC")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _scope_name(scope: str | None) -> str | None:
    if not scope or scope == UNKNOWN_SCOPE:
        return None
    return country_name(scope) or scope.title()


def _summary(row: dict[str, Any]) -> RefereeSummary:
    return RefereeSummary(
        id=int(row["id"]), name=str(row["name"]), country=_scope_name(row["country_key"]), status=row["status"],
        merged_into=None if row["merged_into"] is None else int(row["merged_into"]), name_locked=bool(row["name_locked"]),
        matches=int(row["matches"] or 0), first_match=row["first_match"], last_match=row["last_match"])


def _side(row: dict[str, Any], which: str) -> RefereeSide:
    return RefereeSide(id=int(row[f"referee_{which}"]), name=str(row[f"name_{which}"]), country=_scope_name(row[f"country_{which}"]),
                       matches=int(row[f"matches_{which}"] or 0))


def _pair(row: dict[str, Any]) -> RefereePair:
    return RefereePair(
        id=int(row["id"]), a=_side(row, "a"), b=_side(row, "b"), reason=str(row["reason"]), score=float(row["score"]),
        impact=int(row["impact"]), evidence=dict(row["evidence"] or {}), status=row["status"], decided_by=row["decided_by"],
        decided_at=row["decided_at"])


def _candidate(row: dict[str, Any]) -> RefereeCandidate:
    return RefereeCandidate(
        id=int(row["id"]),
        other=RefereeSide(id=int(row["other_id"]), name=str(row["other_name"]), country=_scope_name(row["other_country"]),
                          matches=int(row["other_matches"] or 0)),
        reason=str(row["reason"]), score=float(row["score"]), impact=int(row["impact"]), evidence=dict(row["evidence"] or {}),
        status=row["status"], decided_by=row["decided_by"], decided_at=row["decided_at"])


def _event(row: dict[str, Any]) -> RefereeEvent:
    return RefereeEvent(
        id=int(row["id"]), at=row["at"], actor=str(row["actor"]), action=str(row["action"]),
        referee_id=None if row["referee_id"] is None else int(row["referee_id"]),
        other_id=None if row["other_id"] is None else int(row["other_id"]), alias_ids=[int(a) for a in row["alias_ids"] or []],
        undone_by=None if row["undone_by"] is None else int(row["undone_by"]), detail=dict(row["detail"] or {}))


def _alias(row: dict[str, Any]) -> RefereeAlias:
    return RefereeAlias(id=int(row["id"]), display=str(row["display"]), name_key=str(row["name_key"]), country=_scope_name(row["scope"]),
                        basis=str(row["basis"]), placed_by=str(row["placed_by"]), matches=int(row["matches"]), first=row["first"],
                        last=row["last"])


def _counts(conn: Conn) -> RefereeCounts:
    c = store.counts(conn)
    return RefereeCounts(
        referees_active=c["referees_active"], referees_merged=c["referees_merged"], aliases=c["aliases"],
        fixtures_with_referee=c["fixtures_with_referee"], candidates_open=c["candidates_open"],
        candidates_rejected=c["candidates_rejected"], candidates_merged=c["candidates_merged"],
        matches_with_a_doubt=c["matches_with_a_doubt"], settled_share=c["settled_share"], problems=store.broken_invariants(c))


# ── reads ────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def referees(conn: Conn, *, q: str | None, limit: int, offset: int) -> Envelope[RefereeList]:
    """The people, the busiest first, or those whose name (under any spelling) holds the words of ``q``; with the figures that say
    whether the identity is healthy."""
    counts = _counts(conn)
    text = (q or "").strip()
    rows = store.find(conn, text, limit=limit) if text else store.top(conn, limit=limit, offset=offset)
    total = len(rows) if text else counts.referees_active
    return ok(RefereeList(items=[_summary(r) for r in rows], total=total, queue_open=counts.candidates_open, counts=counts),
              count=len(rows), total=total, limit=limit, offset=0 if text else offset)


def queue(conn: Conn, *, status: str, reason: str | None, limit: int, offset: int) -> Envelope[RefereeQueue]:
    """The pairs of referees the rules doubt (``open``) or a person already decided (``rejected``, ``merged``), the ones that touch
    most matches first."""
    rows = store.queue(conn, status=status, reason=reason, limit=limit, offset=offset)
    total = store.queue_size(conn, status=status, reason=reason)
    return ok(RefereeQueue(items=[_pair(r) for r in rows], total=total, status=status, reason=reason),  # type: ignore[arg-type]
              count=len(rows), total=total, limit=limit, offset=offset)


def referee(conn: Conn, referee_id: int) -> Envelope[RefereeDetail]:
    """One person: his spellings, his newest matches, the doubts about him and what was changed."""
    row = store.referee_row(conn, referee_id)
    if row is None:
        raise ApiError(404, "not_found", f"referee {referee_id} does not exist")
    return ok(RefereeDetail(
        referee=_summary(row), aliases=[_alias(a) for a in store.aliases_of(conn, referee_id)],
        recent_matches=[RefereeMatch(**m) for m in store.recent_matches(conn, referee_id, limit=20)],
        candidates=[_candidate(c) for c in store.candidates_of(conn, referee_id)],
        events=[_event(e) for e in store.events_of(conn, referee_id, limit=30)]))


# ── decisions ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _run[T](action: Callable[[psycopg.Connection[Any]], T]) -> T:
    """Run a decision on its own connection; what the store refuses, the API refuses."""
    try:
        with write() as conn:
            return action(conn)
    except store.ActionError as exc:
        raise ApiError(REFUSALS.get(exc.code, 409), exc.code, exc.message) from exc
    except (errors.LockNotAvailable, errors.QueryCanceled) as exc:
        raise ApiError(409, "busy", "The pass that places the referees is writing; try again in a minute.") from exc


def _result(conn: psycopg.Connection[Any], action: str, event_id: int | None, referee_id: int, other_id: int | None) -> ActionResult:
    row = store.referee_row(conn, referee_id)
    assert row is not None, f"referee {referee_id} vanished inside its own action"
    return ActionResult(action=action, event_id=event_id, referee_id=referee_id, other_id=other_id,  # type: ignore[arg-type]
                        referee=_summary(row))


def merge(referee_id: int, body: MergeIn, *, actor: str) -> Envelope[ActionResult]:
    """``body.merge_id`` is the same person as ``referee_id``: his spellings move, he is marked merged. Reversible (``undo``)."""
    def act(conn: psycopg.Connection[Any]) -> ActionResult:
        event = store.merge(conn, referee_id, body.merge_id, actor=actor, note=body.note, force=body.force)
        return _result(conn, "merge", event, referee_id, body.merge_id)
    return ok(_run(act))


def undo(event_id: int, *, actor: str) -> Envelope[ActionResult]:
    """Take a merge back: the spellings it moved return to the referee it merged, who is active again."""
    def act(conn: psycopg.Connection[Any]) -> ActionResult:
        undone = store.undo(conn, event_id, actor=actor)
        row = conn.execute("SELECT referee_id, other_id FROM core.referee_events WHERE id = %s", (undone,)).fetchone()
        assert row is not None
        return _result(conn, "undo", undone, int(row[0]), int(row[1]))
    return ok(_run(act))


def split(referee_id: int, body: SplitIn, *, actor: str) -> Envelope[ActionResult]:
    """Some of his spellings are another man: they move to a NEW referee, and the pair is never suggested again."""
    def act(conn: psycopg.Connection[Any]) -> ActionResult:
        created = store.split(conn, referee_id, body.alias_ids, actor=actor, name=body.name, note=body.note)
        event = conn.execute("SELECT max(id) FROM core.referee_events WHERE action = 'split' AND other_id = %s", (created,)).fetchone()
        return _result(conn, "split", None if event is None else int(event[0]), created, referee_id)
    return ok(_run(act))


def reject(referee_id: int, body: PairIn, *, actor: str) -> Envelope[ActionResult]:
    """The two are different people: the pair leaves the queue and is not suggested again."""
    def act(conn: psycopg.Connection[Any]) -> ActionResult:
        event = store.reject(conn, referee_id, body.other_id, actor=actor, note=body.note)
        return _result(conn, "reject", event, referee_id, body.other_id)
    return ok(_run(act))


def reopen(referee_id: int, body: PairIn, *, actor: str) -> Envelope[ActionResult]:
    """Take a rejection back: the pair is a question again."""
    def act(conn: psycopg.Connection[Any]) -> ActionResult:
        event = store.reopen(conn, referee_id, body.other_id, actor=actor)
        return _result(conn, "reopen", event, referee_id, body.other_id)
    return ok(_run(act))


def rename(referee_id: int, body: RenameIn, *, actor: str) -> Envelope[ActionResult]:
    """Set the name he is shown with (the rules keep it from then on); null gives the naming back to the rules."""
    def act(conn: psycopg.Connection[Any]) -> ActionResult:
        event = store.rename(conn, referee_id, body.name, actor=actor)
        return _result(conn, "rename", event, referee_id, None)
    return ok(_run(act))
