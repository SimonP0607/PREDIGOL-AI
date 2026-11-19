"""Whether a competition season records what a rule settles on (plan EA, EA-501; decision of 19-nov-2026): Mi parlay takes a market
of the catalogue only where its settlement data is there for at least ``MIN_SHARE`` of the finished matches of the season (and at
least ``MIN_MATCHES`` of them), so that a leg is settled by its rule and not voided for lack of data.

Measured on the data itself: the columns of ``market.fixture_outcomes`` the rule reads (``Rule.columns``), over the finished matches of
the season. The goals of the score are always there; corners, cards, shots, fouls, saves and offsides are not, league by league. Reads
only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.market.rules import Rule

MIN_SHARE: Final = 0.8
MIN_MATCHES: Final = 10
SCORE_FAMILIES: Final = frozenset({"goals", "goals_half"})
_COLUMN = re.compile(r"^[a-z0-9_]+$")

SEASON_SQL: Final = "SELECT competition_season_id FROM core.fixtures WHERE id = %s"


@dataclass(frozen=True, slots=True)
class Coverage:
    finished: int
    with_data: int

    @property
    def share(self) -> float:
        return self.with_data / self.finished if self.finished else 0.0

    @property
    def enough(self) -> bool:
        return self.finished >= MIN_MATCHES and self.share >= MIN_SHARE


def _sql(rule: Rule) -> str:
    cols = rule.columns
    if not cols or not all(_COLUMN.match(c) for c in cols):
        raise ValueError(f"rule {rule.key} names no readable columns")
    present = " AND ".join(f"o.{c} IS NOT NULL" for c in cols)
    return ("SELECT count(*), count(*) FILTER (WHERE " + present + ") FROM core.fixtures f "
            "LEFT JOIN market.fixture_outcomes o ON o.fixture_id = f.id "
            "WHERE f.competition_season_id = %s AND f.status_group = 'finished'")


def season_coverage(conn: psycopg.Connection[Any], competition_season_id: int, rule: Rule) -> Coverage:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(_sql(rule).encode(), (competition_season_id,))
        row = cur.fetchone()
    return Coverage(int(row[0]), int(row[1])) if row else Coverage(0, 0)


class SeasonCoverage:
    """Coverage of one competition season, rule by rule, read once per rule (one answer reads many markets of one match)."""

    def __init__(self, conn: psycopg.Connection[Any], competition_season_id: int | None) -> None:
        self._conn = conn
        self._cs = competition_season_id
        self._seen: dict[str, bool] = {}

    @classmethod
    def of_fixture(cls, conn: psycopg.Connection[Any], fixture_id: int) -> SeasonCoverage:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(SEASON_SQL, (fixture_id,))
            row = cur.fetchone()
        return cls(conn, int(row[0]) if row and row[0] is not None else None)

    def covered(self, rule: Rule) -> bool:
        if rule.family in SCORE_FAMILIES:
            return True
        if self._cs is None:
            return False
        if rule.key not in self._seen:
            try:
                self._seen[rule.key] = season_coverage(self._conn, self._cs, rule).enough
            except ValueError:
                self._seen[rule.key] = False
        return self._seen[rule.key]
