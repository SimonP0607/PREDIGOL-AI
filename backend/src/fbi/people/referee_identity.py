"""Who is who among the spellings of referees: the rules, as a pure function (plan F3, ``refid-v1``).

The provider gives no referee id. What it gives is a string per match, and the same person comes in many: ``M. Oliver``,
``Michael Oliver``, ``Michael Oliver, England``, sometimes in another competition's country. On 22 Oct 2026 the 199,890 matches
with a referee carried 9,632 spellings (a spelling = a normalised name in a SCOPE: the country the string names, or else the
country of the domestic competition it was written in, or ``?`` for a continental one). This module groups them.

THE RULES, from the safest to the least safe, and what each one is allowed to do
-------------------------------------------------------------------------------
1. **Same scope, one person written two ways: joined.** (a) ``danny makkelie`` and ``danny desmond makkelie``: two full names
   that begin and end with the same words. (b) An initial and a surname (``m oliver``) next to exactly ONE full name that
   ends the same way and begins with that letter (``michael oliver``). If two different full names fit (``r gupta`` fits
   ``rahul kumar gupta`` and ``rajesh gupta``) nothing is joined and the doubt is kept for a person.
2. **Another scope: only the visitor, and only with a witness.** A referee is a foreigner in a handful of matches abroad
   (``d makkelie`` is Dutch and appears in Saudi Arabia, Greece, the Emirates): the same name in a SMALL cluster of another scope
   joins the one HOME cluster it could be - a cluster with at least ``hub_min`` matches, of which the visitor is at most
   ``minor_share`` - when that is the only home it could be. A spelling with no scope at all (``?``, a continental match)
   joins the only scoped cluster it could be, whatever the sizes. Where two homes could be (``j martinez`` in Spain and in
   Mexico) nothing is joined.
3. **A person cannot referee two matches at once, and this holds over every rule above.** Two clusters with a match each that
   kick off less than ``collision_minutes`` apart are two people, whatever their names say: the pair is VETOED, never joined by
   a rule and never suggested. It is the only evidence in the data that says "different".
4. **What is left is suggested, never decided**: the pairs of clusters whose names could be one person and that no rule joined
   (several homes, an ambiguous initial, a typing variant) go to a queue with a reason and a score. A person merges or rejects.

Everything is deterministic (the order of the input does not matter) and the function does not read the database: the store
(``fbi.people.referees``) gives it every spelling with the matches it is the final word on, and marks the spellings already
stored as FROZEN (``Form.entity`` is the referee they belong to). A frozen spelling never changes referee here; a new spelling
may join a stored referee; two stored referees are never joined by a rule, whatever their names say - only a person does that.
Measured on the production history: see ``scripts/referee_identity.py audit`` and the owner guide (``IDENTIDAD_DE_PERSONAS_F3``).
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from fbi.people import referee_names as rn
from fbi.people.countries import UNKNOWN_SCOPE

VERSION: Final = "refid-v1"

FormId = tuple[str, str]
"""(normalised name, scope)."""
Game = tuple[int, int]
"""(kick-off in minutes since the epoch, fixture id): a match whose final referee has this spelling."""

BASES: Final = ("identity", "extension", "initial", "foreign", "unscoped", "stored", "manual")
"""Why a spelling is in its group: it anchors it (identity), or the rule that put it there."""

REASONS: Final = ("same_name_other_scope", "longer_name", "initial_and_full", "spelling_variant")
RELATION_SCORE: Final = {"longer_name": 0.9, "same_name_other_scope": 0.85, "initial_and_full": 0.7, "spelling_variant": 0.6}


@dataclass(frozen=True, slots=True)
class Params:
    hub_min: int = 20
    """Matches a cluster needs to be somebody's HOME: below it, a cluster is never what a visitor joins."""
    minor_max: int = 15
    minor_share: float = 0.15
    """A visitor has at most this many matches and at most this share of its home's."""
    collision_minutes: int = 120
    """Kick-offs this close in two different matches cannot have the same referee."""


DEFAULT_PARAMS: Final = Params()


@dataclass(slots=True)
class Form:
    """One spelling in one scope, with the matches it is the final word on."""

    key: str
    scope: str
    games: list[Game] = field(default_factory=list)
    entity: int | None = None
    """The stored referee this spelling already belongs to (a frozen form), or None for a new spelling."""
    seen: int = 0
    """Observations of this spelling, whether or not a later one replaced it."""

    @property
    def id(self) -> FormId:
        return (self.key, self.scope)


