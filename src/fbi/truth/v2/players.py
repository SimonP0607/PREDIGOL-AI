"""Player statistics truth: /players?id&season against our per-match rows for the same scope, and
against what the product shows.

The provider's player statistics are "calculated according to the team id, league id and season"
(a transfer gives two blocks in one season); its ``rating`` is its own position-relative
algorithm (PROVIDER_DEFINED_METRIC - compared to nothing, averaged by nobody but the provider).
We store one row per player per fixture (``core.fixture_player_stats``, from /fixtures/players),
including the substitutes who never came on (minutes NULL). So, per block (team x league x
season):

* appearances = our rows with minutes > 0, line-ups = those not marked substitute, minutes,
  goals, assists, yellow and red cards - against the provider's block (tolerance 0, minutes
  within ``MINUTES_SLACK`` for the provider's own corrections);
* the product: ``PLAYER_AGG`` (player list and page) counts EVERY row - an unused substitute is
  an "appearance" - over 400 days of every competition, national team included, and labels the
  player with the team of his LAST appearance (Spain, Norway, England after an international
  window). Those are PrediGol bugs of scope and definition, not provider errors.

Three team notions are kept apart: ``current_club`` (the provider's /players/squads or
/players/teams: the club he is registered with now), ``national_team`` and
``last_appearance_team``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.v2.ledger import Evidence

MINUTES_SLACK = 10
COUNT_FIELDS = ("appearances", "lineups", "goals", "assists", "yellow", "red")


def _d(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Block:
    team: int
    team_name: str
    league: int
    league_name: str
    season: int
    appearances: int | None
    lineups: int | None
    minutes: int | None
    goals: int | None
    assists: int | None
    yellow: int | None
    red: int | None
    rating: str | None = None
    bench: int | None = None

    def get(self, name: str) -> int | None:
        return getattr(self, name)  # type: ignore[no-any-return]


def api_blocks(body: Mapping[str, Any]) -> tuple[dict[str, Any], list[Block]]:
    """The player (profile part) and his statistics blocks from a /players?id&season answer."""
    resp = body.get("response")
    items = [x for x in resp if isinstance(x, dict)] if isinstance(resp, list) else []
    if not items:
        return {}, []
    player = _d(items[0].get("player"))
    blocks = []
    for st in items[0].get("statistics") or []:
        st = _d(st)
        team, league, games = _d(st.get("team")), _d(st.get("league")), _d(st.get("games"))
        goals, cards, subs = _d(st.get("goals")), _d(st.get("cards")), _d(st.get("substitutes"))
        tid, lid = _int(team.get("id")), _int(league.get("id"))
        if tid is None or lid is None:
            continue
        red = _int(cards.get("red"))
        yr = _int(cards.get("yellowred"))
        blocks.append(Block(tid, str(team.get("name")), lid, str(league.get("name")), _int(league.get("season")) or 0,
                            _int(games.get("appearences")), _int(games.get("lineups")), _int(games.get("minutes")),
                            _int(goals.get("total")), _int(goals.get("assists")), _int(cards.get("yellow")),
                            None if red is None and yr is None else (red or 0) + (yr or 0),
                            str(games.get("rating")) if games.get("rating") is not None else None,
                            _int(subs.get("bench"))))
    return player, blocks


OUR_BLOCKS_SQL = """
SELECT t.provider_team_id AS team, t.name AS team_name, c.provider_league_id AS league, c.name AS league_name,
       cs.season, count(*) AS rows,
       count(*) FILTER (WHERE ps.minutes > 0) AS appearances,
       count(*) FILTER (WHERE ps.minutes > 0 AND NOT COALESCE(ps.is_substitute, false)) AS lineups,
       COALESCE(sum(ps.minutes), 0) AS minutes, COALESCE(sum(ps.goals), 0) AS goals,
       COALESCE(sum(ps.assists), 0) AS assists, COALESCE(sum(ps.yellow_cards), 0) AS yellow,
       COALESCE(sum(ps.red_cards), 0) AS red,
       count(*) FILTER (WHERE ps.minutes IS NULL OR ps.minutes = 0) AS bench,
       round(avg(ps.rating) FILTER (WHERE ps.minutes > 0), 3) AS avg_match_rating,
       max(f.kickoff_at) AS last_match
  FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
 WHERE ps.provider_player_id = %(p)s AND cs.season = %(s)s
 GROUP BY 1, 2, 3, 4, 5
