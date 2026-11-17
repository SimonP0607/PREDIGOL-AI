"""C-09, the profiles (AD-H07 ``IA-090``; availability AD-H05 ``IA-091``; call-ups AD-H06 ``IA-092``): a club, a national team, a
player and a competition, built from stored data only.

``build_*`` answers the PRIVATE projection; ``public_*`` turns it into the public one with ``to_public`` (a private field is never
copied) and answers 404 while ``FBI_PROFILES`` is off. ``private_*`` serves the owner (``require_admin``, no switch).

Nothing here reads the player engine (``fbi.players``, in shadow): the rates per 90 are what the player did
(``fbi.people.per90``). A read of a table a later migration adds (stadium altitude, external ids, the cycle of selections) is
made inside a savepoint: on a database without it the block says ``sin_datos`` instead of failing the page.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast

import psycopg

from fbi.ai import absences as provider_absences
from fbi.ai import evidence as ai_evidence
from fbi.ai import source_policy
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing
from fbi.api.contracts.intelligence.profiles import (
    PRIVATE_PENDING,
    PUBLIC_PENDING,
    AvailabilityEntry,
    CallUp,
    CallUpPlayer,
    Caps,
    CareerSpell,
    Coach,
    CompetitionHeader,
    CompetitionProfilePrivate,
    CompetitionRecord,
    Coverage,
    Crest,
    EntityRef,
    ExternalId,
    Figure,
    Fixture,
    FormItem,
    Honour,
    Honours,
    Identity,
    Interval,
    LeaderRow,
    NationalTeamBlocks,
    Pending,
    Per90,
    Per90Rate,
    Photo,
    PlayerAvailability,
    PlayerHeader,
    PlayerMatchLine,
    PlayerProfilePrivate,
    PlayerSeasonLine,
    Profile,
    ProfileMatchRef,
    ProfilePrivate,
    ProfileTableRow,
    ProviderTrophy,
    SeasonRef,
    SeasonStats,
    ShadowSelection,
    SideRecord,
    Squad,
    SquadMember,
    TeamAvailability,
    TeamHeader,
    TeamKind,
    TeamProfilePrivate,
    Venue,
)
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one, fetch_value
from fbi.api.repositories import center as center_repo
from fbi.api.repositories import profiles as q
from fbi.api.switches import profiles_on
from fbi.competitions.rules import NotCoded, rules_for
from fbi.core.clock import now
from fbi.people import availability as av
from fbi.people import call_ups, caps, per90
from fbi.people.current_coach_store import current_coach

FORM_MATCHES: Final = 5
UPCOMING_MATCHES: Final = 5
CAMPAIGN_DAYS: Final = 330
SQUAD_FRESH_DAYS: Final = 30
"""A squad answer older than this makes the club's answer ``stale`` (``plantilla_antigua``)."""
STANDINGS_FRESH_DAYS: Final = 14
NATIONAL_WINDOW_DAYS: Final = 4 * 365
"""The scorers of a national team: one World Cup cycle."""
LEADERS: Final = 10
INTELLIGENCE_BACK: Final = timedelta(days=14)
INTELLIGENCE_AHEAD: Final = timedelta(days=7)
OPTIONAL_ERRORS: Final = (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn, psycopg.errors.UndefinedFunction,
                          psycopg.errors.InvalidSchemaName)


# ── small helpers ────────────────────────────────────────────────────────────────────────────────────────────────────

def _missing(reason: str, **extra: Any) -> Missing:
    return Missing.model_validate({"missing_reason": reason, **extra})


def _list[X](items: list[X], reason: str = "sin_datos") -> ItemList[X]:
    if items:
        return ItemList[X](items=items)
    return ItemList[X].model_validate({"items": [], "missing_reason": reason})


def _or[T](value: T | None, reason: str = "sin_datos") -> T | Missing:
    return _missing(reason) if value is None else value


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _day(value: date | None) -> datetime | None:
    return None if value is None else datetime(value.year, value.month, value.day, tzinfo=UTC)


def _num(value: Any) -> float | None:
    return None if value is None else float(value) if isinstance(value, Decimal | int | float) else None


def _optional[T](conn: Conn, read: Callable[[], T]) -> T | None:
    """A read of what a later migration adds, in a savepoint: None when the database does not have it."""
    try:
        with conn.transaction():
            return read()
    except OPTIONAL_ERRORS:
        return None


