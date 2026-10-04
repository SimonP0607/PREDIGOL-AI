"""Why does one team have 338 matches and another 0, 8 or 14? Classify every thin history.

For a team with few fixtures in PrediGol, ``/leagues?team=X`` (one request) lists every league
and season in which the provider has it playing at least one match. Against our tracked
competitions and the seasons we hold:

* the provider has it in a tracked competition's season we do not hold   -> SEASON_NOT_MIGRATED
* ... a season we hold, but we have none of its matches with this team   -> MISSING_BACKFILL
* another team row of ours has the same name and country                 -> IDENTITY_MAPPING_ERROR
* the provider lists nothing at all for it                               -> PROVIDER_COVERAGE
* otherwise: it plays in competitions we do not track; what we hold is
  what we track                                                           -> REAL_LOW_HISTORY
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.v2.ledger import Evidence

YOUTH = re.compile(r"\bU-?\d{2}\b|\bU\d{2}\b|\byouth\b|\bjuniors?\b|\bsub-?\d{2}\b", re.IGNORECASE)
RESERVE = re.compile(r"\s(II|B|2)$|\breserves?\b", re.IGNORECASE)
WOMEN = re.compile(r"\s(W|Women|Femenino|Feminine|Ladies|Frauen|Femminile)$|\bwomen\b", re.IGNORECASE)

COUNTS_SQL = """
WITH apps AS (
    SELECT f.home_team_id AS team_id, f.id, cs.competition_id, cs.id AS cs_id FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    UNION ALL
    SELECT f.away_team_id, f.id, cs.competition_id, cs.id FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
)
SELECT t.id, t.provider_team_id, t.name, t.country, t.is_national,
       count(a.id) AS fixtures, count(DISTINCT a.competition_id) AS competitions, count(DISTINCT a.cs_id) AS seasons,
       array_remove(array_agg(DISTINCT c.provider_league_id), NULL) AS leagues
  FROM core.teams t LEFT JOIN apps a ON a.team_id = t.id
  LEFT JOIN core.competitions c ON c.id = a.competition_id
 GROUP BY t.id
"""


def fold(name: str) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFKD", name.lower()) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def kind_of(name: str, is_national: bool) -> str:
    if WOMEN.search(name):
        return "women"
    if YOUTH.search(name):
        return "youth"
    if RESERVE.search(name):
        return "reserve"
    return "national" if is_national else "club"


def team_counts(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COUNTS_SQL)
        return [dict(r) for r in cur.fetchall()]


def distribution(teams: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How fixtures per team are spread, overall and by kind of team."""
    buckets = {"0": 0, "1-9": 0, "10-49": 0, "50-149": 0, "150-299": 0, "300+": 0}
    by_kind: dict[str, dict[str, int]] = {}
    for t in teams:
        n = int(t["fixtures"])
        b = "0" if n == 0 else "1-9" if n < 10 else "10-49" if n < 50 else "50-149" if n < 150 else \
            "150-299" if n < 300 else "300+"
        buckets[b] += 1
        k = kind_of(str(t["name"]), bool(t["is_national"]))
        by_kind.setdefault(k, {}).setdefault(b, 0)
        by_kind[k][b] += 1
    return {"buckets": buckets, "by_kind": by_kind, "teams": len(teams)}


def duplicates(teams: Sequence[Mapping[str, Any]]) -> dict[int, list[int]]:
    """Team rows sharing a folded name and country with another row (provider ids)."""
    groups: dict[tuple[str, str], list[int]] = {}
    for t in teams:
        groups.setdefault((fold(str(t["name"])), str(t["country"] or "")), []).append(int(t["provider_team_id"]))
    out: dict[int, list[int]] = {}
    for ids in groups.values():
        if len(ids) > 1:
            for i in ids:
                out[i] = [j for j in ids if j != i]
    return out


@dataclass
class HistoryVerdict:
    team: int
    name: str
    fixtures: int
    kind: str
    label: str
    provider_seasons: int = 0
    tracked_seasons: list[str] = field(default_factory=list)
    not_migrated: list[str] = field(default_factory=list)
    missing_matches: list[str] = field(default_factory=list)
    duplicates: list[int] = field(default_factory=list)


