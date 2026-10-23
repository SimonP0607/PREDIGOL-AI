"""The wiring of the ONE post-mortem (plan F8): the learning cycle of the AI (07:35 Bogotá) and the nightly step of the intelligence layer
study each selection and each match once, whichever runs first; the two first post-mortems (pm-v1 by match, pm-v2 by selection) are frozen
and write again only behind ``FBI_AI_LEGACY_POSTMORTEMS`` - after the one post-mortem, so that nothing is remembered twice; a post-mortem that
fails does not stop what the rest of the cycle learns.

The world is the one of ``test_postmortem_v6``; the cycle runs through ``Savepoints`` (the worker commits, the test's transaction does not)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai.config import AiSettings
from fbi.ai.cycle import run_learning_cycle
from fbi.ai.usage import UsageLedger, shared
from fbi.intel.cycle import postmortems_step

from .conftest import Seed
from .helpers import scalar
from .test_ai_decision_layer import Savepoints
from .test_postmortem_v6 import LATE, Pm

pytestmark = pytest.mark.integration

MORNING = LATE + timedelta(minutes=35)
"""07:35 in Bogotá on the 2nd: every match of the 1st is over and its day is closed."""


def count(db: psycopg.Connection[Any], sql: str) -> int:
    return int(scalar(db.execute(sql)))


def learn(db: psycopg.Connection[Any], conn: Savepoints, *, at: Any = MORNING, **settings: Any) -> Any:
    return run_learning_cycle(conn, at=at, settings=AiSettings(mode="shadow", **settings), ledger=UsageLedger(shared(db)))  # type: ignore[arg-type]


def test_the_learning_cycle_studies_each_selection_and_each_match_once_and_leaves_the_frozen_writers_alone(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    Pm(db, seed)
    conn = Savepoints(db)
    report = learn(db, conn)
    assert report.status == "ok", report.errors
    studied = count(db, "SELECT count(*) FROM intel.selection_postmortems")
    assert studied > 0 and report.counts["pick_postmortems"] == studied
    assert report.counts["postmortems"] == count(db, "SELECT count(*) FROM intel.match_postmortems") > 0
    assert report.counts["losses_studied"] + report.counts["wins_studied"] <= studied
    assert any(k.startswith("class_") for k in report.counts), "the classes of the losses are counted"
    assert (count(db, "SELECT count(*) FROM ai.pick_postmortems"), count(db, "SELECT count(*) FROM ai.postmortems")) == (0, 0), \
        "the first two post-mortems are frozen: they wrote nothing"
    assert not any(k.startswith("legacy_") for k in report.counts)
    ai_studied = count(db, "SELECT count(*) FROM intel.selection_postmortems WHERE roles && ARRAY['daily_pick','parlay_leg','llm','reviewed','rejected']")
    assert count(db, "SELECT count(*) FROM ai.memory_events WHERE kind = 'pick_postmortem'") == ai_studied, \
        "one memory event for each selection the AI studied, none for the ones only the decision layer judged"
    # the same morning again writes nothing
    again = learn(db, conn, at=MORNING + timedelta(minutes=5))
    assert (again.counts["pick_postmortems"], again.counts["postmortems"], again.counts["memory_events"]) == (0, 0, 0)
    assert count(db, "SELECT count(*) FROM intel.selection_postmortems") == studied


def test_the_switch_brings_the_two_first_post_mortems_back_after_the_one_and_nothing_is_remembered_twice(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    Pm(db, seed)
    conn = Savepoints(db)
    report = learn(db, conn, legacy_postmortems=True)
    assert report.status == "ok", report.errors
    assert count(db, "SELECT count(*) FROM ai.pick_postmortems") > 0 and count(db, "SELECT count(*) FROM ai.postmortems") > 0
    assert report.counts["legacy_pick_postmortems"] > 0 and report.counts["legacy_postmortems"] > 0
    studied = count(db, "SELECT count(*) FROM intel.selection_postmortems")
    assert report.counts["pick_postmortems"] == studied, "the one post-mortem ran first and studied everything"
    ai_studied = count(db, "SELECT count(*) FROM intel.selection_postmortems WHERE roles && ARRAY['daily_pick','parlay_leg','llm','reviewed','rejected']")
    assert count(db, "SELECT count(*) FROM ai.memory_events WHERE kind = 'pick_postmortem'") == ai_studied, \
        "the frozen writer found each selection already remembered"
    assert report.counts["pick_memory_events"] == ai_studied and count(db, "SELECT count(*) FROM ai.memory_events WHERE kind = 'pick_postmortem' "
                                                                           "AND version = 'pm-v6'") == ai_studied, "the one post-mortem owns them"
    again = learn(db, conn, at=MORNING + timedelta(minutes=5), legacy_postmortems=True)
    assert again.counts["legacy_pick_postmortems"] == 0 and again.counts["legacy_postmortems"] == 0


def test_a_post_mortem_that_fails_does_not_stop_what_the_rest_of_the_cycle_learns(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    Pm(db, seed)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the post-mortem is broken")
    monkeypatch.setattr("fbi.intel.postmortem.study", broken)
    report = learn(db, Savepoints(db))
    assert report.status == "partial" and any(e.startswith("postmortems: RuntimeError") for e in report.errors)
    assert "budget_alerts" in report.counts and "source_domains" in report.counts, "the notes, the patterns and the rest of the cycle ran"
    assert count(db, "SELECT count(*) FROM intel.selection_postmortems") == 0


def test_the_nightly_step_studies_what_the_cycle_left_and_finds_the_rest_done(db: psycopg.Connection[Any], seed: Seed) -> None:
    Pm(db, seed)
    conn = Savepoints(db)
    first = postmortems_step(conn, at=LATE)  # type: ignore[arg-type]
    assert first["selections"] > 0 and first["matches"] > 0 and first["errors"] == 0
    assert first["memory_events"] > 0
    assert postmortems_step(conn, at=LATE + timedelta(minutes=5))["selections"] == 0  # type: ignore[arg-type]
    # the learning cycle that comes after finds everything written
    report = learn(db, conn, at=LATE + timedelta(hours=1))
    assert (report.counts["pick_postmortems"], report.counts["postmortems"]) == (0, 0)
