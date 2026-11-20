"""The shadow comparison of the availability matrix (plan PM, section 4; PM-02-06): ``FBI_AVAILABILITY_SHADOW``.

Before any module reads the matrix (PM-14-04), fourteen days of record say where what each module shows today differs from what the matrix
would say, read at the same instant - so that switching a module to the matrix cannot hide something that is shown well today. Each
discrepancy needs a cause and a decision before its module is switched (the owner's reading, with the console of PM-02-08).

This module holds the pure part - what a discrepancy is - and the writing. The readings of the modules are the API's own functions (C-14,
C-13, Mi parlay's policy), so the comparison that reads them lives beside them (``fbi.api.services.availability_shadow``) and runs in the
same process of its own as the nightly batch (``scripts.availability_refresh``), never in the worker. A sample of ``SAMPLE`` matches a
day: the next ones to be played. Nothing a reader sees; ``analytics.availability_discrepancies`` only grows.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.coverage.levels import RULES_VERSION

SWITCH: Final = "FBI_AVAILABILITY_SHADOW"
JOB: Final = "availability_shadow"
SAMPLE: Final = 500
HORIZON: Final = timedelta(hours=48)
MAX_ROWS_PER_DAY: Final = 20_000
"""A bound on what one day may append (500 matches x some 40 markets): a module gone wrong must not fill the table."""

C13_DATA: Final[dict[str, str]] = {"corners_for": "corners", "shots_for": "shots", "shots_on_target_for": "shots_on_target",
                                   "xg_for": "xg", "fouls": "fouls", "cards": "yellow_cards"}
"""The figures of the statistics documents (C-13, ``fbi.stats.team``) and the datum of the matrix each one rests on."""


def mode(env: Mapping[str, str] | None = None) -> str:
    """``on`` unless the switch says off: it only records, and nothing a reader sees reads the record."""
    e = os.environ if env is None else env
    return "off" if e.get(SWITCH, "on").strip().lower() in ("0", "off", "false", "no") else "on"


@dataclass(frozen=True, slots=True)
class Finding:
    fixture_id: int
    module: str
    subject: str
    shown: bool
    matrix: bool
    reason: str
    detail: Mapping[str, Any] = field(default_factory=dict)


def compare(fixture_id: int, module: str, shown: Mapping[str, bool], matrix: Mapping[str, bool], *,
            reasons: Mapping[str, str] | None = None, details: Mapping[str, Mapping[str, Any]] | None = None) -> list[Finding]:
    """Where the module and the matrix disagree, subject by subject. A subject only one side knows is a discrepancy too: the side that
    does not know it says ``False``."""
    out: list[Finding] = []
    for subject in sorted(set(shown) | set(matrix)):
        s, m = bool(shown.get(subject, False)), bool(matrix.get(subject, False))
        if s != m:
            out.append(Finding(fixture_id, module, subject, s, m, (reasons or {}).get(subject) or ("solo_modulo" if s else "solo_matriz"),
                               dict((details or {}).get(subject, {}))))
    return out


@dataclass(slots=True)
class ShadowReport:
    matches: int = 0
    findings: int = 0
    written: int = 0
    by_module: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    stopped: str | None = None

    def add(self, found: Iterable[Finding]) -> None:
        for f in found:
            self.findings += 1
            self.by_module[f.module] = self.by_module.get(f.module, 0) + 1
            key = f"{f.module}:{f.reason}"
            self.by_reason[key] = self.by_reason.get(key, 0) + 1

    def as_json(self) -> dict[str, Any]:
        top = dict(sorted(self.by_reason.items(), key=lambda kv: -kv[1])[:20])
        return {"matches": self.matches, "findings": self.findings, "written": self.written, "by_module": self.by_module,
                "by_reason": top, "errors": self.errors[:5], "stopped": self.stopped}


SAMPLE_SQL: Final = """
SELECT f.id FROM core.fixtures f
  JOIN core.competition_seasons s ON s.id = f.competition_season_id JOIN core.competitions c ON c.id = s.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at > %(at)s AND f.kickoff_at <= %(until)s
 ORDER BY f.kickoff_at, f.id LIMIT %(limit)s
"""

INSERT_SQL: Final = """
INSERT INTO analytics.availability_discrepancies (day, fixture_id, module, subject, shown, matrix, reason, detail, observed_at, rules_version,
                                                  code_version)
VALUES (%(day)s, %(fixture)s, %(module)s, %(subject)s, %(shown)s, %(matrix)s, %(reason)s, %(detail)s::jsonb, %(at)s, %(version)s, %(code)s)
ON CONFLICT (day, fixture_id, module, subject) DO NOTHING
"""

WRITTEN_TODAY_SQL: Final = "SELECT count(*) FROM analytics.availability_discrepancies WHERE day = %s"


def sample(conn: psycopg.Connection[Any], *, at: datetime, limit: int = SAMPLE) -> list[int]:
    """The next matches to be played of the tracked competitions (``HORIZON``), at most ``limit``."""
    with conn.cursor() as cur:
        cur.execute(SAMPLE_SQL, {"at": at, "until": at + HORIZON, "limit": limit})
        return [int(r[0]) for r in cur.fetchall()]


def _subject(value: str) -> str:
    """The table's subject is ``[A-Za-z0-9][A-Za-z0-9_.:]{0,95}``: anything else becomes ``_``."""
    cleaned = "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "_.:" else "_" for ch in value)[:96]
    return cleaned if cleaned and cleaned[0].isalnum() else f"x{cleaned}"[:96]


def write(conn: psycopg.Connection[Any], found: Iterable[Finding], *, at: datetime, day: date, code_version: str | None) -> int:
    """Append the day's discrepancies (one per match, module and subject: a second pass the same day adds nothing)."""
    rows = [{"day": day, "fixture": f.fixture_id, "module": f.module[:32], "subject": _subject(f.subject), "shown": f.shown,
             "matrix": f.matrix, "reason": f.reason[:60] or "sin_motivo", "detail": json.dumps(dict(f.detail), default=str), "at": at,
             "version": RULES_VERSION, "code": code_version} for f in found]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.execute(WRITTEN_TODAY_SQL, (day,))
        row = cur.fetchone()
        room = MAX_ROWS_PER_DAY - (int(row[0]) if row else 0)
        if room <= 0:
            return 0
        written = 0
        for r in rows[:room]:
            cur.execute(INSERT_SQL, r)
            written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    return written
