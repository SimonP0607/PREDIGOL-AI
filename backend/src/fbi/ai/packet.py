"""AI_MATCH_PACKET: everything a review may know about a match at one moment - and where each part came from.

``build_packet(conn, fixture_id, at=...)`` reads only what was recorded at or before ``at`` (results
settled by then, prices captured by then, standings snapshots taken by then, absences fetched by
then, evidence retrieved by then) - so a packet built for a past moment is what a reviewer could
really have known, and the reviewer can be backtested on history. The two known exceptions are
stated in the packet itself: a fixture's own attributes (round, venue) are its current values, and
kick-off changes are listed as recorded.

Nothing is estimated to fill a gap: a missing block is named in ``missing`` and left out.

Identical inputs give an identical ``packet_hash`` (canonical JSON, sorted keys; no "age" fields -
ages are computed when the packet is read), so a packet is stored once and every review points at
the exact packet it read.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai import context as ctx
from fbi.ai.pricing import approx_tokens

PACKET_VERSION = "packet-v2"
"""v2 (13 Oct 2026): the ``dossier`` block (``fbi.intel.dossier``): teams in depth, coaches, key players, the
referee, the competitive context, how much the head-to-head is worth."""
CORE_KEYS: tuple[tuple[str, str, Decimal], ...] = (
    ("1X2", "Home", Decimal(0)), ("1X2", "Draw", Decimal(0)), ("1X2", "Away", Decimal(0)),
    ("OU", "Over", Decimal("2.5")), ("OU", "Under", Decimal("2.5")),
    ("BTTS", "Yes", Decimal(0)), ("BTTS", "No", Decimal(0)),
)
MODELS = ("dixon_coles", "poisson", "elo_ologit")
FORM_N = 6
STATS_N = 10
H2H_N = 8
PRICE_LOOKBACK = timedelta(hours=36)
P = 3
"""Decimals kept for a probability in a packet: finer changes are noise to a review and would only make a
new packet (a new row) without a new context."""
OPENING_LOOKBACK = timedelta(days=7)

FIXTURE_SQL = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at, f.round, f.status_short, f.status_group, f.is_neutral,
       f.venue_name, COALESCE(v.city, f.venue_city) AS venue_city, v.country AS venue_country,
       f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name,
       th.provider_team_id AS home_provider_id, ta.provider_team_id AS away_provider_id,
       th.country AS home_country, ta.country AS away_country,
       vh.city AS home_base_city, vh.country AS home_base_country, va.city AS away_base_city,
       va.country AS away_base_country,
       c.id AS competition_id, c.name AS competition, c.country AS competition_country, c.type AS competition_type,
       c.competition_type AS competition_kind, c.tier AS competition_tier, c.provider_league_id,
       cs.id AS season_id, cs.season
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.venues v ON v.id = f.venue_id
  LEFT JOIN core.venues vh ON vh.id = th.venue_id
  LEFT JOIN core.venues va ON va.id = ta.venue_id
 WHERE f.id = %(fixture)s
"""

FACTS_SQL = """
SELECT referee, observed_at FROM core.fixture_facts_latest WHERE fixture_id = %(fixture)s AND observed_at <= %(at)s
"""

KICKOFF_CHANGES_SQL = """
SELECT observed_at, before_kickoff, after_kickoff FROM core.fixture_kickoff_changes
 WHERE fixture_id = %(fixture)s AND observed_at <= %(at)s ORDER BY observed_at
"""

STANDINGS_SQL = """
SELECT DISTINCT ON (st.team_id, st.group_key)
       st.team_id, st.group_key, st.rank, st.points, st.played, st.goals_diff, st.form, st.description,
       st.snapshot_at, st.home_played, st.home_wins, st.home_draws, st.home_losses, st.away_played, st.away_wins,
       st.away_draws, st.away_losses
  FROM core.standings st
 WHERE st.competition_season_id = %(season)s AND st.snapshot_at <= %(at)s
 ORDER BY st.team_id, st.group_key, st.snapshot_at DESC
"""

REMAINING_SQL = """
SELECT count(*) FROM core.fixtures f
 WHERE f.competition_season_id = %(season)s AND (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
   AND f.kickoff_at >= %(kickoff)s AND f.status_group IN ('scheduled', 'live')
"""

PAST_SQL = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, r.reg_goals_home, r.reg_goals_away, c.name AS competition
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at < %(kickoff)s
   AND f.kickoff_at >= %(kickoff)s - interval '400 days'
   AND r.settled_at <= %(at)s AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
 ORDER BY f.kickoff_at DESC
 LIMIT %(limit)s
