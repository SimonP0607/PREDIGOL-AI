"""The rules of a competition, as data (IA-072, plan piece AD-B01): format, phases, zones, tie-breakers in order, the tables
that decide each zone (a phase's table, an annual or accumulated one, an average), play-offs, promotion and relegation, and
continental places - one file per competition and version under ``config/rules/``, each with the official source it was read
from and the day it was checked.

WHY
---
``fbi.competitions.context`` says "nothing is assumed about the rules of a competition", and that is right: the rules differ
(UEFA ranks a league phase by goal difference and then by its opponents' points, LaLiga by head-to-head, Brazil by wins first)
and they change (Colombia's 2026 tournament I ends in quarter-finals, its tournament II in two groups of four; Liga MX dropped
its play-in between the Apertura 2025 and the Clausura 2026). What a team "is playing for" cannot be said without them. This
module is the one place that holds them; the scenarios engine (AD-B02) and the private views read it, nothing else.

WHAT IT GUARANTEES
------------------
* A competition is either CODED - a file whose every rule was read in an official regulation, linked with its date - or
  explicitly NOT CODED, with the reason (``coverage.yaml``). ``rules_for`` never guesses and never infers a rule from the
  provider's table: a missing file, a season the file does not cover, a retired version - all answer ``NotCoded``.
* What a coded file could not establish is listed in its ``gaps`` (Argentina's relegations are set by the AFA Statute, which was
  not read): a reader must not assert anything on those topics.
* Only parameters and links are kept, never the text of a regulation.
* Versions are added, never rewritten: a correction is a new version (or the old one ``state: retired`` with its reason), and
  ``core.competition_rules`` (migration 0143) records every version loaded, append-only.

Pure: reading the files touches no database, no network and no model. The arithmetic that applies the tie-breakers to results
is ``fbi.competitions.ranking``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

VERSION: Final = "rules-v1"
"""The reader's own version: what ``rules_for`` answers and how. A change to the answer bumps it."""

SCHEMA: Final = "competition-rules/1"
COVERAGE_SCHEMA: Final = "competition-rules-coverage/1"
RULES_DIR: Final = Path(__file__).resolve().parents[3] / "config" / "rules"
COVERAGE_FILE: Final = "coverage.yaml"

Criterion = Literal[
    # computed from the results of the phase (or table) being ranked; ``points`` only where a table's own metric is another one
    # (an average whose ties are broken on the points of a stated scope)
    "points", "goal_difference", "goals_for", "goals_against_fewer", "wins", "away_goals_for", "away_goals_against_fewer",
    "away_goal_difference", "away_wins", "home_goal_difference", "home_goals_for",
    # computed from the matches between the tied teams only
    "h2h_points", "h2h_goal_difference", "h2h_goals_for", "h2h_away_goals_for",
    # computed from the results of each team's opponents (UEFA league phase)
    "opponents_points", "opponents_goal_difference", "opponents_goals_for",
    # not in the results: given by the caller, or the tie stays open
    "fair_play", "disciplinary_points", "red_cards_fewer", "yellow_cards_fewer", "club_coefficient", "coefficient_table",
    "prior_phase_rank", "seed_priority", "lots", "playoff", "official_decision",
]
H2H_CRITERIA: Final = frozenset({"h2h_points", "h2h_goal_difference", "h2h_goals_for", "h2h_away_goals_for"})
EXTERNAL_CRITERIA: Final = frozenset({"fair_play", "disciplinary_points", "red_cards_fewer", "yellow_cards_fewer",
                                      "club_coefficient", "coefficient_table", "prior_phase_rank", "seed_priority",
                                      "lots", "playoff", "official_decision"})
TERMINAL_CRITERIA: Final = frozenset({"lots", "playoff", "official_decision"})
"""Criteria that end the list: nothing the code can compute decides them, and nothing may follow them."""

ZoneKind = Literal["champion", "next_phase", "playoff_place", "continental", "relegation", "relegation_playoff",
                   "promotion", "eliminated", "title_playoff"]
