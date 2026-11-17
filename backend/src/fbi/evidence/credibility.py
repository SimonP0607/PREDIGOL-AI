"""``credibility-v2`` (IA-126, plan piece AD-C08): the credibility of a source learned PER TYPE OF FACT, with its 95 % interval and its
sample in sight. It INFORMS; it decides nothing on its own. Pure: no database, no clock, no setting.

WHY. ``credibility-v1`` (``fbi.evidence.rules``) learns one number per source (outlet and tier) from every availability claim it made:
an outlet that is right about line-ups and wrong about injuries gets the average of both, and the number travels without its sample or
its uncertainty - 3 of 3 and 300 of 300 both read «learned».

WHAT v2 DOES, beside v1 (v1 is still computed and still what the engine's confidence reads):

* **By type of fact** (``FACT_TYPES``): ``baja`` (out, not a suspension), ``sancion`` (out by a suspension), ``titularidad`` (starts),
  ``disponible`` (available). A doubt is not judged (``duda`` is told, never refuted) - v1 could count one against a higher-tier claim
  that said the same doubt; v2 does not, and the replay lists it.
* **Resolved by what the evaluation after the match resolves** (AD-K01, the same order as v1's ``rules.resolve``): the provider's official
  line-up first, then its injury report, then a claim of a higher tier about the same player within the topic's window. A claim nothing
  can check is not counted.
* **As of, strictly.** The inputs are cut at the moment of the reading by the caller (a line-up fetched after it, an injury report
  observed after it, a claim retrieved after it do not exist), and a claim about the match being read never vouches for its own source
  (``exclude_fixture``).
* **The number and how sure it is.** ``value`` is v1's shrinkage per type, ``(K * prior(tier) + hits) / (K + resolved)``, so that a
  source with little record stays near its tier; beside it the raw hit rate with its Wilson 95 % interval (``fbi.ai.intervals``) and the
  sample. Below ``MIN_RESOLVED`` resolved claims of a type (the minimum the protocol ``AD-C08`` registers before any data), the type is
  ``insuficiente``: the interval is shown, the number is not interpreted.

WHAT IT NEVER DOES. It never lifts a status: the tier (A-D) fixes the highest rung a claim can reach (``ladder-v1``'s ``status_of`` reads
tiers only, ``ladder-v2``'s ``rung`` reads authority only) and the credibility can only refine the confidence inside the cap of that
status (``rules.STATUS_CAP``). It never changes the tier of a domain (nothing here writes ``ai.sources`` or the registry) - a source
that lies with a real quote is corrected by its record, by the corroboration of independent origins and by the provider's
contradictions, never by a process that promotes it. Tests hold both (``tests/unit/test_source_credibility_v2.py``).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from fbi.ai.intervals import Proportion
from fbi.evidence import rules
from fbi.evidence.engine import CredKey, Item, learn_credibility
from fbi.evidence.engine import _resolution_fixture as resolution_fixture

VERSION: Final = "credibility-v2"
FactType = Literal["baja", "sancion", "titularidad", "disponible"]
FACT_TYPES: Final[tuple[FactType, ...]] = ("baja", "sancion", "titularidad", "disponible")
MIN_RESOLVED: Final = 30
"""Resolved claims of one type a source needs before its credibility of that type is interpreted (protocol ``AD-C08``, registered on
17-nov-2026 before any reading): with 30, the Wilson half-width at a hit rate of 0.8 is about 14 points."""
DIFFERENCE: Final = 0.05
"""How far a type's value may sit from v1's single number before the replay lists it as a difference."""

V2Key = tuple[str, str, str]
"""(outlet, tier, type of fact)."""


def fact_type(item: Item) -> FactType | None:
    """The type of fact an availability claim is, or None (a doubt, or not about availability)."""
    if item.topic not in rules.AVAILABILITY_TOPICS:
        return None
    if item.assertion == "out":
        return "sancion" if item.topic == "suspension" else "baja"
    if item.assertion == "starts":
        return "titularidad"
    if item.assertion == "available":
        return "disponible"
    return None


@dataclass(frozen=True, slots=True)
class TypedCredibility:
    """The credibility of one source for one type of fact."""

    outlet: str
    tier: rules.Tier
    fact_type: FactType
    value: float
    basis: Literal["prior", "learned"]
    prior: float
    corroborated: int
    resolved: int

    @property
    def sufficient(self) -> bool:
        return self.resolved >= MIN_RESOLVED

    @property
    def proportion(self) -> Proportion:
        return Proportion(self.corroborated, self.resolved)

    @property
    def word(self) -> str:
        """``insuficiente`` below the registered minimum; otherwise ``aprendida``."""
        return "aprendida" if self.sufficient else "insuficiente"

    @property
    def ci95(self) -> tuple[float, float] | None:
        return self.proportion.wilson

    def as_json(self) -> dict[str, Any]:
        ci = self.ci95
        return {"outlet": self.outlet, "tier": self.tier, "fact_type": self.fact_type, "value": self.value, "basis": self.basis,
                "prior": self.prior, "corroborated": self.corroborated, "resolved": self.resolved,
                "rate": None if self.resolved == 0 else round(self.corroborated / self.resolved, 4),
                "ci95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)], "sufficient": self.sufficient, "word": self.word,
                "min_resolved": MIN_RESOLVED, "decides": False}


def typed(outlet: str, tier: rules.Tier, kind: FactType, corroborated: int, resolved: int) -> TypedCredibility:
    """v1's shrinkage, per type: the prior of the tier alone when nothing of that type was resolved."""
    base = rules.credibility(tier, corroborated, resolved)
    return TypedCredibility(outlet, tier, kind, base.value, base.basis, base.prior, base.corroborated, base.resolved)


