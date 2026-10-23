"""The one door through which a family reads how finished matches ended (plan F10).

What a finished match turned out to be (its goals by half, its corners, its cards) is the training material of a family and the label that
grades it: not an input of what is said about the NEXT match. F9 put it in one view, ``market.fixture_outcomes``, and kept the model packages
from naming it (``tests/unit/test_knowledge_isolation.py``). F10 opens that door on purpose, in this module and in no other, and the door
carries its own lock:

* a match comes through only once its result is KNOWN: ``cutoff - OUTCOME_KNOWN_AFTER`` is the latest kick-off it will return (the rule of
  ``fit.fit_family`` applies it a second time on purpose: two independent guards, because this is where a future would leak);
* what is read is the number the settlement rule compares a line with: the columns come from ``market.settlement_rules`` as the code holds them
  (``fbi.market.rules``), so a family is trained on exactly the quantity that grades its bets, with the same unknown-is-never-zero convention;
* a match with either count unknown is not returned (it would have to be invented).

The cards by period come, through the view, from the events of the match once F7 has classified them: they are outcomes too, and they enter
here as numbers of a match that is over, never as a fact about a match that is not.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.families.fit import OUTCOME_KNOWN_AFTER, Match
from fbi.market.rules import RULES_BY_MEASURE

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class UnknownMeasureError(ValueError):
    """The measure is not one a family can be trained on."""


def columns_of(measure: str) -> tuple[str, str]:
    """The (home, away) columns of the view that the rule of ``measure`` compares a line with."""
    rule = RULES_BY_MEASURE.get(measure)
    if rule is None:
        raise UnknownMeasureError(f"no settlement rule measures {measure!r}")
    if not rule.liquidable or len(rule.columns) != 2:
        raise UnknownMeasureError(f"{measure!r} is not a pair of counts (home, away): {rule.columns!r}")
    home, away = rule.columns
    if not (_IDENTIFIER.match(home) and _IDENTIFIER.match(away)):
        raise UnknownMeasureError(f"the columns of {measure!r} are not plain identifiers: {rule.columns!r}")
    return home, away


def latest_kickoff(cutoff: datetime) -> datetime:
    """The latest kick-off whose result is known at ``cutoff``."""
    return cutoff - OUTCOME_KNOWN_AFTER


def load(conn: psycopg.Connection[Any], measure: str, *, since: datetime, cutoff: datetime, use_neutral: bool = False) -> dict[int, list[Match]]:
    """The finished matches of the followed competitions with a kick-off in ``[since, cutoff - OUTCOME_KNOWN_AFTER]``, by competition.

    ``use_neutral`` reads the neutral-venue flag (``core.fixtures.is_neutral``). It is off: the owner has not promoted the neutral-venue rule
    (plan F0, defect 1) and a family must not decide that for the goal models.
    """
    home_col, away_col = columns_of(measure)
    sql = (f"SELECT o.competition_id, o.fixture_id, o.kickoff_at, f.home_team_id, f.away_team_id, f.is_neutral, "
           f"o.{home_col} AS home, o.{away_col} AS away "
           "FROM market.fixture_outcomes o JOIN core.fixtures f ON f.id = o.fixture_id "
           "WHERE o.is_tracked AND o.kickoff_at >= %(since)s AND o.kickoff_at <= %(latest)s "
           f"AND o.{home_col} IS NOT NULL AND o.{away_col} IS NOT NULL ORDER BY o.competition_id, o.kickoff_at, o.fixture_id")
    out: dict[int, list[Match]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"since": since, "latest": latest_kickoff(cutoff)})
        for r in cur.fetchall():
            out.setdefault(int(r["competition_id"]), []).append(
                Match(int(r["fixture_id"]), r["kickoff_at"], int(r["home_team_id"]), int(r["away_team_id"]), int(r["home"]), int(r["away"]),
                      bool(r["is_neutral"]) if use_neutral else False))
    return out


def export_statement(measure: str, *, since: datetime, cutoff: datetime, use_neutral: bool = False) -> str:
    """The same read as ``load``, written as one ``COPY ... TO STDOUT`` statement (CSV, with a header) whose columns are those of
    ``scripts.families`` exports: to run it with ``psql`` where Python is not at hand, read-only, and bring the history out as a file. The
    window is written in as literals (they are instants made by the caller, not text from anywhere), so the statement is self-contained.
    """
    home_col, away_col = columns_of(measure)
    start, latest = since.astimezone(UTC).isoformat(), latest_kickoff(cutoff).astimezone(UTC).isoformat()
    neutral = "CASE WHEN f.is_neutral THEN 1 ELSE 0 END" if use_neutral else "0"
    return ("COPY (SELECT o.competition_id, o.fixture_id, "
            "to_char(o.kickoff_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS') || '+00:00' AS kickoff_at, "
            f"f.home_team_id AS home_id, f.away_team_id AS away_id, o.{home_col} AS home, o.{away_col} AS away, {neutral} AS neutral "
            "FROM market.fixture_outcomes o JOIN core.fixtures f ON f.id = o.fixture_id "
            f"WHERE o.is_tracked AND o.kickoff_at >= TIMESTAMPTZ '{start}' AND o.kickoff_at <= TIMESTAMPTZ '{latest}' "
            f"AND o.{home_col} IS NOT NULL AND o.{away_col} IS NOT NULL ORDER BY o.competition_id, o.kickoff_at, o.fixture_id) "
            "TO STDOUT WITH (FORMAT csv, HEADER true)")
