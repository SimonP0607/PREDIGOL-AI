"""The dynamic selector of sources (IA-086, plan piece AD-C04): for a match, a side, a player, a market and a TYPE OF CLAIM, which sources
of the directory v2 have authority for THAT claim, in what order, and by which route they may be read today. ``source-select-v1``.

    select(context, claim_type, at=..., policy=..., catalog=...)      pure: a ``Selection`` (picks in order, the Exa queries, why)
    select_sources(conn, fixture_id, claim_type, at=...)              the same, the match read from the database (read only)
    explain(selection)                                                the reasons, in Spanish, one line per source

WHICH SOURCES ARE IN SCOPE (``scope``), from the fields of the directory - never from a text a page wrote:

* ``club_oficial`` - the official site of each club (``tipo = oficial``, ``ambito = club``), when one of its ``clubes_cubiertos`` is the
  team: the same distinctive words of the name (``Atlético Bucaramanga`` = ``Bucaramanga``; ``América de Cali`` is not ``Deportivo Cali``)
  AND the same country (``CD Nacional`` of Madeira is not ``Atlético Nacional``). A team without a known country gets none: abstaining is
  better than a homonym.
* ``liga`` - the league of a domestic competition: the national officials of its country the registry reads as a competition
  (``derived_tier``), without the amateur, youth, women's or futsal ones; ``federacion`` when the country has no league in the directory,
  and always for a national team.
* ``confederacion`` - the confederation or FIFA of an international competition, by the words of its name (``UEFA Nations League``).
* ``regional`` - the regional and city media of a side's country whose ``clubes_cubiertos`` name the team or whose ``region_ciudad``
  names its city (Vanguardia, El Frente, Canal TRO for Bucaramanga; El Colombiano, Telemedellín for Medellín). Not for national teams.
* ``nacional`` - the national media of each side's country; ``datos`` - the statistics sources of the country or international ones.

THE AUTHORITY is the directory's ``autoridad_por_afirmacion`` for the claim type: ``confirma``, ``informa``, ``solo_rumor``,
``sin_autoridad``. A source whose authority is not ``confirma`` or ``informa`` is NOT a source of a fact of that type (a rumour never
comes as a fact from a source without authority); with ``claim_type = rumores`` every source of the scope is returned, and none counts as a
fact. A club «confirma (solo del propio club)»: asked about the other side (``entity_side``), it has no authority.

THE ROUTE (``via``), from the source policy of IA-063 (``fbi.ai.source_policy``) at the moment of asking:

    rss | sitemap | official    read by our own request (only a source that is authorised AND signed by the owner: ``can_fetch``)
    exa                         Exa with ``includeDomains`` (the same, and Exa's envelope not spent to 95 %)
    link                        only its link and title: pending of rights, unsigned, AI-reserved (never a model), or no budget
    none                        nothing: blocked, unchecked, excluded, unknown

``would_via`` says the route it would have if the owner signed it (the «habría leído» of the shadow). An AI-reserved source is ``link``
for ever: its ``would_via`` is ``link`` too.

THE ORDER: priority = proximity of the kick-off (<= 6 h: 1; 6-36 h: 0,7; 36 h-7 d: 0,4; later: 0,1) x priority of the entity (the
caller's, 1 by default) x role x authority x reliability (``fiabilidad``) x what may be done with it today x the market's relevance.

THE QUERIES are written HERE, by the server, from the names of the teams in the database and a fixed list of words per claim type and
language (``TOPICS``): no model writes a query, a URL or a name, and no text read from a page changes one. At most ``max_exa`` of them
per selection (1 by default: today Exa answers 2,0 searches per match - production, 2 to 16 Nov 2026, 890 searches over 446 matches).

Nothing here keeps state, writes, calls a model or the web, or changes a probability, a threshold, a tier or a pick."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai import source_policy
from fbi.ai import source_registry as registry
from fbi.people.countries import country_key
from fbi.people.identity.names import CLUB_WORDS, PARTICLES, alias_key

VERSION: Final = "source-select-v1"

Role = Literal["club_oficial", "liga", "federacion", "confederacion", "regional", "nacional", "datos"]
Via = Literal["rss", "sitemap", "official", "exa", "link", "none"]
Side = Literal["home", "away"]

ROLE_WEIGHT: Final[dict[str, float]] = {"club_oficial": 1.0, "liga": 1.0, "federacion": 0.95, "confederacion": 0.9, "regional": 0.85,
                                        "nacional": 0.75, "datos": 0.6}
AUTHORITY_WEIGHT: Final[dict[str, float]] = {"confirma": 1.0, "informa": 0.6, "solo_rumor": 0.3, "sin_autoridad": 0.2}
RELIABILITY_WEIGHT: Final[dict[str, float]] = {"alta": 1.0, "media-alta": 0.85, "media": 0.7, "baja": 0.4}
VIA_WEIGHT: Final[dict[str, float]] = {"rss": 1.0, "sitemap": 1.0, "official": 1.0, "exa": 0.9}
"""What may be done with a source today: read now (1), or only its link - 0,6 if signing it would let it be read, 0,3 if never."""
FACT_LEVELS: Final = frozenset({"confirma", "informa"})
RUMOUR: Final = "rumores"
MEDIA_TYPES: Final = frozenset({"prensa_generalista", "prensa_deportiva", "radio_tv", "especializada", "agencia"})
NOT_PROFESSIONAL: Final = ("aficionad", "amateur", "femenin", "juvenil", "futsal", "playa", "sub 2", "sub 1", "u19", "u20", "u21")
"""Words that make a national official something else than the league of a professional men's competition (Difútbol, the WE League...)."""
EXA_CUT: Final = Decimal("0.95")
"""The selector stops proposing Exa when the month has spent 95 % of Exa's envelope (US$ 35, decision 12)."""
MAX_EXA: Final = 1
"""Exa queries per selection: below the 2,0 searches per match of today (``ai.usage``, 2-16 Nov 2026, 890 over 446 matches)."""

