"""``python -m scripts.competition_stages``: what a person sees and what the exit code says (plan F2).

The commands are run with the test's own connection (``commit=False``: the build must not end the test's transaction)."""

from __future__ import annotations

import re
from typing import Any

import psycopg
import pytest
from scripts import competition_stages as cli

from tests.integration.conftest import Seed
from tests.integration.test_competition_builder import NOW, World, champions_league, make_world

pytestmark = pytest.mark.integration


def run_build(db: psycopg.Connection[Any], *argv: str) -> int:
    return cli.build_command(db, cli.build_parser().parse_args(["build", *argv]), now=NOW, commit=False)


def run_audit(db: psycopg.Connection[Any], *argv: str) -> int:
    return cli.audit_command(db, cli.build_parser().parse_args(["audit", *argv]), now=NOW)


def run_show(db: psycopg.Connection[Any], *argv: str) -> int:
    return cli.show_command(db, cli.build_parser().parse_args(["show", *argv]))


def tracked(w: World) -> World:
    w.db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (w.competition,))
    return w


def test_build_is_a_dry_run_until_apply_and_says_so(db: psycopg.Connection[Any], seed: Seed,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    w = make_world(db, seed, 99901)
    champions_league(w)

    assert run_build(db, "--season", str(w.season)) == 0
    said = capsys.readouterr().out
    assert "dry run (nothing is written): 1 seasons to read" in said
    assert "1 changed (1 for the first time)" in said and "re-run with --apply to write it" in said
    assert "stages 5 and ties 4" in said and "ties by status: decided 4" in said
    assert w.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = %s", w.season) == 0

    assert run_build(db, "--season", str(w.season), "--apply") == 0
    said = capsys.readouterr().out
    assert said.startswith("APPLY: 1 seasons to read") and "rows written: 9" in said and "re-run" not in said
    assert w.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = %s", w.season) == 5

    assert run_build(db, "--season", str(w.season), "--apply") == 0
    assert "0 changed (0 for the first time), 1 left as they were" in capsys.readouterr().out
    assert run_build(db, "--season", str(w.season), "--apply", "--force") == 0
    assert "1 changed (0 for the first time)" in capsys.readouterr().out


def test_build_picks_its_seasons_by_league_year_or_what_is_pending(db: psycopg.Connection[Any], seed: Seed,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    w = make_world(db, seed, 99902)
    champions_league(w)
    older = w.another_season(2024)
    champions_league(w, season=older, shift=-365)
    parse = cli.build_parser().parse_args

    both = cli.select_seasons(db, parse(["build", "--league", "99902"]), now=NOW)
    assert both == sorted([w.season, older])
    assert cli.select_seasons(db, parse(["build", "--league", "99902", "--year", "2024"]), now=NOW) == [older]
    assert cli.select_seasons(db, parse(["build", "--season", str(older), "--season", str(older)]), now=NOW) == [older]
    assert {w.season, older} <= set(cli.select_seasons(db, parse(["build"]), now=NOW)), "never built is pending"
    assert {w.season, older} <= set(cli.select_seasons(db, parse(["build", "--all"]), now=NOW))

    assert run_build(db, "--league", "99902", "--limit", "1", "--apply") == 0
    assert "1 seasons to read" in capsys.readouterr().out
    assert w.one("SELECT count(*) FROM core.competition_stages WHERE competition_season_id = ANY(%s)",
                 [w.season, older]) == 5, "--limit stopped after one season"


def test_a_build_that_fails_says_which_season_and_exits_1(db: psycopg.Connection[Any], seed: Seed,
                                                           monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    w = make_world(db, seed, 99903)
    champions_league(w)

    def refusing(*_: Any, **__: Any) -> Any:
        raise ValueError("a defect in the rules")

    monkeypatch.setattr("fbi.competitions.seasons.build_season", refusing)

    assert run_build(db, "--season", str(w.season), "--apply") == 1
    said = capsys.readouterr().out
    assert f"FAILED season {w.season}: a defect in the rules" in said and "1 failed" in said


def test_audit_passes_on_a_built_season_and_prints_a_sample_that_can_be_checked(db: psycopg.Connection[Any], seed: Seed,
                                                                               capsys: pytest.CaptureFixture[str]) -> None:
    w = tracked(make_world(db, seed, 99904))
    champions_league(w)
    run_build(db, "--season", str(w.season), "--apply")
    capsys.readouterr()

    assert run_audit(db, "--sample", "5", "--seed", "x") == 0
    said = capsys.readouterr().out

    assert "all criteria pass" in said
    assert "fixtures 9 · with a stage 9 (100.00%)" in said and "PASS  at least 98% of the fixtures have a stage" in said
    assert "ties checked 4 · different from the stored aggregate 0" in said
    assert "decided by: aggregate 3 · penalties 1" in said and "status: decided 4" in said
    assert "-- a sample of 3 decided two-legged ties (seed x" in said
    assert "legs add up to 1-0: OK" in said and "legs add up to 3-1: OK" in said and "legs add up to 2-1: OK" in said
    assert "PASS  the legs of every sampled tie add up to its aggregate" in said
    assert "Round of 16" in said and "Team 99904-1 1-0 Team 99904-4" in said

    run_audit(db, "--sample", "5", "--seed", "x")
    assert capsys.readouterr().out.split("-- a sample")[1] == said.split("-- a sample")[1], "the same seed, the same sample"


def test_audit_fails_when_a_tracked_season_has_no_stages(db: psycopg.Connection[Any], seed: Seed,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    w = tracked(make_world(db, seed, 99905))
    champions_league(w)

    assert run_audit(db, "--sample", "0") == 1
    said = capsys.readouterr().out

    assert "FAIL  at least 98% of the fixtures have a stage" in said and "FAILED: coverage" in said
    assert "Competition 99905 (99905) 2025: 9" in said, "the seasons that lack stages are named"
    run_build(db, "--season", str(w.season), "--apply")
    capsys.readouterr()
    assert run_audit(db, "--sample", "0") == 0
    assert "all criteria pass" in capsys.readouterr().out
    assert run_audit(db, "--sample", "0", "--all-competitions") == 1, "the seed's own fixture has no stage"
    assert "FAILED: coverage" in capsys.readouterr().out


def test_audit_catches_an_aggregate_that_is_not_the_sum_of_its_legs(db: psycopg.Connection[Any], seed: Seed,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    w = tracked(make_world(db, seed, 99906))
    f = champions_league(w)
    run_build(db, "--season", str(w.season), "--apply")
    tie = w.tie_ids()["Round of 16"]
    capsys.readouterr()

    db.execute("UPDATE core.ties SET aggregate_a = 9 WHERE id = %s", (tie,))  # a stored aggregate the builder got wrong
    assert run_audit(db, "--sample", "20") == 1
    said = capsys.readouterr().out
    assert "different from the stored aggregate 1" in said and "FAIL  every stored aggregate is the sum of its legs" in said
    assert f"tie {tie} (different): stored 9-0, legs 1-0" in said
    assert "legs add up to 1-0: DIFFERENT from the stored aggregate" in said
    assert "FAILED: aggregates, sample" in said

    db.execute("UPDATE core.ties SET aggregate_a = 1 WHERE id = %s", (tie,))
    w.set_goals(f["r1"], 4, 0)  # a result corrected after the build: the audit sees the tie is stale
    assert run_audit(db, "--sample", "0") == 1
    assert "different from the stored aggregate 1" in capsys.readouterr().out


def test_audit_lists_the_ties_the_next_round_contradicts_and_counts_the_drift(db: psycopg.Connection[Any], seed: Seed,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    w = tracked(make_world(db, seed, 99907))
    f = champions_league(w)
    w.set_goals(f["r2"], 2, 0)  # team 4 wins the tie on the pitch, team 1 plays the quarter-finals
    run_build(db, "--season", str(w.season), "--apply")
    capsys.readouterr()

    assert run_audit(db, "--sample", "0", "--drift") == 0, "a contradicted tie is reported, not a failure of the build"
    said = capsys.readouterr().out

    assert "-- ties the next round contradicts: 1" in said
    assert "Round of 16 · Team 99907-1 v Team 99907-4 · two_legged decided · aggregate 1-2 · winner Team 99907-4" in said
    assert "next round: contradicted" in said
    first = re.search(r"-- drift: (\d+) of (\d+) seasons would change if they were built now", said)
    assert first is not None, "the drift line is printed"

    w.set_goals(f["r2"], 0, 0)  # a correction since the build: this season now differs from what is stored
    run_audit(db, "--sample", "0", "--drift")
    second = re.search(r"-- drift: (\d+) of (\d+) seasons would change", capsys.readouterr().out)
    assert second is not None
    assert (int(second.group(1)) - int(first.group(1)), second.group(2)) == (1, first.group(2))


def test_show_prints_the_stages_ties_and_legs_of_a_season_and_marks_a_fixture(db: psycopg.Connection[Any], seed: Seed,
                                                                             capsys: pytest.CaptureFixture[str]) -> None:
    w = make_world(db, seed, 99908)
    f = champions_league(w)

    assert run_show(db, "--season", str(w.season)) == 0
    assert "not built yet" in capsys.readouterr().out
    run_build(db, "--season", str(w.season), "--apply")
    capsys.readouterr()

    assert run_show(db, "--fixture", str(f["r2"])) == 0
    said = capsys.readouterr().out

    assert said.startswith(f"Competition 99908 (-) · league 99908 · season 2025 · id {w.season}")
    for stage in ("3rd Qualifying Round", "Group Stage", "Round of 16", "Quarter-finals", "Final"):
        assert stage in said
    assert "4. Quarter-finals · knockout/knockout · rule knockout_word · quarter_final (8 teams) · 2 fixtures" in said
    assert "ties two_legged" in said and "Group Stage · league/group · rule league_format · 2 fixtures" in said
    assert "tie " in said and "Team 99908-1 v Team 99908-7 · single decided · aggregate 1-1 · winner Team 99908-1 (penalties, shoot-out 4-3)" in said
    assert f">>  leg 2 · 2025-11-16 · Team 99908-4 0-0 Team 99908-1 · FT · fixture {f['r2']}" in said, "the fixture asked for is marked"
    assert ">>  leg 1" not in said
    assert "built 2026-10-22 12:00 UTC by stages-1 / ties-2" in said

    assert run_show(db, "--season", "999999999") == 1
    assert run_show(db, "--fixture", "999999999") == 1
    assert "not found" in capsys.readouterr().out


def test_the_parser_refuses_what_makes_no_sense() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["build", "--all", "--season", "1"])  # one way of choosing the seasons
    with pytest.raises(SystemExit):
        parser.parse_args(["show"])  # which season?
    with pytest.raises(SystemExit):
        parser.parse_args([])
