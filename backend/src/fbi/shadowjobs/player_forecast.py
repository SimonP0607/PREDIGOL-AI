"""The worker's job of ``player-engine-v2`` (IA-129, AD-B08): read what was known, forecast every player market, keep.

``FBI_PLAYER_ENGINE_V2`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker does not even
schedule the job. In the shadow, every ``FBI_PLAYER_ENGINE_V2_MINUTES`` (5 by default) one pass forecasts every side of the tracked
matches due at E1 (24 to 12 hours before kick-off) or E4 (20 to 10 minutes before) and not yet forecast in that evaluation, at most
``MAX_FIXTURES`` matches a pass, nearest kick-off first, and appends one row per player, family and line to
``intel.player_forecasts`` (revision 0163).

WHAT IT READS is exactly what the estimated starters read (``fbi.shadowjobs.lineup_estimate.estimate_fixture``, IA-094, as of the
moment and nothing later), walked with v1's full engine so that the NB2 dispersions are fitted on what was known too. The start and
bench probabilities and the minutes are ``lineup-estimate-v1``'s (AD-D04); the rates, the mixture and the dispersions are v1's. No
provider, no model of language, no text of a claim.

Nothing it writes is read by a decision, a pick or a page (``tests/unit/test_players_isolation.py``): only the worker's scheduler
imports this module.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

import psycopg

from fbi.shadowjobs import lineup_estimate as les

if TYPE_CHECKING:
    from fbi.players.v2 import PlayerForecast

SWITCH: Final = "FBI_PLAYER_ENGINE_V2"
JOB: Final = "player_forecast_shadow"
MAX_FIXTURES: Final = 8
LOCK: Final = 0x1A129
TIMEOUT_MS: Final = 95_000


def mode(env: Mapping[str, str] | None = None) -> str:
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


def every_minutes(env: Mapping[str, str] | None = None) -> int:
    e = os.environ if env is None else env
    try:
        value = int(e.get("FBI_PLAYER_ENGINE_V2_MINUTES", "5").strip())
    except ValueError:
        return 5
    return value if 1 <= value <= 10 else 5


DONE_SQL: Final = """
SELECT DISTINCT fixture_id, evaluation FROM intel.player_forecasts
 WHERE fixture_id = ANY(%(fixtures)s) AND version = %(version)s
"""
INSERT_SQL: Final = """
INSERT INTO intel.player_forecasts (fixture_id, team_id, opponent_id, provider_player_id, evaluation, known_at, kickoff_at, position,
    family, stat, line, p_over, p_over_if_plays, mean, p_start, p_sub, p_play, minutes_start, minutes_sub, expected_minutes, per90,
    player_per90, prior_per90, opponent_factor, nineties, phi, start_basis, start_sample, lineup_confirmed, seal, tail, history_matches,
    version, estimate_version, input_hash, code_version)
VALUES (%(fixture_id)s, %(team_id)s, %(opponent_id)s, %(provider_player_id)s, %(evaluation)s, %(known_at)s, %(kickoff_at)s,
    %(position)s, %(family)s, %(stat)s, %(line)s, %(p_over)s, %(p_over_if_plays)s, %(mean)s, %(p_start)s, %(p_sub)s, %(p_play)s,
    %(minutes_start)s, %(minutes_sub)s, %(expected_minutes)s, %(per90)s, %(player_per90)s, %(prior_per90)s, %(opponent_factor)s,
    %(nineties)s, %(phi)s, %(start_basis)s, %(start_sample)s, %(lineup_confirmed)s, %(seal)s, %(tail)s, %(history_matches)s,
    %(version)s, %(estimate_version)s, %(input_hash)s, %(code_version)s)
