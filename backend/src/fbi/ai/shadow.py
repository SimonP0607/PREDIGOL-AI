"""The AI's own prospective test: does the review add information - before it is allowed to touch users?

Over settled selections the AI reviewed BEFORE kick-off (the newest review of each selection, per engine),
three things are compared on the same matches:

    model         every selection the quantitative rule shortlisted (what users would get without the AI)
    model + AI    the selections the review kept (APPROVE, DOWNGRADE, ABSTAIN) - and APPROVE alone
    market        the de-vigged market's own forecast of the same selections

with log loss and Brier score (of the model's and the market's probabilities), calibration (expected
calibration error, ten bins), hit rate, ROI at the price taken (flat one unit), closing-line value (the price
taken at the closing fair probability, ``fbi.market.closing_value``: the system's single CLV), the claimed EV and
the EV by the market's own price, and the worst drawdown. REJECTION QUALITY is the point: what the review
rejected must do measurably worse than what it kept.

Beside the CLV the arms report the PRICE MOVE (the price taken against the final pre-match price of the same
bookmaker, margin in both): ``ai-gate-v1`` called that number CLV, and judged the gate by it; ``ai-gate-v2`` (plan
F0, defect 7) judges by the CLV and keeps the price move as information. Reports written under v1 keep what they say.

The corners and the cards of the shadow (phase 4, the Statistics Agent) are NOT in this gate: ``market_outcome`` refuses a count, so their reviews never enter it.
``counts_report`` measures them apart (CLV by arm and by stance, abstentions, Brier and log loss against the market) and always says ``not_judged``.

The gate (``ai-gate-v2``), which ``FBI_AI_MODE=enforce`` also needs (``fbi.ai.gating``):

* at least 300 settled reviewed selections over at least 30 days, at least 50 of them rejected;
* ROI(kept) - ROI(rejected) at least two standard errors above zero (bootstrap over matches);
* the kept selections' closing-line value (CLV) not below the rejected ones';
* the kept selections' Brier score no worse than all selections' (+0.002).

Otherwise the verdict is ``insufficient`` (not enough evidence yet) or ``fail``. The numbers are reported
either way; nothing is tuned to pass.

The engines of phase 3's shadow (``ma-v1``, ``ma-v1-h``, ``cs-v1``) are judged by the same rule over the same window, and a report is written for one
only once it has settled selections: until then it leaves no row of noise. They change nothing above them - ``fbi.ai.gating`` reads the report of
``combined`` and the comparison of the console the ones of ``combined`` and ``rules``.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.config import PRODUCTION_ENGINES, SHADOW_ENGINES
from fbi.market import closing_value
from fbi.picks.settlement import Status, market_outcome, profit

VERSION = "ai-gate-v2"
WINDOW = timedelta(days=60)
MIN_SELECTIONS = 300
MIN_DAYS = 30
MIN_REJECTED = 50
MIN_Z = 2.0
BRIER_TOLERANCE = 0.002
ENGINES = (*PRODUCTION_ENGINES, *SHADOW_ENGINES)
"""The engines a report is made for: ``rules``, ``llm``, ``combined`` as ever, and the three of phase 3's shadow (``fbi.ai.config``)."""
REPORTED_EMPTY = ("rules", "combined")
"""The engines whose report is written even when nothing has settled yet (an ``insufficient`` gate that counts from zero). The others - ``llm`` while no
model has reviewed, an engine of the shadow while no match it reviewed has settled - leave no row of noise."""
BOOTSTRAP = 300

