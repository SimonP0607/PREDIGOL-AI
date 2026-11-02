"""Evidence: what is known about a match from outside the numbers, where it comes from, and how far
to trust it.

Every item keeps its source (name, URL when it is a web page, the RAW payload when it came from the
data provider), its dates (published, retrieved, the moment it applies to), the source's TIER and a
STATUS that the server - never a model - decides:

    CONFIRMED      an official source (federation, league, club) with a date; the confirmed line-up; or
                   two independent media outlets saying the same thing
    PROBABLE       one media outlet or journalist; the data provider's injury report
    RUMOR          an aggregator, a social post or an unknown site, alone
    CONTRADICTORY  sources of comparable standing disagree, and nothing newer settles it
    OUTDATED       superseded by something newer of equal or higher standing, no longer reported by the
                   provider, or too old for the match it is about

A model may extract items from a page and propose a reading; it cannot raise a status. Rumours stay
rumours: a review may mention one only as such (``fbi.ai.claims``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.contracts.mcp import source_class
from fbi.analyst.provenance import OFFICIAL_DOMAINS, REPUTABLE_DOMAINS

Status = Literal["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"]
Assertion = Literal["out", "doubtful", "available", "starts", "info"]
TIER_RANK: dict[str, int] = {"official": 0, "competition": 1, "club": 2, "provider": 3, "journalist": 4,
                             "media": 5, "aggregator": 6, "social": 7, "unknown": 8}
AVAILABILITY = frozenset({"injury", "suspension", "doubtful", "lineup"})
STALE_AFTER = timedelta(days=10)
"""A report about who plays, published this long before the match, is too old to stand on its own."""
CHECK_MARGIN = timedelta(hours=2)
SEEN_EVERY = timedelta(hours=1)

LEAGUES = frozenset({"premierleague.com", "efl.com", "laliga.com", "legaseriea.it", "bundesliga.com", "ligue1.com",
                     "dimayor.com.co", "ligamx.net", "mlssoccer.com", "ligaportugal.pt", "eredivisie.nl", "spfl.co.uk",
                     "superlig.org.tr", "ligaprofesional.ar", "brasileirao.cbf.com.br"})
FEDERATIONS = frozenset({"fifa.com", "uefa.com", "conmebol.com", "concacaf.com", "the-afc.com", "cafonline.com",
                         "thefa.com", "rfef.es", "figc.it", "dfb.de", "fff.fr", "fcf.com.co", "afa.com.ar", "cbf.com.br",
                         "fmf.mx", "ussoccer.com", "fpf.pt", "knvb.nl"})
AGGREGATORS = frozenset({"transfermarkt.com", "transfermarkt.es", "sofascore.com", "flashscore.com", "fotmob.com",
                         "whoscored.com", "besoccer.com", "soccerway.com", "footystats.org", "sportsgambler.com",
                         "rotowire.com", "fbref.com"})
SOCIAL = frozenset({"twitter.com", "x.com", "instagram.com", "facebook.com", "tiktok.com", "youtube.com", "threads.net",
                    "reddit.com", "t.me"})
MEDIA = frozenset({
    # Spanish-speaking (Colombia first: the owner's market), Spain, Mexico, Argentina, Chile, Peru, Ecuador, Uruguay
    "eltiempo.com", "elespectador.com", "semana.com", "futbolred.com", "antena2.com", "golcaracol.com",
    "noticiascaracol.com", "caracol.com.co", "rcnradio.com", "winsports.co", "bluradio.com", "pulzo.com", "as.com",
    "marca.com", "mundodeportivo.com", "sport.es", "relevo.com", "elpais.com", "elmundo.es", "abc.es",
    "estadiodeportivo.com", "eldesmarque.com", "record.com.mx", "mediotiempo.com", "espn.com.mx", "espn.com.co",
    "espn.com.ar", "tycsports.com", "ole.com.ar", "lanacion.com.ar", "clarin.com", "infobae.com", "latercera.com",
    "emol.com", "redgol.cl", "depor.com", "libero.pe", "elcomercio.pe", "eluniverso.com", "elcomercio.com",
    "ovacion.com.uy", "tenfield.com.uy",
    # Portuguese
    "ge.globo.com", "globoesporte.globo.com", "lance.com.br", "uol.com.br", "espn.com.br", "terra.com.br",
    "abola.pt", "record.pt", "ojogo.pt", "maisfutebol.iol.pt",
    # English and the rest of Europe
    "bbc.co.uk", "bbc.com", "skysports.com", "theguardian.com", "telegraph.co.uk", "independent.co.uk",
    "theathletic.com", "nytimes.com", "espn.com", "espn.co.uk", "goal.com", "football.london", "manchestereveningnews.co.uk",
    "liverpoolecho.co.uk", "standard.co.uk", "mirror.co.uk", "dailymail.co.uk", "thesun.co.uk", "talksport.com",
    "90min.com", "reuters.com", "apnews.com", "kicker.de", "sport1.de", "bild.de", "transfermarkt.de",
    "gazzetta.it", "corrieredellosport.it", "tuttosport.com", "football-italia.net", "lequipe.fr", "footmercato.net",
    "rmcsport.bfmtv.com", "voetbalinternational.nl", "nos.nl", "fanatik.com.tr", "fotomac.com.tr",
    "mlssoccer.com", "cbssports.com", "foxsports.com", "si.com", "theathletic.co.uk",
})
JOURNALISTS = frozenset({"fabrizioromano.com"})

SOURCES_V2: dict[str, str] = {
    # PrediGol Intelligence, sources-v2 (13 Oct 2026): what the web search actually returned in its first week, and
    # the press the owner named, classified. Official first; media by country; betting-tips, streaming and
    # fan sites as aggregators (an item from one of them alone stays a RUMOR).
    # competitions and federations
    "allsvenskan.se": "competition", "eliteserien.no": "competition", "superliga.dk": "competition",
    "proleague.be": "competition", "sfl.ch": "competition", "bundesliga.at": "competition",
    "ekstraklasa.org": "competition", "chanceliga.cz": "competition", "slgr.gr": "competition",
    "premierliga.ru": "competition", "upl.ua": "competition", "hnl.hr": "competition", "superliga.rs": "competition",
    "leagueofireland.ie": "competition", "jleague.jp": "competition", "kleague.com": "competition",
    "aleagues.com.au": "competition", "spl.com.sa": "competition", "uslchampionship.com": "competition",
    "ligapro.ec": "competition", "liga1.pe": "competition", "campeonatochileno.cl": "competition",
    "ligafutve.org": "competition", "unafut.com": "competition", "csl-china.com": "competition",
    "tff.org": "official", "auf.org.uy": "official", "apf.org.py": "official", "fbf.com.bo": "official",
    "anfp.cl": "official", "fef.ec": "official", "fpf.org.pe": "official",
    # clubs that came up
    "eintracht.com": "club",
    # media named by the owner and the national press of the covered leagues
    "directvsports.com": "media", "noticiasrcn.com": "media", "canalrcn.com": "media", "espndeportes.com": "media",
    "eltiempo.com.co": "media", "elcolombiano.com": "media", "eluniversal.com.mx": "media",
    "abc.com.py": "media", "ultimahora.com": "media", "opinion.com.bo": "media", "meridiano.net": "media",
    "nacion.com": "media", "lagaceta.com.ar": "media", "elcomercio.es": "media", "lavanguardia.com": "media",
    "elperiodico.com": "media", "eurosport.com": "media", "eurosport.es": "media", "fourfourtwo.com": "media",
    "football365.com": "media", "sportsmole.co.uk": "media", "dailyrecord.co.uk": "media", "sport.fr": "media",
    "ouest-france.fr": "media", "lemonde.fr": "media", "sportbild.de": "media", "welt.de": "media",
    "faz.net": "media", "spiegel.de": "media", "tag24.de": "media", "laola1.at": "media", "blick.ch": "media",
    "ad.nl": "media", "telegraaf.nl": "media", "vi.nl": "media", "hln.be": "media", "nieuwsblad.be": "media",
    "sporza.be": "media", "bold.dk": "media", "tipsbladet.dk": "media", "bt.dk": "media", "ekstrabladet.dk": "media",
    "expressen.se": "media", "aftonbladet.se": "media", "fotbollskanalen.se": "media", "vg.no": "media",
    "dagbladet.no": "media", "nettavisen.no": "media", "sport.pl": "media", "przegladsportowy.onet.pl": "media",
    "isport.blesk.cz": "media", "sport24.gr": "media", "gazzetta.gr": "media", "sporx.com": "media",
    "sport-express.ru": "media", "championat.com": "media", "sportnet.hr": "media", "sapo.pt": "media",
    "diadejogo.pt": "media", "interfootball.co.kr": "media", "nikkansports.com": "media", "sponichi.co.jp": "media",
    "arriyadiyah.com": "media", "filgoal.com": "media", "supersport.com": "media", "foxsports.com.au": "media",
    # aggregators: statistics sites, betting tips, streaming and fan pages
    "squawka.com": "aggregator", "365scores.com": "aggregator", "kooora.com": "aggregator",
    "dongqiudi.com": "aggregator", "zhibo8.cc": "aggregator", "news.zhibo8.com": "aggregator",
    "163.com": "aggregator", "tuttomercatoweb.com": "aggregator", "calciomercato.com": "aggregator",
    "foot01.com": "aggregator", "meczyki.pl": "aggregator", "mozzartsport.com": "aggregator",
    "mediapronos.com": "aggregator", "90fut.com": "aggregator", "thefalse9.com": "aggregator",
    "injuriesandsuspensions.com": "aggregator", "lineupstoday.com": "aggregator", "5maseldescuento.es": "aggregator",
    "betsgo-global.com": "aggregator", "jarayid.com": "aggregator", "oddspedia.com": "aggregator",
    "forebet.com": "aggregator", "predictz.com": "aggregator", "windrawwin.com": "aggregator",
    "soccerpunter.com": "aggregator", "africasoccer.com": "aggregator", "tuttoatalanta.com": "aggregator",
    "leccezionale.it": "aggregator", "bollsvenskan.se": "aggregator", "campo.dk": "aggregator",
    "zhongchao.yoozhibo.tv": "aggregator", "925zhibo-xueqiu.com": "aggregator", "nbazhibo-ifeng.com": "aggregator",
    "baoyuncnc.com": "aggregator", "ahradio.com.cn": "aggregator",
}


def seed_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [("api-football.com", "provider")]
    rows += [(d, "official") for d in sorted(FEDERATIONS)]
    rows += [(d, "competition") for d in sorted(LEAGUES)]
    rows += [(d, "club") for d in sorted(OFFICIAL_DOMAINS - LEAGUES - FEDERATIONS)]
    rows += [(d, "journalist") for d in sorted(JOURNALISTS)]
    rows += [(d, "media") for d in sorted((REPUTABLE_DOMAINS | MEDIA) - LEAGUES - FEDERATIONS - OFFICIAL_DOMAINS)]
    rows += [(d, "aggregator") for d in sorted(AGGREGATORS)]
    rows += [(d, "social") for d in sorted(SOCIAL)]
    seeded = {d for d, _ in rows}
    rows += [(d, t) for d, t in sorted(SOURCES_V2.items()) if d not in seeded]
    return rows


def seed_sources(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """The starting registry (idempotent); the owner adds or re-tiers domains, a run never does."""
    with conn.cursor(row_factory=tuple_row) as cur:
        n = 0
        for domain, tier in seed_rows():
            cur.execute("INSERT INTO ai.sources (domain, tier, added_by, added_at) VALUES (%s, %s, 'seed', %s) "
                        "ON CONFLICT (domain) DO NOTHING", (domain, tier, at))
            n += max(cur.rowcount, 0)
    return n


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.") or None


def tier_of(conn: psycopg.Connection[Any], domain: str | None) -> str:
    if not domain:
        return "unknown"
    parts = domain.split(".")
    candidates = [".".join(parts[i:]) for i in range(len(parts) - 1)]
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT domain, tier FROM ai.sources WHERE domain = ANY(%s)", (candidates,))
        found: dict[str, str] = {str(d): str(t) for d, t in cur.fetchall()}
    for c in candidates:  # the most specific registered domain wins
        if c in found:
            return str(found[c])
    return "unknown"


def outlets_of(conn: psycopg.Connection[Any], hosts: Iterable[str | None]) -> dict[str, str]:
    """For each host, WHO publishes it: the registered domain that vouches for it (the most specific one, the one ``tier_of`` reads its tier
    from), or the host itself when none does. ``marca.com`` and ``amp.marca.com`` are one outlet, and so are two blogs under a registered
    media suffix: what the registry accepts as «a media outlet» is the registered domain, not every address under it."""
    suffixes: dict[str, list[str]] = {}
    for host in {h for h in hosts if h}:
        parts = host.split(".")
        suffixes[host] = [".".join(parts[i:]) for i in range(len(parts) - 1)]
    wanted = sorted({s for ss in suffixes.values() for s in ss})
    registered: set[str] = set()
    if wanted:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT domain FROM ai.sources WHERE domain = ANY(%s)", (wanted,))
            registered = {str(d) for (d,) in cur.fetchall()}
    return {host: next((s for s in ss if s in registered), host) for host, ss in suffixes.items()}


def normalize_name(name: str | None) -> str:
    import unicodedata

    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@dataclass
class EvidenceIn:
    fixture_id: int | None
    team_id: int | None
    kind: str
    claim: str
    origin: Literal["provider", "web", "owner"]
    source_name: str
    retrieved_at: datetime
    story_key: str
    assertion: Assertion = "info"
    provider_player_id: int | None = None
    source_url: str | None = None
    source_tier: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    event_at: datetime | None = None
    payload_hash: str | None = None
    confidence: float = 0.5
    relevance: float = 0.5
    attributes: dict[str, Any] = field(default_factory=dict)
    claim_type: str | None = None
    subject_type: str | None = None
    subject_id: int | None = None
    fresh_until: datetime | None = None
    """Research v2 (migration 0114): what kind of claim it is and about whom (the words of ``claim-v1``), and until when it can be reused
    without asking again. All four stay ``None`` for what v1 writes, and then the row is exactly the row v1 always wrote."""

    @property
    def typed(self) -> bool:
        return any(v is not None for v in (self.claim_type, self.subject_type, self.subject_id, self.fresh_until))

    def content_hash(self) -> str:
        body: dict[str, Any] = {"claim": " ".join(self.claim.split()), "url": self.source_url, "source": self.source_name,
                "assertion": self.assertion, "published_at": None if self.published_at is None
                else self.published_at.isoformat(), "attributes": self.attributes}
        if self.typed:  # the hash of an untyped item is what it always was; a typed claim says more, so it is another piece of content
            body["typed"] = [self.claim_type, self.subject_type, self.subject_id]
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def store(conn: psycopg.Connection[Any], item: EvidenceIn, *, at: datetime) -> tuple[int, bool]:
    """(id, created). An identical item (same story, same content) is stored once."""
    domain = domain_of(item.source_url)
    tier = item.source_tier or tier_of(conn, domain)
    attributes = dict(item.attributes) | {"assertion": item.assertion}
    published = item.published_at if item.published_at is None or item.published_at <= item.retrieved_at else None
    initial: Status = "PROBABLE" if TIER_RANK.get(tier, 8) <= TIER_RANK["media"] else "RUMOR"
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "INSERT INTO ai.evidence (fixture_id, team_id, provider_player_id, kind, claim, origin, source_name, source_url, "
            "source_domain, source_tier, author, published_at, retrieved_at, event_at, story_key, content_hash, "
            "payload_hash, confidence, relevance, attributes, status, status_reason, status_changed_at, "
            "claim_type, subject_type, subject_id, source_class, fresh_until) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (story_key, content_hash) DO NOTHING RETURNING id",
            (item.fixture_id, item.team_id, item.provider_player_id, item.kind, item.claim[:600], item.origin,
             item.source_name[:200], item.source_url, domain, tier, item.author, published, item.retrieved_at,
             item.event_at, item.story_key, item.content_hash(), item.payload_hash, round(item.confidence, 3),
             round(item.relevance, 3), Jsonb(attributes), initial, "not yet classified", at,
             item.claim_type, item.subject_type, item.subject_id, source_class(tier, domain) if item.typed else None, item.fresh_until))
        row = cur.fetchone()
        if row is not None:
            return int(row[0]), True
        cur.execute("SELECT id FROM ai.evidence WHERE story_key = %s AND content_hash = %s",
                    (item.story_key, item.content_hash()))
        found = cur.fetchone()
        assert found is not None
        # seen again: counted, never stored twice (at most once an hour, so a re-read report is not a write storm)
        cur.execute("UPDATE ai.evidence SET last_seen_at = %s, seen_count = seen_count + 1 WHERE id = %s "
                    "AND (last_seen_at IS NULL OR last_seen_at < %s)", (at, found[0], at - SEEN_EVERY))
    return int(found[0]), False


# ── classification ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Row:
    id: int
    fixture_id: int | None
    team_id: int | None
    player_id: int | None
    player_name: str
    kind: str
    origin: str
    tier: str
    domain: str | None
    assertion: str
    published_at: datetime | None
    retrieved_at: datetime
    story_key: str
    status: str
    attributes: dict[str, Any]
    typed: bool = False
    """Research v2 wrote it: it says what kind of claim it is and about whom (``ai.evidence.subject_type`` is not NULL)."""
    outlet: str | None = None
    """Who published it, for the claims of research v2: the registered domain that vouches for the host (``outlets_of``), so that
    ``marca.com`` and ``amp.marca.com`` are one outlet. None for what v1 wrote - and then the host is the outlet, as it always was."""

    @property
    def flagged(self) -> bool:
        """The page it came from read like an order to a model (``fbi.ai.untrusted``): whatever it says, it says with the standing of a
        source nobody classified. Research v2 marks the claims of such a page (``attributes.instruction_like``); v1 never does."""
        return bool(self.attributes.get("instruction_like"))

    @property
    def effective_tier(self) -> str:
        return "unknown" if self.flagged else self.tier

    @property
    def rank(self) -> int:
        return TIER_RANK.get(self.effective_tier, 8)

    @property
    def when(self) -> datetime:
        return self.published_at or self.retrieved_at

    @property
    def subject(self) -> tuple[Any, ...]:
        """Who the item is about: the same player (by provider id, else by name) of the same team in the
        same match."""
        who = self.player_id if self.player_id is not None else self.player_name or None
        return self.fixture_id, self.team_id, who

    @property
    def person(self) -> tuple[Any, ...]:
        """Who the item is about, whatever match it is tied to: the same player of the same team. Research v2 decides by person: a claim
        that says «he is out» without a match and one that says «he is available» for this match are about the same man."""
        return self.subject[1:]


@dataclass(frozen=True)
class Lineup:
    """A confirmed line-up the provider gave for a team, in any match: who started, and when the server knew it."""

    team_id: int
    starters: frozenset[int]
    known_at: datetime


NEGATIVE = frozenset({"out", "doubtful"})
POSITIVE = frozenset({"available", "starts"})


def _base_status(rows: list[Row]) -> tuple[Status, str]:
    """The status a group of items about one story can support, from its sources alone."""
    best = min(rows, key=lambda r: r.rank)
    dated_official = [r for r in rows if r.rank <= TIER_RANK["club"] and r.published_at is not None]
    media_domains = {r.outlet or r.domain for r in rows if r.effective_tier in ("media", "journalist") and (r.outlet or r.domain)}
    if any(r.kind == "lineup" and r.origin == "provider" for r in rows):
        return "CONFIRMED", "the confirmed line-up"
    if dated_official:
        return "CONFIRMED", f"an official source ({dated_official[0].effective_tier}) with a date"
    if len(media_domains) >= 2:
        return "CONFIRMED", f"{len(media_domains)} independent media outlets"
    if best.effective_tier == "provider":
        return "PROBABLE", "the data provider's report"
    if best.rank <= TIER_RANK["media"]:
        return "PROBABLE", f"one {best.effective_tier} source"
    if any(r.flagged for r in rows):
        return "RUMOR", "only sources nobody classified (a page that reads like an order to a model counts as one)"
    return "RUMOR", f"only {best.tier} sources"


def _too_old(r: Row, kickoff: datetime | None) -> bool:
    """A report about who plays, from the web, published more than ``STALE_AFTER`` before the match: it does not stand on its own."""
    return kickoff is not None and r.kind in AVAILABILITY and r.origin == "web" and kickoff - r.when > STALE_AFTER


def classify(rows: list[Row], *, kickoff: datetime | None, at: datetime, lineup_starters: dict[int, set[int]],
             absences_checked_at: datetime | None, across_scopes: bool = False, lineups: Sequence[Lineup] = ()) -> dict[int, tuple[Status, str]]:
    """The status of every item, decided together (a newer item can outdate an older one, two items can
    contradict each other). ``lineup_starters``: team id -> provider ids of the confirmed starters.

    ``across_scopes`` and ``lineups`` are research v2's (``refresh_typed_statuses``); left alone, the rules are the ones v1 always had.
    ``across_scopes``: the same player of the same team is one subject whatever match his items are tied to, because a claim that belongs to
    no match («he is out») and one for this match («he is available») are about the same man. ``lineups``: the confirmed line-ups of the
    teams in any match; a claim that belongs to no match and says a player is out is disproved by a line-up that came after it with him
    in the eleven - and stays disproved, whichever match is being prepared."""
    out: dict[int, tuple[Status, str]] = {}
    # the claims of a page that read like an order to a model are a story of their own: they neither lift nor are lifted by the honest
    # sources of the same story (``flagged`` is never true for what v1 wrote, so for v1 the groups are the stories, as always)
    by_story: dict[tuple[str, bool], list[Row]] = defaultdict(list)
    for r in rows:
        by_story[(r.story_key, r.flagged)].append(r)
    for story in by_story.values():
        # a story of research v2 spans weeks: a report that is too old to count is outdated below, and it does not corroborate the others
        live = [r for r in story if not (r.typed and _too_old(r, kickoff))] or story
        status, reason = _base_status(live)
        for r in story:
            out[r.id] = (status, reason)
    # the same subject, different stories: newer and stronger outdates; comparable and opposite contradicts
    by_subject: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
    for r in rows:
        who = r.person if across_scopes else r.subject
        if r.kind in AVAILABILITY and who[-1] is not None:
            by_subject[who].append(r)
    for items in by_subject.values():
        items.sort(key=lambda r: (r.when, -r.rank))
        for i, older in enumerate(items):
            for newer in items[i + 1:]:
                if newer.story_key == older.story_key:
                    continue
                opposite = (older.assertion in NEGATIVE) != (newer.assertion in NEGATIVE) and \
                    (older.assertion in NEGATIVE | POSITIVE) and (newer.assertion in NEGATIVE | POSITIVE)
                if newer.rank <= older.rank and newer.when > older.when:
                    out[older.id] = ("OUTDATED", f"superseded by evidence {newer.id} ({newer.tier}, newer)")
                elif opposite and abs(newer.rank - older.rank) <= 1 and out[older.id][0] != "OUTDATED":
                    out[older.id] = ("CONTRADICTORY", f"contradicted by evidence {newer.id}")
                    out[newer.id] = ("CONTRADICTORY", f"contradicted by evidence {older.id}")
    for r in rows:
        status, _ = out[r.id]
        if status == "OUTDATED":
            continue
        # a confirmed starter is not absent, whatever an earlier report said
        starters = lineup_starters.get(r.team_id or -1, set())
        if r.kind in ("injury", "suspension", "doubtful") and r.player_id is not None and r.player_id in starters:
            out[r.id] = ("OUTDATED", "the player is in the confirmed starting line-up")
            continue
        if r.typed and r.fixture_id is None and r.assertion in NEGATIVE and r.kind in ("injury", "suspension", "doubtful") \
                and r.player_id is not None and any(x.team_id == r.team_id and r.player_id in x.starters and x.known_at >= r.retrieved_at
                                                    for x in lineups):
            # what a team's claim says about a player was disproved by a later eleven of that team (any match): it does not come back
            # for the next match just because that match has no line-up yet
            out[r.id] = ("OUTDATED", "the player started in a later confirmed line-up of the team")
            continue
        if r.kind in ("injury", "suspension") and r.player_id is not None and starters and r.player_id not in starters \
                and r.assertion == "out" and not (r.typed and r.rank > TIER_RANK["media"]):
            # the absence from the eleven is confirmed by the provider; what a rumour says about WHY is not (research v2: a rumour never
            # reaches CONFIRMED - the claims v1 wrote keep the rule they always had)
            out[r.id] = ("CONFIRMED", "absent from the confirmed starting line-up")
            continue
        if r.origin == "provider" and r.kind in ("injury", "suspension", "doubtful") and absences_checked_at is not None \
                and r.retrieved_at < absences_checked_at - CHECK_MARGIN:
            out[r.id] = ("OUTDATED", "no longer in the provider's latest injury report")
            continue
        if _too_old(r, kickoff):
            out[r.id] = ("OUTDATED", "published more than ten days before the match")
    return out


LOAD_SQL = """
SELECT e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.origin, e.source_tier, e.source_domain,
       e.published_at, e.retrieved_at, e.story_key, e.status, e.status_reason, e.attributes, e.subject_type
  FROM ai.evidence e WHERE e.fixture_id = %(fixture)s AND e.subject_type IS NULL AND e.retrieved_at <= %(at)s
