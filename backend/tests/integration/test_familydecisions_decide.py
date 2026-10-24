"""The decision layer for a family in a real database (plan F11): the forecasts of the counts and the prices the books quoted go through the ten
filters of the pipeline, in shadow, under a version of their own.

The pure parts are in tests/unit/test_familydecisions_decide.py. Here: a match is forecast, three books price its corners, and a pass of the families
writes one row of ``intel.decisions`` under ``decision-fam-v1`` with no pick, in research and with no stake; a second pass writes nothing; a
price captured after the moment of the decision is never read; a market of two books, or with no value, is not judged; and the core layer
neither sees these rows nor writes anything because of them."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.families import forecast
from fbi.familydecisions import decide as fd
from fbi.intel import decision
from fbi.odds.quote_taxonomy import sync_definitions
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT, catalogue, played, run, upcoming
from .test_families_score import price as quote_prices

pytestmark = pytest.mark.integration

KICKOFF = AT + timedelta(days=1)
NOW = AT + timedelta(hours=1)
"""The moment of the decision: an hour after the forecasts were written, 23 hours before the kick-off."""
LINE = "10.5"


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def over_p(db: psycopg.Connection[Any], fixture_id: int, line: str = LINE) -> float:
    """What the family said of the over of the corners at a line (the one forecast stored)."""
    return float(db.execute("SELECT p FROM models.match_forecasts WHERE fixture_id = %s AND version = %s AND market_key = 'CORNERS_OU' AND line = %s "
                            "AND selection = 'Over' AND model_name = 'family-corners_ft'", (fixture_id, forecast.VERSION, line)).fetchall()[0][0])


class Market:
    """The prices of the corners of one match: an extraction, the definition of the provider's bet, and the books that quote it."""

    def __init__(self, db: psycopg.Connection[Any], w: World, fixture_id: int, *, like: Market | None = None) -> None:
        self.db, self.w, self.fid = db, w, fixture_id
        self.extraction: int
        if like is not None:  # another match of the same extraction
            self.extraction = like.extraction
            return
        sync_definitions(db, names={})
        db.execute("UPDATE market.market_definitions SET market_key = 'CORNERS_OU' WHERE provider_bet_id = 45 AND scope = 'prematch'")
        self.extraction = int(db.execute(
            "INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, stamped_by, status) "
            "VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", (w.hash, AT - timedelta(hours=4))).fetchall()[0][0])

    def quote(self, book: int, over: float, under: float, when: datetime, line: str = LINE) -> None:
        quote_prices(self.db, self.extraction, self.fid, book, str(over), str(under), line, when)

    def pays(self, value: float, *, books: int = 3, when: datetime = AT - timedelta(hours=3), line: str = LINE) -> tuple[float, float]:
        """``books`` books quote the over ``value`` above what the forecast says of it, with a margin of 6 %: (the over, the under)."""
        over = round((1.0 + value) / over_p(self.db, self.fid, line), 2)
        under = round(1.0 / (1.06 - 1.0 / over), 2)
        for book in self.w.books(books):
            self.quote(book, over, under, when, line)
        return over, under

    def read(self, at: datetime) -> None:
        """The odds of the match were read at ``at``: the newest consensus the layer of the market keeps (the age of the price)."""
        self.db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, "
                        "overround, best_odds, best_bookmaker_id) VALUES (%s, 'OU', 'Over', 2.5, %s, 'shin', 0.5, 3, 0.05, 2.0, %s)",
                        (self.fid, at, self.w.books(1)[0]))


def scene(db: psycopg.Connection[Any], w: World, *, value: float = 0.10, books: int = 3) -> tuple[int, Market, tuple[float, float]]:
    """A match 23 hours away that the families forecast, and ``books`` books that quote the corners above the model's own price."""
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    market = Market(db, w, fid)
    prices = market.pays(value, books=books)
    market.read(AT + timedelta(minutes=30))
    return fid, market, prices


