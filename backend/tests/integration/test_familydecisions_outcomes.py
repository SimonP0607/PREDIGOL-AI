"""What became of a family's decision in a real database (plan F11): a decision is taken before the kick-off, the match is played, and the settlement
writes its outcome - the result by the rule of the market, the profit at the price taken, and the value against the close - under its own version.

The pure parts are in tests/unit/test_familydecisions_outcomes.py. Here: the decision of the corners of a match is settled once the statistics are there and
never before, a second pass writes nothing, a close of fewer than three books is no close, a price captured after the kick-off is never read, the
pipeline's decisions are neither settled by this module nor does their settlement see these, and a decision the database refuses costs only itself."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.familydecisions import decide as fd
from fbi.familydecisions import outcomes as fo
from fbi.intel import outcomes
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT, catalogue, played, run, upcoming
from .test_families_score import play
from .test_familydecisions_decide import KICKOFF, NOW, Market, scene

pytestmark = pytest.mark.integration

LATER = KICKOFF + timedelta(hours=31)
"""A pass after the wait (30 hours past the kick-off)."""


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.families import forecast

    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def decided(db: psycopg.Connection[Any], w: World, **kw: Any) -> tuple[int, Market, tuple[float, float]]:
    """A match 23 hours away whose corners three books price above the model's own price, and the decision a pass of the families takes on it."""
    fid, market, prices = scene(db, w, **kw)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    return fid, market, prices