def _pending(blocks: dict[str, str], *, only: Iterable[str]) -> list[Pending]:
    return [Pending.model_validate({"block": b, "missing": {"missing_reason": "no_entregado", "expected_piece": blocks[b]}})
            for b in only]


def _freshness(at: datetime, stale_reason: str | None = None) -> Freshness:
    return Freshness(generated_at=at, stale=stale_reason is not None, stale_reason=stale_reason)


def _identity(conn: Conn, entity_type: str, entity_id: int) -> Identity | Missing:
    params = {"type": entity_type, "id": entity_id}
    rows = _optional(conn, lambda: fetch_all(conn, q.IDENTITY, params))
    if rows is None:
        return _missing("sin_datos")
    reviews = _optional(conn, lambda: fetch_value(conn, q.OPEN_REVIEWS, params))
    ids = [ExternalId(system=str(r["system"]), external_id=str(r["external_id"]), method=str(r["method"]),
                      confidence=_or(_num(r["confidence"])), state=str(r["state"])) for r in rows]
    return Identity(ids=_list(ids), open_reviews=_or(None if reviews is None else int(reviews)))


def _record(rows: Sequence[Row], team_id: int) -> SideRecord:
    won = drawn = lost = gf = ga = 0
    for r in rows:
        mine, theirs = (r["goals_home"], r["goals_away"]) if r["home"] else (r["goals_away"], r["goals_home"])
        gf, ga = gf + int(mine), ga + int(theirs)
        won, drawn, lost = won + (mine > theirs), drawn + (mine == theirs), lost + (mine < theirs)
    return SideRecord(matches=len(rows), won=won, drawn=drawn, lost=lost, goals_for=gf, goals_against=ga)


def _match_ref(r: Row) -> ProfileMatchRef:
    return ProfileMatchRef(fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
                    competition=EntityRef(id=int(r["competition_id"]), name=str(r["competition"])),
                    opponent=EntityRef(id=int(r["opponent_id"]), name=str(r["opponent"])), home=bool(r["home"]))


def _form_item(r: Row) -> FormItem:
    gf, ga = (int(r["goals_home"]), int(r["goals_away"])) if r["home"] else (int(r["goals_away"]), int(r["goals_home"]))
    result = "W" if gf > ga else "L" if gf < ga else "D"
    return FormItem.model_validate({**_match_ref(r).model_dump(), "goals_for": gf, "goals_against": ga,
                                    "score": f"{gf}-{ga}", "result": result})


def _figure(values: Iterable[Any]) -> Figure:
    kept = [float(v) for v in values if v is not None]
    return Figure(per_match=_or(round(sum(kept) / len(kept), 2) if kept else None), matches_with_data=len(kept))


# ── the parts of a team ──────────────────────────────────────────────────────────────────────────────────────────────

def _venue(conn: Conn, venue_id: int | None) -> Venue | Missing:
    if venue_id is None:
        return _missing("sin_datos")
    v = fetch_one(conn, q.VENUE, {"id": venue_id})
    if v is None:
        return _missing("sin_datos")
    altitude = _optional(conn, lambda: fetch_value(conn, q.VENUE_ALTITUDE, {"id": venue_id}))
    return Venue(id=int(v["id"]), name=str(v["name"]), city=_or(_text(v["city"])),
                 capacity=_or(v["capacity"]), altitude_m=_or(_num(altitude)))


def _coach(conn: Conn, team_id: int, at: datetime) -> Coach | Missing:
    found = _optional(conn, lambda: current_coach(conn, [team_id], now=at))
    c = (found or {}).get(team_id) or {}
    name, source, as_of = _text(c.get("coach_name")), c.get("source"), c.get("as_of")
    if not name or source not in ("lineup", "provider_career") or not isinstance(as_of, str):
        return _missing("sin_datos")
    coach_id, fixture = c.get("coach_id"), c.get("fixture_id")
    return Coach(name=name, coach_id=_or(coach_id if isinstance(coach_id, int) else None),
                 basis="ultima_alineacion" if source == "lineup" else "carrera_proveedor",
                 as_of=cast(datetime, _day(date.fromisoformat(as_of))),
                 fixture_id=_or(fixture if isinstance(fixture, int) else None))