def classify(team: Mapping[str, Any], leagues_body: Mapping[str, Any] | None, *, tracked: set[int],
             held: Mapping[tuple[int, int], int], ours_by_cs: Mapping[tuple[int, int], int],
             dups: Sequence[int]) -> HistoryVerdict:
    """``held``: (league, season) -> competition_season id we hold; ``ours_by_cs``: (league, season) -> our
    fixtures with this team there."""
    v = HistoryVerdict(int(team["provider_team_id"]), str(team["name"]), int(team["fixtures"]),
                       kind_of(str(team["name"]), bool(team["is_national"])), "REAL_LOW_HISTORY",
                       duplicates=list(dups))
    items = leagues_body.get("response") if leagues_body else None
    pairs: list[tuple[int, int]] = []
    for item in items if isinstance(items, list) else []:
        league = item.get("league") if isinstance(item, dict) else None
        lid = league.get("id") if isinstance(league, dict) else None
        seasons = (item.get("seasons") or []) if isinstance(item, dict) else []
        for s in seasons if isinstance(seasons, list) else []:
            year = s.get("year") if isinstance(s, dict) else None
            if isinstance(lid, int) and isinstance(year, int):
                pairs.append((lid, year))
    v.provider_seasons = len(pairs)
    for lid, year in sorted(set(pairs)):
        if lid not in tracked:
            continue
        tag = f"{lid}/{year}"
        v.tracked_seasons.append(tag)
        if (lid, year) not in held:
            v.not_migrated.append(tag)
        elif not ours_by_cs.get((lid, year)):
            v.missing_matches.append(tag)
    if dups:
        v.label = "IDENTITY_MAPPING_ERROR"
    elif leagues_body is not None and not pairs:
        v.label = "PROVIDER_COVERAGE"
    elif v.missing_matches:
        v.label = "MISSING_BACKFILL"
    elif v.not_migrated:
        v.label = "SEASON_NOT_MIGRATED"
    return v


def evidence(verdicts: Sequence[HistoryVerdict]) -> list[Evidence]:
    """One entry per label, with examples (never one per team)."""
    out = []
    by: dict[str, list[HistoryVerdict]] = {}
    for v in verdicts:
        by.setdefault(v.label, []).append(v)
    meta = {
        "SEASON_NOT_MIGRATED": ("predigol", "medium", "the provider has these teams in seasons of tracked "
                                "competitions that were never migrated", "migrate those seasons (fixtures only)"),
        "MISSING_BACKFILL": ("predigol", "high", "seasons we hold lack this team's matches",
                             "re-sync the full season fixture list"),
        "IDENTITY_MAPPING_ERROR": ("predigol", "high", "two team rows share a name and country: the history is "
                                   "split between ids (or two clubs share a name)",
                                   "confirm against the provider's team pages; merge only through an alias map"),
        "PROVIDER_COVERAGE": ("provider", "low", "the provider lists no league for these teams", None),
        "REAL_LOW_HISTORY": ("none", "info", "these teams play in competitions PrediGol does not track; what we hold "
                             "is every match of theirs in what we track", None),
    }
    for label, items in sorted(by.items()):
        fault, sev, cause, fix = meta[label]
        ex = [{"team": v.team, "name": v.name, "fixtures": v.fixtures, "kind": v.kind,
               "provider_seasons": v.provider_seasons, "tracked_seasons": v.tracked_seasons[:6],
               "not_migrated": v.not_migrated[:6], "missing": v.missing_matches[:6], "duplicates": v.duplicates}
              for v in items[:8]]
        out.append(Evidence(key=f"team_history:{label}", area="team_history", issue_type=label, severity=sev,
                            at_fault=fault, entity=f"{len(items)} sampled teams",
                            claim=f"{len(items)} of {len(verdicts)} sampled thin-history teams: {cause}",
                            api={"examples": ex}, root_cause=cause, fix=fix,
                            status="ACCEPTED" if label == "REAL_LOW_HISTORY" else "OPEN"))
    return out
