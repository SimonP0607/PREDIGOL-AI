"""What the AI layer costs - measured (``ai.usage``) and simulated before any provider is chosen.

Measured: requests, tokens (cached included), searches, images and dollars for today, the last 7 days, the
last 30 days and the calendar month, by purpose and by model, and the three unit costs the owner asked for:
per match analysed, per pick reviewed, per approved analysis.

Simulated: a day of work (matches, shortlisted selections, model reviews, the deep ones, web searches and
extractions, post-mortems) priced with each candidate set of models (``PROFILES``) from the verified price
table (``fbi.ai.pricing``). The day comes from the platform's own counts (``scripts/ai_simulate.py``); the
WORST CASE is every daily cap reached every day. A user reading an analysis costs nothing: analyses are
computed once per match and stored (200 users are not 200 calls).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.config import AiSettings
from fbi.ai.pricing import search_cost, token_cost
from fbi.ai.usage import budget

PERIODS = (("today", 0), ("7d", 7), ("30d", 30))

SUMMARY_SQL = """
SELECT count(*) AS requests, COALESCE(sum(input_tokens), 0) AS input_tokens, COALESCE(sum(output_tokens), 0) AS output_tokens,
       COALESCE(sum(cached_tokens), 0) AS cached_tokens, COALESCE(sum(searches), 0) AS searches,
       COALESCE(sum(vision_items), 0) AS vision, COALESCE(sum(cost_usd), 0) AS cost_usd,
       count(*) FILTER (WHERE status <> 'ok') AS failed, count(DISTINCT fixture_id) AS fixtures
  FROM ai.usage WHERE at >= %(since)s AND at < %(until)s
"""

BY_SQL = """
SELECT {col} AS key, count(*) AS requests, COALESCE(sum(cost_usd), 0) AS cost_usd,
       COALESCE(sum(input_tokens), 0) AS input_tokens, COALESCE(sum(output_tokens), 0) AS output_tokens
  FROM ai.usage WHERE at >= %(since)s AND at < %(until)s GROUP BY 1 ORDER BY 3 DESC
"""

REVIEWS_SQL = """
SELECT count(*) FILTER (WHERE engine = 'llm') AS llm_reviews,
       count(*) FILTER (WHERE engine = 'combined') AS reviews,
       count(*) FILTER (WHERE engine = 'combined' AND decision = 'APPROVE'
                        AND engine_version NOT LIKE '%%+none') AS approved_with_llm,
       count(DISTINCT fixture_id) AS fixtures_reviewed
  FROM ai.pick_reviews WHERE reviewed_at >= %(since)s AND reviewed_at < %(until)s
