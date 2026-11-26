"""``GET /fixtures/statistics?fixture=&half=true`` -> one DTO per match (plan PM, PM-05-01).

The provider answers with one entry per team: ``statistics`` (the match) and ``statistics_1h`` and ``statistics_2h`` (the two halves),
each a list of ``{"type": ..., "value": ...}``. The types and the way a value is read are those of the match's statistics
(``fbi.providers.api_football.details``: ``STAT_TYPES``, ``number``, ``integer``): "61%" is 61, "0.93" is 0.93, ``null`` and "" are None,
0 stays 0. A type this module has no column for (``Free Kicks``, ``Passes %``, ``goals_prevented`` - which the provider leaves empty by
half) is not stored; it stays in the RAW body the answer was kept in.

An answer is judged, not repaired: a half that is missing or empty is None for that team - never a zero - and ``halves`` is true only
when every team of the answer has both. Pure: no database, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from fbi.providers.api_football.details import DECIMAL_COLUMNS, STAT_TYPES, integer, number

PERIODS: Final[tuple[str, str]] = ("1h", "2h")
BLOCK_OF_PERIOD: Final[Mapping[str, str]] = {"1h": "statistics_1h", "2h": "statistics_2h"}

PERIOD_STAT_COLUMNS: Final[tuple[str, ...]] = (
    "shots", "shots_on_target", "shots_off_target", "shots_blocked", "shots_inside_box", "shots_outside_box", "corners", "fouls",
    "offsides", "yellow_cards", "red_cards", "saves", "possession_pct", "passes", "passes_accurate", "expected_goals",
)
"""The columns of ``core.fixture_team_stats_period``: those of the match table without ``goals_prevented`` (the provider leaves it
empty by half)."""

COUNTED: Final[tuple[str, ...]] = (
    "corners", "yellow_cards", "red_cards", "shots", "shots_on_target", "shots_off_target", "shots_blocked", "shots_inside_box",
    "shots_outside_box", "fouls", "offsides", "saves", "passes", "passes_accurate",
)
"""Whole-number counts that add up: first half + second half = the match."""

Value = Decimal | int | None


@dataclass(frozen=True, slots=True)
class TeamPeriods:
    provider_team_id: int
    total: Mapping[str, Value] | None
    first: Mapping[str, Value] | None
    second: Mapping[str, Value] | None

    def block(self, period: str) -> Mapping[str, Value] | None:
        return self.first if period == "1h" else self.second


@dataclass(frozen=True, slots=True)
class PeriodAnswer:
    provider_fixture_id: int
    teams: tuple[TeamPeriods, ...]

    @property
    def answered(self) -> bool:
        return bool(self.teams)

    @property
    def halves(self) -> bool:
        """Two teams, each with a non-empty first-half and second-half block."""
        return len(self.teams) == 2 and all(t.first is not None and t.second is not None for t in self.teams)

    def filled(self) -> frozenset[str]:
        """The statistics that came, for BOTH teams, in the match block and in both halves: the unit PM-01-05 decided on."""
        if not self.halves:
            return frozenset()
        return frozenset(
            name for name in PERIOD_STAT_COLUMNS
            if all(t.total is not None and t.total.get(name) is not None and t.first is not None and t.first.get(name) is not None
                   and t.second is not None and t.second.get(name) is not None for t in self.teams))

    def sums(self) -> tuple[frozenset[str], frozenset[str]]:
        """(adds up, does not add up): the counted statistics with the three figures for both teams, first half + second half = match."""
        if not self.halves:
            return frozenset(), frozenset()
        ok: set[str] = set()
        off: set[str] = set()
        for name in COUNTED:
            checks: list[bool] = []
            for t in self.teams:
                whole = None if t.total is None else t.total.get(name)
                a = None if t.first is None else t.first.get(name)
                b = None if t.second is None else t.second.get(name)
                if whole is None or a is None or b is None:
                    break
                checks.append(a + b == whole)
            else:
                (ok if all(checks) else off).add(name)
        return frozenset(ok), frozenset(off)

    @property
    def outcome(self) -> str:
        return "with_halves" if self.halves else ("without_halves" if self.answered else "empty")


def _values(block: Any) -> dict[str, Value] | None:
    """A block as ``{column: value}``; None when it is missing or empty (a half the provider did not give)."""
    if not isinstance(block, list) or not block:
        return None
    out: dict[str, Value] = {}
    for item in block:
        if not isinstance(item, dict):
            continue
        column = STAT_TYPES.get(str(item.get("type") or "").strip().lower())
        if column is None or column not in PERIOD_STAT_COLUMNS:
            continue
        raw = item.get("value")
        out[column] = number(raw) if column in DECIMAL_COLUMNS else integer(raw)
    return out


def _team_id(entry: Mapping[str, Any]) -> int | None:
    team = entry.get("team")
    value = team.get("id") if isinstance(team, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_period_answer(body: Mapping[str, Any], provider_fixture_id: int) -> PeriodAnswer:
    teams: list[TeamPeriods] = []
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        team_id = _team_id(entry)
        if team_id is None:
            continue
        teams.append(TeamPeriods(team_id, _values(entry.get("statistics")), _values(entry.get("statistics_1h")),
                                 _values(entry.get("statistics_2h"))))
    return PeriodAnswer(provider_fixture_id, tuple(teams))
