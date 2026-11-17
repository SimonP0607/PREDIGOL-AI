"""What each team of a competition is still playing for (plan 2026, AD-B02, ``scenarios-v2``), in SHADOW: the objectives its regulation
gives (title, next phase, play-off, continental places, promotion, avoiding relegation...), what is MATHEMATICALLY decided - proved
exactly from the table, the matches left and the points system - and, for the rest, how likely each objective is when the matches left
are played out with our goal model.

WHY
---
``stakes-v5`` (``fbi.ai.context.stakes``) reads the provider's description of a row: it does not know the regulation, treats a row
without a description as no zone, reads only the table of the match's phase and knows nothing of the other matches. It wrote "there is
nothing at stake" of teams one point from a play-off place with a match left (Doc 1: 4 of 5 cases checked were false, and the sentence
was in 82 of 432 chronicles). ``scenarios-v1`` (``fbi.intel.scenarios``) does what THIS match alone does to the table and keeps every
other team on its points. Neither can say "decided"; this module can, and only when it is proved.

WHAT IS PROVED, AND HOW
-----------------------
Each objective is "finish within the first N places of this table" (a title is N = 1; avoiding the last three of twenty is N = 17).
For a team T:

* SECURED when, in T's worst case - T loses every match it has left - fewer than N other teams can end with AS MANY points or more.
* LOST when, in T's best case - T wins every match it has left - at least N other teams end with MORE points.

Ties on points always go against the claim (a secured place counts every team level with T as above it; a lost place counts only those
strictly above), so no tie-breaker - goal difference, head-to-head, fair play, lots - is ever needed for a claim to hold: whatever the
regulation's criteria and however the goals fall, a proved claim stays true. The "how many other teams can" is a maximum (or a minimum)
over the results of the matches left: a match between two teams that both matter is enumerated exactly (home win, draw, away win) after
removing the teams the result cannot change; with more than ``ENUM_LIMIT`` such matches the engine falls back to a bound that is looser
and still safe (every contested match given to both sides, or to neither). A team with fewer matches on the calendar than its phase
says (a match not scheduled yet) gets the missing ones as matches it can win or lose against anybody. Point deductions are given as
``adjustments``. When the provider's table and the results disagree on a team's points, both versions are certified and a claim is made
only when both prove it.

A zone the regulation marks ``conditional`` (a continental place that depends on a cup winner) is positioned but NEVER decided. A table
the engine cannot compute (an average over several seasons, a table that adds knock-out rounds) or a group phase whose groups cannot be
identified is reported as such, with no objective asserted. A competition without a coded regulation (``fbi.competitions.rules``) has
status ``reglamento_no_codificado`` and no objective at all.

``SIN_OBJETIVO_DEMOSTRADO`` - the only fact that authorises "nothing is at stake for this team" (AD-F01) - is emitted for a team when
every objective of every table it is in is decided and proved, no zone it could reach is conditional, no table of the competition is
left uncomputed and the regulation has no gap on formats, places, promotion, relegation or play-offs. A language model never writes it.

WHAT IS SIMULATED
-----------------
With a score distribution for every match left (``fbi.competitions.scenario_store``: our Dixon-Coles model, refitted with the spec in
force, the same arithmetic as the real-time forecast), ``sims`` seasons are played out with a fixed seed, every final table ranked with
the regulation's own tie-breakers (``fbi.competitions.ranking``; a tie the results cannot settle - lots, fair play - is drawn at random
with the same seed), and each objective gets the share of seasons in which it is met. A proved claim must be 0 or 1 there: if it is not,
the claim is withdrawn and the reading says so (``contradicciones``). The probability is never a claim of its own: an objective at
0.999 that is not proved is "abierto".

Pure and deterministic: fixtures, rules and distributions in, a reading out. No database, no clock, no model, no network.
"""

from __future__ import annotations

import itertools
import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

import numpy as np
from numpy.typing import NDArray

from fbi.competitions import ranking as rk
from fbi.competitions.rules import Answer, Coded, CompetitionRules, Points, Ranking, Zone

VERSION: Final = "scenarios-v2"
FACT_NO_OBJECTIVE: Final = "SIN_OBJETIVO_DEMOSTRADO"
NOT_CODED: Final = "reglamento_no_codificado"

DEFAULT_SIMS: Final = 2000
DEFAULT_SEED: Final = 20261116
ENUM_LIMIT: Final = 10
"""Contested matches enumerated exactly (3 ** 10 = 59,049 outcomes); with more, the safe bound."""
MAX_RIVALS: Final = 8

FAVOURABLE: Final = frozenset({"champion", "next_phase", "playoff_place", "continental", "promotion", "title_playoff"})
"""Zones a team wants to finish in: the objective is to finish within the zone's last place."""
UNFAVOURABLE: Final = frozenset({"relegation", "relegation_playoff", "eliminated"})
"""Zones a team wants to avoid: the objective is to finish above the zone's first place."""
BLOCKING_GAPS: Final = frozenset({"format", "continental", "relegation", "promotion", "playoff", "table"})
"""Topics of a regulation's ``gaps`` that keep ``SIN_OBJETIVO_DEMOSTRADO`` from being proved: something may still be at stake there."""