SETTLED_SQL = """
WITH last AS (
    SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
           r.fixture_id, r.market_key, r.selection, r.line, r.odds, r.bookmaker_id, r.p_model, r.p_market, r.decision,
           r.reviewed_at, f.kickoff_at, res.reg_goals_home, res.reg_goals_away
      FROM ai.pick_reviews r
      JOIN core.fixtures f ON f.id = r.fixture_id
      JOIN core.fixture_results res ON res.fixture_id = f.id
     WHERE r.engine = %(engine)s AND r.reviewed_at < f.kickoff_at AND f.kickoff_at >= %(since)s
       AND f.kickoff_at < %(until)s AND f.status_group = 'finished' AND res.reg_goals_home IS NOT NULL
       AND r.odds IS NOT NULL AND r.p_model IS NOT NULL AND r.status IN ('ok', 'fallback')
     ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
)
SELECT l.*, cp.p_fair AS p_close
  FROM last l
  LEFT JOIN LATERAL (
      SELECT m.p_fair FROM market.market_consensus m
       WHERE m.fixture_id = l.fixture_id AND m.market_key = l.market_key AND m.selection = l.selection
         AND m.line = l.line AND m.devig_method = 'shin' AND m.as_of < l.kickoff_at
       ORDER BY m.as_of DESC LIMIT 1) cp ON true
"""
"""``p_close``: the closing fair probability - the Shin consensus of the last snapshot before kick-off, the same reference
``intel.decision_outcomes`` and ``picks.pick_line_value.lv_devigged`` use - for the CLV."""

CLOSE_SQL = """
SELECT fixture_id, bookmaker_id, market_key, selection, line, odds_decimal FROM market.final_prematch_odds
 WHERE fixture_id = ANY(%(fixtures)s)
"""


@dataclass(frozen=True)
class Settled:
    fixture_id: int
    kickoff_at: datetime
    decision: str
    odds: float
    p_model: float
    p_market: float | None
    status: str
    profit: float
    close: float | None
    """The final pre-match price of the same bookmaker (``market.final_prematch_odds``): for the PRICE MOVE."""
    p_close: float | None = None
    """The closing fair probability (Shin consensus before kick-off): for the CLV."""

    @property
    def won(self) -> bool | None:
        return True if self.status == "win" else False if self.status == "loss" else None


def _settle(r: dict[str, Any]) -> tuple[str, float]:
    try:
        st = market_outcome(r["market_key"], r["selection"], Decimal(r["line"]), int(r["reg_goals_home"]),
                            int(r["reg_goals_away"]))
    except ValueError:
        return "unknown", 0.0
    return st.value, float(profit(st, Decimal(r["odds"]), Decimal(1))) if st != Status.PENDING else 0.0


def load(conn: psycopg.Connection[Any], *, engine: str, since: datetime, until: datetime) -> list[Settled]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SETTLED_SQL, {"engine": engine, "since": since, "until": until})
        rows = [dict(r) for r in cur.fetchall()]
        fixtures = sorted({int(r["fixture_id"]) for r in rows})
        closes: dict[tuple[int, int, str, str, Decimal], float] = {}
        if fixtures:
            cur.execute(CLOSE_SQL, {"fixtures": fixtures})
            for c in cur.fetchall():
                closes[(int(c["fixture_id"]), int(c["bookmaker_id"]), c["market_key"], c["selection"],
                        Decimal(c["line"]))] = float(c["odds_decimal"])
    out = []
    for r in rows:
        status, prof = _settle(r)
        if status in ("unknown", "pending"):
            continue
        close = None if r["bookmaker_id"] is None else closes.get(
            (int(r["fixture_id"]), int(r["bookmaker_id"]), r["market_key"], r["selection"], Decimal(r["line"])))
        out.append(Settled(int(r["fixture_id"]), r["kickoff_at"], r["decision"], float(r["odds"]), float(r["p_model"]),
                           None if r["p_market"] is None else float(r["p_market"]), status, prof, close,
                           None if r["p_close"] is None else float(r["p_close"])))
    return out


def _ll(p: float, won: bool) -> float:
    return -math.log(min(max(p if won else 1 - p, 1e-6), 1.0))


def ece(pairs: Sequence[tuple[float, bool]], bins: int = 10) -> float | None:
    if not pairs:
        return None
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for p, w in pairs:
        buckets[min(bins - 1, int(p * bins))].append((p, w))
    n = len(pairs)
    return round(sum(len(b) / n * abs(sum(p for p, _ in b) / len(b) - sum(w for _, w in b) / len(b))
                     for b in buckets.values()), 5)


def max_drawdown(items: Sequence[Settled]) -> float:
    peak = cum = worst = 0.0
    for s in sorted(items, key=lambda x: (x.kickoff_at, x.fixture_id)):
        cum += s.profit
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return round(worst, 4)


