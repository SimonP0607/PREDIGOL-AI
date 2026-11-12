"""The panel of the gates (IA-050, ``gates-panel-v1``): no pending gate is ever shown as approved; every entry and every figure has the same shape
and a source; the panel gives the evaluators' own verdicts; the frozen LAB verdicts are the reports' and carry their protocol's fingerprint; and a
value per dollar exists only where a benefit is demonstrated. The readers only read and the script refuses what it cannot measure."""

from __future__ import annotations

import ast
import functools
import itertools
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import cost_paths as cp
from fbi.ai import gate_a, gate_b, gate_research, gates
from fbi.ai import gates_panel as gp
from fbi.ai import gates_panel_readers as readers
from fbi.ai.gate_a import Check as RCheck
from fbi.ai.intervals import Z95
from fbi.research import protocol

BACKEND = Path(__file__).resolve().parents[2]
DOCS = BACKEND / "docs" / "owner"
NOW = datetime(2032, 9, 30, 17, 0, tzinfo=UTC)
TODAY = date(2032, 9, 30)
SINCE = datetime(2032, 9, 16, 5, 0, tzinfo=UTC)


# ── fake evaluators' reports, built with the evaluators' own pieces ──────────────────────────────────────────────


def b_checks(*, invalid: int = 0, attributed: int = 99, battery_passed: bool = True, audited: bool = True) -> list[gate_b.Check]:
    days = [date(2032, 9, 16) + timedelta(days=k) for k in range(14)]
    audit = [(d, r, "leak-audit-v8", 4 if r == "shadow_review_known" else 10, 0) for d in days for r in gate_b.AUDIT_RULES]
    battery = gate_b.BatteryRow(4, SINCE + timedelta(days=2), battery_passed,
                                {"battery": "battery-v3", "targets": {"match": {"prompt": "match-assess-v5"}, "council": {"prompt": "council-v1"}}})
    return [
        gate_b.judge_final(gate_b.FinalTimes(40, 0, 120, 0, 0, 2)),
        gate_b.judge_invalid([gate_b.AgentTally("match", "match-v5", {"ok": 300 - invalid, "invalid": invalid}, {"bad_ref": invalid} if invalid else {}),
                              gate_b.AgentTally("council", "council-v1", {"ok": 250, "invalid": 0}, {})]),
        gate_b.judge_duplicates(550, []),
        gate_b.judge_lab([gate_b.LabMonth(date(2032, 9, 1), date(2032, 9, 29), Decimal("12.5"), Decimal(55))], {}, planned=2, cycles=200,
                         envelope_source="the ledger of the owner's words"),
        gate_b.judge_attribution(100, attributed, []),
        gate_b.judge_audit(days, audit if audited else audit[4:]),
        gate_b.judge_battery(battery, since=SINCE, running={"match": ["match-assess-v5"], "council": ["council-v1"]}, stale=[]),
        gate_b.judge_research({"id": 9, "at": NOW, "passed": True, "evidence": {"checks": [{"id": "coverage", "detail": {"coverage_pct": "96.40"}}]}}),
    ]


def b_report(first_shadow: date, checks: list[gate_b.Check]) -> dict[str, Any]:
    w = gate_b.window_from(today=TODAY, through=None, first_shadow=first_shadow, events=[])
    pending = [f"{c.title}: {'; '.join(c.reasons)}" for c in checks if c.verdict in (gate_b.PENDING_TIME, gate_b.PENDING_ACTIONS)]
    return gate_b.GateReport(gate_b.verdict_of(w, checks), NOW, w, tuple(checks), tuple(pending), preview=not w.complete).as_json()


def r_report(*, coverage_found: int = 97, complete: bool = True) -> dict[str, Any]:
    w = gate_research.Window(date(2032, 9, 23), date(2032, 9, 29), date(2032, 9, 23) if complete else date(2032, 9, 27), "x",
                             7 if complete else 3, date(2032, 9, 30) if complete else date(2032, 10, 4))
    if not complete:
        return gate_research.GateReport(gate_research.PENDING_TIME, NOW, w, pending=("3 de 7 días",), preview={"note": "NOT evidence"}).as_json()
    v1 = frozenset((k, "home", f"p{k}", "out") for k in range(100))
    v2 = frozenset(list(v1)[:coverage_found])
    cov = gate_research.Coverage(40, v1, v2)
    s = gate_research.Searches(passes=50, compared=50)
    s.totals.update({"web_searches": 120, "v2_paid": 80, "v2_shared": 10})
    checks = (RCheck("window", "7 días", True, w.as_json()), gate_research.check_searches(s), gate_research.check_coverage(cov),
              gate_research.check_players(cov), RCheck("shadow_invisible", "invisible", True, {"reviews_citing": 0, "decisions_citing": 0}),
              RCheck("evidence_known", "audit", True, {"days_audited": 7}), gate_research.check_sample(cov))
    failed = [c for c in checks if c.ok is False]
    verdict = gate_research.FAIL if failed else gate_research.PASS
    return gate_research.GateReport(verdict, NOW, w, checks).as_json()


