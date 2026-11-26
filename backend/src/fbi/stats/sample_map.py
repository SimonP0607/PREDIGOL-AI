"""The map of SAMPLE: how many matches each competition has for each family, and at which level each parameter must live (RP-3.1).

Section 8 of the restructuring plan puts every parameter at a level of a ladder - global, type of competition, league, team, referee - and
says when the league level may be used: with 200 matches or more WITH THE FIGURE in the window; below that the parameter inherits from the type
of competition. This module counts the matches (a figure that is NULL does not count), says the level, and keeps nothing that a decision reads:
it is a recomputable matrix, dated, that the next pieces (the hierarchical cards model, the corners and goals by competition) read to know where
a parameter may live.

    competition level .... the competition has ``MIN_MATCHES`` or more matches with the figure in the window
    type level ........... fewer: it inherits from the matches of its TYPE (domestic league, cup, continental...), pooled, if they reach the minimum
    global level ......... not even the type does: only the global figure is used

``level_of`` is the rule, pure. ``build`` pools exactly (sums and sums of squares, not averages of averages). ``read`` is one grouped query over
``market.fixture_outcomes`` for the competitions followed. Read-only; no migration.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.market.rules import OUTCOMES_VIEW

VERSION: Final = "sample-map-v1"
MIN_MATCHES: Final = 200
"""Section 8: the league level is used with 200 matches or more with the figure in the window."""
WINDOW_DAYS: Final = 1095
"""The fixed window: the last three years of matches."""

# family -> (the figure is there, the total counted). The six families of the plan; a NULL side makes the figure absent, never a zero.
FAMILIES: Final[Mapping[str, tuple[str, str]]] = {
    "goals": ("goals_ft_home IS NOT NULL AND goals_ft_away IS NOT NULL", "goals_ft_home + goals_ft_away"),
    "goals_half": ("goals_1h_home IS NOT NULL AND goals_1h_away IS NOT NULL", "goals_1h_home + goals_1h_away"),
    "corners": ("corners_ft_home IS NOT NULL AND corners_ft_away IS NOT NULL", "corners_ft_home + corners_ft_away"),
    "cards": ("cards_lines_ft_home IS NOT NULL AND cards_lines_ft_away IS NOT NULL", "cards_lines_ft_home + cards_lines_ft_away"),
    "shots": ("shots_ft_home IS NOT NULL AND shots_ft_away IS NOT NULL", "shots_ft_home + shots_ft_away"),
    "fouls": ("fouls_ft_home IS NOT NULL AND fouls_ft_away IS NOT NULL", "fouls_ft_home + fouls_ft_away"),
}

COMPETITION: Final = "competition"
TYPE: Final = "type"
GLOBAL: Final = "global"


def level_of(n_competition: int, n_type: int, *, minimum: int = MIN_MATCHES) -> str:
    """The level a parameter of a competition lives at: its own with ``minimum`` matches or more; otherwise its type's, if the type has them; otherwise
    the global one. A lower level is used only with sample: it never fills a gap with a guess."""
    if n_competition >= minimum:
        return COMPETITION
    if n_type >= minimum:
        return TYPE
    return GLOBAL


@dataclass(frozen=True, slots=True)
class Cell:
    """The matches of a competition (or of a type, or all) with the figure of a family: how many, and the sums that pool exactly."""

    n: int = 0
    total: float = 0.0
    squares: float = 0.0

    def __add__(self, other: Cell) -> Cell:
        return Cell(self.n + other.n, self.total + other.total, self.squares + other.squares)

    @property
    def mean(self) -> float | None:
        return self.total / self.n if self.n else None

    @property
    def variance(self) -> float | None:
        if self.n < 2:
            return None
        return max(0.0, (self.squares - self.total * self.total / self.n) / (self.n - 1))

    @property
    def dispersion(self) -> float | None:
        """Variance over mean (1 for a Poisson count; above 1 the count is more spread than Poisson says)."""
        m, v = self.mean, self.variance
        return None if m is None or v is None or m <= 0 else v / m

    def as_json(self) -> dict[str, Any]:
        return {"n": self.n, "mean": _r(self.mean), "dispersion": _r(self.dispersion)}


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def build(competitions: Iterable[Mapping[str, Any]], cells: Mapping[tuple[int, str], Cell], *, at: datetime,
          window_days: int = WINDOW_DAYS, minimum: int = MIN_MATCHES) -> dict[str, Any]:
    """The matrix from the competitions followed (id, name, country, type) and their cells ``(competition id, family) -> Cell``. Pure."""
    comps = [dict(c) for c in competitions]
    by_type: dict[tuple[str, str], Cell] = defaultdict(Cell)
    overall: dict[str, Cell] = defaultdict(Cell)
    for c in comps:
        for fam in FAMILIES:
            cell = cells.get((int(c["id"]), fam), Cell())
            by_type[(str(c["type"]), fam)] += cell
            overall[fam] += cell
    rows: list[dict[str, Any]] = []
    levels: dict[str, dict[str, int]] = {fam: {COMPETITION: 0, TYPE: 0, GLOBAL: 0} for fam in FAMILIES}
    for c in comps:
        per: dict[str, Any] = {}
        for fam in FAMILIES:
            own = cells.get((int(c["id"]), fam), Cell())
            pooled = by_type[(str(c["type"]), fam)]
            level = level_of(own.n, pooled.n, minimum=minimum)
            levels[fam][level] += 1
            per[fam] = {**own.as_json(), "level": level}
        rows.append({"competition_id": int(c["id"]), "name": c.get("name"), "country": c.get("country"), "type": c["type"], "families": per})
    types = {t: {fam: by_type[(t, fam)].as_json() for fam in FAMILIES} for t in sorted({str(c["type"]) for c in comps})}
    return {"version": VERSION, "at": at.isoformat(), "window_days": window_days, "min_matches": minimum, "families": list(FAMILIES),
            "competitions": rows, "types": types, "global": {fam: overall[fam].as_json() for fam in FAMILIES},
            "summary": {"competitions": len(rows), "levels": levels,
                        "with_a_level": len(rows)}}  # every competition gets a level for every family by construction


def read(conn: psycopg.Connection[Any], *, at: datetime, window_days: int = WINDOW_DAYS,
         minimum: int = MIN_MATCHES) -> dict[str, Any]:
    """The matrix over the competitions followed, for the matches that kicked off in the window. One grouped query per run; read-only."""
    since = at - timedelta(days=window_days)
    selects = [f"SELECT competition_id, '{fam}' AS family, count(*) AS n, sum({total})::float8 AS total, sum(({total})::float8 * ({total})::float8) AS squares "
               f"FROM {OUTCOMES_VIEW} WHERE is_tracked AND kickoff_at >= %(since)s AND kickoff_at < %(at)s AND {has} GROUP BY competition_id"
               for fam, (has, total) in FAMILIES.items()]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, name, country, competition_type AS type FROM core.competitions WHERE is_tracked ORDER BY id")
        competitions = cur.fetchall()
        cur.execute(" UNION ALL ".join(selects), {"since": since, "at": at})  # type: ignore[arg-type]
        cells = {(int(r["competition_id"]), str(r["family"])): Cell(int(r["n"]), float(r["total"] or 0.0), float(r["squares"] or 0.0))
                 for r in cur.fetchall()}
    return build(competitions, cells, at=at, window_days=window_days, minimum=minimum)
