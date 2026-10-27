"""Research by entity and topic, read for the Admin Console (plan IA, phase 2). Never a search, never a model call and never a write: the answers are
what research v2 kept in the cache (``ai.research_cache``, scope ``entity``), the claims are what it wrote (``ai.evidence`` with a ``subject_type``),
the passes are what the cycle counted (``ai.fixture_passes.counts``), the spend is the ledger's (``ai.usage``) and the gate is the evaluation of
``fbi.ai.gate_research`` run now - which writes nothing.

This is a reader that chooses research v2's claims on purpose (``subject_type IS NOT NULL``), like the gate: it is the owner's page about v2, and
nothing it reads reaches a packet, a card or a pick. ``tests/unit/test_typed_evidence_guard.py`` lists it.

What the page may say it knows is what is here: how fresh each topic's answers are, how often they were reused instead of searched again, which
classes of source the claims came from and in what state they ended, how many searches v2 needed against what v1 paid, and whether the gate would
let v2 replace v1 today. A part that cannot be computed is an honest sub-answer (``Section``), not a page that breaks."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, get_args

from fbi.ai import cache, gate_research, gates, research
from fbi.ai.calendar import DAY_TZ, day_start, local_day
from fbi.ai.config import AiSettings
from fbi.ai.contracts.claim import ClaimType
from fbi.ai.contracts.mcp import SOURCE_CLASSES
from fbi.ai.entity_research import LEDGER_PREFIX
from fbi.ai.evidence import Status
from fbi.api.contracts.ai_research import (
    AnswerRow,
    ClaimBreakdown,
    Claims,
    Comparison,
    Freshness,
    GateCheckRow,
    GateRow,
    GateView,
    GateWindow,
    PageCache,
    ResearchDay,
    ResearchOverview,
    ResearchSwitch,
    TopicRow,
)
from fbi.api.envelope import DataStatus, Envelope, Section, ok, section
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now

DAYS: Final = 7
"""The window of the figures: a week, the days the gate asks for."""
ANSWERS: Final = 60
"""The most answers the page lists: the newest."""
HISTORY: Final = 5
"""The most rows of the gate the page lists."""
STATUSES: Final = get_args(Status)
CLAIM_TYPES: Final = get_args(ClaimType)

KEY_SHAPE: Final = f"^{cache.KEY_VERSION}:[a-z]+:[0-9]{{1,15}}:[a-z_]+$"
"""What a key of the entity scope looks like: ``rk-v2:<kind>:<id>:<topic>``. A row that does not look like it is counted, never read."""
URL_PREFIX: Final = f"{cache.KEY_VERSION}:url:"

# -- the switch ------------------------------------------------------------------------------------------------------------------------------

GATE_ROWS_SQL = """
SELECT id, at, passed, decided_by, code_version, evidence_hash FROM ai.feature_gates WHERE gate = %(gate)s ORDER BY at DESC, id DESC LIMIT %(limit)s
"""


def switch(conn: Conn, settings: AiSettings) -> ResearchSwitch:
    """The owner's word, what the cycle does with it and why, and the rows of the gate that ``on`` waits for (the newest decides)."""
    described = gates.research_describe(conn, settings)
    state = gates.gate_state(conn, gate_research.GATE)
    return ResearchSwitch(
        asked=described["asked"], mode=described["mode"], why=described["why"], typed_visible=gates.typed_visible(conn, settings),
        gate_passed=state.passed, gate_at=state.at,
        history=[GateRow.model_validate(r) for r in fetch_all(conn, GATE_ROWS_SQL, {"gate": gate_research.GATE, "limit": HISTORY})])


# -- freshness: what the cache holds for each topic ------------------------------------------------------------------------------------------

TOPICS_SQL = """
SELECT split_part(key, ':', 2) AS kind, split_part(key, ':', 4) AS topic, count(*) AS entries,
       count(*) FILTER (WHERE expires_at > %(at)s) AS fresh, COALESCE(sum(hits), 0) AS reuses,
       max(fetched_at) AS newest_at, max(last_hit_at) AS last_reuse_at
  FROM ai.research_cache WHERE scope = 'entity' AND key ~ %(shape)s GROUP BY 1, 2
"""
UNREADABLE_SQL = "SELECT count(*) AS n FROM ai.research_cache WHERE scope = 'entity' AND NOT (key ~ %(shape)s)"


def _hours(x: timedelta) -> float:
    return x.total_seconds() / 3600


