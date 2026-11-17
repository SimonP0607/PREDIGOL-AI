"""The owner's measures of the unified research (IA-087/088/089), READ ONLY: what the shadow did, and what the code would do on what production
already stored. ``scripts/ia_research_unified.py`` prints them. No model, no search, no write.

* ``report``  the ``xu_*`` counts of the passes in a window, the pages remembered (``rk-u1:page``) and the calls of the road (``ai.usage``).
* ``linking`` AD-C06: of the players v1 wrote a web fact about, how many the whole squad names (``name-match-v2``) and how many research v2's
              thirty would - by scope (clubs, national teams); and of research v2's own claims about a player, how many ``name-match-v2`` refuses
              (the validator v2 used accepted any word of the name).
* ``windows`` AD-C05: on the pages v1 read (the search cache, purged 14 days after it expires), whether the player of each of its facts is named
              in the text, in the first 700 characters (what research v2 shows) and in the windows this road would send.
* ``replay``  AD-C07: ``ladder-v1`` against ``ladder-v2`` on the stored web evidence, fact by fact, and the facts ``ladder-v1`` confirms with copies
              of one origin only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import assertions, deep_pages, mentions, quarantine, source_policy, unified_research
from fbi.ai.entity_research import load_match
from fbi.evidence import rules

V2_CUT: Final = 700

PASSES_SQL: Final = """
SELECT key, sum(value::int) AS n FROM ai.fixture_passes p, jsonb_each_text(p.counts)
 WHERE p.started_at >= %(since)s AND p.started_at < %(until)s AND key LIKE 'xu\\_%%' GROUP BY key ORDER BY key
"""
PAGES_SQL: Final = "SELECT count(*) AS n FROM ai.research_cache WHERE scope = 'url' AND key LIKE %(like)s"
CALLS_SQL: Final = """
SELECT count(*) AS calls, COALESCE(sum(cost_usd), 0) AS usd FROM ai.usage
 WHERE agent = %(agent)s AND input_hash LIKE %(like)s AND at >= %(since)s AND at < %(until)s
"""
FACTS_SQL: Final = """
SELECT e.fixture_id, e.attributes->>'player_name' AS player_name, e.provider_player_id, e.source_url, c.entity_scope
  FROM ai.evidence e JOIN core.fixtures f ON f.id = e.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE e.origin = 'web' AND e.subject_type IS NULL AND e.retrieved_at >= %(since)s AND e.retrieved_at < %(until)s
   AND e.kind IN ('injury', 'doubtful', 'suspension', 'lineup') AND COALESCE(e.attributes->>'player_name', '') <> ''
 ORDER BY e.fixture_id LIMIT %(limit)s
"""
V2_CLAIMS_SQL: Final = """
SELECT e.subject_id, e.claim, e.fixture_id, e.team_id FROM ai.evidence e
 WHERE e.subject_type = 'PLAYER' AND e.origin = 'web' AND e.retrieved_at >= %(since)s AND e.retrieved_at < %(until)s
   AND e.fixture_id IS NOT NULL ORDER BY e.fixture_id LIMIT %(limit)s
"""
PAGES_OF_SQL: Final = """
SELECT DISTINCT ON (x->>'url') x->>'url' AS url, COALESCE(x->>'title', '') AS title, COALESCE(x->>'snippet', '') AS snippet
  FROM ai.research_cache rc, jsonb_array_elements(rc.payload->'results') x
 WHERE rc.scope = 'search' AND x->>'url' = ANY(%(urls)s) ORDER BY x->>'url', rc.fetched_at DESC
"""
EVIDENCE_SQL: Final = """
SELECT fixture_id, team_id, provider_player_id, attributes->>'player_name' AS player_name, kind, attributes->>'assertion' AS assertion,
       source_domain, claim, retrieved_at
  FROM ai.evidence WHERE origin = 'web' AND retrieved_at >= %(since)s AND retrieved_at < %(until)s
   AND kind IN ('injury', 'doubtful', 'suspension', 'lineup') LIMIT %(limit)s
