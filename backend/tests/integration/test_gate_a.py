"""Gate A of the Plan Maestro IA (``fbi.ai.gate_a``, ``scripts/ia_gate.py``) on a built world.

The world is September 2032: ten matches with a market every day, a baseline week in which the layer cost 0.80 a match (the earlier
code: no workspace in the ledger), the phase-0 code from the 10th (0.40 a match, the cache reading, a batch, the evidence of the three
optimisations), the owner's actions done (a call of the LAB workspace with its own key) - and today the 20th at noon in Bogotá, so the
window is the 13th to the 19th. Each test spoils ONE thing and says what the gate answers.

The figures are written by hand into a transaction that is rolled back and the gate only reads them: a test of the arithmetic of the
verdict, not evidence of anything. The real gate runs on the real ledger, over seven complete real days."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import gate_a, gates, lab
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.providers.base import LlmUsage
from fbi.ai.usage import UsageLedger, shared

from .conftest import Seed
from .test_ai_decision_layer import Savepoints
from .test_rollback_compat import OLD_BRIEF_INSERT

D = Decimal
SONNET = TierModel("anthropic", "claude-sonnet-5-5")
NOW = datetime(2032, 9, 20, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá
FIRST, LAST = date(2032, 9, 13), date(2032, 9, 19)  # the window: seven complete days
BASE = (date(2032, 9, 2), date(2032, 9, 8))  # the baseline of this world
DEPLOY = date(2032, 9, 10)  # the first day the phase-0 code wrote the ledger
PLAN_FROM = date(2032, 8, 23)
GATES_AT = datetime(2032, 9, 9, 17, 0, tzinfo=UTC)  # the evidence of the optimisations, before the window
M = 10  # matches with a market, every day
UNIT = D("0.40")  # what a match costs in the window of the healthy world


def settings(**kw: Any) -> AiSettings:
    base: dict[str, Any] = {"mode": "shadow", "tiers": {"analysis": SONNET, "bulk": SONNET}, "keys": {"anthropic": "k"},
                            "lab_keys": {"anthropic": "kl"}, "monthly_budget": D(185), "daily_budget": D("6.17"),
                            "lab_monthly_budget": D(15), "joint_ceiling": D(190), "reserve": D(10), "exa_monthly_budget": D(35)}
    return AiSettings(**(base | kw))


def noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 17, 0, tzinfo=UTC)


def span(first: date, last: date) -> list[date]:
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def equivalence(variant: str, *, n: int = 210, repeat: int = 6, changed: int = 5,
                model: str = SONNET.model) -> tuple[dict[str, Any], bool]:
    """The evidence ``lab.equivalence_collect`` writes: every input's three letters (the same call twice, and the variant) and the
    assessment made from them - ``changed`` inputs where the variant moved the verdict, ``repeat`` where the second identical call did."""
    key = lab.VARIANT_KEY[variant]
    rows: dict[str, dict[str, str | None]] = {}
    letters: dict[str, str] = {}
    for k in range(n):
        second = "D" if k < repeat else "A"
        moved = "D" if k < changed else "A"
        rows[f"i{k:03d}"] = {"A1": "A", "A2": second, key: moved}
        letters[f"i{k:03d}"] = "A" + second + moved
    verdict = lab.assess(rows, variant)
    return ({"models": [model], "experiment": "equiv-v1:test", "min_inputs": lab.MIN_INPUTS, "assessment": verdict, "inputs": letters},
            bool(verdict["passed"]))


def fixtures_of(db: psycopg.Connection[Any], seed: Seed) -> list[int]:
    out = []
    for k in range(M):
        row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                         "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                         (9_500_000 + k, seed.season_id, seed.home_team_id, seed.away_team_id,
                          noon(date(2032, 9, 1)) + timedelta(hours=k))).fetchone()
        assert row is not None
        out.append(int(row[0]))
    return out


def brief_of(db: psycopg.Connection[Any], fixture_id: int) -> int:
    params: dict[str, Any] = {
        "fixture": fixture_id, "at": NOW, "pass": "first", "version": "brief-v8", "engine": "llm", "provider": "anthropic",
        "model": SONNET.model, "packet": None, "hash": "h", "status": "ok", "escalate": False, "reasons": [], "uncertainty": "low",
        "quality": "good", "content": Jsonb({"summary": "s"}), "rejected": Jsonb([]), "usage": [], "cost": D("0.01"), "error": None}
    row = db.execute(OLD_BRIEF_INSERT, params).fetchone()
    assert row is not None
    return int(row[0])


REVIEW = ("INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, input_hash, "
          "decision, confidence, output, mode, status) VALUES (%s, %s, 'over25', %s, 0, %s, 'r-v1', 'h', 'APPROVE', 0.5, "
          "'{}'::jsonb, 'shadow', 'ok')")
PASS_ROW = ("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, brief_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'ok', %s)")


def build(db: psycopg.Connection[Any], seed: Seed, *, unit: Decimal = UNIT, pre_missing: int = 0, final_late: int = 0,
          llm: int = 2, cache_days: int = 7, cache: tuple[int, int] | None = (6000, 4000), batch: str | None = "ok",
          with_gates: bool = True, lab_call: bool = True, deploy: date = DEPLOY) -> None:
    """The world. ``pre_missing`` / ``final_late``: how many of the window's 70 pre passes were never done / final passes ended after
    T-15; ``llm``: of the 4 candidates a day, how many the window's days got a model review for (the baseline gets 2);
    ``cache`` = (tokens read, tokens written) a day, read only on the first ``cache_days`` days; ``batch``: ok, stuck, unrecorded,
    expired or None."""
    fixtures = fixtures_of(db, seed)
    brief = brief_of(db, fixtures[0])
    covered = {*span(*BASE), *span(FIRST, LAST)}
    for day in span(PLAN_FROM, LAST):
        universe = [{"fixture_id": f, "has_market": True} for f in fixtures] if day in covered else []
        db.execute("INSERT INTO ai.day_plans (day, stage, created_at, version, fixtures_total, fixtures_with_market, universe) "
                   "VALUES (%s, 'opened', %s, 'day-v1', %s, %s, %s)", (day, noon(day) - timedelta(hours=12), M, M, Jsonb(universe)))
    for day in sorted(covered):
        in_window = FIRST <= day <= LAST
        kickoff = noon(day) + timedelta(hours=3)
        for k, f in enumerate(fixtures):
            n = (day - FIRST).days * M + k  # 0..69 inside the window
            for kind, start, end in (("first", noon(day) - timedelta(hours=11, minutes=55), noon(day) - timedelta(hours=11, minutes=54)),
                                     ("pre", kickoff - timedelta(hours=6), kickoff - timedelta(hours=6) + timedelta(minutes=2)),
                                     ("final", kickoff - timedelta(hours=1),
                                      kickoff - timedelta(minutes=10 if in_window and n < final_late else 40))):
                if kind == "pre" and in_window and n < pre_missing:
                    continue
                db.execute(PASS_ROW, (f, day, kind, start, end, kickoff, brief))
        for s in range(4):
            selection = f"s{day.toordinal()}_{s}"
            db.execute(REVIEW, (noon(day), fixtures[0], selection, "rules"))
            if s < (llm if in_window else 2):
                db.execute(REVIEW, (noon(day), fixtures[0], selection, "llm"))
    ledger = UsageLedger(shared(db))
    for day in span(BASE[0], LAST):
        if BASE[0] <= day <= BASE[1]:
            ledger.record(at=noon(day), purpose="pick_review", tier="analysis", provider="anthropic", model=SONNET.model,
                          usage=None, cost=D("0.80") * M, status="ok")
        elif day >= deploy:
            reads, writes = (0, 0) if cache is None else (cache[0] if (day - FIRST).days < cache_days else 0, cache[1])
            ledger.record(at=noon(day), purpose="pick_review", tier="analysis", provider="anthropic", model=SONNET.model,
                          usage=LlmUsage(input_tokens=reads + writes + 2000, output_tokens=500, cached_tokens=reads,
                                         cache_write_5m_tokens=writes),
                          cost=unit * M, status="ok", workspace="PREDIGOL", key_label="worker-prod")
    if batch is not None:
        row = db.execute("INSERT INTO ai.batches (batch_ref, provider, workspace, key_label, kind, status, created_at, submitted_at, "
                         "ended_at, expires_at, processed_at, n_items) VALUES ('msgbatch_t1', 'anthropic', 'PREDIGOL', 'worker-prod', "
                         "'production', 'ended', %s, %s, %s, %s, %s, 20) RETURNING id",
                         (noon(date(2032, 9, 14)), noon(date(2032, 9, 14)), noon(date(2032, 9, 14)) + timedelta(hours=2),
                          noon(date(2032, 9, 15)), noon(date(2032, 9, 14)) + timedelta(hours=2))).fetchone()
        assert row is not None
        batch_id = int(row[0])
        for k in range(20):
            status = "succeeded"
            record_usage = True
            if k == 19 and batch == "stuck":
                status, record_usage = "submitted", False
            if k == 19 and batch == "unrecorded":
                record_usage = False
            if k >= 18 and batch == "expired":
                status = "expired"
            uid = ledger.record(at=noon(date(2032, 9, 14)), purpose="pick_review", tier="analysis", provider="anthropic",
                                model=SONNET.model, usage=None, cost=D(0), status="timeout" if status == "expired" else "ok",
                                workspace="PREDIGOL", key_label="worker-prod", batch_id=batch_id, custom_id=f"t{k}") \
                if record_usage else None
            db.execute("INSERT INTO ai.batch_items (batch_id, custom_id, purpose, tier, model, input_hash, status, created_at, "
                       "resolved_at, usage_id) VALUES (%s, %s, 'pick_review', 'analysis', %s, 'h', %s, %s, %s, %s)",
                       (batch_id, f"t{k}", SONNET.model, status, noon(date(2032, 9, 14)),
                        None if status == "submitted" else noon(date(2032, 9, 14)) + timedelta(hours=2), uid))
    if with_gates:
        gates.record_gate(db, gate="batch", passed=True, at=GATES_AT, evidence={"models": [SONNET.model], "probe": "ok"})
        for variant in ("native_schema", "shared_layout"):
            evidence, passed = equivalence(variant)
            gates.record_gate(db, gate=lab.GATE_OF_VARIANT[variant], passed=passed, evidence=evidence, at=GATES_AT)
    if lab_call:
        ledger.record(at=noon(date(2032, 9, 12)), purpose="other", tier="analysis", provider="anthropic", model=SONNET.model,
                      usage=None, cost=D("0.02"), status="ok", workspace="PREDIGOL-LAB", key_label="worker-lab")


def evaluate(db: psycopg.Connection[Any], *, cfg: AiSettings | None = None, **kw: Any) -> gate_a.GateReport:
    kw.setdefault("at", NOW)
    return gate_a.evaluate(db, cfg or settings(), baseline_coverage=BASE, baseline_unit=BASE, **kw)


def checks(report: gate_a.GateReport) -> dict[str, gate_a.Check]:
    return {c.id: c for c in report.checks}


def failing(report: gate_a.GateReport) -> set[str]:
    return {c.id for c in report.checks if c.ok is False}


# ── the window: seven complete days, in one configuration ──────────────────────────────────────────────────────────

def test_while_the_phase_0_code_has_written_nothing_there_is_nothing_to_measure(db: psycopg.Connection[Any]) -> None:
    report = evaluate(db)
    assert report.verdict == gate_a.PENDING_TIME and not report.recordable
    assert report.window.anchor is None and not report.window.complete
    assert "has not written the ledger" in report.pending[0]


def test_fewer_than_seven_complete_days_is_pending_by_real_time_and_is_never_recorded(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    at = noon(date(2032, 9, 15))  # the 14th is the last complete day: 11th..14th are stable, four of the seven
    report = evaluate(db, at=at)
    assert report.verdict == "PENDIENTE POR TIEMPO REAL" == gate_a.PENDING_TIME
    assert report.window.anchor == date(2032, 9, 11) and report.window.stable_days == 4
    assert report.window.eligible_on == date(2032, 9, 18), "the first day on which seven complete stable days exist"
    assert "4 de 7 días completos" in report.pending[0] and "2032-09-18" in report.pending[0]
    assert report.checks == () and report.preview["note"].startswith("NOT evidence")
    assert gate_a.record(db, report) is None
    assert db.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'gate_a'").fetchone() == (0,)
    assert not gates.gate_state(db, "gate_a").passed


def test_the_window_is_complete_on_the_first_day_that_has_seven_stable_days_behind_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    assert not gate_a.window_of(db, at=noon(date(2032, 9, 17))).complete
    w = gate_a.window_of(db, at=noon(date(2032, 9, 18)))
    assert (w.first, w.last, w.complete, w.stable_days) == (date(2032, 9, 11), date(2032, 9, 17), True, 7)


def test_only_a_complete_day_can_be_measured(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(ValueError, match="not a complete day yet"):
        gate_a.window_of(db, at=NOW, through=date(2032, 9, 20))


def test_an_optimisation_turned_on_or_off_moves_the_start_of_the_window(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    assert gate_a.flips(db) == [(date(2032, 9, 9), "batch on"), (date(2032, 9, 9), "cache_layout on"),
                                (date(2032, 9, 9), "native_schema on")]
    gates.record_gate(db, gate="batch", passed=True, at=noon(date(2032, 9, 14)), evidence={"again": True})
    assert len(gate_a.flips(db)) == 3, "a row that repeats the answer changes nothing"
    assert gate_a.window_of(db, at=NOW).complete
    gates.record_gate(db, gate="batch", passed=False, at=noon(date(2032, 9, 16)), evidence={"why": "expired"})
    w = gate_a.window_of(db, at=NOW)
    assert not w.complete and w.anchor == date(2032, 9, 17) and "batch off, 2032-09-16" in str(w.anchored_by)
    assert evaluate(db).verdict == gate_a.PENDING_TIME


def test_a_deploy_that_changed_the_layer_can_be_declared_and_only_delays(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    assert gate_a.window_of(db, at=NOW, changes=[date(2032, 9, 12)]).complete, "before the window: nothing changes"
    w = gate_a.window_of(db, at=NOW, changes=[date(2032, 9, 14)])
    assert not w.complete and w.anchor == date(2032, 9, 15) and "declared" in str(w.anchored_by)
    assert evaluate(db, changes=[date(2032, 9, 14)]).verdict == gate_a.PENDING_TIME


# ── a healthy week ────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_healthy_week_passes_with_its_arithmetic_on_view_and_is_recorded(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    report = evaluate(db)
    assert report.verdict == gate_a.PASS == "PASA", [c.id for c in report.checks if c.ok is not True]
    assert report.window.first == FIRST and report.window.last == LAST and report.window.complete
    by = checks(report)
    assert set(by) == {"window", "plans", "cost_production", "cost_joint", "cost_heavy", "coverage", "final_t15",
                       "verdict_equivalence", "cache_visible", "batch_lost", "manual_actions"}
    cost = by["cost_production"].detail
    assert (D(cost["unit_usd_per_match"]), D(cost["projection_usd"]), D(cost["month_matches"]), cost["window_matches"]) == \
        (D("0.4"), D(120), D(300), 70), "0.40 a match x the 300 matches of September (19 gone as planned, 11 as their weekday)"
    assert D(cost["saving_vs_baseline_pct"]) == D(50) and D(cost["claude_usd_per_day"]) == D(4)
    assert D(by["cost_joint"].detail["total_usd"]) == D(171) and D(by["cost_heavy"].detail["production_heavy_usd"]) == D(150)
    assert by["coverage"].detail["metrics"]["pre_ok"] == {"label": "pasadas pre hechas", "window_pct": "100.00",
                                                           "baseline_pct": "100.00", "ok": True}
    cache = by["cache_visible"].detail
    assert (cache["hit_rate_pct"], cache["days_reading"], cache["read_tokens"], cache["written_tokens"]) == ("60.00", 7, 42000, 28000)
    batch = by["batch_lost"].detail
    assert (batch["batch_on"], batch["requests"], batch["lost"], batch["expired"]) == (True, 20, 0, 0)
    assert by["manual_actions"].detail["action_3_and_5"]["done"] and by["manual_actions"].detail["action_7"]["done"]
    assert report.consequence is None and report.recordable
    assert report.lines()[0] == "GATE A · PASA" and "Ventana: 2032-09-13 a 2032-09-19" in report.lines()[1]

    row = gate_a.record(db, report, code_version="test")
    assert row is not None
    state = gates.gate_state(db, "gate_a")
    assert state.passed and state.evidence_hash is not None and state.at == NOW
    stored = db.execute("SELECT evidence, decided_by, code_version FROM ai.feature_gates WHERE id = %s", (row,)).fetchone()
    assert stored is not None and stored[1:] == ("script", "test")
    assert gates.evidence_hash(stored[0]) == state.evidence_hash, "the hash is of the evidence as stored: it can be reproduced"
    assert stored[0]["verdict"] == "PASA" and next(c["id"] for c in stored[0]["checks"]) == "window"


# ── cost ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_unit_cost_that_projects_over_185_fails_and_names_the_switches_to_roll_back(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, unit=D("0.65"))  # 0.65 x 300 = 195
    report = evaluate(db)
    assert report.verdict == gate_a.FAIL and failing(report) == {"cost_production", "cost_joint", "cost_heavy"}
    assert D(checks(report)["cost_production"].detail["projection_usd"]) == D(195)
    assert report.consequence is not None and report.consequence.startswith("se revierte el interruptor que falle")
    assert report.recordable
    row = gate_a.record(db, report)
    assert row is not None and not gates.gate_state(db, "gate_a").passed, "a NO PASA is recorded too: the newest row decides"


def test_when_only_the_cost_with_the_shadow_fails_the_shadow_is_planned_with_less_sample(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, unit=D("0.48"))  # 144 alone, 195 with the shadow at 30 %, 180 in a heavy month
    report = evaluate(db)
    assert report.verdict == gate_a.FAIL and failing(report) == {"cost_joint"}
    assert report.consequence is not None and "la sombra se planifica con menos muestra" in report.consequence
    assert "300 selecciones en 30 días" in report.consequence
    joint = checks(report)["cost_joint"].detail
    assert D(joint["total_usd"]) == D(195) and joint["shadow_share_that_fits_pct"] == "27.06", "(190 - 144) / 51 of the 30 %"


def test_the_edge_of_the_ceiling_passes(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, unit=D("0.46"))  # 138: with the shadow 189 <= 190, heavy 172.5
    report = evaluate(db)
    assert report.verdict == gate_a.PASS and D(checks(report)["cost_joint"].detail["total_usd"]) == D(189)


# ── coverage ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_pass_missing_for_a_few_matches_is_inside_the_tolerance_but_not_for_more(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, pre_missing=1)  # 69 of 70: 98.57 % against 100 %, 1.43 points
    assert evaluate(db).verdict == gate_a.PASS


def test_coverage_two_points_under_the_baseline_fails_and_says_which_figure(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, pre_missing=2)  # 68 of 70: 97.14 %, 2.86 points under
    report = evaluate(db)
    assert report.verdict == gate_a.FAIL and failing(report) == {"coverage"}
    metrics = checks(report)["coverage"].detail["metrics"]
    assert metrics["pre_ok"]["ok"] is False and metrics["pre_ok"]["window_pct"] == "97.14"
    assert all(metrics[k]["ok"] is True for k in ("informed", "first_ok", "final_ok", "candidates_reviewed"))
    assert report.consequence is not None and "FBI_AI_BRIEF_MATERIAL" in report.consequence


def test_fewer_candidates_reviewed_by_the_model_is_less_coverage(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, llm=1)  # a quarter of the candidates against a half in the baseline
    report = evaluate(db)
    assert failing(report) == {"coverage"}
    reviewed = checks(report)["coverage"].detail["metrics"]["candidates_reviewed"]
    assert (reviewed["window_pct"], reviewed["baseline_pct"], reviewed["ok"]) == ("25.00", "50.00", False)


def test_the_coverage_does_not_move_with_the_matches_that_enter_a_plan_after_it_opened(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    extra = fixtures_of_extra(db, seed)
    brief = db.execute("SELECT id FROM ai.match_briefs LIMIT 1").fetchone()
    assert brief is not None
    for day in span(FIRST, LAST):  # a late match every day: it has its passes but was not in the plan of 00:05
        db.execute(PASS_ROW, (extra, day, "first", noon(day), noon(day) + timedelta(minutes=1), noon(day) + timedelta(hours=3), brief[0]))
    mine = gate_a.coverage(db, FIRST, LAST)
    assert mine.opened == 70 and mine.informed == 70 and mine.first_ok == 70, "the late matches are not counted against the plan"


def fixtures_of_extra(db: psycopg.Connection[Any], seed: Seed) -> int:
    row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                     "VALUES (9600000, %s, %s, %s, %s) RETURNING id",
                     (seed.season_id, seed.home_team_id, seed.away_team_id, noon(date(2032, 9, 1)) + timedelta(hours=20))).fetchone()
    assert row is not None
    return int(row[0])


def test_the_final_verdict_must_come_before_t_minus_15_in_99_percent_of_the_passes(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, final_late=1)  # 69 of 70 = 98.57 %
    report = evaluate(db)
    assert failing(report) == {"final_t15"}
    detail = checks(report)["final_t15"].detail
    assert (detail["final_passes"], detail["before_t15"], detail["rate_pct"]) == (70, 69, "98.57")
    assert report.consequence is not None and "FBI_AI_BATCH" in report.consequence


# ── the cache ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("kw", "why"), [
    ({"cache": None}, "the cache is not visible at all"),
    ({"cache_days": 5}, "reads on five of the seven days: it must be six"),
    ({"cache": (1000, 9000)}, "10 % of what was cached is read, 40 % is the alarm"),
])
def test_a_cache_that_is_not_seen_reading_fails(db: psycopg.Connection[Any], seed: Seed, kw: dict[str, Any], why: str) -> None:
    build(db, seed, **kw)
    report = evaluate(db)
    assert failing(report) == {"cache_visible"}, why
    assert report.consequence is not None and "FBI_AI_CACHE" in report.consequence


def test_six_days_of_reads_at_forty_percent_is_enough(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, cache_days=6, cache=(3200, 4000))  # 6 x 3,200 read against 7 x 4,000 written: 19,200 / 47,200
    detail = checks(evaluate(db))["cache_visible"].detail
    assert detail["days_reading"] == 6 and detail["hit_rate_pct"] == "40.68"


# ── the batch ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("scenario", ["stuck", "unrecorded"])
def test_a_batch_result_that_was_lost_fails_the_gate(db: psycopg.Connection[Any], seed: Seed, scenario: str) -> None:
    build(db, seed, batch=scenario)
    report = evaluate(db)
    assert failing(report) == {"batch_lost"}
    detail = checks(report)["batch_lost"].detail
    assert detail["lost"] == 1 and detail["requests"] == 20
    assert report.consequence is not None and "FBI_AI_BATCH" in report.consequence


def test_more_than_one_percent_of_the_requests_expiring_fails_the_gate(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, batch="expired")
    detail = checks(evaluate(db))["batch_lost"].detail
    assert (detail["lost"], detail["expired"], detail["expired_pct"]) == (0, 2, "10.00")
    assert checks(evaluate(db))["batch_lost"].ok is False


def test_batch_on_and_not_a_single_request_through_it_is_a_failure_and_off_is_not(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, batch=None)
    on = gate_a.check_batch(db, settings(), gate_a.window_of(db, at=NOW), at=NOW)
    assert on.ok is False and "ON and not one request" in on.detail["note"]
    off = gate_a.check_batch(db, settings(switches=lab_switches(batch="off")), gate_a.window_of(db, at=NOW), at=NOW)
    assert off.ok is True and "off and nothing went through it" in off.detail["note"]


def lab_switches(**over: str) -> dict[str, Any]:
    from fbi.ai.config import SWITCH_ENV

    return {name: over.get(name, "auto") for name in SWITCH_ENV}


# ── the evidence of the optimisations: recomputed, not believed ───────────────────────────────────────────────────

def test_the_equivalence_is_recomputed_from_the_letters_stored(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    one = gate_a.equivalence_of(db, "native_schema")
    assert one["state"] == "passed" and (one["complete_inputs"], one["changed_repeat"], one["changed_variant"]) == (210, 6, 5)
    assert gate_a.equivalence_of(db, "batch")["probe_passed"] is True


def test_an_assessment_that_the_letters_do_not_reproduce_fails(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, with_gates=False)
    evidence, _ = equivalence("native_schema")
    evidence["assessment"] = evidence["assessment"] | {"changed_variant": 1}  # the row claims less change than its letters hold
    gates.record_gate(db, gate="batch", passed=True, at=GATES_AT, evidence={"models": [SONNET.model]})
    gates.record_gate(db, gate="native_schema", passed=True, at=GATES_AT, evidence=evidence)
    cache_evidence, passed = equivalence("shared_layout")
    gates.record_gate(db, gate="cache_layout", passed=passed, at=GATES_AT, evidence=cache_evidence)
    check = gate_a.check_equivalence(db, settings())
    assert check.ok is False and check.detail["not_reproducible"] == ["native_schema"]


def test_a_variant_that_changed_more_verdicts_than_repeating_the_call_and_is_off_is_reported_and_does_not_block(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    """The owner's decision A (27 Oct 2026): what is off changes nothing the window measures, so it is listed and not judged."""
    build(db, seed, with_gates=False)
    gates.record_gate(db, gate="batch", passed=True, at=GATES_AT, evidence={"models": [SONNET.model]})
    bad, passed = equivalence("native_schema", repeat=3, changed=9)
    assert passed is False
    gates.record_gate(db, gate="native_schema", passed=False, at=GATES_AT, evidence=bad)
    good, ok = equivalence("shared_layout")
    gates.record_gate(db, gate="cache_layout", passed=ok, at=GATES_AT, evidence=good)
    check = gate_a.check_equivalence(db, settings())
    detail = check.detail
    assert check.ok is True and detail["failed"] == [] and detail["missing"] == [] and detail["not_reproducible"] == []
    assert detail["in_force"] == {"batch": True, "native_schema": False, "cache_layout": True}
    assert detail["judged"] == ["batch", "cache_layout"]
    assert detail["not_in_force"] == {"native_schema": "failed"} and detail["rolled_back"] == ["native_schema"]
    assert detail["optimisations"]["native_schema"]["changed_variant"] == 9 > detail["optimisations"]["native_schema"]["changed_repeat"] == 3, \
        "its figures stay on view in the report"
    assert "reported, not judged (off): native_schema" in detail["note"]
    assert evaluate(db).verdict == gate_a.PASS, "and the gate does not wait for a measure of something that is not running"


