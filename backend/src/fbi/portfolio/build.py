"""The shadow portfolio of a day (``portfolio-v1``): read the day's decisions, then ``assemble`` - pure - does the rest.

WHAT IT READS. Exactly the rows ``fbi.intel.decision.select_day`` reads (``decision.LATEST_DAY_SQL``: the newest
decision-v1 row of each selection of the day's matches (Bogotá) known by ``at``, more than 10 minutes before its
kick-off), with the fixture's status and the model version's status for the parlays' value gate. Each row is mapped
through state-v2 (``fbi.intel.state_v2``). Read-only.

WHAT IT BUILDS.

    eligible     the RECOMMENDED selections, in the day's order (``day_priority.order_for_day``: comp-priority-v1's group,
                 then the best PrediGol Pick Score). With ``what_if`` the CAUTION ones follow them, HYPOTHETICAL.
    correlations every pair of eligible selections that shares something, with its source (``correlation``)
    stakes       stake-v1, scaled down for a shared budget, held by the exposure limits (``stakes``, ``exposure``)
    day set      select_day's rules over the eligible selections decided at most ``decision.DAY_FRESH`` ago:
                 comp-priority-v1's order, one per match, at most ``decision.MAX_PER_COMPETITION`` per competition,
                 at most ``decision.MAX_PICKS``; the pick of the day is its first. Recomputed from scratch: the
                 picks production already froze today are not read here.
    parlays      ONLY RECOMMENDED legs (also in the what-if), the ones select_day would combine (``parlay_eligible``
                 or CANDIDATO_PARLAY, decided at most DAY_FRESH ago), through the parlays' value gate
                 (``fbi.parlays.engine.assess``) and their chooser and correlation guard (``fbi.parlays.persist.choose``:
                 one leg per match, no team twice, at most two per competition, the joint probability at the
                 pessimistic end corrected for measured dependence, growth). On top, only narrowing: two legs of one
                 competition's matchday are combined only when their dependence is MEASURED (``measured_pair``). At
                 most ``decision.MAX_PARLAYS``, disjoint, each staked by stake-v1 at its parlay cap on the joint
                 probability and held to the day's room.

When the day has no RECOMMENDED selection the report says so in words and builds nothing: no stake, no day set, no
parlay is invented.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_bounds, local_day
from fbi.core.decision_versions import DECISION_CORE
from fbi.intel import day_priority, decision, state_v2
from fbi.intel import stake as staking
from fbi.parlays import builder as parlay_builder
from fbi.parlays import correlation as icc
from fbi.parlays import persist
from fbi.parlays.engine import Candidate, GateConfig, Leg, Reject, assess
from fbi.picks.daily import Ranked, single_elg
from fbi.portfolio import VERSION, correlation, exposure, stakes
from fbi.portfolio.selection import Selection

MODE_RECOMMENDED: Final = "recommended"
MODE_WHAT_IF: Final = "what_if_caution"

ROWS_SQL: Final = f"""
SELECT x.*, f.status_group AS fixture_status, v.status AS model_status
  FROM ({decision.LATEST_DAY_SQL}) x
  JOIN core.fixtures f ON f.id = x.fixture_id
  LEFT JOIN models.model_versions v ON v.id = x.model_version_id
 ORDER BY x.kickoff_at, x.fixture_id, x.id