"""
TYPE_OF: Final = {"injury": "OUT", "doubtful": "DOUBT", "suspension": "SUSPENSION", "lineup": "STARTER"}


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def report(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> dict[str, Any]:
    counts = {str(r["key"]): int(r["n"]) for r in _rows(conn, PASSES_SQL, {"since": since, "until": until})}
    pages = _rows(conn, PAGES_SQL, {"like": unified_research.KEY_PREFIX + "%"})[0]["n"]
    calls = _rows(conn, CALLS_SQL, {"agent": quarantine.AGENT, "like": unified_research.LEDGER_PREFIX + "%",
                                    "since": since, "until": until})[0]
    return {"counts": counts, "pages_remembered": int(pages), "calls": int(calls["calls"]), "usd": float(calls["usd"])}


class _Rosters:
    """The roster of each match, built once (as of ``at``)."""

    def __init__(self, conn: psycopg.Connection[Any], at: datetime) -> None:
        self.conn, self.at = conn, at
        self.cache: dict[int, tuple[Any, unified_research.Roster] | None] = {}

    def of(self, fixture_id: int) -> tuple[Any, unified_research.Roster] | None:
        if fixture_id not in self.cache:
            match = load_match(self.conn, fixture_id, at=self.at)
            self.cache[fixture_id] = None if match is None else (match, unified_research.roster_for(self.conn, match, at=self.at))
        return self.cache[fixture_id]


def _link(name: str, pid: int | None, roster: unified_research.Roster) -> int | None:
    if pid is not None and roster.catalogue.by_key("PLAYER", pid) is not None:
        return pid
    found = {m.who.id for m in mentions.mentions_in(name, roster.catalogue) if m.who.kind == "PLAYER"}
    return next(iter(found)) if len(found) == 1 else None


def linking(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, at: datetime, limit: int = 5000) -> dict[str, Any]:
    rosters = _Rosters(conn, at)
    strata: dict[str, Counter[str]] = {}
    seen: set[tuple[int, str]] = set()
    for r in _rows(conn, FACTS_SQL, {"since": since, "until": until, "limit": limit}):
        key = (int(r["fixture_id"]), " ".join(mentions.words(r["player_name"])))
        if key in seen:
            continue
        seen.add(key)
        got = rosters.of(int(r["fixture_id"]))
        c = strata.setdefault(str(r["entity_scope"]), Counter())
        c["players"] += 1
        if got is None:
            c["no_match"] += 1
            continue
        linked = _link(str(r["player_name"]), r["provider_player_id"], got[1])
        c["unidentified_full"] += linked is None
        c["unidentified_30"] += linked is None or linked not in got[1].capped
    refused: Counter[str] = Counter()
    claims = 0
    for r in _rows(conn, V2_CLAIMS_SQL, {"since": since, "until": until, "limit": limit}):
        got = rosters.of(int(r["fixture_id"]))
        who = None if got is None else got[1].catalogue.by_key("PLAYER", int(r["subject_id"]))
        if got is None or who is None:
            continue
        claims += 1
        why = mentions.validate(r["claim"], who, got[1].catalogue)
        if why is not None:
            refused[why] += 1
    return {"facts": {k: dict(v) for k, v in sorted(strata.items())}, "v2_claims": claims, "v2_refused": dict(refused)}


def windows(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, at: datetime, limit: int = 3000) -> dict[str, Any]:
    rosters = _Rosters(conn, at)
    facts = _rows(conn, FACTS_SQL, {"since": since, "until": until, "limit": limit})
    by_url: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        by_url.setdefault(str(f["source_url"]), []).append(f)
    pages = _rows(conn, PAGES_OF_SQL, {"urls": sorted(by_url)})
    common = deep_pages.common_lines(((source_policy.host_of(p["url"]) or ""), p["snippet"]) for p in pages)
    out: Counter[str] = Counter()
    for p in pages:
        fl = by_url.get(p["url"]) or []
        got = rosters.of(int(fl[0]["fixture_id"])) if fl else None
        if got is None:
            continue
        roster = got[1]
        text = deep_pages.clean(p["title"], p["snippet"], common=common.get(source_policy.host_of(p["url"]) or "", frozenset()))
        chosen = deep_pages.choose(text, roster.catalogue)
        out["pages"] += 1
        out["windows"] += len(chosen)
        out["pages_without_window"] += not chosen
        for f in {" ".join(mentions.words(x["player_name"])): x for x in fl}.values():
            who = _link(str(f["player_name"]), f["provider_player_id"], roster)
            out["facts"] += 1
            if who is None:
                continue
            out["linked"] += 1
            out["named_in_text"] += any(m.who.id == who for m in mentions.mentions_in(text, roster.catalogue))
            out["named_in_700"] += any(m.who.id == who for m in mentions.mentions_in(str(p["snippet"])[:V2_CUT], roster.catalogue))
            out["named_in_windows"] += any(("PLAYER", who) in w.subjects for w in chosen)
    return dict(out)


def _group(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        kind = TYPE_OF.get(str(r["kind"]))
        if kind is None:
            continue
        kind = "AVAILABLE" if r["assertion"] == "available" else kind
        who = str(r["provider_player_id"] or "") or "n:" + " ".join(mentions.words(r["player_name"] or ""))
        if who in ("", "n:"):
            continue
        scope = str(r["fixture_id"] or f"t{r['team_id']}")
        groups.setdefault((scope, who, assertions.ASSERTION_OF.get(kind, kind)), []).append({**r, "type": kind})
    return groups


def replay(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, policy: source_policy.SourcePolicy | None,
           limit: int = 20000) -> dict[str, Any]:
    groups = _group(_rows(conn, EVIDENCE_SQL, {"since": since, "until": until, "limit": limit}))
    moves: Counter[str] = Counter()
    copies_only = 0
    for items in groups.values():
        outlets: dict[str, str] = {}
        made: list[assertions.Assertion] = []
        for r in items:
            src = assertions.source_facts(policy, r["source_domain"])
            tier = src.tier or "D"
            outlets[src.domain] = min(outlets.get(src.domain, tier), tier, key=lambda t: rules.TIER_RANK[t])
            level, why = assertions.authority_for(src, r["type"], quote=str(r["claim"] or ""))
            made.append(assertions.Assertion("PLAYER", 0, None, r["type"], str(r["source_domain"]), src, level, why, r["retrieved_at"],
                                             attributed_to=assertions.speaker_of(str(r["claim"] or ""), team_id=r["team_id"]),
                                             text_hash=deep_pages.simhash(str(r["claim"] or "")), quote=str(r["claim"] or "")))
        old, _ = rules.status_of(outlets)
        new, _ = assertions.rung(made)
        moves[f"{old}->{new}"] += 1
        if old == "CONFIRMADO" and assertions.rung([replace(a, authority="informa", source=replace(a.source, tier="C")) for a in made])[0] \
                != "CONFIRMADO":
            copies_only += 1
    return {"facts": len(groups), "moves": dict(moves.most_common()), "confirmed_by_copies_only": copies_only}


__all__ = ["linking", "replay", "report", "windows"]
