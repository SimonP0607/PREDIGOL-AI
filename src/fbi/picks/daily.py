"""DAILY_PICK_SET: up to five picks per product day, chosen progressively and then frozen.

Rule ``daily-set-v2`` (v1, 2026-10-04 only, let a probability without an interval stand in
for its own low end; its records are kept as they were chosen). The product day runs midnight to midnight in America/Bogota, where
the platform's users are. Every pipeline run (and every price capture) revisits the next
24 hours:

* A pick is a candidate once its match is within 24 hours (the T-24h stage) and at least
  ten minutes away, and only if it passes the value gate AT THE PRICE AVAILABLE NOW
  (``fbi.parlays.engine.assess``: a current price from two or more books, not an outlier,
  positive expected value).
* Candidates are ranked by expected log growth of a 1% stake computed with the PESSIMISTIC
  end of the model's interval (``p_low``): an uncertain probability pays for its
  uncertainty before it can outrank a firmer one, and a pick whose pessimistic growth is
  not positive is not worth taking at all, whatever its expected value. A probability
  WITHOUT a measured interval has no pessimistic end: it is not ranked, rather than ranked
  as if it were certain (its point estimate standing in for the low end would make the
  least-measured probabilities look the firmest).
* The set fills up to five, one pick per match, in rank order. Never padded: a day with
  two picks worth taking has two.
* An item is FROZEN when it enters the set: the price, bookmaker, probabilities, expected
  value, model version, the stage it was taken at (T-24h, T-12h, T-6h or T-3h) and the gate's
  inputs. Later prices move; the record does not. It stays after kick-off and is settled
  after the match (``fbi.picks.product_settlement``).

Two sets per day: ``qualified`` (picks whose model version beat the market in its own
backtest - the only set a user sees) and ``evaluation`` (shadow picks too - the owner's
preview, labelled evaluation mode). While no model has qualified, the qualified set stays
empty, honestly.

``daily-set-v3`` (8 Oct 2026) adds the AI review (``fbi.ai``): every item freezes the newest combined
review of its selection (decision, confidence, reason, mode). The review changes the choice only when it
is ENFORCED - the owner's ``FBI_AI_MODE=enforce`` and the AI's own shadow gate passed
(``fbi.ai.gating``): then a REJECTED selection is left out and a DOWNGRADED one ranks after the rest.
Until then the set is exactly what the quantitative rule chooses and the review is a record beside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.parlays.engine import Candidate, GateConfig, Leg, assess

RULE_VERSION = "daily-set-v3"
DAY_TZ = ZoneInfo("America/Bogota")
MAX_ITEMS = 5
HORIZON = timedelta(hours=24)
STAKE_FRACTION = 0.01
STAGES: tuple[tuple[int, str], ...] = ((180, "T-3h"), (360, "T-6h"), (720, "T-12h"), (1440, "T-24h"))
CONSENSUS_LOOKBACK = timedelta(hours=36)
GATE = GateConfig()
"""The value gate's limits, as frozen into every item's inputs (shadow picks differ only in
``allow_unqualified``)."""
Source = Literal["qualified", "evaluation"]
SOURCES: tuple[Source, ...] = ("qualified", "evaluation")


def product_day(at: datetime) -> date:
    return at.astimezone(DAY_TZ).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=DAY_TZ)
    return start, start + timedelta(days=1)


def stage_of(minutes_to_kickoff: float) -> str | None:
    """The tightest stage the match has reached: T-3h, T-6h, T-12h or T-24h; None before T-24h."""
    for limit, label in STAGES:
        if minutes_to_kickoff <= limit:
            return label
    return None


def win_probability(p: Decimal, p_push: Decimal | None) -> float:
    """Unconditional probability the bet wins: the stored probability is conditional on it settling."""
    return float(p) * (1.0 - float(p_push or 0))


def single_elg(odds: Decimal, p_low: Decimal, p_push: Decimal | None, f: float = STAKE_FRACTION) -> float:
    """Expected log growth of staking ``f`` of a bankroll, at the pessimistic probability."""
    p_win = win_probability(p_low, p_push)
    p_push_f = float(p_push or 0)
    p_lose = max(0.0, 1.0 - p_win - p_push_f)
    return p_win * math.log(1 + f * (float(odds) - 1)) + p_lose * math.log(1 - f)


def candidate_of(r: dict[str, Any]) -> Candidate:
    return Candidate(
        pick_id=int(r["pick_id"]), fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"],
        fixture_status=r["fixture_status"], home_team_id=int(r["home_team_id"]),
        away_team_id=int(r["away_team_id"]), market_key=r["market_key"], selection=r["selection"],
        line=Decimal(r["line"]), qualified=r["pick_status"] in ("qualified", "published"),
        model_status=r["model_status"], p_model=Decimal(r["p_model"]),
        p_push=Decimal(r["p_push"]) if r.get("p_push") is not None else None,
        p_market_fair=Decimal(r["p_fair"]) if r.get("p_fair") is not None else None,
        price=Decimal(r["best_odds"]) if r.get("best_odds") is not None else None,
        price_at=r.get("price_at"), n_bookmakers=r.get("n_bookmakers"),
    )


@dataclass(frozen=True, slots=True)
class Ranked:
    leg: Leg
    row: dict[str, Any]
    p_low: Decimal
    elg: float


def passing(rows: list[dict[str, Any]], *, at: datetime, source: Source) -> list[Ranked]:
    """Every candidate through the value gate at the current price; one per selection (the best
    pessimistic growth), ranked best first."""
    cfg = GateConfig(allow_unqualified=source == "evaluation")
    best: dict[tuple[int, str, str, Decimal], Ranked] = {}
    for r in rows:
        if r.get("p_low") is None:
            continue  # no measured interval: no pessimistic end to rank by
        verdict = assess(candidate_of(r), at, cfg)
        if not isinstance(verdict, Leg):
            continue
        c = verdict.candidate
        assert c.price is not None
        # The pick stores its bounds on its probability's footing: conditional on the bet
        # settling (``fbi.picks.engine``). No pick with a push probability has ever been stored
        # with bounds on the other footing (the table's interval check refused them).
        p_low = min(Decimal(r["p_low"]), c.p_model)
        ranked = Ranked(verdict, r, p_low, single_elg(c.price, p_low, c.p_push))
        key = c.selection_key
        if key not in best or ranked.elg > best[key].elg:
            best[key] = ranked
    return sorted(best.values(), key=lambda x: (-x.elg, -float(x.leg.ev), x.leg.candidate.kickoff_at,
                                                 x.leg.candidate.pick_id))


@dataclass(frozen=True)
class AiView:
    """The newest combined AI review of each candidate, and whether reviews may change the choice."""

    reviews: dict[tuple[int, str, str, Decimal], dict[str, Any]] = field(default_factory=dict)
    enforced: bool = False
    mode: str = "off"
    reason: str = "ai_unavailable"

    def decision(self, x: Ranked) -> str | None:
        r = self.reviews.get(x.leg.candidate.selection_key)
        return None if r is None else str(r["decision"])

    def record(self, x: Ranked) -> dict[str, Any]:
        r = self.reviews.get(x.leg.candidate.selection_key)
        base: dict[str, Any] = {"mode": self.mode, "enforced": self.enforced, "why": self.reason}
        if r is None:
            return base | {"decision": None}
        out = dict(r.get("output") or {})
        return base | {"decision": r["decision"], "review_id": int(r["id"]), "engine_version": r["engine_version"],
                       "model": r.get("model"), "reviewed_at": r["reviewed_at"].isoformat(),
                       "confidence": str(r["confidence"]), "reason": out.get("reason")}

    def apply(self, ranked: list[Ranked], *, drop_downgraded: bool = False) -> list[Ranked]:
        """In enforce mode: rejected selections out (downgraded ones too for parlays), downgraded ones after the
        rest; otherwise the list unchanged."""
        if not self.enforced:
            return ranked
        bad = {"REJECT", "DOWNGRADE"} if drop_downgraded else {"REJECT"}
        kept = [x for x in ranked if self.decision(x) not in bad]
        return sorted(kept, key=lambda x: self.decision(x) == "DOWNGRADE")  # stable: rank order otherwise


def ai_view(conn: psycopg.Connection[Any], ranked: list[Ranked], *, at: datetime) -> AiView:
    """Read in a savepoint: without the AI tables (an older database) the set is built as before."""
    from fbi.ai.config import AiSettings
    from fbi.ai.gating import enforcement
    from fbi.ai.review import latest_reviews

    settings = AiSettings.from_env()
    fixtures = sorted({x.leg.candidate.fixture_id for x in ranked})
    try:
        with conn.transaction():
            reviews = latest_reviews(conn, fixtures, at=at)
            enf = enforcement(conn, settings)
    except psycopg.errors.UndefinedTable:
        return AiView(mode=settings.mode)
    return AiView(reviews, enf.enforced, settings.mode, enf.reason)


def frozen_inputs(x: Ranked, *, at: datetime, source: Source, rule: str, ai: AiView | None = None) -> dict[str, Any]:
    c, r = x.leg.candidate, x.row
    return {
        "rule_version": rule, "source": source, "selected_at": at.isoformat(), "model": r.get("model"),
        "model_version_id": r.get("model_version_id"), "pick_status": r.get("pick_status"),
        "price": str(c.price), "bookmaker": r.get("bookmaker"), "price_at": c.price_at.isoformat() if c.price_at else None,
        "n_bookmakers": c.n_bookmakers, "p_model": str(c.p_model), "p_low": str(x.p_low),
        "p_push": str(c.p_push or 0), "p_market": str(c.p_market_fair), "ev": str(x.leg.ev),
        "probability_edge": str(x.leg.probability_edge), "elg_1pct": round(x.elg, 8),
        "kickoff_at": c.kickoff_at.isoformat(),
        "gate": {"max_price_age_h": GATE.max_price_age.total_seconds() / 3600, "min_bookmakers": GATE.min_bookmakers,
                 "max_price_edge": str(GATE.max_price_edge), "min_minutes_to_kickoff": GATE.min_minutes_to_kickoff,
                 "min_ev": str(GATE.min_ev)},
    } | ({} if ai is None else {"ai": ai.record(x)})


def load_candidates(conn: psycopg.Connection[Any], *, at: datetime, until: datetime,
                    include_shadow: bool) -> list[dict[str, Any]]:
    from fbi.api.repositories import product as repo

    return repo.pick_candidates(conn, now=at, until=until, since=at - CONSENSUS_LOOKBACK,
                                include_shadow=include_shadow)


@dataclass
class DailyReport:
    sets_created: int = 0
    items_added: int = 0
    by_source: dict[str, int] = field(default_factory=dict)


def _set_id(conn: psycopg.Connection[Any], day: date, source: Source, at: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO picks.daily_sets (day, timezone, source, rule_version, status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, 'BUILDING', %s, %s) ON CONFLICT (day, source) DO NOTHING RETURNING id",
                    (day, str(DAY_TZ), source, RULE_VERSION, at, at))
        row = cur.fetchone()
        if row is not None:
            return int(row[0])
        cur.execute("SELECT id FROM picks.daily_sets WHERE day = %s AND source = %s", (day, source))
        found = cur.fetchone()
        assert found is not None
        return int(found[0])


def build_daily_sets(conn: psycopg.Connection[Any], *, at: datetime) -> DailyReport:
    """Add to today's (and tomorrow's) sets whatever now earns a place. Idempotent; never removes."""
    report = DailyReport()
    for source in SOURCES:
        rows = load_candidates(conn, at=at, until=at + HORIZON, include_shadow=source == "evaluation")
        ranked = [x for x in passing(rows, at=at, source=source)
                  if x.elg > 0 and stage_of((x.leg.candidate.kickoff_at - at).total_seconds() / 60) is not None]
        ai = ai_view(conn, ranked, at=at)
        ranked = ai.apply(ranked)
        by_day: dict[date, list[Ranked]] = {}
        for x in ranked:
            by_day.setdefault(product_day(x.leg.candidate.kickoff_at), []).append(x)
        for day, options in sorted(by_day.items()):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT s.id, count(i.rank) AS n, array_remove(array_agg(i.fixture_id), NULL) AS fixtures "
                            "FROM picks.daily_sets s LEFT JOIN picks.daily_set_items i ON i.set_id = s.id "
                            "WHERE s.day = %s AND s.source = %s GROUP BY s.id", (day, source))
                existing = cur.fetchone()
            taken = int(existing["n"]) if existing else 0
            fixtures = set(existing["fixtures"] or []) if existing else set()
            if taken >= MAX_ITEMS:
                continue
            chosen: list[Ranked] = []
            for x in options:
                if taken + len(chosen) >= MAX_ITEMS:
                    break
                if x.leg.candidate.fixture_id in fixtures:
                    continue
                chosen.append(x)
                fixtures.add(x.leg.candidate.fixture_id)
            if not chosen:
                continue
            if existing is None:
                report.sets_created += 1
            set_id = int(existing["id"]) if existing else _set_id(conn, day, source, at)
            with conn.cursor() as cur:
                for n, x in enumerate(chosen, start=taken + 1):
                    c, r = x.leg.candidate, x.row
                    assert c.price is not None and c.price_at is not None and c.p_market_fair is not None
                    stage = stage_of((c.kickoff_at - at).total_seconds() / 60)
                    cur.execute(
                        "INSERT INTO picks.daily_set_items (set_id, rank, pick_id, fixture_id, market_key, selection, "
                        "line, stage, selected_at, odds, bookmaker_id, price_at, p_model, p_low, p_push, p_market, ev, "
                        "model_version_id, inputs) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (set_id, n, c.pick_id, c.fixture_id, c.market_key, c.selection, c.line, stage, at, c.price,
                         r.get("bookmaker_id"), c.price_at, c.p_model, x.p_low, c.p_push or 0, c.p_market_fair,
                         x.leg.ev, int(r["model_version_id"]),
                         Jsonb(frozen_inputs(x, at=at, source=source, rule=RULE_VERSION, ai=ai))))
                    report.items_added += max(cur.rowcount, 0)
                    report.by_source[source] = report.by_source.get(source, 0) + max(cur.rowcount, 0)
                cur.execute("UPDATE picks.daily_sets SET updated_at = %s WHERE id = %s", (at, set_id))
    with conn.cursor() as cur:
        # A day whose last minute has passed is complete; settlement marks it settled.
        cur.execute("UPDATE picks.daily_sets SET status = 'COMPLETE', updated_at = %s "
                    "WHERE status = 'BUILDING' AND day < %s", (at, product_day(at)))
    return report
