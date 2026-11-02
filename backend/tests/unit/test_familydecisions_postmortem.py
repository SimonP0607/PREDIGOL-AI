"""Plan F11 - what a family learns from one decision (``fbi.familydecisions.postmortem``, ``pm-fam-v1``): the pure parts, checked against numbers worked
by hand.

The pass against a real database is in tests/integration/test_familydecisions_postmortem.py. Here: the count a line was graded on and by how much it
passed it, for every shape of bet; the quality, the verdict and the causes are the pipeline's own functions and none of their rules is copied; the
causes a family's count has no use for are left out and the expected-goals reading of goals is never applied to corners; the answers are Spanish, say
the numbers, never invent one the data does not hold, and the whole row is JSON; a decision that does not say which family it is of is unreadable."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.core import decision_versions as dv
from fbi.familydecisions import postmortem as pm
from fbi.intel import postmortem as pipeline

D = Decimal
KICKOFF = datetime(2035, 3, 2, 12, tzinfo=UTC)


def stood(*, key: str = "CORNERS_OU", family: str | None = "CORNERS", selection: str = "Over", line: str = "10.50", odds: str = "2.100",
          result: str = "win", clv: str | None = "0.050000", p_model: str = "0.520000", p_market: str | None = "0.476190", revisions: int = 1) -> pm.Stood:
    close = None if clv is None else D("0.500000")
    forecast: dict[str, Any] = {"forecast_id": 77, "forecast_known_at": "2035-03-01T13:00:00+00:00", "forecast_cutoff": "2035-03-01T12:50:00+00:00",
                                "calibration": "UNCALIBRATED"}
    if family is not None:
        forecast["family"] = family
    return pm.Stood(
        7, 1, family, "family-corners_ft", key, selection, D(line), KICKOFF, KICKOFF - timedelta(hours=23), "T-24h", D(odds), 4,
        KICKOFF - timedelta(hours=23, minutes=30), 3, D(p_model), None if p_market is None else D(p_market), revisions, forecast, result,
        pipeline_profit(result, D(odds)), close, None if clv is None else D("2.000"), None if clv is None else KICKOFF - timedelta(minutes=12),
        None if clv is None else 12, None if clv is None else D(clv))


def pipeline_profit(result: str, odds: Decimal) -> Decimal:
    from fbi.intel.outcomes import profit_per_unit

    return profit_per_unit(result, odds).quantize(D("0.0001"))


# ── the count a line was graded on ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("key", "line", "counts", "actual", "margin"), [
    ("CORNERS_OU", "10.50", {"corners_ft_home": 7, "corners_ft_away": 4}, "11.00", "0.50"),
    ("CORNERS_OU", "11.50", {"corners_ft_home": 7, "corners_ft_away": 4}, "11.00", "-0.50"),
    ("CORNERS_OU", "11.00", {"corners_ft_home": 7, "corners_ft_away": 4}, "11.00", "0.00"),
    ("CORNERS_OU_HOME", "6.50", {"corners_ft_home": 7, "corners_ft_away": 4}, "7.00", "0.50"),
    ("CORNERS_OU_AWAY", "4.50", {"corners_ft_home": 7, "corners_ft_away": 4}, "4.00", "-0.50"),
    ("CARDS_OU", "4.50", {"cards_lines_ft_home": 3, "cards_lines_ft_away": 4}, "7.00", "2.50"),
    ("YELLOW_OU", "3.50", {"yellow_ft_home": 2, "yellow_ft_away": 3}, "5.00", "1.50"),
    ("OU_1H", "0.50", {"goals_1h_home": 2, "goals_1h_away": 0}, "2.00", "1.50"),
    ("OU_2H", "1.50", {"goals_2h_home": 1, "goals_2h_away": 0}, "1.00", "-0.50"),
])
def test_the_count_is_the_number_the_line_was_graded_on_and_the_margin_is_how_far_it_passed_it(key: str, line: str, counts: dict[str, int], actual: str,
                                                                                               margin: str) -> None:
    assert pm.counted(key, D(line), counts) == (D(actual), D(margin))


def test_a_bet_on_the_parity_has_a_count_and_no_line_to_pass() -> None:
    assert pm.counted("CORNERS_OE", D("0.00"), {"corners_ft_home": 7, "corners_ft_away": 4}) == (D("11.00"), None)


@pytest.mark.parametrize("key", ["CORNERS_1X2", "CORNERS_AH", "HTFT", "HSH", "BTTS_1H"])
def test_a_bet_on_two_counts_has_no_single_number_to_report(key: str) -> None:
    everything = {"corners_ft_home": 7, "corners_ft_away": 4, "goals_1h_home": 1, "goals_1h_away": 0, "goals_2h_home": 2, "goals_2h_away": 1}
    assert pm.counted(key, D("0.00"), everything) == (None, None)


def test_an_unknown_count_is_never_a_zero_and_a_key_the_rules_cannot_read_has_none() -> None:
    assert pm.counted("CORNERS_OU", D("10.50"), None) == (None, None)
    assert pm.counted("CORNERS_OU", D("10.50"), {}) == (None, None)
    assert pm.counted("CORNERS_OU", D("10.50"), {"corners_ft_home": 7}) == (None, None), "one side known is not a count"
    assert pm.counted("CORNERS_OU", D("10.50"), {"corners_ft_home": 7, "corners_ft_away": None}) == (None, None)  # type: ignore[dict-item]
    assert pm.counted("NOT_A_KEY", D("1.50"), {"corners_ft_home": 7, "corners_ft_away": 4}) == (None, None)
    assert pm.counted("CORNERS_OU", D("10.50"), {"corners_ft_home": 0, "corners_ft_away": 0}) == (D("0.00"), D("-10.50")), "and a real zero is one"


# ── the quality, the verdict: the pipeline's, not a copy ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("result", "clv"), list(itertools.product(("win", "loss", "push", "void", "half_win", "half_loss"),
                                                                 ("0.050000", "0.000000", "-0.050000", "0.010000", "-0.010000", "0.010001", None))))
def test_the_quality_and_the_verdict_are_the_ones_the_pipeline_gives(result: str, clv: str | None) -> None:
    built = pm.build(stood(result=result, clv=clv), counts=None, events=[], stats={}, usual=None)
    quality = pipeline.quality_of(None if clv is None else float(clv))
    assert (built.result, built.quality, built.verdict) == (result, quality, pipeline.verdict_of(result, quality))


def test_the_edges_of_the_price_are_neutral_and_just_beyond_them_is_good_or_bad() -> None:
    assert pm.build(stood(clv="0.010000"), counts=None, events=[], stats={}, usual=None).quality == "NEUTRAL"
    assert pm.build(stood(clv="0.010001"), counts=None, events=[], stats={}, usual=None).quality == "GOOD"
    assert pm.build(stood(clv="-0.010000"), counts=None, events=[], stats={}, usual=None).quality == "NEUTRAL"
    assert pm.build(stood(clv="-0.010001"), counts=None, events=[], stats={}, usual=None).quality == "BAD"


def test_luck_and_decision_in_four_words() -> None:
    def verdict(result: str, clv: str | None) -> str:
        return pm.build(stood(result=result, clv=clv), counts=None, events=[], stats={}, usual=None).verdict

    assert verdict("win", "0.05") == "MERECIDO" and verdict("win", "-0.05") == "SUERTE"
    assert verdict("loss", "0.05") == "VARIANZA" and verdict("loss", "-0.05") == "ERROR"
    assert verdict("push", "0.05") == "NULO" and verdict("void", None) == "NULO", "a stake that came back judges nothing, close or no close"
    assert verdict("win", None) == "SIN_DATOS" and verdict("loss", None) == "SIN_DATOS"


# ── the causes ───────────────────────────────────────────────────────────────────────────────────────────────────────

RED = {"minute": 34, "extra_minute": None, "team_side": "home", "event_type": "Card", "detail": "Red Card", "comments": None, "player_name": "A"}
GOAL = {"minute": 9, "extra_minute": None, "team_side": "away", "event_type": "Goal", "detail": "Normal Goal", "comments": None, "player_name": "B"}
SUB = {"minute": 21, "extra_minute": None, "team_side": "home", "event_type": "subst", "detail": "Substitution 1", "comments": None, "player_name": "C"}
STATS = {"home": {"yellow_cards": 5, "red_cards": 1, "xg": 2.4, "corners": 7}, "away": {"yellow_cards": 4, "red_cards": 0, "xg": 0.3, "corners": 4}}


def codes(built: pm.Built) -> list[str]:
    return [c["code"] for c in built.causes]


def test_a_red_card_an_early_goal_and_an_early_substitution_are_what_the_model_could_not_see() -> None:
    built = pm.build(stood(), counts=None, events=[RED, GOAL, SUB], stats={}, usual=None)
    assert codes(built) == ["red_card", "early_goal", "early_substitution"]
    assert built.answers["no_visto"][0].startswith("Roja al local en el 34'")
    assert all(c["effect"] == "neutral" for c in built.causes if c["code"] == "red_card"), "a count has no side for a sending off to hurt"


def test_the_expected_goals_reading_of_goals_is_never_applied_to_a_count() -> None:
    built = pm.build(stood(), counts=None, events=[], stats=STATS, usual=None)
    assert not [c for c in built.causes if c["code"] in ("xg_supported", "xg_against")], "11 corners are not judged against the xG of the match"


def test_the_cards_against_what_the_referee_usually_shows_belong_to_the_families_of_cards_only() -> None:
    for family, key, shown in (("CARDS", "CARDS_OU", True), ("YELLOW", "YELLOW_OU", True), ("CORNERS", "CORNERS_OU", False), ("GOALS_HALF", "OU_1H", False)):
        built = pm.build(stood(key=key, family=family), counts=None, events=[], stats=STATS, usual=2.0)  # 10 cards against a usual 2.0
        assert ("cards_above_referee" in codes(built)) is shown, family
    assert "cards_above_referee" not in codes(pm.build(stood(key="CARDS_OU", family="CARDS"), counts=None, events=[], stats=STATS, usual=None)), \
        "and with no referee that is known, nothing to compare with"


def test_nothing_unusual_says_so() -> None:
    assert pm.build(stood(), counts=None, events=[], stats={}, usual=None).answers["no_visto"] == ["nada fuera de lo normal en los eventos registrados"]


# ── the answers ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_summary_says_the_bet_the_result_the_count_the_price_and_the_verdict() -> None:
    built = pm.build(stood(), counts={"corners_ft_home": 7, "corners_ft_away": 4}, events=[], stats={}, usual=None)
    assert built.answers["resumen"] == "córners · CORNERS_OU Over 10.5 a 2.10: ganó con 11 (0.5 por encima de la línea); precio mejor que el cierre (CLV +5.0%): MERECIDO"
    assert built.answers["conteo"] == {"cuenta": 11.0, "linea": 10.5, "margen": 0.5, "texto": "11 frente a la línea 10.5"}
    assert built.answers["aprendizaje"] == pm.LESSON["MERECIDO"]


def test_a_count_on_the_line_and_a_bet_on_two_counts_say_only_what_is_true() -> None:
    push = pm.build(stood(result="push", line="11.00"), counts={"corners_ft_home": 7, "corners_ft_away": 4}, events=[], stats={}, usual=None)
    assert push.answers["resumen"].startswith("córners · CORNERS_OU Over 11 a 2.10: devuelta con 11;"), push.answers["resumen"]
    two = pm.build(stood(key="CORNERS_1X2", selection="Home", line="0.00"), counts={"corners_ft_home": 7, "corners_ft_away": 4}, events=[], stats={}, usual=None)
    assert two.actual is None and two.margin is None
    assert two.answers["conteo"]["texto"] == "la apuesta compara dos cuentas: no hay una sola que mirar"
    assert "CORNERS_1X2 Home a 2.10" in two.answers["resumen"] and " con " not in two.answers["resumen"]


def test_without_a_close_the_price_is_not_judged_and_no_number_is_made_up() -> None:
    built = pm.build(stood(clv=None), counts=None, events=[], stats={}, usual=None)
    assert built.quality == "UNKNOWN" and built.verdict == "SIN_DATOS"
    assert built.answers["precio"]["clv"] is None and built.answers["precio"]["texto"] == "sin cierre para medir el precio"
    assert built.answers["probabilidad"]["p_cierre"] is None and "al cierre" not in built.answers["probabilidad"]["texto"]
    assert built.answers["conteo"]["cuenta"] is None and built.answers["conteo"]["margen"] is None, "an unknown count is not a zero"


def test_the_probability_the_family_stated_is_said_to_be_uncalibrated_and_the_log_loss_is_that_of_the_outcome() -> None:
    won = pm.build(stood(result="win", p_model="0.520000"), counts=None, events=[], stats={}, usual=None).answers["probabilidad"]
    lost = pm.build(stood(result="loss", p_model="0.520000"), counts=None, events=[], stats={}, usual=None).answers["probabilidad"]
    assert won["calibracion"] == "UNCALIBRATED" and "sin calibrar" in won["texto"]
    assert won["log_loss"] == pytest.approx(0.6539, abs=1e-4) and lost["log_loss"] == pytest.approx(0.734, abs=1e-3)
    for result in ("push", "void", "half_win", "half_loss"):
        assert pm.log_loss(D("0.52"), result) is None, "a half or a push is not a yes or a no"
    assert pm.log_loss(D("0.0000001"), "win") == pm.log_loss(D("0.0001"), "win"), "a probability is kept off the edges, as the pipeline's"


def test_the_evidence_names_the_forecast_the_decision_cited_and_how_many_times_it_was_revised() -> None:
    built = pm.build(stood(revisions=4), counts={"corners_ft_home": 7, "corners_ft_away": 4}, events=[RED], stats=STATS, usual=3.5)
    assert built.evidence["forecast"] == {"id": 77, "known_at": "2035-03-01T13:00:00+00:00", "data_cut_off": "2035-03-01T12:50:00+00:00",
                                         "calibration": "UNCALIBRATED"}
    assert built.evidence["decision"]["revisions"] == 4 and built.evidence["decision"]["checkpoint"] == "T-24h"
    assert built.evidence["outcome"]["version"] == dv.OUTCOME_FAMILIES and built.evidence["outcome"]["close_minutes_to_ko"] == 12
    assert built.evidence["match"] == {"kickoff_at": KICKOFF.isoformat(), "events": 1, "stats": True,
                                       "counts": {"corners_ft_home": 7, "corners_ft_away": 4}, "referee_usual_cards": 3.5}


def test_the_whole_row_is_json() -> None:
    built = pm.build(stood(), counts={"corners_ft_home": 7, "corners_ft_away": 4}, events=[RED, GOAL], stats=STATS, usual=3.5)
    for part in (built.causes, built.answers, built.evidence):
        assert json.loads(json.dumps(part)) == part


def test_a_decision_that_does_not_say_which_family_it_is_of_is_unreadable_and_is_not_guessed() -> None:
    with pytest.raises(pm.UnreadableError, match="which family"):
        pm.build(stood(family=None), counts=None, events=[], stats={}, usual=None)


# ── the reading of a row ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_row_of_the_query_becomes_a_decision_that_stood() -> None:
    row = {"id": 9, "fixture_id": 3, "model_name": "family-corners_ft", "market_key": "CORNERS_OU", "selection": "Over", "line": D("10.50"),
           "kickoff_at": KICKOFF, "known_at": KICKOFF - timedelta(hours=2), "checkpoint": "T-3h", "odds": D("2.100"), "bookmaker_id": None,
           "price_at": None, "n_bookmakers": None, "p_model": D("0.520000"), "p_market": None,
           "forecast": {"family": "CARDS", "forecast_id": 5}, "revisions": 3, "result_status": "loss", "profit_flat": D("-1.0000"),
           "close_p_fair": None, "close_odds": None, "close_as_of": None, "close_minutes_to_ko": None, "clv": None}
    s = pm.stood_from(row)
    assert (s.id, s.fixture_id, s.family, s.key, s.result, s.revisions, s.clv, s.bookmaker_id, s.books) == (9, 3, "CARDS", "CORNERS_OU", "loss", 3, None, None, None)
    assert pm.stood_from({**row, "forecast": None}).family is None, "a decision with no record of its model says no family"
    assert pm.stood_from({**row, "forecast": {"family": 5}}).family is None, "and one that names something that is not a family says none either"


def test_a_number_is_what_json_holds() -> None:
    assert pm.number(D("0.520000")) == 0.52 and pm.number(None) is None and pm.number(D("2.1049999"), 3) == 2.105
    assert pm.plain(D("10.50")) == "10.5" and pm.plain(D("11.00")) == "11" and pm.plain(D("100")) == "100" and pm.plain(D("0.50")) == "0.5"


def test_the_version_is_the_one_place_that_defines_it() -> None:
    assert pm.VERSION == dv.POSTMORTEM_FAMILIES == "pm-fam-v1"
    assert pm.DECISION_VERSION == dv.DECISION_FAMILIES and pm.OUTCOME_VERSION == dv.OUTCOME_FAMILIES