def stored(db: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    cur = db.cursor()
    cur.execute("SELECT o.decision_id, o.settled_at, o.result_status, o.profit_flat, o.profit_staked, o.close_p_fair, o.close_odds, o.close_as_of, "
                "o.close_minutes_to_ko, o.clv, o.version, o.computed_at, d.fixture_id, d.odds FROM intel.decision_outcomes o "
                "JOIN intel.decisions d ON d.id = o.decision_id ORDER BY o.decision_id")
    names = [c.name for c in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def test_a_decision_is_settled_on_the_counts_of_the_match_at_the_price_taken_and_against_the_close(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, (over, under) = decided(db, w)
    play(w, fid)  # 11 corners: the over of 10.5 won
    report = fo.settle(db, at=LATER)
    assert (report.open, report.settled, report.ungradable, report.unreadable, report.no_close, report.failed) == (1, 1, 0, 0, 0, 0), report
    assert report.by_result == {"win": 1}

    [r] = stored(db)
    assert r["version"] == fo.VERSION == "outcome-fam-v1" and r["settled_at"] == LATER == r["computed_at"]
    assert r["result_status"] == "win" and r["profit_flat"] == Decimal(str(over)) - 1 and r["profit_staked"] == 0, "a family has no stake"
    fair = (1 / over) / (1 / over + 1 / under)
    assert float(r["close_p_fair"]) == pytest.approx(fair, abs=1e-6) and float(r["close_odds"]) == pytest.approx(over), "three equal books"
    assert float(r["clv"]) == pytest.approx(over * fair - 1, abs=2e-6)
    assert r["close_as_of"] == AT + timedelta(minutes=30) and r["close_minutes_to_ko"] == 23 * 60 + 30, "the last reading of the odds before the kick-off"
    assert db.execute("SELECT count(*) FROM picks.pick_results").fetchone() == (0,), "no pick was ever involved"


def test_a_second_pass_writes_nothing_and_a_row_is_never_rewritten(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    assert fo.settle(db, at=LATER).settled == 1
    [first] = stored(db)
    again = fo.settle(db, at=LATER + timedelta(hours=1))
    assert (again.open, again.settled) == (0, 0), "a decision with an outcome is not looked at again"
    assert stored(db) == [first]
    assert db.execute("SELECT count(*) FROM intel.decision_outcomes WHERE version <> %s", (fo.VERSION,)).fetchone() == (0,)


def test_a_decision_waits_for_the_statistics_and_an_unknown_count_is_never_a_loss(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    w.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fid,))
    w.result(fid, (3, 1), ht=(2, 0), settled=KICKOFF + timedelta(hours=3), kickoff=KICKOFF)  # the result is known; the statistics never came
    too_soon = fo.settle(db, at=KICKOFF + timedelta(hours=20))
    assert (too_soon.open, too_soon.settled) == (0, 0), "30 hours after the kick-off, not before"
    no_corners = fo.settle(db, at=LATER)
    assert (no_corners.open, no_corners.settled, no_corners.ungradable) == (1, 0, 1), "the corners of the match are unknown"
    assert stored(db) == [], "nothing written: an unknown is not a zero, and not a loss"

    for side, corners in (("home", 7), ("away", 4)):  # the statistics arrive late
        w.team_stats(fid, side, corners=corners, yellow_cards=2, red_cards=0)
    late = fo.settle(db, at=LATER + timedelta(hours=2))
    assert (late.open, late.settled, late.ungradable) == (1, 1, 0)
    assert stored(db)[0]["result_status"] == "win"


def test_the_under_of_a_line_the_count_went_over_is_a_loss_at_minus_one(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid, corners=(3, 3))  # 6 corners: the over of 10.5 lost
    assert fo.settle(db, at=LATER).by_result == {"loss": 1}
    [r] = stored(db)
    assert r["result_status"] == "loss" and r["profit_flat"] == -1
    assert r["clv"] is not None, "the value of the price does not depend on how the match ended"


def test_a_close_of_fewer_than_three_complete_books_is_no_close_and_the_result_is_written_all_the_same(db: psycopg.Connection[Any], w: World) -> None:
    fid, market, (over, _) = decided(db, w)
    [book] = w.books(1)
    market.quote(book, 20.0, 1.70, KICKOFF - timedelta(hours=1))  # a book whose margin is no longer believable (0.64): not a price
    play(w, fid)
    report = fo.settle(db, at=LATER)
    assert (report.settled, report.no_close) == (1, 1)
    [r] = stored(db)
    assert r["result_status"] == "win" and r["profit_flat"] == Decimal(str(over)) - 1
    assert (r["clv"], r["close_p_fair"], r["close_odds"], r["close_as_of"], r["close_minutes_to_ko"]) == (None, None, None, None, None)


def test_a_price_captured_at_or_after_the_kick_off_is_never_the_close(db: psycopg.Connection[Any], w: World) -> None:
    fid, market, (over, under) = decided(db, w)
    [fourth] = w.books(4)[3:]
    market.quote(fourth, 9.00, 1.10, KICKOFF)  # captured at the very kick-off
    market.quote(fourth, 9.00, 1.10, KICKOFF + timedelta(hours=1))
    market.read(KICKOFF + timedelta(minutes=5))  # and the odds were read once more, after the kick-off
    play(w, fid)
    fo.settle(db, at=LATER)
    [r] = stored(db)
    fair = (1 / over) / (1 / over + 1 / under)
    assert float(r["close_p_fair"]) == pytest.approx(fair, abs=1e-6) and float(r["close_odds"]) == pytest.approx(over), "three books, not four"
    assert r["close_as_of"] == AT + timedelta(minutes=30), "and the last reading before the kick-off, not the one after it"


@pytest.mark.parametrize(("new_over", "new_under", "better"), [(1.70, 2.20, True), (2.60, 1.60, False)])
def test_the_close_is_the_price_in_force_at_the_kick_off_not_the_one_of_the_decision(db: psycopg.Connection[Any], w: World, new_over: float,
                                                                                      new_under: float, better: bool) -> None:
    fid, market, (over, _) = decided(db, w)
    for book in w.books(3):  # the books change their minds after the decision
        market.quote(book, new_over, new_under, KICKOFF - timedelta(hours=2))
    market.read(KICKOFF - timedelta(hours=1, minutes=50))
    play(w, fid)
    fo.settle(db, at=LATER)
    [r] = stored(db)
    p_close = (1 / new_over) / (1 / new_over + 1 / new_under)
    assert float(r["close_p_fair"]) == pytest.approx(p_close, abs=1e-6) and float(r["close_odds"]) == pytest.approx(new_over)
    assert float(r["clv"]) == pytest.approx(over * p_close - 1, abs=2e-6), "the price taken at the closing fair probability"
    assert (float(r["clv"]) > 0) is better, "the market moved to the selection (a better price than the close) or away from it"
    assert r["close_minutes_to_ko"] == 110 and r["close_as_of"] == KICKOFF - timedelta(hours=1, minutes=50)


def test_the_decisions_of_the_pipeline_are_neither_settled_here_nor_do_the_families_reach_its_settlement(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    db.execute("INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, pick_id, "
               "model_name, model_version_id, odds, bookmaker_id, price_at, n_bookmakers, p_model, p_low, p_high, p_push, p_cal, calibrator_id, "
               "calibrator_role, p_market, ev_raw, edge_raw, ev_cal, edge_cal, filters, state, reasons, premium, parlay_eligible, score, score_version, "
               "score_components, stake_units, stake_version, stake_components, context_status, context, review_id, evidence_ids, input_hash, "
               "code_version) SELECT %s, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, pick_id, model_name, "
               "model_version_id, odds, bookmaker_id, price_at, n_bookmakers, p_model, p_low, p_high, p_push, p_cal, calibrator_id, calibrator_role, "
               "p_market, ev_raw, edge_raw, ev_cal, edge_cal, filters, state, reasons, premium, parlay_eligible, score, score_version, "
               "score_components, stake_units, stake_version, stake_components, context_status, context, review_id, evidence_ids, 'pipeline', code_version "
               "FROM intel.decisions WHERE fixture_id = %s", (fd.CORE_VERSION, fid))
    assert db.execute("SELECT count(*) FROM intel.decisions").fetchone() == (2,)
    play(w, fid)
    report = fo.settle(db, at=LATER)
    assert (report.open, report.settled) == (1, 1), "only the family's"
    [r] = stored(db)
    assert db.execute("SELECT decision_version FROM intel.decisions WHERE id = %s", (r["decision_id"],)).fetchone() == (fd.VERSION,)
    assert outcomes.settle_decisions(db, at=LATER) == 0, "the pipeline's settlement needs a pick's result, and these have none"
    assert len(stored(db)) == 1


def test_a_decision_the_database_refuses_costs_that_decision_and_nothing_else(db: psycopg.Connection[Any], w: World,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue(db)
    played(w)
    first, second = upcoming(w, 0, 1), upcoming(w, 2, 3)
    run(db, [first, second])
    one = Market(db, w, first)
    one.pays(0.10)
    one.read(AT + timedelta(minutes=30))
    two = Market(db, w, second, like=one)
    two.pays(0.10)
    two.read(AT + timedelta(minutes=30))
    assert fd.decide_families(db, at=NOW)[0].written == 2
    play(w, first)
    play(w, second)

    real, calls = fo._insert, []

    def flaky(conn: psycopg.Connection[Any], o: fo.Outcome, *, at: datetime) -> bool:
        calls.append(o.decision_id)
        if len(calls) == 1:
            raise psycopg.errors.CheckViolation("the database refuses this one")
        return real(conn, o, at=at)

    monkeypatch.setattr(fo, "_insert", flaky)
    report = fo.settle(db, at=LATER)
    assert (report.open, report.settled, report.failed) == (2, 1, 1), report
    assert len(report.errors) == 1 and "CheckViolation" in report.errors[0]
    assert [r["decision_id"] for r in stored(db)] == [calls[1]], "the other decision was written"
    monkeypatch.setattr(fo, "_insert", real)
    assert fo.settle(db, at=LATER + timedelta(hours=1)).settled == 1, "and the one refused is tried again on the next pass"
    assert len(stored(db)) == 2


def test_the_step_does_nothing_while_the_switch_is_off_and_settles_in_shadow(db: psycopg.Connection[Any], w: World,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    monkeypatch.delenv(fd.SWITCH, raising=False)
    assert fo.run_step(db, at=LATER) == {"mode": "off"} and stored(db) == []
    monkeypatch.setenv(fd.SWITCH, "shadow")
    out = fo.run_step(db, at=LATER)
    assert out["mode"] == "shadow" and (out["open"], out["settled"], out["failed"]) == (1, 1, 0) and out["by_result"] == {"win": 1}
    assert len(stored(db)) == 1
