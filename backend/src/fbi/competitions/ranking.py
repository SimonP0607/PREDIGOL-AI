"""A league table from results and a competition's ranking rules (IA-072, plan piece AD-B01): points, then the tie-breakers in
the order the regulation lists them, head-to-head computed among the tied teams the way it says (once, or again among those
still level), and the criteria the results cannot settle (fair play, a club coefficient, lots, a play-off) asked of the caller -
or left OPEN, never guessed.

Pure and deterministic: a list of results in, the ordered table out, each place with the criterion that separated it (or the
reason it is still shared). The scenarios engine (AD-B02) calls it for the best and worst case of every remaining match; the
reconstruction check (``scripts/ia_rules.py reconstruct``) calls it on a closed season and compares with ``core.standings``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from fbi.competitions.rules import H2H_CRITERIA, Points, Ranking, Tiebreak, Zone

VERSION: Final = "ranking-v1"
THREE_ONE_ZERO: Final = Points()

EXTERNAL_UNITS: Final = (
    "External criteria are given by the caller as numbers per team: fair_play, coefficient_table and prior_phase_rank as a "
    "RANK (1 = best); disciplinary_points and card counts as points (fewer = better); club_coefficient as the coefficient "
    "(higher = better); seed_priority as 1 for a seeded team and 0 otherwise; lots as the order drawn (1 = first).")


@dataclass(frozen=True, slots=True)
class Result:
    home: int
    away: int
    home_goals: int
    away_goals: int


@dataclass(slots=True)
class Row:
    team: int
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    adjustment: int = 0
    home_goals_for: int = 0
    home_goals_against: int = 0
    away_goals_for: int = 0
    away_goals_against: int = 0
    away_wins: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    def as_json(self) -> dict[str, Any]:
        return {"team": self.team, "played": self.played, "wins": self.wins, "draws": self.draws, "losses": self.losses,
                "goals_for": self.goals_for, "goals_against": self.goals_against, "points": self.points,
                "adjustment": self.adjustment}


def rows_of(results: Iterable[Result], points: Points, *, teams: Iterable[int] = (),
            adjustments: Mapping[int, int] | None = None) -> dict[int, Row]:
    """The table rows of a set of results (every team in ``teams`` gets a row even with no match). ``adjustments`` are points
    added or deducted by a decision (a sanction): they count in ``points`` and are shown apart."""
    rows: dict[int, Row] = {t: Row(t) for t in teams}
    for r in results:
        h = rows.setdefault(r.home, Row(r.home))
        a = rows.setdefault(r.away, Row(r.away))
        h.played += 1
        a.played += 1
        h.goals_for += r.home_goals
        h.goals_against += r.away_goals
        a.goals_for += r.away_goals
        a.goals_against += r.home_goals
        h.home_goals_for += r.home_goals
        h.home_goals_against += r.away_goals
        a.away_goals_for += r.away_goals
        a.away_goals_against += r.home_goals
        if r.home_goals > r.away_goals:
            h.wins += 1
            a.losses += 1
            h.points += points.win
            a.points += points.loss
        elif r.home_goals < r.away_goals:
            a.wins += 1
            a.away_wins += 1
            h.losses += 1
            a.points += points.win
            h.points += points.loss
        else:
            h.draws += 1
            a.draws += 1
            h.points += points.draw
            a.points += points.draw
    for team, delta in (adjustments or {}).items():
        row = rows.setdefault(team, Row(team))
        row.adjustment += delta
        row.points += delta
    return rows


@dataclass(frozen=True, slots=True)
class Place:
    position: int
    team: int
    row: Row
    shared_with: tuple[int, ...] = ()
    """Teams level with this one after every criterion that could be applied: their order is not decided."""
    decided_by: str | None = None
    """The criterion that separated this team from the one above or below it (None: by points, or not separated)."""
    open_on: str | None = None
    """When the tie is still open: the criterion that would decide it and was not given (``lots``, ``fair_play``...), or
    ``exhausted`` when the regulation's list ends there (the teams share the place)."""

    def as_json(self) -> dict[str, Any]:
        return {"position": self.position, **self.row.as_json(), "shared_with": list(self.shared_with),
                "decided_by": self.decided_by, "open_on": self.open_on}


@dataclass(frozen=True, slots=True)
class Table:
    places: tuple[Place, ...]
    complete: bool
    criteria: tuple[str, ...]
    """The criteria the ranking used (the in-progress list while the phase is being played, when the regulation has one)."""
    version: str = VERSION

    def order(self) -> list[int]:
        return [p.team for p in self.places]

    def place_of(self, team: int) -> Place:
        return next(p for p in self.places if p.team == team)

    @property
    def open_ties(self) -> list[tuple[int, ...]]:
        seen: set[tuple[int, ...]] = set()
        for p in self.places:
            if p.shared_with:
                group = tuple(sorted((p.team, *p.shared_with)))
                seen.add(group)
        return sorted(seen)

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "complete": self.complete, "criteria": list(self.criteria),
                "places": [p.as_json() for p in self.places]}


