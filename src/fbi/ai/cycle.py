"""The AI analysis cycle (worker job ``ai_cycle``, every 30 minutes; also on the owner's request).

    1  evidence     the provider's injury reports and confirmed line-ups of the matches in the next 48 h
                    (free), and - when configured - web team news for the best opportunities (paid, cached)
    2  shortlist    every selection passing the value gate at the current price in the next 72 h
                    (``fbi.picks.daily.passing``: the same gate as the picks of the day and the parlays)
    3  packets      one per match in the horizon, rebuilt only when its inputs changed (hash)
    4  reviews      rules for every shortlisted selection; a language model, when configured and the budget
                    allows, for the shortlist of the next 24 h - the strong (final) tier only for the day's
                    best few; a selection is re-reviewed by the model only when its context changed materially
    5  analyses     the per-match cards (``fbi.ai.analysis``)

Commits after each match: a failure part-way keeps what was done and is recorded in ``ai.cycles``. Nothing
here writes a pick, a probability, a parlay or a rule.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.analysis import ValueOption, build_cards, store_analysis
from fbi.ai.collectors import SearchFn, collect_provider, collect_web
from fbi.ai.config import AiSettings, Tier
from fbi.ai.evidence import seed_sources
from fbi.ai.packet import PacketBuilder, store_packet
from fbi.ai.prompts import REVIEW_VERSION
from fbi.ai.providers.base import LlmProvider
from fbi.ai.review import Candidate, Reviewed, carried_review, review_candidate
from fbi.ai.usage import UsageLedger
from fbi.ai.usage import budget as budget_of
from fbi.core.clock import now
from fbi.picks.daily import Ranked, load_candidates, passing

log = structlog.get_logger(__name__)

SHORTLIST_HORIZON = timedelta(hours=72)
LLM_HORIZON = timedelta(hours=24)
EVIDENCE_HORIZON = timedelta(hours=48)
WEB_HORIZON = timedelta(hours=36)
MAX_FIXTURES = 400
MAX_WEB_FIXTURES = 12
RE_REVIEW_AFTER = timedelta(hours=6)
PRICE_CHANGE = Decimal("0.03")
FAR_REFRESH = timedelta(hours=3)
"""A match more than a day away with nothing shortlisted: its packet is looked at again only after this long."""
NEAR_REFRESH = timedelta(hours=1)
"""Within the day, a match with nothing shortlisted: hourly (a shortlisted one is looked at every cycle)."""

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

LLM_TODAY_SQL = """
SELECT count(*) FILTER (WHERE r.engine = 'llm' AND r.status NOT IN ('over_budget', 'failed')
                        AND NOT r.output ? 'reused_from') AS llm,
       count(*) FILTER (WHERE r.engine = 'llm' AND r.model IS NOT NULL AND r.output->>'tier' = 'final'
                        AND r.status <> 'failed' AND NOT r.output ? 'reused_from') AS deep
  FROM ai.pick_reviews r WHERE r.reviewed_at >= %(day)s
