"""The database side of the scenarios engine (plan 2026, AD-B02, IA-082): a competition season as it could be known at a moment, our
goal model's score distribution for every match left, and the append-only record of the readings (``intel.scenario_readings``,
migration 0147). The engine itself is ``fbi.competitions.scenarios`` (pure).

AS OF A MOMENT. A result counts only when it was recorded by then (``settled_at <= at`` and kick-off before it, the convention of
``fbi.competitions.context``), and the calendar is the one that existed (a fixture created later is not on it). The provider's table
is its newest snapshot taken by then; it is used to identify the groups of a group phase and to check the points, never as the source
of the points.

THE MODEL. The same Dixon-Coles model the real-time forecast fits (``fbi.predictions.forecast``): refitted on the competition's results
known three hours after kick-off, over the training window and with the time decay and shrinkage of the spec a person promoted
(``analytics.promoted_forecast_spec``), so the probabilities are ours and change only when that spec changes. A match whose
Dixon-Coles correction is invalid at its expected goals takes the Poisson model's matrix (the same spec); a team the model does not
know (no result in the window) leaves the table without a simulation, said so - nothing is invented for it. Fitting is in memory: no
row is written to ``models``.

IN SHADOW. ``FBI_SCENARIOS`` is ``off`` by default (and anything unknown means off): the worker's job does nothing. With ``shadow``
it writes, every few hours, one reading per live coded competition season (skipped when nothing changed since the newest one). No
reader of the product reads the table; the private view and AD-F01 will, behind their own switches.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import numpy as np
import psycopg
from numpy.typing import NDArray
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.competitions import rules as rl
from fbi.competitions import scenarios as sc
from fbi.core.env import environment
from fbi.models.goals import GoalModel, GoalObs, InvalidCorrectionError, fit_goal_model

SWITCH: Final = "FBI_SCENARIOS"
MODES: Final = ("off", "shadow")
EVERY_MINUTES: Final = 360
FOCUS_AHEAD: Final = timedelta(days=7)
"""The matches whose three results are read one by one: those that kick off in the next week."""
RESULT_AVAILABLE_AFTER: Final = timedelta(hours=3)
MIN_TRAIN: Final = 100
MODEL: Final = "dixon_coles"
FALLBACK: Final = "poisson"
TABLE: Final = "intel.scenario_readings"
LIVE_WINDOW: Final = timedelta(days=45)
"""A season is live when it has a match left and a match within this window of the moment (either side)."""


def mode() -> str:
    """``FBI_SCENARIOS``: ``off`` (the default, and what anything unknown means) or ``shadow``. Read at the start of each run."""
    value = environment().get(SWITCH, "off").strip().lower()
    return value if value in MODES else "off"


# ── the model ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Played:
    """A result of the competition the model trains on: regulation score where there is one."""

    kickoff_at: datetime
    home: int
    away: int
    home_goals: int
    away_goals: int
    neutral: bool = False


@dataclass(frozen=True, slots=True)
class Target:
    fixture_id: int
    home: int
    away: int
    neutral: bool = False


@dataclass(frozen=True, slots=True)
class GoalSpec:
    xi: float
    penalty: float
    history_days: int

    @property
    def tag(self) -> str:
        return f"xi={self.xi:g},penalty={self.penalty:g},window={self.history_days}d"


def _fit(train: Sequence[Played], kind: str, spec: GoalSpec, at: datetime) -> GoalModel | None:
    obs = [GoalObs(m.home, m.away, m.home_goals, m.away_goals,
                   weight=math.exp(-spec.xi * (at - m.kickoff_at).total_seconds() / 86400), neutral=m.neutral) for m in train]
    try:
        model = fit_goal_model(obs, kind=kind, xi=spec.xi, penalty=spec.penalty, with_covariance=False)
    except (ValueError, np.linalg.LinAlgError):
        return None
    return model if model.converged else None


def fit_scores(history: Iterable[Played], targets: Sequence[Target], *, at: datetime, spec: GoalSpec
               ) -> tuple[dict[int, NDArray[np.float64]], dict[str, Any]]:
    """The score distribution of each target from our goal model fitted at ``at`` on ``history`` (results known three hours after
    kick-off, inside the spec's window), and what was done: model, training size, fallbacks, targets not covered and why."""
    train = [m for m in history if m.kickoff_at + RESULT_AVAILABLE_AFTER < at
             and m.kickoff_at >= at - timedelta(days=spec.history_days)]
    info: dict[str, Any] = {"model": MODEL, "fallback": FALLBACK, "spec": spec.tag, "n_train": len(train), "fallbacks": 0,
                            "uncovered": {}}
    if len(train) < MIN_TRAIN:
        info["error"] = f"fewer than {MIN_TRAIN} results in the training window"
        return {}, info
    main = _fit(train, MODEL, spec, at)
    if main is None:
        info["error"] = "the model fit failed or did not converge"
        return {}, info
    second: GoalModel | None = None
    out: dict[int, NDArray[np.float64]] = {}
    for t in targets:
        if not (main.knows(t.home) and main.knows(t.away)):
            info["uncovered"][str(t.fixture_id)] = "a team has no result in the training window"
            continue
        try:
            out[t.fixture_id] = main.score_matrix(t.home, t.away, neutral=t.neutral)[0]
        except InvalidCorrectionError:
            if second is None:
                second = _fit(train, FALLBACK, spec, at)
            if second is None or not (second.knows(t.home) and second.knows(t.away)):
                info["uncovered"][str(t.fixture_id)] = "Dixon-Coles correction invalid and no Poisson fit"
                continue
            out[t.fixture_id] = second.score_matrix(t.home, t.away, neutral=t.neutral)[0]
            info["fallbacks"] += 1
    return out, info


# ── reading the database (read-only) ────────────────────────────────────────────────────────────────────────────────────────────────

SEASON_SQL: Final = """
SELECT s.id, c.id FROM core.competitions c JOIN core.competition_seasons s ON s.competition_id = c.id
 WHERE c.provider_league_id = %(league)s AND s.season = %(season)s
"""

FIXTURES_SQL: Final = """
SELECT f.id, f.round, f.home_team_id, f.away_team_id, f.kickoff_at,
       CASE WHEN f.kickoff_at <= %(at)s THEN r.goals_home END, CASE WHEN f.kickoff_at <= %(at)s THEN r.goals_away END
  FROM core.fixtures f
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id AND r.settled_at <= %(at)s
 WHERE f.competition_season_id = %(cs)s AND f.created_at <= %(at)s
 ORDER BY f.kickoff_at, f.id
"""
"""The season as known at ``at``: the fixtures that existed, each with the result recorded by then (none otherwise)."""

PROVIDER_SQL: Final = """
WITH last AS (SELECT group_key, max(snapshot_at) AS s FROM core.standings
               WHERE competition_season_id = %(cs)s AND snapshot_at <= %(at)s GROUP BY 1)
SELECT st.group_key, st.team_id, st.points, st.played
  FROM core.standings st JOIN last l ON l.group_key = st.group_key AND l.s = st.snapshot_at
 WHERE st.competition_season_id = %(cs)s
"""

HISTORY_SQL: Final = """
SELECT f.kickoff_at, f.home_team_id, f.away_team_id, coalesce(r.reg_goals_home, r.goals_home), coalesce(r.reg_goals_away, r.goals_away),
       (f.is_neutral OR c.neutral_venue)
  FROM core.fixtures f
  JOIN core.competition_seasons s ON s.id = f.competition_season_id
  JOIN core.competitions c ON c.id = s.competition_id
  JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE c.id = %(comp)s AND f.status_group = 'finished' AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
   AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s AND r.settled_at <= %(at)s
"""
"""The competition's results the model trains on (every season of it, the way the real-time forecast trains per competition)."""

SPEC_SQL: Final = "SELECT spec FROM analytics.promoted_forecast_spec ORDER BY id DESC LIMIT 1"

LIVE_SQL: Final = """
SELECT s.season FROM core.competitions c JOIN core.competition_seasons s ON s.competition_id = c.id
 WHERE c.provider_league_id = %(league)s
   AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = s.id AND f.status_group = 'scheduled'
                  AND f.kickoff_at > %(at)s)
   AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = s.id
                  AND f.kickoff_at BETWEEN %(lo)s AND %(hi)s)
 ORDER BY s.season
"""

NEWEST_SQL: Final = f"SELECT input_hash FROM {TABLE} WHERE competition_season_id = %(cs)s ORDER BY id DESC LIMIT 1"

INSERT_SQL: Final = f"""
INSERT INTO {TABLE} (computed_at, league_id, season, competition_season_id, status, engine_version, rules_version, rules_sha256,
                     model, sims, seed, input_hash, contradictions, reading, code_version)
VALUES (%(at)s, %(league)s, %(season)s, %(cs)s, %(status)s, %(engine)s, %(rules_version)s, %(rules_sha)s, %(model)s, %(sims)s,
        %(seed)s, %(hash)s, %(contradictions)s, %(reading)s, %(code)s)
RETURNING id
"""


def promoted_spec(conn: psycopg.Connection[Any]) -> GoalSpec | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPEC_SQL)
        row = cur.fetchone()
    if row is None:
        return None
    doc = row[0]
    hyper = (doc.get("goal") or {}).get(MODEL)
    if not hyper:
        return None
    return GoalSpec(float(hyper["xi"]), float(hyper["penalty"]), int(doc.get("history_days", 730)))