def rows(db: psycopg.Connection[Any], fixture_id: int) -> list[dict[str, Any]]:
    cur = db.cursor()
    cur.execute("SELECT decision_version, pick_id, known_at, checkpoint, market_key, selection, line, model_name, odds::float8, bookmaker_id, price_at, "
                "n_bookmakers, p_model::float8, p_cal, p_market::float8, ev_raw::float8, ev_cal, state, reasons, premium, parlay_eligible, score, "
                "stake_units::float8, filters, input_hash FROM intel.decisions WHERE fixture_id = %s ORDER BY known_at, id", (fixture_id,))
    names = [c.name for c in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def test_a_pass_writes_the_decision_of_the_family_under_its_own_version_with_no_pick_and_no_stake(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, (over, under) = scene(db, w)
    report, evaluated = fd.decide_families(db, at=NOW)
    assert report.fixtures == 1 and report.forecasts > 0 and report.priced_selections == 2, report
    assert (report.candidates, report.evaluated, report.written) == (1, 1, 1), "only the line the books priced, and only its over"
    assert report.by_family == {"CORNERS": 1} and report.by_state == {"INVESTIGACION": 1}

    [r] = rows(db, fid)
    assert r["decision_version"] == fd.VERSION == "decision-fam-v1" and r["pick_id"] is None
    assert (r["market_key"], r["selection"], float(r["line"]), r["model_name"]) == ("CORNERS_OU", "Over", 10.5, "family-corners_ft")
    assert r["state"] == "INVESTIGACION" and r["stake_units"] == 0.0 and not r["premium"] and not r["parlay_eligible"] and r["score"] is None
    assert r["known_at"] == NOW and r["checkpoint"] == "T-24h", "23 hours before the kick-off"
    assert r["odds"] == pytest.approx(over) and r["bookmaker_id"] == w.books(1)[0], "the best price, and on a tie the lowest book"
    assert r["n_bookmakers"] == 3 and r["price_at"] == AT + timedelta(minutes=30), "the age of the price is when the odds were last read"
    p = over_p(db, fid)
    assert r["p_model"] == pytest.approx(p, abs=1e-6) and r["p_cal"] is None and r["ev_cal"] is None, "no calibrator: the raw number is all there is"
    assert r["ev_raw"] == pytest.approx(over * p - 1, abs=1e-5) and r["ev_raw"] >= fd.MIN_EV
    assert r["p_market"] == pytest.approx((1 / over) / (1 / over + 1 / under), abs=1e-6), "the fair probability of the books, margin out"
    assert {"not_calibrated", fd.REASON_RESEARCH} <= set(r["reasons"]) and fd.REASON_CAPPED not in r["reasons"]
    by_key = {f["key"]: f for f in r["filters"]}
    assert set(by_key) == {"family", "data", "model", "market", "calibration", "ev", "context", "risk", "correlation", "price", "final"}
    assert by_key["model"]["ok"] is True and by_key["model"]["data"]["calibration"] == "UNCALIBRATED", "the width of an interval is not asked of a family"
    assert by_key["model"]["data"]["forecast_id"] and by_key["market"]["ok"] is True and by_key["calibration"]["ok"] is False
    assert [f["n"] for f in r["filters"]] == sorted(f["n"] for f in r["filters"])
    assert [(e.state, e.stake.units) for e in evaluated] == [("INVESTIGACION", 0.0)]
    assert db.execute("SELECT count(*) FROM intel.decisions WHERE decision_version <> %s", (fd.VERSION,)).fetchone() == (0,), "nothing under the core version"
    assert db.execute("SELECT count(*) FROM picks.picks").fetchone() == (0,), "and no pick is born from a family"


def test_a_second_pass_writes_nothing_until_something_moves(db: psycopg.Connection[Any], w: World) -> None:
    fid, market, (over, _) = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    assert fd.decide_families(db, at=NOW)[0].written == 0, "the same moment twice"
    assert fd.decide_families(db, at=NOW + timedelta(hours=1))[0].written == 0, "an hour later, at the same checkpoint, with the same prices"
    assert len(rows(db, fid)) == 1

    for book in w.books(3):  # the books pay 8 % more for the over: a move of the price beyond the threshold of the layer
        market.quote(book, round(over * 1.08, 2), 1.50, AT + timedelta(hours=2))
    market.read(AT + timedelta(hours=2, minutes=5))
    assert fd.decide_families(db, at=AT + timedelta(hours=3))[0].written == 1
    first, second = rows(db, fid)
    assert second["odds"] == pytest.approx(round(over * 1.08, 2)) and second["known_at"] == AT + timedelta(hours=3)
    assert first["odds"] == pytest.approx(over), "the first row stays as it was: append-only"

    later = KICKOFF - timedelta(hours=11)  # another checkpoint (T-12h), the same prices
    assert fd.decide_families(db, at=later)[0].written == 1
    assert rows(db, fid)[-1]["checkpoint"] == "T-12h" and len(rows(db, fid)) == 3


def test_a_price_captured_after_the_moment_of_the_decision_is_never_read(db: psycopg.Connection[Any], w: World) -> None:
    fid, market, (over, _) = scene(db, w)
    [book] = w.books(4)[3:]
    market.quote(book, 9.00, 1.10, AT + timedelta(hours=2))  # a fourth book, captured an hour after the decision
    report = fd.decide_families(db, at=NOW)[0]
    assert report.written == 1
    [r] = rows(db, fid)
    assert r["n_bookmakers"] == 3 and r["odds"] == pytest.approx(over), "the price of an hour later was not known"

    market.read(AT + timedelta(hours=2, minutes=5))
    assert fd.decide_families(db, at=AT + timedelta(hours=3))[0].written == 1
    last = rows(db, fid)[-1]
    assert last["n_bookmakers"] == 4 and last["odds"] == pytest.approx(9.0)
    assert last["state"] == "RECHAZADO" and "price_outlier" in last["reasons"], "an absurd price is refused for a family as for a pick"
    assert fd.REASON_RESEARCH in last["reasons"] and last["stake_units"] == 0.0


def test_a_market_of_two_books_or_with_no_value_is_not_judged(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w, books=2)
    report = fd.decide_families(db, at=NOW)[0]
    assert report.priced_selections == 2 and report.candidates == 0 and report.written == 0, "two books are not a consensus"
    assert rows(db, fid) == []


def test_a_price_that_pays_no_more_than_the_model_says_is_not_a_candidate(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w, value=-0.05)
    report = fd.decide_families(db, at=NOW)[0]
    assert report.priced_selections == 2 and report.candidates == 0 and report.written == 0
    assert rows(db, fid) == []


def test_a_selection_the_database_refuses_costs_that_selection_and_nothing_else(db: psycopg.Connection[Any], w: World,
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

    real, calls = decision.store, []

    def flaky(conn: psycopg.Connection[Any], e: decision.Evaluated, **kw: Any) -> int | None:
        calls.append(e.key[0])
        if len(calls) == 1:
            conn.execute("SELECT 1 / 0")  # the database refuses: the transaction is aborted until the savepoint is rolled back
        return real(conn, e, **kw)

    monkeypatch.setattr(decision, "store", flaky)
    report = fd.decide_families(db, at=NOW)[0]
    assert (report.candidates, report.evaluated, report.written, report.failed) == (2, 1, 1, 1), report
    assert len(report.errors) == 1 and "DivisionByZero" in report.errors[0] and str(min(first, second)) in report.errors[0]
    written = {r["known_at"] for f in (first, second) for r in rows(db, f)}
    assert written == {NOW} and sum(len(rows(db, f)) for f in (first, second)) == 1, "the other selection was written, in the same transaction"
    assert db.execute("SELECT 1").fetchone() == (1,), "and the connection is still usable"
    monkeypatch.setattr(decision, "store", real)
    assert fd.decide_families(db, at=NOW)[0].written == 1, "the next pass writes what the first could not"


def test_a_dry_run_judges_and_writes_nothing(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w)
    report, evaluated = fd.decide_families(db, at=NOW, write=False)
    assert (report.candidates, report.evaluated, report.written) == (1, 1, 0) and len(evaluated) == 1
    assert rows(db, fid) == []


def test_only_the_matches_of_the_next_36_hours_that_have_not_kicked_off_are_read(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w)
    far = upcoming(w, 2, 3, when=timedelta(days=3))
    run(db, [far])
    assert fd.decide_families(db, at=NOW)[0].fixtures == 1, "the match three days out is not in the horizon"
    assert fd.decide_families(db, at=NOW, only=[far])[0].forecasts == 0
    assert fd.decide_families(db, at=NOW, only=[fid])[0].fixtures == 1
    assert fd.decide_families(db, at=KICKOFF + timedelta(hours=1))[0].forecasts == 0, "a match that has kicked off is not decided"
    assert fd.decide_families(db, at=NOW, horizon=timedelta(hours=10))[0].forecasts == 0, "and the horizon is a parameter"


def test_the_core_layer_neither_sees_the_rows_of_the_families_nor_writes_because_of_them(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    later = NOW + timedelta(hours=1)
    assert decision.read_world(db, [fid], at=later).previous == {}, "the previous decisions of the core layer are its own"
    [key] = decision.read_world(db, [fid], at=later, version=fd.VERSION).previous
    assert key[0] == fid and key[1] == "CORNERS_OU"
    report, evaluated = decision.decide(db, at=later)
    assert (report.candidates, report.written, evaluated) == (0, 0, []), "no pick, no candidate for the core layer"
    assert len(rows(db, fid)) == 1


def test_the_step_of_the_job_runs_the_pass_only_in_shadow_and_in_its_hour(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid, _, _ = scene(db, w)
    monkeypatch.setattr(fd, "environment", lambda: {})
    assert fd.run_step(db, at=NOW) == {"mode": "off"} and rows(db, fid) == []
    monkeypatch.setattr(fd, "environment", lambda: {fd.SWITCH: "shadow"})
    assert fd.run_step(db, at=NOW + timedelta(minutes=20)) == {"mode": "shadow", "waiting": 1} and rows(db, fid) == []
    out = fd.run_step(db, at=NOW)
    assert out["mode"] == "shadow" and out["written"] == 1 and out["candidates"] == 1 and out["by_state"] == {"INVESTIGACION": 1}
    assert len(rows(db, fid)) == 1
