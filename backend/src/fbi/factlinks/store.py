"""The list of facts of one evaluation, written with it (IA-122, AD-G08): read as of its moment, validated by ``link-v1``, kept.

``record`` is called by the evaluation cycle (``fbi.evalcycle.run``) right after it writes an evaluation E1-E4 and its verdicts, in the same
transaction: the database refuses the rows otherwise (``intel.eval_sources_at_decision``, revision 0160), so a relation drawn later -
from what is known today - can never be written. It reads only what the evaluation could have read: the match's web facts
(``ai.evidence``, ``origin = 'web'``) known and published by the moment it decided as of, not outdated, and research v2's claims only when
they are part of what the system reads (``typed``: the cycle passes ``fbi.ai.gates.typed_visible``). The provider's own reports (the
injury report, the line-ups) are the match's data, not news: they are not listed here.

Every fact looked at is a row: linked, with its entity, level, relation and the effect on each selection, or refused with the reason.
The list itself is a row too, so an evaluation that looked at nothing says so."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.factlinks import VERSION
from fbi.factlinks.validate import Fact, Link, Person, SelectionDependency, World, validate_all

MAX_FACTS: Final = 500
LINEUP_DAYS: Final = 180
"""The recent line-ups the closed world of a match's players reads, besides the squads."""

FIXTURE_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, h.name AS home_name, h.short_name AS home_short,
       a.name AS away_name, a.short_name AS away_short
  FROM core.fixtures f JOIN core.teams h ON h.id = f.home_team_id JOIN core.teams a ON a.id = f.away_team_id
 WHERE f.id = %(fixture)s
"""
PREVIOUS_SQL: Final = """
SELECT t.team_id, (SELECT max(f.kickoff_at) FROM core.fixtures f
                    WHERE (f.home_team_id = t.team_id OR f.away_team_id = t.team_id) AND f.kickoff_at < %(kickoff)s
                      AND f.id <> %(fixture)s) AS previous
  FROM unnest(%(teams)s::bigint[]) AS t(team_id)
"""
PEOPLE_SQL: Final = """
SELECT w.team_id, w.provider_player_id, p.id AS player_id, p.name, array_remove(array_agg(DISTINCT w.seen_name), NULL) AS seen
  FROM (
    SELECT sm.team_id, sm.provider_player_id, sm.player_name AS seen_name
      FROM core.squad_members sm WHERE sm.team_id = ANY(%(teams)s)
    UNION ALL
    SELECT CASE lp.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END, lp.provider_player_id, lp.player_name
      FROM core.fixtures f JOIN core.fixture_lineup_players lp ON lp.fixture_id = f.id
     WHERE (f.home_team_id = ANY(%(teams)s) OR f.away_team_id = ANY(%(teams)s))
       AND f.kickoff_at > %(kickoff)s - make_interval(days => %(days)s) AND f.kickoff_at <= %(kickoff)s
  ) w
  LEFT JOIN core.players p ON p.provider_player_id = w.provider_player_id
 WHERE w.team_id = ANY(%(teams)s) AND w.provider_player_id > 0
 GROUP BY w.team_id, w.provider_player_id, p.id, p.name
"""
FACTS_SQL: Final = """
SELECT e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.attributes->>'assertion' AS assertion,
       e.subject_type, (e.attributes->>'quote_checked') = 'true' AS quote_checked, e.published_at, e.retrieved_at, e.status,
       e.source_tier, e.source_name, e.source_url, e.item_id
  FROM ai.evidence e
 WHERE e.fixture_id = %(fixture)s AND e.origin = 'web' AND e.retrieved_at <= %(at)s
   AND (e.published_at IS NULL OR e.published_at <= %(at)s) AND e.status <> 'OUTDATED' AND (e.subject_type IS NULL OR %(typed)s)
 ORDER BY e.retrieved_at, e.id LIMIT %(limit)s
"""
"""The match's web facts as the evaluation could read them at its moment: research v2's claims only when the system reads them (``typed``)."""
DEPENDENCIES_SQL: Final = """
SELECT DISTINCT ON (market_key, selection, line) market_key, selection, line, players
  FROM intel.lineup_dependencies WHERE fixture_id = %(fixture)s AND known_at <= %(at)s
 ORDER BY market_key, selection, line, id DESC
