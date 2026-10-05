"""The data-truth audit: ask the provider, read the database, write down every disagreement.

What it asks, and why each costs what it costs (all through ``build_client``, so the
daily guard and the per-run cap both apply, and every answer lands in the raw store
under a ``truth_audit`` ledger run - the evidence for each finding is kept):

* ``/leagues`` - one request: every competition, every season, every coverage flag.
* ``/fixtures?league&season`` - one per current season (all of them) and per sampled
  past season: the full fixture list, statuses and scores, against ours.
* ``/fixtures?ids=`` - one per 20 sampled fixtures: identity, status, score, events,
  line-ups, team and player statistics, field by field.
* ``/standings?league&season`` - one per current league season: the whole table.
* ``/odds?fixture`` and ``/injuries?ids=`` - for the sampled upcoming fixtures.
* ``/teams?id``, ``/players?id&season``, ``/coachs?id``, ``/players/squads?team`` - for
  the sampled identities.
* ``/odds/bookmakers`` - one request: every bookmaker the provider has.

Nothing in ``core``, ``market`` or ``features`` is written. The run, its sample, its
summary and the findings go to ``audit.truth_runs`` / ``audit.truth_findings`` and to
a folder of JSON and Markdown under ``data/truth/``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.core.errors import ProviderError, QuotaExhaustedError
from fbi.core.version import code_version
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.normalize import iter_odds
from fbi.providers.base import RawResponse
from fbi.truth import compare
from fbi.truth.findings import SEVERITY_ORDER, Finding, Kind, Severity, Tally
from fbi.truth.freshness import DatasetFreshness, measure
from fbi.truth.gate import GateSummary, Need, dataset_role, evaluate
from fbi.truth.internal import run_internal
from fbi.truth.report import render_markdown
from fbi.truth.sample import DEFAULT_SIZE, Sample, SampleSize, draw

log = structlog.get_logger(__name__)

MAX_IDS = 20
DETAIL_SOURCE = "api-football"


class Client:
    """What the audit needs from a provider client: one GET. ``ApiFootballClient`` is one."""

    async def get(self, endpoint: str, params: dict[str, Any]) -> Any:  # pragma: no cover - protocol
        raise NotImplementedError


@dataclass
class AuditResult:
    run_id: int
    started_at: datetime
    sample: Sample
    tallies: dict[str, Tally]
    freshness: list[DatasetFreshness]
    gate: GateSummary
    requests: int = 0
    failures: list[str] = field(default_factory=list)
    stopped: str | None = None
    folder: Path | None = None
    sides: dict[str, tuple[str, str]] = field(default_factory=dict)
    """dataset -> (what the provider showed, what the database held) for the matrix."""
    side_keys: dict[str, tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=dict)
    """The same two facts as a message key and its numbers, so a page can say them in its
    reader's language (``truth.sides.<key>``)."""

    def side(self, dataset: str, api: str, db: str, api_key: str, db_key: str, **params: Any) -> None:
        self.sides[dataset] = (api, db)
        self.side_keys[dataset] = ({"key": api_key, "params": params}, {"key": db_key, "params": params})

    def matrix(self) -> list[dict[str, Any]]:
        fresh = {f.dataset: f for f in self.freshness}
        rows = []
        for name in MATRIX_ORDER:
            t = self.tallies.get(name)
            if t is None and name not in fresh:
                continue
            f = fresh.get(FRESHNESS_OF.get(name, name))
            api, db = self.sides.get(name, ("", ""))
            api_key, db_key = self.side_keys.get(name, ({}, {}))
            safe_code, safe_reasons = safety(name, t, f)
            rows.append({
                "dataset": name, "api": api, "db": db, "api_key": api_key, "db_key": db_key,
                "by_kind": t.by_kind() if t else {}, "freshness_counts": f.counts if f else {},
                "safe_code": safe_code, "safe_reasons": safe_reasons,
                "difference": t.difference() if t else "not compared",
                "checked": t.checked if t else 0, "matched": t.matched if t else 0,
                "findings": t.total_findings if t else 0, "worst": (t.worst.value if t and t.worst else None),
                "freshness": f.label() if f else "n/a", "freshness_status": f.status.value if f else None,
                "model_safe": model_safe(name, t, f),
                "role": dataset_role(FRESHNESS_OF.get(name, name)).value,
            })
        return rows