CONFEDERATIONS: Final[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = (
    (("uefa", "champions league", "europa league", "conference league", "euro "), ("uefa", "org-eu-uefa-documents")),
    (("concacaf", "gold cup", "copa oro"), ("concacaf",)),
    (("conmebol", "libertadores", "sudamericana", "copa america", "recopa"), ("conmebol",)),
    (("afc ", "asian cup", "afc champions"), ("afc",)),
    (("caf ", "africa cup", "african nations", "caf champions"), ("caf",)),
    (("ofc", "oceania"), ("ofc",)),
    (("world cup", "fifa", "club world"), ("fifa-com", "fifa")),
)
"""Words of a competition's name (lower case, no accents) -> the directory ids of its organiser."""

MARKET_CLAIMS: Final[dict[str, frozenset[str]]] = {
    "1x2": frozenset({"lesiones", "alineaciones", "convocatorias", "sanciones", "declaraciones"}),
    "goals": frozenset({"lesiones", "alineaciones", "convocatorias", "sanciones"}),
    "btts": frozenset({"lesiones", "alineaciones", "convocatorias", "sanciones"}),
    "cards": frozenset({"arbitraje", "sanciones", "reglamento"}),
    "corners": frozenset({"alineaciones", "lesiones"}),
}
"""The claim types that move a market: a source for another one is ranked a little lower (x 0,8) when a market is given."""

TOPICS: Final[dict[str, dict[str, str]]] = {
    "lesiones": {"es": "lesionados bajas", "en": "injury news", "pt": "lesionados desfalques", "it": "infortunati", "fr": "blessés",
                 "de": "verletzte"},
    "convocatorias": {"es": "convocados", "en": "squad announced", "pt": "convocados", "it": "convocati", "fr": "groupe convoqué",
                      "de": "kader"},
    "alineaciones": {"es": "alineación titular", "en": "starting lineup", "pt": "escalação", "it": "formazione", "fr": "composition",
                     "de": "aufstellung"},
    "sanciones": {"es": "sancionados suspendidos", "en": "suspended", "pt": "suspensos", "it": "squalificati", "fr": "suspendus",
                  "de": "gesperrt"},
    "declaraciones": {"es": "rueda de prensa", "en": "press conference", "pt": "entrevista coletiva", "it": "conferenza stampa",
                      "fr": "conférence de presse", "de": "pressekonferenz"},
    "arbitraje": {"es": "árbitro designado", "en": "referee appointed", "pt": "árbitro escalado", "it": "arbitro designato",
                  "fr": "arbitre désigné", "de": "schiedsrichter"},
    "calendario": {"es": "horario sede", "en": "kick-off venue", "pt": "horário local", "it": "orario stadio", "fr": "horaire stade",
                   "de": "anstoß stadion"},
}
"""The fixed words of a query, per claim type and language. A claim type without words here gets no Exa query."""

COUNTRY_CODES: Final[dict[str, str]] = {
    "germany": "DE", "usa": "US", "colombia": "CO", "england": "GB-ENG", "spain": "ES", "italy": "IT", "brazil": "BR", "argentina": "AR",
    "mexico": "MX", "japan": "JP", "france": "FR", "south korea": "KR", "portugal": "PT", "netherlands": "NL", "turkey": "TR",
    "belgium": "BE", "chile": "CL", "china": "CN", "switzerland": "CH", "australia": "AU", "romania": "RO", "denmark": "DK",
    "sweden": "SE", "norway": "NO", "czech republic": "CZ", "canada": "CA", "hungary": "HU", "poland": "PL", "scotland": "GB-SCT",
    "austria": "AT", "croatia": "HR", "bulgaria": "BG", "slovakia": "SK", "south africa": "ZA", "greece": "GR", "russia": "RU",
    "finland": "FI", "ireland": "IE", "peru": "PE", "ecuador": "EC", "india": "IN", "egypt": "EG", "serbia": "RS", "paraguay": "PY",
    "ukraine": "UA", "saudi arabia": "SA", "israel": "IL", "venezuela": "VE", "cyprus": "CY", "bolivia": "BO", "qatar": "QA",
    "united arab emirates": "AE", "uruguay": "UY", "wales": "GB-WLS", "costa rica": "CR", "vietnam": "VN", "panama": "PA",
    "honduras": "HN", "guatemala": "GT", "new zealand": "NZ", "ghana": "GH", "morocco": "MA", "bosnia and herzegovina": "BA",
    "thailand": "TH", "cameroon": "CM", "tunisia": "TN", "algeria": "DZ", "senegal": "SN", "nigeria": "NG", "el salvador": "SV",
    "slovenia": "SI", "iran": "IR", "northern ireland": "GB-NIR", "iceland": "IS", "jamaica": "JM", "indonesia": "ID",
    "ivory coast": "CI", "uzbekistan": "UZ", "trinidad and tobago": "TT", "malaysia": "MY", "dr congo": "CD", "curacao": "CW",
    "haiti": "HT", "kenya": "KE", "cuba": "CU", "liechtenstein": "LI", "dominican republic": "DO", "jordan": "JO", "mali": "ML",
    "suriname": "SR", "kuwait": "KW", "iraq": "IQ",
}
"""The key of ``fbi.people.countries`` -> the ``pais_codigo`` of the directory v2 (its 95 countries; a test checks every code it uses)."""

_PARENS = re.compile(r"\([^)]*\)")
_SITEMAP = re.compile(r"https?://[^\s,;)«»\"']*(?:sitemap|outboundfeeds)[^\s,;)«»\"']*", re.IGNORECASE)


def folded(text: object) -> str:
    return alias_key(text)


DESCRIPTIVE: Final = frozenset({"real", "atletico", "athletic", "deportivo", "sporting", "united", "city", "sport", "sports", "racing",
                                 "olympique", "dynamo", "dinamo", "inter", "internacional", "union", "academica", "nacional"}) & CLUB_WORDS \
    | frozenset({"town", "county", "rovers", "wanderers", "albion", "borough", "hotspur"})
"""Common words that still tell two clubs of one city apart (Real Madrid / Atlético de Madrid, Manchester City / United): two names
with the same distinctive words are one club only when the descriptive words of one are among those of the other."""


def club_key(text: object) -> frozenset[str]:
    """The distinctive words of a club's name: no parenthesis, no common club words or particles (``Atlético Bucaramanga`` ->
    ``{bucaramanga}``, ``Independiente Medellín (DIM)`` -> ``{independiente, medellin}``)."""
    words = alias_key(_PARENS.sub(" ", str(text or ""))).split()
    return frozenset(w for w in words if w not in CLUB_WORDS and w not in PARTICLES and w not in DESCRIPTIVE)


def descriptive(text: object) -> frozenset[str]:
    return frozenset(w for w in alias_key(_PARENS.sub(" ", str(text or ""))).split() if w in DESCRIPTIVE)


def same_club(a: object, b: object) -> bool:
    """Whether two names are the same club: the same distinctive words (none empty), and descriptive words that do not contradict."""
    ka, kb = club_key(a), club_key(b)
    if not ka or ka != kb:
        return False
    da, db = descriptive(a), descriptive(b)
    return da <= db or db <= da


def country_code(text: object) -> str | None:
    key = country_key(text)
    return COUNTRY_CODES.get(key) if key else None


# ── the catalogue: the directory as the selector reads it ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class SourceInfo:
    source_id: str
    domain: str
    name: str
    source_type: str
    scope: str
    state: str
    country_code: str
    languages: tuple[str, ...]
    clubs: tuple[str, ...]
    """The names of ``clubes_cubiertos``, as the directory wrote them."""
    region: str
    competitions: str
    reliability: str
    rss_url: str | None
    sitemaps: tuple[str, ...]
    url: str
    group: str
    tier: str
    authority: Mapping[str, Mapping[str, str]]
    ai_reserved: bool

    @property
    def official(self) -> bool:
        return self.source_type == "oficial"

    @property
    def route(self) -> Via:
        """How it would be read if it may be: its feed, its sitemap, its own site (an official), or Exa restricted to its domain."""
        if self.rss_url:
            return "rss"
        if self.sitemaps:
            return "sitemap"
        return "official" if self.official else "exa"

    def level(self, claim_type: str) -> tuple[str, str | None]:
        entry = self.authority.get(claim_type) or {}
        level = str(entry.get("level") or "sin_autoridad")
        note = entry.get("note")
        return level, None if note is None else str(note)


def sitemaps_of(record: Mapping[str, Any]) -> tuple[str, ...]:
    """The sitemap addresses the directory wrote in its notes (it has no field for them): only http(s) addresses that say sitemap."""
    text = " ".join(str(record.get(k) or "") for k in ("integracion_nota", "notas", "robots_resumen"))
    seen: list[str] = []
    for m in _SITEMAP.findall(text):
        url = m.rstrip(".")
        if url not in seen:
            seen.append(url)
    return tuple(seen[:3])


def info_of(source: registry.Source) -> SourceInfo:
    r = source.record
    rss = str(r.get("rss_url") or "").strip()
    rss_ok = bool(rss) and (bool(r.get("rss_verificado")) or str(r.get("acceso") or "") == "RSS")
    langs = tuple(x.strip().lower() for x in str(r.get("idiomas") or "").replace(",", ";").split(";") if x.strip())
    clubs = tuple(c.strip() for c in str(r.get("clubes_cubiertos") or "").split(";") if club_key(c))
    return SourceInfo(source_id=source.source_id, domain=source.domain, name=source.name, source_type=source.source_type,
                      scope=str(r.get("ambito") or ""), state=source.state, country_code=str(r.get("pais_codigo") or ""),
                      languages=langs or ("es",), clubs=clubs, region=folded(r.get("region_ciudad")),
                      competitions=folded(f"{source.name} {r.get('competiciones_cubiertas') or ''} {r.get('especialidad') or ''}"),
                      reliability=str(r.get("fiabilidad") or "media"), rss_url=rss if rss_ok and rss.startswith("http") else None,
                      sitemaps=sitemaps_of(r), url=str(r.get("url_futbol") or r.get("url") or ""),
                      group=str(r.get("grupo_editorial") or ""), tier=registry.derived_tier(source), authority=source.authority,
                      ai_reserved=source.ai_reserved)


@dataclass(frozen=True, slots=True)
class Catalog:
    version: str
    sources: tuple[SourceInfo, ...]

    @classmethod
    def of(cls, version: str, sources: Iterable[registry.Source]) -> Catalog:
        return cls(version, tuple(info_of(s) for s in sources))

    def by_id(self) -> dict[str, SourceInfo]:
        return {s.source_id: s for s in self.sources}


_bundled: dict[str, Catalog] = {}


def bundled_catalog() -> Catalog:
    """The pinned directory of the image (the same data the loader loads), read once."""
    if "c" not in _bundled:
        d = registry.bundled_directory()
        _bundled["c"] = Catalog.of(d.version, d.sources)
    return _bundled["c"]


def catalog_for(conn: psycopg.Connection[Any] | None, policy: source_policy.SourcePolicy | None) -> Catalog:
    """The catalogue of the directory version the policy is in force with: the pinned file when it is that one (or the policy came from
    the image), else the records of that version in ``ai.source_registry``; the pinned file when they cannot be read."""
    bundled = bundled_catalog()
    version = None if policy is None else policy.directory_version
    if conn is None or version is None or version == bundled.version or version.startswith("bundled"):
        return bundled
    try:
        with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT record FROM ai.source_registry WHERE version = %s ORDER BY source_id", (version,))
            records = [dict(r[0]) for r in cur.fetchall()]
        if not records:
            return bundled
        return Catalog.of(version, (registry.source_of(r) for r in records))
    except (psycopg.Error, registry.RegistryError):
        return bundled


# ── the match ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Team:
    team_id: int | None
    name: str
    names: tuple[str, ...] = ()
    """Every name of the team the database knows (its own, short name, aliases), the first one shown."""
    country: str | None = None
    """The country as the provider writes it (``Colombia``, ``South-Korea``)."""
    city: str | None = None
    is_national: bool = False

    @property
    def keys(self) -> frozenset[frozenset[str]]:
        return frozenset(k for k in (club_key(n) for n in (self.name, *self.names)) if k)

    def is_club(self, name: str) -> bool:
        """Whether a name of the directory is this team (``same_club`` with any of its names)."""
        return any(same_club(n, name) for n in (self.name, *self.names))

    @property
    def code(self) -> str | None:
        return country_code(self.country)


@dataclass(frozen=True, slots=True)
class MatchContext:
    fixture_id: int | None
    kickoff_at: datetime
    competition: str
    competition_country: str | None
    home: Team
    away: Team

    @property
    def international(self) -> bool:
        return country_code(self.competition_country) is None

    @property
    def national_teams(self) -> bool:
        return self.home.is_national or self.away.is_national

    def team(self, side: Side) -> Team:
        return self.home if side == "home" else self.away


@dataclass(frozen=True, slots=True)
class Candidate:
    source: SourceInfo
    role: Role
    side: Side | None


def _professional(s: SourceInfo, competition: str) -> bool:
    comp = folded(competition)
    return not any(w in s.competitions and w not in comp for w in NOT_PROFESSIONAL)


WOMEN: Final = ("femenin", "women", "feminin", "frauen", "nwsl", "wsl")


def _same_game(s: SourceInfo, competition: str) -> bool:
    """A medium devoted to women's football is not a source of a men's match (and the other way round is left to the directory)."""
    comp = folded(competition)
    return not any(w in s.competitions for w in WOMEN) or any(w in comp for w in WOMEN)


def _city_words(team: Team, clubs: Sequence[SourceInfo]) -> frozenset[str]:
    """The city of a side, from the venue the provider gave and from the ``region_ciudad`` of its official site."""
    words: set[str] = set()
    for text in (team.city, *(c.region for c in clubs)):
        w = folded(_PARENS.sub(" ", str(text or "")))
        if w and len(w) >= 4:
            words.add(w)
    return frozenset(words)


def _names_city(region: str, cities: frozenset[str]) -> bool:
    padded = f" {region} "
    return any(f" {c} " in padded for c in cities)


def scope(catalog: Catalog, ctx: MatchContext) -> list[Candidate]:
    """Every source of the directory that has something to do with the match, with its role and side (claim type not yet applied)."""
    out: list[Candidate] = []
    taken: set[str] = set()

    def add(s: SourceInfo, role: Role, side: Side | None) -> None:
        if s.source_id not in taken:
            taken.add(s.source_id)
            out.append(Candidate(s, role, side))

    sides: tuple[Side, Side] = ("home", "away")
    clubs_of: dict[str, list[SourceInfo]] = {"home": [], "away": []}
    for side in sides:
        team = ctx.team(side)
        if team.is_national or team.code is None:
            continue
        for s in catalog.sources:
            if s.official and s.scope == "club" and s.country_code == team.code and any(team.is_club(c) for c in s.clubs):
                clubs_of[side].append(s)
                add(s, "club_oficial", side)
    comp_code = country_code(ctx.competition_country)
    comp = folded(ctx.competition)
    if comp_code is not None and not ctx.national_teams:
        leagues = [s for s in catalog.sources if s.official and s.scope == "nacional" and s.country_code == comp_code
                   and s.tier == "competition" and _professional(s, ctx.competition)]
        named = [s for s in leagues if comp and f" {comp} " in f" {s.competitions} "]
        leagues = named or leagues  # the league that names the competition, when one does (Serie A, not Serie B)
        for s in leagues:
            add(s, "liga", None)
        if not leagues:
            for s in catalog.sources:
                if s.official and s.scope == "nacional" and s.country_code == comp_code and s.tier == "official" \
                        and _professional(s, ctx.competition):
                    add(s, "federacion", None)
    if ctx.national_teams:
        for side in sides:
            team = ctx.team(side)
            for s in catalog.sources:
                if team.code and s.official and s.scope == "nacional" and s.country_code == team.code and s.tier == "official" \
                        and _professional(s, ctx.competition):
                    add(s, "federacion", side)
    by_id = catalog.by_id()
    padded = f" {comp} "
    for words, ids in CONFEDERATIONS:
        if any(f" {w.strip()} " in padded for w in words):
            for i in ids:
                if i in by_id:
                    add(by_id[i], "confederacion", None)
    countries: dict[str, Side | None] = {}
    for side in sides:
        code = ctx.team(side).code
        if code:
            countries[code] = None if code in countries else side
    if comp_code and comp_code not in countries and not ctx.international:
        countries[comp_code] = None
    for side in sides:
        team = ctx.team(side)
        if team.is_national or team.code is None:
            continue
        cities = _city_words(team, clubs_of[side])
        for s in catalog.sources:
            if s.source_type in MEDIA_TYPES and s.scope in ("regional", "local_ciudad") and s.country_code == team.code \
                    and _same_game(s, ctx.competition) and (
                    any(team.is_club(c) for c in s.clubs) or _names_city(s.region, cities)):
                add(s, "regional", side)
    for code, side_of in countries.items():
        for s in catalog.sources:
            if s.source_type in MEDIA_TYPES and s.scope == "nacional" and s.country_code == code and _same_game(s, ctx.competition):
                add(s, "nacional", side_of)
    for s in catalog.sources:
        if s.source_type == "datos" and (s.country_code in countries or s.scope == "internacional"):
            add(s, "datos", None)
    return out


# ── permission, route, priority ───────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ExaAllowance:
    """What Exa's envelope allows now (``fbi.ai.budget_v3.exa_budget``), with the selector's own cut at 95 % of the month."""

    allowed: bool
    spent_month: Decimal = Decimal(0)
    envelope: Decimal = Decimal(0)
    reason: str = "not_given"

    @classmethod
    def closed(cls, reason: str = "not_given") -> ExaAllowance:
        return cls(False, reason=reason)

    @classmethod
    def of(cls, allowed: bool, spent_month: Decimal, envelope: Decimal, reason: str = "ok") -> ExaAllowance:
        if envelope <= 0:
            return cls(False, spent_month, envelope, "no_envelope")
        if spent_month >= envelope * EXA_CUT:
            return cls(False, spent_month, envelope, "cut_at_95")
        return cls(allowed, spent_month, envelope, reason if not allowed else "ok")


def proximity(kickoff_at: datetime, at: datetime) -> float:
    hours = (kickoff_at - at).total_seconds() / 3600
    if hours < 0:
        return 0.05
    if hours <= 6:
        return 1.0
    if hours <= 36:
        return 0.7
    if hours <= 168:
        return 0.4
    return 0.1


def band(kickoff_at: datetime | None, at: datetime) -> str:
    """The tranche of the plan (AD-C03): ``le6h``, ``6_36h``, ``36h_7d``, ``none``."""
    if kickoff_at is None:
        return "none"
    hours = (kickoff_at - at).total_seconds() / 3600
    if hours < -3:
        return "none"
    return "le6h" if hours <= 6 else "6_36h" if hours <= 36 else "36h_7d" if hours <= 168 else "none"


BLOCKED_STATES: Final = frozenset({"bloqueada", "no_comprobada", "desconocida", "excluida"})
DATA_CLAIMS: Final = frozenset({"estadisticas", "resultados", "analisis", RUMOUR})
"""The claim types a statistics source (``tipo = datos``) is asked about; for a line-up or an injury it is not a source of the fact."""
STRICTER_READINGS: Final[dict[str, str]] = {
    "elcolombiano.com": "contradicción entre fuentes: el directorio v2 dice «sin reserva conocida» y el Doc 2 recoge que sus términos no "
                        "autorizan el uso por IA sin permiso previo; cuenta la lectura más estricta (ficha AD-C04)",
}
"""Domains whose sources disagree about an AI reservation: until it is resolved, the strictest reading counts - as reserved (link only,
never a model), whatever the directory says. Only the owner takes a domain off this list (a new version of the code)."""


def route(source: SourceInfo, standing: source_policy.Standing, exa: ExaAllowance) -> tuple[Via, Via, str]:
    """(the route today, the route it would have if signed, why)."""
    if standing.excluded:
        return "none", "none", f"excluded:{standing.rule_class}"
    if standing.state in BLOCKED_STATES:
        return "none", "none", f"state:{standing.state}"
    if standing.hard_reason or source.ai_reserved:
        return "link", "link", "ai_reserved"
    if source.domain in STRICTER_READINGS:
        return "link", "link", "stricter_reading"
    natural = source.route
    fetch = source_policy.can_fetch(standing)
    if fetch.allowed:
        if natural == "exa" and not exa.allowed:
            return "link", "exa", f"exa:{exa.reason}"
        return natural, natural, "authorised"
    return "link", natural, fetch.reason


@dataclass(frozen=True, slots=True)
class Pick:
    source_id: str
    domain: str
    name: str
    role: Role
    side: Side | None
    claim_type: str
    authority: str
    note: str | None
    as_fact: bool
    state: str
    signed: bool
    via: Via
    would_via: Via
    reason: str
    may_fetch: bool
    may_extract: bool
    store: str
    publish: str
    priority: float
    languages: tuple[str, ...]
    reliability: str
    feed: str | None

    def as_json(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "domain": self.domain, "name": self.name, "role": self.role, "side": self.side,
                "claim_type": self.claim_type, "authority": self.authority, "note": self.note, "as_fact": self.as_fact,
                "state": self.state, "signed": self.signed, "via": self.via, "would_via": self.would_via, "reason": self.reason,
                "may_fetch": self.may_fetch, "may_extract": self.may_extract, "store": self.store, "publish": self.publish,
                "priority": self.priority, "languages": list(self.languages), "reliability": self.reliability, "feed": self.feed}


@dataclass(frozen=True, slots=True)
class ExaQuery:
    query: str
    include_domains: tuple[str, ...]
    lang: str
    claim_type: str
    side: Side | None

    def as_json(self) -> dict[str, Any]:
        return {"query": self.query, "include_domains": list(self.include_domains), "lang": self.lang, "claim_type": self.claim_type,
                "side": self.side}


@dataclass(frozen=True, slots=True)
class Selection:
    version: str
    fixture_id: int | None
    claim_type: str
    at: datetime
    kickoff_at: datetime
    picks: tuple[Pick, ...]
    exa: tuple[ExaQuery, ...]
    exa_allowance: ExaAllowance
    registry_version: str
    catalog_version: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def counts(self) -> dict[str, Any]:
        by_via: dict[str, int] = {}
        would: dict[str, int] = {}
        for p in self.picks:
            by_via[p.via] = by_via.get(p.via, 0) + 1
            would[p.would_via] = would.get(p.would_via, 0) + 1
        return {"sources": len(self.picks), "readable_now": sum(1 for p in self.picks if p.via in READ_VIAS),
                "extractable_now": sum(1 for p in self.picks if p.may_extract),
                "readable_if_signed": sum(1 for p in self.picks if p.would_via in READ_VIAS),
                "confirma": sum(1 for p in self.picks if p.authority == "confirma" and p.as_fact),
                "by_via": dict(sorted(by_via.items())), "would_via": dict(sorted(would.items())), "exa_queries": len(self.exa)}

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "fixture_id": self.fixture_id, "claim_type": self.claim_type, "at": self.at.isoformat(),
                "kickoff_at": self.kickoff_at.isoformat(), "registry_version": self.registry_version,
                "catalog_version": self.catalog_version, "exa_allowance": {"allowed": self.exa_allowance.allowed,
                                                                           "reason": self.exa_allowance.reason},
                "counts": self.counts(), "picks": [p.as_json() for p in self.picks], "exa": [q.as_json() for q in self.exa],
                "notes": list(self.notes)}


