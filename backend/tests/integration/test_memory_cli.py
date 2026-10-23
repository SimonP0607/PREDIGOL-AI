"""``python -m scripts.memory`` (plan F8) on the world of ``test_intel_memory_v4``: a dry run writes nothing, ``--apply`` builds the lineage day by
day and a second one finds it built, ``status`` says whether the nightly step waits for the rebuild, ``coverage`` says day by day what each match
reports and what is written, ``audit`` adds the data up again from scratch and shows the series whose data changed after the memory booked them,
``priors`` measures how many matches a league's mean is worth for each figure."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from typing import Any

import psycopg
import pytest
from scripts import memory as cli

from fbi.intel import memory

from .conftest import Seed
from .helpers import scalar
from .test_ai_decision_layer import Savepoints
from .test_intel_memory_late import DAY, KICKOFF, _night
from .test_intel_memory_v4 import AFTER, League, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

NOW = _night(AFTER)  # 07:50 in Bogotá on the 7th: yesterday is the 6th


@pytest.fixture(autouse=True)
def lineage_from_the_world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory, "LINEAGE_START", DAY)


def args(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(**({"apply": False, "start": None, "end": None, "max_seconds": None, "days": 15, "sample": 100, "seed": 1} | kw))


def rows(db: psycopg.Connection[Any]) -> int:
    return int(scalar(db.execute("SELECT count(*) FROM intel.entity_memory WHERE version = %s", (memory.VERSION,))))


def test_a_dry_run_writes_nothing_and_an_apply_builds_the_lineage_once(db: psycopg.Connection[Any], world: League,  # noqa: F811
                                                                      capsys: pytest.CaptureFixture[str]) -> None:
    conn: Any = Savepoints(db)
    assert cli.rebuild_command(conn, args(), now=NOW) == 0
    said = capsys.readouterr().out
    assert "dry run (nothing is written)" in said and "that would be written" in said and "would grow by" in said and "re-run with --apply" in said
    assert f"from {DAY} to {AFTER}" in said
    conn.rollback()  # what main() does after a dry run
    assert rows(db) == 0

    assert cli.rebuild_command(conn, args(apply=True), now=NOW) == 0
    said = capsys.readouterr().out
    built = rows(db)
    assert built > 0 and f"{built:,} rows written" in said and "grew by" in said and f"{DAY}: " in said
    assert cli.rebuild_command(conn, args(apply=True), now=NOW) == 0
    again = capsys.readouterr().out
    assert "0 rows written" in again and rows(db) == built, "built once"


def test_a_range_and_a_budget_build_only_what_they_are_given(db: psycopg.Connection[Any], world: League,  # noqa: F811
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    conn: Any = Savepoints(db)
    assert cli.rebuild_command(conn, args(apply=True, start=DAY, end=DAY), now=NOW) == 0
    assert f"{DAY}:" in capsys.readouterr().out
    assert scalar(db.execute("SELECT max(as_of_day) FROM intel.entity_memory WHERE version = %s", (memory.VERSION,))) == DAY
    assert cli.rebuild_command(conn, args(start=AFTER, end=DAY), now=NOW) == 0
    assert "nothing to build" in capsys.readouterr().out


def test_the_status_says_the_nightly_step_waits_until_the_lineage_has_begun(db: psycopg.Connection[Any], world: League,  # noqa: F811
                                                                           capsys: pytest.CaptureFixture[str]) -> None:
    conn: Any = Savepoints(db)
    assert cli.status_command(conn, args(), now=NOW) == 0
    said = capsys.readouterr().out
    assert "writer: memory-v4" in said and "WAITING for the rebuild" in said and "no row of memory-v4 yet" in said
    cli.rebuild_command(conn, args(apply=True), now=NOW)
    capsys.readouterr()
    assert cli.status_command(conn, args(), now=NOW) == 0
    said = capsys.readouterr().out
    assert "memory-v4:" in said and "writing: the lineage has begun" in said and "WAITING" not in said
    assert "team x corners" in said and "competition x corners" in said and "market x decisions" not in said, "no decision in this world"
    assert "mean confidence" in said


def test_the_coverage_says_day_by_day_what_each_match_reports_and_what_is_written(db: psycopg.Connection[Any], world: League,  # noqa: F811
                                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    conn: Any = Savepoints(db)
    cli.rebuild_command(conn, args(apply=True), now=NOW)
    capsys.readouterr()
    assert cli.coverage_command(conn, args(days=10), now=NOW) == 0
    said = capsys.readouterr().out
    line = next(ln for ln in said.splitlines() if ln.startswith(str(DAY)))
    figures = line.replace("|", " ").split()
    # three matches that day: two with corners (and cards: both sides have a line), one with expected goals; none for the third
    assert figures[:5] == [str(DAY), "3", "2", "2", "1"], line
    assert figures[5:] == ["4", "4", "2"], "and the rows: two teams for each match that reports the figure"


def test_the_audit_adds_the_data_up_again_and_finds_the_series_whose_data_changed_after_they_were_booked(
        db: psycopg.Connection[Any], world: League, seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    conn: Any = Savepoints(db)
    cli.rebuild_command(conn, args(apply=True), now=NOW)
    capsys.readouterr()
    assert cli.audit_command(conn, args(), now=NOW) == 0
    said = capsys.readouterr().out
    assert "the stored state is what the data say:" in said and "different: 0" in said and "DIFFERENT" not in said

    # the provider corrects a figure after the memory booked it: a row is never rewritten, so the audit shows it
    db.execute("UPDATE core.fixture_team_stats SET corners = 9 WHERE fixture_id = %s AND team_side = 'home'", (world.m1,))  # type: ignore[attr-defined]
    assert cli.audit_command(conn, args(), now=NOW) == 1
    said = capsys.readouterr().out
    assert "DIFFERENT" in said and "corners" in said
    assert f"competition {seed.competition_id} corners" in said and f"team {world.team('Alpha')} corners" in said


def test_the_audit_of_a_memory_with_no_rows_says_so(db: psycopg.Connection[Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.audit_command(Savepoints(db), args(), now=NOW) == 0  # type: ignore[arg-type]
    assert "no row of memory-v4 yet" in capsys.readouterr().out
    parsed = cli.build_parser().parse_args(["rebuild", "--from", "2026-10-13", "--to", "2026-10-20", "--max-seconds", "60"])
    assert (parsed.start, parsed.end, parsed.max_seconds, parsed.apply) == (date(2026, 10, 13), date(2026, 10, 20), 60.0, False)


def test_the_priors_measure_what_a_figure_varies_by_inside_a_team_and_between_the_teams_of_a_competition(
        db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    league = League(db, seed)
    names = ["Ana", "Bea", "Cris", "Dan", "Eva", "Fer"]
    own: dict[str, dict[int, list[float]]] = {"corners": {}, "cards": {}, "xg": {}}
    opp: dict[str, dict[int, list[float]]] = {"corners": {}, "cards": {}, "xg": {}}
    n = 0
    for _ in range(2):                              # a double round-robin: every team plays twenty matches
        for home in names:
            for away in names:
                if home == away:
                    continue
                n += 1
                h = {"corners": 4 + names.index(home) + n % 4, "yellow": 1 + n % 3, "red": 1 if n % 11 == 0 else 0,
                     "xg": round(0.8 + 0.1 * names.index(home) + (n % 5) / 10, 2)}
                a = {"corners": 3 + names.index(away) + (n * 7) % 5, "yellow": (n * 5) % 4, "red": 0,
                     "xg": round(0.6 + 0.1 * names.index(away) + (n % 3) / 10, 2)}
                league.both(league.match(home, away, KICKOFF + timedelta(minutes=n)), h, a)
                pairs = {"corners": (h["corners"], a["corners"]), "cards": (h["yellow"] + h["red"], a["yellow"] + a["red"]),
                         "xg": (h["xg"], a["xg"])}
                for figure, (ph, pa) in pairs.items():
                    for team, mine, theirs in ((league.team(home), ph, pa), (league.team(away), pa, ph)):
                        own[figure].setdefault(team, []).append(float(mine))
                        opp[figure].setdefault(team, []).append(float(theirs))
    assert cli.priors_command(Savepoints(db), args(days=400, min_matches=5, min_teams=6), now=NOW) == 0  # type: ignore[arg-type]
    said = capsys.readouterr().out
    assert "finished matches between" in said and "at least 5 matches that report the figure" in said and "at least 6 such teams" in said
    for figure in ("corners", "cards", "xg"):
        produced = memory.variance_components({seed.competition_id: own[figure]}, min_matches=5, min_teams=6)
        conceded = memory.variance_components({seed.competition_id: opp[figure]}, min_matches=5, min_teams=6)
        assert produced is not None and conceded is not None
        line = next(ln for ln in said.splitlines() if ln.strip().startswith(figure + " "))
        cells = line.replace("|", " ").split()
        assert cells[:4] == [figure, "1", "6", "120"], line
        assert float(cells[4]) == pytest.approx(produced.within ** 0.5, abs=0.006)
        assert float(cells[5]) == pytest.approx(max(produced.between, 0) ** 0.5, abs=0.006)
        assert cells[6:9] == [cli._m(produced.prior_weight), cli._m(conceded.prior_weight), f"{memory.METRICS[figure].prior_weight:.1f}"], line
    assert "a weight changes with a new version of the memory" in said


def test_the_priors_of_a_database_with_nothing_to_measure_say_so(db: psycopg.Connection[Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.priors_command(Savepoints(db), args(days=400, min_matches=5, min_teams=8), now=NOW) == 0  # type: ignore[arg-type]
    said = capsys.readouterr().out
    assert said.count("not enough matches that report it") == 3 and "0 finished matches" in said
    parsed = cli.build_parser().parse_args(["priors", "--days", "200", "--min-matches", "3", "--min-teams", "4"])
    assert (parsed.command, parsed.days, parsed.min_matches, parsed.min_teams) == ("priors", 200, 3, 4)
    assert cli.build_parser().parse_args(["priors"]).days == 365