GapTopic = Literal["format", "tiebreak", "relegation", "promotion", "continental", "table", "playoff", "seeding"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Source(_Model):
    publisher: str = Field(min_length=2, max_length=200)
    title: str = Field(min_length=3, max_length=300)
    url: str = Field(pattern=r"^https://[^\s]+$", max_length=600)
    published: date | None = None
    checked_at: date
    applies_to: str = Field(min_length=2, max_length=120)
    articles: str | None = Field(default=None, max_length=300)


class Points(_Model):
    win: int = Field(default=3, ge=0, le=5)
    draw: int = Field(default=1, ge=0, le=5)
    loss: int = Field(default=0, ge=0, le=5)


class Tiebreak(_Model):
    criterion: Criterion
    when: Literal["always", "complete", "decisive"] = "always"
    """``complete``: only once every match of the phase is played. ``decisive``: only once complete AND for a tie that decides
    something (the tied teams straddle a zone boundary or the title) - e.g. the Premier League's head-to-head (rule C.17)."""
    note: str | None = Field(default=None, max_length=400)

    @model_validator(mode="before")
    @classmethod
    def _from_name(cls, value: Any) -> Any:
        return {"criterion": value} if isinstance(value, str) else value


class HeadToHead(_Model):
    mode: Literal["once", "reapply"] = "once"
    """``once``: the head-to-head criteria are computed among the teams tied on points (LaLiga). ``reapply``: when they separate
    some of them, they are computed again among those still level (UEFA, Argentina)."""
    requires_all_played: bool = False
    """Applied only when every match between the tied teams has been played (Ligue 1, Bundesliga)."""
    max_teams: int | None = Field(default=None, ge=2)
    """Skipped when more teams than this are tied (Brazil: head-to-head only between two)."""


class Ranking(_Model):
    tiebreakers: tuple[Tiebreak, ...] = Field(min_length=1)
    tiebreakers_if_two: tuple[Tiebreak, ...] | None = None
    """When exactly two teams are level and the regulation lists other criteria for that case (LaLiga)."""
    in_progress: tuple[Tiebreak, ...] | None = None
    """The criteria while the phase is being played, when the regulation says (UEFA: a to e; Bundesliga: the first two)."""
    in_progress_fallback: Literal["shared", "alphabetical"] = "shared"
    h2h: HeadToHead = HeadToHead()
    note: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def _terminal_last(self) -> Ranking:
        for name, chain in (("tiebreakers", self.tiebreakers), ("tiebreakers_if_two", self.tiebreakers_if_two),
                            ("in_progress", self.in_progress)):
            if chain is None:
                continue
            names = [t.criterion for t in chain]
            if len(set(names)) != len(names):
                raise ValueError(f"{name}: a criterion is listed twice")
            for i, t in enumerate(chain[:-1]):
                if t.criterion in TERMINAL_CRITERIA:
                    raise ValueError(f"{name}: {t.criterion} ends the list, nothing may follow it (position {i + 1})")
        return self


class Zone(_Model):
    kind: ZoneKind
    from_: int | None = Field(default=None, alias="from", ge=1)
    to: int | None = Field(default=None, ge=1)
    last: int | None = Field(default=None, ge=1)
    """Counted from the bottom: the last ``last`` places (a table whose size can change)."""
    target: str | None = Field(default=None, max_length=200)
    per_group: bool = False
    """The places are of each group (zone, conference) rather than of the whole table."""
    conditional: bool = False
    """The place depends on something outside this table (a cup winner, an access list): never certified from the table."""
    note: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _one_way(self) -> Zone:
        if (self.last is None) == (self.from_ is None):
            raise ValueError("a zone is either from/to (counted from the top) or last (counted from the bottom)")
        if self.from_ is not None and (self.to is None or self.to < self.from_):
            raise ValueError("a zone counted from the top needs to >= from")
        return self

    def positions(self, size: int) -> range:
        """The 1-based places of a table of ``size`` teams this zone covers."""
        if self.last is not None:
            return range(max(1, size - self.last + 1), size + 1)
        assert self.from_ is not None and self.to is not None
        return range(self.from_, min(self.to, size) + 1)


class Knockout(_Model):
    legs: Literal[1, 2, 3]
    """1: a single match; 2: home and away; 3: a best-of-three series."""
    level: tuple[Literal["points_over_legs", "aggregate", "away_goals", "extra_time", "penalties",
                         "better_league_position", "replay"], ...]
    """What decides a tie, in order (``aggregate`` = goals over the legs; ``points_over_legs`` = points of the legs, Colombia).
    Empty when the source read does not state it: nothing is assumed."""
    seeding: str | None = Field(default=None, max_length=400)


class Phase(_Model):
    key: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=120)
    format: Literal["league", "groups", "league_phase", "knockout"]
    rounds: tuple[str, ...] = Field(min_length=1)
    """The provider's round labels this phase covers, as shell patterns (``Regular Season - *``)."""
    teams: int | None = Field(default=None, ge=2, le=80)
    groups: int | None = Field(default=None, ge=2, le=16)
    group_size: int | None = Field(default=None, ge=2, le=40)
    schedule: Literal["single_round_robin", "double_round_robin", "swiss", "ties", "other"]
    matches_per_team: int | None = Field(default=None, ge=1, le=60)
    ranking: Ranking | None = None
    knockout: Knockout | None = None
    zones: tuple[Zone, ...] = ()
    note: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def _shape(self) -> Phase:
        if self.format == "knockout":
            if self.knockout is None or self.ranking is not None:
                raise ValueError(f"{self.key}: a knockout phase has a knockout rule and no ranking")
        elif self.ranking is None:
            raise ValueError(f"{self.key}: a {self.format} phase needs its ranking")
        if self.format == "groups" and (self.groups is None or self.group_size is None):
            raise ValueError(f"{self.key}: a group phase says how many groups and of what size")
        size = self.table_size
        for z in self.zones:
            if size is not None and z.from_ is not None and z.to is not None and z.to > size:
                raise ValueError(f"{self.key}: zone {z.kind} {z.from_}-{z.to} beyond a table of {size}")
        return self

    @property
    def table_size(self) -> int | None:
        return self.group_size if self.format == "groups" else self.teams

    @property
    def legs_between_pair(self) -> int | None:
        """How many matches two teams of the same table play each other in this phase, when the schedule says it."""
        return {"single_round_robin": 1, "double_round_robin": 2}.get(self.schedule)

    def covers(self, round_label: str | None) -> bool:
        return bool(round_label) and any(fnmatch.fnmatchcase(str(round_label), p) for p in self.rounds)