READ_VIAS: Final = frozenset({"rss", "sitemap", "official", "exa"})


def claim_word(claim_type: str | None) -> str:
    """The directory's word for a claim type (``OUT`` and ``injury`` are ``lesiones``); a directory word is kept."""
    word = source_policy.CLAIM_TYPE_OF.get(claim_type or "", claim_type or "contexto")
    if word not in registry.CLAIM_TYPES:
        raise ValueError(f"unknown claim type {claim_type!r} (the directory's are {', '.join(registry.CLAIM_TYPES)})")
    return word


def _authority(c: Candidate, claim: str, entity_side: Side | None) -> tuple[str, str | None]:
    level, note = c.source.level(claim)
    own_only = note is not None and ("propio" in note or "propia" in note)
    if c.role == "club_oficial" and entity_side is not None and c.side is not None and c.side != entity_side and (
            own_only or level == "confirma"):
        return "sin_autoridad", "solo del propio club"
    if c.role == "federacion" and entity_side is not None and c.side is not None and c.side != entity_side:
        return "sin_autoridad", "de la otra selección"
    return level, note


def query_for(claim: str, team: Team, lang: str, player: str | None = None) -> str | None:
    words = TOPICS.get(claim, {})
    topic = words.get(lang) or words.get("en")
    if topic is None:
        return None
    subject = player or team.name
    return " ".join(f"{subject} {topic}".split())[:200]