@dataclass(frozen=True, slots=True)
class Group:
    number: int
    forms: tuple[FormId, ...]
    canonical: FormId
    """The spelling the group is called by."""
    entity: int | None
    """The stored referee this group is (some form in it was stored), or None: a new referee has to be made for it."""
    games: int


@dataclass(frozen=True, slots=True)
class Candidate:
    """Two groups whose names could be one person and that no rule joined."""

    a: int
    b: int
    reason: str
    score: float
    evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class Veto:
    """Two groups whose names could be one person but that have matches at the same time."""

    a: int
    b: int
    collisions: int


@dataclass(frozen=True, slots=True)
class Resolution:
    groups: tuple[Group, ...]
    group_of: dict[FormId, int]
    basis: dict[FormId, str]
    candidates: tuple[Candidate, ...]
    vetoes: tuple[Veto, ...]

    def open_groups(self) -> set[int]:
        """The groups with a question waiting for a person."""
        return {c.a for c in self.candidates} | {c.b for c in self.candidates}

    def summary(self) -> dict[str, int]:
        """The numbers a run is judged by."""
        open_numbers = self.open_groups()
        total = sum(g.games for g in self.groups)
        settled = sum(g.games for g in self.groups if g.number not in open_numbers)
        return {
            "forms": len(self.group_of),
            "groups": len(self.groups),
            "new_groups": sum(1 for g in self.groups if g.entity is None),
            "candidates": len(self.candidates),
            "vetoes": len(self.vetoes),
            "games": total,
            "games_settled": settled,
        }


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def text_compatible(a: str, b: str) -> str | None:
    """How two normalised names could be one person, or None. The reason names the strongest way."""
    if a == b:
        return "same_name_other_scope"
    if rn.is_extension(a, b):
        return "longer_name"
    if rn.initial_matches_full(a, b) or rn.initial_matches_full(b, a):
        return "initial_and_full"
    if rn.is_spelling_variant(a, b):
        return "spelling_variant"
    return None


def collisions(a: Sequence[Game], b: Sequence[Game], window: int) -> int:
    """Pairs of matches, one from each list, whose kick-offs are less than ``window`` minutes apart. Both lists are sorted.
    The same match on both sides is no collision: a correction of the spelling of one referee puts one match under two names."""
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    stamps = [g[0] for g in large]
    found = 0
    for minute, fixture in small:
        lo = bisect.bisect_left(stamps, minute - window + 1)
        hi = bisect.bisect_left(stamps, minute + window)
        found += sum(1 for k in range(lo, hi) if large[k][1] != fixture)
    return found


def canonical_rank(key: str, scope: str, games: int, seen: int = 0) -> tuple[bool, int, int, int, str, str]:
    """What orders the spellings of one referee for the name he is called by: a full name before an initial, then the one with
    most matches, then the one seen most, then the longest, then the first alphabetically. The smallest wins."""
    return (rn.is_initial_form(key), -games, -seen, -len(key), key, scope)


def pick_canonical(forms: Sequence[Form]) -> FormId:
    """The spelling a group is called by (see ``canonical_rank``)."""
    return min(forms, key=lambda f: canonical_rank(f.key, f.scope, len(f.games), f.seen)).id


def home_scope(games_by_scope: Mapping[str, int]) -> str | None:
    """The country a referee referees from: the scope where most of his matches were, the first alphabetically on a tie;
    None when none of his matches has a scope."""
    real = {scope: n for scope, n in games_by_scope.items() if scope != UNKNOWN_SCOPE}
    return min(real, key=lambda scope: (-real[scope], scope)) if real else None