def _season_stats(conn: Conn, team_id: int, campaign: Sequence[Row]) -> tuple[SeasonStats | Missing, list[CompetitionRecord]]:
    if not campaign:
        return _missing("sin_datos"), []
    by_season: dict[int, list[Row]] = defaultdict(list)
    for r in campaign:
        by_season[int(r["competition_season_id"])].append(r)
    seasons = {int(s["id"]): s for s in fetch_all(conn, q.SEASONS, {"ids": list(by_season)})}
    standing = {int(s["competition_season_id"]): s for s in fetch_all(conn, q.TEAM_STANDING,
                                                                        {"id": team_id, "seasons": list(by_season)})}
    newest = sorted(by_season, key=lambda s: max(r["kickoff_at"] for r in by_season[s]), reverse=True)
    records = []
    for sid in newest:
        rows, st = by_season[sid], standing.get(sid) or {}
        records.append(CompetitionRecord(
            competition=EntityRef(id=int(rows[0]["competition_id"]), name=str(rows[0]["competition"])),
            season=_or(seasons.get(sid, {}).get("season")), record=_record(rows, team_id),
            rank=_or(st.get("rank")), points=_or(st.get("points"))))
    leagues = [s for s in newest if seasons.get(s, {}).get("type") == "league"]
    head = (leagues or newest)[0]
    rows = by_season[head]
    stats = {int(r["fixture_id"]): r for r in fetch_all(
        conn, q.SEASON_TEAM_STATS, {"id": team_id, "fixtures": [int(r["fixture_id"]) for r in rows]})}
    lines = [stats.get(int(r["fixture_id"]), {}) for r in rows]
    season_no = seasons.get(head, {}).get("season")
    if season_no is None:
        return _missing("sin_datos"), records
    return SeasonStats(
        competition=EntityRef(id=int(rows[0]["competition_id"]), name=str(rows[0]["competition"])), season=int(season_no),
        record=_record(rows, team_id), home=_record([r for r in rows if r["home"]], team_id),
        away=_record([r for r in rows if not r["home"]], team_id),
        xg_for=_figure(x.get("xg_for") for x in lines), xg_against=_figure(x.get("xg_against") for x in lines),
        shots_for=_figure(x.get("shots_for") for x in lines),
        shots_on_target_for=_figure(x.get("shots_on_target_for") for x in lines),
        corners_for=_figure(x.get("corners_for") for x in lines),
        yellow_cards_for=_figure(x.get("yellow_cards_for") for x in lines)), records


def _honours(conn: Conn, team_id: int, today: date) -> Honours:
    rows = fetch_all(conn, q.HONOURS, {"id": team_id, "today": today})
    first = fetch_value(conn, q.FIRST_SEASON, {"id": team_id})
    titles = [Honour(competition=EntityRef(id=int(r["competition_id"]), name=str(r["competition"])),
                     season=int(r["season"]), basis="tabla_final_guardada") for r in rows]
    return Honours(computed=_list(titles), since_season=_or(first))


def _squad(conn: Conn, team_id: int) -> tuple[Squad | Missing, datetime | None, list[Row]]:
    rows = fetch_all(conn, q.SQUAD, {"id": team_id})
    if not rows:
        return _missing("sin_datos"), None, []
    seen = max(r["last_seen_at"] for r in rows)
    players = [SquadMember(player_id=_or(r["player_id"]), name=str(r["player_name"] or r["provider_player_id"]),
                           position=_or(r["position"]), shirt_number=_or(r["shirt_number"]), age=_or(r["age"]))
               for r in rows]
    return Squad(seen_at=seen, players=_list(players)), seen, rows


@dataclass(frozen=True, slots=True)
class _Report:
    """What availability is known for one match of one team: the season's check and the state of each player."""

    fixture_id: int
    checked_at: datetime | None
    states: dict[int, av.State]


def _press_row(r: Row) -> Row:
    """A v1 item of ``ai.evidence`` as availability reads it: kind, assertion, level, source and time - nothing of its text."""
    raw = r.get("attributes")
    attributes: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return {"provider_player_id": r["provider_player_id"], "kind": r["kind"], "assertion": attributes.get("assertion"),
            "status": r["status"], "source_tier": r["source_tier"], "source_name": r["source_domain"],
            "known_at": r["retrieved_at"], "fixture_id": r["fixture_id"], "player_name": attributes.get("player_name")}


