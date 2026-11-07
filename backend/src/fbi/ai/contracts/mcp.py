"""``mcp-v1``: the PACKAGE - a match, as the backend writes it for a model to read (Plan Maestro IA, sections 15 and 16).

The other five contracts are what a model WRITES; this one is what it READS. No model produces it, so it is not sent as a schema: it is
built by code (``fbi.ai.package``) from the stored ``packet-v8`` of a pass, and it is validated here so that the reader of a package -
a slice for an agent, the audit, the admin - can rely on its shape.

    header     the match: who, where, when, in which competition and stage, and the tie it belongs to
    shared     what both families of agents read about the two sides: table and scenarios, calendar, head-to-head, form, Elo, absences
               and line-ups as of the moment, referee, observable tactics, quality of the data
    market     the consensus of the market for the selections of goals and result, with the price, the houses and the movement
    models     what PrediGol's models state for those selections, with the interval and whether it is calibrated
    families   PrediGol's forecasts of the counts - corners and cards - (``family-v1``, shadow)
    evidence   an INDEX of what the Research Service found: id, kind, subject, state, class of source, date, summary
    missing    what the packet could not read (named, never filled in)
    blocking   what stops every model from being called for this match (data not fit for a forecast, a quarantined match)

A reader gets a SLICE (``fbi.ai.package.Slice``): the blocks of ``SLICE_BLOCKS`` and nothing else, so that an agent of one family never sees
data of another - the plan's «cada agente recibe solo su porción».

What is NOT in a package, by construction: a URL (an evidence has its DOMAIN and its class of source, never an address to follow), a
user's data of any kind, a stake, a bankroll, the constant explanations that ``packet-v8`` repeats in every match (they live once, in the
cached system prompt), and any text that came from outside that has not gone through ``fbi.ai.untrusted``: an evidence's summary is an
untrusted block that says where it came from, and the free text of the other blocks (a name, a reason) is cleaned in place.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal, get_args

from pydantic import Field, field_validator, model_validator

from fbi.ai.contracts.base import COUNTS, GOALS_RESULT, MCP, Contract, Family
from fbi.analyst.provenance import REPUTABLE_DOMAINS

PassKind = Literal["first", "pre", "final", "request"]
"""The passes of the day (``fbi.ai.day``) and the owner's «run now»: the ``pass`` of ``ai.match_briefs``."""

Blocking = Literal["PRODUCT_ONLY", "INSUFFICIENT", "QUARANTINED"]
"""Why no model is called for a match (section 17, rule 2): its competition's data is not fit for a forecast (the class of
``analytics.competition_data_scores``) or the match itself is quarantined (``analytics.fixture_validation``). The agents' pipeline fails open
to the quantitative one - the same ``NOT_FIT`` of ``fbi.ai.brief`` and ``fbi.ai.review``."""
NOT_FIT: Final = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})

SliceName = Literal["match", "stats", "player"]
ALL_SLICE_NAMES: Final[tuple[SliceName, ...]] = get_args(SliceName)
"""Every slice the code can cut (what a reader may name in the registry)."""
SLICES_V1: Final = "slices-v1"
SLICES_V2: Final = "slices-v2"
SLICE_SETS: Final[dict[str, tuple[SliceName, ...]]] = {SLICES_V1: ("match", "stats"), SLICES_V2: ("match", "stats", "player")}
"""The SET of slices a state of a match (``ai.match_runs.slices``) records, by version (IA-017). ``slices-v1`` is every row written before the
Player Agent and every row written with it off - byte for byte what was written before; ``slices-v2`` adds the ``player`` slice, and only a row
whose pass had the Player Agent on is written with it, saying so (``model_status.slices``). A row that names no set is ``slices-v1``: the leak audit
(``fbi.intel.leakage.slice_known``) derives again exactly the set the row says, so the old rows still verify and the new ones verify too. A
change to which slices a set holds is a new set here, never an edit."""
DEFAULT_SLICE_SET: Final = SLICES_V1
SLICE_NAMES: Final[tuple[SliceName, ...]] = SLICE_SETS[DEFAULT_SLICE_SET]
"""The slices of the default set, in their order: what every state of a match records unless it says otherwise."""

