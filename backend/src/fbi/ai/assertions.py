"""Typed assertions with authority per type of claim, a ladder of confirmation by ORIGIN and four dates (IA-089, plan piece AD-C07).

WHY. ``ladder-v1`` (``fbi.evidence.rules``) counts OUTLETS: three pages of one wire story reprinted by three papers of one group are three
outlets and lift a rumour to CONFIRMADO. And the standing of a source is one tier for everything it says: a club's site is A for its line-up
and also for a transfer rumour about another club. Measured on 16 Nov 2026 (production, 30 days, n = 8.075 web evidences): 61,4 % come from
domains nobody classified and 68,1 % stay as rumours. This module is the rule written as code; it reads nothing and writes nothing.

``assertions-v1`` / ``ladder-v2``:

* **Type and authority.** Every assertion has a type of claim (``claim-v2``'s words, and ``LIST`` for a line-up or a list of absentees) and
  the authority of ITS source for THAT type, read from the directory's ``autoridad_por_afirmacion`` (``confirma``, ``informa``,
  ``solo_rumor``, ``sin_autoridad``; ``desconocida`` when the directory does not say). An authority ``confirma`` noted «solo lo propio» (a
  club) confirms only about its own team: about another team it informs. A sentence written as a rumour («según», «could», «se especula»)
  has the authority of a rumour whatever the source. A source of tier D (aggregators, tips, social: ``tiers-v1``) never lifts anything.
* **The ladder** (``RUNGS``, lowest first): RUMOR < REPORTE (one origin informs) < DECLARACION (a statement attributed to someone, reported
  by a source that informs) < CONFIRMADO (two INDEPENDENT origins inform) < OFICIAL (a source that confirms that type of claim says it).
  The press never confirms alone; a rumour never climbs alone.
* **Independent origins.** Two assertions are of the same origin when they come from the same domain, the same editorial group
  (``grupo_editorial``) or syndication network (``sindicacion``), are near-duplicates (``deep_pages.near_duplicate``) or attribute their words
  to the same speaker. Two of them are independent when none of that holds. CONFIRMADO needs a PAIR of independent ones - so adding an
  assertion never lowers a rung (a property test holds it), and three copies of one wire are one origin.
* **Four dates.** ``published_at`` (with where it came from: the page's own date, or none - never today's), ``seen_at`` (the first time the
  server saw the page; never rewritten), ``fact_at`` (the match it is about, or the date of the page) and ``valid_until`` (the window of its
  topic, ``fbi.evidence.rules.valid_until``). ``as_of`` drops what was seen after the moment of a decision: a fact seen later does not exist
  for it.
* **Contradictions** (``contradictions``): incompatible claims about who plays (``CC1``, as ``contra-evidence-v1``), two incompatible
  statements of the SAME speaker (``CS1``), an official time (``CO1``) or ground (``CO2``) that differs from the provider's. They raise an
  alert; they never correct anything.

Nothing here changes a probability, a pick, a status of ``ladder-v1`` or what a reader sees: the unified research uses it in shadow
(``fbi.ai.unified_research``), and ``scripts/ia_research_unified.py replay`` lists what would change against ``ladder-v1``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations
from typing import Final, Literal

from fbi.ai import deep_pages
from fbi.ai.source_policy import CLAIM_TYPE_OF, SourcePolicy, host_of, suffixes
from fbi.evidence import rules
from fbi.people.identity.names import alias_key, names_compatible

VERSION: Final = "assertions-v1"
LADDER_VERSION: Final = "ladder-v2"
Rung = Literal["RUMOR", "REPORTE", "DECLARACION", "CONFIRMADO", "OFICIAL"]
RUNGS: Final[tuple[Rung, ...]] = ("RUMOR", "REPORTE", "DECLARACION", "CONFIRMADO", "OFICIAL")
RANK: Final = {r: i for i, r in enumerate(RUNGS)}
LIFTING: Final = frozenset({"confirma", "informa"})

CLAIM_WORD: Final[dict[str, str]] = {**CLAIM_TYPE_OF, "LIST": "alineaciones", "LIST_OUT": "lesiones", "LIST_STARTER": "alineaciones"}
"""The directory's word (``autoridad_por_afirmacion``) for each type of claim of the code."""
ASSERTION_OF: Final[dict[str, str]] = {"OUT": "out", "SUSPENSION": "out", "DOUBT": "doubtful", "AVAILABLE": "available", "STARTER": "starts",
                                       "LIST_OUT": "out", "LIST_STARTER": "starts"}