class _Clusters:
    """Union-find over spellings that keeps, for each cluster, its members, its matches and the stored referee it is.

    The root of a cluster is its smallest member, so the root (and the number a group gets) does not depend on the order the
    joins happened in."""

    def __init__(self, forms: Sequence[Form], window: int) -> None:
        self.window = window
        self.parent: dict[FormId, FormId] = {}
        self.members: dict[FormId, list[FormId]] = {}
        self.games: dict[FormId, list[Game]] = {}
        self.entity: dict[FormId, int | None] = {}
        self.basis: dict[FormId, str] = {}
        for f in forms:
            self.parent[f.id] = f.id
            self.members[f.id] = [f.id]
            self.games[f.id] = sorted(f.games)
            self.entity[f.id] = f.entity
            self.basis[f.id] = "stored" if f.entity is not None else "identity"
        first_of: dict[int, FormId] = {}
        for f in forms:
            if f.entity is not None:
                if f.entity in first_of:
                    self._join(first_of[f.entity], f.id)
                else:
                    first_of[f.entity] = f.id

    def find(self, x: FormId) -> FormId:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def _join(self, a: FormId, b: FormId) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        keep, drop = (ra, rb) if ra < rb else (rb, ra)
        entity = self.entity[keep] if self.entity[keep] is not None else self.entity[drop]
        self.parent[drop] = keep
        self.members[keep] = sorted(self.members[keep] + self.members.pop(drop))
        self.games[keep] = sorted(self.games[keep] + self.games.pop(drop))
        self.entity[keep] = entity
        del self.entity[drop]

    def can_join(self, a: FormId, b: FormId) -> bool:
        """A rule never joins two stored referees (only a person does) and never joins two people who referee at once."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        ea, eb = self.entity[ra], self.entity[rb]
        if ea is not None and eb is not None and ea != eb:
            return False
        if self.names_conflict(ra, rb):
            return False
        return collisions(self.games[ra], self.games[rb], self.window) == 0

    def names_conflict(self, a: FormId, b: FormId) -> bool:
        """Do the full names of the two clusters contradict each other (``andres rojas`` / ``antonio rojas``)?"""
        fa = [m[0] for m in self.members[self.find(a)] if not rn.is_initial_form(m[0])]
        fb = [m[0] for m in self.members[self.find(b)] if not rn.is_initial_form(m[0])]
        return any(rn.names_conflict(x, y) for x in fa for y in fb)

    def real_scopes(self, root: FormId) -> set[str]:
        return {m[1] for m in self.members[root] if m[1] != UNKNOWN_SCOPE}

    def union(self, a: FormId, b: FormId, *, mover: FormId, basis: str) -> bool:
        """Join the clusters of ``a`` and ``b``; the cluster of ``mover`` is the one that moved, and its anchor spellings are
        marked with ``basis``. False (nothing done) when the rules forbid the join."""
        if self.find(a) == self.find(b):
            return True
        if not self.can_join(a, b):
            return False
        for m in self.members[self.find(mover)]:
            if self.basis[m] == "identity":
                self.basis[m] = basis
        self._join(a, b)
        return True

    def roots(self) -> list[FormId]:
        return sorted(self.members)

    def size(self, root: FormId) -> int:
        return len(self.games[root])

    def scoped(self, root: FormId) -> bool:
        return any(m[1] != UNKNOWN_SCOPE for m in self.members[root])

    def attach(self, form: FormId, targets: Iterable[FormId], basis: str, *, dominance: tuple[int, float] | None = None) -> bool:
        """Join the cluster of ``form`` to the ONE cluster among ``targets`` it can join. Nothing is done when the form already
        sits with one of them, when none can be joined, or when two different ones can (the doubt is for a person) - unless
        ``dominance`` = (minimum matches, share) is given and one option is so much bigger than every other that it is the only
        one that can be somebody's home: at least that many matches, the others at most that share of it."""
        own = self.find(form)
        roots = {self.find(t) for t in targets}
        if own in roots:
            return False
        options = sorted(r for r in roots if self.can_join(own, r))
        if len(options) > 1 and dominance is not None:
            big = max(options, key=lambda r: (self.size(r), r))
            if self.size(big) >= dominance[0] and all(self.size(r) <= dominance[1] * self.size(big) for r in options if r != big):
                options = [big]
        if len(options) != 1:
            return False
        return self.union(own, options[0], mover=own, basis=basis)