"""


def our_blocks(conn: psycopg.Connection[Any], player: int, season: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(OUR_BLOCKS_SQL, {"p": player, "s": season})
        return [dict(r) for r in cur.fetchall()]


MISSING_DETAIL_SQL = """
SELECT count(*) AS finished, count(*) FILTER (WHERE NOT EXISTS (
           SELECT 1 FROM core.fixture_player_stats ps WHERE ps.fixture_id = f.id)) AS without_player_rows
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
 WHERE c.provider_league_id = %(l)s AND cs.season = %(s)s AND t.provider_team_id = %(t)s
   AND f.status_group = 'finished'
"""


def team_detail_gaps(conn: psycopg.Connection[Any], league: int, season: int, team: int) -> dict[str, int]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MISSING_DETAIL_SQL, {"l": league, "s": season, "t": team})
        row = cur.fetchone()
    return {k: int(v) for k, v in (row or {}).items()}


PRODUCT_SQL = """
SELECT count(*)::int AS apps, sum(ps.minutes)::int AS minutes, sum(ps.goals)::int AS goals,
       sum(ps.assists)::int AS assists, round(avg(ps.rating), 2) AS avg_rating, max(f.kickoff_at) AS last_played,
       count(*) FILTER (WHERE ps.minutes IS NULL OR ps.minutes = 0)::int AS bench_rows,
       count(DISTINCT cs.competition_id)::int AS competitions,
       (array_agg(t.name ORDER BY f.kickoff_at DESC))[1] AS team,
       (array_agg(COALESCE(t.is_national, false) ORDER BY f.kickoff_at DESC))[1] AS team_is_national
  FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
 WHERE ps.provider_player_id = %(p)s AND f.kickoff_at > %(since)s
"""


def product_view(conn: psycopg.Connection[Any], player: int, since: datetime) -> dict[str, Any]:
    """What PLAYER_AGG shows on the player list and page (same window and definitions)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PRODUCT_SQL, {"p": player, "since": since})
        row = cur.fetchone()
    return dict(row) if row else {}


@dataclass
class BlockVerdict:
    team: int
    team_name: str
    league: int
    league_name: str
    season: int
    verdict: str
    """ok | ours_missing | provider_behind | stats_mismatch | not_in_db | not_at_provider"""
    api: dict[str, int | None] | None
    ours: dict[str, Any] | None
    differences: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    gaps: dict[str, int] = field(default_factory=dict)
    rating_api: str | None = None
    rating_ours: Any = None


def judge_block(api: Block | None, ours: Mapping[str, Any] | None) -> BlockVerdict:
    if api is not None:
        ref = api
    else:
        assert ours is not None, "a block comes from at least one side"
        ref = Block(int(ours["team"]), str(ours["team_name"]), int(ours["league"]), str(ours["league_name"]),
                    int(ours["season"]), None, None, None, None, None, None, None)
    v = BlockVerdict(ref.team, ref.team_name, ref.league, ref.league_name, ref.season, "ok",
                     {f: api.get(f) for f in (*COUNT_FIELDS, "minutes")} if api else None,
                     dict(ours) if ours else None, rating_api=api.rating if api else None,
                     rating_ours=(ours or {}).get("avg_match_rating"))
    if ours is None:
        v.verdict = "not_in_db" if api and (api.appearances or 0) > 0 else "ok"
        return v
    if api is None:
        v.verdict = "not_at_provider" if int(ours.get("appearances") or 0) > 0 else "ok"
        return v
    for f in COUNT_FIELDS:
        a, b = api.get(f), ours.get(f)
        if (a or 0) != int(b or 0):
            v.differences[f] = (a, b)
    a_min, b_min = api.minutes or 0, int(ours.get("minutes") or 0)
    if abs(a_min - b_min) > MINUTES_SLACK:
        v.differences["minutes"] = (api.minutes, b_min)
    if not v.differences:
        return v
    a_apps, o_apps = api.appearances or 0, int(ours.get("appearances") or 0)
    v.verdict = "ours_missing" if o_apps < a_apps else "provider_behind" if o_apps > a_apps else "stats_mismatch"
    return v


