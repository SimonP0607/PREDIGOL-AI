"""Rest and congestion from the whole calendar, over a database (plan F4.4): the sample the experiment runs on, the coverage report, the export and
the test's record. The calendar is read, never written; the transaction is rolled back afterwards.

The world: a finished match between two teams. The home side played a cup tie two days before it - a competition PrediGol does not follow - after a
league match eight days before; the away side's last match was a league match seven days before. Production counted eight days of rest for the home
side; the calendar says two."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from scripts import calendar_features as cli

from fbi.features.engine import FEATURE_VERSION
from fbi.features.store import ensure_registry
from fbi.research import rest_ab
from tests.integration.calendar_helpers import (
    AT,
    FRESH,
    KICKOFF,
    World,
    cup_tie,
    own_followed,
    read,
    read_both,
    world,
)
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

pytestmark = pytest.mark.integration

SINCE = KICKOFF - timedelta(hours=1)
UNTIL = KICKOFF + timedelta(hours=1)
LATER = KICKOFF + timedelta(days=2)
"""When the experiment runs: after the match, so a list read the day after it shows how that stretch of the season ended."""


def played(db: psycopg.Connection[Any], w: World, *, home_rest: float = 8.0, away_rest: float = 7.0) -> World:
    """The match of the world, finished 2-1, with the feature set production stored for it."""
    db.execute("UPDATE core.fixtures SET status_group = 'finished' WHERE id = %s", (w.fixture_id,))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 1)", (w.fixture_id,))
    ensure_registry(db)
    stored = scalar(db.execute(
        "INSERT INTO features.feature_sets (fixture_id, feature_version, data_cutoff, code_version, input_hash, n_inputs) "
        "VALUES (%s, %s, %s, 'test', 'h', 1) RETURNING id", (w.fixture_id, FEATURE_VERSION, KICKOFF - timedelta(hours=1))))
    for name, value in (("elo_diff", 35.0), ("home_rest_days", home_rest), ("away_rest_days", away_rest)):
        db.execute("INSERT INTO features.fixture_features (feature_set_id, name, value) VALUES (%s, %s, %s)", (stored, name, value))
    return w


def list_both(db: psycopg.Connection[Any], seed: Seed, w: World) -> None:
    """Each team's list read the day after the match."""
    after = KICKOFF + timedelta(days=1)
    read(db, seed, w.home, [own_followed(w, "home", 8.0), cup_tie(w, "home", days_before=2.0)], after)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], after)


# ── the sample ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_real_rest_of_a_finished_match_is_what_the_cup_tie_leaves_not_what_the_league_alone_says(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = played(db, world(db, home_last=8.0, away_last=7.0))
    list_both(db, seed, w)
    sample = cli.build_sample(db, since=SINCE, until=UNTIL, at=LATER)

    assert (sample.finished, sample.with_features, len(sample.observations)) == (1, 1, 1)
    (o,) = sample.observations
    assert o.fixture_id == w.fixture_id and o.outcome == 0 and o.kickoff_at == KICKOFF
    assert (o.home.rest_days, o.home.rest_days_tracked, o.home.rest_days_outside) == (2.0, 8.0, 2.0)
    assert (o.home.played_14d, o.home.outside_14d, o.home.played_7d) == (2, 1, 1)
    assert (o.away.rest_days, o.away.rest_days_tracked, o.away.rest_days_outside) == (7.0, 7.0, None)
    assert o.home.whole and o.away.whole
    assert o.values["home_rest_days"] == 8.0 and o.values["away_rest_days"] == 7.0, "what production read, as stored"
    assert rest_ab.true_rest_diff(o) == -5.0, "2 days against 7, where production's own difference was +1"
    assert not sample.reasons

    d = rest_ab.describe(sample.observations)
    assert d["share_rest_shorter_by_1d_or_more"] == 0.5 and d["max_days_shorter"] == 6.0


def test_a_side_whose_list_was_not_read_after_the_match_keeps_the_match_out_of_the_sample_and_is_counted(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = played(db, world(db, home_last=8.0, away_last=7.0))
    after = KICKOFF + timedelta(days=1)
    read(db, seed, w.home, [own_followed(w, "home", 8.0), cup_tie(w, "home", days_before=2.0)], after)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], KICKOFF - timedelta(days=3))  # read before the match
    sample = cli.build_sample(db, since=SINCE, until=UNTIL, at=LATER)
    assert sample.observations == [] and sample.reasons == {"not_read_after_the_match": 1}
    assert sample.with_features == 1

    lines = "\n".join(cli.sample_lines(sample))
    assert "both calendars whole (the sample of the test)       0" in lines and "not_read_after_the_match 1" in lines
    assert "Nothing to describe yet" in lines