MATRIX_ORDER = ("competitions", "fixtures", "results", "events", "lineups", "team_stats", "player_stats",
                "standings", "teams", "players", "coaches", "squads", "injuries", "odds", "bookmakers", "elo")
FRESHNESS_OF = {"events": "match_detail", "team_stats": "match_detail", "player_stats": "match_detail",
                "odds": "odds_prematch", "bookmakers": "odds_prematch", "competitions": "coverage"}


def safety(dataset: str, tally: Tally | None, fresh: DatasetFreshness | None) -> tuple[str, list[str]]:
    """(code, reasons): yes / yes_optional / partial / no / na, and why ("critical", "high", "stale")."""
    role = dataset_role(FRESHNESS_OF.get(dataset, dataset))
    if role is Need.NOT_USED:
        return "na", []
    worst = tally.worst if tally else None
    reasons: list[str] = []
    if worst in (Severity.CRITICAL, Severity.HIGH):
        reasons.append(worst.value)
    if fresh is not None and fresh.status.value == "STALE":
        reasons.append("stale")
    if not reasons:
        return ("yes" if role is Need.REQUIRED else "yes_optional"), []
    if role is Need.REQUIRED and worst is Severity.CRITICAL:
        return "no", reasons
    return "partial", reasons


def model_safe(dataset: str, tally: Tally | None, fresh: DatasetFreshness | None) -> str:
    """YES / PARTIAL / NO for the models that read this dataset; n/a when none does."""
    code, reasons = safety(dataset, tally, fresh)
    text = {"na": "n/a - no model reads it", "yes": "YES", "yes_optional": "YES (optional input)",
            "partial": "PARTIAL", "no": "NO"}[code]
    return text + (" - " + ", ".join(f"{r} findings" if r != "stale" else r for r in reasons) if reasons else "")


# ── database readers ────────────────────────────────────────────────────────

FIXTURE_COLUMNS = """
SELECT f.id, f.provider_fixture_id, c.provider_league_id, cs.season, f.kickoff_at, f.status_short, f.status_group,
       f.round, th.provider_team_id AS home_provider_id, ta.provider_team_id AS away_provider_id,
       v.provider_venue_id AS venue_provider_id, f.updated_at, f.source_fetched_at,
       r.fixture_id IS NOT NULL AS has_result, r.goals_home, r.goals_away, r.ht_goals_home, r.ht_goals_away,
       r.ft_goals_home, r.ft_goals_away, r.et_goals_home, r.et_goals_away, r.pen_home, r.pen_away
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN core.venues v ON v.id = f.venue_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
"""


