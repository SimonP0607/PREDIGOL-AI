"""Plan F11 - the scoreboard of the stored family forecasts: the pure part (what a key is, how a row is graded, what the sums say)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.families import forecast, score
from fbi.market.rules import RULES_BY_MEASURE

KNOWN = datetime(2035, 3, 1, 12, tzinfo=UTC)

# every key the families state (the verification of the release lists the same 31): key -> (kind, subject)
GOALS_HALVES = {
    "OU_1H": ("over_under", "match"), "OU_2H": ("over_under", "match"), "OU_HOME_1H": ("over_under", "home"), "OU_AWAY_2H": ("over_under", "away"),
    "1X2_1H": ("one_x_two", "match"), "1X2_2H": ("one_x_two", "match"), "DNB_1H": ("draw_no_bet", "match"), "DC_2H": ("double_chance", "match"),
    "BTTS_1H": ("both_teams_score", "match"), "HTFT": ("half_time_full_time", "match"), "HSH": ("highest_scoring_half", "match"),
    "HSH_HOME": ("highest_scoring_half", "home"), "HSH_AWAY": ("highest_scoring_half", "away"),
}
COUNTS = {
    "CORNERS_OU": ("over_under", "match"), "CORNERS_OU_HOME": ("over_under", "home"), "CORNERS_OU_AWAY": ("over_under", "away"),
    "CORNERS_1X2": ("one_x_two", "match"), "CORNERS_DC": ("double_chance", "match"),
    "CARDS_OU": ("over_under", "match"), "CARDS_OU_HOME": ("over_under", "home"), "CARDS_1X2": ("one_x_two", "match"),
    "YELLOW_OU_AWAY": ("over_under", "away"), "YELLOW_DC": ("double_chance", "match"),
}


@pytest.mark.parametrize(("key", "shape"), [*GOALS_HALVES.items(), *COUNTS.items()])
def test_a_key_of_the_catalogue_says_what_kind_of_bet_it_is_and_on_whom(key: str, shape: tuple[str, str]) -> None:
    assert score.key_shape(key) == shape


def test_a_key_it_cannot_read_is_an_error() -> None:
    for key in ("NOPE", "CORNERS_ZZ", "OU_SIDEWAYS_1H"):
        with pytest.raises(ValueError, match="not one the scoreboard can read"):
            score.key_shape(key)
    with pytest.raises(ValueError, match="not graded on a measure"):
        score.measure_of("1X2")


def test_each_key_is_graded_on_the_measure_of_the_model_that_states_it() -> None:
    wanted = {"goals_halves": {"goals_1h", "goals_2h", "goals_halves"}, "corners_ft": {"corners_ft"}, "cards_lines_ft": {"cards_lines_ft"},
              "yellow_ft": {"yellow_ft"}}
    by_prefix = {"CORNERS": "corners_ft", "CARDS": "cards_lines_ft", "YELLOW": "yellow_ft"}
    for key in (*GOALS_HALVES, *COUNTS):
        spec = by_prefix.get(key.split("_")[0], "goals_halves")
        assert score.measure_of(key) in wanted[spec], key
        assert RULES_BY_MEASURE[score.measure_of(key)].liquidable
    assert {s.key for s in forecast.SPECS} == set(wanted), "a family was added: the scoreboard has to learn to read its keys"


def test_the_measures_to_read_expand_the_two_halves() -> None:
    assert score.measures_to_read(["HTFT", "OU_1H", "CORNERS_OU"]) == ["corners_ft", "goals_1h", "goals_2h"]
    assert score.measures_to_read(["YELLOW_OU"]) == ["yellow_ft"]


def row(fixture: int, key: str, selection: str, p: float, line: str = "0", model: str = "family-corners_ft") -> score.Row:
    return score.Row(fixture, model, key, Decimal(line), selection, p, KNOWN)


def test_a_row_is_graded_on_the_counts_of_its_match_and_what_is_unknown_is_left_out_not_lost() -> None:
    counts: dict[int, dict[str, int | None]] = {1: {"corners_ft_home": 7, "corners_ft_away": 4},  # 11 corners
                                                2: {"corners_ft_home": 5, "corners_ft_away": None}}
    rows = [row(1, "CORNERS_OU", "Over", 0.6, "10.5"), row(1, "CORNERS_OU", "Under", 0.4, "10.5"), row(1, "CORNERS_OU", "Over", 0.5, "11"),
            row(1, "CORNERS_OU_HOME", "Over", 0.3, "7.5"), row(1, "CORNERS_1X2", "Home", 0.7), row(2, "CORNERS_OU", "Over", 0.5, "9.5"),
            row(3, "CORNERS_OU", "Over", 0.5, "9.5")]
    graded, left = score.grade(rows, counts)
    assert [(g.row.selection, g.row.line, g.won) for g in graded[:2]] == [("Over", Decimal("10.5"), 1), ("Under", Decimal("10.5"), 0)]
    assert [g.won for g in graded[2:]] == [0, 1], "7 home corners do not beat 7.5; the home side has more than the away side"
    assert left == {"pushed": 1, "ungradable": 2}, "the whole line 11 comes back; a match with a count missing, or with none, is ungradable"


def test_both_halves_grade_half_time_full_time() -> None:
    counts = {1: {"goals_1h_home": 1, "goals_1h_away": 0, "goals_2h_home": 0, "goals_2h_away": 1}}
    rows = [row(1, "HTFT", "Home/Draw", 0.1, model="family-goals_halves"), row(1, "HTFT", "Draw/Draw", 0.1, model="family-goals_halves"),
            row(1, "HSH", "Draw", 0.3, model="family-goals_halves")]
    graded, left = score.grade(rows, counts)
    assert [g.won for g in graded] == [1, 0, 1] and left == {"pushed": 0, "ungradable": 0}


def test_the_sums_are_the_ones_a_hand_calculation_gives() -> None:
    # one selection stated 8 times at 0.75: it happened 6 times. Another stated twice at 0.2: once.
    rows = [row(i, "CORNERS_OU", "Over", 0.75, "9.5") for i in range(8)] + [row(i, "CORNERS_OU", "Under", 0.2, "10.5") for i in range(2)]
    graded = [score.Graded(r, 1 if (i < 6 or 8 <= i < 9) else 0) for i, r in enumerate(rows)]
    report = score.summarise(graded)
    m = report["models"]["family-corners_ft"]
    assert m["rows"] == 10 and m["fixtures"] == 8
    over = next(x for x in m["markets"] if x["selection"] == "Over")
    assert over["n"] == 8 and over["observed"] == pytest.approx(0.75) and over["mean_p"] == pytest.approx(0.75)
    assert over["log_loss"] == pytest.approx(-(0.75 * math.log(0.75) + 0.25 * math.log(0.25)))
    assert over["gain"] == pytest.approx(0.0), "a probability equal to the frequency is the best constant: no gain, no loss"
    under = next(x for x in m["markets"] if x["selection"] == "Under")
    assert under["observed"] == pytest.approx(0.5)
    assert under["log_loss"] == pytest.approx(-0.5 * math.log(0.2) - 0.5 * math.log(0.8))
    assert under["gain"] < 0, "it said 0.2 of something that happened half of the time"
    assert m["brier"] == pytest.approx((6 * 0.25**2 + 2 * 0.75**2 + 0.8**2 + 0.2**2) / 10)
    assert sum(b["n"] for b in m["reliability"]) == 10
    top = next(b for b in m["reliability"] if b["lo"] == pytest.approx(0.7))
    assert top["n"] == 8 and top["observed"] == pytest.approx(0.75)
    assert m["ece"] == pytest.approx((8 * 0.0 + 2 * abs(0.2 - 0.5)) / 10)


def test_nothing_graded_is_an_empty_scoreboard_not_an_error() -> None:
    report = score.summarise([], {"pushed": 0, "ungradable": 5})
    assert report["models"] == {} and report["left_out"] == {"pushed": 0, "ungradable": 5}
    text = score.render({**report, "window": {"since": "2035-02-01T00:00:00", "until": "2035-02-28T00:00:00", "wait_hours": 30.0, "forecast_rows": 5}})
    assert "nothing to grade yet" in text


def test_the_text_names_the_selections_that_stray_most_where_there_are_enough_rows() -> None:
    graded = [score.Graded(row(i, "CORNERS_OU", "Over", 0.9, "9.5"), 1 if i % 2 else 0) for i in range(80)]
    graded += [score.Graded(row(i, "CORNERS_OU", "Over", 0.5, "10.5"), 1 if i % 2 else 0) for i in range(80)]
    graded += [score.Graded(row(i, "CORNERS_OU", "Over", 0.9, "11.5"), 0) for i in range(10)]  # too few rows to be named
    report = score.summarise(graded)
    report["window"] = {"since": "2035-02-01T00:00:00", "until": "2035-02-28T00:00:00", "wait_hours": 30.0, "forecast_rows": len(graded)}
    text = score.render(report, top=5, min_rows=50)
    assert "family-corners_ft: 80 matches, 170 rows" in text
    assert "9.5" in text and "said  90.0 %  happened  50.0 %" in text
    assert "11.5" not in text, "ten rows say nothing"
