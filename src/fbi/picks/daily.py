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

``daily-set-v4`` (11 Oct 2026, REVIEW PREDIGOL B1) adds two stages before the choice, so a pick of the day passes
data -> market -> model -> calibration -> value -> RISK -> CONTEXT -> selection (``fbi.picks.funnel`` reports it):

* RISK (``risk-v1``): no price above 3.00. Evidence, out of sample (``docs/owner/P5_SELECCION_RIESGO_CONTEXTO.md``,
  ``scripts/audit_odds_risk.py``): over 16,114 settled selections the prices from 3.00 to 5.00 lost 13.1 % (95 %
  interval -22.4 % to -2.8 %, closing-line value -8.9 %) and those above 5.00 lost 23.8 %, where the model was
  12 points too confident; a rolling walk-forward (each day's cap chosen on the days before only) picked a cap
  between 2.20 and 3.00 every day and moved the return from -5.7 % to +3.0 % and the closing-line value from -5.3 %
  to -1.7 %. The set as v3 chose it averaged odds of 3.7 with no AI review at all. It avoids a measured loss; it
  does not claim a measured profit.
* CONTEXT (``context-v1``): the selection must have passed through PrediGol Intelligence - a combined review of it
  in the 12 hours before - so every pick of the day carries what the AI read (its decision, reason, risks and the
  outside evidence by status, confirmed / probable / rumour / contradictory / outdated, frozen with the item). The
  review still CHANGES the choice only when it is enforced (above). With the AI switched off (``FBI_AI_MODE=off``)
  there is nothing to require and the item says so (``context: ai_off``).

``daily-set-v5`` (11 Oct 2026, REVIEW PREDIGOL B1/B4) makes the CONTEXT stage the AI's DAY (``context-v2``). Measured
on the real sets of 4-12 Oct: the rule took each day's first matches the moment their 24-hour window opened (40 of
45 items chosen 12-24 h ahead; 7 of the 20 since 9 Oct kicked off at 00:00 Bogotá, which PrediGol Intelligence's
day never reaches) - 37 of 45 matches never had the AI's pass of the day and 41 were never searched for news. A
review by the rules alone satisfied v4. Now:

* the match's FIRST PASS of its day (``fbi.ai.day``, from 00:05 Bogotá: its packet, the web search for the matches
  most likely to be picks - ``fbi.ai.cycle`` searches the daily set's own order first -, the brief, the
  candidates' model review) must be done (``no_day_pass``), and
* the day's set is chosen once PrediGol Intelligence has read the whole day: no first pass still due, or 06:00
  Bogotá at the latest (``day_not_ready``) - so the five are the best of the day, not the first five read; a match
  that kicks off before then cannot be a pick of the day;
* and, as before, a combined review of the selection in the 12 hours before (``not_reviewed``).

The item freezes whether its match had the day's pass and a web search. No claim about returns is made: it is a
process rule - every pick of the day was read by PrediGol Intelligence on its day, with the news it found.
The parlays keep ``context-v1`` (a recent review) - a parlay or a user's builder spans days the AI has not opened.
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

RULE_VERSION = "daily-set-v5"
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


@dataclass(frozen=True, slots=True)
class RiskRule:
    """The risk stage (REVIEW B1): what a selection worth taking must also respect before it can be a pick."""

    version: str
    max_odds: Decimal | None = None

    def stop(self, x: Ranked) -> str | None:
        price = x.leg.candidate.price
        if self.max_odds is not None and price is not None and price > self.max_odds:
            return "odds_above_cap"
        return None


RISK = RiskRule("risk-v1", max_odds=Decimal("3.00"))
"""See the module's note on daily-set-v4 for the evidence; the parlays use the same rule (``fbi.parlays.persist``)."""


@dataclass(frozen=True, slots=True)
class ContextRule:
    """The context stage (REVIEW B1/B4): PrediGol Intelligence must have looked at the selection - and, for the picks
    of the day, on the match's day: its first pass done, the whole day read (``AiView.days_ready``)."""

    version: str
    require_review: bool = True
    require_day_pass: bool = False

    def stop(self, x: Ranked, ai: AiView) -> str | None:
        if ai.mode == "off":
            return None
        c = x.leg.candidate
        if self.require_day_pass:
            if product_day(c.kickoff_at) not in ai.days_ready:
                return "day_not_ready"
            if c.fixture_id not in ai.day_passed:
                return "no_day_pass"
        if self.require_review and not ai.reviewed(x):
            return "not_reviewed"
        return None


CONTEXT = ContextRule("context-v2", require_day_pass=True)
"""The picks of the day (daily-set-v5)."""
LEG_CONTEXT = ContextRule("context-v1")
"""A parlay's legs (parlay-v5, builder-v2): a review in the 12 hours before - they span days the AI has not opened."""
READY_BY = time(6, 0)
"""The day's set is chosen once the AI's first pass of the day is over, or from this time (Bogotá) at the latest."""


