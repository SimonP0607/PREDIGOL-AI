"""Leagues and seasons truth: every tracked competition against one /leagues answer.

Per competition: is it still listed, its type and country, which season the provider calls current
and which we do, the current season's dates, the seasons the provider has since the migration
floor that we never created or never filled, and duplicates among our tracked competitions.
Labels (the mandate's): WRONG_TYPE, WRONG_COUNTRY, STALE_CURRENT_SEASON, WRONG_SEASON,
MISSING_SEASON, SEASON_NOT_MIGRATED, DUPLICATE_COMPETITION.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.v2.ledger import Evidence
from fbi.truth.v2.team_history import fold

MIGRATION_FLOOR = 2018
"""The historical migration fetched fixtures from the 2018 season on (raw.backfill_tasks)."""

COMPETITIONS_SQL = """
SELECT c.id, c.provider_league_id, c.name, c.type, c.country FROM core.competitions c WHERE c.is_tracked
 ORDER BY c.provider_league_id
"""
SEASONS_SQL = """
SELECT c.provider_league_id, cs.season, cs.is_current, cs.start_date, cs.end_date,
       (SELECT count(*) FROM core.fixtures f WHERE f.competition_season_id = cs.id) AS fixtures
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id WHERE c.is_tracked
"""


def ours(conn: psycopg.Connection[Any]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COMPETITIONS_SQL)
        comps = [dict(r) for r in cur.fetchall()]
        cur.execute(SEASONS_SQL)
        seasons: dict[int, list[dict[str, Any]]] = {}
        for r in cur.fetchall():
            seasons.setdefault(int(r["provider_league_id"]), []).append(dict(r))
    return comps, seasons


def _day(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


@dataclass
class LeagueVerdict:
    league: int
    name: str
    labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    api_current: int | None = None
    our_current: list[int] = field(default_factory=list)


def judge(comp: Mapping[str, Any], item: Mapping[str, Any] | None, seasons: Sequence[Mapping[str, Any]]
          ) -> LeagueVerdict:
    v = LeagueVerdict(int(comp["provider_league_id"]), str(comp["name"]))
    v.our_current = sorted(int(s["season"]) for s in seasons if s["is_current"])
    if item is None:
        v.labels.append("STALE_ENTITY")
        v.notes.append("the provider no longer lists this competition")
        return v
    league = item.get("league") if isinstance(item.get("league"), dict) else {}
    country = item.get("country") if isinstance(item.get("country"), dict) else {}
    api_type = str((league or {}).get("type") or "").lower()
    if api_type and api_type != str(comp["type"]).lower():
        v.labels.append("WRONG_TYPE")
        v.notes.append(f"type: provider {api_type}, ours {comp['type']}")
    api_country = (country or {}).get("name")
    if api_country and comp.get("country") and fold(str(api_country)) != fold(str(comp["country"])):
        v.labels.append("WRONG_COUNTRY")
        v.notes.append(f"country: provider {api_country}, ours {comp['country']}")
    api_seasons = [s for s in item.get("seasons") or [] if isinstance(s, dict) and isinstance(s.get("year"), int)]
    current = [s for s in api_seasons if s.get("current")]
    by_year = {int(s["season"]): s for s in seasons}
    if current:
        cur = current[-1]
        v.api_current = int(cur["year"])
        if v.api_current not in by_year:
            v.labels.append("MISSING_SEASON")
            v.notes.append(f"the provider's current season {v.api_current} is not in our seasons")
        elif v.our_current != [v.api_current]:
            older = all(y < v.api_current for y in v.our_current) if v.our_current else True
            v.labels.append("STALE_CURRENT_SEASON" if older else "WRONG_SEASON")
            v.notes.append(f"current season: provider {v.api_current}, ours {v.our_current}")
        else:
            mine = by_year[v.api_current]
            if (_day(cur.get("start")), _day(cur.get("end"))) != (_day(mine.get("start_date")),
                                                                  _day(mine.get("end_date"))):
                v.labels.append("WRONG_SEASON")
                v.notes.append(f"dates: provider {cur.get('start')}..{cur.get('end')}, ours "
                               f"{mine.get('start_date')}..{mine.get('end_date')}")
    elif v.our_current:
        v.notes.append(f"the provider marks no season current; ours: {v.our_current}")
    missing = [int(s["year"]) for s in api_seasons if int(s["year"]) >= MIGRATION_FLOOR
               and int(s["year"]) not in by_year]
    if missing:
        v.labels.append("MISSING_SEASON")
        v.notes.append(f"seasons since {MIGRATION_FLOOR} we never created: {missing}")
    empty = [int(s["year"]) for s in api_seasons if int(s["year"]) >= MIGRATION_FLOOR
             and int(s["year"]) in by_year and not by_year[int(s["year"])]["fixtures"]]
    if empty:
        v.labels.append("SEASON_NOT_MIGRATED")
        v.notes.append(f"seasons since {MIGRATION_FLOOR} the provider covers but we hold no fixture of: {empty}")
    return v


def duplicates(comps: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    groups: dict[tuple[str, str], list[int]] = {}
    for c in comps:
        groups.setdefault((fold(str(c["name"])), fold(str(c.get("country") or ""))), []).append(
            int(c["provider_league_id"]))
    return [ids for ids in groups.values() if len(ids) > 1]


META = {
    "STALE_ENTITY": ("high", "predigol", "we track a competition the provider no longer lists"),
    "WRONG_TYPE": ("medium", "predigol", "our league/cup type differs from the provider's"),
    "WRONG_COUNTRY": ("low", "predigol", "our country differs from the provider's"),
    "STALE_CURRENT_SEASON": ("critical", "predigol", "our current season is older than the provider's: the product "
                             "shows last season as current"),
    "WRONG_SEASON": ("high", "predigol", "our current season or its dates differ from the provider's"),
    "MISSING_SEASON": ("high", "predigol", "a season the provider has (since the migration floor) is missing"),
    "SEASON_NOT_MIGRATED": ("medium", "predigol", "a season row exists but none of its fixtures was migrated"),
}


def evidence(verdicts: Sequence[LeagueVerdict], dups: Sequence[Sequence[int]], api_ref: Mapping[str, Any] | None
             ) -> list[Evidence]:
    out = []
    by: dict[str, list[LeagueVerdict]] = {}
    for v in verdicts:
        for label in v.labels:
            by.setdefault(label, []).append(v)
    for label, items in sorted(by.items()):
        sev, fault, cause = META[label]
        ex = [{"league": v.league, "name": v.name, "notes": v.notes} for v in items[:10]]
        out.append(Evidence(key=f"leagues:{label}", area="leagues", issue_type=label, severity=sev,
                            at_fault=fault, entity=f"{len(items)} competitions",
                            claim=f"{len(items)} tracked competitions: {cause}",
                            api={**(dict(api_ref) if api_ref else {}), "examples": ex}, root_cause=cause))
    if dups:
        out.append(Evidence(key="leagues:DUPLICATE_COMPETITION", area="leagues", issue_type="DUPLICATE_COMPETITION",
                            severity="medium", at_fault="predigol", entity=f"{len(dups)} groups",
                            claim=f"{len(dups)} groups of tracked competitions share a name and country",
                            db={"groups": [list(g) for g in dups]}))
    return out
