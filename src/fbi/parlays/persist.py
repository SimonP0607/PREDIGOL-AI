"""DAILY_PARLAY and MULTIDAY_PARLAY as records: built once, frozen, then followed to the end.

Rule ``parlay-v4`` (8 Oct 2026; v3's records are kept as built). On top of v3 below: at most two legs from
one competition (exposure), every leg priced by at least three bookmakers (liquidity), no leg whose model
interval is wider than 40 points (uncertainty), the joint probability corrected for MEASURED dependence
between legs of one competition's matchday - only where it is significantly negative, so a correction can
make a parlay look worse, never better (``fbi.parlays.correlation``) - and the AI review: recorded with
every leg, and in enforce mode a rejected or downgraded selection is not a leg (``fbi.ai.gating``).

Rule ``parlay-v3`` (v2, 2026-10-04 only, ranked legs without a measured interval as if certain
and checked the day rule only after choosing; its records are kept as built). Legs come from the same gate the daily set uses (a current price from two
or more books, not an outlier, positive expected value at that price), one per match and no
team twice (``fbi.parlays.engine.guard``: distinct matches between distinct teams, so the legs
are treated as independent). Quarter lines (.25 / .75) are left out: a half-won leg has no
clean meaning inside a parlay.

The legs are chosen by EXPECTED LOG GROWTH of a 1% stake on the whole parlay, computed with
each leg's PESSIMISTIC probability (the low end of the model's interval): greedily, the leg
that raises the parlay's growth most, first up to the minimum number of legs - the parlay is
built only if that already grows (> 0) - then beyond it while each added leg still raises the
growth, up to the maximum. A long parlay of long shots does not survive this: every leg
multiplies the uncertainty in.

  daily      the product day's matches (America/Bogota), 2 to 5 legs
  multiday   the next 72 hours, 3 to 7 legs spanning at least two product days

Lifecycle: BUILDING (the day's parlay is being looked for: some candidates, not yet a
parlay that grows) -> READY (built; legs frozen, nothing kicked off) -> ACTIVE (a leg has
kicked off) -> WON / LOST / VOID / PARTIAL_VOID (settled; ``fbi.picks.product_settlement``).
A BUILDING parlay whose product day ends (or whose window passes) without one is VOID with no
legs: there was no parlay that day, and the record says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb

from fbi.parlays import correlation as corr
from fbi.picks.daily import (
    DAY_TZ,
    SOURCES,
    STAKE_FRACTION,
    Ranked,
    Source,
    ai_view,
    day_bounds,
    frozen_inputs,
    load_candidates,
    passing,
    product_day,
    win_probability,
)

RULE_VERSION = "parlay-v4"
MAX_PER_COMPETITION = 2
MIN_LEG_BOOKMAKERS = 3
MAX_INTERVAL_WIDTH = Decimal("0.40")
Kind = Literal["daily", "multiday"]


@dataclass(frozen=True, slots=True)
class Spec:
    kind: Kind
    min_legs: int
    max_legs: int
    min_days: int


SPECS: dict[Kind, Spec] = {"daily": Spec("daily", 2, 5, 1), "multiday": Spec("multiday", 3, 7, 2)}
MULTIDAY_WINDOW = timedelta(hours=72)


Correlations = dict[str, corr.Estimate]


def _polarity(market_key: str, selection: str) -> int:
    """+1 when the selection wins with its measured outcome, -1 when it wins with the complement (Under, No)."""
    return -1 if (market_key, selection) in (("OU", "Under"), ("BTTS", "No")) else 1


def correlated_pairs(legs: list[Ranked], correlations: Correlations | None) -> list[tuple[int, int, float]]:
    """The leg pairs that share a competition and a product day and a measured outcome, with a correlation
    significantly below zero (after the selections' polarity)."""
    if not correlations:
        return []
    out: list[tuple[int, int, float]] = []
    for i, a in enumerate(legs):
        for j in range(i + 1, len(legs)):
            b = legs[j]
            ca, cb = a.leg.candidate, b.leg.candidate
            if a.row.get("competition_id") is None or a.row.get("competition_id") != b.row.get("competition_id"):
                continue
            if product_day(ca.kickoff_at) != product_day(cb.kickoff_at):
                continue
            ma, mb = corr.market_of(ca.market_key, ca.selection), corr.market_of(cb.market_key, cb.selection)
            if ma is None or ma != mb or ma not in correlations:
                continue
            e = correlations[ma]
            sign = _polarity(ca.market_key, ca.selection) * _polarity(cb.market_key, cb.selection)
            rho, upper = sign * e.rho, (sign * e.rho + 1.96 * e.se)
            if e.n_groups >= corr.MIN_GROUPS and upper < 0:
                out.append((i, j, rho))
    return out


def joint_low(legs: list[Ranked], correlations: Correlations | None = None) -> float:
    """P(every leg wins) at the pessimistic probabilities, corrected for significant negative dependence."""
    probs = [win_probability(x.p_low, x.leg.candidate.p_push) for x in legs]
    return corr.joint_probability(probs, correlated_pairs(legs, correlations))


def parlay_elg(legs: list[Ranked], f: float = STAKE_FRACTION, correlations: Correlations | None = None) -> float:
    """Expected log growth of staking ``f`` on the parlay, at the legs' pessimistic probabilities
    (a push counted as a loss: conservative)."""
    if not legs:
        return 0.0
    odds = math.prod(float(x.leg.candidate.price or 0) for x in legs)
    p = joint_low(legs, correlations)
    if p <= 0 or odds <= 1:
        return -math.inf
    return p * math.log(1 + f * (odds - 1)) + (1 - p) * math.log(1 - f)


def eligible_leg(x: Ranked) -> bool:
    """Liquidity and uncertainty: at least three bookmakers, and a model interval no wider than 40 points."""
    c = x.leg.candidate
    if (c.n_bookmakers or 0) < MIN_LEG_BOOKMAKERS:
        return False
    hi = x.row.get("p_high")
    return hi is None or Decimal(hi) - x.p_low <= MAX_INTERVAL_WIDTH


def quarter_line(line: Decimal) -> bool:
    return abs(line * 4) % 2 == 1


def choose(pool: list[Ranked], spec: Spec, correlations: Correlations | None = None) -> list[Ranked] | None:
    """The legs, or None when no parlay of at least ``min_legs`` grows.

    The day rule is honoured while choosing, not checked afterwards: once the slots left before
    ``min_legs`` are only enough to reach ``min_days``, the next leg must come from a day the
    parlay does not have yet (a multi-day parlay of three legs takes its third from another day
    when its first two share one)."""
    legs: list[Ranked] = []
    fixtures: set[int] = set()
    teams: set[int] = set()
    per_competition: dict[Any, int] = {}

    def allowed(x: Ranked) -> bool:
        c = x.leg.candidate
        comp = x.row.get("competition_id")
        return (c.fixture_id not in fixtures and c.home_team_id not in teams and c.away_team_id not in teams
                and not quarter_line(c.line) and eligible_leg(x)
                and (comp is None or per_competition.get(comp, 0) < MAX_PER_COMPETITION))

    while len(legs) < spec.max_legs:
        options = [x for x in pool if allowed(x)]
        have = {product_day(x.leg.candidate.kickoff_at) for x in legs}
        need_days = spec.min_days - len(have)
        if need_days > 0 and spec.min_legs - len(legs) <= need_days:
            options = [x for x in options if product_day(x.leg.candidate.kickoff_at) not in have]
        if not options:
            break
        best = max(options, key=lambda x: parlay_elg([*legs, x], correlations=correlations))
        grown = parlay_elg([*legs, best], correlations=correlations)
        if len(legs) >= spec.min_legs and grown <= parlay_elg(legs, correlations=correlations):
            break
        legs.append(best)
        c = best.leg.candidate
        fixtures.add(c.fixture_id)
        teams.update((c.home_team_id, c.away_team_id))
        comp = best.row.get("competition_id")
        if comp is not None:
            per_competition[comp] = per_competition.get(comp, 0) + 1
    days = {product_day(x.leg.candidate.kickoff_at) for x in legs}
    if len(legs) < spec.min_legs or len(days) < spec.min_days or parlay_elg(legs, correlations=correlations) <= 0:
        return None
    return legs


@dataclass
class ParlayReport:
    built: int = 0
    building: int = 0
    voided_unbuilt: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


def _window(spec: Spec, day: date, at: datetime) -> tuple[datetime, datetime]:
    if spec.kind == "daily":
        return day_bounds(day)
    return at, at + MULTIDAY_WINDOW


def _row(conn: psycopg.Connection[Any], spec: Spec, day: date, source: Source) -> tuple[int, str] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id, status FROM picks.parlays WHERE kind = %s AND day = %s AND source = %s",
                    (spec.kind, day, source))
        r = cur.fetchone()
    return (int(r[0]), str(r[1])) if r else None


