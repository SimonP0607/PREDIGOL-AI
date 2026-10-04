"""API-Football match detail -> DTOs: statistics, events, lineups, player statistics,
injuries and per-season coverage.

The shapes follow the v3 documentation (v3.9.3): /fixtures?ids= returns, for
each fixture, the blocks ``events``, ``lineups``, ``statistics`` and
``players``; /injuries returns one entry per player and fixture; /leagues
returns every season of a league with its ``coverage`` flags.

Same rule as the rest of the normaliser: a value that cannot be read is
dropped (None), counted by the caller if it cares, and never replaced by a
neighbour. "32%" is 32; "" and null are None; 0 stays 0.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# /fixtures statistics "type" -> our column. The sixteen documented types, plus
# the two the provider's own widgets label (expected goals, goals prevented).
STAT_TYPES: dict[str, str] = {
    "shots on goal": "shots_on_target",
    "shots off goal": "shots_off_target",
    "total shots": "shots",
    "blocked shots": "shots_blocked",
    "shots insidebox": "shots_inside_box",
    "shots outsidebox": "shots_outside_box",
    "fouls": "fouls",
    "corner kicks": "corners",
    "offsides": "offsides",
    "ball possession": "possession_pct",
    "yellow cards": "yellow_cards",
    "red cards": "red_cards",
    "goalkeeper saves": "saves",
    "total passes": "passes",
    "passes accurate": "passes_accurate",
    "expected_goals": "expected_goals",
    "expected goals": "expected_goals",
    "goals_prevented": "goals_prevented",
    "goals prevented": "goals_prevented",
}
"""'Passes %' is derivable (accurate / total) and deliberately not stored twice."""

DECIMAL_COLUMNS = frozenset({"possession_pct", "expected_goals", "goals_prevented"})


def number(value: Any) -> Decimal | None:
    """'32%' -> 32, '1.25' -> 1.25, 7 -> 7; '', None, 'N/A', NaN -> None."""
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


def integer(value: Any) -> int | None:
    d = number(value)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_id(block: Any, key: str = "id") -> int | None:
    if not isinstance(block, dict):
        return None
    v = block.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _text(block: Any, key: str) -> str | None:
    if not isinstance(block, dict):
        return None
    v = block.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


@dataclass(frozen=True, slots=True)
class TeamStatsRef:
    provider_fixture_id: int
    provider_team_id: int
    values: dict[str, Decimal | int | None]
    unknown_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EventRef:
    provider_fixture_id: int
    seq: int
    minute: int
    extra_minute: int | None
    provider_team_id: int | None
    provider_player_id: int | None
    player_name: str | None
    provider_assist_id: int | None
    assist_name: str | None
    event_type: str
    detail: str | None
    comments: str | None


@dataclass(frozen=True, slots=True)
class LineupPlayerRef:
    provider_player_id: int
    name: str | None
    number: int | None
    position: str | None
    grid: str | None
    is_starter: bool


@dataclass(frozen=True, slots=True)
class LineupRef:
    provider_fixture_id: int
    provider_team_id: int
    formation: str | None
    provider_coach_id: int | None
    coach_name: str | None
    players: tuple[LineupPlayerRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class PlayerStatsRef:
    provider_fixture_id: int
    provider_team_id: int
    provider_player_id: int
    name: str | None
    values: dict[str, Decimal | int | bool | None]


@dataclass(frozen=True, slots=True)
class FixtureDetail:
    provider_fixture_id: int
    stats: tuple[TeamStatsRef, ...]
    events: tuple[EventRef, ...]
    lineups: tuple[LineupRef, ...]
    players: tuple[PlayerStatsRef, ...]
    blocks_present: frozenset[str]
    """Which of events/lineups/statistics/players the payload carried at all -
    an absent block (plan or coverage) is not the same as an empty one."""


def _stats(fixture_id: int, block: Any) -> Iterator[TeamStatsRef]:
    for entry in block if isinstance(block, list) else []:
        if not isinstance(entry, dict):
            continue
        team_id = _int_id(entry.get("team"))
        if team_id is None:
            continue
        values: dict[str, Decimal | int | None] = {}
        unknown: list[str] = []
        for item in entry.get("statistics") or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "").strip().lower()
            column = STAT_TYPES.get(kind)
            if column is None:
                if kind and kind != "passes %":
                    unknown.append(kind)
                continue
            raw = item.get("value")
            values[column] = number(raw) if column in DECIMAL_COLUMNS else integer(raw)
        yield TeamStatsRef(fixture_id, team_id, values, tuple(unknown))


def _events(fixture_id: int, block: Any) -> Iterator[EventRef]:
    for seq, entry in enumerate(block if isinstance(block, list) else []):
        if not isinstance(entry, dict):
            continue
        time = _dict(entry.get("time"))
        minute = integer(time.get("elapsed"))
        kind = _text(entry, "type")
        if minute is None or minute < 0 or kind is None:
            continue
        extra = integer(time.get("extra"))
        yield EventRef(fixture_id, seq, minute, extra if extra is None or extra >= 0 else None,
                       _int_id(entry.get("team")), _int_id(entry.get("player")), _text(entry.get("player"), "name"),
                       _int_id(entry.get("assist")), _text(entry.get("assist"), "name"), kind,
                       _text(entry, "detail"), _text(entry, "comments"))


def _lineup_players(items: Any, starter: bool) -> Iterator[LineupPlayerRef]:
    for item in items if isinstance(items, list) else []:
        player = item.get("player") if isinstance(item, dict) else None
        pid = _int_id(player)
        if pid is None:
            continue
        yield LineupPlayerRef(pid, _text(player, "name"), integer(player.get("number") if isinstance(player, dict)
                                                                     else None),
                              _text(player, "pos"), _text(player, "grid"), starter)


def _lineups(fixture_id: int, block: Any) -> Iterator[LineupRef]:
    for entry in block if isinstance(block, list) else []:
        if not isinstance(entry, dict):
            continue
        team_id = _int_id(entry.get("team"))
        if team_id is None:
            continue
        players = (*_lineup_players(entry.get("startXI"), True), *_lineup_players(entry.get("substitutes"), False))
        yield LineupRef(fixture_id, team_id, _text(entry, "formation"), _int_id(entry.get("coach")),
                        _text(entry.get("coach"), "name"), tuple(players))


def _player_values(stat: dict[str, Any]) -> dict[str, Decimal | int | bool | None]:
    def sub(key: str) -> dict[str, Any]:
        v = stat.get(key)
        return v if isinstance(v, dict) else {}

    games, shots, goals, passes = sub("games"), sub("shots"), sub("goals"), sub("passes")
    tackles, duels, dribbles, fouls, cards, penalty = (sub("tackles"), sub("duels"), sub("dribbles"),
                                                       sub("fouls"), sub("cards"), sub("penalty"))
    captain = games.get("captain")
    substitute = games.get("substitute")
    return {
        "minutes": integer(games.get("minutes")),
        "rating": number(games.get("rating")),
        "is_captain": captain if isinstance(captain, bool) else None,
        "is_substitute": substitute if isinstance(substitute, bool) else None,
        "shots_total": integer(shots.get("total")),
        "shots_on": integer(shots.get("on")),
        "goals": integer(goals.get("total")),
        "goals_conceded": integer(goals.get("conceded")),
        "assists": integer(goals.get("assists")),
        "saves": integer(goals.get("saves")),
        "passes_total": integer(passes.get("total")),
        "passes_key": integer(passes.get("key")),
        "passes_accuracy_pct": number(passes.get("accuracy")),
        "tackles": integer(tackles.get("total")),
        "blocks": integer(tackles.get("blocks")),
        "interceptions": integer(tackles.get("interceptions")),
        "duels_total": integer(duels.get("total")),
        "duels_won": integer(duels.get("won")),
        "dribbles_attempts": integer(dribbles.get("attempts")),
        "dribbles_success": integer(dribbles.get("success")),
        "fouls_drawn": integer(fouls.get("drawn")),
        "fouls_committed": integer(fouls.get("committed")),
        "yellow_cards": integer(cards.get("yellow")),
        "red_cards": integer(cards.get("red")),
        "penalties_scored": integer(penalty.get("scored")),
        "penalties_missed": integer(penalty.get("missed")),
    }


def _players(fixture_id: int, block: Any) -> Iterator[PlayerStatsRef]:
    for entry in block if isinstance(block, list) else []:
        if not isinstance(entry, dict):
            continue
        team_id = _int_id(entry.get("team"))
        if team_id is None:
            continue
        for item in entry.get("players") or []:
            if not isinstance(item, dict):
                continue
            pid = _int_id(item.get("player"))
            stats = item.get("statistics")
            if pid is None or not isinstance(stats, list) or not stats or not isinstance(stats[0], dict):
                continue
            yield PlayerStatsRef(fixture_id, team_id, pid, _text(item.get("player"), "name"),
                                 _player_values(stats[0]))


DETAIL_BLOCKS = ("events", "lineups", "statistics", "players")


def iter_fixture_details(body: dict[str, Any]) -> Iterator[FixtureDetail]:
    """One FixtureDetail per fixture in a /fixtures?ids= (or ?id=) response."""
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        fid = _int_id(entry.get("fixture"))
        if fid is None:
            continue
        present = frozenset(b for b in DETAIL_BLOCKS if isinstance(entry.get(b), list))
        yield FixtureDetail(
            fid,
            tuple(_stats(fid, entry.get("statistics"))),
            tuple(_events(fid, entry.get("events"))),
            tuple(_lineups(fid, entry.get("lineups"))),
            tuple(_players(fid, entry.get("players"))),
            present,
        )


@dataclass(frozen=True, slots=True)
class AbsenceRef:
    provider_fixture_id: int
    provider_player_id: int
    provider_team_id: int | None
    player_name: str | None
    absence_type: str | None
    reason: str | None


def iter_injuries(body: dict[str, Any]) -> Iterator[AbsenceRef]:
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        player, fixture = entry.get("player"), entry.get("fixture")
        pid, fid = _int_id(player), _int_id(fixture)
        if pid is None or fid is None:
            continue
        yield AbsenceRef(fid, pid, _int_id(entry.get("team")), _text(player, "name"), _text(player, "type"),
                         _text(player, "reason"))


@dataclass(frozen=True, slots=True)
class CoverageRef:
    provider_league_id: int
    season: int
    league_name: str | None
    country: str | None
    league_type: str | None
    is_current: bool | None
    start_date: date | None
    end_date: date | None
    flags: dict[str, bool | None]


COVERAGE_FLAGS = ("events", "lineups", "statistics_fixtures", "statistics_players", "standings", "players",
                  "top_scorers", "top_assists", "top_cards", "injuries", "predictions", "odds")


def _flag(block: dict[str, Any], key: str) -> bool | None:
    v = block.get(key)
    return v if isinstance(v, bool) else None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def iter_coverage(body: dict[str, Any]) -> Iterator[CoverageRef]:
    """Every (league, season) with the provider's coverage flags, from /leagues."""
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        league = _dict(entry.get("league"))
        lid = _int_id(league)
        if lid is None:
            continue
        country = _text(entry.get("country"), "name")
        for season in entry.get("seasons") or []:
            if not isinstance(season, dict) or not isinstance(season.get("year"), int):
                continue
            cov = _dict(season.get("coverage"))
            fx = _dict(cov.get("fixtures"))
            flags = {k: _flag(fx, k) for k in ("events", "lineups", "statistics_fixtures", "statistics_players")}
            flags.update({k: _flag(cov, k) for k in COVERAGE_FLAGS[4:]})
            current = season.get("current")
            yield CoverageRef(lid, int(season["year"]), _text(league, "name"), country, _text(league, "type"),
                              current if isinstance(current, bool) else None, _date(season.get("start")),
                              _date(season.get("end")), flags)