@dataclass(frozen=True)
class AiView:
    """The newest combined AI review of each candidate, and whether reviews may change the choice."""

    reviews: dict[tuple[int, str, str, Decimal], dict[str, Any]] = field(default_factory=dict)
    enforced: bool = False
    mode: str = "off"
    reason: str = "ai_unavailable"
    evidence: dict[int, dict[str, int]] = field(default_factory=dict)
    """Per match: the outside evidence gathered before now, counted by the status the server gave it."""
    day_passed: frozenset[int] = frozenset()
    """Matches whose first pass of their day (``ai.fixture_passes``) was over before now."""
    searched: frozenset[int] = frozenset()
    """Matches PrediGol Intelligence searched on the web in one of their day's passes before now."""
    days_ready: frozenset[date] = frozenset()
    """Bogotá days the AI has read whole: opened, no first pass still due (or ``READY_BY`` passed)."""

    def decision(self, x: Ranked) -> str | None:
        r = self.reviews.get(x.leg.candidate.selection_key)
        return None if r is None else str(r["decision"])

    def reviewed(self, x: Ranked) -> bool:
        return x.leg.candidate.selection_key in self.reviews

    def record(self, x: Ranked) -> dict[str, Any]:
        r = self.reviews.get(x.leg.candidate.selection_key)
        fid = x.leg.candidate.fixture_id
        base: dict[str, Any] = {"mode": self.mode, "enforced": self.enforced, "why": self.reason,
                                "evidence": dict(self.evidence.get(fid, {})), "day_pass": fid in self.day_passed,
                                "web_searched": fid in self.searched}
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


def ai_view(conn: psycopg.Connection[Any], ranked: list[Ranked], *, at: datetime, day: bool = True) -> AiView:
    """Read in a savepoint: without the AI tables (an older database) the set is built as before. ``day``: whether to
    ask if today has been read whole (``day_ready``) - only the daily set's context stage needs it."""
    from fbi.ai.config import AiSettings
    from fbi.ai.gating import enforcement
    from fbi.ai.review import latest_reviews

    settings = AiSettings.from_env()
    fixtures = sorted({x.leg.candidate.fixture_id for x in ranked})
    try:
        with conn.transaction():
            reviews = latest_reviews(conn, fixtures, at=at)
            enf = enforcement(conn, settings)
            evidence = evidence_counts(conn, fixtures, at=at)
            passed, searched = day_passes(conn, fixtures, at=at)
            ready = frozenset({product_day(at)}) if day and day_ready(conn, at=at) else frozenset()
    except psycopg.errors.UndefinedTable:
        return AiView(mode=settings.mode)
    return AiView(reviews, enf.enforced, settings.mode, enf.reason, evidence, passed, searched, ready)


PASSES_SQL = """
SELECT p.fixture_id, bool_or(p.pass = 'first') AS first_done,
       bool_or(COALESCE((p.counts->>'web_searches')::int, 0) > 0) AS searched
  FROM ai.fixture_passes p
 WHERE p.fixture_id = ANY(%(fixtures)s) AND p.finished_at <= %(at)s AND p.status IN ('ok', 'partial')
 GROUP BY 1
"""


def day_passes(conn: psycopg.Connection[Any], fixtures: list[int], *, at: datetime
               ) -> tuple[frozenset[int], frozenset[int]]:
    """(matches whose first pass of the day is over, matches searched on the web in a pass), as of ``at``."""
    if not fixtures:
        return frozenset(), frozenset()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PASSES_SQL, {"fixtures": fixtures, "at": at})
        rows = cur.fetchall()
    return (frozenset(int(r["fixture_id"]) for r in rows if r["first_done"]),
            frozenset(int(r["fixture_id"]) for r in rows if r["searched"]))


def ready(local: time, *, opened: bool, first_due: int) -> bool:
    """Whether the day's set may be chosen (pure): the AI's day is open and its first pass over, or READY_BY."""
    return opened and (first_due == 0 or local >= READY_BY)


def day_ready(conn: psycopg.Connection[Any], *, at: datetime) -> bool:
    from fbi.ai.day import due_passes, opened

    local = at.astimezone(DAY_TZ).time()
    if not opened(at) or local >= READY_BY:
        return ready(local, opened=opened(at), first_due=0)
    return ready(local, opened=True, first_due=sum(1 for d in due_passes(conn, at=at) if d.pass_kind == "first"))


EVIDENCE_SQL = """
SELECT e.fixture_id, e.status, count(*) AS n FROM ai.evidence e
 WHERE e.fixture_id = ANY(%(fixtures)s) AND e.retrieved_at <= %(at)s GROUP BY 1, 2
"""


def evidence_counts(conn: psycopg.Connection[Any], fixtures: list[int], *, at: datetime) -> dict[int, dict[str, int]]:
    """The outside evidence about each match known at ``at``, by status (CONFIRMED, PROBABLE, RUMOR, CONTRADICTORY,
    OUTDATED - the server decides it, never a model: ``fbi.ai.evidence``). No row: no evidence at all."""
    if not fixtures:
        return {}
    out: dict[int, dict[str, int]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EVIDENCE_SQL, {"fixtures": fixtures, "at": at})
        for r in cur.fetchall():
            out.setdefault(int(r["fixture_id"]), {})[str(r["status"])] = int(r["n"])
    return out


def staged(rows: list[dict[str, Any]], *, at: datetime, source: Source) -> list[Ranked]:
    """The day's candidates through every stage up to value (``passing``), in the 24-hour window, with positive
    pessimistic growth, and through the RISK stage. The CONTEXT stage needs the AI's view (``ai_view``)."""
    return [x for x in passing(rows, at=at, source=source)
            if x.elg > 0 and stage_of((x.leg.candidate.kickoff_at - at).total_seconds() / 60) is not None
            and RISK.stop(x) is None]


def frozen_inputs(x: Ranked, *, at: datetime, source: Source, rule: str, ai: AiView | None = None,
                  context: ContextRule = CONTEXT) -> dict[str, Any]:
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
        "risk": {"version": RISK.version, "max_odds": None if RISK.max_odds is None else str(RISK.max_odds)},
        "context": ("ai_off" if ai is not None and ai.mode == "off" else context.version),
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
        ranked = staged(rows, at=at, source=source)
        ai = ai_view(conn, ranked, at=at)
        ranked = ai.apply([x for x in ranked if CONTEXT.stop(x, ai) is None])
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
