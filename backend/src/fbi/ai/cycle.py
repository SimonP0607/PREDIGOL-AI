"""The AI analysis cycle (worker job ``ai_cycle`` every 15 minutes, ``ai_day_start`` at 00:05 Bogotá, and the
owner's "run now").

Two parts, one loop over the matches of the next four days:

FREE, for every match of the horizon: the provider's injury reports and line-ups as evidence (next 48 h), the
shortlist (every selection passing the value gate at the current price, ``fbi.picks.daily.passing``), the packet
when its inputs changed, the rules' review of every shortlisted selection and the per-match analysis cards
(``fbi.ai.analysis``). No model, no search.

PAID, only for TODAY's matches (Bogotá) that HAVE A MARKET, at their passes (``fbi.ai.day``: first from 00:05, pre
6-4 h before, final after the line-ups):

    L1  brief    every match of the day at each of its passes, when its input changed - the economical model, or
                 the rules when no model may answer (``fbi.ai.brief``); the brief comes first and says whether the
                 match escalates
    web          first pass: the candidates' matches - the daily set's own order first (``web_rank``) - and the most
                 important ones (FBI_AI_MAX_WEB_FIRST); pre pass: the escalated ones (FBI_AI_MAX_WEB_PRE) - only when
                 the cached answer is stale
    L2  review   the candidates of the day (intermediate model), again only after a material change (the price
                 moved more than 3 %, new evidence, the line-ups); an escalated match without a candidate gets at
                 most one review of its nearest-to-value selection (a watch, FBI_AI_MAX_WATCH_PER_DAY)
    L3  review   the strong model only for the best potential picks: the top five candidates of the day (one per
                 match), the picks of the day, the parlays' legs, a candidate whose match is contradictory or has
                 important news, and an L2 review the rules contradict outright

Between its passes a match is analysed for free and keeps its last model review while it is in force. Money: the
day's state (``fbi.ai.usage``) and each pass's share of the day. One cycle at a time (an advisory lock), so the same
analysis is never paid twice by two runs.

Commits after each step that paid: a failure part-way keeps what was done and is recorded in ``ai.cycles``. Nothing
here writes a pick, a probability, a parlay or a rule.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai import entity_research, gates, research
from fbi.ai.analysis import ValueOption, build_cards, store_analysis
from fbi.ai.batch import CYCLE_LOCK, BatchClient, BatchQueue, abandon_unsent, open_counts
from fbi.ai.brief import Brief, make_brief
from fbi.ai.calendar import day_bounds, day_start, local_day
from fbi.ai.collectors import SearchFn, collect_provider, collect_web
from fbi.ai.config import AiSettings, Tier
from fbi.ai.day import Due, due_passes, open_day, universe
from fbi.ai.evidence import seed_sources
from fbi.ai.packet import CORE_KEYS, Packet, PacketBuilder, store_packet
from fbi.ai.prompts import REVIEW_VERSION
from fbi.ai.providers.base import LlmProvider
from fbi.ai.review import (
    Candidate,
    Deferral,
    Reviewed,
    carried_review,
    latest_reviews,
    review_candidate,
)
from fbi.ai.usage import UsageLedger, check_alerts
from fbi.ai.usage import budget as budget_of
from fbi.core.clock import now
from fbi.picks.daily import RISK, Ranked, load_candidates, passing

log = structlog.get_logger(__name__)

SHORTLIST_HORIZON = timedelta(hours=72)
EVIDENCE_HORIZON = timedelta(hours=48)
MAX_FIXTURES = 400
CARRY_FOR = timedelta(hours=12)
"""A model review is carried (combined again, not paid again) this long after it was made, while nothing material
changed."""
PRICE_CHANGE = Decimal("0.03")
FAR_REFRESH = timedelta(hours=3)
"""A match more than a day away with nothing shortlisted: its packet is looked at again only after this long."""
NEAR_REFRESH = timedelta(hours=1)
"""Within the day, a match with nothing shortlisted: hourly (a shortlisted one is looked at every cycle)."""
TOP_L3 = 5
TRANSIENT = frozenset({"timeout", "unavailable", "rate_limited", "failed"})
"""A provider error that says nothing about the input: the provider is down for the rest of the cycle, and the pass is
tried again at the next one (what was paid is reused through its input hash, never paid twice)."""
NEAR_VALUE_EV = Decimal("-0.02")
"""A watch review is made only for a selection this close to value at the current price."""

NEWEST_PACKETS_SQL = """
SELECT DISTINCT ON (fixture_id) fixture_id, as_of FROM ai.match_packets
 WHERE fixture_id = ANY(%(fixtures)s) ORDER BY fixture_id, as_of DESC, id DESC
"""

FIXTURES_SQL = """
SELECT f.id, f.kickoff_at FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at > %(start)s AND f.kickoff_at <= %(until)s
 ORDER BY f.kickoff_at, f.id LIMIT %(limit)s
"""

LAST_LLM_SQL = """
SELECT DISTINCT ON (r.market_key, r.selection, r.line) r.id, r.market_key, r.selection, r.line, r.reviewed_at, r.odds,
       r.evidence_ids, r.status, r.decision, r.output, r.engine_version, r.input_hash, r.provider, r.model
  FROM ai.pick_reviews r
 WHERE r.fixture_id = %(fixture)s AND r.engine = 'llm' AND r.status IN ('ok', 'invalid_output')
 ORDER BY r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""

USED_TODAY_SQL = """
SELECT count(*) FILTER (WHERE r.engine = 'llm' AND r.status NOT IN ('over_budget', 'failed')
                        AND NOT r.output ? 'reused_from') AS llm,
       count(*) FILTER (WHERE r.engine = 'llm' AND r.model IS NOT NULL AND r.output->>'tier' = 'final'
                        AND r.status <> 'failed' AND NOT r.output ? 'reused_from') AS deep,
       count(*) FILTER (WHERE r.engine = 'llm' AND r.output->>'role' = 'watch' AND r.status NOT IN ('over_budget', 'failed')
                        AND NOT r.output ? 'reused_from') AS watch
  FROM ai.pick_reviews r WHERE r.reviewed_at >= %(day)s
"""

WEB_USED_SQL = """
SELECT pass, count(*) FROM ai.fixture_passes
 WHERE day = %(day)s AND COALESCE((counts->>'web_searches')::int, 0) > 0 GROUP BY pass
"""

L3_TARGETS_SQL = """
SELECT i.fixture_id, i.market_key, i.selection, i.line FROM picks.daily_set_items i
  JOIN picks.daily_sets s ON s.id = i.set_id WHERE s.day = %(day)s
UNION
SELECT l.fixture_id, l.market_key, l.selection, l.line FROM picks.parlay_legs l
  JOIN picks.parlays p ON p.id = l.parlay_id
 WHERE p.day = %(day)s OR (p.window_from < %(end)s AND p.window_to >= %(start)s)
"""

PASS_SQL = """
INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, escalated, reasons, brief_id,
                               packet_id, counts, cost_usd)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (fixture_id, day, pass) DO NOTHING
"""

UNSENT_FIXTURES_SQL = """
SELECT DISTINCT fixture_id FROM ai.batch_items
 WHERE purpose = 'pick_review' AND created_at = %(at)s AND status = 'abandoned' AND fixture_id IS NOT NULL
"""
"""The matches whose reviews THIS cycle recorded for a Message Batch that then was not sent (it could not be created, or the record
outlived the request body): their pass is not done."""

