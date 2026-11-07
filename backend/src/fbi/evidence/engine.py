"""The read of ``evidence-engine-v1``: what is known about a match from outside the numbers, as of a moment, claim by claim (``evidence_for``),
and the same for every match of a day (``day_summary``). The rules are ``fbi.evidence.rules``; this module only gathers what they read.

AS OF, STRICTLY. Nothing recorded after ``at`` is read: an item retrieved after it, a line-up fetched after it, an injury report observed after
it, a status the server decided after it (the stored status is read back from ``status_history`` as it stood at ``at``). The credibility of a
source is learned from claims whose truth was known by ``at``, about other matches than the one being read (a claim never vouches for itself).

WHAT IT READS. ``ai.evidence`` - v1's items of the match (``subject_type IS NULL``) and research v2's typed claims (``subject_type IS NOT
NULL``) of the match and of its two teams that belong to no match - each kind by its own statement, on purpose: the engine is a read-only
reader of both, in shadow, never on the path of a decision (``tests/unit/test_typed_evidence_guard.py`` lists it among the readers that choose
on purpose). The provider's line-ups (``core.fixture_lineups`` and their players) and its injury reports (``core.player_availability_obs``).
The registry of sources (``ai.sources``), through ``fbi.ai.evidence.outlets_of``, to tell one outlet from another.

WHAT IT REUSES. contra-v1 (``fbi.ai.contra``) where it applies to evidence alone: C07 (two or more items CONTRADICTORY on one subject, by the
statuses ``fbi.ai.evidence`` decided) is run by contra-v1's own ``detect`` on an index of the match's items. C01-C06 and C08 read the package,
the candidates and the assessments of a run of the agents, which evidence alone does not have: they are reported as not applicable.

It never writes: no status, no cache, no row. The text of an item is outside text: only an excerpt passed through ``fbi.ai.untrusted`` is shown.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import contra, untrusted
from fbi.ai.agents.common import Named, Naming
from fbi.ai.evidence import normalize_name, outlets_of
from fbi.ai.review import Candidate
from fbi.ai.team_claims import team_claims
from fbi.evidence import VERSION, rules

AVAILABILITY_KINDS: Final = ("injury", "suspension", "doubtful", "lineup")
EXCERPT_CHARS: Final = 160
NEXT_MATCH_AHEAD: Final = timedelta(days=1)
"""How far past ``at`` a team's match is looked for when a claim that belongs to no match is checked against a line-up (a line-up is
published about an hour before kick-off: a match further away cannot have one known at ``at``)."""

NOT_DERIVED: Final[dict[str, str]] = {
    "national_vs_local_press": "the stored data has no field for an outlet's reach: B is the owner-trusted list (REPUTABLE_DOMAINS) and "
                               "research v2's RELIABLE_MEDIA, every other classified outlet is C",
    "accredited_journalist": "only fabrizioromano.com is registered as a journalist; a journalist's own account on a social network is D",
    "press_conference": "no stored field marks it: it is read from the item's text (rules.PRESS_CONFERENCE), outside the availability topics",
    "claims_by_name": "a claim about a player the provider does not identify (no provider_player_id) is never checked against the provider",
    "assertions_outside_availability": "coach, schedule, venue and news items have no assertion to compare (``info``): no claim-vs-claim "
                                       "contradiction is derived for them",
    "contra_v1_package_rules": "C01-C06 and C08 need the package, the candidates and the assessments of a run: not applicable to evidence alone",
}

# ── the statements ──────────────────────────────────────────────────────────────────────────────────────────────────

MATCH_SQL = """
SELECT 'v1' AS generation, e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.origin, e.source_domain, e.source_tier,
       e.source_class, e.published_at, e.retrieved_at, e.story_key, e.status, e.status_changed_at, e.status_history, e.attributes,
       e.claim_type
  FROM ai.evidence e
 WHERE e.subject_type IS NULL AND e.fixture_id = %(fixture)s AND e.retrieved_at <= %(at)s
