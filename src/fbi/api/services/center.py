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
    CompetitionReference,
    CompetitionTable,
    FormMatch,
    H2HMatch,
    Leader,
    LeaderList,
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
    MatchFacts,
    PlayerAbsence,
    PlayerDetail,
    PlayerLine,
    PlayerMatch,
    PlayerSeason,
    PlayerSidelined,
    PlayerSummary,
    PlayerTransfer,
    PlayerTrophy,
    Provenance,
    ProviderPrediction,
    ProviderPredictionView,
    SeasonRound,
    SeasonStage,
    Side,
    StandingLine,
    StandingsTable,
    TableRow,
    TableSplit,
    TeamForm,
    TeamLineup,
    TeamStatLine,
)
from fbi.api.envelope import DataStatus, Envelope, Section, listing, ok, section, unavailable
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one, fetch_value
from fbi.api.repositories import center as repo
from fbi.api.services.live_quality import completeness
from fbi.competitions.phases import VERSION as PHASES_VERSION
from fbi.competitions.phases import TableMap, current_stage, phase_of, stage_of
from fbi.competitions.tables import load_season, match_tables, newest_maps
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
    standings, no_table, standing_tables = _match_standings(conn, fx)
    facts_row = fetch_one(conn, repo.FIXTURE_FACTS, f)
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
        standings=_sec(standings, no_table),
        standings_tables=standing_tables,
        facts=MatchFacts(**facts_row) if facts_row else None,
        form=section(forms) if any(t.matches for t in forms) else section(
            forms, status=DataStatus.EMPTY, reason="Neither team has a finished match with a result before this one."),
        h2h=_sec(h2h, "No previous meeting with a result is stored."),
        live_states=_sec(states, "No in-play state was captured for this match." if played else not_yet),
        live_odds=_sec(quotes, "No in-play price was captured for this match: the provider prices only some "
                               "matches in play, and capture began on 30 Sep 2026." if played else not_yet),
        live_movement=_sec(moves, "No in-play price movement recorded." if played else not_yet),
    )
    return ok(body)


def _match_standings(conn: Conn, fx: Row) -> tuple[list[StandingLine], str, list[StandingsTable]]:
    """Both teams' rows from the table that ranks this match's stage (``fbi.competitions``): a
    Clausura match is shown with the Clausura table, a knock-out round with its phase's league table,
    a match between two groups with each team's group. Never a row from another phase's table."""
    cs = int(fx["competition_season_id"])
    home, away = int(fx["home_team_id"]), int(fx["away_team_id"])
    stage = stage_of(fx.get("round"))
    found = match_tables(conn, cs, fx.get("round"), fx["kickoff_at"], home, away)
    if found is None:
        if not fetch_value(conn, repo.SEASON_HAS_TABLE, {"cs": cs}):
            return [], "No league table is stored for this competition-season (cups often have none).", []
        return [], (f"No stored table ranks this match's stage ({stage or 'no round label'}): the provider tables "
                    "each phase and group apart, and none of them covers this round. A table of another phase is "
                    "never shown in its place."), []
    rows = {(int(r["team_id"]), str(r["group_key"])): r
            for r in fetch_all(conn, repo.STANDING_ROWS, {"cs": cs, "at": found.snapshot_at, "teams": [home, away]})}
    checked = fetch_value(conn, repo.TABLE_CHECKED, {"cs": cs})
    state, reason = table_reason(found.snapshot_at, found.last_finished_before, checked, None)
    lines = []
    sides: tuple[tuple[Side, int], ...] = (("home", home), ("away", away))
    for side, team in sides:
        key = found.choice.keys.get(team)
        r = rows.get((team, key)) if key is not None else None
        if key is None or r is None:
            continue
        m = found.maps[key]
        lines.append(StandingLine(
            side=side, team=r["team"], rank=r["rank"], points=r["points"], played=r["played"], wins=r["wins"],
            draws=r["draws"], losses=r["losses"], goals_for=r["goals_for"], goals_against=r["goals_against"],
            form=r["form"], group=r["group"], snapshot_at=found.snapshot_at,
            before_kickoff=found.snapshot_at <= fx["kickoff_at"], description=r["description"], checked_at=checked,
            table_state=state.value, table_reason=reason, table=m.label, table_key=key, table_kind=m.kind,
            table_teams=m.rows, stage=m.stage, phase=m.phase, fixture_stage=stage or None,
            selection=found.choice.reason, team_logo=r["team_logo"]))
    keys = list(dict.fromkeys(found.choice.keys.values()))
    full: dict[str, list[TableRow]] = {}
    for r in fetch_all(conn, repo.COMPETITION_TABLE, {"cs": cs, "at": found.snapshot_at}):
        if r["group_key"] in keys:
            full.setdefault(str(r["group_key"]), []).append(_table_row(r))
    tables = [StandingsTable(key=k, label=found.maps[k].label, stage=found.maps[k].stage,
                             stages=list(found.maps[k].stages), phase=found.maps[k].phase, kind=found.maps[k].kind,
                             method=found.maps[k].method, agreement=f"{found.maps[k].agree}/{found.maps[k].counted}",
                             note=found.maps[k].note, is_current=False, rows=full.get(k, [])) for k in keys]
    return lines, "No row for either team in the table of this match's stage.", tables


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
    checks = {str(c["feed"]): c["checked_at"] for c in fetch_all(
        conn, repo.PERSON_CHECKS, {"key": f"player:{r['provider_player_id']}"})}
    provenance: dict[str, Provenance] = {}
    lists: dict[str, list[Row]] = {}
    for name, sql, source, feed in (("transfers", repo.PLAYER_TRANSFERS, "API-Football /transfers", None),
                                    ("sidelined", repo.PLAYER_SIDELINED, "API-Football /sidelined",
                                     "sidelined_players"),
                                    ("trophies", repo.PLAYER_TROPHIES, "API-Football /trophies", "trophies_players")):
        rows = fetch_all(conn, sql, pid)
        lists[name] = rows
        first = rows[0] if rows else {}
        if rows or (feed and checks.get(feed)):
            provenance[name] = Provenance(source=source, observed_at=first.get("observed_at"),
                                          payload_hash=first.get("payload_hash"),
                                          normalizer_version=first.get("normalizer_version"),
                                          checked_at=checks.get(feed) if feed else None)
    drop = ("observed_at", "payload_hash", "normalizer_version")
    transfers = [PlayerTransfer(**_clean(x, drop)) for x in lists["transfers"]]
    sidelined = [PlayerSidelined(**_clean(x, drop)) for x in lists["sidelined"]]
    trophies = [PlayerTrophy(**_clean(x, drop)) for x in lists["trophies"]]
    return ok(PlayerDetail(
        player=PlayerSummary(**r), **extra,
        seasons=_sec(seasons, "No match statistics are stored for this player."),
        matches=_sec(matches, "No match statistics are stored for this player."),
        absences=_sec(absences, "No injury or suspension is recorded for this player."),
        transfers=_sec(transfers, "No transfer is recorded for this player." if "transfers" in provenance
                       else "The provider's transfers have not been read for this player yet."),
        sidelined=_sec(sidelined, "The provider lists no period out for this player." if "sidelined" in provenance
                       else "The provider's sidelined list has not been read for this player yet."),
        trophies=_sec(trophies, "The provider lists no trophy for this player." if "trophies" in provenance
                      else "The provider's trophies have not been read for this player yet."),
        provenance=provenance,
    ))