ESCALATED_SQL = """
SELECT DISTINCT ON (fixture_id) fixture_id, escalate, content -> 'research' AS research FROM ai.match_briefs
 WHERE fixture_id = ANY(%(fixtures)s) ORDER BY fixture_id, created_at DESC, id DESC
"""
"""The latest brief of each match: whether it escalated and what it asked the server to look into (``fbi.ai.research``)."""


@dataclass
class CycleReport:
    cycle_id: int | None = None
    status: str = "ok"
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cost_usd: Decimal = Decimal(0)
    errors: list[str] = field(default_factory=list)
    detail: dict[str, Any] | None = None
    """What the cycle writes in ``counts`` when it is more than counts: the orchestrator's report (counts and codes, plain JSON). None - every
    other kind of cycle - writes ``counts`` as before."""


def open_cycle(conn: psycopg.Connection[Any], kind: str, *, at: datetime, settings: AiSettings) -> int:
    b = budget_of(conn, at=at, settings=settings)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.cycles (kind, started_at, mode, budget_state) VALUES (%s, %s, %s, %s) RETURNING id",
                    (kind, at, settings.mode, b.state))
        row = cur.fetchone()
    assert row is not None
    conn.commit()
    return int(row[0])


def close_cycle(conn: psycopg.Connection[Any], cycle_id: int, report: CycleReport, *, at: datetime) -> None:
    conn.rollback()  # whatever the last match left half-done is not part of the record
    with conn.cursor(row_factory=tuple_row) as cur:
        counts = dict(report.counts) if report.detail is None else report.detail
        cur.execute("UPDATE ai.cycles SET finished_at = %s, status = %s, counts = %s, cost_usd = %s, error = %s "
                    "WHERE id = %s", (max(at, now()), report.status, Jsonb(counts),
                                      report.cost_usd, "; ".join(report.errors)[:500] or None, cycle_id))
    conn.commit()