def select(ctx: MatchContext, claim_type: str, *, at: datetime, policy: source_policy.SourcePolicy | None,
           catalog: Catalog | None = None, exa: ExaAllowance | None = None, entity_side: Side | None = None,
           player: str | None = None, market: str | None = None, entity_priority: float = 1.0, max_exa: int = MAX_EXA) -> Selection:
    """The sources with authority for ``claim_type`` in this match, in order of priority, with their route today. Without a policy
    (the registry cannot be read) every source is ``none``: closed on failure."""
    claim = claim_word(claim_type)
    catalog = catalog or bundled_catalog()
    exa = exa or ExaAllowance.closed()
    rumour = claim == RUMOUR
    prox = proximity(ctx.kickoff_at, at)
    relevant = MARKET_CLAIMS.get((market or "").lower())
    market_factor = 1.0 if relevant is None or claim in relevant else 0.8
    picks: list[Pick] = []
    for c in scope(catalog, ctx):
        if c.role == "datos" and claim not in DATA_CLAIMS:
            continue
        level, note = _authority(c, claim, entity_side)
        as_fact = level in FACT_LEVELS and not rumour
        if not rumour and not as_fact:
            continue
        if policy is None:
            standing = source_policy.Standing(c.source.domain, None, source_policy.UNKNOWN)
            via: Via = "none"
            would: Via = "none"
            why = "registry_unavailable"
        else:
            standing = policy.standing(c.source.domain)
            via, would, why = route(c.source, standing, exa)
        perm = VIA_WEIGHT.get(via, 0.6 if would in READ_VIAS else 0.3 if via == "link" else 0.0)
        score = (prox * max(0.0, min(entity_priority, 1.0)) * ROLE_WEIGHT[c.role] * AUTHORITY_WEIGHT.get(level, 0.2)
                 * RELIABILITY_WEIGHT.get(c.source.reliability, 0.7) * perm * market_factor)
        extract = policy is not None and source_policy.can_extract(standing).allowed and not c.source.ai_reserved
        picks.append(Pick(source_id=c.source.source_id, domain=c.source.domain, name=c.source.name, role=c.role, side=c.side,
                          claim_type=claim, authority=level, note=note, as_fact=as_fact, state=standing.state, signed=standing.signed,
                          via=via, would_via=would, reason=why, may_fetch=via in READ_VIAS and via != "exa",
                          may_extract=extract and via in READ_VIAS, store=source_policy.can_store(standing),
                          publish=source_policy.can_publish(standing, claim).level, priority=round(score, 4),
                          languages=c.source.languages, reliability=c.source.reliability,
                          feed=c.source.rss_url or (c.source.sitemaps[0] if c.source.sitemaps else None)))
    picks.sort(key=lambda p: (-p.priority, p.role != "club_oficial", p.source_id))
    queries: list[ExaQuery] = []
    notes: list[str] = []
    exa_picks = [p for p in picks if p.via == "exa" and p.as_fact]
    groups: dict[tuple[str, Side | None], list[Pick]] = {}
    for p in exa_picks:
        groups.setdefault((p.languages[0] if p.languages else "es", p.side), []).append(p)
    for (lang, side), group in sorted(groups.items(), key=lambda kv: -max(p.priority for p in kv[1])):
        if len(queries) >= max(0, max_exa):
            notes.append(f"exa_quota:{lang}:{side}")
            continue
        team = ctx.team(side or entity_side or "home")
        q = query_for(claim, team, lang, player)
        if q is None:
            notes.append(f"exa_no_topic:{claim}")
            continue
        queries.append(ExaQuery(q, tuple(sorted({p.domain for p in group}))[:10], lang, claim, side))
    if not exa.allowed and any(p.reason.startswith("exa:") for p in picks):
        notes.append(f"exa_closed:{exa.reason}")
    return Selection(VERSION, ctx.fixture_id, claim, at, ctx.kickoff_at, tuple(picks), tuple(queries), exa,
                     "unavailable" if policy is None else policy.version, catalog.version, tuple(notes))


