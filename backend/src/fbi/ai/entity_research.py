"""Research v2 (Plan Maestro IA, phase 2): ONE research per entity and topic, shared by every match and every agent that needs it.

v1 researches a MATCH: it asks the web about «A vs B», reads what comes back for that match and writes items tied to it; a team that plays
twice in three days is researched twice, and a page that two matches share is read twice. v2 researches what is known about a TEAM on a topic
(its availability, the official confirmations) and about a MATCH on the one topic that is about the match (the international preview), keeps ONE
answer per entity and topic (``fbi.ai.cache.entity_key``), and lets every match that needs it read it while it is fresh:

    for each level of the tiered search the pass asks for (``fbi.ai.research.levels_for``; the same levels v1 would search):
        the entities the level is about  -> the answers of them that are still fresh (judged NOW, by the nearest kick-off of each entity)
        the ones missing                 -> ONE search: the query of the match when both sides are missing (the very query - the very cache
                                            key - v1 uses: an answer already cached for it is the answer), the query of one team alone when only
                                            one is, the preview always about the match
        the first level whose answer has a source of known standing is enough (v1's rule)
    the pages found, most authoritative first, minus the ones already read for the same subjects  -> ONE extraction call:
        the claim extractor (``claim_extractor``, ``extract-v2``) reads them and answers in claim-v1 about SUBJECTS the server lists
        (``fbi.ai.extract_v2``); what of the answer stands becomes typed evidence (``ai.evidence.subject_type``).
    what was found is remembered, for as long as the topic's freshness says.

What does NOT change, and why it can run beside v1 in the week of comparison (``FBI_AI_RESEARCH_V2=shadow``):

* It never searches more than the levels the pass asks for, one search per level, like v1: the savings come from the answers it keeps.
* It writes typed evidence only. The packet does not show a typed claim until the owner turns v2 ``on`` and the gate has passed
  (``fbi.ai.packet``); v1's items are decided without it (``fbi.ai.evidence.LOAD_SQL``) and v2's among themselves
  (``fbi.ai.evidence.refresh_typed_statuses``). Nothing v2 does moves a status, a packet or a pick of v1.
* It spends like v1: the same guards (a search API and a model configured, the budget allows a search, Exa's own envelope), the same ledger,
  the same cost. Its paid searches are in the ledger under ``input_hash`` ``rk-v2:<key>``; its extraction calls under the agent
  ``claim_extractor``. A search that v1 already paid for in the same pass is READ (it is the same query), not paid again, and counted apart:
  ``demand`` is the searches the pass needed, ``paid`` the ones it paid, ``shared`` the ones the search cache answered - so the report that
  compares the two researches can say how many searches v2 would have paid on its own.
* It fails open: a search that fails, a model that is down or an answer that is not claim-v1 is recorded and the pass goes on.

Spend decisions that are mine, declared: pages beyond the sixth most authoritative are not read (v1 reads them in the next pass, one more
call for the weakest sources); an answer is remembered only after the pages were read. What "read" means (plan, section 15: only a failure of
the transport is retried, never one of the content):

* the call could not be made or answered (a timeout, a server error, the budget): nothing was read, the pages are not marked and the next pass
  asks again at no search cost - the search is cached;
* the call was answered and the answer is not ``claim-v1`` (or the provider could not read it as the schema, or the model refused): the pages are
  DISCARDED - marked as read, counted (``v2_invalid``) and never asked again for the same subjects - and the pass goes on;
* the call was answered: the claims that stand are stored; a claim that breaks a limit or a rule is dropped and counted, the others stand.

A page that reads like an order to a model is read in a call of its own (``extract_v2.groups``): the model that reads the others never sees it
(independent review of phase 2, 27 Oct 2026, finding H1).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import httpx
import psycopg
from psycopg.rows import dict_row

from fbi.ai import cache, extract_v2, gates, research
from fbi.ai.absences import absences_as_of
from fbi.ai.budget_v3 import exa_budget
from fbi.ai.collectors import (
    EARLY_TTL,
    EXTRACT_TTL,
    KNOWN_STANDING,
    LATE_TTL,
    LATE_WINDOW,
    LINEUPS_SQL,
    MAX_READ,
    Collected,
    SearchFn,
    default_search,
    levels_wanted,
    query_for_sides,
    record_source_results,
    search_key,
)
from fbi.ai.config import AiSettings
from fbi.ai.evidence import TIER_RANK, domain_of, refresh_typed_statuses, store, tier_of
from fbi.ai.pricing import search_cost
from fbi.ai.prompts import EXTRACT_V2_VERSION
from fbi.ai.providers.base import LlmProvider
from fbi.ai.usage import UsageLedger, call_json, effective_tier
from fbi.ai.usage import budget as budget_of
from fbi.analyst.search import SearchResult

AGENT: Final = "claim_extractor"
LEDGER_PREFIX: Final = "rk-v2:"
"""What the ledger's ``input_hash`` of a search paid by v2 starts with: the report that compares the researches counts them apart."""
MAX_PLAYERS: Final = 30
"""Players of a team the extractor may be asked about: the ones the provider reports absent first, then the ones with most minutes."""
CONTENT_ERRORS: Final = frozenset({"invalid_output", "refused"})
"""How a call ends when the fault is in what came back and not in the road to it: an answer the provider could not read as the schema, or a
refusal. It is recorded and not asked again for the same pages (a transport failure - timeout, server error, budget - is)."""