def recover_interrupted(conn: psycopg.Connection[Any], *, before: datetime, at: datetime) -> tuple[int, int]:
    """Cycles and "run now" requests a stopped worker left running, closed as failed. Returns (cycles, requests).

    Only the worker runs them, so at its start nothing opened before it can still be running. A restart part-way
    left the row 'running' for ever - the dashboard showed a cycle in progress hours later (9 Oct 2026, cycle 87,
    stopped by the 13:00 UTC restart). What the cycle paid for was committed step by step and stays.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("UPDATE ai.cycles SET status = 'failed', finished_at = %s, error = %s "
                    "WHERE status = 'running' AND started_at < %s",
                    (max(at, before), "interrupted: the worker stopped before the cycle finished", before))
        cycles = cur.rowcount
        cur.execute("UPDATE ai.run_requests SET status = 'failed' WHERE status = 'running' AND picked_at < %s",
                    (before,))
        requests = cur.rowcount
    conn.commit()
    return max(cycles, 0), max(requests, 0)


def candidate_of(x: Ranked, packet_models: dict[str, Any]) -> Candidate:
    c, r = x.leg.candidate, x.row
    p_high: Decimal | None = None
    for s in (packet_models.get(r.get("model") or "") or {}).get("selections", []):
        if s["market"] == c.market_key and s["selection"] == c.selection and Decimal(s["line"]) == c.line \
                and s.get("p_hi") is not None:
            p_high = Decimal(str(s["p_hi"]))
    return Candidate(fixture_id=c.fixture_id, market_key=c.market_key, selection=c.selection, line=c.line,
                     p_model=c.p_model, kickoff_at=c.kickoff_at, pick_id=c.pick_id, odds=c.price,
                     bookmaker_id=r.get("bookmaker_id"), bookmaker=r.get("bookmaker"), p_low=x.p_low, p_high=p_high,
                     p_push=c.p_push, p_market=c.p_market_fair, ev=x.leg.ev, model=r.get("model"),
                     n_bookmakers=c.n_bookmakers, price_at=c.price_at)


def value_option(x: Ranked) -> ValueOption:
    c, r = x.leg.candidate, x.row
    assert c.price is not None and c.p_market_fair is not None
    return ValueOption(c.market_key, c.selection, c.line, c.price, r.get("bookmaker"), c.p_model, x.p_low,
                       c.p_market_fair, x.leg.ev, x.elg, r.get("model"), c.pick_id, c.qualified)


def watch_candidate(packet: Packet) -> Candidate | None:
    """The main selection of a match nearest to value at the current price (the model above the market, the expected
    value not below -2 %), for a watch review; None when there is none."""
    content = packet.content
    market = {(s["market"], s["selection"], Decimal(s["line"])): s for s in (content.get("market") or {}).get("selections", [])}
    models = content.get("models") or {}
    name = "dixon_coles" if "dixon_coles" in models else next(iter(models), None)
    if name is None:
        return None
    best: tuple[Decimal, Candidate] | None = None
    kickoff = datetime.fromisoformat(str((content.get("fixture") or {}).get("kickoff_at")))
    for s in models[name].get("selections", []):
        key = (s["market"], s["selection"], Decimal(s["line"]))
        m = market.get(key)
        if key not in CORE_KEYS or m is None or s.get("p") is None or m.get("p_fair") is None or not m.get("best_odds"):
            continue
        p, odds = Decimal(str(s["p"])), Decimal(str(m["best_odds"]))
        ev = p * odds - 1
        if p <= Decimal(str(m["p_fair"])) or ev < NEAR_VALUE_EV:
            continue
        cand = Candidate(fixture_id=packet.fixture_id, market_key=key[0], selection=key[1], line=key[2], p_model=p,
                         kickoff_at=kickoff, odds=odds, bookmaker=m.get("bookmaker"),
                         p_low=None if s.get("p_lo") is None else Decimal(str(s["p_lo"])),
                         p_high=None if s.get("p_hi") is None else Decimal(str(s["p_hi"])),
                         p_market=Decimal(str(m["p_fair"])), ev=ev, model=name, n_bookmakers=m.get("n_bookmakers"))
        if best is None or ev > best[0]:
            best = (ev, cand)
    return None if best is None else best[1]


def needs_llm(last: dict[str, Any] | None, cand: Candidate, *, evidence_ids: set[int], lineups_confirmed: bool) -> bool:
    """A new model review only when something material changed since the last one: the price moved more than 3 %,
    evidence it had not seen, the line-ups confirmed since - or it was made by an older version of the reviewer, or
    it did not answer."""
    if last is None or last.get("status") != "ok":
        return True
    if last.get("engine_version") != REVIEW_VERSION:
        return True
    if cand.odds is not None and last["odds"] is not None and \
            abs(cand.odds - Decimal(last["odds"])) / Decimal(last["odds"]) > PRICE_CHANGE:
        return True
    output = last.get("output") or {}
    seen = set(output.get("seen_evidence") or last.get("evidence_ids") or [])
    if evidence_ids - seen:
        return True
    return lineups_confirmed and not output.get("lineups_seen")


def run_analysis_cycle(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                       ledger: UsageLedger | None = None, only_fixtures: list[int] | None = None,
                       search: SearchFn | None = None, provider: tuple[LlmProvider, str] | None = None,
                       transport: httpx.BaseTransport | None = None, request: bool = False,
                       batches: BatchClient | None = None) -> CycleReport:
    """One analysis cycle. ``batches`` is the Message Batches client the cycle's queue sends through (tests give a simulated one; the
    worker leaves it out and the queue builds the real one from the settings)."""
    settings = settings or AiSettings.from_env()
    report = CycleReport()
    if settings.mode == "off":
        report.status = "ok"
        report.counts["skipped_mode_off"] = 1
        return report
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (CYCLE_LOCK,))  # the lock the batch poll looks at to know a cycle is running
        row = cur.fetchone()
    if not (row and row[0]):
        report.counts["skipped_busy"] = 1  # another cycle is running: it will do this one's work
        return report
    try:
        seed_sources(conn, at=at)
        # what an earlier cycle recorded for a batch and never sent (it stopped) is abandoned: the cycle lock means nothing is sending now
        report.counts["batch_items_unsent"] = abandon_unsent(conn, at=at, before=at)
        if not report.counts["batch_items_unsent"]:
            del report.counts["batch_items_unsent"]
        conn.commit()
        report.cycle_id = open_cycle(conn, "analysis", at=at, settings=settings)
        ledger = ledger or UsageLedger()
        queue = BatchQueue(conn, settings, at=at, ledger=ledger, client=batches, transport=transport)
        try:
            _run(conn, settings, report, at=at, ledger=ledger, only=only_fixtures, search=search, provider=provider,
                 transport=transport, request=request, queue=queue)
        except Exception as exc:  # the cycle records its own failure; the worker carries on
            report.status = "failed"
            report.errors.append(f"{type(exc).__name__}: {exc}"[:300])
            log.error("ai.cycle.failed", error=report.errors[-1])
        close_cycle(conn, report.cycle_id, report, at=at)
    finally:
        conn.rollback()
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (CYCLE_LOCK,))
        conn.commit()
    return report


@dataclass
class Allowance:
    """What today may still pay for (counted in Bogotá's day)."""

    llm: int
    deep: int
    watch: int
    web_first: int
    web_pre: int


def _allowance(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime) -> Allowance:
    day = local_day(at)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(USED_TODAY_SQL, {"day": day_start(day)})
        used = cur.fetchone() or {}
        cur.execute(WEB_USED_SQL, {"day": day})
        web = {str(r["pass"]): int(r["count"]) for r in cur.fetchall()}
    waiting = open_counts(conn, "pick_review")  # reviews asked of a Message Batch and not answered yet: they are spent allowance
    return Allowance(llm=max(0, settings.max_llm_reviews_per_day - int(used.get("llm") or 0) - sum(waiting.values())),
                     deep=max(0, settings.max_deep_per_day - int(used.get("deep") or 0) - waiting.get("final", 0)),
                     watch=max(0, settings.max_watch_per_day - int(used.get("watch") or 0)),
                     web_first=max(0, settings.max_web_first - web.get("first", 0)),
                     web_pre=max(0, settings.max_web_pre - web.get("pre", 0)))


def _l3_keys(conn: psycopg.Connection[Any], by_fixture: dict[int, list[Ranked]], universe_ids: set[int], *,
             at: datetime) -> set[tuple[int, str, str, Decimal]]:
    """The best potential picks of the day: the top candidates (one per match), the picks of the day and the
    parlays' legs."""
    best: dict[int, Ranked] = {}
    for fid, xs in by_fixture.items():
        if fid in universe_ids and xs:
            best[fid] = max(xs, key=lambda x: x.elg)
    keys = {x.leg.candidate.selection_key for x in sorted(best.values(), key=lambda x: -x.elg)[:TOP_L3]}
    start, end = day_bounds(local_day(at))
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(L3_TARGETS_SQL, {"day": local_day(at), "start": start, "end": end})
        keys |= {(int(r[0]), str(r[1]), str(r[2]), Decimal(r[3])) for r in cur.fetchall()}
    return keys


def _run(conn: psycopg.Connection[Any], settings: AiSettings, report: CycleReport, *, at: datetime,
         ledger: UsageLedger, only: list[int] | None, search: SearchFn | None,
         provider: tuple[LlmProvider, str] | None, transport: httpx.BaseTransport | None, request: bool,
         queue: BatchQueue | None = None) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"start": at + timedelta(minutes=10),
                                   "until": at + timedelta(hours=settings.horizon_hours), "limit": MAX_FIXTURES})
        fixtures = [(int(r["id"]), r["kickoff_at"]) for r in cur.fetchall()]
    if only:
        fixtures = [f for f in fixtures if f[0] in set(only)]
    report.counts["fixtures"] = len(fixtures)
    # what the research of an entity does in this cycle (``FBI_AI_RESEARCH_V2`` and its gate): nothing, runs beside v1 (shadow), or replaces it (on)
    research_mode = gates.research_mode(conn, settings)
    if research_mode != "off":
        report.counts[f"research_v2_{research_mode}"] = 1

    # 1. evidence from the provider (free)
    for fid, kickoff in fixtures:
        if kickoff - at <= EVIDENCE_HORIZON:
            try:
                got = collect_provider(conn, fid, at=at)
                report.counts["evidence_seen"] += got.seen
                report.counts["evidence_new"] += got.created
                conn.commit()
            except Exception as exc:
                conn.rollback()
                report.status = "partial"
                report.errors.append(f"evidence {fid}: {type(exc).__name__}")
            if research_mode != "off":
                _refresh_typed(conn, report, fid, at=at, replaces=research_mode == "on")

    # 2. the shortlist: the value gate at the current price, one per selection
    rows = load_candidates(conn, at=at, until=at + SHORTLIST_HORIZON, include_shadow=True)
    ranked = [x for x in passing(rows, at=at, source="evaluation") if x.elg > 0]
    wanted = {f[0] for f in fixtures}
    by_fixture: dict[int, list[Ranked]] = defaultdict(list)
    for x in ranked:
        if x.leg.candidate.fixture_id in wanted:
            by_fixture[x.leg.candidate.fixture_id].append(x)
    report.counts["shortlist"] = sum(len(v) for v in by_fixture.values())

    # 3. today: the day opened, its universe (matches with a market), the passes due now
    if open_day(conn, at=at, settings=settings) is not None:
        report.counts["day_opened"] = 1
    check_alerts(conn, at=at, settings=settings)
    conn.commit()
    today = [f for f in universe(conn, day=local_day(at), at=at) if f.has_market]
    universe_ids = {f.fixture_id for f in today}
    report.counts["universe"] = len(universe_ids)
    dues: dict[int, Due] = {d.fixture.fixture_id: d for d in due_passes(conn, at=at, only=set(only) if only else None)}
    if request and only:
        for f in today:
            if f.fixture_id in set(only):
                dues[f.fixture_id] = Due(f, "request")
    report.counts["passes_due"] = len(dues)
    llm_ready = settings.llm_configured or provider is not None
    allow = _allowance(conn, settings, at=at)
    l3 = _l3_keys(conn, by_fixture, universe_ids, at=at) if dues and llm_ready else set()
    web_ready = settings.search_configured or search is not None
    web: set[int] = set()
    escalated: set[int] = set()
    asked: dict[int, list[research.Ask]] = {}  # what the latest brief of each match asked the server to look into
    if dues:
        with conn.cursor(row_factory=tuple_row) as tcur:
            tcur.execute(ESCALATED_SQL, {"fixtures": list(dues)})
            latest = tcur.fetchall()
        escalated = {int(r[0]) for r in latest if r[1]}
        asked = {int(r[0]): found for r in latest if (found := research.asks_in(r[2]))}
    if dues and web_ready:
        def rank(d: Due) -> tuple[int, int, float, float, datetime]:
            return web_rank(d, by_fixture)
        firsts = sorted((d for d in dues.values() if d.pass_kind in ("first", "request")), key=rank)
        # a match that asked for research is searched at its pre pass too, ranked like any other match without a candidate:
        # after the ones with a candidate, inside the same allowance (``research`` explains why)
        pres = sorted((d for d in dues.values() if d.pass_kind == "pre"
                       and (d.fixture.fixture_id in by_fixture or d.fixture.fixture_id in escalated
                            or d.fixture.fixture_id in asked)), key=rank)
        web = {d.fixture.fixture_id for d in firsts[:allow.web_first]} | \
              {d.fixture.fixture_id for d in pres[:allow.web_pre]}

    # 4-5. packets, briefs, reviews, analyses - the paid ones first, by priority
    builder = PacketBuilder(conn, typed_evidence=research_mode == "on")  # shadow writes claims nobody reads
    with conn.cursor(row_factory=tuple_row) as tcur:
        tcur.execute(NEWEST_PACKETS_SQL, {"fixtures": [f[0] for f in fixtures]})
        newest = {int(r[0]): r[1] for r in tcur.fetchall()}
    order = sorted(fixtures, key=lambda f: (f[0] not in dues, -(dues[f[0]].fixture.priority if f[0] in dues else 0),
                                            f[1]))
    health = {"llm_down": False}
    held: list[tuple[Any, ...]] = []  # the passes whose record waits for the batch their reviews went to
    try:
        for fid, kickoff in order:
            due = dues.get(fid)
            try:
                if due is not None:
                    _pass(conn, settings, report, due, by_fixture.get(fid, []), builder, at=at, ledger=ledger,
                          search=search, provider=provider, transport=transport, allow=allow, l3=l3,
                          web=fid in web, llm_ready=llm_ready, health=health, asks=asked.get(fid, []), queue=queue,
                          held=held, research_mode=research_mode)
                else:
                    _free(conn, settings, report, fid, kickoff, by_fixture.get(fid, []), builder, newest, at=at)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                report.status = "partial"
                report.errors.append(f"fixture {fid}: {type(exc).__name__}: {exc}"[:200])
                log.warning("ai.cycle.fixture_failed", fixture=fid, error=f"{type(exc).__name__}: {exc}"[:200])
    finally:
        _send_batches(conn, report, queue, held, at=at)


