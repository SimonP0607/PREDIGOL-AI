"""What the AI layer would cost, measured on the platform's own matches before any provider is contracted.

The analysis cycle (every 15 minutes, V2: models and the web only at the passes of TODAY's matches with a market)
and the daily learning cycle are run over past days of a COPY of the
database with a stand-in model (``FakeProvider``: it answers instantly and counts the tokens it is sent) and,
with ``--search``, a stand-in search engine returning five results per query. Every call the real layer would
make is then in ``ai.usage``: how many reviews, deep reviews, extractions, searches and post-mortems a day,
and how many tokens each one sends. Those calls are priced with each candidate set of models
(``fbi.ai.costs.PROFILES``) from the verified price table, plus a WORST CASE where every daily cap is reached.

It WRITES the ai.* tables of the database it is given: point it at a copy, never at production.

    python -m scripts.ai_simulate --dsn postgresql://...copy... --start 2026-10-03T00:00:00+00:00 --days 3 --search
    python -m scripts.ai_simulate ... --max-reviews 1000 --max-deep 15   # the demand when the daily cap does not bind
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ai.config import AiSettings
from fbi.ai.costs import PROFILES, Profile
from fbi.ai.cycle import run_analysis_cycle, run_learning_cycle
from fbi.ai.pricing import TOKEN_FACTOR, search_cost, token_cost
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared
from fbi.analyst.search import SearchResult

OUTPUT_TOKENS = {"pick_review": 1700, "evidence_extraction": 600, "postmortem": 450, "pattern_review": 900,
                 "match_brief": 1100, "learning": 900}
"""Planning output per call, thinking included (Claude 5.5 measured 8 Oct 2026: a review ~1,700 tokens out)."""
"""Planning output per call: a real answer is longer than the stand-in's (claims with references)."""
STEP_MINUTES = 15


def answer(req: JsonRequest) -> dict[str, Any]:
    if req.schema_name == "submit_review":
        return {"decision": "ABSTAIN", "confidence": 0.5, "context_score": 0.5, "model_score": 0.5,
                "market_score": 0.5, "positive_evidence": [], "negative_evidence": [], "uncertainties": [],
                "contradictions": [], "reason": "simulación", "minimum_playable_odds": None, "fair_odds": None}
    if req.schema_name == "submit_items":
        return {"items": []}
    if req.schema_name == "submit_brief":
        return {"summary": "simulación", "context": [], "injuries": [], "changes": [], "data_quality": "good",
                "uncertainty": "medium", "contradiction": False, "escalate": False, "cards": []}
    if req.schema_name == "submit_postmortem":
        return {"summary": "simulación", "agrees_with_class": True, "lessons": []}
    if req.schema_name == "submit_lessons":
        return {"lessons": []}
    return {"hypotheses": []}


def fake_search(query: str, at: datetime) -> list[SearchResult]:
    text = ("Team news: the coach confirmed that two players trained apart and one is a doubt for the match; "
            "the striker is expected to start after returning from suspension. " * 4)[:700]
    return [SearchResult(url=f"https://news{i}.example/{abs(hash(query)) % 10_000}", title=f"Preview {i}",
                         publisher=f"news{i}.example", published_at=at.isoformat(), retrieved_at=at.isoformat(),
                         snippet=text) for i in range(5)]