"""

H2H_SQL = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, r.reg_goals_home, r.reg_goals_away
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE ((f.home_team_id = %(a)s AND f.away_team_id = %(b)s) OR (f.home_team_id = %(b)s AND f.away_team_id = %(a)s))
   AND f.kickoff_at < %(kickoff)s AND r.settled_at <= %(at)s AND r.reg_goals_home IS NOT NULL
 ORDER BY f.kickoff_at DESC LIMIT %(limit)s
"""

PREVIOUS_SQL = """
SELECT max(f.kickoff_at) AS previous,
       count(*) FILTER (WHERE f.kickoff_at >= %(kickoff)s - interval '14 days') AS last_14d
  FROM core.fixtures f
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at < %(kickoff)s
   AND f.kickoff_at >= %(kickoff)s - interval '60 days' AND f.status_group = 'finished'
"""

NEXT_SQL = """
SELECT f.kickoff_at, c.name AS competition, c.type AS competition_type
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at > %(kickoff)s
   AND f.kickoff_at <= %(kickoff)s + interval '7 days' AND f.created_at <= %(at)s
 ORDER BY f.kickoff_at LIMIT 1
"""

ELO_RUN_SQL = """
WITH RECURSIVE runs AS (
    (SELECT elo_version, run_id, computed_at FROM features.elo_ratings ORDER BY elo_version DESC, run_id DESC LIMIT 1)
    UNION ALL
    SELECT nxt.elo_version, nxt.run_id, nxt.computed_at FROM runs, LATERAL (
        SELECT e.elo_version, e.run_id, e.computed_at FROM features.elo_ratings e
         WHERE (e.elo_version, e.run_id) < (runs.elo_version, runs.run_id)
         ORDER BY e.elo_version DESC, e.run_id DESC LIMIT 1) nxt
)
SELECT elo_version, run_id FROM runs WHERE computed_at <= %(at)s LIMIT 1
"""
"""Runs are whole recomputations (one computed_at each): walk them newest first on the primary key
instead of scanning half a million rows for the newest computed_at."""

ELO_SQL = """
SELECT DISTINCT ON (team_id) team_id, fixture_id, kickoff_at, rating_before, rating_after
  FROM features.elo_ratings
 WHERE elo_version = %(version)s AND run_id = %(run)s AND team_id = ANY(%(teams)s) AND kickoff_at <= %(kickoff)s
 ORDER BY team_id, kickoff_at DESC
"""

TEAM_STATS_SQL = """
WITH past AS (
    SELECT f.id, CASE WHEN f.home_team_id = %(team)s THEN 'home' ELSE 'away' END AS side
      FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at < %(kickoff)s
       AND f.kickoff_at >= %(kickoff)s - interval '400 days' AND r.settled_at <= %(at)s
     ORDER BY f.kickoff_at DESC LIMIT %(limit)s
), stats AS (
    SELECT DISTINCT ON (s.fixture_id, s.team_side) s.fixture_id, s.team_side, s.shots, s.shots_on_target,
           s.expected_goals, s.possession_pct, s.corners
      FROM core.fixture_team_stats s JOIN past ON past.id = s.fixture_id
     WHERE s.fetched_at <= %(at)s
     ORDER BY s.fixture_id, s.team_side, (s.source = 'api-football') DESC, s.fetched_at DESC
)
SELECT count(DISTINCT p.id) FILTER (WHERE own.fixture_id IS NOT NULL) AS n,
       avg(own.shots) AS shots, avg(own.shots_on_target) AS sot, avg(own.expected_goals) AS xg,
       count(own.expected_goals) AS n_xg, avg(own.possession_pct) AS possession, avg(own.corners) AS corners,
       avg(opp.shots) AS shots_against, avg(opp.shots_on_target) AS sot_against, avg(opp.expected_goals) AS xg_against
  FROM past p
  LEFT JOIN stats own ON own.fixture_id = p.id AND own.team_side = p.side
  LEFT JOIN stats opp ON opp.fixture_id = p.id AND opp.team_side <> p.side
"""

ABSENCES_SQL = """
SELECT a.provider_team_id, a.provider_player_id, a.player_name, a.absence_type, a.reason, a.fetched_at, a.payload_hash
  FROM core.player_absences a
 WHERE a.fixture_id = %(fixture)s AND a.fetched_at <= %(at)s
 ORDER BY a.provider_team_id, a.player_name
"""

