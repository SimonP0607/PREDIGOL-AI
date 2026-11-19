"""The nightly pass of the statistics documents (plan EA, EA-003 to EA-006 and EA-008): ``FBI_STATS_AGG``.

``FBI_STATS_AGG`` = ``off`` (the default; anything not understood is off) or ``on``. Off, the worker does not schedule the job. On, once
a night (``HOUR`` UTC) one pass goes through every current competition season that is not a friendly and has at least
``MIN_MATCHES`` finished matches, reads it once (``fbi.stats.data``), computes every team's and player's documents in memory
(``fbi.stats.team``, ``fbi.stats.player``) and writes them to ``analytics.stat_documents`` (revision 0167), one transaction per
competition season. A document the season no longer produces (a scope a team fell out of) is deleted with the rest of that season's
old rows, so what a page reads is always one pass.

Each season also gets its ``league`` document: the coverage of every metric (EA-008: publishable at ``COVERAGE``), how many matches and
teams it rests on and the survival of 0-0 over all its matches.

Reads stored data only: no provider, no model of language, no forecast, no pick. Nothing it writes is read by a model, a decision or a
settlement. ``analytics.stat_runs`` keeps one row per pass with its duration (acceptance: under 35 minutes a night).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from fbi.stats import data as sd
from fbi.stats import player as sp
from fbi.stats import team as st

SWITCH: Final = "FBI_STATS_AGG"
JOB: Final = "stats_documents"
HOUR: Final = 7
"""07:20 UTC, 02:20 in Bogotá: after the night's results and before the morning's pages."""
MINUTE: Final = 20
MIN_MATCHES: Final = 10
LOCK: Final = 0x0EA003
CALC_VERSION: Final = "stats-docs-v1"
COVERAGE: Final = 0.8
MAX_SECONDS: Final = 35 * 60


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON: {type(value).__name__}")


def dumps(doc: Any) -> str:
    """The document as JSON (times in ISO 8601 with their zone)."""
    return json.dumps(doc, default=_default, separators=(",", ":"))


def as_json(doc: dict[str, Any]) -> Jsonb:
    return Jsonb(doc, dumps=dumps)


def mode(env: Mapping[str, str] | None = None) -> str:
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "off").strip().lower() in ("1", "on", "true", "yes") else "off"


UPSERT_SQL: Final = """
INSERT INTO analytics.stat_documents (kind, entity_id, competition_season_id, scope, context, calc_version, sample, doc, computed_at)
VALUES (%(kind)s, %(entity)s, %(cs)s, %(scope)s, %(context)s, %(version)s, %(sample)s, %(doc)s, %(at)s)
ON CONFLICT (kind, entity_id, competition_season_id, scope, context) DO UPDATE
   SET calc_version = EXCLUDED.calc_version, sample = EXCLUDED.sample, computed_at = EXCLUDED.computed_at,
       doc = CASE WHEN analytics.stat_documents.doc IS DISTINCT FROM EXCLUDED.doc THEN EXCLUDED.doc ELSE analytics.stat_documents.doc END
"""
"""BE-050: a document that did not change keeps its stored value (its TOAST pointer), so a night that adds no match to a season
rewrites only the small row, not the document: the table does not double in size night after night."""
PRUNE_SQL: Final = "DELETE FROM analytics.stat_documents WHERE competition_season_id = %(cs)s AND computed_at < %(at)s"


@dataclass(slots=True)
class PassReport:
    seasons: int = 0
    documents: int = 0
    seconds: float = 0.0
    stopped: str | None = None
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"seasons": self.seasons, "documents": self.documents, "seconds": round(self.seconds, 1), "stopped": self.stopped,
                "errors": self.errors}


def league_doc(data: sd.SeasonData, refs: Mapping[str, st.LeagueRef], run_id: int | None) -> dict[str, Any]:
    team_cover = st.coverage(data)
    player_cover = sp.coverage(data.players)
    teams = {m.home_id for m in data.matches} | {m.away_id for m in data.matches}
    return {
        "competition_season_id": data.season.id, "matches": len(data.matches), "teams": len(teams),
        "player_lines": len(data.players), "run_id": run_id, "calc_version": CALC_VERSION, "threshold": COVERAGE,
        "coverage": [{"key": k, "share": v, "publishable": v >= COVERAGE} for k, v in sorted(team_cover.items())]
        + [{"key": f"player_{k}", "share": v, "publishable": v >= COVERAGE} for k, v in sorted(player_cover.items())],
        "means": {c: {k: round(v, 4) for k, v in r.means.items()} for c, r in refs.items()},
        "scatter": sp.scatter(data),
    }


def season_rows(data: sd.SeasonData, run_id: int | None, at: datetime) -> list[dict[str, Any]]:
    """Every row one competition season writes."""
    docs, refs, _ = st.season_documents(data)
    rows: list[dict[str, Any]] = []
    for d in docs:
        rows.append({"kind": "team", "entity": d.team_id, "cs": data.season.id, "scope": d.scope, "context": d.context,
                     "version": st.CALC_VERSION, "sample": d.sample, "doc": as_json(d.body), "at": at})
    for p in sp.season_documents(data):
        rows.append({"kind": "player", "entity": p.player_id, "cs": data.season.id, "scope": "season", "context": "all",
                     "version": sp.CALC_VERSION, "sample": p.sample, "doc": as_json(p.body), "at": at})
    rows.append({"kind": "league", "entity": data.season.id, "cs": data.season.id, "scope": "season", "context": "all",
                 "version": CALC_VERSION, "sample": len(data.matches), "doc": as_json(league_doc(data, refs, run_id)), "at": at})
    return rows


def write_season(conn: psycopg.Connection[Any], data: sd.SeasonData, run_id: int | None, at: datetime) -> int:
    rows = season_rows(data, run_id, at)
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
        cur.execute(PRUNE_SQL, {"cs": data.season.id, "at": at})
    return len(rows)


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None = None,
             only: set[int] | None = None, max_seconds: float = MAX_SECONDS) -> PassReport:
    report = PassReport()
    started = time.monotonic()
    locked = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
    if not locked or not locked[0]:
        report.stopped = "otro_pase_en_curso"
        return report
    try:
        row = conn.execute("INSERT INTO analytics.stat_runs (calc_version, code_version) VALUES (%s, %s) RETURNING id",
                           (CALC_VERSION, code_version)).fetchone()
        run_id = int(row[0]) if row else None
        conn.commit()
        for season in sd.seasons(conn, min_matches=MIN_MATCHES):
            if only is not None and season.id not in only:
                continue
            if time.monotonic() - started > max_seconds:
                report.stopped = "tiempo_maximo"
                break
            try:
                data = sd.load_season(conn, season)
                report.documents += write_season(conn, data, run_id, now)
                # The reads above open the connection's transaction, so write_season's block is a savepoint: commit here, one season
                # at a time, so that a pass never holds one long write transaction (and a failure keeps the seasons already done).
                conn.commit()
                report.seasons += 1
            except Exception as exc:  # one season's failure never stops the others
                conn.rollback()
                report.errors.append(f"{season.id}: {type(exc).__name__}: {exc}"[:200])
        report.seconds = time.monotonic() - started
        conn.execute("UPDATE analytics.stat_runs SET finished_at = now(), seasons = %s, documents = %s, seconds = %s, "
                     "stopped_reason = %s WHERE id = %s",
                     (report.seasons, report.documents, round(report.seconds, 2), report.stopped, run_id))
        conn.commit()
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        conn.commit()
    return report