def metrics(items: Sequence[Settled]) -> dict[str, Any]:
    n = len(items)
    if n == 0:
        return {"n": 0}
    binary = [s for s in items if s.won is not None]
    with_market = [s for s in binary if s.p_market is not None]
    clv = [closing_value.clv(s.odds, s.p_close) for s in items if s.p_close is not None]
    moves = [closing_value.price_move(s.odds, s.close) for s in items if s.close]
    out: dict[str, Any] = {
        "n": n, "fixtures": len({s.fixture_id for s in items}),
        "hit_rate": round(sum(1 for s in binary if s.won) / len(binary), 4) if binary else None,
        "profit": round(sum(s.profit for s in items), 4), "roi": round(sum(s.profit for s in items) / n, 4),
        "ev_claimed": round(sum(s.p_model * s.odds - 1 for s in items) / n, 4),
        "ev_market": round(sum((s.p_market or 0) * s.odds - 1 for s in with_market) / len(with_market), 4)
        if with_market else None,
        "clv": round(sum(clv) / len(clv), 4) if clv else None, "n_clv": len(clv),
        "price_move": round(sum(moves) / len(moves), 4) if moves else None, "n_price_move": len(moves),
        "logloss_model": round(sum(_ll(s.p_model, bool(s.won)) for s in binary) / len(binary), 5) if binary else None,
        "logloss_market": round(sum(_ll(s.p_market or 0.5, bool(s.won)) for s in with_market) / len(with_market), 5)
        if with_market else None,
        "brier_model": round(sum((s.p_model - (1.0 if s.won else 0.0)) ** 2 for s in binary) / len(binary), 5)
        if binary else None,
        "brier_market": round(sum(((s.p_market or 0.5) - (1.0 if s.won else 0.0)) ** 2 for s in with_market)
                              / len(with_market), 5) if with_market else None,
        "ece_model": ece([(s.p_model, bool(s.won)) for s in binary]),
        "ece_market": ece([(s.p_market or 0.5, bool(s.won)) for s in with_market]),
        "max_drawdown": max_drawdown(items),
    }
    return out


def roi_difference(kept: Sequence[Settled], rejected: Sequence[Settled], *, seed: int = 11) -> dict[str, Any]:
    """ROI(kept) - ROI(rejected), its bootstrap standard error (resampling matches, not bets) and z."""
    if not kept or not rejected:
        return {"diff": None, "se": None, "z": None}

    def by_fixture(xs: Sequence[Settled]) -> list[list[float]]:
        g: dict[int, list[float]] = defaultdict(list)
        for s in xs:
            g[s.fixture_id].append(s.profit)
        return list(g.values())

    def roi(groups: list[list[float]]) -> float:
        flat = [x for g in groups for x in g]
        return sum(flat) / len(flat) if flat else 0.0

    gk, gr = by_fixture(kept), by_fixture(rejected)
    diff = roi(gk) - roi(gr)
    rng = random.Random(seed)
    boots = []
    for _ in range(BOOTSTRAP):
        bk = [gk[rng.randrange(len(gk))] for _ in gk]
        br = [gr[rng.randrange(len(gr))] for _ in gr]
        boots.append(roi(bk) - roi(br))
    mean = sum(boots) / len(boots)
    se = math.sqrt(sum((b - mean) ** 2 for b in boots) / (len(boots) - 1))
    return {"diff": round(diff, 4), "se": round(se, 4), "z": round(diff / se, 3) if se > 0 else None}


