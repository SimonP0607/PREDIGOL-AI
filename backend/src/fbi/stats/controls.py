"""The three controls a statistical fact passes before it is cited (plan RP-6.4, finding H32): ``stats-controls-v1``.

The owner asked for controls against outdated statistics, small samples, biases and leaks. They are checks of a document read with
``fbi.stats.reading`` (RP-6.1) - they compute no figure and decide nothing:

* ``datos_posteriores_al_corte`` - the document was computed after the cut-off the fact is made for (``reading`` already refuses to hand
  it over: status ``after_cutoff``). A fact that cites a ``known_at`` later than its cut-off is a LEAK: ``assert_no_leak`` raises.
* ``documento_desactualizado`` - the document is older than the last match the entity has played before the cut-off: the figure does not
  know that match (kickoff, not the final whistle, so it only says «stale» when it is certain).
* ``muestra_insuficiente`` - the document's sample is under the threshold the caller holds; the fact says so instead of citing a figure
  that a handful of matches made.

The fourth thing the plan asks for, the note of an uneven recent calendar, is made by the calendar-difficulty module of ``fbi.competitions``
(``calendar_note``): it stays there because that module is in shadow until the owner signs its publication (DM-14) and no other module
may read it. The caller that holds the note passes it here as text and it travels with the verdict.

Read only: one indexed SELECT (the last finished match) and nothing is written.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg

from fbi.stats.reading import Document

VERSION: Final = "stats-controls-v1"
AFTER_CUTOFF: Final = "datos_posteriores_al_corte"
STALE: Final = "documento_desactualizado"
SMALL_SAMPLE: Final = "muestra_insuficiente"
CODES: Final = (AFTER_CUTOFF, STALE, SMALL_SAMPLE)

LAST_MATCH_SQL: Final = """
SELECT max(f.kickoff_at)
  FROM core.fixtures f
 WHERE f.competition_season_id = %(cs)s AND (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
   AND f.status_group = 'finished' AND f.kickoff_at <= %(as_of)s
"""


class LeakError(Exception):
    """A fact cites a date later than the cut-off it was made for."""


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the controls found in one document: no codes means the figure can be cited."""

    document_id: str | None
    codes: tuple[str, ...]
    note_es: str | None = None
    """The note of the uneven calendar, when the caller holds one; it is never a reason to refuse a fact."""

    @property
    def citable(self) -> bool:
        return not self.codes


def problems(doc: Document, *, as_of: datetime, last_match_at: datetime | None, min_sample: int) -> tuple[str, ...]:
    """The controls, pure. A document that is not there has nothing to check (``no_document`` is its own answer)."""
    if doc.status == "after_cutoff" or (doc.computed_at is not None and doc.computed_at > as_of):
        return (AFTER_CUTOFF,)
    if doc.status != "ok" or doc.computed_at is None:
        return ()
    found: list[str] = []
    if last_match_at is not None and doc.computed_at < last_match_at:
        found.append(STALE)
    if doc.sample < min_sample:
        found.append(SMALL_SAMPLE)
    return tuple(found)


def last_match_at(conn: psycopg.Connection[Any], doc: Document, *, as_of: datetime) -> datetime | None:
    """The kickoff of the last finished match of the team of the document before the cut-off (players: None, their sample says it)."""
    if doc.kind != "team":
        return None
    with conn.cursor() as cur:
        cur.execute(LAST_MATCH_SQL, {"cs": doc.competition_season_id, "team": doc.entity_id, "as_of": as_of})
        row = cur.fetchone()
    return None if row is None else row[0]


def check(conn: psycopg.Connection[Any], doc: Document, *, as_of: datetime, min_sample: int, calendar_note_es: str | None = None) -> Verdict:
    """The verdict on a document read from the database at the cut-off ``as_of``."""
    last = None if doc.status != "ok" else last_match_at(conn, doc, as_of=as_of)
    return Verdict(doc.document_id, problems(doc, as_of=as_of, last_match_at=last, min_sample=min_sample), calendar_note_es)


def assert_no_leak(citations: Iterable[Mapping[str, Any] | None], *, as_of: datetime) -> int:
    """Raise ``LeakError`` if any citation is dated after the cut-off or carries no date at all; return how many were checked. The test of the
    ficha (a provoked leak must fail) and the replay both go through here."""
    checked = 0
    for c in citations:
        if c is None:
            continue
        raw = c.get("known_at")
        if raw is None:
            raise LeakError(f"a fact without its date cannot be proved to precede {as_of.isoformat()}: {c.get('document_id')}")
        known = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        if known > as_of:
            raise LeakError(f"{c.get('document_id')} was known at {known.isoformat()}, after the cut-off {as_of.isoformat()}")
        checked += 1
    return checked


__all__ = ["AFTER_CUTOFF", "CODES", "SMALL_SAMPLE", "STALE", "VERSION", "LeakError", "Verdict", "assert_no_leak", "check", "last_match_at",
           "problems"]
