"""DAILY_PARLAY and MULTIDAY_PARLAY as records: built once, frozen, then followed to the end.

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

from fbi.picks.daily import (
    DAY_TZ,
    SOURCES,
    STAKE_FRACTION,
    Ranked,
    Source,
    day_bounds,
    frozen_inputs,
    load_candidates,
    passing,
    product_day,
    win_probability,
)

RULE_VERSION = "parlay-v3"
Kind = Literal["daily", "multiday"]


@dataclass(frozen=True, slots=True)
class Spec:
    kind: Kind
    min_legs: int
    max_legs: int
    min_days: int


SPECS: dict[Kind, Spec] = {"daily": Spec("daily", 2, 5, 1), "multiday": Spec("multiday", 3, 7, 2)}
MULTIDAY_WINDOW = timedelta(hours=72)


def parlay_elg(legs: list[Ranked], f: float = STAKE_FRACTION) -> float:
    """Expected log growth of staking ``f`` on the parlay, at the legs' pessimistic probabilities
    (a push counted as a loss: conservative)."""
    if not legs:
        return 0.0
    odds = math.prod(float(x.leg.candidate.price or 0) for x in legs)
    p = math.prod(win_probability(x.p_low, x.leg.candidate.p_push) for x in legs)
    if p <= 0 or odds <= 1:
        return -math.inf
    return p * math.log(1 + f * (odds - 1)) + (1 - p) * math.log(1 - f)


def quarter_line(line: Decimal) -> bool:
    return abs(line * 4) % 2 == 1


def choose(pool: list[Ranked], spec: Spec) -> list[Ranked] | None:
    """The legs, or None when no parlay of at least ``min_legs`` grows.

    The day rule is honoured while choosing, not checked afterwards: once the slots left before
    ``min_legs`` are only enough to reach ``min_days``, the next leg must come from a day the
    parlay does not have yet (a multi-day parlay of three legs takes its third from another day
    when its first two share one)."""
    legs: list[Ranked] = []
    fixtures: set[int] = set()
    teams: set[int] = set()

    def allowed(x: Ranked) -> bool:
        c = x.leg.candidate
        return (c.fixture_id not in fixtures and c.home_team_id not in teams and c.away_team_id not in teams
                and not quarter_line(c.line))

    while len(legs) < spec.max_legs:
        options = [x for x in pool if allowed(x)]
        have = {product_day(x.leg.candidate.kickoff_at) for x in legs}
        need_days = spec.min_days - len(have)
        if need_days > 0 and spec.min_legs - len(legs) <= need_days:
            options = [x for x in options if product_day(x.leg.candidate.kickoff_at) not in have]
        if not options:
            break
        best = max(options, key=lambda x: parlay_elg([*legs, x]))
        grown = parlay_elg([*legs, best])
        if len(legs) >= spec.min_legs and grown <= parlay_elg(legs):
            break
        legs.append(best)
        c = best.leg.candidate
        fixtures.add(c.fixture_id)
        teams.update((c.home_team_id, c.away_team_id))
    days = {product_day(x.leg.candidate.kickoff_at) for x in legs}
    if len(legs) < spec.min_legs or len(days) < spec.min_days or parlay_elg(legs) <= 0:
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
    for source in SOURCES:
        rows = load_candidates(conn, at=at, until=at + MULTIDAY_WINDOW, include_shadow=source == "evaluation")
        ranked = passing(rows, at=at, source=source)
        for spec in SPECS.values():
            existing = _row(conn, spec, today, source)
            if existing is not None and existing[1] != "BUILDING":
                continue
            frm, to = _window(spec, today, at)
            pool = [x for x in ranked if frm <= x.leg.candidate.kickoff_at < to]
            legs = choose(pool, spec)
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
                p_all = math.prod(Decimal(str(win_probability(x.p_low, x.leg.candidate.p_push))) for x in legs)
                for n, x in enumerate(sorted(legs, key=lambda y: y.leg.candidate.kickoff_at), start=1):
                    c, r = x.leg.candidate, x.row
                    cur.execute(
                        "INSERT INTO picks.parlay_legs (parlay_id, leg_no, pick_id, fixture_id, market_key, selection, "
                        "line, added_at, odds, bookmaker_id, price_at, p_model, p_low, p_push, p_market, ev, inputs) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (parlay_id, n, c.pick_id, c.fixture_id, c.market_key, c.selection, c.line, at, c.price,
                         r.get("bookmaker_id"), c.price_at, c.p_model, x.p_low, c.p_push or 0, c.p_market_fair,
                         x.leg.ev, Jsonb(frozen_inputs(x, at=at, source=source, rule=RULE_VERSION))))
                # The window recorded is the one the legs were actually chosen from (a multi-day
                # parlay looks 72 hours ahead of the moment it is built, not of the moment it was
                # first looked for).
                cur.execute(
                    "UPDATE picks.parlays SET status = 'READY', ready_at = %s, combined_odds = %s, p_all_low = %s, "
                    "expected_log_growth = %s, window_from = %s, window_to = %s, rule_version = %s "
                    "WHERE id = %s AND status = 'BUILDING'",
                    (at, round(odds, 3), round(p_all, 8), round(Decimal(str(parlay_elg(legs))), 8), frm, to,
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


__all__ = ["DAY_TZ", "RULE_VERSION", "SPECS", "build_parlays", "choose", "parlay_elg"]
