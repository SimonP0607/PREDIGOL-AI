"""Plan F10 - the command line of the families: the history in a file, the measures a family can be trained on, and an evaluation that reads."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pytest
from scripts import families as cli

from fbi.core.clock import now as clock_now
from fbi.families import dependence, evaluate, score
from fbi.families.fit import Match
from fbi.familydecisions import decide as family_decide

from .test_families_dependence import synthetic
from .test_familydecisions_preview import decided

N = 12


def simulated(days_back: int, seed: int = 5) -> dict[int, list[Match]]:
    """Six seasons of a twelve-team league whose last match was a day ago; the corners are negative binomial and the strengths are real."""
    rng = np.random.default_rng(seed)
    attack, defence = rng.normal(0.0, 0.18, N), rng.normal(0.0, 0.18, N)
    r = 1.0 / 0.15
    start = clock_now() - timedelta(days=days_back)
    out: list[Match] = []
    fid = day = 0
    for _ in range(6):
        for h in range(N):
            for a in range(N):
                if h != a:
                    fid += 1
                    day += 1
                    mh, ma = float(np.exp(1.6 + 0.12 + attack[h] - defence[a])), float(np.exp(1.6 + attack[a] - defence[h]))
                    out.append(Match(fid, start + timedelta(days=day), h + 1, a + 1, int(rng.negative_binomial(r, r / (r + mh))),
                                     int(rng.negative_binomial(r, r / (r + ma)))))
    return {7: out}


def test_the_history_goes_to_a_file_and_comes_back_the_same(tmp_path: Path) -> None:
    data = simulated(900)
    for name in ("history.csv", "history.csv.gz"):
        path = tmp_path / name
        assert cli.write_csv(path, data) == len(data[7])
        assert cli.read_csv(path) == data


def test_the_measures_listed_are_the_pairs_of_counts_that_a_rule_grades(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["measures"]) == 0
    out = capsys.readouterr().out
    for measure in ("corners_ft", "goals_1h", "cards_lines_ft", "yellow_ft"):
        assert measure in out
    for not_a_pair in ("goals_halves", "corners_1h"):
        assert not_a_pair not in out


def test_a_measure_a_family_cannot_be_trained_on_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    from fbi.families.history import UnknownMeasureError

    with pytest.raises(UnknownMeasureError):
        cli.main(["evaluate", "--measure", "corners_1h", "--csv", str(tmp_path / "nothing.csv")])


def test_an_evaluation_from_a_file_reports_what_the_family_learnt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "corners.csv.gz"
    cli.write_csv(path, simulated(800))
    assert cli.main(["evaluate", "--measure", "corners_ft", "--csv", str(path), "--months", "12", "--json", "--xi", "0", "--penalty", "1",
                     "--lines", "9.5", "--side-lines", "4.5"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["n"] > 200 and s["measure"] == "corners_ft"
    assert set(s["side_lines"]) == {"home 4.5", "away 4.5"} and s["result"]["log_score_gain"] is not None
    assert s["side_lines"]["home 4.5"]["log_loss_gain"] > 0.0, "teams that differ: the model knows more about one side than the average does"
    assert s["log_score_gain_per_match"]["total"]["mean"] > 0.0
    assert "9.5" in s["lines"] and s["by_competition"][0]["competition_id"] == 7
    assert s["window"]["start"] < s["window"]["end"]


def test_the_text_report_reads(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "c.csv"
    cli.write_csv(path, simulated(800))
    assert cli.main(["evaluate", "--measure", "corners_ft", "--csv", str(path), "--months", "12", "--xi", "0", "--penalty", "1"]) == 0
    out = capsys.readouterr().out
    assert "log-score gain over the baseline" in out and "reliability of over" in out and "by competition" in out
    assert "who has more" in out and "home 4.5" in out, "the usual lines of one side are graded by default"


def test_the_time_decay_and_the_penalty_are_chosen_before_the_test_window() -> None:
    data = simulated(800)
    matches = data[7]
    start = matches[len(matches) // 2].kickoff_at
    xi, penalty, grid = evaluate.tune(data, measure="corners_ft", start=start, days=200, xis=(0.0, 0.004), penalties=(1.0, 8.0))
    assert (xi, penalty) in {(0.0, 1.0), (0.0, 8.0), (0.004, 1.0), (0.004, 8.0)} and len(grid) == 4
    assert grid[f"xi={xi},penalty={penalty}"] == max(grid.values())
    # nothing from the test window decides the choice: matches after `start` can be changed without changing it
    future = [Match(m.fixture_id, m.kickoff_at, m.home_id, m.away_id, 99, 0) if m.kickoff_at >= start else m for m in matches]
    assert evaluate.tune({7: future}, measure="corners_ft", start=start, days=200, xis=(0.0, 0.004), penalties=(1.0, 8.0))[:2] == (xi, penalty)


def test_the_halves_command_grades_the_bets_of_the_halves_from_two_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Two exports (the first and the second half), the same matches: the command joins them, derives the bets of the halves and grades them."""
    first, second = tmp_path / "goals_1h.csv.gz", tmp_path / "goals_2h.csv.gz"
    cli.write_csv(first, simulated(800, seed=5))
    cli.write_csv(second, simulated(800, seed=6))
    argv = ["halves", "--csv-1h", str(first), "--csv-2h", str(second), "--months", "12", "--xi", "0", "--penalty", "1"]
    assert cli.main([*argv, "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["n"] > 200 and r["window"]["start"] < r["window"]["end"]
    assert {"result_1h", "result_2h", "highest_half", "htft", "btts_1h", "btts_2h", "ou_1h_0.5", "odd_2h"} <= set(r["markets"])
    assert len(r["htft_calibration"]) == 9 and r["halves_residual_correlation"]["se"] > 0
    assert r["params"] == {"goals_1h": {"xi": 0.0, "penalty": 1.0}, "goals_2h": {"xi": 0.0, "penalty": 1.0}}, "what each half was fitted with"
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "log-loss gain over the competition's average" in out and "HT/FT cells" in out and "htft" in out


def test_the_halves_command_says_so_when_no_match_could_be_predicted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "empty.csv"
    cli.write_csv(path, {})
    assert cli.main(["halves", "--csv-1h", str(path), "--csv-2h", str(path), "--months", "12"]) == 0
    assert "no match was predicted in both halves" in capsys.readouterr().out


def test_the_history_can_leave_a_one_off_container_through_the_standard_output(tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    """``export --out -`` writes gzip to the standard output (the message goes to the error output), so a ``docker run`` can be redirected."""
    import gzip

    source = tmp_path / "in.csv"
    data = simulated(800)
    cli.write_csv(source, data)
    assert cli.main(["export", "--measure", "corners_ft", "--csv", str(source), "--out", "-"]) == 0
    captured = capsysbinary.readouterr()
    assert captured.out[:2] == b"\x1f\x8b", "gzip, and nothing else, on the standard output"
    assert b"written to -" in captured.err
    copy = tmp_path / "copy.csv"
    copy.write_bytes(gzip.decompress(captured.out))
    assert cli.read_csv(copy) == data


def test_the_sql_command_prints_the_statement_that_reads_a_history_and_touches_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    from fbi.families.history import UnknownMeasureError

    assert cli.main(["sql", "--measure", "corners_ft", "--months", "6"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("COPY (SELECT") and "o.corners_ft_home AS home" in out and "FROM market.fixture_outcomes" in out
    assert "TO STDOUT WITH (FORMAT csv, HEADER true)" in out and "o.is_tracked" in out
    assert "is_neutral" not in out and "0 AS neutral" in out, "the neutral-venue flag is not read: the owner has not promoted that rule"
    with pytest.raises(UnknownMeasureError):
        cli.main(["sql", "--measure", "corners_1h"])


def test_the_choice_is_made_on_the_sides_and_the_total_not_on_the_total_alone() -> None:
    """Corners (23 Oct 2026): the sides had the skill and the total none, so a choice made on the total alone was a choice made on noise."""
    data = simulated(800)
    matches = data[7]
    start = matches[len(matches) // 2].kickoff_at
    _, _, grid = evaluate.tune(data, measure="corners_ft", start=start, days=200, xis=(0.0,), penalties=(1.0,))
    ev = evaluate.walk_forward(data, measure="corners_ft", start=start - timedelta(days=200), end=start, step_days=28, xi=0.0, penalty=1.0)
    gains = evaluate.summarise(ev)["log_score_gain_per_match"]
    assert grid["xi=0.0,penalty=1.0"] == pytest.approx((gains["home"]["mean"] + gains["away"]["mean"] + gains["total"]["mean"]) / 3)
    _, _, only_total = evaluate.tune(data, measure="corners_ft", start=start, days=200, xis=(0.0,), penalties=(1.0,), counts=("total",))
    assert only_total["xi=0.0,penalty=1.0"] == pytest.approx(gains["total"]["mean"])


def test_the_grid_of_the_command_line_replaces_the_default_one() -> None:
    import argparse

    named = argparse.Namespace(xis="0,0.002", penalties="4,16,64")
    assert cli.grid_of(named) == ((0.0, 0.002), (4.0, 16.0, 64.0))
    assert cli.grid_of(argparse.Namespace(xis=None, penalties=None)) == (tuple(evaluate.DEFAULT_XIS), tuple(evaluate.DEFAULT_PENALTIES))
    assert 32.0 in evaluate.DEFAULT_PENALTIES, "the best of the first grid was its largest penalty: the grid goes beyond it"


def test_the_csv_carries_the_referee_when_there_is_one_and_old_files_still_read(tmp_path: Path) -> None:
    ko = clock_now() - timedelta(days=3)
    data = {7: [Match(1, ko, 10, 11, 3, 2, False, 55), Match(2, ko + timedelta(hours=3), 12, 13, 1, 1)]}
    path = tmp_path / "with.csv.gz"
    cli.write_csv(path, data)
    assert cli.read_csv(path) == data, "a referee comes back as the referee, no referee as none"
    old = tmp_path / "old.csv"
    old.write_text("competition_id,fixture_id,kickoff_at,home_id,away_id,home,away,neutral\n"
                   f"7,1,{ko.isoformat()},10,11,3,2,0\n", encoding="utf-8")
    assert cli.read_csv(old)[7][0].referee_id is None, "an export made before the referee was read"


def test_the_sql_command_reads_the_referee_only_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sql", "--measure", "cards_lines_ft", "--referee"]) == 0
    with_referee = capsys.readouterr().out
    assert cli.main(["sql", "--measure", "cards_lines_ft"]) == 0
    without = capsys.readouterr().out
    assert "fr.referee_id AS referee_id" in with_referee and "referee" not in without
    assert "fixture_team_stats" in with_referee and "fixture_team_stats" in without, "cards are read from the statistics, or from events that agree with them"
    assert "cards_consistent" not in with_referee and "cards_consistent" not in without, "a red card is not asked to be reported (it is a selection)"


def test_the_score_command_reads_through_a_connection_that_cannot_write_and_passes_what_it_was_asked(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: dict[str, Any] = {}

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *exc: object) -> None:
            seen["closed"] = True

        def rollback(self) -> None:
            seen["rolled_back"] = True

    def connect(url: str, **kwargs: Any) -> Connection:
        seen["options"] = kwargs.get("options")
        return Connection()

    def fake_score(conn: Connection, **kwargs: Any) -> dict[str, Any]:
        seen["asked"] = kwargs
        window = {"since": "2035-02-01T00:00:00", "until": "2035-02-28T00:00:00", "wait_hours": kwargs["wait_hours"], "forecast_rows": 0}
        return {**score.summarise([], {"pushed": 0, "ungradable": 3}), "window": window}

    monkeypatch.setattr(psycopg, "connect", connect)  # the very modules the command calls through
    monkeypatch.setattr(score, "score", fake_score)
    assert cli.main(["score", "--days", "7", "--wait-hours", "36", "--model", "family-yellow_ft", "--no-market", "--min-books", "4", "--min-ev", "0.05",
                     "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["left_out"] == {"pushed": 0, "ungradable": 3}
    assert seen["options"] == "-c default_transaction_read_only=on", "it reads; it cannot write by mistake"
    assert (seen["asked"]["days"], seen["asked"]["wait_hours"], seen["asked"]["model"]) == (7, 36.0, "family-yellow_ft")
    assert (seen["asked"]["market"], seen["asked"]["min_books"], seen["asked"]["min_ev"]) == (False, 4, 0.05)
    assert seen["rolled_back"] and seen["closed"]
    assert cli.main(["score"]) == 0
    assert "nothing to grade yet" in capsys.readouterr().out
    assert (seen["asked"]["days"], seen["asked"]["wait_hours"], seen["asked"]["model"]) == (14, 30.0, None), "the defaults"
    assert (seen["asked"]["market"], seen["asked"]["min_books"], seen["asked"]["min_ev"]) == (True, 3, 0.03), "against the market unless told not to"


def three_files(tmp_path: Path, rows: list[dependence.Row]) -> dict[str, str]:
    """The three histories of the rows as the ``export`` command writes them (one file per family)."""
    paths: dict[str, str] = {}
    for family in dependence.FAMILIES:
        by_competition: dict[int, list[Match]] = {}
        for r in rows:
            home, away = getattr(r, family)
            by_competition.setdefault(r.competition_id, []).append(Match(r.fixture_id, r.kickoff_at, 1, 2, home, away))
        path = tmp_path / f"{family}.csv.gz"
        cli.write_csv(path, by_competition)
        paths[family] = str(path)
    return paths


def test_the_dependence_command_reads_three_files_and_prints_the_reading(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = synthetic(dependent=True, seed=4, size=200)
    files = three_files(tmp_path, rows)
    args = ["dependence", "--days", "36500", "--csv-goals", files["goals"], "--csv-corners", files["corners"], "--csv-cards", files["cards"], "--replicates", "20"]
    assert cli.main([*args, "--top", "1"]) == 0
    text = capsys.readouterr().out
    assert "dependence-v1" in text and "600 matches with the goals, the corners and the cards known" in text and "20 resamples" in text
    assert text.count("-> ") == 1, "the pair that depends most, as asked"
    assert cli.main([*args, "--json", "--seed", "5"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["criterion"]["seed"] == 5 and report["criterion"]["replicates"] == 20 and len(report["pairs"]) == 96
    assert report["data"]["coverage"] == {"goals": 600, "corners": 600, "cards": 600, "joined": 600}
    assert cli.main(["dependence", "--days", "1", "--csv-goals", files["goals"], "--csv-corners", files["corners"], "--csv-cards", files["cards"]]) == 0
    assert "at least 300 matches in two strata are needed" in capsys.readouterr().out, "the window leaves them all out"


def test_the_dependence_command_wants_the_three_files_or_none(tmp_path: Path) -> None:
    files = three_files(tmp_path, synthetic(dependent=False, seed=1, size=50))
    with pytest.raises(SystemExit, match="needs the three of them; missing --csv-cards"):
        cli.main(["dependence", "--csv-goals", files["goals"], "--csv-corners", files["corners"]])
    with pytest.raises(SystemExit, match="missing --csv-corners, --csv-cards"):
        cli.main(["dependence", "--csv-goals", files["goals"]])


def test_the_dependence_command_reads_the_database_through_a_connection_that_cannot_write(monkeypatch: pytest.MonkeyPatch,
                                                                                         capsys: pytest.CaptureFixture[str]) -> None:
    seen: dict[str, Any] = {}

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *exc: object) -> None:
            seen["closed"] = True

        def rollback(self) -> None:
            seen["rolled_back"] = True

    def connect(url: str, **kwargs: Any) -> Connection:
        seen["options"] = kwargs.get("options")
        return Connection()

    def read(conn: Connection, *, since: Any, cutoff: Any) -> dict[str, dict[int, list[Match]]]:
        seen["window"] = (since, cutoff)
        return {"goals": {}, "corners": {}, "cards": {}}

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(dependence, "read", read)
    assert cli.main(["dependence", "--days", "30"]) == 0
    assert "0 matches with the goals, the corners and the cards known" in capsys.readouterr().out
    assert seen["options"] == "-c default_transaction_read_only=on" and seen["rolled_back"] and seen["closed"]
    since, cutoff = seen["window"]
    assert cutoff - since == timedelta(days=30)
    assert cli.main(["dependence"]) == 0
    capsys.readouterr()
    since, cutoff = seen["window"]
    assert cutoff - since == timedelta(days=dependence.HISTORY_DAYS), "three years unless told"


class ReadOnlyConnection:
    """What ``psycopg.connect`` hands back when the connection itself is not the point: a context that remembers it was closed and rolled back."""

    def __init__(self, seen: dict[str, Any]) -> None:
        self.seen = seen

    def __enter__(self) -> ReadOnlyConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.seen["closed"] = True

    def rollback(self) -> None:
        self.seen["rolled_back"] = True


def test_the_decide_command_runs_the_pass_as_a_dry_run_through_a_connection_that_cannot_write(monkeypatch: pytest.MonkeyPatch,
                                                                                            capsys: pytest.CaptureFixture[str]) -> None:
    seen: dict[str, Any] = {}

    def connect(url: str, **kwargs: Any) -> ReadOnlyConnection:
        seen["options"] = kwargs.get("options")
        return ReadOnlyConnection(seen)

    def dry_pass(conn: ReadOnlyConnection, **kwargs: Any) -> tuple[family_decide.FamilyReport, list[Any]]:
        seen["asked"] = kwargs
        return family_decide.FamilyReport(forecasts=4, fixtures=1), []

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(family_decide, "decide_families", dry_pass)
    monkeypatch.setattr(family_decide, "environment", lambda: {"FBI_FAMILY_DECISIONS": "shadow"})
    assert cli.main(["decide", "--at", "2035-03-01T12:00", "--horizon-hours", "10", "--fixture", "5", "--fixture", "7"]) == 0
    out = capsys.readouterr().out
    assert "what a pass would do at 2035-03-01 12:00 UTC over the next 10 h under decision-fam-v1" in out
    assert "FBI_FAMILY_DECISIONS is shadow" in out, "the switch as the worker would read it"
    assert "funnel: 4 forecasts of 1 matches" in out
    assert seen["options"] == "-c default_transaction_read_only=on", "it reads; it cannot write by mistake"
    assert seen["rolled_back"] and seen["closed"]
    assert seen["asked"] == {"at": datetime(2035, 3, 1, 12, tzinfo=UTC), "horizon": timedelta(hours=10), "only": [5, 7], "write": False}


def test_the_decide_command_looks_at_the_next_36_hours_of_every_match_from_now_unless_told(monkeypatch: pytest.MonkeyPatch,
                                                                                        capsys: pytest.CaptureFixture[str]) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(psycopg, "connect", lambda url, **kw: ReadOnlyConnection(seen))
    monkeypatch.setattr(family_decide, "decide_families",
                        lambda conn, **kw: (seen.update(asked=kw) or (family_decide.FamilyReport(), [])))
    monkeypatch.setattr(family_decide, "environment", lambda: {})
    before = clock_now()
    assert cli.main(["decide"]) == 0
    after = clock_now()
    asked = seen["asked"]
    assert before <= asked["at"] <= after and asked["horizon"] == timedelta(hours=36) == family_decide.HORIZON
    assert asked["only"] is None and asked["write"] is False
    out = capsys.readouterr().out
    assert "FBI_FAMILY_DECISIONS is off: the worker runs no pass" in out, "unset is off"
    assert "nothing to decide: the families have stated no forecast" in out, "an empty pass says where it ran dry"


def test_the_decide_command_can_print_everything_as_json_and_limit_the_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(psycopg, "connect", lambda url, **kw: ReadOnlyConnection(seen))
    monkeypatch.setattr(family_decide, "decide_families", lambda conn, **kw: (family_decide.FamilyReport(forecasts=2, would_write=0), []))
    assert cli.main(["decide", "--at", "2035-03-01", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["version"] == "decision-fam-v1" and summary["at"] == "2035-03-01T00:00:00+00:00" and summary["horizon_hours"] == 36.0
    assert summary["report"]["forecasts"] == 2 and summary["report"]["would_write"] == 0 and summary["decisions"] == []
    assert cli.main(["decide", "--top", "0"]) == 0
    assert "decisions of the families, dry run" in capsys.readouterr().out
    monkeypatch.setattr(family_decide, "decide_families", lambda conn, **kw: (family_decide.FamilyReport(forecasts=9, evaluated=5),
                                                                              [decided(fixture=i, odds=2.0 + i / 10) for i in (1, 2, 3, 4, 5)]))
    assert cli.main(["decide", "--top", "1"]) == 0
    listed = capsys.readouterr().out
    assert listed.count(" [CORNERS]: ") == 1 and "best price 2.50" in listed and "... and 4 more" in listed, "the one that sees the most value"
    assert cli.main(["decide"]) == 0
    everything = capsys.readouterr().out
    assert everything.count(" [CORNERS]: ") == 5 and " more (" not in everything, "twenty are listed unless told: all five are"
    assert cli.main(["decide", "--json"]) == 0
    assert [x["fixture_id"] for x in json.loads(capsys.readouterr().out)["decisions"]] == [5, 4, 3, 2, 1], "and the JSON carries them all, the best first"
    with pytest.raises(SystemExit):
        cli.main(["decide", "--horizon-hours", "soon"])
    with pytest.raises(SystemExit):
        cli.main(["decide", "--at", "tomorrow"])
