"""The current coach read from the database, and the corrections of open careers written to it (AD-H03, IA-075).

Readers: ``current_coach(conn, team_ids)`` is what a profile service (AD-H07, C-09) will call - one query per call, bounded by
the teams asked and the window of ``fbi.people.current_coach.LOOKBACK_DAYS``. ``audit`` runs the rule over every team and
says what the corrections would be; ``close`` writes them (``apply=False``: a dry run that only counts); ``retract`` withdraws
one. Nothing here writes ``core.coach_careers``, ``core.fixture_lineups`` or any provider table: a correction is a row of
``core.coach_career_corrections``, read through the view ``core.coach_careers_audited``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

import psycopg

from fbi.people.current_coach import (
    LOOKBACK_DAYS,
    RULES_VERSION,
    Closure,
    Decision,
    OpenCareer,
    SamePerson,
    Sheet,
    closures_of,
    decide_all,
    same_person_by_names,
    summary,
)

LOCK_KEY: Final = "fbi.coach_current"

SHEETS_SQL: Final = """
SELECT s.team_id, s.fixture_id, s.kickoff_at, NULLIF(s.provider_coach_id, 0) AS provider_coach_id, s.coach_id, s.coach_name
  FROM (SELECT f.home_team_id AS team_id, f.id AS fixture_id, f.kickoff_at, l.provider_coach_id, l.coach_id, l.coach_name
          FROM core.fixtures f JOIN core.fixture_lineups l ON l.fixture_id = f.id AND l.team_side = 'home'
         WHERE f.kickoff_at > %(now)s - make_interval(days => %(days)s) AND f.kickoff_at <= %(now)s
           AND f.status_group IN ('finished', 'live') {home}
        UNION ALL
        SELECT f.away_team_id, f.id, f.kickoff_at, l.provider_coach_id, l.coach_id, l.coach_name
          FROM core.fixtures f JOIN core.fixture_lineups l ON l.fixture_id = f.id AND l.team_side = 'away'
         WHERE f.kickoff_at > %(now)s - make_interval(days => %(days)s) AND f.kickoff_at <= %(now)s
           AND f.status_group IN ('finished', 'live') {away}) s"""
"""The match sheets of the window, one row per team and match. ``{home}``/``{away}`` narrow it to some teams (the reader)."""

OPEN_SQL: Final = """
SELECT a.team_id, a.provider_coach_id, a.observed_at, a.ordinal, a.start_date, a.coach_id
  FROM core.coach_careers_audited a
 WHERE a.effective_end_date IS NULL AND a.team_id IS NOT NULL {teams}"""
"""The careers open now (net of the corrections in force) at a team we hold."""

PROFILES_SQL: Final = """
SELECT p.provider_coach_id, p.provider_team_id, p.name, btrim(concat_ws(' ', p.firstname, p.lastname)), p.birth_date
  FROM core.coach_profiles_latest p
 WHERE p.provider_coach_id = ANY(%(coaches)s)"""

PERSONS_SQL: Final = """
SELECT c.provider_coach_id, c.name, btrim(concat_ws(' ', c.firstname, c.lastname)), c.birth_date FROM core.coaches c
 WHERE c.provider_coach_id = ANY(%(coaches)s)"""

TEAMS_SQL: Final = "SELECT id, provider_team_id FROM core.teams WHERE id = ANY(%(ids)s)"


def _sheets(conn: psycopg.Connection[Any], now: datetime, team_ids: Sequence[int] | None) -> list[tuple[int, Sheet]]:
    params: dict[str, Any] = {"now": now, "days": LOOKBACK_DAYS}
    home = away = ""
    if team_ids is not None:
        params["teams"] = list(team_ids)
        home, away = "AND f.home_team_id = ANY(%(teams)s)", "AND f.away_team_id = ANY(%(teams)s)"
    with conn.cursor() as cur:
        cur.execute(SHEETS_SQL.format(home=home, away=away), params)
        return [(int(r[0]), Sheet(int(r[1]), r[2], int(r[3]) if r[3] else None, r[4], r[5])) for r in cur.fetchall()]


def _opens(conn: psycopg.Connection[Any], team_ids: Sequence[int] | None) -> list[tuple[int, OpenCareer]]:
    params: dict[str, Any] = {}
    teams = ""
    if team_ids is not None:
        params["teams"], teams = list(team_ids), "AND a.team_id = ANY(%(teams)s)"
    with conn.cursor() as cur:
        cur.execute(OPEN_SQL.format(teams=teams), params)
        return [(int(r[0]), OpenCareer(int(r[1]), r[2], int(r[3]), r[4], r[5])) for r in cur.fetchall()]


@dataclass(slots=True)
class _Context:
    profiles: dict[int, int | None]
    providers: dict[int, int]
    same: SamePerson


def _context(conn: psycopg.Connection[Any], sheets: Sequence[tuple[int, Sheet]],
             opens: Sequence[tuple[int, OpenCareer]]) -> _Context:
    coaches = sorted({s.provider_coach_id for _, s in sheets if s.provider_coach_id}
                     | {c.provider_coach_id for _, c in opens})
    teams = sorted({t for t, _ in sheets} | {t for t, _ in opens})
    names: dict[int, set[str]] = {}
    births: dict[int, date] = {}
    for _, s in sheets:
        if s.provider_coach_id and s.coach_name:
            names.setdefault(s.provider_coach_id, set()).add(s.coach_name)
    with conn.cursor() as cur:
        cur.execute(PROFILES_SQL, {"coaches": coaches})
        profiles: dict[int, int | None] = {}
        for cid, team, name, full, born in cur.fetchall():
            profiles[int(cid)] = int(team) if team is not None else None
            names.setdefault(int(cid), set()).update(n for n in (name, full) if n)
            if born:
                births[int(cid)] = born
        cur.execute(PERSONS_SQL, {"coaches": coaches})
        for cid, name, full, born in cur.fetchall():
            names.setdefault(int(cid), set()).update(n for n in (name, full) if n)
            if born and int(cid) not in births:
                births[int(cid)] = born
        cur.execute(TEAMS_SQL, {"ids": teams})
        providers = {int(r[0]): int(r[1]) for r in cur.fetchall()}
    same = same_person_by_names({k: tuple(sorted(v)) for k, v in names.items()}, births)
    return _Context(profiles, providers, same)


def _decide(sheets: Sequence[tuple[int, Sheet]], opens: Sequence[tuple[int, OpenCareer]], ctx: _Context,
            at: datetime) -> dict[int, Decision]:
    return decide_all(sheets, opens, now=at, profile_teams=ctx.profiles, team_provider_ids=ctx.providers,
                      same_person=ctx.same)


def decisions(conn: psycopg.Connection[Any], team_ids: Sequence[int] | None = None, *,
              now: datetime | None = None) -> dict[int, Decision]:
    """The rule over the teams asked (every team with a sheet or an open career when ``team_ids`` is None)."""
    at = now or datetime.now(UTC)
    sheets = _sheets(conn, at, team_ids)
    opens = _opens(conn, team_ids)
    return _decide(sheets, opens, _context(conn, sheets, opens), at)


def current_coach(conn: psycopg.Connection[Any], team_ids: Sequence[int], *,
                  now: datetime | None = None) -> dict[int, dict[str, object]]:
    """team id -> the current coach with its source and date (``CurrentCoach.as_dict``); a team with neither a sheet nor an open
    career is answered with ``reason = no_sheet``. One read, no write."""
    if not team_ids:
        return {}
    found = decisions(conn, team_ids, now=now)
    out: dict[int, dict[str, object]] = {}
    for team_id in team_ids:
        d = found.get(team_id)
        if d is None:
            out[team_id] = {"team_id": team_id, "source": None, "reason": "no_sheet", "rules_version": RULES_VERSION}
        else:
            out[team_id] = d.current.as_dict()
    return out


def _open_counts(opens: Iterable[tuple[int, OpenCareer]]) -> dict[int, int]:
    per: dict[int, set[int]] = {}
    for team_id, c in opens:
        per.setdefault(team_id, set()).add(c.provider_coach_id)
    return {t: len(s) for t, s in per.items()}


def audit(conn: psycopg.Connection[Any], *, now: datetime | None = None) -> dict[str, Any]:
    """The rule over every team: the answers by source and the corrections it would write. Only reads."""
    at = now or datetime.now(UTC)
    sheets = _sheets(conn, at, None)
    opens = _opens(conn, None)
    found = _decide(sheets, opens, _context(conn, sheets, opens), at)
    out: dict[str, Any] = dict(summary(found, open_before=_open_counts(opens)))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FILTER (WHERE action = 'close'), count(*) FILTER (WHERE action = 'retract') "
                    "FROM core.coach_career_corrections")
        row = cur.fetchone()
    out["corrections_written"] = int(row[0]) if row else 0
    out["corrections_retracted"] = int(row[1]) if row else 0
    out["rules_version"] = RULES_VERSION
    out["now"] = at.isoformat()
    return out


@dataclass(slots=True)
class CloseReport:
    applied: bool
    proposed: int = 0
    written: int = 0
    already: int = 0
    skipped_locked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"applied": self.applied, "proposed": self.proposed, "written": self.written, "already": self.already,
                "skipped_locked": self.skipped_locked, "rules_version": RULES_VERSION}


def _evidence(k: Closure) -> str:
    return json.dumps({"successor_provider_coach_id": k.successor_provider_coach_id,
                       "successor_since": k.successor_since.isoformat(), "successor_streak": k.successor_streak,
                       "successor_first_fixture_id": k.successor_fixture_id, "last_fixture_id": k.last_fixture_id},
                      sort_keys=True)


def close(conn: psycopg.Connection[Any], *, apply: bool = False, actor: str, now: datetime | None = None,
          team_ids: Sequence[int] | None = None) -> CloseReport:
    """Write the corrections the rule proposes (one per career row and rules version: a second pass writes nothing). A
    correction retracted once is not proposed again under the same rules version."""
    found = decisions(conn, team_ids, now=now)
    proposals = closures_of(found)
    report = CloseReport(applied=apply, proposed=len(proposals))
    if not apply:
        return report
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        got = cur.fetchone()
        if not (got and got[0]):
            report.skipped_locked, report.applied = True, False
            return report
        for team_id, k in proposals:
            cur.execute(
                "INSERT INTO core.coach_career_corrections (provider_coach_id, observed_at, ordinal, team_id, action, "
                "end_date, basis, rules_version, evidence, decided_by) "
                "VALUES (%s, %s, %s, %s, 'close', %s, %s, %s, %s::jsonb, %s) "
                "ON CONFLICT (provider_coach_id, observed_at, ordinal, rules_version) WHERE action = 'close' DO NOTHING",
                (k.provider_coach_id, k.observed_at, k.ordinal, team_id, k.end_date, k.basis, RULES_VERSION,
                 _evidence(k), actor))
            if cur.rowcount:
                report.written += 1
            else:
                report.already += 1
    return report


def retract(conn: psycopg.Connection[Any], correction_id: int, *, actor: str, note: str,
            apply: bool = False) -> dict[str, Any]:
    """Withdraw one correction (the career is open again in the audited view). Refused for an id that is not a close or that
    was already retracted."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT c.provider_coach_id, c.observed_at, c.ordinal, c.team_id, c.rules_version, "
                    "EXISTS (SELECT 1 FROM core.coach_career_corrections r WHERE r.retracts_id = c.id) "
                    "FROM core.coach_career_corrections c WHERE c.id = %s AND c.action = 'close'", (correction_id,))
        row = cur.fetchone()
        if row is None:
            return {"ok": False, "reason": "not_a_close"}
        if row[5]:
            return {"ok": False, "reason": "already_retracted"}
        if apply:
            cur.execute("INSERT INTO core.coach_career_corrections (provider_coach_id, observed_at, ordinal, team_id, action, "
                        "retracts_id, rules_version, decided_by, note) VALUES (%s, %s, %s, %s, 'retract', %s, %s, %s, %s)",
                        (row[0], row[1], row[2], row[3], correction_id, row[4], actor, note))
    return {"ok": True, "applied": apply, "retracts": correction_id}


def team_open_counts(conn: psycopg.Connection[Any]) -> Mapping[str, int]:
    """Teams by number of distinct coaches with a career open now, provider-only and net of corrections."""
    sql = """
    WITH p AS (SELECT team_id, count(DISTINCT provider_coach_id) n FROM core.coach_careers_audited
                WHERE provider_end_date IS NULL AND team_id IS NOT NULL GROUP BY 1),
         a AS (SELECT team_id, count(DISTINCT provider_coach_id) n FROM core.coach_careers_audited
                WHERE effective_end_date IS NULL AND team_id IS NOT NULL GROUP BY 1)
    SELECT (SELECT count(*) FROM p), (SELECT count(*) FROM p WHERE n > 1),
           (SELECT count(*) FROM a), (SELECT count(*) FROM a WHERE n > 1)"""
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    assert row
    return {"teams_open_provider": int(row[0]), "teams_open_gt1_provider": int(row[1]),
            "teams_open_audited": int(row[2]), "teams_open_gt1_audited": int(row[3])}