ABSENCE_CHECK_SQL = """
SELECT max(checked_at) AS checked_at FROM core.context_checks
 WHERE competition_season_id = %(season)s AND dataset = 'injuries' AND checked_at <= %(at)s
"""

SQUAD_STATS_SQL = """
WITH squad AS (
    SELECT DISTINCT s.provider_player_id FROM core.player_season_stats s
     WHERE s.provider_team_id = %(provider_team)s AND s.season = %(season)s AND s.provider_league_id = %(league)s
       AND s.observed_at <= %(at)s
    UNION
    SELECT m.provider_player_id FROM core.squad_members m WHERE m.team_id = %(team)s
), latest AS (
    SELECT DISTINCT ON (s.provider_player_id, s.provider_league_id)
           s.provider_player_id, s.provider_league_id, s.minutes, s.appearances, s.goals, s.assists, s.rating,
           s.position
      FROM core.player_season_stats s JOIN squad q ON q.provider_player_id = s.provider_player_id
     WHERE s.provider_team_id = %(provider_team)s AND s.season = %(season)s AND s.observed_at <= %(at)s
     ORDER BY s.provider_player_id, s.provider_league_id, s.observed_at DESC
)
SELECT l.provider_player_id, max(p.name) AS name, max(COALESCE(l.position, p.position)) AS position,
       sum(COALESCE(l.minutes, 0))::int AS minutes, sum(COALESCE(l.appearances, 0))::int AS appearances,
       sum(COALESCE(l.goals, 0))::int AS goals, sum(COALESCE(l.assists, 0))::int AS assists,
       avg(l.rating) AS rating
  FROM latest l LEFT JOIN core.players p ON p.provider_player_id = l.provider_player_id
 GROUP BY l.provider_player_id
"""

LINEUPS_SQL = """
SELECT l.team_side, l.formation, l.coach_name, l.fetched_at, l.payload_hash,
       array_agg(lp.provider_player_id ORDER BY lp.provider_player_id) FILTER (WHERE lp.is_starter) AS starters
  FROM core.fixture_lineups l
  LEFT JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side
       AND lp.source = l.source
 WHERE l.fixture_id = %(fixture)s AND l.fetched_at <= %(at)s
 GROUP BY l.team_side, l.formation, l.coach_name, l.fetched_at, l.payload_hash
"""

CONSENSUS_SQL = """
SELECT DISTINCT ON (m.market_key, m.selection, m.line)
       m.market_key, m.selection, m.line, m.p_fair, m.best_odds, b.name AS bookmaker, m.n_bookmakers, m.overround,
       m.dispersion, m.as_of
  FROM market.market_consensus m LEFT JOIN market.bookmakers b ON b.id = m.best_bookmaker_id
 WHERE m.fixture_id = %(fixture)s AND m.devig_method = 'shin' AND m.as_of <= %(at)s AND m.as_of >= %(since)s
 ORDER BY m.market_key, m.selection, m.line, m.as_of DESC
"""

OPENING_SQL = """
SELECT DISTINCT ON (m.market_key, m.selection, m.line) m.market_key, m.selection, m.line, m.p_fair, m.as_of
  FROM market.market_consensus m
 WHERE m.fixture_id = %(fixture)s AND m.devig_method = 'shin' AND m.as_of <= %(at)s AND m.as_of >= %(since)s
 ORDER BY m.market_key, m.selection, m.line, m.as_of
"""

PREDICTIONS_SQL = """
WITH newest AS (
    SELECT DISTINCT ON (r.name) r.name AS model, p.model_version_id, p.data_cutoff_ts
      FROM models.predictions p JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry r ON r.id = v.model_id
     WHERE p.fixture_id = %(fixture)s AND p.backtest_session_id IS NULL AND p.data_cutoff_ts <= %(at)s
       AND r.name = ANY(%(models)s)
     ORDER BY r.name, p.data_cutoff_ts DESC, p.model_version_id DESC
)
SELECT n.model, p.model_version_id, p.data_cutoff_ts, p.market_key, p.selection, p.line, p.p_calibrated, p.p_lo,
       p.p_hi, p.p_push
  FROM models.predictions p JOIN newest n ON n.model_version_id = p.model_version_id
       AND n.data_cutoff_ts = p.data_cutoff_ts
 WHERE p.fixture_id = %(fixture)s AND p.backtest_session_id IS NULL
"""

