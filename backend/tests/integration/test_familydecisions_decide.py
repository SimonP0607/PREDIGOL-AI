"""The decision layer for a family in a real database (plan F11): the forecasts of the counts and the prices the books quoted go through the ten
filters of the pipeline, in shadow, under a version of their own.

The pure parts are in tests/unit/test_familydecisions_decide.py. Here: a match is forecast, three books price its corners, and a pass of the families
writes one row of ``intel.decisions`` under ``decision-fam-v1`` with no pick, in research and with no stake; a second pass writes nothing; a
price captured after the moment of the decision is never read; a market of two books, or with no value, is not judged; and the core layer
neither sees these rows nor writes anything because of them."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.families import forecast
from fbi.familydecisions import decide as fd
from fbi.familydecisions import research
from fbi.intel import decision, factors
from fbi.odds.quote_taxonomy import sync_definitions
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT, catalogue, played, referees, run, upcoming, whistle

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


def over_p(db: psycopg.Connection[Any], fixture_id: int, line: str = LINE, *, key: str = "CORNERS_OU", model: str = "family-corners_ft") -> float:
    """What the family said of the over of a market at a line (the one forecast stored): the corners unless told otherwise."""
    return float(db.execute("SELECT p FROM models.match_forecasts WHERE fixture_id = %s AND version = %s AND market_key = %s AND line = %s "
                            "AND selection = 'Over' AND model_name = %s", (fixture_id, forecast.VERSION, key, line, model)).fetchall()[0][0])


class Market:
    """The prices of a market of counts of one match (the corners unless told otherwise): an extraction, the definition of the provider's bet, and
    the books that quote it."""

    def __init__(self, db: psycopg.Connection[Any], w: World, fixture_id: int, *, like: Market | None = None, key: str = "CORNERS_OU", bet: int = 45,
                 model: str = "family-corners_ft") -> None:
        self.db, self.w, self.fid = db, w, fixture_id
        self.key, self.bet, self.model = key, bet, model
        self.extraction: int
        if like is not None:  # another match of the same extraction
            self.extraction = like.extraction
            return
        sync_definitions(db, names={})
        db.execute("UPDATE market.market_definitions SET market_key = %s WHERE provider_bet_id = %s AND scope = 'prematch'", (key, bet))
        self.extraction = int(db.execute(
            "INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, stamped_by, status) "
            "VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", (w.hash, AT - timedelta(hours=4))).fetchall()[0][0])

    def quote(self, book: int, over: float, under: float, when: datetime, line: str = LINE) -> None:
        """One book's over/under of the market at an instant."""
        definition = self.db.execute("SELECT id FROM market.market_definitions WHERE provider_bet_id = %s AND scope = 'prematch'", (self.bet,)).fetchall()[0][0]
        for selection, odds in (("Over", over), ("Under", under)):
            self.db.execute("INSERT INTO market.odds_quotes (fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, captured_at, "
                            "minutes_to_ko, extraction_id) VALUES (%s, %s, %s, %s, %s, %s, %s, 60, %s)",
                            (self.fid, book, definition, selection, line, str(odds), when, self.extraction))

    def pays(self, value: float, *, books: int = 3, when: datetime = AT - timedelta(hours=3), line: str = LINE) -> tuple[float, float]:
        """``books`` books quote the over ``value`` above what the forecast says of it, with a margin of 6 %: (the over, the under)."""
        over = round((1.0 + value) / over_p(self.db, self.fid, line, key=self.key, model=self.model), 2)
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
                "stake_units::float8, filters, input_hash, context_status FROM intel.decisions WHERE fixture_id = %s ORDER BY known_at, id", (fixture_id,))
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
    assert set(by_key) == {"family", "data", "model", "market", "calibration", "ev", "context", "risk", "correlation", "price", "final", "research"}
    assert by_key["model"]["ok"] is True and by_key["model"]["data"]["calibration"] == "UNCALIBRATED", "the width of an interval is not asked of a family"
    assert by_key["model"]["data"]["forecast_id"] and by_key["market"]["ok"] is True and by_key["calibration"]["ok"] is False
    assert [f["n"] for f in r["filters"]] == sorted(f["n"] for f in r["filters"])
    request = by_key["research"]
    assert request["ok"] is None and request["n"] == 0 and request["data"] == record_of(r), "informational: it passes nothing and refuses nothing"
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


