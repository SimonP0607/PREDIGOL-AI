"""The ingestion of signals (IA-085, plan piece AD-C03): the RSS feeds and sitemaps of the directory v2 read into ``news.items``, planned by
the proximity of the matches, with Exa only for gaps. ``signals-v1``. In SHADOW only: nothing a reader sees reads ``news`` before AD-G07
(behind ``FBI_NEWS_V2``, off).

THE SWITCH - ``FBI_SIGNALS``: ``off`` (default: the worker does not schedule the job) | ``shadow`` (every ``EVERY_MINUTES`` the worker
runs ``run_pass``). Any other word is ``off``.

WHAT A PASS DOES, per feed of the directory (``targets``: the ``rss_url`` of a source, and the sitemap addresses its notes give):

1. The source policy of IA-063 decides FIRST, at the moment of reading (``source_policy.can_fetch``). A source that is blocked, unchecked,
   excluded, not in the directory, reserved from AI, or whose sources disagree about a reservation (``source_select.STRICTER_READINGS``)
   is never read and never planned. A source that is pending of rights - or authorised and not yet signed by the owner - is NOT read
   either: when its feed is due, the pass writes what it WOULD have read (``news.feed_reads``, ``would_read``, no request made) and a
   ``would_block`` row of ``ai.source_policy_log`` (path ``ingest``, action ``fetch``): the «habría leído» of the shadow.
2. Only an authorised and signed source is read, by our own request: robots.txt first (``robots_allows``; one read per host and day;
   a robots.txt that cannot be read counts as forbidding), then the feed with ``If-None-Match`` / ``If-Modified-Since``, an honest
   User-Agent, ten seconds, no retry, no other route ever (no proxy, no other User-Agent, no cache of a third party): a 401, 403, 429 or a
   failure is a failure, and a feed that fails is read less often (``interval``: the double per consecutive failure, at most 7 days).
3. A body whose sha256 is the one already read is not parsed again (``unchanged``). Of a parsed feed, only entries of the source's own
   domain, not older than the newest one already seen, are written - each through ``fbi.news.store.write_item``: idempotent, deduplicated
   by canonical URL and fingerprint, the policy copied into the row. What is written of an entry: its address, its title (as untrusted
   text: ``fbi.ai.untrusted``; flagged when it reads like an order - a flag, never a change of what the pass does), its date, its author.
   Never a body, a description or a picture.
4. The next read is planned by TRANCHE of the nearest match of a team or competition the source covers (``source_select.scope``):
   <= 6 h, 6-36 h, 36 h-7 days, no match (``INTERVALS``); an official source is read more often.

EXA, ONLY FOR GAPS (``plan_exa``): for the matches of the next 36 hours and the claim types that move a pick (injuries, line-ups,
suspensions), a query is planned only when no source readable today with ``confirma`` covers it, only through ``source_select`` (Exa
restricted to the domains of sources that may be read, the query written by the server), at most ``MAX_EXA_PER_MATCH`` per match (below
the 2,0 searches per match of today) and never above 95 % of Exa's envelope. In shadow the plan is COUNTED, not run: this piece spends
nothing.

A BODY is asked only when a title names a team with a match in the next 36 hours (``wants_body``); this piece only counts those
candidates - reading bodies is AD-C05's, with ``can_extract``.

Nothing here reads a key, calls a model, writes ``ai.evidence``, or changes a probability, a threshold, a tier, a pick or what a reader
sees. Only the server writes a query; no text read from a feed changes one."""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai import source_policy, untrusted
from fbi.ai import source_select as ss
from fbi.news import canonical, feeds, store, vocab
from fbi.people.identity.names import alias_key