def _availability_of(conn: Conn, team_id: int, fixture_id: int, squad: Sequence[tuple[int, str]], at: datetime) -> _Report:
    season = fetch_value(conn, q.SEASON_OF_FIXTURE, {"id": fixture_id})
    checked = provider_absences.checked_at_as_of(conn, int(season), at) if season is not None else None
    listed = provider_absences.absences_as_of(conn, fixture_id, at)
    press = [_press_row(r) for r in fetch_all(conn, ai_evidence.CONTEXT_SQL, {"fixture": fixture_id, "at": at})
             if r["team_id"] == team_id and r["kind"] != "lineup" and r["provider_player_id"]]
    reports = (av.available_by_default(squad, checked_at=checked, fixture_id=fixture_id)
               + av.provider_reports(listed, fixture_id=fixture_id) + av.press_reports(press))
    return _Report(fixture_id, checked, av.resolve(reports))


def _core_ids(conn: Conn, pids: Iterable[int]) -> dict[int, int]:
    wanted = sorted(set(pids))
    if not wanted:
        return {}
    return {int(r["provider_player_id"]): int(r["id"]) for r in fetch_all(conn, q.PLAYER_IDS, {"pids": wanted})}


def _team_availability(conn: Conn, team_id: int, next_match: Row | None, squad_rows: Sequence[Row],
                       at: datetime) -> TeamAvailability | Missing:
    if next_match is None:
        return _missing("sin_datos")
    squad = [(int(r["provider_player_id"]), str(r["player_name"] or r["provider_player_id"])) for r in squad_rows
             if int(r["provider_player_id"]) > 0]
    report = _availability_of(conn, team_id, int(next_match["fixture_id"]), squad, at)
    out = [s for s in report.states.values() if s.status != "disponible"]
    if report.checked_at is None and not out:
        return _missing("sin_cobertura")
    ids = _core_ids(conn, (s.provider_player_id for s in out))
    entries = [AvailabilityEntry(player_id=_or(ids.get(s.provider_player_id)), name=s.name, status=s.status, basis=s.basis,
                                 source=s.source, known_at=s.known_at, fixture_id=_or(s.fixture_id))
               for s in sorted(out, key=lambda s: (av.RANK[s.basis], s.name))]
    return TeamAvailability(fixture_id=report.fixture_id, report_checked_at=_or(report.checked_at),
                            unavailable=_list(entries, "sin_resultados"))


def _shadow(conn: Conn, team_id: int, at: datetime) -> ItemList[ShadowSelection]:
    def read() -> list[Row]:
        ids = [int(r["id"]) for r in fetch_all(conn, q.TEAM_FIXTURE_IDS,
                                               {"id": team_id, "from": at - INTELLIGENCE_BACK, "to": at + INTELLIGENCE_AHEAD})]
        return fetch_all(conn, q.SHADOW_SELECTIONS, {"fixtures": ids}) if ids else []

    rows = _optional(conn, read) or []
    items = [ShadowSelection(fixture_id=int(r["fixture_id"]), market_key=str(r["market_key"]), selection=str(r["selection"]),
                             line=_or(_num(r["line"])), state=r["state"], evaluation=_or(r["evaluation"]),
                             known_at=r["known_at"]) for r in rows]
    return _list(items, "sin_resultados")


# ── national teams ───────────────────────────────────────────────────────────────────────────────────────────────────

def _permitted_official(conn: Conn) -> int:
    try:
        policy = source_policy.load(conn)
    except Exception:  # the registry unreadable: no source is permitted - the closed answer
        return 0
    return len(call_ups.permitted_official_domains(policy))