def freshness(conn: Conn, *, at: datetime) -> Freshness:
    """Each topic of the research with the rule of its freshness (the code's) and what the cache holds: answers kept, how many can still be reused,
    how often they were. A key this code does not read - another kind, another topic, another shape - is counted apart."""
    kept: dict[str, Counter[str]] = defaultdict(Counter)
    newest: dict[str, datetime] = {}
    last_reuse: dict[str, datetime] = {}
    unreadable = int((fetch_one(conn, UNREADABLE_SQL, {"shape": KEY_SHAPE}) or {}).get("n") or 0)
    for r in fetch_all(conn, TOPICS_SQL, {"at": at, "shape": KEY_SHAPE}):
        topic = str(r["topic"])
        if topic not in research.BY_KEY or str(r["kind"]).upper() not in cache.ENTITY_KINDS:
            unreadable += int(r["entries"])
            continue
        mine = kept[topic]
        mine["entries"] += int(r["entries"])
        mine["fresh"] += int(r["fresh"])
        mine["reuses"] += int(r["reuses"])
        if r["newest_at"] is not None and (topic not in newest or r["newest_at"] > newest[topic]):
            newest[topic] = r["newest_at"]
        if r["last_reuse_at"] is not None and (topic not in last_reuse or r["last_reuse_at"] > last_reuse[topic]):
            last_reuse[topic] = r["last_reuse_at"]
    topics: list[TopicRow] = []
    for t in research.TOPICS:
        early, late = cache.FRESHNESS[t.key]
        mine = kept[t.key]
        topics.append(TopicRow(
            topic=t.key, entity=research.TOPIC_ENTITY[t.key], levels=list(t.levels), label=t.label, early_hours=_hours(early), late_hours=_hours(late),
            entries=mine["entries"], fresh=mine["fresh"], expired=mine["entries"] - mine["fresh"], reuses=mine["reuses"],
            newest_at=newest.get(t.key), last_reuse_at=last_reuse.get(t.key)))
    return Freshness(late_window_hours=_hours(cache.LATE_WINDOW), topics=topics, unreadable=unreadable)


# -- the answers kept, entity by entity ------------------------------------------------------------------------------------------------------

ANSWERS_SQL = """
SELECT split_part(key, ':', 2) AS kind, split_part(key, ':', 3)::bigint AS entity_id, split_part(key, ':', 4) AS topic,
       fetched_at, expires_at, hits, last_hit_at, payload
  FROM ai.research_cache WHERE scope = 'entity' AND key ~ %(shape)s AND fetched_at >= %(since)s ORDER BY fetched_at DESC, key LIMIT %(limit)s
"""
TEAMS_SQL = "SELECT id, name FROM core.teams WHERE id = ANY(%(ids)s)"
MATCHES_SQL = """
SELECT f.id, f.kickoff_at, th.name AS home, ta.name AS away
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id WHERE f.id = ANY(%(ids)s)
"""
CLAIMS_OF_SQL = """
SELECT team_id, fixture_id, count(*) AS n, count(*) FILTER (WHERE fresh_until > %(at)s) AS fresh
  FROM ai.evidence WHERE subject_type IS NOT NULL AND retrieved_at >= %(since)s GROUP BY team_id, fixture_id
"""
"""How many typed claims there are about each team and each match, in the window. A team's include its players' (``team_id`` is the player's side);
a claim about a team in a given match counts for the team and for the match."""


def _int(x: Any) -> int | None:
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def _count(x: Any) -> int:
    """A figure of a counts column as a whole number; anything that is not one (a row put in by hand) is nothing."""
    return _int(x) or 0