OBJECTIVE_NAMES: Final[dict[str, str]] = {
    "champion": "titulo", "next_phase": "clasificacion", "playoff_place": "plaza_de_playoff", "continental": "plaza_continental",
    "promotion": "ascenso", "title_playoff": "desempate_por_el_titulo", "relegation": "evitar_descenso",
    "relegation_playoff": "evitar_promocion_de_descenso", "eliminated": "evitar_eliminacion",
}

State = Literal["conseguido", "descartado", "abierto"]
Outcome = Literal["home", "draw", "away"]
OUTCOMES: Final[tuple[Outcome, ...]] = ("home", "draw", "away")


@dataclass(frozen=True, slots=True)
class Fixture:
    """A match of the competition season as known at the moment asked: with its goals when a result was recorded by then, without them
    otherwise (scheduled, postponed, suspended: a match still to be played)."""

    id: int
    round: str | None
    home: int
    away: int
    home_goals: int | None = None
    away_goals: int | None = None

    @property
    def played(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None


@dataclass(frozen=True, slots=True)
class ProviderRow:
    """A row of the provider's table (``core.standings``) at the newest snapshot taken by the moment asked."""

    team: int
    points: int
    played: int


# ── the tables of a competition season ───────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TableSpec:
    key: str
    name: str
    kind: Literal["phase", "annual", "aggregate"]
    group: str | None
    members: tuple[int, ...]
    fixtures: tuple[Fixture, ...]
    """Every match counting for the members' rows (a conference table counts the inter-conference matches)."""
    ranking: Ranking
    zones: tuple[Zone, ...]
    legs: int | None
    matches_per_team: int | None
    provider: tuple[tuple[ProviderRow, ...], ...] = ()
    """The provider's tables of exactly these teams (two when an Apertura and a Clausura have the same clubs): the one that agrees
    with the results is the one compared."""

    @property
    def size(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class Skipped:
    key: str
    name: str
    reason: str
    detail: str
    teams: tuple[int, ...] = ()
    blocking: bool = True
    """Whether it keeps ``SIN_OBJETIVO_DEMOSTRADO`` from being proved for ``teams`` (or for everybody when ``teams`` is empty)."""

    def as_json(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "reason": self.reason, "detail": self.detail, "blocking": self.blocking}


def _phase_groups(members: set[int], hint: Mapping[str, Sequence[ProviderRow]], groups: int, size: int
                  ) -> dict[str, tuple[int, ...]] | None:
    """The provider tables that are exactly the groups of a phase: ``groups`` disjoint tables of ``size`` teams covering every member."""
    fits = {label: tuple(sorted(r.team for r in rows)) for label, rows in hint.items()
            if len(rows) == size and {r.team for r in rows} <= members}
    for combo in itertools.combinations(sorted(fits), groups):
        teams = [t for label in combo for t in fits[label]]
        if len(teams) == len(set(teams)) == len(members):
            return {label: fits[label] for label in combo}
    return None


def _provider_rows(hint: Mapping[str, Sequence[ProviderRow]], members: Iterable[int], label: str | None
                   ) -> tuple[tuple[ProviderRow, ...], ...]:
    wanted = set(members)
    if label is not None:
        return (tuple(r for r in hint.get(label, ()) if r.team in wanted),)
    return tuple(tuple(rows) for _, rows in sorted(hint.items()) if {r.team for r in rows} == wanted)


def tables_of(rules: CompetitionRules, fixtures: Sequence[Fixture], *,
              provider: Mapping[str, Sequence[ProviderRow]] | None = None) -> tuple[list[TableSpec], list[Skipped]]:
    """The tables of a competition season that decide something (they have zones) and have matches on the calendar, and those that
    cannot be computed, with the reason. ``provider``: the provider's tables by label (group membership and the check of the points)."""
    hint = provider or {}
    specs: list[TableSpec] = []
    skipped: list[Skipped] = []
    phase_fixtures: dict[str, list[Fixture]] = {}
    for tournament, phase in rules.phases():
        ref = f"{tournament.key}.{phase.key}"
        mine = [f for f in fixtures if phase.covers(f.round)]
        phase_fixtures[ref] = mine
        if phase.format == "knockout" or phase.ranking is None or not phase.zones or not mine:
            continue
        members = {t for f in mine for t in (f.home, f.away)}
        name = f"{tournament.name} · {phase.name}"
        if phase.format == "groups":
            assert phase.groups is not None and phase.group_size is not None
            if any(not z.per_group for z in phase.zones):
                skipped.append(Skipped(ref, name, "zona_entre_grupos_no_soportada",
                                       "A zone ranks teams of different groups together (best thirds): not computed in scenarios-v2.",
                                       tuple(sorted(members))))
                continue
            groups = _phase_groups(members, hint, phase.groups, phase.group_size)
            if groups is None:
                skipped.append(Skipped(ref, name, "grupos_no_identificados",
                                       f"No {phase.groups} provider tables of {phase.group_size} teams cover the {len(members)} teams "
                                       "of the phase: the groups are not known, nothing is asserted.", tuple(sorted(members))))
                continue
            for label, teams in sorted(groups.items()):
                specs.append(TableSpec(f"{ref}:{label}", f"{name} · {label}", "phase", label, teams, tuple(
                    f for f in mine if f.home in teams or f.away in teams), phase.ranking, phase.zones,
                    phase.legs_between_pair, phase.matches_per_team, _provider_rows(hint, teams, label)))
            continue
        if phase.teams is not None and len(members) != phase.teams:
            skipped.append(Skipped(ref, name, "equipos_distintos",
                                   f"The calendar holds {len(members)} teams and the regulation says {phase.teams}: not computed.",
                                   tuple(sorted(members))))
            continue
        teams = tuple(sorted(members))
        specs.append(TableSpec(ref, name, "phase", None, teams, tuple(mine), phase.ranking, phase.zones, phase.legs_between_pair,
                               phase.matches_per_team, _provider_rows(hint, teams, None)))
    for table in rules.tables:
        if not table.zones:
            continue
        refs: list[str] = []
        for ref in table.counts:
            tk, _, pk = ref.partition(".")
            refs.extend(r for r in phase_fixtures if r.startswith(f"{tk}.") and (pk == "*" or r == ref))
        counted = [f for r in refs for f in phase_fixtures[r]]
        members = {t for f in counted for t in (f.home, f.away)}
        key = f"table.{table.key}"
        if table.kind == "average":
            skipped.append(Skipped(key, table.name, "tabla_promedio_no_calculada",
                                   f"An average over {table.seasons} seasons ({table.metric}) is not computed in scenarios-v2.",
                                   tuple(sorted(members))))
            continue
        formats = {rules.phase(r)[1].format for r in refs}
        if "knockout" in formats:
            skipped.append(Skipped(key, table.name, "tabla_con_eliminatorias",
                                   "The table adds the points of knock-out rounds, whose matches are not known in advance: not computed.",
                                   tuple(sorted(members))))
            continue
        if not counted:
            continue
        per_team = [rules.phase(r)[1].matches_per_team for r in refs]
        total = None if any(n is None for n in per_team) else sum(n for n in per_team if n is not None)
        teams = tuple(sorted(members))
        specs.append(TableSpec(key, table.name, table.kind, None, teams, tuple(counted), table.ranking, table.zones, None, total,
                               _provider_rows(hint, teams, None)))
    return specs, skipped


# ── certification: points only, ties against the claim ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Board:
    """The points of a table now and the matches left, as the certification sees them."""

    points: Mapping[int, int]
    members: tuple[int, ...]
    pending: tuple[tuple[int, int], ...]
    """(home, away) of every match left that counts for a member (the other side may be outside the table)."""
    phantom: Mapping[int, int]
    """Matches a member still has to play that are not on the calendar yet."""
    scheme: Points

    def left(self, team: int) -> int:
        return sum(1 for h, a in self.pending if team in (h, a)) + self.phantom.get(team, 0)

    def max_points(self, team: int) -> int:
        return self.points[team] + self.scheme.win * self.left(team)

    def min_points(self, team: int) -> int:
        return self.points[team] + self.scheme.loss * self.left(team)

    def fixed(self, home: int, away: int, outcome: Outcome) -> Board:
        """The board once the match ``home`` v ``away`` (one of those left) ends with ``outcome``."""
        pending = list(self.pending)
        pending.remove((home, away))
        pts = dict(self.points)
        w, d, lo = self.scheme.win, self.scheme.draw, self.scheme.loss
        gain = {"home": (w, lo), "draw": (d, d), "away": (lo, w)}[outcome]
        for team, g in ((home, gain[0]), (away, gain[1])):
            if team in pts:
                pts[team] += g
        return Board(pts, self.members, tuple(pending), self.phantom, self.scheme)


def _split(board: Board, team: int, *, worst: bool) -> tuple[dict[int, int], list[tuple[int, int]]]:
    """The other members' points once every match left that is not between two of them is given its side (to the member in the worst
    case for ``team``, against it in the best case), and the matches left between two of them."""
    pts = {u: board.points[u] for u in board.members if u != team}
    s = board.scheme
    for u in pts:
        pts[u] += (s.win if worst else s.loss) * board.phantom.get(u, 0)
    between: list[tuple[int, int]] = []
    for h, a in board.pending:
        if team in (h, a):
            other = a if h == team else h
            if other in pts:
                pts[other] += s.win if worst else s.loss
            continue
        if h in pts and a in pts:
            between.append((h, a))
        elif h in pts:
            pts[h] += s.win if worst else s.loss
        elif a in pts:
            pts[a] += s.win if worst else s.loss
    return pts, between


def _results(scheme: Points) -> tuple[tuple[int, int], ...]:
    return (scheme.win, scheme.loss), (scheme.draw, scheme.draw), (scheme.loss, scheme.win)


def rivals_level_or_above(board: Board, team: int, target: int) -> tuple[int, bool]:
    """The most other members that can end with ``target`` points or more, when ``team``'s own matches left go to its opponents.
    Second value: whether it was enumerated exactly (False: the safe upper bound)."""
    pts, between = _split(board, team, worst=True)
    s = board.scheme
    sure: set[int] = set()
    out: set[int] = set()
    changed = True
    while changed:
        changed = False
        degree: dict[int, int] = {}
        for h, a in between:
            degree[h] = degree.get(h, 0) + 1
            degree[a] = degree.get(a, 0) + 1
        for u, p in pts.items():
            if u in sure or u in out:
                continue
            if p >= target:
                sure.add(u)
                changed = True
            elif p + s.win * degree.get(u, 0) < target:
                out.add(u)
                changed = True
        keep: list[tuple[int, int]] = []
        for h, a in between:
            done_h, done_a = h in sure or h in out, a in sure or a in out
            if done_h and done_a:
                continue
            if done_h:
                pts[a] += s.win
            elif done_a:
                pts[h] += s.win
            else:
                keep.append((h, a))
                continue
            changed = True
        between = keep
    if not between:
        return len(sure), True
    if len(between) > ENUM_LIMIT:
        open_teams = {t for m in between for t in m}
        return len(sure) + len(open_teams), False
    teams = sorted({t for m in between for t in m})
    best = 0
    for combo in itertools.product(_results(s), repeat=len(between)):
        final = {u: pts[u] for u in teams}
        for (h, a), (gh, ga) in zip(between, combo, strict=True):
            final[h] += gh
            final[a] += ga
        best = max(best, sum(1 for u in teams if final[u] >= target))
    return len(sure) + best, True


def rivals_above(board: Board, team: int, target: int) -> tuple[int, bool]:
    """The fewest other members that must end with MORE than ``target`` points, when ``team`` wins every match it has left.
    Second value: whether it was enumerated exactly (False: the safe lower bound)."""
    pts, between = _split(board, team, worst=False)
    s = board.scheme
    above: set[int] = set()
    never: set[int] = set()
    changed = True
    while changed:
        changed = False
        degree: dict[int, int] = {}
        for h, a in between:
            degree[h] = degree.get(h, 0) + 1
            degree[a] = degree.get(a, 0) + 1
        for u, p in pts.items():
            if u in above or u in never:
                continue
            if p > target:
                above.add(u)
                changed = True
            elif p + s.win * degree.get(u, 0) <= target:
                never.add(u)
                changed = True
        keep: list[tuple[int, int]] = []
        for h, a in between:
            done_h, done_a = h in above or h in never, a in above or a in never
            if done_h and done_a:
                continue
            if done_h:  # the decided side takes the match: the other one gets the fewest points
                pts[h] += s.win
                pts[a] += s.loss
            elif done_a:
                pts[a] += s.win
                pts[h] += s.loss
            else:
                keep.append((h, a))
                continue
            changed = True
        between = keep
    if not between:
        return len(above), True
    if len(between) > ENUM_LIMIT:
        return len(above), False
    teams = sorted({t for m in between for t in m})
    least = len(teams)
    for combo in itertools.product(_results(s), repeat=len(between)):
        final = {u: pts[u] for u in teams}
        for (h, a), (gh, ga) in zip(between, combo, strict=True):
            final[h] += gh
            final[a] += ga
        least = min(least, sum(1 for u in teams if final[u] > target))
    return len(above) + least, True


@dataclass(frozen=True, slots=True)
class Certificate:
    state: State
    exact: bool
    """False when a bound was used instead of the exact enumeration (the state is still safe; an "abierto" may be a decided one)."""


def certify(board: Board, team: int, n: int) -> Certificate:
    """Whether ``team`` is sure to finish within the first ``n`` places of the table (``conseguido``), sure not to (``descartado``), or
    neither (``abierto``). Ties on points always count against the claim."""
    if n <= 0:
        return Certificate("descartado", True)
    if n >= len(board.members):
        return Certificate("conseguido", True)
    level, exact_up = rivals_level_or_above(board, team, board.min_points(team))
    if level <= n - 1:
        return Certificate("conseguido", exact_up)
    above, exact_down = rivals_above(board, team, board.max_points(team))
    if above >= n:
        return Certificate("descartado", exact_down)
    return Certificate("abierto", exact_up and exact_down)


def points_that_secure(board: Board, team: int, n: int) -> int | None:
    """The fewest final points with which ``team`` is sure to finish within the first ``n`` places whatever the others do (its own
    matches left are given to its opponents, so the number is safe, possibly above the least one); None when even winning every match
    left is not enough on its own."""
    if n >= len(board.members):
        return board.points[team]
    lo, hi = board.points[team], board.max_points(team)
    if rivals_level_or_above(board, team, hi)[0] > n - 1:
        return None
    while lo < hi:  # the count can only fall as the target rises: the least target that works, by bisection
        mid = (lo + hi) // 2
        if rivals_level_or_above(board, team, mid)[0] <= n - 1:
            hi = mid
        else:
            lo = mid + 1
    while rivals_level_or_above(board, team, lo)[0] > n - 1:  # never taken with an exact count; kept so the answer is always safe
        lo += 1
    return lo


def contested(board: Board, team: int) -> list[int]:
    """The other members whose range of final points overlaps ``team``'s: the results that can still move it against them."""
    lo, hi = board.min_points(team), board.max_points(team)
    return sorted((u for u in board.members if u != team and board.min_points(u) <= hi and board.max_points(u) >= lo),
                  key=lambda u: (-board.points[u], u))


# ── the reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Objective:
    kind: str
    sense: Literal["lograr", "evitar"]
    within: int
    """The objective is to finish within the first ``within`` places."""
    places: tuple[int, int]
    target: str | None
    conditional: bool
    note: str | None

    @property
    def name(self) -> str:
        return OBJECTIVE_NAMES.get(self.kind, self.kind)


def objectives_of(spec: TableSpec) -> list[Objective]:
    out: list[Objective] = []
    for z in spec.zones:
        pos = z.positions(spec.size)
        if not pos:
            continue
        favourable = z.kind in FAVOURABLE
        within = pos.stop - 1 if favourable else pos.start - 1
        out.append(Objective(z.kind, "lograr" if favourable else "evitar", within, (pos.start, pos.stop - 1), z.target,
                             z.conditional, z.note))
    return out


def board_of(spec: TableSpec, points: Points, *, adjustments: Mapping[int, int] | None = None) -> tuple[Board, list[str]]:
    """The certification's board of a table, and what is wrong with its calendar (a team with more matches than its phase allows)."""
    members = set(spec.members)
    rows = rk.rows_of([rk.Result(f.home, f.away, int(f.home_goals or 0), int(f.away_goals or 0)) for f in spec.fixtures if f.played],
                      points, teams=spec.members, adjustments={t: d for t, d in (adjustments or {}).items() if t in members})
    pending = tuple((f.home, f.away) for f in spec.fixtures if not f.played)
    flags: list[str] = []
    phantom: dict[int, int] = {}
    if spec.matches_per_team is not None:
        for t in spec.members:
            on_calendar = rows[t].played + sum(1 for h, a in pending if t in (h, a))
            if on_calendar < spec.matches_per_team:
                phantom[t] = spec.matches_per_team - on_calendar
            elif on_calendar > spec.matches_per_team:
                flags.append(f"calendario_excede:{t}")
    return Board({t: rows[t].points for t in spec.members}, spec.members, pending, phantom, points), flags


def _provider_versions(spec: TableSpec, board: Board) -> tuple[list[Board], list[dict[str, Any]], bool]:
    """The boards to certify (ours, and the provider's points where they differ on the same matches played) and the differences.
    Third value: whether the provider's table was taken at another moment (played counts differ: it cannot be compared)."""
    played = {t: board.points[t] for t in board.members}
    differences: list[dict[str, Any]] = []
    lagging = False
    ours_played: dict[int, int] = dict.fromkeys(board.members, 0)
    for f in spec.fixtures:
        if f.played:
            for t in (f.home, f.away):
                if t in ours_played:
                    ours_played[t] += 1
    theirs = dict(played)
    candidates = [c for c in spec.provider if c]
    chosen: tuple[ProviderRow, ...] = max(candidates, key=lambda c: sum(
        1 for r in c if r.team in played and r.played == ours_played[r.team] and r.points == played[r.team])) if candidates else ()
    for r in chosen:
        if r.team not in played:
            continue
        if r.played != ours_played[r.team]:
            lagging = True
            continue
        if r.points != played[r.team]:
            differences.append({"team": r.team, "points_results": played[r.team], "points_provider": r.points,
                                "played": r.played})
            theirs[r.team] = r.points
    if not differences:
        return [board], differences, lagging
    return [board, Board(theirs, board.members, board.pending, board.phantom, board.scheme)], differences, lagging


def _agree(certs: Sequence[Certificate]) -> Certificate:
    states = {c.state for c in certs}
    return Certificate(certs[0].state if len(states) == 1 else "abierto", all(c.exact for c in certs))


# ── the simulation ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Simulation:
    status: Literal["ok", "sin_modelo", "calendario_incompleto", "sin_partidos", "desactivada"]
    sims: int = 0
    seed: int = 0
    positions: dict[int, NDArray[np.int64]] = field(default_factory=dict)
    """Each member's final place in each simulated season."""
    outcomes: dict[int, NDArray[np.int8]] = field(default_factory=dict)
    """Each match left's result in each simulated season: 0 home win, 1 draw, 2 away win."""
    missing: list[int] = field(default_factory=list)
    open_ties: int = 0
    """Seasons whose final table left a tie open (lots, fair play, a play-off) and was drawn at random."""

    def share(self, team: int, within: int, mask: NDArray[np.bool_] | None = None) -> float | None:
        pos = self.positions.get(team)
        if pos is None or self.sims == 0:
            return None
        if mask is not None:
            if not mask.any():
                return None
            pos = pos[mask]
        return float(np.mean(pos <= within))


def table_seed(seed: int, key: str) -> int:
    return (seed + zlib.crc32(key.encode())) % (2 ** 32)


def simulate(spec: TableSpec, points: Points, board: Board, scores: Mapping[int, NDArray[np.float64]], *, sims: int, seed: int,
             adjustments: Mapping[int, int] | None = None) -> Simulation:
    """Play the matches left ``sims`` times from their score distributions and rank every final table with the regulation."""
    pending = [f for f in spec.fixtures if not f.played]
    if sims <= 0:
        return Simulation("desactivada")
    if not pending:
        return Simulation("sin_partidos")
    if any(board.phantom.values()):
        return Simulation("calendario_incompleto")
    missing = [f.id for f in pending if f.id not in scores]
    if missing:
        return Simulation("sin_modelo", missing=missing)
    s = table_seed(seed, spec.key)
    rng = np.random.default_rng(s)
    played = [rk.Result(f.home, f.away, int(f.home_goals or 0), int(f.away_goals or 0)) for f in spec.fixtures if f.played]
    goals: list[tuple[NDArray[np.int64], NDArray[np.int64]]] = []
    outcomes: dict[int, NDArray[np.int8]] = {}
    for f in pending:
        m = np.asarray(scores[f.id], dtype=np.float64)
        flat = m.ravel() / m.sum()
        idx = rng.choice(flat.size, size=sims, p=flat)
        gh, ga = np.divmod(idx, m.shape[1])
        goals.append((gh.astype(np.int64), ga.astype(np.int64)))
        outcomes[f.id] = np.where(gh > ga, 0, np.where(gh == ga, 1, 2)).astype(np.int8)
    positions = {t: np.zeros(sims, dtype=np.int64) for t in spec.members}
    members = list(spec.members) if spec.group is not None else None
    open_ties = 0
    adj = {t: d for t, d in (adjustments or {}).items() if t in set(spec.members)}
    for i in range(sims):
        results = played + [rk.Result(f.home, f.away, int(g[0][i]), int(g[1][i])) for f, g in zip(pending, goals, strict=True)]
        table = rk.rank(results, spec.ranking, points=points, teams=spec.members, complete=True, legs=spec.legs, zones=spec.zones,
                        size=spec.size, adjustments=adj, members=members)
        order = table.order()
        if table.open_ties:
            open_ties += 1
            for group in table.open_ties:
                slots = sorted(order.index(t) for t in group)
                drawn = list(group)
                rng.shuffle(drawn)
                for slot, t in zip(slots, drawn, strict=True):
                    order[slot] = t
        for place, t in enumerate(order, start=1):
            if t in positions:
                positions[t][i] = place
    return Simulation("ok", sims, s, positions, outcomes, open_ties=open_ties)


# ── the whole reading ────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _objective_json(o: Objective, cert: Certificate, decided_ok: bool, board: Board, team: int, sim: Simulation,
                    withdrawn: bool) -> dict[str, Any]:
    decided = cert.state != "abierto" and decided_ok and not o.conditional and not withdrawn
    reasons: list[str] = []
    if o.conditional:
        reasons.append("zona_condicional")
    if withdrawn:
        reasons.append("contradiccion_interna")
    secure = None if cert.state != "abierto" else points_that_secure(board, team, o.within)
    rivals = [] if cert.state != "abierto" else contested(board, team)[:MAX_RIVALS]
    return {
        "objetivo": o.name, "zona": o.kind, "sentido": o.sense, "puestos": list(o.places), "terminar_entre_los": o.within,
        "destino": o.target, "condicional": o.conditional,
        "estado": cert.state, "exacto": cert.exact,
        "decidido": {"valor": decided, "demostrado": decided, "motivos": reasons},
        "probabilidad": sim.share(team, o.within),
        "necesita": {"puntos_actuales": board.points[team], "puntos_maximos": board.max_points(team),
                     "partidos_restantes": board.left(team), "puntos_que_lo_aseguran": secure},
        "depende_de": {"tipo": "decidido" if cert.state != "abierto" else ("de_si_mismo" if secure is not None else "de_otros"),
                       "rivales": rivals},
    }


def _now_places(spec: TableSpec, points: Points, adjustments: Mapping[int, int] | None
                ) -> tuple[dict[int, int], dict[int, tuple[int, int]] | None]:
    """Each member's place now and, when every match of the table is played, the span of places it ends in (its own place, or the
    places of a tie the regulation's criteria leave open: lots, a play-off, fair play not given)."""
    played = [rk.Result(f.home, f.away, int(f.home_goals or 0), int(f.away_goals or 0)) for f in spec.fixtures if f.played]
    complete = all(f.played for f in spec.fixtures)
    table = rk.rank(played, spec.ranking, points=points, teams=spec.members, complete=complete, legs=spec.legs, zones=spec.zones,
                    size=spec.size, adjustments={t: d for t, d in (adjustments or {}).items() if t in set(spec.members)},
                    members=list(spec.members) if spec.group is not None else None)
    places = {p.team: p.position for p in table.places}
    if not complete:
        return places, None
    spans: dict[int, tuple[int, int]] = {}
    for p in table.places:
        group = (p.team, *p.shared_with)
        lo = min(places[t] for t in group)
        spans[p.team] = (lo, lo + len(group) - 1)
    return places, spans


def _final(span: tuple[int, int], within: int) -> Certificate:
    """The certificate of a table whose every match is played: by its final order, the regulation's tie-breakers applied."""
    if span[1] <= within:
        return Certificate("conseguido", True)
    if span[0] > within:
        return Certificate("descartado", True)
    return Certificate("abierto", True)


def read_table(spec: TableSpec, points: Points, *, scores: Mapping[int, NDArray[np.float64]] | None = None,
               adjustments: Mapping[int, int] | None = None, sims: int = DEFAULT_SIMS, seed: int = DEFAULT_SEED,
               focus: Iterable[int] = ()) -> dict[str, Any]:
    """One table: each member's objectives, certified and simulated; for each match of ``focus`` left in it, what each result does."""
    board, flags = board_of(spec, points, adjustments=adjustments)
    boards, differences, lagging = _provider_versions(spec, board)
    if differences:
        flags.append("datos_discrepantes")
    if lagging:
        flags.append("tabla_proveedor_de_otro_momento")
    decided_ok = not any(f.startswith("calendario_excede") for f in flags)
    sim = simulate(spec, points, board, scores or {}, sims=sims, seed=seed, adjustments=adjustments) if scores is not None else \
        Simulation("desactivada")
    objectives = objectives_of(spec)
    places, spans = _now_places(spec, points, adjustments)
    final = spans is not None and not any(board.phantom.values()) and not differences
    contradictions: list[dict[str, Any]] = []
    teams: list[dict[str, Any]] = []
    for t in spec.members:
        rows: list[dict[str, Any]] = []
        for o in objectives:
            cert = _final(spans[t], o.within) if final and spans is not None else _agree([certify(b, t, o.within) for b in boards])
            share = sim.share(t, o.within)
            withdrawn = share is not None and ((cert.state == "conseguido" and share < 1.0) or
                                               (cert.state == "descartado" and share > 0.0))
            if withdrawn:
                contradictions.append({"team": t, "objetivo": o.name, "estado": cert.state, "probabilidad": share})
            rows.append(_objective_json(o, cert, decided_ok, board, t, sim, withdrawn))
        teams.append({"team": t, "puesto": places.get(t), "puntos": board.points[t], "partidos_restantes": board.left(t),
                      "puntos_minimos": board.min_points(t), "puntos_maximos": board.max_points(t), "objetivos": rows})
    matches: dict[str, Any] = {}
    focus_ids = set(focus)
    pending_by_id = {f.id: f for f in spec.fixtures if not f.played}
    for fid in sorted(focus_ids & set(pending_by_id)):
        f = pending_by_id[fid]
        sides: dict[str, Any] = {}
        for side, t in (("home", f.home), ("away", f.away)):
            if t not in set(spec.members):
                continue
            per: list[dict[str, Any]] = []
            for o in objectives:
                row: dict[str, Any] = {"objetivo": o.name, "terminar_entre_los": o.within, "condicional": o.conditional}
                for k, outcome in enumerate(OUTCOMES):
                    after = _agree([certify(b.fixed(f.home, f.away, outcome), t, o.within) for b in boards])
                    mask = None if fid not in sim.outcomes else sim.outcomes[fid] == k
                    row[_outcome_name(side, outcome)] = {"estado": after.state, "probabilidad": sim.share(t, o.within, mask)}
                per.append(row)
            sides[side] = {"team": t, "objetivos": per}
        matches[str(fid)] = sides
    return {
        "key": spec.key, "name": spec.name, "kind": spec.kind, "group": spec.group, "size": spec.size,
        "played": sum(1 for f in spec.fixtures if f.played), "pending": len(pending_by_id),
        "phantom": dict(sorted((str(k), v) for k, v in board.phantom.items())), "complete": not pending_by_id and not any(board.phantom.values()),
        "flags": flags, "provider_differences": differences,
        "simulation": {"status": sim.status, "sims": sim.sims, "seed": sim.seed, "missing": sim.missing[:20],
                       "open_ties": sim.open_ties},
        "contradicciones": contradictions, "teams": teams, "matches": matches,
    }


def _outcome_name(side: str, outcome: Outcome) -> str:
    if outcome == "draw":
        return "empate"
    return "victoria" if (outcome == "home") == (side == "home") else "derrota"


def no_objective(rules: CompetitionRules, tables: Sequence[Mapping[str, Any]], skipped: Sequence[Skipped], team: int
                 ) -> dict[str, Any]:
    """Whether ``SIN_OBJETIVO_DEMOSTRADO`` holds for ``team``, and why not."""
    reasons: list[str] = []
    mine = [(t, row) for t in tables for row in t["teams"] if row["team"] == team]
    eliminated = any(o["zona"] == "eliminated" and o["estado"] == "descartado" and o["decidido"]["demostrado"]
                     for _, row in mine for o in row["objetivos"])
    for gap in rules.gaps:
        if gap.topic in BLOCKING_GAPS and not (gap.topic == "format" and eliminated):
            reasons.append(f"hueco_reglamento:{gap.topic}")
    for s in skipped:
        if s.blocking and (not s.teams or team in s.teams):
            reasons.append(f"tabla_no_calculada:{s.key}:{s.reason}")
    if not mine:
        reasons.append("sin_tabla")
    for t, row in mine:
        for o in row["objetivos"]:
            if o["decidido"]["demostrado"]:
                continue
            if o["condicional"]:
                if o["estado"] != "descartado":
                    reasons.append(f"zona_condicional:{t['key']}:{o['zona']}")
                else:
                    reasons.append(f"zona_condicional_sin_certificar:{t['key']}:{o['zona']}")
            else:
                reasons.append(f"objetivo_abierto:{t['key']}:{o['objetivo']}")
    proved = not reasons
    return {"hecho": FACT_NO_OBJECTIVE if proved else None, "demostrado": proved, "alcance": "tablas_codificadas",
            "motivos": sorted(set(reasons))}


def evaluate(answer: Answer, fixtures: Sequence[Fixture], *, at: datetime, scores: Mapping[int, NDArray[np.float64]] | None = None,
             provider: Mapping[str, Sequence[ProviderRow]] | None = None, adjustments: Mapping[int, int] | None = None,
             sims: int = DEFAULT_SIMS, seed: int = DEFAULT_SEED, focus: Iterable[int] = (), include_closed: bool = False
             ) -> dict[str, Any]:
    """The reading of a competition season at ``at``: every table that decides something, each team's objectives, the fact
    ``SIN_OBJETIVO_DEMOSTRADO`` where it is proved, and, for each match of ``focus``, what each result does. ``fixtures`` must be the
    season as known at ``at`` (results recorded by then; the calendar as it stood)."""
    base: dict[str, Any] = {"version": VERSION, "at": at.isoformat(), "league_id": answer.league_id, "season": answer.season}
    if not isinstance(answer, Coded):
        return {**base, "status": NOT_CODED, "rules": answer.as_json(), "tables": [], "skipped": [], "teams": {}}
    rules = answer.rules
    specs, skipped = tables_of(rules, fixtures, provider=provider)
    live = [s for s in specs if not _closed(s, rules.points)]
    closed = [s.key for s in specs if s not in live]
    if live and not include_closed:  # a tournament already over (the Apertura while the Clausura is played) is history, not what is at stake
        specs = live
        skipped = [k for k in skipped if not k.teams or set(k.teams) & {t for s in live for t in s.members}]
    focus_ids = list(focus)
    tables = [read_table(s, rules.points, scores=scores, adjustments=adjustments, sims=sims, seed=seed, focus=focus_ids)
              for s in specs]
    teams = sorted({t for s in specs for t in s.members} | {t for s in skipped for t in s.teams})
    return {**base, "status": "ok", "rules": answer.as_json(), "tables": tables, "skipped": [s.as_json() for s in skipped],
            "closed": closed if live and not include_closed else [], "teams": {str(t): no_objective(rules, tables, skipped, t) for t in teams},
            "contradicciones": sum(len(t["contradicciones"]) for t in tables)}


def _closed(spec: TableSpec, points: Points) -> bool:
    """Every match of the table played and none missing from the calendar."""
    if any(not f.played for f in spec.fixtures):
        return False
    board, _ = board_of(spec, points)
    return not any(board.phantom.values())


def stakes_for(reading: Mapping[str, Any], team: int) -> list[dict[str, Any]]:
    """The team's objectives flattened for a reader (the ``stakes[]`` of the match contract, C-01 entrega 2): one row per objective of
    every table it is in, with ``objetivo``, ``necesita``, ``depende_de``, ``decidido`` and when it was computed."""
    if reading.get("status") != "ok":
        return []
    out: list[dict[str, Any]] = []
    for t in reading["tables"]:
        for row in t["teams"]:
            if row["team"] != team:
                continue
            for o in row["objetivos"]:
                out.append({"team": team, "tabla": t["key"], "objetivo": o["objetivo"], "puestos": o["puestos"], "estado": o["estado"],
                            "necesita": o["necesita"], "depende_de": o["depende_de"], "decidido": o["decidido"],
                            "probabilidad": o["probabilidad"], "computed_at": reading["at"], "version": reading["version"]})
    return out
