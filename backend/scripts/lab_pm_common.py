"""Plan PM, wave 6 (IA-154 to IA-157): what the LAB lines share - reading a ``lab-export-v2`` folder and the small statistics they use.

Runs OFF the server (the owner's laptop or a cloud container), on a folder written by ``scripts.lab_export run``: the folder is
checked against its manifest first (``lab_export.verify``, standard library), then each Parquet file is a DuckDB view named after
its table (``core_fixtures``, ``market_historical_odds``...). Nothing here reads or writes a database, a provider or the network.

``matches`` is the one reading of a finished match every line uses: the regulation score where there is one (``reg_goals``, else
``ft_goals``, else ``goals``), the competition, its season and whether that season is CLOSED (``is_current`` false and no match of it
left to play other than cancelled or abandoned ones - the protocols' definition).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

PRIORITY: tuple[int, ...] = (1, 2, 3, 4, 13, 49)
"""Premier League, Serie A, LaLiga, Bundesliga, Ligue 1 and Primera A of Colombia (internal competition ids)."""
MARKET_LEAGUES: tuple[int, ...] = (1, 2, 3, 4, 13)
NOT_PLAYED_OK = ("cancelled", "abandoned")
"""Status groups that do not keep a season open (a match that will never be played)."""


class ExportError(RuntimeError):
    """The folder is not a verified lab-export-v2 export."""


def manifest_run(folder: Path) -> dict[str, Any]:
    with (folder / "manifest.jsonl").open(encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("kind") == "run":
                return dict(obj)
    raise ExportError("manifest.jsonl has no run line")


def open_export(folder: Path, *, need: Sequence[str] = ()) -> Any:
    """A DuckDB connection with one view per exported table, after checking every file against the manifest."""
    import duckdb

    from scripts import lab_export

    problems = lab_export.verify(folder)
    if problems:
        raise ExportError("the export does not match its manifest: " + "; ".join(problems[:5]))
    run = manifest_run(folder)
    if run.get("version") not in ("lab-export-v2", "lab-export-v3"):
        raise ExportError(f"need a lab-export-v2 or later export, this one is {run.get('version')!r}")
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for p in sorted(folder.glob("*.parquet")):
        view = p.stem.replace(".", "_")
        con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{p.as_posix()}')")
    have = {p.stem for p in folder.glob("*.parquet")}
    missing = [t for t in need if t not in have]
    if missing:
        raise ExportError(f"the export lacks {missing}")
    return con


MATCHES_SQL = """
WITH st AS (
  SELECT competition_season_id AS cs_id,
         count(*) FILTER (WHERE status_group NOT IN ('finished', 'cancelled', 'abandoned')) AS open_left
    FROM core_fixtures GROUP BY 1
)
SELECT f.id AS fixture_id, f.kickoff_at, f.home_team_id AS home, f.away_team_id AS away, coalesce(f.is_neutral, false) AS neutral,
       cs.id AS cs_id, cs.competition_id AS comp, cs.season, c.type AS ctype, c.tier, c.is_tracked,
       (NOT coalesce(cs.is_current, false) AND coalesce(st.open_left, 0) = 0) AS closed,
       coalesce(r.reg_goals_home, r.ft_goals_home, r.goals_home) AS gh,
       coalesce(r.reg_goals_away, r.ft_goals_away, r.goals_away) AS ga
  FROM core_fixtures f
  JOIN core_competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core_competitions c ON c.id = cs.competition_id
  LEFT JOIN core_fixture_results r ON r.fixture_id = f.id
  LEFT JOIN st ON st.cs_id = cs.id
 WHERE f.status_group = 'finished'
   AND coalesce(r.reg_goals_home, r.ft_goals_home, r.goals_home) IS NOT NULL
   AND coalesce(r.reg_goals_away, r.ft_goals_away, r.goals_away) IS NOT NULL
"""


def one(con: Any, sql: str) -> Any:
    """The first row of ``sql`` (None when empty); DuckDB 2 wants every result fetched to the end."""
    rows = con.execute(sql).fetchall()
    return rows[0] if rows else None


def matches(con: Any) -> Any:
    """Finished matches with a score (a DuckDB relation; ``.df()``/``.fetchall()`` to read it)."""
    return con.sql(MATCHES_SQL)


# ── small statistics ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def wilson(successes: float, n: float, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval of a proportion (Brown, Cai and DasGupta 2001); ``successes`` may be fractional."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def block_bootstrap_mean(values: NDArray[np.float64], blocks: NDArray[np.int64], *, reps: int, seed: int,
                         level: float = 0.95) -> tuple[float, float, float]:
    """Mean of ``values`` and its percentile interval when whole blocks (weeks, seasons) are resampled with replacement."""
    if values.size == 0:
        return (math.nan, math.nan, math.nan)
    ids, inv = np.unique(blocks, return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=ids.size)
    counts = np.bincount(inv, minlength=ids.size).astype(np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, ids.size, size=(reps, ids.size))
    boot = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lo, hi = np.quantile(boot, [(1 - level) / 2, 1 - (1 - level) / 2])
    return (float(values.mean()), float(lo), float(hi))


def log_loss_1x2(p: NDArray[np.float64], outcome: NDArray[np.int64], *, eps: float = 1e-12) -> NDArray[np.float64]:
    """Per match: -log of the probability given to the outcome (0 home, 1 draw, 2 away); rows of ``p`` are home, draw, away."""
    return -np.log(np.clip(p[np.arange(p.shape[0]), outcome], eps, 1.0))


def outcome_of(gh: NDArray[np.int64], ga: NDArray[np.int64]) -> NDArray[np.int64]:
    return np.where(gh > ga, 0, np.where(gh == ga, 1, 2)).astype(np.int64)


def monday_of(moment: datetime) -> datetime:
    """00:00 UTC of the Monday of the ISO week of ``moment``."""
    d = moment.astimezone(UTC)
    start = datetime(d.year, d.month, d.day, tzinfo=UTC)
    return start.fromordinal(start.toordinal() - start.weekday()).replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Stamp:
    """What a LAB result carries: its protocol (key, version, fingerprint) and the export it read (version, snapshot, when)."""

    protocol: Mapping[str, Any]
    export: Mapping[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"protocol": dict(self.protocol), "export": dict(self.export)}


def stamp(key: str, folder: Path | None) -> Stamp:
    import fbi.research.protocol as protocol

    export: dict[str, Any] = {}
    if folder is not None:
        run = manifest_run(folder)
        export = {k: run.get(k) for k in ("version", "snapshot", "at", "code_version", "filters") if k in run}
        export["folder"] = folder.name
    return Stamp(protocol.stamp(key), export)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, default=_default) + "\n", encoding="utf-8")


def _default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o).__name__)


def r6(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), 6)