@functools.cache
def b_case(case: str) -> dict[str, Any]:
    """Gate B's report in four situations, built once: the window not complete, a check that fails, all checks green, a night not audited."""
    return {"incomplete": lambda: b_report(date(2032, 9, 20), b_checks()), "fails": lambda: b_report(date(2032, 9, 1), b_checks(invalid=20)),
            "passes": lambda: b_report(date(2032, 9, 1), b_checks()),
            "manual": lambda: b_report(date(2032, 9, 1), b_checks(audited=False))}[case]()


@functools.cache
def r_case(case: str) -> dict[str, Any]:
    return {"incomplete": lambda: r_report(complete=False), "passes": r_report, "fails": lambda: r_report(coverage_found=80)}[case]()


def row(gate: str, passed: bool, **kw: Any) -> gp.Row:
    return gp.Row(kw.pop("id", 7), gate, kw.pop("at", NOW - timedelta(days=1)), passed, "script", "ab" * 32, **kw)


def shadow(engine: str, verdict: str, *, selections: int = 2223, rejected: int = 814, diff: str = "-0.0748", se: str = "0.094",
           z: float = -0.796, days: int = 34) -> dict[str, Any]:
    return {"id": 120, "engine": engine, "created_at": NOW, "window_from": date(2032, 8, 1), "window_to": TODAY, "version": "ai-gate-v2",
            "verdict": verdict, "selections": selections, "days": days, "rejected": rejected, "diff": diff, "se": se, "z": str(z),
            "clv_kept": "-0.0286", "clv_rejected": "-0.047", "roi_kept": "0.01", "roi_rejected": "0.02"}


_ids = itertools.count(1)


def call(prompt: str | None, cost: str, *, purpose: str = "pick_review", tier: str = "analysis", fixture: int = 1) -> cp.Call:
    provider = "exa" if tier == "search" else "anthropic"
    return cp.Call(next(_ids), NOW - timedelta(hours=2), purpose, tier, provider, "claude-sonnet-5-5", prompt, "ok", Decimal(cost), fixture,
                   NOW + timedelta(hours=6))


def cost_report() -> dict[str, Any]:
    calls = [call("review-v2", "0.040000"), call("review-v2", "0.044000", fixture=2), call("brief-v8", "0.007000", purpose="match_brief"),
             call("council-v1", "0.011000"), call("match-assess-v5", "0.001600"), call(None, "0.015000", purpose="web_search", tier="search"),
             call("extract-v3", "0.000800", purpose="evidence_extraction"), call("learning-v2", "0.030000", purpose="learning"),
             call("pmr-v1", "0.002000", purpose="postmortem"), call("battery-v3", "0.010000", purpose="other"),
             call("something-v1", "0.001000", purpose="other")]
    links = [cp.Link(calls[0].id, "llm", 1, "1X2", "Home", Decimal(0)), cp.Link(calls[1].id, "llm", 2, "OU", "Over", Decimal("2.5")),
             cp.Link(calls[3].id, "ma-v1", 1, "1X2", "Home", Decimal(0))]
    total = sum((c.cost for c in calls), Decimal(0))
    return cp.report(calls, links, ledger=cp.Ledger(len(calls), total), user_ledger=[{"prompt_version": "user-narrative-v3",
                                                                                       "model": "claude-haiku-5-5", "calls": 3, "usd": "0.0060"}],
                     since=NOW - timedelta(days=14), until=NOW)


def inputs(**kw: Any) -> gp.PanelInputs:
    base: dict[str, Any] = {"at": NOW, "rows": {}, "shadow_reports": [shadow("combined", "fail"), shadow("llm", "fail"),
                                                                       shadow("ma-v1", "insufficient", selections=273, rejected=28, days=7)],
                            "p1": gp.P1Counts(date(2032, 9, 20), "match match-v5 first ran, 2032-09-19", TODAY,
                                              (("ma-v1", "1X2", 40, 12), ("ma-v1", "CORNERS_OU", 9, 2))),
                            "cost": cost_report(), "cost_days": 14.0}
    return gp.PanelInputs(**(base | kw))


def by_id(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in doc["gates"]}