# ── the formal request for research ──────────────────────────────────────────────────────────────────────────────

def record_of(row: dict[str, Any]) -> dict[str, Any]:
    """The request for research a decision carries among its filters (empty when it has none)."""
    found = [f for f in row["filters"] if f["key"] == research.KEY]
    assert len(found) <= 1
    return dict(found[0]["data"]) if found else {}


def need_of(row: dict[str, Any], key: str) -> dict[str, Any]:
    return next(n for n in record_of(row)["needs"] if n["key"] == key)


def cards_scene(db: psycopg.Connection[Any], w: World, *, value: float = 0.10) -> tuple[int, Market, str]:
    """A match 23 hours away whose cards the families forecast, and three books that quote the line closest to even above the model's own price."""
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    lines = db.execute("SELECT line, p FROM models.match_forecasts WHERE fixture_id = %s AND version = %s AND market_key = 'CARDS_OU' "
                       "AND selection = 'Over' AND model_name = 'family-cards_lines_ft'", (fid, forecast.VERSION)).fetchall()
    assert lines, "the families forecast the cards of the match"
    line = str(min(lines, key=lambda r: abs(float(r[1]) - 0.5))[0])
    market = Market(db, w, fid, key="CARDS_OU", bet=80, model="family-cards_lines_ft")
    market.pays(value, line=line)
    market.read(AT + timedelta(minutes=30))
    return fid, market, line


