"""Who was reported missing for a match, AS KNOWN at a moment (plan F0, defect 8).

The AI packet, the evidence collector and the dossier read the absences of a match "as of" the moment they are built.
They used to read ``core.player_absences``, which keeps only the last thing said about each player and is overwritten by
every /injuries answer, with ``fetched_at <= at``. That broke in both directions:

* a player the newest answer no longer names kept his old row, so a player who had recovered still counted as out (the
  packet then reported a key absence, and the decision rule turned it into CAUTELA or RECHAZADO);
* a row refreshed after ``at`` disappeared from a read as of ``at``, although it had been known then.

Now they read the history (``core.player_availability_obs``, written by ``fbi.ingestion.availability``): per player the
newest row with ``observed_at <= at``, and only the ones that row lists. Both questions have one answer: only the
latest answer as of ``at`` counts.

"Was the season's list asked for by ``at``?" has the same flaw in ``core.context_checks``, which keeps only the LATEST
check: after a later check, a read as of an earlier moment found none and said the list had never been asked for.
``checked_at_as_of`` also counts the history's own rows, which are dated and never overwritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

SOURCE = "api-football"

AS_OF_SQL = """
SELECT o.provider_team_id, o.provider_player_id, o.player_name, o.absence_type, o.reason,
       o.observed_at AS fetched_at, o.payload_hash
  FROM (
        SELECT DISTINCT ON (x.provider_player_id) x.*
          FROM core.player_availability_obs x
         WHERE x.fixture_id = %(fixture)s AND x.source = %(source)s AND x.observed_at <= %(at)s
         ORDER BY x.provider_player_id, x.observed_at DESC
       ) o
 WHERE o.status = 'LISTED'
 ORDER BY o.provider_team_id, o.player_name
"""
"""``fetched_at`` is the name the readers always used for "when this was learned": here, when the answer that last
changed the row was asked for (``observed_at``)."""


CHECKED_SQL = """
SELECT greatest(
        (SELECT max(k.checked_at) FROM core.context_checks k
          WHERE k.competition_season_id = %(season)s AND k.dataset = 'injuries' AND k.checked_at <= %(at)s),
        (SELECT max(o.observed_at) FROM core.player_availability_obs o JOIN core.fixtures f ON f.id = o.fixture_id
          WHERE f.competition_season_id = %(season)s AND o.observed_at <= %(at)s)
       ) AS checked_at
"""


def checked_at_as_of(conn: psycopg.Connection[Any], season_id: int, at: datetime) -> datetime | None:
    """The latest moment at or before ``at`` at which the season's injury list is known to have been asked for: the
    newest of the last context check (when it is not later than ``at``) and the newest recorded answer. None: no
    evidence that it had been asked for by then."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CHECKED_SQL, {"season": season_id, "at": at})
        row = cur.fetchone()
    value = None if row is None else row["checked_at"]
    return value if isinstance(value, datetime) else None


def absences_as_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> list[dict[str, Any]]:
    """The players the provider reported missing or doubtful for ``fixture_id``, as the latest answer at or before
    ``at`` had them. Empty when none was listed or nothing was recorded by then (``checked_at_as_of`` says which)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(AS_OF_SQL, {"fixture": fixture_id, "source": SOURCE, "at": at})
        return list(cur.fetchall())