TOPIC_OF: Final[dict[str, str]] = {"OUT": "injury", "DOUBT": "injury", "AVAILABLE": "injury", "SUSPENSION": "suspension", "STARTER": "lineup",
                                   "LIST_OUT": "injury", "LIST_STARTER": "lineup", "COACH": "coach_change", "SCHEDULE": "other",
                                   "VENUE": "other", "OTHER": "other"}

RUMOR_CUES: Final = re.compile(
    r"\b(?:rumou?rs?|rumores?|rumeurs?|geruchte?|voci|reportedly|according to reports|could|might|would|linked with|set to|"
    r"segun|podria|podrian|se especula|se habla|suena|interesa|habria|estaria|poderia|seria|cogita|potrebbe|sarebbe|pourrait|serait|"
    r"selon|soll|sollen|angeblich|zou|zouden|iddia|iddiaya)\b")
SPEECH: Final = re.compile(
    r"\b(?:said|says|told|confirmed|explained|admitted|insisted|revealed|dijo|afirmo|declaro|explico|aseguro|confirmo|reconocio|senalo|"
    r"disse|afirmou|declarou|ha detto|ha dichiarato|a declare|a dit|a confirme|sagte|erklarte|bestatigte|zei|verklaarde|dedi|acikladi|"
    r"rueda de prensa|press conference|conferencia de prensa|coletiva|conferenza stampa|conference de presse|pressekonferenz|persconferentie|"
    r"basin toplantisi)\b")
ROLE: Final = re.compile(
    r"\b(?:coach|manager|head coach|boss|entrenador|tecnico|dt|director tecnico|tecnico|treinador|allenatore|mister|entraineur|trainer|"
    r"coach|teknik direktor|hoca|seleccionador|selecionador|ct)\b")


@dataclass(frozen=True, slots=True)
class SourceFacts:
    """What the directory says of the source of a page, as the ladder reads it."""

    domain: str
    source_id: str | None = None
    name: str = ""
    source_type: str = ""
    authority: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    group: str = ""
    network: str = ""
    clubs: tuple[str, ...] = ()
    tier: str | None = None
    """``tiers-v1``'s tier of the domain (``fbi.evidence.rules.domain_tier``): D never lifts."""