def _call_up(conn: Conn, team_id: int, squad: Squad | Missing, squad_rows: Sequence[Row], at: datetime) -> CallUp | Missing:
    permitted = _permitted_official(conn)
    match_rows = fetch_all(conn, q.LAST_MATCH_SQUAD, {"id": team_id, "now": at})
    candidates = []
    if match_rows:
        candidates.append(call_ups.Candidate("convocados_ultimo_partido", match_rows[0]["kickoff_at"],
                                             int(match_rows[0]["fixture_id"]), len(match_rows)))
    if isinstance(squad, Squad):
        candidates.append(call_ups.Candidate("plantilla_proveedor", squad.seen_at, None, len(squad_rows)))
    chosen = call_ups.choose(candidates, now=at)
    if chosen is None:
        return _missing("sin_datos")
    rows = match_rows if chosen.basis == "convocados_ultimo_partido" else list(squad_rows)
    clubs = {int(r["provider_player_id"]): r for r in fetch_all(
        conn, q.CLUBS_OF, {"pids": [int(r["provider_player_id"]) for r in rows]})}
    players = []
    for r in rows:
        club = clubs.get(int(r["provider_player_id"]))
        players.append(CallUpPlayer(player_id=_or(r["player_id"]), name=str(r["player_name"] or r["provider_player_id"]),
                                    club=EntityRef(id=int(club["id"]), name=str(club["name"])) if club else _missing("sin_datos"),
                                    position=_or(r["position"])))
    source = ("API-Football (convocados del último partido)" if chosen.basis == "convocados_ultimo_partido"
              else "API-Football (plantilla)")
    return CallUp(level="proveedor", basis=chosen.basis, source=source, published_at=_missing("sin_datos"),
                  known_at=chosen.seen_at, fixture_id=_or(chosen.fixture_id),
                  official_state=call_ups.official_state(permitted), permitted_official_sources=permitted,
                  players=_list(players))


def _leaders(rows: Iterable[Row]) -> ItemList[LeaderRow]:
    return _list([LeaderRow(player_id=_or(r["player_id"]), name=str(r["name"]), value=int(r["value"])) for r in rows])


def _national(conn: Conn, team_id: int, squad: Squad | Missing, squad_rows: Sequence[Row], at: datetime) -> NationalTeamBlocks:
    return NationalTeamBlocks(
        call_up=_call_up(conn, team_id, squad, squad_rows, at),
        caps_leaders=_leaders(fetch_all(conn, q.CAPS_LEADERS, {"id": team_id, "limit": LEADERS})),
        scorers=_leaders(fetch_all(conn, q.SCORERS, {"id": team_id, "limit": LEADERS, "now": at,
                                                     "since": at - timedelta(days=NATIONAL_WINDOW_DAYS)})),
        window_days=NATIONAL_WINDOW_DAYS)


# ── the team ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def build_team(conn: Conn, team_id: int, *, at: datetime | None = None) -> ProfilePrivate:
    moment = at or now()
    t = fetch_one(conn, q.TEAM, {"id": team_id})
    if t is None:
        raise ApiError(404, "not_found", "not found")
    national = bool(t["national"])
    kind: TeamKind = "national_team" if national else "club"
    logo = _text(t["logo_url"])
    header = TeamHeader(id=int(t["id"]), name=str(t["name"]), short_name=_or(_text(t["short_name"])),
                        country=_or(_text(t["country"])), kind=kind, senior=not caps.is_youth(str(t["name"])),
                        founded=_or(t["founded"]), crest=Crest(allowed=logo is not None, url=_or(logo)),
                        venue=_venue(conn, t["venue_id"]), coach=_coach(conn, team_id, moment))
    form = [_form_item(r) for r in fetch_all(conn, q.FORM, {"id": team_id, "now": moment, "limit": FORM_MATCHES})]
    upcoming_rows = fetch_all(conn, q.UPCOMING, {"id": team_id, "now": moment, "limit": UPCOMING_MATCHES})
    campaign = fetch_all(conn, q.CAMPAIGN, {"id": team_id, "now": moment, "since": moment - timedelta(days=CAMPAIGN_DAYS)})
    season_stats, records = _season_stats(conn, team_id, campaign)
    squad, seen, squad_rows = _squad(conn, team_id)
    next_row = upcoming_rows[0] if upcoming_rows else None
    profile = TeamProfilePrivate(
        header=header, next_match=_match_ref(next_row) if next_row else _missing("sin_datos"), form=_list(form),
        season_stats=season_stats, availability=_team_availability(conn, team_id, next_row, squad_rows, moment),
        squad=squad, upcoming=_list([_match_ref(r) for r in upcoming_rows]), competitions=_list(records),
        honours=_honours(conn, team_id, moment.date()),
        national=_national(conn, team_id, squad, squad_rows, moment) if national else None,
        intelligence=_shadow(conn, team_id, moment), identity=_identity(conn, "team", team_id))
    stale = None if seen is None or seen >= moment - timedelta(days=SQUAD_FRESH_DAYS) or national else "plantilla_antigua"
    return ProfilePrivate(kind=kind, team=profile, freshness=_freshness(moment, stale),
                          not_yet=_pending(PUBLIC_PENDING, only=("stakes", "news", "honours_external")),
                          not_yet_private=[])