def test_a_variant_rejected_by_its_evidence_but_forced_on_by_the_owner_fails_and_names_its_switch(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, with_gates=False)
    gates.record_gate(db, gate="batch", passed=True, at=GATES_AT, evidence={"models": [SONNET.model]})
    bad, _ = equivalence("native_schema", repeat=3, changed=9)
    gates.record_gate(db, gate="native_schema", passed=False, at=GATES_AT, evidence=bad)
    good, ok = equivalence("shared_layout")
    gates.record_gate(db, gate="cache_layout", passed=ok, at=GATES_AT, evidence=good)
    forced = settings(switches=lab_switches(native_schema="on"))
    check = gate_a.check_equivalence(db, forced)
    assert check.ok is False and check.detail["in_force"]["native_schema"] is True
    assert check.detail["failed"] == ["native_schema"] and check.detail["rolled_back"] == []
    assert check.revert == "FBI_AI_NATIVE_SCHEMA", "the switch to roll back is the one in force that fails, not a list of all of them"
    report = evaluate(db, cfg=forced)
    assert report.verdict == gate_a.FAIL and "verdict_equivalence" in failing(report)
    assert report.consequence is not None and "FBI_AI_NATIVE_SCHEMA" in report.consequence


def test_a_batch_forced_on_whose_probe_failed_fails_and_a_batch_left_to_its_probe_is_only_reported(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, with_gates=False)
    gates.record_gate(db, gate="batch", passed=False, at=GATES_AT, evidence={"models": [SONNET.model], "why": "probe failed"})
    for variant in ("native_schema", "shared_layout"):
        evidence, passed = equivalence(variant)
        gates.record_gate(db, gate=lab.GATE_OF_VARIANT[variant], passed=passed, evidence=evidence, at=GATES_AT)
    left = gate_a.check_equivalence(db, settings())
    assert left.ok is True and left.detail["not_in_force"] == {"batch": "failed"}
    forced = gate_a.check_equivalence(db, settings(switches=lab_switches(batch="on")))
    assert forced.ok is False and forced.detail["failed"] == ["batch"] and forced.revert == "FBI_AI_BATCH"