MATCH_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name,
       th.provider_team_id AS home_provider_id, ta.provider_team_id AS away_provider_id,
       c.id AS competition_id, c.name AS competition, c.country, c.provider_league_id, cs.season
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(fixture)s
"""

NEAREST_SQL: Final = """
SELECT team_id, min(kickoff_at) AS nearest FROM (
    SELECT home_team_id AS team_id, kickoff_at FROM core.fixtures
     WHERE home_team_id = ANY(%(teams)s) AND status_group = 'scheduled' AND kickoff_at > %(at)s
    UNION ALL
    SELECT away_team_id AS team_id, kickoff_at FROM core.fixtures
     WHERE away_team_id = ANY(%(teams)s) AND status_group = 'scheduled' AND kickoff_at > %(at)s
) x GROUP BY team_id
"""

PLAYERS_SQL: Final = """
WITH squad AS (
    SELECT s.provider_player_id FROM core.player_season_stats s
     WHERE s.provider_team_id = %(provider_team)s AND s.season = %(season)s AND s.provider_league_id = %(league)s
       AND s.observed_at <= %(at)s
    UNION
    SELECT m.provider_player_id FROM core.squad_members m WHERE m.team_id = %(team)s
), latest AS (
    SELECT DISTINCT ON (s.provider_player_id, s.provider_league_id) s.provider_player_id, s.minutes
      FROM core.player_season_stats s JOIN squad q ON q.provider_player_id = s.provider_player_id
     WHERE s.provider_team_id = %(provider_team)s AND s.season = %(season)s AND s.observed_at <= %(at)s
     ORDER BY s.provider_player_id, s.provider_league_id, s.observed_at DESC
)
SELECT q.provider_player_id, COALESCE(max(p.name), max(m.player_name)) AS name, COALESCE(sum(l.minutes), 0)::int AS minutes
  FROM squad q
  LEFT JOIN latest l ON l.provider_player_id = q.provider_player_id
  LEFT JOIN core.players p ON p.provider_player_id = q.provider_player_id
  LEFT JOIN core.squad_members m ON m.provider_player_id = q.provider_player_id AND m.team_id = %(team)s
 GROUP BY q.provider_player_id
HAVING COALESCE(max(p.name), max(m.player_name)) IS NOT NULL
 ORDER BY minutes DESC, name, q.provider_player_id
 LIMIT %(limit)s
