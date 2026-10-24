"""Plan F11 - the decision layer for a family (``fbi.intel.family_decision``): the pure parts, checked against numbers worked by hand.

The pass against a real database is in tests/integration/test_family_decision.py."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.intel import decision
from fbi.intel import family_decision as fd
from fbi.intel import stake as staking

D = Decimal
AT = datetime(2035, 3, 1, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(hours=20)


# ── the books ────────────────────────────────────────────────────────────────────────────────────────────────────

def quote(book: int, selection: str, odds: float, *, fixture: int = 1, line: str = "9.5", key: str = "CORNERS_OU", kind: str = "over_under",
          seen: datetime = AT - timedelta(hours=2)) -> fd.AsOfQuote:
    return fd.AsOfQuote("now", fixture, book, key, kind, selection, D(line), odds, seen)


def pair(book: int, over: float, under: float, **kw: Any) -> list[fd.AsOfQuote]:
    """The over and the under of one line at one book."""
    return [quote(book, "Over", over, **kw), quote(book, "Under", under, **kw)]


def test_the_price_is_the_consensus_of_the_complete_books_and_the_best_price_with_who_quoted_it() -> None:
    quotes = (pair(1, 1.80, 2.10) + pair(2, 1.90, 2.00, seen=AT - timedelta(minutes=30)) + pair(3, 2.05, 1.85)
              + pair(4, 1.30, 1.30)                       # a margin of 54 %: not a price
              + [quote(5, "Over", 2.50)])                 # half a book
    priced = fd.price(quotes)
    over = priced[(1, "CORNERS_OU", D("9.5"), "Over")]
    margins = [1 / 1.80 + 1 / 2.10, 1 / 1.90 + 1 / 2.00, 1 / 2.05 + 1 / 1.85]
    shares = [(1 / 1.80) / margins[0], (1 / 1.90) / margins[1], (1 / 2.05) / margins[2]]
    assert over.books == 3 and over.p_fair == pytest.approx(sum(shares) / 3) and over.overround == pytest.approx(sum(margins) / 3)
    assert (over.best_odds, over.best_bookmaker_id) == (2.05, 3), "the highest price any complete book quoted, and its book"
    assert over.newest_quote == AT - timedelta(minutes=30)
    under = priced[(1, "CORNERS_OU", D("9.5"), "Under")]
    assert under.p_fair == pytest.approx(1 - over.p_fair) and (under.best_odds, under.best_bookmaker_id) == (2.10, 1)
    assert len(priced) == 2, "the half book and the broken one add nothing"


def test_on_a_tied_best_price_the_lowest_bookmaker_wins_whatever_the_order_of_the_quotes() -> None:
    quotes = pair(7, 2.00, 1.90) + pair(3, 2.00, 1.90) + pair(5, 1.95, 1.95)
    forward, backward = fd.price(quotes), fd.price(list(reversed(quotes)))
    key = (1, "CORNERS_OU", D("9.5"), "Over")
    assert forward[key].best_bookmaker_id == backward[key].best_bookmaker_id == 3 and forward[key] == backward[key]


def test_each_line_and_each_match_has_its_own_price() -> None:
    quotes = (pair(1, 1.80, 2.10) + pair(1, 1.50, 2.60, line="8.5") + pair(1, 1.90, 2.00, fixture=2)
              + [quote(1, s, o, line="0", key="CORNERS_1X2", kind="one_x_two") for s, o in (("Home", 2.0), ("Draw", 3.5), ("Away", 4.0))])
    priced = fd.price(quotes)
    assert {(*k[:2], str(k[2])) for k in priced} == {(1, "CORNERS_OU", "9.5"), (1, "CORNERS_OU", "8.5"), (2, "CORNERS_OU", "9.5"),
                                                      (1, "CORNERS_1X2", "0")}
    assert priced[(1, "CORNERS_1X2", D(0), "Draw")].books == 1


# ── the forecasts ────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE: Mapping[str, Any] = {"kickoff_at": KICKOFF, "status_short": "NS", "status_group": "scheduled", "home_team_id": 1, "away_team_id": 2,
                              "competition_season_id": 1, "competition_id": 1, "competition_name": "League", "home_name": "A", "away_name": "B"}


def forecast(selection: str = "Over", p: float = 0.55, *, line: str = "9.5", key: str = "CORNERS_OU", family: str = "CORNERS", fixture: int = 1,
             model: str = "family-corners_ft", lo: float | None = None, hi: float | None = None, id: int = 100) -> fd.Forecast:
    return fd.Forecast(id, fixture, family, model, 7, key, D(line), selection, p, p, lo, hi, "UNCALIBRATED", AT - timedelta(hours=5),
                       AT - timedelta(hours=5), FIXTURE)


def priced(odds: float = 2.05, *, books: int = 3, p_fair: float = 0.5, newest: datetime = AT - timedelta(hours=1)) -> fd.Priced:
    return fd.Priced(p_fair, odds, 3, books, 1.03, newest)


def keyed(fixture: int, key: str, line: str, selection: str, found: fd.Priced) -> dict[fd.PriceKey, fd.Priced]:
    return {(fixture, key, D(line), selection): found}


def test_a_selection_the_model_sees_value_in_at_the_best_price_is_a_candidate() -> None:
    found = fd.candidates([forecast()], keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), {})
    assert len(found) == 1
    c = found[0]
    assert c.believed == pytest.approx(2.05 * 0.55 - 1) and c.key == (1, "CORNERS_OU", "Over", D("9.50"))
    assert c.price_at == AT - timedelta(hours=1), "with no reading of the odds of the match, the newest quote is the age of the price"
    seen = {1: AT - timedelta(minutes=10)}
    assert fd.candidates([forecast()], keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), seen)[0].price_at == AT - timedelta(minutes=10), (
        "the age of the price is the last time the odds of the match were read: a price that did not change is not an old price")


@pytest.mark.parametrize("what,odds,books,line,key,family", [
    ("value below the floor", 1.85, 3, "9.5", "CORNERS_OU", "CORNERS"),       # 1.85 x 0.55 - 1 = 1.8 %
    ("two books are not a consensus", 2.05, 2, "9.5", "CORNERS_OU", "CORNERS"),
    ("a line that can push", 2.05, 3, "10", "CORNERS_OU", "CORNERS"),
    ("a quarter line", 2.05, 3, "10.25", "CORNERS_OU", "CORNERS"),
    ("a kind of bet the books have no consensus for", 2.05, 3, "0", "HTFT", "GOALS_HALF"),
    ("a key the catalogue does not have", 2.05, 3, "0", "FOO", "CORNERS"),
    ("a family that is not decided", 2.05, 3, "9.5", "CORNERS_OU", "REDS"),
])
def test_what_is_not_a_candidate(what: str, odds: float, books: int, line: str, key: str, family: str) -> None:
    f = forecast(line=line, key=key, family=family)
    assert fd.candidates([f], keyed(1, key, line, "Over", priced(odds, books=books)), {}) == [], what


def test_a_selection_no_book_priced_is_not_a_candidate_and_the_floor_belongs_to_the_spec() -> None:
    assert fd.candidates([forecast()], {}, {}) == []
    low = {"CORNERS": fd.FamilySpec("CORNERS", min_ev=0.30), "CARDS": fd.FamilySpec("CARDS", min_books=4)}
    assert fd.candidates([forecast()], keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), {}, specs=low) == [], "12.8 % is below a floor of 30 %"
    assert fd.candidates([forecast()], keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), {}, specs={"CORNERS": fd.FamilySpec("CORNERS", min_ev=0.10)})


def test_the_width_of_an_interval_is_judged_only_where_there_is_one() -> None:
    narrow = {"CORNERS": fd.FamilySpec("CORNERS", max_width=0.5)}
    found = keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05))
    assert fd.candidates([forecast()], found, {}, specs=narrow), "a family that states no interval cannot be refused for its width"
    assert fd.candidates([forecast(lo=0.25, hi=0.75)], found, {}, specs=narrow), "50 points is the widest allowed"
    assert fd.candidates([forecast(lo=0.125, hi=0.875)], found, {}, specs=narrow) == [], "75 points is too wide"
    assert fd.candidates([forecast(lo=0.125, hi=0.875)], found, {}), "and with no limit in the spec, nothing is judged"


def test_only_the_best_line_of_each_market_of_each_match_stays_and_a_tie_is_broken_the_same_way_each_time() -> None:
    books = {**keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), **keyed(1, "CORNERS_OU", "10.5", "Over", priced(2.60)),
             **keyed(1, "CORNERS_OU", "8.5", "Over", priced(1.95)), **keyed(1, "CORNERS_OU", "10.5", "Under", priced(2.40))}
    rows = [forecast("Over", 0.55, line="9.5"), forecast("Over", 0.55, line="10.5"), forecast("Over", 0.55, line="8.5"),
            forecast("Under", 0.45, line="10.5")]
    # 9.5: 2.05 x 0.55 - 1 = 12.8 %   10.5 over: 2.60 x 0.55 - 1 = 43.0 %   8.5: 7.3 %   10.5 under: 2.40 x 0.45 - 1 = 8.0 %
    [c] = fd.candidates(rows, books, {})
    assert (c.forecast.line, c.forecast.selection) == (D("10.5"), "Over")
    assert fd.candidates(list(reversed(rows)), books, {})[0].key == c.key, "whatever the order of the rows, the same line"
    # two lines with the same value: the larger (selection, line) wins, as it does in the simulated bets
    tie = {**keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.00)), **keyed(1, "CORNERS_OU", "10.5", "Over", priced(2.00))}
    pair_rows = [forecast("Over", 0.55, line="9.5"), forecast("Over", 0.55, line="10.5")]
    assert fd.candidates(pair_rows, tie, {})[0].forecast.line == fd.candidates(list(reversed(pair_rows)), tie, {})[0].forecast.line == D("10.5")


def test_a_market_of_another_model_or_another_match_is_its_own_slot() -> None:
    books = {**keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), **keyed(2, "CORNERS_OU", "9.5", "Over", priced(2.05)),
             **keyed(1, "CARDS_OU", "4.5", "Over", priced(2.10))}
    rows = [forecast(fixture=1), forecast(fixture=2, id=101), forecast(key="CARDS_OU", line="4.5", family="CARDS", model="family-cards_lines_ft", id=102)]
    found = fd.candidates(rows, books, {})
    assert [(c.forecast.fixture_id, c.forecast.key) for c in found] == [(1, "CARDS_OU"), (1, "CORNERS_OU"), (2, "CORNERS_OU")], "sorted, one per slot"


def test_the_candidate_is_read_by_the_judge_as_a_pick_with_no_pick() -> None:
    c = fd.candidates([forecast(id=77)], keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), {})[0]
    r = c.row()
    assert r["pick_id"] is None and r["forecast_id"] == 77 and r["interval_optional"] is True
    assert r["p_model"] == 0.55 and r["p_push"] == 0.0 and r["p_low"] is None and r["p_high"] is None
    assert r["data_cutoff_ts"] is None, "the age of a forecast that held is not an age to refuse it by"
    assert (r["best_odds"], r["best_bookmaker_id"], r["n_bookmakers"], r["p_fair"]) == (2.05, 3, 3, 0.5)
    assert r["kickoff_at"] == KICKOFF and r["market_key"] == "CORNERS_OU" and r["model_name"] == "family-corners_ft"


# ── the judge and the cap ────────────────────────────────────────────────────────────────────────────────────────

def evaluated(state: str, *, odds: float = 2.05, p_cal: float | None = None) -> decision.Evaluated:
    """A decision as the judge hands it over, with the filters it would have written for a family."""
    row = {**FIXTURE, "pick_id": None, "forecast_id": 100, "best_odds": odds, "p_push": 0.0, "p_model": 0.55, "interval_optional": True}
    filters = [decision._f("model", True, "family-corners_ft: p 0.550", n=2, model="family-corners_ft", model_version_id=7),
               decision._f("final", False, f"{state}: x", state, 10)]
    return decision.Evaluated((1, "CORNERS_OU", "Over", D("9.50")), row, "T-24h", state, [], filters, p_cal, None, None, 0.1, None, None, None,
                              None, staking.stake_for(state, p_cal, odds, 0.0), decision.Context("PENDING"))


def candidate() -> fd.Candidate:
    return fd.candidates([forecast(id=100)], keyed(1, "CORNERS_OU", "9.5", "Over", priced(2.05)), {})[0]


def test_whatever_the_filters_said_a_family_is_never_more_than_in_research_and_never_staked() -> None:
    for state in ("APROBADO", "CANDIDATO_PARLAY", "PICK_PREMIUM", "CAUTELA"):
        e = evaluated(state, p_cal=0.6)
        e.premium = e.parlay_eligible = True
        out = fd.finalise(e, candidate(), fd.SPECS["CORNERS"])
        assert out.state == "INVESTIGACION" and not out.premium and not out.parlay_eligible, state
        assert fd.REASON_CAPPED in out.reasons and fd.REASON_RESEARCH in out.reasons
        assert out.stake.units == 0.0, "a stake above research is the owner's to give"
    for state in ("INVESTIGACION", "RECHAZADO"):
        out = fd.finalise(evaluated(state), candidate(), fd.SPECS["CORNERS"])
        assert out.state == state and fd.REASON_CAPPED not in out.reasons and fd.REASON_RESEARCH in out.reasons
        assert out.stake.units == 0.0


def test_the_record_says_where_the_forecast_came_from_and_that_the_filter_of_the_match_does_not_apply() -> None:
    out = fd.finalise(evaluated("INVESTIGACION"), candidate(), fd.SPECS["CORNERS"])
    by_key = {f["key"]: f for f in out.filters}
    assert by_key["model"]["data"]["forecast_id"] == 100 and by_key["model"]["data"]["family"] == "CORNERS"
    assert by_key["model"]["data"]["calibration"] == "UNCALIBRATED" and by_key["model"]["data"]["forecast_known_at"] == (AT - timedelta(hours=5)).isoformat()
    assert by_key["model"]["data"]["forecast_cutoff"] == (AT - timedelta(hours=5)).isoformat()
    fam = by_key["family"]
    assert fam["ok"] is True and fam["n"] == 0 and fam["data"]["min_books"] == 3 and fam["data"]["min_ev"] == fd.MIN_EV
    assert fam["data"]["believed"] == pytest.approx(2.05 * 0.55 - 1, abs=1e-6) and "en investigación" in fam["why"] and "CORNERS" in fam["why"]
    assert by_key["correlation"]["ok"] is None and by_key["correlation"]["n"] == 8
    assert [f["n"] for f in out.filters] == sorted(f["n"] for f in out.filters), "the filters stay in the order of the ten"


def test_the_width_asked_of_a_family_is_written_in_its_filter_when_it_has_one() -> None:
    out = fd.finalise(evaluated("INVESTIGACION"), candidate(), fd.FamilySpec("CORNERS", max_width=0.2))
    assert "intervalo de 20 puntos" in next(f for f in out.filters if f["key"] == "family")["why"]


# ── the switch, the clock and the step of the job ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [(None, "off"), ("", "off"), ("off", "off"), ("shadow", "shadow"), (" Shadow ", "shadow"), ("SHADOW", "shadow"),
                                            ("on", "off"), ("enforce", "off"), ("1", "off")])
def test_the_switch_is_off_unless_it_says_shadow(monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str) -> None:
    monkeypatch.setattr(fd, "environment", lambda: {} if value is None else {fd.SWITCH: value})
    assert fd.mode() == expected


def test_the_pass_of_the_families_is_the_first_of_each_hour() -> None:
    day = datetime(2035, 3, 1, tzinfo=UTC)
    runs = [day + timedelta(hours=h, minutes=m) for h in range(24) for m in (2, 17, 32, 47)]
    assert sum(fd.due(at) for at in runs) == 24, "one pass an hour, whatever the phase of the quarter-hour job"
    assert [m for m in range(60) if fd.due(day + timedelta(minutes=m))] == list(range(15))


class _Conn:
    """A connection that records what it is asked and fails if it is used for anything else."""

    def __init__(self) -> None:
        self.rolled_back = 0

    def rollback(self) -> None:
        self.rolled_back += 1


def test_the_step_does_nothing_while_the_switch_is_off_and_waits_for_its_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the pass must not run")

    monkeypatch.setattr(fd, "decide_families", never)
    conn = _Conn()
    monkeypatch.setattr(fd, "environment", lambda: {})
    assert fd.run_step(conn, at=AT) == {"mode": "off"}  # type: ignore[arg-type]
    monkeypatch.setattr(fd, "environment", lambda: {fd.SWITCH: "shadow"})
    assert fd.run_step(conn, at=AT + timedelta(minutes=20)) == {"mode": "shadow", "waiting": 1}  # type: ignore[arg-type]
    assert conn.rolled_back == 0


def test_a_failure_of_the_pass_reaches_the_record_of_the_job_and_leaves_the_connection_to_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("the quotes could not be read")

    monkeypatch.setattr(fd, "environment", lambda: {fd.SWITCH: "shadow"})
    monkeypatch.setattr(fd, "decide_families", broken)
    conn = _Conn()
    with pytest.raises(RuntimeError, match="the quotes could not be read"):
        fd.run_step(conn, at=AT)  # type: ignore[arg-type]
    assert conn.rolled_back == 0, "the job closes the transaction of a step that failed, as it does for every step"


def test_the_step_hands_back_what_the_pass_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    report = fd.FamilyReport(forecasts=10, fixtures=2, priced_selections=6, candidates=3, evaluated=3, written=2, failed=1,
                             by_family={"CORNERS": 3}, by_state={"INVESTIGACION": 3}, by_reason={fd.REASON_RESEARCH: 3},
                             errors=[f"e{i}" for i in range(9)])
    monkeypatch.setattr(fd, "environment", lambda: {fd.SWITCH: "shadow"})
    monkeypatch.setattr(fd, "decide_families", lambda *_a, **_k: (report, []))
    out = fd.run_step(_Conn(), at=AT)  # type: ignore[arg-type]
    assert out == {"mode": "shadow", "forecasts": 10, "fixtures": 2, "priced": 6, "candidates": 3, "evaluated": 3, "written": 2, "failed": 1,
                   "by_family": {"CORNERS": 3}, "by_state": {"INVESTIGACION": 3}, "by_reason": {fd.REASON_RESEARCH: 3},
                   "errors": ["e0", "e1", "e2", "e3", "e4"]}, "the record carries the first five errors; the count says how many there were"


def test_the_versions_are_kept_apart() -> None:
    assert fd.VERSION == "decision-fam-v1" and fd.CORE_VERSION == "decision-v1" and fd.VERSION != fd.CORE_VERSION
    assert fd.SPECS.keys() == {"GOALS_HALF", "CORNERS", "CARDS", "YELLOW"} and fd.MIN_EV == 0.03