# ── the words ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_words_are_the_gates_own() -> None:
    assert (gp.PASS, gp.FAIL, gp.PENDING_TIME, gp.PENDING_ACTIONS) == (gate_b.PASS, gate_b.FAIL, gate_b.PENDING_TIME, gate_b.PENDING_ACTIONS)
    assert (gp.PASS, gp.FAIL, gp.PENDING_TIME) == (gate_research.PASS, gate_research.FAIL, gate_research.PENDING_TIME)
    assert (gp.PASS, gp.FAIL, gp.PENDING_ACTIONS) == (gate_a.PASS, gate_a.FAIL, gate_a.PENDING_ACTIONS)
    e4 = json.loads((DOCS / "lab" / "IA_039" / "resultado_e4.json").read_text(encoding="utf-8"))
    assert set(e4["veredicto"]["por_celda"].values()) == {gp.REJECTS, gp.PENDING_SAMPLE}
    assert frozenset(gates.NOT_GATES) == gp.NOT_GATES
    assert frozenset(gp.STATUSES) - {gp.PASS, gp.FAIL, gp.REJECTS} == gp.PENDING


# ── the rule: no pending gate is shown as approved ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("recorded", [None, True, False])
@pytest.mark.parametrize("verdict", [None, gp.PASS, gp.FAIL, gp.PENDING_TIME, gp.PENDING_ACTIONS, "UNKNOWN WORD"])
@pytest.mark.parametrize("error", [None, "OperationalError: canceling statement due to statement timeout"])
def test_a_live_gate_is_pasa_only_with_a_passing_row_on_file(recorded: bool | None, verdict: str | None, error: str | None) -> None:
    status, why = gp.live_status(verdict, None if recorded is None else row("gate_b", recorded), error=error)
    assert status in gp.STATUSES and why
    assert (status == gp.PASS) == (recorded is True)
    if recorded is not None:
        assert status == (gp.PASS if recorded else gp.FAIL), "the recorded row is what the system acts on"
    elif error is None and verdict == gp.PASS:
        assert status == gp.PENDING_ACTIONS and "no está registrado" in why[0]
    elif error is None and verdict in (gp.FAIL, gp.PENDING_TIME, gp.PENDING_ACTIONS):
        assert status == verdict, "otherwise the panel says what the evaluator says"


SCENARIOS = list(itertools.product(
    [None, "pass", "fail"],                             # the newest gate_b row
    ["incomplete", "fails", "passes", "manual"],        # what Gate B's evaluator sees
    [None, "pass", "fail"],                             # the newest research_v2 row
    ["incomplete", "passes", "fails"],                  # what research's evaluator sees
    ["pass", "fail", "insufficient"],                   # combined's ai-gate-v2
))


@pytest.mark.parametrize(("b_row", "b_situation", "r_row", "r_situation", "combined"), SCENARIOS)
def test_no_pending_gate_is_ever_shown_as_approved(b_row: str | None, b_situation: str, r_row: str | None, r_situation: str,
                                                   combined: str) -> None:
    b, r = b_case(b_situation), r_case(r_situation)
    rows = {g: row(g, w == "pass") for g, w in (("gate_b", b_row), ("research_v2", r_row), ("gate_a", "pass")) if w is not None}
    doc = gp.panel(inputs(rows=rows, gate_b=b, research=r, shadow_reports=[shadow("combined", combined)]))
    assert doc["violations"] == [] and doc["rule_holds"] is True
    for e in doc["gates"]:
        assert e["status"] in gp.STATUSES
        assert e["approved"] == (e["status"] == gp.PASS)
        if e["status"] == gp.PASS:
            assert gp.on_file_pass(e), e["id"]
        if e["kind"] in ("dependencias", "muestra"):
            assert e["status"] in gp.PENDING, e["id"]
    entries = by_id(doc)
    assert (entries["gate_b"]["status"] == gp.PASS) == (b_row == "pass")
    assert (entries["research_v2"]["status"] == gp.PASS) == (r_row == "pass")
    assert (entries["ai_gate_v2"]["status"] == gp.PASS) == (combined == "pass")
    assert entries["gate_b"]["evaluator"]["verdict"] == b["verdict"] and entries["research_v2"]["evaluator"]["verdict"] == r["verdict"]


def test_the_checker_catches_a_panel_that_breaks_the_rule() -> None:
    doc = gp.panel(inputs(gate_b=b_case("incomplete")))
    assert gp.violations(doc) == []
    for gate in ("gate_b", "p1", "g_delib", "g_eventos"):
        broken = json.loads(json.dumps(doc, default=str))
        e = by_id(broken)[gate]
        e["status"], e["approved"] = gp.PASS, True
        assert any(gate in v for v in gp.violations(broken)), gate
    broken = json.loads(json.dumps(doc, default=str))
    by_id(broken)["g_e4"]["approved"] = True
    assert any("approved=True" in v for v in gp.violations(broken))
    by_id(broken)["g_e4"]["status"] = "APROBADO"
    assert any("unknown status" in v for v in gp.violations(broken))
    with pytest.raises(ValueError, match="not a status"):
        gp.entry(gp.SPEC["g_cron"], "APROBADO", [])