# ── in Spanish, for the owner ─────────────────────────────────────────────────────────────────────────────────────────────────

ROLE_ES: Final[dict[str, str]] = {"club_oficial": "web oficial del club", "liga": "liga organizadora", "federacion": "federación",
                                  "confederacion": "confederación", "regional": "prensa regional", "nacional": "prensa nacional",
                                  "datos": "fuente de datos"}
VIA_ES: Final[dict[str, str]] = {"rss": "su RSS", "sitemap": "su sitemap", "official": "su web oficial",
                                 "exa": "Exa limitado a su dominio", "link": "solo enlace", "none": "nada"}


def explain(selection: Selection, ctx: MatchContext | None = None) -> list[str]:
    """One line per source: who, why it is here, its authority for this claim, what may be done with it today and what if signed."""
    lines = []
    for p in selection.picks:
        who = ROLE_ES[p.role]
        if p.side is not None and ctx is not None:
            who += f" ({ctx.team(p.side).name})"
        elif p.side is not None:
            who += f" ({'local' if p.side == 'home' else 'visitante'})"
        auth = p.authority + (f" ({p.note})" if p.note else "") + ("" if p.as_fact else ", solo como rumor")
        today = VIA_ES[p.via]
        tail = "" if p.via == p.would_via or p.would_via == "none" else f"; si lo firmas: {VIA_ES[p.would_via]} (habría leído)"
        lines.append(f"{p.domain} — {who}: {auth} en {p.claim_type}. Estado {p.state}; hoy: {today} [{p.reason}]{tail}. "
                     f"Prioridad {p.priority:.3f}.")
    for q in selection.exa:
        lines.append(f"Consulta de Exa (la escribe el servidor): «{q.query}» en {', '.join(q.include_domains)}.")
    if not selection.picks:
        lines.append(f"Ninguna fuente del directorio tiene autoridad para {selection.claim_type} en este partido.")
    return lines


