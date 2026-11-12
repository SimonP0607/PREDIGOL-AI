"""The price rule, a yardstick in shadow (``fbi.decision.price_rule``, plan INT-A10, IA-054), without a database: the rule is decision-v1's
thresholds on the price alone, a selection is taken at the first moment it qualifies inside the window (never later, never by reading
ahead), its CLV is the system's one definition against a close observed AFTER the take, the intervals are deterministic, the gate says
«pendiente por muestra» below 300, the book's answers are read as of each ask, and the rule has no path to a pick. The SQL against a real
database is in tests/integration/test_price_rule.py."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from scripts import ia_price_rule as cli

from fbi.ai.calendar import day_start
from fbi.decision import book_price, price_rule
from fbi.decision.book_price import CAPTURE, REFRESH, TaggedAsk
from fbi.decision.engine import BOOK, CONSENSUS
from fbi.decision.price_rule import Closing, Measured, Quote, Taken
from fbi.intel import decision
from fbi.market import closing_reference, closing_value
from fbi.models.metrics import block_bootstrap_ci

from .test_decision_v2_book_price import FIXTURE, KO, PID, at, reader, stored

HOME = ("1X2", "Home", Decimal("0.00"))
LINE = Decimal("0.00")


def quote(odds: float = 2.2, p: float = 0.48, *, books: int = 6, price_at: datetime = KO - timedelta(hours=6),
          kind: str = CAPTURE) -> Quote:
    return Quote(odds, p, books, price_at, kind)


def taken(odds: float = 2.2, p: float = 0.48, *, fixture: int = FIXTURE, hours: float = 6.0, market: str = "1X2",
          kickoff: datetime = KO) -> Taken:
    moment = kickoff - timedelta(hours=hours)
    return Taken((fixture, market, "Home", LINE), kickoff, moment, quote(odds, p, price_at=moment), CONSENSUS)


# -- the rule ------------------------------------------------------------------------------------------------------------------------------

def test_the_rule_takes_a_best_price_that_beats_the_consensus_by_decision_v1s_value_threshold() -> None:
    moment = KO - timedelta(hours=6)
    fair = 0.5
    at_threshold = (1 + decision.EV_MIN) / fair  # exactly EV_MIN over the consensus without margin
    assert price_rule.verdict(quote(at_threshold, fair, price_at=moment), moment) is None
    assert price_rule.verdict(quote(at_threshold - 0.01, fair, price_at=moment), moment) == "price_below"
    assert price_rule.verdict(quote(2.0, fair, price_at=moment), moment) == "price_below", "the fair price itself is no value"
    assert quote(2.2, 0.5).price_ev == pytest.approx(0.10)


def test_the_rule_refuses_what_decision_v1s_market_stage_refuses_in_its_order() -> None:
    moment = KO - timedelta(hours=6)
    assert price_rule.verdict(quote(2.2, 0.5, books=decision.MIN_BOOKS - 1, price_at=moment), moment) == "thin_market"
    outlier = (1 + decision.MAX_PRICE_EDGE) / 0.5 + 0.02
    assert price_rule.verdict(quote(outlier, 0.5, price_at=moment), moment) == "price_outlier"
    old = moment - decision.MAX_PRICE_AGE - timedelta(minutes=1)
    assert price_rule.verdict(quote(2.2, 0.5, price_at=old), moment) == "price_stale"
    assert price_rule.verdict(quote(2.2, 0.5, price_at=moment - decision.MAX_PRICE_AGE), moment) is None, "three hours is still fresh"


def test_the_window_is_the_one_decision_v1_decides_in() -> None:
    assert price_rule.in_window(KO - decision.HORIZON, KO) and price_rule.in_window(KO - timedelta(minutes=decision.MIN_MINUTES), KO)
    assert not price_rule.in_window(KO - decision.HORIZON - timedelta(minutes=1), KO)
    assert not price_rule.in_window(KO - timedelta(minutes=decision.MIN_MINUTES - 1), KO)
    assert price_rule.MARKETS == ("1X2", "AH", "BTTS", "DC", "OU"), "decision-v1's core markets"


def test_a_selection_is_taken_at_the_first_moment_it_qualifies_and_never_again() -> None:
    t24, t12, t6, t48 = (KO - timedelta(hours=h) for h in (24, 12, 6, 48))
    moments = [
        (t6, {HOME: quote(2.3, 0.5, price_at=t6), ("OU", "Over", Decimal("2.5")): quote(2.2, 0.5, price_at=t6)}),
        (t48, {HOME: quote(2.5, 0.5, price_at=t48)}),  # outside the window: not a moment of the rule
        (t24, {HOME: quote(2.0, 0.5, price_at=t24)}),  # no value yet
        (t12, {HOME: quote(2.1, 0.5, price_at=t12), ("HT", "Home", LINE): quote(2.5, 0.5, price_at=t12)}),  # HT is no core market
    ]
    out = price_rule.first_taken(FIXTURE, KO, moments, source=CONSENSUS)
    assert set(out) == {(FIXTURE, *HOME), (FIXTURE, "OU", "Over", Decimal("2.50"))}
    home = out[(FIXTURE, *HOME)]
    assert (home.at, home.quote.best_odds, home.source) == (t12, 2.1, CONSENSUS), "the first moment inside the window, in time order"
    assert home.minutes_to_kickoff == 720.0


# -- the measure ---------------------------------------------------------------------------------------------------------------------------

def test_the_clv_is_the_systems_one_definition_against_a_close_observed_after_the_take() -> None:
    t = taken(2.2, 0.48)
    close = Closing(0.50, KO - timedelta(minutes=10), book_price.VERSION)
    m = price_rule.measure(t, close)
    assert m.clv == pytest.approx(closing_value.clv(2.2, 0.50)) == pytest.approx(0.10) and m.missing is None
    assert m.close_minutes_to_kickoff == 10.0


def test_a_close_that_is_the_take_itself_or_older_measures_nothing_and_is_counted() -> None:
    t = taken(2.2, 0.48, hours=3)
    same = price_rule.measure(t, Closing(0.48, t.quote.price_at, closing_reference.REFERENCE))
    assert (same.clv, same.missing) == (None, price_rule.NOT_LATER), "a snapshot is not measured against itself"
    none = price_rule.measure(t, None)
    assert (none.clv, none.missing) == (None, price_rule.NO_CLOSE)
    assert price_rule.measure(t, None, missing="withdrawn").missing == "withdrawn"


def measured(n: int, *, clv: float = 0.02, matches: int | None = None, start: datetime = KO) -> list[Measured]:
    """``n`` measured selections over ``matches`` matches (one per day), CLV alternating around ``clv``."""
    out: list[Measured] = []
    for i in range(n):
        f = i % (matches or n)
        kickoff = start + timedelta(days=f)
        t = taken(2.2, 0.48, fixture=1000 + f, kickoff=kickoff, market=("1X2", "OU")[i % 2])
        value = clv + (0.01 if i % 2 else -0.01)
        out.append(Measured(t, Closing(0.5, kickoff - timedelta(minutes=10), book_price.VERSION), value, None))
    return out


def summary(ms: Sequence[Measured]) -> dict[str, Any]:
    return price_rule.summarise(ms, source=CONSENSUS, since=KO - timedelta(days=30), until=KO + timedelta(days=30),
                                population={"matches": 10})


def test_the_report_gives_the_mean_clv_with_its_intervals_by_match_and_by_day_and_they_are_deterministic() -> None:
    ms = measured(40, matches=10)
    a, b = summary(ms), summary(ms)
    assert a == b, "a fixed seed: the same rows give the same report"
    values = [m.clv for m in ms if m.clv is not None]
    mean, low, high, blocks = block_bootstrap_ci(values, [m.taken.key[0] for m in ms], draws=price_rule.REPS, level=price_rule.LEVEL,
                                                 seed=price_rule.SEED)
    assert a["clv"]["by_match"] == {"mean": round(mean, 6), "low": round(low, 6), "high": round(high, 6), "blocks": 10}
    assert blocks == 10 and a["clv"]["by_day"]["blocks"] == 10 and low <= mean <= high
    assert a["clv"]["positive"] == 1.0 and a["clv"]["definition"] == closing_value.VERSION
    assert set(a["by_market"]) == {"1X2", "OU"} and a["by_market"]["1X2"]["selections"] == 20
    assert a["price_ev_at_take"]["mean"] == pytest.approx(2.2 * 0.48 - 1) and a["p_drift_pp"]["mean"] == pytest.approx(2.0)
    assert a["close"]["minutes_to_kickoff"]["p50"] == 10.0 and a["by_lead_hours"] == {"6-12": a["by_lead_hours"]["6-12"]}
    assert a["role"] == "reference" and a["rule"]["ev_min"] == decision.EV_MIN


def test_the_gate_asks_for_three_hundred_measured_selections_and_says_pending_below() -> None:
    assert summary(measured(299, matches=50))["gate"] == {"min_selections": 300, "selections": 299, "verdict": price_rule.PENDING}
    assert summary(measured(300, matches=50))["gate"]["verdict"] == price_rule.REPORT
    unmeasured = [Measured(taken(), None, None, price_rule.NO_CLOSE)] * 5
    out = summary(measured(10) + unmeasured)
    assert out["gate"]["selections"] == 10 and out["taken"]["selections"] == 15, "a selection without a CLV is counted, never measured"
    assert out["measured"]["without_clv"] == {"no_close": 5}


def test_an_empty_window_has_no_figures_not_zeros() -> None:
    out = summary([])
    assert out["clv"]["by_match"] == {"mean": None, "low": None, "high": None, "blocks": 0} and out["clv"]["positive"] is None
    assert out["gate"]["verdict"] == price_rule.PENDING and out["by_market"] == {}


def test_the_bands_of_value_and_lead_cover_every_take() -> None:
    assert price_rule._band(decision.EV_MIN, price_rule.EV_BANDS) == "0.02-0.05"
    assert price_rule._band(decision.MAX_PRICE_EDGE, price_rule.EV_BANDS) == "0.1-0.25", "the outlier limit closes the last band"
    assert price_rule._band(36.0, price_rule.LEAD_BANDS) == "24-36" and price_rule._band(0.2, price_rule.LEAD_BANDS) == "0-3"


# -- the captures (the long history) -------------------------------------------------------------------------------------------------------

def test_the_captured_rows_become_the_moments_of_each_match() -> None:
    t6, t3 = KO - timedelta(hours=6), KO - timedelta(hours=3)
    rows = [{"fixture_id": FIXTURE, "market_key": "1X2", "selection": "Home", "line": Decimal("0"), "as_of": t3, "best_odds": 2.2,
             "p_fair": 0.48, "n_bookmakers": 6},
            {"fixture_id": FIXTURE, "market_key": "OU", "selection": "Over", "line": Decimal("2.5"), "as_of": t6, "best_odds": 2.1,
             "p_fair": 0.5, "n_bookmakers": 5}]
    found = price_rule.consensus_moments(rows)
    assert [m for m, _ in found[FIXTURE]] == [t6, t3]
    assert found[FIXTURE][1][1][HOME] == Quote(2.2, 0.48, 6, t3, CAPTURE)


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.rows: list[dict[str, Any]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> None:
        self.conn.seen.append(sql)
        self.rows = self.conn.answer(sql, dict(params or {}))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    """The four reads of the long history, answered from a list of consensus rows with the SQL's own meaning."""

    def __init__(self, kickoffs: dict[int, datetime], rows: list[dict[str, Any]]) -> None:
        self.kickoffs, self.rows = kickoffs, rows
        self.seen: list[str] = []

    def cursor(self, **_: Any) -> FakeCursor:
        return FakeCursor(self)

    def window(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        lead = params["lead"]
        return [r for r in self.rows if r["fixture_id"] in params["ids"] and r["market_key"] in params["markets"]
                and self.kickoffs[r["fixture_id"]] - params["horizon"] <= r["as_of"] <= self.kickoffs[r["fixture_id"]] - lead]

    def answer(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if sql == price_rule.FIXTURES_SQL:
            return [{"id": f, "kickoff_at": k} for f, k in sorted(self.kickoffs.items()) if params["since"] <= k < params["until"]]
        if sql == price_rule.SEEN_SQL:
            by: dict[int, list[dict[str, Any]]] = {}
            for r in self.window(params):
                by.setdefault(r["fixture_id"], []).append(r)
            return [{"fixture_id": f, "selections": len({(r["market_key"], r["selection"], r["line"]) for r in rs}),
                     "moments": len({r["as_of"] for r in rs})} for f, rs in by.items()]
        if sql == price_rule.PRICES_SQL:
            return [r for r in self.window(params) if r["n_bookmakers"] >= params["min_books"]
                    and params["ev_low"] <= r["best_odds"] * r["p_fair"] - 1 <= params["ev_high"]]
        if sql == closing_reference.CLOSE_SQL:
            out = []
            for i, key in enumerate(zip(params["fixtures"], params["markets"], params["selections"], params["lines"], strict=True), 1):
                before = [r for r in self.rows if (r["fixture_id"], r["market_key"], r["selection"], r["line"]) == key
                          and r["as_of"] < self.kickoffs[key[0]]]
                if before:
                    last = max(before, key=lambda r: r["as_of"])
                    out.append({"ord": i, "p_fair": last["p_fair"], "best_odds": last["best_odds"], "as_of": last["as_of"],
                                "kickoff_at": self.kickoffs[key[0]]})
            return out
        raise AssertionError(f"an unexpected statement: {sql[:60]}")


def row(fixture: int, as_of: datetime, odds: float, p: float, *, selection: str = "Home", books: int = 6) -> dict[str, Any]:
    return {"fixture_id": fixture, "market_key": "1X2", "selection": selection, "line": LINE, "as_of": as_of, "best_odds": odds,
            "p_fair": p, "n_bookmakers": books}


def test_the_long_history_takes_from_the_captures_and_measures_against_the_systems_close() -> None:
    kickoffs = {1: KO, 2: KO + timedelta(days=1)}
    rows = [row(1, KO - timedelta(hours=24), 2.0, 0.5), row(1, KO - timedelta(hours=12), 2.2, 0.48),  # taken at T-12h
            row(1, KO - timedelta(hours=3), 2.05, 0.5),  # the close (the last capture before kick-off)
            row(2, KO + timedelta(days=1) - timedelta(hours=3), 2.3, 0.47),  # taken at its last capture: nothing after it
            row(2, KO + timedelta(days=1) - timedelta(hours=6), 2.0, 0.5, selection="Away", books=2)]
    conn = cast(psycopg.Connection[Any], FakeConn(kickoffs, rows))
    out = price_rule.report(conn, since=KO - timedelta(days=1), until=KO + timedelta(days=2))
    assert out["population"] == {"matches": 2, "matches_with_price": 2, "selections_with_price": 3, "moments": 5}
    assert out["taken"]["selections"] == 2 and out["measured"]["selections"] == 1
    assert out["measured"]["without_clv"] == {"not_later": 1}
    assert out["clv"]["by_match"]["mean"] == pytest.approx(round(2.2 * 0.5 - 1, 6))
    assert out["close"]["minutes_to_kickoff"]["p50"] == 180.0 and out["close"]["reference"] == {closing_reference.REFERENCE: 1}
    assert out["taken"]["minutes_to_kickoff"]["p50"] == 720.0 and out["taken"]["by_market"] == {"1X2": 2}


def test_the_report_refuses_an_unknown_source_and_the_book_without_its_store() -> None:
    nothing = cast(psycopg.Connection[Any], None)
    with pytest.raises(ValueError, match="source must be one of"):
        price_rule.report(nothing, since=KO, until=KO, source="mercado")
    with pytest.raises(ValueError, match="RAW store"):
        price_rule.report(nothing, since=KO, until=KO, source=BOOK)


# -- the book (the refreshes) ----------------------------------------------------------------------------------------------------------------

def body(outsider: float) -> dict[str, Any]:
    """An answer of ``/odds?fixture=`` with the match's 1X2 at three bookmakers that keep their margin: two near the consensus and one whose
    home price is ``outsider`` (its draw and away shortened so that it keeps a margin)."""
    prices = {8: (2.00, 3.50, 3.90), 11: (2.05, 3.40, 3.80), 16: (outsider, 3.00, 3.20)}
    return {"get": "odds", "results": 1, "response": [{"fixture": {"id": PID}, "update": "2026-11-05T14:00:00+00:00", "bookmakers": [
        {"id": b, "name": f"Book {b}", "bets": [{"id": 1, "name": "Match Winner", "values": [
            {"value": "Home", "odd": f"{h:.2f}"}, {"value": "Draw", "odd": f"{d:.2f}"}, {"value": "Away", "odd": f"{a:.2f}"}]}]}
        for b, (h, d, a) in prices.items()]}]}


def test_the_book_is_read_as_of_each_ask_and_measured_against_its_last_answer_before_kick_off(tmp_path: Path) -> None:
    a = stored(tmp_path, body(2.05), "a")  # the capture: no value at the best price
    b = stored(tmp_path, body(2.40), "b")  # a refresh: one book pays 2.40, clear value over the consensus
    c = stored(tmp_path, body(2.20), "c")  # the last refresh before kick-off: the close
    asks = [TaggedAsk(CAPTURE, at(360), 1, a.payload_hash), TaggedAsk(REFRESH, at(120), 1, b.payload_hash),
            TaggedAsk(REFRESH, at(60), 1, b.payload_hash), TaggedAsk(REFRESH, at(9), 1, c.payload_hash),
            TaggedAsk(REFRESH, at(5), 1, c.payload_hash)]  # inside the last ten minutes: no moment of the rule, still the close
    r = reader(tmp_path, asks, [a, b, c])
    moments = price_rule.book_moments(r, FIXTURE)
    assert [m for m, _ in moments] == [at(360), at(120), at(60)], "asks inside the window only (at 9 and 5 min the window is over)"
    assert price_rule.verdict(moments[0][1][HOME], at(360)) == "price_below"
    found, seen = price_rule.measure_book(r)
    home = next(m for m in found if m.taken.key[1:] == HOME)
    assert (home.taken.at, home.taken.quote.confirmed_by, home.taken.quote.best_odds) == (at(120), REFRESH, 2.40)
    assert home.taken.quote.price_ev == pytest.approx(r.answer_at(FIXTURE, at(120)).prices[HOME].best_odds
                                                      * r.answer_at(FIXTURE, at(120)).prices[HOME].p_fair - 1)
    close = book_price.close_of(r.close(FIXTURE), KO)[HOME]
    assert home.close is not None and home.close.observed_at == at(5) and home.close.reference == book_price.VERSION
    assert home.clv == pytest.approx(closing_value.clv(2.40, close.p_fair)) and home.missing is None
    assert (seen["matches_with_price"], seen["moments"], seen["selections_with_price"]) == (1, 3, 3)


def test_a_book_that_withdrew_its_prices_before_kick_off_leaves_the_take_without_a_close(tmp_path: Path) -> None:
    b = stored(tmp_path, body(2.40), "b")
    r = reader(tmp_path, [TaggedAsk(REFRESH, at(120), 1, b.payload_hash), TaggedAsk(REFRESH, at(9), 0, None)], [b])
    found, _ = price_rule.measure_book(r)
    home = next(m for m in found if m.taken.key[1:] == HOME)
    assert (home.clv, home.missing) == (None, "withdrawn")


# -- the command ---------------------------------------------------------------------------------------------------------------------------

def test_the_command_reads_bogota_days_never_after_now_and_read_only() -> None:
    args = cli.build_parser().parse_args(["report", "--since", "2026-10-12", "--until", "2026-11-11", "--price", "book", "--raw", "/r"])
    assert (args.price, args.raw, args.as_json) == (BOOK, "/r", False)
    assert cli.build_parser().parse_args(["report", "--since", "2026-10-12", "--until", "2026-11-11"]).price == CONSENSUS
    late = datetime(2026, 11, 11, 15, tzinfo=UTC)
    lo, hi = cli.bounds(cli.parse_day("2026-11-10"), cli.parse_day("2026-11-12"), at=late)
    assert lo == day_start(cli.parse_day("2026-11-10")) and lo.utcoffset() == timedelta(hours=-5) and hi == late
    with pytest.raises(ValueError, match="after"):
        cli.bounds(cli.parse_day("2026-11-10"), cli.parse_day("2026-11-10"), at=late)
    assert "default_transaction_read_only=on" in cli.READ_ONLY and "statement_timeout=95000" in cli.READ_ONLY


def test_the_command_prints_the_report_with_its_gate() -> None:
    text = cli.render(summary(measured(12, matches=4)))
    assert text.startswith("price-rule-v1 (reference, never a pick) from consensus")
    assert "gate: 12 measured selections, 300 needed: pending_sample" in text and "CLV (clv-v1): by match +" in text


# -- no path to a pick ---------------------------------------------------------------------------------------------------------------------

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"
MODULE = SRC / "decision" / "price_rule.py"


def test_the_rule_writes_nothing_and_never_reads_picks_or_decisions() -> None:
    sql = [v for k, v in vars(price_rule).items() if k.endswith("_SQL") or k == "WINDOW"]
    assert len(sql) >= 4
    for text in sql:
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|MERGE|ALTER|CREATE|DROP)\b", text, re.IGNORECASE), text
        assert not re.search(r"\b(picks|intel|ai)\.", text), "the rule reads fixtures and prices, nothing that decides"


def imports_the_rule(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import) and any(a.name == "fbi.decision.price_rule" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module == "fbi.decision.price_rule"
                                                 or (node.module == "fbi.decision" and any(a.name == "price_rule" for a in node.names))):
            return True
    return False


def test_the_rule_calls_no_stage_of_decision_v2_nor_any_writer_and_nothing_but_its_command_imports_it() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    used = {(n.value.id, n.attr) for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    forbidden = {"decide", "decide_all", "assess", "finish", "evaluate", "correlate", "store", "select_day", "replay_day", "priced"}
    assert not {(m, a) for m, a in used if a in forbidden}, "the rule computes its own measure from prices, never a decision"
    root = SRC.parents[1]
    importers = sorted(str(p.relative_to(root)) for p in [*SRC.rglob("*.py"), *(root / "scripts").rglob("*.py"), *(root / "apps").rglob("*.py")]
                       if "__pycache__" not in p.parts and imports_the_rule(p))
    assert importers == ["scripts/ia_price_rule.py"], importers