def evaluate(items: list[Settled]) -> tuple[dict[str, Any], dict[str, Any]]:
    kept = [s for s in items if s.decision != "REJECT"]
    rejected = [s for s in items if s.decision == "REJECT"]
    arms = {"model": metrics(items), "model_ai": metrics(kept),
            "approved": metrics([s for s in items if s.decision == "APPROVE"]),
            "downgraded": metrics([s for s in items if s.decision == "DOWNGRADE"]),
            "rejected": metrics(rejected), "abstained": metrics([s for s in items if s.decision == "ABSTAIN"])}
    rq = roi_difference(kept, rejected)
    days = len({s.kickoff_at.date() for s in items})
    checks: dict[str, dict[str, Any]] = {
        "selections": {"value": len(items), "need": MIN_SELECTIONS, "ok": len(items) >= MIN_SELECTIONS},
        "days": {"value": days, "need": MIN_DAYS, "ok": days >= MIN_DAYS},
        "rejected": {"value": len(rejected), "need": MIN_REJECTED, "ok": len(rejected) >= MIN_REJECTED},
        "rejection_quality": {"value": rq, "need": f"z >= {MIN_Z}", "ok": rq["z"] is not None and rq["z"] >= MIN_Z},
    }
    ck, cr = arms["model_ai"].get("clv"), arms["rejected"].get("clv")
    checks["clv"] = {"value": {"kept": ck, "rejected": cr}, "need": "kept >= rejected",
                     "ok": ck is not None and cr is not None and ck >= cr}
    bk, ba = arms["model_ai"].get("brier_model"), arms["model"].get("brier_model")
    checks["calibration"] = {"value": {"kept": bk, "all": ba}, "need": f"kept <= all + {BRIER_TOLERANCE}",
                             "ok": bk is not None and ba is not None and bk <= ba + BRIER_TOLERANCE}
    sample_ok = checks["selections"]["ok"] and checks["days"]["ok"] and checks["rejected"]["ok"]
    verdict = ("pass" if all(c["ok"] for c in checks.values()) else "fail" if sample_ok else "insufficient")
    gate = {"version": VERSION, "verdict": verdict, "checks": checks, "rejection_quality": rq}
    return arms, gate


# -- the counts of the Statistics Agent (plan IA, phase 4) -----------------------------------------------------------------------------------------

COUNTS_VERSION = "ai-counts-v1"
"""The report of the corners and the cards of the shadow. It is NOT the gate ``ai-gate-v2`` (that one judges goals and result, and its settlement
(``market_outcome``) refuses a count, so the reviews of corners and cards never enter it): it measures, and it judges nothing."""
COUNTS_MIN_DAYS = 14
"""The days of evaluations the plan asks for before anybody reads the counts as evidence (section 34, phase 4: «14 días de evaluaciones»)."""
COUNTS_REASON = ("the plan asks for 14 days of evaluations and a person reads them: this report states the figures and never a pass "
                 "(a pass is forced by nobody, and the Statistics Agent reaches no decision from here)")

COUNTS_SQL = """
WITH last AS (
    SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
           r.fixture_id, r.market_key, r.selection, r.line, r.odds, r.bookmaker_id, r.p_model, r.p_market, r.decision, r.status,
           r.reviewed_at, f.kickoff_at, r.output #>> '{assessment,stats_evaluation}' AS stance
      FROM ai.pick_reviews r
      JOIN core.fixtures f ON f.id = r.fixture_id
     WHERE f.status_group = 'finished' AND r.engine = %(engine)s AND r.reviewed_at < f.kickoff_at
       AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
       AND r.odds IS NOT NULL AND r.p_model IS NOT NULL AND r.status IN ('ok', 'fallback')
       AND (left(r.market_key, 8) = 'CORNERS_' OR left(r.market_key, 6) = 'CARDS_')
     ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
)
SELECT l.*, cp.p_fair AS p_close
  FROM last l
  LEFT JOIN LATERAL (
      SELECT m.p_fair FROM market.market_consensus m
       WHERE m.fixture_id = l.fixture_id AND m.market_key = l.market_key AND m.selection = l.selection
         AND m.line = l.line AND m.devig_method = 'shin' AND m.as_of < l.kickoff_at
       ORDER BY m.as_of DESC LIMIT 1) cp ON true
"""
"""The newest review of each count selection before the kick-off, per engine, with the stance of ``A:stats_evaluation`` the engine read (NULL when it read
none) and the closing fair probability for the CLV: the same references as ``SETTLED_SQL``."""


class ScoreDoor(Protocol):
    """What the report needs of the scoreboard of the families (``fbi.families.score`` is one): who reads a market key and where the counts of the finished
    matches are. It is GIVEN, not imported: ``fbi.ai`` importing ``fbi.families`` would close one more loop between packages (``tests/unit/test_architecture``)."""

    def key_shape(self, key: str) -> tuple[str, str]: ...

    def measure_of(self, key: str) -> str: ...

    def measures_to_read(self, keys: Iterable[str]) -> list[str]: ...

    def load_counts(self, conn: psycopg.Connection[Any], measures: Sequence[str], *, since: datetime, until: datetime) -> dict[int, dict[str, int]]: ...