def competition_reference(conn: Conn, competition_id: int, *, season: int | None = None,
                          at: datetime | None = None) -> Envelope[CompetitionReference | None]:
    """The provider's top scorers, assists and cards and the round calendar of a competition season."""
    seasons = fetch_all(conn, repo.REFERENCE_SEASONS, {"c": competition_id})
    chosen = next((r for r in seasons if season is None or int(r["season"]) == season), None)
    if chosen is None:
        return unavailable(None, f"No season {season} is stored for this competition." if season
                           else "No season is stored for this competition.", status=DataStatus.EMPTY)
    cs = {"cs": int(chosen["id"])}
    by_list: dict[str, list[Row]] = {}
    for row in fetch_all(conn, repo.COMPETITION_LEADERS, cs):
        by_list.setdefault(str(row["list"]), []).append(row)
    lists: list[LeaderList] = []
    for name in ("topscorers", "topassists", "topyellowcards", "topredcards"):
        rows = by_list.get(name)
        if not rows:
            continue
        first = rows[0]
        lists.append(LeaderList(
            kind=name,
            rows=[Leader(**_clean(x, ("list", "observed_at", "payload_hash", "normalizer_version"))) for x in rows],
            provenance=Provenance(source=f"API-Football /players/{name}", observed_at=first["observed_at"],
                                  payload_hash=first["payload_hash"], normalizer_version=first["normalizer_version"])))
    current_row = fetch_one(conn, repo.CURRENT_ROUNDS, cs)
    current = list(current_row["rounds"]) if current_row and current_row["rounds"] else []
    round_rows = fetch_all(conn, repo.COMPETITION_ROUNDS, cs)
    rounds = [SeasonRound(ordinal=int(x["ordinal"]), round=str(x["round"]), stage=stage_of(str(x["round"])),
                          phase=phase_of(str(x["round"])), dates=list(x["dates"] or []),
                          is_current=str(x["round"]) in current) for x in round_rows]
    provenance = None
    if round_rows:
        provenance = Provenance(source="API-Football /fixtures/rounds?dates=true",
                                observed_at=round_rows[0]["observed_at"], payload_hash=round_rows[0]["payload_hash"],
                                normalizer_version=round_rows[0]["normalizer_version"])
    return ok(CompetitionReference(
        competition_id=competition_id, season=int(chosen["season"]),
        leaders=_sec(lists, "The provider's top scorers and cards have not been read for this season yet (or its "
                            "coverage has none)."),
        rounds=_sec(rounds, "The provider's round calendar has not been read for this season yet."),
        rounds_provenance=provenance, current_rounds=current))


