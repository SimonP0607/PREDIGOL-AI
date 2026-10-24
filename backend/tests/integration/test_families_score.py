"""The scoreboard of the stored family forecasts in a real database (plan F11): the rows the writer stored, graded on what the match turned out to be.

The pure parts are in tests/unit/test_families_score.py. Here: a match is forecast before it kicks off, it is played, and the scoreboard reads
the last forecast stored before the kick-off, the counts through the door the families read outcomes through, and grades the one against the other."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.families import forecast, score
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT, catalogue, played, run, upcoming

pytestmark = pytest.mark.integration

KICKOFF = AT + timedelta(days=1)
NOW = AT + timedelta(days=4)


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def play(w: World, fixture_id: int, *, goals: tuple[int, int] = (3, 1), ht: tuple[int, int] = (2, 0), corners: tuple[int, int] = (7, 4),
         yellows: tuple[int, int] = (2, 3), reds: tuple[int, int] = (0, 1)) -> None:
    """The match is over: its result, its half-time score and the statistics of the two sides."""
    w.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fixture_id,))
    w.result(fixture_id, goals, ht=ht, settled=KICKOFF + timedelta(hours=3), kickoff=KICKOFF)
    for side, c, y, r in (("home", corners[0], yellows[0], reds[0]), ("away", corners[1], yellows[1], reds[1])):
        w.team_stats(fixture_id, side, corners=c, yellow_cards=y, red_cards=r)


def market(report: dict[str, Any], model: str, key: str, line: float, selection: str) -> dict[str, Any]:
    return next(x for x in report["models"][model]["markets"] if (x["key"], x["line"], x["selection"]) == (key, line, selection))


def test_the_forecasts_of_a_match_that_was_played_are_graded_on_what_happened(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    play(w, fid)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    assert set(report["models"]) == {"family-goals_halves", "family-corners_ft", "family-cards_lines_ft", "family-yellow_ft"}
    assert all(m["fixtures"] == 1 and m["rows"] > 0 for m in report["models"].values())
    assert report["left_out"] == {"pushed": 0, "ungradable": 0}
    corners = "family-corners_ft"  # 11 corners: 7 for the home side, 4 for the away side
    assert market(report, corners, "CORNERS_OU", 10.5, "Over")["observed"] == 1.0
    assert market(report, corners, "CORNERS_OU", 11.5, "Over")["observed"] == 0.0
    assert market(report, corners, "CORNERS_OU_HOME", 6.5, "Over")["observed"] == 1.0
    assert market(report, corners, "CORNERS_1X2", 0, "Home")["observed"] == 1.0
    halves = "family-goals_halves"  # 2-0 at the break, 3-1 at the end: 2 goals in each half
    assert market(report, halves, "HTFT", 0, "Home/Home")["observed"] == 1.0
    assert market(report, halves, "HTFT", 0, "Draw/Draw")["observed"] == 0.0
    assert market(report, halves, "HSH", 0, "Draw")["observed"] == 1.0
    assert market(report, halves, "1X2_1H", 0, "Home")["observed"] == 1.0
    assert market(report, "family-cards_lines_ft", "CARDS_OU", 5.5, "Over")["observed"] == 1.0, "2 + 3 yellows and one red are 6 cards"
    assert market(report, "family-yellow_ft", "YELLOW_OU", 4.5, "Over")["observed"] == 1.0, "and 5 of them yellow"


def test_the_probability_graded_is_the_one_stored_the_last_before_the_kick_off(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    before = db.execute("SELECT p FROM models.match_forecasts WHERE fixture_id = %s AND market_key = 'CORNERS_OU' AND selection = 'Over' AND line = 10.5 "
                        "AND model_name = 'family-corners_ft'", (fid,)).fetchall()
    assert len(before) == 1
    # a row stored AFTER the kick-off (a re-run that should not exist) must never be what the match is graded with
    db.execute("INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, model_name, model_version_id, "
               "data_cutoff_ts, p_model, p, p_push, calibration, basis, input_hash, code_version) "
               "SELECT version, %s, fixture_id, family, market_key, selection, line, model_name, model_version_id, data_cutoff_ts, 0.999, 0.999, p_push, "
               "calibration, basis, input_hash, code_version FROM models.match_forecasts "
               "WHERE fixture_id = %s AND market_key = 'CORNERS_OU' AND selection = 'Over' AND line = 10.5 AND model_name = 'family-corners_ft'",
               (KICKOFF + timedelta(minutes=5), fid))
    play(w, fid)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    assert market(report, "family-corners_ft", "CORNERS_OU", 10.5, "Over")["mean_p"] == pytest.approx(float(before[0][0]))


def test_a_match_with_no_forecast_or_too_recent_or_without_its_statistics_is_not_graded(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    play(w, fid)
    assert score.score(db, now=KICKOFF + timedelta(hours=20), days=14, wait_hours=30)["models"] == {}, "the statistics have not settled yet"
    assert score.score(db, now=NOW, days=2, wait_hours=30)["models"] == {}, "the match kicked off more than two days before"
    assert score.score(db, now=NOW, days=14, wait_hours=30, model="family-yellow_ft")["models"].keys() == {"family-yellow_ft"}
    other = upcoming(w, 2, 3)  # forecast, but its statistics never arrive
    run(db, [other])
    w.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (other,))
    w.result(other, (1, 0), ht=(0, 0), settled=KICKOFF + timedelta(hours=3), kickoff=KICKOFF)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    assert report["models"]["family-goals_halves"]["fixtures"] == 2, "the goals of both matches are known"
    assert report["models"]["family-corners_ft"]["fixtures"] == 1, "the corners of the second are not"
    assert report["left_out"]["ungradable"] > 0 and report["left_out"]["pushed"] == 0


def test_the_report_is_text_and_json_ready(db: psycopg.Connection[Any], w: World) -> None:
    import json

    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    play(w, fid)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    json.dumps(report, default=str)
    text = score.render(report, min_rows=1)
    assert "family-corners_ft: 1 matches" in text and "log loss" in text and "calibration gap" in text