def _rows(conn: psycopg.Connection, sql: str, params: Any = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def db_fixtures(conn: psycopg.Connection, provider_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    rows = _rows(conn, FIXTURE_COLUMNS + " WHERE f.provider_fixture_id = ANY(%s)", (list(provider_ids),))
    return {int(r["provider_fixture_id"]): r for r in rows}


def db_season_fixtures(conn: psycopg.Connection, league: int, season: int) -> dict[int, dict[str, Any]]:
    rows = _rows(conn, FIXTURE_COLUMNS + " WHERE c.provider_league_id = %s AND cs.season = %s", (league, season))
    return {int(r["provider_fixture_id"]): r for r in rows}


def _by_fixture(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["provider_fixture_id"]), []).append(r)
    return out


def db_detail(conn: psycopg.Connection, provider_ids: Sequence[int]) -> dict[str, dict[int, list[dict[str, Any]]]]:
    ids = list(provider_ids)
    join = "JOIN core.fixtures f ON f.id = x.fixture_id WHERE f.provider_fixture_id = ANY(%(ids)s)"
    src = "AND x.source = %(src)s"
    p = {"ids": ids, "src": DETAIL_SOURCE}
    return {
        "events": _by_fixture(_rows(conn, "SELECT f.provider_fixture_id, x.* FROM core.fixture_events x "
                                          f"{join} {src}", p)),
        "lineups": _by_fixture(_rows(conn, "SELECT f.provider_fixture_id, x.* FROM core.fixture_lineups x "
                                           f"{join} {src}", p)),
        "lineup_players": _by_fixture(_rows(conn, "SELECT f.provider_fixture_id, x.* FROM core.fixture_lineup_players x "
                                                  f"{join} {src}", p)),
        "team_stats": _by_fixture(_rows(conn, "SELECT f.provider_fixture_id, x.* FROM core.fixture_team_stats x "
                                              f"{join} {src}", p)),
        "player_stats": _by_fixture(_rows(conn, "SELECT f.provider_fixture_id, x.* FROM core.fixture_player_stats x "
                                                f"{join} {src}", p)),
        "coverage": _by_fixture(_rows(conn, "SELECT f.provider_fixture_id, f.kickoff_at, x.* FROM "
                                            f"core.fixture_detail_coverage x {join} {src}", p)),
    }


def db_standings(conn: psycopg.Connection, league: int, season: int) -> tuple[list[dict[str, Any]], datetime | None]:
    rows = _rows(conn, """
        WITH cs AS (SELECT cs.id FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
                     WHERE c.provider_league_id = %(l)s AND cs.season = %(s)s),
             latest AS (SELECT max(snapshot_at) AS at FROM core.standings WHERE competition_season_id IN
                        (SELECT id FROM cs))
        SELECT t.provider_team_id, s.* FROM core.standings s JOIN core.teams t ON t.id = s.team_id
         WHERE s.competition_season_id IN (SELECT id FROM cs) AND s.snapshot_at = (SELECT at FROM latest)""",
                 {"l": league, "s": season})
    last = _rows(conn, """
        SELECT max(f.kickoff_at) AS at FROM core.fixtures f JOIN core.competition_seasons cs
            ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
         WHERE c.provider_league_id = %s AND cs.season = %s AND f.status_group = 'finished'""", (league, season))
    return rows, (last[0]["at"] if last else None)


def db_team(conn: psycopg.Connection, provider_team_id: int) -> dict[str, Any] | None:
    rows = _rows(conn, "SELECT t.*, v.provider_venue_id AS venue_provider_id, v.name AS venue_name FROM core.teams t "
                       "LEFT JOIN core.venues v ON v.id = t.venue_id WHERE t.provider_team_id = %s",
                 (provider_team_id,))
    return rows[0] if rows else None


def db_player(conn: psycopg.Connection, provider_player_id: int) -> dict[str, Any] | None:
    rows = _rows(conn, "SELECT * FROM core.players WHERE provider_player_id = %s", (provider_player_id,))
    return rows[0] if rows else None


def db_coach(conn: psycopg.Connection, provider_coach_id: int) -> dict[str, Any] | None:
    rows = _rows(conn, """
        SELECT co.*, (SELECT t.provider_team_id FROM core.fixture_lineups l JOIN core.fixtures f ON f.id = l.fixture_id
                        JOIN core.teams t ON t.id = CASE l.team_side WHEN 'home' THEN f.home_team_id
                                                                     ELSE f.away_team_id END
                       WHERE l.provider_coach_id = co.provider_coach_id ORDER BY f.kickoff_at DESC LIMIT 1)
               AS current_team_provider_id
          FROM core.coaches co WHERE co.provider_coach_id = %s""", (provider_coach_id,))
    return rows[0] if rows else None


def db_known_players(conn: psycopg.Connection, ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    rows = _rows(conn, "SELECT provider_player_id, birth_date, nationality FROM core.players "
                       "WHERE provider_player_id = ANY(%s)", (list(ids),))
    return {int(r["provider_player_id"]): r for r in rows}


def db_absences(conn: psycopg.Connection, provider_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    rows = _rows(conn, "SELECT * FROM core.player_absences WHERE provider_fixture_id = ANY(%s)", (list(provider_ids),))
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["provider_fixture_id"]), []).append(r)
    return out


def db_latest_odds(conn: psycopg.Connection, provider_fixture_id: int) -> list[dict[str, Any]]:
    return _rows(conn, """
        SELECT DISTINCT ON (o.bookmaker_id, o.market_key, o.selection, o.line)
               b.provider_bookmaker_id, b.name AS bookmaker, o.market_key, o.selection, o.line, o.odds_decimal,
               o.captured_at
          FROM market.odds_snapshots o JOIN core.fixtures f ON f.id = o.fixture_id
          JOIN market.bookmakers b ON b.id = o.bookmaker_id
         WHERE f.provider_fixture_id = %s
         ORDER BY o.bookmaker_id, o.market_key, o.selection, o.line, o.captured_at DESC""", (provider_fixture_id,))


# ── the run ─────────────────────────────────────────────────────────────────


class _Asker:
    """Every provider request of the run, counted, indexed in the ledger, and survivable."""

    def __init__(self, client: Any, ledger: RunLedger, run_id: int, counters: RunCounters, result: AuditResult,
                 conn: psycopg.Connection) -> None:
        self.client, self.ledger, self.run_id, self.counters, self.result = client, ledger, run_id, counters, result
        self.conn = conn

    async def get(self, endpoint: str, params: dict[str, Any], tally: Tally | None = None) -> dict[str, Any] | None:
        if self.result.stopped:
            return None
        try:
            response = await self.client.get(endpoint, params)
        except QuotaExhaustedError as exc:
            self.result.stopped = f"quota: {exc}"
            self.counters.stopped_early = "quota"
            return None
        except ProviderError as exc:
            self.counters.api_calls += 1
            self.result.requests += 1
            message = f"{endpoint} {params}: {exc}"
            self.result.failures.append(message)
            self.counters.errors.append(message)
            if tally is not None:
                tally.requests += 1
                tally.notes.append(f"request failed: {message}"[:300])
            return None
        self.counters.api_calls += 1
        self.result.requests += 1
        if tally is not None:
            tally.requests += 1
        stored = getattr(response, "stored", None)
        if stored is not None:
            raw = RawResponse(endpoint=endpoint, params=response.params, fetched_at=response.fetched_at,
                              http_status=response.http_status, results_count=response.results_count,
                              payload_hash=stored.hash, file_path=stored.file_path, bytes_written=stored.bytes_written,
                              body=response.body)
            self.counters.payloads_stored += self.ledger.record_payloads(self.run_id, [raw])
            self.conn.commit()
        body = response.body
        return body if isinstance(body, dict) else None


def _items(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    response = (body or {}).get("response")
    return [x for x in response if isinstance(x, dict)] if isinstance(response, list) else []


async def _competitions(ask: _Asker, conn: psycopg.Connection, result: AuditResult) -> None:
    tally = result.tallies.setdefault("competitions", Tally("competitions"))
    body = await ask.get("/leagues", {}, tally)
    comps = {int(r["provider_league_id"]): r for r in _rows(conn, "SELECT * FROM core.competitions WHERE is_tracked")}
    seasons: dict[int, dict[int, dict[str, Any]]] = {}
    for r in _rows(conn, "SELECT c.provider_league_id, cs.* FROM core.competition_seasons cs JOIN core.competitions c "
                         "ON c.id = cs.competition_id WHERE c.is_tracked"):
        seasons.setdefault(int(r["provider_league_id"]), {})[int(r["season"])] = r
    coverage: dict[int, dict[int, dict[str, Any]]] = {}
    for r in _rows(conn, "SELECT * FROM raw.league_coverage"):
        coverage.setdefault(int(r["provider_league_id"]), {})[int(r["season"])] = r
    listed = 0
    for item in _items(body):
        lid = compare._id(item.get("league"))
        if lid is None or lid not in comps:
            continue
        listed += 1
        compare.compare_league(item, comps[lid], seasons.get(lid, {}), coverage.get(lid, {}), tally=tally)
    result.side("competitions", f"{len(_items(body)):,} competitions listed, {listed} of ours among them",
                f"{len(comps)} tracked", "leagues_listed", "tracked", listed=len(_items(body)), ours=listed,
                tracked=len(comps))


async def _fixture_lists(ask: _Asker, conn: psycopg.Connection, result: AuditResult, now: datetime) -> None:
    fixtures = result.tallies.setdefault("fixtures", Tally("fixtures"))
    results = result.tallies.setdefault("results", Tally("results"))
    api_total = db_total = 0
    seasons = [(lg, s, True) for lg, s in result.sample.current_seasons] + \
              [(lg, s, False) for lg, s in result.sample.historical_seasons]
    for league, season, _current in seasons:
        body = await ask.get("/fixtures", {"league": league, "season": season}, fixtures)
        if body is None:
            continue
        ours = db_season_fixtures(conn, league, season)
        items = _items(body)
        api_total += len(items)
        db_total += len(ours)
        seen: set[int] = set()
        for item in items:
            pid = compare._id(item.get("fixture"))
            if pid is None:
                continue
            seen.add(pid)
            compare.compare_fixture(item, ours.get(pid), now=now, tally=fixtures, results=results)
        absent = [i for i in items if compare._id(i.get("fixture")) not in ours]
        if absent:
            played = sum(1 for i in absent if str(compare._d(compare._d(i.get("fixture")).get("status")).get("short"))
                         .upper() in compare.FINISHED)
            name = compare._d(items[0].get("league")).get("name") if items else league
            fixtures.notes.append(f"{name} {season} ({league}): the provider lists {len(items):,}, we hold "
                                  f"{len(ours):,}; {len(absent):,} missing, {played:,} of them played")
        for pid, row in ours.items():
            if pid not in seen:
                fixtures.compared()
                fixtures.add(Finding.of(
                    "fixtures", f"fixture {pid} ({league}/{season})", "fixture", Kind.MISSING_IN_API,
                    Severity.MEDIUM if row["status_group"] in ("scheduled", "live") else Severity.LOW,
                    db=f"{row['status_short']} {row['kickoff_at']:%Y-%m-%d %H:%M}Z",
                    note="we hold a fixture the provider no longer lists for this season (re-numbered or "
                         "deleted); a scheduled one would be captured and predicted for nothing"))
    result.side("fixtures", f"{api_total:,} fixtures in {len(seasons)} seasons "
                f"({len(result.sample.current_seasons)} current)", f"{db_total:,} stored for them",
                "fixture_lists", "stored_for_them", n=api_total, seasons=len(seasons),
                current=len(result.sample.current_seasons), stored=db_total)
    result.side("results", "scores of the finished fixtures in those lists", "core.fixture_results",
                "finished_scores", "result_rows")


async def _details(ask: _Asker, conn: psycopg.Connection, result: AuditResult, now: datetime) -> None:
    names = ("events", "lineups", "team_stats", "player_stats")
    tallies = {n: result.tallies.setdefault(n, Tally(n)) for n in names}
    fixtures = result.tallies.setdefault("fixtures", Tally("fixtures"))
    results = result.tallies.setdefault("results", Tally("results"))
    ids = result.sample.detail_fixtures + result.sample.upcoming_fixtures
    for start in range(0, len(ids), MAX_IDS):
        batch = ids[start:start + MAX_IDS]
        body = await ask.get("/fixtures", {"ids": "-".join(str(i) for i in batch)}, tallies["events"])
        if body is None:
            continue
        ours = db_fixtures(conn, batch)
        detail = db_detail(conn, batch)
        for item in _items(body):
            pid = compare._id(item.get("fixture"))
            if pid is None:
                continue
            row = ours.get(pid)
            compare.compare_fixture(item, row, now=now, tally=fixtures, results=results)
            if row is None:
                continue
            cov = {r["dataset"]: r for r in detail["coverage"].get(pid, [])}
            home = row["home_provider_id"]
            compare.compare_events(item, detail["events"].get(pid, []), cov.get("events"), tally=tallies["events"])
            compare.compare_lineups(item, detail["lineups"].get(pid, []), detail["lineup_players"].get(pid, []),
                                    home_provider_id=home, tally=tallies["lineups"])
            compare.compare_team_stats(item, detail["team_stats"].get(pid, []), home_provider_id=home,
                                       coverage=cov.get("team_statistics"), tally=tallies["team_stats"])
            compare.compare_player_stats(item, detail["player_stats"].get(pid, []), home_provider_id=home,
                                         tally=tallies["player_stats"])
    for n in names:
        result.side(n, f"{len(ids)} sampled fixtures (/fixtures?ids=)", "the rows stored for them",
                    "sampled_fixtures", "rows_for_them", n=len(ids))


async def _standings(ask: _Asker, conn: psycopg.Connection, result: AuditResult, now: datetime) -> None:
    tally = result.tallies.setdefault("standings", Tally("standings"))
    rows_api = rows_db = 0
    extended = bool(_rows(conn, "SELECT 1 FROM information_schema.columns WHERE table_schema = 'core' "
                                "AND table_name = 'standings' AND column_name = 'description'"))
    for league, season in result.sample.standings_seasons:
        body = await ask.get("/standings", {"league": league, "season": season}, tally)
        if body is None:
            continue
        ours, last_finished = db_standings(conn, league, season)
        rows_api += len(compare.api_standing_rows(body))
        rows_db += len(ours)
        label = f"standings {league}/{season}"
        name = next((compare._d(i.get("league")).get("name") for i in _items(body)), None)
        if name:
            label = f"{name} {season} ({league})"
        compare.compare_standings(body, ours, label=label, last_finished=last_finished, now=now, tally=tally,
                                  stored_extended=extended and any(r.get("description") is not None
                                                                   or r.get("home_played") is not None
                                                                   for r in ours))
    result.side("standings", f"{rows_api:,} table rows in {len(result.sample.standings_seasons)} league seasons",
                f"{rows_db:,} rows in our newest snapshots", "table_rows", "newest_snapshot_rows", n=rows_api,
                seasons=len(result.sample.standings_seasons), stored=rows_db)


async def _identities(ask: _Asker, conn: psycopg.Connection, result: AuditResult) -> None:
    teams = result.tallies.setdefault("teams", Tally("teams"))
    for tid in result.sample.teams:
        body = await ask.get("/teams", {"id": tid}, teams)
        if body is None and result.stopped:
            break
        items = _items(body)
        compare.compare_team(items[0] if items else None, db_team(conn, tid), provider_team_id=tid, tally=teams)
    result.side("teams", f"{len(result.sample.teams)} sampled teams (/teams?id)", "core.teams + core.venues",
                "sampled_teams", "teams_table", n=len(result.sample.teams))

    players = result.tallies.setdefault("players", Tally("players"))
    for pid, season in result.sample.players:
        body = await ask.get("/players", {"id": pid, "season": season}, players)
        items = _items(body)
        compare.compare_player(items[0] if items else None, db_player(conn, pid), provider_player_id=pid,
                               tally=players)
    result.side("players", f"{len(result.sample.players)} sampled players (/players?id&season)", "core.players",
                "sampled_players", "players_table", n=len(result.sample.players))

    coaches = result.tallies.setdefault("coaches", Tally("coaches"))
    for cid in result.sample.coaches:
        body = await ask.get("/coachs", {"id": cid}, coaches)
        items = _items(body)
        compare.compare_coach(items[0] if items else None, db_coach(conn, cid), provider_coach_id=cid, tally=coaches)
    result.side("coaches", f"{len(result.sample.coaches)} sampled coaches (/coachs?id)", "core.coaches",
                "sampled_coaches", "coaches_table", n=len(result.sample.coaches))

    squads = result.tallies.setdefault("squads", Tally("squads"))
    for tid in result.sample.squads:
        body = await ask.get("/players/squads", {"team": tid}, squads)
        items = _items(body)
        players_in = [p for p in compare._l((items[0] if items else {}).get("players")) if isinstance(p, dict)]
        known = db_known_players(conn, [i for i in (compare._id(p) for p in players_in) if i is not None])
        stored = _rows(conn, """
            SELECT m.provider_player_id FROM core.squad_members m JOIN core.teams t ON t.id = m.team_id
             WHERE t.provider_team_id = %s AND m.last_seen_at = t.squad_checked_at""", (tid,))
        compare.compare_squad(items[0] if items else None, known, provider_team_id=tid, tally=squads,
                              stored=stored)
    result.side("squads", f"{len(result.sample.squads)} sampled squads (/players/squads)", "not stored",
                "sampled_squads", "not_stored", n=len(result.sample.squads))


async def _upcoming(ask: _Asker, conn: psycopg.Connection, result: AuditResult, now: datetime) -> None:
    injuries = result.tallies.setdefault("injuries", Tally("injuries"))
    odds = result.tallies.setdefault("odds", Tally("odds"))
    ids = result.sample.upcoming_fixtures
    ours = db_fixtures(conn, ids)
    for start in range(0, len(ids), MAX_IDS):
        batch = ids[start:start + MAX_IDS]
        body = await ask.get("/injuries", {"ids": "-".join(str(i) for i in batch)}, injuries)
        if body is None:
            continue
        by_fixture: dict[int, list[dict[str, Any]]] = {i: [] for i in batch}
        for item in _items(body):
            fid = compare._id(item.get("fixture"))
            if fid in by_fixture:
                by_fixture[fid].append(item)
        absences = db_absences(conn, batch)
        for fid in batch:
            compare.compare_injuries(by_fixture[fid], absences.get(fid, []), provider_fixture_id=fid, tally=injuries)
    result.side("injuries", f"{len(ids)} sampled upcoming fixtures (/injuries?ids)", "core.player_absences",
                "sampled_upcoming", "absences_table", n=len(ids))

    books_seen: dict[int, str] = {}
    priced = 0
    for fid in ids:
        body = await ask.get("/odds", {"fixture": fid}, odds)
        if body is None:
            continue
        items = _items(body)
        row = ours.get(fid)
        kickoff = row["kickoff_at"] if row else None
        if not items:
            odds.compared()
            odds.matched += 1
            odds.notes.append(f"fixture {fid}: the provider has no prices")
            continue
        priced += 1
        api_books = {int(b["id"]): str(b.get("name")) for b in compare._l(items[0].get("bookmakers"))
                     if isinstance(b, dict) and isinstance(b.get("id"), int)}
        books_seen.update(api_books)
        quotes = [{"provider_bookmaker_id": q.provider_bookmaker_id, "market_key": q.market_key,
                   "selection": q.selection, "line": q.line, "odds_decimal": q.odds_decimal}
                  for q in iter_odds(body, kickoff_at=kickoff or now, captured_at=now, payload_hash="audit",
                                     source="prematch")]
        latest = db_latest_odds(conn, fid)
        db_books = {int(r["provider_bookmaker_id"]): str(r["bookmaker"]) for r in latest}
        compare.compare_odds(quotes, api_books, compare._when(items[0].get("update")), latest, db_books,
                             provider_fixture_id=fid, kickoff=kickoff, now=now, tally=odds)
    result.side("odds", f"{priced} of {len(ids)} sampled upcoming fixtures priced; {len(books_seen)} bookmakers",
                "our newest price per bookmaker, market, selection and line", "priced_upcoming", "newest_prices",
                priced=priced, n=len(ids), books=len(books_seen))

    books = result.tallies.setdefault("bookmakers", Tally("bookmakers"))
    body = await ask.get("/odds/bookmakers", {}, books)
    provider_books = {int(b["id"]): str(b.get("name")) for b in _items(body) if isinstance(b.get("id"), int)}
    ours_books = {int(r["provider_bookmaker_id"]): r for r in _rows(conn, "SELECT * FROM market.bookmakers")}
    seen_ever = {int(r["provider_bookmaker_id"]) for r in _rows(conn, """
        SELECT DISTINCT b.provider_bookmaker_id FROM market.bookmakers b
         WHERE EXISTS (SELECT 1 FROM market.odds_snapshots o WHERE o.bookmaker_id = b.id)""")}
    for bid, name in sorted(provider_books.items()):
        books.compared()
        if bid in seen_ever:
            books.matched += 1
            continue
        books.add(Finding.of(
            "bookmakers", f"bookmaker {bid} {name}", "prices", Kind.MISSING_IN_DB, Severity.INFO,
            api="offered by the provider", db="known, never priced" if bid in ours_books else "never seen",
            note="seen in today's sample" if bid in books_seen else "absent from every /odds payload we stored"))
    result.side("bookmakers", f"{len(provider_books)} bookmakers offered (/odds/bookmakers)",
                f"{len(seen_ever)} with at least one stored price", "bookmakers_offered", "bookmakers_priced",
                n=len(provider_books), priced=len(seen_ever))


async def run_audit(conn: psycopg.Connection, client: Any, *, at: datetime, seed: float,
                    size: SampleSize = DEFAULT_SIZE, out_root: Path | None = None,
                    skip: frozenset[str] = frozenset()) -> AuditResult:
    """One full audit. ``conn`` must be autocommit: reads are short, writes are committed as they go."""
    ledger = RunLedger(conn)
    ingestion_run = ledger.open("truth_audit", params={"seed": seed}, scheduled_for=at)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO audit.truth_runs (started_at, ingestion_run_id, seed, code_version) "
                    "VALUES (%s, %s, %s, %s) RETURNING id", (at, ingestion_run, seed, code_version()))
        row = cur.fetchone()
        assert row is not None
        run_id = int(row[0])
    conn.commit()
    counters = RunCounters()
    sample = draw(conn, at=at, seed=seed, size=size)
    result = AuditResult(run_id=run_id, started_at=at, sample=sample, tallies={}, freshness=[],
                         gate=GateSummary(72))
    ask = _Asker(client, ledger, ingestion_run, counters, result, conn)
    steps: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("competitions", lambda: _competitions(ask, conn, result)),
        ("fixtures", lambda: _fixture_lists(ask, conn, result, at)),
        ("details", lambda: _details(ask, conn, result, at)),
        ("standings", lambda: _standings(ask, conn, result, at)),
        ("identities", lambda: _identities(ask, conn, result)),
        ("upcoming", lambda: _upcoming(ask, conn, result, at)),
    ]
    status = "completed"
    try:
        for name, step in steps:
            if name in skip or result.stopped:
                continue
            log.info("truth_audit.step", step=name, requests=result.requests)
            await step()
        internal = run_internal(conn, at=at)
        for name, t in internal.items():
            merge_internal(result.tallies.setdefault(name, Tally(name)), t)
        if "elo" not in result.sides:
            result.side("elo", "finished fixtures", "features.elo_ratings", "finished_fixtures", "elo_rows")
        result.freshness = measure(conn, at=at)
        result.gate, _ = evaluate(conn, at=at, horizon_hours=72)
        if result.stopped or result.failures:
            status = "partial"
    except Exception:
        status = "failed"
        raise
    except BaseException:
        status = "interrupted"
        raise
    finally:
        try:
            _persist(conn, result, status)
        except psycopg.Error as exc:  # the run must still close: a crash here left it 'running' (5 Oct 2026)
            conn.rollback()
            counters.errors.append(f"findings not stored: {type(exc).__name__}: {exc}"[:500])
            with conn.cursor() as cur:
                cur.execute("UPDATE audit.truth_runs SET finished_at = now(), status = 'failed', requests = %s "
                            "WHERE id = %s", (result.requests, run_id))
            conn.commit()
        ledger.close(ingestion_run, counters, notes=f"truth audit {run_id}: {result.requests} requests")
        if out_root is not None:
            result.folder = write_report(result, out_root)
            with conn.cursor() as cur:
                cur.execute("UPDATE audit.truth_runs SET report_dir = %s WHERE id = %s", (str(result.folder), run_id))
            conn.commit()
    return result


