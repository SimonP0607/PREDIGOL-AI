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

LABELS = ("GOOD", "NEUTRAL", "BAD")

pytestmark = pytest.mark.integration


def args(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(**({"apply": False, "days": 7, "chunk": 400, "max_seconds": None} | kw))


def count(db: psycopg.Connection[Any], sql: str) -> int:
    return int(scalar(db.execute(sql)))


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


def test_the_closes_measure_both_references_over_the_same_selections(db: psycopg.Connection[Any], seed: Seed,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    pm = Pm(db, seed)
    conn: Any = Savepoints(db)
    assert cli.closes_command(conn, args(days=15), now=LATE) == 0
    assert "nothing is written in that window" in capsys.readouterr().out, "before the post-mortems exist there is nothing to measure"

    # the world already has a consensus for five of the 26 selections (150, 175, 270, 390 and 510 minutes before kick-off) and the last price
    # of the bookmaker for one; here the same book's last price is added to four more, and a later consensus (60 minutes) to the 2.10 of F3
    pm.consensus("F3", "1X2", "Home", "0", "0.45", 60)
    pm.book_close("F2", pm.book, "1X2", "Away", "0", "3.50")  # 3.30 taken: -5.7 % against the book's own close, CLV -4.3 %: both BAD
    pm.book_close("F3", pm.book, "1X2", "Home", "0", "2.20")  # 2.10 taken: -4.5 %, CLV 2.10 x 0.45 - 1 = -5.5 %: both BAD
    pm.book_close("F4", pm.book, "1X2", "Home", "0", "2.39")  # 2.40 taken: +0.4 % (NEUTRAL) and CLV +3.2 % (GOOD)
    pm.book_close("F4", pm.book, "OU", "Over", "2.5", "1.90", minutes_to_ko=30)  # 1.95 taken: +2.6 % (GOOD) and CLV -2.5 % (BAD)
    cli.build_command(conn, args(apply=True), now=LATE)
    capsys.readouterr()
    assert cli.closes_command(conn, args(days=15), now=LATE) == 0
    said = capsys.readouterr().out
    lines = {ln.strip()[:2]: ln for ln in said.splitlines()}
    assert "the matches of the last 15 days (26 post-mortems)" in said
    assert "last-shin-consensus-before-kickoff" in lines["1."] and "5 (19.2 %)" in lines["1."]
    assert "p10 96, median 175, p90 414" in lines["1."] and "more than 120 minutes before it: 80.0 %" in lines["1."]
    assert "5 (19.2 %)" in lines["2."] and "p10 20, median 20, p90 26" in lines["2."]
    assert "both: 5 (19.2 %); only the first: 0; only the second: 0; neither: 21" in said
    assert "over the 5 that have both:" in said
    assert "mean CLV -2.0 %, mean price move +1.6 %: the gap, 3.6 points" in said and "correlation " in said
    assert "p10 0.90, median 0.99, p90 1.02; above 1.00 in 40.0 %" in said
    grid = [ln.split() for ln in said.splitlines() if ln.split()[:1] and ln.split()[0] in LABELS and ln.split()[1].isdigit()]
    assert grid == [["GOOD", "0", "1", "0"], ["NEUTRAL", "0", "0", "0"], ["BAD", "2", "0", "2"]], grid
    assert "the two labels agree in 40.0 %; where they differ (3), CLV says worse than the price move in 66.7 %" in said
    assert "they agree in 100.0 % of 1 when the consensus was captured at most 120 minutes before kick-off, in 25.0 % of 4 when" in said
    assert "that is the owner's decision" in said
    assert cli.build_parser().parse_args(["closes", "--days", "9"]).days == 9