def build_parlays(conn: psycopg.Connection[Any], *, at: datetime) -> ParlayReport:
    """Build today's daily and multi-day parlays if they can be built now. Idempotent: a parlay
    that exists past BUILDING is never touched again here."""
    report = ParlayReport()
    today = product_day(at)
    correlations = corr.latest(conn)
    for source in SOURCES:
        rows = load_candidates(conn, at=at, until=at + MULTIDAY_WINDOW, include_shadow=source == "evaluation")
        ranked = passing(rows, at=at, source=source)
        ai = ai_view(conn, ranked, at=at)
        ranked = ai.apply(ranked, drop_downgraded=True)
        for spec in SPECS.values():
            existing = _row(conn, spec, today, source)
            if existing is not None and existing[1] != "BUILDING":
                continue
            frm, to = _window(spec, today, at)
            pool = [x for x in ranked if frm <= x.leg.candidate.kickoff_at < to]
            legs = choose(pool, spec, correlations)
            with conn.cursor() as cur:
                if existing is None:
                    if not pool:
                        continue  # nothing to look at yet: no record of a parlay that was never in sight
                    cur.execute(
                        "INSERT INTO picks.parlays (kind, day, source, rule_version, status, min_legs, max_legs, "
                        "window_from, window_to, created_at) VALUES (%s, %s, %s, %s, 'BUILDING', %s, %s, %s, %s, %s) "
                        "ON CONFLICT (kind, day, source) DO NOTHING RETURNING id",
                        (spec.kind, today, source, RULE_VERSION, spec.min_legs, spec.max_legs, frm, to, at))
                    created = cur.fetchone()
                    if created is None:
                        continue
                    parlay_id = int(created[0])
                else:
                    parlay_id = existing[0]
                if legs is None:
                    report.building += 1
                    continue
                odds = math.prod(Decimal(x.leg.candidate.price or 0) for x in legs)
                p_all = Decimal(str(joint_low(legs, correlations)))
                for n, x in enumerate(sorted(legs, key=lambda y: y.leg.candidate.kickoff_at), start=1):
                    c, r = x.leg.candidate, x.row
                    cur.execute(
                        "INSERT INTO picks.parlay_legs (parlay_id, leg_no, pick_id, fixture_id, market_key, selection, "
                        "line, added_at, odds, bookmaker_id, price_at, p_model, p_low, p_push, p_market, ev, inputs) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (parlay_id, n, c.pick_id, c.fixture_id, c.market_key, c.selection, c.line, at, c.price,
                         r.get("bookmaker_id"), c.price_at, c.p_model, x.p_low, c.p_push or 0, c.p_market_fair,
                         x.leg.ev, Jsonb(frozen_inputs(x, at=at, source=source, rule=RULE_VERSION, ai=ai))))
                # The window recorded is the one the legs were actually chosen from (a multi-day
                # parlay looks 72 hours ahead of the moment it is built, not of the moment it was
                # first looked for).
                cur.execute(
                    "UPDATE picks.parlays SET status = 'READY', ready_at = %s, combined_odds = %s, p_all_low = %s, "
                    "expected_log_growth = %s, window_from = %s, window_to = %s, rule_version = %s "
                    "WHERE id = %s AND status = 'BUILDING'",
                    (at, round(odds, 3), round(p_all, 8),
                     round(Decimal(str(parlay_elg(legs, correlations=correlations))), 8), frm, to,
                     RULE_VERSION, parlay_id))
                report.built += 1
                report.by_kind[spec.kind] = report.by_kind.get(spec.kind, 0) + 1
    with conn.cursor() as cur:
        # Looked for and never built: once its product day is over (or its window has passed)
        # the record says there was no parlay that day.
        cur.execute("UPDATE picks.parlays p SET status = 'VOID', settled_at = %s, profit_units = 0 "
                    "WHERE p.status = 'BUILDING' AND (p.window_to <= %s OR p.day < %s) "
                    "AND NOT EXISTS (SELECT 1 FROM picks.parlay_legs l WHERE l.parlay_id = p.id)", (at, at, today))
        report.voided_unbuilt = max(cur.rowcount, 0)
    return report


__all__ = ["DAY_TZ", "RULE_VERSION", "SPECS", "build_parlays", "choose", "joint_low", "parlay_elg"]
