"""The prop families of the player engine: one per market, each with its own status (``player-engine-v1``).

A family is the count a prop settles on (a player's goals, his shots on target, a goalkeeper's saves), the lines the engine prices and
the SUBJECT it is about, in the words of ``fbi.odds.quote_taxonomy`` (``player`` or ``keeper``). The provider prices about fifty player
bets (``players`` and ``saves`` in the taxonomy, all NOT_MODELABLE there); that a bet is offered activates nothing here, and this registry
is not derived from the taxonomy.

STATUS. Every family is ``SHADOW``: computed and reported, read by nothing that decides. Whether a family has the data to be modelled is
not a property of the registry: the evaluation (``fbi.players.backtest``) measures it on the history it was given and says MODELABLE or
NOT_MODELABLE with the numbers behind it. No family can be ACTIVE in this version; a test holds that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

SHADOW: Final = "SHADOW"
STATUSES: Final = (SHADOW,)
"""The only status of ``player-engine-v1``. ACTIVE is not a value this package can hold."""

MODELABLE: Final = "MODELABLE"
NOT_MODELABLE: Final = "NOT_MODELABLE"
VERDICTS: Final = (MODELABLE, NOT_MODELABLE)

PLAYER: Final = "player"
KEEPER: Final = "keeper"

STATS: Final = ("goals", "assists", "shots", "shots_on", "fouls", "cards", "saves")
"""The per-match counts read from ``core.fixture_player_stats``: ``goals``, ``assists``, ``shots`` (``shots_total``), ``shots_on``,
``fouls`` (``fouls_committed``), ``cards`` (yellow plus red: a booking is at least one) and ``saves``. NULL means the provider did not
report it, never zero; a NULL count is left out of the rate and of the evaluation of that prop."""


@dataclass(frozen=True, slots=True)
class PropFamily:
    key: str
    stat: str
    """The count of ``STATS`` it settles on."""
    lines: tuple[float, ...]
    """The lines priced: P(count > line). The first one is the family's main line (the one the data threshold is measured on)."""
    subject: str
    status: str = SHADOW
    label: str = ""


FAMILIES: Final[tuple[PropFamily, ...]] = (
    PropFamily("player_goals", "goals", (0.5, 1.5), PLAYER, label="Goleador (anytime) / 2+ goles"),
    PropFamily("player_assists", "assists", (0.5,), PLAYER, label="Asistencia"),
    PropFamily("player_shots", "shots", (0.5, 1.5, 2.5), PLAYER, label="Tiros"),
    PropFamily("player_shots_on", "shots_on", (0.5, 1.5), PLAYER, label="Tiros a puerta"),
    PropFamily("player_fouls", "fouls", (0.5, 1.5), PLAYER, label="Faltas cometidas"),
    PropFamily("player_cards", "cards", (0.5,), PLAYER, label="Tarjeta del jugador"),
    PropFamily("keeper_saves", "saves", (1.5, 2.5, 3.5), KEEPER, label="Atajadas del portero"),
)
BY_KEY: Final = {f.key: f for f in FAMILIES}


def applies(family: PropFamily, position: str) -> bool:
    """A keeper family is about goalkeepers only; a player family is about everyone else (a goalkeeper's goals are not priced)."""
    return (position == "G") == (family.subject == KEEPER)
