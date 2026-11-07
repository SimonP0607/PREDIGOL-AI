"""The rules of ``evidence-engine-v1``: pure functions and versioned constants. Nothing here reads a database, a clock or a setting.

TIERS (``tiers-v1``). Every stored item gets one of four tiers, by deterministic rules from what is stored - its origin, its kind, its domain,
the tier the registry gave it (``ai.sources``, via ``ai.evidence.source_tier``) and research v2's ``source_class`` - in this order:

    1. a page that read like an order to a model (``attributes.instruction_like``)      -> D
    2. the data provider: its confirmed line-up (the clubs' own team sheets)           -> A ; its injury report -> B
    3. the owner's own note                                                            -> B
    4. the domain (its most specific suffix) in the versioned lists ``DOMAIN_TIERS``     -> its tier
       A official club / league / federation, B national outlet (the owner-trusted ``REPUTABLE_DOMAINS``) or accredited journalist,
       C the rest of the classified press (local press), D aggregators, betting tips, streaming and social networks
    5. the registry's tier (the owner may add domains the lists do not have): official/competition/club -> A, journalist/provider -> B,
       media -> B when research v2 classed it ``RELIABLE_MEDIA`` else C, aggregator/social -> D
    6. anything else (no domain, a domain nobody classified)                            -> D

    An A-tier web page without a publication date counts as B: an official statement is official with its date (as v1's CONFIRMED rule).

CREDIBILITY (``credibility-v1``). A source's credibility is LEARNED from its own history when it has one, else it is its tier's prior::

    credibility = (K * prior(tier) + corroborated) / (K + resolved)        K = PRIOR_WEIGHT = 10 pseudo-claims

    over the source's availability claims about an identified player (by the provider's id) of the last ``CREDIBILITY_WINDOW`` days, other
    matches than the one being read, whose truth was KNOWN by the moment of the reading (as of, strictly):
      corroborated  the provider's line-up agrees (said OUT and he is not in the squad sheet; said STARTS and he started; said AVAILABLE
                    and he is in it), or - with no line-up - the provider's injury report lists him missing for a claim that he is OUT, or a
                    claim of a HIGHER tier (another outlet) says the same thing within the topic's window;
      refuted       the line-up disagrees (OUT but in the squad sheet; STARTS but not a starter), the provider lists him missing for a claim
                    that he plays, or a higher-tier claim says the opposite;
      resolved      corroborated + refuted. A claim nothing could check is not counted (it is neither right nor wrong).

    With no resolved claim the credibility IS the prior (basis ``prior``); each resolved claim moves it towards the source's own hit rate.

STATUS LADDER (``ladder-v1``). RUMOR -> REPORTADO -> CONFIRMADO -> OFICIAL, from the INDEPENDENT outlets that say the same thing (one outlet
counts once, however many pages it has, with its best tier and its highest credibility; ``marca.com`` and ``amp.marca.com`` are one) and that
are live (not expired). ``(T, n)`` means at least n independent outlets of tier T or better; the first rule that holds wins (``LADDER``):

    OFICIAL     (A, 1)
    CONFIRMADO  (B, 1) and (C, 2)      a national outlet and another independent one of the press
    CONFIRMADO  (C, 3)                 three independent local outlets
    REPORTADO   (C, 1)
    RUMOR       otherwise - D sources alone, however many, never lift a status (aggregators copy each other)

    Adding an outlet only adds to the counts, so the ladder never goes down with more corroboration.

CONFIDENCE (``confidence-v1``)::

    support    = 1 - prod(1 - credibility(o))   over the independent live outlets, D tier counted once (its best outlet)
    freshness  = max over the live items of 0.5 ** (age / (HALF_LIFE_SHARE * window(topic)))           (0 once expired)
    confidence = min(STATUS_CAP[status], support) * freshness

    Every term is non-decreasing in the corroboration (an extra independent outlet adds a factor below one to the product, raises or keeps
    the status, raises or keeps the freshest item): more corroboration never lowers the confidence (a test holds it). Contradictions do not
    enter ``confidence``: they are reported apart, and ``confidence_net`` discounts them (``net``).

VALIDITY (``validity-v1``). Each topic has a window counted from the item's own date (published, else retrieved): ``VALIDITY``. An item past
its window is expired; a claim whose every item is expired is reported as expired, with confidence 0 and its status as it stood.

CONTRADICTIONS (``contra-evidence-v1``), beside contra-v1's C07 (which the engine reuses as it is):

    CC1  claim vs claim     the same person, an availability topic (injury, suspension, line-up), incompatible assertions (``INCOMPATIBLE``),
                            both live
    CP1  claim vs provider  claimed OUT, and the provider's line-up lists him (starter or bench)
    CP2  claim vs provider  claimed STARTS, and the provider's line-up is known and he is not a starter
    CP3  claim vs provider  claimed AVAILABLE or STARTS, and the provider's injury report lists him missing at that moment

    ``confidence_net = confidence * prod(1 - confidence(opposing claim))`` over its CC1 contradictions, 0 when CP1 or CP2 refutes it, and
    ``* (1 - prior(B))`` for CP3 (the injury report is the provider's word, of B standing, not a team sheet).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal

from fbi.ai.evidence import (
    AGGREGATORS,
    FEDERATIONS,
    JOURNALISTS,
    LEAGUES,
    MEDIA,
    SOCIAL,
    SOURCES_V2,
)
from fbi.analyst.provenance import OFFICIAL_DOMAINS, REPUTABLE_DOMAINS

TIERS_VERSION: Final = "tiers-v1"
CREDIBILITY_VERSION: Final = "credibility-v1"
LADDER_VERSION: Final = "ladder-v1"
CONFIDENCE_VERSION: Final = "confidence-v1"
VALIDITY_VERSION: Final = "validity-v1"
CONTRA_VERSION: Final = "contra-evidence-v1"

Tier = Literal["A", "B", "C", "D"]
TIERS: Final[tuple[Tier, ...]] = ("A", "B", "C", "D")
TIER_RANK: Final[dict[str, int]] = {"A": 0, "B": 1, "C": 2, "D": 3}
Status = Literal["RUMOR", "REPORTADO", "CONFIRMADO", "OFICIAL"]
STATUSES: Final[tuple[Status, ...]] = ("RUMOR", "REPORTADO", "CONFIRMADO", "OFICIAL")
"""The ladder, lowest first."""
Topic = Literal["injury", "suspension", "lineup", "coach_change", "press_conference", "other"]
TOPICS: Final[tuple[Topic, ...]] = ("injury", "suspension", "lineup", "coach_change", "press_conference", "other")
AVAILABILITY_TOPICS: Final = frozenset({"injury", "suspension", "lineup"})

# ── tiers ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _v2(*tiers: str) -> frozenset[str]:
    return frozenset(d for d, t in SOURCES_V2.items() if t in tiers)


_A: Final = FEDERATIONS | LEAGUES | OFFICIAL_DOMAINS | _v2("official", "competition", "club")
_B: Final = (REPUTABLE_DOMAINS | JOURNALISTS) - _A
_D: Final = (AGGREGATORS | SOCIAL | _v2("aggregator")) - _A - _B
_C: Final = (MEDIA | _v2("media")) - _A - _B - _D
DOMAIN_TIERS: Final[dict[str, Tier]] = {**dict.fromkeys(_D, "D"), **dict.fromkeys(_C, "C"), **dict.fromkeys(_B, "B"), **dict.fromkeys(_A, "A")}
"""``tiers-v1``: the domain lists, from the registries the code base already keeps (``fbi.ai.evidence``'s federations, leagues, media,
aggregators, social networks and sources-v2; ``fbi.analyst.provenance``'s official and reputable domains). A domain in two lists takes the
better tier. The lists are pinned by ``DOMAINS_DIGEST``: a change to any of them fails a test until the version is bumped."""
DOMAINS_DIGEST: Final = "7ed11932d969"
"""The first 12 hex of the SHA-256 of ``DOMAIN_TIERS`` in canonical form (``domains_digest``). Pinned so that the lists are versioned."""

REGISTRY_TIERS: Final[dict[str, Tier]] = {"official": "A", "competition": "A", "club": "A", "journalist": "B", "provider": "B",
                                          "aggregator": "D", "social": "D", "unknown": "D"}
"""Step 5: the tier the registry (``ai.sources``) gave a domain the lists do not have. ``media`` is B or C by research v2's class."""


def domains_digest() -> str:
    return hashlib.sha256(json.dumps(sorted(DOMAIN_TIERS.items()), separators=(",", ":")).encode()).hexdigest()[:12]


def _suffixes(domain: str) -> list[str]:
    parts = domain.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def domain_tier(domain: str | None) -> Tier | None:
    """The tier of the most specific listed suffix of a domain, or None when no list has it."""
    if not domain:
        return None
    host = domain.strip().lower().removeprefix("www.")
    return next((DOMAIN_TIERS[s] for s in _suffixes(host) if s in DOMAIN_TIERS), None)


@dataclass(frozen=True, slots=True)
class Tiered:
    tier: Tier
    reason: str


def tier_of(*, origin: str, kind: str, domain: str | None, registry_tier: str | None, source_class: str | None, flagged: bool,
            dated: bool) -> Tiered:
    """The tier of one stored item (``tiers-v1``, steps 1-6 of the module's docstring)."""
    if flagged:
        return Tiered("D", "the page read like an order to a model")
    if origin == "provider":
        return Tiered("A", "the provider's confirmed line-up") if kind == "lineup" else Tiered("B", "the provider's injury report")
    if origin == "owner":
        return Tiered("B", "the owner's note")
    listed = domain_tier(domain)
    if listed is not None:
        found, why = listed, f"listed domain ({TIERS_VERSION})"
    else:
        registered = (registry_tier or "").strip().lower()
        if registered == "media":
            found, why = ("B", "registry: media, reliable") if source_class == "RELIABLE_MEDIA" else ("C", "registry: media")
        elif registered in REGISTRY_TIERS and registered != "unknown":
            found, why = REGISTRY_TIERS[registered], f"registry: {registered}"
        else:
            return Tiered("D", "unknown source")
    if found == "A" and not dated:
        return Tiered("B", "an official domain without a publication date")
    return Tiered(found, why)


# ── credibility ─────────────────────────────────────────────────────────────────────────────────────────────────────

TIER_PRIOR: Final[dict[str, float]] = {"A": 0.95, "B": 0.80, "C": 0.60, "D": 0.30}
"""What a source of each tier is believed before its history says anything (``credibility-v1``)."""
PRIOR_WEIGHT: Final = 10
"""How many resolved claims the prior is worth: after ten, the source's own record weighs as much as its tier."""
CREDIBILITY_WINDOW: Final = timedelta(days=180)
HISTORY_PER_SOURCE: Final = 2000
"""The newest availability claims of a source that its credibility is learned from (a bound on the read, not a statistic)."""

Resolution = Literal["corroborated", "refuted"]


@dataclass(frozen=True, slots=True)
class Credibility:
    value: float
    basis: Literal["prior", "learned"]
    prior: float
    corroborated: int = 0
    resolved: int = 0

    def as_json(self) -> dict[str, Any]:
        return {"value": self.value, "basis": self.basis, "prior": self.prior, "corroborated": self.corroborated, "resolved": self.resolved}


def credibility(tier: str, corroborated: int, resolved: int) -> Credibility:
    """``(K * prior + corroborated) / (K + resolved)``; the prior alone when nothing of the source was resolved."""
    prior = TIER_PRIOR[tier]
    if resolved <= 0:
        return Credibility(prior, "prior", prior)
    hits = max(0, min(corroborated, resolved))
    return Credibility(round((PRIOR_WEIGHT * prior + hits) / (PRIOR_WEIGHT + resolved), 4), "learned", prior, hits, resolved)


@dataclass(frozen=True, slots=True)
class SquadSheet:
    """The provider's line-up of one team in one match, as known at a moment: who started and who was on the bench."""

    team_id: int
    known_at: datetime
    starters: frozenset[int]
    bench: frozenset[int] = frozenset()

    @property
    def listed(self) -> frozenset[int]:
        return self.starters | self.bench


@dataclass(frozen=True, slots=True)
class Listing:
    """The provider's injury report for one player in one match, as known at a moment (the newest observation by then)."""

    status: Literal["LISTED", "CLEARED"]
    missing: bool
    """LISTED with an absence type ``Missing...`` (``Questionable`` is a doubt, not an absence)."""
    observed_at: datetime


def resolve(assertion: str, *, sheet: SquadSheet | None, listing: Listing | None, player_id: int,
            higher: Sequence[str] = ()) -> Resolution | None:
    """Whether a past availability claim turned out right, from what was known by the moment of the reading (``credibility-v1``): the
    provider's line-up first, then its injury report, then claims of a higher tier (their assertions). None when nothing could check it."""
    if sheet is not None:
        if assertion == "out":
            return "refuted" if player_id in sheet.listed else "corroborated"
        if assertion == "starts":
            return "corroborated" if player_id in sheet.starters else "refuted"
        if assertion == "available" and player_id in sheet.listed:
            return "corroborated"
    if listing is not None and listing.status == "LISTED" and listing.missing:
        if assertion == "out":
            return "corroborated"
        if assertion in ("available", "starts"):
            return "refuted"
    if assertion in higher:
        return "corroborated"
    if any(incompatible(assertion, h) for h in higher):
        return "refuted"
    return None


# ── validity ────────────────────────────────────────────────────────────────────────────────────────────────────────

VALIDITY: Final[dict[str, timedelta]] = {
    "injury": timedelta(days=10), "suspension": timedelta(days=14), "lineup": timedelta(days=2), "coach_change": timedelta(days=90),
    "press_conference": timedelta(days=3), "other": timedelta(days=7)}
"""``validity-v1``: how long an item of each topic stands from its own date. ``injury`` is the packet's ``STALE_AFTER`` (one number, not
two); a suspension outlives a knock; a line-up is about one match; a change of coach lasts; what was said in a press conference is about the
next match; anything else a week."""
HALF_LIFE_SHARE: Final = 0.5
"""The freshness of an item halves every half of its topic's window: 1 when new, 0.25 at the edge, 0 past it."""
LOOKBACK: Final = max(VALIDITY.values())
"""How far back the claims about a team that belong to no match are read: an item older than the longest window is expired anyway."""

PRESS_CONFERENCE: Final = re.compile(
    r"rueda de prensa|conferencia de prensa|press conference|pre-?match (?:press )?conference|coletiva|conf[ée]rence de presse|"
    r"pressekonferenz|conferenza stampa|persconferentie", re.IGNORECASE)
"""The one topic nothing stored names: an item that is not about who plays or the coach, whose text says it comes from a press conference."""
KIND_TOPIC: Final[dict[str, Topic]] = {"injury": "injury", "doubtful": "injury", "suspension": "suspension", "lineup": "lineup",
                                       "coach": "coach_change"}


def topic_of(kind: str, text: str = "") -> Topic:
    """The topic of an item, from its kind (``ai.evidence.kind``) and, for the press conference only, its text."""
    topic = KIND_TOPIC.get(kind)
    if topic is not None:
        return topic
    return "press_conference" if PRESS_CONFERENCE.search(text or "") else "other"


def valid_until(topic: str, when: datetime) -> datetime:
    return when + VALIDITY[topic]


def expired(topic: str, when: datetime, at: datetime) -> bool:
    return at > valid_until(topic, when)


def freshness(topic: str, when: datetime, at: datetime) -> float:
    if expired(topic, when, at):
        return 0.0
    age = max((at - when).total_seconds(), 0.0)
    return round(float(0.5 ** (age / (HALF_LIFE_SHARE * VALIDITY[topic].total_seconds()))), 4)


# ── the ladder and the confidence ───────────────────────────────────────────────────────────────────────────────────

LADDER: Final[tuple[tuple[Status, tuple[tuple[Tier, int], ...]], ...]] = (
    ("OFICIAL", (("A", 1),)),
    ("CONFIRMADO", (("B", 1), ("C", 2))),
    ("CONFIRMADO", (("C", 3),)),
    ("REPORTADO", (("C", 1),)),
)
"""``ladder-v1``: ``(T, n)`` = at least n independent live outlets of tier T or better. The first rule that holds wins; none -> RUMOR."""
STATUS_CAP: Final[dict[str, float]] = {"RUMOR": 0.35, "REPORTADO": 0.70, "CONFIRMADO": 0.90, "OFICIAL": 1.0}
"""The most a claim of each status can be believed (``confidence-v1``): a rumour stays below 0.35 whatever its sources' record."""
D_COUNTED: Final = 1
"""How many D-tier outlets count in the support: one, the best (aggregators copy each other)."""


def at_least(tiers: Iterable[str], tier: str) -> int:
    return sum(1 for t in tiers if TIER_RANK[t] <= TIER_RANK[tier])


def status_of(outlet_tiers: Mapping[str, str]) -> tuple[Status, str]:
    """The status a set of independent outlets (outlet -> its tier) supports, and the rule that gave it."""
    tiers = list(outlet_tiers.values())
    for status, needs in LADDER:
        if all(at_least(tiers, t) >= n for t, n in needs):
            return status, " and ".join(f">= {n} independent {t}-or-better" for t, n in needs)
    return "RUMOR", "only D sources" if tiers else "no live source"


def support(outlets: Mapping[str, tuple[str, float]]) -> float:
    """``1 - prod(1 - credibility)`` over independent outlets (outlet -> (tier, credibility)), the D tier counted ``D_COUNTED`` times."""
    kept = [c for t, c in outlets.values() if t != "D"]
    kept += sorted((c for t, c in outlets.values() if t == "D"), reverse=True)[:D_COUNTED]
    miss = float(math.prod(1.0 - min(max(c, 0.0), 1.0) for c in kept))
    return round(1.0 - miss, 4)


def confidence(status: str, outlets: Mapping[str, tuple[str, float]], fresh: float) -> float:
    return round(min(STATUS_CAP[status], support(outlets)) * fresh, 4)


# ── contradictions ──────────────────────────────────────────────────────────────────────────────────────────────────

INCOMPATIBLE: Final = frozenset({frozenset({"out", "available"}), frozenset({"out", "starts"})})
"""The assertions about one person's availability that cannot both be true. A doubt is compatible with anything: it is a doubt."""
ContraRule = Literal["CC1", "CP1", "CP2", "CP3"]
CONTRA_RULES: Final[dict[str, str]] = {
    "CC1": "claim vs claim: the same person, an availability topic, incompatible assertions, both live",
    "CP1": "claim vs provider: claimed OUT, and the provider's line-up lists him (starter or bench)",
    "CP2": "claim vs provider: claimed STARTS, and the provider's line-up is known and he is not a starter",
    "CP3": "claim vs provider: claimed AVAILABLE or STARTS, and the provider's injury report lists him missing",
}
HARD: Final = frozenset({"CP1", "CP2"})
"""The contradictions that refute a claim outright: the team sheet is the clubs' own word."""


def incompatible(a: str, b: str) -> bool:
    return frozenset({a, b}) in INCOMPATIBLE


def against_provider(assertion: str, player_id: int | None, *, sheet: SquadSheet | None, listing: Listing | None) -> list[ContraRule]:
    """The claim-vs-provider rules a claim about a player breaks (none for a player the provider does not identify)."""
    if player_id is None:
        return []
    found: list[ContraRule] = []
    if sheet is not None and assertion == "out" and player_id in sheet.listed:
        found.append("CP1")
    if sheet is not None and assertion == "starts" and player_id not in sheet.starters:
        found.append("CP2")
    if listing is not None and listing.status == "LISTED" and listing.missing and assertion in ("available", "starts"):
        found.append("CP3")
    return found


def net(conf: float, *, opposing: Iterable[float] = (), provider: Iterable[str] = ()) -> float:
    """``confidence_net``: the confidence discounted by what contradicts it (module docstring)."""
    rules = set(provider)
    if rules & HARD:
        return 0.0
    value = conf * float(math.prod(1.0 - min(max(o, 0.0), 1.0) for o in opposing))
    if "CP3" in rules:
        value *= 1.0 - TIER_PRIOR["B"]
    return round(value, 4)


# ── one claim, decided ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Support:
    """One stored item that says a claim, as the rules read it."""

    evidence_id: int
    outlet: str
    tier: Tier
    credibility: float
    when: datetime


@dataclass(frozen=True, slots=True)
class Decided:
    status: Status
    rule: str
    confidence: float
    support: float
    freshness: float
    expired: bool
    valid_from: datetime
    valid_until: datetime
    live_ids: tuple[int, ...] = field(default_factory=tuple)


def decide(topic: str, items: Sequence[Support], *, at: datetime) -> Decided:
    """Status, confidence and validity of one claim (the items that say the same thing about the same subject), as of ``at``. Only live items
    count; when every item has expired, the status is the one all of them supported and the confidence is 0."""
    if not items:
        raise ValueError("a claim has at least one item")
    live = [s for s in items if not expired(topic, s.when, at)]
    basis = live or list(items)

    def outlets(of: Sequence[Support]) -> dict[str, tuple[str, float]]:
        best: dict[str, tuple[str, float]] = {}
        for s in of:  # one outlet counts once: with its best tier and, apart, its highest credibility (each a maximum: never lowered)
            seen = best.get(s.outlet)
            if seen is None:
                best[s.outlet] = (s.tier, s.credibility)
            else:
                best[s.outlet] = (min(seen[0], s.tier, key=TIER_RANK.__getitem__), max(seen[1], s.credibility))
        return best

    counted = outlets(basis)
    status, rule = status_of({o: t for o, (t, _) in counted.items()})
    fresh = max((freshness(topic, s.when, at) for s in live), default=0.0)
    sup = support(counted)
    conf = confidence(status, counted, fresh) if live else 0.0
    first = min(s.when for s in items)
    until = max(valid_until(topic, s.when) for s in items)
    return Decided(status, rule, conf, sup, fresh, not live, first, until, tuple(sorted(s.evidence_id for s in live)))


def rules_digest() -> str:
    """The digest of every constant of this version: what goes with each report, so that two reports are comparable."""
    body = {"tiers": [TIERS_VERSION, DOMAINS_DIGEST, sorted(REGISTRY_TIERS.items())],
            "credibility": [CREDIBILITY_VERSION, sorted(TIER_PRIOR.items()), PRIOR_WEIGHT, CREDIBILITY_WINDOW.days, HISTORY_PER_SOURCE],
            "ladder": [LADDER_VERSION, [[s, [list(n) for n in needs]] for s, needs in LADDER]],
            "confidence": [CONFIDENCE_VERSION, sorted(STATUS_CAP.items()), D_COUNTED],
            "validity": [VALIDITY_VERSION, sorted((k, v.total_seconds()) for k, v in VALIDITY.items()), HALF_LIFE_SHARE, PRESS_CONFERENCE.pattern],
            "contra": [CONTRA_VERSION, sorted(CONTRA_RULES), sorted(sorted(p) for p in INCOMPATIBLE)]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