UNION ALL
SELECT 'v2' AS generation, e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.origin, e.source_domain, e.source_tier,
       e.source_class, e.published_at, e.retrieved_at, e.story_key, e.status, e.status_changed_at, e.status_history, e.attributes,
       e.claim_type
  FROM ai.evidence e
 WHERE e.subject_type IS NOT NULL AND e.retrieved_at <= %(at)s
   AND (e.fixture_id = %(fixture)s OR """ + team_claims(home="%(home)s", away="%(away)s", at="%(at)s", set_aside=True) + """)
 ORDER BY id
"""
"""The match's items as of ``at``: v1's of the match, research v2's of the match and of its teams that belong to no match - the one definition of
those (``fbi.ai.team_claims``), keeping what the server set aside (the engine decides for itself) and with the engine's own window (``rules.LOOKBACK``
as ``stale``). ``typed`` is always true here: the engine reads research v2's claims on purpose, in shadow, and decides nothing with them."""

HISTORY_SQL = """
SELECT * FROM (
  SELECT 'v1' AS generation, e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.origin, e.source_domain,
         e.source_tier, e.source_class, e.published_at, e.retrieved_at, e.attributes,
         row_number() OVER (PARTITION BY COALESCE(e.source_domain, e.origin) ORDER BY e.retrieved_at DESC, e.id DESC) AS n
    FROM ai.evidence e
   WHERE e.subject_type IS NULL AND e.kind IN ('injury', 'suspension', 'doubtful', 'lineup') AND e.provider_player_id IS NOT NULL
     AND e.retrieved_at <= %(at)s AND e.retrieved_at > %(since)s
     AND (e.source_domain = ANY(%(hosts)s) OR e.source_domain LIKE ANY(%(below)s) OR e.origin = ANY(%(origins)s))
  UNION ALL
  SELECT 'v2' AS generation, e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.origin, e.source_domain,
         e.source_tier, e.source_class, e.published_at, e.retrieved_at, e.attributes,
         row_number() OVER (PARTITION BY COALESCE(e.source_domain, e.origin) ORDER BY e.retrieved_at DESC, e.id DESC) AS n
    FROM ai.evidence e
   WHERE e.subject_type IS NOT NULL AND e.kind IN ('injury', 'suspension', 'doubtful', 'lineup') AND e.provider_player_id IS NOT NULL
     AND e.retrieved_at <= %(at)s AND e.retrieved_at > %(since)s
     AND (e.source_domain = ANY(%(hosts)s) OR e.source_domain LIKE ANY(%(below)s) OR e.origin = ANY(%(origins)s))
) h WHERE h.n <= %(per_source)s
"""
"""What the sources of the match said before, about identified players: what their credibility is learned from."""

PEERS_SQL = """
SELECT 'v1' AS generation, e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.origin, e.source_domain, e.source_tier,
       e.source_class, e.published_at, e.retrieved_at, e.attributes
  FROM ai.evidence e
 WHERE e.subject_type IS NULL AND e.kind IN ('injury', 'suspension', 'doubtful', 'lineup') AND e.retrieved_at <= %(at)s
   AND e.retrieved_at > %(since)s
   AND (e.team_id, e.provider_player_id) IN (SELECT t, p FROM unnest(%(teams)s::bigint[], %(players)s::int[]) AS u(t, p))
UNION ALL
SELECT 'v2' AS generation, e.id, e.fixture_id, e.team_id, e.provider_player_id, e.kind, e.claim, e.origin, e.source_domain, e.source_tier,
       e.source_class, e.published_at, e.retrieved_at, e.attributes
  FROM ai.evidence e
 WHERE e.subject_type IS NOT NULL AND e.kind IN ('injury', 'suspension', 'doubtful', 'lineup') AND e.retrieved_at <= %(at)s
   AND e.retrieved_at > %(since)s
   AND (e.team_id, e.provider_player_id) IN (SELECT t, p FROM unnest(%(teams)s::bigint[], %(players)s::int[]) AS u(t, p))
"""
"""Everything said about the same players in the same window, by any source: the claims of a higher tier a past claim is checked against."""

