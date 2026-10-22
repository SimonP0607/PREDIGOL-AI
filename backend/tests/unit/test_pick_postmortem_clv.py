"""Plan F0, defect 7, in the post-mortem by selection (pm-v2) and in the notes the day's learning draws from it.

pm-v2 called "CLV" the price against the SAME bookmaker's close (margin in both prices) and judged "the market moved
against it" by it. That judgement is right for a price move and stays exactly as it was; what changes is the name, and that
the CLV proper (the price at the closing fair probability) is shown beside it and is what the learning averages."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from fbi.ai.learning import notes_for
from fbi.ai.pick_postmortem import MOVED_AGAINST, Facts, answers, classify, stored_clv, win_quality


def facts(*, settled: str = "loss", odds: float | None = 2.0, close_odds: float | None = 2.0,
          p_close: float | None = 0.50, p_market: float | None = 0.50, p_model: float | None = 0.52,
          decision: str | None = "APPROVE") -> Facts:
    return Facts(settled=settled, decision=decision, p_model=p_model, p_market=p_market, p_close=p_close, odds=odds,
                 close_odds=close_odds)


# ── the two numbers of one selection ──────────────────────────────────────────

def test_a_facts_object_carries_the_price_move_and_the_clv_apart() -> None:
    f = facts(odds=2.10, close_odds=2.00, p_close=0.47)
    assert f.price_move == pytest.approx(0.05)
    assert f.clv == pytest.approx(-0.013)
    assert f.price_move != f.clv


def test_without_the_reference_a_number_is_missing_not_zero() -> None:
    assert facts(close_odds=None).price_move is None and facts(close_odds=None).clv is not None
    assert facts(p_close=None).clv is None and facts(p_close=None).price_move is not None
    assert facts(odds=None).price_move is None and facts(odds=None).clv is None


# ── the class of a loss is decided by the PRICE MOVE, as it always was ────────

def test_a_margin_is_not_a_market_move() -> None:
    """The regression behind the defect. The price taken is the price the bookmaker closed at (it did not move) and the
    consensus did not move either: the CLV is minus the margin, about -5 %. Read against the price-move threshold of
    -3 % it would be a MARKET_ERROR - 'the market knew something' - on every selection priced at a margin."""
    f = facts(odds=1.90, close_odds=1.90, p_close=0.50, p_market=0.50)
    assert f.price_move == 0.0
    assert f.clv is not None and f.clv < MOVED_AGAINST
    assert classify(f) == "NORMAL_VARIANCE", "nothing moved: a fair loss"


def test_a_price_that_moved_against_is_a_market_error() -> None:
    f = facts(odds=2.10, close_odds=2.20, p_close=0.455, p_market=0.50)  # 2.10 / 2.20 - 1 = -4.5 %
    assert f.price_move is not None and f.price_move == pytest.approx(-0.0455, abs=1e-4)
    assert f.price_move <= MOVED_AGAINST
    assert classify(f) == "MARKET_ERROR"


def test_the_closing_probability_moving_three_points_against_is_still_a_market_error() -> None:
    f = facts(odds=2.0, close_odds=2.0, p_close=0.46, p_market=0.50)
    assert f.price_move == 0.0
    assert classify(f) == "MARKET_ERROR"


def test_a_win_is_lucky_only_if_the_price_moved_against_and_the_model_was_far_above() -> None:
    lucky = facts(settled="win", odds=2.10, close_odds=2.20, p_close=0.42, p_market=0.50, p_model=0.60)
    assert win_quality(lucky) == "LUCKY"
    margin_only = facts(settled="win", odds=1.90, close_odds=1.90, p_close=0.50, p_market=0.50, p_model=0.60)
    assert margin_only.clv is not None and margin_only.clv < MOVED_AGAINST
    assert win_quality(margin_only) == "EARNED", "a negative CLV from the margin does not make a win lucky"


# ── what the post-mortem says about it ────────────────────────────────────────

def test_the_question_odds_moved_answers_by_the_price_move_and_shows_both() -> None:
    f = facts(odds=1.90, close_odds=1.90, p_close=0.50)
    a = answers(f, classify(f), score=(0, 1), label="X")["odds_moved"]
    assert a["answer"] == "estable", "the price did not move"
    assert a["data"] == {"price_move": 0.0, "close_odds": 1.9, "clv_v1": pytest.approx(-0.05)}
    assert "clv" not in a["data"], "the old key meant a price move: it is not reused for the CLV"
    assert "misma casa" in a["detail"] and "CLV frente al cierre justo -5.0 %" in a["detail"]

    moved = facts(odds=2.10, close_odds=2.20, p_close=0.455)
    assert answers(moved, classify(moved), score=(0, 1), label="X")["odds_moved"]["answer"] == "en contra"
    toward = facts(odds=2.40, close_odds=2.30, p_close=0.43)
    assert answers(toward, classify(toward), score=(0, 1), label="X")["odds_moved"]["answer"] == "a favor"
    nothing = facts(odds=2.0, close_odds=None, p_close=None)
    assert answers(nothing, classify(nothing), score=(0, 1), label="X")["odds_moved"]["answer"] == "sin datos"


# ── reading a stored post-mortem ──────────────────────────────────────────────

def test_the_clv_of_a_stored_row_comes_from_its_odds_and_closing_probability() -> None:
    assert stored_clv(Decimal("2.10"), {"model": {"data": {"p_close": 0.47}}}) == pytest.approx(-0.013)
    assert stored_clv(2.10, {"model": {"data": {"p_close": None}}}) is None
    assert stored_clv(None, {"model": {"data": {"p_close": 0.47}}}) is None
    assert stored_clv(2.10, {}) is None and stored_clv(2.10, None) is None
    assert stored_clv(2.10, {"model": None}) is None and stored_clv(2.10, {"model": {"data": None}}) is None


def test_a_legacy_row_is_never_read_as_clv() -> None:
    """Rows written before clv-v1 keep a price move under the name ``clv`` (column and JSON). The reader ignores both."""
    legacy_answers = {"model": {"data": {"p_close": 0.47}},
                      "odds_moved": {"answer": "a favor", "data": {"clv": 0.05, "close_odds": 2.0}}}
    assert stored_clv(2.10, legacy_answers) == pytest.approx(-0.013), "from the odds and the close, never from 0.05"


# ── the day's learning note ───────────────────────────────────────────────────

def row(i: int, *, decision: str = "APPROVE", odds: float = 2.0, p_close: float | None = 0.48,
        price_move: float | None = 0.02) -> dict[str, Any]:
    return {"id": i, "fixture_id": i, "market_key": "1X2", "selection": "Home", "line": Decimal(0), "roles": [],
            "decision": decision, "settled": "win", "verdict": "approved_won", "classification": None,
            "odds": Decimal(str(odds)), "close_odds": None, "price_move": None if price_move is None else Decimal(str(price_move)),
            "p_model": 0.5, "p_market": 0.45, "answers": {"model": {"data": {"p_close": p_close}}}, "evidence": {},
            "match": f"M{i}"}


def market_note(rows: list[dict[str, Any]]) -> Any:
    return {n.kind: n for n in notes_for(rows, [], [])}["market"]


def test_the_market_note_averages_the_clv_and_counts_the_moves_apart() -> None:
    """Each approved selection: odds 2.00 against a closing fair 0.48 (CLV -4 %), while its bookmaker's price moved +2 %
    in its favour. The old note averaged the +2 % and called it 'CLV medio'."""
    note = market_note([row(1), row(2), row(3, price_move=-0.05)])
    assert note.evidence["mean_clv_approved"] == pytest.approx(-0.04)
    assert note.evidence["n_clv_approved"] == 3 and note.evidence["clv_version"] == "clv-v1"
    assert "CLV medio de las aprobadas -4,0 % (3)" in note.body
    assert "2,0" not in note.body.split("La cuota")[0], "the price move is not in the CLV sentence"
    assert "3 % o más en contra en 1 de 3 selecciones con cierre" in note.body
    assert note.evidence["moved_against"] == 1 and note.evidence["with_price_move"] == 3
    assert note.evidence["postmortems"] == [3]
    assert note.n == 3


def test_a_selection_without_a_closing_probability_has_no_clv_and_still_has_its_price_move() -> None:
    note = market_note([row(1, p_close=None, price_move=-0.04), row(2, p_close=0.48)])
    assert note.evidence["n_clv_approved"] == 1 and note.evidence["mean_clv_approved"] == pytest.approx(-0.04)
    assert note.evidence["moved_against"] == 1 and note.evidence["with_price_move"] == 2
    assert note.n == 2, "two selections, not 1 + 1 + 1 counted over two lists"


def test_only_the_approved_count_for_the_clv_and_every_studied_selection_for_the_moves() -> None:
    note = market_note([row(1, decision="REJECT", p_close=0.40, price_move=-0.06), row(2, decision="APPROVE")])
    assert note.evidence["n_clv_approved"] == 1 and note.evidence["mean_clv_approved"] == pytest.approx(-0.04)
    assert note.evidence["moved_against"] == 1


def test_no_clv_and_no_move_means_no_note() -> None:
    rows = [row(1, p_close=None, price_move=None)]
    assert "market" not in {n.kind for n in notes_for(rows, [], [])}


def test_the_legacy_clv_key_is_not_read() -> None:
    """A row that still carries a ``clv`` key (the old column name) and no ``price_move`` is not a row of this query."""
    legacy = row(1) | {"clv": Decimal("0.5")}
    legacy.pop("price_move")
    with pytest.raises(KeyError):
        notes_for([legacy], [], [])