# ── the panel gives the evaluators' verdicts ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("first_shadow", "checks", "want"), [
    (date(2032, 9, 20), b_checks(), gp.PENDING_TIME),
    (date(2032, 9, 1), b_checks(invalid=20), gp.FAIL),
    (date(2032, 9, 1), b_checks(audited=False), gp.PENDING_ACTIONS),
    (date(2032, 9, 1), b_checks(attributed=80), gp.FAIL),
    (date(2032, 9, 1), b_checks(), gp.PASS),
])
def test_gate_b_in_the_panel_is_what_its_evaluator_says(first_shadow: date, checks: list[gate_b.Check], want: str) -> None:
    report = b_report(first_shadow, checks)
    assert report["verdict"] == want
    e = gp.gate_b_entry(report, None)
    assert e["evaluator"]["verdict"] == want and e["evaluator"]["module"] == "fbi.ai.gate_b"
    assert e["status"] == (gp.PENDING_ACTIONS if want == gp.PASS else want)
    assert [c["verdict"] for c in e["checks"]] == [c.verdict for c in checks]
    assert e["failing_now"] == report["failing_now"] and e["evaluable_on"] == report["window"]["eligible_on"]
    invalid = next(c for c in e["checks"] if c["id"] == "invalid_outputs")
    assert {f["label"] for f in invalid["figures"]} == {"inválidas de match match-v5", "inválidas de council council-v1"}
    match = next(f for f in invalid["figures"] if "match" in f["label"])
    reported = next(c for c in report["checks"] if c["id"] == "invalid_outputs")["detail"]["agents"]
    expected = next(a for a in reported if a["agent"] == "match")["interval"]
    assert (match["counted"], match["cases"], match["value"]) == (expected["counted"], expected["cases"], f"{expected['pct']} %")
    assert match["ci95"] == expected["ci95_wilson_pct"] and match["threshold"] == "≤ 3.0 %"
    assert match["interval_vs_threshold"] == expected["interval_vs_threshold"]
    assert match["verdict"] is None and "sin veredicto propio" in match["note"], "a version's row is not judged alone: the check is"
    assert invalid["verdict"] == checks[1].verdict
    if want == gp.PASS:
        assert gp.gate_b_entry(report, row("gate_b", True))["status"] == gp.PASS


@pytest.mark.parametrize(("case", "want"), [("incomplete", gp.PENDING_TIME), ("passes", gp.PASS), ("fails", gp.FAIL)])
def test_research_v2_in_the_panel_is_what_its_evaluator_says(case: str, want: str) -> None:
    report = r_case(case)
    e = gp.research_entry(report, None)
    assert e["evaluator"]["verdict"] == want == report["verdict"]
    assert e["status"] == (gp.PENDING_ACTIONS if want == gp.PASS else want)
    assert [c["verdict"] for c in e["checks"]] == [gp.RESEARCH_WORDS[c["ok"]] for c in report["checks"]]
    if case != "incomplete":
        coverage = next(c for c in e["checks"] if c["id"] == "coverage")["figures"][0]
        found = 97 if case == "passes" else 80
        assert (coverage["counted"], coverage["cases"], coverage["threshold"]) == (found, 100, "≥ 95.0 %")
        assert e["failing_now"] == ([] if case == "passes" else ["coverage", "coverage_players"])
    assert gp.research_entry(report, row("research_v2", False))["status"] == gp.FAIL


def test_an_evaluator_that_could_not_run_is_pending_by_manual_action_and_says_why() -> None:
    doc = gp.panel(inputs(gate_b=None, gate_b_error="OperationalError: timeout", research=None, research_error="ValueError: x"))
    e = by_id(doc)
    assert e["gate_b"]["status"] == e["research_v2"]["status"] == gp.PENDING_ACTIONS
    assert "timeout" in e["gate_b"]["why"][0] and doc["rule_holds"]