FIXTURE_SQL = """
SELECT f.id, f.home_team_id, f.away_team_id, f.kickoff_at, h.name AS home_name, a.name AS away_name
  FROM core.fixtures f JOIN core.teams h ON h.id = f.home_team_id JOIN core.teams a ON a.id = f.away_team_id
 WHERE f.id = %(fixture)s
"""
TEAM_FIXTURES_SQL = """
SELECT f.id, f.home_team_id, f.away_team_id, f.kickoff_at FROM core.fixtures f
 WHERE (f.home_team_id = ANY(%(teams)s) OR f.away_team_id = ANY(%(teams)s)) AND f.kickoff_at > %(since)s AND f.kickoff_at <= %(until)s
"""
SHEETS_SQL = """
SELECT l.fixture_id, CASE l.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END AS team_id, l.fetched_at,
       COALESCE(array_agg(lp.provider_player_id) FILTER (WHERE lp.is_starter), '{}') AS starters,
       COALESCE(array_agg(lp.provider_player_id) FILTER (WHERE NOT lp.is_starter), '{}') AS bench
  FROM core.fixture_lineups l JOIN core.fixtures f ON f.id = l.fixture_id
  LEFT JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side AND lp.source = l.source
 WHERE l.fixture_id = ANY(%(fixtures)s) AND l.fetched_at <= %(at)s
 GROUP BY l.fixture_id, l.team_side, l.source, l.fetched_at, f.home_team_id, f.away_team_id
"""
LISTINGS_SQL = """
SELECT DISTINCT ON (o.fixture_id, o.provider_player_id) o.fixture_id, o.provider_player_id, o.status, o.absence_type, o.observed_at
  FROM core.player_availability_obs o
 WHERE o.fixture_id = ANY(%(fixtures)s) AND o.observed_at <= %(at)s
 ORDER BY o.fixture_id, o.provider_player_id, o.observed_at DESC
"""
DAY_SQL = "SELECT f.id FROM core.fixtures f WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s ORDER BY f.kickoff_at, f.id"


# ── one stored item, normalised ─────────────────────────────────────────────────────────────────────────────────────

def _stamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None
    return None


def status_as_of(current: str, changed_at: datetime, history: Any, at: datetime) -> str | None:
    """The status ``fbi.ai.evidence`` had given an item at ``at``: the current one if it was decided by then, else the entry of
    ``status_history`` that spans ``at`` (``from <= at < until``). None when the item had no status yet at ``at``."""
    if changed_at <= at:
        return current
    for entry in history if isinstance(history, list) else []:
        if not isinstance(entry, Mapping):
            continue
        start, end, status = _stamp(entry.get("from")), _stamp(entry.get("until")), entry.get("status")
        if start is not None and end is not None and start <= at < end and isinstance(status, str):
            return status
    return None


@dataclass(frozen=True, slots=True)
class Item:
    """One stored item as the engine reads it: who it is about, what it says, where it comes from and its tier."""

    evidence_id: int
    generation: str
    fixture_id: int | None
    team_id: int | None
    player_id: int | None
    player_name: str
    kind: str
    topic: str
    assertion: str
    origin: str
    domain: str | None
    outlet: str
    tier: rules.Tier
    tier_reason: str
    published_at: datetime | None
    retrieved_at: datetime
    stored_status: str | None = None
    flagged: bool = False
    claim_type: str | None = None
    excerpt: str = ""

    @property
    def when(self) -> datetime:
        return self.published_at or self.retrieved_at

    @property
    def subject(self) -> str:
        if self.player_id is not None:
            return f"player:{self.team_id}:{self.player_id}"
        if self.player_name:
            return f"player:{self.team_id}:name:{self.player_name}"
        if self.team_id is not None:
            return f"team:{self.team_id}"
        return f"match:{self.fixture_id}"

    @property
    def key(self) -> str:
        return f"{self.subject}|{self.topic}|{self.assertion}"


