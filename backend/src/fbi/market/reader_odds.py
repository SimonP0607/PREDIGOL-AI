"""The odds a reader finds at their own house, compared with the market's fair reference (plan RP-10.2, finding H22, ``reader-odds-v1``).

A pure calculation. Given the odds the reader reports, the fair probability of the market for that selection (the consensus without margin, ``fbi.market.consensus``)
and how many houses it comes from, it says three things and nothing else:

* the implied probability of the reader's odds (one over them: the margin of the house is inside);
* the distance to the equivalent fair odds, in percent of the fair odds (positive when the reader's odds are above the fair ones), and
* the margin the reader pays on this selection: the points of probability between the reader's odds and the fair reference.

It says whether the reader's house is among the ones the provider prices, using the list of licensed houses of Colombia (``fbi.market.local_operators``): a house
the provider does not quote has no reference of its own and the comparison is against the consensus of other houses, which the answer says.

WHAT IT NEVER DOES. It never says that a bet is worth making or not: no text of recommendation, no sign read as «value», no probability of PrediGol. PrediGol
never declares value on odds the reader has not confirmed having: these are the reader's own figure, taken as given, never stored and never tied to an account (the
function has no state, no clock and no database). A fair reference from fewer than three houses is not given: ``reference`` says ``insuficiente``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from fbi.market.local_operators import COLJUEGOS_OPERATORS, normalise, provider_match

VERSION: Final = "reader-odds-v1"
MIN_HOUSES: Final = 3
"""A fair reference needs this many houses (the rule of the whole board of prices)."""
MIN_ODDS: Final = 1.01
MAX_ODDS: Final = 1000.0

Reference = Literal["suficiente", "insuficiente", "sin_dato"]
House = Literal["cotizada", "no_cotizada", "no_licenciada", "sin_casa"]
Status = Literal["ok", "cuota_invalida"]


@dataclass(frozen=True, slots=True)
class Comparison:
    status: Status
    reference: Reference
    house: House
    implied_probability: float | None
    fair_odds: float | None
    distance_pct: float | None
    margin_points: float | None
    note_es: str
    note_en: str

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "status": self.status, "reference": self.reference, "house": self.house,
                "implied_probability": self.implied_probability, "fair_odds": self.fair_odds, "distance_pct": self.distance_pct,
                "margin_points": self.margin_points, "note_es": self.note_es, "note_en": self.note_en}


def house_state(brand: str | None, provider_names: Mapping[int, str]) -> House:
    """Whether the reader's house is a licensed house of Colombia the provider quotes (``cotizada``), a licensed one it does not (``no_cotizada``), not on the list
    (``no_licenciada``) or not given (``sin_casa``)."""
    if brand is None or not brand.strip():
        return "sin_casa"
    name = normalise(brand)
    for op in COLJUEGOS_OPERATORS:
        if name in {normalise(op.brand), *(normalise(a) for a in op.aliases)} or name.replace(" ", "") == normalise(op.brand).replace(" ", ""):
            return "cotizada" if provider_match(op, dict(provider_names)) else "no_cotizada"
    return "no_licenciada"


_NOTES: Final[Mapping[str, tuple[str, str]]] = {
    "ok": ("Comparación con la referencia del mercado: la cuota que informas, la cuota justa equivalente y el margen que pagas. No es una recomendación.",
           "Comparison with the market reference: the odds you report, the equivalent fair odds and the margin you pay. It is not a recommendation."),
    "insuficiente": ("La referencia del mercado sale de menos de tres casas: no se da una cuota justa para comparar.",
                     "The market reference comes from fewer than three houses: no fair odds are given to compare."),
    "sin_dato": ("No hay referencia de mercado para esta selección.", "There is no market reference for this selection."),
    "cuota_invalida": ("La cuota debe estar entre 1,01 y 1000.", "The odds must be between 1.01 and 1000."),
}


def compare(odds: float, fair_probability: float | None, *, books: int = 0, brand: str | None = None,
            provider_names: Mapping[int, str] | None = None) -> Comparison:
    """The comparison of the reader's ``odds`` with the market. ``fair_probability`` is the consensus without margin (None when the market has none)."""
    house = house_state(brand, provider_names or {})
    if not MIN_ODDS <= odds <= MAX_ODDS:
        return Comparison("cuota_invalida", "sin_dato", house, None, None, None, None, *_NOTES["cuota_invalida"])
    implied = 1.0 / odds
    if fair_probability is None or not 0.0 < fair_probability < 1.0:
        return Comparison("ok", "sin_dato", house, round(implied, 4), None, None, None, *_NOTES["sin_dato"])
    if books < MIN_HOUSES:
        return Comparison("ok", "insuficiente", house, round(implied, 4), None, None, None, *_NOTES["insuficiente"])
    fair_odds = 1.0 / fair_probability
    return Comparison("ok", "suficiente", house, round(implied, 4), round(fair_odds, 3), round((odds / fair_odds - 1.0) * 100, 2),
                      round((implied - fair_probability) * 100, 2), *_NOTES["ok"])


__all__ = ["MAX_ODDS", "MIN_HOUSES", "MIN_ODDS", "VERSION", "Comparison", "compare", "house_state"]
