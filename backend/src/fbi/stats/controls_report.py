"""The report of the controls of RP-6.4 over the real documents: what the three checks say about the teams of the coming matches, and the
replay of the past days that closes the piece («cero hechos con datos posteriores al corte»).

Read only. It reads documents with ``fbi.stats.reading`` and judges them with ``fbi.stats.controls``; it builds no fact and writes nothing.
The table keeps ONE document per entity (the nightly pass replaces it), so the replay of a past moment cannot rebuild what was known then:
it proves that every document computed after the moment is REFUSED (``after_cutoff``) and that every figure it does hand over carries a date
the moment can check. It says so in its own output (``nota``)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.stats import controls
from fbi.stats import reading as rd

VERSION: Final = "stats-controls-report-v1"
UPCOMING_DAYS: Final = 7
REPLAY_LEAD: Final = timedelta(hours=1)
"""A fact for a match is made before it: the replay puts the cut-off one hour before the kickoff."""

UPCOMING_SQL: Final = """
SELECT competition_season_id, home_team_id, away_team_id, kickoff_at FROM core.fixtures
 WHERE kickoff_at > %(at)s AND kickoff_at <= %(hi)s AND status_group = 'scheduled' ORDER BY kickoff_at, id
"""
PLAYED_SQL: Final = """
SELECT competition_season_id, home_team_id, away_team_id, kickoff_at FROM core.fixtures
 WHERE kickoff_at >= %(lo)s AND kickoff_at < %(at)s AND status_group = 'finished' ORDER BY kickoff_at, id
"""


def _pairs(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[tuple[int, int, datetime]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [(int(cs), int(team), ko) for cs, home, away, ko in rows for team in (home, away)]


def upcoming(conn: psycopg.Connection[Any], *, at: datetime, min_sample: int, days: int = UPCOMING_DAYS) -> dict[str, Any]:
    """The documents (season, all) of the teams that play in the next days, at the cut-off ``at``, and what the controls say of each."""
    seen: set[tuple[int, int]] = set()
    status: Counter[str] = Counter()
    found: Counter[str] = Counter()
    checked = leaks = 0
    for cs, team, _ko in _pairs(conn, UPCOMING_SQL, {"at": at, "hi": at + timedelta(days=days)}):
        if (cs, team) in seen:
            continue
        seen.add((cs, team))
        doc = rd.read(conn, kind="team", entity_id=team, competition_season_id=cs, scope="season", context="all", as_of=at)
        status[doc.status] += 1
        if doc.status != "ok":
            continue
        verdict = controls.check(conn, doc, as_of=at, min_sample=min_sample)
        found.update(verdict.codes)
        try:
            checked += controls.assert_no_leak([doc.citation(r.key) for r in doc.readings], as_of=at)
        except controls.LeakError:
            leaks += 1
    return {"days": days, "teams": len(seen), "status": dict(status), "controls": {c: found.get(c, 0) for c in controls.CODES},
            "citations_checked": checked, "documents_with_a_leak": leaks}


def replay(conn: psycopg.Connection[Any], *, at: datetime, days: int) -> dict[str, Any]:
    """For every team of every match finished in the last ``days`` days: the document as it can be read at the moment a fact for that match
    would have been made. ``facts_with_a_leak`` must be 0."""
    status: Counter[str] = Counter()
    checked = leaks = moments = 0
    for cs, team, ko in _pairs(conn, PLAYED_SQL, {"at": at, "lo": at - timedelta(days=days)}):
        moments += 1
        cutoff = ko - REPLAY_LEAD
        doc = rd.read(conn, kind="team", entity_id=team, competition_season_id=cs, scope="season", context="all", as_of=cutoff)
        status[doc.status] += 1
        if doc.status != "ok":
            continue
        try:
            checked += controls.assert_no_leak([doc.citation(r.key) for r in doc.readings], as_of=cutoff)
        except controls.LeakError:
            leaks += 1
    return {"days": days, "moments": moments, "status": dict(status), "citations_checked": checked, "facts_with_a_leak": leaks,
            "refused_after_cutoff": status.get("after_cutoff", 0),
            "nota": "La tabla guarda un solo documento por entidad: la repetición prueba que lo calculado después del momento se rechaza y que "
                    "toda cifra entregada lleva una fecha comprobable, no reconstruye lo que se sabía entonces."}


def report(conn: psycopg.Connection[Any], *, at: datetime, min_sample: int, replay_days: int = 30) -> dict[str, Any]:
    return {"version": VERSION, "controls_version": controls.VERSION, "reading_version": rd.VERSION, "as_of": at.isoformat(),
            "min_sample": min_sample, "upcoming": upcoming(conn, at=at, min_sample=min_sample),
            "replay": replay(conn, at=at, days=replay_days)}


__all__ = ["VERSION", "replay", "report", "upcoming"]