def test_a_failed_batch_probe_leaves_batch_off_and_the_other_checks_judge_what_is_left(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, with_gates=False, batch=None)
    gates.record_gate(db, gate="batch", passed=False, at=GATES_AT, evidence={"models": [SONNET.model], "why": "probe failed"})
    for variant in ("native_schema", "shared_layout"):
        evidence, passed = equivalence(variant)
        gates.record_gate(db, gate=lab.GATE_OF_VARIANT[variant], passed=passed, evidence=evidence, at=GATES_AT)
    report = evaluate(db)
    assert report.verdict == gate_a.PASS, [c.id for c in report.checks if c.ok is not True]
    assert checks(report)["verdict_equivalence"].detail["rolled_back"] == ["batch"]
    assert checks(report)["batch_lost"].detail["batch_on"] is False


def test_with_nothing_in_force_there_is_nothing_to_compare_and_the_check_does_not_block(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, with_gates=False)
    check = gate_a.check_equivalence(db, settings())
    assert check.ok is True and check.detail["judged"] == [] and "nothing to compare" in check.detail["note"]
    assert check.detail["unmeasured"] == ["batch", "native_schema", "cache_layout"], "and the report says none was ever measured"
    assert check.detail["not_in_force"] == dict.fromkeys(gate_a.OPTIMISATIONS, "missing")


