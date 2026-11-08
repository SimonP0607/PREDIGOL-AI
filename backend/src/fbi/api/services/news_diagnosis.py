"""Why a match has news or not (IA-019; plan Partidos y Match Center, point 4): the owner's diagnosis in «Avanzado / Auditoría».

Reading only, from what already exists - nothing is searched, paid, written or decided here:

* the match: its kick-off, its competition and the owner's priority group (``fbi.intel.day_priority.group_of``), and whether it is in the
  guaranteed news coverage of IA-016 (``fbi.ai.cycle.NEWS_GROUPS`` with ``FBI_AI_NEWS_PRIORITY``);
* the AI's day (``fbi.ai.day``): whether the match has a market by the day's own rule (``universe``) and whether its Bogotá day has opened
  (00:05);
* its passes (``ai.fixture_passes``) with their web counts, and the pass it is waiting for (``next_pass``, pure, from the constants of
  ``fbi.ai.day.due_pass``);
* the searches paid for it (``ai.usage``, purpose ``web_search``), Exa's envelope of the month (``fbi.ai.budget_v3.exa_budget``) and the web
  items kept for it by status - read by the reader's news themselves (``fbi.api.services.news.stored_items``), so this module reads no
  evidence of its own;
* one verdict (``verdict``, pure): the first reason that applies, from «searched» to «outside the guaranteed coverage».

Only a SUPER_ADMIN reaches it (``/api/v1/admin``); a reader's news say only whether the match was searched (``fbi.api.services.news``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, cast

import psycopg

from fbi.ai.budget_v3 import exa_budget
from fbi.ai.calendar import DAY_TZ, local_day
from fbi.ai.config import AiSettings
from fbi.ai.cycle import NEWS_GROUPS
from fbi.ai.day import (
    FINAL_FROM,
    FINAL_WAIT_UNTIL,
    MIN_LEAD,
    OPENS_AT,
    PRE_AFTER_FIRST,
    PRE_FROM,
    PRE_UNTIL,
    universe,
)
from fbi.api.contracts.news import (
    DiagnosisCode,
    DiagnosisCoverage,
    DiagnosisDay,
    DiagnosisExa,
    DiagnosisMatch,
    DiagnosisNextPass,
    DiagnosisPass,
    DiagnosisSearches,
    DiagnosisVerdict,
    NewsDiagnosis,
    NewsStatus,
)
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services.news import STATUS_ORDER, search_state, stored_items
from fbi.core.clock import now
from fbi.intel.day_priority import group_of

FIXTURE_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_group, th.name AS home, ta.name AS away, c.name AS competition, c.provider_league_id,
       c.is_tracked
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.id = %(f)s
"""

PASSES_SQL: Final = """
SELECT pass, day, started_at, finished_at, status, counts FROM ai.fixture_passes
 WHERE fixture_id = %(f)s AND finished_at <= %(at)s ORDER BY started_at, id
"""

USAGE_SQL: Final = """
SELECT count(*) FILTER (WHERE status = 'ok') AS searches, count(*) FILTER (WHERE status <> 'ok') AS failed,
       min(at) FILTER (WHERE status = 'ok') AS first_at, max(at) FILTER (WHERE status = 'ok') AS last_at,
       COALESCE(sum(cost_usd) FILTER (WHERE status = 'ok'), 0) AS cost_usd
  FROM ai.usage WHERE fixture_id = %(f)s AND purpose = 'web_search' AND at <= %(at)s
"""
"""One row per search tried for the match (``fbi.ai.collectors``): only an answered one is paid."""

# ── the pass a match is waiting for ─────────────────────────────────────────────────────────────────────────────────


def opens_at(day: date) -> datetime:
    """When a Bogotá day opens for the AI (00:05)."""
    return datetime.combine(day, OPENS_AT, tzinfo=DAY_TZ)


