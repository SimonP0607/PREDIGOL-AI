"""Match Center detail, Live, Players and the private Admin view.

Every block is a Section: a match with no line-ups says so with a reason
instead of rendering an empty table that reads as "nobody played".
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.envelope import Section

Side = Literal["home", "away"]
TableKind = Literal["full", "group", "ranking", "aggregate", "other"]
TableSelection = Literal["fixture_stage", "phase_league_stage", "previous_stage"]


class TeamStatLine(Contract):
    side: Side
    shots: int | None
    shots_on_target: int | None
    shots_off_target: int | None
    shots_blocked: int | None
    shots_inside_box: int | None
    shots_outside_box: int | None
    corners: int | None
    fouls: int | None
    offsides: int | None
    yellow_cards: int | None
    red_cards: int | None
    saves: int | None
    possession_pct: Decimal | None
    passes: int | None
    passes_accurate: int | None
    expected_goals: Decimal | None
    fetched_at: datetime


class MatchEvent(Contract):
    seq: int
    minute: int
    extra_minute: int | None
    side: Side | None
    player: str | None
    player_id: int | None = Field(description="core.players id when the provider's player is known to us.")
    assist: str | None
    type: str
    detail: str | None
    comments: str | None


class LineupPlayer(Contract):
    provider_player_id: int
    player_id: int | None
    name: str | None
    number: int | None
    position: str | None
    grid: str | None
    starter: bool
    photo_url: str | None = Field(default=None, description="The provider's photo URL as stored (profiles); "
                                  "null when none is stored - pages show initials, never a guessed URL.")


class TeamLineup(Contract):
    side: Side
    formation: str | None
    coach: str | None
    players: list[LineupPlayer]


class PlayerLine(Contract):
    provider_player_id: int
    player_id: int | None
    side: Side
    name: str | None
    minutes: int | None
    rating: Decimal | None
    goals: int | None
    assists: int | None
    shots: int | None
    shots_on: int | None
    passes: int | None
    key_passes: int | None
    tackles: int | None
    yellow_cards: int | None
    red_cards: int | None
    saves: int | None
    substitute: bool | None
    photo_url: str | None = None
    position_played: str | None = Field(default=None, description="The position he played in this match (G, D, "
                                        "M, F), from the provider's player statistics.")
    offsides: int | None = None
    dribbled_past: int | None = None
    penalties_won: int | None = None
    penalties_committed: int | None = None
    penalties_saved: int | None = None


class MatchFacts(Contract):
    """What the fixture's payloads say beyond the score (core.fixture_facts, newest change)."""

    referee: str | None
    referee_country: str | None
    home_winner: bool | None = Field(description="The provider's winner flag: the side that won, or went through "
                                     "on penalties; null for a draw or a match not over.")
    away_winner: bool | None
    first_half_at: datetime | None
    second_half_at: datetime | None
    observed_at: datetime
    payload_hash: str
    normalizer_version: str


class Absence(Contract):
    side: Side | None
    player: str | None
    player_id: int | None
    type: str | None
    reason: str | None


class StandingLine(Contract):
    side: Side
    team: str
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
    snapshot_at: datetime
    before_kickoff: bool = Field(description="False when the only table we hold was taken after kick-off.")
    description: str | None = Field(default=None, description="The provider's zone: 'Promotion - Champions League'.")
    checked_at: datetime | None = Field(default=None, description="When the provider was last asked for this table.")
    table_state: Literal["FRESH", "STALE", "UNKNOWN", "UNAVAILABLE"] = Field(
        default="UNKNOWN", description="Whether the table reflects every match played before this one.")
    table_reason: str = Field(default="no_table", description="no_match_yet, reflects_last_match, "
                              "provider_not_updated or not_asked_since (fbi.truth.freshness.table_reason).")
    table: str | None = Field(default=None, description="The provider's label of the table this row comes from "
                              "('Clausura', 'Apertura - Group A', 'Eastern Conference'). A season can hold several "
                              "tables; a row is never taken from another phase's table.")
    table_key: str | None = Field(default=None, description="The stored table key (the label, '#n' for the n-th "
                                  "table under a repeated label).")
    table_kind: TableKind | None = Field(default=None, description="full, group, ranking, aggregate or other "
                                         "(fbi.competitions.phases).")
    table_teams: int | None = Field(default=None, description="Teams in that table.")
    stage: str | None = Field(default=None, description="The stage the table ranks ('Clausura', 'Group Stage').")
    phase: str | None = Field(default=None, description="Its phase ('Clausura'); null for an aggregate.")
    fixture_stage: str | None = Field(default=None, description="This match's stage, from its round label.")
    selection: TableSelection | None = Field(
        default=None, description="fixture_stage: the match's own stage's table; phase_league_stage: a knock-out "
        "round shown with its phase's league table; previous_stage: a knock-out round shown with the last league "
        "stage before it (a single-phase season).")
    team_logo: str | None = None


class FormMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    opponent: str
    venue: Literal["H", "A"]
    goals_for: int
    goals_against: int
    result: Literal["W", "D", "L"]


class TeamForm(Contract):
    side: Side
    team: str
    matches: list[FormMatch]


class H2HMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: str
    home: str
    away: str
    goals_home: int
    goals_away: int


class LiveState(Contract):
    observed_at: datetime
    source: Literal["fixture_feed", "odds_feed"]
    status: str
    elapsed: int | None
    extra: int | None
    goals_home: int | None
    goals_away: int | None


class LiveQuote(Contract):
    market_key: str | None = Field(description="Null for an in-play bet with no market of ours; its price is kept.")
    provider_bet_id: int
    selection: str
    line: Decimal
    odds: Decimal | None = Field(description="Null: the selection was withdrawn at this instant.")
    suspended: bool
    main_line: bool | None
    captured_at: datetime
    minute: int | None


class LiveMove(Contract):
    market_key: str | None
    selection: str
    line: Decimal
    captured_at: datetime
    minute: int | None
    score: str | None
    previous_odds: Decimal | None
    odds: Decimal | None
    delta: Decimal | None
    kind: Literal["moved", "withdrawn", "offered", "suspended", "available", "other"]


class MatchCenter(Contract):
    fixture_id: int
    status_group: str
    statistics: Section[list[TeamStatLine]]
    events: Section[list[MatchEvent]]
    lineups: Section[list[TeamLineup]]
    players: Section[list[PlayerLine]]
    absences: Section[list[Absence]]
    standings: Section[list[StandingLine]]
    standings_tables: list[StandingsTable] = Field(
        default_factory=list, description="The whole table(s) the two rows come from (one, or each team's group).")
    facts: MatchFacts | None = None
    form: Section[list[TeamForm]]
    h2h: Section[list[H2HMatch]]
    live_states: Section[list[LiveState]]
    live_odds: Section[list[LiveQuote]]
    live_movement: Section[list[LiveMove]]


class LiveTeam(Contract):
    id: int
    name: str
    logo_url: str | None = None


class LiveCompleteness(Contract):
    """How much of the match we can actually show, from what is stored - not a guess.

    Weights (sum 100): score 10, minute 10, key events 15, team statistics 20, line-ups 10,
    player ratings 10, in-play prices 15, in-play market breadth 10.
    """

    score: int = Field(ge=0, le=100)
    level: Literal["rich", "partial", "basic"]
    signals: dict[str, bool]


class LiveMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: str
    country: str | None
    competition_id: int | None = None
    competition_logo: str | None = None
    competition_flag: str | None = None
    home: LiveTeam
    away: LiveTeam
    status: str
    elapsed: int | None
    extra: int | None
    goals_home: int | None
    goals_away: int | None
    state_at: datetime
    state_source: Literal["fixture_feed", "odds_feed"]
    state_age_seconds: int
    odds_feed_at: datetime | None
    markets_offered: int | None
    values_suspended: int | None
    events: list[MatchEvent]
    statistics: list[TeamStatLine]
    main_odds: list[LiveQuote]
    data_status: Literal["ok", "stale", "no_odds"] = Field(
        description="stale: no state for 3 minutes; no_odds: in play but nobody quotes it in play.")
    has_lineups: bool = False
    has_player_stats: bool = False
    completeness: LiveCompleteness | None = None


class LiveBoard(Contract):
    matches: list[LiveMatch]
    followed_by_fixture_feed: int
    priced_by_odds_feed: int
    last_fixture_feed_at: datetime | None
    last_odds_feed_at: datetime | None


class PlayerSummary(Contract):
    id: int
    provider_player_id: int
    name: str
    nationality: str | None
    position: str | None
    birth_date: date | None
    photo_url: str | None = None
    team_logo: str | None = None
    national_team_logo: str | None = None
    #: The player's CLUB now: the club whose newest squad lists him (``club_source`` "squad"), else the
    #: club of his last appearance ("appearances"). Never a national team.
    team_id: int | None
    team: str | None
    club_source: str | None = None
    national_team_id: int | None = None
    national_team: str | None = None
    #: Whoever he last played for (a club or a national side) - kept apart from the club.
    last_team_id: int | None = None
    last_team: str | None = None
    #: Matches he played (minutes > 0) - an unused substitute is not an appearance.
    apps: int
    minutes: int | None
    goals: int | None
    assists: int | None
    avg_rating: Decimal | None
    last_played: datetime | None