def outlet_of(origin: str, domain: str | None, outlets: Mapping[str, str], evidence_id: int) -> str:
    """Who said it, for independence: the provider, the owner, or the registered domain that vouches for a web host."""
    if origin in ("provider", "owner"):
        return origin
    if domain:
        return outlets.get(domain, domain)
    return f"unknown:{evidence_id}"


def item_of(row: Mapping[str, Any], outlets: Mapping[str, str], *, at: datetime | None = None, excerpt: bool = True) -> Item:
    attributes = row.get("attributes") or {}
    flagged = bool(attributes.get("instruction_like"))
    text = str(row.get("claim") or "")
    kind, origin, domain = str(row["kind"]), str(row["origin"]), row.get("source_domain")
    tiered = rules.tier_of(origin=origin, kind=kind, domain=domain, registry_tier=row.get("source_tier"), source_class=row.get("source_class"),
                       flagged=flagged, dated=row.get("published_at") is not None)
    stored = None
    if at is not None and row.get("status") is not None and row.get("status_changed_at") is not None:
        stored = status_as_of(str(row["status"]), row["status_changed_at"], row.get("status_history"), at)
    shown = untrusted.sanitize(text, origin=domain or origin, max_chars=EXCERPT_CHARS).text if excerpt else ""
    return Item(int(row["id"]), str(row["generation"]), row.get("fixture_id"), row.get("team_id"), row.get("provider_player_id"),
                normalize_name(attributes.get("player_name")) if row.get("provider_player_id") is None else "", kind,
                rules.topic_of(kind, text), str(attributes.get("assertion") or "info"), origin, domain,
                outlet_of(origin, domain, outlets, int(row["id"])), tiered.tier, tiered.reason, row.get("published_at"), row["retrieved_at"],
                stored, flagged, row.get("claim_type"), shown)


# ── the provider ────────────────────────────────────────────────────────────────────────────────────────────────────

def _sheets(conn: psycopg.Connection[Any], fixtures: Iterable[int], *, at: datetime) -> dict[tuple[int, int], rules.SquadSheet]:
    ids = sorted(set(fixtures))
    if not ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SHEETS_SQL, {"fixtures": ids, "at": at})
        rows = cur.fetchall()
    out: dict[tuple[int, int], rules.SquadSheet] = {}
    for r in rows:
        starters = frozenset(int(p) for p in r["starters"] or [] if p is not None)
        if not starters:  # a line-up without starters is not a line-up
            continue
        out[(int(r["fixture_id"]), int(r["team_id"]))] = rules.SquadSheet(int(r["team_id"]), r["fetched_at"], starters,
                                                                       frozenset(int(p) for p in r["bench"] or [] if p is not None))
    return out


def _listings(conn: psycopg.Connection[Any], fixtures: Iterable[int], *, at: datetime) -> dict[tuple[int, int], rules.Listing]:
    ids = sorted(set(fixtures))
    if not ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LISTINGS_SQL, {"fixtures": ids, "at": at})
        rows = cur.fetchall()
    return {(int(r["fixture_id"]), int(r["provider_player_id"])): rules.Listing(
        r["status"], r["status"] == "LISTED" and str(r["absence_type"] or "").strip().lower().startswith("missing"), r["observed_at"])
        for r in rows}


# ── credibility, learned ────────────────────────────────────────────────────────────────────────────────────────────

CredKey = tuple[str, str]
"""(outlet, tier): one outlet may speak with two tiers (the provider's line-up is A, its injury report B)."""


def _resolution_fixture(item: Item, team_fixtures: Mapping[int, Sequence[tuple[datetime, int]]]) -> int | None:
    """The match a past claim is about: its own, or - for a claim that belongs to no match - its team's first match from the claim's date
    within the topic's window."""
    if item.fixture_id is not None:
        return item.fixture_id
    if item.team_id is None:
        return None
    limit = item.when + rules.VALIDITY[item.topic]
    return next((fid for kickoff, fid in sorted(team_fixtures.get(item.team_id, ())) if item.when <= kickoff <= limit), None)