@dataclass(frozen=True)
class Counted:
    """A settled review of a count (corners or cards of the whole match) and what the engine read of the Statistics Agent."""

    family: str
    stance: str | None
    """The stance of ``A:stats_evaluation`` in the view the engine's Council read, or None when it read none (``cs-v1``, or a pass without the agent)."""
    answered: bool
    """The engine gave a verdict (review status ``ok``); False for a ``fallback`` (the arm did not answer: paused, skipped, invalid)."""
    item: Settled


def counts_of(rows: Sequence[dict[str, Any]], counts: dict[int, dict[str, int]], door: ScoreDoor) -> tuple[list[Counted], dict[str, int]]:
    """Settle the reviews of counts against the counts of the finished matches (pure). ``left``: ``half`` (a market of a half: never graded, the provider
    gives no corners by half), ``ungradable`` (a count is unknown or not settled yet: never read as a zero) and ``unreadable`` (a key nobody can read)."""
    from fbi.ai.agents.common import is_full_time
    from fbi.market.rules import RULES_BY_MEASURE
    from fbi.picks.count_settlement import settle_numbers

    left = {"half": 0, "ungradable": 0, "unreadable": 0}
    out: list[Counted] = []
    for r in rows:
        key = str(r["market_key"])
        if not is_full_time(key):
            left["half"] += 1
            continue
        try:
            kind, subject = door.key_shape(key)
            rule = RULES_BY_MEASURE[door.measure_of(key)]
            values = counts.get(int(r["fixture_id"]))
            st = None if values is None else settle_numbers(rule, kind, subject, str(r["selection"]), Decimal(r["line"]), values)
        except (ValueError, KeyError):
            left["unreadable"] += 1
            continue
        if st is None or st == Status.PENDING:
            left["ungradable"] += 1
            continue
        p_market = None if r["p_market"] is None else float(r["p_market"])
        settled = Settled(int(r["fixture_id"]), r["kickoff_at"], str(r["decision"]), float(r["odds"]), float(r["p_model"]), p_market, st.value,
                          float(profit(st, Decimal(r["odds"]), Decimal(1))), None, None if r["p_close"] is None else float(r["p_close"]))
        out.append(Counted("CORNERS" if key.startswith("CORNERS_") else "CARDS", r["stance"], r["status"] == "ok", settled))
    return out, left


def versus_market(items: Sequence[Settled]) -> dict[str, Any]:
    """The model against the market on the SAME rows (those with a market probability and a win or a loss): Brier and log loss of each, and the gain of the
    model over the market (positive: the model was closer to what happened). It measures; it decides nothing."""
    paired = [s for s in items if s.won is not None and s.p_market is not None]
    if not paired:
        return {"n": 0}
    n = len(paired)
    bm = sum((s.p_model - (1.0 if s.won else 0.0)) ** 2 for s in paired) / n
    bk = sum(((s.p_market or 0.5) - (1.0 if s.won else 0.0)) ** 2 for s in paired) / n
    lm = sum(_ll(s.p_model, bool(s.won)) for s in paired) / n
    lk = sum(_ll(s.p_market or 0.5, bool(s.won)) for s in paired) / n
    return {"n": n, "brier_model": round(bm, 5), "brier_market": round(bk, 5), "brier_gain": round(bk - bm, 5),
            "logloss_model": round(lm, 5), "logloss_market": round(lk, 5), "logloss_gain": round(lk - lm, 5)}