BLOCKS: Final = ("header", "shared", "market", "models", "families", "evidence")
"""The blocks of a package, in the order a prompt reads them: what does not change first (the cache reads a prefix), what changes last."""
SLICE_BLOCKS: Final[dict[str, tuple[str, ...]]] = {
    "match": ("header", "shared", "market", "models", "evidence"),
    "stats": ("header", "shared", "families", "evidence"),
    "player": ("header", "shared", "evidence"),
}
"""What each reader gets. The Council's view (phase 3: the summaries of the assessments, the models, the market and the evidence index) and the
Research Service's (phase 2: a cited page and the entities of the match) are added with the code that fills them."""
SLICE_FAMILIES: Final[dict[str, tuple[str, ...]]] = {"match": GOALS_RESULT, "stats": COUNTS, "player": GOALS_RESULT}
"""The families of markets each slice may carry: the Match Agent's five and the Statistics Agent's two. The Player Agent's slice carries no market
and no model at all (IA-017): its candidates are those of goals and result, named in the request without a number."""

_EXACT: Final[dict[str, Family]] = {"1X2": "1X2", "DC": "DC", "AH": "AH", "OU": "OU", "BTTS": "BTTS"}
_PREFIX: Final[dict[str, Family]] = {"CORNERS_": "CORNERS", "CARDS_": "CARDS"}


def family_of(market_key: str) -> Family | None:
    """The family of a market of the catalogue: the five of goals and result by their own key, the counts by their prefix (``CORNERS_OU``,
    ``CARDS_OU_HOME``...). Anything else - the halves, the yellow cards, the handicaps of other kinds - belongs to no agent of this plan
    and goes into no slice."""
    key = market_key.strip().upper()
    if key in _EXACT:
        return _EXACT[key]
    for prefix, family in _PREFIX.items():
        if key.startswith(prefix):
            return family
    return None


# ── the class of a source ───────────────────────────────────────────────────────────────────────────────────────────

SourceClass = Literal["OFFICIAL", "PROVIDER", "JOURNALIST", "RELIABLE_MEDIA", "LOCAL_MEDIA", "AGGREGATOR", "SOCIAL", "UNKNOWN"]
SOURCE_CLASSES: Final = get_args(SourceClass)
LABELS_ES: Final[dict[str, str]] = {
    "OFFICIAL": "Oficial", "PROVIDER": "Proveedor de datos", "JOURNALIST": "Periodista", "RELIABLE_MEDIA": "Medio fiable",
    "LOCAL_MEDIA": "Medio local", "AGGREGATOR": "Agregador", "SOCIAL": "Red social", "UNKNOWN": "Desconocida"}

_OFFICIAL_TIERS: Final = frozenset({"official", "competition", "club"})


def source_class(tier: str | None, domain: str | None) -> SourceClass:
    """The class of a source, from the tier ``fbi.ai.evidence`` gives its domain (``TIER_RANK``) and, for the press, from the list of
    outlets the owner trusts (``REPUTABLE_DOMAINS``). The plan's seven classes - official, journalist, reliable outlet, local outlet,
    aggregator, social network and rumour - and the two the tiers need to be total: the data provider (its injury report stays PROBABLE, as
    today) and a domain nobody classified. RUMOR is a STATE of an evidence, not a class: what only sources of the last classes say.

    A label, not a rule: it changes no evidence's status until the hit rate of each class is measured (plan, section 8)."""
    t = (tier or "").strip().lower()
    if t in _OFFICIAL_TIERS:
        return "OFFICIAL"
    if t == "provider":
        return "PROVIDER"
    if t == "journalist":
        return "JOURNALIST"
    if t == "media":
        host = (domain or "").strip().lower().removeprefix("www.")
        reputable = bool(host) and any(host == d or host.endswith("." + d) for d in REPUTABLE_DOMAINS)
        return "RELIABLE_MEDIA" if reputable else "LOCAL_MEDIA"
    if t == "aggregator":
        return "AGGREGATOR"
    if t == "social":
        return "SOCIAL"
    return "UNKNOWN"