def test_a_decision_says_what_it_lacks_and_that_nothing_serves_it(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [r] = rows(db, fid)
    data = record_of(r)
    assert r["context_status"] in {"PENDING", "AI_OFF"}, "no AI read the match"
    assert data["version"] == "research-fam-v1" and data["family"] == "CORNERS" and data["registry"] == "read"
    assert [(n["key"], n["state"], n["source"], n["since"]) for n in data["needs"]] == [
        ("lineups", "MISSING", "provider", None), ("context", "MISSING", "search", None)], "no line-up was read and no AI read the match"
    assert data["open"] == ["lineups", "context"] and data["levels"] == [1, 2, 3] and data["searches"] == 3
    assert data["served"] is False and data["unserved"] == "family_shadow"
    assert data["factors"] == [{"factor": "tactics_profile", "version": factors.BY_KEY["tactics_profile"].version, "status": "DESCRIPTIVE"}]
    [asked] = [f for f in r["filters"] if f["key"] == research.KEY]
    assert asked["why"].startswith("pedir investigación: le falta las alineaciones confirmadas (lo trae el proveedor) y el contexto de fuera")
    assert db.execute("SELECT count(*) FROM ai.fixture_passes").fetchone() == (0,), "and nothing was asked of the AI"


def test_the_line_ups_are_known_from_the_moment_they_were_read_and_not_before(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w)
    read = NOW - timedelta(minutes=20)
    w.sheet(fid, "home", "4-3-3", [11, 12, 13], fetched=read)
    w.sheet(fid, "away", "4-4-2", [21, 22, 23], fetched=NOW + timedelta(minutes=30))  # read after the decision
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [r] = rows(db, fid)
    assert need_of(r, "lineups") == {"key": "lineups", "state": "KNOWN", "source": "provider", "topics": [], "levels": [], "since": read.isoformat()}
    assert record_of(r)["open"] == ["context"], "the sheet that was read by then is the one that counts"


def test_line_ups_read_after_the_moment_of_the_decision_are_missing_then_and_known_at_the_next_row(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w)
    after = NOW + timedelta(minutes=30)
    w.sheet(fid, "home", "4-3-3", [11, 12, 13], fetched=after)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    later = KICKOFF - timedelta(hours=11)  # another checkpoint (T-12h): another row
    assert fd.decide_families(db, at=later)[0].written == 1
    first, second = rows(db, fid)
    assert need_of(first, "lineups")["state"] == "MISSING" and need_of(first, "lineups")["since"] is None, "not known at the first decision"
    assert need_of(second, "lineups")["state"] == "KNOWN" and need_of(second, "lineups")["since"] == after.isoformat()
    assert first["known_at"] == NOW and second["known_at"] == later, "append-only: the first row says what was known then"


def test_the_context_need_is_the_word_of_the_decision_layer(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid, _, _ = scene(db, w)
    monkeypatch.setattr(decision, "context_status", lambda **kw: "FULL")
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [r] = rows(db, fid)
    assert need_of(r, "context")["state"] == "KNOWN" and record_of(r)["open"] == ["lineups"]
    assert record_of(r)["searches"] == 0 and record_of(r)["unserved"] is None, "what only the provider can bring needs no search"
    monkeypatch.setattr(decision, "context_status", lambda **kw: "PARTIAL")
    assert fd.decide_families(db, at=KICKOFF - timedelta(hours=11))[0].written == 1
    assert need_of(rows(db, fid)[-1], "context")["state"] == "PARTIAL" and record_of(rows(db, fid)[-1])["open"] == ["lineups", "context"]


def test_the_referee_is_the_newest_sighting_by_the_moment_and_only_if_the_provider_still_had_one(db: psycopg.Connection[Any], w: World) -> None:
    alpha, bravo = referees(db, "Alpha", "Bravo")
    f1, f2, f3, f4 = (upcoming(w, 0, 1, when=timedelta(days=d)) for d in (1, 2, 3, 4))
    whistle(db, f1, alpha, NOW)                                    # seen at the very moment: it counts
    whistle(db, f2, alpha, NOW + timedelta(hours=1))               # seen an hour after
    whistle(db, f3, alpha, NOW - timedelta(hours=4))               # seen, and taken off by the provider an hour before
    db.execute("INSERT INTO core.fixture_officials (fixture_id, role, observed_at, alias_id) VALUES (%s, 'referee', %s, NULL)",
               (f3, NOW - timedelta(hours=1)))
    whistle(db, f4, alpha, NOW - timedelta(hours=5))               # one referee, and another named after the moment
    whistle(db, f4, bravo, NOW + timedelta(hours=1))
    everything = [f1, f2, f3, f4]
    assert fd.read_referees(db, everything, at=NOW) == {f1: NOW, f4: NOW - timedelta(hours=5)}
    assert fd.read_referees(db, everything, at=NOW - timedelta(hours=2)) == {f3: NOW - timedelta(hours=4), f4: NOW - timedelta(hours=5)}, (
        "two hours earlier the provider had not taken him off")
    assert fd.read_referees(db, everything, at=NOW + timedelta(hours=2)) == {f1: NOW, f2: NOW + timedelta(hours=1), f4: NOW + timedelta(hours=1)}
    assert fd.read_referees(db, [], at=NOW) == {}
    assert fd.read_referees(db, [f2], at=NOW - timedelta(days=1)) == {}
    assert fd.read_referees(db, [f1], at=NOW) == {f1: NOW}, "only the matches asked for are read, not every sighting of the history"


def test_the_cards_ask_for_the_referee_and_know_him_from_the_moment_he_was_designated(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = cards_scene(db, w)
    [alpha] = referees(db, "Alpha")
    seen = NOW + timedelta(hours=2)
    whistle(db, fid, alpha, seen)  # on the books before the first pass, but seen after its moment
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [first] = rows(db, fid)
    assert first["market_key"] == "CARDS_OU" and first["model_name"] == "family-cards_lines_ft"
    assert record_of(first)["family"] == "CARDS" and record_of(first)["open"] == ["referee", "context"]
    assert need_of(first, "referee") == {"key": "referee", "state": "MISSING", "source": "provider", "topics": [], "levels": [], "since": None}
    assert [h["factor"] for h in record_of(first)["factors"]] == ["scenarios"]

    later = KICKOFF - timedelta(hours=11)
    assert fd.decide_families(db, at=later)[0].written == 1
    second = rows(db, fid)[-1]
    assert need_of(second, "referee")["state"] == "KNOWN" and need_of(second, "referee")["since"] == seen.isoformat()
    assert record_of(second)["open"] == ["context"]
    assert need_of(rows(db, fid)[0], "referee")["state"] == "MISSING", "the first row still says what was known then"


def test_the_factors_are_read_as_of_the_moment_of_the_decision(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = scene(db, w)
    decided = NOW + timedelta(hours=1)
    factors.promote(db, "tactics_profile", experiment="F12-tactics-01", result={"matches": 2000, "logloss_delta": -0.003},
                    reason="the observable tactics beat the form on the test matches", who="Simon", at=decided)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    assert fd.decide_families(db, at=KICKOFF - timedelta(hours=11))[0].written == 1
    first, second = rows(db, fid)
    tactics = factors.BY_KEY["tactics_profile"].version
    assert record_of(first)["factors"] == [{"factor": "tactics_profile", "version": tactics, "status": "DESCRIPTIVE"}], "validated an hour later"
    assert record_of(second)["factors"] == [{"factor": "tactics_profile", "version": tactics, "status": "VALIDATED"}]
    assert second["state"] == "INVESTIGACION" and second["stake_units"] == 0.0 and second["ev_raw"] == pytest.approx(first["ev_raw"]), (
        "a validated factor moves nothing of the decision of a family")


def test_a_read_that_fails_costs_the_record_and_never_the_decision(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid, _, _ = scene(db, w)

    def broken(conn: psycopg.Connection[Any], fixtures: Any, *, at: datetime) -> Any:
        conn.execute("SELECT 1 / 0")  # the database refuses: the savepoint of the read must be rolled back

    monkeypatch.setattr(fd, "read_referees", broken)
    report = fd.decide_families(db, at=NOW)[0]
    assert (report.written, report.failed) == (1, 0), report
    [r] = rows(db, fid)
    assert research.KEY not in {f["key"] for f in r["filters"]} and r["state"] == "INVESTIGACION"
    assert db.execute("SELECT 1").fetchone() == (1,), "and the connection is still usable"


def test_a_registry_that_cannot_be_read_is_said_in_the_record_and_every_factor_is_descriptive(db: psycopg.Connection[Any], w: World,
                                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    fid, _, _ = scene(db, w)

    def broken(conn: psycopg.Connection[Any], *, at: datetime) -> Any:
        conn.execute("SELECT 1 / 0")

    monkeypatch.setattr(factors, "standings", broken)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [r] = rows(db, fid)
    assert record_of(r)["registry"] == "unread" and {h["status"] for h in record_of(r)["factors"]} == {"DESCRIPTIVE"}
    assert db.execute("SELECT 1").fetchone() == (1,)


def test_the_request_changes_nothing_of_the_decision_in_a_real_pass(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid, _, _ = scene(db, w)
    w.sheet(fid, "home", "4-3-3", [11, 12, 13], fetched=NOW - timedelta(minutes=20))
    [with_record] = fd.decide_families(db, at=NOW, write=False)[1]

    def broken(conn: psycopg.Connection[Any], fixtures: Any, *, at: datetime) -> Any:
        conn.execute("SELECT 1 / 0")

    monkeypatch.setattr(fd, "read_referees", broken)
    [without] = fd.decide_families(db, at=NOW, write=False)[1]
    assert any(f["key"] == research.KEY for f in with_record.filters) and all(f["key"] != research.KEY for f in without.filters)
    for field in dataclasses.fields(decision.Evaluated):
        if field.name != "filters":
            assert getattr(with_record, field.name) == getattr(without, field.name), field.name
    assert [f for f in with_record.filters if f["key"] != research.KEY] == without.filters