"""
"""What v1 decides: the items of a match that nobody typed - the provider's reports and what the web collector of v1 wrote. The claims of
research v2 (``subject_type`` is not NULL) are decided apart (``TYPED_SQL``): while research v2 runs beside v1, nothing it writes can move a
status of v1."""

TYPED_SQL = """
SELECT e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.origin, e.source_tier, e.source_domain,
       e.published_at, e.retrieved_at, e.story_key, e.status, e.status_reason, e.attributes, e.subject_type
  FROM ai.evidence e
 WHERE e.subject_type IS NOT NULL AND e.retrieved_at <= %(at)s AND e.retrieved_at > %(since)s
   AND (e.fixture_id = %(fixture)s OR (e.fixture_id IS NULL AND e.team_id = ANY(%(teams)s)))
"""
CONTEXT_SQL = """
SELECT e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.origin, e.source_tier, e.source_domain,
       e.published_at, e.retrieved_at, e.story_key, e.status, e.status_reason, e.attributes, e.subject_type
  FROM ai.evidence e
 WHERE e.fixture_id = %(fixture)s AND e.subject_type IS NULL AND e.status <> 'OUTDATED' AND e.retrieved_at <= %(at)s
   AND e.kind IN ('injury', 'suspension', 'doubtful', 'lineup')
