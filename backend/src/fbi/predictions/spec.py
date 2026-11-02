"""The forecast spec production uses, and the only way it changes: an explicit promotion (plan F0, defect 2).

The real-time forecast refits each goal model with a time decay ``xi`` and a shrinkage ``penalty`` that a backtest chose
on its validation season, over a training window, and trains the feature models on the competitions of that backtest.
Until 22 Oct 2026 it read all of that from "the latest completed backtest session". The weekly ``research_v2`` job
stores a completed session whenever the model code or the dataset version changes, or the last one is four weeks old, so
production's parameters could change in any week with no decision, no record of the change and no way back.

``analytics.promoted_forecast_spec`` (migration 0079) is now the only thing the forecast reads. It is an append-only
history of promotions: the newest row is the spec in force. A row carries

* the backtest session the spec came from (the foreign key refuses to delete a session that was ever promoted),
* a COPY of the spec (editing a session afterwards cannot move production),
* who promoted it ('owner', or 'system' for the row migration 0079 seeded from the session production already used),
* the reason, the previous row, and the evidence read at the time.

Rolling back is promoting an earlier session again. Nothing is ever updated or deleted, and nothing here promotes by
itself: ``research_v2`` keeps writing sessions, and a session is only research until a person promotes it with
``python -m scripts.promote_forecast_spec``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.backtesting.walkforward import GoalSpec, WalkForwardConfig
from fbi.core.clock import now

SPEC_VERSION = "spec-v1"
GOAL_KINDS = ("poisson", "dixon_coles")
"""The goal models whose hyper-parameters a spec holds. The Elo ordered logit has none to choose."""
DEFAULT_HISTORY_DAYS = 730
MIN_REASON = 10
"""A promotion without a reason is not a decision anyone can look back on."""
PROMOTERS = ("owner", "system")


@dataclass(frozen=True, slots=True)
class Spec:
    competition_ids: tuple[int, ...]
    cfg: WalkForwardConfig
    goal: dict[str, GoalSpec]
    session_id: int


@dataclass(frozen=True, slots=True)
class Promotion:
    """One row of the history: a spec put in force."""

    id: int
    session_id: int
    promoted_at: datetime
    promoted_by: str
    reason: str
    snapshot: dict[str, Any]
    previous_id: int | None
    evidence: dict[str, Any]

    @property
    def spec(self) -> Spec:
        return parse(self.snapshot, session_id=self.session_id)


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """What ``promote`` did: the row now in force, whether it is a new one, and what changed against the one before."""

    promotion: Promotion
    changed: bool
    changes: list[str]


def snapshot(competition_ids: list[int] | tuple[int, ...], config: Mapping[str, Any],
             selection: Mapping[str, Any]) -> dict[str, Any]:
    """The spec a backtest session chose, as stored: the competitions it ran on, its training window and, for each goal
    model, the ``xi`` and ``penalty`` it chose on the validation season. Migration 0079 builds the same document in
    SQL for the seed (a test holds the two together)."""
    goal: dict[str, dict[str, float]] = {}
    for kind, sel in dict(selection).items():
        if kind in GOAL_KINDS:
            goal[kind] = {"xi": float(sel["chosen"]["xi"]), "penalty": float(sel["chosen"]["penalty"])}
    return {"version": SPEC_VERSION, "competition_ids": [int(x) for x in competition_ids],
            "history_days": int(config.get("history_days", DEFAULT_HISTORY_DAYS)), "goal": goal}


def parse(doc: Mapping[str, Any], *, session_id: int) -> Spec:
    """A stored spec, checked: a spec that cannot be used must stop the forecast loudly, not fit something else."""
    if doc.get("version") != SPEC_VERSION:
        raise ValueError(f"unknown forecast spec version {doc.get('version')!r} (this code reads {SPEC_VERSION})")
    competitions = tuple(int(x) for x in doc["competition_ids"])
    history = int(doc["history_days"])
    if not competitions:
        raise ValueError("a forecast spec names at least one competition")
    if history < 1:
        raise ValueError(f"the training window must be at least one day, not {history}")
    goal: dict[str, GoalSpec] = {}
    for kind, hyper in dict(doc["goal"]).items():
        if kind not in GOAL_KINDS:
            raise ValueError(f"{kind!r} is not a goal model ({', '.join(GOAL_KINDS)})")
        xi, penalty = float(hyper["xi"]), float(hyper["penalty"])
        if not (math.isfinite(xi) and math.isfinite(penalty)) or xi < 0 or penalty < 0:
            raise ValueError(f"{kind}: xi {xi} and penalty {penalty} must be finite and not negative")
        goal[kind] = GoalSpec(kind, xi, penalty)
    return Spec(competitions, WalkForwardConfig(competition_ids=competitions, history_days=history), goal, session_id)


def describe(old: Spec | None, new: Spec) -> list[str]:
    """What putting ``new`` in force changes against ``old``, one line each (empty: the same forecast)."""
    if old is None:
        goals = ", ".join(f"{k} xi={g.xi:g} penalty={g.penalty:g}" for k, g in sorted(new.goal.items()))
        return [f"first spec: {goals or 'no goal model'}; window {new.cfg.history_days} days; "
                f"{len(new.competition_ids)} competitions"]
    out: list[str] = []
    for kind in sorted(set(old.goal) | set(new.goal)):
        a, b = old.goal.get(kind), new.goal.get(kind)
        if a is None or b is None:
            out.append(f"{kind}: {'added' if a is None else 'removed'}")
        elif (a.xi, a.penalty) != (b.xi, b.penalty):
            out.append(f"{kind}: xi {a.xi:g} -> {b.xi:g}, penalty {a.penalty:g} -> {b.penalty:g}")
    if old.cfg.history_days != new.cfg.history_days:
        out.append(f"training window {old.cfg.history_days} -> {new.cfg.history_days} days")
    added = sorted(set(new.competition_ids) - set(old.competition_ids))
    removed = sorted(set(old.competition_ids) - set(new.competition_ids))
    if added:
        out.append(f"competitions added to the feature models: {added}")
    if removed:
        out.append(f"competitions removed from the feature models: {removed}")
    return out


_COLUMNS = "id, session_id, promoted_at, promoted_by, reason, spec, previous_id, evidence"


def _promotion(row: Mapping[str, Any]) -> Promotion:
    return Promotion(int(row["id"]), int(row["session_id"]), row["promoted_at"], str(row["promoted_by"]),
                     str(row["reason"]), dict(row["spec"]), None if row["previous_id"] is None else int(row["previous_id"]),
                     dict(row["evidence"]))


def promoted(conn: psycopg.Connection[Any]) -> Promotion | None:
    """The promotion in force: the newest row of the history."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM analytics.promoted_forecast_spec ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return None if row is None else _promotion(row)


