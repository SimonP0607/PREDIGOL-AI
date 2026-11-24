"""C-11 1.1 (plan de correcciones UX/UI, AP-A04, AP-A05): the reason of a research role as a code the console translates.

``fbi.research.roles.model_role`` and ``fbi.research.v2_record`` write each role's reason as an English sentence with its
figures (``analytics.experiments.role_reason``); the console showed it as it came. Here the sentence is read back to one code
by how it starts - the sentence and its figures stay as they are, nothing is re-run or re-written, and the figures behind
each code travel in the entry's ``metrics`` (``vs_champion``, ``blend``, ``segments``). A sentence this list does not know
(an older or a newer one) has no code: never a guess. Standard library only: the API reads it.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

ReasonCode = Literal["campeon_mercado", "variante_mercado", "mejor_que_mercado", "aporta_informacion",
                     "rechazado_peor_que_mercado", "evidencia_insuficiente", "sin_partidos_comunes", "muestra_insuficiente"]

REASON_CODES: Final[tuple[tuple[str, ReasonCode], ...]] = (
    ("lowest log loss of the de-vigged market baselines", "campeon_mercado"),
    ("a market variant:", "variante_mercado"),
    ("beats the champion alone", "mejor_que_mercado"),
    ("beats the closing consensus prospectively", "mejor_que_mercado"),
    ("adds information the market lacks", "aporta_informacion"),
    ("worse than the champion and adds nothing to it", "rechazado_peor_que_mercado"),
    ("worse than the closing consensus and adds nothing to it", "rechazado_peor_que_mercado"),
    ("the evidence cannot tell", "evidencia_insuficiente"),
    ("no fixture shared with the champion", "sin_partidos_comunes"),
)
"""How a reason starts -> its code. ``muestra_insuficiente`` is read apart (the sentence starts with a count)."""

CODES: Final[tuple[str, ...]] = get_args(ReasonCode)

_NOT_JUDGED: Final = " matches with a forecast and a closing price on "


def reason_code(reason: str | None) -> ReasonCode | None:
    """The code of a stored reason, or None when the list does not know it."""
    if not reason:
        return None
    for prefix, code in REASON_CODES:
        if reason.startswith(prefix):
            return code
    head, found, tail = reason.partition(_NOT_JUDGED)
    if found and head.isdigit() and tail.endswith("not judged"):
        return "muestra_insuficiente"
    return None
