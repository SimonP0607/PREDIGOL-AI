"""Who officiated a match AS KNOWN at a moment (plan F3): the reading side of ``core.fixture_officials``.

The AI packet, the dossier, the leak audit and the Match Center read the referee of a match "as of" a moment, like the absences
(``fbi.ai.absences``) and the tie legs (``fbi.competitions.context``): the newest thing the provider had said by then, not the
newest thing it has said since. ``core.fixture_facts_latest`` cannot answer that - it keeps one row per match, and a read as of
an earlier moment found NOTHING when the provider had changed its mind in between.

``referee_as_of`` is the one door. Its answer has three shapes, and the difference matters:

* ``identity == "id"``: the referee is a person (``core.referees``): the alias the provider's spelling belongs to, through the
  referee it is placed with NOW. A merge or a split made after the moment changes WHO a spelling is, never WHAT the provider
  said when.
* ``identity == "text"``: the match is not placed (``core.fixture_officials`` has no row for it - the hourly pass of
  ``fbi.people.referees`` has not seen its facts yet) or the pass has not caught up with the newest observation (the provider
  changed the referee in the last hour). The string the provider wrote is returned as it was, from the newest observation of
  ``core.fixture_facts`` at or before the moment - never a person who is no longer the one the provider names.
* ``identity is None``: nobody is named - the provider had not said yet, or had taken the referee off the match. Nothing is
  made up.

Whether the pass has "caught up" is read from the facts themselves: the spelling of the newest observation at the moment has to
be the spelling of the alias the newest officials row points to (``fbi.people.referee_names`` is the one parser of both).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.people.countries import country_name
from fbi.people.referee_names import parse_referee

AS_OF_SQL = """
SELECT EXISTS (SELECT 1 FROM core.fixture_officials x WHERE x.fixture_id = %(fixture)s AND x.role = 'referee') AS placed,
       n.observed_at, n.referee_id, n.name, n.country_key, n.display, n.name_key,
       w.observed_at AS written_at, w.referee AS written, w.referee_country AS written_country
  FROM (SELECT 1) one
  LEFT JOIN LATERAL (
        SELECT o.observed_at, a.referee_id, r.name, r.country_key, a.display, a.name_key
          FROM core.fixture_officials o
          LEFT JOIN core.referee_aliases a ON a.id = o.alias_id
          LEFT JOIN core.referees r ON r.id = a.referee_id
         WHERE o.fixture_id = %(fixture)s AND o.role = 'referee' AND o.observed_at <= %(at)s
         ORDER BY o.observed_at DESC LIMIT 1) n ON true
  LEFT JOIN LATERAL (
        SELECT f.observed_at, f.referee, f.referee_country
          FROM core.fixture_facts f
         WHERE f.fixture_id = %(fixture)s AND f.observed_at <= %(at)s
         ORDER BY f.observed_at DESC LIMIT 1) w ON true
"""

ID = "id"
TEXT = "text"


@dataclass(frozen=True, slots=True)
class RefereeAsOf:
    """The referee of a match as the provider had named him at a moment."""

    identity: str | None
    """``"id"`` (a person), ``"text"`` (the string the provider wrote) or None (nobody is named)."""
    name: str | None
    """The person's name, or the string the provider wrote when the identity has not caught up. None when nobody is named."""
    referee_id: int | None
    """His id in ``core.referees`` (only with ``identity == "id"``)."""
    country: str | None
    """The name of the country he referees from (``None`` when no scope is known)."""
    spelling: str | None
    """The string the provider wrote, put in order (``Michael Oliver``, ``M. Oliver``)."""
    seen_at: datetime | None
    """The observation of the provider the answer comes from (also set when the answer is "taken off")."""
    placed: bool
    """The match has rows in ``core.fixture_officials`` (whether or not the answer comes from them)."""


def referee_as_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> RefereeAsOf:
    """The referee the provider had given for ``fixture_id`` at or before ``at``."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(AS_OF_SQL, {"fixture": fixture_id, "at": at})
        row = cur.fetchone()
    if row is None:  # the query always returns a row; this is for the type checker
        return RefereeAsOf(None, None, None, None, None, None, False)
    placed = bool(row["placed"])
    written = parse_referee(row["written"], row["written_country"]) if row["written_at"] is not None else None
    if placed:
        if row["referee_id"] is None:
            # the newest officials row took the referee off the match (or there is none yet at this moment)
            if written is None:
                return RefereeAsOf(None, None, None, None, None, row["observed_at"] or row["written_at"], True)
        elif written is not None and written.key == row["name_key"]:
            return RefereeAsOf(ID, str(row["name"]), int(row["referee_id"]), country_name(row["country_key"]),
                               str(row["display"]), row["observed_at"], True)
    # not placed, or the pass has not caught up with the newest observation: what the provider wrote
    if written is None:
        return RefereeAsOf(None, None, None, None, None, row["written_at"], placed)
    return RefereeAsOf(TEXT, str(row["written"]), None, None, written.display, row["written_at"], placed)