@contextmanager
def as_of_queries() -> Iterator[None]:
    """Past days read as they were: the live queries look at today's statuses (a match since played is no longer
    'scheduled', a settled pick is no longer a candidate). For the simulation only - and only inside this block -
    a match counts as upcoming by its kick-off, and a pick by its creation time. Production code is untouched."""
    from fbi.ai import cycle, day
    from fbi.api.repositories import product

    saved = (cycle.FIXTURES_SQL, product.PICK_CANDIDATES, day.UNIVERSE_SQL)
    cycle.FIXTURES_SQL = cycle.FIXTURES_SQL.replace("f.status_group = 'scheduled'",
                                                    "f.status_group IN ('scheduled', 'finished', 'live')")
    day.UNIVERSE_SQL = day.UNIVERSE_SQL.replace("f.status_group = 'scheduled'",
                                                "f.status_group IN ('scheduled', 'finished', 'live')")
    product.PICK_CANDIDATES = product.PICK_CANDIDATES.replace(
        "AND NOT EXISTS (SELECT 1 FROM picks.pick_results pr WHERE pr.pick_id = p.id AND pr.result_status <> 'pending')",
        "AND p.created_at <= %(now)s").replace(
        "p.status = 'shadow'", "p.status IN ('shadow', 'settled')").replace(  # settled since: shadow then
        "f.status_group AS fixture_status",
        "CASE WHEN f.kickoff_at > %(now)s AND f.status_group IN ('finished', 'live') THEN 'scheduled' "
        "ELSE f.status_group END AS fixture_status")  # played since: scheduled then
    assert saved[0] != cycle.FIXTURES_SQL and saved[1] != product.PICK_CANDIDATES and saved[2] != day.UNIVERSE_SQL, \
        "the queries changed: update this"
    try:
        yield
    finally:
        cycle.FIXTURES_SQL, product.PICK_CANDIDATES, day.UNIVERSE_SQL = saved


def simulate_calls(dsn: str, *, start: datetime, days: int, search: bool,
                   settings: AiSettings | None = None) -> dict[str, Any]:
    with as_of_queries():
        return _simulate_calls(dsn, start=start, days=days, search=search, settings=settings or sim_settings())


def sim_settings(max_reviews: int = 60, max_deep: int = 10) -> AiSettings:
    """The layer's daily caps as configured; the money caps out of the way (the point is to count calls). The free
    part looks 30 h ahead instead of 96 (the paid part only ever concerns today)."""
    return AiSettings(mode="shadow", daily_budget=Decimal(10_000), monthly_budget=Decimal(1_000_000),
                      max_llm_reviews_per_day=max_reviews, max_deep_per_day=max_deep, horizon_hours=30)


def _simulate_calls(dsn: str, *, start: datetime, days: int, search: bool, settings: AiSettings) -> dict[str, Any]:
    model = FakeProvider(answer, name="anthropic")
    timings: list[float] = []
    with psycopg.connect(dsn) as conn:
        ledger = UsageLedger(shared(conn))
        first_usage = conn.execute("SELECT COALESCE(max(id), 0) FROM ai.usage").fetchone()
        assert first_usage is not None
        at = start
        end = start + timedelta(days=days)
        while at < end:
            t = time.monotonic()
            run_analysis_cycle(conn, at=at, settings=settings, ledger=ledger, provider=(model, "claude-haiku-5-5"),
                               search=fake_search if search else None)
            timings.append(time.monotonic() - t)
            if at.hour == 12 and at.minute == 30:  # the learning job runs at 07:35 Bogota
                run_learning_cycle(conn, at=at + timedelta(minutes=5), settings=settings, ledger=ledger,
                                   provider=(model, "claude-haiku-5-5"))
            at += timedelta(minutes=STEP_MINUTES)
        conn.commit()
        rows = conn.execute(
            "SELECT at::date, purpose, tier, count(*), sum(input_tokens), sum(searches) FROM ai.usage WHERE id > %s "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 3", (first_usage[0],)).fetchall()
        matches = conn.execute(
            "SELECT count(*) FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id WHERE c.is_tracked AND f.kickoff_at >= %s "
            "AND f.kickoff_at < %s", (start, end)).fetchone()
    per_day: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(lambda: {"calls": 0, "input_tokens": 0}))
    for day, purpose, tier, n, tokens, _ in rows:
        key = f"{purpose}:{tier}"
        per_day[str(day)][key]["calls"] += int(n)
        per_day[str(day)][key]["input_tokens"] += int(tokens or 0)
    return {"days": days, "max_llm_reviews_per_day": settings.max_llm_reviews_per_day,
            "max_deep_per_day": settings.max_deep_per_day,
            "cycles": len(timings), "cycle_seconds_avg": round(sum(timings) / len(timings), 2),
            "cycle_seconds_max": round(max(timings), 2), "matches": int(matches[0]) if matches else 0,
            "per_day": {d: dict(v) for d, v in per_day.items()}}