def answers(conn: Conn, *, at: datetime, since: datetime) -> list[AnswerRow]:
    """The newest answers kept for an entity on a topic, with the entity named and what its claims are worth."""
    rows = [r for r in fetch_all(conn, ANSWERS_SQL, {"shape": KEY_SHAPE, "since": since, "limit": ANSWERS})
            if str(r["topic"]) in research.BY_KEY and str(r["kind"]).upper() in cache.ENTITY_KINDS]
    team_ids = sorted({int(r["entity_id"]) for r in rows if str(r["kind"]).upper() == "TEAM"})
    match_ids = sorted({int(r["entity_id"]) for r in rows if str(r["kind"]).upper() == "MATCH"})
    teams = {int(r["id"]): str(r["name"]) for r in fetch_all(conn, TEAMS_SQL, {"ids": team_ids})} if team_ids else {}
    matches = {int(r["id"]): r for r in fetch_all(conn, MATCHES_SQL, {"ids": match_ids})} if match_ids else {}
    per_team: Counter[int] = Counter()
    per_team_fresh: Counter[int] = Counter()
    per_match: Counter[int] = Counter()
    per_match_fresh: Counter[int] = Counter()
    for c in fetch_all(conn, CLAIMS_OF_SQL, {"at": at, "since": since}):
        if c["team_id"] is not None:
            per_team[int(c["team_id"])] += int(c["n"])
            per_team_fresh[int(c["team_id"])] += int(c["fresh"])
        if c["fixture_id"] is not None:
            per_match[int(c["fixture_id"])] += int(c["n"])
            per_match_fresh[int(c["fixture_id"])] += int(c["fresh"])
    out: list[AnswerRow] = []
    for r in rows:
        kind, entity_id = str(r["kind"]).upper(), int(r["entity_id"])
        body: dict[str, Any] = r["payload"] if isinstance(r["payload"], dict) else {}
        shown = body.get("classes")
        classes: dict[str, Any] = shown if isinstance(shown, dict) else {}
        match = matches.get(entity_id) if kind == "MATCH" else None
        name = teams.get(entity_id) if kind == "TEAM" else (f"{match['home']} vs {match['away']}" if match is not None else None)
        standing = body.get("standing")
        out.append(AnswerRow(
            kind=kind, id=entity_id, name=name, kickoff_at=None if match is None else match["kickoff_at"], topic=str(r["topic"]),
            level=_int(body.get("level")), results=_int(body.get("results")), standing=standing if isinstance(standing, bool) else None,
            tiers={str(k): n for k, v in classes.items() if (n := _int(v)) is not None}, fetched_at=r["fetched_at"], expires_at=r["expires_at"],
            fresh=r["expires_at"] > at, reuses=int(r["hits"]), last_reuse_at=r["last_hit_at"],
            claims=(per_team if kind == "TEAM" else per_match)[entity_id] if kind in ("TEAM", "MATCH") else 0,
            claims_fresh=(per_team_fresh if kind == "TEAM" else per_match_fresh)[entity_id] if kind in ("TEAM", "MATCH") else 0))
    return out


# -- the claims: class of source, type, status ---------------------------------------------------------------------------------------------

CLAIMS_SQL = """
SELECT COALESCE(source_class, 'UNKNOWN') AS source_class, COALESCE(claim_type, 'OTHER') AS claim_type, status,
       fixture_id IS NULL AS entity_scoped, COALESCE(attributes->>'instruction_like', '') = 'true' AS flagged,
       count(*) AS n, count(*) FILTER (WHERE fresh_until > %(at)s) AS fresh
  FROM ai.evidence WHERE subject_type IS NOT NULL AND retrieved_at >= %(since)s GROUP BY 1, 2, 3, 4, 5
"""


def _breakdown(words: tuple[str, ...], seen: dict[str, Counter[str]], fresh: Counter[str]) -> list[ClaimBreakdown]:
    """One row per word of the vocabulary, in the vocabulary's order, even when nothing was written under it (a class of source that produced
    nothing is a finding); then any word the database holds that the code does not know, never hidden."""
    order = [*words, *sorted(w for w in seen if w not in words)]
    return [ClaimBreakdown(key=w, total=sum(seen.get(w, Counter()).values()), fresh=fresh[w],
                           by_status=dict.fromkeys(STATUSES, 0) | {s: n for s, n in seen.get(w, Counter()).items() if n}) for w in order]


def claims(conn: Conn, *, at: datetime, since: datetime) -> Claims:
    """The typed claims written in the window by class of source and by type of claim, each by the status it ended in."""
    by_class: dict[str, Counter[str]] = defaultdict(Counter)
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    fresh_class: Counter[str] = Counter()
    fresh_type: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    total = fresh = entity_scoped = flagged = 0
    for r in fetch_all(conn, CLAIMS_SQL, {"at": at, "since": since}):
        n, f = int(r["n"]), int(r["fresh"])
        by_class[str(r["source_class"])][str(r["status"])] += n
        by_type[str(r["claim_type"])][str(r["status"])] += n
        fresh_class[str(r["source_class"])] += f
        fresh_type[str(r["claim_type"])] += f
        by_status[str(r["status"])] += n
        total, fresh = total + n, fresh + f
        entity_scoped += n if r["entity_scoped"] else 0
        flagged += n if r["flagged"] else 0
    return Claims(total=total, fresh=fresh, entity_scoped=entity_scoped, match_scoped=total - entity_scoped, flagged=flagged,
                  by_status=dict.fromkeys(STATUSES, 0) | {s: n for s, n in by_status.items() if n},
                  by_class=_breakdown(tuple(SOURCE_CLASSES), by_class, fresh_class), by_type=_breakdown(tuple(CLAIM_TYPES), by_type, fresh_type))


