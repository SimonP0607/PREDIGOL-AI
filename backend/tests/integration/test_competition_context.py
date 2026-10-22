"""``fbi.competitions.context`` against the real schema (plan F2): a match's stage and tie as they can be said BEFORE it is played.

The rule these tests defend: ``core.ties`` and ``core.competition_stages`` also store what came out of the competition - the
winner, the aggregate, the way a tie was decided, whether a replay was needed - and that includes the result of the match about to
be played. A reader asked "as of" a moment must say the same thing whatever those columns hold. So the tests do not only check
what the reader returns: they POISON every post-match column (and the result of the match itself, and of the legs after it) and
require the answer, byte for byte, to be the same."""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from datetime import timedelta
from typing import Any

import psycopg
import pytest

import fbi
from fbi.competitions import builder
from fbi.competitions import context as cx
from tests.integration.conftest import Seed
from tests.integration.test_competition_builder import D0, NOW, World, champions_league, make_world

pytestmark = pytest.mark.integration


def kickoff(day: int) -> Any:
    return D0 + timedelta(days=day)


def phase(w: World, fixture_id: int, at: Any) -> dict[str, Any] | None:
    found = cx.phase_as_of(w.db, fixture_id, at=at)
    return None if found is None else found.as_json()


def built(db: psycopg.Connection[Any], seed: Seed, league: int) -> tuple[World, dict[str, int]]:
    w = make_world(db, seed, league)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    return w, f


# ── what is said ────────────────────────────────────────────────────────────