# ── the player ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _age(birth: date | None, today: date) -> int | None:
    if birth is None:
        return None
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return years if 0 <= years < 80 else None


def _count(value: Any) -> int | Missing:
    return _missing("sin_datos") if value is None else int(value)


def _player_line(r: Row) -> PlayerMatchLine:
    return PlayerMatchLine(
        fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
        competition=EntityRef(id=int(r["competition_id"]), name=str(r["competition"])),
        team=EntityRef(id=int(r["team_id"]), name=str(r["team"])),
        opponent=EntityRef(id=int(r["opponent_id"]), name=str(r["opponent"])), minutes=int(r["minutes"]),
        started=bool(r["started"]), goals=_count(r["goals"]), assists=_count(r["assists"]), shots=_count(r["shots_total"]),
        shots_on_target=_count(r["shots_on"]), yellow_cards=_count(r["yellow_cards"]), red_cards=_count(r["red_cards"]))


def _sum(rows: Sequence[Row], column: str) -> int | Missing:
    kept = [int(r[column]) for r in rows if r[column] is not None]
    return int(sum(kept)) if kept else _missing("sin_datos")


def _season_lines(rows: Sequence[Row]) -> list[PlayerSeasonLine]:
    groups: dict[tuple[int, int, int], list[Row]] = defaultdict(list)
    for r in rows:
        groups[(int(r["competition_id"]), int(r["season"]), int(r["team_id"]))].append(r)
    out = []
    for (_, season, _), g in sorted(groups.items(), key=lambda kv: (-kv[0][1], -len(kv[1]))):
        out.append(PlayerSeasonLine(
            competition=EntityRef(id=int(g[0]["competition_id"]), name=str(g[0]["competition"])), season=season,
            team=EntityRef(id=int(g[0]["team_id"]), name=str(g[0]["team"])), matches=len(g),
            starts=sum(1 for r in g if r["started"]), minutes=sum(int(r["minutes"]) for r in g),
            goals=_sum(g, "goals"), assists=_sum(g, "assists")))
    return out


def per90_block(rows: Sequence[Row], *, goalkeeper: bool) -> Per90:
    lines = [per90.Line(int(r["minutes"]), {m: r[per90.COLUMN[m]] for m in per90.METRICS}) for r in rows]
    metrics = [m for m in per90.METRICS if m != "saves" or goalkeeper]
    items = []
    for rt in per90.rates(lines, metrics):
        if rt.value is not None and rt.low is not None and rt.high is not None:
            value: float | Missing = rt.value
            interval: Interval | Missing = Interval(low=rt.low, high=rt.high)
        elif rt.matches == 0:
            value = interval = _missing("sin_datos")
        else:
            value = interval = _missing("muestra_insuficiente", sample=rt.minutes, min_sample=per90.MIN_MINUTES)
        items.append(Per90Rate(metric=cast(Any, rt.metric), value=value, interval=interval, count=rt.count,
                               matches=rt.matches, minutes_sample=rt.minutes, sample_ok=rt.sample_ok))
    return Per90(min_minutes=per90.MIN_MINUTES, window_days=per90.WINDOW_DAYS, items=items)


def _player_availability(conn: Conn, p: Row, next_row: Row | None, at: datetime) -> PlayerAvailability | Missing:
    if next_row is None or p["team_id"] is None:
        return _missing("sin_datos")
    pid = int(p["provider_player_id"])
    report = _availability_of(conn, int(p["team_id"]), int(next_row["fixture_id"]), [(pid, str(p["name"]))], at)
    state = report.states.get(pid)
    if state is None:
        return _missing("sin_cobertura" if report.checked_at is None else "sin_datos")
    return PlayerAvailability(status=state.status, basis=state.basis, source=state.source, known_at=state.known_at,
                              fixture_id=report.fixture_id)


