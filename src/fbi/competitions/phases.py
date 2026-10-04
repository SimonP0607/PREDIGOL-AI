"""A competition season is not one table: its stages and phases, and the provider's tables mapped to them.

``/standings?league&season`` answers a LIST of tables (``response[].league.standings[]``), and one
season can hold many: a split season's Apertura and Clausura (Colombia, Peru, Mexico), the groups
of a phase (Argentina's "Apertura - Group A"), conferences (MLS), a tournament's groups and the
ranking of its third-placed teams (World Cup 2026), cumulative championship and relegation groups
(Ecuador), an annual aggregate (Peru's "Tabla Anual"), period tables (Eerste Divisie). Each is kept
as its own table (``core.standings.group_key``, the n-th table under a repeated label is
"<label> #n"); this module says which part of the season each one ranks, so no page mixes two.

Stages come from the fixtures' round labels: the label without its match-day number. "Clausura - 12"
is match day 12 of the stage "Clausura"; "Apertura - Quarter-finals" is a knockout stage;
"Apertura - Quadrangular - 3" a league-format play-off group. The phase is the label's first part
("Apertura").

A table is mapped to a stage by, in order:

1. ``label`` - its label names one of the season's league stages ("Apertura - Group A" -> Apertura,
   "Liga Pro: Championship Group" -> Championship Group, "League A - Group B" -> League A);
2. ``games`` - the games each of its teams has played agree, on most rows, with that team's
   finished matches in one league stage at the snapshot's time (World Cup "Group C" -> Group Stage,
   "UEFA Champions League" -> League Stage), or in all of them together (Peru's "Tabla Anual": an
   aggregate);
3. ``single`` - the season has one league stage and no table ranks it by games (a provider a match
   day behind still ranks the only stage there is).

Table kinds within a stage: ``full`` (the stage's only table, or the one holding all the others),
``group`` (one of several: groups, conferences, a division inside the full table), ``ranking``
(ranks teams the stage's groups already rank: the third-placed teams), ``aggregate`` (counts several
stages), ``other`` (ranks something the rounds do not name, e.g. period tables; never used for a
match). Nothing here reads a payload or writes a row: it is a pure function of stored facts, run
when a page is built, so it cannot go stale.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

VERSION = "phases-1"
"""Bumped whenever a rule below changes what a table maps to; pages and audits report it."""

StageKind = Literal["league", "knockout", "qualifying", "friendly"]
TableKind = Literal["full", "group", "ranking", "aggregate", "other"]
Method = Literal["label", "games", "single", "unmapped"]
Reason = Literal["fixture_stage", "phase_league_stage", "previous_stage"]

MATCH_DAY = re.compile(r"\s*-\s*\d+\s*$")
KNOCKOUT = re.compile(r"final|play-?offs?|knockout|round of|quarter|semi|8th|16th|1/\d|qualifying|qualification|preliminary|"
                      r"promotion|relegation (?:play|deciding)|third place|super cup|repechage|elimination",
                      re.IGNORECASE)
"""Rounds no league table counts (the truth audit's rule, shared)."""
STRICT_KNOCKOUT = re.compile(r"final|semi|quarter|round of|1/\d|8th|16th|32nd|play-?offs?(?!\s*group)|knockout|"
                             r"repechage|third place|3rd place", re.IGNORECASE)
"""Knock-out words that still mean knock-out when the rounds carry a match-day number."""
LEAGUE_FORMAT = re.compile(r"\bgroups?\b|quadrangular|hexagonal|triangular|pentagonal|octagonal|"
                           r"league (?:stage|phase)|round robin|championship round|relegation round|regular season",
                           re.IGNORECASE)
QUALIFYING = re.compile(r"qualif|preliminary", re.IGNORECASE)
UNNUMBERED_KNOCKOUT = re.compile(r"\b\d+(?:st|nd|rd|th) (?:round|phase)\b|\bround \d+\b", re.IGNORECASE)
FRIENDLY = re.compile(r"friendl", re.IGNORECASE)
LABEL_COPY = re.compile(r"\s*#\d+$")
LAG = timedelta(hours=30)
"""A table may be up to this far behind its snapshot (the provider updates hourly; a slow day)."""
RUNNING_AFTER = timedelta(days=3)


def stage_of(round_label: str | None) -> str:
    """The round label without its match-day number: "Apertura - 7" -> "Apertura", "Apertura -
    Quadrangular - 3" -> "Apertura - Quadrangular", "Round of 16" -> "Round of 16"."""
    return MATCH_DAY.sub("", round_label or "").strip()


def phase_of(label: str | None) -> str:
    """The first part of a round or stage label: "Apertura - Quarter-finals" -> "Apertura"."""
    return (label or "").split(" - ")[0].strip()


def fold(s: str) -> str:
    """Lower case without accents: "Primera División" and "Primera Division" are one name."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def stage_kind(stage: str, *, numbered: bool) -> StageKind:
    """``league`` (a table counts it), ``knockout``, ``qualifying`` or ``friendly``. Rounds with a
    match-day number are a league format unless a knock-out word says otherwise; "Championship
    Group", "Quadrangular" and "Conference League Play-off Group" are league formats whatever else
    they say."""
    if FRIENDLY.search(stage):
        return "friendly"
    if LEAGUE_FORMAT.search(stage):
        return "league"
    if numbered:
        return "knockout" if STRICT_KNOCKOUT.search(stage) else "league"
    if QUALIFYING.search(stage):
        return "qualifying"
    if KNOCKOUT.search(stage) or UNNUMBERED_KNOCKOUT.search(stage):
        return "knockout"
    return "league"


@dataclass(frozen=True)
class Stage:
    name: str
    phase: str
    kind: StageKind
    ordinal: int
    first_kickoff: datetime | None
    last_kickoff: datetime | None
    fixtures: int
    finished: int
    numbered: bool


@dataclass(frozen=True)
class RoundCount:
    """One round label of a season: its fixtures, finished ones, first and last kick-off."""

    round: str | None
    first_kickoff: datetime | None
    last_kickoff: datetime | None
    fixtures: int
    finished: int


@dataclass
class _Acc:
    first: datetime | None = None
    last: datetime | None = None
    fixtures: int = 0
    finished: int = 0
    numbered: bool = False


def stages_from_rounds(rounds: Iterable[RoundCount]) -> list[Stage]:
    """The season's stages in the order they start."""
    acc: dict[str, _Acc] = {}
    for r in rounds:
        name = stage_of(r.round)
        if not name:
            continue
        a = acc.setdefault(name, _Acc())
        a.numbered = a.numbered or MATCH_DAY.search(r.round or "") is not None
        if r.first_kickoff is not None and (a.first is None or r.first_kickoff < a.first):
            a.first = r.first_kickoff
        if r.last_kickoff is not None and (a.last is None or r.last_kickoff > a.last):
            a.last = r.last_kickoff
        a.fixtures += r.fixtures
        a.finished += r.finished

    def order(item: tuple[str, _Acc]) -> tuple[bool, float, str]:
        first = item[1].first
        return (first is None, first.timestamp() if first is not None else 0.0, item[0])

    return [Stage(name, phase_of(name), stage_kind(name, numbered=a.numbered), i, a.first, a.last, a.fixtures,
                  a.finished, a.numbered)
            for i, (name, a) in enumerate(sorted(acc.items(), key=order))]


@dataclass(frozen=True)
class Match:
    stage: str
    home: int
    away: int
    kickoff: datetime
    finished: bool


@dataclass(frozen=True)
class TableIn:
    """One stored table of one snapshot: its key (``core.standings.group_key``) and each team's games."""

    key: str
    played: Mapping[int, int | None]


@dataclass
class TableMap:
    key: str
    label: str
    teams: frozenset[int]
    played: Mapping[int, int | None] = field(repr=False)
    stage: str | None = None
    stages: tuple[str, ...] = ()
    phase: str | None = None
    kind: TableKind = "other"
    method: Method = "unmapped"
    agree: int = 0
    note: str = ""

    @property
    def rows(self) -> int:
        return len(self.teams)

    @property
    def counted(self) -> int:
        return sum(1 for p in self.played.values() if p is not None)


Counts = dict[str, Counter[int]]
_NONE: Counter[int] = Counter()


def counts_at(matches: Iterable[Match], at: datetime) -> tuple[Counts, Counts]:
    """Each team's finished matches per stage that kicked off before ``at`` (the most a table taken
    at ``at`` can count) and before ``at - LAG`` (the least it should)."""
    hi: Counts = defaultdict(Counter)
    lo: Counts = defaultdict(Counter)
    floor = at - LAG
    for m in matches:
        if not m.finished or m.kickoff >= at:
            continue
        for team in (m.home, m.away):
            hi[m.stage][team] += 1
            if m.kickoff < floor:
                lo[m.stage][team] += 1
    return hi, lo


def agreement(played: Mapping[int, int | None], stages: Sequence[str], hi: Counts, lo: Counts) -> int:
    """Rows whose games played lie between the least and the most the stages' matches allow."""
    n = 0
    for team, p in played.items():
        if p is None:
            continue
        top = sum(hi.get(s, _NONE).get(team, 0) for s in stages)
        bottom = sum(lo.get(s, _NONE).get(team, 0) for s in stages)
        if bottom <= p <= top:
            n += 1
    return n


def _majority(agree: int, counted: int) -> bool:
    return counted > 0 and agree * 2 > counted


def _named(label: str, league: Sequence[Stage]) -> Stage | None:
    """The league stage the label names (the longest name found as whole words)."""
    text = fold(label)
    hits = [s for s in league
            if re.search(r"(?<![a-z0-9])" + re.escape(fold(s.name)) + r"(?![a-z0-9])", text)]
    if not hits:
        return None
    return max(hits, key=lambda s: (len(s.name), s.ordinal))


def _distance(stage: Stage | None, at: datetime) -> float:
    """How far a stage is from ``at``: 0 while it is played, then the next to start, then past ones."""
    if stage is None or stage.first_kickoff is None:
        return 4e9
    last = stage.last_kickoff or stage.first_kickoff
    if stage.first_kickoff <= at <= last + RUNNING_AFTER:
        return 0.0
    if stage.first_kickoff > at:
        return (stage.first_kickoff - at).total_seconds()
    return 2e9 + (at - last).total_seconds()


def _by_games(m: TableMap, league: Sequence[Stage], hi: Counts, lo: Counts, at: datetime) -> None:
    cands: list[tuple[tuple[str, ...], Stage | None]] = [((s.name,), s) for s in league]
    if len(league) > 1:
        cands.append((tuple(s.name for s in league), None))
    best: tuple[tuple[int, int, float], tuple[str, ...], int] | None = None
    for names, stage in cands:
        a = agreement(m.played, names, hi, lo)
        if not _majority(a, m.counted):
            continue
        key = (-a, 0 if stage is not None else 1, _distance(stage, at))
        if best is None or key < best[0]:
            best = (key, names, a)
    if best is not None:
        m.stages, m.agree, m.method = best[1], best[2], "games"
        m.stage = best[1][0] if len(best[1]) == 1 else None


def _single(maps: Sequence[TableMap], league: Sequence[Stage], hi: Counts, lo: Counts) -> None:
    if len(league) != 1:
        return
    only = league[0].name
    if any(m.method == "games" and m.stage == only for m in maps):
        return
    same_teams: dict[frozenset[int], list[TableMap]] = defaultdict(list)
    for m in maps:
        if m.method == "unmapped" and m.teams:
            same_teams[m.teams].append(m)

    def off(m: TableMap) -> int:
        return sum(abs((p or 0) - hi.get(only, _NONE).get(t, 0)) for t, p in m.played.items())

    for tables in same_teams.values():  # parallel tables of one team set: only the closest ranks the stage
        best = min(tables, key=lambda m: (off(m), m.key))
        best.stage, best.stages, best.method = only, (only,), "single"
        best.agree = agreement(best.played, (only,), hi, lo)


def _kinds(maps: Sequence[TableMap]) -> None:
    by_stage: dict[tuple[str, ...], list[TableMap]] = defaultdict(list)
    for m in maps:
        if m.method == "unmapped":
            continue
        if len(m.stages) > 1:
            m.kind = "aggregate"
            continue
        by_stage[m.stages].append(m)
    for tables in by_stage.values():
        if len(tables) == 1:
            tables[0].kind = "full"
            continue
        for m in tables:
            others = [o for o in tables if o is not m]
            rest = frozenset().union(*(o.teams for o in others))
            if m.teams >= rest and len(m.teams) > max(len(o.teams) for o in others):
                m.kind = "full"
            elif any(m.teams < o.teams for o in others):
                m.kind = "group"
            elif m.teams <= rest and sum(1 for o in others if m.teams & o.teams) >= 2:
                m.kind = "ranking"
            else:
                m.kind = "group"
    loose = [m for m in maps if m.method == "unmapped"]
    for m in loose:
        m.kind = "full" if len(maps) == 1 else "other"


def map_tables(tables: Sequence[TableIn], stages: Sequence[Stage], matches: Iterable[Match],
               at: datetime) -> list[TableMap]:
    """Each table of one snapshot (taken at ``at``) with the stage it ranks, how that was decided and
    its kind. Tables keep their order."""
    league = [s for s in stages if s.kind == "league"]
    hi, lo = counts_at(matches, at)
    out = []
    for t in tables:
        label = LABEL_COPY.sub("", t.key)
        m = TableMap(key=t.key, label=label, teams=frozenset(t.played), played=dict(t.played))
        named = _named(label, league) if label else None
        if named is not None:
            m.stage, m.stages, m.method = named.name, (named.name,), "label"
            m.agree = agreement(m.played, m.stages, hi, lo)
            if not _majority(m.agree, m.counted):
                upto = tuple(s.name for s in league if s.ordinal <= named.ordinal)
                if len(upto) > 1 and _majority(agreement(m.played, upto, hi, lo), m.counted):
                    m.note = "cumulative: its games include the earlier stages'"
        else:
            _by_games(m, league, hi, lo, at)
        out.append(m)
    _single(out, league, hi, lo)
    _kinds(out)
    for m in out:
        m.phase = phase_of(m.stage) if m.stage else None
    return out


# ── the table a match is shown with ─────────────────────────────────────────


@dataclass(frozen=True)
class Choice:
    stage: str
    reason: Reason
    keys: Mapping[int, str]
    """Each team's table (the key); one table when it holds both teams."""


def is_split(stages: Sequence[Stage]) -> bool:
    """Two or more phases with a league stage of their own (Apertura and Clausura; a regular season
    and championship/relegation groups): a table of one phase is never shown for another."""
    return len({s.phase for s in stages if s.kind == "league"}) > 1


def choose(fixture_round: str | None, kickoff: datetime, stages: Sequence[Stage], maps: Sequence[TableMap],
           teams: Sequence[int]) -> Choice | None:
    """The table(s) a match is shown with: its own stage's; for a knock-out round, the league stage
    of its phase that came before ("Apertura - Final" -> the Apertura table) or, in a season of one
    league phase, the last league stage before it (a Round of 16 -> the group stage). Never another
    phase's table, never a ranking or an aggregate. None when no table qualifies."""
    usable = [m for m in maps if m.stage and m.kind in ("full", "group")]

    def pick(stage: str, reason: Reason) -> Choice | None:
        tables = [m for m in usable if m.stage == stage]
        both = [m for m in tables if all(t in m.teams for t in teams)]
        keys: dict[int, str] = {}
        if both:
            best = min(both, key=lambda m: (len(m.teams), m.key))
            keys = dict.fromkeys(teams, best.key)
        else:
            for t in teams:
                mine = [m for m in tables if t in m.teams]
                if mine:
                    keys[t] = min(mine, key=lambda m: (len(m.teams), m.key)).key
        return Choice(stage, reason, keys) if keys else None

    own = stage_of(fixture_round)
    if not own:
        return None
    found = pick(own, "fixture_stage")
    if found is not None:
        return found
    me = next((s for s in stages if s.name == own), None)
    kind = me.kind if me else stage_kind(own, numbered=MATCH_DAY.search(fixture_round or "") is not None)
    if kind in ("league", "friendly"):
        return None
    before = [s for s in stages if s.kind == "league" and s.name != own
              and s.first_kickoff is not None and s.first_kickoff < kickoff]
    phase = phase_of(own)
    same = [s for s in before if s.phase == phase]
    reason: Reason
    if same:
        candidates, reason = same, "phase_league_stage"
    elif not is_split(stages):
        candidates, reason = before, "previous_stage"
    else:
        return None
    for s in sorted(candidates, key=lambda s: s.first_kickoff or kickoff, reverse=True):
        found = pick(s.name, reason)
        if found is not None:
            return found
    return None


def current_stage(stages: Sequence[Stage], at: datetime) -> Stage | None:
    """The league stage being played at ``at``: the last one started, else the first to come."""
    league = [s for s in stages if s.kind == "league" and s.first_kickoff is not None]
    started = [s for s in league if s.first_kickoff is not None and s.first_kickoff <= at]
    if started:
        return max(started, key=lambda s: s.first_kickoff or at)
    return min(league, key=lambda s: s.first_kickoff or at) if league else None