"""
E2_SQL: Final = "SELECT evidence_id, action FROM intel.eval_facts WHERE fixture_id = %(fixture)s AND known_at <= %(at)s"

LIST_SQL: Final = """
INSERT INTO intel.eval_source_lists (run_id, fixture_id, evaluation, evaluation_version, known_at, candidates, linked, rejected, by_relation,
    by_rejection, version)
VALUES (%(run_id)s, %(fixture_id)s, %(evaluation)s, %(evaluation_version)s, %(known_at)s, %(candidates)s, %(linked)s, %(rejected)s,
    %(by_relation)s, %(by_rejection)s, %(version)s)
RETURNING id
"""
SOURCE_SQL: Final = """
INSERT INTO intel.eval_sources (list_id, run_id, fixture_id, evidence_id, item_id, linked, rejection, relation, level, warning, entity_type,
    entity_id, team_id, provider_player_id, named_as, kind, assertion, source_name, source_url, source_tier, source_type, fact_at,
    fact_known_at, decided_at, e2_action, selections, version)
VALUES (%(list_id)s, %(run_id)s, %(fixture_id)s, %(evidence_id)s, %(item_id)s, %(linked)s, %(rejection)s, %(relation)s, %(level)s,
    %(warning)s, %(entity_type)s, %(entity_id)s, %(team_id)s, %(provider_player_id)s, %(named_as)s, %(kind)s, %(assertion)s,
    %(source_name)s, %(source_url)s, %(source_tier)s, %(source_type)s, %(fact_at)s, %(fact_known_at)s, %(decided_at)s, %(e2_action)s,
    %(selections)s, %(version)s)