class Tournament(_Model):
    key: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=120)
    phases: tuple[Phase, ...] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def _unique(self) -> Tournament:
        keys = [p.key for p in self.phases]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{self.key}: phase keys repeat")
        return self


class PastSeason(_Model):
    """An earlier season an average counts (BE-075): the provider's season key and the round labels of the phases that count,
    as shell patterns - an earlier season has no rules file of its own, so its phases are named here."""

    season: int = Field(ge=1990, le=2100)
    rounds: tuple[str, ...] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=300)


class Window(_Model):
    """The seasons a named club's average counts when the regulation says so (BE-075; Colombia art. 32: a promoted club)."""

    team: int = Field(ge=1)
    """The provider's team id (``core.teams.provider_team_id``)."""
    name: str = Field(min_length=2, max_length=120)
    seasons: tuple[int, ...] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=300)


class Slot(_Model):
    """One place a table gives (BE-075): who takes it, in the regulation's order."""

    slot: str = Field(min_length=2, max_length=60)
    source: Literal["champion", "cup_winner", "table_rank"]
    """``champion``: the winner of the last knock-out phase of a tournament of this file (``of``). ``cup_winner``: the winner of
    another competition (``of`` names it), given by the caller - unknown until it is. ``table_rank``: the best placed team of
    this table not given an earlier slot (of any competition of ``places``)."""
    of: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _of(self) -> Slot:
        if (self.source in ("champion", "cup_winner")) != bool(self.of):
            raise ValueError(f"slot {self.slot}: 'of' names the tournament or cup of a champion, and only then")
        return self