def learn_credibility(history: Sequence[Item], peers: Sequence[Item], *, wanted: Iterable[CredKey], exclude_fixture: int,
                      team_fixtures: Mapping[int, Sequence[tuple[datetime, int]]], sheets: Mapping[tuple[int, int], rules.SquadSheet],
                      listings: Mapping[tuple[int, int], rules.Listing]) -> dict[CredKey, rules.Credibility]:
    """The credibility of each (outlet, tier) asked for (``rules.credibility``), from its past availability claims about identified players of
    other matches, judged with what was known at the moment of the reading (the inputs are already cut at it)."""
    want = set(wanted)
    by_person: dict[tuple[int | None, int | None], list[Item]] = defaultdict(list)
    for p in peers:
        by_person[(p.team_id, p.player_id)].append(p)
    hits: Counter[CredKey] = Counter()
    resolved: Counter[CredKey] = Counter()
    seen: set[int] = set()
    for h in history:
        key = (h.outlet, h.tier)
        if key not in want or h.evidence_id in seen or h.player_id is None or h.topic not in rules.AVAILABILITY_TOPICS:
            continue
        seen.add(h.evidence_id)
        fixture = _resolution_fixture(h, team_fixtures)
        if fixture == exclude_fixture:
            continue  # a claim about the match being read never vouches for its own source
        window = rules.VALIDITY[h.topic]
        higher = [p.assertion for p in by_person[(h.team_id, h.player_id)]
                  if p.evidence_id != h.evidence_id and p.outlet != h.outlet and rules.TIER_RANK[p.tier] < rules.TIER_RANK[h.tier]
                  and p.topic in rules.AVAILABILITY_TOPICS and abs(p.when - h.when) <= window
                  and (fixture is None or _resolution_fixture(p, team_fixtures) in (fixture, None))]
        sheet = sheets.get((fixture, h.team_id)) if fixture is not None and h.team_id is not None else None
        listing = listings.get((fixture, h.player_id)) if fixture is not None else None
        outcome = rules.resolve(h.assertion, sheet=sheet, listing=listing, player_id=h.player_id, higher=higher)
        if outcome is not None:
            resolved[key] += 1
            hits[key] += int(outcome == "corroborated")
    return {k: rules.credibility(k[1], hits[k], resolved[k]) for k in want}


def _credibilities(conn: psycopg.Connection[Any], items: Sequence[Item], *, fixture_id: int, at: datetime) -> dict[CredKey, rules.Credibility]:
    wanted = {(i.outlet, i.tier) for i in items}
    hosts = sorted({i.domain for i in items if i.origin == "web" and i.domain})
    outlets_ = sorted({i.outlet for i in items if i.origin == "web" and not i.outlet.startswith("unknown:")})
    origins = sorted({i.origin for i in items if i.origin in ("provider", "owner")})
    since = at - rules.CREDIBILITY_WINDOW
    params = {"at": at, "since": since, "hosts": sorted(set(hosts) | set(outlets_)), "below": [f"%.{o}" for o in outlets_],
              "origins": origins, "per_source": rules.HISTORY_PER_SOURCE}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(HISTORY_SQL, params)
        raw_history = [dict(r) for r in cur.fetchall()]
    persons = sorted({(int(r["team_id"]), int(r["provider_player_id"])) for r in raw_history if r["team_id"] is not None})
    raw_peers: list[dict[str, Any]] = []
    team_rows: list[dict[str, Any]] = []
    if persons:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(PEERS_SQL, {"at": at, "since": since - rules.LOOKBACK, "teams": [t for t, _ in persons], "players": [p for _, p in persons]})
            raw_peers = [dict(r) for r in cur.fetchall()]
            cur.execute(TEAM_FIXTURES_SQL, {"teams": sorted({t for t, _ in persons}), "since": since - rules.LOOKBACK, "until": at + NEXT_MATCH_AHEAD})
            team_rows = [dict(r) for r in cur.fetchall()]
    hosts_all = {str(r["source_domain"]) for r in (*raw_history, *raw_peers) if r.get("source_domain")}
    outlets = outlets_of(conn, hosts_all) if hosts_all else {}
    history = [item_of(r, outlets, excerpt=False) for r in raw_history]
    peers = [item_of(r, outlets, excerpt=False) for r in raw_peers]
    team_fixtures: dict[int, list[tuple[datetime, int]]] = defaultdict(list)
    for f in team_rows:
        for team in (f["home_team_id"], f["away_team_id"]):
            team_fixtures[int(team)].append((f["kickoff_at"], int(f["id"])))
    fixtures = {i.fixture_id for i in (*history, *peers) if i.fixture_id is not None} | {fid for v in team_fixtures.values() for _, fid in v}
    fixtures.discard(fixture_id)
    return learn_credibility(history, peers, wanted=wanted, exclude_fixture=fixture_id, team_fixtures=team_fixtures,
                             sheets=_sheets(conn, fixtures, at=at), listings=_listings(conn, fixtures, at=at))


