"""PM-05-08: the facts of a match's «importance» (``fbi.competitions.importance``) - pure parts: the match days of a league stage at
the end of a season (the last day, the day before it, a team with a match in hand), the knock-out rounds to the final, the home and away
places, and the switch born off. The database side is ``tests/integration/test_match_importance.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.competitions import importance as imp
from fbi.competitions.context import reading_of

T0 = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)


def season(days: int, teams: int = 4) -> list[imp.StageMatch]:
    """A round robin with one match day a week: day d has its matches at T0 + d weeks."""
    out = []
    fid = 1
    for d in range(1, days + 1):
        for k in range(teams // 2):
            out.append(imp.StageMatch(fid, home=2 * k + 1, away=2 * k + 2, kickoff=T0 + timedelta(weeks=d, minutes=k), match_day=d))
            fid += 1
    return out


def test_the_last_match_day_of_the_season() -> None:
    matches = season(38)
    last = next(m for m in matches if m.match_day == 38)
    days = imp.match_days(last.fixture_id, last.home, last.away, last.kickoff, 38, matches)
    assert (days.match_day, days.last_published, days.after, days.is_last) == (38, 38, 0, True)
    assert (days.left_home, days.left_away) == (0, 0)
    assert days.as_json()["schedule"] == "publicado"


def test_the_day_before_the_last() -> None:
    matches = season(38)
    m = next(x for x in matches if x.match_day == 37)
    days = imp.match_days(m.fixture_id, m.home, m.away, m.kickoff, 37, matches)
    assert (days.after, days.is_last, days.left_home, days.left_away) == (1, False, 1, 1)


def test_a_postponed_match_played_after_the_last_day_is_still_left() -> None:
    matches = season(10)
    # team 1's match of day 5 moved after day 10: on day 10 team 1 still has one left, team 2's opponent too
    moved = next(m for m in matches if m.match_day == 5 and m.home == 1)
    matches = [m for m in matches if m != moved] + [imp.StageMatch(moved.fixture_id, 1, 2, T0 + timedelta(weeks=12), 5)]
    day10 = next(m for m in matches if m.match_day == 10 and m.home == 3)
    days = imp.match_days(day10.fixture_id, 3, 4, day10.kickoff, 10, matches)
    assert (days.after, days.is_last, days.left_home, days.left_away) == (0, True, 0, 0)
    day10_1 = next(m for m in matches if m.match_day == 10 and m.home == 1)
    days = imp.match_days(day10_1.fixture_id, 1, 2, day10_1.kickoff, 10, matches)
    assert (days.left_home, days.left_away) == (1, 1)


def test_a_schedule_published_in_parts_says_only_what_it_has() -> None:
    matches = season(19)  # the Clausura: 19 days published, the play-offs not yet drawn
    m = next(x for x in matches if x.match_day == 19)
    days = imp.match_days(m.fixture_id, m.home, m.away, m.kickoff, 19, matches)
    assert days.is_last and days.last_published == 19 and days.schedule == "publicado"


def test_rounds_to_the_final() -> None:
    def r(label: str) -> int | None:
        reading = reading_of(label)
        assert reading is not None
        return imp.rounds_to_final(reading)

    assert r("Final") == 0
    assert r("Semi-finals") == 1
    assert r("Quarter-finals") == 2
    assert r("Round of 16") == 3
    assert r("Round of 32") == 4
    assert r("1st Round") is None
    assert r("2nd Qualifying Round") is None


def test_stage_facts_of_a_league_a_cup_and_an_unreadable_label() -> None:
    league = imp.stage_facts("Clausura - 18", None)
    assert (league["name"], league["kind"], league["role"]) == ("Clausura", "league", "league")
    cup = imp.stage_facts("Round of 16", 2)
    assert (cup["kind"], cup["teams"], cup["rounds_to_final"], cup["leg"]) == ("knockout", 16, 3, 2)
    assert imp.stage_facts(None, None)["kind"] == "unresolved"


def rec(team: int, w: int, d: int, lo: int, gf: int, ga: int) -> imp.SideRecord:
    return imp.SideRecord(team, w + d + lo, w, d, lo, gf, ga)


def test_the_home_place_is_by_points_then_goal_difference_then_goals() -> None:
    records = [rec(1, 5, 2, 2, 14, 8), rec(2, 5, 2, 2, 12, 6), rec(3, 6, 0, 3, 15, 10), rec(4, 2, 1, 6, 6, 15), rec(5, 5, 2, 2, 14, 8)]
    def place(team: int) -> imp.SidePlace:
        got = imp.side_place(team, "home", records)
        assert got is not None
        return got

    assert place(3).position == 1  # 18 points
    # 2 and 1 and 5 have 17; 1 and 5: +6 with 14 scored, 2: +6 with 12 -> 1 and 5 share second, 2 fourth
    p1, p5, p2 = (place(t) for t in (1, 5, 2))
    assert (p1.position, p5.position, p2.position) == (2, 2, 4)
    assert p1.of == 5 and p1.as_json()["points"] == 17 and p1.as_json()["side"] == "home"
    assert imp.side_place(9, "home", records) is None


def test_the_switch_is_born_off_and_the_rule_says_it_is_not_the_official_table() -> None:
    assert imp.mode({}) == "off" and imp.mode({imp.SWITCH: "1"}) == "on"
    assert "no es la tabla oficial" in imp.RULE and "no una probabilidad" in imp.RULE


def test_nothing_of_the_module_reaches_a_probability_a_model_or_a_pick() -> None:
    import ast
    from pathlib import Path

    tree = ast.parse(Path(imp.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert {m for m in imported if m.startswith("fbi.")} <= {"fbi.competitions", "fbi.competitions.context", "fbi.competitions.tables"}
    sql = (imp.FIXTURE_SQL + imp.STAGE_MATCHES_SQL + imp.SIDES_SQL).lower()
    assert "fixture_results" not in sql  # nothing of a result: the schedule and the stored tables only
    for word in ("picks.", "models.", "predictions", "features."):
        assert word not in sql
