"""Truth checks that need no provider request: the database against itself.

Each check is one query whose rows are the contradictions, with the total count
carried on every row (``count(*) OVER ()``) so a check that finds ten thousand of
something reports ten thousand and keeps a few hundred examples. They run in a
read-only transaction; nothing here writes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.findings import FINDINGS_KEPT_PER_KIND, Finding, Kind, Severity, Tally

GROUP_OF_SQL = """CASE upper({col})
    WHEN 'TBD' THEN 'scheduled' WHEN 'NS' THEN 'scheduled'
    WHEN '1H' THEN 'live' WHEN 'HT' THEN 'live' WHEN '2H' THEN 'live' WHEN 'ET' THEN 'live'
    WHEN 'BT' THEN 'live' WHEN 'P' THEN 'live' WHEN 'LIVE' THEN 'live' WHEN 'INT' THEN 'live'
    WHEN 'FT' THEN 'finished' WHEN 'AET' THEN 'finished' WHEN 'PEN' THEN 'finished'
    WHEN 'SUSP' THEN 'postponed' WHEN 'PST' THEN 'postponed'
    WHEN 'CANC' THEN 'cancelled' WHEN 'ABD' THEN 'cancelled' WHEN 'AWD' THEN 'cancelled'
    WHEN 'WO' THEN 'cancelled' END"""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    dataset: str
    field: str
    kind: Kind
    severity: Severity
    sql: str
    describe: Callable[[Mapping[str, Any]], tuple[str, Any, Any, str]]
    """row -> (entity, api-or-expected, db, note)."""
    checked_sql: str | None = None
    """How many rows the check looked at, for the 'checked' column."""


def _fx(r: Mapping[str, Any]) -> str:
    return f"fixture {r['provider_fixture_id']} ({r.get('competition')} {r.get('season')})"


CHECKS: tuple[Check, ...] = (
    Check(
        "status_spelling", "fixtures", "status_short", Kind.INCONSISTENT, Severity.HIGH,
        """SELECT f.provider_fixture_id, f.status_short, f.status_group, c.name AS competition, cs.season,
                  count(*) OVER () AS n_total
             FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE f.status_short <> upper(f.status_short)""",
        lambda r: (_fx(r), r["status_short"].upper(), r["status_short"],
                   "stored in the provider's mixed-case spelling"),
        "SELECT count(*) FROM core.fixtures",
    ),
    Check(
        "status_group", "fixtures", "status_group", Kind.INCONSISTENT, Severity.HIGH,
        f"""SELECT f.provider_fixture_id, f.status_short, f.status_group, {GROUP_OF_SQL.format(col='f.status_short')}
                   AS expected, c.name AS competition, cs.season, count(*) OVER () AS n_total
              FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
             WHERE {GROUP_OF_SQL.format(col='f.status_short')} IS DISTINCT FROM f.status_group""",
        lambda r: (_fx(r), r["expected"], f"{r['status_short']} -> {r['status_group']}",
                   "the group does not follow from the status"),
    ),
    Check(
        "finished_without_result", "results", "result", Kind.MISSING_IN_DB, Severity.HIGH,
        """SELECT f.provider_fixture_id, f.status_short, f.kickoff_at, c.name AS competition, cs.season,
                  count(*) OVER () AS n_total
             FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE f.status_group = 'finished'
              AND NOT EXISTS (SELECT 1 FROM core.fixture_results r WHERE r.fixture_id = f.id)
            ORDER BY f.kickoff_at DESC""",
        lambda r: (_fx(r), f"{r['status_short']}: a score", "no result row",
                   "finished, but nothing to settle or train on (often an extra-time match whose 90-minute "
                   "score the provider never stated)"),
        "SELECT count(*) FROM core.fixtures WHERE status_group = 'finished'",
    ),
    Check(
        "result_without_finish", "results", "result", Kind.INCONSISTENT, Severity.CRITICAL,
        """SELECT f.provider_fixture_id, f.status_short, r.goals_home, r.goals_away, c.name AS competition,
                  cs.season, count(*) OVER () AS n_total
             FROM core.fixture_results r JOIN core.fixtures f ON f.id = r.fixture_id
             JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE f.status_group <> 'finished'""",
        lambda r: (_fx(r), "no result (not finished)", f"{r['goals_home']}-{r['goals_away']} with {r['status_short']}",
                   "a score stored for a match not recorded as finished"),
        "SELECT count(*) FROM core.fixture_results",
    ),
    Check(
        "result_parts", "results", "score parts", Kind.INCONSISTENT, Severity.MEDIUM,
        """SELECT f.provider_fixture_id, f.status_short, r.goals_home, r.goals_away, r.ft_goals_home,
                  r.ft_goals_away, r.et_goals_home, r.et_goals_away, c.name AS competition, cs.season,
                  count(*) OVER () AS n_total
             FROM core.fixture_results r JOIN core.fixtures f ON f.id = r.fixture_id
             JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE (r.ft_goals_home IS NOT NULL AND (r.ft_goals_home > r.goals_home OR r.ft_goals_away > r.goals_away))
               OR (upper(f.status_short) = 'FT' AND r.ft_goals_home IS NOT NULL
                   AND (r.ft_goals_home, r.ft_goals_away) <> (r.goals_home, r.goals_away))
               OR (r.ht_goals_home IS NOT NULL AND (r.ht_goals_home > r.goals_home OR r.ht_goals_away > r.goals_away))""",
        lambda r: (_fx(r), "parts no greater than the final; FT final = 90-minute score",
                   f"final {r['goals_home']}-{r['goals_away']}, 90' {r['ft_goals_home']}-{r['ft_goals_away']}, "
                   f"ET {r['et_goals_home']}-{r['et_goals_away']} ({r['status_short']})", ""),
    ),
    Check(
        "past_kickoff_not_final", "fixtures", "status_short", Kind.STALE, Severity.HIGH,
        """SELECT f.provider_fixture_id, f.status_short, f.kickoff_at, c.name AS competition, cs.season,
                  count(*) OVER () AS n_total
             FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND f.status_group IN ('scheduled', 'live')
              AND f.kickoff_at < %(at)s - interval '3 hours'
            ORDER BY f.kickoff_at DESC""",
        lambda r: (_fx(r), "a final status", f"{r['status_short']}, kicked off {r['kickoff_at']:%Y-%m-%d %H:%M}Z",
                   "the provider can take up to 48 h for some competitions; the API sample says whose lag it is"),
    ),
    Check(
        "live_stuck", "fixtures", "status_group", Kind.STALE, Severity.HIGH,
        """SELECT f.provider_fixture_id, f.status_short, f.kickoff_at, c.name AS competition, cs.season,
                  count(*) OVER () AS n_total
             FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE f.status_group = 'live' AND f.kickoff_at < %(at)s - interval '4 hours'""",
        lambda r: (_fx(r), "finished by now", f"{r['status_short']} since {r['kickoff_at']:%Y-%m-%d %H:%M}Z", ""),
    ),
    Check(
        "duplicate_fixture", "fixtures", "identity", Kind.INCONSISTENT, Severity.HIGH,
        """SELECT a.provider_fixture_id, b.provider_fixture_id AS other, a.kickoff_at, b.kickoff_at AS other_kickoff,
                  a.status_short, b.status_short AS other_status, c.name AS competition, cs.season,
                  count(*) OVER () AS n_total
             FROM core.fixtures a
             JOIN core.fixtures b ON b.home_team_id = a.home_team_id AND b.away_team_id = a.away_team_id
                                  AND b.id > a.id AND abs(extract(epoch FROM b.kickoff_at - a.kickoff_at)) < 36 * 3600
             JOIN core.competition_seasons cs ON cs.id = a.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE a.status_group NOT IN ('cancelled', 'postponed') AND b.status_group NOT IN ('cancelled', 'postponed')""",
        lambda r: (_fx(r), "one fixture", f"also {r['other']} ({r['other_status']}, {r['other_kickoff']:%Y-%m-%d %H:%M}Z)",
                   "the same pairing twice within 36 hours"),
    ),
    Check(
        "prematch_price_after_kickoff", "odds", "captured_at", Kind.INCONSISTENT, Severity.CRITICAL,
        """SELECT f.provider_fixture_id, f.kickoff_at, max(o.captured_at) AS last_capture, count(*) AS rows,
                  c.name AS competition, cs.season, count(*) OVER () AS n_total
             FROM market.odds_snapshots o JOIN core.fixtures f ON f.id = o.fixture_id
             JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
             JOIN core.competitions c ON c.id = cs.competition_id
            WHERE o.captured_at > f.kickoff_at
            GROUP BY f.provider_fixture_id, f.kickoff_at, c.name, cs.season""",
        lambda r: (_fx(r), f"captured before {r['kickoff_at']:%Y-%m-%d %H:%M}Z",
                   f"{r['rows']} pre-match rows captured up to {r['last_capture']:%Y-%m-%d %H:%M}Z",
                   "a pre-match series must end at kick-off, or a backtest reads the future"),
        "SELECT count(DISTINCT fixture_id) FROM market.odds_snapshots",
    ),
    Check(
        "duplicate_team_name", "teams", "identity", Kind.INCONSISTENT, Severity.LOW,
        """SELECT lower(t.name) AS name, t.country, array_agg(t.provider_team_id ORDER BY t.provider_team_id) AS ids,
                  count(*) OVER () AS n_total
             FROM core.teams t GROUP BY lower(t.name), t.country HAVING count(*) > 1""",
        lambda r: (f"team '{r['name']}' ({r['country']})", "one identity", f"provider ids {r['ids']}",
                   "two provider ids with one name and country: a duplicate, or two sides (men/women, B team)"),
        "SELECT count(*) FROM core.teams",
    ),
)


TABLE_STALENESS_SQL = """
WITH snap AS (
    SELECT s.competition_season_id AS cs, max(s.snapshot_at) AS at FROM core.standings s GROUP BY 1
), finished AS (
    SELECT f.competition_season_id AS cs, max(f.kickoff_at) AS last_kickoff, count(*) AS n
      FROM core.fixtures f WHERE f.status_group = 'finished' GROUP BY 1
)
SELECT c.name AS competition, c.provider_league_id, cs.season, snap.at AS snapshot_at, fin.last_kickoff,
       k.checked_at, k.changed_at
  FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN snap ON snap.cs = cs.id
  LEFT JOIN finished fin ON fin.cs = cs.id
  LEFT JOIN core.context_checks k ON k.competition_season_id = cs.id AND k.dataset = 'standings'
 WHERE c.is_tracked AND cs.is_current AND c.type = 'league' AND fin.n > 0
 ORDER BY c.name