def _send_batches(conn: psycopg.Connection[Any], report: CycleReport, queue: BatchQueue | None,
                  held: list[tuple[Any, ...]], *, at: datetime) -> None:
    """The end of the cycle: what it recorded for the Message Batches API is sent, one batch per workspace, and only then are the passes
    that waited for it recorded as done. A batch that could not be created leaves its matches' passes undone: the next cycle asks again
    (the brief and the web are reused, nothing is paid twice) and after two failures asks in real time. A failure here is noted and
    never stops the cycle: the reviews were not paid, and the quantitative pipeline never waited for them."""
    if queue is None:
        return
    try:
        sent = queue.flush()
        conn.commit()
    except Exception as exc:
        conn.rollback()
        report.status = "partial"
        report.errors.append(f"batch flush: {type(exc).__name__}: {exc}"[:200])
        log.error("ai.batch.flush_failed", error=f"{type(exc).__name__}: {exc}"[:200])
        report.counts["passes_to_retry"] += len(held)
        held.clear()
        return
    for key, n in (("batches_sent", sent.batches), ("batch_items_sent", sent.sent), ("batch_items_failed", sent.failed),
                   ("batch_items_orphans", sent.orphans)):
        if n:
            report.counts[key] += n
    if sent.error:
        report.errors.append(f"batch: {sent.error}"[:200])
    if sent.failed or sent.orphans:
        report.status = "partial" if report.status == "ok" else report.status
    for reason, n in queue.refused.items():
        report.counts[f"batch_refused_{reason}"] += n
    unsent: set[int] = set()
    if held and (sent.failed or sent.orphans):
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(UNSENT_FIXTURES_SQL, {"at": at})
            unsent = {int(r[0]) for r in cur.fetchall()}
    try:
        for row in held:
            if int(row[0]) in unsent:
                report.counts["passes_to_retry"] += 1
                continue
            with conn.cursor() as cur:
                cur.execute(PASS_SQL, row)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        report.status = "partial"
        report.errors.append(f"passes: {type(exc).__name__}: {exc}"[:200])
        log.error("ai.cycle.passes_failed", error=f"{type(exc).__name__}: {exc}"[:200])
    held.clear()


def web_rank(d: Due, by_fixture: dict[int, list[Ranked]]) -> tuple[int, int, float, float, datetime]:
    """Which matches of a pass are searched on the web first (REVIEW B4): the daily set's own order - the matches whose
    best selection passes the risk stage (``fbi.picks.daily.RISK``), by its pessimistic growth, the likeliest picks of
    the day -, then the other shortlisted matches, then the rest; within each, the match's priority."""
    options = by_fixture.get(d.fixture.fixture_id, [])
    eligible = [x.elg for x in options if RISK.stop(x) is None]
    return (-int(bool(eligible)), -int(bool(options)), -(max(eligible) if eligible else 0.0), -d.fixture.priority,
            d.fixture.kickoff_at)


def _last_llm(conn: psycopg.Connection[Any], fixture_id: int) -> dict[tuple[str, str, Decimal], dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LAST_LLM_SQL, {"fixture": fixture_id})
        return {(r["market_key"], r["selection"], Decimal(r["line"])): dict(r) for r in cur.fetchall()}


def _carried(last: dict[str, Any] | None, *, at: datetime) -> Any:
    if last is not None and last["status"] == "ok" and at - last["reviewed_at"] < CARRY_FOR \
            and last.get("engine_version") == REVIEW_VERSION:
        return carried_review(last)
    return None


def _free(conn: psycopg.Connection[Any], settings: AiSettings, report: CycleReport, fid: int, kickoff: datetime,
          options: list[Ranked], builder: PacketBuilder, newest: dict[int, datetime], *, at: datetime) -> None:
    """A match outside its passes: the packet on its cadence, the rules (and a model review still in force), the
    cards. No model call, no search."""
    last_packet = newest.get(fid)
    every = FAR_REFRESH if kickoff - at > timedelta(hours=24) else NEAR_REFRESH
    if not options and last_packet is not None and timedelta(0) <= at - last_packet < every:
        report.counts["packets_not_due"] += 1
        return
    extra = [(x.leg.candidate.market_key, x.leg.candidate.selection, x.leg.candidate.line) for x in options]
    packet = builder.build(fid, at=at, extra_keys=extra)
    if packet is None:
        return
    packet_id = store_packet(conn, packet, built_at=at)
    report.counts["packets"] += 1
    reviews: dict[tuple[str, str, Decimal], Reviewed] = {}
    if options:
        last_llm = _last_llm(conn, fid)
        for x in options:
            cand = candidate_of(x, packet.content.get("models") or {})
            key = (cand.market_key, cand.selection, cand.line)
            reviewed = review_candidate(conn, settings, cand, packet, packet_id, at=at, use_llm=False,
                                        prior_llm=_carried(last_llm.get(key), at=at))
            reviews[key] = reviewed
            report.counts["reviews"] += 1
            report.counts[f"decision_{reviewed.decision.lower()}"] += 1
    cards = build_cards(packet, [value_option(x) for x in options], reviews)
    engines = ["rules"] + (["llm"] if any(r.by_llm for r in reviews.values()) else [])
    _, created = store_analysis(conn, packet, packet_id, cards, at=at, engines=engines)
    report.counts["analyses_new" if created else "analyses_same"] += 1