@dataclass(frozen=True, slots=True)
class Judged:
    """One past claim and what it turned out to be (for the record of the replay)."""

    evidence_id: int
    key: V2Key
    fixture_id: int | None
    outcome: rules.Resolution


def judge(history: Sequence[Item], peers: Sequence[Item], *, exclude_fixture: int | None,
          team_fixtures: Mapping[int, Sequence[tuple[datetime, int]]], sheets: Mapping[tuple[int, int], rules.SquadSheet],
          listings: Mapping[tuple[int, int], rules.Listing]) -> list[Judged]:
    """Every past claim of ``history`` that could be checked, with its outcome. The inputs are already cut at the moment of the reading;
    a claim about ``exclude_fixture`` (the match being read) is never judged: it would vouch for its own source."""
    by_person: dict[tuple[int | None, int | None], list[Item]] = defaultdict(list)
    for p in peers:
        by_person[(p.team_id, p.player_id)].append(p)
    out: list[Judged] = []
    seen: set[int] = set()
    for h in history:
        kind = fact_type(h)
        if kind is None or h.player_id is None or h.evidence_id in seen:
            continue
        seen.add(h.evidence_id)
        fixture = resolution_fixture(h, team_fixtures)
        if exclude_fixture is not None and fixture == exclude_fixture:
            continue
        window = rules.VALIDITY[h.topic]
        higher = [p.assertion for p in by_person[(h.team_id, h.player_id)]
                  if p.evidence_id != h.evidence_id and p.outlet != h.outlet and rules.TIER_RANK[p.tier] < rules.TIER_RANK[h.tier]
                  and p.topic in rules.AVAILABILITY_TOPICS and abs(p.when - h.when) <= window
                  and (fixture is None or resolution_fixture(p, team_fixtures) in (fixture, None))]
        sheet = sheets.get((fixture, h.team_id)) if fixture is not None and h.team_id is not None else None
        listing = listings.get((fixture, h.player_id)) if fixture is not None else None
        outcome = rules.resolve(h.assertion, sheet=sheet, listing=listing, player_id=h.player_id, higher=higher)
        if outcome is not None:
            out.append(Judged(h.evidence_id, (h.outlet, h.tier, kind), fixture, outcome))
    return out


def learn(judged: Iterable[Judged], *, wanted: Iterable[V2Key] = ()) -> dict[V2Key, TypedCredibility]:
    """The credibility of every (outlet, tier, type) judged - and of every one ``wanted`` with nothing judged, at its prior."""
    hits: Counter[V2Key] = Counter()
    resolved: Counter[V2Key] = Counter()
    for j in judged:
        resolved[j.key] += 1
        hits[j.key] += int(j.outcome == "corroborated")
    keys = set(resolved) | set(wanted)
    return {k: typed(k[0], k[1], k[2], hits[k], resolved[k]) for k in sorted(keys)}  # type: ignore[arg-type]