def build_player(conn: Conn, player_id: int, *, at: datetime | None = None) -> ProfilePrivate:
    moment = at or now()
    p = fetch_one(conn, center_repo.PLAYER, {"id": player_id, "since": moment - timedelta(days=365)})
    if p is None:
        raise ApiError(404, "not_found", "not found")
    pid = int(p["provider_player_id"])
    position = fetch_value(conn, "SELECT core.position_group(%(p)s)", {"p": p["position"]})
    shirt = (fetch_value(conn, q.PLAYER_SHIRT, {"pid": pid, "team": p["team_id"]}) if p["team_id"] is not None else None)
    header = PlayerHeader(
        id=int(p["id"]), name=str(p["name"]), age=_or(_age(p["birth_date"], moment.date())),
        nationality=_or(_text(p["nationality"])), position=_or(position),
        club=EntityRef(id=int(p["team_id"]), name=str(p["team"])) if p["team_id"] is not None else _missing("sin_datos"),
        national_team=(EntityRef(id=int(p["national_team_id"]), name=str(p["national_team"]))
                       if p["national_team_id"] is not None else _missing("sin_datos")),
        shirt_number=_or(shirt), photo=Photo())
    rows = fetch_all(conn, q.PLAYER_LINES, {"pid": pid, "now": moment, "since": moment - timedelta(days=per90.WINDOW_DAYS)})
    next_rows = (fetch_all(conn, q.UPCOMING, {"id": int(p["team_id"]), "now": moment, "limit": 1})
                 if p["team_id"] is not None else [])
    next_row = next_rows[0] if next_rows else None
    spells = [CareerSpell(team=EntityRef(id=int(s["team_id"]), name=str(s["team_name"])) if s["team_id"] else _missing("sin_datos"),
                          team_name=str(s["team_name"]), valid_from=cast(datetime, _day(s["valid_from"])),
                          valid_to=_or(_day(s["valid_to"])), matches=_or(s["matches"]))
              for s in fetch_all(conn, q.PLAYER_SPELLS, {"pid": pid}) if s["valid_from"] and _text(s["team_name"])]
    c = fetch_one(conn, q.PLAYER_CAPS, {"pid": pid})
    capsblock: Caps | Missing = (Caps(team=EntityRef(id=int(c["team_id"]), name=str(c["name"])), matches=int(c["matches"]),
                                      appeared=int(c["appeared"]), starts=int(c["starts"]), minutes=int(c["minutes"]),
                                      last_at=c["last_at"]) if c else _missing("sin_datos"))
    trophies = [ProviderTrophy(league=str(t["league"]), country=_or(_text(t["country"])), season=_or(_text(t["season"])),
                               place=_or(_text(t["place"])))
                for t in fetch_all(conn, center_repo.PLAYER_TROPHIES, {"pid": pid}) if _text(t["league"])]
    profile = PlayerProfilePrivate(
        header=header, availability=_player_availability(conn, p, next_row, moment),
        next_match=_match_ref(next_row) if next_row else _missing("sin_datos"),
        form_last10=_list([_player_line(r) for r in rows[:10]]), season=_list(_season_lines(rows)),
        per90=per90_block(rows, goalkeeper=position == "goalkeeper"), career=_list(spells), caps=capsblock,
        trophies=_list(trophies), identity=_identity(conn, "player", player_id))
    return ProfilePrivate(kind="player", player=profile, freshness=_freshness(moment),
                          not_yet=_pending(PUBLIC_PENDING, only=("news",)),
                          not_yet_private=_pending(PRIVATE_PENDING, only=("start_probability", "engine_forecasts",
                                                                          "player_markets")))


# ── the competition ──────────────────────────────────────────────────────────────────────────────────────────────────

