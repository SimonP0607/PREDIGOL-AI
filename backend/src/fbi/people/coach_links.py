"""The careers of the coaches tied to the person and to the club (plan F3).

``core.coach_careers`` is what the provider lists for a coach - a row per club he managed, a snapshot each time the list changes - with
the provider's ids. ``core.coaches`` is the person as we hold him (made from the match sheets: a coach we have seen on one) and
``core.teams`` the clubs we hold. Nothing tied them: a row of a career was two provider ids and a text. This pass ties them -
``coach_id`` and ``team_id`` of every row, which the view ``core.coach_spells`` shows for the newest snapshot of each career - and gives
a person to the coach who has a profile (the weekly ``/coachs`` refresh brings those of the tracked teams) and that no match sheet
has named yet.

It never invents anything: a row of a club we do not hold keeps ``team_id`` NULL (the club is not in the catalogue), the career of a
coach nobody has a name for keeps ``coach_id`` NULL, and a link already made is never touched. It reads the facts already stored and
asks the provider for nothing; a pass writes only the difference, so a second one writes nothing, and a dry run (the default of the
console) only counts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Final

import psycopg

JOB: Final = "coach_links"
LOCK_KEY: Final = "fbi.coach_links"
MANUAL_LOCK_WAIT: Final = "20s"

_CREATABLE: Final = "p.provider_coach_id > 0 AND btrim(coalesce(p.name, '')) <> ''"
"""A profile that can become a person: a real provider id and a name (``core.coaches.name`` is mandatory)."""

PERSONS_WANTED: Final = f"""
SELECT p.provider_coach_id, btrim(p.name) AS name, p.firstname, p.lastname, p.birth_date, p.nationality, p.payload_hash,
       p.observed_at AS fetched_at
  FROM core.coach_profiles_latest p
 WHERE {_CREATABLE} AND NOT EXISTS (SELECT 1 FROM core.coaches c WHERE c.provider_coach_id = p.provider_coach_id)"""
"""The profiles that have no person yet, with what the person is made of."""

COACH_LINKABLE: Final = f"""
  FROM core.coach_careers k
 WHERE k.coach_id IS NULL AND (EXISTS (SELECT 1 FROM core.coaches c WHERE c.provider_coach_id = k.provider_coach_id)
        OR EXISTS (SELECT 1 FROM core.coach_profiles_latest p WHERE p.provider_coach_id = k.provider_coach_id AND {_CREATABLE}))"""
"""The rows with no person that will have one once the persons above are made."""

TEAM_LINKABLE: Final = """
  FROM core.coach_careers k
 WHERE k.team_id IS NULL AND EXISTS (SELECT 1 FROM core.teams t WHERE t.provider_team_id = k.provider_team_id)"""
"""The rows of a club we hold that do not point at it yet."""


@dataclass(slots=True)
class BuildReport:
    applied: bool = False
    skipped_locked: bool = False
    seconds: float = 0.0
    persons_created: int = 0
    """Coaches with a profile that had no person: ``core.coaches`` rows made from it."""
    careers_coach_linked: int = 0
    """Rows of careers that got their ``coach_id``."""
    careers_team_linked: int = 0
    """Rows of careers that got their ``team_id``."""

    @property
    def changed(self) -> bool:
        return bool(self.persons_created or self.careers_coach_linked or self.careers_team_linked)

    def as_dict(self) -> dict[str, Any]:
        return {"applied": self.applied, "skipped_locked": self.skipped_locked, "seconds": round(self.seconds, 1),
                "persons_created": self.persons_created, "careers_coach_linked": self.careers_coach_linked,
                "careers_team_linked": self.careers_team_linked}


def _lock(conn: psycopg.Connection[Any], *, wait: bool) -> bool:
    with conn.cursor() as cur:
        if wait:
            cur.execute(f"SET LOCAL lock_timeout = '{MANUAL_LOCK_WAIT}'")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
            return True
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        row = cur.fetchone()
        return bool(row and row[0])


def _count(cur: psycopg.Cursor[Any], sql: str) -> int:
    cur.execute(sql)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def build(conn: psycopg.Connection[Any], *, apply: bool = False, wait: bool = False) -> BuildReport:
    """One pass. Without ``apply`` nothing is written and the report says what would be. ``wait`` takes the lock and waits for it (a
    person at the console); the worker does not wait: when another pass is writing it returns ``skipped_locked``."""
    started = time.monotonic()
    report = BuildReport(applied=apply)
    with conn.transaction():
        if apply and not _lock(conn, wait=wait):
            report.skipped_locked = True
            report.applied = False
            return report
        with conn.cursor() as cur:
            if apply:
                cur.execute("INSERT INTO core.coaches (provider_coach_id, name, firstname, lastname, birth_date, nationality, "
                            f"source_payload_hash, source_fetched_at) {PERSONS_WANTED} ON CONFLICT (provider_coach_id) DO NOTHING")
                report.persons_created = max(cur.rowcount, 0)
                cur.execute("UPDATE core.coach_careers k SET coach_id = c.id FROM core.coaches c "
                            "WHERE c.provider_coach_id = k.provider_coach_id AND k.coach_id IS NULL")
                report.careers_coach_linked = max(cur.rowcount, 0)
                cur.execute("UPDATE core.coach_careers k SET team_id = t.id FROM core.teams t "
                            "WHERE t.provider_team_id = k.provider_team_id AND k.team_id IS NULL")
                report.careers_team_linked = max(cur.rowcount, 0)
            else:
                report.persons_created = _count(cur, f"SELECT count(*) FROM ({PERSONS_WANTED}) w")
                report.careers_coach_linked = _count(cur, f"SELECT count(*) {COACH_LINKABLE}")
                report.careers_team_linked = _count(cur, f"SELECT count(*) {TEAM_LINKABLE}")
    report.seconds = time.monotonic() - started
    return report


# ── the figures ──────────────────────────────────────────────────────────────────────────────────────────────────────────

COUNTS: Final = (
    ("coaches", "SELECT count(*) FROM core.coaches"),
    ("profiles_without_person", """
        SELECT count(*) FROM core.coach_profiles_latest p
         WHERE NOT EXISTS (SELECT 1 FROM core.coaches c WHERE c.provider_coach_id = p.provider_coach_id)"""),
    ("careers", "SELECT count(*) FROM core.coach_careers"),
    ("careers_without_coach", "SELECT count(*) FROM core.coach_careers WHERE coach_id IS NULL"),
    ("careers_of_clubs_not_held", "SELECT count(*) FROM core.coach_careers WHERE team_id IS NULL AND provider_team_id IS NOT NULL"),
    ("careers_without_club", "SELECT count(*) FROM core.coach_careers WHERE provider_team_id IS NULL"),
    ("spells", "SELECT count(*) FROM core.coach_spells"),
    ("spells_with_person_and_club", "SELECT count(*) FROM core.coach_spells WHERE coach_id IS NOT NULL AND team_id IS NOT NULL"),
    ("spells_open", "SELECT count(*) FROM core.coach_spells WHERE end_date IS NULL"),
    ("coach_links_to_another_person", """
        SELECT count(*) FROM core.coach_careers k JOIN core.coaches c ON c.id = k.coach_id
         WHERE c.provider_coach_id <> k.provider_coach_id"""),
    ("team_links_to_another_club", """
        SELECT count(*) FROM core.coach_careers k JOIN core.teams t ON t.id = k.team_id
         WHERE t.provider_team_id IS DISTINCT FROM k.provider_team_id"""),
)
INVARIANTS: Final = ("coach_links_to_another_person", "team_links_to_another_club")
"""Counts that must be zero: a row of a career pointing at a person or a club that is not the one its provider ids name."""


def counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """The figures of the tables, cheap: no pass is simulated (``audit`` adds what a pass would write)."""
    with conn.cursor() as cur:
        return {name: _count(cur, sql) for name, sql in COUNTS}


def broken_invariants(figures: dict[str, Any]) -> list[str]:
    """The invariants that do not hold in ``figures`` (an audit or ``counts``); empty when all is well."""
    return [name for name in INVARIANTS if figures[name]]


def audit(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """The state of the tables, read from the database, and what a pass would still write (it must be nothing)."""
    out: dict[str, Any] = dict(counts(conn))
    pending = build(conn, apply=False)
    out["pass_would_write"] = {"persons": pending.persons_created, "coach_links": pending.careers_coach_linked,
                               "team_links": pending.careers_team_linked}
    return out
