"""Each arrival of a side's official line-up, kept once per content (IA-069, plan piece AD-D05).

``core.fixture_lineups`` keeps the newest payload's view of a line-up and rewrites ``fetched_at`` on every read, so on its own
it cannot say when the line-up first reached us or whether it changed before kick-off. Two things keep that now
(migration 0140):

* ``core.fixture_lineups.first_seen_at``, written once by the database itself (trigger ``keep_lineup_first_seen``);
* ``core.fixture_lineup_arrivals``, append-only: one row per observation whose CONTENT differs from the previous observation
  of the same side - formation, coach and the squad as the writer stores it (player, name, number, position, grid,
  starter). An identical re-send adds nothing; a corrected starter adds a row with a new ``starters_hash``.

"Previous" is the newest arrival observed at or before this one, so a replay of an older payload (reprocess) compares with
what was known at its own instant and never hides a later change. Only observations up to ``ARRIVAL_HORIZON`` after kick-off
are kept: the follow, the pre-match read and the two post-match reads (+150 min, +26 h) - not the history backfill of old
seasons, whose "arrival" would be the day we backfilled it.

Nothing of the product reads these rows; they measure.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg

from fbi.providers.api_football.details import LineupRef

SOURCE: Final = "api-football"
ARRIVAL_HORIZON: Final = timedelta(hours=30)
"""Observations later than kick-off + 30 h are not arrivals worth keeping (the late post-match read is at + 26 h)."""

Channel = Literal["detail_writer", "lineup_watch"]
CHANNELS: Final[tuple[Channel, ...]] = ("detail_writer", "lineup_watch")


@dataclass(frozen=True, slots=True)
class LineupContent:
    """What one side's line-up says, reduced to the fields the writer stores, and its two hashes."""

    content_hash: str
    starters_hash: str
    starters: int
    players: int
    formation: str | None


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def squad_rows(lu: LineupRef) -> list[tuple[Any, ...]]:
    """The squad as ``fbi.ingestion.details`` stores it: the first occurrence of each provider player id."""
    seen: set[int] = set()
    rows: list[tuple[Any, ...]] = []
    for p in lu.players:
        if p.provider_player_id in seen:
            continue
        seen.add(p.provider_player_id)
        rows.append((p.provider_player_id, p.name, p.number, p.position, p.grid, bool(p.is_starter)))
    return rows


def lineup_content(lu: LineupRef) -> LineupContent:
    """The content of a side's line-up. Order-free: the provider listing the same players in another order is the same
    line-up. Pure."""
    rows = sorted(squad_rows(lu), key=lambda r: (int(r[0] or 0), str(r[1] or "")))
    starters = sorted((int(r[0] or 0), str(r[1] or "")) for r in rows if r[5])
    content = {"formation": lu.formation, "coach_id": lu.provider_coach_id, "coach": lu.coach_name,
               "players": [list(r) for r in rows]}
    return LineupContent(content_hash=_sha(content), starters_hash=_sha([list(s) for s in starters]),
                         starters=len(starters), players=len(rows), formation=lu.formation)


ARRIVAL_SQL = """
INSERT INTO core.fixture_lineup_arrivals (fixture_id, team_side, source, observed_at, kickoff_at, content_hash,
       starters_hash, starters, players, formation, channel, payload_hash, run_id)
SELECT f.id, %(side)s, %(source)s, %(at)s, f.kickoff_at, %(content)s, %(starters_hash)s, %(starters)s, %(players)s,
       %(formation)s, %(channel)s, %(payload)s, %(run)s
  FROM core.fixtures f
 WHERE f.id = %(fixture)s
   AND %(at)s < f.kickoff_at + %(horizon)s
   AND (SELECT a.content_hash FROM core.fixture_lineup_arrivals a
         WHERE a.fixture_id = %(fixture)s AND a.team_side = %(side)s AND a.source = %(source)s
           AND a.observed_at <= %(at)s
         ORDER BY a.observed_at DESC, a.id DESC LIMIT 1) IS DISTINCT FROM %(content)s
ON CONFLICT (fixture_id, team_side, source, observed_at, content_hash) DO NOTHING
"""
"""One statement: the kick-off as stored now, the horizon and the change-only rule together. The latest-arrival lookup is
served by ``fixture_lineup_arrivals_latest``."""


def record_arrival(cur: psycopg.Cursor[Any], *, fixture_id: int, side: str, lineup: LineupRef, observed_at: datetime,
                   payload_hash: str, channel: Channel, run_id: int | None = None) -> bool:
    """Add an arrival when this observation's content differs from the previous one of that side. True when a row was
    added. Runs inside the caller's transaction (the detail writers' advisory lock per fixture already holds)."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    c = lineup_content(lineup)
    cur.execute(ARRIVAL_SQL, {"fixture": fixture_id, "side": side, "source": SOURCE, "at": observed_at,
                              "content": c.content_hash, "starters_hash": c.starters_hash, "starters": c.starters,
                              "players": c.players, "formation": c.formation[:32] if c.formation else None,
                              "channel": channel, "payload": payload_hash[:128], "run": run_id,
                              "horizon": ARRIVAL_HORIZON})
    return cur.rowcount > 0


def provider_side(provider_team_id: int | None, home: int, away: int) -> str | None:
    if provider_team_id == home:
        return "home"
    if provider_team_id == away:
        return "away"
    return None


def record_arrivals(cur: psycopg.Cursor[Any], *, fixture_id: int, home: int, away: int, lineups: Sequence[LineupRef],
                    observed_at: datetime, payload_hash: str, channel: Channel, run_id: int | None = None) -> int:
    """``record_arrival`` for each side a payload carried (a side the fixture does not have is skipped). Rows added."""
    added = 0
    for lu in lineups:
        side = provider_side(lu.provider_team_id, home, away)
        if side is None:
            continue
        added += record_arrival(cur, fixture_id=fixture_id, side=side, lineup=lu, observed_at=observed_at,
                                payload_hash=payload_hash, channel=channel, run_id=run_id)
    return added