"""

LEGACY_SQL = ("SELECT COALESCE(sum(cost_usd), 0) AS cost FROM analytics.ai_runs WHERE started_at >= %(since)s "
              "AND started_at < %(until)s")


def _period(at: datetime, days: int) -> tuple[datetime, datetime]:
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    return (day if days == 0 else at - timedelta(days=days)), at + timedelta(seconds=1)


def _f(x: Any) -> float:
    return float(x or 0)


def summary(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None) -> dict[str, Any]:
    settings = settings or AiSettings.from_env()
    out: dict[str, Any] = {"periods": {}, "budget": budget(conn, at=at, settings=settings).as_json()}
    month_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for name, since, until in [(n, *_period(at, d)) for n, d in PERIODS] + [("month", month_start,
                                                                             at + timedelta(seconds=1))]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(SUMMARY_SQL, {"since": since, "until": until})
            s = dict(cur.fetchone() or {})
            cur.execute(REVIEWS_SQL, {"since": since, "until": until})
            r = dict(cur.fetchone() or {})
            cur.execute(LEGACY_SQL, {"since": since, "until": until})
            legacy = cur.fetchone()
            by_purpose = [dict(x) for x in cur.execute(BY_SQL.format(col="purpose"), {"since": since, "until": until})]
            by_model = [dict(x) for x in cur.execute(BY_SQL.format(col="provider || ':' || model"),
                                                     {"since": since, "until": until})]
        legacy_cost = _f((legacy or {}).get("cost"))
        cost = _f(s.get("cost_usd")) + legacy_cost
        review_cost = sum(_f(x["cost_usd"]) for x in by_purpose if x["key"] == "pick_review")
        out["periods"][name] = {
            "since": since.isoformat(), "requests": int(s.get("requests") or 0),
            "input_tokens": int(s.get("input_tokens") or 0), "output_tokens": int(s.get("output_tokens") or 0),
            "cached_tokens": int(s.get("cached_tokens") or 0), "searches": int(s.get("searches") or 0),
            "vision": int(s.get("vision") or 0), "failed": int(s.get("failed") or 0),
            "cost_usd": round(cost, 6), "legacy_cost_usd": round(legacy_cost, 6),
            "fixtures": int(s.get("fixtures") or 0), "llm_reviews": int(r.get("llm_reviews") or 0),
            "reviews": int(r.get("reviews") or 0), "approved_with_llm": int(r.get("approved_with_llm") or 0),
            "cost_per_match": round(cost / int(s["fixtures"]), 6) if s.get("fixtures") else None,
            "cost_per_review": round(review_cost / int(r["llm_reviews"]), 6) if r.get("llm_reviews") else None,
            "cost_per_approved": round(review_cost / int(r["approved_with_llm"]), 6) if r.get("approved_with_llm")
            else None,
            "by_purpose": [{"key": x["key"], "requests": int(x["requests"]), "cost_usd": round(_f(x["cost_usd"]), 6)}
                           for x in by_purpose],
            "by_model": [{"key": x["key"], "requests": int(x["requests"]), "cost_usd": round(_f(x["cost_usd"]), 6),
                          "input_tokens": int(x["input_tokens"]), "output_tokens": int(x["output_tokens"])}
                         for x in by_model],
        }
    return out


# ── simulation ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Profile:
    name: str
    bulk: tuple[str, str]
    analysis: tuple[str, str]
    final: tuple[str, str]
    search: str
    note: str = ""


PROFILES: tuple[Profile, ...] = (
    Profile("economico", ("anthropic", "claude-haiku-5-5"), ("anthropic", "claude-haiku-5-5"),
            ("anthropic", "claude-sonnet-5-5"), "exa", "un solo proveedor (ya integrado); Sonnet solo para los mejores"),
    Profile("economico_openai", ("openai", "gpt-6-luna"), ("openai", "gpt-6-luna"), ("openai", "gpt-6.1-sol"),
            "exa", "alternativa de precio equivalente; requiere cuenta nueva"),
    Profile("equilibrado", ("anthropic", "claude-haiku-5-5"), ("anthropic", "claude-sonnet-5-5"),
            ("anthropic", "claude-opus-5-5"), "exa", "Sonnet revisa la shortlist del día; Opus solo los mejores"),
    Profile("equilibrado_openai", ("openai", "gpt-6-luna"), ("openai", "gpt-6.1-sol"), ("openai", "gpt-6-astra"),
            "exa", "el mismo esquema con OpenAI; Astra cuesta 2,5 veces lo que Opus 5.5"),
    Profile("equilibrado_gemini", ("gemini", "gemini-3.1-flash-lite"), ("gemini", "gemini-3.8-flash"),
            ("gemini", "gemini-3.1-pro-preview"), "gemini", "búsqueda de Google incluida (5.000/mes); términos de "
            "almacenamiento de resultados con grounding: revisar"),
    Profile("equilibrado_deepseek", ("deepseek", "deepseek-flash"), ("deepseek", "deepseek-v4-pro"),
            ("deepseek", "deepseek-v4-pro"), "exa", "precio de hora punta; datos procesados en China"),
    Profile("alta_calidad", ("anthropic", "claude-haiku-5-5"), ("anthropic", "claude-opus-5-5"),
            ("anthropic", "claude-opus-5-5"), "exa", "Opus revisa todo; Haiku solo extrae noticias"),
    Profile("maxima_calidad", ("anthropic", "claude-sonnet-5-5"), ("anthropic", "claude-opus-5-5"),
            ("anthropic", "claude-fable-5-1"), "anthropic", "los modelos más fuertes en cada nivel"),
)


@dataclass
class Workload:
    """One day of work, from the platform's own counts."""

    matches: float
    shortlist: float
    llm_reviews: float
    deep_reviews: float
    web_fixtures: float
    searches_per_fixture: float = 1.0
    postmortem_narratives: float = 10.0
    pattern_calls: float = 1.0 / 7
    review_in: int = 6000
    review_out: int = 700
    extract_in: int = 2500
    extract_out: int = 600
    postmortem_in: int = 2500
    postmortem_out: int = 450
    pattern_in: int = 12000
    pattern_out: int = 900
    cached_share: float = 0.0
    """The share of review input the provider serves from its cache (the common instructions)."""
    notes: dict[str, Any] = field(default_factory=dict)