# ── the match from the database (read only) ───────────────────────────────────────────────────────────────────────────────────

CONTEXT_SELECT: Final = """
SELECT f.id, f.kickoff_at, c.name AS competition, c.country AS competition_country,
       th.id AS home_id, th.name AS home_name, th.short_name AS home_short, th.country AS home_country, th.is_national AS home_national,
       coalesce(vh.city, CASE WHEN NOT coalesce(f.is_neutral, false) THEN f.venue_city END) AS home_city,
       ta.id AS away_id, ta.name AS away_name, ta.short_name AS away_short, ta.country AS away_country, ta.is_national AS away_national,
       va.city AS away_city
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN core.venues vh ON vh.id = th.venue_id LEFT JOIN core.venues va ON va.id = ta.venue_id
"""
CONTEXT_SQL: Final = CONTEXT_SELECT + " WHERE f.id = %s"
ALIASES_SQL: Final = ("SELECT entity_id, alias FROM core.entity_aliases_live WHERE entity_type = 'team' AND entity_id = ANY(%s) "
                      "ORDER BY entity_id, alias")
OLD_ALIASES_SQL: Final = "SELECT team_id, alias FROM core.team_aliases WHERE team_id = ANY(%s) ORDER BY team_id, alias"


def team_aliases(conn: psycopg.Connection[Any], team_ids: Sequence[int]) -> dict[int, list[str]]:
    """The names of the teams: the live aliases of AD-H02 when the database has them, the old table otherwise (each in a savepoint)."""
    out: dict[int, list[str]] = {}
    for sql in (ALIASES_SQL, OLD_ALIASES_SQL):
        try:
            with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
                cur.execute(sql, (list(team_ids),))
                for tid, alias in cur.fetchall():
                    out.setdefault(int(tid), []).append(str(alias))
            if out:
                return out
        except psycopg.Error:
            continue
    return out