"""


@dataclass
class CycleReport:
    cycle_id: int | None = None
    status: str = "ok"
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cost_usd: Decimal = Decimal(0)
    errors: list[str] = field(default_factory=list)


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
        cur.execute("UPDATE ai.cycles SET finished_at = %s, status = %s, counts = %s, cost_usd = %s, error = %s "
                    "WHERE id = %s", (max(at, now()), report.status, Jsonb(dict(report.counts)),
                                      report.cost_usd, "; ".join(report.errors)[:500] or None, cycle_id))
    conn.commit()


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


def needs_llm(last: dict[str, Any] | None, cand: Candidate, *, at: datetime, evidence_ids: set[int],
              lineups_confirmed: bool) -> bool:
    """A new model review only when something material changed: the price moved more than 3 %, new evidence,
    the line-ups were confirmed since, the last one is older than six hours - or was made by an older version of
    the reviewer."""
    if last is None:
        return True
    if last.get("engine_version") != REVIEW_VERSION:
        return True
    if at - last["reviewed_at"] >= RE_REVIEW_AFTER:
        return True
    if cand.odds is not None and last["odds"] is not None and \
            abs(cand.odds - Decimal(last["odds"])) / Decimal(last["odds"]) > PRICE_CHANGE:
        return True
    if evidence_ids - set(last["evidence_ids"] or []):
        return True
    return lineups_confirmed and at - last["reviewed_at"] > timedelta(minutes=30)


def run_analysis_cycle(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                       ledger: UsageLedger | None = None, only_fixtures: list[int] | None = None,
                       search: SearchFn | None = None, provider: tuple[LlmProvider, str] | None = None,
                       transport: httpx.BaseTransport | None = None) -> CycleReport:
    settings = settings or AiSettings.from_env()
    report = CycleReport()
    if settings.mode == "off":
        report.status = "ok"
        report.counts["skipped_mode_off"] = 1
        return report
    seed_sources(conn, at=at)
    conn.commit()
    report.cycle_id = open_cycle(conn, "analysis", at=at, settings=settings)
    ledger = ledger or UsageLedger()
    try:
        _run(conn, settings, report, at=at, ledger=ledger, only=only_fixtures, search=search, provider=provider,
             transport=transport)
    except Exception as exc:  # the cycle records its own failure; the worker carries on
        report.status = "failed"
        report.errors.append(f"{type(exc).__name__}: {exc}"[:300])
        log.error("ai.cycle.failed", error=report.errors[-1])
    close_cycle(conn, report.cycle_id, report, at=at)
    return report


def _run(conn: psycopg.Connection[Any], settings: AiSettings, report: CycleReport, *, at: datetime,
         ledger: UsageLedger, only: list[int] | None, search: SearchFn | None,
         provider: tuple[LlmProvider, str] | None, transport: httpx.BaseTransport | None) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"start": at + timedelta(minutes=10),
                                   "until": at + timedelta(hours=settings.horizon_hours), "limit": MAX_FIXTURES})
        fixtures = [(int(r["id"]), r["kickoff_at"]) for r in cur.fetchall()]
    if only:
        fixtures = [f for f in fixtures if f[0] in set(only)]
    report.counts["fixtures"] = len(fixtures)

    # 1. evidence from the provider
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

    # 2. the shortlist: the value gate at the current price, one per selection
    rows = load_candidates(conn, at=at, until=at + SHORTLIST_HORIZON, include_shadow=True)
    ranked = [x for x in passing(rows, at=at, source="evaluation") if x.elg > 0]
    wanted = {f[0] for f in fixtures}
    by_fixture: dict[int, list[Ranked]] = defaultdict(list)
    for x in ranked:
        if x.leg.candidate.fixture_id in wanted:
            by_fixture[x.leg.candidate.fixture_id].append(x)
    report.counts["shortlist"] = sum(len(v) for v in by_fixture.values())

    # web team news for the best opportunities (paid: configured, budgeted, cached)
    if settings.search_configured or search is not None:
        best = sorted(((max(x.elg for x in xs), fid) for fid, xs in by_fixture.items()), reverse=True)
        kickoffs = dict(fixtures)
        for _, fid in best[:MAX_WEB_FIXTURES]:
            if kickoffs[fid] - at > WEB_HORIZON:
                continue
            got = collect_web(conn, settings, fid, at=at, ledger=ledger, search=search, provider=provider,
                              transport=transport)
            report.counts["web_searches"] += got.searches
            report.counts["web_items"] += got.extracted
            report.cost_usd += Decimal(str(got.cost_usd))
            if got.skipped:
                report.counts[f"web_skipped_{got.skipped}"] += 1
            conn.commit()

    # the day's model allowance
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LLM_TODAY_SQL, {"day": day})
        today = cur.fetchone() or {"llm": 0, "deep": 0}
    llm_left = max(0, settings.max_llm_reviews_per_day - int(today["llm"] or 0))
    deep_left = max(0, settings.max_deep_per_day - int(today["deep"] or 0))
    soon = sorted((x for xs in by_fixture.values() for x in xs if x.leg.candidate.kickoff_at - at <= LLM_HORIZON),
                  key=lambda x: -x.elg)
    deep_keys = {x.leg.candidate.selection_key for x in soon[:deep_left]}
    llm_ready = settings.llm_configured or provider is not None

    # 3-5. packets, reviews, analyses
    builder = PacketBuilder(conn)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(NEWEST_PACKETS_SQL, {"fixtures": [f[0] for f in fixtures]})
        newest = {int(r[0]): r[1] for r in cur.fetchall()}
    for fid, kickoff in fixtures:
        try:
            options = by_fixture.get(fid, [])
            last_packet = newest.get(fid)
            every = FAR_REFRESH if kickoff - at > LLM_HORIZON else NEAR_REFRESH
            if not options and last_packet is not None and timedelta(0) <= at - last_packet < every:
                report.counts["packets_not_due"] += 1
                continue
            extra = [(x.leg.candidate.market_key, x.leg.candidate.selection, x.leg.candidate.line) for x in options]
            packet = builder.build(fid, at=at, extra_keys=extra)
            if packet is None:
                continue
            packet_id = store_packet(conn, packet, built_at=at)
            report.counts["packets"] += 1
            reviews: dict[tuple[str, str, Decimal], Reviewed] = {}
            if options:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(LAST_LLM_SQL, {"fixture": fid})
                    last_llm = {(r["market_key"], r["selection"], Decimal(r["line"])): r for r in cur.fetchall()}
                evidence_ids = {int(e["id"]) for e in packet.content.get("evidence", [])}
                confirmed = bool(packet.content.get("lineups", {}).get("confirmed"))
                for x in options:
                    cand = candidate_of(x, packet.content.get("models") or {})
                    key = (cand.market_key, cand.selection, cand.line)
                    use_llm = (llm_ready and llm_left > 0 and kickoff - at <= LLM_HORIZON
                               and needs_llm(last_llm.get(key), cand, at=at, evidence_ids=evidence_ids,
                                             lineups_confirmed=confirmed))
                    tier: Tier = "final" if x.leg.candidate.selection_key in deep_keys else "analysis"
                    last = last_llm.get(key)
                    prior = None
                    if not use_llm and last is not None and last["status"] == "ok" \
                            and at - last["reviewed_at"] < RE_REVIEW_AFTER:
                        prior = carried_review(last)  # still in force: combined again, not paid again
                    reviewed = review_candidate(conn, settings, cand, packet, packet_id, at=at, use_llm=use_llm,
                                                tier=tier, ledger=ledger, transport=transport, provider=provider,
                                                prior_llm=prior)
                    reviews[key] = reviewed
                    report.counts["reviews"] += 1
                    report.counts[f"decision_{reviewed.decision.lower()}"] += 1
                    if reviewed.llm is not None:
                        llm_left -= 1
                        report.counts["llm_reviews"] += 1
                        report.cost_usd += reviewed.llm.cost
                        if reviewed.llm.status != "ok":
                            report.counts[f"llm_{reviewed.llm.status}"] += 1
            cards = build_cards(packet, [value_option(x) for x in options], reviews)
            engines = ["rules"] + (["llm"] if any(r.by_llm for r in reviews.values()) else [])
            _, created = store_analysis(conn, packet, packet_id, cards, at=at, engines=engines)
            report.counts["analyses_new" if created else "analyses_same"] += 1
            conn.commit()
        except Exception as exc:
            conn.rollback()
            report.status = "partial"
            report.errors.append(f"fixture {fid}: {type(exc).__name__}: {exc}"[:200])
            log.warning("ai.cycle.fixture_failed", fixture=fid, error=f"{type(exc).__name__}: {exc}"[:200])


# ── learning: post-mortems, patterns, dependence, the AI's shadow evaluation ──

CORRELATION_EVERY = timedelta(days=7)
CORRELATION_WINDOW = timedelta(days=730)


def run_learning_cycle(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                       ledger: UsageLedger | None = None, provider: tuple[LlmProvider, str] | None = None,
                       transport: httpx.BaseTransport | None = None) -> CycleReport:
    """Daily (worker job ``ai_learn``): what the finished matches taught, written down; patterns proposed as
    hypotheses; the parlays' dependence re-measured weekly; the AI's own shadow report."""
    from fbi.ai.patterns import run_patterns
    from fbi.ai.postmortem import run_postmortems
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
    try:
        pm = run_postmortems(conn, at=at, settings=settings, ledger=ledger, provider=provider, transport=transport)
        report.counts.update({"postmortems": pm.fixtures, "memory_events": pm.memory_events,
                              "context_errors": pm.context_errors, "narratives": pm.narratives})
        report.errors += pm.errors[:5]
        steps += 1
        pat = run_patterns(conn, at=at, settings=settings, ledger=ledger, use_llm=at.weekday() == 0,
                           provider=provider, transport=transport)
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
    except Exception as exc:
        conn.rollback()
        report.status = "partial" if steps else "failed"
        report.errors.append(f"{type(exc).__name__}: {exc}"[:300])
        log.error("ai.learning.failed", error=report.errors[-1])
    close_cycle(conn, report.cycle_id, report, at=at)
    return report


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
                r = run_analysis_cycle(conn, at=at, settings=settings,
                                       only_fixtures=None if req["fixture_id"] is None else [int(req["fixture_id"])])
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
