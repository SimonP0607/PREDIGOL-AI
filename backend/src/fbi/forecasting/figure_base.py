"""The label of a figure's base and the weights of the calibrator behind it (plan RP-2.1, findings H01 and H03, ``figure-base-v1``). Pure.

A probability PrediGol states can rest on four different things, and until now nothing said which: the model's own number (``raw``), a champion
that corrects the model alone (``calibrated_no_market``: identity or Platt), a champion that also reads the market's price
(``calibrated_with_market``: ``logit2``), or the market's own de-vigged number (``market``, the third figure of a selection, kept in
``p_market_used``). The three figures of a selection (raw, calibrated, market) stay separate columns; this module names the base of the one that is
stated and keeps the weights the calibrator gave each input, so that nobody has to guess how much the market weighs in a number (the audit of
10-nov found the champion in use weighs the market 0.50 to 1.30 and the model -0.25 to +0.31, on the logit scale).

Weights are the coefficients of ``logit(p) = intercept + w_model * logit(p_model) + w_market * logit(p_market)``, the formula of
``intel.calibration.apply_params``: identity is (0, 1, 0), Platt is (a, b, 0) and ``logit2`` is (a, b, c). A figure with no champion has no weights
(the label ``raw`` says it is the model's own number). Nothing here computes a probability or changes one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

VERSION: Final = "figure-base-v1"

RAW: Final = "raw"
CALIBRATED_NO_MARKET: Final = "calibrated_no_market"
CALIBRATED_WITH_MARKET: Final = "calibrated_with_market"
MARKET: Final = "market"
LABELS: Final = (RAW, CALIBRATED_NO_MARKET, CALIBRATED_WITH_MARKET, MARKET)
STATED: Final = (RAW, CALIBRATED_NO_MARKET, CALIBRATED_WITH_MARKET)
"""The labels the stated figure can have (``MARKET`` labels the third figure, never the stated one)."""
METHODS: Final = ("identity", "platt", "logit2")


@dataclass(frozen=True, slots=True)
class Base:
    """What the stated figure rests on: its label and, when a champion was applied, its method and weights."""

    label: str
    method: str | None = None
    intercept: float | None = None
    w_model: float | None = None
    w_market: float | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label}
        if self.method is not None:
            out |= {"method": self.method, "intercept": self.intercept, "w_model": self.w_model, "w_market": self.w_market}
        return out


UNCALIBRATED_BASE: Final = Base(RAW)


def weights_of(method: str, params: dict[str, float]) -> tuple[float, float, float]:
    """(intercept, weight of the model, weight of the market) of a calibrator, on the logit scale."""
    if method == "identity":
        return 0.0, 1.0, 0.0
    if method == "platt":
        return float(params["a"]), float(params["b"]), 0.0
    if method == "logit2":
        return float(params["a"]), float(params["b"]), float(params["c"])
    raise ValueError(f"unknown calibration method {method}")


def base_of(method: str | None, params: dict[str, float] | None = None) -> Base:
    """The base of a stated figure: ``raw`` without a champion, else the champion's label with its weights."""
    if method is None:
        return UNCALIBRATED_BASE
    a, b, c = weights_of(method, params or {})
    return Base(CALIBRATED_WITH_MARKET if method == "logit2" else CALIBRATED_NO_MARKET, method, a, b, c)


def of_champion(champion: Any | None, *, applied: bool) -> Base:
    """The base from a ``Calibrator`` (or None) and whether it was applied to this figure (a champion that could not be applied leaves ``raw``)."""
    if champion is None or not applied:
        return UNCALIBRATED_BASE
    return base_of(str(champion.method), dict(champion.params))


def label_of_stored(calibration: str, method: str | None) -> str:
    """The label of a stored row from what it already says: its seal and its calibrator's method (None for rows written before the label)."""
    if calibration != "CALIBRATED":
        return RAW
    return CALIBRATED_WITH_MARKET if method == "logit2" else CALIBRATED_NO_MARKET


__all__ = ["CALIBRATED_NO_MARKET", "CALIBRATED_WITH_MARKET", "LABELS", "MARKET", "METHODS", "RAW", "STATED", "VERSION", "Base", "base_of",
           "label_of_stored", "of_champion", "weights_of"]