VERSION: Final = "signals-v1"
SWITCH: Final = "FBI_SIGNALS"
EVERY_MINUTES: Final = int(os.environ.get("FBI_SIGNALS_MINUTES", "15") or 15)
USER_AGENT: Final = "PrediGolSignals/1.0 (reads the RSS feeds and sitemaps of a football news directory; honours robots.txt)"
ROBOTS_AGENT: Final = "predigolsignals"
TIMEOUT_SECONDS: Final = 10.0
PAUSE_SECONDS: Final = 1.0
"""Between two requests to the same host in one pass."""
MAX_FETCHES: Final = 40
"""Requests of one pass (feeds, child sitemaps and robots.txt together); what is left waits for the next pass."""
MAX_CHILD_SITEMAPS: Final = 2
MAX_EXA_PER_MATCH: Final = 1
EXA_SEARCH_USD: Final = Decimal("0.015")
"""What the ledger charges a search (``fbi.ai.budget_v3.EXA_SEARCH_USD``; production: US$ 13,35 for 890 searches, 2-16 Nov 2026)."""
GAP_CLAIMS: Final = ("lesiones", "alineaciones", "sanciones")
LOOKAHEAD: Final = timedelta(days=7)
ROBOTS_TTL: Final = timedelta(hours=24)
INTERVALS: Final[dict[str, tuple[int, int]]] = {"le6h": (30, 60), "6_36h": (120, 180), "36h_7d": (360, 480), "none": (1440, 1440)}
"""Minutes between two reads of a feed, by tranche of its nearest match: (an official source, any other)."""
MAX_INTERVAL: Final = timedelta(days=7)
RETRY_AFTER_MAX: Final = timedelta(days=2)

Mode = Literal["off", "shadow"]
Outcome = Literal["read", "not_modified", "unchanged", "failed", "robots", "would_read"]


def mode(env: Mapping[str, str] | None = None) -> Mode:
    """``FBI_SIGNALS``: only the word ``shadow`` switches the ingestion on; anything else (unset, a typo, ``on``) is ``off``."""
    raw = (os.environ if env is None else env).get(SWITCH, "")
    return "shadow" if raw.strip().lower() == "shadow" else "off"


# ── the feeds of the directory ────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class FeedTarget:
    source_id: str
    domain: str
    name: str
    url: str
    kind: vocab.FeedKind
    official: bool
    lang: str | None
    country: str | None

    @property
    def key(self) -> str:
        return canonical.sha256_hex(self.url)

    @property
    def found_via(self) -> vocab.FoundVia:
        return "rss" if self.kind in ("rss", "atom") else "sitemap"


def targets(catalog: ss.Catalog) -> list[FeedTarget]:
    """Every feed address the directory gives: a source's ``rss_url`` and the sitemaps its notes name, once each."""
    out: dict[str, FeedTarget] = {}
    for s in catalog.sources:
        urls: list[tuple[str, vocab.FeedKind]] = []
        if s.rss_url:
            urls.append((s.rss_url, "rss"))
        for sm in s.sitemaps:
            urls.append((sm, "news_sitemap" if "news" in sm.lower() else "sitemap"))
        for url, kind in urls:
            if url not in out and len(url) <= 2000:
                out[url] = FeedTarget(s.source_id, s.domain, s.name, url, kind, s.official, s.languages[0] if s.languages else None,
                                      s.country_code or None)
    return sorted(out.values(), key=lambda t: (t.source_id, t.url))


def never_read(standing: source_policy.Standing, target: FeedTarget) -> str | None:
    """Why a feed is neither read nor planned, whatever is signed: excluded, blocked, unchecked, unknown, reserved, disputed."""
    if standing.excluded:
        return f"excluded:{standing.rule_class}"
    if standing.state in ss.BLOCKED_STATES:
        return f"state:{standing.state}"
    if standing.hard_reason:
        return standing.hard_reason
    if target.domain in ss.STRICTER_READINGS or (standing.domain or "") in ss.STRICTER_READINGS:
        return "stricter_reading"
    return None


# ── the plan: when is a feed due ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class FeedState:
    """The newest row of ``news.feed_reads`` of a feed."""

    at: datetime
    outcome: str
    etag: str | None
    last_modified: str | None
    body_sha256: str | None
    failures: int
    next_due_at: datetime
    newest_published_at: datetime | None


def interval(band: str, *, official: bool, failures: int = 0) -> timedelta:
    base = timedelta(minutes=INTERVALS.get(band, INTERVALS["none"])[0 if official else 1])
    return min(base * (2 ** min(max(failures, 0), 6)), MAX_INTERVAL) if failures else base


def is_due(state: FeedState | None, at: datetime) -> bool:
    return state is None or state.next_due_at <= at


def nearest_kickoffs(catalog: ss.Catalog, contexts: Iterable[ss.MatchContext], at: datetime) -> dict[str, datetime]:
    """For every source of the scope of an upcoming match, the kick-off of its nearest one."""
    out: dict[str, datetime] = {}
    for ctx in contexts:
        if ctx.kickoff_at < at - timedelta(hours=3):
            continue
        for c in ss.scope(catalog, ctx):
            old = out.get(c.source.source_id)
            if old is None or ctx.kickoff_at < old:
                out[c.source.source_id] = ctx.kickoff_at
    return out