"""

TABLE_PLAYED_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (s.competition_season_id) s.competition_season_id AS cs, s.snapshot_at
      FROM core.standings s
      JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE c.is_tracked AND cs.is_current AND c.type = 'league'
     ORDER BY s.competition_season_id, s.snapshot_at DESC
), rows AS (
    SELECT s.competition_season_id AS cs, s.team_id, s."group", s.played, s.snapshot_at
      FROM core.standings s JOIN latest l ON l.cs = s.competition_season_id AND l.snapshot_at = s.snapshot_at
), counted AS (
    SELECT r.cs, r.team_id, r."group", r.played, r.snapshot_at,
           (SELECT count(*) FROM core.fixtures f
             WHERE f.competition_season_id = r.cs AND f.status_group = 'finished'
               AND (f.home_team_id = r.team_id OR f.away_team_id = r.team_id)
               AND f.kickoff_at + interval '2 hours' <= r.snapshot_at) AS finished_before
      FROM rows r
)
SELECT c.name AS competition, cs.season, t.provider_team_id, t.name AS team, x."group", x.played, x.finished_before,
       x.snapshot_at
  FROM counted x JOIN core.competition_seasons cs ON cs.id = x.cs JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id = x.team_id
"""

ELO_COVERAGE_SQL = """
WITH fin AS (
    SELECT cs.competition_id, count(*) AS finished, max(f.kickoff_at) AS last_finished
      FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
     WHERE f.status_group = 'finished' GROUP BY 1
), rated AS (
    SELECT cs.competition_id, count(DISTINCT e.fixture_id) AS rated, max(e.kickoff_at) AS last_rated
      FROM features.elo_ratings e JOIN core.fixtures f ON f.id = e.fixture_id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
     GROUP BY 1
)
SELECT c.name AS competition, c.provider_league_id, c.is_tracked, fin.finished, COALESCE(rated.rated, 0) AS rated,
       fin.last_finished, rated.last_rated
  FROM fin JOIN core.competitions c ON c.id = fin.competition_id
  LEFT JOIN rated ON rated.competition_id = fin.competition_id
 ORDER BY fin.finished DESC
"""