def price(calls: dict[str, dict[str, Any]], profile: Profile, *, day: date, search_backend: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for key, c in calls.items():
        purpose, tier = key.split(":")
        n = int(c["calls"])
        if n == 0:
            continue
        if purpose == "web_search":
            backend = profile.search if search_backend == "profile" else search_backend
            free = 5000 / 30 if backend == "gemini" else 0
            out["searches"] += float(search_cost(backend, int(max(0.0, n - free))))
            continue
        provider, model = getattr(profile, tier)
        tokens_in = int(c["input_tokens"] / n * float(TOKEN_FACTOR.get(provider, Decimal(1))))
        one = token_cost(provider, model, input_tokens=tokens_in, output_tokens=OUTPUT_TOKENS.get(purpose, 600), at=day)
        out[purpose + ("_deep" if tier == "final" else "")] += float(one) * n
    return dict(out)


def report(sim: dict[str, Any], settings: AiSettings) -> dict[str, Any]:
    days = sim["per_day"]
    total: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "input_tokens": 0})
    for calls in days.values():
        for k, v in calls.items():
            total[k]["calls"] += v["calls"]
            total[k]["input_tokens"] += v["input_tokens"]
    n_days = max(1, len(days))
    avg = {k: {"calls": v["calls"] / n_days, "input_tokens": v["input_tokens"] / n_days} for k, v in total.items()}
    # WORST CASE: every capped call at its daily cap; every uncapped one at 1.5 x the busiest day measured;
    # every prompt 1.5 x longer than measured.
    caps = {"pick_review:analysis": settings.max_llm_reviews_per_day - settings.max_deep_per_day,
            "pick_review:final": settings.max_deep_per_day, "postmortem:bulk": 12, "postmortem:analysis": 3,
            "pattern_review:analysis": 1, "learning:analysis": 1}
    busiest = {k: max(int(d.get(k, {}).get("calls", 0)) for d in days.values()) for k in total}
    worst: dict[str, dict[str, Any]] = {}
    for k in set(total) | set(caps):
        calls = caps.get(k, math.ceil(1.5 * busiest.get(k, 0)))
        per_call = (total[k]["input_tokens"] / total[k]["calls"]) if total.get(k, {}).get("calls") else 9000
        worst[k] = {"calls": calls, "input_tokens": per_call * 1.5 * calls}
    today = datetime.now(UTC).date()
    profiles = []
    for p in PROFILES:
        typical = price(avg, p, day=today, search_backend="profile")
        bad = price(worst, p, day=today, search_backend="profile")
        profiles.append({"profile": p.name, "bulk": ":".join(p.bulk), "analysis": ":".join(p.analysis),
                         "final": ":".join(p.final), "search": p.search, "note": p.note,
                         "day_usd": round(sum(typical.values()), 4), "month_usd": round(30 * sum(typical.values()), 2),
                         "worst_day_usd": round(sum(bad.values()), 4),
                         "worst_month_usd": round(30 * sum(bad.values()), 2),
                         "per_match_usd": round(sum(typical.values()) / (sim["matches"] / n_days), 6)
                         if sim["matches"] else None,
                         "parts": {k: round(v, 4) for k, v in typical.items()}})
    return {"simulation": sim, "average_day": avg, "worst_day": worst, "profiles": profiles,
            "output_tokens_planned": OUTPUT_TOKENS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--max-reviews", type=int, default=60, help="FBI_AI_MAX_LLM_REVIEWS_PER_DAY to simulate")
    ap.add_argument("--max-deep", type=int, default=10, help="FBI_AI_MAX_DEEP_PER_DAY to simulate")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    settings = sim_settings(args.max_reviews, args.max_deep)
    sim = simulate_calls(args.dsn, start=datetime.fromisoformat(args.start), days=args.days, search=args.search,
                         settings=settings)
    text = json.dumps(report(sim, settings), indent=1, default=str, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