@dataclass(slots=True)
class _Ctx:
    results: Sequence[Result]
    rows: Mapping[int, Row]
    points: Points
    ranking: Ranking
    zones: Sequence[Zone]
    size: int
    complete: bool
    legs: int | None
    external: Mapping[str, Mapping[int, float]]
    opponents: dict[int, list[int]] = field(default_factory=dict)


def _h2h_rows(ctx: _Ctx, group: Sequence[int]) -> dict[int, Row]:
    members = set(group)
    return rows_of((r for r in ctx.results if r.home in members and r.away in members), ctx.points, teams=group)


def _h2h_complete(ctx: _Ctx, group: Sequence[int]) -> bool:
    if ctx.legs is None:
        return ctx.complete
    members = set(group)
    played: dict[frozenset[int], int] = {}
    for r in ctx.results:
        if r.home in members and r.away in members:
            key = frozenset((r.home, r.away))
            played[key] = played.get(key, 0) + 1
    pairs = len(members) * (len(members) - 1) // 2
    return len(played) == pairs and all(n >= ctx.legs for n in played.values())


def _opponents_value(ctx: _Ctx, team: int, measure: Callable[[Row], int]) -> int:
    if not ctx.opponents:
        for r in ctx.results:
            ctx.opponents.setdefault(r.home, []).append(r.away)
            ctx.opponents.setdefault(r.away, []).append(r.home)
    return sum(measure(ctx.rows[o]) for o in ctx.opponents.get(team, []) if o in ctx.rows)


_COMPUTED: Final[dict[str, Callable[[Row], int]]] = {
    "points": lambda r: r.points,
    "goal_difference": lambda r: r.goal_difference,
    "goals_for": lambda r: r.goals_for,
    "goals_against_fewer": lambda r: r.goals_against,
    "wins": lambda r: r.wins,
    "away_goals_for": lambda r: r.away_goals_for,
    "away_goals_against_fewer": lambda r: r.away_goals_against,
    "away_goal_difference": lambda r: r.away_goals_for - r.away_goals_against,
    "away_wins": lambda r: r.away_wins,
    "home_goal_difference": lambda r: r.home_goals_for - r.home_goals_against,
    "home_goals_for": lambda r: r.home_goals_for,
}
_H2H: Final[dict[str, Callable[[Row], int]]] = {
    "h2h_points": lambda r: r.points,
    "h2h_goal_difference": lambda r: r.goal_difference,
    "h2h_goals_for": lambda r: r.goals_for,
    "h2h_away_goals_for": lambda r: r.away_goals_for,
}
_OPPONENTS: Final[dict[str, Callable[[Row], int]]] = {
    "opponents_points": lambda r: r.points,
    "opponents_goal_difference": lambda r: r.goal_difference,
    "opponents_goals_for": lambda r: r.goals_for,
}
_EXTERNAL_LOWER: Final = frozenset({"fair_play", "coefficient_table", "disciplinary_points", "red_cards_fewer",
                                    "yellow_cards_fewer", "prior_phase_rank", "lots"})


def _decisive(ctx: _Ctx, start: int, n: int) -> bool:
    """Whether a tie over places start..start+n-1 decides something: the title, or a boundary of a zone falls inside it."""
    if start == 1:
        return True
    span = set(range(start, start + n))
    for z in ctx.zones:
        covered = set(z.positions(ctx.size))
        if covered & span and not span <= covered:
            return True
    return False


@dataclass(frozen=True, slots=True)
class _Split:
    groups: list[list[int]]
    by: str | None
    open_on: str | None = None


def _values(ctx: _Ctx, criterion: str, group: Sequence[int], h2h_set: Sequence[int]) -> dict[int, float] | None:
    if criterion in _COMPUTED:
        f = _COMPUTED[criterion]
        return {t: float(f(ctx.rows[t])) for t in group}
    if criterion in _H2H:
        mini = _h2h_rows(ctx, h2h_set)
        g = _H2H[criterion]
        return {t: float(g(mini[t])) for t in group}
    if criterion in _OPPONENTS:
        m = _OPPONENTS[criterion]
        return {t: float(_opponents_value(ctx, t, m)) for t in group}
    given = ctx.external.get(criterion)
    if given is None or any(t not in given for t in group):
        return None
    return {t: float(given[t]) for t in group}


def _lower_is_better(criterion: str) -> bool:
    return criterion in _EXTERNAL_LOWER or criterion in ("goals_against_fewer", "away_goals_against_fewer")


