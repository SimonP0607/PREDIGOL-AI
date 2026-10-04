"""Colombia's licensed online bookmakers, and whether any of our sources prices them.

The owner's users bet with Colombian operators. API-Football is the only price source we
hold, and it was never a promise to carry them: this list is what the coverage report
measures the gap against, so "do we have Betplay?" has a stored, dated answer instead of
an assumption.

Source: Coljuegos, "Operadores de Juegos Online Autorizados por Coljuegos", page last
modified 1 Oct 2026 (https://www.coljuegos.gov.co/publicaciones/301841/juegosonline/).
The page's own text still says "16 páginas" while listing 14 brands, and a July 2026
press report counted 15; re-check before relying on the count.

A provider bookmaker with the same BRAND is not the Colombian book: an international
Betano or bwin feed prices for other jurisdictions, with its own margins and limits. That
is why ``same_brand_in_provider`` and ``colombian_edition_confirmed`` are separate facts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LIST_AS_OF = "2026-10-01"
LIST_SOURCE = "https://www.coljuegos.gov.co/publicaciones/301841/juegosonline/"


@dataclass(frozen=True, slots=True)
class LocalOperator:
    brand: str
    domain: str
    company: str
    aliases: tuple[str, ...] = ()
    """Names a provider might give the same brand (normalised before comparing)."""


COLJUEGOS_OPERATORS: tuple[LocalOperator, ...] = (
    LocalOperator("Wplay", "wplay.co", "Aquila Global Group"),
    LocalOperator("Betplay", "betplay.com.co", "Corredor Empresarial"),
    LocalOperator("Betsson", "betsson.co", "Colbet"),
    LocalOperator("Zamba", "zamba.co", "E Total Gaming"),
    LocalOperator("Codere", "codere.com.co", "Codere Online Colombia"),
    LocalOperator("Luckia", "luckia.co", "Luckia Colombia"),
    LocalOperator("Sportium", "sportium.com.co", "Sportium Apuestas Colombia"),
    LocalOperator("Rushbet", "rushbet.co", "Rush Street Interactive Colombia", aliases=("rush bet",)),
    LocalOperator("Rivalo", "rivalo.co", "Teclino"),
    LocalOperator("Yajuego", "yajuego.co", "Games and Betting", aliases=("ya juego",)),
    LocalOperator("bwin", "sports.bwin.co", "Bwin Latam"),
    LocalOperator("Stake", "stake.com.co", "Stake Colombia"),
    LocalOperator("Betano", "betano.co", "Kaizen Gaming Colombia"),
    LocalOperator("MrYoker", "mryoker.co", "Global Vitxo", aliases=("mr yoker",)),
)


def normalise(name: str) -> str:
    """Lower case, accents and punctuation removed, spaces collapsed: 'BetPlay ' == 'betplay'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _keys(op: LocalOperator) -> set[str]:
    keys = {normalise(op.brand), *(normalise(a) for a in op.aliases)}
    return keys | {k.replace(" ", "") for k in keys}


def provider_match(op: LocalOperator, provider_names: dict[int, str]) -> list[int]:
    """The provider bookmaker ids whose name is this brand (whole-name match only: 'Betsson'
    is not 'NordicBet', and 'Stake' must not match 'Stakers')."""
    keys = _keys(op)
    out = []
    for pid, name in provider_names.items():
        n = normalise(name)
        if n and (n in keys or n.replace(" ", "") in keys):
            out.append(pid)
    return sorted(out)