def refine(v: BlockVerdict, *, tracked: set[int], migrated: set[tuple[int, int]]) -> BlockVerdict:
    """Say WHY our side lacks what the provider has, or name a definition difference:

    * the competition is not tracked                         -> untracked (not an issue)
    * tracked, but the season was never migrated             -> season_not_migrated
    * finished matches of his team without any player rows   -> details_missing (backfill)
    * every match has player rows, he is not in some         -> player_rows_missing (provider)
    * only the number of starts differs (by 1-2)             -> starts_definition
    """
    if v.verdict in ("not_in_db", "ours_missing"):
        if v.league not in tracked:
            v.verdict = "untracked"
        elif (v.league, v.season) not in migrated:
            v.verdict = "season_not_migrated"
        elif v.gaps.get("without_player_rows"):
            v.verdict = "details_missing"
        else:
            v.verdict = "player_rows_missing"
    elif v.verdict == "stats_mismatch" and set(v.differences) == {"lineups"}:
        a, b = v.differences["lineups"]
        if a is not None and b is not None and abs(int(a) - int(b)) <= 2:
            v.verdict = "starts_definition"
    return v


def player_evidence(player: int, name: str, verdicts: Sequence[BlockVerdict], product: Mapping[str, Any],
                    current_club: Mapping[str, Any] | None, api_ref: Mapping[str, Any] | None) -> list[Evidence]:
    out = []
    label = f"{name} ({player})"
    for v in verdicts:
        if v.verdict == "ok":
            continue
        key = f"player_stats:{player}:{v.league}:{v.season}:{v.team}"
        diffs = {k: list(x) for k, x in v.differences.items()}
        entity = f"{label} - {v.team_name} in {v.league_name} {v.season}"
        if v.verdict in ("untracked", "season_not_migrated", "starts_definition"):
            continue  # summarised once per run (summary_evidence), not per player
        if v.verdict in ("ours_missing", "not_in_db", "details_missing"):
            out.append(Evidence(key=f"{key}:ours_missing", area="player_stats", issue_type="MISSING_BACKFILL",
                                severity="medium", at_fault="predigol", entity=entity,
                                claim=f"{entity}: the provider counts more appearances than our match rows "
                                      f"({diffs or 'no rows at all'}); finished team matches without any player "
                                      f"rows: {v.gaps.get('without_player_rows', '?')}",
                                api={**(dict(api_ref) if api_ref else {}), "block": v.api},
                                db={"block": v.ours, "detail_gaps": v.gaps},
                                root_cause="per-match player statistics not fetched for some finished fixtures",
                                fix="backfill /fixtures/players for the listed fixtures"))
        elif v.verdict == "provider_behind":
            out.append(Evidence(key=f"{key}:provider_behind", area="player_stats", issue_type="PROVIDER_STALE",
                                severity="low", at_fault="provider", entity=entity,
                                claim=f"{entity}: our match rows have more appearances than the provider's season "
                                      f"figures ({diffs}); its player statistics update several times a week",
                                api={**(dict(api_ref) if api_ref else {}), "block": v.api}, db={"block": v.ours}))
        elif v.verdict == "player_rows_missing":
            out.append(Evidence(key=f"{key}:rows_missing", area="player_stats", issue_type="PLAYER_STATS_MISMATCH",
                                severity="low", at_fault="provider", entity=entity,
                                claim=f"{entity}: every finished match of his team has player rows, yet the provider's "
                                      f"season figures count more appearances ({diffs}) - its per-match players "
                                      "lists omit him where its aggregate counts him",
                                api={**(dict(api_ref) if api_ref else {}), "block": v.api}, db={"block": v.ours}))
        elif v.verdict in ("stats_mismatch", "not_at_provider"):
            out.append(Evidence(key=f"{key}:mismatch", area="player_stats", issue_type="PLAYER_STATS_MISMATCH",
                                severity="medium", at_fault="undetermined", entity=entity,
                                claim=f"{entity}: same appearances, different figures ({diffs})",
                                api={**(dict(api_ref) if api_ref else {}), "block": v.api}, db={"block": v.ours},
                                root_cause="the provider's season aggregate and its per-match rows disagree"))
    if product.get("team_is_national"):
        out.append(Evidence(
            key=f"player_stats:{player}:product_team_label", area="player_stats", issue_type="PRODUCT_SCOPE",
            severity="high", at_fault="predigol", entity=label,
            claim=f"{label}: the product shows '{product.get('team')}' (his last appearance, a national team) as his "
                  f"team; his club is {(current_club or {}).get('name', 'unknown')}",
            db={"product": product}, api={"current_club": current_club},
            root_cause="PLAYER_AGG / PLAYERS_ACTIVE label a player with the team of his last appearance",
            fix="show current_club (squad / career), national_team and last_appearance_team as three fields"))
    return out