"""


@dataclass(frozen=True, slots=True)
class Team:
    side: str
    id: int
    name: str
    provider_id: int | None
    nearest_kickoff: datetime
    """The nearest kick-off of the team from now on (this match's if there is no sooner one): it decides how long what is known of the team is
    reused - a team with a match tomorrow and another in three days is read as a team with a match tomorrow."""


@dataclass(frozen=True, slots=True)
class Match:
    fixture_id: int
    kickoff_at: datetime
    competition_id: int
    competition: str | None
    country: str | None
    season: int | None
    league: int | None
    home: Team
    away: Team

    @property
    def teams(self) -> tuple[Team, Team]:
        return self.home, self.away

    def block(self) -> dict[str, Any]:
        return extract_v2.match_block(self.fixture_id, self.home.name, self.away.name, self.kickoff_at.isoformat(), self.competition)


def load_match(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> Match | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MATCH_SQL, {"fixture": fixture_id})
        f = cur.fetchone()
        if f is None:
            return None
        cur.execute(NEAREST_SQL, {"teams": [f["home_team_id"], f["away_team_id"]], "at": at})
        nearest = {int(r["team_id"]): r["nearest"] for r in cur.fetchall()}

    def team(side: str, team_id: int, name: str, provider_id: int | None) -> Team:
        return Team(side, int(team_id), str(name), provider_id, min(nearest.get(int(team_id), f["kickoff_at"]), f["kickoff_at"]))

    return Match(int(f["id"]), f["kickoff_at"], int(f["competition_id"]), f["competition"], f["country"], f["season"], f["provider_league_id"],
                 team("home", f["home_team_id"], f["home_name"], f["home_provider_id"]),
                 team("away", f["away_team_id"], f["away_name"], f["away_provider_id"]))


@dataclass(frozen=True, slots=True)
class Entity:
    """What a level of the tiered search is about: a team (team news, official confirmations) or the match (the preview)."""

    kind: str
    id: int
    side: str | None
    nearest_kickoff: datetime


def entities_of(match: Match, level: int) -> list[Entity]:
    if research.TOPIC_ENTITY[research.LEVEL_TOPIC[level]] == "MATCH":
        return [Entity("MATCH", match.fixture_id, None, match.kickoff_at)]
    return [Entity("TEAM", t.id, t.side, t.nearest_kickoff) for t in match.teams]


def token(kind: str, entity_id: int) -> str:
    """What a page read is remembered by: the subjects it was read for."""
    return f"{kind}:{entity_id}"


@dataclass(slots=True)
class Found:
    """A result of a search, the topic it answers and the subjects it must be read for."""

    result: SearchResult
    topic: str
    tokens: set[str]


@dataclass(frozen=True, slots=True)
class Answer:
    """What is remembered of an entity on a topic once the pages were read."""

    entity: Entity
    topic: str
    body: dict[str, Any]


@dataclass
class CollectedV2(Collected):
    """What a pass of research v2 did. ``searches`` and ``cost_usd`` are what it PAID (a search the cache answered is ``shared``)."""

    demand: int = 0
    """Searches the pass needed: levels with an entity whose answer was not fresh."""
    paid: int = 0
    """... paid by v2 (the same number as ``searches``)."""
    shared: int = 0
    """... answered by the search cache (a query v1 or an earlier pass had paid for): v2 would have paid for them on its own."""
    reused: int = 0
    """Entity answers that were still fresh: searches the pass did not need."""
    pages: int = 0
    pages_known: int = 0
    """Pages not shown to the extractor because they had been read for the same subjects."""
    pages_unread: int = 0
    pages_flagged: int = 0
    """Pages that read like an order to a model (``fbi.ai.untrusted``)."""
    kept: int = 0
    """Claims of the answer that stand."""
    invalid: int = 0
    """Calls whose answer came back and was not ``claim-v1`` (the ledger wrote them down as ``ok``: the provider did answer): their pages were
    discarded, not read again. A call the provider could not read, or that the model refused, is in the ledger as ``invalid_output`` or
    ``refused`` and its pages are discarded in the same way; it is not counted here."""
    stored_match: int = 0
    stored_entity: int = 0
    dropped: dict[str, int] = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def counts(self) -> dict[str, int]:
        """The counts of a pass, as the cycle writes them (``v2_*``); zero ones left out."""
        raw = {"v2_demand": self.demand, "v2_paid": self.paid, "v2_shared": self.shared, "v2_reused": self.reused, "v2_pages": self.pages,
               "v2_pages_known": self.pages_known, "v2_pages_unread": self.pages_unread, "v2_pages_flagged": self.pages_flagged,
               "v2_claims": self.kept, "v2_invalid": self.invalid, "v2_new": self.created, "v2_stored_match": self.stored_match, "v2_stored_entity": self.stored_entity,
               **{f"v2_dropped_{k}": n for k, n in self.dropped.items()}}
        return {k: n for k, n in raw.items() if n}


# ── who the extractor may talk about ─────────────────────────────────────────────────────────────────────────────────

def players_of(conn: psycopg.Connection[Any], match: Match, team: Team, *, at: datetime) -> list[tuple[int, str]]:
    """(provider id, name) of the players of a team the extractor is asked about: the ones the provider's latest injury report names first,
    then the squad by minutes of the season. Never more than ``MAX_PLAYERS``."""
    out: list[tuple[int, str]] = []
    seen: set[int] = set()
    for a in absences_as_of(conn, match.fixture_id, at):
        if team.provider_id is not None and a["provider_team_id"] == team.provider_id and a["player_name"] \
                and int(a["provider_player_id"]) not in seen:
            seen.add(int(a["provider_player_id"]))
            out.append((int(a["provider_player_id"]), str(a["player_name"])))
    if match.season is not None and match.league is not None and team.provider_id is not None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(PLAYERS_SQL, {"provider_team": team.provider_id, "team": team.id, "season": match.season, "league": match.league, "at": at,
                                      "limit": MAX_PLAYERS})
            for r in cur.fetchall():
                if int(r["provider_player_id"]) not in seen and len(out) < MAX_PLAYERS:
                    seen.add(int(r["provider_player_id"]))
                    out.append((int(r["provider_player_id"]), str(r["name"])))
    return out[:MAX_PLAYERS]


def subjects_for(conn: psycopg.Connection[Any], match: Match, team_ids: Sequence[int], *, at: datetime) -> list[extract_v2.Subject]:
    """The list the extractor is shown, written by the server: the teams being researched, the match, the competition and the players of those
    teams. A claim about anyone else does not stand."""
    out: list[extract_v2.Subject] = []

    def add(subject: extract_v2.Subject | None) -> None:
        if subject is not None:
            out.append(subject)

    researched = [t for t in match.teams if t.id in set(team_ids)]
    for t in researched:
        add(extract_v2.subject("TEAM", t.id, t.name, team_id=t.id))
    add(extract_v2.subject("MATCH", match.fixture_id, f"{match.home.name} vs {match.away.name}"))
    if match.competition:
        add(extract_v2.subject("COMPETITION", match.competition_id, match.competition))
    for t in researched:
        for player_id, name in players_of(conn, match, t, at=at):
            add(extract_v2.subject("PLAYER", player_id, name, team_id=t.id))
    return out


def lineup_starters(conn: psycopg.Connection[Any], match: Match, *, at: datetime) -> dict[int, set[int]]:
    """Team id -> provider ids of the confirmed starters, as of ``at`` (the newest line-up of each side)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LINEUPS_SQL, {"fixture": match.fixture_id, "at": at})
        rows = sorted(cur.fetchall(), key=lambda r: r["fetched_at"])
    out: dict[int, set[int]] = {}
    for lu in rows:
        team_id = match.home.id if lu["team_side"] == "home" else match.away.id
        out[team_id] = {int(x) for x in (lu["starters"] or []) if x is not None}
    return out