"""
"""What v1 and the provider say about who plays in the match, read — and only read — when the claims of research v2 are decided: a newer
report of the provider settles an older claim of the web, as it does among the items of v1. Nothing here is ever written."""
TEAM_LINEUPS_SQL = """
SELECT CASE l.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END AS team_id, l.fetched_at,
       COALESCE(array_agg(lp.provider_player_id) FILTER (WHERE lp.is_starter), '{}') AS starters
  FROM core.fixture_lineups l JOIN core.fixtures f ON f.id = l.fixture_id
  LEFT JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side AND lp.source = l.source
 WHERE (f.home_team_id = ANY(%(teams)s) OR f.away_team_id = ANY(%(teams)s)) AND l.fetched_at <= %(at)s AND l.fetched_at > %(since)s
 GROUP BY l.fixture_id, l.team_side, l.source, l.fetched_at, f.home_team_id, f.away_team_id
"""
"""The confirmed line-ups of the teams in ANY of their matches of the last ``TYPED_WINDOW``: a man who started in one of them is not absent
for what a claim said before it, whichever match is being prepared now."""
TYPED_WINDOW = timedelta(days=21)
"""How far back the statuses of what research v2 knows about a team are re-decided: more than ``STALE_AFTER`` and some, so that a report
that has become too old is marked so before it stops being looked at. The packet does not show a typed claim older than ``STALE_AFTER``."""


def _decide(conn: psycopg.Connection[Any], raw: list[dict[str, Any]], *, at: datetime, kickoff: datetime | None,
            lineup_starters: dict[int, set[int]], absences_checked_at: datetime | None, across_scopes: bool = False,
            lineups: Sequence[Lineup] = (), read_only: Collection[int] = ()) -> dict[str, int]:
    """Decide the status of every row together and write only the statuses that changed (the trigger keeps the history). ``read_only``: rows
    that take part in the decision but are never written (what v1 and the provider say, when the claims of research v2 are decided)."""
    typed_hosts = [r["source_domain"] for r in raw if r.get("subject_type") is not None]
    outlets = outlets_of(conn, typed_hosts) if typed_hosts else {}
    rows = [Row(int(r["id"]), r["fixture_id"], r["team_id"], r["provider_player_id"],
                normalize_name((r["attributes"] or {}).get("player_name")), r["kind"], r["origin"], r["source_tier"],
                r["source_domain"], str((r["attributes"] or {}).get("assertion") or "info"), r["published_at"],
                r["retrieved_at"], r["story_key"], r["status"], r["attributes"] or {},
                typed=r.get("subject_type") is not None,
                outlet=outlets.get(r["source_domain"]) if r.get("subject_type") is not None and r["source_domain"] else None) for r in raw]
    decided = classify(rows, kickoff=kickoff, at=at, lineup_starters=lineup_starters,
                       absences_checked_at=absences_checked_at, across_scopes=across_scopes, lineups=lineups)
    skip = set(read_only)
    counts: dict[str, int] = defaultdict(int)
    current = {int(r["id"]): (r["status"], r["status_reason"]) for r in raw}
    with conn.cursor(row_factory=tuple_row) as cur:
        for eid, (status, reason) in decided.items():
            if eid in skip:
                continue
            counts[status] += 1
            if current[eid] != (status, reason):
                cur.execute("UPDATE ai.evidence SET status = %s, status_reason = %s, status_changed_at = %s "
                            "WHERE id = %s", (status, reason, at, eid))
    return dict(counts)


def refresh_statuses(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, kickoff: datetime | None,
                     lineup_starters: dict[int, set[int]], absences_checked_at: datetime | None) -> dict[str, int]:
    """Re-decide every item of a match; write only the statuses that changed (the trigger keeps the
    history). Returns the count per status."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LOAD_SQL, {"fixture": fixture_id, "at": at})
        raw = [dict(r) for r in cur.fetchall()]
    return _decide(conn, raw, at=at, kickoff=kickoff, lineup_starters=lineup_starters, absences_checked_at=absences_checked_at)