def test_a_match_without_the_features_production_read_is_not_in_the_sample(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    db.execute("UPDATE core.fixtures SET status_group = 'finished' WHERE id = %s", (w.fixture_id,))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 0, 0)", (w.fixture_id,))
    list_both(db, seed, w)
    sample = cli.build_sample(db, since=SINCE, until=UNTIL, at=LATER)
    assert (sample.finished, sample.with_features, sample.observations) == (1, 0, [])


def test_the_sample_is_the_window_asked_for(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = played(db, world(db, home_last=8.0, away_last=7.0))
    list_both(db, seed, w)
    assert cli.build_sample(db, since=UNTIL, until=UNTIL + timedelta(days=1), at=LATER).finished == 0
    assert cli.build_sample(db, since=SINCE - timedelta(days=30), until=SINCE, at=LATER).observations == []


# ── the export ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_export_is_one_row_per_match_with_the_rest_as_production_counted_it_and_as_it_was(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = played(db, world(db, home_last=8.0, away_last=7.0))
    list_both(db, seed, w)
    sample = cli.build_sample(db, since=SINCE, until=UNTIL, at=LATER)
    out = io.StringIO()
    assert cli.write_csv(sample.observations, out) == 1
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert list(rows[0]) == list(cli.COLUMNS) and len(rows) == 1
    row = rows[0]
    assert row["fixture_id"] == str(w.fixture_id) and row["outcome"] == "0"
    assert (row["production_home_rest"], row["production_away_rest"]) == ("8.0", "7.0")
    assert (row["home_rest_days"], row["home_rest_tracked"], row["home_rest_outside"]) == ("2.0", "8.0", "2.0")
    assert (row["away_rest_days"], row["away_rest_outside"]) == ("7.0", "")
    assert (row["home_played_14d"], row["home_outside_14d"], row["away_outside_14d"]) == ("2", "1", "0")
    assert row["true_rest_diff"] == "-5.0"


# ── the coverage ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_coverage_says_how_many_of_next_weeks_matches_have_a_calendar_that_is_whole_on_both_sides(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    assert cli.upcoming_lines(db, days=7, at=AT)[:4] == [
        "Matches in the next 7 days: 1", "  both calendars whole       1  (100.0%)", "  one side whole             0  (0.0%)",
        "  neither whole              0  (0.0%)"]

    second = world(db, home_last=9.0, away_last=6.0)
    read(db, seed, second.away, [own_followed(second, "away", 6.0)], FRESH)  # only the away side of the second match was read
    lines = cli.upcoming_lines(db, days=7, at=AT)
    assert lines[0] == "Matches in the next 7 days: 2" and "  both calendars whole       1  (50.0%)" in lines
    assert "  one side whole             1  (50.0%)" in lines
    assert lines[-1] == "  why a side is not whole: never_fetched 1"
    assert cli.upcoming_lines(db, days=0, at=AT)[0] == "Matches in the next 0 days: 0"


# ── the test ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_sample_this_small_is_inconclusive_and_the_record_says_what_it_stood_on(
        db: psycopg.Connection[Any], seed: Seed, tmp_path: Path) -> None:
    w = played(db, world(db, home_last=8.0, away_last=7.0))
    list_both(db, seed, w)
    out = tmp_path / "rest.json"
    code, lines = cli.compare_command(db, since=SINCE, until=UNTIL, at=LATER, out=out)
    text = "\n".join(lines)
    assert code == 0
    assert "protocol rest-ab-v1, definitions rest-v1" in text and "VERDICT: INCONCLUSIVE" in text
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["verdict"] == "inconclusive" and record["n_sample"] == 1 and record["n_tested"] == 0
    assert record["coverage"] == {"finished": 1, "with_features": 1, "why_a_side_is_not_whole": {}}
    assert record["window"]["since"] == SINCE.isoformat() and record["protocol"]["protocol"] == "rest-ab-v1"


def test_the_command_reads_and_never_writes(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = played(db, world(db, home_last=8.0, away_last=7.0))
    list_both(db, seed, w)
    tables = ("core.fixtures", "core.fixture_results", "core.calendar_matches", "core.calendar_fetches", "features.feature_sets")
    before = {t: scalar(db.execute(f"SELECT count(*) FROM {t}")) for t in tables}
    cli.coverage_command(db, days=7, since=SINCE, until=UNTIL, at=LATER)
    cli.compare_command(db, since=SINCE, until=UNTIL, at=LATER, out=None)
    assert {t: scalar(db.execute(f"SELECT count(*) FROM {t}")) for t in tables} == before


def test_the_command_line_runs_against_the_database_it_is_given(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["coverage", "--days", "1"]) == 0
    printed = capsys.readouterr().out
    assert "Matches in the next 1 days:" in printed and "definitions rest-v1, protocol rest-ab-v1" in printed
    assert cli.main(["export"]) == 2, "an export needs a first day"
