"""One vocabulary of positions (plan 2026, AD-H09, ``IA-071``).

The provider writes a player's position in two vocabularies: the profile and the squad say ``Goalkeeper`` / ``Defender`` /
``Midfielder`` / ``Attacker`` (and, in old season rows, ``Forward``); a line-up says ``G`` / ``D`` / ``M`` / ``F``. Production,
16-nov-2026: ``core.players`` holds both (55,118 ``Midfielder`` and 11,393 ``M``...), plus ``SUB`` (5) and ``U`` (1), which say
nothing about where a man plays. Everything that groups players by position reads it through ``position_group``, here or in
SQL through ``core.position_group(text)`` (migration 0141), which is the same table: ``tests/unit/test_positions.py`` holds the
two to each other and to every spelling seen in production.

The closed list is ``goalkeeper``, ``defender``, ``midfielder``, ``forward``; ``None`` means "not known" (a substitute marker,
an empty field, a word not in the table). A detailed role (``Centre-Back``, ``Left Winger``) is kept as ``detail`` when a
source gives one; the provider gives none today. Nothing stored is rewritten: the raw column stays as it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fbi.people.identity.names import alias_key

GROUPS: Final = ("goalkeeper", "defender", "midfielder", "forward")

_GROUP_OF: Final[dict[str, str]] = {
    # the provider's two vocabularies
    "goalkeeper": "goalkeeper", "g": "goalkeeper", "gk": "goalkeeper", "keeper": "goalkeeper",
    "defender": "defender", "d": "defender", "df": "defender",
    "midfielder": "midfielder", "m": "midfielder", "mf": "midfielder",
    "attacker": "forward", "forward": "forward", "f": "forward", "fw": "forward", "striker": "forward",
    # Spanish (the owner's words, and what a Spanish source writes)
    "portero": "goalkeeper", "arquero": "goalkeeper", "defensa": "defender", "defensor": "defender",
    "centrocampista": "midfielder", "mediocampista": "midfielder", "volante": "midfielder",
    "delantero": "forward", "atacante": "forward",
}

_DETAIL: Final[dict[str, tuple[str, str]]] = {
    "centre back": ("defender", "centre_back"), "center back": ("defender", "centre_back"),
    "cb": ("defender", "centre_back"), "left back": ("defender", "left_back"), "lb": ("defender", "left_back"),
    "right back": ("defender", "right_back"), "rb": ("defender", "right_back"),
    "left wing back": ("defender", "left_wing_back"), "right wing back": ("defender", "right_wing_back"),
    "defensive midfield": ("midfielder", "defensive_midfield"), "cdm": ("midfielder", "defensive_midfield"),
    "dm": ("midfielder", "defensive_midfield"), "central midfield": ("midfielder", "central_midfield"),
    "cm": ("midfielder", "central_midfield"), "attacking midfield": ("midfielder", "attacking_midfield"),
    "cam": ("midfielder", "attacking_midfield"), "am": ("midfielder", "attacking_midfield"),
    "left midfield": ("midfielder", "left_midfield"), "right midfield": ("midfielder", "right_midfield"),
    "left winger": ("forward", "left_winger"), "lw": ("forward", "left_winger"),
    "right winger": ("forward", "right_winger"), "rw": ("forward", "right_winger"),
    "centre forward": ("forward", "centre_forward"), "center forward": ("forward", "centre_forward"),
    "cf": ("forward", "centre_forward"), "st": ("forward", "centre_forward"),
    "second striker": ("forward", "second_striker"), "ss": ("forward", "second_striker"),
}

NOT_A_POSITION: Final = frozenset({"", "sub", "substitute", "u", "unknown", "n a", "na", "none", "null"})
"""What the provider writes where it does not say a position: read as ``None``."""


@dataclass(frozen=True, slots=True)
class Position:
    group: str | None
    """One of ``GROUPS``, or None when the position is not known."""
    detail: str | None = None
    """The detailed role when the source gave one (``centre_back``), else None."""


def normalize_position(raw: object) -> Position:
    key = alias_key(raw)
    if key in NOT_A_POSITION:
        return Position(None)
    if key in _GROUP_OF:
        return Position(_GROUP_OF[key])
    if key in _DETAIL:
        group, detail = _DETAIL[key]
        return Position(group, detail)
    return Position(None)


def position_group(raw: object) -> str | None:
    """The group of a position as the provider (or any source) wrote it; None when it is not one."""
    return normalize_position(raw).group


def sql_case(column: str) -> str:
    """The same table as a SQL ``CASE`` over ``lower(btrim(column))``: what ``core.position_group`` is made of."""
    whens = [f"WHEN '{k}' THEN '{g}'" for k, g in sorted(_GROUP_OF.items())]
    whens += [f"WHEN '{k}' THEN '{g}'" for k, (g, _d) in sorted(_DETAIL.items())]
    expr = f"regexp_replace(lower(btrim({column})), '[^a-z0-9]+', ' ', 'g')"
    return f"CASE btrim({expr}) " + " ".join(whens) + " ELSE NULL END"