def followed_keys(contexts: Iterable[ss.MatchContext], at: datetime, within: timedelta = timedelta(hours=36)) -> set[frozenset[str]]:
    keys: set[frozenset[str]] = set()
    for ctx in contexts:
        if at - timedelta(hours=3) <= ctx.kickoff_at <= at + within:
            for team in (ctx.home, ctx.away):
                keys |= set(team.keys)
    return keys


def wants_body(title: str | None, followed: Iterable[frozenset[str]]) -> bool:
    """Whether a title names a team with a match soon (all the distinctive words of one of its names): then its body is worth asking
    for - by AD-C05, with ``can_extract``. A name is matched against the title; the title never chooses what is searched."""
    words = set(alias_key(title or "").split())
    return bool(words) and any(k and k <= words for k in followed)


# ── the reader: our own request, robots first ─────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Response:
    status: int | None
    headers: Mapping[str, str]
    body: bytes
    elapsed_ms: int
    error: str | None = None


class Fetcher(Protocol):
    def __call__(self, url: str, headers: Mapping[str, str]) -> Response: ...


def http_fetcher(client: httpx.Client) -> Fetcher:
    """One GET, no retry, no redirect to another host, at most ``feeds.MAX_BYTES``. Never raises: a failure is a response without status."""

    def fetch(url: str, headers: Mapping[str, str]) -> Response:
        start = time.monotonic()
        try:
            with client.stream("GET", url, headers={"User-Agent": USER_AGENT, **headers}, timeout=TIMEOUT_SECONDS,
                               follow_redirects=False) as r:
                chunks: list[bytes] = []
                size = 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > feeds.MAX_BYTES:
                        return Response(r.status_code, dict(r.headers), b"", int((time.monotonic() - start) * 1000), "too_big")
                    chunks.append(chunk)
                return Response(r.status_code, dict(r.headers), b"".join(chunks), int((time.monotonic() - start) * 1000))
        except httpx.HTTPError as exc:
            return Response(None, {}, b"", int((time.monotonic() - start) * 1000), type(exc).__name__)

    return fetch


def _robots_rules(text: str) -> dict[str, list[tuple[str, bool]]]:
    """``user-agent`` -> [(path, allowed)] in order (consecutive agent lines share a group)."""
    groups: dict[str, list[tuple[str, bool]]] = {}
    agents: list[str] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value.lower())
            groups.setdefault(value.lower(), [])
        elif key in ("allow", "disallow") and agents:
            in_rules = True
            if value or key == "allow":
                for a in agents:
                    groups.setdefault(a, []).append((value, key == "allow"))
    return groups


def _rule_matches(rule: str, path: str) -> bool:
    if not rule:
        return False
    pattern = re.escape(rule).replace(r"\*", ".*")
    if pattern.endswith(r"\$"):
        pattern = pattern[:-2] + "$"
    return re.match(pattern, path) is not None


def robots_allows(text: str, url: str, agent: str = ROBOTS_AGENT) -> bool:
    """Whether robots.txt lets our reader read ``url``: our own group if it has one, else ``*``; the longest matching rule wins, and
    a tie goes to ``disallow`` (the stricter reading)."""
    groups = _robots_rules(text)
    rules = next((v for k, v in groups.items() if k != "*" and k and agent.startswith(k.rstrip("*"))), None)
    if rules is None:
        rules = groups.get("*", [])
    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    best: tuple[int, bool] | None = None
    for rule, allowed in rules:
        if _rule_matches(rule, path):
            cand = (len(rule), allowed)
            if best is None or cand[0] > best[0] or (cand[0] == best[0] and not allowed):
                best = cand
    return True if best is None else best[1]


_robots_cache: dict[str, tuple[datetime, int | None, str]] = {}


def reset_robots_cache() -> None:
    _robots_cache.clear()