def next_pass(kickoff: datetime, *, at: datetime, done: Mapping[str, datetime]) -> DiagnosisNextPass | None:
    """The pass a match with a market is waiting for, and its window (pure), by the rule of ``fbi.ai.day.due_pass``: first from the
    opening of the match's day; pre from 6 h before (and 2 h after the first) until 90 min before, unless the final came first; final
    from 100 min before - without the confirmed line-ups it waits until 50 min before - and never in the last 10 minutes. ``done``: the
    passes of the match's day with their end. None when no pass is left."""
    until = kickoff - MIN_LEAD
    if at >= until or "final" in done:
        return None
    if "first" not in done:
        start = opens_at(local_day(kickoff))
        if start >= until:
            return None
        return DiagnosisNextPass(kind="first", window_from=start, window_until=until, due_now=at >= start)
    final_from = kickoff - FINAL_FROM
    if "pre" not in done and at < final_from:
        pre_from, pre_until = max(kickoff - PRE_FROM, done["first"] + PRE_AFTER_FIRST), kickoff - PRE_UNTIL
        if pre_from < pre_until and at < pre_until:
            return DiagnosisNextPass(kind="pre", window_from=pre_from, window_until=pre_until, due_now=at >= pre_from)
    return DiagnosisNextPass(kind="final", window_from=final_from, window_until=until, lineups_until=kickoff - FINAL_WAIT_UNTIL,
                             due_now=at >= final_from)


# ── the verdict ─────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Facts:
    """What the verdict reads, gathered from the database (or written by a test)."""
    at: datetime
    kickoff: datetime
    has_market: bool | None
    opened: bool
    covered: bool
    passes: Sequence[DiagnosisPass]
    """Every pass of the match (its day's decide whether the first one ran)."""
    searches: DiagnosisSearches
    items: int
    exa: DiagnosisExa | None
    next_pass: DiagnosisNextPass | None


def searched_at(passes: Sequence[DiagnosisPass], searches: DiagnosisSearches) -> datetime | None:
    """The newest search of the match (pure): a search paid, or a pass that read the web (a fresh search or one answered by the
    cache) - the same rule as the reader's «was it searched» (``fbi.api.services.news.search_state``)."""
    read = [p.finished_at for p in passes if p.web.get("web_asked", 0) > 0 or p.web.get("web_searches", 0) > 0]
    moments = [m for m in (searches.last_at, max(read, default=None)) if m is not None]
    return max(moments, default=None)


def verdict(f: Facts) -> DiagnosisVerdict:
    """Why the match has news or not (pure): the first reason that applies, in this order - searched; its competition is not followed; no
    market; it kicked off unsearched; its day has not opened; Exa's envelope is spent; the first pass has not run; the passes saved their
    depth near the budget; covered but its passes did not search; outside the guaranteed coverage and without a place among the day's
    searches."""
    nxt = f.next_pass

    def waiting(code: DiagnosisCode, exa_reason: str | None = None) -> DiagnosisVerdict:
        return DiagnosisVerdict(code=code, exa_reason=exa_reason, next_pass=None if nxt is None else nxt.kind,
                                next_at=None if nxt is None else nxt.window_from)

    last = searched_at(f.passes, f.searches)
    if last is not None:
        return DiagnosisVerdict(code="searched", at=last, searches=f.searches.searches, pages=f.searches.sources_read, items=f.items)
    if f.has_market is None:
        return DiagnosisVerdict(code="not_tracked")
    if not f.has_market:
        return DiagnosisVerdict(code="no_market")
    if f.kickoff - f.at <= MIN_LEAD:
        return DiagnosisVerdict(code="kicked_off")
    if not f.opened:
        return waiting("day_not_open")
    if f.exa is not None and not f.exa.allowed:
        return waiting("exa_spent", f.exa.reason)
    today = [p for p in f.passes if p.day == local_day(f.kickoff)]
    if not any(p.kind == "first" for p in today):
        return waiting("first_pending")
    if any(p.near_budget for p in today):
        return waiting("near_budget")
    return waiting("covered_not_searched" if f.covered else "not_covered")


# ── reading it ──────────────────────────────────────────────────────────────────────────────────────────────────────


def pass_of(row: Mapping[str, Any]) -> DiagnosisPass:
    counts = cast(dict[str, Any], row.get("counts") or {})
    web = {k: int(v) for k, v in counts.items() if k.startswith("web_") and isinstance(v, int | float)}
    return DiagnosisPass(kind=row["pass"], day=row["day"], started_at=row["started_at"], finished_at=row["finished_at"],
                         status=str(row["status"]), web=web, near_budget=int(counts.get("marginal_saved") or 0) > 0)


