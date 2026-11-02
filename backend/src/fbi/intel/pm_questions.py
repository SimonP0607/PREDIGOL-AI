"""The ten questions of a post-mortem, the class of a loss and the verdict of a review - pure functions of what was stored before
kick-off and of what happened (plan F8: they moved here from ``fbi.ai.pick_postmortem`` (pm-v2) so that the ONE post-mortem
(``fbi.intel.postmortem``, pm-v6) and the frozen writer of the AI share one definition; nothing in this module reads a database).

    Facts            what a post-mortem judges by
    classify         the class of a loss, the first that applies
    win_quality      whether a WIN was earned or lucky, judged against the close like a loss
    review_verdict_of  what the review decided against how the selection ended (approved and won, rejected and would have won...)
    answers          the ten questions (+ the quality of a win), answered only from stored numbers
    stored_clv       the CLV (clv-v1) of a stored row, derived from what it keeps

TWO PRICE NUMBERS, TWO NAMES (plan F0, defect 7): "the market moved against the price" is judged by the PRICE MOVE - the price taken
against the same bookmaker's closing price, margin in both (``closing_value.price_move``) - and the CLV is the price taken at the closing
fair probability (``closing_value.clv``, ``clv-v1``). Each has its own threshold and they are never averaged together.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fbi.market import closing_value

MOVED_AGAINST = closing_value.MOVED_AGAINST
"""A price move of 3 % or more against the price taken: the class MARKET_ERROR. A threshold on the PRICE MOVE."""
MODEL_GAP = 0.08
STALE_PRICE = timedelta(hours=3)
NOT_FIT = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})
CLASSES = ("MODEL_ERROR", "CONTEXT_ERROR", "DATA_ERROR", "MARKET_ERROR", "EXECUTION_ERROR", "NORMAL_VARIANCE", "UNKNOWN")


def stored_clv(odds: Any, answers_: Mapping[str, Any] | None) -> float | None:
    """The CLV (``clv-v1``) of a stored post-mortem, derived from what the row keeps in a traceable way: the odds taken
    (``odds``) and the closing fair probability its model question recorded (``answers.model.data.p_close``).

    The ``clv`` column of ``ai.pick_postmortems`` and the ``clv`` key of the JSON of rows written before ``clv-v1`` are
    PRICE MOVES; they are never read as CLV. None when the row has no odds or no closing probability."""
    model = (answers_ or {}).get("model") or {}
    p_close = (model.get("data") or {}).get("p_close")
    if odds is None or p_close is None:
        return None
    return round(closing_value.clv(float(odds), float(p_close)), 4)


def logloss(p: float, won: bool) -> float:
    q = min(max(p if won else 1 - p, 1e-6), 1.0)
    return -math.log(q)


@dataclass
class Facts:
    """What a post-mortem judges by: known before kick-off, and what happened."""

    settled: str
    decision: str | None
    p_model: float | None
    p_market: float | None
    p_close: float | None
    odds: float | None
    close_odds: float | None
    data_unfit: bool = False
    stale_price: bool = False
    kickoff_changed: bool = False
    information_failed: bool = False
    information: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    key_absence: list[str] = field(default_factory=list)
    lineup_changed: bool = False
    lineup_detail: str | None = None
    edge_in_noise: bool = False

    @property
    def won(self) -> bool:
        return self.settled in ("win", "half_win")

    @property
    def lost(self) -> bool:
        return self.settled in ("loss", "half_loss")

    @property
    def price_move(self) -> float | None:
        """The price taken against the SAME bookmaker's closing price, margin in both: whether that book's price moved
        after the selection was taken. It is NOT the CLV (``clv``)."""
        if self.odds is None or not self.close_odds:
            return None
        return round(closing_value.price_move(self.odds, self.close_odds), 4)

    @property
    def clv(self) -> float | None:
        """``clv-v1``: the price taken at the closing fair probability (the Shin consensus before kick-off)."""
        if self.odds is None or self.p_close is None:
            return None
        return round(closing_value.clv(self.odds, self.p_close), 4)


def classify(f: Facts) -> str | None:
    """The class of a loss (None for anything else), the first that applies."""
    if not f.lost:
        return None
    if f.data_unfit:
        return "DATA_ERROR"
    if f.stale_price or f.kickoff_changed:
        return "EXECUTION_ERROR"
    if f.key_absence and f.decision == "APPROVE":
        return "CONTEXT_ERROR"  # a known key absence on the chosen side, let through
    move = f.price_move
    moved_against = (move is not None and move <= MOVED_AGAINST) or (
        f.p_close is not None and f.p_market is not None and f.p_close <= f.p_market + MOVED_AGAINST)
    if moved_against:
        return "MARKET_ERROR"  # the market knew something before the kick-off
    if f.information_failed:
        return "CONTEXT_ERROR"
    if f.p_close is not None and f.p_model is not None and f.p_model - f.p_close >= MODEL_GAP:
        return "MODEL_ERROR"
    if f.p_close is not None or (move is not None and move >= 0):
        return "NORMAL_VARIANCE"
    return "UNKNOWN"


def win_quality(f: Facts) -> str | None:
    """Whether a WIN was earned or lucky, judged like a loss is - against the close, never by the result alone:

        EARNED   the market moved toward the selection before kick-off (the price beat the close, or the closing
                 probability rose), or the model stood close to the closing market;
        LUCKY    the market moved against it and the model was far above the close: it won despite a weak case;
        UNKNOWN  no closing price to judge by.

    A lucky win teaches nothing about the model and must not be learned from as if it were a good decision."""
    if not f.won:
        return None
    move = f.price_move
    moved_against = (move is not None and move <= MOVED_AGAINST) or (
        f.p_close is not None and f.p_market is not None and f.p_close <= f.p_market + MOVED_AGAINST)
    far_above = f.p_close is not None and f.p_model is not None and f.p_model - f.p_close >= MODEL_GAP
    if moved_against and far_above:
        return "LUCKY"
    if f.p_close is None and move is None:
        return "UNKNOWN"
    if moved_against:
        return "LUCKY"
    return "EARNED"


def review_verdict_of(f: Facts) -> str:
    if not (f.won or f.lost):
        return "push"
    d = f.decision
    if d == "APPROVE":
        return "approved_won" if f.won else "approved_lost"
    if d == "DOWNGRADE":
        return "caution_won" if f.won else "caution_lost"
    if d == "REJECT":
        return "rejected_would_have_won" if f.won else "rejected_correctly"
    return "unreviewed_won" if f.won else "unreviewed_lost"


def _yes(x: bool | None) -> str:
    return "sin datos" if x is None else "sí" if x else "no"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def answers(f: Facts, cls: str | None, *, score: tuple[int, int], label: str) -> dict[str, Any]:
    move, clv = f.price_move, f.clv
    ll_model = None if f.p_model is None or not (f.won or f.lost) else round(logloss(f.p_model, f.won), 4)
    ll_close = None if f.p_close is None or not (f.won or f.lost) else round(logloss(f.p_close, f.won), 4)
    model_failed = None if f.p_close is None or f.p_model is None else (
        f.lost and f.p_model - f.p_close >= MODEL_GAP)
    return {
        "expected": {"answer": label, "detail": f"PrediGol {_pct(f.p_model)} · mercado {_pct(f.p_market)} · cuota "
                     f"{'—' if f.odds is None else f'{f.odds:.2f}'} · decisión {f.decision or 'sin revisión'}",
                     "data": {"p_model": f.p_model, "p_market": f.p_market, "odds": f.odds, "decision": f.decision}},
        "happened": {"answer": f.settled, "detail": f"{score[0]}-{score[1]}: la selección {f.settled}",
                     "data": {"score": list(score)}},
        "model": {"answer": _yes(model_failed),
                  "detail": f"modelo {_pct(f.p_model)} frente al cierre {_pct(f.p_close)}; log loss modelo "
                            f"{ll_model} vs cierre {ll_close}",
                  "data": {"p_close": f.p_close, "logloss_model": ll_model, "logloss_close": ll_close}},
        "information": {"answer": _yes(f.information_failed), "detail": "; ".join(f.information) or "nada falló",
                        "data": {"items": f.information}},
        "ignored_signal": {"answer": _yes(bool(f.ignored) and f.decision == "APPROVE"),
                           "detail": ", ".join(f.ignored) or "ninguna", "data": {"signals": f.ignored}},
        "odds_moved": {"answer": "sin datos" if move is None else "en contra" if move <= MOVED_AGAINST
                       else "a favor" if move >= -MOVED_AGAINST else "estable",
                       "detail": f"Cuota frente al cierre de la misma casa {'—' if move is None else f'{100 * move:+.1f} %'} "
                                 f"(tomada {f.odds} · cierre {f.close_odds}); CLV frente al cierre justo "
                                 f"{'—' if clv is None else f'{100 * clv:+.1f} %'}",
                       "data": {"price_move": move, "close_odds": f.close_odds, "clv_v1": clv}},
        "key_absence": {"answer": _yes(bool(f.key_absence)), "detail": ", ".join(f.key_absence) or "ninguna",
                        "data": {"players": f.key_absence}},
        "lineup_changed": {"answer": _yes(f.lineup_changed), "detail": f.lineup_detail or "sin cambios relevantes",
                           "data": {}},
        "uncertainty": {"answer": _yes(f.edge_in_noise and f.decision == "APPROVE"),
                        "detail": "la ventaja estaba dentro del ruido del modelo" if f.edge_in_noise
                        else "la ventaja superaba el ruido del modelo", "data": {"edge_in_noise": f.edge_in_noise}},
        "variance": {"answer": _yes(cls == "NORMAL_VARIANCE") if f.lost else "no aplica",
                     "detail": (f"con el cierre en {_pct(f.p_close)}, perder tenía {_pct(1 - f.p_close)} de "
                                "probabilidad") if f.p_close is not None and f.lost else "—", "data": {}},
        "win_quality": {"answer": {"EARNED": "merecido", "LUCKY": "con suerte", "UNKNOWN": "sin datos"}.get(
                            str(win_quality(f)), "no aplica"),
                        "detail": ("el mercado se movió hacia la selección o el modelo estaba cerca del cierre"
                                   if win_quality(f) == "EARNED" else
                                   "ganó con el mercado en contra: no enseña nada sobre el modelo"
                                   if win_quality(f) == "LUCKY" else "—"),
                        "data": {"win_quality": win_quality(f)}},
    }