def resolve(forms: Iterable[Form], params: Params = DEFAULT_PARAMS) -> Resolution:
    """Group the spellings; see the module docstring for the rules. Deterministic: sorted inputs, sorted outputs."""
    ordered = sorted(forms, key=lambda f: (f.key, f.scope))
    if len({f.id for f in ordered}) != len(ordered):
        raise ValueError("a spelling can be given only once per scope")
    cl = _Clusters(ordered, params.collision_minutes)
    by_id = {f.id: f for f in ordered}
    by_tail: dict[str, list[Form]] = defaultdict(list)
    by_scope_tail: dict[tuple[str, str], list[Form]] = defaultdict(list)
    for f in ordered:
        tail = rn.surname_tail(f.key)
        by_tail[tail].append(f)
        by_scope_tail[(f.scope, tail)].append(f)

    # 1a. A full name and the same name with a middle name, in one scope. The longest names first, so that a chain
    #     (makkelie / danny makkelie / danny desmond makkelie) is already one cluster when its shortest member looks for a home.
    for bucket in by_scope_tail.values():
        fulls = [f for f in bucket if not rn.is_initial_form(f.key)]
        for short in sorted(fulls, key=lambda f: (-len(rn.tokens(f.key)), f.key)):
            longer = [g.id for g in fulls if len(rn.tokens(g.key)) > len(rn.tokens(short.key)) and rn.is_extension(short.key, g.key)]
            if longer:
                cl.attach(short.id, longer, "extension")

    # 1b. An initial and a surname beside the ONE full name it could be, in one scope.
    for bucket in by_scope_tail.values():
        fulls = [f for f in bucket if not rn.is_initial_form(f.key)]
        for initial in (f for f in bucket if rn.is_initial_form(f.key)):
            fits = [g.id for g in fulls if rn.initial_matches_full(initial.key, g.key)]
            if fits:
                cl.attach(initial.id, fits, "initial", dominance=(params.hub_min, params.minor_share))

    def partners(root: FormId, *, cross_scope_only: bool) -> dict[FormId, tuple[str, FormId, FormId]]:
        """The other clusters one of whose spellings could be a spelling of this cluster: the strongest relation, and the two
        spellings it is between (this cluster's first)."""
        found: dict[FormId, tuple[str, FormId, FormId]] = {}
        for m in cl.members[root]:
            for other in by_tail[rn.surname_tail(m[0])]:
                ro = cl.find(other.id)
                if ro == root or (cross_scope_only and other.scope == m[1]):
                    continue
                reason = text_compatible(m[0], other.key)
                if reason is not None and (ro not in found or RELATION_SCORE[reason] > RELATION_SCORE[found[ro][0]]):
                    found[ro] = (reason, m, other.id)
        return found

    # 2. A visitor joins the one home it could be; a spelling with no scope joins the one scoped cluster it could be.
    #    Smallest clusters first. Each cluster of the start gets one turn, as the cluster it has become by then.
    for first in sorted(cl.roots(), key=lambda r: (cl.size(r), r)):
        root = cl.find(first)
        if not cl.scoped(root):
            cl.attach(root, [y for y in partners(root, cross_scope_only=True) if cl.scoped(y)], "unscoped",
                      dominance=(params.hub_min, params.minor_share))
        elif cl.size(root) <= params.minor_max:
            home_of = [y for y in partners(root, cross_scope_only=True)
                       if cl.scoped(y) and cl.size(y) >= params.hub_min and cl.size(root) <= params.minor_share * cl.size(y)
                       and cl.real_scopes(y).isdisjoint(cl.real_scopes(root))]
            cl.attach(root, home_of, "foreign")

    # 3. What is left: the vetoed pairs and the suggestions.
    roots = cl.roots()
    number = {r: i + 1 for i, r in enumerate(roots)}
    pairs: dict[tuple[FormId, FormId], tuple[str, FormId, FormId]] = {}
    for root in roots:
        for other, relation in partners(root, cross_scope_only=False).items():
            if root < other:
                pairs[(root, other)] = relation
    vetoes: list[Veto] = []
    open_pairs: list[tuple[FormId, FormId, tuple[str, FormId, FormId]]] = []
    for (a, b), relation in sorted(pairs.items()):
        hits = collisions(cl.games[a], cl.games[b], params.collision_minutes)
        if hits:
            vetoes.append(Veto(number[a], number[b], hits))
        else:
            open_pairs.append((a, b, relation))
    degree: dict[FormId, int] = defaultdict(int)
    for a, b, _ in open_pairs:
        degree[a] += 1
        degree[b] += 1
    candidates = tuple(
        Candidate(number[a], number[b], reason, round(RELATION_SCORE[reason] / max(degree[a], degree[b]), 3),
                  {"relation": reason, "forms": [list(fa), list(fb)], "games": [cl.size(a), cl.size(b)]})
        for a, b, (reason, fa, fb) in open_pairs)

    canonical = {r: pick_canonical([by_id[m] for m in cl.members[r]]) for r in roots}
    groups = tuple(Group(number[r], tuple(cl.members[r]), canonical[r], cl.entity[r], cl.size(r)) for r in roots)
    group_of = {m: number[r] for r in roots for m in cl.members[r]}
    return Resolution(groups, group_of, {k: cl.basis[k] for k in by_id}, candidates, tuple(vetoes))