class PlayerSeason(Contract):
    competition: str
    season: int
    team: str | None
    national: bool | None = None
    apps: int
    starts: int
    minutes: int | None
    goals: int | None
    assists: int | None
    yellow_cards: int | None
    red_cards: int | None
    avg_rating: Decimal | None


class PlayerMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: str
    team: str | None
    opponent: str | None
    minutes: int | None
    rating: Decimal | None
    goals: int | None
    assists: int | None
    substitute: bool | None


class PlayerAbsence(Contract):
    fixture_id: int | None
    kickoff_at: datetime | None
    type: str | None
    reason: str | None


class PlayerDetail(Contract):
    player: PlayerSummary
    firstname: str | None
    lastname: str | None
    height_cm: int | None
    weight_kg: int | None
    seasons: Section[list[PlayerSeason]]
    matches: Section[list[PlayerMatch]]
    absences: Section[list[PlayerAbsence]]


class AdminCount(Contract):
    label: str
    value: int | None
    at: datetime | None = None
    note: str | None = None
    #: Stable machine name of the count (the label is English text); the UI translates by it.
    key: str | None = None


class BackfillProgress(Contract):
    kind: str
    total: int
    done: int
    pending: int
    running: int
    failed: int
    other: int
    last_completed_at: datetime | None


class AdminError(Contract):
    run_id: int
    job_type: str
    status: str
    started_at: datetime
    error: str | None


class BackupFile(Contract):
    name: str
    location: str
    bytes: int
    modified_at: datetime


class AdminOverview(Contract):
    backend_version: str
    code_version: str
    schema_revision: str | None
    database_bytes: int | None
    worker: dict[str, object]
    quota: dict[str, object]
    jobs_next: dict[str, str | None]
    migration: Section[list[BackfillProgress]]
    captures: list[AdminCount]
    errors: Section[list[AdminError]]
    quality: list[AdminCount]
    backups: Section[list[BackupFile]]


class TableSplit(Contract):
    """A row's home or away games (the provider gives no points for them: 3 a win, 1 a draw)."""

    played: int | None
    wins: int | None
    draws: int | None
    losses: int | None
    goals_for: int | None
    goals_against: int | None


class TableRow(Contract):
    rank: int
    team_id: int
    team: str
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    points: int
    form: str | None
    group: str | None
    team_logo: str | None = None
    goals_diff: int | None = None
    description: str | None = Field(default=None, description="The provider's zone ('Promotion - Libertadores').")
    zone_status: str | None = Field(default=None, description="The provider's move since the last round: same, up, down.")
    home: TableSplit | None = None
    away: TableSplit | None = None


class SeasonStage(Contract):
    """One stage of the season, from the fixtures' round labels ("Clausura - 12" -> Clausura)."""

    name: str
    phase: str
    kind: Literal["league", "knockout", "qualifying", "friendly"]
    first_kickoff: datetime | None
    last_kickoff: datetime | None
    fixtures: int
    finished: int
    last_finished: datetime | None = Field(default=None, description="Kick-off of its last finished match.")
    tables: int = Field(description="Tables of the shown snapshot that rank this stage.")
    is_current: bool = Field(description="The league stage being played now (the last one started).")


class StandingsTable(Contract):
    """One table of the provider's answer, kept apart from the season's other tables."""

    key: str
    label: str
    stage: str | None = Field(description="The stage it ranks; null for an aggregate or an unmapped table.")
    stages: list[str] = Field(description="Every stage it counts (several for an aggregate).")
    phase: str | None
    kind: TableKind
    method: Literal["label", "games", "single", "unmapped"] = Field(
        description="How its stage was found: its label names it, its games played agree with the stage's "
                    "matches, the season's only league stage, or not found.")
    agreement: str = Field(description="Rows whose games played agree with the stage's finished matches ('20/20').")
    note: str = ""
    is_current: bool
    rows: list[TableRow]


class CompetitionTable(Contract):
    competition_id: int
    season: int
    snapshot_at: datetime
    seasons: list[int] = Field(default_factory=list, description="Seasons of this competition with a stored table.")
    stages: list[SeasonStage] = Field(default_factory=list)
    tables: list[StandingsTable] = Field(default_factory=list, description="Each table apart, in stage order.")
    mapping_version: str = ""
    rows: list[TableRow] = Field(description="Deprecated: every table's rows flattened (use tables).")