# ── the claims of a match ───────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Contradiction:
    rule: str
    subject: str
    claims: tuple[str, ...]
    evidence_ids: tuple[int, ...]

    def as_json(self) -> dict[str, Any]:
        return {"rule": self.rule, "subject": self.subject, "claims": list(self.claims), "evidence_ids": list(self.evidence_ids),
                "means": rules.CONTRA_RULES.get(self.rule, "contra-v1 C07: two or more items CONTRADICTORY on one subject")}


@dataclass(frozen=True, slots=True)
class Claim:
    """One normalised claim: every item of the match that says the same thing about the same subject, decided together."""

    key: str
    subject: str
    side: str
    topic: str
    assertion: str
    player_id: int | None
    decided: rules.Decided
    items: tuple[Item, ...]
    credibility: Mapping[CredKey, rules.Credibility]
    confidence_net: float = 0.0
    contradictions: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        d = self.decided
        return {
            "key": self.key, "subject": self.subject, "side": self.side, "topic": self.topic, "assertion": self.assertion,
            "player_id": self.player_id, "status": d.status, "status_rule": d.rule, "confidence": d.confidence,
            "confidence_net": self.confidence_net, "support": d.support, "freshness": d.freshness,
            "validity": {"window_hours": int(rules.VALIDITY[self.topic].total_seconds() // 3600), "from": d.valid_from.isoformat(),
                         "until": d.valid_until.isoformat(), "expired": d.expired},
            "contradictions": list(self.contradictions),
            "sources": [{"evidence_id": i.evidence_id, "generation": i.generation, "origin": i.origin, "domain": i.domain, "outlet": i.outlet,
                         "tier": i.tier, "tier_reason": i.tier_reason, "kind": i.kind, "claim_type": i.claim_type,
                         "credibility": self.credibility[(i.outlet, i.tier)].as_json(),
                         "published_at": None if i.published_at is None else i.published_at.isoformat(),
                         "retrieved_at": i.retrieved_at.isoformat(), "live": i.evidence_id in d.live_ids,
                         "stored_status_as_of": i.stored_status, "flagged": i.flagged, "excerpt": i.excerpt} for i in self.items]}


@dataclass(frozen=True, slots=True)
class Report:
    fixture_id: int
    at: datetime
    kickoff_at: datetime
    home: tuple[int, str]
    away: tuple[int, str]
    claims: tuple[Claim, ...]
    contradictions: tuple[Contradiction, ...]
    items: tuple[Item, ...] = field(default_factory=tuple)

    def counts(self) -> dict[str, Any]:
        return counts_of([self])

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "rules": rules.rules_digest(), "shadow": True, "fixture_id": self.fixture_id, "at": self.at.isoformat(),
                "kickoff_at": self.kickoff_at.isoformat(), "home": {"team_id": self.home[0], "name": self.home[1]},
                "away": {"team_id": self.away[0], "name": self.away[1]}, "counts": self.counts(),
                "claims": [c.as_json() for c in self.claims], "contradictions": [c.as_json() for c in self.contradictions],
                "not_derived": NOT_DERIVED}


