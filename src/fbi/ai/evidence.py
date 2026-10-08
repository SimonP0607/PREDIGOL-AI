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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.analyst.provenance import OFFICIAL_DOMAINS, REPUTABLE_DOMAINS

Status = Literal["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"]
Assertion = Literal["out", "doubtful", "available", "starts", "info"]
TIER_RANK: dict[str, int] = {"official": 0, "competition": 1, "club": 2, "provider": 3, "journalist": 4,
                             "media": 5, "aggregator": 6, "social": 7, "unknown": 8}
AVAILABILITY = frozenset({"injury", "suspension", "doubtful", "lineup"})
STALE_AFTER = timedelta(days=10)
"""A report about who plays, published this long before the match, is too old to stand on its own."""
CHECK_MARGIN = timedelta(hours=2)

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


def seed_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [("api-football.com", "provider")]
    rows += [(d, "official") for d in sorted(FEDERATIONS)]
    rows += [(d, "competition") for d in sorted(LEAGUES)]
    rows += [(d, "club") for d in sorted(OFFICIAL_DOMAINS - LEAGUES - FEDERATIONS)]
    rows += [(d, "media") for d in sorted(REPUTABLE_DOMAINS)]
    rows += [(d, "aggregator") for d in sorted(AGGREGATORS)]
    rows += [(d, "social") for d in sorted(SOCIAL)]
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

    def content_hash(self) -> str:
        body = {"claim": " ".join(self.claim.split()), "url": self.source_url, "source": self.source_name,
                "assertion": self.assertion, "published_at": None if self.published_at is None
                else self.published_at.isoformat(), "attributes": self.attributes}
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
            "payload_hash, confidence, relevance, attributes, status, status_reason, status_changed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (story_key, content_hash) DO NOTHING RETURNING id",
            (item.fixture_id, item.team_id, item.provider_player_id, item.kind, item.claim[:600], item.origin,
             item.source_name[:200], item.source_url, domain, tier, item.author, published, item.retrieved_at,
             item.event_at, item.story_key, item.content_hash(), item.payload_hash, round(item.confidence, 3),
             round(item.relevance, 3), Jsonb(attributes), initial, "not yet classified", at))
        row = cur.fetchone()
        if row is not None:
            return int(row[0]), True
        cur.execute("SELECT id FROM ai.evidence WHERE story_key = %s AND content_hash = %s",
                    (item.story_key, item.content_hash()))
        found = cur.fetchone()
    assert found is not None
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

    @property
    def rank(self) -> int:
        return TIER_RANK.get(self.tier, 8)

    @property
    def when(self) -> datetime:
        return self.published_at or self.retrieved_at

    @property
    def subject(self) -> tuple[Any, ...]:
        """Who the item is about: the same player (by provider id, else by name) of the same team in the
        same match."""
        who = self.player_id if self.player_id is not None else self.player_name or None
        return self.fixture_id, self.team_id, who


NEGATIVE = frozenset({"out", "doubtful"})
POSITIVE = frozenset({"available", "starts"})


def _base_status(rows: list[Row]) -> tuple[Status, str]:
    """The status a group of items about one story can support, from its sources alone."""
    best = min(rows, key=lambda r: r.rank)
    dated_official = [r for r in rows if r.rank <= TIER_RANK["club"] and r.published_at is not None]
    media_domains = {r.domain for r in rows if r.tier in ("media", "journalist") and r.domain}
    if any(r.kind == "lineup" and r.origin == "provider" for r in rows):
        return "CONFIRMED", "the confirmed line-up"
    if dated_official:
        return "CONFIRMED", f"an official source ({dated_official[0].tier}) with a date"
    if len(media_domains) >= 2:
        return "CONFIRMED", f"{len(media_domains)} independent media outlets"
    if best.tier == "provider":
        return "PROBABLE", "the data provider's report"
    if best.rank <= TIER_RANK["media"]:
        return "PROBABLE", f"one {best.tier} source"
    return "RUMOR", f"only {best.tier} sources"


def classify(rows: list[Row], *, kickoff: datetime | None, at: datetime, lineup_starters: dict[int, set[int]],
             absences_checked_at: datetime | None) -> dict[int, tuple[Status, str]]:
    """The status of every item, decided together (a newer item can outdate an older one, two items can
    contradict each other). ``lineup_starters``: team id -> provider ids of the confirmed starters."""
    out: dict[int, tuple[Status, str]] = {}
    by_story: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_story[r.story_key].append(r)
    for story in by_story.values():
        status, reason = _base_status(story)
        for r in story:
            out[r.id] = (status, reason)
    # the same subject, different stories: newer and stronger outdates; comparable and opposite contradicts
    by_subject: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
    for r in rows:
        if r.kind in AVAILABILITY and r.subject[2] is not None:
            by_subject[r.subject].append(r)
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
        if r.kind in ("injury", "suspension") and r.player_id is not None and starters and r.player_id not in starters \
                and r.assertion == "out":
            out[r.id] = ("CONFIRMED", "absent from the confirmed starting line-up")
            continue
        if r.origin == "provider" and r.kind in ("injury", "suspension", "doubtful") and absences_checked_at is not None \
                and r.retrieved_at < absences_checked_at - CHECK_MARGIN:
            out[r.id] = ("OUTDATED", "no longer in the provider's latest injury report")
            continue
        if kickoff is not None and r.kind in AVAILABILITY and r.origin == "web" and kickoff - r.when > STALE_AFTER:
            out[r.id] = ("OUTDATED", "published more than ten days before the match")
    return out


LOAD_SQL = """
SELECT e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.origin, e.source_tier, e.source_domain,
       e.published_at, e.retrieved_at, e.story_key, e.status, e.status_reason, e.attributes
  FROM ai.evidence e WHERE e.fixture_id = %(fixture)s AND e.retrieved_at <= %(at)s
"""


def refresh_statuses(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, kickoff: datetime | None,
                     lineup_starters: dict[int, set[int]], absences_checked_at: datetime | None) -> dict[str, int]:
    """Re-decide every item of a match; write only the statuses that changed (the trigger keeps the
    history). Returns the count per status."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LOAD_SQL, {"fixture": fixture_id, "at": at})
        raw = [dict(r) for r in cur.fetchall()]
    rows = [Row(int(r["id"]), r["fixture_id"], r["team_id"], r["provider_player_id"],
                normalize_name((r["attributes"] or {}).get("player_name")), r["kind"], r["origin"], r["source_tier"],
                r["source_domain"], str((r["attributes"] or {}).get("assertion") or "info"), r["published_at"],
                r["retrieved_at"], r["story_key"], r["status"], r["attributes"] or {}) for r in raw]
    decided = classify(rows, kickoff=kickoff, at=at, lineup_starters=lineup_starters,
                       absences_checked_at=absences_checked_at)
    counts: dict[str, int] = defaultdict(int)
    current = {int(r["id"]): (r["status"], r["status_reason"]) for r in raw}
    with conn.cursor(row_factory=tuple_row) as cur:
        for eid, (status, reason) in decided.items():
            counts[status] += 1
            if current[eid] != (status, reason):
                cur.execute("UPDATE ai.evidence SET status = %s, status_reason = %s, status_changed_at = %s "
                            "WHERE id = %s", (status, reason, at, eid))
    return dict(counts)
