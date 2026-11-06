"""The three sections derived from the structured reading (plan de cierre UX, 2.1): the key points, why a published pick has value
and the factors that stand out - pure, from facts a reading already holds and the pick cards a reader is shown. Nothing is
estimated, nothing is padded, and a datum that is missing is left out."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from fbi.api.contracts.product import CompetitionBadge, PickCard, StartedPick, TeamBadge
from fbi.api.contracts.reading import MatchReading, ReadingFact
from fbi.api.envelope import Envelope, unavailable
from fbi.api.services import reading_value as rv

AT = datetime(2026, 11, 5, 18, 0, tzinfo=UTC)


def fact(code: str, ref: str = "packet:x", **params: Any) -> ReadingFact:
    return ReadingFact(code=code, params=params, ref=ref)


SECTIONS: dict[str, list[ReadingFact]] = {
    "summary": [fact("match_intro", competition="Liga"), fact("expected_result", ref="forecast:1X2", outcome="home",
                                                                 team="Nacional", probability=0.52, calibrated=True)],
    "context": [fact("stakes_pressure", side="home", team="Nacional", pressure="title"),
                fact("stakes_pressure", side="away", team="Millonarios", pressure="settled"),
                fact("rest_days", side="home", team="Nacional", days=3.0)],
    "data": [fact("form", side="home", team="Nacional"), fact("key_absences", side="away", team="Millonarios", count=1,
                                                                 players=["A. Uno"]),
             fact("streak_unbeaten", side="home", team="Nacional", n=5)],
    "market": [fact("market_favourite", outcome="home"), fact("market_moved", outcome="home", opening=0.35, now=0.32)],
    "risks": [fact("lineups_unconfirmed"), fact("uncalibrated", markets=["BTTS"])],
    "conclusion": [fact("likely", market="1X2", outcome="home", probability=0.52, calibrated=True)],
}


def card(**over: Any) -> PickCard:
    base: dict[str, Any] = {
        "pick_id": 7,
        "fixture_id": 1,
        "kickoff_at": AT,
        "competition": CompetitionBadge(id=1, name="Liga", country="CO", logo_url=None, flag_url=None),
        "home": TeamBadge(id=1, name="Nacional", logo_url=None),
        "away": TeamBadge(id=2, name="Millonarios", logo_url=None),
        "market_key": "1X2",
        "selection": "Home",
        "line": Decimal(0),
        "status": "published",
        "model": "m",
        "best_odds": Decimal("2.30"),
        "bookmaker": "Bet",
        "price_at": AT,
        "p_model": Decimal("0.5"),
        "p_market": Decimal("0.43"),
        "fair_odds": Decimal("2.326"),
        "edge": Decimal("0.07"),
        "ev": Decimal("0.15"),
        "freshness": "fresh",
        "value_now": True,
        "value_reason": None,
        "user_status": "RECOMMENDED",
        "status_reason": "approved",
        "context_pending": False,
    }
    base.update(over)
    return PickCard(**base)


def test_a_pick_says_its_two_probabilities_and_its_three_prices_with_the_picks_own_numbers() -> None:
    facts = rv._card(card())
    assert [f.code for f in facts] == ["value_pick", "value_price"]
    assert {f.ref for f in facts} == {"pick:7"}
    pick, price = (f.params for f in facts)
    assert (pick["p_model"], pick["p_market"]) == (0.5, 0.43)
    assert pick["market"] == "1X2" and pick["selection"] == "Home" and pick["home"] == "Nacional"
    assert (price["odds"], price["fair_market"], price["fair_model"], price["taken"]) == (2.3, 2.33, 2.0, False)


def test_without_a_market_probability_or_a_price_what_is_missing_is_left_out_never_filled() -> None:
    assert [f.code for f in rv._card(card(p_market=None))] == ["value_price"]
    only_prob = rv._card(card(best_odds=None))
    assert [f.code for f in only_prob] == ["value_pick"]
    nothing = rv._card(card(p_market=None, best_odds=None))
    assert nothing == []
    price = rv._card(card(p_market=None))[0].params
    assert price["fair_market"] is None and price["fair_model"] == 2.0


def test_a_started_pick_is_told_as_it_was_taken() -> None:
    started = StartedPick.model_construct(
        pick_id=9, market_key="OU", selection="Over", line=Decimal("2.5"), home=TeamBadge(id=1, name="Nacional", logo_url=None),
        away=TeamBadge(id=2, name="Millonarios", logo_url=None), p_model=Decimal("0.6"), p_market=Decimal("0.55"),
        odds_taken=Decimal("1.95"))
    facts = rv._started(started)
    assert [f.params.get("taken") for f in facts if f.code == "value_price"] == [True]
    assert facts[0].ref == "pick:9" and facts[0].params["line"] == 2.5


def test_the_factors_are_the_facts_the_readings_own_rules_flag_and_never_a_settled_pressure() -> None:
    got = rv.factors(SECTIONS)
    assert [f.code for f in got] == ["stakes_pressure", "key_absences", "streak_unbeaten", "market_moved"]
    assert [f.params["team"] for f in got if f.code == "stakes_pressure"] == ["Nacional"], "«settled»: nothing to play for"
    assert got[0] is SECTIONS["context"][0], "copied as they are, with their reference"


def test_the_factors_never_pass_the_cap() -> None:
    many = {"context": [fact("stakes_pressure", side="home", team=f"T{i}", pressure="title") for i in range(20)]}
    assert len(rv.factors(many)) == rv.MAX_FACTORS


def test_the_key_points_go_in_the_order_a_reader_needs_them_and_never_pass_five() -> None:
    value = rv._card(card())
    standing = rv.factors(SECTIONS)
    points = rv.key_points(SECTIONS, value, standing)
    assert [f.code for f in points] == ["expected_result", "value_pick", "stakes_pressure", "key_absences"]
    assert all(f.code != "value_price" for f in points), "the price is told in the value section, not as a point"
    assert all(f.code not in ("lineups_unconfirmed", "uncalibrated") for f in points), "the risks have their own list"


def test_the_points_never_pass_five() -> None:
    many = {**SECTIONS, "conclusion": [fact("description_only", ref="packet:quality")],
            "context": [fact("stakes_pressure", side="home", team=f"T{i}", pressure="title") for i in range(4)]}
    points = rv.key_points(many, rv._card(card()) + rv._card(card(pick_id=8)), rv.factors(many))
    assert len(points) == rv.MAX_POINTS and points[0].code == "description_only"


def test_a_match_without_a_pick_has_no_value_point_and_a_match_with_little_data_has_fewer_points_not_padding() -> None:
    sparse = {"summary": [fact("forecast_missing", ref="forecast", reason="no_forecast_yet")],
              "risks": [fact("no_context_yet", ref="packet")]}
    points = rv.key_points(sparse, [], rv.factors(sparse))
    assert [f.code for f in points] == ["forecast_missing"], "it says what is missing; the risks are listed beside"
    assert rv.key_points({}, [], []) == []


def test_a_conclusion_that_is_description_only_leads_the_points() -> None:
    sections = {**SECTIONS, "conclusion": [fact("description_only", ref="packet:quality")]}
    assert rv.key_points(sections, [], [])[0].code == "description_only"


def test_a_repeated_fact_counts_once() -> None:
    value = rv._card(card())
    assert [f.code for f in rv.key_points({}, value + value, [])] == ["value_pick"]


def test_a_reading_that_is_not_shown_gets_nothing_added() -> None:
    hidden: Envelope[MatchReading | None] = unavailable(None, "The structured reading is not shown to users yet.")
    assert rv.attach(cast(Any, None), hidden) is hidden, "the owner's switch hides the derived sections with the reading"


def test_the_derived_sections_are_never_one_of_the_six_the_ai_reads() -> None:
    assert set(rv.EXTRA_KEYS).isdisjoint(SECTIONS)
