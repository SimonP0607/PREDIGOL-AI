"""Assemble the Match Center detail, the Live board, Players and the Admin view."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fbi.api.contracts.center import (
    Absence,
    AdminCount,
    AdminError,
    AdminOverview,
    BackfillProgress,
    BackupFile,
    CompetitionTable,
    FormMatch,
    H2HMatch,
    LineupPlayer,
    LiveBoard,
    LiveCompleteness,
    LiveMatch,
    LiveMove,
    LiveQuote,
    LiveState,
    LiveTeam,
    MatchCenter,
    MatchEvent,
    PlayerAbsence,
    PlayerDetail,
    PlayerLine,
    PlayerMatch,
    PlayerSeason,
    PlayerSummary,
    StandingLine,
    TableRow,
    TeamForm,
    TeamLineup,
    TeamStatLine,
)
from fbi.api.envelope import DataStatus, Envelope, Section, listing, ok, section, unavailable
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one
from fbi.api.repositories import center as repo
from fbi.api.services.live_quality import completeness
from fbi.core.clock import now
from fbi.truth.freshness import table_reason

STALE_AFTER = timedelta(minutes=3)
PLAYER_WINDOW = timedelta(days=400)
ACTIVE_WINDOW = timedelta(days=30)
LIVE_ODDS_WINDOW = timedelta(hours=4)


def _sec[T](items: list[T], empty: str, *, status: DataStatus = DataStatus.EMPTY) -> Section[list[T]]:
    return section(items) if items else section(items, status=status, reason=empty)


def _clean(row: Row, drop: tuple[str, ...] = ()) -> Row:
    return {k: v for k, v in row.items() if k not in drop}


# ── Match Center ───────────────────────────────────────────────────────────

def match_center(conn: Conn, fixture_id: int) -> Envelope[MatchCenter | None]:
    fx = fetch_one(conn, repo.FIXTURE, {"f": fixture_id})
    if fx is None:
        return unavailable(None, f"No fixture {fixture_id} is stored.", status=DataStatus.EMPTY)
    f = {"f": fixture_id}
    played = fx["status_group"] in ("live", "finished")
    not_yet = "The match has not started: nothing of this kind exists before kick-off."

    stats = [TeamStatLine(**_clean(r, ("goals_prevented",))) for r in fetch_all(conn, repo.TEAM_STATS, f)]
    events = [MatchEvent(**r) for r in fetch_all(conn, repo.EVENTS, f)]
    lineup_rows = fetch_all(conn, repo.LINEUPS, f)
    players_by_side: dict[str, list[LineupPlayer]] = {}
    for r in fetch_all(conn, repo.LINEUP_PLAYERS, f):
        players_by_side.setdefault(r.pop("side"), []).append(LineupPlayer(**r))
    lineups = [TeamLineup(**r, players=players_by_side.get(r["side"], [])) for r in lineup_rows]
    player_lines = [PlayerLine(**r) for r in fetch_all(conn, repo.PLAYER_STATS, f)]
    absences = [Absence(**r) for r in fetch_all(conn, repo.ABSENCES, {
        "f": fixture_id, "home_pid": fx["home_pid"], "away_pid": fx["away_pid"]})]
    ctx = {"cs": fx["competition_season_id"], "home": fx["home_team_id"], "away": fx["away_team_id"],
           "ko": fx["kickoff_at"]}
    standings = []
    for r in fetch_all(conn, repo.STANDINGS, ctx):
        last = r.pop("last_finished_before")
        r.pop("provider_updated_at", None)
        state, reason = table_reason(r["snapshot_at"], last, r["checked_at"], None)
        standings.append(StandingLine(**r, table_state=state.value, table_reason=reason))
    standings.sort(key=lambda s: 0 if s.side == "home" else 1)
    forms: list[TeamForm] = []
    for side, team_id, name in (("home", fx["home_team_id"], fx["home"]), ("away", fx["away_team_id"], fx["away"])):
        rows = fetch_all(conn, repo.FORM, {"team": team_id, "ko": fx["kickoff_at"]})
        matches = [FormMatch(**r, result="W" if r["goals_for"] > r["goals_against"]
                             else "D" if r["goals_for"] == r["goals_against"] else "L") for r in rows]
        forms.append(TeamForm(side=side, team=name, matches=matches))  # type: ignore[arg-type]
    h2h = [H2HMatch(**r) for r in fetch_all(conn, repo.H2H, ctx)]
    states = [LiveState(**r) for r in fetch_all(conn, repo.LIVE_STATES, f)]
    since = fx["kickoff_at"] - timedelta(minutes=30)
    quotes = [LiveQuote(**r) for r in fetch_all(conn, repo.LIVE_LATEST_QUOTES, {"f": fixture_id, "since": since})]
    quotes.sort(key=lambda q: (q.market_key is None, q.market_key or "", q.provider_bet_id, q.line, q.selection))
    moves = [LiveMove(**r) for r in fetch_all(conn, repo.LIVE_MOVEMENT, {"f": fixture_id, "limit": 200})]

    no_detail = ("No detail payload for this match yet: it arrives while the match is played "
                 "(live follow) or with the post-match detail backfill.")
    body = MatchCenter(
        fixture_id=fixture_id,
        status_group=fx["status_group"],
        statistics=_sec(stats, no_detail if played else not_yet),
        events=_sec(events, ("No event recorded." if played else not_yet)),
        lineups=_sec(lineups, "Line-ups are published about an hour before kick-off; none is stored for this match."),
        players=_sec(player_lines, no_detail if played else not_yet),
        absences=_sec(absences, "No injury or suspension report is stored for this match. That is not "
                                "the same as nobody being absent."),
        standings=_sec(standings, "No league table is stored for this competition-season (cups often have none)."),
        form=section(forms) if any(t.matches for t in forms) else section(
            forms, status=DataStatus.EMPTY, reason="Neither team has a finished match with a result before this one."),
        h2h=_sec(h2h, "No previous meeting with a result is stored."),
        live_states=_sec(states, "No in-play state was captured for this match." if played else not_yet),
        live_odds=_sec(quotes, "No in-play price was captured for this match: the provider prices only some "
                               "matches in play, and capture began on 30 Sep 2026." if played else not_yet),
        live_movement=_sec(moves, "No in-play price movement recorded." if played else not_yet),
    )
    return ok(body)


# ── Live board ─────────────────────────────────────────────────────────────

def live_board(conn: Conn, *, at: datetime | None = None) -> Envelope[LiveBoard]:
    moment = at or now()
    rows = fetch_all(conn, repo.LIVE_BOARD, {"at": moment})
    ids = [int(r["fixture_id"]) for r in rows]
    events: dict[int, list[MatchEvent]] = {}
    stats: dict[int, list[TeamStatLine]] = {}
    quotes: dict[int, list[LiveQuote]] = {}
    if ids:
        for r in fetch_all(conn, repo.LIVE_BOARD_EVENTS, {"ids": ids}):
            events.setdefault(int(r.pop("fixture_id")), []).append(MatchEvent(**r))
        for r in fetch_all(conn, repo.LIVE_BOARD_STATS, {"ids": ids}):
            stats.setdefault(int(r.pop("fixture_id")), []).append(TeamStatLine(**_clean(r, ("goals_prevented",))))
        for r in fetch_all(conn, repo.LIVE_BOARD_ODDS, {"ids": ids, "at": moment}):
            quotes.setdefault(int(r.pop("fixture_id")), []).append(LiveQuote(**r))
    matches: list[LiveMatch] = []
    for r in rows:
        feed_at, odds_at = r["feed_at"], r["odds_at"]
        # The fixture feed wins when it is current AND says the match has started: it
        # lags kick-off by up to a minute, and an 'NS' from it is staler news than an
        # odds feed already pricing the match in play.
        feed_started = r["feed_status"] not in (None, "NS", "TBD")
        use_feed = feed_at is not None and (odds_at is None or (
            feed_started and feed_at >= odds_at - timedelta(seconds=90)))
        state_at = feed_at if use_feed else odds_at
        age = int((moment - state_at).total_seconds())
        fid = int(r["fixture_id"])
        q = sorted(quotes.get(fid, []), key=lambda x: (x.market_key or "", x.line, x.selection))
        elapsed = r["feed_elapsed"] if use_feed else r["odds_elapsed"]
        gh = r["feed_gh"] if use_feed else r["odds_gh"]
        ga = r["feed_ga"] if use_feed else r["odds_ga"]
        fx_events, fx_stats = events.get(fid, []), stats.get(fid, [])
        score, level, signals = completeness(
            goals_home=gh, goals_away=ga, elapsed=elapsed, events=len(fx_events), stats=len(fx_stats),
            lineups=bool(r.get("has_lineups")), players=bool(r.get("has_player_stats")),
            live_quotes=sum(1 for x in q if x.odds is not None), markets_offered=r["markets_offered"])
        matches.append(LiveMatch(
            fixture_id=fid, kickoff_at=r["kickoff_at"], competition=r["competition"], country=r["country"],
            competition_id=r.get("competition_id"), competition_logo=r.get("competition_logo"),
            competition_flag=r.get("competition_flag"),
            home=LiveTeam(id=r["home_id"], name=r["home_name"], logo_url=r.get("home_logo")),
            away=LiveTeam(id=r["away_id"], name=r["away_name"], logo_url=r.get("away_logo")),
            status=(r["feed_status"] if use_feed else r["odds_status"]) or "?",
            elapsed=elapsed,
            extra=r["feed_extra"] if use_feed else None,
            goals_home=gh,
            goals_away=ga,
            state_at=state_at, state_source="fixture_feed" if use_feed else "odds_feed", state_age_seconds=age,
            odds_feed_at=odds_at, markets_offered=r["markets_offered"], values_suspended=r["values_suspended"],
            events=fx_events, statistics=fx_stats, main_odds=q,
            data_status="stale" if age > STALE_AFTER.total_seconds() else ("ok" if odds_at else "no_odds"),
            has_lineups=bool(r.get("has_lineups")), has_player_stats=bool(r.get("has_player_stats")),
            completeness=LiveCompleteness(score=score, level=level, signals=signals),
        ))
    # Richest first: the matches we can show most of lead the board; within a level the
    # board keeps its competition order (tier, then name) and kick-off.
    order = {m.fixture_id: i for i, m in enumerate(matches)}
    matches.sort(key=lambda m: (-(m.completeness.score if m.completeness else 0), order[m.fixture_id]))
    feeds = fetch_one(conn, repo.LIVE_FEEDS, {"at": moment}) or {}
    board = LiveBoard(matches=matches, followed_by_fixture_feed=sum(1 for m in matches if m.state_source ==
                                                                    "fixture_feed"),
                      priced_by_odds_feed=int(feeds.get("priced") or 0),
                      last_fixture_feed_at=feeds.get("fixture_feed_at"), last_odds_feed_at=feeds.get("odds_feed_at"))
    if not matches:
        return unavailable(board, "No tracked match is in play right now.", status=DataStatus.EMPTY, count=0)
    return ok(board, count=len(matches))


# ── Players ────────────────────────────────────────────────────────────────

def players(conn: Conn, *, q: str | None, team_id: int | None, limit: int, offset: int,
            at: datetime | None = None) -> Envelope[list[PlayerSummary]]:
    moment = at or now()
    params: dict[str, Any] = {"since": moment - PLAYER_WINDOW, "limit": limit, "offset": offset}
    if q and q.strip():
        rows = fetch_all(conn, repo.PLAYERS_SEARCH, {**params, "q": f"%{q.strip()}%"})
        empty = f"No stored player matches “{q.strip()}”."
    elif team_id is not None:
        rows = fetch_all(conn, repo.PLAYERS_OF_TEAM, {**params, "team": team_id})
        empty = "No player has a stored appearance for this team in the last 400 days."
    else:
        rows = fetch_all(conn, repo.PLAYERS_ACTIVE, {**params, "recent": moment - ACTIVE_WINDOW, "at": moment})
        empty = "No player statistics were stored for matches in the last 30 days."
    return listing([PlayerSummary(**r) for r in rows], empty_reason=empty, limit=limit, offset=offset)


def player(conn: Conn, player_id: int, *, at: datetime | None = None) -> Envelope[PlayerDetail | None]:
    moment = at or now()
    r = fetch_one(conn, repo.PLAYER, {"id": player_id, "since": moment - PLAYER_WINDOW})
    if r is None:
        return unavailable(None, f"No player {player_id} is stored.", status=DataStatus.EMPTY)
    extra = {k: r.pop(k) for k in ("firstname", "lastname", "height_cm", "weight_kg")}
    pid = {"pid": r["provider_player_id"]}
    seasons = [PlayerSeason(**s) for s in fetch_all(conn, repo.PLAYER_SEASONS, pid)]
    matches = [PlayerMatch(**m) for m in fetch_all(conn, repo.PLAYER_MATCHES, pid)]
    absences = [PlayerAbsence(**a) for a in fetch_all(conn, repo.PLAYER_ABSENCES, pid)]
    return ok(PlayerDetail(
        player=PlayerSummary(**r), **extra,
        seasons=_sec(seasons, "No match statistics are stored for this player."),
        matches=_sec(matches, "No match statistics are stored for this player."),
        absences=_sec(absences, "No injury or suspension is recorded for this player."),
    ))


# ── Admin ──────────────────────────────────────────────────────────────────

def _backup_dirs() -> list[Path]:
    raw = os.environ.get("FBI_BACKUP_DIRS")
    if raw:
        return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    root = Path(__file__).resolve().parents[4]
    return [Path.home() / "backups", root / "data" / "backups"]


def backups(limit: int = 15) -> list[BackupFile]:
    found: list[BackupFile] = []
    for d in _backup_dirs():
        if not d.is_dir():
            continue
        for p in d.iterdir():
            try:
                st = p.stat()
            except OSError:
                continue
            if p.is_dir():
                size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            elif p.suffix in (".dump", ".sql", ".gz", ".zst") or p.name.endswith(".dump.part"):
                size = st.st_size
            else:
                continue
            found.append(BackupFile(name=p.name, location=str(d), bytes=size,
                                    modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC)))
    found.sort(key=lambda b: b.modified_at, reverse=True)
    return found[:limit]


def admin_overview(conn: Conn, *, frontend_version: str | None = None) -> Envelope[AdminOverview]:
    from fbi.api.services.ops import VERSION, system_health
    from fbi.core.config import settings
    from fbi.core.version import code_version
    from fbi.providers.quota import read_usage

    moment = now()
    health = system_health(conn)
    worker = health.worker.model_dump(mode="json")
    beat = (worker.get("data") or {}).get("heartbeat") or {}
    jobs_next = {str(k): (str(v) if v else None) for k, v in (beat.get("jobs") or {}).items()}
    cfg = settings.api_football
    usage = read_usage(conn, budget=min(cfg.daily_budget, cfg.per_day_limit))
    quota = {"date": usage.quota_date.isoformat(), "spent": usage.spent, "budget": usage.budget,
             "remaining": usage.remaining, "plan_limit_per_day": cfg.per_day_limit,
             "ledger_api_calls": usage.ledger_api_calls,
             "provider_status": health.football_provider.model_dump(mode="json")}
    facts = fetch_one(conn, repo.ADMIN_FACTS) or {}
    progress = [BackfillProgress(**r) for r in fetch_all(conn, repo.BACKFILL_PROGRESS)]
    c = fetch_one(conn, repo.CAPTURES, {"at": moment}) or {}
    captures = [
        AdminCount(key="prematch_1h", label="Pre-match prices, last hour", value=c.get("prematch_1h"),
                   at=c.get("prematch_last")),
        AdminCount(key="prematch_24h", label="Pre-match prices, last 24 h", value=c.get("prematch_24h")),
        AdminCount(key="live_1h", label="In-play price changes, last hour", value=c.get("live_1h"),
                   at=c.get("live_last")),
        AdminCount(key="live_24h", label="In-play price changes, last 24 h", value=c.get("live_24h")),
        AdminCount(key="live_priced_now", label="Matches priced in play now", value=c.get("live_priced_now")),
        AdminCount(key="match_states_24h", label="Match states (fixture feed), last 24 h",
                   value=c.get("match_states_24h"),
                   at=c.get("match_states_last")),
        AdminCount(key="upcoming_7d", label="Fixtures in the next 7 days", value=c.get("upcoming_7d")),
        AdminCount(key="finished_total", label="Finished fixtures stored", value=c.get("finished_total")),
        AdminCount(key="awaiting_result", label="Kicked off > 3 h ago, still scheduled",
                   value=c.get("awaiting_result"),
                   note="should fall to 0 after the next results sync"),
        AdminCount(key="predictions_24h", label="Predictions written, last 24 h", value=c.get("predictions_24h")),
        AdminCount(key="candidates_24h", label="Pick candidates evaluated, last 24 h",
                   value=c.get("candidates_24h")),
    ]
    errors = [AdminError(**r) for r in fetch_all(conn, repo.RECENT_ERRORS, {"at": moment})]
    qrows = fetch_all(conn, repo.QUALITY_COUNTS)
    quality = [AdminCount(key=f"open_{r['severity']}", label=f"Open {r['severity']} issues", value=r["n"],
                          at=r["at"]) for r in
               sorted(qrows, key=lambda r: ["critical", "error", "warning", "info"].index(r["severity"])
                      if r["severity"] in ("critical", "error", "warning", "info") else 9)]
    files = backups()
    body = AdminOverview(
        backend_version=VERSION, code_version=code_version(), schema_revision=facts.get("schema_revision"),
        database_bytes=facts.get("database_bytes"), worker=worker, quota=quota, jobs_next=jobs_next,
        migration=_sec(progress, "No backfill task was ever seeded.", status=DataStatus.NOT_AVAILABLE),
        captures=captures,
        errors=_sec(errors, "No failed, partial, aborted or interrupted run in the last 72 hours."),
        quality=quality,
        backups=_sec(files, "No backup file found in " + ", ".join(str(d) for d in _backup_dirs()) + ".",
                     status=DataStatus.NOT_AVAILABLE),
    )
    del frontend_version
    return ok(body, data_as_of=moment)


def competition_table(conn: Conn, competition_id: int, *, season: int | None = None) -> Envelope[CompetitionTable | None]:
    """The latest league table we hold for a competition (its newest season with one, or the season asked)."""
    rows = fetch_all(conn, repo.COMPETITION_TABLE, {"c": competition_id, "season": season})
    if not rows:
        return unavailable(None, "No league table is stored for this competition"
                                 + (f" in {season}" if season else "") + " (cups and friendlies usually have none).",
                           status=DataStatus.EMPTY)
    first = rows[0]
    body = CompetitionTable(
        competition_id=competition_id, season=int(first["season"]), snapshot_at=first["snapshot_at"],
        rows=[TableRow(**{k: v for k, v in r.items() if k not in ("season", "snapshot_at")}) for r in rows],
    )
    return ok(body, data_as_of=first["snapshot_at"])