def test_gate_a_is_its_recorded_verdict_and_the_ai_layer_gate_is_combineds_report() -> None:
    doc = gp.panel(inputs(rows={"gate_a": row("gate_a", True, window={"first": "2032-09-01", "last": "2032-09-07", "stable_complete_days": 7})}))
    e = by_id(doc)
    assert e["gate_a"]["status"] == gp.PASS and e["gate_a"]["recorded"]["passed"] is True and e["gate_a"]["figures"][0]["cases"] == 7
    assert e["ai_gate_v2"]["status"] == gp.FAIL and e["ai_gate_v2"]["recorded"]["table"] == "ai.shadow_reports"
    llm = next(f for f in e["ai_gate_v2"]["figures"] if f["label"].startswith("llm"))
    assert llm["value"] == "-0.0748" and llm["ci95"] == ["-0.2590", "0.1094"] and llm["cases"] == 2223 and llm["counted"] == 814
    assert by_id(gp.panel(inputs(rows={})))["gate_a"]["status"] == gp.PENDING_ACTIONS
    assert by_id(gp.panel(inputs(shadow_reports=[])))["ai_gate_v2"]["status"] == gp.PENDING_ACTIONS


# ── the LAB: frozen facts, with their protocol ──────────────────────────────────────────────────────────────────


def test_the_frozen_lab_verdicts_carry_their_registered_protocol() -> None:
    for key, record in gp.LAB.items():
        assert record.registered, key
        assert record.fingerprint == protocol.stamp(key)["fingerprint"] and record.version == protocol.require(key).version
        assert record.verdict == gp.REJECTS
    stale = gp.LabRecord(**{**{f: getattr(gp.LAB_A02, f) for f in gp.LabRecord.__dataclass_fields__}, "fingerprint": "0" * 64})
    assert not stale.registered
    assert "la huella guardada no es la del protocolo" in gp.lab_entry(gp.SPEC["g_e4"], stale)["why"][-1]


def test_a02_and_a09_are_their_result_files_figure_by_figure() -> None:
    a02 = json.loads((DOCS / "lab" / "IA_036" / "resultado.json").read_text(encoding="utf-8"))
    assert a02["stamp"]["fingerprint"] == gp.LAB_A02.fingerprint and a02["run_at"] in gp.LAB_A02.evaluated
    for r in gp.LAB_A02.rows:
        res, paired = a02["results"][r.segment], a02["results"][r.segment]["paired"]["coherent-rescaled"]
        assert (r.n, r.blocks, r.estimate, r.ci95, r.mde) == (res["n"], res["days"], paired["mean_of_days"], tuple(paired["ci95"]), paired["mde"])
        assert (r.verdict, list(r.why)) == (a02["verdict"][r.segment]["verdict"], a02["verdict"][r.segment]["why"])
        assert f"suma 1 en {res['sums']['coherent_within']} de {res['sums']['n']}" in r.facts
    e4 = json.loads((DOCS / "lab" / "IA_039" / "resultado_e4.json").read_text(encoding="utf-8"))
    assert e4["sello"]["fingerprint"] == gp.LAB_A09.fingerprint and e4["veredicto"]["global"] == gp.LAB_A09.verdict
    assert e4["auditoria_fugas"]["limpia"] is True and set(e4["celdas"]) == {r.segment for r in gp.LAB_A09.rows}
    for r in gp.LAB_A09.rows:
        cell = e4["celdas"][r.segment]
        d, w = cell["dif_retador_menos_actual"], cell["peso_retador_vs_mercado"]
        assert (r.n, r.blocks, r.estimate, r.ci95, r.mde) == (cell["n"], cell["dias"], d["media"], tuple(d["ic95"]), d["dmd_alcanzada"])
        assert r.weight == (w["w"], tuple(w["ic95"])) and (r.verdict, list(r.why)) == (cell["veredicto"], cell["motivos"])


def _es(x: float) -> str:
    return f"{x:.3f}".replace(".", ",").replace("-", chr(0x2212))


def test_b09_is_the_table_of_its_report() -> None:
    doc = (DOCS / "IA_045_ESTUDIO_EVENTOS.md").read_text(encoding="utf-8")
    assert gp.LAB_B09.fingerprint in doc and "**rechazo**" in doc
    for r in gp.LAB_B09.rows:
        assert f"{_es(r.estimate)} [{_es(r.ci95[0])}; {_es(r.ci95[1])}]" in doc, r.segment
        assert f"| {r.n:,}".replace(",", ".") + f" | {r.blocks} |" in doc, r.segment


def test_the_lab_gates_are_their_experiments_and_g_coh_only_carries_a02() -> None:
    e = by_id(gp.panel(inputs()))
    assert e["g_eventos"]["status"] == e["g_e4"]["status"] == gp.REJECTS
    assert e["g_eventos"]["lab"]["key"] == "INT-B09" and e["g_e4"]["lab"]["key"] == "INT-A09"
    assert [f["verdict"] for f in e["g_e4"]["figures"]] == [gp.PENDING_SAMPLE, gp.PENDING_SAMPLE, gp.REJECTS, gp.REJECTS]
    assert e["g_coh"]["status"] == gp.PENDING_DEPENDENCIES and e["g_coh"]["lab"]["key"] == "INT-A02"
    assert "queda la reescalada como cifra coherente" in e["g_coh"]["why"][1]