def context_from_row(row: Mapping[str, Any], aliases: Mapping[int, Sequence[str]] | None = None) -> MatchContext:
    aliases = aliases or {}

    def team(prefix: str) -> Team:
        tid = row.get(f"{prefix}_id")
        names = [str(n) for n in (row.get(f"{prefix}_short"), *aliases.get(int(tid) if tid is not None else -1, ())) if n]
        return Team(None if tid is None else int(tid), str(row[f"{prefix}_name"]), tuple(dict.fromkeys(names)),
                    row.get(f"{prefix}_country"), row.get(f"{prefix}_city"), bool(row.get(f"{prefix}_national")))

    return MatchContext(None if row.get("id") is None else int(row["id"]), row["kickoff_at"], str(row.get("competition") or ""),
                        row.get("competition_country"), team("home"), team("away"))


def context_for(conn: psycopg.Connection[Any], fixture_id: int) -> MatchContext | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CONTEXT_SQL, (fixture_id,))
        row = cur.fetchone()
    if row is None:
        return None
    ids = [int(row["home_id"]), int(row["away_id"])]
    return context_from_row(row, team_aliases(conn, ids))


def select_sources(conn: psycopg.Connection[Any], fixture_id: int, claim_type: str, *, at: datetime,
                   policy: source_policy.SourcePolicy | None = None, catalog: Catalog | None = None, exa: ExaAllowance | None = None,
                   entity_side: Side | None = None, player: str | None = None, market: str | None = None,
                   entity_priority: float = 1.0) -> Selection | None:
    """``select`` for a match of the database. Reads only; None when there is no such match. The policy in force is loaded when none is
    given; Exa is closed unless the caller hands its allowance."""
    ctx = context_for(conn, fixture_id)
    if ctx is None:
        return None
    pol = policy if policy is not None else source_policy.load(conn)
    return select(ctx, claim_type, at=at, policy=pol, catalog=catalog or catalog_for(conn, pol), exa=exa, entity_side=entity_side,
                  player=player, market=market, entity_priority=entity_priority)