def pages_read(passes: Sequence[DiagnosisPass], searches: DiagnosisSearches) -> int | None:
    """The pages read across the passes, by the reader's own rule (``search_state``, pure): 0 when never searched, unknown when a pass that
    searched did not count them."""
    counted = [p.web["web_read"] for p in passes if "web_read" in p.web]
    row = {"paid_at": searched_at(passes, searches), "searches": searches.searches, "pass_at": None,
           "sources_read": sum(counted) if counted else None,
           "untracked": sum(1 for p in passes if p.web.get("web_searches", 0) > 0 and "web_read" not in p.web)}
    return search_state(row).sources_read


def _exa(conn: Conn, *, at: datetime, settings: AiSettings) -> DiagnosisExa | None:
    try:
        with conn.transaction():
            b = exa_budget(conn, at=at, settings=settings)
    except psycopg.Error:
        return None
    return DiagnosisExa(allowed=b.allowed, reason=b.reason, budget_usd=b.envelope, spent_month_usd=b.spent_month,
                        spent_today_usd=b.spent_today, daily_cap_usd=b.cap)


def diagnosis(conn: Conn, fixture_id: int, *, at: datetime | None = None, settings: AiSettings | None = None) -> Envelope[NewsDiagnosis]:
    at = at or now()
    settings = settings or AiSettings.from_env()
    f = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if f is None:
        raise ApiError(404, "not_found", "no such fixture")
    kickoff: datetime = f["kickoff_at"]
    league = None if f["provider_league_id"] is None else int(f["provider_league_id"])
    group = group_of(league)
    day = local_day(kickoff)
    mine = next((x for x in universe(conn, day=day, at=at, scheduled_only=False)
                 if x.fixture_id == fixture_id), None)
    has_market = None if mine is None else mine.has_market
    every = [pass_of(r) for r in fetch_all(conn, PASSES_SQL, {"f": fixture_id, "at": at})]
    today = [p for p in every if p.day == day]
    u = fetch_one(conn, USAGE_SQL, {"f": fixture_id, "at": at}) or {}
    searches = DiagnosisSearches(searches=int(u.get("searches") or 0), failed=int(u.get("failed") or 0), first_at=u.get("first_at"),
                                 last_at=u.get("last_at"), cost_usd=Decimal(u.get("cost_usd") or 0))
    searches = searches.model_copy(update={"sources_read": pages_read(every, searches)})
    evidence: dict[NewsStatus, int] = dict.fromkeys(STATUS_ORDER, 0)
    newest: datetime | None = None
    for item in stored_items(conn, fixture_id, at=at):
        if item.status in evidence:
            evidence[item.status] += 1
        newest = item.retrieved_at if newest is None or item.retrieved_at > newest else newest
    nxt = None if not has_market else next_pass(kickoff, at=at, done={p.kind: p.finished_at for p in today})
    exa = _exa(conn, at=at, settings=settings)
    covered = settings.news_priority and group in NEWS_GROUPS
    start = opens_at(day)
    facts = Facts(at=at, kickoff=kickoff, has_market=has_market, opened=at >= start, covered=covered, passes=every, searches=searches,
                  items=sum(evidence.values()), exa=exa, next_pass=nxt)
    return ok(NewsDiagnosis(
        as_of=at,
        match=DiagnosisMatch(fixture_id=fixture_id, kickoff_at=kickoff, status_group=str(f["status_group"]), home=f["home"], away=f["away"],
                             competition=f["competition"], provider_league_id=league, priority_group=group, tracked=bool(f["is_tracked"])),
        coverage=DiagnosisCoverage(covered=covered, switch_on=settings.news_priority, groups=sorted(NEWS_GROUPS)),
        day=DiagnosisDay(day=day, opens_at=start, opened=at >= start, has_market=has_market, odds_at=None if mine is None else mine.odds_at),
        passes=every, next_pass=nxt, searches=searches, exa=exa, evidence=evidence, evidence_newest_at=newest, verdict=verdict(facts)))