def robots_verdict(fetch: Fetcher, url: str, at: datetime, counter: list[int]) -> tuple[bool, str]:
    """(allowed, why). robots.txt is read once per host and day; a 404 allows, anything else that is not a 200 forbids."""
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    cached = _robots_cache.get(host)
    if cached is None or at - cached[0] > ROBOTS_TTL:
        counter[0] += 1
        r = fetch(f"{host}/robots.txt", {})
        cached = (at, r.status, r.body.decode("utf-8", "replace")[:500_000] if r.status == 200 else "")
        _robots_cache[host] = cached
    status, text = cached[1], cached[2]
    if status == 404:
        return True, "robots_absent"
    if status != 200:
        return False, f"robots_unreadable:{status}"
    return (True, "robots_allows") if robots_allows(text, url) else (False, "robots_disallows")


# ── the database: states, rows ────────────────────────────────────────────────────────────────────────────────────────────────

STATE_SQL: Final = """
SELECT DISTINCT ON (url_sha256) url_sha256, at, outcome, etag, last_modified, body_sha256, failures, next_due_at, newest_published_at
  FROM news.feed_reads ORDER BY url_sha256, at DESC, id DESC
"""
UPCOMING_SQL: Final = ss.CONTEXT_SELECT + """
 WHERE c.is_tracked AND f.kickoff_at BETWEEN %(since)s AND %(until)s
   AND coalesce(f.status_group, '') NOT IN ('finished', 'cancelled', 'postponed')
 ORDER BY f.kickoff_at LIMIT 800
"""
READ_COLUMNS: Final = ("feed_id", "url_sha256", "source_id", "at", "mode", "outcome", "reason", "http_status", "etag", "last_modified",
                       "body_sha256", "bytes", "elapsed_ms", "entries", "created", "new_versions", "unchanged", "refused",
                       "newest_published_at", "failures", "band", "next_due_at", "reader_version", "registry_version")
INSERT_READ: Final = (f"INSERT INTO news.feed_reads ({', '.join(READ_COLUMNS)}) VALUES ({', '.join(['%s'] * len(READ_COLUMNS))}) "
                      "RETURNING id")


def latest_states(conn: psycopg.Connection[Any]) -> dict[str, FeedState]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STATE_SQL)
        return {str(r["url_sha256"]): FeedState(r["at"], str(r["outcome"]), r["etag"], r["last_modified"], r["body_sha256"],
                                                int(r["failures"]), r["next_due_at"], r["newest_published_at"]) for r in cur.fetchall()}


