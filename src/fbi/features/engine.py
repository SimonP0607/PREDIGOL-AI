"""The walk-forward feature engine.

ONE pass over time. Every result becomes an event at the moment it could
first have been known, every feature request is an event at its data
cut-off, and the events are processed in time order. A feature vector is
therefore built from exactly the state that existed at its cut-off - not by
filtering a table with a WHERE clause that one careless edit can widen.

AVAILABILITY MODEL. A result is treated as known ``RESULT_AVAILABLE_AFTER``
after kick-off (three hours: ninety minutes, half time, stoppages, extra time
and the delay before a provider publishes the final score). Using the
ingestion time instead would be wrong for history - a 2023 result backfilled
today was knowable in 2023 - and using kick-off would let a match inform a
prediction made during it. At equal instants a feature request is processed
BEFORE a result, so a result that becomes available exactly at the cut-off
is excluded.

NULL, NOT ZERO. A team with no previous match has no form; its value is
None, and ``*_history_n`` says how much history there was. Zero would be a
claim ("scored nothing") the data never made.

WHAT A VECTOR RECORDS. The number of results consumed, the kick-off of the
newest one, and a running sha256 over every consumed (fixture, score) pair in
consumption order: the same information set always yields the same hash.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from fbi.features.data import MatchRecord
from fbi.features.elo import EloBook, EloParams, expected_score

FEATURE_VERSION = "fv1.0.0"
RESULT_AVAILABLE_AFTER = timedelta(hours=3)
FORM_N = 5
STRENGTH_N = 10
LEAGUE_N = 200
TEAM_MEMORY = 60


class LeakageError(ValueError):
    """A feature request whose cut-off is after the fixture's kick-off."""


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    group: str
    description: str
    window: str | None = None


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("elo_home", "rating", "Home team Elo going into the match (initial rating if unseen)."),
    FeatureSpec("elo_away", "rating", "Away team Elo going into the match."),
    FeatureSpec("elo_diff", "rating", "elo_home - elo_away, without home advantage."),
    FeatureSpec("elo_expected_home", "rating", "Elo expected score of the home side, with home advantage unless neutral."),
    FeatureSpec("home_gf_avg5", "form", "Home team goals scored per match, last 5 (any venue).", "last 5"),
    FeatureSpec("home_ga_avg5", "form", "Home team goals conceded per match, last 5.", "last 5"),
    FeatureSpec("away_gf_avg5", "form", "Away team goals scored per match, last 5.", "last 5"),
    FeatureSpec("away_ga_avg5", "form", "Away team goals conceded per match, last 5.", "last 5"),
    FeatureSpec("home_ppg5", "form", "Home team points per game, last 5.", "last 5"),
    FeatureSpec("away_ppg5", "form", "Away team points per game, last 5.", "last 5"),
    FeatureSpec("home_gf_home5", "venue", "Home team goals scored per HOME match, last 5 home matches.", "last 5 home"),
    FeatureSpec("home_ga_home5", "venue", "Home team goals conceded per HOME match.", "last 5 home"),
    FeatureSpec("away_gf_away5", "venue", "Away team goals scored per AWAY match, last 5 away matches.", "last 5 away"),
    FeatureSpec("away_ga_away5", "venue", "Away team goals conceded per AWAY match.", "last 5 away"),
    FeatureSpec("home_attack", "strength", "Home team goals scored per match (last 10) / competition goals per team-match (last 200).", "last 10 / 200"),
    FeatureSpec("home_defence", "strength", "Home team goals conceded per match (last 10) / competition average. Lower is better.", "last 10 / 200"),
    FeatureSpec("away_attack", "strength", "Away team attack strength, as home_attack.", "last 10 / 200"),
    FeatureSpec("away_defence", "strength", "Away team defence strength, as home_defence.", "last 10 / 200"),
    FeatureSpec("home_rest_days", "schedule", "Days since the home team's previous match in the dataset."),
    FeatureSpec("away_rest_days", "schedule", "Days since the away team's previous match in the dataset."),
    FeatureSpec("home_sos5", "schedule", "Mean Elo of the home team's last 5 opponents, before those matches.", "last 5"),
    FeatureSpec("away_sos5", "schedule", "Mean Elo of the away team's last 5 opponents.", "last 5"),
    FeatureSpec("league_goals_avg", "context", "Goals per match in this competition, last 200 matches.", "last 200"),
    FeatureSpec("league_home_win_rate", "context", "Share of home wins in this competition, last 200 matches.", "last 200"),
    FeatureSpec("is_neutral", "context", "1 if played at a neutral venue."),
    FeatureSpec("is_cup", "context", "1 unless the competition is a domestic league."),
    FeatureSpec("home_season_matches", "context", "Home team matches already played in this competition-season."),
    FeatureSpec("away_season_matches", "context", "Away team matches already played in this competition-season."),
    FeatureSpec("home_history_n", "sufficiency", "Home team matches available in the dataset (capped at 60)."),
    FeatureSpec("away_history_n", "sufficiency", "Away team matches available in the dataset (capped at 60)."),
)
FEATURE_NAMES = tuple(f.name for f in FEATURES)


