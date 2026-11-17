"""The specialist readers (IA-123, AD-D09): ``readers-v1`` says when they speak, ``porcion-v1`` what findings each is handed, and the
orchestrator follows ``FBI_AI_READERS`` (``passes`` by default: today's shadow). No database, no model, no clock."""

from __future__ import annotations

import ast
import copy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import orchestrator, outputs, readers, runtime
from fbi.ai.agents import match, player, stats
from fbi.ai.agents.common import Contradiction
from fbi.ai.config import AiSettings
from fbi.evalcycle import clock

from .test_deliberation_contract import CONTRA0, round_of


def ko() -> Any:
    from datetime import UTC, datetime

    return datetime(2026, 11, 20, 20, 0, tzinfo=UTC)


def finding(code: str, *, candidates: tuple[str, ...] = ("c1",), **kw: Any) -> Contradiction:
    return Contradiction(code, "match", candidates, (), **kw)  # type: ignore[arg-type]


# -- the moment -------------------------------------------------------------------------------------------------------------------------

def test_the_windows_are_the_cycles_own() -> None:
    assert (readers.E1_FROM, readers.E1_UNTIL, readers.E4_FROM) == (clock.E1_FROM, clock.E1_UNTIL, clock.E4_FROM)
    assert readers.VERSION == "readers-v1" and readers.READERS == ("match", "stats", "player")
    assert readers.CONTRACTS == {"match": "aa-v1", "stats": "aa-v1", "player": "pa-v1"}
    assert (match.VERSION, stats.VERSION, player.VERSION) == ("match-v6", "stats-v5", "player-v2")


@pytest.mark.parametrize(("before", "e1_seen", "expected"), [
    (timedelta(hours=30), False, "none"),
    (timedelta(hours=24), False, "E1"),
    (timedelta(hours=18), False, "E1"),
    (timedelta(hours=12), True, "E1"),
    (timedelta(hours=6), True, "E2"),
    (timedelta(hours=6), False, "E1"),
    (timedelta(minutes=21), True, "E2"),
    (timedelta(minutes=20), True, "E4"),
    (timedelta(minutes=5), True, "E4"),
    (timedelta(0), True, "none"),
    (-timedelta(minutes=5), True, "none"),
])
def test_which_evaluation_a_pass_is(before: timedelta, e1_seen: bool, expected: str) -> None:
    assert readers.evaluation_of(ko() - before, ko(), e1_seen=e1_seen) == expected


def test_a_moment_without_a_zone_is_refused() -> None:
    with pytest.raises(ValueError):
        readers.evaluation_of(ko().replace(tzinfo=None), ko(), e1_seen=False)


# -- the rule ---------------------------------------------------------------------------------------------------------------------------

def test_what_is_material_for_a_second_reading() -> None:
    assert readers.material([finding("C04"), finding("C05")]) == ()
    assert readers.material([finding("C01")]) == (), "an absence that is not confirmed"
    assert readers.material([finding("C01", confirmed=True), finding("C02", confirmed=True)]) == ("C01", "C02")
    assert readers.material([finding("C03")]) == () and readers.material([finding("C03", official_lineup=True)]) == ("C03",)
    assert readers.material([finding("C06", gap=Decimal("0.25")), finding("C07"), finding("C07")]) == ("C06", "C07")
    assert readers.material([finding("C07", candidates=())]) == (), "a finding that touches no candidate"
    assert set(readers.MATERIAL_CODES) == {"C01", "C02", "C03", "C06", "C07"}


def test_when_the_readers_speak() -> None:
    material = [finding("C07")]
    assert all(readers.when("passes", e, ()).speak for e in ("E1", "E2", "E3", "E4", "none")), "passes: every pass, as before"
    assert readers.when("e1", "E1", ()).as_json() == {"version": "readers-v1", "speak": True, "evaluation": "E1", "reason": "e1", "material": []}
    assert not readers.when("e1", "E2", ()).speak and readers.when("e1", "E2", ()).reason == "e2_without_material_contradiction"
    assert readers.when("e1", "E2", material).speak and readers.when("e1", "E2", material).reason == "e2_material"
    for e in ("E3", "E4"):
        assert not readers.when("e1", e, material).speak and readers.when("e1", e, material).reason == f"{e.lower()}_is_code_only"
    assert not readers.when("e1", "none", material).speak


def test_the_switch_is_passes_unless_it_says_e1(monkeypatch: pytest.MonkeyPatch) -> None:
    assert [readers.schedule_of(w) for w in (None, "", "passes", "E1 ", "e2", "on")] == ["passes", "passes", "passes", "e1", "passes", "passes"]
    monkeypatch.delenv("FBI_AI_READERS", raising=False)
    assert AiSettings.from_env().readers == "passes" == AiSettings().readers
    monkeypatch.setenv("FBI_AI_READERS", "e1")
    assert AiSettings.from_env().readers == "e1" and AiSettings.from_env().public()["readers"] == "e1"