def _refresh_typed(conn: psycopg.Connection[Any], report: CycleReport, fid: int, *, at: datetime, replaces: bool) -> None:
    """The statuses of what research v2 knows for a match, decided again (new line-ups, time passing): free, no model, no search. It never
    stops the cycle - beside v1 a failure is only noted."""
    try:
        entity_research.refresh_for(conn, fid, at=at)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        _research_failed(report, fid, exc, replaces=replaces)


def _research_failed(report: CycleReport, fid: int, exc: Exception, *, replaces: bool, counts: dict[str, int] | None = None) -> None:
    """Research v2 failed for a match: counted and written down, never raised. Beside v1 (shadow) the cycle stays ``ok`` - the quantitative
    pipeline and v1 did their work; instead of v1 (on) the match went without research, which is what ``partial`` says.

    ``counts`` is the pass's own (a failure inside a pass): the pass row says v2 failed, so a comparison does not read «v2 found nothing»."""
    text = f"{type(exc).__name__}: {exc}"[:200]
    report.counts["v2_failed"] += 1
    if counts is not None:
        counts["v2_failed"] += 1
    report.errors.append(f"research v2 {fid}: {text}")
    if replaces:
        report.status = "partial" if report.status == "ok" else report.status
    log.warning("ai.research_v2.failed", fixture=fid, error=text)


def _research_v2(conn: psycopg.Connection[Any], settings: AiSettings, report: CycleReport, counts: dict[str, int], fid: int, *, at: datetime,
                 ledger: UsageLedger, search: SearchFn | None, provider: tuple[LlmProvider, str] | None,
                 transport: httpx.BaseTransport | None, levels: int | Sequence[int], replaces: bool) -> tuple[Decimal, bool]:
    """The research of an entity for one pass (``fbi.ai.entity_research``) - returns what it cost and whether it ran. It fails open: an
    exception is rolled back (what it paid is in the ledger, which has its own connection), counted and written down, and the pass goes on.

    Beside v1 (``replaces`` False) its numbers are the ``v2_*`` counts and nothing else moves: not ``web_searches`` - the allowance of the day
    counts v1's searches -, not a status of v1, not a packet. Instead of v1 (``replaces`` True) its searches, items and reasons ARE the pass's
    web numbers, because the allowance of the day, the pass row and the reports read those."""
    try:
        got = entity_research.collect(conn, settings, fid, at=at, ledger=ledger, search=search, provider=provider, transport=transport, levels=levels)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        _research_failed(report, fid, exc, replaces=replaces, counts=counts)
        return Decimal(0), False
    for key, n in got.counts().items():
        counts[key] += n
        report.counts[key] += n
    if got.skipped:
        reason = got.skipped.replace(" ", "_")
        counts[f"v2_skipped_{reason}"] += 1
        report.counts[f"v2_skipped_{reason}"] += 1
    if replaces:
        counts["web_searches"] += got.searches
        counts["web_items"] += got.extracted
        counts["web_new"] += got.created
        report.counts["web_searches"] += got.searches
        report.counts["web_items"] += got.extracted
        if got.skipped:
            report.counts[f"web_skipped_{got.skipped}"] += 1
    return Decimal(str(got.cost_usd)), True


