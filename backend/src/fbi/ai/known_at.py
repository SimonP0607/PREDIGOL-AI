"""The moment of knowledge of every fact an agent reads (IA-061, plan AD-A04, after INT-B06): ``known-at-v1``.

A package (``fbi.ai.package``) already refuses any block stamped later than its own moment (``PackageLeakError``) and leaves out an evidence its
packet copied without a retrieval time, or retrieved or published after the moment. What it cannot see from the packet alone is whether the times
the packet COPIED are the ones of the row: the packet keeps its own copy of ``retrieved_at`` and ``published_at`` (``fbi.ai.packet``), and the
package trusts it. This is the door that does not: before an agent reads a package, every fact of it that comes from outside with a time of its own -
the evidence (news, injuries, line-ups, coaches... ``ai.evidence``, whose moment of knowledge is ``retrieved_at``, the column that is NOT NULL since
migration 0072) - is read back from its row by id and refused when:

    fact_missing        the row is not there (a fact that cannot be found cannot be proved to have been known)
    fact_after_cutoff   its row was retrieved, or published, after the cut-off (the package's ``known_at``)
    fact_stamp_differs  the times the packet copied are not the row's (a copy that moved the moment)
    fact_other_match    the row is about another match (``fixture_id`` set and not the package's)

Pure where it can be: ``fact_problems`` decides from what was read, ``rows_of`` reads (by id: a lookup of what the package already named), ``check``
does both. The nightly audit applies the same function to the packages of the day (``leak-audit-v10``, ``news_known``).

The blocks the code computes (prices, forecasts, tables, calendars...) carry their own stamps and are held by ``PackageLeakError``; a table created
from now on carries its moment of knowledge from its first migration. No table changes here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg

from fbi.ai.final_reread import parse_moment

VERSION: Final = "known-at-v1"
CODES: Final = ("fact_missing", "fact_after_cutoff", "fact_stamp_differs", "fact_other_match")

ROWS_SQL: Final = "SELECT id, fixture_id, retrieved_at, published_at FROM ai.evidence WHERE id = ANY(%(ids)s)"


@dataclass(frozen=True, slots=True)
class Row:
    """What ``ai.evidence`` says about one fact: its match (None: a team's) and its moments."""

    fixture_id: int | None
    retrieved_at: datetime
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class Copy:
    """What the packet copied of one fact: its moments as the packet states them (None: absent or not a moment)."""

    retrieved_at: datetime | None
    published_at: datetime | None


def package_facts(document: Mapping[str, Any]) -> list[int]:
    """The ids of the facts a package carries (its ``evidence`` index), in its order."""
    out: list[int] = []
    for item in document.get("evidence") or []:
        if isinstance(item, Mapping) and isinstance(item.get("id"), int) and not isinstance(item.get("id"), bool):
            out.append(int(item["id"]))
    return out


def packet_copies(content: Mapping[str, Any]) -> dict[int, Copy]:
    """The moments the packet copied of each evidence, by id."""
    out: dict[int, Copy] = {}
    for item in content.get("evidence") or []:
        if isinstance(item, Mapping) and isinstance(item.get("id"), int) and not isinstance(item.get("id"), bool):
            out[int(item["id"])] = Copy(parse_moment(item.get("retrieved_at")), parse_moment(item.get("published_at")))
    return out


def fact_problems(fixture_id: int, cutoff: datetime, facts: Iterable[int], copies: Mapping[int, Copy], rows: Mapping[int, Row]) -> dict[int, list[str]]:
    """What is wrong with each fact (only the facts with something wrong). Pure."""
    out: dict[int, list[str]] = {}
    for fid in facts:
        row = rows.get(fid)
        if row is None:
            out[fid] = ["fact_missing"]
            continue
        found: list[str] = []
        if row.retrieved_at > cutoff or (row.published_at is not None and row.published_at > cutoff):
            found.append("fact_after_cutoff")
        copy = copies.get(fid)
        if copy is None or copy.retrieved_at != row.retrieved_at or copy.published_at != row.published_at:
            found.append("fact_stamp_differs")
        if row.fixture_id is not None and row.fixture_id != fixture_id:
            found.append("fact_other_match")
        if found:
            out[fid] = found
    return out


def rows_of(conn: psycopg.Connection[Any], ids: Iterable[int]) -> dict[int, Row]:
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    with conn.cursor() as cur:
        cur.execute(ROWS_SQL, {"ids": wanted})
        return {int(i): Row(None if f is None else int(f), r, p) for i, f, r, p in cur.fetchall()}


@dataclass(frozen=True, slots=True)
class Check:
    """The verdict on the facts of one package: how many were read and what is wrong (empty: every fact was known by the cut-off)."""

    facts: int
    problems: dict[int, list[str]]

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def codes(self) -> list[str]:
        return sorted({c for found in self.problems.values() for c in found})

    def record(self) -> dict[str, Any]:
        """What the state of the pass keeps (``data_status.known_at``)."""
        return {"version": VERSION, "facts": self.facts, "ok": self.ok, "codes": self.codes, "ids": sorted(self.problems)[:10]}


def check(conn: psycopg.Connection[Any], *, fixture_id: int, cutoff: datetime, document: Mapping[str, Any], content: Mapping[str, Any]) -> Check:
    """The facts of the package ``document`` (derived from the packet ``content``) against their rows, at the cut-off ``cutoff``."""
    facts = package_facts(document)
    return Check(facts=len(facts), problems=fact_problems(fixture_id, cutoff, facts, packet_copies(content), rows_of(conn, facts)))