@dataclass(frozen=True, slots=True)
class SeasonInputs:
    competition_season_id: int
    competition_id: int
    fixtures: list[sc.Fixture]
    kickoffs: dict[int, datetime]
    provider: dict[str, list[sc.ProviderRow]]


def season_inputs(conn: psycopg.Connection[Any], league_id: int, season: int, at: datetime) -> SeasonInputs | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SEASON_SQL, {"league": league_id, "season": season})
        row = cur.fetchone()
        if row is None:
            return None
        cs, comp = int(row[0]), int(row[1])
        cur.execute(FIXTURES_SQL, {"cs": cs, "at": at})
        fixtures: list[sc.Fixture] = []
        kickoffs: dict[int, datetime] = {}
        for fid, rd, h, a, ko, gh, ga in cur.fetchall():
            fixtures.append(sc.Fixture(int(fid), None if rd is None else str(rd), int(h), int(a),
                                       None if gh is None or ga is None else int(gh), None if gh is None or ga is None else int(ga)))
            kickoffs[int(fid)] = ko
        cur.execute(PROVIDER_SQL, {"cs": cs, "at": at})
        provider: dict[str, list[sc.ProviderRow]] = {}
        for g, team, pts, played in cur.fetchall():
            provider.setdefault(str(g), []).append(sc.ProviderRow(int(team), int(pts or 0), int(played or 0)))
    return SeasonInputs(cs, comp, fixtures, kickoffs, provider)


