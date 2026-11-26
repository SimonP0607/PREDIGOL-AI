"""The ten concepts of price, each with ONE definition in Spanish and English, and the two names of the references of the market (plan RP-10.1, finding H22,
``price-glossary-v1``).

WHY. The same word was used for different numbers: the «cierre» that PrediGol stored is the consensus about three hours before the kick-off, not the closing price;
«la cuota» could be the best price, the price a decision took or the last one captured; the probability of the houses was sometimes with their margin and
sometimes without. The plan fixes ten concepts that are never mixed (section 14) and gives each a name, a definition and the place where its figure lives.

``CONCEPTS`` is the glossary; ``REFERENCES`` names the two references of the market. ``contract_field`` says which field of C-14 carries the concept when it
travels (a concept computed elsewhere, or not yet produced by anything, says so: ``None``). The first concept, the probability of PrediGol that has been
validated, does not exist today and the glossary says it: nothing in the product may call a figure «validated» before a calibrated figure without the market
passes its gates.

A test refuses a concept without both languages and a field that is not in the contract. Pure: no database, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

VERSION: Final = "price-glossary-v1"


@dataclass(frozen=True, slots=True)
class Concept:
    key: str
    es: str
    en: str
    definition_es: str
    definition_en: str
    lives_in: str
    contract_field: str | None = None
    exists_today: bool = True


CONCEPTS: Final[tuple[Concept, ...]] = (
    Concept("validated_probability", "Probabilidad de PrediGol validada", "Validated PrediGol probability",
            "La cifra calibrada sin mercado que superó sus puertas. Hoy no existe ninguna: ninguna cifra se llama validada.",
            "The calibrated figure without the market that passed its gates. None exists today: no figure is called validated.",
            "Cifra única", None, False),
    Concept("fair_probability", "Probabilidad justa del consenso", "Fair probability of the consensus",
            "La media de las casas sin su margen.", "The average of the houses with their margin removed.",
            "market.market_consensus", "implied.value"),
    Concept("implied_probability", "Probabilidad implícita de una cuota", "Implied probability of an odds",
            "Uno dividido por la cuota, con el margen de la casa dentro.", "One divided by the odds, with the house's margin inside.",
            "Cálculo", "best_implied"),
    Concept("fair_odds", "Cuota justa equivalente", "Equivalent fair odds",
            "Uno dividido por la probabilidad de referencia: el precio sin margen.", "One divided by the reference probability: the price without margin.",
            "Cálculo", "implied.fair_odds"),
    Concept("best_price", "Mejor precio disponible", "Best available price",
            "La cuota más alta entre las casas del proveedor en ese momento.", "The highest odds among the provider's houses at that moment.",
            "Libro de cuotas", "best_odds"),
    Concept("publication_odds", "Cuota de publicación", "Publication odds",
            "La que se tomó al decidir, con su hora y su casa.", "The one taken when deciding, with its time and its house.",
            "Decisión", None),
    Concept("current_odds", "Cuota actual", "Current odds", "La última capturada.", "The last one captured.",
            "Libro de cuotas", "best_odds"),
    Concept("houses", "Número de casas", "Number of houses", "Cuántas casas forman el consenso.", "How many houses make up the consensus.",
            "Consenso", "implied.books"),
    Concept("price_age", "Antigüedad del precio", "Age of the price", "Minutos desde la captura.", "Minutes since the capture.",
            "Consenso y libro", "price_age_minutes"),
    Concept("settlement_rule", "Regla de liquidación", "Settlement rule", "Con qué convención se da por ganada una selección.",
            "Under which convention a selection is graded as won.", "market.settlement_rules y código", "settlement"),
)


@dataclass(frozen=True, slots=True)
class Reference:
    key: str
    es: str
    en: str
    definition_es: str
    definition_en: str
    use_es: str
    use_en: str


REFERENCES: Final[tuple[Reference, ...]] = (
    Reference("previous", "Referencia previa", "Previous reference",
              "El consenso a unas tres horas del saque, que hasta ahora se llamaba «cierre».",
              "The consensus about three hours before the kick-off, which used to be called «closing».",
              "Decidir y escribir antes del partido.", "Deciding and writing before the match."),
    Reference("real_close", "Cierre real", "Real close",
              "El consenso calculado con las cuotas ya capturadas en la última hora (`final_prematch_odds`).",
              "The consensus computed from the odds captured in the last hour (`final_prematch_odds`).",
              "Evaluar: valor frente al cierre y experimentos.", "Evaluating: value against the close, and experiments."),
)

KEY_COUNT: Final = 10
TOLERANCE: Final = 0.002
"""A figure stored rounded (fair odds to three decimals, the probability to four) must agree with its reciprocal within this."""


def problems(selection: Mapping[str, Any]) -> list[str]:
    """What is incoherent between the concepts of price a selection of C-14 carries (the private answer, as a dict): the equivalent fair odds is one over the
    fair probability, the implied probability of the best price is one over it, no age is negative and a fair price needs three houses at least. Empty when
    coherent. A concept that is absent is not a problem here (the fields are optional); ``present`` says how many travel."""
    out: list[str] = []
    raw = selection.get("implied")
    implied: Mapping[str, Any] = raw if isinstance(raw, Mapping) and "value" in raw else {}
    has_implied = bool(implied)
    if has_implied and implied.get("fair_odds") is not None and abs(float(implied["fair_odds"]) * float(implied["value"]) - 1) > TOLERANCE:
        out.append("fair_odds is not one over the fair probability")
    if has_implied and implied.get("reference") not in (None, "consenso_vigente"):
        out.append("the reference of the consensus is not the one in force")
    if has_implied and implied.get("fair_odds") is not None and int(implied.get("books", 0)) < 3:
        out.append("a fair price from fewer than three houses")
    if selection.get("best_implied") is not None and abs(float(selection["best_implied"]) * float(selection["best_odds"]) - 1) > TOLERANCE:
        out.append("best_implied is not one over best_odds")
    for age in (selection.get("price_age_minutes"), implied.get("age_minutes") if has_implied else None):
        if age is not None and int(age) < 0:
            out.append("a negative age")
    return out


def present(selection: Mapping[str, Any], market: Mapping[str, Any]) -> set[str]:
    """The concepts (by key) a selection of a market carries in the answer. A concept that has no field never counts as present."""
    raw = selection.get("implied")
    implied: Mapping[str, Any] = raw if isinstance(raw, Mapping) and "value" in raw else {}
    has_implied = bool(implied)
    found: set[str] = set()
    if has_implied:
        found |= {"fair_probability", "houses"}
        if implied.get("fair_odds") is not None:
            found.add("fair_odds")
    if selection.get("best_implied") is not None:
        found.add("implied_probability")
    if "best_odds" in selection:
        found |= {"best_price", "current_odds"}
    if selection.get("price_age_minutes") is not None:
        found.add("price_age")
    if market.get("settlement"):
        found.add("settlement_rule")
    return found


def card(lang: str = "es") -> list[dict[str, Any]]:
    """The glossary as a reader or the owner's console is shown it, in one language."""
    en = lang == "en"
    return [{"key": c.key, "name": c.en if en else c.es, "definition": c.definition_en if en else c.definition_es, "lives_in": c.lives_in,
             "field": c.contract_field, "exists_today": c.exists_today} for c in CONCEPTS]


def references(lang: str = "es") -> list[dict[str, str]]:
    en = lang == "en"
    return [{"key": r.key, "name": r.en if en else r.es, "definition": r.definition_en if en else r.definition_es, "use": r.use_en if en else r.use_es}
            for r in REFERENCES]


__all__ = ["CONCEPTS", "KEY_COUNT", "REFERENCES", "TOLERANCE", "VERSION", "Concept", "Reference", "card", "present", "problems", "references"]