# ── the gates whose pieces do not exist, and P1 ─────────────────────────────────────────────────────────────────


def test_a_gate_without_its_pieces_is_pending_by_dependencies_and_says_what_it_waits_for() -> None:
    e = by_id(gp.panel(inputs()))
    for gate in ("g_coh", "g_precio", "g_fuentes_1", "g_fuentes_2", "g_fuentes_3", "g_e6", "g_delib", "g_cron", "f_player"):
        assert e[gate]["status"] == gp.PENDING_DEPENDENCIES and e[gate]["depends_on"] and e[gate]["why"], gate
    from fbi.research import protocol

    if "INT-A08" in protocol.PROTOCOLS:  # registered in its own PR (IA-033): pending all the same until its result is frozen
        assert "proto-int-a08-v1 registrado" in e["g_e6"]["why"][0] and "sin resultado congelado" in e["g_e6"]["why"][0]
    else:
        assert "INT-A08 no tiene protocolo registrado" in e["g_e6"]["why"][0]
    f1 = e["g_fuentes_1"]["figures"]
    assert [(f["counted"], f["cases"], f["value"]) for f in f1] == [(3560, 6074, "58.6 %"), (3398, 6074, "55.9 %"), (284, 6074, "4.7 %")]
    assert all(f["threshold"] == "≤ 20.0 %" and f["verdict"] is None and "NO es el veredicto" in f["note"] for f in f1)


def test_g_fuentes_1_carries_the_measure_of_ia_040_as_its_document_gives_it() -> None:
    """The panel reads nothing of ``ai.evidence``: G-FUENTES 1 carries IA-040's table 2, which must be the document's."""
    doc = (BACKEND / "docs" / "owner" / "IA_040_REGISTRO_FUENTES.md").read_text(encoding="utf-8")

    def count(n: int) -> str:
        return f"{n:,}".replace(",", ".")

    assert f"**2. Ítems sin nivel y reparto por nivel A{chr(0x2013)}D (n = {count(gp.FUENTES_1_ITEMS)}).**" in doc
    assert "6.074 ítems de 1.047 hosts (5.175 de v1 y 899 de Research v2" in doc
    for f in by_id(gp.panel(inputs()))["g_fuentes_1"]["figures"]:
        assert f"| {count(f['counted'])} | {f['value'].removesuffix(' %').replace('.', ',')} |" in doc, f["label"]
    assert not any("ai.evidence" in s for s in readers.STATEMENTS)