def upcoming_contexts(conn: psycopg.Connection[Any], at: datetime, lookahead: timedelta = LOOKAHEAD) -> list[ss.MatchContext]:
    """The tracked matches from three hours ago to ``lookahead`` ahead, with the names of their teams (read only)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(UPCOMING_SQL, {"since": at - timedelta(hours=3), "until": at + lookahead})
        rows = cur.fetchall()
    ids = sorted({int(r["home_id"]) for r in rows} | {int(r["away_id"]) for r in rows})
    aliases = ss.team_aliases(conn, ids) if ids else {}
    return [ss.context_from_row(r, aliases) for r in rows]


@dataclass
class ReadRow:
    outcome: Outcome
    band: str
    next_due_at: datetime
    reason: str | None = None
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    body_sha256: str | None = None
    bytes: int | None = None
    elapsed_ms: int | None = None
    entries: int = 0
    created: int = 0
    new_versions: int = 0
    unchanged: int = 0
    refused: int = 0
    newest_published_at: datetime | None = None
    failures: int = 0


def write_read(conn: psycopg.Connection[Any], feed_id: int, target: FeedTarget, row: ReadRow, *, at: datetime,
               registry_version: str) -> int:
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(INSERT_READ, (feed_id, target.key, target.source_id, at, "shadow", row.outcome, (row.reason or None) and row.reason[:120],
                                  row.http_status, (row.etag or None) and row.etag[:500],
                                  (row.last_modified or None) and row.last_modified[:100], row.body_sha256, row.bytes, row.elapsed_ms,
                                  row.entries, row.created, row.new_versions, row.unchanged, row.refused, row.newest_published_at,
                                  row.failures, row.band, row.next_due_at, VERSION, registry_version[:200]))
        new = cur.fetchone()
        assert new is not None
        return int(new[0])


# ── one feed ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Report:
    mode: str
    at: datetime
    registry_version: str = "unavailable"
    skipped: str | None = None
    targets: int = 0
    never: dict[str, int] = field(default_factory=dict)
    due: int = 0
    not_due: int = 0
    deferred: int = 0
    would_read: int = 0
    readable: int = 0
    requests: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    items: dict[str, int] = field(default_factory=dict)
    foreign: int = 0
    older: int = 0
    instruction_like: int = 0
    body_candidates: int = 0
    bands: dict[str, int] = field(default_factory=dict)
    exa: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add(self, bucket: dict[str, int], key: str, n: int = 1) -> None:
        bucket[key] = bucket.get(key, 0) + n

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "mode": self.mode, "at": self.at.isoformat(), "registry_version": self.registry_version,
                "skipped": self.skipped, "targets": self.targets, "never": dict(sorted(self.never.items())), "due": self.due,
                "not_due": self.not_due, "deferred": self.deferred, "would_read": self.would_read, "readable": self.readable,
                "requests": self.requests, "outcomes": dict(sorted(self.outcomes.items())), "items": dict(sorted(self.items.items())),
                "foreign": self.foreign, "older": self.older, "instruction_like": self.instruction_like,
                "body_candidates": self.body_candidates, "bands": dict(sorted(self.bands.items())), "exa": self.exa,
                "errors": self.errors[:10]}


def _own(url: str, domain: str) -> bool:
    host = source_policy.host_of(url) or ""
    return host == domain or host.endswith("." + domain)


def _retry_after(headers: Mapping[str, str], at: datetime) -> timedelta | None:
    raw = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if raw is None:
        return None
    try:
        return min(timedelta(seconds=max(0, int(raw.strip()))), RETRY_AFTER_MAX)
    except ValueError:
        return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next((v for k, v in headers.items() if k.lower() == name), None)


def read_feed(conn: psycopg.Connection[Any], target: FeedTarget, state: FeedState | None, *, band: str, at: datetime,
              policy: source_policy.SourcePolicy, fetch: Fetcher, followed: set[frozenset[str]], report: Report,
              counter: list[int], feed_id: int | None = None) -> ReadRow:
    """One authorised feed: robots, the conditional request, the entries into ``news.items``. Returns the row for ``news.feed_reads``."""
    failures = 0 if state is None else state.failures

    def failed(outcome: Outcome, reason: str, status: int | None = None, wait: timedelta | None = None) -> ReadRow:
        n = failures + 1
        step = interval(band, official=target.official, failures=n)
        return ReadRow(outcome, band, at + max(step, wait or timedelta(0)), reason=reason, http_status=status, failures=n,
                       etag=None if state is None else state.etag, last_modified=None if state is None else state.last_modified,
                       body_sha256=None if state is None else state.body_sha256,
                       newest_published_at=None if state is None else state.newest_published_at)

    allowed, why = robots_verdict(fetch, target.url, at, counter)
    if not allowed:
        return failed("robots", why)
    headers: dict[str, str] = {}
    if state is not None and state.etag:
        headers["If-None-Match"] = state.etag
    if state is not None and state.last_modified:
        headers["If-Modified-Since"] = state.last_modified
    counter[0] += 1
    r = fetch(target.url, headers)
    next_ok = at + interval(band, official=target.official)
    etag, modified = _header(r.headers, "etag"), _header(r.headers, "last-modified")
    if r.status == 304:
        return ReadRow("not_modified", band, next_ok, http_status=304, elapsed_ms=r.elapsed_ms,
                       etag=etag or (None if state is None else state.etag),
                       last_modified=modified or (None if state is None else state.last_modified),
                       body_sha256=None if state is None else state.body_sha256,
                       newest_published_at=None if state is None else state.newest_published_at)
    if r.status != 200 or r.error:
        return failed("failed", r.error or f"http_{r.status}", r.status, _retry_after(r.headers, at))
    digest = hashlib.sha256(r.body).hexdigest()
    if state is not None and state.body_sha256 == digest:
        return ReadRow("unchanged", band, next_ok, http_status=200, etag=etag, last_modified=modified, body_sha256=digest,
                       bytes=len(r.body), elapsed_ms=r.elapsed_ms, newest_published_at=state.newest_published_at)
    try:
        parsed = feeds.parse(r.body)
        entries = list(parsed.entries)
        for child in parsed.children[:MAX_CHILD_SITEMAPS]:
            if not _own(child, target.domain) or counter[0] >= MAX_FETCHES:
                continue
            counter[0] += 1
            cr = fetch(child, {})
            if cr.status == 200 and not cr.error:
                entries.extend(feeds.parse(cr.body).entries)
    except feeds.FeedError as exc:
        return failed("failed", f"parse:{str(exc)[:80]}", r.status)
    row = ReadRow("read", band, next_ok, http_status=200, etag=etag, last_modified=modified, body_sha256=digest, bytes=len(r.body),
                  elapsed_ms=r.elapsed_ms, entries=len(entries))
    newest = None if state is None else state.newest_published_at
    seen_newest = newest
    for e in entries:
        if not _own(e.url, target.domain):
            report.foreign += 1
            continue
        published = e.published_at if e.published_at is not None and e.published_at <= at else None
        if published is not None and newest is not None and published < newest:
            report.older += 1
            continue
        title = untrusted.sanitize(e.title or "", origin=target.domain, max_chars=300) if e.title else None
        if title is not None and title.instruction_like:
            report.instruction_like += 1
        shown = title.text if title is not None and title.text else None
        if wants_body(shown, followed):
            report.body_candidates += 1
        article = store.Article(url=e.url, source_name=target.name, fingerprint_text=shown or e.url, seen_at=at, found_via=target.found_via,
                                written_by=VERSION, source_title=shown, author=e.author, lang=e.lang or target.lang, published_at=published,
                                published_day_only=published is not None and e.day_only,
                                published_structured=published is not None and e.structured, feed_id=feed_id)
        written = store.write_item(conn, article, policy)
        report.add(report.items, written.outcome)
        if written.outcome == "created":
            row.created += 1
        elif written.outcome == "new_version":
            row.new_versions += 1
        elif written.outcome == "unchanged":
            row.unchanged += 1
        else:
            row.refused += 1
        if published is not None and (seen_newest is None or published > seen_newest):
            seen_newest = published
    row.newest_published_at = seen_newest
    return row


# ── Exa, only for gaps (planned, never run here) ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ExaPlan:
    matches: int
    covered: int
    queries: tuple[tuple[int | None, ss.ExaQuery], ...]
    would_if_signed: int
    allowance: str

    def as_json(self) -> dict[str, Any]:
        n = len(self.queries)
        return {"matches_36h": self.matches, "covered_by_feeds": self.covered, "queries": n, "per_match": round(n / self.matches, 3)
                if self.matches else 0.0, "usd": str(EXA_SEARCH_USD * n), "would_if_signed": self.would_if_signed,
                "allowance": self.allowance, "baseline_per_match": 2.0, "executed": 0}


def plan_exa(contexts: Sequence[ss.MatchContext], catalog: ss.Catalog, policy: source_policy.SourcePolicy | None, *, at: datetime,
             exa: ss.ExaAllowance | None = None, claims: Sequence[str] = GAP_CLAIMS) -> ExaPlan:
    """The targeted Exa queries the matches of the next 36 hours would need: per match and claim type, none when a source readable
    today with ``confirma`` covers it; at most ``MAX_EXA_PER_MATCH`` per match. Pure: nothing is searched."""
    allowance = exa or ss.ExaAllowance.closed()
    queries: list[tuple[int | None, ss.ExaQuery]] = []
    matches = covered = would = 0
    for ctx in contexts:
        if ss.band(ctx.kickoff_at, at) not in ("le6h", "6_36h"):
            continue
        matches += 1
        mine: list[ss.ExaQuery] = []
        fed = 0
        for claim in claims:
            sel = ss.select(ctx, claim, at=at, policy=policy, catalog=catalog, exa=allowance, max_exa=1)
            if any(p.as_fact and p.authority == "confirma" and p.via in ("rss", "sitemap", "official") for p in sel.picks):
                fed += 1
                continue
            would += sum(1 for p in sel.picks if p.as_fact and p.would_via == "exa")
            mine.extend(sel.exa)
        covered += int(fed == len(claims))
        queries.extend((ctx.fixture_id, q) for q in mine[:MAX_EXA_PER_MATCH])
    return ExaPlan(matches, covered, tuple(queries), would, allowance.reason if not allowance.allowed else "ok")


# ── one pass ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _log_would(conn: psycopg.Connection[Any], target: FeedTarget, standing: source_policy.Standing, reason: str, *, at: datetime,
               registry_version: str) -> None:
    event = source_policy.Event("fetch", "would_block", reason, False, target.url, standing)
    screened = source_policy.Screened([], [event], source_policy.policy_mode(), source_policy.exclusion_mode(), registry_version)
    source_policy.record(conn, screened, at=at, path="ingest")


def run_pass(conn: psycopg.Connection[Any], *, at: datetime, fetch: Fetcher | None = None,
             policy: source_policy.SourcePolicy | None = None, catalog: ss.Catalog | None = None,
             contexts: Sequence[ss.MatchContext] | None = None, exa: ss.ExaAllowance | None = None, max_fetches: int = MAX_FETCHES,
             commit: bool = True, sleep: Callable[[float], None] = time.sleep, env: Mapping[str, str] | None = None) -> Report:
    """One pass over the feeds of the directory (see the module). Does nothing unless ``FBI_SIGNALS=shadow``; without a registry it reads
    nothing (closed on failure). ``commit`` after each feed (the worker); the tests keep one transaction."""
    report = Report(mode(env), at)
    if report.mode != "shadow":
        report.skipped = "off"
        return report
    pol = policy if policy is not None else source_policy.load(conn)
    if pol is None:
        report.skipped = "registry_unavailable"
        return report
    report.registry_version = pol.version
    cat = catalog or ss.catalog_for(conn, pol)
    ctxs = list(contexts) if contexts is not None else upcoming_contexts(conn, at)
    nearest = nearest_kickoffs(cat, ctxs, at)
    followed = followed_keys(ctxs, at)
    states = latest_states(conn)
    all_targets = targets(cat)
    report.targets = len(all_targets)
    counter = [0]
    last_host: dict[str, float] = {}
    order = sorted(all_targets, key=lambda t: (nearest.get(t.source_id) is None, nearest.get(t.source_id) or at, not t.official, t.url))
    for t in order:
        standing = pol.standing(t.url)
        why_never = never_read(standing, t)
        if why_never is not None:
            report.add(report.never, why_never.split(":", 1)[0])
            continue
        state = states.get(t.key)
        band = ss.band(nearest.get(t.source_id), at)
        report.add(report.bands, band)
        if not is_due(state, at):
            report.not_due += 1
            continue
        report.due += 1
        fetchable = source_policy.can_fetch(standing)
        try:
            feed = store.write_feed(conn, store.Feed(url=t.url, kind=t.kind, source_id=t.source_id, source_domain=standing.domain or t.domain,
                                                     at=at, added_by="system", lang=t.lang, country=t.country,
                                                     reason="IA-085: the directory v2 gives this feed"))
            assert feed.id is not None
            if not fetchable.allowed:
                row = ReadRow("would_read", band, at + interval(band, official=t.official), reason=fetchable.reason[:120],
                              failures=0 if state is None else state.failures)
                write_read(conn, feed.id, t, row, at=at, registry_version=pol.version)
                _log_would(conn, t, standing, fetchable.reason, at=at, registry_version=pol.version)
                report.would_read += 1
            elif counter[0] >= max_fetches:
                report.deferred += 1
                continue
            else:
                report.readable += 1
                host = urlsplit(t.url).netloc
                wait = PAUSE_SECONDS - (time.monotonic() - last_host.get(host, -1e9))
                if wait > 0:
                    sleep(wait)
                row = read_feed(conn, t, state, band=band, at=at, policy=pol, fetch=fetch or _no_network, followed=followed,
                                report=report, counter=counter, feed_id=feed.id)
                last_host[host] = time.monotonic()
                write_read(conn, feed.id, t, row, at=at, registry_version=pol.version)
            report.add(report.outcomes, row.outcome)
            if commit:
                conn.commit()
        except (psycopg.Error, ValueError) as exc:
            report.errors.append(f"{t.source_id}:{type(exc).__name__}:{str(exc)[:120]}")
            if commit:
                conn.rollback()
    report.requests = counter[0]
    report.exa = plan_exa(ctxs, cat, pol, at=at, exa=exa).as_json()
    return report


def _no_network(url: str, headers: Mapping[str, str]) -> Response:
    """The default of a pass without a fetcher: nothing is asked (a pass from the worker always hands its own client)."""
    return Response(None, {}, b"", 0, "no_fetcher")


__all__ = ["EVERY_MINUTES", "MAX_EXA_PER_MATCH", "SWITCH", "USER_AGENT", "VERSION", "ExaPlan", "FeedState", "FeedTarget", "Fetcher",
           "ReadRow", "Report", "Response", "http_fetcher", "interval", "is_due", "latest_states", "mode", "nearest_kickoffs",
           "never_read", "plan_exa", "read_feed", "reset_robots_cache", "robots_allows", "robots_verdict", "run_pass", "targets",
           "upcoming_contexts", "wants_body", "write_read"]