def _call(provider: str, model: str, n: float, tin: int, tout: int, cached_share: float, day: date) -> Decimal:
    cached = int(tin * cached_share)
    one = token_cost(provider, model, input_tokens=tin, output_tokens=tout, cached_tokens=cached, at=day)
    return one * Decimal(str(n))


def simulate(w: Workload, p: Profile, *, day: date) -> dict[str, Any]:
    deep = min(w.deep_reviews, w.llm_reviews)
    regular = max(0.0, w.llm_reviews - deep)
    parts = {
        "reviews": _call(*p.analysis, regular, w.review_in, w.review_out, w.cached_share, day),
        "deep_reviews": _call(*p.final, deep, w.review_in, w.review_out, w.cached_share, day),
        "extraction": _call(*p.bulk, w.web_fixtures, w.extract_in, w.extract_out, 0.0, day),
        "postmortems": _call(*p.bulk, w.postmortem_narratives, w.postmortem_in, w.postmortem_out, 0.0, day),
        "patterns": _call(*p.analysis, w.pattern_calls, w.pattern_in, w.pattern_out, 0.0, day),
    }
    searches = w.web_fixtures * w.searches_per_fixture
    if p.search == "gemini":
        free_per_day = 5000 / 30
        parts["searches"] = search_cost("gemini", int(max(0.0, searches - free_per_day)))
    else:
        parts["searches"] = search_cost(p.search, round(searches))
    total = sum(parts.values(), Decimal(0))
    return {"profile": p.name, "note": p.note, "per_day": {k: round(float(v), 4) for k, v in parts.items()},
            "day_usd": round(float(total), 4), "month_usd": round(float(total) * 30, 2),
            "per_match_usd": round(float(total) / w.matches, 5) if w.matches else None,
            "per_review_usd": round(float(parts["reviews"] + parts["deep_reviews"]) / w.llm_reviews, 5)
            if w.llm_reviews else None}


def worst_case(settings: AiSettings, w: Workload) -> Workload:
    """Every cap reached every day."""
    return Workload(matches=w.matches, shortlist=w.shortlist, llm_reviews=settings.max_llm_reviews_per_day,
                    deep_reviews=settings.max_deep_per_day, web_fixtures=12, searches_per_fixture=w.searches_per_fixture,
                    postmortem_narratives=10, pattern_calls=1, review_in=int(w.review_in * 1.5),
                    review_out=int(w.review_out * 1.5), extract_in=w.extract_in, extract_out=w.extract_out,
                    postmortem_in=w.postmortem_in, postmortem_out=w.postmortem_out, pattern_in=w.pattern_in,
                    pattern_out=w.pattern_out)
