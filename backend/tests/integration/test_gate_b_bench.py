"""Gate B (``fbi.ai.gate_b``, ``scripts/ia_gate_b.py``) and the agent evaluation bench (``fbi.ai.eval_bench``, ``scripts/ia_eval_bench.py``) on a
built world, end to end against the schema the migrations build.

The world is September 2032: the shadow's first run on the 15th; every day of the 16th-29th four finished matches, each with a final pass of the
shadow written 30 minutes before its kick-off and two answered runs (the Match Agent and the Council) with their tasks; the nightly audit clean;
the battery green over the corpus in force with targets for both agents; research v2 passed; the LAB well inside its envelope; every match
attributed. Today is the 30th at noon in Bogotá, so the window is the 16th to the 29th. Each test spoils ONE thing and says what the gate answers.

The figures are written by hand into a transaction that is rolled back, and the code only reads them: a test of the arithmetic, not evidence of
anything. The real gate runs on the real shadow, over fourteen complete real days."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from scripts import ia_eval_bench, ia_gate_b

from fbi.ai import eval_bench, gate_b, gates
from fbi.ai.battery import TARGETS, corpus
from fbi.ai.battery import VERSION as BATTERY_VERSION
from fbi.ai.config import AiSettings

from .conftest import Seed
from .test_ai_decision_layer import Savepoints

D = Decimal
NOW = datetime(2032, 9, 30, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá
FIRST, LAST = date(2032, 9, 16), date(2032, 9, 29)
SHADOW_FROM = date(2032, 9, 15)
PER_DAY = 4
AGENTS = (("match", "match-v2", "match-assess-v2", "evaluation"), ("council", "council-v1", "council-v1", "council"))
_n = [0]


def key() -> str:
    _n[0] += 1
    return f"{_n[0] + 7_000_000:064x}"


def at_noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 17, 0, tzinfo=UTC)


def days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def fixture(db: psycopg.Connection[Any], seed: Seed, kickoff: datetime) -> int:
    _n[0] += 1
    row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                     "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                     (8_800_000 + _n[0], seed.season_id, seed.home_team_id, seed.away_team_id, kickoff)).fetchone()
    assert row is not None
    return int(row[0])


def run(db: psycopg.Connection[Any], fixture_id: int, agent: tuple[str, str, str, str], *, started: datetime, deadline: datetime,
        status: str = "ok", pass_kind: str = "final", idem: str | None = None, input_hash: str | None = None,
        output: dict[str, Any] | None = None, with_task: bool = True, attempts: int = 1, attempt: int = 1) -> int:
    name, version, prompt, task_kind = agent
    k = idem or key()
    paid = status in ("ok", "invalid", "abstain")
    answer = status in ("ok", "abstain")
    row = db.execute(
        "INSERT INTO ai.agent_runs (run_kind, reason, task_kind, pass_kind, fixture_id, started_at, finished_at, known_at, model, agent, "
        "agent_version, prompt_version, schema_version, router_version, idem_key, attempt, output, verdict, input_tokens, output_tokens, "
        "cached_tokens, cache_write_tokens, cost_usd, latency_ms, status, error) "
        "VALUES ('shadow', 'shadow pass', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'cd-v1', 'router-v1', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "RETURNING id",
        (task_kind, pass_kind, fixture_id, started, started + timedelta(seconds=40), started - timedelta(minutes=5),
         "claude-haiku-5-5" if paid else None, name, version, prompt, k, attempt, Jsonb(output or {"v": 1}) if answer else None,
         "APPROVE" if answer else None, 1000 if paid else None, 200 if paid else None, 600 if paid else None, 0 if paid else None,
         D("0.002") if paid else D(0), 4000 if paid else None, status, None if answer else "bad_ref: c9 is not a candidate")).fetchone()
    assert row is not None
    run_id = int(row[0])
    if with_task:
        db.execute(
            "INSERT INTO ai.agent_tasks (idem_key, custom_id, workspace, agent, agent_version, prompt_version, schema_version, model, effort, "
            "input_version, input_hash, pass_kind, fixture_id, run_kind, task_kind, reason, router_version, priority, est_cost_usd, state, "
            "created_at, not_before, deadline_at, queued_at, started_at, finished_at, attempts, last_run_id) "
            "VALUES (%s, %s, 'lab', %s, %s, %s, 'cd-v1', 'claude-haiku-5-5', 'low', 'mcp-v1', %s, %s, %s, 'shadow', %s, 'shadow pass', "
            "'router-v1', 100, 0.002, 'done', %s, %s, %s, %s, %s, %s, %s, %s)",
            (k, k[:48], name, version, prompt, input_hash or k, pass_kind, fixture_id, task_kind, started, started, deadline, started, started,
             started + timedelta(seconds=40), attempts, run_id))
    return run_id


def pass_row(db: psycopg.Connection[Any], fixture_id: int, written: datetime, pass_kind: str = "final") -> None:
    db.execute("INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version) "
               "VALUES (%s, 'shadow', %s, %s, %s, 'ms-v1')", (fixture_id, pass_kind, written - timedelta(minutes=5), written))


def attribute(db: psycopg.Connection[Any], fixture_id: int, agent: str, version: str, signal: str, outcome: str) -> None:
    db.execute("INSERT INTO intel.agent_attributions (attribution_version, classified_by, fixture_id, market_key, selection, line, engine, agent, "
               "agent_version, signal, stance, outcome, error_class, settled, review_id, postmortem_id, source, computed_at) "
               "VALUES ('attr-v1', 'code', %s, '1X2', %s, 0, 'ma-v1', %s, %s, %s, 'APPROVE', %s, %s, 'win', 1, 1, 'live', %s)",
               (fixture_id, f"Home-{signal}", agent, version, signal, outcome, "UNKNOWN" if outcome == "MISS" else "NONE", NOW))


def gate_row(db: psycopg.Connection[Any], gate: str, at: datetime, passed: bool, evidence: dict[str, Any]) -> None:
    db.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) VALUES (%s, %s, %s, %s, %s, 'script')",
               (gate, at, passed, Jsonb(evidence), "c" * 64))


def battery_evidence(targets: tuple[str, ...] = ("match", "stats", "council")) -> dict[str, Any]:
    """The evidence of a battery measured over the corpus IN FORCE (its own hashes), with the agents' targets beside the corpus's."""
    agent_targets = {t for t in TARGETS if corpus.target(t).agent}  # battery-v3: the agents' own targets (match, stats, council)
    measured: dict[str, Any] = {t: {"prompt": corpus.target(t).prompt, "agent": corpus.target(t).agent or None,
                                    "prompts": list(corpus.target(t).every_prompt), "requests_hash": corpus.requests_hash(t, native=False)}
                                for t in TARGETS if t not in agent_targets or t in targets}
    measured |= {t: {"prompt": f"{t}-prompt"} for t in targets if t not in TARGETS}
    return {"battery": BATTERY_VERSION, "native": False, "corpus_hash": corpus.corpus_hash(), "targets": measured}


def build(db: psycopg.Connection[Any], seed: Seed) -> list[int]:
    gate_row(db, "switches", at_noon(SHADOW_FROM) - timedelta(days=1), True,
             {"kind": "switch-words-v1", "words": {"mode": "shadow", "budgets_usd": {"production": "185", "lab": "55", "exa": "35"}}})
    fixtures: list[int] = []
    for d in [SHADOW_FROM, *days(FIRST, LAST)]:
        db.execute("INSERT INTO ai.cycles (kind, started_at, finished_at, status, mode, budget_state, counts) "
                   "VALUES ('orchestrate', %s, %s, 'ok', 'shadow', 'NORMAL', %s)",
                   (at_noon(d), at_noon(d) + timedelta(minutes=1), Jsonb({"too_late": 0, "paused": [], "budget_stop": None})))
        db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, workspace) "
                   "VALUES (%s, 'other', 'analysis', 'anthropic', 'claude-haiku-5-5', 1.20, 'ok', 'PREDIGOL-LAB')", (at_noon(d),))
        for rule in gate_b.AUDIT_RULES:
            db.execute("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations) VALUES (%s, %s, 'leak-audit-v8', %s, %s, 0)",
                       (d, at_noon(d) + timedelta(days=1), rule, 6))
        for k in range(PER_DAY):
            kickoff = at_noon(d) + timedelta(hours=3, minutes=10 * k)
            fid = fixture(db, seed, kickoff)
            fixtures.append(fid)
            pass_row(db, fid, kickoff - timedelta(minutes=30))
            for agent in AGENTS:
                run(db, fid, agent, started=kickoff - timedelta(minutes=50), deadline=kickoff - timedelta(minutes=15))
                attribute(db, fid, agent[0], agent[1], "VERDICT", "HIT")
            attribute(db, fid, "match", "match-v2", "FORM", "HIT" if k % 2 == 0 else "MISS")
            db.execute("INSERT INTO ai.shadow_assignments (experiment, fixture_id, bucket, sampled, council_solo, share, assigned_at) "
                       "VALUES ('arms-v1', %s, 10, true, false, 0.3, %s)", (fid, kickoff - timedelta(hours=6)))
    gate_row(db, "battery", at_noon(date(2032, 9, 20)), True, battery_evidence())
    gate_row(db, "research_v2", at_noon(date(2032, 9, 22)), True,
             {"checks": [{"id": "coverage", "detail": {"coverage_pct": "97.10"}}]})
    return fixtures


def plan(db: psycopg.Connection[Any], days: int, *, at: datetime | None = None, reason: str = "the plan") -> int:
    """The owner's plan of the LAB, as ``set-lab-plan --confirm-owner`` writes it (by default before the shadow's first run)."""
    when = at_noon(SHADOW_FROM) - timedelta(hours=2) if at is None else at
    return gate_b.record_lab_plan(db, days=days, reason=reason, at=when, confirmed_by_owner=True, code_version="test")


def gate_b_rows(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT passed, decided_by, evidence, evidence_hash, code_version FROM ai.feature_gates WHERE gate = 'gate_b' "
                      "ORDER BY id").fetchall()


def evaluate(db: psycopg.Connection[Any], **kw: Any) -> gate_b.GateReport:
    return gate_b.evaluate(db, AiSettings(lab_monthly_budget=D(55)), at=NOW, **kw)


def by_id(report: gate_b.GateReport) -> dict[str, gate_b.Check]:
    return {c.id: c for c in report.checks}


# ── Gate B ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_without_a_shadow_run_there_is_nothing_to_measure(db: psycopg.Connection[Any]) -> None:
    report = evaluate(db)
    assert report.verdict == gate_b.PENDING_TIME and report.window.anchor is None and not report.checks


def test_a_healthy_fortnight_waits_only_for_the_owners_planned_days_and_passes_when_they_are_known(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    report = evaluate(db)
    verdicts = {i: c.verdict for i, c in by_id(report).items()}
    assert report.window.complete and (report.window.first, report.window.last) == (FIRST, LAST)
    assert verdicts.pop("lab_envelope") == gate_b.PENDING_ACTIONS
    assert verdicts.pop("invalid_outputs") == gate_b.PENDING_TIME  # 56 answers per agent: under the minimum of 100
    assert set(verdicts.values()) == {gate_b.PASS}, verdicts
    assert report.verdict == gate_b.PENDING_ACTIONS and not report.preview
    c = by_id(report)
    assert c["final_deadline"].detail["final_passes"] == 14 * PER_DAY and c["final_deadline"].detail["late_calls"] == 0
    assert {a["agent"]: a["n"] for a in c["invalid_outputs"].detail["agents"]} == {"match": 56, "council": 56}
    assert c["lab_envelope"].detail["envelope_source"] == "the ledger of the owner's words"
    assert c["lab_envelope"].detail["months"][0]["spent_usd"] == "18.00"  # the 15th and the fourteen days, 1.20 each
    assert c["attribution"].detail["rate_pct"] == "100.00"
    assert c["research_v2"].detail["row"]["coverage_pct"] == "97.10"
    plan(db, 0)
    assert evaluate(db).verdict == gate_b.PENDING_TIME  # 56 answers per agent: under the minimum of 100


def test_with_enough_answers_and_the_planned_days_known_the_gate_passes(db: psycopg.Connection[Any], seed: Seed, monkeypatch: Any) -> None:
    build(db, seed)
    monkeypatch.setattr(gate_b, "MIN_RUNS_PER_AGENT", 50)
    doc, code = ia_gate_b.run(db, AiSettings(lab_monthly_budget=D(55)), at=NOW)
    assert code == ia_gate_b.PENDING and "recorded_row" not in doc  # no plan of the owner yet: pending by manual action
    plan(db, 0)
    report = evaluate(db)
    assert report.verdict == gate_b.PASS, [(c.id, c.verdict, c.reasons) for c in report.checks]
    doc, code = ia_gate_b.run(db, AiSettings(lab_monthly_budget=D(55)), at=NOW)
    assert code == ia_gate_b.OK and doc["verdict"] == gate_b.PASS and "recorded_row" not in doc and gate_b_rows(db) == [], "asking is not recording"


def test_a_final_pass_written_after_t_minus_15_fails(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    late = fixture(db, seed, at_noon(date(2032, 9, 25)) + timedelta(hours=5))
    pass_row(db, late, at_noon(date(2032, 9, 25)) + timedelta(hours=4, minutes=50))
    c = by_id(evaluate(db))["final_deadline"]
    assert c.verdict == gate_b.FAIL and c.detail["late_passes"] == 1


def test_a_call_started_after_its_deadline_fails(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    kickoff = at_noon(date(2032, 9, 25)) + timedelta(hours=5)
    fid = fixture(db, seed, kickoff)
    started = kickoff - timedelta(minutes=10)
    run(db, fid, AGENTS[0], started=started, deadline=started)  # the store raises the deadline of a late start to the start itself
    c = by_id(evaluate(db))["final_deadline"]
    assert c.verdict == gate_b.FAIL and c.detail["late_calls"] == 1


def test_invalid_outputs_over_three_percent_fail_by_agent_and_version(db: psycopg.Connection[Any], seed: Seed) -> None:
    fixtures = build(db, seed)
    for fid in fixtures[:3]:
        run(db, fid, AGENTS[1], started=at_noon(date(2032, 9, 20)), deadline=at_noon(date(2032, 9, 21)), status="invalid", pass_kind="pre")
    c = by_id(evaluate(db))["invalid_outputs"]
    council = next(a for a in c.detail["agents"] if a["agent"] == "council")
    assert c.verdict == gate_b.FAIL and council["invalid"] == 3 and council["invalid_by_code"] == {"bad_ref": 3}


def test_a_duplicate_payment_is_counted_even_when_the_index_that_forbids_it_is_gone(db: psycopg.Connection[Any], seed: Seed) -> None:
    fixtures = build(db, seed)
    db.execute("DROP INDEX ai.ai_agent_runs_paid_once")  # rolled back with the test
    k = key()
    run(db, fixtures[0], AGENTS[0], started=at_noon(date(2032, 9, 20)), deadline=at_noon(date(2032, 9, 21)), idem=k, pass_kind="first")
    run(db, fixtures[0], AGENTS[0], started=at_noon(date(2032, 9, 20)) + timedelta(minutes=1), deadline=at_noon(date(2032, 9, 21)), idem=k,
        pass_kind="first", with_task=False, attempt=2)
    c = by_id(evaluate(db))["duplicate_payments"]
    assert c.verdict == gate_b.FAIL and c.detail["keys_paid_twice"] == 1


def test_a_lab_month_over_its_envelope_fails(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, workspace) "
               "VALUES (%s, 'other', 'analysis', 'anthropic', 'claude-sonnet-5-5', 40, 'ok', 'PREDIGOL-LAB')", (at_noon(date(2032, 9, 26)),))
    assert by_id(evaluate(db))["lab_envelope"].verdict == gate_b.FAIL


def test_a_violation_of_the_audit_on_one_night_fails(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    db.execute("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations) "
               "VALUES ('2032-09-20', %s, 'leak-audit-v8', 'agent_known', 6, 1)", (NOW,))
    assert by_id(evaluate(db))["leak_audit"].verdict == gate_b.FAIL


def test_a_battery_without_a_target_for_an_agent_that_ran_fails_by_name(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    gate_row(db, "battery", at_noon(date(2032, 9, 21)), True, battery_evidence(("match",)))
    c = by_id(evaluate(db))["battery"]
    assert c.verdict == gate_b.FAIL and "battery does not cover council" in c.reasons


def test_a_new_version_inside_the_window_restarts_the_clock(db: psycopg.Connection[Any], seed: Seed) -> None:
    fixtures = build(db, seed)
    run(db, fixtures[-1], ("match", "match-v3", "match-assess-v3", "evaluation"), started=at_noon(date(2032, 9, 24)),
        deadline=at_noon(date(2032, 9, 25)), pass_kind="pre")
    plan(db, 0)
    report = evaluate(db)
    assert report.verdict == gate_b.PENDING_TIME and report.preview and report.window.anchor == date(2032, 9, 25)


# ── recording Gate B and the owner's plan of the LAB (migration 0127) ──────────────────────────────────────────────

def test_the_newest_plan_the_owner_wrote_by_the_evaluation_is_the_one_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    assert gate_b.lab_plan(db, NOW) is None
    first = plan(db, 1, reason="one day of the qualifiers")
    newest = plan(db, 3, at=at_noon(SHADOW_FROM) - timedelta(hours=1), reason="  three days: the qualifiers and the cup  ")
    plan(db, 9, at=NOW + timedelta(hours=1), reason="written after the evaluation")  # the future does not speak for the past
    db.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) VALUES ('lab_plan', %s, true, %s, %s, 'script')",
               (NOW - timedelta(minutes=1), Jsonb({"kind": "lab-plan-v1", "planned_excluded_days": 14}), "d" * 64))  # not the owner's: ignored
    read = gate_b.lab_plan(db, NOW)
    assert read is not None and (read.row, read.days, read.reason) == (newest, 3, "three days: the qualifiers and the cup") and read.row != first
    row = db.execute("SELECT decided_by, passed, evidence, evidence_hash, code_version FROM ai.feature_gates WHERE id = %s", (newest,)).fetchone()
    assert row is not None and row[0] == "owner" and row[1] is True and row[4] == "test"
    assert row[2]["shadow_started_on"] == SHADOW_FROM.isoformat() and row[3] == gates.evidence_hash(row[2]) == read.evidence_hash
    c = by_id(evaluate(db))["lab_envelope"]
    assert c.detail["planned_excluded_days"] == 3 and c.detail["plan"]["row"] == newest and c.verdict == gate_b.PASS


def test_a_malformed_plan_is_never_guessed(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    db.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) VALUES ('lab_plan', %s, true, %s, %s, 'owner')",
               (NOW - timedelta(days=1), Jsonb({"kind": "lab-plan-v1", "planned_excluded_days": "two"}), "e" * 64))
    assert gate_b.lab_plan(db, NOW) is None
    assert by_id(evaluate(db))["lab_envelope"].verdict == gate_b.PENDING_ACTIONS


def test_more_excluded_days_than_the_owner_planned_fail(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    plan(db, 0)
    db.execute("UPDATE ai.cycles SET counts = %s WHERE kind = 'orchestrate' AND started_at = %s",
               (Jsonb({"too_late": 0, "paused": [], "budget_stop": "lab_yielded"}), at_noon(date(2032, 9, 24))))
    c = by_id(evaluate(db))["lab_envelope"]
    assert c.verdict == gate_b.FAIL and c.detail["excluded_days"] == 1 and "more than the 0 planned" in c.reasons[0]


def test_record_appends_only_a_pass_or_a_failure_with_its_evidence_and_hash(db: psycopg.Connection[Any], seed: Seed, monkeypatch: Any) -> None:
    build(db, seed)
    conn: Any = Savepoints(db)
    settings = AiSettings(lab_monthly_budget=D(55))
    doc, code = ia_gate_b.run(conn, settings, at=NOW, record=True, version="test")  # no plan: PENDIENTE POR ACCIONES MANUALES
    assert code == ia_gate_b.PENDING and doc["recorded_row"] is None and "nothing was written" in doc["recorded_note"] and gate_b_rows(db) == []
    plan(db, 0)
    doc, code = ia_gate_b.run(conn, settings, at=NOW, record=True)  # under the minimum of answers: PENDIENTE POR TIEMPO REAL
    assert code == ia_gate_b.PENDING and doc["verdict"] == gate_b.PENDING_TIME and doc["recorded_row"] is None and gate_b_rows(db) == []
    monkeypatch.setattr(gate_b, "MIN_RUNS_PER_AGENT", 50)
    doc, code = ia_gate_b.run(conn, settings, at=NOW, record=True, version="test")
    assert code == ia_gate_b.OK and isinstance(doc["recorded_row"], int)
    [(passed, decided_by, evidence, digest, version)] = gate_b_rows(db)
    assert passed is True and decided_by == "script" and version == "test"
    assert evidence["verdict"] == gate_b.PASS and evidence["method"] == "gate-b-v1" and digest == gates.evidence_hash(evidence)
    assert gates.gate_state(db, "gate_b").passed is True
    kickoff = at_noon(date(2032, 9, 26)) + timedelta(hours=6)
    started = kickoff - timedelta(minutes=10)
    run(db, fixture(db, seed, kickoff), AGENTS[0], started=started, deadline=started)  # a call that started after T-15
    doc, code = ia_gate_b.run(conn, settings, at=NOW + timedelta(minutes=5), record=True, version="test")  # a call out of time: NO PASA
    assert code == ia_gate_b.NO and isinstance(doc["recorded_row"], int)
    assert [r[0] for r in gate_b_rows(db)] == [True, False] and gates.gate_state(db, "gate_b").passed is False, "the newest row decides"
    assert gates.gate_state(db, "lab_plan").passed is True and "gate_b" in gates.describe(db, settings)["gates"]
    assert "lab_plan" not in gates.describe(db, settings)["gates"], "the owner's plan is not a gate"


def test_record_refuses_a_window_looked_at_from_the_past(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    plan(db, 0)
    doc, code = ia_gate_b.run(Savepoints(db), AiSettings(lab_monthly_budget=D(55)), at=NOW, through=LAST, record=True)  # type: ignore[arg-type]
    assert code == ia_gate_b.CANNOT and "not recorded" in doc["error"] and gate_b_rows(db) == []


def test_set_lab_plan_is_the_owners_and_gate_b_reads_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    conn: Any = Savepoints(db)
    count = "SELECT count(*) FROM ai.feature_gates WHERE gate = 'lab_plan'"
    doc, code = ia_gate_b.set_lab_plan(conn, days=2, reason="qualifiers", confirm_owner=False, at=NOW)
    assert code == ia_gate_b.CANNOT and db.execute(count).fetchone() == (0,)
    for days, reason in ((2, None), (None, "x"), (-1, "x"), (gate_b.WINDOW_DAYS + 1, "x"), (2, "  ")):
        doc, code = ia_gate_b.set_lab_plan(conn, days=days, reason=reason, confirm_owner=True, at=NOW)
        assert code == ia_gate_b.CANNOT and "nothing was written" in doc["error"], (days, reason)
    assert db.execute(count).fetchone() == (0,)
    doc, code = ia_gate_b.set_lab_plan(conn, days=2, reason="qualifiers", confirm_owner=True, at=NOW - timedelta(days=20), version="test")
    assert code == ia_gate_b.OK and doc["plan"]["planned_excluded_days"] == 2 and doc["plan"]["decided_by"] == "owner"
    assert db.execute("SELECT decided_by FROM ai.feature_gates WHERE id = %s", (doc["recorded_row"],)).fetchone() == ("owner",)
    c = by_id(evaluate(db))["lab_envelope"]
    assert c.detail["planned_excluded_days"] == 2 and c.verdict == gate_b.PASS


# ── the bench ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_bench_measures_every_version_day_by_day_and_over_the_range(db: psycopg.Connection[Any], seed: Seed) -> None:
    fixtures = build(db, seed)
    day = date(2032, 9, 20)
    inside = fixtures[PER_DAY:]  # the matches of the 16th on: the 15th's are before the range
    run(db, inside[0], AGENTS[0], started=at_noon(day), deadline=at_noon(day) + timedelta(hours=1), status="invalid", pass_kind="pre")
    run(db, inside[0], AGENTS[0], started=at_noon(day), deadline=at_noon(day) + timedelta(hours=1), status="timeout", pass_kind="pre",
        attempts=3)
    same = "d" * 64
    for out in ({"v": 1}, {"v": 1}, {"v": 2}):  # one input asked three times: two repeats, one gave the same answer
        run(db, inside[1], AGENTS[1], started=at_noon(day), deadline=at_noon(day) + timedelta(hours=1), pass_kind="first",
            input_hash=same, output=out)
    rep = eval_bench.report(db, first=FIRST, last=LAST, at=NOW)
    match = next(a for a in rep.agents if a.agent == "match")
    council = next(a for a in rep.agents if a.agent == "council")
    t = match.totals
    assert (t.runs, t.by_status, t.retries) == (58, {"ok": 56, "invalid": 1, "timeout": 1}, 2)
    assert t.valid_first_attempt == D("0.9655")  # 56 valid of 58 first attempts that reached the model
    assert t.invalid_by_code == {"bad_ref": 1} and t.cost == D("0.114")
    assert eval_bench.percentile(t.latencies, 0.95) == 4000 and len(match.days) == 14
    assert match.coverage == (56, 56) and council.coverage == (56, 56)
    assert council.stability is not None and (council.stability.repeats, council.stability.same) == (2, 1)
    assert match.signals is not None and match.signals.useful == 28 and match.signals.precision == D("0.5000")
    assert match.signals.verdict_precision == D("1.0000")
    doc, code = ia_eval_bench.run(db, first=FIRST, last=LAST, at=NOW, agent="council")
    assert code == ia_eval_bench.OK and [a["agent"] for a in doc["agents"]] == ["council"] and "latency_ms" in doc["agents"][0]["totals"]
    assert ia_eval_bench.run(db, first=LAST, last=FIRST, at=NOW)[1] == ia_eval_bench.CANNOT