def counts_of(reports: Sequence[Report]) -> dict[str, Any]:
    """Counts by tier (of items), by status and topic (of claims), the expired claims, the contradictions by rule, and how many of the items
    are v1's evidences and how many research v2's claims - the comparison the gate of research v2 needs."""
    items = [i for r in reports for i in r.items]
    claims = [c for r in reports for c in r.claims]
    contradictions = [c for r in reports for c in r.contradictions]
    return {"items": len(items), "claims": len(claims),
            "by_tier": {t: sum(1 for i in items if i.tier == t) for t in rules.TIERS},
            "by_status": {s: sum(1 for c in claims if c.decided.status == s and not c.decided.expired) for s in rules.STATUSES},
            "by_topic": {t: sum(1 for c in claims if c.topic == t) for t in rules.TOPICS},
            "expired": sum(1 for c in claims if c.decided.expired),
            "contradictions": dict(sorted(Counter(c.rule for c in contradictions).items())),
            "generations": {"v1_evidences": sum(1 for i in items if i.generation == "v1"),
                            "v2_claims": sum(1 for i in items if i.generation == "v2")}}


def side_of(team_id: int | None, home: int, away: int) -> str:
    return "home" if team_id == home else "away" if team_id == away else "match"


def build_claims(items: Sequence[Item], credibility: Mapping[CredKey, rules.Credibility], *, at: datetime, fixture_id: int, home: int,
                 away: int, sheets: Mapping[tuple[int, int], rules.SquadSheet], listings: Mapping[tuple[int, int], rules.Listing]
                 ) -> tuple[tuple[Claim, ...], tuple[Contradiction, ...]]:
    """Group the items into claims, decide each one, and find the contradictions (claim vs claim, claim vs provider). Pure."""
    groups: dict[str, list[Item]] = defaultdict(list)
    for i in items:
        groups[i.key].append(i)
    decided: dict[str, tuple[rules.Decided, list[Item]]] = {}
    for key, members in groups.items():
        topic = members[0].topic
        support = [rules.Support(i.evidence_id, i.outlet, i.tier, credibility[(i.outlet, i.tier)].value, i.when) for i in members]
        decided[key] = (rules.decide(topic, support, at=at), sorted(members, key=lambda i: i.evidence_id))
    found: list[Contradiction] = []
    by_subject: dict[str, list[str]] = defaultdict(list)
    for key, (_, members) in decided.items():
        if members[0].topic in rules.AVAILABILITY_TOPICS and members[0].subject.startswith("player:"):
            by_subject[members[0].subject].append(key)
    opposing: dict[str, list[float]] = defaultdict(list)
    for subject, keys in by_subject.items():
        for a in sorted(keys):
            for b in sorted(keys):
                da, ma = decided[a]
                db, mb = decided[b]
                if a < b and not da.expired and not db.expired and rules.incompatible(ma[0].assertion, mb[0].assertion):
                    found.append(Contradiction("CC1", subject, (a, b), tuple(sorted({*da.live_ids, *db.live_ids}))))
                    opposing[a].append(db.confidence)
                    opposing[b].append(da.confidence)
    provider: dict[str, list[str]] = defaultdict(list)
    for key, (d, members) in sorted(decided.items()):
        first = members[0]
        if d.expired or first.topic not in rules.AVAILABILITY_TOPICS or first.team_id is None:
            continue
        rules_broken = rules.against_provider(first.assertion, first.player_id, sheet=sheets.get((fixture_id, first.team_id)),
                                          listing=None if first.player_id is None else listings.get((fixture_id, first.player_id)))
        for rule in rules_broken:
            found.append(Contradiction(rule, first.subject, (key,), d.live_ids))
            provider[key].append(rule)
    names: dict[str, list[str]] = defaultdict(list)
    for c in found:
        for k in c.claims:
            names[k].append(c.rule)
    claims = tuple(
        Claim(key, members[0].subject, side_of(members[0].team_id, home, away), members[0].topic, members[0].assertion, members[0].player_id,
              d, tuple(members), {(i.outlet, i.tier): credibility[(i.outlet, i.tier)] for i in members},
              rules.net(d.confidence, opposing=opposing[key], provider=provider[key]), tuple(sorted(set(names[key]))))
        for key, (d, members) in sorted(decided.items(), key=lambda kv: (rules.STATUSES.index(kv[1][0].status) * -1, kv[0])))
    return claims, tuple(sorted(found, key=lambda c: (c.rule, c.subject, c.claims)))