def merge_internal(target: Tally, internal: Tally) -> None:
    """Add the database's own checks to a dataset's tally. A finding the provider sample already reported for the
    same entity, field and kind is not added twice: the provider's answer is the more direct evidence (5 Oct 2026:
    three NS fixtures were listed both as provider lag, from the sample, and as our staleness, from the database)."""
    target.checked += internal.checked
    target.matched += internal.matched
    known = {(f.entity, f.field, f.kind) for f in target.findings}
    kept: dict[tuple[str, str, str], int] = {}
    for f in internal.findings:
        key = (f.field, f.kind.value, f.severity.value)
        kept[key] = kept.get(key, 0) + 1
        if (f.entity, f.field, f.kind) not in known:
            target.add(f)
    for key, n in internal.counts.items():
        hidden = n - kept.get(key, 0)
        if hidden > 0:
            target.counts[key] = target.counts.get(key, 0) + hidden
    target.notes.extend(f"internal {n}" for n in internal.notes)


def summary_of(result: AuditResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id, "started_at": result.started_at.isoformat(), "requests": result.requests,
        "stopped": result.stopped, "failures": result.failures[:50],
        "matrix": result.matrix(),
        "datasets": {name: t.summary() for name, t in sorted(result.tallies.items())},
        "freshness": [f.as_dict() for f in result.freshness],
        "gate": result.gate.as_dict(),
    }