ON CONFLICT ON CONSTRAINT player_forecasts_once DO NOTHING
"""


@dataclass
class PassReport:
    due: Counter[str] = field(default_factory=Counter)
    fixtures: int = 0
    players: int = 0
    rows: int = 0
    confirmed_sides: int = 0
    families: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"due": dict(sorted(self.due.items())), "fixtures": self.fixtures, "players": self.players, "rows": self.rows,
                "confirmed_sides": self.confirmed_sides, "families": dict(sorted(self.families.items())), "errors": self.errors[:20]}


def row_of(f: PlayerForecast, *, evaluation: str, kickoff: datetime, history_matches: int, code_version: str | None) -> dict[str, Any]:
    """One ``PlayerForecast`` as the row it is stored as (the rounded figures and their hash). Pure."""
    r: dict[str, Any] = f.as_row()
    p_play = r["p_play"]
    return r | {"evaluation": evaluation, "known_at": f.known_at, "kickoff_at": kickoff, "history_matches": history_matches,
                "p_over": r["p_over"] if p_play > 0 else 0.0, "p_over_if_plays": r["p_over_if_plays"] if p_play > 0 else None,
                "input_hash": f.input_hash(), "code_version": code_version}


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None = None, commit: bool = True,
             limit: int = MAX_FIXTURES) -> PassReport:
    """One pass. Each match is its own transaction (``commit``; a savepoint without it): one that fails is counted and the pass goes on."""
    from fbi.ai.gates import typed_visible
    from fbi.players import v2

    rep = PassReport()
    got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
    if not got or not got[0]:
        rep.errors.append("another pass holds the lock")
        return rep
    try:
        if commit:
            conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        due = [(int(r["id"]), r["kickoff_at"]) for r in les._fetch(conn, les.DUE_SQL, {"at": now, "floor": les.E4_UNTIL,
                                                                                         "ahead": les.E1_FROM})]
        done = {(int(r["fixture_id"]), str(r["evaluation"])) for r in les._fetch(conn, DONE_SQL, {"fixtures": [f for f, _ in due],
                                                                                                   "version": v2.VERSION})} if due else set()
        todo = [(f, k, ev) for f, k in due if (ev := les.evaluation_due(k, now)) is not None and (f, ev) not in done]
        todo.sort(key=lambda x: (x[1], x[0]))
        typed = typed_visible(conn)
        if commit:
            conn.commit()
        for fid, kickoff, ev in todo[:limit]:
            rep.due[ev] += 1
            try:
                with conn.transaction():
                    _one(conn, fid, kickoff, ev, now=now, typed=typed, code_version=code_version, rep=rep)
            except (psycopg.Error, ValueError, KeyError) as exc:
                rep.errors.append(f"{fid}/{ev}: {type(exc).__name__}: {exc}"[:300])
    finally:
        if commit:
            conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        if commit:
            conn.commit()
    return rep


def forecast_fixture(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, typed: bool) -> dict[str, Any] | None:
    """The forecasts of one match as of ``at`` and what they were made from. Read-only (the owner's script prints it)."""
    from fbi.players import v2

    doc = les.estimate_fixture(conn, fixture_id, at=at, typed=typed, dispersion=True)
    if doc is None:
        return None
    return doc | {"forecasts": v2.forecast_fixture(doc, at=at, phi=doc["dispersion"])}


def _one(conn: psycopg.Connection[Any], fixture_id: int, kickoff: datetime, evaluation: str, *, now: datetime, typed: bool,
         code_version: str | None, rep: PassReport) -> None:
    doc = forecast_fixture(conn, fixture_id, at=now, typed=typed)
    if doc is None:
        return
    rep.fixtures += 1
    rep.confirmed_sides += sum(int(bool(s["confirmed"])) for s in doc["sides"].values())
    rep.players += len({f.provider_player_id for f in doc["forecasts"]})
    for f in doc["forecasts"]:
        conn.execute(INSERT_SQL, row_of(f, evaluation=evaluation, kickoff=kickoff, history_matches=int(doc["history_matches"]),
                                        code_version=code_version))
        rep.rows += 1
        rep.families[f.family] += 1