PLAYER_PROFILE_SQL = """
WITH recent AS (
    SELECT DISTINCT lp.provider_player_id
      FROM core.fixture_lineup_players lp JOIN core.fixtures f ON f.id = lp.fixture_id
     WHERE f.kickoff_at > %(at)s - interval '365 days' AND lp.provider_player_id > 0
)
SELECT count(*) AS appeared,
       count(p.id) AS known,
       count(p.birth_date) AS with_birth_date,
       count(p.nationality) AS with_nationality,
       count(p.height_cm) AS with_height
  FROM recent r LEFT JOIN core.players p ON p.provider_player_id = r.provider_player_id
"""


def _run_check(conn: psycopg.Connection, check: Check, at: datetime, tally: Tally) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(check.sql + f" LIMIT {FINDINGS_KEPT_PER_KIND}", {"at": at})
        rows = cur.fetchall()
        total = int(rows[0]["n_total"]) if rows else 0
        checked = None
        if check.checked_sql:
            cur.execute(check.checked_sql)
            got = cur.fetchone()
            checked = int(next(iter(got.values()))) if got else None
    for r in rows:
        entity, expected, db, note = check.describe(r)
        tally.add(Finding.of(check.dataset, entity, check.field, check.kind, check.severity, api=expected, db=db,
                             note=note))
    hidden = total - len(rows)
    if hidden > 0:
        key = (check.field, check.kind.value, check.severity.value)
        tally.counts[key] = tally.counts.get(key, 0) + hidden
    if checked is not None:
        tally.checked += checked
        tally.matched += max(checked - total, 0)
    tally.notes.append(f"{check.name}: {total:,}")