def refresh(conn: psycopg.Connection[Any], match: Match, *, at: datetime) -> dict[str, int]:
    """Re-decide the statuses of what research v2 knows for the match (``fbi.ai.evidence.refresh_typed_statuses``)."""
    return refresh_typed_statuses(conn, match.fixture_id, [match.home.id, match.away.id], at=at, kickoff=match.kickoff_at,
                                  lineup_starters=lineup_starters(conn, match, at=at))


def refresh_for(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> dict[str, int]:
    """The same for a match by id (the cycle calls it when a pass could not search)."""
    match = load_match(conn, fixture_id, at=at)
    return {} if match is None else refresh(conn, match, at=at)


# ── the research ────────────────────────────────────────────────────────────────────────────────────────────────────

def _results(payload: dict[str, Any]) -> list[SearchResult]:
    out: list[SearchResult] = []
    for hit in payload.get("results") or []:
        if isinstance(hit, dict):
            try:
                out.append(SearchResult(str(hit["url"]), str(hit.get("title") or ""), str(hit.get("publisher") or ""), hit.get("published_at"),
                                        str(hit.get("retrieved_at") or ""), str(hit.get("snippet") or "")))
            except KeyError:
                continue
    return out


def _rank(conn: psycopg.Connection[Any], url: str) -> int:
    return TIER_RANK.get(tier_of(conn, domain_of(url) or ""), 8)


def collect(conn: psycopg.Connection[Any], settings: AiSettings, fixture_id: int, *, at: datetime, ledger: UsageLedger | None = None,
            search: SearchFn | None = None, provider: tuple[LlmProvider, str] | None = None,
            transport: httpx.BaseTransport | None = None, levels: int | Sequence[int] = 1) -> CollectedV2:
    """The research of one match for one pass, when a search API and a model are configured and the budget allows - otherwise nothing is
    fetched and the reason is returned (``skipped``). Whatever it did, the statuses of what research v2 knows for the match are decided again."""
    out = CollectedV2()
    match = load_match(conn, fixture_id, at=at)
    if match is None:
        out.skipped = "no such fixture"
        return out
    answers = _research(conn, settings, match, out, at=at, ledger=ledger or UsageLedger(), search=search, provider=provider, transport=transport,
                        levels=levels)
    for answer in answers:
        cache.remember(conn, answer.entity.kind, answer.entity.id, answer.topic, answer.body, at=at, nearest_kickoff=answer.entity.nearest_kickoff)
    out.statuses = refresh(conn, match, at=at)
    return out


def _research(conn: psycopg.Connection[Any], settings: AiSettings, match: Match, out: CollectedV2, *, at: datetime, ledger: UsageLedger,
              search: SearchFn | None, provider: tuple[LlmProvider, str] | None, transport: httpx.BaseTransport | None,
              levels: int | Sequence[int]) -> list[Answer]:
    """Search what is missing, read what is new. Returns the answers to remember: none when the pages could not be read."""
    search = search or default_search(settings, transport)
    if search is None:
        out.skipped = "search_not_configured"
        return []
    b = budget_of(conn, at=at, settings=settings)
    if not b.allows("search"):
        out.skipped = f"budget_{b.state.lower()}"
        return []
    if provider is None and effective_tier(b, "bulk", settings) is None:
        out.skipped = "model_not_configured"
        return []
    exa_envelope = gates.enabled(conn, settings, "budget_v3")
    late = match.kickoff_at - at <= LATE_WINDOW
    bucket = "late" if late else "early"
    found: list[Found] = []
    answers: list[Answer] = []
    for tried, level in enumerate(levels_wanted(levels), start=1):
        out.levels_tried = tried
        topic = research.LEVEL_TOPIC[level]
        missing: list[Entity] = []
        known = False
        for entity in entities_of(match, level):
            answer = cache.fresh(conn, entity.kind, entity.id, topic, at=at, nearest_kickoff=entity.nearest_kickoff)
            if answer is None:
                missing.append(entity)
            else:
                out.reused += 1
                known = known or bool(answer.get("standing"))
        if missing:
            sides = tuple(e.side for e in missing if e.side is not None) or ("home", "away")
            query = query_for_sides(level, sides, home=match.home.name, away=match.away.name, kickoff=match.kickoff_at, country=match.country,
                                    competition=match.competition)
            key = search_key(query, bucket, level)
            out.demand += 1
            max_age = cache.ttl_for(topic, nearest_kickoff=min(e.nearest_kickoff for e in missing), at=at)
            payload = cache.get(conn, "search", key, at=at, max_age=max_age)
            if payload is None:
                if exa_envelope and not exa_budget(conn, at=at, settings=settings).allowed:
                    out.skipped = "budget_exa"  # Exa's own envelope (budget v3): spent for the month, or for today
                    break
                engine = settings.search or "exa"
                try:
                    results = search(query, at)
                except Exception as exc:  # an outage of the search API: recorded, free, the day goes on
                    ledger.record(at=at, purpose="web_search", tier="search", provider=engine, model=engine, usage=None, cost=Decimal(0),
                                  status="failed", fixture_id=match.fixture_id, input_hash=LEDGER_PREFIX + key,
                                  error=f"search failed: {type(exc).__name__}")
                    out.skipped = "search_failed"
                    break
                out.searches += 1
                out.paid += 1
                cost = search_cost(engine, 1)
                out.cost_usd += float(cost)
                ledger.record(at=at, purpose="web_search", tier="search", provider=engine, model=engine, usage=None, cost=cost, status="ok",
                              fixture_id=match.fixture_id, input_hash=LEDGER_PREFIX + key)
                record_source_results(conn, results, at=at, cost=cost)
                payload = {"query": query, "level": level, "results": [r.as_json() for r in results]}
                cache.put(conn, "search", key, payload, at=at, ttl=LATE_TTL if late else EARLY_TTL)
            else:
                out.shared += 1
            hits = _results(payload)
            standing = any(_rank(conn, r.url) <= KNOWN_STANDING for r in hits)
            classes = Counter(tier_of(conn, domain_of(r.url) or "") for r in hits)
            tokens = {token("TEAM", e.id) for e in missing if e.kind == "TEAM"} | {token("MATCH", match.fixture_id)}
            if any(e.kind == "MATCH" for e in missing):  # a preview speaks of both teams
                tokens |= {token("TEAM", match.home.id), token("TEAM", match.away.id)}
            body = {"v": cache.KEY_VERSION, "topic": topic, "level": level, "search": key, "searched_at": at.isoformat(), "results": len(hits),
                    "standing": standing, "classes": dict(sorted(classes.items()))}
            answers.extend(Answer(e, topic, body) for e in missing)
            found.extend(Found(r, topic, set(tokens)) for r in hits)
            known = known or standing
        if known:
            break  # the first level with a source of known standing is enough (v1's rule)
    if found and not _read(conn, settings, match, found, out, at=at, ledger=ledger, provider=provider, transport=transport):
        return []  # nothing was read: nothing is remembered, the next pass reads the pages again (the search is cached)
    return answers


def _read(conn: psycopg.Connection[Any], settings: AiSettings, match: Match, found: list[Found], out: CollectedV2, *, at: datetime,
          ledger: UsageLedger, provider: tuple[LlmProvider, str] | None, transport: httpx.BaseTransport | None) -> bool:
    """Read the pages that are new for the subjects they were found for, ask the extractor (once for the pages that do not read like an order,
    once for the ones that do), store what stands. True when the pages were read or discarded (or there was nothing to read); False when a
    call could not be made or answered. A group of pages is marked as read as soon as its call is over, so a failure of a later call never
    makes the pass pay again for an earlier one."""
    unique: dict[str, Found] = {}
    for f in found:
        try:
            key = cache.url_key(f.result.url)
        except ValueError:  # not a web address: not a page
            continue
        if key in unique:
            unique[key].tokens |= f.tokens
        else:
            unique[key] = Found(f.result, f.topic, set(f.tokens))
    seen: dict[str, set[str]] = {}
    unread: list[tuple[str, Found]] = []
    for key, f in unique.items():
        marker = cache.get(conn, "url", key, at=at)
        seen[key] = {str(t) for t in (marker or {}).get("tokens", [])}
        if f.tokens <= seen[key]:
            out.pages_known += 1
        else:
            unread.append((key, f))
    if not unread:
        return True
    unread.sort(key=lambda kf: _rank(conn, kf[1].result.url))  # the most authoritative first
    out.pages_unread += max(0, len(unread) - MAX_READ)
    chosen = unread[:MAX_READ]
    pages = extract_v2.pages_from([f.result for _, f in chosen])
    teams = sorted({int(t.split(":", 1)[1]) for _, f in chosen for t in f.tokens if t.startswith("TEAM:")})
    read_for = {token("TEAM", t) for t in teams} | {token("MATCH", match.fixture_id)}
    key_of = {f.result.url: key for key, f in chosen}
    topic_of = {f.result.url: f.topic for _, f in chosen}
    marked: set[str] = set()

    def mark(keys: Sequence[str]) -> None:  # not read again for these subjects
        for key in keys:
            if key not in marked:
                cache.put(conn, "url", key, {"tokens": sorted(seen[key] | read_for), "read_at": at.isoformat()}, at=at, ttl=EXTRACT_TTL)
                marked.add(key)

    if pages:
        subjects = subjects_for(conn, match, teams, at=at)
        for group in extract_v2.groups(pages):
            if not _extract(conn, settings, match, subjects, group, topic_of, out, at=at, ledger=ledger, provider=provider, transport=transport):
                return False
            mark([key_of[p.url] for p in group])
    mark([key for key, _ in chosen])  # the ones with nothing to read
    return True


def _extract(conn: psycopg.Connection[Any], settings: AiSettings, match: Match, subjects: list[extract_v2.Subject], pages: list[extract_v2.Page],
             topic_of: dict[str, str], out: CollectedV2, *, at: datetime, ledger: UsageLedger, provider: tuple[LlmProvider, str] | None,
             transport: httpx.BaseTransport | None) -> bool:
    """One extraction call over ``pages`` and what it gives rise to. True when the pages are over - read, or discarded for the content of the
    answer; False when the call could not be made or answered (nothing was read)."""
    user = extract_v2.user_message(match.block(), subjects, pages)
    call = call_json(conn, settings, tier="bulk", purpose="evidence_extraction", request=extract_v2.request(user), at=at,
                     prompt_version=EXTRACT_V2_VERSION, input_hash=extract_v2.input_hash(user), fixture_id=match.fixture_id, ledger=ledger,
                     transport=transport, provider=provider, agent=AGENT)
    out.cost_usd += float(call.cost)
    if call.result is None and call.error not in CONTENT_ERRORS:
        out.skipped = call.error
        return False
    out.pages += len(pages)
    out.pages_flagged += sum(1 for p in pages if p.instruction_like)
    if call.result is None:  # the provider could not read the answer or the model refused: the ledger has it; the pages are not asked again
        return True
    reading = extract_v2.read(call.result.data, subjects=subjects, pages=pages)
    if not reading.ok:
        out.invalid += 1  # the provider answered (the ledger says ok) and the answer is not claim-v1: the pages are discarded, not asked again
        return True
    out.kept += len(reading.kept)
    for _, reason in reading.dropped:
        out.drop(reason)
    who = {(s.kind, s.id): s for s in subjects}
    page_of = {p.id: p for p in pages}
    for claim in reading.kept:
        page = page_of[claim.page_id]
        converted = extract_v2.to_evidence(claim, who[(claim.subject_kind, claim.subject_id)], page,
                                           extract_v2.Context(match.fixture_id, match.kickoff_at, at, topic_of[page.url]))
        if converted.item is None:
            out.drop(converted.dropped or "dropped")
            continue
        _, created = store(conn, converted.item, at=at)
        out.extracted += 1
        if created:
            out.created += 1
            if converted.scope == "entity":
                out.stored_entity += 1
            else:
                out.stored_match += 1
    return True


__all__ = ["AGENT", "LEDGER_PREFIX", "CollectedV2", "Match", "collect", "load_match", "refresh", "refresh_for", "subjects_for"]
