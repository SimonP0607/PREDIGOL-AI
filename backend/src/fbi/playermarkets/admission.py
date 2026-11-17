"""The state of a player selection in the private evaluation (IA-130, AD-E04). Pure: no database, no clock.

Decision n.º 7 of the owner (16-nov-2026): the player markets only once the line-up evaluation is reliable. So the families are ``off``
and stay off until E3 is reliable - and then ``shadow``, never more. ``E3_RELIABLE`` is that gate: False, the same fact as
``market-states-v1``'s ``LINEUP_EVALUATION_RELIABLE`` (a test holds the two equal), and only a reviewed change of both, after a verdict
on E3 in the validation board (AD-K02), moves it. Today no such verdict exists.

THE STATES of one selection (a player, a family, a line), checked in this order - the first that applies is the state:

    apagada .................... the families are off (the switch is not ``shadow``, or E3 is not reliable)
    sin_regla .................. no settlement rule reads the family's figure (``fbi.playermarkets.settle.STATS``)
    sin_resolver ............... the provider's name fits no single man of the side's sheet
    sin_precio ................. no house quotes the line
    descartada_sin_alineacion .. kick-off came and no official line-up was read: discarded, never confirmed blind
    pendiente_alineaciones ..... before the official line-up: it always waits
    no_juega ................... the official sheet does not have him (or he is on the bench: a starter's prop)
    una_sola_casa .............. one house: no selection confirms on a single price (the norm today)
    mercado_estrecho ........... two houses: below ``MIN_BOOKS``
    evaluable .................. the official line-up has him starting and three houses or more quote the line

``evaluable`` is the only state that could ever be judged, and it needs the official line-up by construction: a test walks every
combination of facts and finds no selection confirmed without it. Even ``evaluable`` publishes nothing: it is a private evaluation.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from fbi.playermarkets.quotes import MIN_BOOKS
from fbi.playermarkets.settle import STATS

SWITCH: Final = "FBI_PLAYER_MARKETS"
E3_RELIABLE: Final = False
"""The gate of decision n.º 7: no verdict on E3 exists (AD-K02). A reviewed change, never a setting."""

OFF: Final = "apagada"
NO_RULE: Final = "sin_regla"
UNRESOLVED: Final = "sin_resolver"
NO_PRICE: Final = "sin_precio"
DISCARDED: Final = "descartada_sin_alineacion"
WAITING: Final = "pendiente_alineaciones"
NOT_PLAYING: Final = "no_juega"
SINGLE: Final = "una_sola_casa"
THIN: Final = "mercado_estrecho"
EVALUABLE: Final = "evaluable"
STATES: Final = (OFF, NO_RULE, UNRESOLVED, NO_PRICE, DISCARDED, WAITING, NOT_PLAYING, SINGLE, THIN, EVALUABLE)


def mode(env: Mapping[str, str] | None = None, *, e3_reliable: bool = E3_RELIABLE) -> str:
    """``shadow`` only when the switch says so AND E3 is reliable; otherwise ``off`` (the default)."""
    e = os.environ if env is None else env
    asked = e.get(SWITCH, "off").strip().lower() == "shadow"
    return "shadow" if asked and e3_reliable else "off"


@dataclass(frozen=True, slots=True)
class Facts:
    family: str
    resolved: bool
    books: int
    official_lineup: bool
    """The official sheet of his side was read by the moment."""
    starts: bool | None
    """On that sheet as a starter (None: no sheet)."""
    kicked_off: bool


def state(f: Facts, *, mode_now: str) -> str:
    """The state of one selection. Pure."""
    if mode_now != "shadow":
        return OFF
    if f.family not in STATS:
        return NO_RULE
    if not f.resolved:
        return UNRESOLVED
    if f.books <= 0:
        return NO_PRICE
    if not f.official_lineup:
        return DISCARDED if f.kicked_off else WAITING
    if not f.starts:
        return NOT_PLAYING
    if f.books == 1:
        return SINGLE
    if f.books < MIN_BOOKS:
        return THIN
    return EVALUABLE