def test_missing_or_too_small_evidence_of_what_is_in_force_is_pending_never_a_pass(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, with_gates=False)
    forced = settings(switches=lab_switches(native_schema="on"))
    check = gate_a.check_equivalence(db, forced)
    assert check.ok is None and check.detail["missing"] == ["native_schema"], "forced on without a single measure"
    gates.record_gate(db, gate="batch", passed=True, at=GATES_AT, evidence={"models": [SONNET.model]})
    small, _ = equivalence("native_schema", n=150, repeat=4, changed=3)
    gates.record_gate(db, gate="native_schema", passed=False, at=GATES_AT, evidence=small)
    full, passed = equivalence("shared_layout")
    gates.record_gate(db, gate="cache_layout", passed=passed, at=GATES_AT, evidence=full)
    check = gate_a.check_equivalence(db, forced)
    assert check.ok is None and check.detail["missing"] == ["native_schema"], "150 inputs are INSUFICIENTE, not a verdict"
    assert check.detail["optimisations"]["native_schema"]["state"] == "insufficient"
    assert "pruebas del LAB de lo que está en vigor (native_schema)" in gate_a._waiting_for(check)
    # the same 150 inputs with the switch left to its evidence: off, so reported (not measured) and not judged
    left = gate_a.check_equivalence(db, settings())
    assert left.ok is True and left.detail["unmeasured"] == ["native_schema"] and left.detail["judged"] == ["batch", "cache_layout"]
    # a row that CLAIMS a pass with 150 inputs turns the switch on (auto): in force, and 150 inputs are still not a verdict
    gates.record_gate(db, gate="native_schema", passed=True, at=GATES_AT + timedelta(minutes=1), evidence=small)
    claimed = gate_a.check_equivalence(db, settings())
    assert claimed.ok is None and claimed.detail["in_force"]["native_schema"] is True and claimed.detail["missing"] == ["native_schema"]


