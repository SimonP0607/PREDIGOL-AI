"""The unified deep research (IA-087 + IA-088 + IA-089; plan pieces AD-C05, AD-C06, AD-C07) - IN SHADOW: one road instead of Research v1
and v2, nothing of it reaches a reader, a packet, a status, a gate or a pick.

WHY. Two researches run side by side today. ``research-v1`` (``extract-v1``) reads six pages in one call with no door; Research v2 (``extract-v3``)
reads the first 700 characters of six pages in one call, about at most 30 players a team, and recovered 23,1 % of what v1 found (gate
``research_v2``, row 17, 12 Nov 2026: NO PASA - that row is kept as it is). Of the 987 facts v2 lost, 747 were lost in the EXTRACTION and 24
in the search (RV2, 12 Nov). This road is what the plan puts in their place, measured beside them before anything depends on it.

THE ROAD, for one pass of one match (``collect``) - it never searches and never pays for a search:

    the pages the pass already has            -> the answers v1 and research v2 cached for the levels of the pass (``cache.peek``: read, not
                                                 counted as a reuse, so their own comparison does not move)
    each page                                 -> the source's standing (``fbi.ai.source_policy``): a reserved or excluded source is never read
                                                 clean text (``deep_pages.clean``: no repeated title, no lines the domain prints on every page)
                                                 its fingerprint: a page extracted once (by any match, under any address) is NOT paid again
                                                 the windows that name a candidate (``deep_pages.choose`` with ``fbi.ai.mentions``, the whole
                                                 squad and its aliases: the prefilter; a page that names nobody is not asked about)
                                                 the door and the check for orders, window by window (``fbi.ai.quarantine``): a window with
                                                 an order taints the WHOLE page, which is never sent
    a page a model MAY read                   -> ONE call for the page (``extract-v4``, ``claim-v2``, agent ``quarantine_extractor``, in the
                                                 LAB): its windows, the subjects they name; what stands is checked again by ``name-match-v2``
                                                 and must sit in ONE window; claims of a line-up or a list of absentees are grouped by code
                                                 (``LIST``, a quote of up to 600 characters) - the model's contract does not change
    what stood                                -> typed assertions (``fbi.ai.assertions``): authority per type of claim, the ladder by origin,
                                                 four dates, contradictions (alerts, never corrections)
    the comparison                            -> the facts v1 and research v2 wrote for the same match: how many of their players the whole
                                                 squad can name (and the 30 of v2), how many sit in the windows chosen, how many this road found

**Which page may be read by a model.** Only one the directory v2 lists as ``verificada_autorizada`` AND the owner signed
(``source_policy.can_extract``), whatever ``FBI_SOURCE_POLICY`` says: the plan's rule for anything new. On 16 Nov 2026 that is 3 sources of
2.001, none signed - so in production this road makes NO model call today, and its measure is the code's: the windows, the links, the
ceiling. The limit is the rights, not the technique.

**Where it writes** (and nothing else): the pass's counts (``xu_*`` in ``ai.fixture_passes.counts``); the page it extracted, once per
fingerprint, in ``ai.research_cache`` (scope ``url``, key ``rk-u1:page:<fp>``: no reader, no packet and no gate reads that prefix - the cache of
research v2 is ``rk-v2:url:`` and v1's ``<fixture>:<url>``); a call in ``ai.usage`` (the LAB's workspace, ``input_hash`` ``rk-u1:...``). Never
``ai.evidence``: v1's rows (``subject_type IS NULL``) and v2's stay exactly as they are.

**The switch** ``FBI_AI_RESEARCH_UNIFIED`` (``off`` by default: production does what it does today; ``shadow``: this road after the research
of the pass). Its calls are capped per day (``FBI_AI_RESEARCH_UNIFIED_MAX_PER_DAY``, 60) and paid by the LAB's envelope.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

import httpx
import psycopg
from psycopg.rows import dict_row

from fbi.ai import (
    assertions,
    cache,
    commands,
    deep_pages,
    mentions,
    quarantine,
    source_policy,
    untrusted,
)
from fbi.ai.calendar import day_start, local_day
from fbi.ai.collectors import LATE_WINDOW, levels_wanted, queries_for, query_for_sides, search_key
from fbi.ai.config import AiSettings
from fbi.ai.contracts.claim_v2 import SUBJECT_REFS
from fbi.ai.evidence import domain_of
from fbi.ai.providers.base import LlmProvider
from fbi.ai.usage import UsageLedger, call_json
from fbi.analyst.search import SearchResult

VERSION: Final = "research-unified-v1"
KEY_PREFIX: Final = "rk-u1:page:"
LEDGER_PREFIX: Final = "rk-u1:"
PAGE_TTL: Final = timedelta(days=30)
"""How long a page extracted is remembered by its fingerprint: within it, the page is never paid again (whatever match or address asks)."""
LIST_TYPES: Final = {"OUT": "LIST_OUT", "SUSPENSION": "LIST_OUT", "STARTER": "LIST_STARTER"}
LIST_MIN: Final = 3
LIST_QUOTE_MAX: Final = 600
MAX_LISTED: Final = len(SUBJECT_REFS)
SEPARATOR: Final = "\n\n[…]\n\n"
"""What stands between two windows of one page in the message. A quote must sit inside ONE window: a quote across it does not stand."""
KICKOFF_ZONES: Final = ("UTC", "America/Bogota", "America/Argentina/Buenos_Aires", "America/Sao_Paulo", "America/Mexico_City",
                        "Europe/London", "Europe/Madrid", "Europe/Istanbul")
"""The zones a kick-off time is written in for ``CO1`` (an official time that differs from the provider's). A page in another zone can raise
a false alert: an alert is never a correction."""
LOOKBACK: Final = timedelta(hours=36)
"""The comparison reads the facts v1 and research v2 wrote for the match this long before the pass."""

Ask = quarantine.Ask


# ── the catalogue: the whole squad, its aliases, the coach ─────────────────────────────────────────────────────────

ROSTER_SQL: Final = """
WITH roster AS (
    SELECT m.provider_player_id, 'squad' AS src FROM core.squad_members m WHERE m.team_id = %(team)s
    UNION ALL
    SELECT s.provider_player_id, 'season' FROM core.player_season_stats s
     WHERE %(provider_team)s::int IS NOT NULL AND s.provider_team_id = %(provider_team)s AND s.season = %(season)s AND s.observed_at <= %(at)s
    UNION ALL
    SELECT lp.provider_player_id, 'lineup' FROM core.fixture_lineup_players lp JOIN core.fixtures f ON f.id = lp.fixture_id
     WHERE ((lp.team_side = 'home' AND f.home_team_id = %(team)s) OR (lp.team_side = 'away' AND f.away_team_id = %(team)s))
       AND f.kickoff_at <= %(at)s AND f.kickoff_at > %(at)s - interval '120 days'
    UNION ALL
    SELECT t.provider_player_id, 'transfer' FROM core.player_transfers t
     WHERE %(provider_team)s::int IS NOT NULL AND t.team_in_id = %(provider_team)s AND t.observed_at <= %(at)s
       AND t.transfer_date > (%(at)s::timestamptz - interval '400 days')::date
)
SELECT r.provider_player_id, array_agg(DISTINCT r.src ORDER BY r.src) AS sources, max(p.id) AS player_id, max(p.name) AS name,
       max(p.firstname) AS firstname, max(p.lastname) AS lastname, max(m.player_name) AS squad_name,
       (SELECT lp.player_name FROM core.fixture_lineup_players lp WHERE lp.provider_player_id = r.provider_player_id
         AND lp.player_name IS NOT NULL LIMIT 1) AS lineup_name
  FROM roster r
  LEFT JOIN core.players p ON p.provider_player_id = r.provider_player_id
  LEFT JOIN core.squad_members m ON m.provider_player_id = r.provider_player_id AND m.team_id = %(team)s
 GROUP BY r.provider_player_id
"""
COACH_SQL: Final = """
SELECT l.coach_name FROM core.fixture_lineups l JOIN core.fixtures f ON f.id = l.fixture_id
 WHERE ((l.team_side = 'home' AND f.home_team_id = %(team)s) OR (l.team_side = 'away' AND f.away_team_id = %(team)s))
   AND l.coach_name IS NOT NULL AND l.fetched_at <= %(at)s
 ORDER BY f.kickoff_at DESC LIMIT 1
"""
ALIASES_SQL: Final = """
SELECT entity_type, entity_id, alias FROM core.entity_aliases_live
 WHERE (entity_type = 'player' AND entity_id = ANY(%(players)s)) OR (entity_type = 'team' AND entity_id = ANY(%(teams)s))
 ORDER BY entity_type, entity_id, alias
"""
VENUES_SQL: Final = """
SELECT DISTINCT venue_name FROM core.fixtures
 WHERE (home_team_id = ANY(%(teams)s) OR away_team_id = ANY(%(teams)s)) AND venue_name IS NOT NULL
   AND kickoff_at > %(at)s - interval '365 days' AND kickoff_at < %(at)s + interval '30 days'
"""


def _aliases(conn: psycopg.Connection[Any], players: Sequence[int], teams: Sequence[int]) -> dict[tuple[str, int], list[str]]:
    """Our ids -> the aliases in force (``core.entity_aliases_live``, AD-H02). Empty on a database that does not have it yet."""
    out: dict[tuple[str, int], list[str]] = {}
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT to_regclass('core.entity_aliases_live') IS NOT NULL AS ok")
            row = cur.fetchone()
            if not row or not row["ok"]:
                return out
            cur.execute(ALIASES_SQL, {"players": list(players), "teams": list(teams)})
            for r in cur.fetchall():
                out.setdefault((str(r["entity_type"]), int(r["entity_id"])), []).append(str(r["alias"]))
    except psycopg.Error:
        return {}
    return out


@dataclass(frozen=True, slots=True)
class Roster:
    catalogue: mentions.Catalogue
    persons: tuple[quarantine.Person, ...]
    """The same people as ``quarantine.Person`` (the provider's name, through the door): what ``quarantine.read`` checks homonyms against."""
    capped: frozenset[int]
    """The provider ids research v2 would list (its 30 a team): for the comparison only."""
    venue: str | None
    venues: tuple[str, ...]


def roster_for(conn: psycopg.Connection[Any], match: Any, *, at: datetime) -> Roster:
    """The catalogue of a match (``match`` is ``entity_research.Match``): the two teams with their aliases and their coach, and every player of
    either squad - the squad lists, the season, the line-ups of the last 120 days (the latest call-up of a national team), signings and loans
    of the last 400 days, the provider's absences - with their names and aliases. No cap."""
    from fbi.ai.absences import absences_as_of
    from fbi.ai.entity_research import players_of

    rows: dict[int, dict[str, Any]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for team in match.teams:
            cur.execute(ROSTER_SQL, {"team": team.id, "provider_team": team.provider_id, "season": match.season, "at": at})
            for r in cur.fetchall():
                rows.setdefault(int(r["provider_player_id"]), {**r, "team": team})
        coaches: dict[int, str] = {}
        for team in match.teams:
            cur.execute(COACH_SQL, {"team": team.id, "at": at})
            c = cur.fetchone()
            if c and c["coach_name"]:
                coaches[team.id] = str(c["coach_name"])
        cur.execute("SELECT venue_name FROM core.fixtures WHERE id = %s", (match.fixture_id,))
        v = cur.fetchone()
        cur.execute(VENUES_SQL, {"teams": [t.id for t in match.teams], "at": at})
        venues = tuple(str(r["venue_name"]) for r in cur.fetchall())
    for a in absences_as_of(conn, match.fixture_id, at):
        team = next((t for t in match.teams if t.provider_id is not None and a["provider_team_id"] == t.provider_id), None)
        if team is not None and a.get("player_name"):
            rows.setdefault(int(a["provider_player_id"]), {"provider_player_id": a["provider_player_id"], "sources": ["absence"],
                                                           "player_id": None, "name": a["player_name"], "team": team})
    aliases = _aliases(conn, [int(r["player_id"]) for r in rows.values() if r.get("player_id")], [t.id for t in match.teams])
    candidates: list[mentions.Candidate] = []
    persons: list[quarantine.Person] = []
    for t in match.teams:
        names = [t.name, *aliases.get(("team", t.id), [])]
        candidates.append(mentions.Candidate("TEAM", t.id, t.id, tuple(dict.fromkeys(names)), t.side))
        p = quarantine.person("TEAM", t.id, t.name, team_id=t.id, side=t.side)
        if p is not None:
            persons.append(p)
        if t.id in coaches:
            candidates.append(mentions.Candidate("COACH", t.id, t.id, (coaches[t.id],), t.side, ("lineup",)))
    for pid, r in sorted(rows.items()):
        team = r["team"]
        first_last = f"{r.get('firstname') or ''} {r.get('lastname') or ''}".strip()
        names = [n for n in (r.get("name"), r.get("squad_name"), r.get("lineup_name"), first_last) if n]
        if r.get("player_id"):
            names.extend(aliases.get(("player", int(r["player_id"])), []))
        clean = [untrusted.sanitize(n, origin="provider", max_chars=quarantine.NAME_CHARS, version=quarantine.DOOR) for n in names]
        names = [c.text for c in clean if c.text and not c.instruction_like]
        if not names:
            continue
        candidates.append(mentions.Candidate("PLAYER", pid, team.id, tuple(dict.fromkeys(names)), team.side,
                                             tuple(r.get("sources") or ())))
        p = quarantine.person("PLAYER", pid, names[0], team_id=team.id, side=team.side)
        if p is not None:
            persons.append(p)
    capped = frozenset(pid for t in match.teams for pid, _ in players_of(conn, match, t, at=at))
    context = [match.competition or "", *(venues or ()), *([str(v["venue_name"])] if v and v["venue_name"] else [])]
    return Roster(mentions.Catalogue.of(candidates, context_names=context), tuple(quarantine.catalogue_of(persons)), capped,
                  str(v["venue_name"]) if v and v["venue_name"] else None, venues)


# ── the pages the pass already has ────────────────────────────────────────────────────────────────────────────────

def pages_for(conn: psycopg.Connection[Any], match: Any, *, at: datetime, levels: int | Sequence[int]) -> list[SearchResult]:
    """The results v1 and research v2 have in the search cache for this match and these levels, without a page twice (by canonical address).
    Read with ``cache.peek``: nothing is searched, nothing is counted as a reuse."""
    bucket = "late" if match.kickoff_at - at <= LATE_WINDOW else "early"
    wanted = levels_wanted(levels)
    keys: list[str] = []
    for level, query in zip(wanted, queries_for(match.home.name, match.away.name, match.kickoff_at, match.country, match.competition,
                                                levels=wanted), strict=True):
        keys.append(search_key(query, bucket, level))
        for side in ("home", "away"):
            q = query_for_sides(level, (side,), home=match.home.name, away=match.away.name, kickoff=match.kickoff_at, country=match.country,
                                competition=match.competition)
            keys.append(search_key(q, bucket, level))
    out: list[SearchResult] = []
    seen: set[str] = set()
    for key in dict.fromkeys(keys):
        payload = cache.peek(conn, "search", key, at=at)
        for hit in (payload or {}).get("results") or []:
            if not isinstance(hit, dict) or not hit.get("url"):
                continue
            try:
                canon = cache.canonical_url(str(hit["url"]))
            except ValueError:
                continue
            if canon in seen:
                continue
            seen.add(canon)
            out.append(SearchResult(str(hit["url"]), str(hit.get("title") or ""), str(hit.get("publisher") or ""), hit.get("published_at"),
                                    str(hit.get("retrieved_at") or ""), str(hit.get("snippet") or "")))
    return out


# ── one page ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Claim:
    """A claim that stood, as the page cache keeps it (never the model's words but the quote, and the quote only for a source whose facts may
    be stored)."""

    kind: str
    id: int
    team_id: int
    type: str
    applies_to: str
    window: int
    quote: str
    speaker: str | None = None

    def as_json(self, *, keep_quote: bool) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "team_id": self.team_id, "type": self.type, "applies_to": self.applies_to,
                "window": self.window, "quote": self.quote if keep_quote else "", "speaker": self.speaker}


@dataclass
class PageRead:
    """What the road did with one page."""

    url: str
    domain: str
    outcome: str
    """``blocked_<reason>``, ``empty``, ``unnamed``, ``tainted``, ``not_authorised``, ``reused``, ``capped``, ``failed``, ``invalid``, ``read``."""
    fp: str | None = None
    windows: list[deep_pages.Window] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    lists: list[dict[str, Any]] = field(default_factory=list)
    dropped: Counter[str] = field(default_factory=Counter)
    cost: float = 0.0
    simhash: int | None = None

    @property
    def subjects(self) -> frozenset[tuple[str, int]]:
        return frozenset(s for w in self.windows for s in w.subjects)


def _squash(text: str) -> str:
    return " ".join(text.split())


def taint_of(result: SearchResult, text: str, windows: Sequence[deep_pages.Window]) -> tuple[str, ...]:
    """Why a page is never sent (``fbi.ai.quarantine`` invariant 2), judged on the WHOLE page - its title, its raw text, its clean text through
    the door - and on every window: an order anywhere taints the page, even outside the windows that would be sent."""
    domain = domain_of(result.url) or "unknown"
    reasons: set[str] = set()
    pieces = [SearchResult(result.url, result.title, result.publisher, result.published_at, result.retrieved_at, w.text) for w in windows]
    for piece in pieces or [result]:
        reasons.update(set(quarantine.window_of(piece).taint) - {"empty"})
    whole = untrusted.sanitize(text, origin=domain, max_chars=deep_pages.PAGE_CHARS, version=quarantine.DOOR)
    reasons.update(quarantine.TAINT_FLAGS.intersection(whole.flags))
    if quarantine.hides_markup(result.snippet) or quarantine.hides_markup(result.title):
        reasons.add("hidden_markup")
    raw = result.snippet if isinstance(result.snippet, str) else ""
    if any(commands.command_like(piece) for piece in (raw, text, whole.text, whole.read) if piece):
        reasons.add("command_like")
    return tuple(sorted(reasons))


def sent_window(result: SearchResult, windows: Sequence[deep_pages.Window]) -> tuple[quarantine.Window, list[str]]:
    """The page as the message carries it: its title and its windows through the door, one after the other with ``SEPARATOR``; and the text
    of each window as it was sent (a quote must be inside one)."""
    domain = domain_of(result.url) or "unknown"
    title = untrusted.sanitize(result.title, origin=domain, max_chars=quarantine.TITLE_CHARS, version=quarantine.DOOR)
    parts = [untrusted.sanitize(w.text, origin=domain, max_chars=deep_pages.WINDOW_CHARS, version=quarantine.DOOR) for w in windows]
    flags = tuple(sorted(set(title.flags).union(*(set(p.flags) for p in parts))))
    texts = [p.text for p in parts]
    return (quarantine.Window(result.url, domain, title.text, SEPARATOR.join(texts), result.published_at, flags,
                              title.truncated or any(p.truncated for p in parts), ()), [title.text, *texts])


def listing(windows: Sequence[deep_pages.Window], roster: Roster) -> list[quarantine.Listed]:
    """The subjects of the call: the teams and the players the windows name (``name-match-v2``), in the order they first appear, each under
    the name the page uses for him when it is one of his (an alias in another script), at most ``MAX_LISTED``."""
    order: list[tuple[str, int]] = []
    for w in windows:
        for m in w.mentions:
            key = (m.who.kind, m.who.id)
            if m.who.kind in ("TEAM", "PLAYER") and key not in order:
                order.append(key)
    order.sort(key=lambda k: k[0] != "TEAM")
    text = " ".join(w.text for w in windows)
    present = set(mentions.words(text))
    out: list[quarantine.Listed] = []
    for kind, ident in order[:MAX_LISTED]:
        who = roster.catalogue.by_key(kind, ident)
        if who is None:
            continue
        shown = next((n for n in who.names if mentions.surname_of(n) in present or set(mentions.words(n)) <= present), who.name)
        p = quarantine.person(kind, ident, shown, team_id=who.team_id, side=who.side or "home")  # type: ignore[arg-type]
        if p is not None:
            out.append(quarantine.Listed(SUBJECT_REFS[len(out)], p))
    return out


def lists_of(claims: Sequence[Claim], texts: Sequence[str]) -> list[dict[str, Any]]:
    """Line-ups and lists of absentees, grouped by code: at least ``LIST_MIN`` players of one team with the same type in one window, whose quotes
    sit in one passage of at most ``LIST_QUOTE_MAX`` characters of it. The model's contract has no list: the server writes it from what stood."""
    groups: dict[tuple[str, int, int], list[Claim]] = {}
    for c in claims:
        if c.kind == "PLAYER" and c.type in LIST_TYPES:
            groups.setdefault((LIST_TYPES[c.type], c.team_id, c.window), []).append(c)
    out: list[dict[str, Any]] = []
    for (kind, team_id, window), members in sorted(groups.items()):
        if len({m.id for m in members}) < LIST_MIN or window + 1 >= len(texts):
            continue
        text = _squash(texts[window + 1])
        spots = [(text.find(_squash(m.quote)), len(_squash(m.quote))) for m in members]
        if any(s < 0 for s, _ in spots):
            continue
        lo, hi = min(s for s, _ in spots), max(s + n for s, n in spots)
        if hi - lo > LIST_QUOTE_MAX:
            continue
        out.append({"type": kind, "team_id": team_id, "window": window, "players": sorted({m.id for m in members}), "quote": text[lo:hi]})
    return out


def read_page(result: SearchResult, roster: Roster, *, match_block: Mapping[str, Any], standing: source_policy.Standing,
              common: frozenset[str], ask: Ask | None, known: Callable[[str], dict[str, Any] | None],
              new_call: Callable[[], str] = quarantine.new_call) -> PageRead:
    """One page through the road (pure but for ``ask`` and ``known``, the page cache). ``ask`` None: no call may be made (the day's cap, no LAB
    envelope) and a page that could be read is counted ``capped``."""
    domain = domain_of(result.url) or "unknown"
    if standing.hard_reason or standing.excluded:
        return PageRead(result.url, domain, f"blocked_{standing.hard_reason or 'excluded'}")
    text = deep_pages.clean(result.title, result.snippet if isinstance(result.snippet, str) else "", common=common)
    fp = deep_pages.fingerprint(text)
    if fp is None:
        return PageRead(result.url, domain, "empty")
    page = PageRead(result.url, domain, "unnamed", fp, simhash=deep_pages.simhash(text))
    page.windows = deep_pages.choose(text, roster.catalogue)
    if not page.windows:
        return page
    if taint_of(result, text, page.windows):
        page.outcome = "tainted"
        return page
    stored = known(fp)
    if stored is not None:
        page.outcome = "reused"
        page.claims = [Claim(str(c["kind"]), int(c["id"]), int(c["team_id"]), str(c["type"]), str(c["applies_to"]), int(c["window"]),
                             str(c.get("quote") or ""), c.get("speaker")) for c in stored.get("claims") or []]
        page.lists = list(stored.get("lists") or [])
        return page
    if not source_policy.can_extract(standing).allowed:
        page.outcome = "not_authorised"
        return page
    if ask is None:
        page.outcome = "capped"
        return page
    listed = listing(page.windows, roster)
    if not listed:
        page.outcome = "unnamed"
        return page
    window, texts = sent_window(result, page.windows)
    code = new_call()
    while any(code in t for t in texts):
        code = new_call()
    user = quarantine.user_message(match_block, listed, window, code)
    asked = ask(quarantine.request(user), LEDGER_PREFIX + quarantine.input_hash(user, code)[:58])
    page.cost = asked.cost
    if asked.data is None and asked.error not in quarantine.CONTENT_ERRORS:
        page.outcome = "failed"
        return page
    if asked.data is None:
        page.outcome = "invalid"
        return page
    reading = quarantine.read(asked.data, call=code, listed=listed, window=window, catalogue=roster.persons)
    if not reading.ok:
        page.outcome = "invalid"
        page.dropped.update(f"whole_{p}" for p in reading.problems[:1])
        return page
    page.outcome = "read"
    page.dropped.update(r for _, r in reading.dropped)
    for kept in reading.kept:
        who = roster.catalogue.by_key(kept.who.kind, kept.who.id)
        if who is None:
            page.dropped["not_in_catalogue"] += 1
            continue
        why = mentions.validate(kept.quote, who, roster.catalogue)
        if why is not None:
            page.dropped[f"nm2_{why}"] += 1
            continue
        inside = [i for i, t in enumerate(texts[1:]) if _squash(kept.quote) in _squash(t)]
        in_title = _squash(kept.quote) in _squash(texts[0])
        if not inside and not in_title:
            page.dropped["quote_across_windows"] += 1
            continue
        named_players = [m.who.id for m in mentions.mentions_in(kept.quote, roster.catalogue) if m.who.kind == "PLAYER"]
        page.claims.append(Claim(who.kind, who.id, who.team_id, kept.claim.claim_type, kept.claim.applies_to, inside[0] if inside else -1,
                                 kept.quote, assertions.speaker_of(kept.quote, team_id=who.team_id, players=named_players)))
    page.lists = lists_of(page.claims, texts)
    return page


# ── the pass ──────────────────────────────────────────────────────────────────────────────────────────────────────

V1_SQL: Final = """
SELECT DISTINCT provider_player_id, attributes->>'player_name' AS player_name, team_id, attributes->>'assertion' AS assertion, kind
  FROM ai.evidence
 WHERE fixture_id = %(fixture)s AND origin = 'web' AND subject_type IS NULL AND kind IN ('injury', 'doubtful', 'suspension', 'lineup')
   AND retrieved_at <= %(at)s AND retrieved_at > %(since)s
"""
V2_SQL: Final = """
SELECT DISTINCT subject_id AS provider_player_id, attributes->>'player_name' AS player_name, team_id, attributes->>'assertion' AS assertion, kind
  FROM ai.evidence
 WHERE subject_type IS NOT NULL AND subject_type = 'PLAYER' AND origin = 'web' AND (fixture_id = %(fixture)s OR (fixture_id IS NULL AND team_id = ANY(%(teams)s)))
   AND retrieved_at <= %(at)s AND retrieved_at > %(since)s
"""
CALLS_TODAY_SQL: Final = "SELECT count(*) FROM ai.usage WHERE agent = %(agent)s AND input_hash LIKE %(like)s AND at >= %(since)s"


@dataclass
class Outcome:
    counts: Counter[str] = field(default_factory=Counter)
    cost_usd: float = 0.0
    pages: list[PageRead] = field(default_factory=list)
    facts: list[assertions.Fact] = field(default_factory=list)
    alerts: list[assertions.Alert] = field(default_factory=list)
    skipped: str | None = None


def calls_today(conn: psycopg.Connection[Any], at: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(CALLS_TODAY_SQL, {"agent": quarantine.AGENT, "like": LEDGER_PREFIX + "%", "since": day_start(local_day(at))})
        row = cur.fetchone()
    return int(row[0]) if row else 0


def page_key(fp: str) -> str:
    return KEY_PREFIX + fp[:40]


def _remember(conn: psycopg.Connection[Any], page: PageRead, standing: source_policy.Standing, *, fixture_id: int, at: datetime,
              published_at: str | None, old: dict[str, Any] | None) -> None:
    """The page cache: written once per fingerprint when the page was read; a later reading of the same fingerprint (another match, another
    address) only adds its match and its address - ``first_seen_at`` is never rewritten."""
    assert page.fp is not None
    keep = source_policy.can_store(standing) == "facts"
    if old is None:
        body: dict[str, Any] = {
            "v": VERSION, "fp": page.fp, "first_seen_at": at.isoformat(), "extracted_at": at.isoformat(), "domain": page.domain,
            "published_at": published_at, "simhash": str(page.simhash or 0), "windows": len(page.windows),
            "subjects": sorted(f"{k}:{i}" for k, i in page.subjects), "store": "facts" if keep else "link",
            "claims": [c.as_json(keep_quote=keep) for c in page.claims],
            "lists": [{**x, "quote": x["quote"] if keep else ""} for x in page.lists], "dropped": dict(sorted(page.dropped.items())),
            "urls": [page.url], "read_for": [fixture_id], "first_fixture": fixture_id}
    else:
        body = dict(old)
        if page.url in body.get("urls", []) and fixture_id in body.get("read_for", []):
            return
        body["urls"] = sorted({*body.get("urls", []), page.url})[:20]
        body["read_for"] = sorted({*body.get("read_for", []), fixture_id})[-50:]
    cache.put(conn, "url", page_key(page.fp), body, at=at, ttl=PAGE_TTL)


def _kickoff_times(kickoff: datetime) -> set[str]:
    out = set()
    for zone in KICKOFF_ZONES:
        try:
            out.add(kickoff.astimezone(ZoneInfo(zone)).strftime("%H:%M"))
        except Exception:  # a zone the image does not have: one fewer way to write the time
            continue
    return out


def _compare(conn: psycopg.Connection[Any], match: Any, roster: Roster, pages: Sequence[PageRead], out: Outcome, *, at: datetime) -> None:
    """The comparison, in the pass's counts: of the players v1 (``xu_v1_*``) and research v2 (``xu_v2_*``) wrote a fact about for this match,
    how many the whole squad names (``full``), how many v2's thirty name (``capped``), how many sit in a window this road chose (``windows``)
    and how many this road has a claim about (``found``)."""
    teams = [t.id for t in match.teams]
    windowed = {i for p in pages for k, i in p.subjects if k == "PLAYER"}
    claimed = {c.id for p in pages for c in p.claims if c.kind == "PLAYER"} | {i for p in pages for x in p.lists for i in x["players"]}
    with conn.cursor(row_factory=dict_row) as cur:
        for arm, sql in (("v1", V1_SQL), ("v2", V2_SQL)):
            cur.execute(sql, {"fixture": match.fixture_id, "teams": teams, "at": at, "since": at - LOOKBACK})
            players: set[tuple[int | None, str]] = set()
            for r in cur.fetchall():
                players.add((None if r["provider_player_id"] is None else int(r["provider_player_id"]), str(r["player_name"] or "")))
            seen: set[int | str] = set()
            for pid, name in players:
                linked = pid if pid is not None and roster.catalogue.by_key("PLAYER", pid) is not None else None
                if linked is None and name:
                    found = [m.who.id for m in mentions.mentions_in(name, roster.catalogue) if m.who.kind == "PLAYER"]
                    linked = found[0] if len(found) == 1 else None
                ident: int | str = linked if linked is not None else (pid if pid is not None else f"name:{' '.join(mentions.words(name))}")
                if ident in seen:
                    continue
                seen.add(ident)
                out.counts[f"xu_{arm}_players"] += 1
                if linked is None:
                    continue
                out.counts[f"xu_{arm}_full"] += 1
                out.counts[f"xu_{arm}_capped"] += int(linked in roster.capped)
                out.counts[f"xu_{arm}_windows"] += int(linked in windowed)
                out.counts[f"xu_{arm}_found"] += int(linked in claimed)


def collect(conn: psycopg.Connection[Any], settings: AiSettings, fixture_id: int, *, at: datetime, levels: int | Sequence[int] = 1,
            ledger: UsageLedger | None = None, provider: tuple[LlmProvider, str] | None = None, transport: httpx.BaseTransport | None = None,
            policy: source_policy.SourcePolicy | None = None, results: Sequence[SearchResult] | None = None) -> Outcome:
    """The unified research of one match for one pass, in shadow. ``results``: the pages (a test, a replay); by default the ones v1 and
    research v2 cached for this pass's levels. ``policy``: the source policy (by default the one in force)."""
    from fbi.ai.entity_research import load_match

    out = Outcome()
    match = load_match(conn, fixture_id, at=at)
    if match is None:
        out.skipped = "no_such_fixture"
        return out
    policy = policy if policy is not None else source_policy.load(conn)
    found = list(results) if results is not None else pages_for(conn, match, at=at, levels=levels)
    roster = roster_for(conn, match, at=at)
    out.counts["xu_candidates"] = len(roster.catalogue.players)
    out.counts["xu_candidates_beyond_30"] = sum(1 for c in roster.catalogue.players if c.id not in roster.capped)
    ledger = ledger or UsageLedger()
    budget_left = max(0, settings.unified_max_per_day - calls_today(conn, at))
    block = quarantine.match_block(match.fixture_id, match.home.name, match.away.name, match.kickoff_at.isoformat(), match.competition)

    def ask(req: Any, h: str) -> quarantine.Asked:
        call = call_json(conn, settings, tier="bulk", purpose="evidence_extraction", request=req, at=at, prompt_version=quarantine.VERSION,
                         input_hash=h, fixture_id=fixture_id, ledger=ledger, transport=transport, provider=provider, lab=True,
                         agent=quarantine.AGENT)
        return quarantine.Asked(None if call.result is None else call.result.data, call.error, float(call.cost))

    common = deep_pages.common_lines((domain_of(r.url) or "unknown", r.snippet or "") for r in found)
    stored: dict[str, dict[str, Any] | None] = {}

    def known(fp: str) -> dict[str, Any] | None:
        if fp not in stored:
            stored[fp] = cache.peek(conn, "url", page_key(fp), at=at)
        return stored[fp]

    seen_fp: set[str] = set()
    stopped = False
    for r in found:
        st = policy.standing(r.url) if policy is not None else source_policy.Standing(None, None, source_policy.UNKNOWN)
        if policy is None:
            out.counts["xu_blocked_registry_unavailable"] += 1
            continue
        calls = out.counts["xu_calls"]
        page = read_page(r, roster, match_block=block, standing=st, common=common.get(domain_of(r.url) or "unknown", frozenset()),
                         ask=None if stopped or calls >= budget_left else ask, known=known)
        out.pages.append(page)
        out.counts["xu_pages"] += 1
        out.counts[f"xu_page_{page.outcome}"] += 1
        out.counts["xu_windows"] += len(page.windows)
        out.cost_usd += page.cost
        if page.fp is not None and page.fp in seen_fp:
            out.counts["xu_same_fp_in_pass"] += 1
        if page.fp is not None:
            seen_fp.add(page.fp)
        if page.outcome in ("read", "invalid"):
            out.counts["xu_calls"] += 1
        if page.outcome == "failed":
            stopped = True  # a call that could not be made (budget, outage): no other page is tried in this pass
        for reason, n in page.dropped.items():
            out.counts[f"xu_drop_{reason}"[:60]] += n
        out.counts["xu_claims"] += len(page.claims)
        out.counts["xu_lists"] += len(page.lists)
        if page.outcome in ("read", "invalid", "reused") and page.fp is not None:
            _remember(conn, page, st, fixture_id=fixture_id, at=at, published_at=r.published_at, old=stored.get(page.fp))
            stored[page.fp] = cache.peek(conn, "url", page_key(page.fp), at=at)
    _ladder(match, roster, out, policy=policy, at=at, stored=stored)
    _compare(conn, match, roster, out.pages, out, at=at)
    return out


def _ladder(match: Any, roster: Roster, out: Outcome, *, policy: source_policy.SourcePolicy | None, at: datetime,
            stored: Mapping[str, dict[str, Any] | None]) -> None:
    """The typed assertions of what this road found for the match, their rungs and their alerts (counts ``xu_rung_*``, ``xu_alert_*``)."""
    items: list[assertions.Assertion] = []
    names = {t.id: [n for c in roster.catalogue.teams if c.id == t.id for n in c.names] for t in match.teams}
    for page in out.pages:
        if page.fp is None or not page.claims:
            continue
        body = stored.get(page.fp) or {}
        seen = _stamp(body.get("first_seen_at")) or at
        published = _stamp(body.get("published_at"))
        src = assertions.source_facts(policy, page.url)
        for c in page.claims:
            if c.applies_to == "THIS_MATCH" and int(body.get("first_fixture") or match.fixture_id) != match.fixture_id:
                continue  # about the match the page was first read for, not this one
            level, why = assertions.authority_for(src, c.type, team_names=names.get(c.team_id, []), quote=c.quote)
            pub, origin, seen_at, fact_at, until = assertions.four_dates(published_at=published, seen_at=seen, kickoff_at=match.kickoff_at,
                                                                          applies_to=c.applies_to, claim_type=c.type)
            items.append(assertions.Assertion(c.kind, c.id, c.team_id, c.type, page.url, src, level, why, seen_at, pub, origin, fact_at,
                                              until, c.applies_to, match.fixture_id, c.speaker, page.simhash, c.quote))
    out.facts = assertions.facts(items, at=at)
    for f in out.facts:
        out.counts[f"xu_rung_{f.rung}"] += 1
    out.alerts = assertions.contradictions(items, at=at, kickoff_times=_kickoff_times(match.kickoff_at), venue=roster.venue,
                                           venues=roster.venues)
    for a in out.alerts:
        out.counts[f"xu_alert_{a.rule}"] += 1


def _stamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def describe(payload: Mapping[str, Any]) -> str:
    """A page of the cache as one line for the owner's report (counts and ids, never a quote)."""
    return json.dumps({k: payload.get(k) for k in ("fp", "domain", "windows", "store", "read_for")} |
                      {"claims": len(payload.get("claims") or []), "lists": len(payload.get("lists") or [])}, ensure_ascii=False)


__all__ = ["KEY_PREFIX", "LEDGER_PREFIX", "VERSION", "Claim", "Outcome", "PageRead", "Roster", "collect", "listing", "lists_of", "pages_for",
           "read_page", "roster_for", "sent_window", "taint_of"]