def contra_v1(items: Sequence[Item], *, fixture_id: int, home: int, away: int, kickoff: datetime, at: datetime) -> tuple[Contradiction, ...]:
    """contra-v1's C07, run by contra-v1's own detector on an index of the match's items with the status ``fbi.ai.evidence`` had given each
    at ``at``. The detector drops a contradiction that touches no candidate, and C07 touches every candidate: a probe candidate is named so
    that it fires, and nothing of the probe is kept."""
    index = [{"id": i.evidence_id, "kind": i.kind, "side": side_of(i.team_id, home, away), "player_id": i.player_id, "status": i.stored_status}
             for i in items if i.stored_status is not None]
    probe = Candidate(fixture_id, "1X2", "HOME", Decimal(0), Decimal("0.5"), kickoff)
    naming = Naming((Named("c1", probe, "1X2"),))
    found = contra.detect({"evidence": index}, naming=naming, at=at)
    return tuple(Contradiction("C07", c.subject, (), tuple(sorted(int(r[2:]) for r in c.refs if r.startswith("E:")))) for c in found
                 if c.code == "C07")


def evidence_for(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> Report | None:
    """What is known about a match as of ``at`` (strictly), claim by claim: status, computed confidence, validity, contradictions. None for a
    match that does not exist. Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURE_SQL, {"fixture": fixture_id})
        f = cur.fetchone()
        if f is None:
            return None
        home, away = int(f["home_team_id"]), int(f["away_team_id"])
        cur.execute(MATCH_SQL, {"fixture": fixture_id, "at": at, "home": home, "away": away, "typed": True, "stale": rules.LOOKBACK})
        raw = [dict(r) for r in cur.fetchall()]
    hosts = {str(r["source_domain"]) for r in raw if r.get("source_domain")}
    outlets = outlets_of(conn, hosts) if hosts else {}
    items = tuple(item_of(r, outlets, at=at) for r in raw)
    credibility = _credibilities(conn, items, fixture_id=fixture_id, at=at) if items else {}
    sheets = _sheets(conn, [fixture_id], at=at)
    listings = _listings(conn, [fixture_id], at=at)
    claims, found = build_claims(items, credibility, at=at, fixture_id=fixture_id, home=home, away=away, sheets=sheets, listings=listings)
    c07 = contra_v1(items, fixture_id=fixture_id, home=home, away=away, kickoff=f["kickoff_at"], at=at)
    return Report(fixture_id, at, f["kickoff_at"], (home, str(f["home_name"])), (away, str(f["away_name"])), claims, (*found, *c07), items)


def day_summary(conn: psycopg.Connection[Any], the_day: date, *, at: datetime) -> dict[str, Any]:
    """``evidence_for`` for every match that kicks off on a day (Bogotá), as of ``at``, and the counts of all of them together."""
    from fbi.ai.calendar import day_bounds

    start, end = day_bounds(the_day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DAY_SQL, {"start": start, "end": end})
        ids = [int(r["id"]) for r in cur.fetchall()]
    reports = [r for r in (evidence_for(conn, fid, at=at) for fid in ids) if r is not None]
    return {"version": VERSION, "rules": rules.rules_digest(), "shadow": True, "day": the_day.isoformat(), "at": at.isoformat(),
            "fixtures": len(reports), "with_evidence": sum(1 for r in reports if r.items), "counts": counts_of(reports),
            "matches": [{"fixture_id": r.fixture_id, "kickoff_at": r.kickoff_at.isoformat(), "home": r.home[1], "away": r.away[1]}
                        | r.counts() for r in reports]}