def history(conn: psycopg.Connection[Any], competition_id: int, at: datetime, spec: GoalSpec) -> list[Played]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(HISTORY_SQL, {"comp": competition_id, "since": at - timedelta(days=spec.history_days),
                                  "until": at - RESULT_AVAILABLE_AFTER, "at": at})
        return [Played(ko, int(h), int(a), int(gh), int(ga), bool(n)) for ko, h, a, gh, ga, n in cur.fetchall()]


def input_hash(answer: rl.Answer, fixtures: Sequence[sc.Fixture], provider: Mapping[str, Sequence[sc.ProviderRow]],
               model: Mapping[str, Any], *, sims: int, seed: int, focus: Sequence[int]) -> str:
    """What a reading was computed from: a reading with the same inputs is the same reading (and is not written again)."""
    doc = {"engine": sc.VERSION, "rules": answer.as_json(), "sims": sims, "seed": seed, "focus": sorted(focus),
           "fixtures": [(f.id, f.round, f.home, f.away, f.home_goals, f.away_goals) for f in sorted(fixtures, key=lambda x: x.id)],
           "provider": {k: sorted((r.team, r.points, r.played) for r in v) for k, v in sorted(provider.items())},
           "model": {k: v for k, v in model.items() if k in ("model", "spec", "n_train", "train_hash")}}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()