class Places(_Model):
    """The places in another competition a table gives (BE-075; Colombia arts. 30-31), allocated in order. A case the
    regulation settles in a paragraph that is not coded here (the same club twice) is never resolved by the code: the
    allocation stops and says so."""

    competition: str = Field(min_length=2, max_length=120)
    article: str = Field(min_length=2, max_length=60)
    slots: tuple[Slot, ...] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=400)


class Table(_Model):
    key: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["annual", "aggregate", "average"]
    counts: tuple[str, ...] = Field(min_length=1)
    """``tournament.phase`` (or ``tournament.*``) of THIS season whose matches the table adds up."""
    seasons: int = Field(default=1, ge=1, le=5)
    """An average spans this many seasons, the current one included (Colombia: 3)."""
    metric: Literal["points", "points_per_match"] = "points"
    ranking: Ranking
    zones: tuple[Zone, ...] = ()
    exceptions: tuple[str, ...] = ()
    """Cases the regulation settles by name (a promoted club's average built over fewer seasons): said, not computed."""
    past: tuple[PastSeason, ...] = ()
    """BE-075: the earlier seasons an average counts and their phases (``seasons - 1`` of them when given)."""
    windows: tuple[Window, ...] = ()
    """BE-075: ``exceptions`` as data - the seasons a named club's average counts."""
    ties_on: tuple[str, ...] = ()
    """BE-075: ``tournament.phase`` of THIS season whose matches break a tie in the table's metric (Colombia art. 33: the
    average's ties on the Fase I of 2026 only). Empty: the table's own matches."""
    places: tuple[Places, ...] = ()
    """BE-075: the places this table gives, in the order they are allocated."""
    note: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def _past(self) -> Table:
        if self.past and (self.kind != "average" or len(self.past) != self.seasons - 1):
            raise ValueError(f"table {self.key}: 'past' lists the {self.seasons - 1} earlier seasons of an average")
        if len({p.season for p in self.past}) != len(self.past):
            raise ValueError(f"table {self.key}: a past season is listed twice")
        if len({w.team for w in self.windows}) != len(self.windows):
            raise ValueError(f"table {self.key}: a club's window is listed twice")
        return self


class Gap(_Model):
    topic: GapTopic
    reason: str = Field(min_length=10, max_length=600)


