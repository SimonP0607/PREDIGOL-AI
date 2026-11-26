"""The FORMAT of a match as one fact: league, group, knock-out of one match or of two legs, final, replay... (RP-3.2, finding H08).

In the Copa del Rey the home side wins 22.5 % of the matches: applying a league's home advantage to a cup gets the sign wrong. For the models and
the context facts to stop doing that, each match has to say - as data, before it is played - what it is: the stage, how many legs its tie has,
which leg this is, what the first leg ended (when this is the second), and whether the ground is neutral.

Nothing here is new knowledge. The stage and the tie are read by ``fbi.competitions.stages`` and ``ties`` and stored by the builder; the first
leg as it was recorded at the cut-off is ``fbi.competitions.context``'s; the neutral ground is ``fbi.catalog.neutral``'s verdict in
``core.fixtures.is_neutral``. This module is the ONE reading that puts them together, and the measure of how many matches have it:

    read ......... ``format_of`` (pure, from the stored structure) and ``read_many`` / ``read_one`` (the database, as of a cut-off)
    coverage ..... ``coverage``: of the tracked matches of the last days, how many have a known format (the acceptance: 98 %)

It goes through ``fbi.competitions.context`` (the single door to the tie tables) and writes nothing: the stage's counts, the winner, the aggregate
and every other outcome of a tie stay unread (``tests/integration/test_competition_context.py`` holds that line).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.competitions import context as cx

VERSION: Final = "match-format-v1"

LEAGUE: Final = "league"
GROUP: Final = "group"
KNOCKOUT_SINGLE: Final = "knockout_single"
KNOCKOUT_TWO_LEGGED: Final = "knockout_two_legged"
KNOCKOUT_SERIES: Final = "knockout_series"
REPLAY: Final = "replay"
FINAL: Final = "final"
THIRD_PLACE: Final = "third_place"
FRIENDLY: Final = "friendly"
UNKNOWN: Final = "unknown"

FORMATS: Final = (LEAGUE, GROUP, KNOCKOUT_SINGLE, KNOCKOUT_TWO_LEGGED, KNOCKOUT_SERIES, REPLAY, FINAL, THIRD_PLACE, FRIENDLY, UNKNOWN)

_BRACKET_ROLES: Final = frozenset({"knockout", "playoff", "placement", "qualifying"})
_BY_TIE: Final = {"single": KNOCKOUT_SINGLE, "two_legged": KNOCKOUT_TWO_LEGGED, "series": KNOCKOUT_SERIES, "replay": REPLAY}


@dataclass(frozen=True, slots=True)
class MatchFormat:
    fixture_id: int
    format: str
    role: str | None
    stage: str | None
    legs: int | None
    """How many matches the tie has, as the schedule shows it before the match (1, 2; None for a series or when there is no tie)."""
    leg: int | None
    first_leg: dict[str, Any] | None
    """In a second leg: what the first leg had ended at the cut-off, from this match's home side's point of view; None otherwise."""
    neutral: bool

    @property
    def known(self) -> bool:
        return self.format != UNKNOWN

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "fixture_id": self.fixture_id, "format": self.format, "role": self.role, "stage": self.stage,
                "legs": self.legs, "leg": self.leg, "first_leg": self.first_leg, "neutral": self.neutral}


def format_of(role: str | None, tie_format: str | None, leg: int | None) -> str:
    """The format of a match from the role of its stage and, in a bracket, the format of its tie as the schedule shows it before the match. Pure.

    A replay or the third game of a series exists only because the matches before it did not decide the tie: seen from the first match the
    schedule shows a single match (``fbi.competitions.context.known_format``). A match of a bracket stage with no tie (a stage that is not a
    bracket, a cancelled match) has no format: it says so instead of guessing."""
    if role is None or role == "unresolved":
        return UNKNOWN
    if role == "league":
        return LEAGUE
    if role == "group":
        return GROUP
    if role == "friendly":
        return FRIENDLY
    if role in ("final", "third_place"):
        return role
    if role in _BRACKET_ROLES:
        if tie_format is None or leg is None:
            return UNKNOWN
        return _BY_TIE[cx.known_format(tie_format, leg)]
    return UNKNOWN  # pragma: no cover - a role the stages do not make


def _legs(fmt: str) -> int | None:
    return {KNOCKOUT_SINGLE: 1, KNOCKOUT_TWO_LEGGED: 2, REPLAY: 2, FINAL: 1, THIRD_PLACE: 1}.get(fmt)


def read_many(conn: psycopg.Connection[Any], fixture_ids: Sequence[int], *, at: datetime) -> list[MatchFormat]:
    """The format of each fixture as it could be said at ``at``. The first leg of a second leg is only the one recorded by ``at``."""
    out: list[MatchFormat] = []
    for r in cx.structure_rows(conn, fixture_ids):
        role = None if r["role"] is None else str(r["role"])
        tie_format = None if r["tie_format"] is None else str(r["tie_format"])
        leg = None if r["leg"] is None else int(r["leg"])
        fmt = format_of(role, tie_format, leg)
        first_leg: dict[str, Any] | None = None
        legs = _legs(fmt)
        if fmt in (KNOCKOUT_TWO_LEGGED, REPLAY) and leg is not None and leg >= 2:
            phase = cx.phase_as_of(conn, int(r["id"]), at=at)
            if phase is not None and phase.tie is not None:
                legs = phase.tie.legs if phase.tie.legs is not None else legs
                if phase.tie.previous:
                    first_leg = phase.tie.previous[0].as_json()
        elif fmt == KNOCKOUT_TWO_LEGGED:
            legs = 2
        out.append(MatchFormat(fixture_id=int(r["id"]), format=fmt, role=role, stage=None if r["stage"] is None else str(r["stage"]),
                               legs=legs, leg=leg, first_leg=first_leg, neutral=bool(r["is_neutral"])))
    return out


def read_one(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> MatchFormat | None:
    found = read_many(conn, [fixture_id], at=at)
    return found[0] if found else None


TRACKED_SQL: Final = """
SELECT f.id FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
 ORDER BY f.id
"""
"""The matches the coverage counts: those of the competitions followed, kicked off in the window."""


def coverage(conn: psycopg.Connection[Any], *, at: datetime, days: int = 30) -> dict[str, Any]:
    """Of the tracked matches that kicked off in the last ``days``, how many have a known format, by format and the ones that do not, by
    competition. Read-only; the acceptance of RP-3.2 is ``known_pct >= 0.98``."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(TRACKED_SQL, {"since": at - timedelta(days=days), "until": at})
        ids = [int(r[0]) for r in cur.fetchall()]
    formats = read_many(conn, ids, at=at)
    by_format = Counter(f.format for f in formats)
    unknown = [f.fixture_id for f in formats if not f.known]
    return {"version": VERSION, "at": at.isoformat(), "days": days, "matches": len(formats), "known": len(formats) - len(unknown),
            "known_pct": round((len(formats) - len(unknown)) / len(formats), 4) if formats else None,
            "by_format": {k: by_format[k] for k in FORMATS if by_format.get(k)}, "unknown_fixtures": unknown[:50],
            "neutral": sum(1 for f in formats if f.neutral)}
