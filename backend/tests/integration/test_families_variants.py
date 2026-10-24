"""Plan F12.5 in a real database: the history is read as the families read it, the prices as the scoreboard reads them, the counts that grade a
forecast are the ones the outcomes view holds, and nothing is written.

The arithmetic of the reading (the corrections, the dispersion, the main line, the extra signal, the no-leak property) is in
``tests/unit/test_families_variants.py``. Here: the whole path from the tables to the report, in a world of four teams that play every day."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.families import bets, evaluate, forecast, history, variants, versus
from fbi.families.fit import OUTCOME_KNOWN_AFTER
from fbi.odds.quote_taxonomy import sync_definitions
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT, catalogue, played, referees
from .test_families_score import price

pytestmark = pytest.mark.integration

START = AT - timedelta(days=28)
TUNING: dict[str, Any] = {"dispersion_days": 40, "min_dispersion": 20}


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_world(monkeypatch: pytest.MonkeyPatch) -> None:
    """The world has a match a day: a week of them are 7, not the 200 a correction asks for."""
    monkeypatch.setattr(variants, "MIN_PAST", 5)


def window_fixtures(db: psycopg.Connection[Any]) -> list[tuple[int, datetime]]:
    return [(int(r[0]), r[1]) for r in db.execute("SELECT id, kickoff_at FROM core.fixtures WHERE kickoff_at >= %s AND kickoff_at < %s ORDER BY kickoff_at",
                                                  (START, AT)).fetchall()]


def priced(db: psycopg.Connection[Any], w: World, fixtures: list[tuple[int, datetime]]) -> None:
    """Three books quote the total of the corners at 10.5: even a day or more before the kick-off, the over shortened an hour before it."""
    sync_definitions(db, names={})
    db.execute("UPDATE market.market_definitions SET market_key = 'CORNERS_OU' WHERE provider_bet_id = 45 AND scope = 'prematch'")
    extraction = db.execute("INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, stamped_by, status) "
                            "VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", (w.hash, START - timedelta(days=3))).fetchall()[0][0]
    for fixture_id, kickoff in fixtures:
        for book in w.books(3):
            price(db, extraction, fixture_id, book, "1.90", "1.90", "10.5", kickoff - timedelta(days=2))
            price(db, extraction, fixture_id, book, "1.80", "2.00", "10.5", kickoff - timedelta(hours=1))


def over_rate(db: psycopg.Connection[Any], fixtures: list[int]) -> float:
    """How often the total of the corners was over 10.5, straight from the statistics of the two sides."""
    totals = db.execute("SELECT fixture_id, sum(corners) FROM core.fixture_team_stats WHERE fixture_id = ANY(%s) GROUP BY fixture_id", (fixtures,)).fetchall()
    assert len(totals) == len(fixtures)
    return sum(1 for _, total in totals if total > 10.5) / len(totals)


def test_the_family_and_its_variant_are_read_against_the_books_from_the_tables(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fixtures = window_fixtures(db)
    assert len(fixtures) == 28
    with_prices = fixtures[:20]
    priced(db, w, with_prices)
    before = db.execute("SELECT count(*) FROM models.match_forecasts").fetchone()
    db.execute("SET TRANSACTION READ ONLY")  # from here on a write is an error: the reading only reads
    report = variants.run(db, family="corners_ft", variants=variants.variants_of(["recent-level:7"]), start=START, end=AT, **TUNING)

    assert report["version"] == variants.VERSION and report["family"] == "corners_ft" and report["measure"] == "corners_ft"
    assert report["window"] == {"start": START.isoformat(), "end": AT.isoformat(), "first_block": (START - timedelta(days=56)).isoformat(), "step_days": 7}
    assert report["params"] == {"xi": 0.0019, "penalty": 32.0, "referee_kappa": 0.0}
    assert report["history"]["priced_fixtures"] == 20 and report["history"]["walk_forward_rows"] > 28 + 7 * 6, "the weeks before the window are replayed too"
    assert report["reference"] == "as-is" and set(report["variants"]) == {"as-is", "recent-level:7"}
    as_is, level = report["variants"]["as-is"], report["variants"]["recent-level:7"]
    assert as_is["matches"] == level["matches"] == 28 and as_is["without_dispersion"] == 0 == level["without_dispersion"]
    assert as_is["corrected_matches"] == 0 and level["corrected_matches"] == 28 and len(level["levels"]) == 4 == len(level["dispersion"])
    assert all(lv["matches"] >= 5 and lv["home"] > 0 and lv["away"] > 0 for lv in level["levels"])
    assert report["left_out"] == {"pushed": 0, "ungradable": 0}

    # the books: even at the last price but one (a day or more before), 2.00 / 3.80 for the over an hour before the kick-off
    graded = [f for f, _ in with_prices]
    for variant in (as_is, level):
        close, h24 = variant["versus"]["close"]["total"], variant["versus"]["h24"]["total"]
        for scope in ("main", "all"):
            assert close[scope]["n"] == h24[scope]["n"] == 20 and close[scope]["fixtures"] == 20, "only the matches with a price are compared"
            assert close[scope]["mean_p_market"] == pytest.approx(2.0 / 3.8) and h24[scope]["mean_p_market"] == pytest.approx(0.5)
            assert close[scope]["observed"] == pytest.approx(over_rate(db, graded)), "graded on the corners of the two sides' statistics"
            assert close[scope]["mean_books"] == 3
        assert "home" not in close and "away" not in close, "the books quoted no side"
    assert report["paired"]["recent-level:7"]["close"]["total"]["main"]["n"] == 20
    assert set(report["bets"]["models"]) == {"as-is", "recent-level:7"}
    assert report["bets"]["criterion"]["min_bets"] == 300
    window = variants.plan(START, AT, step_days=7, burn_in_days=TUNING["dispersion_days"] + 7)
    early = [f for f, kickoff in with_prices if variants.block_start(kickoff, window) + timedelta(hours=24) <= kickoff]
    assert 0 < len(early) < len(with_prices), "the match that kicks off the moment its week begins was stated too late to be bet on"
    for name, m in report["bets"]["models"].items():
        assert m["taken"] <= len(early), f"{name}: one market is priced, so at most one bet per match stated a day before"

    assert db.execute("SELECT count(*) FROM models.match_forecasts").fetchone() == before, "nothing was stored"
    text = variants.render(report)
    assert text.startswith("corners_ft (variants-v1)") and "recent-level:7 against as-is" in text


def test_a_match_in_the_last_hour_of_the_window_is_read_and_one_that_kicks_off_at_its_end_is_not(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    late = w.match(AT - timedelta(hours=1), 0, 1, goals=(2, 1), ht=(1, 0), settled=None)
    at_the_end = w.match(AT, 1, 2, goals=(1, 1), ht=(0, 0), settled=None)
    for fixture_id in (late, at_the_end):
        for side in ("home", "away"):
            w.team_stats(fixture_id, side, corners=6, yellow_cards=2, red_cards=0)
    report = variants.run(db, family="corners_ft", variants=variants.variants_of(["recent-level:7"]), start=START, end=AT, **TUNING)
    assert report["variants"]["as-is"]["matches"] == report["variants"]["recent-level:7"]["matches"] == 29, "28 days and the match of the last hour; not the one at the end"


def test_a_reading_with_no_prices_still_states_the_family_and_compares_nothing(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    report = variants.run(db, family="corners_ft", variants=variants.variants_of([]), start=START, end=AT, **TUNING)
    assert report["variants"]["as-is"]["matches"] == 28 and report["variants"]["as-is"]["versus"] == {}
    assert report["paired"] == {} and report["history"]["priced_fixtures"] == 0
    text = variants.render(report)
    assert "market minus model" not in text.split("\n", 3)[-1] and "as-is: no bet" in text, "no price: nothing to say about the books, and no bet"


def test_a_card_family_is_replayed_with_the_referee_multiplier_it_states_with_and_a_corner_family_with_none(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    strict, lenient = referees(db, "Strict", "Lenient")
    played(w, refs=((strict, 1.6), (lenient, 0.6)))
    cards = variants.run(db, family="yellow_ft", variants=variants.variants_of(["recent-level:7"]), start=START, end=AT, **TUNING)
    assert cards["params"]["referee_kappa"] == 150.0 and cards["measure"] == "yellow_ft"
    assert cards["variants"]["as-is"]["matches"] == 28
    assert 0 < cards["history"]["window_with_referee"] <= 28, "the multiplier of the whistle was applied to the matches whose referee is known"
    assert "the referee's multiplier (kappa 150) is part of the family's means: it was applied to" in variants.render(cards)
    corners = variants.run(db, family="corners_ft", variants=variants.variants_of([]), start=START, end=AT, **TUNING)
    assert corners["params"]["referee_kappa"] == 0.0 and corners["history"]["window_with_referee"] == 0
    assert "referee" not in variants.render(corners)


def test_the_family_is_replayed_with_its_own_parameters_and_the_window_is_what_those_who_read_are_asked_for(
        db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue(db)
    played(w)
    fixtures = window_fixtures(db)
    priced(db, w, fixtures[:20])
    seen: dict[str, dict[str, Any]] = {}

    def spy(name: str, module: Any, attr: str) -> None:
        real = getattr(module, attr)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            seen[name] = {"args": args, "kwargs": kwargs}
            return real(*args, **kwargs)

        monkeypatch.setattr(module, attr, wrapper)

    spy("load", history, "load")
    spy("walk", evaluate, "walk_forward")
    spy("prices", versus, "read_prices")
    variants.run(db, family="corners_ft", variants=variants.variants_of(["recent-level:7"]), start=START, end=AT, **TUNING)
    spec, first = variants.spec_of("corners_ft"), START - timedelta(days=56)
    assert seen["load"]["args"][1] == "corners_ft"
    assert seen["load"]["kwargs"] == {"since": first - timedelta(days=forecast.HISTORY_DAYS), "cutoff": AT + OUTCOME_KNOWN_AFTER, "with_referee": False}
    walk = seen["walk"]["kwargs"]
    assert (walk["measure"], walk["start"], walk["end"], walk["step_days"]) == ("corners_ft", first, AT, 7)
    assert (walk["xi"], walk["penalty"], walk["referee_kappa"]) == (spec.xi, spec.penalty, None), "the family's own time decay and penalty"
    prices = seen["prices"]["kwargs"]
    assert set(prices["fixtures"]) == {f for f, _ in fixtures} and prices["since"] == START, "the prices of the matches compared, not of the weeks replayed before them"
    assert prices["keys"] == ["CORNERS_1X2", "CORNERS_OU", "CORNERS_OU_HOME"], "the markets the variants stated, and the catalogue has"


def test_a_competition_with_more_sides_than_a_family_fits_is_left_out_and_said(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue(db)
    played(w)
    monkeypatch.setattr(forecast, "MAX_TEAMS", 3)  # four sides play
    report = variants.run(db, family="corners_ft", variants=variants.variants_of([]), start=START, end=AT, **TUNING)
    assert report["history"]["competitions"] == 0 and report["history"]["competitions_dropped"] == 1
    assert report["variants"]["as-is"]["matches"] == 0 and report["variants"]["as-is"]["versus"] == {}


def test_a_family_that_is_not_fitted_on_one_count_is_refused(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(variants.NotAFamilyError):
        variants.run(db, family="goals_halves", variants=variants.variants_of([]), start=START, end=AT)


def test_a_window_with_nothing_in_it_is_refused(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(ValueError, match="empty"):
        variants.run(db, family="corners_ft", variants=variants.variants_of([]), start=AT, end=START)


def test_the_reading_says_the_criterion_it_was_made_with_and_the_books_asked_for_are_the_ones_that_count(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    priced(db, w, window_fixtures(db)[:20])  # three books quote each of the 20
    asked = variants.run(db, family="corners_ft", variants=variants.variants_of(["recent-level:7"]), start=START, end=AT, min_books=2, min_ev=0.05, **TUNING)
    assert asked["criterion"] == {"min_books": 2, "min_ev": 0.05, "min_bets": bets.MIN_BETS, "dispersion_days": 40, "min_dispersion": 20, "min_past": 5,
                                  "main_band": list(variants.MAIN_BAND), "pick_lead_hours": 24.0, "references": [name for name, _ in versus.REFERENCES]}
    assert asked["bets"]["criterion"] == {"min_bets": bets.MIN_BETS, "min_ev": 0.05, "min_books": 2, "pick": bets.PICK_REF, "close": bets.CLOSE_REF}
    assert asked["variants"]["as-is"]["versus"]["close"]["total"]["main"]["n"] == 20
    four = variants.run(db, family="corners_ft", variants=variants.variants_of([]), start=START, end=AT, min_books=4, **TUNING)
    assert four["criterion"]["min_books"] == 4 and four["variants"]["as-is"]["versus"] == {}, "three books are not a consensus when four are asked for"