class CompetitionRules(_Model):
    schema_: Literal["competition-rules/1"] = Field(alias="schema")
    league_id: int = Field(ge=1)
    """The provider's league id (``core.competitions.provider_league_id``): the one id the repository can know."""
    competition: str = Field(min_length=2, max_length=120)
    country: str = Field(min_length=2, max_length=60)
    version: int = Field(ge=1)
    state: Literal["coded", "retired"] = "coded"
    retired_reason: str | None = Field(default=None, max_length=600)
    seasons: tuple[int, ...] = Field(min_length=1)
    """The provider's season keys (``core.competition_seasons.season``) this version applies to."""
    valid_from: date | None = None
    valid_to: date | None = None
    points: Points = Points()
    sources: tuple[Source, ...] = Field(min_length=1)
    tournaments: tuple[Tournament, ...] = Field(min_length=1)
    tables: tuple[Table, ...] = ()
    gaps: tuple[Gap, ...] = ()
    notes: tuple[str, ...] = ()

    @field_validator("seasons")
    @classmethod
    def _seasons(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) != len(value) or any(s < 1990 or s > 2100 for s in value):
            raise ValueError("seasons are distinct years")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def _coherent(self) -> CompetitionRules:
        if self.state == "retired" and not (self.retired_reason or "").strip():
            raise ValueError("a retired version says why")
        if self.state == "coded" and self.retired_reason:
            raise ValueError("retired_reason only on a retired version")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to before valid_from")
        keys = [t.key for t in self.tournaments]
        if len(set(keys)) != len(keys):
            raise ValueError("tournament keys repeat")
        phases = {(t.key, p.key) for t in self.tournaments for p in t.phases}
        for table in self.tables:
            for ref in table.counts:
                tk, _, pk = ref.partition(".")
                if tk not in keys or (pk != "*" and (tk, pk) not in phases):
                    raise ValueError(f"table {table.key} counts {ref!r}, which is not a phase of this file")
            for ref in table.ties_on:
                if tuple(ref.partition(".")[::2]) not in phases:
                    raise ValueError(f"table {table.key} breaks ties on {ref!r}, which is not a phase of this file")
            if any(p.season >= min(self.seasons) for p in table.past):
                raise ValueError(f"table {table.key}: a past season is not earlier than the seasons of this file")
            for places in table.places:
                for s in places.slots:
                    if s.source == "champion" and s.of not in keys:
                        raise ValueError(f"table {table.key}: slot {s.slot} is the champion of {s.of!r}, not a tournament here")
        return self

    def phases(self) -> Iterable[tuple[Tournament, Phase]]:
        for t in self.tournaments:
            for p in t.phases:
                yield t, p

    def phase_of_round(self, round_label: str | None) -> tuple[Tournament, Phase] | None:
        """The tournament and phase a provider round label belongs to (``Clausura - Quadrangular - 3``), or None."""
        for t, p in self.phases():
            if p.covers(round_label):
                return t, p
        return None

    def phase(self, ref: str) -> tuple[Tournament, Phase]:
        tk, _, pk = ref.partition(".")
        for t, p in self.phases():
            if t.key == tk and p.key == pk:
                return t, p
        raise KeyError(ref)

    def table(self, key: str) -> Table:
        for t in self.tables:
            if t.key == key:
                return t
        raise KeyError(key)

    def gap(self, topic: GapTopic) -> Gap | None:
        return next((g for g in self.gaps if g.topic == topic), None)


# ── coverage: every tracked competition, coded or not, with the reason ──────


NotCodedReason = Literal["no_official_source_read", "source_unreachable", "not_yet_coded", "season_not_covered",
                         "version_retired", "outside_scope"]


class CoverageEntry(_Model):
    league_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=120)
    country: str = Field(min_length=2, max_length=60)
    type: Literal["league", "cup"]
    status: Literal["coded", "not_coded"]
    reason: NotCodedReason | None = None
    detail: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def _reason(self) -> CoverageEntry:
        if self.status == "not_coded" and (self.reason is None or not (self.detail or "").strip()):
            raise ValueError(f"{self.league_id}: a competition not coded says why (reason and detail)")
        if self.status == "coded" and self.reason is not None:
            raise ValueError(f"{self.league_id}: a coded competition has no reason")
        return self