def counts_arms(items: Sequence[Counted]) -> dict[str, Any]:
    """What an engine did on the counts it reviewed that have settled: the figures of ``metrics`` for all of them, by the verdict it gave, by family and by what
    the Statistics Agent said (the CLV of each evaluation is the ``clv`` of its arm), its abstentions, and the model against the market on the same rows."""
    everything = [c.item for c in items]
    by_stance: dict[str, list[Settled]] = defaultdict(list)
    by_family: dict[str, list[Settled]] = defaultdict(list)
    for c in items:
        by_stance[c.stance or "none"].append(c.item)
        by_family[c.family].append(c.item)
    n = len(items)
    abstained = sum(1 for c in items if c.item.decision == "ABSTAIN")
    unanswered = sum(1 for c in items if not c.answered)
    return {
        "n": n,
        "by_decision": {name: metrics([s for s in everything if s.decision in decisions])
                        for name, decisions in (("kept", ("APPROVE", "DOWNGRADE", "ABSTAIN")), ("approved", ("APPROVE",)), ("downgraded", ("DOWNGRADE",)),
                                                ("rejected", ("REJECT",)), ("abstained", ("ABSTAIN",)))},
        "all": metrics(everything),
        "by_family": {family: {"all": metrics(xs), "versus_market": versus_market(xs)} for family, xs in sorted(by_family.items())},
        "by_stance": {stance: metrics(xs) for stance, xs in sorted(by_stance.items())},
        "abstentions": {"abstained": abstained, "no_answer": unanswered, "rate": round(abstained / n, 4) if n else None},
        "versus_market": versus_market(everything),
    }


def load_counted(conn: psycopg.Connection[Any], door: ScoreDoor, *, engine: str, since: datetime, until: datetime) -> tuple[list[Counted], dict[str, int]]:
    """The settled reviews of counts of an engine in a window, and what was left out (see ``counts_of``). Reads only."""
    from fbi.ai.agents.common import is_full_time

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COUNTS_SQL, {"engine": engine, "since": since, "until": until})
        rows = [dict(r) for r in cur.fetchall()]
    keys = [str(r["market_key"]) for r in rows if is_full_time(str(r["market_key"]))]
    counts: dict[int, dict[str, int]] = {}
    if keys:
        counts = door.load_counts(conn, door.measures_to_read(keys), since=since, until=until)
    return counts_of(rows, counts, door)


def counts_report(conn: psycopg.Connection[Any], door: ScoreDoor, *, at: datetime, window: timedelta = WINDOW, engines: Sequence[str] = SHADOW_ENGINES) -> dict[str, Any]:
    """The corners and the cards of the shadow, per engine of the shadow (``ma-v1`` and ``ma-v1-h`` read the Statistics Agent's assessments, ``cs-v1`` none:
    the comparison between them is the agent's contribution). Reads only, writes nothing, and the verdict is never a pass: ``not_judged``, with the days of
    evaluations it rests on against the 14 the plan asks for."""
    since, until = at - window, at
    out: dict[str, Any] = {}
    days: set[Any] = set()
    for engine in engines:
        items, left = load_counted(conn, door, engine=engine, since=since, until=until)
        days.update(c.item.kickoff_at.date() for c in items)
        out[engine] = {"left_out": left, **counts_arms(items)}
    return {"version": COUNTS_VERSION, "at": at.isoformat(), "window": {"since": since.isoformat(), "until": until.isoformat()},
            "verdict": "not_judged", "reason": COUNTS_REASON,
            "evidence": {"days": len(days), "need_days": COUNTS_MIN_DAYS, "enough_days": len(days) >= COUNTS_MIN_DAYS}, "engines": out}


@dataclass
class ShadowRun:
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)


def run_shadow(conn: psycopg.Connection[Any], *, at: datetime, store: bool = True) -> ShadowRun:
    since, until = at - WINDOW, at
    out = ShadowRun()
    for engine in ENGINES:
        items = load(conn, engine=engine, since=since, until=until)
        if engine not in REPORTED_EMPTY and not items:
            continue
        arms, gate = evaluate(items)
        out.reports[engine] = {"arms": arms, "gate": gate}
        if store:
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute("INSERT INTO ai.shadow_reports (created_at, window_from, window_to, engine, arms, gate, "
                            "version) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (at, since.date(), until.date(), engine, Jsonb(arms), Jsonb(gate), VERSION))
    return out


def latest(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT DISTINCT ON (engine) engine, created_at, window_from, window_to, arms, gate, version "
                    "FROM ai.shadow_reports ORDER BY engine, created_at DESC, id DESC")
        return [dict(r) for r in cur.fetchall()]


__all__ = ["COUNTS_VERSION", "ENGINES", "REPORTED_EMPTY", "VERSION", "counts_report", "evaluate", "latest", "load", "metrics", "run_shadow"]
