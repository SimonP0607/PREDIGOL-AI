"""Fixture facts and player extras: written change-only, from live payloads and from RAW.

A payload adds a row only when it says something new about a match (or a player's match) - the
first observation that says anything, then each one that differs from the newest row - and only when
it is newer than that row: an older payload, replayed, never rewrites what a newer one established.
Nothing is updated. ``NORMALIZER_VERSION`` names the parsing rules that produced a row.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import psycopg

from fbi.providers.api_football.details import FixtureFactsRef, PlayerStatsRef

NORMALIZER_VERSION = "fixture-facts-1"

FACTS_SQL = """
INSERT INTO core.fixture_facts (fixture_id, observed_at, referee, referee_country, home_winner, away_winner,
                                first_half_at, second_half_at, payload_hash, normalizer_version)
SELECT f.id, %(at)s, %(referee)s, %(country)s, %(hw)s, %(aw)s, %(h1)s, %(h2)s, %(hash)s, %(version)s
  FROM core.fixtures f
 WHERE f.provider_fixture_id = %(pf)s
   AND NOT EXISTS (SELECT 1 FROM core.fixture_facts x WHERE x.fixture_id = f.id AND x.observed_at >= %(at)s)
   AND NOT EXISTS (SELECT 1 FROM core.fixture_facts_latest l WHERE l.fixture_id = f.id
                     AND (l.referee, l.referee_country, l.home_winner, l.away_winner, l.first_half_at,
                          l.second_half_at)
                         IS NOT DISTINCT FROM (%(referee)s::text, %(country)s::text, %(hw)s::boolean, %(aw)s::boolean,
                                               %(h1)s::timestamptz, %(h2)s::timestamptz))
ON CONFLICT DO NOTHING
"""

EXTRAS_SQL = """
INSERT INTO core.fixture_player_extras (fixture_id, provider_player_id, observed_at, team_side, position_played,
                                        offsides, dribbled_past, penalties_won, penalties_committed,
                                        penalties_saved, payload_hash, normalizer_version)
SELECT %(f)s, %(p)s, %(at)s, %(side)s, %(pos)s, %(off)s, %(past)s, %(won)s, %(com)s, %(saved)s, %(hash)s, %(version)s
 WHERE NOT EXISTS (SELECT 1 FROM core.fixture_player_extras x WHERE x.fixture_id = %(f)s
                     AND x.provider_player_id = %(p)s AND x.observed_at >= %(at)s)
   AND NOT EXISTS (SELECT 1 FROM core.fixture_player_extras_latest l WHERE l.fixture_id = %(f)s
                     AND l.provider_player_id = %(p)s
                     AND (l.team_side, l.position_played, l.offsides, l.dribbled_past, l.penalties_won,
                          l.penalties_committed, l.penalties_saved)
                         IS NOT DISTINCT FROM (%(side)s::text, %(pos)s::text, %(off)s::smallint, %(past)s::smallint,
                                               %(won)s::smallint, %(com)s::smallint, %(saved)s::smallint))
ON CONFLICT DO NOTHING
"""

EXTRA_KEYS = ("position_played", "offsides", "dribbled_past", "penalties_won", "penalties_committed",
              "penalties_saved")


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 32768 else None


def apply_fixture_facts(conn: psycopg.Connection[Any], refs: Iterable[FixtureFactsRef], *, payload_hash: str,
                        observed_at: datetime) -> int:
    """Rows added (changes) for the fixtures of a /fixtures payload that we hold."""
    added = 0
    with conn.cursor() as cur:
        for r in refs:
            if r.empty or (r.home_winner and r.away_winner):
                continue
            cur.execute(FACTS_SQL, {"pf": r.provider_fixture_id, "at": observed_at, "referee": r.referee,
                                    "country": r.referee_country, "hw": r.home_winner, "aw": r.away_winner,
                                    "h1": r.first_half_at, "h2": r.second_half_at, "hash": payload_hash,
                                    "version": NORMALIZER_VERSION})
            added += max(cur.rowcount, 0)
    return added


def apply_player_extras(cur: psycopg.Cursor[Any], fixture_id: int, sides: Mapping[int, str],
                        refs: Iterable[PlayerStatsRef], *, payload_hash: str, observed_at: datetime) -> int:
    """Rows added for one fixture's players. ``sides`` maps a provider team id to 'home' / 'away'."""
    added = 0
    for ps in refs:
        x = ps.extras
        if not x or all(x.get(k) is None for k in EXTRA_KEYS):
            continue
        pos = x.get("position_played")
        cur.execute(EXTRAS_SQL, {
            "f": fixture_id, "p": ps.provider_player_id, "at": observed_at, "side": sides.get(ps.provider_team_id),
            "pos": pos if isinstance(pos, str) else None, "off": _count(x.get("offsides")),
            "past": _count(x.get("dribbled_past")), "won": _count(x.get("penalties_won")),
            "com": _count(x.get("penalties_committed")), "saved": _count(x.get("penalties_saved")),
            "hash": payload_hash, "version": NORMALIZER_VERSION})
        added += max(cur.rowcount, 0)
    return added