class Coverage(_Model):
    schema_: Literal["competition-rules-coverage/1"] = Field(alias="schema")
    measured_at: date
    measured_from: str = Field(min_length=10, max_length=400)
    competitions: tuple[CoverageEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Coverage:
        ids = [c.league_id for c in self.competitions]
        if len(set(ids)) != len(ids):
            raise ValueError("a league id is listed twice")
        return self

    def entry(self, league_id: int) -> CoverageEntry | None:
        return next((c for c in self.competitions if c.league_id == league_id), None)


# ── the files ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RulesFile:
    path: str
    """Relative to ``config/rules`` (what the database records)."""
    sha256: str
    rules: CompetitionRules

    @property
    def key(self) -> tuple[int, int]:
        return self.rules.league_id, self.rules.version

    def as_json(self) -> dict[str, Any]:
        return self.rules.model_dump(mode="json", by_alias=True, exclude_none=True)


class RulesError(ValueError):
    """A rules file (or the coverage) that does not hold to the schema: the message names the file and the field."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_file(path: Path, *, root: Path = RULES_DIR) -> RulesFile:
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw)
        rules = CompetitionRules.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        raise RulesError(f"{path.relative_to(root)}: {exc}") from exc
    return RulesFile(path=path.relative_to(root).as_posix(), sha256=_sha256(raw), rules=rules)


def load_coverage(root: Path = RULES_DIR) -> Coverage:
    path = root / COVERAGE_FILE
    try:
        return Coverage.model_validate(yaml.safe_load(path.read_bytes()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RulesError(f"{COVERAGE_FILE}: {exc}") from exc


def load_files(root: Path = RULES_DIR) -> tuple[RulesFile, ...]:
    """Every rules file under ``root`` (one directory per competition), validated, in path order."""
    files = [parse_file(p, root=root) for p in sorted(root.glob("*/*.yaml"))]
    seen: dict[tuple[int, int], str] = {}
    for f in files:
        if f.key in seen:
            raise RulesError(f"{f.path}: league {f.key[0]} version {f.key[1]} is also {seen[f.key]}")
        seen[f.key] = f.path
    return tuple(files)


def validate(root: Path = RULES_DIR) -> list[str]:
    """Everything wrong with the files and the coverage, as sentences (empty when it all holds)."""
    problems: list[str] = []
    try:
        files = load_files(root)
    except RulesError as exc:
        return [str(exc)]
    try:
        coverage = load_coverage(root)
    except RulesError as exc:
        return [str(exc)]
    coded = {f.rules.league_id for f in files if f.rules.state == "coded"}
    for f in files:
        entry = coverage.entry(f.rules.league_id)
        if entry is None:
            problems.append(f"{f.path}: league {f.rules.league_id} is not in {COVERAGE_FILE}")
        elif entry.status != "coded" and f.rules.state == "coded":
            problems.append(f"{f.path}: {COVERAGE_FILE} says league {f.rules.league_id} is not coded")
        if not Path(f.path).parent.name.startswith(f"{f.rules.league_id}_"):
            problems.append(f"{f.path}: the directory is named <league_id>_<name>")
        if Path(f.path).name != f"v{f.rules.version}.yaml":
            problems.append(f"{f.path}: the file of version {f.rules.version} is v{f.rules.version}.yaml")
    for entry in coverage.competitions:
        if entry.status == "coded" and entry.league_id not in coded:
            problems.append(f"{COVERAGE_FILE}: league {entry.league_id} is marked coded and has no coded file")
    by_league: dict[int, list[RulesFile]] = {}
    for f in files:
        if f.rules.state == "coded":
            by_league.setdefault(f.rules.league_id, []).append(f)
    for league, versions in by_league.items():
        for i, a in enumerate(versions):
            for b in versions[i + 1:]:
                if set(a.rules.seasons) & set(b.rules.seasons) and _windows_overlap(a.rules, b.rules):
                    problems.append(f"league {league}: versions {a.rules.version} and {b.rules.version} both answer "
                                    f"for seasons {sorted(set(a.rules.seasons) & set(b.rules.seasons))} on the same days")
    return problems


def _windows_overlap(a: CompetitionRules, b: CompetitionRules) -> bool:
    lo_a, hi_a = a.valid_from or date.min, a.valid_to or date.max
    lo_b, hi_b = b.valid_from or date.min, b.valid_to or date.max
    return lo_a <= hi_b and lo_b <= hi_a


# ── the reader ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Coded:
    league_id: int
    season: int
    file: RulesFile
    status: Literal["coded"] = "coded"

    @property
    def rules(self) -> CompetitionRules:
        return self.file.rules

    def as_json(self) -> dict[str, Any]:
        return {"status": self.status, "league_id": self.league_id, "season": self.season,
                "version": self.rules.version, "file": self.file.path, "sha256": self.file.sha256,
                "gaps": [g.model_dump(mode="json") for g in self.rules.gaps], "reader": VERSION}


@dataclass(frozen=True, slots=True)
class NotCoded:
    league_id: int
    season: int
    reason: NotCodedReason
    detail: str
    status: Literal["reglamento_no_codificado"] = "reglamento_no_codificado"

    def as_json(self) -> dict[str, Any]:
        return {"status": self.status, "league_id": self.league_id, "season": self.season, "reason": self.reason,
                "detail": self.detail, "reader": VERSION}


Answer = Coded | NotCoded


@dataclass(frozen=True, slots=True)
class Library:
    """The files and the coverage, read once. ``rules_for`` uses the repository's; a test builds its own."""

    files: tuple[RulesFile, ...]
    coverage: Coverage

    @classmethod
    def read(cls, root: Path = RULES_DIR) -> Library:
        return cls(files=load_files(root), coverage=load_coverage(root))

    def versions(self, league_id: int) -> list[RulesFile]:
        return sorted((f for f in self.files if f.rules.league_id == league_id), key=lambda f: f.rules.version)

    def rules_for(self, league_id: int, season: int, *, on: date | None = None) -> Answer:
        versions = self.versions(league_id)
        entry = self.coverage.entry(league_id)
        if not versions:
            if entry is not None and entry.status == "not_coded" and entry.reason and entry.detail:
                return NotCoded(league_id, season, entry.reason, entry.detail)
            return NotCoded(league_id, season, "not_yet_coded",
                            "No rules file for this competition: nothing is assumed about its rules.")
        for_season = [f for f in versions if season in f.rules.seasons]
        if not for_season:
            covered = sorted({s for f in versions for s in f.rules.seasons})
            detail = f"The rules on file cover seasons {covered}, not {season}."
            if entry is not None and entry.detail:
                detail = f"{detail} {entry.detail}"
            return NotCoded(league_id, season, "season_not_covered", detail)
        if on is not None:
            for_season = [f for f in for_season
                          if (f.rules.valid_from or date.min) <= on <= (f.rules.valid_to or date.max)]
            if not for_season:
                return NotCoded(league_id, season, "season_not_covered",
                                f"No version of the rules of season {season} is in force on {on.isoformat()}.")
        live = [f for f in for_season if f.rules.state == "coded"]
        if not live:
            last = for_season[-1].rules
            return NotCoded(league_id, season, "version_retired",
                            f"Version {last.version} was retired: {last.retired_reason}")
        return Coded(league_id, season, live[-1])


@lru_cache(maxsize=1)
def library() -> Library:
    return Library.read()


def rules_for(league_id: int, season: int, *, on: date | None = None) -> Answer:
    """The rules in force for a competition season (by the provider's league id and season key) - on a day when ``on`` is
    given - or ``NotCoded`` with the reason. Never raises for a competition or season it does not know."""
    return library().rules_for(league_id, season, on=on)


def fingerprint(files: Iterable[RulesFile]) -> str:
    """One hash of a set of rules files (what a reader that cached them can compare)."""
    return _sha256(json.dumps(sorted((f.path, f.sha256) for f in files)).encode())


def summary(lib: Library, tracked: Mapping[int, str] | None = None) -> dict[str, Any]:
    """How many competitions are coded, not coded (by reason), and - given the tracked ones - missing from the coverage."""
    by_reason: dict[str, int] = {}
    for c in lib.coverage.competitions:
        if c.status == "not_coded" and c.reason:
            by_reason[c.reason] = by_reason.get(c.reason, 0) + 1
    out: dict[str, Any] = {
        "reader": VERSION,
        "leagues": sum(1 for c in lib.coverage.competitions if c.type == "league"),
        "leagues_coded": sum(1 for c in lib.coverage.competitions if c.type == "league" and c.status == "coded"),
        "cups": sum(1 for c in lib.coverage.competitions if c.type == "cup"),
        "cups_coded": sum(1 for c in lib.coverage.competitions if c.type == "cup" and c.status == "coded"),
        "not_coded_by_reason": dict(sorted(by_reason.items())),
        "files": len(lib.files), "fingerprint": fingerprint(lib.files),
    }
    if tracked is not None:
        out["tracked_missing_from_coverage"] = sorted(i for i in tracked if lib.coverage.entry(i) is None)
    return out