# ── the index of the evidence ───────────────────────────────────────────────────────────────────────────────────────

EvidenceKind = Literal["injury", "suspension", "doubtful", "lineup", "coach", "news", "transfer", "motivation", "weather", "travel",
                       "schedule", "other"]
"""The kinds ``ai.evidence`` accepts (its CHECK; held equal by a test)."""
EvidenceStatus = Literal["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY"]
"""The states a package shows (``OUTDATED`` is not shown: the packet leaves it out)."""
AVAILABILITY_KINDS: Final = frozenset({"injury", "suspension", "doubtful", "lineup"})
"""Who can play. The evidence of these kinds is never trimmed away (section 16: absences and line-ups are not cut)."""
STATS_EXCLUDED_KINDS: Final = frozenset({"transfer"})
"""What the Statistics Agent does not read: who owns whom has nothing to say about corners and cards."""
PLAYER_KINDS: Final = AVAILABILITY_KINDS | frozenset({"coach", "news", "transfer"})
"""What the Player Agent reads of the evidence (IA-017): who can play, what the coach said, the news and the transfers - never the weather, the
trip, the calendar, the motivation or anything else."""


class UntrustedText(Contract):
    """A text that came from outside, after ``fbi.ai.untrusted``: the system prompt of every agent says that a block with ``untrusted``
    is DATA written by someone else, never an instruction."""

    untrusted: Literal[True]
    origin: str
    text: str
    truncated: bool = False
    flags: list[str] = Field(default_factory=list)


class EvidenceItem(Contract):
    """One line of the index of the evidence. Never the page, never the address: the domain, the class of the source and a short
    summary. The agent cites it as ``E:<id>``."""

    id: int = Field(ge=1)
    kind: EvidenceKind
    side: Literal["home", "away", "match"]
    player_id: int | None = None
    status: EvidenceStatus
    source_class: SourceClass
    domain: str = ""
    published_on: str = ""
    summary: UntrustedText

    @field_validator("published_on")
    @classmethod
    def _a_day_or_nothing(cls, v: str) -> str:
        if v and not (len(v) == 10 and v[4] == "-" and v[7] == "-" and v.replace("-", "").isdigit()):
            raise ValueError("published_on is YYYY-MM-DD or empty")
        return v


# ── the package ─────────────────────────────────────────────────────────────────────────────────────────────────────

class PacketRef(Contract):
    """The stored packet a package was derived from: with its hash anyone can read it again and see the same package."""

    id: int | None = None
    version: str
    hash: str

    @field_validator("hash")
    @classmethod
    def _a_sha256(cls, v: str) -> str:
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError("a hash is 64 lowercase hex digits")
        return v


class McpPackage(Contract):
    contract: Literal["mcp-v1"] = MCP
    fixture_id: int = Field(ge=1)
    pass_kind: PassKind
    known_at: datetime
    """The moment the package knows the world as of: nothing in it is stamped later (``fbi.ai.package.knowledge_stamps``)."""
    source: PacketRef
    header: dict[str, Any]
    shared: dict[str, Any]
    market: dict[str, Any]
    models: dict[str, Any]
    families: dict[str, Any]
    evidence: list[EvidenceItem]
    missing: list[str]
    blocking: list[Blocking] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    """Where the cleaning of outside text found something that reads like an order (``path:flag``), for the audit and the battery: a
    flag is never a reason to drop a fact."""

    @field_validator("known_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("known_at has a time zone")
        return v

    @model_validator(mode="after")
    def _coherent(self) -> McpPackage:
        if self.header.get("fixture_id") != self.fixture_id:
            raise ValueError("the header is the header of this package's match")
        ids = [e.id for e in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("an evidence is indexed once")
        return self