@dataclass(frozen=True, slots=True)
class TeamMatch:
    kickoff_at: datetime
    at_home: bool
    goals_for: int
    goals_against: int
    opponent_elo_before: float
    competition_id: int
    season: int

    @property
    def points(self) -> int:
        return 3 if self.goals_for > self.goals_against else 1 if self.goals_for == self.goals_against else 0


@dataclass(frozen=True, slots=True)
class FeatureVector:
    fixture_id: int
    kickoff_at: datetime
    data_cutoff: datetime
    values: dict[str, float | None]
    n_inputs: int
    newest_input_at: datetime | None
    input_hash: str


@dataclass(frozen=True, slots=True)
class EloRecord:
    team_id: int
    fixture_id: int
    kickoff_at: datetime
    rating_before: float
    rating_after: float
    expected_score: float
    actual_score: float
    k_factor: float
    margin_multiplier: float


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _ratio(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or b == 0 else a / b


class WalkForward:
    """State as of a moment: ratings, recent matches per team and competition."""

    def __init__(self, params: EloParams) -> None:
        self.book = EloBook(params)
        self.teams: dict[int, deque[TeamMatch]] = defaultdict(lambda: deque(maxlen=TEAM_MEMORY))
        self.league: dict[int, deque[tuple[int, int]]] = defaultdict(lambda: deque(maxlen=LEAGUE_N))
        self.n_inputs = 0
        self.newest_input_at: datetime | None = None
        self._digest = hashlib.sha256()
        self.elo_history: list[EloRecord] = []

    def ingest(self, m: MatchRecord) -> None:
        assert m.goals_home is not None and m.goals_away is not None
        gh, ga = m.goals_home, m.goals_away
        up = self.book.update(m.home_team_id, m.away_team_id, gh, ga, neutral=m.is_neutral)
        self.teams[m.home_team_id].append(
            TeamMatch(m.kickoff_at, True, gh, ga, up.away_before, m.competition_id, m.season))
        self.teams[m.away_team_id].append(
            TeamMatch(m.kickoff_at, False, ga, gh, up.home_before, m.competition_id, m.season))
        self.league[m.competition_id].append((gh, ga))
        self.n_inputs += 1
        if self.newest_input_at is None or m.kickoff_at > self.newest_input_at:
            self.newest_input_at = m.kickoff_at
        self._digest.update(f"{m.fixture_id}:{gh}-{ga};".encode())
        self.elo_history.append(EloRecord(m.home_team_id, m.fixture_id, m.kickoff_at, up.home_before,
                                          up.home_after, up.expected_home, up.actual_home, up.k, up.multiplier))
        self.elo_history.append(EloRecord(m.away_team_id, m.fixture_id, m.kickoff_at, up.away_before,
                                          up.away_after, 1.0 - up.expected_home, 1.0 - up.actual_home,
                                          up.k, up.multiplier))

    def features(self, t: MatchRecord, cutoff: datetime) -> FeatureVector:
        home = list(self.teams[t.home_team_id])
        away = list(self.teams[t.away_team_id])
        h5, a5 = home[-FORM_N:], away[-FORM_N:]
        h10, a10 = home[-STRENGTH_N:], away[-STRENGTH_N:]
        hh5 = [x for x in home if x.at_home][-FORM_N:]
        aa5 = [x for x in away if not x.at_home][-FORM_N:]
        league = self.league[t.competition_id]
        per_team = (sum(gh + ga for gh, ga in league) / (2 * len(league))) if league else None
        eh, ea = self.book.rating(t.home_team_id), self.book.rating(t.away_team_id)
        advantage = 0.0 if t.is_neutral else self.book.params.home_advantage

        def rest(ms: list[TeamMatch]) -> float | None:
            return (t.kickoff_at - ms[-1].kickoff_at).total_seconds() / 86400 if ms else None

        def season_n(ms: list[TeamMatch]) -> float:
            return float(sum(1 for x in ms if x.competition_id == t.competition_id and x.season == t.season))

        values: dict[str, float | None] = {
            "elo_home": eh,
            "elo_away": ea,
            "elo_diff": eh - ea,
            "elo_expected_home": expected_score(eh, ea, advantage=advantage),
            "home_gf_avg5": _mean([x.goals_for for x in h5]),
            "home_ga_avg5": _mean([x.goals_against for x in h5]),
            "away_gf_avg5": _mean([x.goals_for for x in a5]),
            "away_ga_avg5": _mean([x.goals_against for x in a5]),
            "home_ppg5": _mean([x.points for x in h5]),
            "away_ppg5": _mean([x.points for x in a5]),
            "home_gf_home5": _mean([x.goals_for for x in hh5]),
            "home_ga_home5": _mean([x.goals_against for x in hh5]),
            "away_gf_away5": _mean([x.goals_for for x in aa5]),
            "away_ga_away5": _mean([x.goals_against for x in aa5]),
            "home_attack": _ratio(_mean([x.goals_for for x in h10]), per_team),
            "home_defence": _ratio(_mean([x.goals_against for x in h10]), per_team),
            "away_attack": _ratio(_mean([x.goals_for for x in a10]), per_team),
            "away_defence": _ratio(_mean([x.goals_against for x in a10]), per_team),
            "home_rest_days": rest(home),
            "away_rest_days": rest(away),
            "home_sos5": _mean([x.opponent_elo_before for x in h5]),
            "away_sos5": _mean([x.opponent_elo_before for x in a5]),
            "league_goals_avg": (sum(gh + ga for gh, ga in league) / len(league)) if league else None,
            "league_home_win_rate": (sum(1 for gh, ga in league if gh > ga) / len(league)) if league else None,
            "is_neutral": 1.0 if t.is_neutral else 0.0,
            "is_cup": 0.0 if t.competition_type == "domestic_league" else 1.0,
            "home_season_matches": season_n(home),
            "away_season_matches": season_n(away),
            "home_history_n": float(len(home)),
            "away_history_n": float(len(away)),
        }
        assert set(values) == set(FEATURE_NAMES)
        return FeatureVector(
            fixture_id=t.fixture_id, kickoff_at=t.kickoff_at, data_cutoff=cutoff, values=values,
            n_inputs=self.n_inputs, newest_input_at=self.newest_input_at,
            input_hash=self._digest.copy().hexdigest(),
        )


def walk_forward(
    history: Sequence[MatchRecord],
    targets: Sequence[tuple[MatchRecord, datetime]],
    params: EloParams | None = None,
) -> tuple[list[FeatureVector], list[EloRecord]]:
    """Feature vectors for ``targets`` (fixture, cut-off), and the Elo history.

    ``history`` may contain the targets themselves with their results: a
    target's own result becomes available three hours after its kick-off,
    which is always after its cut-off, so it never informs its own features.
    """
    params = params or EloParams()
    events: list[tuple[datetime, int, datetime, int, MatchRecord]] = []
    for m in history:
        if m.has_result:
            events.append((m.kickoff_at + RESULT_AVAILABLE_AFTER, 1, m.kickoff_at, m.fixture_id, m))
    for t, cutoff in targets:
        if cutoff > t.kickoff_at:
            raise LeakageError(f"cut-off {cutoff.isoformat()} is after kick-off of fixture {t.fixture_id}")
        events.append((cutoff, 0, t.kickoff_at, t.fixture_id, t))
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    state = WalkForward(params)
    vectors: list[FeatureVector] = []
    for at, kind, _ko, _fid, m in events:
        if kind == 1:
            state.ingest(m)
        else:
            v = state.features(m, at)
            if v.newest_input_at is not None and v.newest_input_at >= v.data_cutoff:
                raise LeakageError(f"fixture {m.fixture_id}: an input at {v.newest_input_at} is not before {at}")
            vectors.append(v)
    return vectors, state.elo_history