"""


@dataclass
class Recorded:
    list_id: int
    candidates: int
    linked: int
    by_relation: dict[str, int] = field(default_factory=dict)
    by_rejection: dict[str, int] = field(default_factory=dict)


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def world_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> World | None:
    fx = _rows(conn, FIXTURE_SQL, {"fixture": fixture_id})
    if not fx:
        return None
    f = fx[0]
    teams = {int(f["home_team_id"]): tuple(n for n in (f["home_name"], f["home_short"]) if n),
             int(f["away_team_id"]): tuple(n for n in (f["away_name"], f["away_short"]) if n)}
    ids = list(teams)
    previous = {int(r["team_id"]): r["previous"] for r in _rows(conn, PREVIOUS_SQL, {"teams": ids, "kickoff": f["kickoff_at"],
                                                                                   "fixture": fixture_id}) if r["previous"]}
    people = [Person(int(r["provider_player_id"]), None if r["player_id"] is None else int(r["player_id"]), int(r["team_id"]),
                     tuple(dict.fromkeys(n for n in [r["name"], *(r["seen"] or [])] if n)))
              for r in _rows(conn, PEOPLE_SQL, {"teams": ids, "kickoff": f["kickoff_at"], "days": LINEUP_DAYS})]
    return World(fixture_id, f["kickoff_at"], at, teams, people, previous)


def facts_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime, *, typed: bool) -> list[Fact]:
    return [Fact(int(r["id"]), r["fixture_id"], r["team_id"], r["provider_player_id"], str(r["kind"]), r["assertion"], str(r["claim"]),
                 r["subject_type"] is not None or bool(r["quote_checked"]), r["published_at"], r["retrieved_at"], str(r["status"]),
                 str(r["source_tier"]), str(r["source_name"]), r["source_url"], r["item_id"])
            for r in _rows(conn, FACTS_SQL, {"fixture": fixture_id, "at": at, "typed": typed, "limit": MAX_FACTS})]


def dependencies_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> list[SelectionDependency]:
    out: list[SelectionDependency] = []
    for r in _rows(conn, DEPENDENCIES_SQL, {"fixture": fixture_id, "at": at}):
        shifts = {int(p["provider_player_id"]): (float(p.get("shift_without") or 0.0), float(p.get("shift_full") or 0.0))
                  for p in r["players"] or [] if p.get("provider_player_id") is not None}
        out.append(SelectionDependency((str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"]))), shifts))
    return out


def _row(link: Link, *, list_id: int, run_id: int, at: datetime, e2: Mapping[int, str]) -> dict[str, Any]:
    f = link.fact
    return {"list_id": list_id, "run_id": run_id, "fixture_id": f.fixture_id, "evidence_id": f.evidence_id, "item_id": f.item_id,
            "linked": link.linked, "rejection": link.rejection, "relation": link.relation,
            "level": link.level if link.linked else None, "warning": link.warning if link.linked else None,
            "entity_type": link.entity_type, "entity_id": link.entity_id, "team_id": link.team_id,
            "provider_player_id": f.provider_player_id, "named_as": None if link.named_as is None else link.named_as[:120],
            "kind": f.kind[:40], "assertion": None if not f.assertion else f.assertion[:40], "source_name": f.source_name[:200],
            "source_url": f.source_url if f.source_url and f.source_url.startswith(("http://", "https://")) else None,
            "source_tier": f.tier[:40], "source_type": link.source_type,
            "fact_at": f.published_at if f.published_at is not None and f.published_at <= at else None,
            "fact_known_at": min(f.known_at, at), "decided_at": at, "e2_action": e2.get(f.evidence_id),
            "selections": Jsonb([{"market_key": e.key[0], "selection": e.key[1], "line": str(e.key[2]), "relation": e.relation,
                                  "shift": e.shift} for e in link.effects]),
            "version": link.version}


def record(conn: psycopg.Connection[Any], *, run_id: int, fixture_id: int, evaluation: str, evaluation_version: int, known_at: datetime,
           typed: bool) -> Recorded | None:
    """The facts evaluation ``run_id`` looked at, validated and written - in the caller's transaction, the evaluation's own. None when
    revision 0160 is not applied yet (the evaluation goes on without its list)."""
    present = conn.execute("SELECT to_regclass('intel.eval_sources') IS NOT NULL").fetchone()
    if not (present and present[0]):
        return None
    world = world_of(conn, fixture_id, known_at)
    facts = facts_of(conn, fixture_id, known_at, typed=typed) if world is not None else []
    links = validate_all(facts, world, dependencies_of(conn, fixture_id, known_at)) if world is not None else []
    # a fact known after the moment is never written: the SQL does not read it, and the validator refuses it if it did
    links = [lk for lk in links if lk.rejection != "posterior_a_la_decision"]
    relations: Counter[str] = Counter(str(lk.relation) for lk in links if lk.relation is not None)
    rejections: Counter[str] = Counter(str(lk.rejection) for lk in links if lk.rejection is not None)
    got = conn.execute(LIST_SQL, {
        "run_id": run_id, "fixture_id": fixture_id, "evaluation": evaluation, "evaluation_version": evaluation_version,
        "known_at": known_at, "candidates": len(links), "linked": sum(1 for lk in links if lk.linked),
        "rejected": sum(1 for lk in links if not lk.linked), "by_relation": Jsonb(dict(sorted(relations.items()))),
        "by_rejection": Jsonb(dict(sorted(rejections.items()))), "version": VERSION}).fetchone()
    assert got is not None
    list_id = int(got[0])
    e2 = {int(r["evidence_id"]): str(r["action"]) for r in _rows(conn, E2_SQL, {"fixture": fixture_id, "at": known_at})}
    for lk in links:
        conn.execute(SOURCE_SQL, _row(lk, list_id=list_id, run_id=run_id, at=known_at, e2=e2))
    return Recorded(list_id, len(links), sum(1 for lk in links if lk.linked), dict(relations), dict(rejections))


def coverage(conn: psycopg.Connection[Any], *, since: datetime) -> dict[str, int]:
    """How many evaluations (not failed) since ``since`` have their list, and how many facts were written after their decision (0)."""
    rows = _rows(conn, """
        SELECT count(*) FILTER (WHERE r.status <> 'fallida') AS evaluations,
               count(l.id) FILTER (WHERE r.status <> 'fallida') AS with_list,
               (SELECT count(*) FROM intel.eval_sources s JOIN intel.eval_runs r2 ON r2.id = s.run_id
                 WHERE r2.known_at >= %(since)s AND s.fact_known_at > r2.known_at) AS after_decision
          FROM intel.eval_runs r LEFT JOIN intel.eval_source_lists l ON l.run_id = r.id
         WHERE r.known_at >= %(since)s
    """, {"since": since})
    return {k: int(v or 0) for k, v in rows[0].items()} if rows else {}


__all__ = ["Recorded", "coverage", "dependencies_of", "facts_of", "record", "world_of"]
