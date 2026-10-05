"""Compare what the provider says now with what the database holds. Pure functions.

Each comparator reads the provider's JSON *directly*, field by field, instead of
through the ingestion parsers. That is deliberate: a comparison that reused the
parser would agree with the database whenever the parser was wrong in the same
way it was wrong when the row was written - which is exactly how 79 cancelled
fixtures came to be "scheduled" without any check noticing.

The database side arrives as plain dicts (one per row, column names as in the
queries in ``fbi.truth.audit``), so every comparator can be tested on two small
literals.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fbi.truth.findings import Finding, Kind, Severity, Tally

FINISHED = frozenset({"FT", "AET", "PEN"})
STATUS_GROUP: dict[str, str] = {
    "TBD": "scheduled", "NS": "scheduled",
    "1H": "live", "HT": "live", "2H": "live", "ET": "live", "BT": "live", "P": "live", "LIVE": "live",
    "INT": "live", "FT": "finished", "AET": "finished", "PEN": "finished", "SUSP": "postponed",
    "PST": "postponed", "CANC": "cancelled", "ABD": "cancelled", "AWD": "cancelled", "WO": "cancelled",
}
"""Restated here rather than imported, for the reason in the module docstring."""

PROVIDER_LAG_AFTER = timedelta(hours=3)
"""A match still NS this long after kick-off is the provider's lag, not ours: the
documentation says a result "can take up to 48 hours, depending on the competition"."""

STAT_COLUMNS: dict[str, str] = {
    "shots on goal": "shots_on_target", "shots off goal": "shots_off_target", "total shots": "shots",
    "blocked shots": "shots_blocked", "shots insidebox": "shots_inside_box",
    "shots outsidebox": "shots_outside_box", "fouls": "fouls", "corner kicks": "corners",
    "offsides": "offsides", "ball possession": "possession_pct", "yellow cards": "yellow_cards",
    "red cards": "red_cards", "goalkeeper saves": "saves", "total passes": "passes",
    "passes accurate": "passes_accurate", "expected_goals": "expected_goals",
    "expected goals": "expected_goals", "goals_prevented": "goals_prevented",
    "goals prevented": "goals_prevented",
}


# ── small readers ───────────────────────────────────────────────────────────


def _d(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _id(block: Any) -> int | None:
    v = _d(block).get("id")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().split(" ")[0].rstrip("%")
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _num(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().rstrip("%").strip()
    if not text:
        return None
    try:
        d = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _same_text(a: Any, b: Any) -> bool:
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold()


def _same_number(a: Any, b: Any) -> bool:
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return x is None and y is None
    return x == y


# ── fixtures and results ────────────────────────────────────────────────────


def compare_fixture(api: Mapping[str, Any], db: Mapping[str, Any] | None, *, now: datetime,
                    tally: Tally, results: Tally | None = None) -> None:
    """One /fixtures item against one core.fixtures row (+ its core.fixture_results row).

    Identity, competition, kick-off, status and round go to ``tally``; the score goes to
    ``results`` (when given), because a wrong score and a wrong round are not the same
    kind of problem and should not share a line of the report.
    """
    fx, league, teams = _d(api.get("fixture")), _d(api.get("league")), _d(api.get("teams"))
    pid = _id(fx)
    entity = f"fixture {pid} ({league.get('name')} {league.get('season')})"
    raw_short = _text(_d(fx.get("status")).get("short")) or ""
    short = raw_short.upper()
    api_group = STATUS_GROUP.get(short, "unknown")
    kickoff = _when(fx.get("date"))
    ds = "fixtures"

    if db is None:
        tally.compared()
        severity = Severity.HIGH
        if api_group == "finished":
            severity = Severity.CRITICAL
        tally.add(Finding.of(ds, entity, "fixture", Kind.MISSING_IN_DB, severity,
                             api=f"{short} {kickoff:%Y-%m-%d %H:%M}Z" if kickoff else short,
                             note="the provider lists this fixture for a season we track; we do not have it"))
        return

    before = tally.total_findings
    tally.compared()
    if (league.get("id"), league.get("season")) != (db.get("provider_league_id"), db.get("season")):
        tally.add(Finding.of(ds, entity, "competition", Kind.MISMATCH, Severity.HIGH,
                             api=f"{league.get('id')}/{league.get('season')}",
                             db=f"{db.get('provider_league_id')}/{db.get('season')}"))
    home, away = _id(teams.get("home")), _id(teams.get("away"))
    if (home, away) != (db.get("home_provider_id"), db.get("away_provider_id")):
        tally.add(Finding.of(ds, entity, "teams", Kind.MISMATCH, Severity.CRITICAL,
                             api=f"{home} v {away}", db=f"{db.get('home_provider_id')} v {db.get('away_provider_id')}",
                             note="the sides of a fixture are its identity"))
    db_kickoff = _when(db.get("kickoff_at"))
    if kickoff and db_kickoff and kickoff != db_kickoff:
        upcoming = kickoff > now
        tally.add(Finding.of(ds, entity, "kickoff_at", Kind.STALE if upcoming else Kind.MISMATCH,
                             Severity.HIGH if upcoming or abs((kickoff - db_kickoff).total_seconds()) > 3600
                             else Severity.MEDIUM,
                             api=f"{kickoff:%Y-%m-%d %H:%M}Z", db=f"{db_kickoff:%Y-%m-%d %H:%M}Z",
                             note=f"row last written {db.get('source_fetched_at') or db.get('updated_at')}"))
    _compare_status(entity, raw_short, short, api_group, kickoff, db, now, tally)
    if not _same_text(league.get("round"), db.get("round")) and _text(league.get("round")):
        tally.add(Finding.of(ds, entity, "round", Kind.MISMATCH, Severity.LOW,
                             api=league.get("round"), db=db.get("round")))
    venue = _id(fx.get("venue"))
    if venue is not None and db.get("venue_provider_id") not in (None, venue):
        tally.add(Finding.of(ds, entity, "venue", Kind.MISMATCH, Severity.LOW,
                             api=venue, db=db.get("venue_provider_id")))
    if tally.total_findings == before:
        tally.matched += 1
    if results is not None:
        compare_result(api, db, tally=results, now=now)


def _compare_status(entity: str, raw_short: str, short: str, api_group: str, kickoff: datetime | None,
                    db: Mapping[str, Any], now: datetime, tally: Tally) -> None:
    db_short = str(db.get("status_short") or "")
    db_group = str(db.get("status_group") or "")
    spelled = f" (the provider spells it {raw_short!r})" if raw_short and raw_short != short else ""
    expected_group = STATUS_GROUP.get(db_short.upper())
    if expected_group is not None and expected_group != db_group:
        tally.add(Finding.of("fixtures", entity, "status_group", Kind.INCONSISTENT, Severity.HIGH,
                             db=f"{db_short} -> {db_group}", api=f"{db_short.upper()} -> {expected_group}",
                             note="the stored group does not follow from the stored status" + spelled))
    if short == db_short.upper():
        if short in ("NS", "TBD") and kickoff is not None and now - kickoff > PROVIDER_LAG_AFTER:
            tally.add(Finding.of("fixtures", entity, "status_short", Kind.PROVIDER_LAG, Severity.INFO,
                                 api=short, db=db_short,
                                 note=f"kicked off {kickoff:%Y-%m-%d %H:%M}Z; the provider has not updated it "
                                      "yet (it can take up to 48 h for some competitions)"))
        return
    if api_group == "live" and db_group in ("live", "scheduled"):
        return  # a moving target: the live follower writes it every minute
    if api_group == "finished" and db_group != "finished":
        kind, severity, note = Kind.STALE, Severity.CRITICAL, f"played, stored as {db_short}" + spelled
    elif api_group in ("cancelled", "postponed") and db_group in ("scheduled", "live"):
        kind, severity, note = Kind.STALE, Severity.HIGH, f"{short}, stored as {db_short}" + spelled
    else:
        kind, severity, note = Kind.MISMATCH, Severity.HIGH, spelled.strip()
    tally.add(Finding.of("fixtures", entity, "status_short", kind, severity, api=raw_short, db=db_short, note=note))


def compare_result(api: Mapping[str, Any], db: Mapping[str, Any], *, tally: Tally, now: datetime) -> None:
    """The score. Only a finished match has one, on both sides."""
    fx, goals, score = _d(api.get("fixture")), _d(api.get("goals")), _d(api.get("score"))
    pid = _id(fx)
    short = (_text(_d(fx.get("status")).get("short")) or "").upper()
    entity = f"fixture {pid}"
    has_db = bool(db.get("has_result"))
    if short not in FINISHED:
        if has_db:
            tally.compared()
            tally.add(Finding.of("results", entity, "result", Kind.MISMATCH, Severity.CRITICAL,
                                 api=f"{short} (no result)", db=f"{db.get('goals_home')}-{db.get('goals_away')}",
                                 note="the database holds a score for a match the provider says was not played "
                                      "to a conclusion"))
        return
    tally.compared()
    gh, ga = _int(goals.get("home")), _int(goals.get("away"))
    if not has_db:
        parts = {k: (_int(_d(score.get(k)).get("home")), _int(_d(score.get(k)).get("away")))
                 for k in ("fulltime", "extratime")}
        above = [k for k, (h, a) in parts.items() if None not in (h, a, gh, ga)
                 and ((h or 0) > (gh or 0) or (a or 0) > (ga or 0))]
        if above:  # the writer's rule: no result rather than a wrong one (normalize.iter_results)
            tally.add(Finding.of("results", entity, "result", Kind.PROVIDER_CONTRADICTION, Severity.MEDIUM,
                                 api=f"{short} final {gh}-{ga}, " + ", ".join(
                                     f"{k} {parts[k][0]}-{parts[k][1]}" for k in above),
                                 db=f"{db.get('status_short')} (no result row)",
                                 note="the provider's score blocks contradict each other; no result is stored "
                                      "rather than a wrong one"))
            return
        tally.add(Finding.of("results", entity, "result", Kind.MISSING_IN_DB, Severity.CRITICAL,
                             api=f"{short} {gh}-{ga}", db=f"{db.get('status_short')} (no result row)"))
        return
    before = tally.total_findings
    pairs: list[tuple[str, tuple[int | None, int | None], tuple[Any, Any], Severity]] = [
        ("final", (gh, ga), (db.get("goals_home"), db.get("goals_away")), Severity.CRITICAL),
        ("halftime", (_int(_d(score.get("halftime")).get("home")), _int(_d(score.get("halftime")).get("away"))),
         (db.get("ht_goals_home"), db.get("ht_goals_away")), Severity.MEDIUM),
        ("extratime", (_int(_d(score.get("extratime")).get("home")), _int(_d(score.get("extratime")).get("away"))),
         (db.get("et_goals_home"), db.get("et_goals_away")), Severity.HIGH),
        ("penalty", (_int(_d(score.get("penalty")).get("home")), _int(_d(score.get("penalty")).get("away"))),
         (db.get("pen_home"), db.get("pen_away")), Severity.HIGH),
    ]
    ft = (_int(_d(score.get("fulltime")).get("home")), _int(_d(score.get("fulltime")).get("away")))
    # The writer ignores a stated fulltime greater than the final score (the provider
    # contradicting itself); expecting it here would report the rule as a mismatch.
    if not (ft[0] is not None and gh is not None and ft[1] is not None and ga is not None
            and (ft[0] > gh or ft[1] > ga)):
        pairs.append(("fulltime (90 min)", ft, (db.get("ft_goals_home"), db.get("ft_goals_away")),
                      Severity.CRITICAL))
    for name, a, b, severity in pairs:
        if tuple(a) != tuple(b):
            tally.add(Finding.of("results", entity, name, Kind.MISMATCH, severity,
                                 api=f"{a[0]}-{a[1]}", db=f"{b[0]}-{b[1]}"))
    if tally.total_findings == before:
        tally.matched += 1


# ── match detail: events, line-ups, statistics, player statistics ───────────


def _event_key(e: Mapping[str, Any]) -> tuple[Any, ...]:
    return (e.get("minute"), e.get("extra"), str(e.get("type") or "").casefold(),
            str(e.get("detail") or "").casefold(), e.get("team"), e.get("player"))


def api_events(api: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for e in _l(api.get("events")):
        if not isinstance(e, dict):
            continue
        t = _d(e.get("time"))
        minute = _int(t.get("elapsed"))
        if minute is None or minute < 0 or not _text(e.get("type")):
            continue  # the writer drops these too, and says so in its parse log
        extra = _int(t.get("extra"))
        out.append({"minute": minute, "extra": extra if extra is None or extra >= 0 else None,
                    "type": e.get("type"), "detail": e.get("detail"), "team": _id(e.get("team")),
                    "player": _id(e.get("player"))})
    return out


def compare_events(api: Mapping[str, Any], db_events: Sequence[Mapping[str, Any]],
                   coverage: Mapping[str, Any] | None, *, tally: Tally) -> None:
    pid = _id(api.get("fixture"))
    entity = f"fixture {pid}"
    if not isinstance(api.get("events"), list):
        return  # the provider sent no events block at all: nothing to hold us to
    a = Counter(_event_key(e) for e in api_events(api))
    b = Counter(_event_key({"minute": r.get("minute"), "extra": r.get("extra_minute"), "type": r.get("event_type"),
                            "detail": r.get("detail"), "team": r.get("provider_team_id"),
                            "player": r.get("provider_player_id")}) for r in db_events)
    tally.compared()
    if a == b:
        tally.matched += 1
        return
    if not b and a:
        tally.add(Finding.of("events", entity, "events", Kind.MISSING_IN_DB, Severity.MEDIUM,
                             api=f"{sum(a.values())} events", db="none", note=_detail_note(coverage)))
        return
    missing, extra = a - b, b - a
    if missing:
        tally.add(Finding.of("events", entity, "events", Kind.STALE if _fetched_early(coverage) else Kind.MISMATCH,
                             Severity.MEDIUM, api=f"{sum(missing.values())} not stored, e.g. {next(iter(missing))}",
                             db=f"{sum(b.values())} stored", note=_detail_note(coverage)))
    if extra:
        tally.add(Finding.of("events", entity, "events", Kind.MISSING_IN_API, Severity.LOW,
                             api=f"{sum(a.values())} listed", db=f"{sum(extra.values())} not listed any more, "
                             f"e.g. {next(iter(extra))}", note="the provider revised the timeline after we stored it"))


def _fetched_early(coverage: Mapping[str, Any] | None) -> bool:
    if not coverage:
        return False
    fetched, kickoff = _when(coverage.get("fetched_at")), _when(coverage.get("kickoff_at"))
    return bool(fetched and kickoff and fetched < kickoff + timedelta(hours=2, minutes=30))


def _detail_note(coverage: Mapping[str, Any] | None) -> str:
    if not coverage or coverage.get("fetched_at") is None:
        return "the match detail was never fetched"
    fetched, kickoff = _when(coverage.get("fetched_at")), _when(coverage.get("kickoff_at"))
    if fetched and kickoff:
        minutes = int((fetched - kickoff).total_seconds() // 60)
        return f"detail fetched {minutes} min after kick-off" + (" (before the match could end)"
                                                                 if minutes < 110 else "")
    return "detail fetched at an unknown time"


def compare_lineups(api: Mapping[str, Any], db_lineups: Sequence[Mapping[str, Any]],
                    db_players: Sequence[Mapping[str, Any]], *, home_provider_id: int | None,
                    tally: Tally) -> None:
    pid = _id(api.get("fixture"))
    blocks = [b for b in _l(api.get("lineups")) if isinstance(b, dict)]
    if not blocks:
        return
    by_side = {str(r.get("team_side")): r for r in db_lineups}
    for block in blocks:
        team = _id(block.get("team"))
        side = "home" if team == home_provider_id else "away"
        entity = f"fixture {pid} {side}"
        tally.compared()
        db = by_side.get(side)
        if db is None:
            tally.add(Finding.of("lineups", entity, "lineup", Kind.MISSING_IN_DB, Severity.MEDIUM,
                                 api=f"{block.get('formation')} with {len(_l(block.get('startXI')))} starters",
                                 db="none"))
            continue
        before = tally.total_findings
        if _text(block.get("formation")) and not _same_text(block.get("formation"), db.get("formation")):
            tally.add(Finding.of("lineups", entity, "formation", Kind.MISMATCH, Severity.LOW,
                                 api=block.get("formation"), db=db.get("formation")))
        coach = _id(block.get("coach"))
        if coach is not None and coach > 0 and coach != db.get("provider_coach_id"):
            tally.add(Finding.of("lineups", entity, "coach", Kind.MISMATCH, Severity.LOW,
                                 api=coach, db=db.get("provider_coach_id")))
        for flag, key in ((True, "startXI"), (False, "substitutes")):
            want = {_id(_d(p).get("player")) for p in _l(block.get(key))} - {None}
            have = {r.get("provider_player_id") for r in db_players
                    if r.get("team_side") == side and bool(r.get("is_starter")) is flag}
            if want != have:
                tally.add(Finding.of("lineups", entity, "starters" if flag else "substitutes", Kind.MISMATCH,
                                     Severity.MEDIUM, api=f"{len(want)} players, {len(want - have)} not stored",
                                     db=f"{len(have)} players, {len(have - want)} not listed"))
        if tally.total_findings == before:
            tally.matched += 1


def compare_team_stats(api: Mapping[str, Any], db_stats: Sequence[Mapping[str, Any]], *,
                       home_provider_id: int | None, coverage: Mapping[str, Any] | None,
                       tally: Tally) -> None:
    pid = _id(api.get("fixture"))
    blocks = [b for b in _l(api.get("statistics")) if isinstance(b, dict)]
    if not blocks:
        return
    by_side = {str(r.get("team_side")): r for r in db_stats}
    for block in blocks:
        side = "home" if _id(block.get("team")) == home_provider_id else "away"
        entity = f"fixture {pid} {side}"
        tally.compared()
        db = by_side.get(side)
        if db is None:
            tally.add(Finding.of("team_stats", entity, "statistics", Kind.MISSING_IN_DB, Severity.MEDIUM,
                                 api=f"{len(_l(block.get('statistics')))} values", db="none",
                                 note=_detail_note(coverage)))
            continue
        dropped = set(db.get("dropped_fields") or [])
        before = tally.total_findings
        for item in _l(block.get("statistics")):
            column = STAT_COLUMNS.get(str(_d(item).get("type") or "").strip().lower())
            if column is None or column in dropped:
                continue
            value = _d(item).get("value")
            if not _same_number(value, db.get(column)):
                kind = Kind.STALE if _fetched_early(coverage) else Kind.MISMATCH
                tally.add(Finding.of("team_stats", entity, column, kind,
                                     Severity.LOW if column in ("expected_goals", "goals_prevented") else Severity.MEDIUM,
                                     api=value, db=db.get(column), note=_detail_note(coverage)))
        if tally.total_findings == before:
            tally.matched += 1


PLAYER_FIELDS = (("minutes", ("games", "minutes")), ("goals", ("goals", "total")), ("assists", ("goals", "assists")),
                 ("yellow_cards", ("cards", "yellow")), ("red_cards", ("cards", "red")),
                 ("shots_total", ("shots", "total")), ("rating", ("games", "rating")))


def compare_player_stats(api: Mapping[str, Any], db_rows: Sequence[Mapping[str, Any]], *,
                         home_provider_id: int | None, tally: Tally) -> None:
    pid = _id(api.get("fixture"))
    blocks = [b for b in _l(api.get("players")) if isinstance(b, dict)]
    if not blocks:
        return
    db_by_player = {int(r["provider_player_id"]): r for r in db_rows if r.get("provider_player_id")}
    seen: set[int] = set()
    for block in blocks:
        side = "home" if _id(block.get("team")) == home_provider_id else "away"
        for item in _l(block.get("players")):
            player = _id(_d(item).get("player"))
            stats = _l(_d(item).get("statistics"))
            if player is None or player <= 0 or not stats:
                continue
            seen.add(player)
            entity = f"fixture {pid} {side} player {player}"
            tally.compared()
            db = db_by_player.get(player)
            if db is None:
                tally.add(Finding.of("player_stats", entity, "row", Kind.MISSING_IN_DB, Severity.LOW,
                                     api=_d(_d(item).get("player")).get("name"), db="none"))
                continue
            stat = _d(stats[0])
            before = tally.total_findings
            for column, (group, key) in PLAYER_FIELDS:
                value = _d(stat.get(group)).get(key)
                if not _same_number(value, db.get(column)):
                    tally.add(Finding.of("player_stats", entity, column, Kind.MISMATCH, Severity.LOW,
                                         api=value, db=db.get(column)))
            if tally.total_findings == before:
                tally.matched += 1
    extra = set(db_by_player) - seen
    if extra:
        tally.add(Finding.of("player_stats", f"fixture {pid}", "row", Kind.MISSING_IN_API, Severity.LOW,
                             db=f"{len(extra)} players stored that the provider no longer lists"))


# ── standings ───────────────────────────────────────────────────────────────


STANDING_NOT_STORED = ("goalsDiff", "status", "description", "home", "away", "update")


def api_standing_rows(api_body: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in _l(api_body.get("response")):
        league = _d(_d(entry).get("league"))
        for table in _l(league.get("standings")):
            for row in _l(table):
                if isinstance(row, dict) and _id(row.get("team")) is not None:
                    rows.append(row)
    return rows


def compare_standings(api_body: Mapping[str, Any], db_rows: Sequence[Mapping[str, Any]], *, label: str,
                      last_finished: datetime | None, now: datetime, tally: Tally,
                      stored_extended: bool = False, checked_at: datetime | None = None) -> None:
    """The provider's current table against our newest snapshot of it.

    ``db_rows`` is the newest snapshot only (every row sharing the latest snapshot_at).
    ``last_finished`` is the kick-off of the competition-season's last finished fixture:
    a snapshot taken before that match ended cannot reflect it, whatever it says.
    ``checked_at`` is when we last asked for the table: a row behind the provider's is the provider's lag when the
    provider's own update stamp is later than that ask (5 Oct 2026: twelve "stale" rows were tables the provider
    updated between our 05:47 ask and the audit's 06:30 one).
    """
    api_rows = api_standing_rows(api_body)
    if not api_rows:
        if db_rows:
            tally.add(Finding.of("standings", label, "table", Kind.MISSING_IN_API, Severity.LOW,
                                 db=f"{len(db_rows)} rows", note="the provider serves no table for this season now"))
        return
    snapshots = [d for d in (_when(r.get("snapshot_at")) for r in db_rows) if d is not None]
    snapshot = max(snapshots) if snapshots else None
    updates = [d for d in (_when(r.get("update")) for r in api_rows) if d is not None]
    api_update = max(updates) if updates else None
    if not db_rows:
        tally.compared(len(api_rows))
        tally.add(Finding.of("standings", label, "table", Kind.MISSING_IN_DB, Severity.MEDIUM,
                             api=f"{len(api_rows)} rows (updated {api_update})", db="no snapshot"))
        return
    if snapshot and last_finished and snapshot < last_finished + timedelta(hours=2):
        hours = (now - snapshot).total_seconds() / 3600
        tally.add(Finding.of("standings", label, "snapshot_at", Kind.STALE, Severity.MEDIUM,
                             api=f"provider update {api_update}", db=f"snapshot {snapshot:%Y-%m-%d %H:%M}Z",
                             note=f"taken before the last finished match ({last_finished:%Y-%m-%d %H:%M}Z) could "
                                  f"have ended; {hours:.0f} h old"))
    db_by_key = {(r.get("provider_team_id"), _text(r.get("group"))): r for r in db_rows}
    db_by_team: dict[Any, list[Mapping[str, Any]]] = {}
    for r in db_rows:
        db_by_team.setdefault(r.get("provider_team_id"), []).append(r)
    for row in api_rows:
        team = _id(row.get("team"))
        group = _text(row.get("group"))
        entity = f"{label} team {team} ({_d(row.get('team')).get('name')}){' ' + group if group else ''}"
        tally.compared()
        db = db_by_key.get((team, group))
        if db is None and len(db_by_team.get(team, [])) == 1 and len([r for r in api_rows
                                                                       if _id(r.get("team")) == team]) == 1:
            db = db_by_team[team][0]  # one row each side: the group label alone differs
        if db is None:
            tally.add(Finding.of("standings", entity, "row", Kind.MISSING_IN_DB, Severity.MEDIUM,
                                 api=f"rank {row.get('rank')}, {row.get('points')} pts",
                                 db="no row" if team not in db_by_team else
                                 f"{len(db_by_team[team])} row(s) in other groups",
                                 note="one team in two tables of the same season is stored once "
                                      "(the key has no group)" if team in db_by_team else ""))
            continue
        total = _d(row.get("all"))
        goals = _d(total.get("goals"))
        api_played, db_played = _int(total.get("played")), db.get("played")
        before = tally.total_findings
        row_update = _when(row.get("update")) or api_update
        if api_played is not None and isinstance(db_played, int) and api_played > db_played:
            if checked_at is not None and row_update is not None and row_update > checked_at:
                tally.add(Finding.of("standings", entity, "played", Kind.PROVIDER_LAG, Severity.INFO,
                                     api=api_played, db=db_played,
                                     note=f"the provider updated its table at {row_update:%Y-%m-%d %H:%M}Z, after our "
                                          f"last ask at {checked_at:%Y-%m-%d %H:%M}Z; the next refresh takes it"))
            else:
                tally.add(Finding.of("standings", entity, "played", Kind.STALE,
                                     Severity.HIGH if api_played - db_played >= 2 else Severity.MEDIUM,
                                     api=api_played, db=db_played, note="our table is behind the provider's"))
        else:
            for name, a, b in (("rank", row.get("rank"), db.get("rank")), ("points", row.get("points"), db.get("points")),
                               ("played", api_played, db_played), ("wins", total.get("win"), db.get("wins")),
                               ("draws", total.get("draw"), db.get("draws")),
                               ("losses", total.get("lose"), db.get("losses")),
                               ("goals_for", goals.get("for"), db.get("goals_for")),
                               ("goals_against", goals.get("against"), db.get("goals_against"))):
                if _int(a) != (b if isinstance(b, int) else _int(b)):
                    tally.add(Finding.of("standings", entity, name, Kind.MISMATCH, Severity.MEDIUM, api=a, db=b))
            if _text(row.get("form")) and not _same_text(row.get("form"), db.get("form")):
                tally.add(Finding.of("standings", entity, "form", Kind.MISMATCH, Severity.LOW,
                                     api=row.get("form"), db=db.get("form")))
        if tally.total_findings == before:
            tally.matched += 1
    if not stored_extended:
        present = [k for k in STANDING_NOT_STORED if any(k in r for r in api_rows)]
        if present:
            tally.add(Finding.of("standings", label, ",".join(present), Kind.NOT_STORED, Severity.LOW,
                                 api="sent for every row", db="no column",
                                 note="home/away split, the zone description and the provider's own update time "
                                      "are dropped at ingestion"))


# ── identities: teams, players, coaches, squads ─────────────────────────────


def compare_team(api_item: Mapping[str, Any] | None, db: Mapping[str, Any] | None, *, provider_team_id: int,
                 tally: Tally) -> None:
    entity = f"team {provider_team_id}"
    tally.compared()
    if api_item is None:
        tally.add(Finding.of("teams", entity, "team", Kind.MISSING_IN_API, Severity.LOW,
                             db=(db or {}).get("name"), note="the provider returned nothing for this id"))
        return
    team, venue = _d(api_item.get("team")), _d(api_item.get("venue"))
    if db is None:
        tally.add(Finding.of("teams", entity, "team", Kind.MISSING_IN_DB, Severity.MEDIUM, api=team.get("name")))
        return
    before = tally.total_findings
    checks: list[tuple[str, Any, Any, Severity]] = [
        ("name", team.get("name"), db.get("name"), Severity.LOW),
        ("country", team.get("country"), db.get("country"), Severity.LOW),
        ("founded", team.get("founded"), db.get("founded"), Severity.LOW),
        ("code", team.get("code"), db.get("short_name"), Severity.INFO),
        ("logo", team.get("logo"), db.get("logo_url"), Severity.INFO),
    ]
    for name, a, b, severity in checks:
        if a is None or a == "":
            continue
        if b is None or b == "":
            tally.add(Finding.of("teams", entity, name, Kind.MISSING_IN_DB, severity, api=a, db=None))
        elif not _same_text(a, b):
            tally.add(Finding.of("teams", entity, name, Kind.MISMATCH, severity, api=a, db=b))
    national = team.get("national")
    if isinstance(national, bool) and db.get("is_national") is not national:
        tally.add(Finding.of("teams", entity, "is_national", Kind.MISMATCH if db.get("is_national") is not None
                             else Kind.MISSING_IN_DB, Severity.MEDIUM, api=national, db=db.get("is_national"),
                             note="the competition scope and the rating weights read this flag"))
    vid = _id(venue)
    if vid is not None and db.get("venue_provider_id") not in (None, vid):
        tally.add(Finding.of("teams", entity, "venue", Kind.MISMATCH, Severity.LOW,
                             api=f"{vid} {venue.get('name')}", db=f"{db.get('venue_provider_id')} {db.get('venue_name')}"))
    elif vid is not None and db.get("venue_provider_id") is None:
        tally.add(Finding.of("teams", entity, "venue", Kind.MISSING_IN_DB, Severity.LOW, api=f"{vid} {venue.get('name')}"))
    if tally.total_findings == before:
        tally.matched += 1


def _measure(value: Any) -> int | None:
    """'185 cm' -> 185, '75 kg' -> 75, '185' -> 185."""
    return _int(value)


def compare_player(api_item: Mapping[str, Any] | None, db: Mapping[str, Any] | None, *, provider_player_id: int,
                   tally: Tally) -> None:
    entity = f"player {provider_player_id}"
    tally.compared()
    if api_item is None:
        tally.add(Finding.of("players", entity, "player", Kind.MISSING_IN_API, Severity.INFO,
                             db=(db or {}).get("name"), note="no season profile served for this player and season"))
        return
    player = _d(api_item.get("player"))
    if db is None:
        tally.add(Finding.of("players", entity, "player", Kind.MISSING_IN_DB, Severity.MEDIUM, api=player.get("name")))
        return
    before = tally.total_findings
    birth = _d(player.get("birth"))
    checks: list[tuple[str, Any, Any, Severity]] = [
        ("name", player.get("name"), db.get("name"), Severity.LOW),
        ("firstname", player.get("firstname"), db.get("firstname"), Severity.LOW),
        ("lastname", player.get("lastname"), db.get("lastname"), Severity.LOW),
        ("birth_date", _day(birth.get("date")), _day(db.get("birth_date")), Severity.MEDIUM),
        ("nationality", player.get("nationality"), db.get("nationality"), Severity.MEDIUM),
        ("height_cm", _measure(player.get("height")), db.get("height_cm"), Severity.LOW),
        ("weight_kg", _measure(player.get("weight")), db.get("weight_kg"), Severity.LOW),
    ]
    for name, a, b, severity in checks:
        if a is None or a == "":
            continue
        if b is None or b == "":
            tally.add(Finding.of("players", entity, name, Kind.MISSING_IN_DB, severity, api=a, db=None,
                                 note="the player profile was never fetched" if name in ("birth_date", "nationality")
                                 else ""))
        elif (isinstance(a, int | date) and a != b) or (isinstance(a, str) and not _same_text(a, b)):
            tally.add(Finding.of("players", entity, name, Kind.MISMATCH, severity, api=a, db=b))
    if tally.total_findings == before:
        tally.matched += 1


def compare_coach(api_item: Mapping[str, Any] | None, db: Mapping[str, Any] | None, *, provider_coach_id: int,
                  tally: Tally) -> None:
    entity = f"coach {provider_coach_id}"
    tally.compared()
    if api_item is None:
        tally.add(Finding.of("coaches", entity, "coach", Kind.MISSING_IN_API, Severity.INFO, db=(db or {}).get("name")))
        return
    if db is None:
        tally.add(Finding.of("coaches", entity, "coach", Kind.MISSING_IN_DB, Severity.LOW, api=api_item.get("name")))
        return
    before = tally.total_findings
    birth = _d(api_item.get("birth"))
    for name, a, b, severity in (("name", api_item.get("name"), db.get("name"), Severity.LOW),
                                 ("birth_date", _day(birth.get("date")), _day(db.get("birth_date")), Severity.LOW),
                                 ("nationality", api_item.get("nationality"), db.get("nationality"), Severity.LOW)):
        if a is None or a == "":
            continue
        if b is None or b == "":
            tally.add(Finding.of("coaches", entity, name, Kind.MISSING_IN_DB, severity, api=a))
        elif (isinstance(a, date) and a != b) or (isinstance(a, str) and not _same_text(a, b)):
            tally.add(Finding.of("coaches", entity, name, Kind.MISMATCH, severity, api=a, db=b))
    team = _id(api_item.get("team"))
    if team is not None and db.get("current_team_provider_id") not in (None, team):
        tally.add(Finding.of("coaches", entity, "current_team", Kind.STALE, Severity.LOW,
                             api=f"{team} {_d(api_item.get('team')).get('name')}",
                             db=f"{db.get('current_team_provider_id')} (from the last line-up we hold)"))
    if tally.total_findings == before:
        tally.matched += 1


def compare_squad(api_item: Mapping[str, Any] | None, known: Mapping[int, Mapping[str, Any]], *,
                  provider_team_id: int, tally: Tally, stored: Sequence[Mapping[str, Any]] | None = None) -> None:
    """The provider's current squad against ours (``stored``: the members seen at the team's
    latest squad read), or - when we hold none - how much of it we know at all."""
    entity = f"team {provider_team_id} squad"
    if api_item is None:
        return
    players = [p for p in _l(api_item.get("players")) if isinstance(p, dict) and _id(p)]
    tally.compared()
    if stored:
        want = {_id(p) for p in players}
        have = {r.get("provider_player_id") for r in stored}
        before = tally.total_findings
        if want - have:
            tally.add(Finding.of("squads", entity, "players", Kind.STALE, Severity.LOW,
                                 api=f"{len(want - have)} players not in our squad", db=f"{len(have)} stored"))
        if have - want:
            tally.add(Finding.of("squads", entity, "players", Kind.MISSING_IN_API, Severity.LOW,
                                 api=f"{len(want)} listed", db=f"{len(have - want)} no longer listed"))
        if tally.total_findings == before:
            tally.matched += 1
        return
    unknown = [p for p in players if _id(p) not in known]
    no_profile = [p for p in players if _id(p) in known and not known[_id(p) or 0].get("birth_date")]
    tally.add(Finding.of("squads", entity, "squad", Kind.NOT_STORED, Severity.MEDIUM,
                         api=f"{len(players)} players", db=f"no squad table; {len(players) - len(unknown)} of them "
                         f"known as players, {len(no_profile)} without a profile",
                         note="current squads (shirt numbers, positions) are never fetched"))
    if unknown:
        tally.add(Finding.of("squads", entity, "players", Kind.MISSING_IN_DB, Severity.LOW,
                             api=f"{len(unknown)} squad players unknown to core.players",
                             db=", ".join(str(_id(p)) for p in unknown[:5])))


# ── injuries ────────────────────────────────────────────────────────────────


def compare_injuries(api_items: Iterable[Mapping[str, Any]], db_rows: Sequence[Mapping[str, Any]], *,
                     provider_fixture_id: int, tally: Tally) -> None:
    entity = f"fixture {provider_fixture_id}"
    api_by_player = {}
    for item in api_items:
        p = _id(item.get("player"))
        if p is not None:
            api_by_player[p] = _d(item.get("player"))
    db_by_player = {r.get("provider_player_id"): r for r in db_rows}
    tally.compared()
    missing = set(api_by_player) - set(db_by_player)
    extra = set(db_by_player) - set(api_by_player)
    before = tally.total_findings
    if missing:
        tally.add(Finding.of("injuries", entity, "absences", Kind.MISSING_IN_DB, Severity.MEDIUM,
                             api=f"{len(missing)} of {len(api_by_player)} not stored",
                             db=f"{len(db_by_player)} stored"))
    if extra:
        tally.add(Finding.of("injuries", entity, "absences", Kind.MISSING_IN_API, Severity.LOW,
                             api=f"{len(api_by_player)} listed", db=f"{len(extra)} stored that the provider no "
                             "longer lists (recovered, or withdrawn)"))
    for p in set(api_by_player) & set(db_by_player):
        a, b = api_by_player[p], db_by_player[p]
        if not _same_text(a.get("type"), b.get("absence_type")) or not _same_text(a.get("reason"), b.get("reason")):
            tally.add(Finding.of("injuries", f"{entity} player {p}", "type/reason", Kind.MISMATCH, Severity.LOW,
                                 api=f"{a.get('type')}: {a.get('reason')}",
                                 db=f"{b.get('absence_type')}: {b.get('reason')}"))
    if tally.total_findings == before:
        tally.matched += 1


# ── odds ────────────────────────────────────────────────────────────────────


def compare_odds(api_quotes: Sequence[Mapping[str, Any]], api_books: Mapping[int, str], api_update: datetime | None,
                 db_latest: Sequence[Mapping[str, Any]], db_books: Mapping[int, str], *, provider_fixture_id: int,
                 kickoff: datetime | None, now: datetime, tally: Tally) -> None:
    """Prices for one fixture: the provider's book now, against the newest price we hold.

    ``api_quotes`` are the provider's prices for the markets we model, keyed the way we
    store them (bookmaker, market, selection, line, odds). ``db_latest`` is our newest
    price per key, with ``captured_at``. When our capture is at or after the provider's
    own ``update`` stamp the two must be identical; before it, ours is merely older.
    """
    entity = f"fixture {provider_fixture_id}"
    soon = kickoff is not None and kickoff - now < timedelta(hours=24)
    missing_books = sorted(set(api_books) - set(db_books))
    tally.compared()
    before = tally.total_findings
    if missing_books:
        tally.add(Finding.of("odds", entity, "bookmakers", Kind.MISSING_IN_DB, Severity.MEDIUM if soon else Severity.LOW,
                             api=", ".join(f"{b} {api_books[b]}" for b in missing_books[:8]),
                             db=f"{len(db_books)} bookmakers captured"))
    db_by_key = {(r["provider_bookmaker_id"], r["market_key"], r["selection"], _num(r.get("line"))): r
                 for r in db_latest}
    stale = mismatched = absent = 0
    example: dict[str, str] = {}
    for q in api_quotes:
        key = (q["provider_bookmaker_id"], q["market_key"], q["selection"], _num(q.get("line")))
        db = db_by_key.get(key)
        if db is None:
            absent += 1
            example.setdefault("absent", f"{key}")
            continue
        captured = _when(db.get("captured_at"))
        if _num(db.get("odds_decimal")) == _num(q.get("odds_decimal")):
            continue
        if api_update is not None and captured is not None and captured >= api_update:
            mismatched += 1
            example.setdefault("mismatch", f"{key}: provider {q.get('odds_decimal')}, ours {db.get('odds_decimal')} "
                                           f"captured {captured:%H:%M}Z after the provider's update {api_update:%H:%M}Z")
        else:
            stale += 1
            example.setdefault("stale", f"{key}: provider {q.get('odds_decimal')} (update {api_update}), ours "
                                        f"{db.get('odds_decimal')} captured {captured}")
    if absent:
        tally.add(Finding.of("odds", entity, "prices", Kind.MISSING_IN_DB, Severity.MEDIUM if soon else Severity.LOW,
                             api=f"{absent} of {len(api_quotes)} prices never captured", db=example.get("absent")))
    if mismatched:
        tally.add(Finding.of("odds", entity, "prices", Kind.MISMATCH, Severity.HIGH,
                             api=f"{mismatched} prices differ", db=example.get("mismatch"),
                             note="captured after the provider's last update, so they should be identical"))
    if stale:
        tally.add(Finding.of("odds", entity, "prices", Kind.STALE, Severity.MEDIUM if soon else Severity.LOW,
                             api=f"{stale} prices moved since our last capture", db=example.get("stale")))
    if tally.total_findings == before:
        tally.matched += 1


# ── leagues and coverage ────────────────────────────────────────────────────


COVERAGE_PATHS: dict[str, tuple[str, ...]] = {
    "events": ("fixtures", "events"), "lineups": ("fixtures", "lineups"),
    "statistics_fixtures": ("fixtures", "statistics_fixtures"),
    "statistics_players": ("fixtures", "statistics_players"), "standings": ("standings",),
    "players": ("players",), "injuries": ("injuries",), "odds": ("odds",),
}


def compare_league(api_item: Mapping[str, Any], db_comp: Mapping[str, Any],
                   db_seasons: Mapping[int, Mapping[str, Any]], db_coverage: Mapping[int, Mapping[str, Any]], *,
                   tally: Tally) -> None:
    league = _d(api_item.get("league"))
    entity = f"competition {league.get('id')} {league.get('name')}"
    tally.compared()
    before = tally.total_findings
    if not _same_text(league.get("name"), db_comp.get("name")):
        tally.add(Finding.of("competitions", entity, "name", Kind.MISMATCH, Severity.LOW,
                             api=league.get("name"), db=db_comp.get("name")))
    if _text(league.get("type")) and not _same_text(league.get("type"), db_comp.get("type")):
        tally.add(Finding.of("competitions", entity, "type", Kind.MISMATCH, Severity.MEDIUM,
                             api=league.get("type"), db=db_comp.get("type")))
    api_current = [s for s in _l(api_item.get("seasons")) if isinstance(s, dict) and s.get("current") is True]
    for s in _l(api_item.get("seasons")):
        if not isinstance(s, dict) or not isinstance(s.get("year"), int):
            continue
        year = int(s["year"])
        db_season = db_seasons.get(year)
        label = f"{entity} {year}"
        if db_season is None:
            if s.get("current") is True:
                tally.add(Finding.of("competitions", label, "season", Kind.MISSING_IN_DB, Severity.HIGH,
                                     api="current season", db="not listed"))
            continue
        if bool(s.get("current")) != bool(db_season.get("is_current")):
            tally.add(Finding.of("competitions", label, "is_current", Kind.STALE, Severity.HIGH,
                                 api=s.get("current"), db=db_season.get("is_current"),
                                 note="which season is current decides what the worker refreshes"))
        if _day(s.get("end")) and _day(s.get("end")) != _day(db_season.get("end_date")):
            tally.add(Finding.of("competitions", label, "end_date", Kind.STALE, Severity.LOW,
                                 api=s.get("end"), db=db_season.get("end_date")))
        cov_db = db_coverage.get(year)
        cov = _d(s.get("coverage"))
        if cov_db is not None:
            for name, path in COVERAGE_PATHS.items():
                node: Any = cov
                for step in path:
                    node = _d(node).get(step)
                if isinstance(node, bool) and cov_db.get(name) is not None and node != cov_db.get(name):
                    tally.add(Finding.of("competitions", label, f"coverage.{name}", Kind.STALE, Severity.LOW,
                                         api=node, db=cov_db.get(name)))
    if not api_current:
        tally.add(Finding.of("competitions", entity, "season", Kind.MISSING_IN_API, Severity.INFO,
                             note="the provider marks no season of this competition as current"))
    if tally.total_findings == before:
        tally.matched += 1
