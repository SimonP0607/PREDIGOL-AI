"""The reads of ``credibility-v2`` (IA-126, AD-C08): every source's past availability claims about identified players, and the provider's
truth they are judged with, as of a moment. Read only: every statement is a SELECT; it writes nothing.

It reads ``ai.evidence`` with the ONE question every reader asks (``subject_type IS NULL OR %(typed)s``): research v2's claims count only
when the caller says they are part of what the system reads (``fbi.ai.gates.typed_visible``, passed in as ``typed``). The provider's line-ups
and injury reports are read with the engine's own statements (``fbi.evidence.engine``), cut at the same moment.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.evidence import outlets_of
from fbi.evidence import credibility, engine, rules

CLAIMS_SQL: Final = """
SELECT * FROM (
  SELECT CASE WHEN e.subject_type IS NULL THEN 'v1' ELSE 'v2' END AS generation, e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.origin, e.source_domain,
         e.source_tier, e.source_class, e.published_at, e.retrieved_at, e.attributes,
         row_number() OVER (PARTITION BY COALESCE(e.source_domain, e.origin) ORDER BY e.retrieved_at DESC, e.id DESC) AS n
    FROM ai.evidence e
   WHERE (e.subject_type IS NULL OR %(typed)s)
     AND e.kind IN ('injury', 'suspension', 'doubtful', 'lineup') AND e.provider_player_id IS NOT NULL AND e.team_id IS NOT NULL
     AND e.retrieved_at <= %(at)s AND e.retrieved_at > %(since)s
) h WHERE h.n <= %(per_source)s
"""
"""Every source's availability claims about identified players in the window, the newest ``HISTORY_PER_SOURCE`` of each (a bound on the
read, as v1). They are both the history judged and the peers a claim is checked against (a claim of a higher tier about the same man)."""


def snapshot_inputs(conn: psycopg.Connection[Any], *, at: datetime, typed: bool,
                    window: timedelta = rules.CREDIBILITY_WINDOW) -> dict[str, Any]:
    """What a snapshot of every source is learned from, as of ``at``: the claims (as the engine's items), the teams' matches and the
    provider's line-ups and injury reports of those matches known by ``at``."""
    since = at - window
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET LOCAL statement_timeout = '90s'")
        cur.execute(CLAIMS_SQL, {"at": at, "since": since, "typed": typed, "per_source": rules.HISTORY_PER_SOURCE})
        raw = [dict(r) for r in cur.fetchall()]
        teams = sorted({int(r["team_id"]) for r in raw})
        team_rows: list[dict[str, Any]] = []
        if teams:
            cur.execute(engine.TEAM_FIXTURES_SQL, {"teams": teams, "since": since - rules.LOOKBACK, "until": at + engine.NEXT_MATCH_AHEAD})
            team_rows = [dict(r) for r in cur.fetchall()]
    hosts = {str(r["source_domain"]) for r in raw if r.get("source_domain")}
    outlets = outlets_of(conn, hosts) if hosts else {}
    items = [engine.item_of(r, outlets, excerpt=False) for r in raw]
    team_fixtures: dict[int, list[tuple[datetime, int]]] = defaultdict(list)
    for f in team_rows:
        for team in (f["home_team_id"], f["away_team_id"]):
            team_fixtures[int(team)].append((f["kickoff_at"], int(f["id"])))
    fixtures = {i.fixture_id for i in items if i.fixture_id is not None} | {fid for v in team_fixtures.values() for _, fid in v}
    return {"items": items, "team_fixtures": dict(team_fixtures), "sheets": engine._sheets(conn, fixtures, at=at),
            "listings": engine._listings(conn, fixtures, at=at), "claims": len(raw)}


def snapshot(conn: psycopg.Connection[Any], *, at: datetime, typed: bool) -> dict[str, Any]:
    """The credibility of every source by type of fact as of ``at`` (no match excluded: a snapshot, not the reading of one match), and the
    replay against ``credibility-v1`` on the same inputs."""
    got = snapshot_inputs(conn, at=at, typed=typed)
    items = got["items"]
    learned = credibility.learn_v2(items, items, exclude_fixture=None, team_fixtures=got["team_fixtures"], sheets=got["sheets"],
                                   listings=got["listings"])
    rep = credibility.replay(items, items, team_fixtures=got["team_fixtures"], sheets=got["sheets"], listings=got["listings"])
    return {"version": credibility.VERSION, "digest": credibility.digest(), "at": at.isoformat(), "typed": typed, "claims": got["claims"],
            "credibilities": [c.as_json() for c in learned.values()], "replay": rep, "decides": False}