def _group_key(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    head = re.split(r"[:(;]", text, maxsplit=1)[0]
    key = alias_key(head)
    return key.removeprefix("red ").removeprefix("grupo ").removeprefix("group ").strip()[:60]


def source_facts(policy: SourcePolicy | None, url_or_domain: str | None) -> SourceFacts:
    """The directory's record of the most specific registered domain of a page (the same suffix rule as ``fbi.ai.source_policy``)."""
    host = host_of(url_or_domain) or ""
    tier = rules.domain_tier(host) if host else None
    if policy is None or not host:
        return SourceFacts(host, tier=tier)
    for candidate in suffixes(host):
        s = policy.by_domain.get(candidate)
        if s is not None:
            rec = s.record
            clubs = tuple(c.strip() for c in str(rec.get("clubes_cubiertos") or "").split(";") if c.strip())
            return SourceFacts(candidate, s.source_id, s.name, s.source_type, s.authority, _group_key(rec.get("grupo_editorial")),
                               _group_key(rec.get("sindicacion")), clubs, tier)
    return SourceFacts(host, tier=tier)


def authority_for(src: SourceFacts | None, claim_type: str, *, team_names: Sequence[str] = (), quote: str = "") -> tuple[str, str]:
    """The authority of a source for one type of claim, and why: the directory's level; ``confirma`` «solo lo propio» only about its own
    team; a sentence written as a rumour is a rumour; a source the directory does not have is ``desconocida``."""
    if RUMOR_CUES.search(" ".join(alias_key(quote).split())):
        return "solo_rumor", "rumor_cue"
    if src is None or not src.authority:
        return "desconocida", "not_in_directory"
    word = CLAIM_WORD.get(claim_type, "contexto")
    entry = src.authority.get(word) or {}
    level = str(entry.get("level") or "desconocida")
    note = alias_key(entry.get("note") or "")
    if level == "confirma" and ("propio" in note or (src.source_type == "oficial" and src.clubs)):
        own = [src.name, *src.clubs]
        if not team_names or not names_compatible(own, team_names, person=False):
            return "informa", "confirms_only_its_own"
    return level, f"directory:{word}"


CLUB_VOICE: Final = re.compile(r"\b(?:club|clube|verein|vereniging|kulup|comunicado|statement|communique|comunicato|mitteilung|aciklama)\b")
QUOTE_MARKS: Final = re.compile(r"[«»“”\"]")


def speaker_of(quote: str, *, team_id: int | None, players: Iterable[int] = ()) -> str | None:
    """Who the words of a quote are attributed to, by code - only when the quote has a word of speech: the coach of the team (a word of the
    role), the club (its statement), or the one player it names when his words are in quotation marks. None otherwise: a quote is not a
    statement by default, and «no jugará, confirmó el club» is the club's word, not the player's."""
    folded = " ".join(alias_key(quote).split())
    if not SPEECH.search(folded):
        return None
    if ROLE.search(folded) and team_id is not None:
        return f"coach:{team_id}"
    if CLUB_VOICE.search(folded) and team_id is not None:
        return f"club:{team_id}"
    named = sorted(set(players))
    return f"player:{named[0]}" if len(named) == 1 and QUOTE_MARKS.search(quote) else None


@dataclass(frozen=True, slots=True)
class Assertion:
    """One typed claim of one page."""

    subject_kind: str
    subject_id: int
    team_id: int | None
    claim_type: str
    url: str
    source: SourceFacts
    authority: str
    authority_why: str
    seen_at: datetime
    published_at: datetime | None = None
    published_from: str = "none"
    """``page`` (the date the search API gave for the page) or ``none``: the server never uses today's date."""
    fact_at: datetime | None = None
    valid_until: datetime | None = None
    applies_to: str = "UNSPECIFIED"
    fixture_id: int | None = None
    attributed_to: str | None = None
    text_hash: int | None = None
    """The simhash of the page's clean text (``deep_pages.simhash``): near-duplicates are one origin."""
    quote: str = ""

    @property
    def assertion(self) -> str:
        return ASSERTION_OF.get(self.claim_type, "info")

    @property
    def topic(self) -> str:
        return TOPIC_OF.get(self.claim_type, "other")

    @property
    def fact_key(self) -> tuple[str, int, str]:
        """What two assertions must share to support the same fact: the subject and what is said of him."""
        return (self.subject_kind, self.subject_id, self.assertion if self.assertion != "info" else self.claim_type)

    @property
    def lifts(self) -> bool:
        return self.authority in LIFTING and self.source.tier != "D"


def four_dates(*, published_at: datetime | None, seen_at: datetime, kickoff_at: datetime | None, applies_to: str, claim_type: str
               ) -> tuple[datetime | None, str, datetime, datetime, datetime]:
    """(published_at, its provenance, seen_at, fact_at, valid_until) of an assertion. A page date in the future of when it was seen is not a
    date (``none``)."""
    published = published_at if published_at is not None and published_at <= seen_at + timedelta(hours=1) else None
    origin = "page" if published is not None else "none"
    base = published or seen_at
    fact = kickoff_at if applies_to == "THIS_MATCH" and kickoff_at is not None else base
    until = rules.valid_until(TOPIC_OF.get(claim_type, "other"), base)
    return published, origin, seen_at, fact, until


def same_origin(a: Assertion, b: Assertion) -> bool:
    """Whether two assertions come from the same origin: same domain, group or syndication network, near-duplicate texts, or the same speaker."""
    if a.source.domain and a.source.domain == b.source.domain:
        return True
    if a.source.group and a.source.group in (b.source.group, b.source.network):
        return True
    if a.source.network and a.source.network in (b.source.group, b.source.network):
        return True
    if a.attributed_to is not None and a.attributed_to == b.attributed_to:
        return True
    return a.text_hash is not None and b.text_hash is not None and deep_pages.near_duplicate(a.text_hash, b.text_hash)


def independent_origins(items: Sequence[Assertion]) -> int:
    """A count of the independent origins of a set (greedy, for the report). The ladder asks only whether a PAIR exists (``rung``)."""
    reps: list[Assertion] = []
    for a in items:
        if not any(same_origin(a, r) for r in reps):
            reps.append(a)
    return len(reps)


def live(items: Iterable[Assertion], at: datetime) -> list[Assertion]:
    """What was seen by ``at`` and is still valid then."""
    return [a for a in as_of(items, at) if a.valid_until is None or a.valid_until > at]


def rung(items: Sequence[Assertion]) -> tuple[Rung, str]:
    """The rung of a fact from the assertions that support it (all about the same ``fact_key``), and the rule that gave it."""
    lifting = [a for a in items if a.lifts]
    if any(a.authority == "confirma" for a in lifting):
        return "OFICIAL", "a source that confirms this type of claim"
    informing = [a for a in lifting if a.authority == "informa"]
    if any(not same_origin(a, b) for a, b in combinations(informing, 2)):
        return "CONFIRMADO", "two independent origins"
    if any(a.attributed_to is not None for a in informing):
        return "DECLARACION", "a statement attributed by a source that informs"
    if informing:
        return "REPORTE", "one origin informs"
    return "RUMOR", "no source with authority for this type of claim"


@dataclass(frozen=True, slots=True)
class Fact:
    key: tuple[str, int, str]
    rung: Rung
    why: str
    origins: int
    items: tuple[Assertion, ...]


def facts(items: Iterable[Assertion], *, at: datetime) -> list[Fact]:
    """The facts of a set of assertions as of ``at`` (live only), each with its rung."""
    groups: dict[tuple[str, int, str], list[Assertion]] = {}
    for a in live(items, at):
        groups.setdefault(a.fact_key, []).append(a)
    out = []
    for key, group in sorted(groups.items()):
        r, why = rung(group)
        out.append(Fact(key, r, why, independent_origins([a for a in group if a.lifts]), tuple(group)))
    return out


def as_of(items: Iterable[Assertion], known_at: datetime) -> list[Assertion]:
    """What existed at ``known_at``: an assertion seen after it does not exist for a decision taken then (fugas temporales)."""
    return [a for a in items if a.seen_at <= known_at]


# ── contradictions: alerts, never corrections ─────────────────────────────────────────────────────────────────────

INCOMPATIBLE: Final = rules.INCOMPATIBLE
_TIME: Final = re.compile(r"\b([01]?\d|2[0-3])[:.h]([0-5]\d)\b")


@dataclass(frozen=True, slots=True)
class Alert:
    rule: str
    """``CC1`` claim vs claim, ``CS1`` the same speaker, ``CO1`` official time vs provider, ``CO2`` official ground vs provider."""
    subject: tuple[str, int]
    urls: tuple[str, ...]


def times_in(text: str) -> set[str]:
    """``HH:MM`` of every time a quote writes («20:00», «20.00», «20h00»)."""
    return {f"{int(h):02d}:{m}" for h, m in _TIME.findall(text)}


def contradictions(items: Sequence[Assertion], *, at: datetime, kickoff_times: Iterable[str] = (), venue: str | None = None,
                   venues: Iterable[str] = ()) -> list[Alert]:
    """The alerts of a set of assertions as of ``at``.

    * ``CC1``: two live assertions about the same subject say incompatible things about whether he plays, from different origins.
    * ``CS1``: the same speaker says incompatible things about the same subject.
    * ``CO1``: a source that confirms the calendar writes a time that is none of ``kickoff_times`` (the provider's kick-off, written in each
      zone the caller knows it in).
    * ``CO2``: a source that confirms the calendar names a ground of ``venues`` that is not the provider's ``venue``.
    """
    now = live(items, at)
    out: list[Alert] = []
    for a, b in combinations(now, 2):
        if (a.subject_kind, a.subject_id) != (b.subject_kind, b.subject_id):
            continue
        if frozenset({a.assertion, b.assertion}) in INCOMPATIBLE:
            if a.attributed_to is not None and a.attributed_to == b.attributed_to:
                out.append(Alert("CS1", (a.subject_kind, a.subject_id), (a.url, b.url)))
            elif not same_origin(a, b):
                out.append(Alert("CC1", (a.subject_kind, a.subject_id), (a.url, b.url)))
    known = set(kickoff_times)
    others = {alias_key(v) for v in venues if v and alias_key(v) != alias_key(venue or "")}
    for a in now:
        if a.authority != "confirma" or a.claim_type not in ("SCHEDULE", "VENUE"):
            continue
        written = times_in(a.quote)
        if known and written and not written & known:
            out.append(Alert("CO1", (a.subject_kind, a.subject_id), (a.url,)))
        folded = alias_key(a.quote)
        if venue and any(o and o in folded for o in others) and alias_key(venue) not in folded:
            out.append(Alert("CO2", (a.subject_kind, a.subject_id), (a.url,)))
    return out


__all__ = ["LADDER_VERSION", "RUNGS", "VERSION", "Alert", "Assertion", "Fact", "SourceFacts", "as_of", "authority_for", "contradictions",
           "facts", "four_dates", "independent_origins", "live", "rung", "same_origin", "source_facts", "speaker_of", "times_in"]