def _resolve(ctx: _Ctx, group: list[int], chain: Sequence[Tiebreak], start: int, i: int,
             h2h_set: list[int] | None) -> list[tuple[list[int], str | None, str | None]]:
    """The ordered sub-groups of a tied group: (teams still level, criterion that set them apart from the rest, open_on)."""
    if len(group) == 1:
        return [(group, None, None)]
    for j in range(i, len(chain)):
        tb = chain[j]
        c = tb.criterion
        if tb.when == "complete" and not ctx.complete:
            continue
        if tb.when == "decisive" and not (ctx.complete and _decisive(ctx, start, len(group))):
            continue
        if c in H2H_CRITERIA:
            h2h = ctx.ranking.h2h
            members = group if (h2h.mode == "reapply" or h2h_set is None) else h2h_set
            if h2h.max_teams is not None and len(members) > h2h.max_teams:
                continue
            if h2h.requires_all_played and not _h2h_complete(ctx, members):
                continue
            vals = _values(ctx, c, group, members)
        else:
            vals = _values(ctx, c, group, group)
        if vals is None:
            return [(group, None, c)]
        if len(set(vals.values())) == 1:
            continue
        lower = _lower_is_better(c)
        levels = sorted(set(vals.values()), reverse=not lower)
        out: list[tuple[list[int], str | None, str | None]] = []
        pos = start
        for v in levels:
            sub = [t for t in group if vals[t] == v]
            if len(sub) == 1:
                out.append((sub, c, None))
            else:
                restart = c in H2H_CRITERIA and ctx.ranking.h2h.mode == "reapply"
                first_h2h = next((k for k, t in enumerate(chain) if t.criterion in H2H_CRITERIA), j + 1)
                nxt = first_h2h if restart else j + 1
                keep = None if restart else (h2h_set if h2h_set is not None else
                                             (group if c in H2H_CRITERIA else None))
                for subgroup, by, open_on in _resolve(ctx, sub, chain, pos, nxt, keep):
                    out.append((subgroup, by or c, open_on))
            pos += len(sub)
        return out
    return [(group, None, "exhausted")]


def rank(results: Sequence[Result], ranking: Ranking, *, points: Points = THREE_ONE_ZERO, teams: Iterable[int] = (),
         complete: bool, legs: int | None = None, zones: Sequence[Zone] = (), size: int | None = None,
         adjustments: Mapping[int, int] | None = None, external: Mapping[str, Mapping[int, float]] | None = None,
         names: Mapping[int, str] | None = None, members: Iterable[int] | None = None) -> Table:
    """The table of ``results`` under ``ranking``.

    ``complete``: every match of the phase has been played (end-of-season criteria apply). ``legs``: how many matches two teams
    play each other (to know whether a head-to-head is complete). ``zones`` and ``size``: to know which ties decide something
    (criteria marked ``decisive``). ``external``: the numbers of criteria not in the results, by criterion and team.
    ``names``: only for an in-progress fallback that is alphabetical (UEFA). ``members``: rank only these teams (a group, a
    conference) while their rows count every result given - a conference table counts the inter-conference matches.
    """
    rows = rows_of(results, points, teams=teams, adjustments=adjustments)
    ranked = list(rows) if members is None else list(dict.fromkeys(members))
    for t in ranked:
        rows.setdefault(t, Row(t))
    n = size if size is not None else len(ranked)
    in_progress = not complete and ranking.in_progress is not None
    ctx = _Ctx(results=results, rows=rows, points=points, ranking=ranking, zones=zones, size=n, complete=complete,
               legs=legs, external=external or {})
    by_points = sorted(ranked, key=lambda t: (-rows[t].points, t))
    places: list[Place] = []
    pos = 1
    i = 0
    while i < len(by_points):
        level = [t for t in by_points[i:] if rows[t].points == rows[by_points[i]].points]
        two = len(level) == 2 and ranking.tiebreakers_if_two is not None
        chain: Sequence[Tiebreak]
        if in_progress:
            assert ranking.in_progress is not None
            chain = ranking.in_progress
        elif two:
            assert ranking.tiebreakers_if_two is not None
            chain = ranking.tiebreakers_if_two
        else:
            chain = ranking.tiebreakers
        for sub, by, open_on in _resolve(ctx, sorted(level), chain, pos, 0, None):
            if len(sub) > 1 and in_progress and ranking.in_progress_fallback == "alphabetical" and names is not None:
                sub = sorted(sub, key=lambda t: names.get(t, str(t)))
                for t in sub:
                    places.append(Place(pos, t, rows[t], decided_by="alphabetical" if by is None else by))
                    pos += 1
                continue
            for t in sub:
                shared = tuple(x for x in sub if x != t)
                places.append(Place(pos, t, rows[t], shared_with=shared,
                                    decided_by=by if len(level) > 1 else None,
                                    open_on=open_on if shared else None))
            pos += len(sub)
        i += len(level)
    criteria = tuple(t.criterion for t in (ranking.in_progress if in_progress and ranking.in_progress
                                           else ranking.tiebreakers))
    return Table(places=tuple(places), complete=complete, criteria=criteria)