def build_competition(conn: Conn, competition_id: int, *, at: datetime | None = None) -> ProfilePrivate:
    moment = at or now()
    c = fetch_one(conn, q.COMPETITION, {"id": competition_id})
    if c is None:
        raise ApiError(404, "not_found", "not found")
    s = fetch_one(conn, q.CURRENT_SEASON, {"id": competition_id})
    coded = s is not None and not isinstance(rules_for(int(c["provider_league_id"]), int(s["season"])), NotCoded)
    logo = _text(c["logo_url"])
    header = CompetitionHeader(id=int(c["id"]), name=str(c["name"]), country=_or(_text(c["country"])),
                               type=_or(_text(c["type"])), gender=_or(_text(c["gender"])),
                               age_group=_or(_text(c["age_group"])), tracked=bool(c["is_tracked"]),
                               logo=Crest(allowed=logo is not None, url=_or(logo)), rules_coded=coded)
    stale = None
    if s is None:
        season: SeasonRef | Missing = _missing("sin_datos")
        table: list[ProfileTableRow] = []
        table_at: datetime | Missing = _missing("sin_datos")
        upcoming: list[Fixture] = []
        scorers = _leaders([])
        coverage: Coverage | Missing = _missing("sin_datos")
    else:
        sid = int(s["id"])
        season = SeasonRef(season=int(s["season"]), start=_or(_day(s["start_date"])), end=_or(_day(s["end_date"])),
                           current=bool(s["is_current"]))
        rows = fetch_all(conn, q.STANDINGS, {"season": sid})
        table = [ProfileTableRow(rank=int(r["rank"]), team=EntityRef(id=int(r["team_id"]), name=str(r["name"])),
                          group=_or(_text(r["group"])), played=int(r["played"] or 0), points=int(r["points"] or 0),
                          goals_for=int(r["goals_for"] or 0), goals_against=int(r["goals_against"] or 0))
                 for r in rows if r["rank"] is not None]
        newest = max((r["snapshot_at"] for r in rows), default=None)
        table_at = _or(newest)
        if newest is not None and s["is_current"] and newest < moment - timedelta(days=STANDINGS_FRESH_DAYS):
            stale = "tabla_antigua"
        upcoming = [Fixture(fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
                            home=EntityRef(id=int(r["home_id"]), name=str(r["home"])),
                            away=EntityRef(id=int(r["away_id"]), name=str(r["away"])))
                    for r in fetch_all(conn, q.COMPETITION_UPCOMING, {"season": sid, "now": moment, "limit": 10})]
        scorers = _leaders(fetch_all(conn, q.COMPETITION_SCORERS, {"season": sid, "limit": LEADERS}))
        cov = fetch_one(conn, q.COMPETITION_COVERAGE, {"season": sid}) or {}
        coverage = Coverage(finished_matches=int(cov.get("finished") or 0), with_player_stats=int(cov.get("players") or 0),
                            with_team_stats=int(cov.get("teams") or 0))
    profile = CompetitionProfilePrivate(header=header, season=season, standings=_list(table), standings_at=table_at,
                                        upcoming=_list(upcoming), scorers=scorers, coverage=coverage,
                                        identity=_identity(conn, "competition", competition_id))
    return ProfilePrivate(kind="competition", competition=profile, freshness=_freshness(moment, stale),
                          not_yet=_pending(PUBLIC_PENDING, only=("news",)), not_yet_private=[])


# ── the two projections ──────────────────────────────────────────────────────────────────────────────────────────────

def _public(answer: ProfilePrivate) -> Envelope[Profile]:
    return ok(to_public(answer, Profile))


def _gate() -> None:
    if not profiles_on():
        raise ApiError(404, "not_found", "not found")


def public_team(conn: Conn, team_id: int, *, at: datetime | None = None) -> Envelope[Profile]:
    _gate()
    return _public(build_team(conn, team_id, at=at))


def public_player(conn: Conn, player_id: int, *, at: datetime | None = None) -> Envelope[Profile]:
    _gate()
    return _public(build_player(conn, player_id, at=at))


def public_competition(conn: Conn, competition_id: int, *, at: datetime | None = None) -> Envelope[Profile]:
    _gate()
    return _public(build_competition(conn, competition_id, at=at))


def private_team(conn: Conn, team_id: int, *, at: datetime | None = None) -> Envelope[ProfilePrivate]:
    return ok(build_team(conn, team_id, at=at))


def private_player(conn: Conn, player_id: int, *, at: datetime | None = None) -> Envelope[ProfilePrivate]:
    return ok(build_player(conn, player_id, at=at))


def private_competition(conn: Conn, competition_id: int, *, at: datetime | None = None) -> Envelope[ProfilePrivate]:
    return ok(build_competition(conn, competition_id, at=at))