def provider_prediction(conn: Conn, fixture_id: int) -> Envelope[ProviderPredictionView | None]:
    """Admin only: the provider's own forecast of a match, every version kept, labelled as the provider's."""
    fx = fetch_one(conn, "SELECT provider_fixture_id FROM core.fixtures WHERE id = %(f)s", {"f": fixture_id})
    if fx is None:
        return unavailable(None, f"No fixture {fixture_id} is stored.", status=DataStatus.EMPTY)
    history = [ProviderPrediction(**x) for x in fetch_all(conn, repo.PROVIDER_PREDICTIONS, {"f": fixture_id})]
    checks = int(fetch_value(conn, repo.PREDICTION_CHECKS, {"pf": str(fx["provider_fixture_id"])}) or 0)
    view = ProviderPredictionView(fixture_id=fixture_id, history=history, checks=checks)
    if not history:
        return unavailable(view, "The provider's prediction has not been read for this match "
                                 + ("(asked, nothing returned)." if checks else "yet (it is asked 48 h, 24 h and 3 h "
                                                                                 "before kick-off)."),
                           status=DataStatus.EMPTY)
    return ok(view)


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
    """A competition season's tables, each kept apart and mapped to the stage it ranks (its newest
    season with a table, or the season asked): Apertura and Clausura, groups, conferences, a ranking
    of third-placed teams, an annual aggregate - never one table built from all of them."""
    seasons = fetch_all(conn, repo.COMPETITION_SEASONS, {"c": competition_id})
    chosen = next((r for r in seasons if season is None or int(r["season"]) == season), None)
    newest = None
    if chosen is not None:
        structure = load_season(conn, int(chosen["id"]))
        newest = newest_maps(conn, structure)
    if chosen is None or newest is None:
        return unavailable(None, "No league table is stored for this competition"
                                 + (f" in {season}" if season else "") + " (cups and friendlies usually have none).",
                           status=DataStatus.EMPTY)
    at, maps = newest
    rows_by_key: dict[str, list[TableRow]] = {}
    flat: list[TableRow] = []
    for r in fetch_all(conn, repo.COMPETITION_TABLE, {"cs": int(chosen["id"]), "at": at}):
        row = _table_row(r)
        rows_by_key.setdefault(str(r["group_key"]), []).append(row)
        flat.append(row)
    current = current_stage(structure.stages, now())
    order = {s.name: s.ordinal for s in structure.stages}

    def rank(m: TableMap) -> tuple[int, int, str]:
        first = min((order.get(x, 999) for x in m.stages), default=999)
        kind = {"full": 0, "group": 1, "ranking": 2, "aggregate": 3, "other": 4}[m.kind]
        return (first if m.stages else 1000, kind, m.key)

    tables = [StandingsTable(
        key=m.key, label=m.label, stage=m.stage, stages=list(m.stages), phase=m.phase, kind=m.kind, method=m.method,
        agreement=f"{m.agree}/{m.counted}", note=m.note,
        is_current=current is not None and m.stage == current.name,
        rows=rows_by_key.get(m.key, [])) for m in sorted(maps, key=rank)]
    per_stage = {s.name: sum(1 for m in maps if m.stage == s.name) for s in structure.stages}
    last_finished: dict[str, datetime] = {}
    for match in structure.matches:
        if match.finished and (match.stage not in last_finished or match.kickoff > last_finished[match.stage]):
            last_finished[match.stage] = match.kickoff
    stages = [SeasonStage(name=s.name, phase=s.phase, kind=s.kind, first_kickoff=s.first_kickoff,
                          last_kickoff=s.last_kickoff, fixtures=s.fixtures, finished=s.finished,
                          last_finished=last_finished.get(s.name),
                          tables=per_stage.get(s.name, 0), is_current=current is not None and s.name == current.name)
              for s in structure.stages]
    body = CompetitionTable(
        competition_id=competition_id, season=int(chosen["season"]), snapshot_at=at,
        seasons=[int(r["season"]) for r in seasons], stages=stages, tables=tables, mapping_version=PHASES_VERSION,
        rows=flat)
    return ok(body, data_as_of=at)


def _split(r: Row, side: str) -> TableSplit | None:
    if r.get(f"{side}_played") is None:
        return None
    return TableSplit(**{k: r.get(f"{side}_{k}") for k in ("played", "wins", "draws", "losses", "goals_for",
                                                          "goals_against")})


def _table_row(r: Row) -> TableRow:
    return TableRow(rank=r["rank"], team_id=r["team_id"], team=r["team"], played=r["played"], wins=r["wins"],
                    draws=r["draws"], losses=r["losses"], goals_for=r["goals_for"], goals_against=r["goals_against"],
                    points=r["points"], form=r["form"], group=r["group"], team_logo=r["team_logo"],
                    goals_diff=r["goals_diff"], description=r["description"], zone_status=r["zone_status"],
                    home=_split(r, "home"), away=_split(r, "away"))
