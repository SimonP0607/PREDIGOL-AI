"""The last look before the last pass (IA-061, plan AD-A04): ``reread-v1``.

The pass ``final`` of a match is built on the kick-off and the state the packet read, up to 100 minutes before the pass is shadowed. On 12 Nov
2026 (match 180277) the provider had the kick-off at 20:00 when it was 19:00: the packet said ``NS`` at 19:20:51 and its state was written at
19:26:51, with the match already played. Nothing looked again at the match at the moment of the pass.

So, right before a pass of ``PASSES`` is given to an agent, this module reads the match AGAIN - the kick-off and the state stored now
(``core.fixtures``, which the live follow and the line-up refresh keep moving with the provider's word) and whether the in-play odds feed sees it
playing (``market.live_fixture_current``) - and holds it against what the packet knew (``fixture.kickoff_at`` / ``fixture.status``). The pass goes on
only when the match is still to be played, at the same kick-off, and that kick-off is still ahead; otherwise it stops with ONE closed reason of
``REASONS``:

    fixture_missing         the match is not in ``core.fixtures`` any more
    packet_without_kickoff  the packet names no kick-off (nothing to compare)
    kickoff_unknown         the match has no kick-off now, or its state is ``TBD`` (time to be defined)
    finished                the state now is a final one (``FT``, ``AET``, ``PEN``)
    cancelled               cancelled, abandoned, awarded or a walkover (``CANC``, ``ABD``, ``AWD``, ``WO``)
    postponed               ``PST``
    suspended               ``SUSP`` or ``INT``: it kicked off and stopped
    started                 any other state of play, or the in-play odds feed has seen it within ``IN_PLAY_RECENT``
    status_unknown          a code this table does not know
    kickoff_passed          the kick-off now is at or before the moment of the reading
    kickoff_moved           the kick-off now is not the packet's (earlier or later)
    reread_failed           the reading itself failed (the database): the pass is not given to an agent on a reading that could not be made

The reading is free (two indexed rows, no provider call, no model) and is a pure function of what it read: ``judge`` decides, ``read`` reads,
``reread`` does both. ``Verdict.record`` is what the shadow keeps of it in ``ai.match_runs.data_status.reread``, so that the nightly audit
(``leak-audit-v10``, ``final_reread_known``) can hold every final state written after this code to a reading made between the moment of the packet
and the writing of the state.

What it does NOT do: it does not ask the provider (on 12 Nov the provider's own ``/fixtures`` still said ``NS`` and 20:00 at 19:18, 19:29 and 19:40 -
three payloads read in production on 16 Nov - so a call would not have seen it either), it changes no packet, no pass of production and no reader.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.core import match_state

VERSION: Final = "reread-v1"
PASSES: Final = frozenset({"final"})
"""The passes read again before an agent reads them: the last one of the day (the plan's E4 when it exists)."""
IN_PLAY_RECENT: Final = timedelta(minutes=5)
"""A capture of the in-play odds feed this recent, not finished, says the match is being played (``fbi.ingestion.live_match.ODDS_FEED_RECENT``)."""
REASONS: Final = ("fixture_missing", "packet_without_kickoff", "kickoff_unknown", "finished", "cancelled", "postponed", "suspended", "started",
                  "status_unknown", "kickoff_passed", "kickoff_moved", "reread_failed")
"""Every reason a reading stops a pass with, and nothing else (a test holds the codes ``judge`` returns to this list)."""

READ_SQL: Final = """
SELECT f.kickoff_at, f.status_short,
       (SELECT s.captured_at FROM market.live_fixture_current s
         WHERE s.fixture_id = f.id AND s.captured_at > %(at)s - %(recent)s AND s.captured_at <= %(at)s
           AND NOT COALESCE(s.is_finished, false)) AS in_play_at
  FROM core.fixtures f
 WHERE f.id = %(fixture)s
"""


@dataclass(frozen=True, slots=True)
class Reading:
    """What the match is now: its kick-off and state as stored, and the last capture of the in-play feed that saw it playing (None: none)."""

    fixture_id: int
    at: datetime
    kickoff_at: datetime | None
    status: str | None
    in_play_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether the pass goes on (``ok``) or the reason it stops, with what was compared."""

    ok: bool
    reason: str | None
    at: datetime
    packet_kickoff: datetime | None
    packet_status: str | None
    reading: Reading | None

    def record(self) -> dict[str, Any]:
        """What the state of the pass keeps (``data_status.reread``): plain JSON, moments in ISO 8601."""
        r = self.reading
        return {"version": VERSION, "ok": self.ok, "reason": self.reason, "at": self.at.isoformat(),
                "packet_kickoff_at": None if self.packet_kickoff is None else self.packet_kickoff.isoformat(),
                "packet_status": self.packet_status,
                "kickoff_at": None if r is None or r.kickoff_at is None else r.kickoff_at.isoformat(),
                "status": None if r is None else r.status,
                "in_play_at": None if r is None or r.in_play_at is None else r.in_play_at.isoformat()}


def parse_moment(value: object) -> datetime | None:
    """A moment from the ISO text a packet states it in; None when it is absent, not a text, not a moment or has no time zone."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def packet_fixture(content: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    """The kick-off and the state the packet read (its ``fixture`` block)."""
    block = content.get("fixture")
    if not isinstance(block, Mapping):
        return None, None
    status = block.get("status")
    return parse_moment(block.get("kickoff_at")), status if isinstance(status, str) else None


def status_reason(status: str | None) -> str | None:
    """The reason a state stops a pass, or None when the match is still to be played."""
    code = match_state.code(status)
    if code == "NS":
        return None
    if code == "TBD":
        return "kickoff_unknown"
    if code in match_state.FINISHED:
        return "finished"
    if code in match_state.CANCELLED | match_state.ABANDONED | match_state.NOT_PLAYED:
        return "cancelled"
    if code in match_state.POSTPONED:
        return "postponed"
    if code in ("SUSP", "INT"):
        return "suspended"
    if code in match_state.IN_PLAY:
        return "started"
    return "status_unknown"


def judge(packet_kickoff: datetime | None, packet_status: str | None, reading: Reading | None, *, at: datetime) -> Verdict:
    """The verdict of a reading made at ``at`` against what the packet knew. Pure."""

    def stop(reason: str) -> Verdict:
        return Verdict(ok=False, reason=reason, at=at, packet_kickoff=packet_kickoff, packet_status=packet_status, reading=reading)

    if reading is None:
        return stop("fixture_missing")
    if packet_kickoff is None:
        return stop("packet_without_kickoff")
    if reading.kickoff_at is None:
        return stop("kickoff_unknown")
    if (why := status_reason(reading.status)) is not None:
        return stop(why)
    if reading.in_play_at is not None:
        return stop("started")
    if reading.kickoff_at <= at:
        return stop("kickoff_passed")
    if reading.kickoff_at != packet_kickoff:
        return stop("kickoff_moved")
    return Verdict(ok=True, reason=None, at=at, packet_kickoff=packet_kickoff, packet_status=packet_status, reading=reading)


def read(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> Reading | None:
    """The match as it is stored at ``at`` (None: it is not there). Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(READ_SQL, {"fixture": fixture_id, "at": at, "recent": IN_PLAY_RECENT})
        row = cur.fetchone()
    if row is None:
        return None
    return Reading(fixture_id=fixture_id, at=at, kickoff_at=row["kickoff_at"], status=row["status_short"], in_play_at=row["in_play_at"])


def reread(conn: psycopg.Connection[Any], fixture_id: int, content: Mapping[str, Any], *, at: datetime) -> Verdict:
    """Read the match again and judge it against the packet ``content``. A reading the database could not make is ``reread_failed`` (and the
    transaction is rolled back to where it was: the reading is the first statement of the pass)."""
    kickoff, status = packet_fixture(content)
    try:
        reading = read(conn, fixture_id, at=at)
    except psycopg.Error:
        conn.rollback()
        return Verdict(ok=False, reason="reread_failed", at=at, packet_kickoff=kickoff, packet_status=status, reading=None)
    return judge(kickoff, status, reading, at=at)