def refresh_typed_statuses(conn: psycopg.Connection[Any], fixture_id: int, team_ids: Sequence[int], *, at: datetime, kickoff: datetime | None,
                           lineup_starters: dict[int, set[int]]) -> dict[str, int]:
    """Re-decide what research v2 knows for a match: its claims typed by subject - the ones about the match itself (``fixture_id``) and the
    ones about its teams and their players that belong to no match (``fixture_id`` NULL: what is known of a team whatever match asks) - of the
    last ``TYPED_WINDOW``. The rules are the ones of a match: the same story in two independent outlets is CONFIRMED, a rumour alone stays a
    rumour, opposite claims of comparable sources contradict each other unless a newer, stronger one settles it, a report too old for the match
    is outdated, a player in the confirmed eleven is not absent - read at the kick-off and the line-ups of the match that is being prepared.

    Three things are particular to research v2 (the independent review of 27 Oct 2026):

    * the same player of the same team is ONE subject whatever match his claims are tied to (the model's ``applies_to`` decides what a claim
      is tied to, never whether the rules of contradiction apply to it), and what v1 and the provider say about the match is read beside them,
      so a newer report of the provider settles an older claim of the web as it does among the items of v1 (those rows are read, never written:
      while research v2 runs beside v1, nothing it does moves a status of v1);
    * a claim that belongs to no match and says a player is out is disproved by any confirmed line-up of his team, in any match, that came
      after it with him in the eleven - so it does not come back for the next match;
    * outlets are counted by the registered domain that vouches for them, and a report too old to count does not corroborate a current one.

    The statuses it writes are the claims'. Returns the count per status of those."""
    team_list = list(team_ids)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TYPED_SQL, {"fixture": fixture_id, "teams": team_list, "at": at, "since": at - TYPED_WINDOW})
        raw = [dict(r) for r in cur.fetchall()]
        if not raw:
            return {}
        cur.execute(CONTEXT_SQL, {"fixture": fixture_id, "at": at})
        context = [dict(r) for r in cur.fetchall()]
        cur.execute(TEAM_LINEUPS_SQL, {"teams": team_list, "at": at, "since": at - TYPED_WINDOW})
        lineups = [Lineup(int(x["team_id"]), frozenset(int(p) for p in (x["starters"] or []) if p is not None), x["fetched_at"])
                   for x in cur.fetchall() if int(x["team_id"]) in set(team_list)]
    return _decide(conn, raw + context, at=at, kickoff=kickoff, lineup_starters=lineup_starters, absences_checked_at=None, across_scopes=True,
                   lineups=lineups, read_only=[int(r["id"]) for r in context])