def product_evidence(rows: Sequence[Mapping[str, Any]]) -> list[Evidence]:
    """Platform-wide definition bugs seen across the audited players (one entry each)."""
    out = []
    inflated = [r for r in rows if int(r["product"].get("bench_rows") or 0) > 0]
    if inflated:
        ex = [{"player": r["player"], "name": r["name"], "product_apps": r["product"].get("apps"),
               "unused_bench_rows": r["product"].get("bench_rows")} for r in inflated[:8]]
        out.append(Evidence(
            key="player_stats:product:apps_counts_bench", area="player_stats", issue_type="PLAYER_STATS_MISMATCH",
            severity="high", at_fault="predigol", entity="PLAYER_AGG / PLAYERS_ACTIVE / PLAYERS_OF_TEAM",
            claim=f"'Apps' counts every stored match row, including substitutes who never came on: "
                  f"{len(inflated)} of {len(rows)} audited players have such rows",
            db={"examples": ex}, root_cause="count(*) over core.fixture_player_stats; unused substitutes are stored "
                                            "with minutes NULL", fix="appearances = rows with minutes > 0"))
    mixed = [r for r in rows if int(r["product"].get("competitions") or 0) > 1]
    if mixed:
        ex = [{"player": r["player"], "name": r["name"], "competitions": r["product"].get("competitions"),
               "product_apps": r["product"].get("apps")} for r in mixed[:8]]
        out.append(Evidence(
            key="player_stats:product:window_scope", area="player_stats", issue_type="PRODUCT_SCOPE",
            severity="medium", at_fault="predigol", entity="PLAYER_AGG",
            claim=f"The player figures add 400 days of every competition (league, cups, continental, national "
                  f"team): {len(mixed)} of {len(rows)} audited players mix several; the provider's figures are per "
                  "team, league and season",
            db={"examples": ex}, root_cause="aggregation scope: a rolling window with no competition or season",
            fix="per competition and season blocks (the provider's scope), the rolling total labelled as such"))
    return out


def summary_evidence(rows: Sequence[Mapping[str, Any]]) -> list[Evidence]:
    """One entry each for the definitional and scope verdicts across all audited players."""
    tally: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        for b in r["blocks"]:
            if b["verdict"] in ("season_not_migrated", "starts_definition", "untracked"):
                tally.setdefault(b["verdict"], []).append({"player": r["player"], "name": r["name"],
                                                          "league": b["league_name"], "season": b["season"],
                                                          "differences": b["differences"]})
    out = []
    if tally.get("season_not_migrated"):
        items = tally["season_not_migrated"]
        out.append(Evidence(
            key="player_stats:summary:season_not_migrated", area="player_stats", issue_type="SEASON_NOT_MIGRATED",
            severity="low", at_fault="predigol", entity=f"{len(items)} player blocks",
            claim=f"{len(items)} provider blocks belong to tracked competitions whose season was never migrated "
                  "(Friendlies Clubs before the current season, seasons before 2018)",
            api={"examples": items[:8]}, root_cause="historical migration scope",
            fix="migrate those seasons if the product should show them; otherwise say the scope"))
    if tally.get("starts_definition"):
        items = tally["starts_definition"]
        out.append(Evidence(
            key="player_stats:summary:starts_definition", area="player_stats", issue_type="PROVIDER_DEFINED_METRIC",
            severity="info", at_fault="none", entity=f"{len(items)} player blocks",
            claim=f"Starts differ by 1-2 in {len(items)} blocks: the provider's season 'lineups' and its per-match "
                  "substitute flag (which we count) disagree",
            api={"examples": items[:8]}, status="ACCEPTED"))
    return out
