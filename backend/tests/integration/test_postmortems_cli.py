"""``python -m scripts.postmortems`` (plan F8) on the world of ``test_postmortem_v6``: a dry run writes nothing, ``--apply`` writes the post-mortem
of every selection and every match and a second one writes nothing, ``status`` says what is written and how often the parts of PrediGol
priced the same selection differently, ``coverage`` says day by day what is written and what waits."""

from __future__ import annotations

import argparse
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest
from scripts import postmortems as cli

from .conftest import Seed
from .helpers import scalar
from .test_ai_decision_layer import Savepoints
from .test_postmortem_v6 import LATE, Pm

pytestmark = pytest.mark.integration


def args(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(**({"apply": False, "days": 7, "chunk": 400, "max_seconds": None} | kw))


def count(db: psycopg.Connection[Any], sql: str) -> int:
    return int(scalar(db.execute(sql)))  # type: ignore[arg-type]


def test_a_dry_run_writes_nothing_and_an_apply_writes_once(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    Pm(db, seed)
    conn: Any = Savepoints(db)
    assert cli.build_command(conn, args(), now=LATE) == 0
    said = capsys.readouterr().out
    assert "dry run (nothing is written)" in said and "that would be written" in said and "re-run with --apply" in said
    conn.rollback()  # what main() does after a dry run
    assert count(db, "SELECT count(*) FROM intel.postmortems WHERE market_key IS NOT NULL") == 0
    assert count(db, "SELECT count(*) FROM intel.match_postmortems") == 0 and count(db, "SELECT count(*) FROM ai.memory_events") == 0

    assert cli.build_command(conn, args(apply=True), now=LATE) == 0
    said = capsys.readouterr().out
    written = count(db, "SELECT count(*) FROM intel.postmortems WHERE market_key IS NOT NULL")
    assert written > 0 and f"{written:,} written" in said and "classes of the losses" in said
    assert count(db, "SELECT count(*) FROM intel.match_postmortems") > 0

    assert cli.build_command(conn, args(apply=True), now=LATE) == 0
    again = capsys.readouterr().out
    assert "0 written" in again and "matches as a whole: 0 written" in again
    assert count(db, "SELECT count(*) FROM intel.postmortems WHERE market_key IS NOT NULL") == written


def test_a_chunk_smaller_than_the_backlog_is_looped_until_nothing_is_left(db: psycopg.Connection[Any], seed: Seed,
                                                                         capsys: pytest.CaptureFixture[str]) -> None:
    Pm(db, seed)
    conn: Any = Savepoints(db)
    assert cli.build_command(conn, args(apply=True, chunk=5), now=LATE) == 0
    said = capsys.readouterr().out
    assert "round 2:" in said and "0 left" in said
    full = count(db, "SELECT count(*) FROM intel.postmortems WHERE market_key IS NOT NULL")
    assert full > 5


def test_the_status_and_the_coverage_say_what_is_written_and_what_waits(db: psycopg.Connection[Any], seed: Seed,
                                                                       capsys: pytest.CaptureFixture[str]) -> None:
    pm = Pm(db, seed)
    conn: Any = Savepoints(db)
    cli.build_command(conn, args(apply=True), now=LATE)
    capsys.readouterr()
    assert cli.status_command(conn, args(), now=LATE) == 0
    said = capsys.readouterr().out
    assert "writer: pm-v6" in said and "pm-v6:" in said and "who looked at them:" in said and "the price taken came from:" in said
    assert "the same selection priced by" in said and "item / review" in said, "the three prices of scenario A are compared in pairs"
    assert "0 waiting" in said
    assert cli.coverage_command(conn, args(days=15), now=LATE) == 0
    table = capsys.readouterr().out
    assert "written" in table and "100.0 % written" in table
    day = pm.kickoff("F1").astimezone(ZoneInfo("America/Bogota")).date().isoformat()
    assert day in table
