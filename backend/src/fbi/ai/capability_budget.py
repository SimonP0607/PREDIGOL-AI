"""What each NEW capability of the plan may spend a month, and what it has spent (IA-058; AD-A06 of the plan of the definitive architecture
2026, decision 12). ``capability-budget-v1``.

THE REGISTER. Each new piece that calls a model declares here, in code, its capability key, the envelope it is paid from (production US$185,
Exa US$35, LAB US$55 - decision 12) and its monthly cap, with where the figure comes from (``CAPABILITIES``). ``get(key)`` answers what a
capability may spend; the cost panel (``fbi.ai.costs_v3``) shows every one of them against what it spent this month.

    key          the capability's name (``chronicle_v4``): one per capability, never reused
    envelope     production | lab | exa - the money it is paid from; a call counts only against a capability of its own envelope
    monthly_usd  the cap: the piece's own estimate in its file of the plan until the owner says another figure
    prompts      the prompt-version prefixes its calls carry in the ledger (``ai.usage.prompt_version``, and the readers' ledger's for the
                 readers' chronicle); a piece not built yet has none and spends 0 until it declares them
    purposes     the same by the ledger's ``purpose`` (a search has no prompt)

A CAP WARNS, IT DOES NOT CUT. Reaching 80 % or 95 % of a cap is shown in the owner's panel and written to the log of the process that built
it (``fbi.ai.envelopes_readers.log_warnings``); no call is refused because of it - what stops money is still ``fbi.ai.budget_v3`` and its envelopes. Changing that is another
version, decided by the owner.

Pure: the month's rows are read by ``fbi.ai.envelopes_readers`` (the owner's panel), never by the cycle."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

VERSION: Final = "capability-budget-v1"
ENVELOPES: Final[tuple[str, ...]] = ("production", "exa", "lab")
DECISION_12: Final[dict[str, Decimal]] = {"production": Decimal(185), "exa": Decimal(35), "lab": Decimal(55)}
"""The owner's monthly envelopes (decision 12 of the plan, approved 16 Nov 2026): Claude in production (the readers' chronicle included), Exa,
the LAB. What the code applies comes from the environment (``FBI_AI_MONTHLY_BUDGET_USD``, ``FBI_AI_EXA_MONTHLY_BUDGET_USD``,
``FBI_AI_LAB_MONTHLY_BUDGET_USD``): the panel shows both and says when they differ."""
ALERT_AT: Final[tuple[int, ...]] = (80, 95)
"""The internal warnings of AD-A06, percent of an envelope or of a capability's cap."""


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    piece: str
    envelope: str
    monthly_usd: Decimal
    source: str
    prompts: tuple[str, ...] = ()
    purposes: tuple[str, ...] = ()

    @property
    def tagged(self) -> bool:
        """Whether its calls can be found in the ledger yet (a piece not built has no prompt to look for)."""
        return bool(self.prompts or self.purposes)


CAPABILITIES: Final[tuple[Capability, ...]] = (
    Capability("chronicle_v4", "AD-F02", "production", Decimal("14.00"),
               "ficha AD-F02: 0,004 por crónica x 120 al día con el modelo pequeño", prompts=("chronicle-v4",)),
    Capability("news_summaries", "AD-G04", "production", Decimal("13.50"),
               "ficha AD-G04: 4 con 300 noticias al día, 13,5 con 1.000 (se toma el alto)"),
    Capability("deep_extraction", "AD-C05", "production", Decimal("4.40"),
               "ficha AD-C05: 210 páginas al día en tiempo real (2,2 por lotes)"),
    Capability("specialist_readers", "AD-D09", "production", Decimal("15.00"),
               "costes del plan: unos 15 al mes que pasan del LAB a producción (7,33 en 15 días)"),
    Capability("page_bodies", "AD-C05", "exa", Decimal("9.00"),
               "ficha AD-C05 y costes del plan: de 6 a 9 al mes de cuerpos completos (se toma el alto)"),
    Capability("battery_v4", "AD-A03", "lab", Decimal("3.00"),
               "ficha AD-A03: menos de 3 por ejecución; una ejecución al mes", prompts=("battery-v4",)),
    Capability("quarantine_tests", "AD-A01", "lab", Decimal("3.00"),
               "ficha AD-A01: pruebas A1-A6 por debajo de 3, una vez"),
    Capability("label_bank_arms", "AD-C09", "lab", Decimal("2.00"),
               "ficha AD-C09: menos de 2 para los cuatro brazos"),
    Capability("news_text_shadow", "AD-G04", "lab", Decimal("2.00"),
               "encargo IA-101: tope de 2 del LAB para el texto propio de las noticias en sombra (fbi.news.writer.PIECE_MONTHLY_USD)",
               prompts=("news-text-v1",)),
    Capability("replay_regression", "AD-K04", "lab", Decimal("2.93"),
               "ficha AD-K04: 2,93 por pasada completa medida (15-nov); una pasada al mes", prompts=("replay-bank-",)),
)