FACT_CLAIMS: Final = tuple(c for c in registry.CLAIM_TYPES if c != RUMOUR)


def summarize(contexts: Iterable[MatchContext], *, at: datetime, policy: source_policy.SourcePolicy | None, catalog: Catalog | None = None,
              exa: ExaAllowance | None = None, claims: Sequence[str] = FACT_CLAIMS) -> dict[str, Any]:
    """For a set of matches (the matches of a day, say): how many distinct sources the selector would choose for each one over the
    claim types given, how many it could read today with the permissions in force, how many if the owner signed them, and how many
    Exa queries it would propose. Pure; the measurement of IA-086."""
    catalog = catalog or bundled_catalog()
    per: list[dict[str, Any]] = []
    union_all: set[str] = set()
    readable_all: set[str] = set()
    signed_all: set[str] = set()
    for ctx in contexts:
        chosen: dict[str, Pick] = {}
        readable: set[str] = set()
        if_signed: set[str] = set()
        queries = 0
        for claim in claims:
            sel = select(ctx, claim, at=at, policy=policy, catalog=catalog, exa=exa)
            queries += len(sel.exa)
            for p in sel.picks:
                chosen.setdefault(p.source_id, p)
                if p.via in READ_VIAS:
                    readable.add(p.source_id)
                if p.would_via in READ_VIAS:
                    if_signed.add(p.source_id)
        roles: dict[str, int] = {}
        for p in chosen.values():
            roles[p.role] = roles.get(p.role, 0) + 1
        per.append({"fixture_id": ctx.fixture_id, "match": f"{ctx.home.name} - {ctx.away.name}", "competition": ctx.competition,
                    "sources": len(chosen), "readable_now": len(readable), "readable_if_signed": len(if_signed),
                    "reserved_or_none": sum(1 for p in chosen.values() if p.would_via in ("link", "none")),
                    "roles": dict(sorted(roles.items())), "exa_queries": queries})
        union_all |= set(chosen)
        readable_all |= readable
        signed_all |= if_signed
    n = len(per)
    return {"version": VERSION, "at": at.isoformat(), "matches": n, "claims": list(claims),
            "registry_version": "unavailable" if policy is None else policy.version, "catalog_version": catalog.version,
            "sources_per_match": {"mean": round(sum(p["sources"] for p in per) / n, 2) if n else 0.0,
                                  "min": min((p["sources"] for p in per), default=0), "max": max((p["sources"] for p in per), default=0)},
            "matches_with_no_source": sum(1 for p in per if p["sources"] == 0),
            "readable_now_per_match": round(sum(p["readable_now"] for p in per) / n, 2) if n else 0.0,
            "matches_with_a_readable_source": sum(1 for p in per if p["readable_now"] > 0),
            "distinct_sources": len(union_all), "distinct_readable_now": len(readable_all), "distinct_readable_if_signed": len(signed_all),
            "exa_queries": sum(p["exa_queries"] for p in per), "per_match": per}


__all__ = ["FACT_CLAIMS", "MAX_EXA", "VERSION", "Candidate", "Catalog", "ExaAllowance", "ExaQuery", "MatchContext", "Pick",
           "Selection", "SourceInfo", "Team", "band", "bundled_catalog", "catalog_for", "claim_word", "club_key", "context_for",
           "context_from_row", "country_code", "explain", "info_of", "proximity", "query_for", "route", "same_club", "scope", "select",
           "select_sources", "sitemaps_of", "summarize", "team_aliases"]
