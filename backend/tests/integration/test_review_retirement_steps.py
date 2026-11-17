"""The steps of the retirement of ``review-v2`` (IA-125, AD-D11) through the real analysis cycle, with the scripted model of
``test_ai_decision_layer``: ``on`` (the default) is today's path, ``off`` asks no model review and keeps the rules' alone, ``sample`` asks it
only for the selections of the control, and going back to ``on`` asks it again. Nothing is retired here: the steps are the owner's."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import psycopg
import pytest

from fbi.ai import review_retirement as rr

from .conftest import Seed
from .test_ai_decision_layer import SHADOW, Savepoints, count, cycle, fake, reviews_asked
from .test_daily_records import World

pytestmark = pytest.mark.integration


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Iterator[World]:
    yield World(db, seed)


def engines(db: psycopg.Connection[Any], fixture: int) -> list[str]:
    return sorted({str(r[0]) for r in db.execute("SELECT engine FROM ai.pick_reviews WHERE fixture_id = %s", (fixture,)).fetchall()})


def test_off_keeps_the_rules_alone_and_asks_no_model(db: psycopg.Connection[Any], world: Any) -> None:
    fixture = world.fixtures["F1"]
    conn = Savepoints(db)
    off = fake("REJECT")
    report = cycle(conn, provider=off, only=[fixture], settings=replace(SHADOW, review_v2="off"))
    assert reviews_asked(off) == [] and report.counts["llm_reviews"] == 0, "off: no model review is asked"
    assert engines(db, fixture) == ["combined", "rules"]
    assert count(db, "SELECT count(*) FROM ai.usage WHERE purpose = 'pick_review'") == 0


@pytest.mark.parametrize("step", ["on", "no_opus"])
def test_on_and_the_first_step_keep_the_model_review(db: psycopg.Connection[Any], world: Any, step: str) -> None:
    """``on`` is the path of ``test_ai_decision_layer`` exactly (the setting's default); ``no_opus`` only takes the strong model away."""
    fixture = world.fixtures["F1"]
    conn = Savepoints(db)
    model = fake("REJECT")
    report = cycle(conn, provider=model, only=[fixture], settings=replace(SHADOW, review_v2=step))
    assert len(reviews_asked(model)) == 1 and report.counts["llm_reviews"] == 1
    assert engines(db, fixture) == ["combined", "llm", "rules"]
    assert db.execute("SELECT decision FROM ai.pick_reviews WHERE fixture_id = %s AND engine = 'combined'", (fixture,)).fetchone() == ("REJECT",)


def test_sample_asks_the_model_only_for_the_control(db: psycopg.Connection[Any], world: Any) -> None:
    fixture = world.fixtures["F1"]
    conn = Savepoints(db)
    model = fake("APPROVE")
    cycle(conn, provider=model, only=[fixture], settings=replace(SHADOW, review_v2="sample"))
    reviewed = db.execute("SELECT DISTINCT market_key, selection, line FROM ai.pick_reviews WHERE fixture_id = %s AND engine = 'rules'",
                          (fixture,)).fetchall()
    assert reviewed, "the rules review every selection in every step"
    expected = sum(rr.in_sample(fixture, str(m), str(s), line) for m, s, line in reviewed)
    assert len(reviews_asked(model)) == expected, (expected, len(reviews_asked(model)))