def _persist(conn: psycopg.Connection, result: AuditResult, status: str) -> None:
    rows = []
    for t in result.tallies.values():
        for f in sorted(t.findings, key=lambda f: SEVERITY_ORDER[f.severity]):
            rows.append((result.run_id, f.dataset, f.entity, f.field, f.kind.value, f.severity.value, f.api, f.db,
                         f.note))
    with conn.cursor() as cur:
        if rows:
            cur.executemany("INSERT INTO audit.truth_findings (run_id, dataset, entity, field, kind, severity, "
                            "api_value, db_value, note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        cur.execute("UPDATE audit.truth_runs SET finished_at = now(), status = %s, requests = %s, sample = %s, "
                    "summary = %s WHERE id = %s",
                    (status, result.requests, Json(result.sample.as_dict()), Json(_jsonable(summary_of(result))),
                     result.run_id))
    conn.commit()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def write_report(result: AuditResult, out_root: Path) -> Path:
    folder = out_root / f"{result.started_at:%Y%m%dT%H%M%SZ}-truth-{result.run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    summary = summary_of(result)
    (folder / "summary.json").write_text(json.dumps(summary, indent=1, default=str, sort_keys=True))
    findings = [f.as_dict() for t in result.tallies.values() for f in t.findings]
    (folder / "findings.json").write_text(json.dumps(findings, indent=1, default=str))
    (folder / "sample.json").write_text(json.dumps(result.sample.as_dict(), indent=1, default=str))
    (folder / "REPORT.md").write_text(render_markdown(summary, findings))
    return folder