def _pass(conn: psycopg.Connection[Any], settings: AiSettings, report: CycleReport, due: Due, options: list[Ranked],
          builder: PacketBuilder, *, at: datetime, ledger: UsageLedger, search: SearchFn | None,
          provider: tuple[LlmProvider, str] | None, transport: httpx.BaseTransport | None, allow: Allowance,
          l3: set[tuple[int, str, str, Decimal]], web: bool, llm_ready: bool, health: dict[str, bool],
          asks: Sequence[research.Ask] = (), queue: BatchQueue | None = None,
          held: list[tuple[Any, ...]] | None = None, research_mode: str = "off") -> None:
    """One pass of one match of the day: web (when chosen), packet, L1 brief, L2/L3 reviews, cards, the pass row.
    A pass the provider failed (down, timing out) is not recorded: the next cycle tries it again.

    ``queue`` is where a candidate's review goes when it can wait (``fbi.ai.batch``): in a Message Batch, at half the price, answered
    later; the combined review is the rules' alone until then, and the next cycle combines the two. Without a queue, or when the
    queue refuses (a switch, a gate, a budget), the review is asked in real time exactly as before. A pass that put a review in a batch
    is recorded as done only once the batch is sent (``held``, ``_send_batches``).

    ``asks`` is what the match's latest brief asked the server to look into (``fbi.ai.research``): a pass that reads the web reads it
    with the levels of the topics asked, when the match has no candidate to read it deeper for; a pass that does not, or has no
    allowance or budget for it, says so in its counts (``research_unserved_<reason>``).

    ``research_mode`` is what the research of an entity does (``fbi.ai.gates.research_mode``): ``off``, beside v1 (``shadow``: after v1's
    research, in the same pass and with the same allowance, its claims written for the comparison and shown to nobody - its numbers are the
    ``v2_*`` counts) or instead of it (``on``: v1's research does not run and v2's numbers are the pass's web numbers)."""
    fid, kind = due.fixture.fixture_id, due.pass_kind
    started = now()
    counts: dict[str, int] = defaultdict(int)
    cost = Decimal(0)
    report.counts[f"pass_{kind}"] += 1
    if research_mode != "off":  # the pass says which research it ran under: the gate of research v2 reads the days from these rows
        counts[f"research_v2_{research_mode}"] = 1
    llm_ready = llm_ready and not health["llm_down"]
    transient = False
    # Near the budget a match without any candidate loses its paid depth first (``Budget.marginal_allowed``): no
    # model brief, no web. The candidates keep theirs up to the day's ceiling.
    deep = bool(options) or kind == "request" or budget_of(conn, at=at, settings=settings).marginal_allowed()
    if not deep:
        counts["marginal_saved"] += 1
        report.counts["marginal_saved"] += 1

    # the web (first and pre passes; the most important matches; only a stale cached answer is asked again)
    barrier: str | None = None  # why a match that asked for research was not read
    if kind not in ("first", "pre", "request"):
        barrier = "no_search_pass"
    elif not web:
        barrier = "no_allowance"
    elif not deep:
        barrier = "near_budget"
    elif not budget_of(conn, at=at, settings=settings).pass_allows(kind):
        barrier = "pass_budget"
    else:
        # the tiered search (sources-v2): up to three levels for a match with candidates, the levels of the topics asked for
        # (``fbi.ai.research``) or the first level for the others
        levels = research.levels_for(asks, candidates=bool(options))
        if research_mode != "on":  # v1 decides what the packet knows (research v2 off, or beside it in shadow)
            got = collect_web(conn, settings, fid, at=at, ledger=ledger, search=search, provider=provider,
                              transport=transport, levels=levels)
            counts["web_searches"] += got.searches
            counts["web_items"] += got.extracted
            counts["web_new"] += got.created
            cost += Decimal(str(got.cost_usd))
            report.counts["web_searches"] += got.searches
            report.counts["web_items"] += got.extracted
            if got.skipped:
                report.counts[f"web_skipped_{got.skipped}"] += 1
            conn.commit()
        if research_mode != "off":
            spent, ran = _research_v2(conn, settings, report, counts, fid, at=at, ledger=ledger, search=search, provider=provider,
                                      transport=transport, levels=levels, replaces=research_mode == "on")
            cost += spent
            if not ran and research_mode == "on":
                barrier = "research_failed"  # v1 did not run either: nobody read the web for this match
    if asks:
        counts["research_asked"] = len(asks)
        report.counts["research_asked"] += len(asks)
        if barrier is None:
            counts["research_searched"] = 1
            report.counts["research_searched"] += 1
        else:
            counts[f"research_unserved_{barrier}"] = 1
            report.counts[f"research_unserved_{barrier}"] += 1

    extra = [(x.leg.candidate.market_key, x.leg.candidate.selection, x.leg.candidate.line) for x in options]
    packet = builder.build(fid, at=at, extra_keys=extra)
    if packet is None:
        return
    packet_id = store_packet(conn, packet, built_at=at)
    report.counts["packets"] += 1

    # L1: the brief, on the cards as the last reviews leave them
    known = latest_reviews(conn, [fid], at=at, window=CARRY_FOR)
    preview = build_cards(packet, [value_option(x) for x in options],
                          {(k[1], k[2], k[3]): v for k, v in known.items()})
    brief: Brief = make_brief(conn, settings, packet, packet_id, cards=preview, candidates=len(options),
                              pass_kind=kind, at=at, use_llm=llm_ready and deep, ledger=ledger, transport=transport,
                              provider=provider)
    if brief.engine == "rules" and brief.error in TRANSIENT:
        health["llm_down"], transient, llm_ready = True, True, False
    counts["brief_reused" if brief.reused else f"brief_{brief.engine}"] += 1
    report.counts["briefs_llm" if brief.engine == "llm" and not brief.reused else
                  "briefs_reused" if brief.reused else "briefs_rules"] += 1
    if brief.reuse == "material":  # a call saved because nothing material changed (plan section 19), apart from the identical input
        counts["brief_reused_material"] += 1
        report.counts["briefs_reused_material"] += 1
    if brief.escalate:
        report.counts["escalated"] += 1
    if not brief.reused and brief.content.get("research"):  # what this reading asks the next pass that reads the web to look into
        counts["research_requested"] = len(brief.content["research"])
        report.counts["research_requested"] += len(brief.content["research"])
    cost += brief.cost
    conn.commit()

    # L2 / L3: the candidates' reviews, after a material change only
    evidence_ids = {int(e["id"]) for e in packet.content.get("evidence", [])}
    confirmed = bool(packet.content.get("lineups", {}).get("confirmed"))
    last_llm = _last_llm(conn, fid)
    material = {"contradiction", "important_news"} & set(brief.reasons)
    best_key = max(options, key=lambda x: x.elg).leg.candidate.selection_key if options else None
    reviews: dict[tuple[str, str, Decimal], Reviewed] = {}
    for x in options:
        cand = candidate_of(x, packet.content.get("models") or {})
        key = (cand.market_key, cand.selection, cand.line)
        sel_key = x.leg.candidate.selection_key
        strong = sel_key in l3 or (bool(material) and sel_key == best_key)
        tier: Tier = "final" if strong and allow.deep > 0 else "analysis"
        role = "pick" if sel_key in l3 else "candidate"
        last = last_llm.get(key)
        b = budget_of(conn, at=at, settings=settings)
        use_llm = (llm_ready and allow.llm > 0 and b.pass_allows(kind) and b.allows("bulk")
                   and needs_llm(last, cand, evidence_ids=evidence_ids, lineups_confirmed=confirmed))
        # a review that can wait goes to a Message Batch: the plan's table (first pass; pre pass with the match four hours away or
        # more), the owner's switch and the evidence of the gate decide (``BatchQueue.routes``)
        deferral = Deferral(queue, packet_id, settings.mode, kind) if use_llm and queue is not None and queue.routes(
            tier=tier, pass_kind=kind, kickoff_at=cand.kickoff_at, role=role) else None
        reviewed = review_candidate(conn, settings, cand, packet, packet_id, at=at, use_llm=use_llm, tier=tier,
                                    ledger=ledger, transport=transport, provider=provider,
                                    prior_llm=None if use_llm else _carried(last, at=at), role=role, deferral=deferral)
        if reviewed.pending is not None:
            _count_batched(report, counts, reviewed, allow, tier)
        if use_llm and reviewed.llm is not None and reviewed.llm.status == "ok" and tier == "analysis" \
                and {reviewed.rules.decision, reviewed.llm.decision} == {"APPROVE", "REJECT"} and allow.deep > 0 \
                and budget_of(conn, at=at, settings=settings).pass_allows(kind):
            # the rules and the intermediate model contradict each other outright: the strong model decides
            _count_llm(report, counts, reviewed, allow, "analysis")
            cost += reviewed.llm.cost
            conn.commit()
            tier = "final"
            reviewed = review_candidate(conn, settings, cand, packet, packet_id, at=at, use_llm=True, tier=tier,
                                        ledger=ledger, transport=transport, provider=provider, role="contradiction")
        elif _arbitrable(reviewed, use_llm=use_llm) and llm_ready and allow.llm > 0 and allow.deep > 0 \
                and budget_of(conn, at=at, settings=settings).pass_allows(kind):
            # the same contradiction, with the intermediate review having come from a Message Batch: it arrived after the pass that asked it,
            # so the strong model decides now, in real time, at the first pass that can (once: its answer is the newest review)
            tier = "final"
            report.counts["batch_arbitrations"] += 1
            reviewed = review_candidate(conn, settings, cand, packet, packet_id, at=at, use_llm=True, tier=tier,
                                        ledger=ledger, transport=transport, provider=provider, role="contradiction")
        reviews[key] = reviewed
        report.counts["reviews"] += 1
        report.counts[f"decision_{reviewed.decision.lower()}"] += 1
        if reviewed.llm is not None:
            _count_llm(report, counts, reviewed, allow, tier)
            cost += reviewed.llm.cost
            if reviewed.llm.status == "failed" and (reviewed.llm.error or "failed") in TRANSIENT:
                health["llm_down"], transient, llm_ready = True, True, False
        conn.commit()

    # an escalated match without a candidate: one watch review of its nearest-to-value selection
    if not options and brief.escalate and llm_ready and allow.watch > 0 and allow.llm > 0 and kind != "final":
        b = budget_of(conn, at=at, settings=settings)
        watch = watch_candidate(packet)
        if watch is not None and b.pass_allows(kind):
            key = (watch.market_key, watch.selection, watch.line)
            if needs_llm(last_llm.get(key), watch, evidence_ids=evidence_ids, lineups_confirmed=confirmed):
                reviewed = review_candidate(conn, settings, watch, packet, packet_id, at=at, use_llm=True,
                                            tier="analysis", ledger=ledger, transport=transport, provider=provider,
                                            role="watch")
                reviews[key] = reviewed
                if reviewed.llm is not None:
                    allow.watch -= 1
                    counts["watch"] += 1
                    report.counts["watch_reviews"] += 1
                    _count_llm(report, counts, reviewed, allow, "analysis")
                    cost += reviewed.llm.cost
                conn.commit()

    cards = build_cards(packet, [value_option(x) for x in options], reviews)
    engines = ["rules"] + (["llm"] if any(r.by_llm for r in reviews.values()) or brief.engine == "llm" else [])
    _, created = store_analysis(conn, packet, packet_id, cards, at=at, engines=engines)
    report.counts["analyses_new" if created else "analyses_same"] += 1
    report.cost_usd += cost
    if transient:
        report.counts["passes_to_retry"] += 1
        return
    if kind == "request":
        return
    counts["reviews"] = len(reviews)
    counts["candidates"] = len(options)
    row = (fid, local_day(at), kind, min(started, at), max(now(), at), due.fixture.kickoff_at, "ok", brief.escalate,
           brief.reasons, brief.id, packet_id, Jsonb(dict(counts)), cost)
    if held is not None and counts.get("batch_queued"):
        held.append(row)  # recorded when the batch is sent: a batch that cannot be created leaves this pass to be done again
        return
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PASS_SQL, row)