# -- the days: what the passes needed, paid, borrowed and reused ----------------------------------------------------------------------------

PASSES_SQL = "SELECT day, counts FROM ai.fixture_passes WHERE day BETWEEN %(first)s AND %(last)s"
EXA_SQL = """
SELECT (at AT TIME ZONE %(tz)s)::date AS day, COALESCE(left(input_hash, %(n)s) = %(prefix)s, false) AS v2,
       count(*) AS searches, COALESCE(sum(cost_usd), 0) AS usd
  FROM ai.usage WHERE purpose = 'web_search' AND status = 'ok' AND at >= %(since)s GROUP BY 1, 2
"""
DAILY: Final = {"searches": "web_searches", "demand": "v2_demand", "paid": "v2_paid", "shared": "v2_shared", "reused": "v2_reused",
                "pages": "v2_pages", "pages_known": "v2_pages_known", "claims": "v2_claims", "claims_new": "v2_new"}
"""The figure of a day -> the key of the pass's counts it adds up."""


def per_day(conn: Conn, *, first: date, last: date, since: datetime) -> tuple[list[ResearchDay], Counter[str]]:
    """Every day of the window, newest first, with zeros on a day nothing ran (that is a finding too), and the window's totals of what the page
    needs besides (pages left unread, pages that sounded like an order)."""
    days: dict[date, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    for r in fetch_all(conn, PASSES_SQL, {"first": first, "last": last}):
        counts = r["counts"] if isinstance(r["counts"], dict) else {}
        mine = days[r["day"]]
        mine["passes"] += 1
        mine["passes_v2"] += int(gate_research.SHADOW_MARK in counts or gate_research.ON_MARK in counts)
        failed = bool(counts.get("v2_failed"))
        mine["passes_failed"] += int(failed)
        mine["passes_cut"] += int(not failed and any(str(k).startswith("v2_skipped_") for k in counts))
        for name, key in DAILY.items():
            mine[name] += _count(counts.get(key))
        for key in ("v2_pages_unread", "v2_pages_flagged"):
            totals[key] += _count(counts.get(key))
    exa: dict[tuple[date, bool], Decimal] = {}
    for r in fetch_all(conn, EXA_SQL, {"tz": DAY_TZ.key, "prefix": LEDGER_PREFIX, "n": len(LEDGER_PREFIX), "since": since}):
        exa[(r["day"], bool(r["v2"]))] = Decimal(r["usd"])
    out: list[ResearchDay] = []
    for back in range((last - first).days + 1):
        day = last - timedelta(days=back)
        c = days.get(day, Counter())
        out.append(ResearchDay(day=day, passes=c["passes"], passes_v2=c["passes_v2"], passes_failed=c["passes_failed"], passes_cut=c["passes_cut"],
                               searches=c["searches"], demand=c["demand"], paid=c["paid"], shared=c["shared"], reused=c["reused"], pages=c["pages"],
                               pages_known=c["pages_known"], claims=c["claims"], claims_new=c["claims_new"],
                               exa_v1_usd=exa.get((day, False), Decimal(0)), exa_v2_usd=exa.get((day, True), Decimal(0))))
    return out, totals


PAGES_SQL = """
SELECT count(*) AS remembered, count(*) FILTER (WHERE expires_at > %(at)s) AS fresh, COALESCE(sum(hits), 0) AS reuses
  FROM ai.research_cache WHERE scope = 'url' AND key LIKE %(like)s
"""


def pages(conn: Conn, *, at: datetime, days: list[ResearchDay], totals: Counter[str]) -> PageCache:
    """The pages research v2 remembers having read, and what it did with pages in the window."""
    row = fetch_one(conn, PAGES_SQL, {"at": at, "like": URL_PREFIX + "%"}) or {}
    return PageCache(remembered=int(row.get("remembered") or 0), fresh=int(row.get("fresh") or 0), reuses=int(row.get("reuses") or 0),
                     read=sum(d.pages for d in days), known=sum(d.pages_known for d in days), unread=totals["v2_pages_unread"],
                     flagged=totals["v2_pages_flagged"])


# -- v1 against research v2, and the gate -------------------------------------------------------------------------------------------------------

def _pct(x: Any) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def comparison(conn: Conn, *, first: date, last: date) -> Section[Comparison | None]:
    """The gate's own arithmetic over the window of the page: the searches research v2 would have paid on its own against v1's, the facts of v1 it
    found, the Exa spend of each arm and how the extractor fared. Over the passes that ran it beside v1; with none, there is nothing to compare."""
    s = gate_research.searches(conn, first, last)
    if s.passes == 0:
        return section(None, status=DataStatus.EMPTY, reason="no pass of the window ran research v2 beside v1", code="no_v2_passes")
    c = gate_research.coverage(conn, first, last)
    exa = gate_research.spend(conn, first, last)
    ext = gate_research.extractor(conn, first, last)
    a, b = s.as_json(), c.as_json()
    return section(Comparison(
        first=first, last=last, passes_in_shadow=a["passes_in_shadow"], passes_compared=a["passes_compared"], passes_v2_failed=a["passes_v2_failed"],
        passes_v2_cut_short=a["passes_v2_cut_short"], searches_v1=a["searches_v1"], searches_v2_alone=a["searches_v2_alone"], saved=a["saved"],
        saved_pct=_pct(a["saved_pct"]), reuse_pct=_pct(a["reuse_pct"]), fixtures=b["fixtures"], facts_v1=b["facts_v1"], facts_v2=b["facts_v2"],
        found_by_v2=b["found_by_v2"], coverage_pct=_pct(b["coverage_pct"]), coverage_players_pct=_pct(b["coverage_players_pct"]),
        facts_per_match_v1=b["facts_per_match_v1"], facts_per_match_v2=b["facts_per_match_v2"], missed_examples=b["missed_examples"],
        exa_v1_searches=exa["v1"]["searches"], exa_v1_usd=Decimal(exa["v1"]["usd"]), exa_v2_searches=exa["v2"]["searches"],
        exa_v2_usd=Decimal(exa["v2"]["usd"]), extractor_calls=ext["calls"], extractor_by_status=ext["by_status"],
        extractor_invalid_pct=_pct(ext["invalid_pct"])))


def gate(conn: Conn, settings: AiSettings, *, at: datetime) -> Section[GateView | None]:
    """The gate of research v2 evaluated now, over the seven complete days that ended yesterday. Evaluating is reading: the verdict is recorded only by
    ``python -m scripts.ia_research_gate evaluate --record``."""
    report = gate_research.evaluate(conn, settings, at=at)
    return section(GateView(
        verdict=report.verdict, at=report.at, window=GateWindow.model_validate(report.window.as_json()),
        checks=[GateCheckRow(id=k.id, title=k.title, ok=k.ok, mark=k.mark, detail=k.detail, revert=k.revert) for k in report.checks],
        pending=list(report.pending), consequence=report.consequence, preview=report.preview))


def _guarded[T](conn: Conn, work: Callable[[], Section[T | None]], *, code: str) -> Section[T | None]:
    """A part of the page that may fail without taking the rest down: its failure is the sub-answer (``not_available``, the class of the error and
    nothing else - a message can carry a host or a user), inside a savepoint so that a statement that failed does not leave the transaction aborted."""
    try:
        with conn.transaction():
            return work()
    except Exception as exc:
        return section(None, status=DataStatus.NOT_AVAILABLE, reason=f"{code}: {type(exc).__name__}", code=code)


# -- the page --------------------------------------------------------------------------------------------------------------------------------

def overview(conn: Conn, *, at: datetime | None = None, days: int = DAYS, settings: AiSettings | None = None) -> Envelope[ResearchOverview]:
    at = at or now()
    settings = settings or AiSettings.from_env()
    last = local_day(at)
    first = last - timedelta(days=days - 1)
    since = day_start(first)
    rows, totals = per_day(conn, first=first, last=last, since=since)
    return ok(ResearchOverview(
        days=days, since=since, switch=switch(conn, settings), freshness=freshness(conn, at=at), answers=answers(conn, at=at, since=since),
        claims=claims(conn, at=at, since=since), per_day=rows, pages=pages(conn, at=at, days=rows, totals=totals),
        comparison=_guarded(conn, lambda: comparison(conn, first=first, last=last), code="comparison_failed"),
        gate=_guarded(conn, lambda: gate(conn, settings, at=at), code="gate_failed")))