# ── the manual actions of the owner, by data ──────────────────────────────────────────────────────────────────────

def test_the_actions_are_done_when_the_lab_answered_with_its_own_key_and_the_server_holds_the_budgets(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    check = gate_a.check_actions(db, settings())
    assert check.ok is True and check.detail["action_3_and_5"]["lab_key_differs_from_production"] is True


@pytest.mark.parametrize(("kw", "lab_call", "where"), [
    ({}, False, "action_3_and_5"),
    ({"lab_keys": {}}, True, "action_7"),
    ({"lab_keys": {"anthropic": "k"}}, True, "action_3_and_5"),
    ({"monthly_budget": D(190)}, True, "action_7"),
    ({"lab_monthly_budget": D(55)}, True, "action_7"),
    ({"exa_monthly_budget": D(20)}, True, "action_7"),
])
def test_an_action_not_done_is_pending_for_the_owner_never_a_failure(db: psycopg.Connection[Any], seed: Seed, kw: dict[str, Any],
                                                                     lab_call: bool, where: str) -> None:
    build(db, seed, lab_call=lab_call)
    check = gate_a.check_actions(db, settings(**kw))
    assert check.ok is None and check.detail[where]["done"] is False


def test_the_report_never_carries_a_key(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    text = str(evaluate(db, cfg=settings(keys={"anthropic": "sk-prod-SECRET"}, lab_keys={"anthropic": "sk-lab-SECRET"})).as_json())
    assert "SECRET" not in text and "sk-" not in text


def test_a_window_without_the_owners_actions_is_pending_and_not_a_verdict(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, lab_call=False)
    report = evaluate(db)
    assert report.verdict == gate_a.PENDING_ACTIONS == "PENDIENTE POR ACCIONES MANUALES" and not report.recordable
    assert report.preview["failing_now"] == [] and any("acciones 3, 5 y 7" in p for p in report.pending)
    assert gate_a.record(db, report) is None
    assert db.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'gate_a'").fetchone() == (0,)


def test_what_fails_while_an_action_is_pending_is_shown_but_does_not_decide(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, lab_call=False, unit=D("0.65"))
    report = evaluate(db)
    assert report.verdict == gate_a.PENDING_ACTIONS and report.consequence is None
    assert set(report.preview["failing_now"]) == {"cost_production", "cost_joint", "cost_heavy"}
    assert "NOT a verdict" in report.preview["note"]


def test_no_plan_for_a_day_of_the_window_fails_the_gate(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    stand_in = replace(gate_a.window_of(db, at=NOW), first=date(2032, 9, 12), last=date(2032, 9, 18))
    assert gate_a.check_plans(db, stand_in).ok is True
    gone = replace(stand_in, first=date(2032, 9, 20), last=date(2032, 9, 26))
    check = gate_a.check_plans(db, gone)
    assert check.ok is False and check.detail["days_with_plan"] == 0


# ── rolling an optimisation back ──────────────────────────────────────────────────────────────────────────────────

def test_reverting_an_optimisation_writes_a_row_that_switches_it_off_and_moves_the_window(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    assert gates.describe(db, settings())["native_schema"]["on"] is True
    row = gate_a.revert(db, "native_schema", reason="changed 4 more verdicts than repeating", at=NOW, code_version="test")
    state = gates.gate_state(db, "native_schema")
    assert not state.passed and state.at == NOW
    assert gates.describe(db, settings())["native_schema"]["on"] is False
    evidence = db.execute("SELECT evidence FROM ai.feature_gates WHERE id = %s", (row,)).fetchone()
    assert evidence is not None and evidence[0]["reverted_by"] == "scripts.ia_gate" and evidence[0]["previous"]["passed"] is True
    assert ("native_schema off") in [why for _, why in gate_a.flips(db)]
    for bad in ("gate_a", "cache", "bogus"):
        with pytest.raises(ValueError, match="can be reverted this way"):
            gate_a.revert(db, bad, reason="x", at=NOW)


# ── the command ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_command_answers_with_an_exit_status_and_records_only_on_request(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_gate

    build(db, seed)
    conn: Any = Savepoints(db)
    doc, code = ia_gate.run("evaluate", conn, settings(), at=NOW, baseline=BASE)
    assert code == ia_gate.OK and doc["verdict"] == "PASA" and "recorded_row" not in doc
    assert doc["lines"][0] == "GATE A · PASA"
    assert db.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'gate_a'").fetchone() == (0,)
    doc, code = ia_gate.run("evaluate", conn, settings(), at=NOW, record=True, version="test", baseline=BASE)
    assert code == ia_gate.OK and isinstance(doc["recorded_row"], int)
    assert gates.gate_state(db, "gate_a").passed
    doc, code = ia_gate.run("evaluate", conn, settings(monthly_budget=D(190)), at=NOW, record=True, baseline=BASE)
    assert code == ia_gate.PENDING and doc["verdict"] == "PENDIENTE POR ACCIONES MANUALES" and doc["recorded_row"] is None
    assert "nothing was written" in doc["recorded_note"]
    doc, code = ia_gate.run("evaluate", conn, settings(), at=noon(date(2032, 9, 15)), baseline=BASE)
    assert code == ia_gate.PENDING and doc["verdict"] == "PENDIENTE POR TIEMPO REAL"


def test_the_command_exits_one_when_the_gate_says_no(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_gate

    build(db, seed, unit=D("0.65"))
    conn: Any = Savepoints(db)
    doc, code = ia_gate.run("evaluate", conn, settings(), at=NOW, baseline=BASE)
    assert code == ia_gate.NO and doc["verdict"] == "NO PASA" and doc["consequence"]


def test_the_command_refuses_what_it_should(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import ia_gate

    conn: Any = Savepoints(db)
    doc, code = ia_gate.run("evaluate", conn, settings(), at=NOW, through=date(2032, 9, 19), record=True)
    assert code == ia_gate.CANNOT and "not recorded" in doc["error"]
    doc, code = ia_gate.run("evaluate", conn, settings(), at=NOW, through=date(2032, 9, 20))
    assert code == ia_gate.CANNOT and "not a complete day yet" in doc["error"]
    assert ia_gate.run("revert", conn, settings(), at=NOW, gate="batch")[1] == ia_gate.CANNOT, "a reason is needed"
    assert ia_gate.run("revert", conn, settings(), at=NOW, reason="x")[1] == ia_gate.CANNOT, "and an optimisation"
    doc, code = ia_gate.run("revert", conn, settings(), at=NOW, gate="batch", reason="  expired 3 %  ", version="test")
    assert code == ia_gate.OK and doc["reverted"] == "batch" and doc["reason"] == "expired 3 %"
    assert not gates.gate_state(db, "batch").passed
    with pytest.raises(SystemExit):
        ia_gate.main(["evaluate", "--through", "yesterday"])
    assert "not a day" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        ia_gate.main(["revert", "gate_a"])