def _count_llm(report: CycleReport, counts: dict[str, int], reviewed: Reviewed, allow: Allowance, tier: str) -> None:
    assert reviewed.llm is not None
    if reviewed.llm.output.get("reused_from") is not None:
        report.counts["llm_reused"] += 1
        return
    if reviewed.llm.status == "over_budget":
        report.counts["llm_over_budget"] += 1
        return
    allow.llm -= 1
    level = "l3" if (reviewed.llm.output.get("tier") or tier) == "final" else "l2"
    if level == "l3":
        allow.deep -= 1
    counts[level] += 1
    report.counts["llm_reviews"] += 1
    report.counts[f"llm_{level}"] += 1
    if reviewed.llm.status != "ok":
        report.counts[f"llm_{reviewed.llm.status}"] += 1


def _count_batched(report: CycleReport, counts: dict[str, int], reviewed: Reviewed, allow: Allowance, tier: str) -> None:
    """A review that waits in a Message Batch: nothing was paid and nothing stored yet. The day's allowance holds its place from the
    moment it is queued (the cycle counts the open items of earlier cycles at its start); one already waiting was counted then."""
    assert reviewed.pending is not None
    state = str(reviewed.pending.output.get("batch"))
    report.counts["reviews_batched"] += 1
    if state != "queued":
        counts["batch_waiting"] += 1
        report.counts["batch_waiting"] += 1
        return
    allow.llm -= 1
    if tier == "final":
        allow.deep -= 1
    counts["batch_queued"] += 1
    report.counts["batch_queued"] += 1


def _arbitrable(reviewed: Reviewed, *, use_llm: bool) -> bool:
    """A model review that came from a Message Batch, still in force, that the rules contradict outright (the model approves what they
    reject, or the reverse): the strong model arbitrates it, as it arbitrates a live one."""
    carried = reviewed.carried
    return (not use_llm and carried is not None and carried.output.get("via") == "batch" and carried.output.get("tier") == "analysis"
            and {reviewed.rules.decision, carried.decision} == {"APPROVE", "REJECT"})


# ── learning: post-mortems, notes, patterns, dependence, the AI's shadow evaluation, tomorrow ──

CORRELATION_EVERY = timedelta(days=7)
CORRELATION_WINDOW = timedelta(days=730)

PAID_TODAY_SQL = """
SELECT count(*) FROM ai.usage WHERE purpose = %(purpose)s AND status = 'ok' AND at >= %(since)s
"""


def _paid_today(conn: psycopg.Connection[Any], purpose: str, *, at: datetime) -> bool:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PAID_TODAY_SQL, {"purpose": purpose, "since": day_start(local_day(at))})
        row = cur.fetchone()
    return bool(row and row[0])


def _isolated(conn: psycopg.Connection[Any], report: CycleReport, name: str, step: Callable[[], None]) -> int:
    """A step whose failure must not stop what the rest of the cycle learns: its error is recorded, what it had not committed is rolled
    back and the cycle ends ``partial``. Returns 1 when the step ran."""
    try:
        step()
        return 1
    except Exception as exc:
        conn.rollback()
        report.status = "partial"
        report.errors.append(f"{name}: {type(exc).__name__}: {exc}"[:300])
        log.error(f"ai.learning.{name}_failed", error=report.errors[-1])
        return 0


def _attributions(conn: psycopg.Connection[Any], report: CycleReport, *, at: datetime, settings: AiSettings,
                  ledger: UsageLedger, transport: httpx.BaseTransport | None) -> None:
    """Phase 5, behind ``FBI_AI_PM_REVIEWER``: which agent and version was right or wrong in the matches that finished (code only, nothing of
    production changes), then the cases the Post-Match Reviewer is asked about, in the Batch of the LAB. The attribution is committed before the
    model is asked: the model's failure leaves it standing."""
    from fbi.ai.agents import attribution, pmr

    today = local_day(at)
    for d in (today - timedelta(days=1), today):
        r = attribution.attribute_day(conn, day=d, at=at)
        report.counts["attributions"] = report.counts.get("attributions", 0) + r.written
    conn.commit()
    sent = pmr.run(conn, settings, at=at, ledger=ledger, transport=transport)
    report.counts.update(pmr_counts(sent))
    log.info("ai.learning.pmr", **{k: v for k, v in sent.items() if k != "estimate_usd"})
    conn.commit()


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:48] or "unknown"


def pmr_counts(sent: dict[str, Any]) -> dict[str, int]:
    """The Post-Match Reviewer's report as the integers ``ai.cycles.counts`` keeps (IA-014): its counts as they are, and WHY it asked nothing as
    counts of their own - ``pmr_stopped_<reason>`` (a LAB without key or envelope, a day without room...), ``pmr_blockers`` (how many) and
    ``pmr_refused_<reason>`` (a model the router does not name). Before, only the integers were kept and a reviewer that asked nothing left no
    word of why."""
    out: dict[str, int] = {}
    for key, value in sent.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[f"pmr_{key}"] = value
    stopped = sent.get("stopped")
    if isinstance(stopped, str) and stopped:
        out[f"pmr_stopped_{_slug(stopped)}"] = 1
    blockers = sent.get("blockers")
    if isinstance(blockers, list) and blockers:
        out["pmr_blockers"] = len(blockers)
    refused = sent.get("refused")
    if isinstance(refused, dict):
        for reason, n in refused.items():
            if isinstance(n, int) and not isinstance(n, bool):
                out[f"pmr_refused_{_slug(str(reason))}"] = n
    return out


def _postmortems(conn: psycopg.Connection[Any], report: CycleReport, *, at: datetime, settings: AiSettings,
                 ledger: UsageLedger, provider: tuple[LlmProvider, str] | None,
                 transport: httpx.BaseTransport | None) -> None:
    """The one post-mortem (plan F8): every selection that finished, once, whoever looked at it; the matches as a whole; and the narratives
    of the ones that matter, which are optional, paid for and apart. Each part is committed before the next."""
    from fbi.ai.pm_narratives import run_narratives
    from fbi.intel.match_review import review_matches
    from fbi.intel.postmortem import study

    sel = study(conn, at=at)
    conn.commit()
    matches = review_matches(conn, at=at)
    conn.commit()
    narr = run_narratives(conn, at=at, settings=settings, ledger=ledger, provider=provider, transport=transport)
    conn.commit()
    report.counts.update({"postmortems": matches.matches, "memory_events": matches.memory_events,
                          "context_errors": matches.context_errors, "narratives": narr.written,
                          "pick_postmortems": sel.studied, "losses_studied": sel.losses, "wins_studied": sel.wins,
                          "pick_memory_events": sel.memory_events, "postmortems_left": sel.left})
    for cls, n in sel.by_class.items():
        report.counts[f"class_{cls.lower()}"] = n
    report.errors += (sel.errors[:3] + matches.errors[:3] + narr.errors[:3])