def learn_v2(history: Sequence[Item], peers: Sequence[Item], *, exclude_fixture: int | None,
             team_fixtures: Mapping[int, Sequence[tuple[datetime, int]]], sheets: Mapping[tuple[int, int], rules.SquadSheet],
             listings: Mapping[tuple[int, int], rules.Listing]) -> dict[V2Key, TypedCredibility]:
    return learn(judge(history, peers, exclude_fixture=exclude_fixture, team_fixtures=team_fixtures, sheets=sheets, listings=listings))


# ── the replay against credibility-v1 ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Difference:
    outlet: str
    tier: str
    reason: str
    v1: dict[str, Any]
    v2: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"outlet": self.outlet, "tier": self.tier, "reason": self.reason, "v1": self.v1, "v2": self.v2}


def replay(history: Sequence[Item], peers: Sequence[Item], *, team_fixtures: Mapping[int, Sequence[tuple[datetime, int]]],
           sheets: Mapping[tuple[int, int], rules.SquadSheet], listings: Mapping[tuple[int, int], rules.Listing]
           ) -> dict[str, Any]:
    """v1 and v2 on the same inputs (a snapshot: no match excluded), and every source where they differ, with why:

    * ``doubts_not_judged``    v1 resolved more claims than v2: the doubts v1 judged against a higher-tier claim;
    * ``types_apart``          a type of the source sits more than ``DIFFERENCE`` from v1's single number (v1 averaged it with others);
    * ``insufficient_by_type`` v1 learned a number, and no type of v2 reaches the registered minimum.
    """
    wanted: set[CredKey] = {(h.outlet, h.tier) for h in history}
    v1 = learn_credibility(history, peers, wanted=wanted, exclude_fixture=-1, team_fixtures=team_fixtures, sheets=sheets, listings=listings)
    v2 = learn_v2(history, peers, exclude_fixture=None, team_fixtures=team_fixtures, sheets=sheets, listings=listings)
    by_source: dict[CredKey, list[TypedCredibility]] = defaultdict(list)
    for (outlet, tier, _), c in v2.items():
        by_source[(outlet, tier)].append(c)
    diffs: list[Difference] = []
    for key in sorted(wanted):
        one = v1[key]
        types = by_source.get(key, [])
        shown = {"value": one.value, "basis": one.basis, "resolved": one.resolved, "corroborated": one.corroborated}
        mine: dict[str, Any] = {str(c.fact_type): c.as_json() for c in types}
        total = sum(c.resolved for c in types)
        if one.resolved != total:
            diffs.append(Difference(key[0], key[1], "doubts_not_judged", shown | {"v2_resolved": total}, mine))
        apart = [c.fact_type for c in types if c.basis == "learned" and abs(c.value - one.value) > DIFFERENCE]
        if apart:
            diffs.append(Difference(key[0], key[1], "types_apart", shown, {t: mine[t] for t in apart}))
        if one.basis == "learned" and not any(c.sufficient for c in types):
            diffs.append(Difference(key[0], key[1], "insufficient_by_type", shown, mine))
    return {"version": VERSION, "against": rules.CREDIBILITY_VERSION, "sources": len(wanted), "typed": len(v2),
            "sufficient": sum(1 for c in v2.values() if c.sufficient), "min_resolved": MIN_RESOLVED,
            "differences": [d.as_json() for d in diffs], "by_reason": dict(sorted(Counter(d.reason for d in diffs).items())),
            "decides": False}


def digest() -> str:
    """The constants of this version, hashed: what goes with every stored row, so that two snapshots are comparable."""
    body = [VERSION, list(FACT_TYPES), MIN_RESOLVED, DIFFERENCE, rules.rules_digest()]
    return hashlib.sha256(json.dumps(body, separators=(",", ":")).encode()).hexdigest()[:12]


__all__ = ["DIFFERENCE", "FACT_TYPES", "MIN_RESOLVED", "VERSION", "Difference", "FactType", "Judged", "TypedCredibility", "V2Key",
           "digest", "fact_type", "judge", "learn", "learn_v2", "replay", "typed"]
