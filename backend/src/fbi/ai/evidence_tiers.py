"""The pure tables of ``evidence-engine-v1`` that the shadow unified research shares (IA-089, ``ladder-v2``): the tiers of a domain
(``tiers-v1``), the windows of validity per topic (``validity-v1``), the status ladder (``ladder-v1``) and the assertions that cannot both be
true (``contra-evidence-v1``).

They were written in ``fbi.evidence.rules`` (IA-012) and live here, unchanged, so that ``fbi.ai.assertions`` and ``fbi.ai.unified_readers``
read the same numbers as the Evidence Engine WITHOUT importing it: the engine is in shadow and nothing under ``fbi.ai`` imports it
(``tests/unit/test_evidence_engine_isolation.py``), and ``fbi.ai`` and ``fbi.evidence`` do not import each other
(``tests/unit/test_architecture.py``). ``fbi.evidence.rules`` re-exports every name under the same name: its digests (``DOMAINS_DIGEST``,
``rules_digest``) and its behaviour are what they were. The module's docstring there says what each table means.

Pure: nothing here reads a database, a clock or a setting.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Final, Literal

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

Tier = Literal["A", "B", "C", "D"]
TIERS: Final[tuple[Tier, ...]] = ("A", "B", "C", "D")
TIER_RANK: Final[dict[str, int]] = {"A": 0, "B": 1, "C": 2, "D": 3}
Status = Literal["RUMOR", "REPORTADO", "CONFIRMADO", "OFICIAL"]
STATUSES: Final[tuple[Status, ...]] = ("RUMOR", "REPORTADO", "CONFIRMADO", "OFICIAL")
"""The ladder, lowest first."""

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
better tier. The lists are pinned by ``fbi.evidence.rules.DOMAINS_DIGEST``: a change to any of them fails a test until the version is bumped."""


def _suffixes(domain: str) -> list[str]:
    parts = domain.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def domain_tier(domain: str | None) -> Tier | None:
    """The tier of the most specific listed suffix of a domain, or None when no list has it."""
    if not domain:
        return None
    host = domain.strip().lower().removeprefix("www.")
    return next((DOMAIN_TIERS[s] for s in _suffixes(host) if s in DOMAIN_TIERS), None)


# ── validity ────────────────────────────────────────────────────────────────────────────────────────────────────────

VALIDITY: Final[dict[str, timedelta]] = {
    "injury": timedelta(days=10), "suspension": timedelta(days=14), "lineup": timedelta(days=2), "coach_change": timedelta(days=90),
    "press_conference": timedelta(days=3), "other": timedelta(days=7)}
"""``validity-v1``: how long an item of each topic stands from its own date. ``injury`` is the packet's ``STALE_AFTER`` (one number, not
two); a suspension outlives a knock; a line-up is about one match; a change of coach lasts; what was said in a press conference is about the
next match; anything else a week."""


def valid_until(topic: str, when: datetime) -> datetime:
    return when + VALIDITY[topic]


# ── the ladder ──────────────────────────────────────────────────────────────────────────────────────────────────────

LADDER: Final[tuple[tuple[Status, tuple[tuple[Tier, int], ...]], ...]] = (
    ("OFICIAL", (("A", 1),)),
    ("CONFIRMADO", (("B", 1), ("C", 2))),
    ("CONFIRMADO", (("C", 3),)),
    ("REPORTADO", (("C", 1),)),
)
"""``ladder-v1``: ``(T, n)`` = at least n independent live outlets of tier T or better. The first rule that holds wins; none -> RUMOR."""


def at_least(tiers: Iterable[str], tier: str) -> int:
    return sum(1 for t in tiers if TIER_RANK[t] <= TIER_RANK[tier])


def status_of(outlet_tiers: Mapping[str, str]) -> tuple[Status, str]:
    """The status a set of independent outlets (outlet -> its tier) supports, and the rule that gave it."""
    tiers = list(outlet_tiers.values())
    for status, needs in LADDER:
        if all(at_least(tiers, t) >= n for t, n in needs):
            return status, " and ".join(f">= {n} independent {t}-or-better" for t, n in needs)
    return "RUMOR", "only D sources" if tiers else "no live source"


# ── contradictions ──────────────────────────────────────────────────────────────────────────────────────────────────

INCOMPATIBLE: Final = frozenset({frozenset({"out", "available"}), frozenset({"out", "starts"})})
"""The assertions about one person's availability that cannot both be true. A doubt is compatible with anything: it is a doubt."""

__all__ = ["DOMAIN_TIERS", "INCOMPATIBLE", "LADDER", "STATUSES", "TIERS", "TIER_RANK", "VALIDITY", "Status", "Tier", "at_least",
           "domain_tier", "status_of", "valid_until"]