def _legacy_postmortems(conn: psycopg.Connection[Any], report: CycleReport, *, at: datetime, settings: AiSettings,
                        ledger: UsageLedger, provider: tuple[LlmProvider, str] | None,
                        transport: httpx.BaseTransport | None) -> None:
    """The two first post-mortems (pm-v1 by match, pm-v2 by selection), frozen since F8: they write only when
    ``FBI_AI_LEGACY_POSTMORTEMS`` brings them back, after the one post-mortem. Their memory events keep the keys they always had, so
    what the one post-mortem already remembered is not remembered twice."""
    from fbi.ai.pick_postmortem import run_pick_postmortems
    from fbi.ai.postmortem import run_postmortems

    pm = run_postmortems(conn, at=at, settings=settings, ledger=ledger, provider=provider, transport=transport)
    pp = run_pick_postmortems(conn, at=at, settings=settings, ledger=ledger, provider=provider, transport=transport)
    report.counts.update({"legacy_postmortems": pm.fixtures, "legacy_pick_postmortems": pp.studied,
                          "legacy_narratives": pm.narratives + pp.narratives})
    report.errors += pm.errors[:3] + pp.errors[:3]


def run_learning_cycle(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                       ledger: UsageLedger | None = None, provider: tuple[LlmProvider, str] | None = None,
                       transport: httpx.BaseTransport | None = None) -> CycleReport:
    """Daily (worker job ``ai_learn``, 07:35 Bogotá): what the finished matches taught, written down - the ONE
    post-mortem of every selection PrediGol looked at and of every match (plan F8, ``fbi.intel.postmortem``; the two
    first ones, pm-v1 and pm-v2, run again only with ``FBI_AI_LEGACY_POSTMORTEMS``), the narratives a model writes
    for the ones that matter, yesterday's notes and lessons (QUÉ APRENDIÓ PREDIGOL HOY), the sources' day, patterns
    proposed as hypotheses (never applied), the parlays' dependence re-measured weekly, the AI's own shadow report,
    the month's budget alerts - and tomorrow prepared without any model or search."""
    from fbi.ai.day import prepare_day
    from fbi.ai.learning import learn_day, refresh_source_stats
    from fbi.ai.patterns import run_patterns
    from fbi.ai.shadow import run_shadow
    from fbi.parlays import correlation

    settings = settings or AiSettings.from_env()
    report = CycleReport()
    if settings.mode == "off":
        report.counts["skipped_mode_off"] = 1
        return report
    report.cycle_id = open_cycle(conn, "learning", at=at, settings=settings)
    ledger = ledger or UsageLedger()
    steps = 0
    today = local_day(at)
    yesterday = today - timedelta(days=1)
    try:
        # a post-mortem that fails must not stop what the rest of the cycle learns
        steps += _isolated(conn, report, "postmortems", lambda: _postmortems(
            conn, report, at=at, settings=settings, ledger=ledger, provider=provider, transport=transport))
        if settings.legacy_postmortems:
            steps += _isolated(conn, report, "legacy_postmortems", lambda: _legacy_postmortems(
                conn, report, at=at, settings=settings, ledger=ledger, provider=provider, transport=transport))
        if settings.pm_reviewer:
            steps += _isolated(conn, report, "attributions", lambda: _attributions(
                conn, report, at=at, settings=settings, ledger=ledger, transport=transport))
        for d in (yesterday, today):
            report.counts["source_domains"] = refresh_source_stats(conn, day=d, at=at)
        conn.commit()
        lr = learn_day(conn, day=yesterday, at=at, settings=settings, ledger=ledger, provider=provider,
                       transport=transport, use_llm=not _paid_today(conn, "learning", at=at))
        report.counts.update({"learning_notes": lr.notes, "lessons": lr.lessons})
        conn.commit()
        steps += 1
        pat = run_patterns(conn, at=at, settings=settings, ledger=ledger,
                           use_llm=not _paid_today(conn, "pattern_review", at=at), provider=provider,
                           transport=transport)
        report.counts.update({"patterns_found": len(pat.found), "hypotheses_proposed": len(pat.proposed),
                              "ai_hypotheses": len(pat.ai_proposed)})
        conn.commit()
        steps += 1
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT max(estimated_at) FROM ai.correlation_estimates")
            row = cur.fetchone()
        if row is None or row[0] is None or at - row[0] >= CORRELATION_EVERY:
            estimates = correlation.estimate(conn, since=at - CORRELATION_WINDOW, until=at)
            correlation.store(conn, estimates, at=at, since=(at - CORRELATION_WINDOW).date(), until=at.date())
            report.counts["correlation_estimates"] = len(estimates)
            conn.commit()
        steps += 1
        shadow = run_shadow(conn, at=at)
        for engine, r in shadow.reports.items():
            report.counts[f"shadow_{engine}_n"] = int(r["arms"]["model"].get("n") or 0)
        conn.commit()
        steps += 1
        report.counts["budget_alerts"] = len(check_alerts(conn, at=at, settings=settings))
        if prepare_day(conn, day=today + timedelta(days=1), at=at, settings=settings) is not None:
            report.counts["tomorrow_prepared"] = 1
        conn.commit()
        steps += 1
    except Exception as exc:
        conn.rollback()
        report.status = "partial" if steps else "failed"
        report.errors.append(f"{type(exc).__name__}: {exc}"[:300])
        log.error("ai.learning.failed", error=report.errors[-1])
    close_cycle(conn, report.cycle_id, report, at=at)
    return report


def run_day_start(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None) -> CycleReport:
    """00:05 Bogotá (worker job ``ai_day_start``): the day opened, the month's alerts, then the analysis cycle -
    whose first passes are today's first reading."""
    settings = settings or AiSettings.from_env()
    return run_analysis_cycle(conn, at=at, settings=settings)


def process_requests(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None) -> int:
    """The owner's "run now" requests (``ai.run_requests``), oldest first, one at a time."""
    settings = settings or AiSettings.from_env()
    done = 0
    while True:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("UPDATE ai.run_requests SET status = 'running', picked_at = %s WHERE id = (SELECT id FROM "
                        "ai.run_requests WHERE status = 'queued' ORDER BY requested_at, id LIMIT 1 "
                        "FOR UPDATE SKIP LOCKED) RETURNING id, kind, fixture_id", (at,))
            req = cur.fetchone()
        conn.commit()
        if req is None:
            return done
        status = "done"
        cycle_id: int | None = None
        try:
            if req["kind"] == "analysis":
                one = req["fixture_id"] is not None
                r = run_analysis_cycle(conn, at=at, settings=settings,
                                       only_fixtures=[int(req["fixture_id"])] if one else None, request=one)
                cycle_id = r.cycle_id
                status = "done" if r.status in ("ok", "partial") else "failed"
            elif req["kind"] in ("learning", "postmortem", "evaluation"):
                r = run_learning_cycle(conn, at=at, settings=settings)
                cycle_id = r.cycle_id
                status = "done" if r.status in ("ok", "partial") else "failed"
        except Exception:
            conn.rollback()
            status = "failed"
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("UPDATE ai.run_requests SET status = %s, cycle_id = %s WHERE id = %s",
                        (status, cycle_id, req["id"]))
        conn.commit()
        done += 1
