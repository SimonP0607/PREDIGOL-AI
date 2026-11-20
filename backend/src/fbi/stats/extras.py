"""What PrediGol already keeps from API-Football and no page showed (plan PM, PM-05-05; BE-068): a player's offsides, dribbled past,
penalties won, committed and saved (``core.fixture_player_extras``), a team's offsides and goals prevented (``core.fixture_team_stats``),
as figures of the statistics documents (C-13 1.1.0, ``provider_extras``), each with its sample, its coverage in the competition season
and its origin (``api_football``: «dato de API-Football», measured by the provider and not recalculated by PrediGol).

Two switches, both OFF by default (the documents are then byte for byte what they were, so the nightly pass rewrites nothing):

* ``FBI_STATS_PROVIDER_EXTRAS``: the pass reads the extras and writes the figures;
* ``FBI_STATS_GOALS_PREVENTED``: adds a team's goals prevented. Turned on only when the quality probe passes
  (``python -m scripts.goals_prevented_probe``: coherence with the opponent's xG minus the goals conceded): the provider's field is
  known to be inconsistent, and the match centre has been dropping it.

A figure the competition season reports in less than ``COVERAGE`` of its appearances (team-matches) is ``sin_cobertura``; none at all,
``sin_datos``. Pure: no read, no write. Plan EA's rule of coverage (EA-008) and its threshold are the ones of ``fbi.stats.player``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from fbi.statmath import formulas as fx
from fbi.stats.data import PlayerLine
from fbi.stats.doc import Doc, missing

SWITCH: Final = "FBI_STATS_PROVIDER_EXTRAS"
GOALS_PREVENTED_SWITCH: Final = "FBI_STATS_GOALS_PREVENTED"
ORIGIN: Final = "api_football"
COVERAGE: Final = 0.8

Unit = Literal["por_90", "total", "por_partido"]


def _on(name: str, env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return e.get(name, "off").strip().lower() in ("1", "on", "true", "yes")


def extras_on(env: Mapping[str, str] | None = None) -> bool:
    return _on(SWITCH, env)


def goals_prevented_on(env: Mapping[str, str] | None = None) -> bool:
    """Only with the extras on: goals prevented is one of them."""
    return extras_on(env) and _on(GOALS_PREVENTED_SWITCH, env)


@dataclass(frozen=True, slots=True)
class Extra:
    key: str
    column: str
    unit: Unit
    better: Literal["mas", "menos"]


PLAYER_EXTRAS: Final[tuple[Extra, ...]] = (
    Extra("offsides", "offsides", "por_90", "menos"),
    Extra("dribbled_past", "dribbled_past", "por_90", "menos"),
    Extra("penalties_won", "penalties_won", "total", "mas"),
    Extra("penalties_committed", "penalties_committed", "total", "menos"),
    Extra("penalties_saved", "penalties_saved", "total", "mas"),
)
"""``core.fixture_player_extras``: the rare counts (penalties) as season totals, the others per 90."""
PLAYER_COLUMNS: Final[tuple[str, ...]] = tuple(e.column for e in PLAYER_EXTRAS)

TEAM_EXTRAS: Final[tuple[Extra, ...]] = (
    Extra("offsides", "offsides", "por_partido", "menos"),
    Extra("goals_prevented", "goals_prevented", "por_partido", "mas"),
)
"""``core.fixture_team_stats``: means per match of the team's own side."""


def figure(extra: Extra, value: float | None, with_data: int, share: float) -> Doc:
    """One ``ProviderFigure`` of C-13."""
    shown: float | Doc
    if with_data == 0 or value is None:
        shown = missing("sin_datos")
    elif share < COVERAGE:
        shown = missing("sin_cobertura")
    else:
        shown = fx.half_up(value, 3)
    return {"key": extra.key, "unit": extra.unit, "better": extra.better, "value": shown, "matches_with_data": with_data,
            "coverage": fx.half_up(share, 4), "origin": ORIGIN}


def player_coverage(lines: Sequence[PlayerLine]) -> dict[str, float]:
    """The share of the competition season's appearances that report each extra."""
    if not lines:
        return {}
    return {e.key: sum(1 for line in lines if line.counts.get(e.column) is not None) / len(lines) for e in PLAYER_EXTRAS}


def player_figures(lines: Sequence[PlayerLine], cover: Mapping[str, float]) -> list[Doc]:
    out = []
    for e in PLAYER_EXTRAS:
        count = minutes = 0.0
        used = 0
        for line in lines:
            c = line.counts.get(e.column)
            if c is None:
                continue
            used += 1
            count += c
            minutes += line.minutes
        value: float | None
        if used == 0:
            value = None
        elif e.unit == "total":
            value = count
        else:
            value = count * 90.0 / minutes if minutes > 0 else None
        out.append(figure(e, value, used, cover.get(e.key, 0.0)))
    return out


def team_extras(with_goals_prevented: bool) -> tuple[Extra, ...]:
    return tuple(e for e in TEAM_EXTRAS if with_goals_prevented or e.key != "goals_prevented")


def team_figures(values: Mapping[str, Sequence[float | None]], cover: Mapping[str, float], *, with_goals_prevented: bool) -> list[Doc]:
    """``values``: each extra's value in each of the team's matches (None: not reported)."""
    out = []
    for e in team_extras(with_goals_prevented):
        seen = [v for v in values.get(e.column, ()) if v is not None]
        out.append(figure(e, sum(seen) / len(seen) if seen else None, len(seen), cover.get(e.key, 0.0)))
    return out