def standings_freshness(conn: psycopg.Connection, at: datetime, tally: Tally) -> None:
    """Every current league table against the last match it should already reflect."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TABLE_STALENESS_SQL)
        rows = cur.fetchall()
    for r in rows:
        tally.compared()
        label = f"{r['competition']} {r['season']}"
        snap, last = r["snapshot_at"], r["last_kickoff"]
        if snap is None:
            tally.add(Finding.of("standings", label, "snapshot_at", Kind.MISSING_IN_DB, Severity.MEDIUM,
                                 api="a table", db="no snapshot", note="a league with finished matches and no table"))
            continue
        if last is not None and snap < last + timedelta(hours=2):
            checked = r["checked_at"]
            lag = checked is not None and checked > last + timedelta(hours=2)
            tally.add(Finding.of("standings", label, "snapshot_at", Kind.PROVIDER_LAG if lag else Kind.STALE,
                                 Severity.LOW if lag else Severity.MEDIUM,
                                 api=f"a table after the match of {last:%Y-%m-%d %H:%M}Z",
                                 db=f"newest content {snap:%Y-%m-%d %H:%M}Z"
                                    + (f", asked again {checked:%Y-%m-%d %H:%M}Z" if checked else ", never re-asked"),
                                 note="the provider had not updated it when we last asked" if lag
                                 else "not re-requested since the match ended"))
        else:
            tally.matched += 1


def standings_played(conn: psycopg.Connection, tally: Tally) -> None:
    """Matches played in our newest table against the finished matches we hold for that team."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TABLE_PLAYED_SQL)
        rows = cur.fetchall()
    for r in rows:
        tally.compared()
        if r["played"] == r["finished_before"]:
            tally.matched += 1
            continue
        label = f"{r['competition']} {r['season']} team {r['provider_team_id']} ({r['team']})"
        more_in_table = r["played"] > r["finished_before"]
        tally.add(Finding.of(
            "standings", label, "played", Kind.INCONSISTENT, Severity.MEDIUM if more_in_table else Severity.LOW,
            api=f"{r['played']} played in the table", db=f"{r['finished_before']} finished fixtures stored",
            note="fixtures missing from our database (or a phase the table counts differently)" if more_in_table
            else "the table counts fewer matches than we hold (a split season, or a table behind)"))