def test_g_e6_reads_the_registry_of_protocols(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = protocol.Protocol(**{**{f: getattr(protocol.A09, f) for f in protocol.Protocol.__dataclass_fields__}, "key": "INT-A08",
                                "version": "proto-int-a08-v1"})
    monkeypatch.setitem(protocol.PROTOCOLS, "INT-A08", fake)
    e = gp.e6_entry()
    assert e["status"] == gp.PENDING_DEPENDENCIES and "proto-int-a08-v1 registrado" in e["why"][0]


@pytest.mark.parametrize(("anchor", "reviewed", "want"), [
    (date(2032, 9, 20), 40, gp.PENDING_TIME),
    (date(2032, 8, 1), 40, gp.PENDING_TIME),
    (date(2032, 9, 20), 400, gp.PENDING_TIME),
    (date(2032, 8, 1), 400, gp.PENDING_ACTIONS),
])
def test_p1_counts_against_its_threshold_and_is_never_a_pass(anchor: date, reviewed: int, want: str) -> None:
    p = gp.P1Counts(anchor, "x", TODAY, (("ma-v1", "1X2", reviewed, 10), ("ma-v1", "OU", 5, 1), ("ma-v1", "CORNERS_OU_HOME", 7, 0),
                                         ("ma-v1-h", "HALF_TIME", 3, 0)))
    assert p.days == (TODAY - anchor).days
    assert p.families()["ma-v1"] == {"1X2": {"reviewed": reviewed, "finished": 10}, "OU": {"reviewed": 5, "finished": 1},
                                     "CORNERS": {"reviewed": 7, "finished": 0}}
    assert p.families()["ma-v1-h"] == {"otras": {"reviewed": 3, "finished": 0}}
    e = gp.p1_entry(p)
    assert e["status"] == want and e["evaluable_on"] == (anchor + timedelta(days=30)).isoformat()
    assert gp.p1_entry(None)["status"] == gp.PENDING_TIME and gp.p1_entry(p, error="boom")["status"] == gp.PENDING_ACTIONS


# ── the value per dollar ────────────────────────────────────────────────────────────────────────────────────────


def test_the_components_add_up_to_the_cost_report_and_cover_every_part_once() -> None:
    cost = cost_report()
    v = gp.value_section(cost, [], cost_days=14.0)
    covered = [(c.path, p) for c in gp.COMPONENTS for p in (c.parts or cp.PARTS[c.path])]
    assert sorted(covered) == sorted((p, q) for p in cp.PATHS for q in cp.PARTS[p]), "every part of the cost by path, once"
    total = sum(Decimal(c["cost"]["usd_exact"]) for c in v["components"])
    assert total == Decimal(cost["total"]["usd_exact"]) and v["cost_window"]["reconciles"] is True
    comp = {c["id"]: c for c in v["components"]}
    assert comp["review-v2"]["cost"]["usd_per_candidate"] == cost["paths"]["production"]["parts"]["review"]["usd_per_candidate"]
    assert comp["chronicles"]["cost"]["own_ledger"] == {"ledger": gp.OWN_LEDGER, "calls": 3, "usd": "0.01"}
    assert comp["review-v2"]["cost"]["pace_30_days_usd"] == str((Decimal("0.084") / 14 * 30).quantize(Decimal("0.01")))


def test_a_value_per_dollar_only_where_the_benefit_is_demonstrated() -> None:
    cost = cost_report()
    v = gp.value_section(cost, [shadow("llm", "fail"), shadow("ma-v1", "insufficient", selections=273, rejected=28)], cost_days=14.0)
    comp = {c["id"]: c for c in v["components"]}
    assert comp["review-v2"]["benefit"]["status"] == "no demostrado"
    assert comp["review-v2"]["benefit"]["engines"][0]["value_per_usd"]["value"] is None
    assert "NO PASA" in comp["review-v2"]["benefit"]["engines"][0]["value_per_usd"]["why"]
    assert comp["deliberation"]["benefit"]["status"] == "pendiente por muestra"
    assert {e["engine"]: e["status"] for e in comp["deliberation"]["benefit"]["engines"]} == {"ma-v1": gp.PENDING_TIME, "ma-v1-h": "sin medir",
                                                                                            "cs-v1": "sin medir"}
    assert comp["research-search"]["benefit"]["status"] == "no demostrado"
    assert [s["segment"] for s in comp["research-search"]["benefit"]["segments"]] == list(gp.LAB_WEB_SEGMENTS)
    for c in ("brief-v8", "chronicles", "learning", "postmortem", "lab", "other"):
        assert comp[c]["benefit"]["status"] == "sin medir" and comp[c]["benefit"]["value_per_usd"]["value"] is None, c
    passed = gp.value_section(cost, [shadow("llm", "pass", selections=1000, rejected=400, diff="0.0500", se="0.0200", z=2.5)], cost_days=14.0)
    got = next(c for c in passed["components"] if c["id"] == "review-v2")
    assert got["benefit"]["status"] == "demostrado"
    vp = got["benefit"]["engines"][0]["value_per_usd"]
    per = Decimal(cost["paths"]["production"]["parts"]["review"]["usd_per_candidate"])
    q = Decimal("0.0001")
    assert vp["value"] == str((Decimal("0.6") * Decimal("0.4") * Decimal("0.05") / per).quantize(q))
    z = Decimal(str(Z95))
    assert vp["ci95"] == [str((Decimal("0.24") * (Decimal("0.05") - z * Decimal("0.02")) / per).quantize(q)),
                          str((Decimal("0.24") * (Decimal("0.05") + z * Decimal("0.02")) / per).quantize(q))]


# ── the shape the admin view reads ──────────────────────────────────────────────────────────────────────────────

ENTRY_KEYS = {"id", "name", "piece", "code", "kind", "status", "approved", "why", "threshold", "rejects_if", "evaluable_on", "evaluated_on", "when",
              "figures", "checks", "failing_now", "evaluator", "recorded", "lab", "depends_on", "note", "sources"}
FIGURE_KEYS = {"label", "value", "cases", "counted", "ci95", "ci_method", "threshold", "interval_vs_threshold", "verdict", "source", "note"}


def test_every_entry_and_every_figure_has_the_same_keys_and_a_source() -> None:
    doc = gp.panel(inputs(rows={"gate_a": row("gate_a", True), "battery": row("battery", False), "switches": row("switches", True)},
                          gate_b=b_report(date(2032, 9, 20), b_checks(battery_passed=False)), research=r_report()))
    assert set(doc) == {"version", "decides", "at", "day", "rule", "summary", "gates", "evidence_rows", "value", "violations", "rule_holds"}
    assert doc["decides"] is False and doc["value"]["decides"] is False and doc["version"] == gp.VERSION
    assert [e["id"] for e in doc["gates"]] == [s.id for s in gp.SPECS]
    assert sum(doc["summary"].values()) == len(doc["gates"])
    for e in doc["gates"]:
        assert set(e) == ENTRY_KEYS, e["id"]
        assert e["threshold"] and e["sources"] and all(s["where"] for s in e["sources"]), e["id"]
        for f in [*e["figures"], *(f for c in e["checks"] for f in c["figures"])]:
            assert set(f) == FIGURE_KEYS and f["source"], (e["id"], f["label"])
    json.dumps(doc, default=str)
    assert by_id(doc)["gate_b"]["failing_now"] == ["battery"]
    rows = {r["gate"]: r for r in doc["evidence_rows"]}
    assert set(rows) == set(gates.GATES) and rows["switches"]["is_gate"] is False and rows["battery"]["reads_as"] == gp.FAIL
    assert rows["gate_b"]["reads_as"].startswith("sin fila")


def test_the_lines_name_every_gate_with_its_status() -> None:
    doc = gp.panel(inputs(gate_b=b_case("incomplete"), research=r_case("incomplete")))
    text = "\n".join(gp.lines(doc))
    assert "ningún gate pendiente aparece como aprobado — se cumple" in text
    for e in doc["gates"]:
        assert f"[{e['status']}] {e['name']}" in text, e["id"]
    assert "Valor por dólar" in text and "review-v2" in text
    assert "Valor por dólar · el coste no se leyó" in "\n".join(gp.lines(gp.panel(inputs(cost=None))))


# ── it reads and decides nothing ────────────────────────────────────────────────────────────────────────────────


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}


