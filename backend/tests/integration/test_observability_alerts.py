"""The observability rail's alerts (``drift-v1``, ``cost-alerts-v1``, ``scripts.ia_alerts``) on a built world: every statement runs against
the migrated schema, an overconfident model and a falling CLV drift, a healthy calibrator does not, an expensive day and a cold cache
alert, and nothing is written. No network, no key. One transaction, rolled back.

THE DAY is Saturday 18 Sep 2032 (Bogotá). A CHAMPION identity calibrator of (OU, dixon_coles) was promoted a month before with a reference
of ECE 0.02 and the market's log loss; the fourteen days before the day hold its settled selections."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from scripts import ia_alerts

from fbi.ai.calendar import day_start
from fbi.ai.config import AiSettings
from fbi.ai.providers.base import LlmUsage
from fbi.ai.usage import UsageLedger, shared
from fbi.observability import cost_alerts as ca
from fbi.observability import drift as dr

from .conftest import Seed
from .helpers import scalar
from .test_budget_v3 import plan, settings, spend
from .test_gate_b_bench import fixture, run
from .test_intel import IntelWorld

D = Decimal
DAY = date(2032, 9, 18)
NOW = datetime(2032, 9, 20, 15, tzinfo=UTC)
PROMOTED = day_start(DAY) - timedelta(days=30)


def ko(day: date, k: int) -> datetime:
    return datetime(day.year, day.month, day.day, 18, tzinfo=UTC) + timedelta(minutes=k)


def champion(world: IntelWorld, *, ece: float = 0.02, ll: float = 0.66, ll_market: float = 0.66) -> int:
    cur = world.cur
    cur.execute("INSERT INTO intel.calibrators (market_key, model_name, method, version, params, known_at, fitted_at, n_train, "
                "train_hash, wf, gate) VALUES ('OU', 'dixon_coles', 'identity', 'cal-logit2-v1', '{}', %s, %s, 900, 'h', %s, '{}') "
                "RETURNING id", (PROMOTED, PROMOTED, Jsonb({"n": 1600, "ece_cal": ece, "logloss_cal": ll, "logloss_market": ll_market})))
    cid = scalar(cur)
    cur.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, to_role, gate_version, criteria, reason, "
                "decided_by) VALUES (%s, 'calibrator', 'OU', 'dixon_coles', %s, 'CHAMPION', 'calib-gate-v1', '{}', 'test', 'system')",
                (PROMOTED, cid))
    return int(cid)


def history(world: IntelWorld, *, overconfidence: float, per_day: int = 40, seed: int = 5) -> None:
    """Fourteen days ending on DAY of settled OU selections: outcomes drawn from the market, the model ``overconfidence`` above it."""
    rng = random.Random(seed)
    for back in range(14):
        day = DAY - timedelta(days=back)
        for k in range(per_day // 10):
            when = ko(day, k)
            fid = world.fixture(when)
            for line in ("0.5", "1.5", "2.5", "3.5", "4.5"):
                for selection in ("Over", "Under"):
                    p_mkt = rng.uniform(0.3, 0.7)
                    pid = world.pick(fid, "OU", selection, line, p_model=min(0.95, p_mkt + overconfidence), p_market=p_mkt,
                                     odds=round(0.97 / p_mkt, 3), created=when - timedelta(hours=3))
                    world.settle(pid, rng.random() < p_mkt, when + timedelta(hours=2))


def clv_rows(world: IntelWorld, *, recent: float, baseline: float) -> None:
    """Selections the core layer saw value in, settled with their CLV: 150 in the last 7 days, 400 in the 28 before (one match, a line
    each), plus rows the trend must leave out: no value seen, and outside the window."""
    fid = world.fixture(ko(DAY, 0))
    cur = world.cur

    def one(n: int, kick: datetime, clv: float, *, ev: float = 0.05) -> None:
        cur.execute("INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, "
                    "line, model_name, odds, p_model, p_cal, p_market, ev_raw, ev_cal, filters, state, context_status, input_hash) "
                    "VALUES ('decision-v1', %s, 'T-3h', %s, %s, 'OU', 'Over', %s, 'dixon_coles', 2.0, 0.55, 0.52, 0.5, 0.1, %s, '[]', "
                    "'CAUTELA', 'PENDING', %s) RETURNING id", (kick - timedelta(hours=3), fid, kick, n * 0.25, ev, f"clv-{n}"))
        did = scalar(cur)
        cur.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, clv, version, "
                    "computed_at) VALUES (%s, %s, 'win', 1, 1, %s, 'outcome-v1', %s)", (did, kick + timedelta(hours=2), clv, NOW))

    n = 0
    for i in range(150):
        n += 1
        one(n, ko(DAY - timedelta(days=i % 7), i), recent + (0.04 if i % 2 else -0.04))
    for i in range(400):
        n += 1
        one(n, ko(DAY - timedelta(days=7 + i % 28), i), baseline + (0.04 if i % 2 else -0.04))
    for i in range(40):
        n += 1
        one(n, ko(DAY, 200 + i), 0.5, ev=0.0)  # no value seen: not in the trend
        n += 1
        one(n, ko(DAY - timedelta(days=40), i), 0.5)  # before the baseline


def test_an_overconfident_champion_and_a_falling_clv_drift(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = IntelWorld(db, seed)
    cid = champion(world)
    history(world, overconfidence=0.12)
    clv_rows(world, recent=-0.06, baseline=-0.02)
    rep = dr.report(db, day=DAY, at=NOW)
    cells = {c.segment: c for c in rep.cells}
    assert set(cells) == {dr.ALL, "other_league"} and cells[dr.ALL].n == 14 * 40
    assert cells[dr.ALL].reference.calibrator_id == cid
    assert cells[dr.ALL].status == dr.DRIFT and cells[dr.ALL].metrics["ece_status"] == dr.DRIFT
    assert cells[dr.ALL].metrics["gap_status"] in (dr.WATCH, dr.DRIFT) and cells[dr.ALL].metrics["gap_drift"] > 0
    (trend,) = rep.clv
    assert (trend.subject, trend.recent_n, trend.baseline_n, trend.status) == ("decision-v1/OU", 150, 400, dr.DRIFT)
    rules = [a["rule"] for a in rep.alerts()]
    assert rules.count("calibration_drift") == 2 and "clv_trend" in rules


def test_a_healthy_champion_and_a_steady_clv_raise_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = IntelWorld(db, seed)
    champion(world, ll=0.67, ll_market=0.67)
    history(world, overconfidence=0.0)
    clv_rows(world, recent=-0.02, baseline=-0.02)
    rep = dr.report(db, day=DAY, at=NOW)
    assert [c.status for c in rep.cells] == [dr.OK, dr.OK] and rep.clv[0].status == dr.OK and rep.alerts() == []


def test_selections_after_the_day_or_settled_after_the_cut_off_are_not_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = IntelWorld(db, seed)
    champion(world)
    history(world, overconfidence=0.12)
    rep = dr.report(db, day=DAY - timedelta(days=1), at=NOW)
    assert rep.cells[0].n == 13 * 40, "the day after DAY is not in its window"
    early = dr.report(db, day=DAY, at=day_start(DAY) + timedelta(hours=1))
    assert early.cells[0].n == 13 * 40, "a selection of DAY settled after the cut-off is not read"


# ── costs ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

MATCH = ("match", "match-v2", "match-assess-v2", "evaluation")


def costs(db: psycopg.Connection[Any], seed: Seed, *, today_unit: str, cache_hit: float) -> None:
    """Fourteen days of ten matches with a market at 0.50 USD each and the day at ``today_unit``; the match agent on five matches a day
    (one run of 0.002 USD each; on the day ``today_unit`` / 0.5 runs each); the real-time cacheable input read at ``cache_hit`` on the
    last three days."""
    ledger = UsageLedger(shared(db))
    for back in range(15):
        day = DAY - timedelta(days=back)
        plan(db, day, 10)
        unit = D(today_unit) if back == 0 else D("0.5")
        spend(db, ko(day, 0), unit * 10)
        repeat = int(D(today_unit) / D("0.5")) if back == 0 else 1
        for k in range(5):
            fid = fixture(db, seed, ko(day, k))
            for _ in range(repeat):
                run(db, fid, MATCH, started=ko(day, k) - timedelta(hours=2), deadline=ko(day, k))
        if back < 3:
            total = 200_000
            reads = int(total * cache_hit)
            ledger.record(at=ko(day, 1), purpose="pick_review", tier="analysis", provider="anthropic", model="claude-sonnet-5-5",
                          usage=LlmUsage(input_tokens=300_000, cached_tokens=reads, cache_write_5m_tokens=total - reads),
                          cost=D(0), status="ok", workspace="PREDIGOL")


def by_rule(findings: tuple[ca.Finding, ...]) -> dict[str, ca.Finding]:
    return {f.rule if f.rule != "envelope_projection" else f.subject: f for f in findings}


def test_an_expensive_day_and_a_cold_cache_alert(db: psycopg.Connection[Any], seed: Seed) -> None:
    costs(db, seed, today_unit="2", cache_hit=0.2)
    rep = ca.report(db, day=DAY, at=NOW, settings=settings())
    f = by_rule(rep.findings)
    assert f["cost_per_match_production"].status == ca.ALERT
    assert f["cost_per_match_production"].evidence["baseline_median_usd"] == "0.500000"
    assert f["cost_per_match_agent"].status == ca.ALERT and f["cost_per_match_agent"].subject == "match match-v2"
    assert f["cost_per_match_agent"].evidence["today"]["matches"] == 5
    assert f["cache_hit_low"].status == ca.ALERT
    assert f["production month"].status == ca.OK and f["production month"].evidence["projected_usd"] is not None


def test_a_normal_day_with_a_warm_cache_raises_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    costs(db, seed, today_unit="0.5", cache_hit=0.7)
    rep = ca.report(db, day=DAY, at=NOW, settings=settings())
    assert rep.alerts() == [], rep.alerts()
    assert by_rule(rep.findings)["cost_per_match_agent"].status == ca.OK


def test_the_script_reports_with_evidence_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = IntelWorld(db, seed)
    champion(world)
    history(world, overconfidence=0.12)
    costs(db, seed, today_unit="2", cache_hit=0.2)
    tables = ("intel.promotions", "intel.calibrators", "intel.calibrator_evaluations", "ai.budget_alerts", "ai.envelope_alerts",
              "audit.notifications")
    before = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables}
    doc, code = ia_alerts.run(db, day=DAY, now=NOW, settings=settings())
    assert code == ia_alerts.ALERTS and doc["complete_day"] is True
    assert {"calibration_drift", "cost_per_match_production", "cost_per_match_agent", "cache_hit_low"} <= {a["rule"] for a in doc["alerts"]}
    assert all(a["evidence"] for a in doc["alerts"])
    assert {t: db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables} == before


def test_an_empty_database_has_nothing_to_say(db: psycopg.Connection[Any]) -> None:
    doc, code = ia_alerts.run(db, day=DAY, now=NOW, settings=AiSettings())
    assert code == ia_alerts.NONE and doc["alerts"] == [] and doc["drift"]["calibration"] == []