QUALITY_SQL = """
SELECT (SELECT jsonb_build_object('class', s.class, 'score', s.score, 'computed_at', s.computed_at)
          FROM analytics.competition_data_scores s
         WHERE s.competition_season_id = %(season)s AND s.computed_at <= %(at)s
         ORDER BY s.computed_at DESC LIMIT 1) AS competition_score,
       (SELECT jsonb_build_object('state', v.state, 'validated_at', v.validated_at)
          FROM analytics.fixture_validation v WHERE v.fixture_id = %(fixture)s) AS fixture_validation
"""

EVIDENCE_SQL = """
SELECT e.id, e.kind, e.claim, e.team_id, e.provider_player_id, e.status, e.origin, e.source_tier, e.source_name,
       e.source_url, e.published_at, e.retrieved_at, e.confidence, e.relevance, e.attributes
  FROM ai.evidence e
 WHERE (e.fixture_id = %(fixture)s OR (e.fixture_id IS NULL AND e.team_id = ANY(%(teams)s)))
   AND e.retrieved_at <= %(at)s AND e.status <> 'OUTDATED'
 ORDER BY e.relevance DESC, e.retrieved_at DESC, e.id
 LIMIT 40
"""


@dataclass
class Packet:
    fixture_id: int
    as_of: datetime
    content: dict[str, Any]
    sources: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    version: str = PACKET_VERSION

    @property
    def hash(self) -> str:
        return content_hash({"v": self.version, "content": self.content, "missing": sorted(self.missing)})

    @property
    def approx_tokens(self) -> int:
        return approx_tokens(canonical(self.content))


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=False)


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    return str(o)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _f(x: Any, places: int = 4) -> float | None:
    return None if x is None else round(float(x), places)