def current_spec(conn: psycopg.Connection[Any]) -> Spec | None:
    """The spec the forecast uses: the one in force by promotion, never "the newest backtest". None when nothing was
    ever promoted (the forecast then says so and writes nothing)."""
    p = promoted(conn)
    return None if p is None else p.spec


def history(conn: psycopg.Connection[Any], *, limit: int = 20) -> list[Promotion]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM analytics.promoted_forecast_spec ORDER BY id DESC LIMIT %s", (limit,))
        return [_promotion(r) for r in cur.fetchall()]


@dataclass(frozen=True, slots=True)
class Plan:
    """What promoting a session would do, worked out without writing anything."""

    session_id: int
    snapshot: dict[str, Any]
    spec: Spec
    current: Promotion | None
    changes: list[str]
    evidence: dict[str, Any]

    @property
    def already_in_force(self) -> bool:
        return self.current is not None and self.current.session_id == self.session_id \
            and self.current.snapshot == self.snapshot


def check_reason(by: str, reason: str) -> str:
    reason = reason.strip()
    if by not in PROMOTERS:
        raise ValueError(f"promoted_by must be one of {PROMOTERS}, not {by!r}")
    if len(reason) < MIN_REASON:
        raise ValueError(f"a promotion needs a reason of at least {MIN_REASON} characters")
    return reason


def plan(conn: psycopg.Connection[Any], session_id: int) -> Plan:
    """What putting the spec of a backtest session in force would change. Refuses a session that is not completed, is
    not a walk-forward, or chose no goal model. Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, name, protocol, status, competition_ids, config, selection, dataset_hash, code_version, "
                    "n_targets, validation_season, test_season, finished_at FROM analytics.backtest_sessions "
                    "WHERE id = %s", (session_id,))
        session = cur.fetchone()
    if session is None:
        raise LookupError(f"no backtest session {session_id}")
    if session["status"] != "completed" or session["protocol"] != "walk_forward":
        raise PermissionError(f"session {session_id} is {session['protocol']}/{session['status']}: only a completed "
                              "walk-forward session can be promoted")
    doc = snapshot(session["competition_ids"], session["config"], session["selection"])
    if not doc["goal"]:
        raise PermissionError(f"session {session_id} chose no hyper-parameters for a goal model: nothing to promote")
    new = parse(doc, session_id=session_id)
    current = promoted(conn)
    changes = describe(None if current is None else current.spec, new)
    evidence = {"session": session["name"], "finished_at": session["finished_at"].isoformat(),
                "dataset_hash": session["dataset_hash"], "code_version": session["code_version"],
                "n_targets": session["n_targets"], "validation_season": session["validation_season"],
                "test_season": session["test_season"], "changes": changes or ["same forecast, another session"]}
    return Plan(session_id, doc, new, current, changes, evidence)


def promote(conn: psycopg.Connection[Any], session_id: int, *, by: str, reason: str, who: str | None = None,
            at: datetime | None = None) -> PromotionResult:
    """Put the spec of a completed walk-forward session in force. The caller commits. ``who`` is the person's name,
    kept in the evidence. Promoting what is already in force changes nothing and writes nothing."""
    reason = check_reason(by, reason)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('analytics.promoted_forecast_spec'))")
    p = plan(conn, session_id)
    if p.already_in_force:
        assert p.current is not None
        return PromotionResult(p.current, False, [])
    evidence = p.evidence | ({} if who is None else {"who": who})
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"INSERT INTO analytics.promoted_forecast_spec (session_id, promoted_at, promoted_by, reason, spec, "
                    f"previous_id, evidence) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING {_COLUMNS}",
                    (session_id, at or now(), by, reason, Jsonb(p.snapshot),
                     None if p.current is None else p.current.id, Jsonb(evidence)))
        row = cur.fetchone()
    assert row is not None
    return PromotionResult(_promotion(row), True, p.changes)
