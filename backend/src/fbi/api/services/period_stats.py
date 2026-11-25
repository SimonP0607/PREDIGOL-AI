"""A match's statistics by half served (plan PM, PM-10-03): the match, the first half and the second half of the statistics its
competition has built (``fbi.core.period_rules``: >= 90 % of the matches asked carry the statistic in both halves for both teams, at
least 5). Read only: ``core.fixture_team_stats_period`` and ``core.fixture_team_stats`` (the match's total, the same provider and the same
columns). A statistic the competition has not built is not in the answer, and a figure the provider did not send is null - the page says
«información no disponible», it never draws a zero. Every route answers 404 while ``FBI_MATCH_HALVES`` is off (the default)."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Final

from fbi.api.cache import shared
from fbi.api.contracts.period_stats import MatchPeriodStats, PeriodBlock, PeriodFigure
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.switches import match_halves_on
from fbi.core.period_rules import STATS, decide

CACHE_SECONDS: Final = 60
SHOWN: Final[tuple[str, ...]] = (
    "possession_pct", "expected_goals", "shots", "shots_on_target", "corners", "fouls", "offsides", "yellow_cards", "red_cards", "saves",
)
"""What the card draws, in its order (a built statistic outside this list is kept in the table and not drawn here)."""

COMPETITION_SQL: Final = """
SELECT cs.competition_id FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id WHERE f.id = %(id)s
"""
ASKED_SQL: Final = """
SELECT count(*) AS asked FROM core.fixture_period_asks a JOIN core.fixtures f ON f.id = a.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id WHERE cs.competition_id = %(competition)s
"""
FILLED_SQL: Final = """
SELECT s AS stat, count(*) AS n FROM core.fixture_period_asks a JOIN core.fixtures f ON f.id = a.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 CROSS JOIN LATERAL unnest(a.filled) AS s WHERE cs.competition_id = %(competition)s GROUP BY 1
"""
_COLUMNS: Final = ", ".join(STATS)
PERIOD_SQL: Final = f"SELECT team_side, period, fetched_at, {_COLUMNS} FROM core.fixture_team_stats_period WHERE fixture_id = %(id)s AND source = 'api-football'"
TOTAL_SQL: Final = f"SELECT team_side, {_COLUMNS} FROM core.fixture_team_stats WHERE fixture_id = %(id)s AND source = 'api-football'"


def _guard() -> None:
    if not match_halves_on():
        raise ApiError(404, "not_found", "not found")


def _number(value: object) -> float | None:
    return None if value is None else float(value) if isinstance(value, Decimal | int | float) else None


def match(conn: Conn, fixture_id: int) -> Envelope[MatchPeriodStats]:
    _guard()
    return _cached(conn, fixture_id)


@shared(CACHE_SECONDS)
def _cached(conn: Conn, fixture_id: int) -> Envelope[MatchPeriodStats]:
    row = fetch_one(conn, COMPETITION_SQL, {"id": fixture_id})
    if row is None:
        raise ApiError(404, "not_found", "not found")
    competition = int(row["competition_id"])
    asked_row = fetch_one(conn, ASKED_SQL, {"competition": competition})
    asked = int(asked_row["asked"]) if asked_row else 0
    filled = Counter({str(r["stat"]): int(r["n"]) for r in fetch_all(conn, FILLED_SQL, {"competition": competition})})
    decisions = decide(asked, filled)
    built = [stat for stat in SHOWN if decisions[stat].build]
    empty = MatchPeriodStats(fixture_id=fixture_id, built=built, asked=asked, periods=[])
    if not built:
        return unavailable(empty, "sin_estadisticas_por_mitad", status=DataStatus.NOT_AVAILABLE)
    halves = fetch_all(conn, PERIOD_SQL, {"id": fixture_id})
    if not halves:
        return unavailable(empty, "partido_sin_mitades", status=DataStatus.NOT_AVAILABLE)
    totals = {str(r["team_side"]): r for r in fetch_all(conn, TOTAL_SQL, {"id": fixture_id})}
    by_period: dict[str, dict[str, dict[str, object]]] = {"1h": {}, "2h": {}}
    for r in halves:
        by_period[str(r["period"])][str(r["team_side"])] = r
    blocks: list[PeriodBlock] = []
    for period, source in (("total", totals), ("1h", by_period["1h"]), ("2h", by_period["2h"])):
        figures = [PeriodFigure(key=stat, home=_number(source.get("home", {}).get(stat)), away=_number(source.get("away", {}).get(stat)))
                   for stat in built]
        blocks.append(PeriodBlock(period=period, figures=figures))  # type: ignore[arg-type]
    as_of = max((r["fetched_at"] for r in halves), default=None)
    return ok(MatchPeriodStats(fixture_id=fixture_id, built=built, asked=asked, periods=blocks, as_of=as_of), data_as_of=as_of)