def read_season(conn: psycopg.Connection[Any], league_id: int, season: int, *, at: datetime, sims: int = sc.DEFAULT_SIMS,
                seed: int = sc.DEFAULT_SEED, simulate: bool = True, focus: Sequence[int] | None = None) -> dict[str, Any] | None:
    """The reading of a competition season at ``at`` (read-only). None when the season is not in the database."""
    answer = rl.rules_for(league_id, season, on=at.date())
    inputs = season_inputs(conn, league_id, season, at)
    if inputs is None:
        return None
    if focus is None:
        focus = [f.id for f in inputs.fixtures if not f.played and at < inputs.kickoffs[f.id] <= at + FOCUS_AHEAD]
    scores: dict[int, NDArray[np.float64]] | None = None
    model: dict[str, Any] = {"model": None}
    if simulate and isinstance(answer, rl.Coded):
        spec = promoted_spec(conn)
        if spec is None:
            model = {"model": None, "error": "no promoted forecast spec"}
        else:
            train = history(conn, inputs.competition_id, at, spec)
            targets = [Target(f.id, f.home, f.away) for f in inputs.fixtures if not f.played]
            scores, model = fit_scores(train, targets, at=at, spec=spec)
            model["train_hash"] = hashlib.sha256(json.dumps(sorted(
                (m.kickoff_at.isoformat(), m.home, m.away, m.home_goals, m.away_goals) for m in train)).encode()).hexdigest()[:16]
    reading = sc.evaluate(answer, inputs.fixtures, at=at, scores=scores, provider=inputs.provider, sims=sims if scores else 0,
                          seed=seed, focus=focus)
    reading["competition_season_id"] = inputs.competition_season_id
    reading["seed"] = seed
    reading["model"] = model
    reading["input_hash"] = input_hash(answer, inputs.fixtures, inputs.provider, model, sims=sims, seed=seed, focus=focus)
    return reading


def write(conn: psycopg.Connection[Any], reading: Mapping[str, Any], *, code_version: str | None = None) -> int | None:
    """Append the reading unless the newest one of its season had the same inputs. The caller commits."""
    cs = int(reading["competition_season_id"])
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(NEWEST_SQL, {"cs": cs})
        row = cur.fetchone()
        if row is not None and row[0] == reading["input_hash"]:
            return None
        rules = reading.get("rules") or {}
        model = reading.get("model") or {}
        cur.execute(INSERT_SQL, {
            "at": datetime.fromisoformat(str(reading["at"])), "league": int(reading["league_id"]), "season": int(reading["season"]),
            "cs": cs, "status": str(reading["status"]), "engine": str(reading["version"]),
            "rules_version": rules.get("version"), "rules_sha": rules.get("sha256"),
            "model": None if not model.get("model") else f"{model['model']}:{model.get('spec')}",
            "sims": max((int(t["simulation"]["sims"]) for t in reading.get("tables", [])), default=0),
            "seed": int(reading.get("seed", sc.DEFAULT_SEED)),
            "hash": str(reading["input_hash"]), "contradictions": int(reading.get("contradicciones", 0)),
            "reading": Jsonb(reading), "code": code_version})
        out = cur.fetchone()
    return None if out is None else int(out[0])


def live_seasons(conn: psycopg.Connection[Any], lib: rl.Library, at: datetime) -> list[tuple[int, int]]:
    """(league, season) of every coded competition with a season being played around ``at``."""
    out: list[tuple[int, int]] = []
    coded = sorted({f.rules.league_id for f in lib.files if f.rules.state == "coded"})
    with conn.cursor(row_factory=tuple_row) as cur:
        for league in coded:
            cur.execute(LIVE_SQL, {"league": league, "at": at, "lo": at - LIVE_WINDOW, "hi": at + LIVE_WINDOW})
            out.extend((league, int(r[0])) for r in cur.fetchall())
    return out


def run_shadow(conn: psycopg.Connection[Any], *, at: datetime, code_version: str | None = None,
               sims: int = sc.DEFAULT_SIMS) -> dict[str, Any]:
    """The worker's step: nothing unless ``FBI_SCENARIOS=shadow``; then one reading per live coded season, each committed on its own
    (a season that fails does not stop the others)."""
    if mode() != "shadow":
        return {"skipped": "switch_off"}
    report: dict[str, Any] = {"at": at.isoformat(), "seasons": 0, "written": 0, "unchanged": 0, "errors": []}
    for league, season in live_seasons(conn, rl.library(), at):
        report["seasons"] += 1
        try:
            with conn.transaction():
                reading = read_season(conn, league, season, at=at, sims=sims)
                if reading is None:
                    continue
                if write(conn, reading, code_version=code_version) is None:
                    report["unchanged"] += 1
                else:
                    report["written"] += 1
        except (psycopg.Error, ValueError, KeyError) as exc:
            report["errors"].append(f"{league}/{season}: {type(exc).__name__}: {exc}"[:300])
    return report