def _ts(x: datetime | None) -> str | None:
    return None if x is None else x.isoformat()


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _row(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


class PacketBuilder:
    """Builds packets for many fixtures with the per-run lookups (the Elo run) done once."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn
        self._elo_run: dict[datetime, tuple[str, int] | None] = {}

    def _elo_version(self, at: datetime) -> tuple[str, int] | None:
        key = at.replace(minute=0, second=0, microsecond=0)
        if key not in self._elo_run:
            row = _row(self.conn, ELO_RUN_SQL, {"at": at})
            self._elo_run[key] = None if row is None else (str(row["elo_version"]), int(row["run_id"]))
        return self._elo_run[key]

    # ── the blocks ──────────────────────────────────────────────────────────
    def build(self, fixture_id: int, *, at: datetime, extra_keys: list[tuple[str, str, Decimal]] | None = None
              ) -> Packet | None:
        conn = self.conn
        f = _row(conn, FIXTURE_SQL, {"fixture": fixture_id})
        if f is None:
            return None
        kickoff: datetime = f["kickoff_at"]
        home, away = int(f["home_team_id"]), int(f["away_team_id"])
        sources: list[dict[str, Any]] = [{"block": "fixture", "table": "core.fixtures", "note": "current values"}]
        missing: list[str] = []
        content: dict[str, Any] = {}

        facts = _row(conn, FACTS_SQL, {"fixture": fixture_id, "at": at})
        changes = _rows(conn, KICKOFF_CHANGES_SQL, {"fixture": fixture_id, "at": at})
        content["fixture"] = {
            "id": fixture_id, "provider_fixture_id": f["provider_fixture_id"], "kickoff_at": _ts(kickoff),
            "competition": f["competition"], "competition_country": f["competition_country"],
            "competition_type": f["competition_type"], "competition_tier": f["competition_tier"],
            "season": f["season"], "round": f["round"], "stage": ctx.round_stage(f["round"]),
            "venue": f["venue_name"], "venue_city": f["venue_city"], "venue_country": f["venue_country"],
            "neutral": bool(f["is_neutral"]), "status": f["status_short"],
            "referee": facts["referee"] if facts else None,
            "home": {"id": home, "name": f["home_name"], "country": f["home_country"]},
            "away": {"id": away, "name": f["away_name"], "country": f["away_country"]},
            "kickoff_changes": [{"observed_at": _ts(c["observed_at"]), "before": _ts(c["before_kickoff"]),
                                 "after": _ts(c["after_kickoff"])} for c in changes],
        }
        if changes:
            sources.append({"block": "fixture.kickoff_changes", "table": "core.fixture_kickoff_changes",
                            "as_of": _ts(changes[-1]["observed_at"])})

        content["standings"], content["stakes"] = self._standings(f, at, sources, missing)
        content["form"] = {}
        content["schedule"] = {}
        for side, team in (("home", home), ("away", away)):
            past = _rows(conn, PAST_SQL, {"team": team, "kickoff": kickoff, "at": at, "limit": FORM_N})
            content["form"][side] = ctx.form(team, [ctx.PastMatch(r["kickoff_at"], r["home_team_id"], r["away_team_id"],
                                                                   int(r["reg_goals_home"]), int(r["reg_goals_away"]))
                                                     for r in past])
            prev = _row(conn, PREVIOUS_SQL, {"team": team, "kickoff": kickoff})
            nxt = _row(conn, NEXT_SQL, {"team": team, "kickoff": kickoff, "at": at})
            content["schedule"][side] = {
                "previous_kickoff": _ts(prev["previous"]) if prev else None,
                "rest_days": ctx.rest_days(kickoff, prev["previous"]) if prev else None,
                "matches_last_14d": int(prev["last_14d"]) if prev else 0,
                "next_match": None if nxt is None else {
                    "kickoff_at": _ts(nxt["kickoff_at"]), "competition": nxt["competition"],
                    "days_after": round((nxt["kickoff_at"] - kickoff).total_seconds() / 86400, 1)},
            }
        if not content["form"]["home"].get("n") and not content["form"]["away"].get("n"):
            missing.append("form")
        else:
            sources.append({"block": "form", "table": "core.fixture_results", "as_of": _ts(at)})
        content["schedule"]["flags"] = ctx.rest_flags(content["schedule"]["home"]["rest_days"],
                                                      content["schedule"]["away"]["rest_days"])

        h2h = _rows(conn, H2H_SQL, {"a": home, "b": away, "kickoff": kickoff, "at": at, "limit": H2H_N})
        content["h2h"] = {"n": len(h2h), "home_view": ctx.form(home, [
            ctx.PastMatch(r["kickoff_at"], r["home_team_id"], r["away_team_id"], int(r["reg_goals_home"]),
                          int(r["reg_goals_away"])) for r in h2h])}
        if not h2h:
            missing.append("h2h")

        content["elo"] = self._elo(f, at, sources, missing)
        from fbi.intel.dossier import VERSION as DOSSIER_VERSION
        from fbi.intel.dossier import build_dossier, finite

        try:  # in a savepoint: a dossier that cannot be read never costs the rest of the packet
            with conn.transaction():
                content["dossier"] = finite(build_dossier(
                    conn, f, at=at, elo=self._elo_version(at), referee=facts["referee"] if facts else None,
                    h2h_n=len(h2h), h2h_last=h2h[0]["kickoff_at"] if h2h else None))
            sources.append({"block": "dossier", "tables": ["core.fixture_team_stats", "core.fixture_events",
                                                           "core.fixture_lineups", "core.fixture_player_stats",
                                                           "core.fixture_facts", "features.elo_ratings"],
                            "as_of": _ts(at), "version": DOSSIER_VERSION})
        except psycopg.Error as exc:
            content["dossier"] = {"version": DOSSIER_VERSION, "error": type(exc).__name__}
            missing.append("dossier")
        content["stats"] = {}
        for side, team in (("home", home), ("away", away)):
            s = _row(conn, TEAM_STATS_SQL, {"team": team, "kickoff": kickoff, "at": at, "limit": STATS_N}) or {}
            content["stats"][side] = {k: _f(v, 2) for k, v in s.items() if k not in ("n", "n_xg")} | \
                {"n": int(s.get("n") or 0), "n_xg": int(s.get("n_xg") or 0)}
        if not any(content["stats"][s]["n"] for s in ("home", "away")):
            missing.append("stats")
        else:
            sources.append({"block": "stats", "table": "core.fixture_team_stats", "as_of": _ts(at)})

        content["absences"] = self._absences(f, at, sources, missing)
        content["lineups"] = self._lineups(fixture_id, at, sources, missing)
        content["travel"] = ctx.travel(f["venue_city"], f["venue_country"], f["away_base_city"],
                                       f["away_base_country"], neutral=bool(f["is_neutral"]))
        content["market"] = self._market(fixture_id, at, extra_keys or [], sources, missing, kickoff=kickoff)
        content["models"] = self._models(fixture_id, at, content["market"], extra_keys or [], sources, missing)
        quality = self._quality(f, at, content, sources)
        content["quality"] = quality
        content["evidence"] = self._evidence(fixture_id, home, away, at, sources)
        return Packet(fixture_id, at, content, sources, sorted(set(missing)), quality)

    def _standings(self, f: dict[str, Any], at: datetime, sources: list[dict[str, Any]], missing: list[str]
                   ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        rows = _rows(self.conn, STANDINGS_SQL, {"season": f["season_id"], "at": at})
        home, away = int(f["home_team_id"]), int(f["away_team_id"])
        mine = {int(r["team_id"]): r for r in rows if int(r["team_id"]) in (home, away)}
        if not mine:
            missing.append("standings")
            return None, None
        out: dict[str, Any] = {}
        stakes: dict[str, Any] = {}
        snapshot = max(r["snapshot_at"] for r in mine.values())
        for side, team in (("home", home), ("away", away)):
            r = mine.get(team)
            if r is None:
                continue
            group = r["group_key"]
            table = [ctx.TableRow(int(x["team_id"]), int(x["rank"]), int(x["points"] or 0), int(x["played"] or 0),
                                  x["description"]) for x in rows if x["group_key"] == group]
            remaining_row = _row(self.conn, REMAINING_SQL, {"season": f["season_id"], "team": team,
                                                            "kickoff": f["kickoff_at"]})
            remaining = int(remaining_row["count"]) if remaining_row else None
            st = ctx.stakes(table, team, remaining)
            out[side] = {"rank": r["rank"], "points": r["points"], "played": r["played"], "goals_diff": r["goals_diff"],
                         "form": r["form"], "description": r["description"], "group": group, "teams": len(table),
                         "home_record": [r["home_wins"], r["home_draws"], r["home_losses"]],
                         "away_record": [r["away_wins"], r["away_draws"], r["away_losses"]]}
            stakes[side] = None if st is None else st.as_json()
        sources.append({"block": "standings", "table": "core.standings", "as_of": _ts(snapshot)})
        return out, stakes

    def _elo(self, f: dict[str, Any], at: datetime, sources: list[dict[str, Any]], missing: list[str]
             ) -> dict[str, Any] | None:
        run = self._elo_version(at)
        if run is None:
            missing.append("elo")
            return None
        rows = _rows(self.conn, ELO_SQL, {"version": run[0], "run": run[1], "teams": [f["home_team_id"],
                                                                                          f["away_team_id"]],
                                          "kickoff": f["kickoff_at"]})
        by_team = {int(r["team_id"]): r for r in rows}
        out: dict[str, Any] = {"version": run[0]}
        for side, team in (("home", f["home_team_id"]), ("away", f["away_team_id"])):
            r = by_team.get(int(team))
            if r is None:
                out[side] = None
                continue
            rating = r["rating_before"] if r["fixture_id"] == f["id"] else r["rating_after"]
            out[side] = _f(rating, 1)
        if out.get("home") is None or out.get("away") is None:
            missing.append("elo")
        else:
            out["diff"] = round(out["home"] - out["away"], 1)
            sources.append({"block": "elo", "table": "features.elo_ratings", "version": run[0], "run_id": run[1]})
        return out

    def _absences(self, f: dict[str, Any], at: datetime, sources: list[dict[str, Any]], missing: list[str]
                  ) -> dict[str, Any]:
        rows = _rows(self.conn, ABSENCES_SQL, {"fixture": f["id"], "at": at})
        check = _row(self.conn, ABSENCE_CHECK_SQL, {"season": f["season_id"], "at": at})
        checked = None if check is None else check.get("checked_at")
        out: dict[str, Any] = {"checked": checked is not None}
        for side, team, provider_team in (("home", f["home_team_id"], f["home_provider_id"]),
                                          ("away", f["away_team_id"], f["away_provider_id"])):
            players = [ctx.PlayerSeason(int(r["provider_player_id"]), r["name"], r["position"], int(r["minutes"] or 0),
                                        int(r["appearances"] or 0), int(r["goals"] or 0), int(r["assists"] or 0),
                                        None if r["rating"] is None else float(r["rating"]))
                       for r in _rows(self.conn, SQUAD_STATS_SQL, {"provider_team": provider_team, "team": team,
                                                                   "season": f["season"], "league": f["provider_league_id"],
                                                                   "at": at})]
            weights = ctx.importance(players)
            listed = []
            for r in rows:
                if r["provider_team_id"] != provider_team:
                    continue
                info = weights.get(int(r["provider_player_id"]))
                listed.append({"player_id": r["provider_player_id"], "name": r["player_name"], "type": r["absence_type"],
                               "reason": r["reason"],
                               "key": bool(info and info["key"]), "first_choice_gk": bool(info and info["first_choice_gk"]),
                               "minutes_share": info["minutes_share"] if info else None,
                               "ga_share": info["ga_share"] if info else None,
                               "weight": ctx.absence_weight(info, r["absence_type"])})
            listed.sort(key=lambda x: -x["weight"])
            out[side] = {"players": listed, "weight": round(sum(x["weight"] for x in listed), 3),
                         "key_out": sum(1 for x in listed if x["key"] and not str(x["type"] or "").startswith("Quest")),
                         "squad_known": len(players)}
        if rows or checked:
            sources.append({"block": "absences", "table": "core.player_absences",
                            "as_of": _ts(max(r["fetched_at"] for r in rows)) if rows else None,
                            "checked_at": _ts(checked),
                            "payload_hashes": sorted({r["payload_hash"] for r in rows})[:5]})
        if not checked and not rows:
            missing.append("absences")
        return out

    def _lineups(self, fixture_id: int, at: datetime, sources: list[dict[str, Any]], missing: list[str]
                 ) -> dict[str, Any]:
        rows = _rows(self.conn, LINEUPS_SQL, {"fixture": fixture_id, "at": at})
        if not rows:
            missing.append("lineups")
            return {"confirmed": False}
        out: dict[str, Any] = {"confirmed": True}
        for r in rows:
            out[r["team_side"]] = {"formation": r["formation"], "coach": r["coach_name"],
                                   "starters": [int(x) for x in (r["starters"] or [])]}
        sources.append({"block": "lineups", "table": "core.fixture_lineups",
                        "as_of": _ts(max(r["fetched_at"] for r in rows)),
                        "payload_hashes": sorted({r["payload_hash"] for r in rows if r["payload_hash"]})})
        return out

    def _market(self, fixture_id: int, at: datetime, extra: list[tuple[str, str, Decimal]],
                sources: list[dict[str, Any]], missing: list[str], *, kickoff: datetime) -> dict[str, Any]:
        wanted = {(m, s, Decimal(str(line))) for m, s, line in (*CORE_KEYS, *extra)}
        rows = _rows(self.conn, CONSENSUS_SQL, {"fixture": fixture_id, "at": at, "since": at - PRICE_LOOKBACK})
        # the opening is the first consensus in the week before kick-off: a fixed reference, not a sliding one
        opening = {(r["market_key"], r["selection"], Decimal(r["line"])): r for r in
                   _rows(self.conn, OPENING_SQL, {"fixture": fixture_id, "at": at,
                                                  "since": kickoff - OPENING_LOOKBACK})}
        out: dict[str, Any] = {"selections": []}
        latest: datetime | None = None
        for r in rows:
            key = (r["market_key"], r["selection"], Decimal(r["line"]))
            if key not in wanted:
                continue
            o = opening.get(key)
            out["selections"].append({
                "market": key[0], "selection": key[1], "line": str(key[2]), "p_fair": _f(r["p_fair"], P),
                "best_odds": _f(r["best_odds"], 2), "bookmaker": r["bookmaker"], "n_bookmakers": r["n_bookmakers"],
                "overround": _f(r["overround"], P), "dispersion": _f(r["dispersion"], P),
                "opening_p_fair": _f(o["p_fair"], P) if o else None, "opening_as_of": _ts(o["as_of"]) if o else None,
                "movement": (ctx.movement(_f(o["p_fair"], P), _f(r["p_fair"], P))
                             if o and o["as_of"] < r["as_of"] else None),
            })
            latest = r["as_of"] if latest is None or r["as_of"] > latest else latest
        out["selections"].sort(key=lambda s: (s["market"], s["line"], s["selection"]))
        out["observed"] = bool(out["selections"])
        if not out["selections"]:
            missing.append("market")
        else:
            sources.append({"block": "market", "table": "market.market_consensus", "method": "shin",
                            "as_of": _ts(latest)})
        return out

    def _models(self, fixture_id: int, at: datetime, market: dict[str, Any], extra: list[tuple[str, str, Decimal]],
                sources: list[dict[str, Any]], missing: list[str]) -> dict[str, Any]:
        wanted = {(m, s, Decimal(str(line))) for m, s, line in (*CORE_KEYS, *extra)}
        fair = {(s["market"], s["selection"], Decimal(s["line"])): s["p_fair"] for s in market.get("selections", [])}
        rows = _rows(self.conn, PREDICTIONS_SQL, {"fixture": fixture_id, "at": at, "models": list(MODELS)})
        out: dict[str, Any] = {}
        cutoffs: dict[str, str | None] = {}
        versions: dict[str, int] = {}
        for r in rows:
            key = (r["market_key"], r["selection"], Decimal(r["line"]))
            if key not in wanted:
                continue
            p = _f(r["p_calibrated"], P)
            entry = {"market": key[0], "selection": key[1], "line": str(key[2]), "p": p, "p_lo": _f(r["p_lo"], P),
                     "p_hi": _f(r["p_hi"], P), "p_push": _f(r["p_push"], P),
                     "fair_odds": None if not p else round(1 / p, 2)}
            pf = fair.get(key)
            if p is not None and pf is not None:
                entry["edge_vs_market"] = round(p - pf, P)
            model = out.setdefault(r["model"], {"selections": []})
            cutoffs[r["model"]] = _ts(r["data_cutoff_ts"])
            versions[r["model"]] = r["model_version_id"]
            model["selections"].append(entry)
        for m in out.values():
            m["selections"].sort(key=lambda s: (s["market"], s["line"], s["selection"]))
        if not out:
            missing.append("models")
        else:
            # the version and the cut-off are provenance: a refit that gives the same numbers is the same context
            sources.append({"block": "models", "table": "models.predictions", "versions": dict(sorted(versions.items())),
                            "data_cutoff_ts": dict(sorted(cutoffs.items()))})
        return out

    def _quality(self, f: dict[str, Any], at: datetime, content: dict[str, Any], sources: list[dict[str, Any]]
                 ) -> dict[str, Any]:
        q = _row(self.conn, QUALITY_SQL, {"season": f["season_id"], "fixture": f["id"], "at": at}) or {}
        out = {"competition_score": q.get("competition_score"), "fixture_validation": q.get("fixture_validation"),
               "lineups_confirmed": bool(content["lineups"].get("confirmed"))}
        sources.append({"block": "quality", "table": "analytics.competition_data_scores"})
        return out

    def _evidence(self, fixture_id: int, home: int, away: int, at: datetime, sources: list[dict[str, Any]]
                  ) -> list[dict[str, Any]]:
        rows = _rows(self.conn, EVIDENCE_SQL, {"fixture": fixture_id, "teams": [home, away], "at": at})
        out = [{"id": int(r["id"]), "kind": r["kind"], "claim": r["claim"],
                "side": "home" if r["team_id"] == home else "away" if r["team_id"] == away else None,
                "player_id": r["provider_player_id"], "status": r["status"], "origin": r["origin"], "tier": r["source_tier"],
                "source": r["source_name"], "url": r["source_url"], "published_at": _ts(r["published_at"]),
                "retrieved_at": _ts(r["retrieved_at"]), "confidence": _f(r["confidence"], 3),
                "relevance": _f(r["relevance"], 3)} for r in rows]
        if out:
            sources.append({"block": "evidence", "table": "ai.evidence", "ids": [e["id"] for e in out]})
        return out


def build_packet(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime,
                 extra_keys: list[tuple[str, str, Decimal]] | None = None) -> Packet | None:
    return PacketBuilder(conn).build(fixture_id, at=at, extra_keys=extra_keys)


NEWEST_PACKET_SQL = ("SELECT id, packet_hash FROM ai.match_packets WHERE fixture_id = %s "
                     "ORDER BY as_of DESC, id DESC LIMIT 1")


def store_packet(conn: psycopg.Connection[Any], packet: Packet, *, built_at: datetime) -> int:
    """The packet's row id: the newest stored one when its content is the same, a new row otherwise (so the
    newest row is always the current context, even when an earlier content comes back)."""
    h = packet.hash
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(NEWEST_PACKET_SQL, (packet.fixture_id,))
        newest = cur.fetchone()
        if newest is not None and newest[1] == h:
            return int(newest[0])
        cur.execute(
            "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, sources, "
            "missing, quality, approx_tokens) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (packet.fixture_id, packet.version, packet.as_of, max(built_at, packet.as_of), h, Jsonb(_jsonable(packet.content)),
             Jsonb(_jsonable(packet.sources)), packet.missing, Jsonb(_jsonable(packet.quality)), packet.approx_tokens))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _jsonable(value: Any) -> Any:
    return json.loads(canonical(value))