def test_the_second_leg_is_seen_with_the_first_leg_that_had_been_recorded(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, f = built(db, seed, 99901)
    t = w.team
    before = kickoff(107) - timedelta(hours=3)

    got = phase(w, f["r2"], before)

    assert got is not None
    assert (got["version"], got["stage"], got["kind"], got["role"], got["round_key"]) == (
        "phase-v1", "Round of 16", "knockout", "knockout", "round_of_16")
    tie = got["tie"]
    assert (tie["format"], tie["leg"], tie["legs"], tie["previous_without_result"]) == ("two_legged", 2, 2, 0)
    # team 1 won the first leg at home, 1-0; the second leg is played at team 4's ground: team 4 trails by one
    assert tie["previous"] == [{
        "fixture_id": f["r1"], "leg": 1, "kickoff_at": kickoff(100).isoformat(), "home_side_was": "away",
        "goals_home_side": 0, "goals_away_side": 1, "after_extra_time": False}]
    assert tie["aggregate_before"] == {"home_side": 0, "away_side": 1}
    assert tie["outlook"] == {"kind": "second_leg", "home_side_ahead_if_home_margin_at_least": 2,
                              "level_if_home_margin_is": 1, "away_side_ahead_if_home_margin_at_most": 0,
                              "if_level": "competition_rules"}
    assert t[4] != t[1]


def test_a_first_leg_is_a_first_leg_and_a_group_match_has_a_stage_but_no_tie(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, f = built(db, seed, 99902)

    first = phase(w, f["r1"], kickoff(100) - timedelta(hours=1))
    group = phase(w, f["g1"], kickoff(30) - timedelta(hours=1))
    final = phase(w, f["fin"], kickoff(200) - timedelta(hours=1))

    assert first is not None and first["tie"]["outlook"] == {"kind": "first_leg"}
    assert (first["tie"]["previous"], first["tie"]["aggregate_before"], first["tie"]["legs"]) == ([], None, 2)
    assert group == {"version": "phase-v1", "stage": "Group Stage", "kind": "league", "role": "group", "round_key": None,
                     "tie": None}
    assert final is not None and final["role"] == "final" and final["tie"]["format"] == "single"
    assert final["tie"]["outlook"] == {"kind": "single_match"} and final["tie"]["aggregate_before"] is None


def test_a_first_leg_without_a_recorded_result_leaves_the_aggregate_unknown(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, f = built(db, seed, 99903)

    at = kickoff(100) + timedelta(hours=1)  # the first leg is over; its result was recorded two hours after kick-off
    unrecorded = phase(w, f["r2"], at)
    recorded = phase(w, f["r2"], kickoff(100) + timedelta(hours=2))  # exactly when it was recorded

    assert unrecorded is not None and recorded is not None
    assert unrecorded["tie"]["previous"] == [] and unrecorded["tie"]["previous_without_result"] == 1
    assert unrecorded["tie"]["aggregate_before"] is None
    assert unrecorded["tie"]["outlook"] == {"kind": "second_leg", "aggregate": "unknown"}
    assert recorded["tie"]["previous_without_result"] == 0 and recorded["tie"]["aggregate_before"] == {
        "home_side": 0, "away_side": 1}, "settled_at <= at: a result recorded at the very moment is known"


def test_a_fixture_whose_season_was_never_built_has_no_phase(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99904)
    f = champions_league(w)

    assert cx.phase_as_of(db, f["r2"], at=NOW) is None
    assert cx.phase_as_of(db, 999999999, at=NOW) is None


def test_an_unread_round_label_is_a_stage_of_unknown_kind_not_a_guess(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99905)
    odd = w.fixture("R60310", 1, 2, 0, (1, 0))
    builder.build_one(db, w.season, now=NOW)

    got = phase(w, odd, NOW)

    assert got is not None and got["kind"] == "unresolved" and got["role"] == "unresolved" and got["tie"] is None


def test_a_replay_knows_it_is_one_and_the_first_match_does_not(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99906)
    first = w.fixture("3rd Round", 1, 2, 0, (1, 1))
    w.fixture("3rd Round", 3, 4, 0, (2, 0))
    replay = w.fixture("3rd Round Replays", 2, 1, 5, (0, 1))
    builder.build_one(db, w.season, now=NOW)

    the_first = phase(w, first, kickoff(0) - timedelta(hours=1))
    the_replay = phase(w, replay, kickoff(5) - timedelta(hours=1))

    assert the_first is not None and the_replay is not None
    assert the_first["tie"]["format"] == "single" and the_first["tie"]["legs"] == 1, "a replay is not scheduled until needed"
    assert (the_replay["tie"]["format"], the_replay["tie"]["legs"], the_replay["replay_stage"]) == ("replay", 2, True)
    assert the_replay["tie"]["aggregate_before"] == {"home_side": 1, "away_side": 1}
    assert the_replay["tie"]["outlook"] == {"kind": "replay", "decides_the_tie": True}


def test_the_first_match_reads_the_same_whether_or_not_a_replay_turned_out_to_be_needed(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    """The stored format of the tie ('replay') is itself a result: the first match ended level. It must not reach a reader of
    the first match - the answer is the one of a world where the first match was decisive and no replay exists."""
    needed = make_world(db, seed, 99907)
    a = needed.fixture("3rd Round", 1, 2, 0, (1, 1))
    needed.fixture("3rd Round", 3, 4, 0, (2, 0))
    needed.fixture("3rd Round Replays", 2, 1, 5, (0, 1))
    decisive = make_world(db, seed, 99908)
    b = decisive.fixture("3rd Round", 1, 2, 0, (1, 1))
    decisive.fixture("3rd Round", 3, 4, 0, (2, 0))
    builder.build_one(db, needed.season, now=NOW)
    builder.build_one(db, decisive.season, now=NOW)
    assert needed.one("SELECT format FROM core.ties t JOIN core.fixtures f ON f.tie_id = t.id WHERE f.id = %s", a) == "replay"
    assert decisive.one("SELECT format FROM core.ties t JOIN core.fixtures f ON f.tie_id = t.id WHERE f.id = %s", b) == "single"

    at = kickoff(0) - timedelta(hours=2)

    assert phase(needed, a, at) == phase(decisive, b, at)


def test_a_series_shows_a_single_match_at_its_first_game(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99909)
    g1 = w.fixture("Final", 1, 2, 0, (1, 0))
    g2 = w.fixture("Final", 2, 1, 3, (1, 0))
    g3 = w.fixture("Final", 1, 2, 6, (2, 1))
    builder.build_one(db, w.season, now=NOW)
    assert w.one("SELECT format FROM core.ties") == "series"

    first = phase(w, g1, kickoff(0) - timedelta(hours=1))
    second = phase(w, g2, kickoff(3) - timedelta(hours=1))
    third = phase(w, g3, kickoff(6) - timedelta(hours=1))

    assert first is not None and first["tie"]["format"] == "single"
    assert second is not None and second["tie"]["outlook"]["kind"] == "series" and second["tie"]["outlook"]["game"] == 2
    assert third is not None and third["tie"]["outlook"] == {
        "kind": "series", "game": 3, "wins_home_side": 1, "wins_away_side": 1, "draws": 0, "complete": True}


# ── the leak: nothing that came out of the competition moves what is said before ───


def snapshot(w: World, fixtures: dict[str, int]) -> dict[str, str]:
    """The packet-ready phase of every fixture of the world at three moments around each of its own kick-offs, as text."""
    out: dict[str, str] = {}
    for name, fixture_id in fixtures.items():
        ko = w.one("SELECT kickoff_at FROM core.fixtures WHERE id = %s", fixture_id)
        for label, at in (("3h before", ko - timedelta(hours=3)), ("at kick-off", ko), ("a day after", ko + timedelta(days=1))):
            out[f"{name} {label}"] = json.dumps(phase(w, fixture_id, at), sort_keys=True)
    return out


POISON_TIES = """
UPDATE core.ties SET status = 'decided', winner_team_id = team_b_id, decided_by = 'walkover', reason = 'poison',
       decided_at = '2031-01-01 00:00Z', aggregate_a = 9, aggregate_b = 0, shootout_a = 1, shootout_b = 2,
       winner_check = 'contradicted', flags = ARRAY['poison'], played = legs + 5, legs = legs + 5
"""
POISON_STAGES = """
UPDATE core.competition_stages SET ties = ties + 40, fixtures = fixtures + 40, teams = COALESCE(teams, 0) + 40,
       tie_format = 'series', tie_reason = 'poison', round_no = 99
 WHERE tie_format IS NOT NULL
"""


def test_nothing_the_competition_produced_changes_what_is_said_before_a_match(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, f = built(db, seed, 99910)
    quiet = snapshot(w, f)
    assert any('"aggregate_before": {"away_side": 1, "home_side": 0}' in v for v in quiet.values()), "the snapshot sees a tie"

    db.execute(POISON_TIES)
    db.execute(POISON_STAGES)
    db.execute("UPDATE core.competition_stages SET kind = kind")  # the build's own columns stay as they are

    assert snapshot(w, f) == quiet, "the winner, aggregate, shoot-out, status, reason and the counts are not read"


def test_the_result_of_the_match_itself_and_of_the_legs_after_it_are_not_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, f = built(db, seed, 99911)
    r2_before = phase(w, f["r2"], kickoff(107) - timedelta(hours=3))
    r1_before = phase(w, f["r1"], kickoff(100) - timedelta(hours=3))

    w.set_goals(f["r2"], 7, 0)                       # the second leg, as it ended - and corrected
    db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s", (kickoff(107) + timedelta(hours=2), f["r2"]))
    w.set_goals(f["k1"], 5, 5)                       # and a later round
    db.execute("UPDATE core.fixtures SET status_short = 'CANC', status_group = 'cancelled' WHERE id = %s", (f["r2"],))

    assert phase(w, f["r2"], kickoff(107) - timedelta(hours=3)) == r2_before
    assert phase(w, f["r1"], kickoff(100) - timedelta(hours=3)) == r1_before, "the first leg cannot see its own second leg"


def test_a_first_leg_never_sees_its_second_leg_however_long_after_it_is_asked(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, f = built(db, seed, 99913)
    long_after = NOW + timedelta(days=30)

    for first in ("q1", "r1", "k1"):
        got = phase(w, f[first], long_after)
        assert got is not None
        assert got["tie"]["leg"] == 1 and got["tie"]["previous"] == [], first
        assert got["tie"]["aggregate_before"] is None and got["tie"]["outlook"] == {"kind": "first_leg"}, first
    final = phase(w, f["fin"], long_after)
    assert final is not None and final["tie"]["previous"] == [] and final["tie"]["outlook"] == {"kind": "single_match"}


# ── the structural guard: who may read the tables that hold outcomes ────────

OUTCOME_TABLES = re.compile(r"\bcore\.(ties|competition_stages)\b")

READERS_OF_STRUCTURE: dict[str, str] = {
    "fbi.competitions.builder": "writes the tables and checks them from the outside (post-match by nature)",
    "fbi.competitions.context": "the one door for the pre-match readers: structure and the legs already recorded, nothing else",
    "fbi.api.repositories.center": "the match page: a finished tie is shown with its outcome, a match not yet played with "
                                   "the legs recorded so far",
}
"""The modules that name ``core.ties`` or ``core.competition_stages`` in SQL, and why each may. A new reader is added HERE, by a
person, with the reason: a pre-match reader (a feature, a model, a pick, the AI packet, the dossier) belongs behind
``fbi.competitions.context`` and never on this list."""


def _modules() -> list[str]:
    return sorted(m.name for m in pkgutil.walk_packages(fbi.__path__, prefix="fbi.") if not m.ispkg)


def _sql_strings(module: Any) -> list[str]:
    import ast
    import inspect

    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError):
        return []
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_only_the_listed_modules_name_the_tables_that_hold_the_outcome_of_a_tie() -> None:
    naming = {name for name in _modules()
              if any(OUTCOME_TABLES.search(s) for s in _sql_strings(importlib.import_module(name)))}

    assert naming <= set(READERS_OF_STRUCTURE), (
        f"{sorted(naming - set(READERS_OF_STRUCTURE))} read core.ties / core.competition_stages: a pre-match reader goes "
        "through fbi.competitions.context; a post-match one is added to READERS_OF_STRUCTURE with its reason")
    assert {"fbi.competitions.builder", "fbi.competitions.context"} <= naming, "the scan does reach the modules that matter"


def test_the_one_door_reads_only_the_columns_that_are_structure() -> None:
    sql = " ".join(s for s in (cx.STAGE_SQL, cx.EARLIER_LEGS_SQL))
    ties = set(re.findall(r"\bt\.(\w+)", sql))
    stages = set(re.findall(r"\bs\.(\w+)", sql))

    assert ties == {"id", "format"}, "from core.ties: the key to join on and the format, nothing that is an outcome"
    assert stages == {"id", "stage", "kind", "role", "round_key", "is_replay"}, "the words of the label, not the counts"
    forbidden = ("winner", "aggregate", "decided", "shootout", "winner_check", "flags", "reason", "played", "status")
    assert not [w for w in forbidden if re.search(rf"\b[ts]\.{w}", sql)]