_BY_KEY: Final[dict[str, Capability]] = {c.key: c for c in CAPABILITIES}


def get(key: str) -> Capability | None:
    """What a capability may spend a month and from which envelope, or None when it is not in the register."""
    return _BY_KEY.get(key)


def capability_of(scope: str, prompt: str | None, purpose: str | None) -> str | None:
    """The capability a row of the ledger belongs to: the first of its OWN envelope whose prompt prefix or purpose it carries."""
    for c in CAPABILITIES:
        if c.envelope != scope:
            continue
        if prompt and any(prompt.startswith(p) for p in c.prompts):
            return c.key
        if purpose and purpose in c.purposes:
            return c.key
    return None


@dataclass(frozen=True, slots=True)
class Row:
    """The month's spend of one (envelope, prompt, purpose) of the ledgers."""

    scope: str
    prompt: str | None
    purpose: str | None
    cost: Decimal


def spend(rows: Iterable[Row]) -> dict[str, Decimal]:
    """What each capability of the register has spent over these rows (0 for one without calls)."""
    out = {c.key: Decimal(0) for c in CAPABILITIES}
    for r in rows:
        key = capability_of(r.scope, r.prompt, r.purpose)
        if key is not None:
            out[key] += r.cost
    return out


def level(spent: Decimal, cap: Decimal, thresholds: tuple[int, ...] = ALERT_AT) -> int | None:
    """The highest warning a figure has reached (80 or 95), or None. A cap of 0 warns of nothing: it is not a budget."""
    if cap <= 0:
        return None
    reached = [t for t in thresholds if spent * 100 >= cap * t]
    return max(reached) if reached else None


def _usd(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def report(rows: Iterable[Row]) -> list[dict[str, Any]]:
    """Every capability of the register against its cap this month, in the register's order."""
    spent = spend(rows)
    return [{"key": c.key, "piece": c.piece, "envelope": c.envelope, "monthly_usd": _usd(c.monthly_usd), "spent_usd": _usd(spent[c.key]),
             "share": round(float(spent[c.key] / c.monthly_usd), 4) if c.monthly_usd > 0 else None,
             "alert": level(spent[c.key], c.monthly_usd), "tagged": c.tagged, "prompts": list(c.prompts), "purposes": list(c.purposes),
             "source": c.source} for c in CAPABILITIES]


def declared(envelopes: Mapping[str, Decimal] = DECISION_12) -> dict[str, dict[str, str]]:
    """What the register declares from each envelope, against the envelope: the caps of the new pieces must fit inside it."""
    out: dict[str, dict[str, str]] = {}
    for e in ENVELOPES:
        caps = sum((c.monthly_usd for c in CAPABILITIES if c.envelope == e), Decimal(0))
        out[e] = {"declared_usd": _usd(caps), "envelope_usd": _usd(envelopes.get(e, Decimal(0)))}
    return out


__all__ = ["ALERT_AT", "CAPABILITIES", "DECISION_12", "ENVELOPES", "VERSION", "Capability", "Row", "capability_of", "declared", "get",
           "level", "report", "spend"]