# -- the readers in the orchestrator --------------------------------------------------------------------------------------------------

def test_with_passes_every_round_asks_the_readers_and_the_row_says_nothing_new(monkeypatch: pytest.MonkeyPatch) -> None:
    sent, _, p = round_of(monkeypatch, context="AWAY", research_ask=False, stances=("SUPPORT", "SUPPORT", "SUPPORT"))
    assert [(a, t) for a, t, _ in sent] == [("match", "context"), ("match", "evaluation"), ("stats", "evaluation"), ("player", "evaluation")]
    assert p.turn is None and p.readers_speak and "readers" not in orchestrator._Runner.model_status(p, CONTRA0)


def test_the_turn_follows_the_switch_and_the_moment_of_the_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, p = round_of(monkeypatch, context="AWAY", research_ask=False, stances=("SUPPORT", "SUPPORT", "SUPPORT"))
    runner = orchestrator._Runner(object(), AiSettings(readers="e1"), at=p.at, limit=1, max_seconds=60.0, provider=None,  # type: ignore[arg-type]
                                  transport=None, ledger=None, slots=runtime.Slots(), circuit=runtime.Circuit(),
                                  monotonic=lambda: 0.0, sleep=lambda s: None)
    hours = (p.work.kickoff_at - p.at).total_seconds() / 3600
    assert 0.5 < hours < 12, "the hostile match is read inside the day: an E2, or a first reading when no pass fell in E1"

    class Cursor:
        def __init__(self, seen: bool) -> None:
            self.seen = seen

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def execute(self, sql: str, params: Any) -> None:
            assert sql == orchestrator.E1_SEEN_SQL and params["fixture"] == p.work.fixture_id and params["at"] == p.at

        def fetchone(self) -> tuple[bool]:
            return (self.seen,)

    class Conn:
        def __init__(self, seen: bool) -> None:
            self.seen = seen

        def cursor(self) -> Cursor:
            return Cursor(self.seen)

    for seen, evaluation in ((False, "E1"), (True, "E2")):
        runner.conn = Conn(seen)  # type: ignore[assignment]
        got = runner.readers_turn(p, CONTRA0)
        assert got is not None and got.evaluation == evaluation, (seen, got)
        assert got.speak, "a first reading speaks; an E2 of the hostile match has material findings (C03 official, C06, C07)"
        assert set(got.material) >= {"C06", "C07"}
        quiet = runner.readers_turn(p, ())
        assert quiet is not None and quiet.speak is (evaluation == "E1")
    runner.settings = AiSettings()
    assert runner.readers_turn(p, CONTRA0) is None


def test_a_pass_whose_readers_do_not_speak_asks_none_of_them(monkeypatch: pytest.MonkeyPatch) -> None:
    sent, _, p = round_of(monkeypatch, context="AWAY", research_ask=False, stances=("SUPPORT", "SUPPORT", "SUPPORT"))
    assert sent
    quiet = copy.copy(p)
    quiet.turn = readers.when("e1", "E4", CONTRA0)
    assert not quiet.readers_speak
    status = orchestrator._Runner.model_status(quiet, CONTRA0)
    assert status["readers"] == {"version": "readers-v1", "speak": False, "evaluation": "E4", "reason": "e4_is_code_only",
                                 "material": list(readers.material(CONTRA0))}


ORCHESTRATOR = ast.parse(Path(orchestrator.__file__).read_text(encoding="utf-8"))


def test_every_path_that_asks_the_readers_asks_the_turn_first() -> None:
    """The real-time round, the Batch calendar and the estimate of a pass: wherever the Match Agent's tasks are planned or asked behind
    ``WITH_MATCH``, the condition also reads ``readers_speak``."""
    guarded = 0
    for node in ast.walk(ORCHESTRATOR):
        if isinstance(node, ast.If) and "WITH_MATCH" in ast.unparse(node.test):
            body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
            if "match_round" in body or "match.context_request" in body:
                assert "readers_speak" in ast.unparse(node.test), ast.unparse(node.test)
                guarded += 1
    assert guarded == 3, guarded


def test_the_readers_answers_are_refused_outside_their_contract_before_anything_is_kept() -> None:
    """AD-A02: the shadow agents' surfaces are ``enforce`` by default - an answer outside ``aa-v1``/``pa-v1`` is invalid output."""
    by_name = {s.name: s for s in outputs.SURFACES}
    for name in ("aa-v1", "pa-v1"):
        assert outputs.mode_of("default", by_name[name], pinned=False) == "enforce", name