def elo_coverage(conn: psycopg.Connection, tally: Tally) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ELO_COVERAGE_SQL)
        rows = cur.fetchall()
    total_finished = sum(int(r["finished"]) for r in rows)
    total_rated = sum(int(r["rated"]) for r in rows)
    tally.checked += total_finished
    tally.matched += total_rated
    for r in rows:
        missing = int(r["finished"]) - int(r["rated"])
        if missing <= 0:
            continue
        tally.add(Finding.of(
            "elo", f"competition {r['provider_league_id']} {r['competition']}", "rated fixtures", Kind.MISSING_IN_DB,
            Severity.HIGH if r["is_tracked"] else Severity.LOW,
            api=f"{r['finished']:,} finished (last {r['last_finished']:%Y-%m-%d})",
            db=f"{r['rated']:,} rated" + (f" (last {r['last_rated']:%Y-%m-%d})" if r["last_rated"] else ""),
            note="ratings were computed once and never extended"))
    tally.notes.append(f"{total_rated:,} of {total_finished:,} finished fixtures carry an Elo rating")


def player_profiles(conn: psycopg.Connection, at: datetime, tally: Tally) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PLAYER_PROFILE_SQL, {"at": at})
        r = cur.fetchone() or {}
    appeared = int(r.get("appeared") or 0)
    tally.checked += appeared
    tally.matched += int(r.get("with_birth_date") or 0)
    for column, label in (("known", "identity"), ("with_birth_date", "birth_date"),
                          ("with_nationality", "nationality"), ("with_height", "height_cm")):
        have = int(r.get(column) or 0)
        if have < appeared:
            tally.add(Finding.of("players", "players in a line-up in the last 365 days", label, Kind.MISSING_IN_DB,
                                 Severity.MEDIUM if label in ("birth_date", "nationality") else Severity.LOW,
                                 api=f"{appeared:,} players", db=f"{have:,} with {label}",
                                 note="season profiles (/players) were never fetched" if label != "identity" else ""))


def run_internal(conn: psycopg.Connection, *, at: datetime) -> dict[str, Tally]:
    """Every internal check, grouped by the dataset it is about."""
    tallies: dict[str, Tally] = {}

    def tally(name: str) -> Tally:
        return tallies.setdefault(name, Tally(name))

    for check in CHECKS:
        _run_check(conn, check, at, tally(check.dataset))
    standings_freshness(conn, at, tally("standings"))
    standings_played(conn, tally("standings"))
    elo_coverage(conn, tally("elo"))
    player_profiles(conn, at, tally("players"))
    return tallies