def test_the_panel_and_its_readers_never_write() -> None:
    for sql in readers.STATEMENTS:
        assert sql.lstrip().upper().startswith("SELECT"), sql[:40]
        assert not any(w in sql.upper() for w in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "ALTER ", "CREATE "))
    src = BACKEND / "src" / "fbi" / "ai"
    for path in (src / "gates_panel.py", src / "gates_panel_readers.py", BACKEND / "scripts" / "ia_gates_panel.py"):
        called = _calls(path)
        assert not called & {"record", "record_gate", "record_switches", "record_lab_plan", "commit"}, path.name
    script = (BACKEND / "scripts" / "ia_gates_panel.py").read_text(encoding="utf-8")
    assert "default_transaction_read_only=on" in script and "statement_timeout=95000" in script and "conn.read_only = True" in script
    assert "REPEATABLE_READ" in script


def test_a_failing_evaluator_rolls_back_to_its_savepoint_and_is_reported() -> None:
    import psycopg

    class Conn:
        def __init__(self) -> None:
            self.opened = 0

        def transaction(self) -> Any:
            import contextlib

            self.opened += 1
            return contextlib.nullcontext()

    conn = Conn()
    got, error = readers.guarded(conn, lambda: (_ for _ in ()).throw(psycopg.errors.QueryCanceled("canceling statement due to statement timeout")))  # type: ignore[arg-type]
    assert got is None and error == "QueryCanceled: canceling statement due to statement timeout" and conn.opened == 1
    assert readers.guarded(conn, lambda: 7) == (7, None)  # type: ignore[arg-type]
    assert readers.shadow_report_of({"selections": "273", "days": "7", "rejected": None, "engine": "ma-v1"}) == {
        "selections": 273, "days": 7, "rejected": None, "engine": "ma-v1"}
    p1 = readers.p1_counts(conn, None, at=NOW)  # type: ignore[arg-type]
    assert p1.anchor is None and p1.today == TODAY


def test_the_script_refuses_a_window_it_cannot_measure_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import ia_gates_panel as script

    now = datetime(2026, 11, 11, 13, 30, tzinfo=UTC)
    assert script.cost_window(14, None, None, now=now) == (datetime(2026, 10, 28, tzinfo=UTC), datetime(2026, 11, 11, tzinfo=UTC))
    assert script.cost_window(14, date(2026, 11, 1), date(2026, 11, 8), now=now) == (datetime(2026, 11, 1, tzinfo=UTC),
                                                                                    datetime(2026, 11, 8, tzinfo=UTC))
    for days, since, until in ((0, None, None), (14, date(2026, 11, 9), date(2026, 11, 9)), (14, None, date(2026, 11, 12))):
        with pytest.raises(ValueError):
            script.cost_window(days, since, until, now=now)

    def no_connection(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("it must not connect")

    monkeypatch.setattr("psycopg.connect", no_connection)
    assert script.main(["show", "--cost-days", "0"]) == script.CANNOT
    assert script.exit_code({"rule_holds": True, "violations": []}) == script.OK
    assert script.exit_code({"rule_holds": False, "violations": ["x"]}) == script.BROKEN
