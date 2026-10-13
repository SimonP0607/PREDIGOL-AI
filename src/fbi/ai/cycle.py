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
from fbi.ai.brief import Brief, make_brief
from fbi.ai.calendar import day_bounds, day_start, local_day
from fbi.ai.collectors import SearchFn, collect_provider, collect_web
from fbi.ai.config import AiSettings, Tier
from fbi.ai.day import Due, due_passes, open_day, universe
from fbi.ai.evidence import seed_sources
from fbi.ai.packet import CORE_KEYS, Packet, PacketBuilder, store_packet
from fbi.ai.prompts import REVIEW_VERSION
from fbi.ai.providers.base import LlmProvider
from fbi.ai.review import Candidate, Reviewed, carried_review, latest_reviews, review_candidate
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
CYCLE_LOCK = 7310073

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

ESCALATED_SQL = """
SELECT DISTINCT ON (fixture_id) fixture_id, escalate FROM ai.match_briefs
 WHERE fixture_id = ANY(%(fixtures)s) ORDER BY fixture_id, created_at DESC, id DESC
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
                       transport: httpx.BaseTransport | None = None, request: bool = False) -> CycleReport:
    settings = settings or AiSettings.from_env()
    report = CycleReport()
    if settings.mode == "off":
        report.status = "ok"
        report.counts["skipped_mode_off"] = 1
        return report
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (CYCLE_LOCK,))
        row = cur.fetchone()
    if not (row and row[0]):
        report.counts["skipped_busy"] = 1  # another cycle is running: it will do this one's work
        return report
    try:
        seed_sources(conn, at=at)
        conn.commit()
        report.cycle_id = open_cycle(conn, "analysis", at=at, settings=settings)
        ledger = ledger or UsageLedger()
        try:
            _run(conn, settings, report, at=at, ledger=ledger, only=only_fixtures, search=search, provider=provider,
                 transport=transport, request=request)
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
    return Allowance(llm=max(0, settings.max_llm_reviews_per_day - int(used.get("llm") or 0)),
                     deep=max(0, settings.max_deep_per_day - int(used.get("deep") or 0)),
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
         provider: tuple[LlmProvider, str] | None, transport: httpx.BaseTransport | None, request: bool) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"start": at + timedelta(minutes=10),
                                   "until": at + timedelta(hours=settings.horizon_hours), "limit": MAX_FIXTURES})
        fixtures = [(int(r["id"]), r["kickoff_at"]) for r in cur.fetchall()]
    if only:
        fixtures = [f for f in fixtures if f[0] in set(only)]
    report.counts["fixtures"] = len(fixtures)

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
    if dues and web_ready:
        with conn.cursor(row_factory=tuple_row) as tcur:
            tcur.execute(ESCALATED_SQL, {"fixtures": list(dues)})
            escalated = {int(r[0]) for r in tcur.fetchall() if r[1]}

        def rank(d: Due) -> tuple[int, int, float, float, datetime]:
            return web_rank(d, by_fixture)
        firsts = sorted((d for d in dues.values() if d.pass_kind in ("first", "request")), key=rank)
        pres = sorted((d for d in dues.values() if d.pass_kind == "pre"
                       and (d.fixture.fixture_id in by_fixture or d.fixture.fixture_id in escalated)), key=rank)
        web = {d.fixture.fixture_id for d in firsts[:allow.web_first]} | \
              {d.fixture.fixture_id for d in pres[:allow.web_pre]}

    # 4-5. packets, briefs, reviews, analyses - the paid ones first, by priority
    builder = PacketBuilder(conn)
    with conn.cursor(row_factory=tuple_row) as tcur:
        tcur.execute(NEWEST_PACKETS_SQL, {"fixtures": [f[0] for f in fixtures]})
        newest = {int(r[0]): r[1] for r in tcur.fetchall()}
    order = sorted(fixtures, key=lambda f: (f[0] not in dues, -(dues[f[0]].fixture.priority if f[0] in dues else 0),
                                            f[1]))
    health = {"llm_down": False}
    for fid, kickoff in order:
        due = dues.get(fid)
        try:
            if due is not None:
                _pass(conn, settings, report, due, by_fixture.get(fid, []), builder, at=at, ledger=ledger,
                      search=search, provider=provider, transport=transport, allow=allow, l3=l3,
                      web=fid in web, llm_ready=llm_ready, health=health)
            else:
                _free(conn, settings, report, fid, kickoff, by_fixture.get(fid, []), builder, newest, at=at)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            report.status = "partial"
            report.errors.append(f"fixture {fid}: {type(exc).__name__}: {exc}"[:200])
            log.warning("ai.cycle.fixture_failed", fixture=fid, error=f"{type(exc).__name__}: {exc}"[:200])


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


def _pass(conn: psycopg.Connection[Any], settings: AiSettings, report: CycleReport, due: Due, options: list[Ranked],
          builder: PacketBuilder, *, at: datetime, ledger: UsageLedger, search: SearchFn | None,
          provider: tuple[LlmProvider, str] | None, transport: httpx.BaseTransport | None, allow: Allowance,
          l3: set[tuple[int, str, str, Decimal]], web: bool, llm_ready: bool, health: dict[str, bool]) -> None:
    """One pass of one match of the day: web (when chosen), packet, L1 brief, L2/L3 reviews, cards, the pass row.
    A pass the provider failed (down, timing out) is not recorded: the next cycle tries it again."""
    fid, kind = due.fixture.fixture_id, due.pass_kind
    started = now()
    counts: dict[str, int] = defaultdict(int)
    cost = Decimal(0)
    report.counts[f"pass_{kind}"] += 1
    llm_ready = llm_ready and not health["llm_down"]
    transient = False
    # Near the budget a match without any candidate loses its paid depth first (``Budget.marginal_allowed``): no
    # model brief, no web. The candidates keep theirs up to the day's ceiling.
    deep = bool(options) or kind == "request" or budget_of(conn, at=at, settings=settings).marginal_allowed()
    if not deep:
        counts["marginal_saved"] += 1
        report.counts["marginal_saved"] += 1

    # the web (first and pre passes; the most important matches; only a stale cached answer is asked again)
    if web and deep and kind in ("first", "pre", "request") \
            and budget_of(conn, at=at, settings=settings).pass_allows(kind):
        # the tiered search (sources-v2): up to three levels for a match with candidates, one for the others
        got = collect_web(conn, settings, fid, at=at, ledger=ledger, search=search, provider=provider,
                          transport=transport, levels=3 if options else 1)
        counts["web_searches"] += got.searches
        counts["web_items"] += got.extracted
        counts["web_new"] += got.created
        cost += Decimal(str(got.cost_usd))
        report.counts["web_searches"] += got.searches
        report.counts["web_items"] += got.extracted
        if got.skipped:
            report.counts[f"web_skipped_{got.skipped}"] += 1
        conn.commit()

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
    if brief.escalate:
        report.counts["escalated"] += 1
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
        last = last_llm.get(key)
        b = budget_of(conn, at=at, settings=settings)
        use_llm = (llm_ready and allow.llm > 0 and b.pass_allows(kind) and b.allows("bulk")
                   and needs_llm(last, cand, evidence_ids=evidence_ids, lineups_confirmed=confirmed))
        reviewed = review_candidate(conn, settings, cand, packet, packet_id, at=at, use_llm=use_llm, tier=tier,
                                    ledger=ledger, transport=transport, provider=provider,
                                    prior_llm=None if use_llm else _carried(last, at=at),
                                    role="pick" if sel_key in l3 else "candidate")
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
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, "
                    "escalated, reasons, brief_id, packet_id, counts, cost_usd) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (fixture_id, day, pass) DO NOTHING",
                    (fid, local_day(at), kind, min(started, at), max(now(), at), due.fixture.kickoff_at, "ok",
                     brief.escalate, brief.reasons, brief.id, packet_id, Jsonb(dict(counts)), cost))


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


def run_learning_cycle(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                       ledger: UsageLedger | None = None, provider: tuple[LlmProvider, str] | None = None,
                       transport: httpx.BaseTransport | None = None) -> CycleReport:
    """Daily (worker job ``ai_learn``, 07:35 Bogotá): what the finished matches taught, written down - the
    post-mortems of every match (pm-v1) and of every studied selection (pm-v2), yesterday's notes and lessons
    (QUÉ APRENDIÓ PREDIGOL HOY), the sources' day, patterns proposed as hypotheses (never applied), the parlays'
    dependence re-measured weekly, the AI's own shadow report, the month's budget alerts - and tomorrow prepared
    without any model or search."""
    from fbi.ai.day import prepare_day
    from fbi.ai.learning import learn_day, refresh_source_stats
    from fbi.ai.patterns import run_patterns
    from fbi.ai.pick_postmortem import run_pick_postmortems
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
    today = local_day(at)
    yesterday = today - timedelta(days=1)
    try:
        pm = run_postmortems(conn, at=at, settings=settings, ledger=ledger, provider=provider, transport=transport)
        report.counts.update({"postmortems": pm.fixtures, "memory_events": pm.memory_events,
                              "context_errors": pm.context_errors, "narratives": pm.narratives})
        report.errors += pm.errors[:5]
        steps += 1
        pp = run_pick_postmortems(conn, at=at, settings=settings, ledger=ledger, provider=provider,
                                  transport=transport)
        report.counts.update({"pick_postmortems": pp.studied, "losses_studied": pp.losses, "wins_studied": pp.wins,
                              "pick_narratives": pp.narratives, "pick_memory_events": pp.memory_events})
        for cls, n in pp.by_class.items():
            report.counts[f"class_{cls.lower()}"] = n
        report.errors += pp.errors[:5]
        steps += 1
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