@dataclass(frozen=True, slots=True)
class SplitRecord:
    """One side of a table row: home matches only, or away matches only."""

    played: int | None
    wins: int | None
    draws: int | None
    losses: int | None
    goals_for: int | None
    goals_against: int | None


def _split(block: Any) -> SplitRecord | None:
    b = _dict(block)
    if not b:
        return None
    goals = _dict(b.get("goals"))
    return SplitRecord(integer(b.get("played")), integer(b.get("win")), integer(b.get("draw")),
                       integer(b.get("lose")), integer(goals.get("for")), integer(goals.get("against")))


@dataclass(frozen=True, slots=True)
class StandingRef:
    provider_league_id: int
    season: int
    provider_team_id: int
    rank: int
    points: int
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    form: str | None
    group: str | None
    goals_diff: int | None = None
    zone_status: str | None = None
    """The provider's movement marker: "same", "up" or "down"."""
    description: str | None = None
    """The zone the rank falls in, as the provider words it: "Promotion - Champions League"."""
    provider_updated_at: datetime | None = None
    home: SplitRecord | None = None
    away: SplitRecord | None = None


def _instant(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def labelled_rows(tables: Any) -> Iterator[tuple[dict[str, Any], str | None]]:
    """Every row of a /standings answer's tables, with its group label made unique per table.

    The label is part of the stored key (a team can sit in several tables of one season), and the
    provider can give two tables of one season the same label: Colombia's Primera A 2023 and 2024
    serve the Apertura and the Clausura play-off groups as "Group A" and "Group B" twice. Keyed by
    the bare label, the second table merged into the first and the rows of a team in both were
    dropped. The first table with a label keeps it; the n-th table with the same label is
    "<label> #n" (the provider's own label stays in the raw payload).
    """
    tables_of: dict[str | None, list[int]] = {}
    for index, table in enumerate(tables if isinstance(tables, list) else []):
        for row in table if isinstance(table, list) else []:
            if not isinstance(row, dict):
                continue
            label = _text(row, "group")
            seen = tables_of.setdefault(label, [])
            if index not in seen:
                seen.append(index)
            nth = seen.index(index) + 1
            yield row, label if nth == 1 else f"{label or ''} #{nth}".strip()


def iter_standings(body: dict[str, Any]) -> Iterator[StandingRef]:
    """Every row of every table in a /standings response.

    A competition can serve several tables for one season (conferences, groups, a
    regular season and a play-off round), and a team can appear in more than one of
    them; each row is yielded with its group, which is part of the stored key - unique
    per table even when the provider repeats a label (``labelled_rows``).
    """
    for entry in body.get("response") or []:
        league = _dict(entry.get("league")) if isinstance(entry, dict) else {}
        if not league:
            continue
        lid, season = _int_id(league), league.get("season")
        if lid is None or not isinstance(season, int):
            continue
        for row, group in labelled_rows(league.get("standings") or []):
            team = _int_id(row.get("team"))
            total = _dict(row.get("all"))
            goals = _dict(total.get("goals"))
            values = (integer(row.get("rank")), integer(row.get("points")), integer(total.get("played")),
                      integer(total.get("win")), integer(total.get("draw")), integer(total.get("lose")),
                      integer(goals.get("for")), integer(goals.get("against")))
            if team is None or any(v is None for v in values):
                continue
            rank, points, played, wins, draws, losses, gf, ga = (int(v) for v in values if v is not None)
            yield StandingRef(lid, int(season), team, rank, points, played, wins, draws, losses, gf, ga,
                              _text(row, "form"), group, integer(row.get("goalsDiff")),
                              _text(row, "status"), _text(row, "description"), _instant(row.get("update")),
                              _split(row.get("home")), _split(row.get("away")))


# ── identity: /teams, and what the detail payloads already tell us ───────────


@dataclass(frozen=True, slots=True)
class VenueRef:
    provider_venue_id: int | None
    name: str | None
    city: str | None
    country: str | None
    capacity: int | None = None
    surface: str | None = None
    address: str | None = None


@dataclass(frozen=True, slots=True)
class TeamRef:
    provider_team_id: int
    name: str
    code: str | None
    country: str | None
    founded: int | None
    is_national: bool | None
    """None when the payload did not say. Defaulting it to False asserted
    "club" about sides nobody had described, three of which were national
    youth teams - and the competition scope and the history weighting both
    read this flag, so a wrong value does not stay in one column."""
    logo_url: str | None
    venue: VenueRef | None


def iter_teams(body: dict[str, Any]) -> Iterator[TeamRef]:
    """Parse /teams?league&season.

    Fifty-four of these payloads were fetched and normalised into nothing. The
    shape is ``{"team": {...}, "venue": {...}}`` per entry; a team without an id
    or a name is not an identity and is skipped rather than invented.
    """
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        team = entry.get("team")
        if not isinstance(team, dict) or not isinstance(team.get("id"), int):
            continue
        name = _text(team, "name")
        if name is None:
            continue
        raw_venue = entry.get("venue")
        venue: VenueRef | None = None
        if isinstance(raw_venue, dict) and (raw_venue.get("id") is not None or _text(raw_venue, "name")):
            venue = VenueRef(
                provider_venue_id=raw_venue["id"] if isinstance(raw_venue.get("id"), int) else None,
                name=_text(raw_venue, "name"),
                city=_text(raw_venue, "city"),
                country=_text(team, "country"),
                capacity=raw_venue["capacity"] if isinstance(raw_venue.get("capacity"), int) else None,
                surface=_text(raw_venue, "surface"),
                address=_text(raw_venue, "address"),
            )
        national = team.get("national")
        yield TeamRef(
            provider_team_id=int(team["id"]),
            name=name,
            code=_text(team, "code"),
            country=_text(team, "country"),
            founded=team["founded"] if isinstance(team.get("founded"), int) else None,
            is_national=national if isinstance(national, bool) else None,
            logo_url=_text(team, "logo"),
            venue=venue,
        )


@dataclass(frozen=True, slots=True)
class PersonRef:
    """A player or a coach as the provider names them: an id and a name.

    Detail payloads carry nothing richer, and that is enough for identity - which
    is the point. Height, birth date and the rest arrive from /players later, and
    a row written from a detail payload must not pretend to hold them.
    """

    provider_id: int
    name: str
    position: str | None = None


def iter_lineup_people(detail: FixtureDetail) -> tuple[list[PersonRef], list[PersonRef]]:
    """(players, coaches) named by the line-ups and player statistics of one fixture.

    De-duplicated by provider id, keeping the first name seen, so a payload that
    repeats a player between the line-up and the statistics block yields one
    identity rather than two.
    """
    players: dict[int, PersonRef] = {}
    coaches: dict[int, PersonRef] = {}
    for lu in detail.lineups:
        if lu.provider_coach_id is not None and lu.coach_name:
            coaches.setdefault(lu.provider_coach_id, PersonRef(lu.provider_coach_id, lu.coach_name))
        for p in lu.players:
            if p.name:
                players.setdefault(p.provider_player_id, PersonRef(p.provider_player_id, p.name, p.position))
    for ps in detail.players:
        if ps.name:
            players.setdefault(ps.provider_player_id, PersonRef(ps.provider_player_id, ps.name))
    return list(players.values()), list(coaches.values())


# ── people: /players/profiles and /players/squads ───────────────────────────


@dataclass(frozen=True, slots=True)
class PlayerProfileRef:
    """A player's profile as the provider states it (/players/profiles). Unknown is None."""

    provider_player_id: int
    name: str | None
    firstname: str | None
    lastname: str | None
    birth_date: date | None
    birth_place: str | None
    birth_country: str | None
    nationality: str | None
    height_cm: int | None
    weight_kg: int | None
    position: str | None
    photo_url: str | None


def _measure(value: Any) -> int | None:
    """'187', '187 cm', 187 -> 187; anything implausible for a person -> None."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().split(" ")[0]
    n = integer(text)
    return n if n is not None and 0 < n < 300 else None


def iter_player_profiles(body: dict[str, Any]) -> Iterator[PlayerProfileRef]:
    for entry in body.get("response") or []:
        player = _dict(entry.get("player")) if isinstance(entry, dict) else {}
        pid = _int_id(player)
        if pid is None or pid <= 0:
            continue
        birth = _dict(player.get("birth"))
        yield PlayerProfileRef(pid, _text(player, "name"), _text(player, "firstname"), _text(player, "lastname"),
                               _date(birth.get("date")), _text(birth, "place"), _text(birth, "country"),
                               _text(player, "nationality"), _measure(player.get("height")),
                               _measure(player.get("weight")), _text(player, "position"), _text(player, "photo"))


@dataclass(frozen=True, slots=True)
class SquadMemberRef:
    provider_player_id: int
    name: str | None
    number: int | None
    position: str | None
    age: int | None
    photo_url: str | None


def iter_squad(body: dict[str, Any]) -> Iterator[tuple[int, list[SquadMemberRef]]]:
    """(provider team id, its current squad) for each team in a /players/squads response."""
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        team = _int_id(entry.get("team"))
        if team is None:
            continue
        members = []
        for p in entry.get("players") or []:
            pid = _int_id(p)
            if pid is None or pid <= 0:
                continue
            age = integer(p.get("age")) if isinstance(p, dict) else None
            members.append(SquadMemberRef(pid, _text(p, "name"), integer(p.get("number")), _text(p, "position"),
                                          age if age is not None and 0 < age < 80 else None, _text(p, "photo")))
        yield team, members