"""

PARLAY_GATE: Final = GateConfig(allow_unqualified=True)
"""The parlays' value gate as it stands, with one switch: ``qualified`` there means a pick of the published rule, which a
decision-v1 selection is not; a RECOMMENDED selection has passed decision-v1's own out-of-sample edge gate (filter 10)
instead. Every other check (scheduled, > 10 min to kick-off, a price <= 3 h old from >= 2 books, not an outlier, EV > 0
at the current price) runs unchanged, on the CALIBRATED probability."""
PARLAY_SPEC: Final = persist.SPECS["daily"]


def read_rows(conn: psycopg.Connection[Any], *, day: date, at: datetime) -> list[dict[str, Any]]:
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROWS_SQL, {"start": start, "end": end, "at": at, "version": DECISION_CORE})
        return [dict(r) for r in cur.fetchall()]


def ordered(selections: Sequence[Selection]) -> list[Selection]:
    return day_priority.order_for_day(selections, league=lambda s: s.provider_league_id,
                                      score=lambda s: s.score or 0.0)


def fresh(s: Selection, at: datetime) -> bool:
    return at - s.known_at <= decision.DAY_FRESH


def day_set(eligible: Sequence[Selection], *, at: datetime) -> list[Selection]:
    """select_day's rules: fresh, comp-priority-v1's order, one per match, two per competition, five at most."""
    out: list[Selection] = []
    fixtures: set[int] = set()
    per_comp: Counter[int] = Counter()
    for s in ordered([s for s in eligible if fresh(s, at)]):
        if len(out) >= decision.MAX_PICKS:
            break
        if s.fixture_id in fixtures or per_comp[s.competition_id] >= decision.MAX_PER_COMPETITION:
            continue
        out.append(s)
        fixtures.add(s.fixture_id)
        per_comp[s.competition_id] += 1
    return out


# -- parlays ---------------------------------------------------------------------------------------------------------

def ranked_of(s: Selection, *, at: datetime) -> Ranked | str:
    """The selection as a parlay leg (the parlays' own ``Ranked``), or why it cannot be one."""
    if s.p_cal is None or s.odds is None:
        return "no_calibrated_probability_or_price"
    if s.p_low is None:
        return "no_interval"
    p_model = Decimal(str(s.p_cal))
    cand = Candidate(pick_id=s.pick_id or 0, fixture_id=s.fixture_id, kickoff_at=s.kickoff_at,
                     fixture_status=s.fixture_status, home_team_id=s.home_team_id, away_team_id=s.away_team_id,
                     market_key=s.market_key, selection=s.selection, line=s.line, qualified=False,
                     model_status=s.model_status or "unknown", p_model=p_model,
                     p_push=Decimal(str(s.p_push)) if s.p_push else None,
                     p_market_fair=None if s.p_market is None else Decimal(str(s.p_market)),
                     price=Decimal(str(s.odds)), price_at=s.price_at, n_bookmakers=s.n_bookmakers)
    verdict = assess(cand, at, PARLAY_GATE)
    if isinstance(verdict, Reject):
        return verdict.value
    assert isinstance(verdict, Leg) and cand.price is not None
    p_low = min(Decimal(str(s.p_low)), p_model)
    row = {"competition_id": s.competition_id, "p_high": None if s.p_high is None else Decimal(str(s.p_high)),
           "decision_id": s.decision_id}
    return Ranked(verdict, row, p_low, single_elg(cand.price, p_low, cand.p_push))


def measured_pair(a: Selection, b: Selection, measured: Mapping[str, icc.Estimate] | None) -> bool:
    """Two legs may share a parlay when they share no competition's matchday, or when the dependence of that matchday is
    measured for their market (an estimate of at least ``icc.MIN_GROUPS`` matchdays, significant or not)."""
    if a.competition_id != b.competition_id or local_day(a.kickoff_at) != local_day(b.kickoff_at):
        return True
    ma, mb = icc.market_of(a.market_key, a.selection), icc.market_of(b.market_key, b.selection)
    e = None if not measured or ma is None or ma != mb else measured.get(ma)
    return e is not None and e.n_groups >= icc.MIN_GROUPS


def parlays(recommended: Sequence[Selection], *, at: datetime, measured: Mapping[str, icc.Estimate] | None,
            book: exposure.Book) -> dict[str, Any]:
    by_id = {s.decision_id: s for s in recommended}
    estimates: persist.Correlations | None = dict(measured) if measured else None
    candidates = [s for s in recommended if s.state_v2 == "RECOMMENDED" and fresh(s, at)
                  and (s.parlay_eligible or s.state_v1 == "CANDIDATO_PARLAY")]
    rejections: Counter[str] = Counter()
    pool: list[Ranked] = []
    for s in candidates:
        r = ranked_of(s, at=at)
        if isinstance(r, str):
            rejections[r] += 1
        else:
            pool.append(r)

    def sel(x: Ranked) -> Selection:
        return by_id[int(x.row["decision_id"])]

    def allow(chosen: list[Ranked], x: Ranked) -> bool:
        return all(measured_pair(sel(y), sel(x), measured) for y in chosen)

    built: list[dict[str, Any]] = []
    left = list(pool)
    while len(built) < decision.MAX_PARLAYS:
        legs = persist.choose(left, PARLAY_SPEC, estimates, allow=allow)
        if legs is None:
            break
        legs = sorted(legs, key=lambda x: (x.leg.candidate.kickoff_at, x.leg.candidate.fixture_id))
        odds = parlay_builder.total_odds(legs)
        p_all = persist.joint_low(legs, estimates)
        st = staking.stake_for("CANDIDATO_PARLAY", p_all, float(odds), cap=staking.PARLAY_CAP)
        check = book.check_day(st.units)
        book.add_day(check.allowed)
        n_pairs = len(persist.correlated_pairs(legs, estimates))
        built.append({
            "legs": [{"decision_id": sel(x).decision_id, "fixture_id": x.leg.candidate.fixture_id,
                      "competition_id": sel(x).competition_id, "market_key": x.leg.candidate.market_key,
                      "selection": x.leg.candidate.selection, "line": str(x.leg.candidate.line),
                      "odds": float(x.leg.candidate.price or 0), "p_cal": sel(x).p_cal, "p_low": float(x.p_low),
                      "ev": float(x.leg.ev)} for x in legs],
            "combined_odds": float(round(odds, 3)), "p_all_low": round(p_all, 6),
            "expected_log_growth": round(persist.parlay_elg(legs, correlations=estimates), 8),
            "correlation": {"method": persist.RULE_VERSION + " joint at the pessimistic end, " + icc.VERSION
                            + (" estimates" if measured else " (no estimate stored: legs of one competition's matchday "
                                                             "are not combined)"),
                            "corrected_pairs": n_pairs},
            "stake": st.as_json() | {"final_units": check.allowed, "binding_limit": check.binding}})
        used = {id(x) for x in legs}
        left = [x for x in left if id(x) not in used]
    reason = None
    if not built:
        reason = ("no RECOMMENDED parlay candidate" if not candidates else
                  "no leg through the value gate" if not pool else
                  f"no combination of at least {PARLAY_SPEC.min_legs} legs grows under the guard")
    return {"rule": persist.RULE_VERSION, "spec": {"min_legs": PARLAY_SPEC.min_legs, "max_legs": PARLAY_SPEC.max_legs},
            "candidates": len(candidates), "through_gate": len(pool), "rejections": dict(sorted(rejections.items())),
            "built": built, "reason": reason}


# -- the day ---------------------------------------------------------------------------------------------------------

def assemble(selections: Sequence[Selection], *, day: date, at: datetime, what_if: bool = False,
             joint: correlation.JointProvider | None = None,
             measured: Mapping[str, icc.Estimate] | None = None) -> dict[str, Any]:
    """The shadow portfolio of the selections. Pure."""
    by_state = Counter(s.state_v2 for s in selections)
    recommended = ordered([s for s in selections if s.state_v2 == "RECOMMENDED"])
    hypothetical = ordered([s for s in selections if what_if and s.state_v2 in stakes.HYPOTHETICAL_STATES])
    eligible = [*recommended, *hypothetical]
    corrs = correlation.pairs(eligible, joint=joint, measured=measured)
    allocated, book = stakes.allocate(eligible, corrs, hypothetical=what_if)
    stake_of = {p.decision_id: p for p in allocated}
    chosen = day_set(eligible, at=at)
    rank = {s.decision_id: n for n, s in enumerate(chosen, start=1)}
    combos: dict[str, Any] = parlays(recommended, at=at, measured=measured, book=book) if recommended else {
        "rule": persist.RULE_VERSION, "candidates": 0, "through_gate": 0, "rejections": {}, "built": [],
        "reason": "no RECOMMENDED selection"}
    related: dict[int, list[dict[str, Any]]] = {s.decision_id: [] for s in eligible}
    for c in corrs:
        related[c.a].append({"with": c.b, "rho": round(c.rho, 6), "source": c.source})
        related[c.b].append({"with": c.a, "rho": round(c.rho, 6), "source": c.source})

    def entry(s: Selection) -> dict[str, Any]:
        return s.brief() | {"hypothetical": s.state_v2 != "RECOMMENDED",
                            "priority_group": day_priority.group_of(s.provider_league_id),
                            "fresh_for_day": fresh(s, at), "day_rank": rank.get(s.decision_id),
                            "stake": stake_of[s.decision_id].as_json(), "correlated_with": related[s.decision_id]}

    def day_entry(s: Selection) -> dict[str, Any]:
        return {"rank": rank[s.decision_id], "decision_id": s.decision_id, "fixture_id": s.fixture_id,
                "competition_id": s.competition_id, "priority_group": day_priority.group_of(s.provider_league_id),
                "score": s.score, "market_key": s.market_key, "selection": s.selection, "line": str(s.line),
                "state_v2": s.state_v2, "hypothetical": s.state_v2 != "RECOMMENDED",
                "final_units": stake_of[s.decision_id].final}

    total = sum(p.final for p in allocated) + sum(p["stake"]["final_units"] for p in combos["built"])
    if not recommended:
        message = (f"No RECOMMENDED selection for {day.isoformat()} as of {at.isoformat()}: the portfolio is empty - "
                   "nothing is staked, there is no day set, no pick of the day and no parlay. None is invented.")
    else:
        message = (f"{len(recommended)} RECOMMENDED selection(s) for {day.isoformat()}: "
                   f"{sum(1 for p in allocated if p.final > 0 and not p.hypothetical)} staked, "
                   f"{len(chosen)} in the day set, {len(combos['built'])} parlay(s).")
    if what_if:
        message = ("HYPOTHETICAL (what-if): CAUTION is treated as eligible for MEASUREMENT ONLY - "
                   f"{len(hypothetical)} CAUTION selection(s) added after the RECOMMENDED ones, at stake-v1's CAUTELA "
                   "cap; parlays stay RECOMMENDED-only. Nothing here is a recommendation. " + message)
    binding = Counter(p.binding for p in allocated if p.binding is not None)
    return {
        "version": VERSION, "shadow": True, "mode": MODE_WHAT_IF if what_if else MODE_RECOMMENDED,
        "hypothetical": what_if, "day": day.isoformat(), "at": at.isoformat(), "message": message,
        "versions": {"decision": DECISION_CORE, "state": state_v2.VERSION, "stake": staking.VERSION,
                     "portfolio_stake": stakes.VERSION, "exposure": exposure.VERSION,
                     "correlation": correlation.VERSION, "measured_correlation": icc.VERSION,
                     "priority": day_priority.VERSION, "day_rule": decision.RULE_DAY, "parlay_rule": persist.RULE_VERSION},
        "counts": {"rows": len(selections), "by_state_v2": {s: by_state.get(s, 0) for s in state_v2.STATES},
                   "recommended": len(recommended), "hypothetical": len(hypothetical), "eligible": len(eligible),
                   "staked": sum(1 for p in allocated if p.final > 0), "total_units": round(total, 4)},
        "selections": [entry(s) for s in eligible],
        "correlations": [c.as_json() for c in corrs],
        "budget_groups": correlation.groups([s.decision_id for s in eligible], corrs),
        "exposure": book.as_json() | {"binding": dict(sorted(binding.items()))},
        "day_set": [day_entry(s) for s in chosen],
        "pick_of_the_day": day_entry(chosen[0]) if chosen else None,
        "parlays": combos,
    }


def build_day(conn: psycopg.Connection[Any], day: date, *, at: datetime, what_if: bool = False,
              joint: correlation.JointProvider | None = None) -> dict[str, Any]:
    """The shadow portfolio of ``day`` as of ``at``. Read-only."""
    selections = [Selection.of(r) for r in read_rows(conn, day=day, at=at)]
    return assemble(selections, day=day, at=at, what_if=what_if, joint=joint, measured=icc.latest(conn))
